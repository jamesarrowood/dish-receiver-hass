"""Remote entity exposing the full DISH key namespace via remote.send_command."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

import voluptuous as vol
from homeassistant.components.remote import RemoteEntity, RemoteEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)

from .entity import DishReceiverEntity
from .keys import RemoteKey, parse_key

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the remote from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([DishRemote(coordinator)])

    platform = async_get_current_platform()
    platform.async_register_entity_service(
        "send_key",
        {vol.Required("key"): cv.string},
        "async_send_single_key",
    )


class DishRemote(DishReceiverEntity, RemoteEntity):
    """Raw key access, for everything the media_player doesn't model.

    Example:
        remote.send_command:
          target: {entity_id: remote.living_room_dish}
          data: {command: [guide, down, down, select], delay_secs: 0.4}
    """

    _attr_name = "Remote"
    _attr_supported_features = RemoteEntityFeature(0)

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._base_unique_id}_remote"
        self._assumed_on = True

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data
        if data is not None and data.power is not None:
            return data.power
        return self._assumed_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        # The Wally does not expose Power over IP (IR-only). Attempt it for
        # forward-compatibility with other models, but don't fail loudly.
        await self._try_power(RemoteKey.POWER_ON, on=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._try_power(RemoteKey.POWER_OFF, on=False)

    async def _try_power(self, key: RemoteKey, *, on: bool) -> None:
        from .transport import TransportError

        try:
            await self._transport.async_send_key(key)
        except TransportError as err:
            _LOGGER.info("Power control not available on this receiver: %s", err)
            return
        self._assumed_on = on
        self.async_write_ha_state()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send one or more keys, honoring num_repeats and delay_secs."""
        num_repeats: int = kwargs.get("num_repeats", 1)
        delay: float = kwargs.get("delay_secs", 0.4)

        keys: list[RemoteKey] = []
        for raw in command:
            try:
                keys.append(parse_key(raw))
            except ValueError as err:
                _LOGGER.error("Ignoring command: %s", err)

        for repeat in range(num_repeats):
            if repeat:
                await asyncio.sleep(delay)
            await self._transport.async_send_keys(keys, delay=delay)

        await self.coordinator.async_request_refresh()

    async def async_send_single_key(self, key: str) -> None:
        """Entity-service target for dish_receiver.send_key."""
        try:
            resolved = parse_key(key)
        except ValueError as err:
            _LOGGER.error("send_key: %s", err)
            return
        await self._transport.async_send_key(resolved)
        await self.coordinator.async_request_refresh()
