"""Cloud transport (DISH Anywhere) — stub pending traffic capture.

The user's chosen fallback if no local API is usable is to drive the receiver
through DISH Anywhere. What that takes — the auth flow, whether control is even
exposed to the app or only cloud-side EPG/streaming — is unknown until the app
traffic is captured (tools/SNIFFING.md). This class exists so the transport
factory, config flow, and tests have a real object to target; its methods raise
a clear TransportError rather than pretending to work.

Fill in `async_connect`/`async_send_key`/`async_tune`/`async_get_state` once the
capture reveals the API. The rest of the integration needs no changes.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import CONF_PASSWORD, CONF_USERNAME, TRANSPORT_CLOUD
from ..keys import RemoteKey
from .base import DishTransport, TransportError

_LOGGER = logging.getLogger(__name__)

_NOT_IMPLEMENTED = (
    "The DISH Anywhere cloud transport is not implemented yet — its API must be "
    "captured first (see tools/SNIFFING.md). Use the local or delegate transport."
)


class CloudTransport(DishTransport):
    """Placeholder for DISH Anywhere control."""

    transport_id = TRANSPORT_CLOUD

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self._hass = hass
        self._username = config.get(CONF_USERNAME)
        self._password = config.get(CONF_PASSWORD)

    async def async_connect(self) -> None:
        raise TransportError(_NOT_IMPLEMENTED)

    async def async_send_key(self, key: RemoteKey) -> None:
        raise TransportError(_NOT_IMPLEMENTED)

    @property
    def supports_state(self) -> bool:
        return False
