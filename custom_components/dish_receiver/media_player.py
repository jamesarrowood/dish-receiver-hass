"""Media player entity presenting the DISH receiver as a controllable device."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback, async_get_current_platform

from .const import CONF_FAVORITES
from .entity import DishReceiverEntity
from .keys import RemoteKey

_LOGGER = logging.getLogger(__name__)

# Feature set confirmed against a Wally over IP. Power and channel up/down are
# intentionally absent: the Wally does not expose them over its SGS API (they are
# IR-only). Channel changes are done by direct tuning (digits + Enter), which is
# what PLAY_MEDIA / SELECT_SOURCE drive. See tools/protocol-findings/WALLY_KEYS.md.
SUPPORT = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.SELECT_SOURCE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the media player from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([DishMediaPlayer(coordinator)])

    platform = async_get_current_platform()
    platform.async_register_entity_service(
        "tune_channel",
        {vol.Required("channel"): cv.string},
        "async_tune_channel",
    )
    platform.async_register_entity_service(
        "launch_app",
        {vol.Required("app"): cv.string},
        "async_launch_app",
    )


class DishMediaPlayer(DishReceiverEntity, MediaPlayerEntity):
    """A DISH receiver as a media_player.

    Volume/mute are deliberately not exposed: DISH's own control API omits them
    (they are a TV-side function). Route volume through your TV/AVR entity.
    """

    _attr_name = None  # use the device name
    _attr_supported_features = SUPPORT
    _attr_device_class = "receiver"
    _attr_media_content_type = MediaType.CHANNEL

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._base_unique_id}_media_player"
        # favorites is a {name: channel} map from the options flow.
        self._favorites: dict[str, str] = dict(self._config.get(CONF_FAVORITES) or {})
        # No power feedback over IP, so the player is optimistic.
        self._attr_assumed_state = not self._transport.supports_state

    # -- source list (favorites) ------------------------------------------

    @property
    def source_list(self) -> list[str] | None:
        # Favorite channels plus any launchable apps (Netflix, YouTube).
        sources = sorted(self._favorites) + list(self._transport.app_list)
        return sources or None

    @property
    def source(self) -> str | None:
        state = self.coordinator.data
        if state is None or state.channel_number is None:
            return None
        # Reverse-map the current channel number to a favorite name if we can.
        for name, channel in self._favorites.items():
            if channel == state.channel_number:
                return name
        return None

    # -- state -------------------------------------------------------------

    @property
    def state(self) -> MediaPlayerState:
        data = self.coordinator.data
        if data is not None and data.power is not None:
            return MediaPlayerState.ON if data.power else MediaPlayerState.OFF
        # The Wally exposes no power control or state over IP, so it is always
        # treated as on (it sleeps on its own; commands wake it).
        return MediaPlayerState.ON

    @property
    def media_channel(self) -> str | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.channel_name or data.channel_number

    @property
    def media_title(self) -> str | None:
        data = self.coordinator.data
        return data.program_title if data else None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        data = self.coordinator.data
        attrs: dict[str, str] = {}
        if data is None:
            return attrs
        if data.channel_number:
            attrs["channel_number"] = data.channel_number
        if data.tuner:
            attrs["tuner"] = data.tuner
        if data.is_recording is not None:
            attrs["recording"] = str(data.is_recording).lower()
        return attrs

    # -- commands ----------------------------------------------------------

    async def _press(self, key: RemoteKey) -> None:
        await self._transport.async_send_key(key)
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        await self._press(RemoteKey.PLAY)

    async def async_media_pause(self) -> None:
        await self._press(RemoteKey.PAUSE)

    async def async_media_stop(self) -> None:
        await self._press(RemoteKey.STOP)

    async def async_select_source(self, source: str) -> None:
        # A source is either a launchable app or a favorite channel.
        if source in self._transport.app_list:
            await self._transport.async_launch_app(source)
            await self.coordinator.async_request_refresh()
            return
        channel = self._favorites.get(source)
        if channel is None:
            _LOGGER.warning("Unknown source %r (not an app or favorite)", source)
            return
        await self._transport.async_tune(channel)
        await self.coordinator.async_request_refresh()

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs
    ) -> None:
        """Tune to a channel.

        Accepts media_type "channel"/"tvchannel", or a favorite name passed as
        media_id when media_type is "channel".
        """
        if media_type not in (MediaType.CHANNEL, "tvchannel", "channel"):
            _LOGGER.warning("Unsupported media_type %r", media_type)
            return
        # Allow a favorite name here too, for convenience from scripts.
        channel = self._favorites.get(media_id, media_id)
        await self._transport.async_tune(channel)
        await self.coordinator.async_request_refresh()

    async def async_tune_channel(self, channel: str) -> None:
        """Entity-service target for dish_receiver.tune_channel."""
        await self._transport.async_tune(channel)
        await self.coordinator.async_request_refresh()

    async def async_launch_app(self, app: str) -> None:
        """Entity-service target for dish_receiver.launch_app."""
        await self._transport.async_launch_app(app)
        await self.coordinator.async_request_refresh()
