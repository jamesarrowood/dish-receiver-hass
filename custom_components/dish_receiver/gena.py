"""UPnP GENA event subscription for the EchoStar service.

The receiver's EchoStar UPnP service has evented state variables (including
`Standby_Status`). Subscribing to its event URL makes the box POST a NOTIFY to a
callback whenever state changes — so Home Assistant learns of standby/power
changes immediately instead of waiting for the next poll.

This is a small self-contained GENA client:
  * an aiohttp server on the LAN receives NOTIFY callbacks,
  * SUBSCRIBE registers our callback and returns a SID + timeout,
  * the subscription is renewed before it expires,
  * UNSUBSCRIBE + server shutdown on stop.

It is best-effort: any failure logs and leaves the coordinator's polling as the
fallback source of truth.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from typing import Callable, Optional
from urllib.parse import urlparse

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

_RENEW_MARGIN = 30  # renew this many seconds before the subscription expires
_DEFAULT_TIMEOUT = 300


def parse_notify(body: str) -> dict[str, str]:
    """Pull {var: value} pairs out of a GENA NOTIFY property set."""
    out: dict[str, str] = {}
    for key, value in re.findall(r"<(\w+)>([^<]*)</\1>", body):
        if value.strip() and not key.startswith("e:"):
            out[key] = value.strip()
    return out


def _timeout_seconds(header: Optional[str]) -> int:
    if header and header.lower().startswith("second-"):
        try:
            return int(header.split("-", 1)[1])
        except ValueError:
            pass
    return _DEFAULT_TIMEOUT


class GenaSubscription:
    """Manages one GENA subscription and its callback listener."""

    def __init__(
        self,
        hass: HomeAssistant,
        event_url: str,
        on_event: Callable[[dict[str, str]], None],
    ) -> None:
        self._hass = hass
        self._event_url = event_url
        self._on_event = on_event
        self._runner: Optional[web.AppRunner] = None
        self._sid: Optional[str] = None
        self._callback_url: Optional[str] = None
        self._renew_task: Optional[asyncio.Task] = None

    async def async_start(self) -> bool:
        """Start the listener and subscribe. Returns True on success."""
        try:
            local_ip = await self._async_local_ip()
            sock = await self._hass.async_add_executor_job(self._bind_socket, local_ip)
            port = sock.getsockname()[1]

            app = web.Application()
            app.router.add_route("NOTIFY", "/notify", self._handle_notify)
            self._runner = web.AppRunner(app)
            await self._runner.setup()
            await web.SockSite(self._runner, sock).start()

            self._callback_url = f"http://{local_ip}:{port}/notify"
            if not await self._async_subscribe():
                await self.async_stop()
                return False
            return True
        except Exception as err:  # noqa: BLE001 - never break setup over eventing
            _LOGGER.debug("GENA start failed (%s); falling back to polling", err)
            await self.async_stop()
            return False

    async def async_stop(self) -> None:
        if self._renew_task:
            self._renew_task.cancel()
            self._renew_task = None
        if self._sid:
            await self._async_unsubscribe()
            self._sid = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _bind_socket(local_ip: str) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((local_ip, 0))
        sock.listen(16)
        sock.setblocking(False)
        return sock

    async def _async_local_ip(self) -> str:
        host = urlparse(self._event_url).hostname or ""

        def _detect() -> str:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.connect((host, 80))
                return sock.getsockname()[0]
            finally:
                sock.close()

        return await self._hass.async_add_executor_job(_detect)

    async def _handle_notify(self, request: web.Request) -> web.Response:
        try:
            body = await request.text()
            props = parse_notify(body)
            if props:
                self._on_event(props)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Error handling NOTIFY: %s", err)
        return web.Response(status=200)

    async def _async_subscribe(self) -> bool:
        session = async_get_clientsession(self._hass)
        headers = {
            "CALLBACK": f"<{self._callback_url}>",
            "NT": "upnp:event",
            "TIMEOUT": f"Second-{_DEFAULT_TIMEOUT}",
        }
        try:
            async with session.request(
                "SUBSCRIBE", self._event_url, headers=headers, timeout=_client_timeout()
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("SUBSCRIBE returned HTTP %s", resp.status)
                    return False
                self._sid = resp.headers.get("SID")
                secs = _timeout_seconds(resp.headers.get("TIMEOUT"))
        except (asyncio.TimeoutError, OSError) as err:
            _LOGGER.debug("SUBSCRIBE failed: %s", err)
            return False
        self._schedule_renew(secs)
        return True

    async def _async_renew(self) -> None:
        session = async_get_clientsession(self._hass)
        try:
            async with session.request(
                "SUBSCRIBE",
                self._event_url,
                headers={"SID": self._sid, "TIMEOUT": f"Second-{_DEFAULT_TIMEOUT}"},
                timeout=_client_timeout(),
            ) as resp:
                if resp.status == 200:
                    secs = _timeout_seconds(resp.headers.get("TIMEOUT"))
                    self._schedule_renew(secs)
                    return
                _LOGGER.debug("Renew HTTP %s; re-subscribing", resp.status)
        except (asyncio.TimeoutError, OSError) as err:
            _LOGGER.debug("Renew failed (%s); re-subscribing", err)
        # Renewal failed — establish a fresh subscription.
        self._sid = None
        await self._async_subscribe()

    async def _async_unsubscribe(self) -> None:
        session = async_get_clientsession(self._hass)
        try:
            await session.request(
                "UNSUBSCRIBE",
                self._event_url,
                headers={"SID": self._sid},
                timeout=_client_timeout(),
            )
        except (asyncio.TimeoutError, OSError):
            pass

    def _schedule_renew(self, seconds: int) -> None:
        delay = max(30, seconds - _RENEW_MARGIN)

        async def _wait_then_renew() -> None:
            try:
                await asyncio.sleep(delay)
                await self._async_renew()
            except asyncio.CancelledError:
                pass

        if self._renew_task:
            self._renew_task.cancel()
        self._renew_task = self._hass.async_create_task(_wait_then_renew())


def _client_timeout():
    from aiohttp import ClientTimeout

    return ClientTimeout(total=10)
