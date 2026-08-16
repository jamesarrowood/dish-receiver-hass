"""The transport seam.

Everything the integration knows about *how* to reach a receiver lives behind
this interface. The entity layer (media_player, remote) depends only on
`DishTransport` and `ReceiverState`, never on a concrete transport, so swapping
the local-HTTP path for the cloud path (or a delegate) changes nothing above.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..keys import RemoteKey, channel_to_keys


@dataclass
class ReceiverState:
    """A snapshot of what a receiver is doing, as far as a transport can tell.

    Every field is optional: transports that cannot read a given datum leave it
    as None, and the entity presents what it has. A transport that can read
    nothing at all returns None from `async_get_state` instead of an instance.
    """

    power: Optional[bool] = None
    channel_number: Optional[str] = None
    channel_name: Optional[str] = None
    program_title: Optional[str] = None
    is_recording: Optional[bool] = None
    tuner: Optional[str] = None


class TransportError(Exception):
    """A transport failed to talk to the receiver."""


class PairingRequired(TransportError):
    """The receiver needs to be paired before it will accept commands."""


class DishTransport(ABC):
    """Abstract control channel to a single DISH receiver."""

    #: Human-readable id, matches the CONF_TRANSPORT value.
    transport_id: str = "base"

    @abstractmethod
    async def async_connect(self) -> None:
        """Establish/validate the connection. Raise TransportError on failure."""

    async def async_close(self) -> None:
        """Release any held resources. Safe to call more than once."""

    async def async_pair(self, pin: str) -> bool:
        """Complete pairing with the on-TV PIN.

        Default: transports that need no pairing accept unconditionally, so the
        config-flow pairing step is a no-op for them.
        """
        return True

    @abstractmethod
    async def async_send_key(self, key: RemoteKey) -> None:
        """Send a single remote key press."""

    async def async_send_keys(self, keys: list[RemoteKey], delay: float = 0.3) -> None:
        """Send a sequence of keys. Overridable if a transport batches natively."""
        import asyncio

        for index, key in enumerate(keys):
            if index:
                await asyncio.sleep(delay)
            await self.async_send_key(key)

    async def async_tune(self, channel: str) -> None:
        """Tune directly to a channel.

        Default implementation replays the digits + ENTER via `async_send_keys`,
        which works on any transport. Override when the receiver has a real tune
        command (fewer round-trips, no timing sensitivity).
        """
        await self.async_send_keys(channel_to_keys(channel))

    async def async_get_state(self) -> Optional[ReceiverState]:
        """Return current state, or None if this transport can't read state."""
        return None

    async def async_launch_app(self, app: str) -> None:
        """Launch an app by name. Override where the transport supports it."""
        raise TransportError("app launch not supported by this transport")

    async def async_stop_app(self, app: str) -> None:
        """Stop a running app. Override where supported."""
        raise TransportError("app control not supported by this transport")

    @property
    def app_list(self) -> list[str]:
        """Launchable app names, if any."""
        return []

    @property
    def supports_state(self) -> bool:
        """Whether `async_get_state` can return meaningful data.

        When False, the coordinator is disabled and the entity runs optimistic.
        """
        return False
