"""The DISH receiver integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TRANSPORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRANSPORT,
    PLATFORMS,
)
from .coordinator import DishDataUpdateCoordinator
from .frontend import async_register_frontend
from .transport import DishTransport, TransportError, build_transport

_LOGGER = logging.getLogger(__name__)


@dataclass
class DishRuntimeData:
    """Everything an entry's platforms need, stored on the config entry."""

    transport: DishTransport
    coordinator: DishDataUpdateCoordinator
    gena: object | None = None  # GenaSubscription, when event push is active


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a DISH receiver from a config entry."""
    await async_register_frontend(hass)

    config = {**entry.data, **entry.options}
    transport_id = config.get(CONF_TRANSPORT, DEFAULT_TRANSPORT)

    transport = build_transport(hass, transport_id, config)
    try:
        await transport.async_connect()
    except TransportError as err:
        await transport.async_close()
        raise ConfigEntryNotReady(f"cannot reach receiver: {err}") from err

    scan_seconds = config.get(CONF_SCAN_INTERVAL)
    scan_interval = (
        timedelta(seconds=scan_seconds) if scan_seconds else DEFAULT_SCAN_INTERVAL
    )
    coordinator = DishDataUpdateCoordinator(hass, entry, transport, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    # Subscribe to GENA events for instant standby/power push, if available.
    gena = None
    event_url = getattr(transport, "event_url", None)
    if event_url:
        from .gena import GenaSubscription

        gena = GenaSubscription(hass, event_url, coordinator.handle_push)
        if await gena.async_start():
            _LOGGER.debug("GENA event push active for %s", entry.title)
        else:
            gena = None  # fell back to polling

    entry.runtime_data = DishRuntimeData(
        transport=transport, coordinator=coordinator, gena=gena
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and hasattr(entry, "runtime_data"):
        if entry.runtime_data.gena is not None:
            await entry.runtime_data.gena.async_stop()
        await entry.runtime_data.transport.async_close()
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change (favorites, scan interval, delegate)."""
    await hass.config_entries.async_reload(entry.entry_id)
