"""Local SGS control for EchoStar receivers (Wally, Hopper) — confirmed protocol.

Reverse-engineered from the RTI "Dish Network" driver source (HTTPDigest.js,
dish.js) and verified against a live Wally (model XiP813 / 211HEVC). No part of
this is guesswork except the digit key_name, which is flagged below.

Wire summary (port 80):

  Pairing (unauthenticated) — POST /sgs_noauth
    start:    {"command":"device_pairing_start", …}   → PIN shown on TV
    complete: {"command":"device_pairing_complete","pin":"…", …}
              → response JSON carries `name` and `passwd`, which become the
                Digest username/password for all subsequent commands.

  Remote key (Digest MD5, qop=auth) — POST /www/sgs
    {"receiver":"XT1<mac>","key_name":"<KEY>","tv_id":"0",
     "stb":"<serial>","command":"remote_key"}
    The Authorization header carries EchoStar's non-standard `message-digest`
    body-integrity field (see transport/digest.py).

Identity fields in every body:
  stb      = receiver serial (device.xml <serialNumber>, e.g. R0000000000-00)
  receiver = "XT1" + controller MAC (lowercase, no separators)
  mac      = controller MAC
  tv_id    = "0"
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import (
    APP_ID,
    APP_LABEL,
    APP_NAME,
    APP_TYPE,
    CONF_CONTROL_HOST,
    CONF_CONTROLLER_MAC,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SERIAL,
    CONF_USERNAME,
    DIGEST_REALM,
    LOCAL_HTTP_PORT,
    SGS_KEY_PATH,
    SGS_PAIR_PATH,
    TRANSPORT_LOCAL_HTTP,
)
from ..keys import RemoteKey
from .base import (
    DishTransport,
    PairingRequired,
    ReceiverState,
    TransportError,
)
from .digest import echostar_authorization, parse_challenge

_LOGGER = logging.getLogger(__name__)


# key_name tokens as sent to the receiver. CONFIRMED by live hardware testing on
# a Wally (HEVC211/XiP813) — see tools/protocol-findings/WALLY_KEYS.md. The Wally
# uses CamelCase words and all-caps acronyms; the RTI Hopper driver's lowercase
# tokens are rejected. Keys the Wally does not expose over IP (Power, ChannelUp/
# Down, PageUp/Down, FastForward) are mapped to their best-known token for
# forward-compatibility with the Hopper, but return "unsupported" on a Wally.
_KEY_WIRE: dict[RemoteKey, str] = {
    # Power — NOT exposed over IP on the Wally (IR-only); best-effort token.
    RemoteKey.POWER_ON: "Power",
    RemoteKey.POWER_OFF: "Power",
    RemoteKey.POWER_TOGGLE: "Power",
    # Digits — CONFIRMED: the bare digit character.
    RemoteKey.NUM_0: "0",
    RemoteKey.NUM_1: "1",
    RemoteKey.NUM_2: "2",
    RemoteKey.NUM_3: "3",
    RemoteKey.NUM_4: "4",
    RemoteKey.NUM_5: "5",
    RemoteKey.NUM_6: "6",
    RemoteKey.NUM_7: "7",
    RemoteKey.NUM_8: "8",
    RemoteKey.NUM_9: "9",
    RemoteKey.DASH: "Dash",  # not exposed on Wally; best-effort
    RemoteKey.ENTER: "Enter",
    RemoteKey.UP: "Up",
    RemoteKey.DOWN: "Down",
    RemoteKey.LEFT: "Left",
    RemoteKey.RIGHT: "Right",
    RemoteKey.SELECT: "Enter",  # D-pad center is Enter (no separate Select)
    RemoteKey.GUIDE: "Guide",
    RemoteKey.MENU: "Menu",
    RemoteKey.INFO: "Info",
    RemoteKey.DVR: "DVR",
    RemoteKey.BACK: "Back",
    RemoteKey.EXIT: "Cancel",
    RemoteKey.OPTIONS: "Options",
    RemoteKey.LIVE_TV: "TV",
    RemoteKey.HOME: "Home",
    RemoteKey.SEARCH: "Search",
    RemoteKey.INPUT: "Input",
    RemoteKey.APPLICATIONS: "Applications",
    RemoteKey.HELP: "Help",
    RemoteKey.MICROPHONE: "Microphone",
    RemoteKey.KEYPAD: "Keypad",
    RemoteKey.BACKSPACE: "Backspace",
    RemoteKey.DELETE: "Delete",
    RemoteKey.FORMAT: "Format",
    # Channel step / paging — NOT exposed over IP on the Wally; tune by digits.
    RemoteKey.CH_UP: "ChannelUp",
    RemoteKey.CH_DOWN: "ChannelDown",
    RemoteKey.PAGE_UP: "PageUp",
    RemoteKey.PAGE_DOWN: "PageDown",
    RemoteKey.RECALL: "Recall",
    RemoteKey.PLAY: "Play",
    RemoteKey.PAUSE: "Pause",
    RemoteKey.STOP: "Stop",
    RemoteKey.REWIND: "Rewind",
    RemoteKey.JUMP: "Jump",  # CONFIRMED: skip-forward
    RemoteKey.RECORD: "Record",
    RemoteKey.RED: "Red",
    RemoteKey.GREEN: "Green",
    RemoteKey.YELLOW: "Yellow",
    RemoteKey.BLUE: "Blue",
    RemoteKey.MUTE: "Mute",  # receiver-side mute (confirmed; volume steps are IR)
    RemoteKey.MODE: "Mode",
    RemoteKey.SPACE: "Space",  # on-screen keyboard
}


def _pairing_body(command: str, serial: str, mac: str, pin: str | None = None) -> str:
    """Build a /sgs_noauth body, byte-compatible with the RTI driver."""
    pin_field = f'"pin": "{pin}",' if pin is not None else ""
    return (
        f'{{"command": "{command}",{pin_field}'
        f'"stb": "{serial}",'
        f'"receiver": "XT1{mac}",'
        f'"app": "{APP_NAME}",'
        f'"name": "{APP_LABEL}",'
        f'"type": "{APP_TYPE}",'
        f'"id": "{APP_ID}",'
        f'"mac": "{mac}"}}'
    )


def _remote_key_body(key_name: str, serial: str, mac: str) -> str:
    """Build a /www/sgs remote_key body, byte-compatible with the RTI driver."""
    return (
        f'{{"receiver": "XT1{mac}",'
        f'"key_name": "{key_name}",'
        f'"tv_id": "0",'
        f'"stb": "{serial}",'
        f'"command": "remote_key"}}'
    )


class LocalHttpTransport(DishTransport):
    """EchoStar SGS control over the LAN."""

    transport_id = TRANSPORT_LOCAL_HTTP

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self._hass = hass
        self._host = config.get(CONF_HOST, "")
        # Commands go to the control host (the Hopper's IP for a Joey); state is
        # read from _host (the device's own IP). They're equal for Wally/Hopper.
        self._control_host = config.get(CONF_CONTROL_HOST) or self._host
        self._port = LOCAL_HTTP_PORT
        self._serial = config.get(CONF_SERIAL) or ""
        self._mac = (config.get(CONF_CONTROLLER_MAC) or "").lower().replace(":", "")
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()
        # UPnP URLs (state read + GENA events) and DIAL base (app launch),
        # resolved at connect.
        self._control_url: Optional[str] = None
        self._event_url: Optional[str] = None
        self._dial_url: Optional[str] = None

        # Digest credentials minted by pairing. Exposed as attributes so the
        # config flow can persist whatever pairing produced.
        self.username = config.get(CONF_USERNAME) or ""
        self.password = config.get(CONF_PASSWORD) or ""
        self.serial = self._serial

    @property
    def _base(self) -> str:
        """Base URL for control commands (pairing + remote_key)."""
        return f"http://{self._control_host}:{self._port}"

    # -- lifecycle ---------------------------------------------------------

    async def async_connect(self) -> None:
        if not self._host:
            raise TransportError("no host configured")
        self._session = async_get_clientsession(self._hass)

        # One UPnP discovery pass resolves the serial (stb), the control URL
        # (state), and the DIAL base (app launch) for our host.
        from ..discovery import async_discover

        for rec in await async_discover(session=self._session):
            if rec.host != self._host:
                continue
            if rec.serial and not self._serial:
                self._serial = rec.serial
                self.serial = rec.serial
            self._control_url = rec.control_url
            self._event_url = rec.event_url
            self._dial_url = rec.dial_url
            break

        if not self._serial:
            raise TransportError(
                "could not determine receiver serial (stb); enter it manually"
            )

    # -- app launch (DIAL) -------------------------------------------------

    @property
    def app_list(self) -> list[str]:
        # DIAL apps confirmed present on the Wally. GET /dial/<name> would
        # verify others, but these two are the common ones.
        return ["Netflix", "YouTube"] if self._dial_url else []

    async def async_launch_app(self, app: str) -> None:
        """Launch a DIAL app (e.g. Netflix, YouTube)."""
        if not self._dial_url or self._session is None:
            raise TransportError("app launch unavailable (no DIAL endpoint)")
        try:
            async with self._session.post(
                f"{self._dial_url}{app}", data=b"", timeout=_timeout()
            ) as resp:
                if resp.status not in (200, 201):
                    raise TransportError(f"launch {app}: HTTP {resp.status}")
        except aiohttp.ClientError as err:
            raise TransportError(f"launch {app}: {err}") from err

    async def async_stop_app(self, app: str) -> None:
        """Stop a running DIAL app."""
        if not self._dial_url or self._session is None:
            raise TransportError("app control unavailable")
        try:
            async with self._session.delete(
                f"{self._dial_url}{app}/run", timeout=_timeout()
            ) as resp:
                if resp.status not in (200, 201, 204):
                    raise TransportError(f"stop {app}: HTTP {resp.status}")
        except aiohttp.ClientError as err:
            raise TransportError(f"stop {app}: {err}") from err

    async def async_close(self) -> None:
        self._session = None  # HA-managed shared session; don't close it.

    # -- pairing -----------------------------------------------------------

    async def async_pairing_start(self) -> None:
        """Ask the receiver to display a pairing PIN on the TV."""
        body = _pairing_body("device_pairing_start", self._serial, self._mac)
        status, text = await self._post_noauth(SGS_PAIR_PATH, body)
        if status >= 400:
            raise TransportError(f"pairing_start failed (HTTP {status})")

    async def async_pair(self, pin: str) -> bool:
        """Complete pairing with the on-TV PIN; capture Digest credentials."""
        if not pin:
            raise PairingRequired("a PIN is required to pair")
        body = _pairing_body("device_pairing_complete", self._serial, self._mac, pin)
        status, text = await self._post_noauth(SGS_PAIR_PATH, body)
        if status >= 400:
            raise TransportError(f"pairing_complete failed (HTTP {status})")

        try:
            data = json.loads(text[text.index("{"):])
        except (ValueError, json.JSONDecodeError) as err:
            raise PairingRequired(f"unexpected pairing response: {err}") from err

        if "passwd" not in data:
            # Wrong or expired PIN — the box replies without credentials.
            raise PairingRequired("receiver did not return credentials (bad PIN?)")

        self.username = data.get("name", "")
        self.password = data["passwd"]
        return True

    # -- commands ----------------------------------------------------------

    async def async_send_key(self, key: RemoteKey) -> None:
        wire = _KEY_WIRE.get(key)
        if wire is None:
            _LOGGER.warning("No key_name mapping for %s", key)
            return
        body = _remote_key_body(wire, self._serial, self._mac)
        await self._post_sgs(body, describe=key.value)

    async def async_tune(self, channel: str) -> None:
        # No direct-tune command exists in the SGS emulation API; replay the
        # digits followed by ENTER, as a person would.
        await super().async_tune(channel)

    # -- state (UPnP GetEchostarDevInfo) -----------------------------------

    async def async_get_state(self) -> Optional[ReceiverState]:
        if not self._control_url or self._session is None:
            return None
        from ..discovery import async_echostar_devinfo

        info = await async_echostar_devinfo(self._session, self._control_url)
        if not info:
            return None
        return state_from_devinfo(info)

    @property
    def event_url(self) -> Optional[str]:
        """GENA event-subscription URL, if discovered (for push updates)."""
        return self._event_url

    @property
    def supports_state(self) -> bool:
        # State (power/standby) is readable via the EchoStar UPnP service when
        # we found its control URL during discovery.
        return self._control_url is not None

    # -- HTTP plumbing -----------------------------------------------------

    async def _post_noauth(self, path: str, body: str) -> tuple[int, str]:
        if self._session is None:
            raise TransportError("not connected")
        try:
            async with self._session.post(
                f"{self._base}{path}",
                data=body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                timeout=_timeout(),
                allow_redirects=False,
            ) as resp:
                # A Joey redirects control to its Hopper over the internal MoCA
                # network (169.254.x.x), which the LAN can't reach — never chase
                # it; surface a clear error instead of a connect timeout.
                if resp.status in (301, 302, 303, 307, 308):
                    raise TransportError(
                        "receiver redirected control to its Hopper — this looks "
                        "like a Joey; add its Hopper first, then the Joey"
                    )
                return resp.status, await resp.text()
        except aiohttp.ClientError as err:
            raise TransportError(f"POST {path} failed: {err}") from err
        except asyncio.TimeoutError as err:
            raise TransportError(f"POST {path} timed out") from err

    async def _post_sgs(self, body: str, *, describe: str) -> None:
        """POST to /www/sgs with the EchoStar Digest handshake (401 → auth)."""
        if self._session is None:
            raise TransportError("not connected")
        if not self.username or not self.password:
            raise PairingRequired("not paired; no Digest credentials")

        url = f"{self._base}{SGS_KEY_PATH}"
        payload = body.encode("utf-8")
        base_headers = {"Content-Type": "application/json"}

        async with self._lock:
            # 1) Unauthenticated POST to obtain the per-request nonce.
            try:
                async with self._session.post(
                    url, data=payload, headers=base_headers, timeout=_timeout(),
                    allow_redirects=False,
                ) as first:
                    if first.status in (301, 302, 303, 307, 308):
                        raise TransportError(
                            f"{describe}: receiver redirected control to its "
                            "Hopper (Joey must be controlled via its Hopper)"
                        )
                    if first.status not in (401, 200):
                        raise TransportError(
                            f"{describe}: unexpected HTTP {first.status}"
                        )
                    if first.status == 200:
                        return  # already authorized (unlikely, but fine)
                    challenge = parse_challenge(
                        first.headers.get("WWW-Authenticate", "")
                    )
            except aiohttp.ClientError as err:
                raise TransportError(f"{describe}: {err}") from err
            except asyncio.TimeoutError as err:
                raise TransportError(f"{describe}: timed out") from err

            nonce = challenge.get("nonce")
            if not nonce:
                raise TransportError(f"{describe}: no nonce in challenge")

            # 2) Authorized POST with the exact EchoStar Digest header.
            auth = echostar_authorization(
                self.username,
                self.password,
                nonce,
                body,
                uri=SGS_KEY_PATH,
                realm=challenge.get("realm", DIGEST_REALM),
            )
            headers = {**base_headers, "Authorization": auth}
            try:
                async with self._session.post(
                    url, data=payload, headers=headers, timeout=_timeout(),
                    allow_redirects=False,
                ) as second:
                    if second.status == 401:
                        raise PairingRequired(
                            f"{describe}: credentials rejected — re-pair"
                        )
                    if second.status >= 400:
                        raise TransportError(f"{describe}: HTTP {second.status}")
                    text = await second.text()
            except aiohttp.ClientError as err:
                raise TransportError(f"{describe}: {err}") from err
            except asyncio.TimeoutError as err:
                raise TransportError(f"{describe}: timed out") from err

        # The receiver reports success/failure in the JSON body, not the HTTP
        # status: {"result":1} = accepted, {"result":20,"reason":…} = the key
        # is not supported over IP on this model.
        try:
            result = json.loads(text.strip())
        except (ValueError, json.JSONDecodeError):
            return  # no/blank body — treat HTTP 200 as success
        if isinstance(result, dict) and result.get("result") not in (None, 1):
            reason = result.get("reason") or f"result {result.get('result')}"
            raise TransportError(f"{describe}: receiver rejected ({reason})")


def _timeout() -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(total=10, connect=5)


def state_from_devinfo(info: dict) -> ReceiverState:
    """Map EchoStar device-info fields (polled or GENA-pushed) to ReceiverState."""
    standby = info.get("Standby_Status") or info.get("Status")
    power: Optional[bool] = None
    if standby:
        # "LIVE"/"ON"/"ACTIVE" = on; anything else (e.g. "STANDBY") = off.
        power = standby.upper() in ("LIVE", "ON", "ACTIVE")
    return ReceiverState(power=power)
