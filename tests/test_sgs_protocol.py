"""SGS wire-format tests. HA-gated (local_http imports aiohttp/HA)."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("homeassistant")

from custom_components.dish_receiver.transport.local_http import (  # noqa: E402
    _KEY_WIRE,
    _pairing_body,
    _remote_key_body,
)
from custom_components.dish_receiver.keys import RemoteKey  # noqa: E402


def test_pairing_start_body_shape():
    body = _pairing_body("device_pairing_start", "R0000000000-00", "aabbccddeeff")
    data = json.loads(body)
    assert data["command"] == "device_pairing_start"
    assert data["stb"] == "R0000000000-00"
    assert data["receiver"] == "XT1aabbccddeeff"
    assert data["mac"] == "aabbccddeeff"
    assert data["id"] == "T1"
    assert "pin" not in data  # start carries no PIN


def test_pairing_complete_body_has_pin():
    body = _pairing_body("device_pairing_complete", "R1", "aabbccddeeff", pin="4321")
    data = json.loads(body)
    assert data["command"] == "device_pairing_complete"
    assert data["pin"] == "4321"


def test_remote_key_body_shape():
    body = _remote_key_body("guide", "R0000000000-00", "aabbccddeeff")
    data = json.loads(body)
    assert data == {
        "receiver": "XT1aabbccddeeff",
        "key_name": "guide",
        "tv_id": "0",
        "stb": "R0000000000-00",
        "command": "remote_key",
    }


def test_every_remote_key_has_a_wire_name():
    missing = [k for k in RemoteKey if k not in _KEY_WIRE]
    assert not missing, f"unmapped keys: {missing}"


def test_confirmed_key_names():
    # Tokens verified live on a Wally (CamelCase words, all-caps acronyms).
    assert _KEY_WIRE[RemoteKey.HOME] == "Home"
    assert _KEY_WIRE[RemoteKey.GUIDE] == "Guide"
    assert _KEY_WIRE[RemoteKey.DVR] == "DVR"
    assert _KEY_WIRE[RemoteKey.LIVE_TV] == "TV"
    assert _KEY_WIRE[RemoteKey.SELECT] == "Enter"  # D-pad center is Enter
    assert _KEY_WIRE[RemoteKey.JUMP] == "Jump"
    assert _KEY_WIRE[RemoteKey.NUM_5] == "5"  # bare digit
    assert _KEY_WIRE[RemoteKey.MUTE] == "Mute"  # confirmed live
    assert _KEY_WIRE[RemoteKey.MODE] == "Mode"
