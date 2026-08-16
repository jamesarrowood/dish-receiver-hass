"""Remote key vocabulary — pure logic, runs without Home Assistant."""

import pytest

from conftest import load_module

keys = load_module("keys.py")
RemoteKey = keys.RemoteKey
channel_to_keys = keys.channel_to_keys
parse_key = keys.parse_key


def test_channel_to_keys_simple():
    result = channel_to_keys("140")
    assert result == [
        RemoteKey.NUM_1,
        RemoteKey.NUM_4,
        RemoteKey.NUM_0,
        RemoteKey.ENTER,
    ]


def test_channel_to_keys_subchannel():
    result = channel_to_keys("140-01")
    assert result == [
        RemoteKey.NUM_1,
        RemoteKey.NUM_4,
        RemoteKey.NUM_0,
        RemoteKey.DASH,
        RemoteKey.NUM_0,
        RemoteKey.NUM_1,
        RemoteKey.ENTER,
    ]


def test_channel_to_keys_rejects_letters():
    with pytest.raises(ValueError):
        channel_to_keys("ES2")


def test_parse_key_by_value_and_name():
    assert parse_key("channel_up") is RemoteKey.CH_UP
    assert parse_key("CH_UP") is RemoteKey.CH_UP
    assert parse_key("  Guide ") is RemoteKey.GUIDE


def test_parse_key_unknown():
    with pytest.raises(ValueError):
        parse_key("teleport")


def test_remotekey_is_str():
    # Enum members must behave as their wire string for logs/payloads.
    assert RemoteKey.GUIDE == "guide"
    assert RemoteKey.GUIDE.value == "guide"
