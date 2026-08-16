"""Config and options flow for the DISH receiver integration."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.components import ssdp
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_CONTROLLER_MAC,
    CONF_DELEGATE_ENTITY,
    CONF_FAVORITES,
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_TRANSPORT,
    CONF_USERNAME,
    DEFAULT_TRANSPORT,
    DOMAIN,
    TRANSPORT_CLOUD,
    TRANSPORT_DELEGATE,
    TRANSPORT_LOCAL_HTTP,
)
from .discovery import async_discover
from .transport import (
    PairingRequired,
    TransportError,
    build_transport,
)

_LOGGER = logging.getLogger(__name__)

TRANSPORT_LABELS = {
    TRANSPORT_LOCAL_HTTP: "Local (receiver on the network)",
    TRANSPORT_CLOUD: "Cloud (DISH Anywhere account)",
    TRANSPORT_DELEGATE: "Delegate to another remote entity (IR/Harmony)",
}


def _generate_controller_mac() -> str:
    """A stable locally-administered unicast MAC (12 lowercase hex, no colons).

    The receiver pairs against "XT1<mac>", so this identifies Home Assistant as
    a paired device. It only needs to be unique and stable, not a real NIC.
    """
    octets = bytearray(os.urandom(6))
    octets[0] = (octets[0] | 0x02) & 0xFE  # locally administered, unicast
    return octets.hex()


def _favorites_from_text(text: str) -> dict[str, str]:
    """Parse a "Name=Channel" line-per-entry textarea into a map."""
    favorites: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        name, _, channel = line.partition("=")
        name, channel = name.strip(), channel.strip()
        if name and channel:
            favorites[name] = channel
    return favorites


def _favorites_to_text(favorites: dict[str, str]) -> str:
    return "\n".join(f"{name}={channel}" for name, channel in favorites.items())


class DishConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step: pick transport and (for local) host."""
        errors: dict[str, str] = {}

        # Best-effort discovery to pre-fill host, serial, and model.
        suggested_host = ""
        if user_input is None:
            try:
                discovered = await async_discover(timeout=4.0)
            except Exception:  # noqa: BLE001 - discovery must never block setup
                discovered = []
            if discovered:
                first = discovered[0]
                suggested_host = first.host
                self._data[CONF_MODEL] = first.model
                self._data[CONF_MAC] = first.udn or first.host
                if first.serial:
                    self._data[CONF_SERIAL] = first.serial
                if first.friendly_name:
                    self._data.setdefault(CONF_NAME, first.friendly_name)

        if user_input is not None:
            self._data.update(user_input)
            transport_id = user_input[CONF_TRANSPORT]

            if transport_id == TRANSPORT_DELEGATE:
                # No receiver network handshake; go straight to delegate config.
                return await self.async_step_delegate()
            if transport_id == TRANSPORT_CLOUD:
                return await self.async_step_cloud()

            # Local transport: generate a stable controller identity, then pair.
            self._data.setdefault(CONF_CONTROLLER_MAC, _generate_controller_mac())
            return await self.async_step_pair()

        schema = vol.Schema(
            {
                vol.Required(CONF_TRANSPORT, default=DEFAULT_TRANSPORT): vol.In(
                    TRANSPORT_LABELS
                ),
                vol.Optional(CONF_HOST, default=suggested_host): str,
                vol.Optional(CONF_NAME, default="DISH Receiver"): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_ssdp(
        self, discovery_info: ssdp.SsdpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a receiver found by Home Assistant's passive SSDP scanner.

        manifest.json's `ssdp` matcher (deviceType +
        urn:schemas-echostar-com:device:EchoStarDevice:1, confirmed from a real
        Wally's UPnP device.xml) is what routes discovery here — HA watches for
        SSDP announcements network-wide and calls this step on a match, with no
        polling or extra network access needed from us.
        """
        host = urlparse(discovery_info.ssdp_location or "").hostname
        if not host:
            return self.async_abort(reason="cannot_connect")

        upnp = discovery_info.upnp
        serial = upnp.get(ssdp.ATTR_UPNP_SERIAL)
        model = upnp.get(ssdp.ATTR_UPNP_MODEL_NAME) or upnp.get(
            ssdp.ATTR_UPNP_MODEL_DESCRIPTION
        )
        name = upnp.get(ssdp.ATTR_UPNP_FRIENDLY_NAME)
        udn = upnp.get(ssdp.ATTR_UPNP_UDN)

        unique = serial or udn or host
        await self.async_set_unique_id(unique)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._data[CONF_HOST] = host
        self._data[CONF_TRANSPORT] = TRANSPORT_LOCAL_HTTP
        self._data.setdefault(CONF_CONTROLLER_MAC, _generate_controller_mac())
        if serial:
            self._data[CONF_SERIAL] = serial
        if model:
            self._data[CONF_MODEL] = model
        if name:
            self._data[CONF_NAME] = name
        if udn:
            self._data[CONF_MAC] = udn

        self.context["title_placeholders"] = {"name": name or "DISH Receiver"}
        return await self.async_step_ssdp_confirm()

    async def async_step_ssdp_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the discovered receiver; submitting starts pairing."""
        if user_input is not None:
            return await self.async_step_pair()

        return self.async_show_form(
            step_id="ssdp_confirm",
            description_placeholders={
                "name": self._data.get(CONF_NAME) or "DISH Receiver",
                "host": self._data.get(CONF_HOST, ""),
            },
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Local transport, stage 1: connect and trigger the on-TV PIN.

        On first entry we connect (which resolves the serial from the
        receiver's UPnP description) and send device_pairing_start, which makes
        a PIN appear on the TV. Then we hand off to the PIN-entry step.
        """
        errors: dict[str, str] = {}

        if not self._data.get(CONF_HOST):
            errors["base"] = "no_host"
            return self.async_show_form(step_id="user")

        # A serial typed by the user (System Status screen) overrides discovery.
        if user_input is not None and user_input.get(CONF_SERIAL):
            self._data[CONF_SERIAL] = user_input[CONF_SERIAL].strip()

        transport = build_transport(self.hass, TRANSPORT_LOCAL_HTTP, self._data)
        try:
            await transport.async_connect()
            # Capture the resolved serial for the completion step.
            if getattr(transport, "serial", None):
                self._data[CONF_SERIAL] = transport.serial
            await transport.async_pairing_start()
        except TransportError as err:
            _LOGGER.debug("Pairing start failed: %s", err)
            errors["base"] = "cannot_connect"
            # Let the user supply the serial if discovery couldn't.
            return self.async_show_form(
                step_id="pair",
                data_schema=vol.Schema(
                    {vol.Optional(CONF_SERIAL, default=self._data.get(CONF_SERIAL, "")): str}
                ),
                errors=errors,
                description_placeholders={"host": self._data.get(CONF_HOST, "")},
            )
        finally:
            await transport.async_close()

        return await self.async_step_pair_pin()

    async def async_step_pair_pin(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Local transport, stage 2: enter the PIN, capture Digest credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            transport = build_transport(self.hass, TRANSPORT_LOCAL_HTTP, self._data)
            try:
                await transport.async_connect()
                paired = await transport.async_pair(user_input.get("pin", "").strip())
            except PairingRequired as err:
                _LOGGER.debug("Pairing rejected: %s", err)
                errors["base"] = "pairing_failed"
            except TransportError as err:
                _LOGGER.debug("Pairing complete failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if paired:
                    self._data[CONF_USERNAME] = transport.username
                    self._data[CONF_PASSWORD] = transport.password
                    if getattr(transport, "serial", None):
                        self._data[CONF_SERIAL] = transport.serial
                    await transport.async_close()
                    return await self._create_entry()
                errors["base"] = "pairing_failed"
            finally:
                await transport.async_close()

        return self.async_show_form(
            step_id="pair_pin",
            data_schema=vol.Schema({vol.Required("pin"): str}),
            errors=errors,
            description_placeholders={"host": self._data.get(CONF_HOST, "")},
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cloud transport: DISH Anywhere credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            self._data[CONF_TRANSPORT] = TRANSPORT_CLOUD
            transport = build_transport(self.hass, TRANSPORT_CLOUD, self._data)
            try:
                await transport.async_connect()
            except TransportError as err:
                _LOGGER.debug("Cloud connect failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                await transport.async_close()
                return await self._create_entry()
            finally:
                await transport.async_close()

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="cloud", data_schema=schema, errors=errors
        )

    async def async_step_delegate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate transport: choose the remote entity to forward keys to."""
        if user_input is not None:
            self._data.update(user_input)
            self._data[CONF_TRANSPORT] = TRANSPORT_DELEGATE
            return await self._create_entry()

        schema = vol.Schema(
            {
                vol.Required(CONF_DELEGATE_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="remote")
                ),
            }
        )
        return self.async_show_form(step_id="delegate", data_schema=schema)

    async def _create_entry(self) -> ConfigFlowResult:
        """Finalize, keyed on the receiver serial (stable across DHCP changes)."""
        unique = (
            self._data.get(CONF_SERIAL)
            or self._data.get(CONF_MAC)
            or self._data.get(CONF_HOST)
        )
        if unique:
            await self.async_set_unique_id(unique)
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: self._data.get(CONF_HOST)}
            )
        title = self._data.get(CONF_NAME) or "DISH Receiver"
        return self.async_create_entry(title=title, data=self._data)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> "DishOptionsFlow":
        return DishOptionsFlow(entry)


class DishOptionsFlow(OptionsFlow):
    """Favorites, poll interval, delegate override."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            options = dict(user_input)
            options[CONF_FAVORITES] = _favorites_from_text(
                user_input.get("favorites_text", "")
            )
            options.pop("favorites_text", None)
            return self.async_create_entry(title="", data=options)

        current = {**self._entry.data, **self._entry.options}
        favorites_text = _favorites_to_text(current.get(CONF_FAVORITES) or {})

        schema = vol.Schema(
            {
                vol.Optional(
                    "favorites_text", default=favorites_text
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=current.get(CONF_SCAN_INTERVAL, 10),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
                vol.Optional(
                    CONF_DELEGATE_ENTITY,
                    description={
                        "suggested_value": current.get(CONF_DELEGATE_ENTITY)
                    },
                ): EntitySelector(EntitySelectorConfig(domain="remote")),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
