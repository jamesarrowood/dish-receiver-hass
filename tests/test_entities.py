"""Entity-layer tests against a FakeTransport.

These need Home Assistant + pytest-homeassistant-custom-component. Where those
aren't installed the whole module skips. They prove the entity layer is truly
transport-agnostic: a fake in-memory transport drives the full media_player and
remote surface with no network and no receiver.
"""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.components.media_player import MediaPlayerState  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402

from custom_components.dish_receiver import transport as transport_pkg  # noqa: E402
from custom_components.dish_receiver.const import (  # noqa: E402
    CONF_FAVORITES,
    CONF_HOST,
    CONF_NAME,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_LOCAL_HTTP,
)
from custom_components.dish_receiver.keys import RemoteKey  # noqa: E402
from custom_components.dish_receiver.transport.base import (  # noqa: E402
    DishTransport,
    ReceiverState,
)

from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
)


class FakeTransport(DishTransport):
    """Records what it's told to do; optionally reports state."""

    transport_id = TRANSPORT_LOCAL_HTTP

    def __init__(self, hass, config, *, stateful: bool = False) -> None:
        self.sent: list[RemoteKey] = []
        self.tuned: list[str] = []
        self.launched: list[str] = []
        self._stateful = stateful
        self._state = ReceiverState(power=True, channel_number="140")

    @property
    def app_list(self) -> list[str]:
        return ["Netflix", "YouTube"]

    async def async_launch_app(self, app: str) -> None:
        self.launched.append(app)

    serial = "R0000000000-00"
    username = "hauser"
    password = "hapass"

    async def async_connect(self) -> None:
        return None

    async def async_pairing_start(self) -> None:
        return None

    async def async_pair(self, pin: str) -> bool:
        return True

    async def async_send_key(self, key: RemoteKey) -> None:
        self.sent.append(key)
        if key is RemoteKey.POWER_OFF:
            self._state.power = False
        elif key is RemoteKey.POWER_ON:
            self._state.power = True

    async def async_tune(self, channel: str) -> None:
        self.tuned.append(channel)
        self._state.channel_number = channel

    async def async_get_state(self):
        return self._state if self._stateful else None

    @property
    def supports_state(self) -> bool:
        return self._stateful


@pytest.fixture
def install_fake(monkeypatch):
    """Route build_transport to a FakeTransport we can inspect."""
    created: dict[str, FakeTransport] = {}

    def _factory(stateful: bool):
        def _build(hass, transport_id, config):
            fake = FakeTransport(hass, config, stateful=stateful)
            created["transport"] = fake
            return fake

        return _build

    def _apply(stateful: bool = False):
        monkeypatch.setattr(
            "custom_components.dish_receiver.build_transport", _factory(stateful)
        )
        return created

    return _apply


async def _setup(hass: HomeAssistant, favorites=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "10.0.0.9",
            CONF_NAME: "Living Room DISH",
            CONF_TRANSPORT: TRANSPORT_LOCAL_HTTP,
            CONF_FAVORITES: favorites or {},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_media_player_optimistic_power(hass, install_fake):
    created = install_fake(stateful=False)
    await _setup(hass)
    transport = created["transport"]

    state = hass.states.get("media_player.living_room_dish")
    assert state is not None
    assert state.state == MediaPlayerState.ON  # optimistic default

    await hass.services.async_call(
        "media_player",
        "turn_off",
        {"entity_id": "media_player.living_room_dish"},
        blocking=True,
    )
    assert RemoteKey.POWER_OFF in transport.sent
    assert hass.states.get("media_player.living_room_dish").state == MediaPlayerState.OFF


async def test_next_previous_map_to_channel(hass, install_fake):
    created = install_fake(stateful=False)
    await _setup(hass)
    transport = created["transport"]

    for service, key in (
        ("media_next_track", RemoteKey.CH_UP),
        ("media_previous_track", RemoteKey.CH_DOWN),
    ):
        await hass.services.async_call(
            "media_player",
            service,
            {"entity_id": "media_player.living_room_dish"},
            blocking=True,
        )
    assert transport.sent == [RemoteKey.CH_UP, RemoteKey.CH_DOWN]


async def test_select_source_tunes_favorite(hass, install_fake):
    created = install_fake(stateful=False)
    await _setup(hass, favorites={"ESPN": "140", "TNT": "138"})
    transport = created["transport"]

    state = hass.states.get("media_player.living_room_dish")
    assert set(state.attributes["source_list"]) == {"ESPN", "TNT"}

    await hass.services.async_call(
        "media_player",
        "select_source",
        {"entity_id": "media_player.living_room_dish", "source": "TNT"},
        blocking=True,
    )
    assert transport.tuned == ["138"]


async def test_apps_in_source_list_and_launch(hass, install_fake):
    created = install_fake(stateful=False)
    await _setup(hass, favorites={"ESPN": "140"})
    transport = created["transport"]

    state = hass.states.get("media_player.living_room_dish")
    # Sources are favorites + apps.
    assert "ESPN" in state.attributes["source_list"]
    assert "Netflix" in state.attributes["source_list"]

    await hass.services.async_call(
        "media_player",
        "select_source",
        {"entity_id": "media_player.living_room_dish", "source": "Netflix"},
        blocking=True,
    )
    assert transport.launched == ["Netflix"]
    assert transport.tuned == []  # app launch, not a tune

    await hass.services.async_call(
        DOMAIN,
        "launch_app",
        {"entity_id": "media_player.living_room_dish", "app": "YouTube"},
        blocking=True,
    )
    assert transport.launched == ["Netflix", "YouTube"]


async def test_play_media_channel(hass, install_fake):
    created = install_fake(stateful=False)
    await _setup(hass)
    transport = created["transport"]

    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": "media_player.living_room_dish",
            "media_content_type": "channel",
            "media_content_id": "205",
        },
        blocking=True,
    )
    assert transport.tuned == ["205"]


async def test_tune_channel_service(hass, install_fake):
    created = install_fake(stateful=False)
    await _setup(hass)
    transport = created["transport"]

    await hass.services.async_call(
        DOMAIN,
        "tune_channel",
        {"entity_id": "media_player.living_room_dish", "channel": "140-01"},
        blocking=True,
    )
    assert transport.tuned == ["140-01"]


async def test_remote_send_command_and_send_key(hass, install_fake):
    created = install_fake(stateful=False)
    await _setup(hass)
    transport = created["transport"]

    await hass.services.async_call(
        "remote",
        "send_command",
        {
            "entity_id": "remote.living_room_dish_remote",
            "command": ["guide", "down", "select"],
        },
        blocking=True,
    )
    assert transport.sent == [RemoteKey.GUIDE, RemoteKey.DOWN, RemoteKey.SELECT]

    transport.sent.clear()
    await hass.services.async_call(
        DOMAIN,
        "send_key",
        {"entity_id": "remote.living_room_dish_remote", "key": "info"},
        blocking=True,
    )
    assert transport.sent == [RemoteKey.INFO]


async def test_stateful_transport_reports_real_state(hass, install_fake):
    created = install_fake(stateful=True)
    await _setup(hass)
    transport = created["transport"]

    state = hass.states.get("media_player.living_room_dish")
    assert state.state == MediaPlayerState.ON
    assert state.attributes.get("channel_number") == "140"

    await hass.services.async_call(
        "media_player",
        "turn_off",
        {"entity_id": "media_player.living_room_dish"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert transport._state.power is False
