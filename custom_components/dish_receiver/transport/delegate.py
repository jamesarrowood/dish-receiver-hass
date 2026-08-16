"""Delegate transport: forward key presses to another Home Assistant remote.

This is the hardware-agnostic fallback. It never talks to the receiver over IP
at all — instead it calls `remote.send_command` on an entity you already have
working (Global Cache iTach, Broadlink, ESPHome IR, Harmony), passing the DISH
key name as the command string. Whatever that remote's command set is named, you
map our keys to it in that integration; here we just relay.

It is stateless (no feedback), so the media_player runs optimistically.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import CONF_DELEGATE_ENTITY, TRANSPORT_DELEGATE
from ..keys import RemoteKey
from .base import DishTransport, TransportError

_LOGGER = logging.getLogger(__name__)


class DelegateTransport(DishTransport):
    """Relay keys to a user-specified `remote` entity."""

    transport_id = TRANSPORT_DELEGATE

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self._hass = hass
        self._entity_id = config.get(CONF_DELEGATE_ENTITY)

    async def async_connect(self) -> None:
        if not self._entity_id:
            raise TransportError("no delegate remote entity configured")
        if self._hass.states.get(self._entity_id) is None:
            # Not fatal at setup — the entity may load later — but worth noting.
            _LOGGER.warning(
                "Delegate remote %s not found yet; commands will fail until it exists",
                self._entity_id,
            )

    async def async_send_key(self, key: RemoteKey) -> None:
        await self._hass.services.async_call(
            "remote",
            "send_command",
            {"entity_id": self._entity_id, "command": key.value},
            blocking=True,
        )

    @property
    def supports_state(self) -> bool:
        return False
