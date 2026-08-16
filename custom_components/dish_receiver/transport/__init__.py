"""Transport implementations and a small factory.

Adding a new control path means: write a `DishTransport` subclass in this
package and register it in `_BUILDERS`. Nothing above the transport layer needs
to change.
"""

from __future__ import annotations

from typing import Any, Callable

from ..const import (
    TRANSPORT_CLOUD,
    TRANSPORT_DELEGATE,
    TRANSPORT_LOCAL_HTTP,
)
from .base import (
    DishTransport,
    PairingRequired,
    ReceiverState,
    TransportError,
)

__all__ = [
    "DishTransport",
    "ReceiverState",
    "TransportError",
    "PairingRequired",
    "build_transport",
    "available_transports",
]


def _build_local_http(hass: Any, config: dict[str, Any]) -> DishTransport:
    from .local_http import LocalHttpTransport

    return LocalHttpTransport(hass, config)


def _build_cloud(hass: Any, config: dict[str, Any]) -> DishTransport:
    from .cloud import CloudTransport

    return CloudTransport(hass, config)


def _build_delegate(hass: Any, config: dict[str, Any]) -> DishTransport:
    from .delegate import DelegateTransport

    return DelegateTransport(hass, config)


_BUILDERS: dict[str, Callable[[Any, dict[str, Any]], DishTransport]] = {
    TRANSPORT_LOCAL_HTTP: _build_local_http,
    TRANSPORT_CLOUD: _build_cloud,
    TRANSPORT_DELEGATE: _build_delegate,
}


def available_transports() -> list[str]:
    """Transport ids that can be selected in the config flow."""
    return list(_BUILDERS)


def build_transport(hass: Any, transport_id: str, config: dict[str, Any]) -> DishTransport:
    """Instantiate the transport named by `transport_id`."""
    try:
        builder = _BUILDERS[transport_id]
    except KeyError:
        raise TransportError(f"unknown transport {transport_id!r}") from None
    return builder(hass, config)
