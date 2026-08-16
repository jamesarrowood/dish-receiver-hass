"""Registers the bundled dish-remote-card frontend resource.

The card (and its background image) live in this integration's own `www/`
folder and are served at `/dish_receiver_static/...`, then injected as an
extra Lovelace JS module — so the card is available automatically after
install, with no manual "add resource" step in Settings → Dashboards.

Idempotent: safe to call once per Home Assistant start even with multiple
config entries, guarded by a `hass.data` flag.
"""

from __future__ import annotations

import logging

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STATIC_URL = "/dish_receiver_static"
CARD_URL = f"{STATIC_URL}/dish-remote-card.js"
_REGISTERED_KEY = "frontend_registered"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve custom_components/dish_receiver/www/ and register the card JS."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_REGISTERED_KEY):
        return

    www_path = hass.config.path("custom_components", DOMAIN, "www")

    try:
        # Modern (2023.9+) async static-path API.
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, www_path, cache_headers=False)]
        )
    except ImportError:
        # Older HA cores only have the sync registrar.
        hass.http.register_static_path(STATIC_URL, www_path, cache_headers=False)

    add_extra_js_url(hass, CARD_URL)
    domain_data[_REGISTERED_KEY] = True
    _LOGGER.debug("Registered dish-remote-card frontend resource at %s", CARD_URL)
