"""State coordinator for a DISH receiver.

Only meaningful when the active transport can read state. For fire-and-forget
transports (`supports_state == False`) the coordinator still exists but never
polls — the entities run optimistically off their own last command.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .transport import DishTransport, ReceiverState, TransportError

_LOGGER = logging.getLogger(__name__)


class DishDataUpdateCoordinator(DataUpdateCoordinator[Optional[ReceiverState]]):
    """Polls the transport for receiver state when it supports it."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        transport: DishTransport,
        scan_interval: timedelta = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self.transport = transport
        self.entry = entry
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.title}",
            # None disables the internal timer entirely for stateless transports.
            update_interval=scan_interval if transport.supports_state else None,
        )

    async def _async_update_data(self) -> Optional[ReceiverState]:
        if not self.transport.supports_state:
            return None
        try:
            return await self.transport.async_get_state()
        except TransportError as err:
            raise UpdateFailed(str(err)) from err

    @callback
    def handle_push(self, props: dict[str, str]) -> None:
        """Apply a GENA-pushed device-info update immediately."""
        from .transport.local_http import state_from_devinfo

        state = state_from_devinfo(props)
        self.async_set_updated_data(state)
