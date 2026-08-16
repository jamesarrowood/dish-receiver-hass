"""Shared base for DISH receiver entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MAC, CONF_MODEL, CONF_NAME, DOMAIN, MANUFACTURER
from .coordinator import DishDataUpdateCoordinator


class DishReceiverEntity(CoordinatorEntity[DishDataUpdateCoordinator]):
    """Common device wiring for the receiver's entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DishDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.entry
        config = {**entry.data, **entry.options}
        self._config = config
        self._transport = coordinator.transport

        # MAC is the stable identity (survives DHCP changes); fall back to the
        # entry id if we somehow never learned it.
        mac = config.get(CONF_MAC)
        self._base_unique_id = mac or entry.entry_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._base_unique_id)},
            manufacturer=MANUFACTURER,
            model=config.get(CONF_MODEL) or "DISH receiver",
            name=config.get(CONF_NAME) or entry.title,
        )

    @property
    def available(self) -> bool:
        # Stateless transports never mark themselves unavailable via the
        # coordinator; only gate availability on the coordinator when it polls.
        if not self._transport.supports_state:
            return True
        return super().available
