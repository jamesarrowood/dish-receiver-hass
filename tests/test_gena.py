"""GENA parsing + state mapping. HA-gated (gena imports aiohttp/HA)."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.dish_receiver.gena import (  # noqa: E402
    parse_notify,
    _timeout_seconds,
)
from custom_components.dish_receiver.transport.local_http import (  # noqa: E402
    state_from_devinfo,
)

# A real NOTIFY property set captured from the Wally.
NOTIFY = (
    '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
    "<e:property><Name>Living Room</Name></e:property>"
    "<e:property><Standby_Status>LIVE</Standby_Status></e:property>"
    "<e:property><Version>W5961618NJTD</Version></e:property>"
    "<e:property><MAC>AA:BB:CC:DD:EE:FF</MAC></e:property>"
    "</e:propertyset>"
)


def test_parse_notify_extracts_vars_skips_envelope():
    props = parse_notify(NOTIFY)
    assert props["Standby_Status"] == "LIVE"
    assert props["Name"] == "Living Room"
    assert props["Version"] == "W5961618NJTD"
    # The e:property / e:propertyset envelope tags must not appear.
    assert not any(k.startswith("e:") for k in props)


def test_state_from_pushed_props_power_on():
    state = state_from_devinfo(parse_notify(NOTIFY))
    assert state.power is True


def test_state_from_pushed_props_standby_off():
    body = NOTIFY.replace("LIVE", "STANDBY")
    state = state_from_devinfo(parse_notify(body))
    assert state.power is False


def test_timeout_seconds():
    assert _timeout_seconds("Second-300") == 300
    assert _timeout_seconds("Second-1800") == 1800
    assert _timeout_seconds("infinite") == 300  # default fallback
    assert _timeout_seconds(None) == 300
