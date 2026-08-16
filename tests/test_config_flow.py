"""Config-flow tests. Skips where Home Assistant isn't installed."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402

from custom_components.dish_receiver.const import (  # noqa: E402
    CONF_DELEGATE_ENTITY,
    CONF_HOST,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_DELEGATE,
    TRANSPORT_LOCAL_HTTP,
)


@pytest.fixture(autouse=True)
def _no_discovery(monkeypatch):
    async def _empty(timeout=4.0):
        return []

    monkeypatch.setattr(
        "custom_components.dish_receiver.config_flow.async_discover", _empty
    )


from custom_components.dish_receiver.transport.base import PairingRequired  # noqa: E402


class _FakeLocal:
    """Stand-in local transport implementing the SGS pairing surface."""

    serial = "R0000000000-00"

    def __init__(self, good_pin="1234"):
        self.username = ""
        self.password = ""
        self._good = good_pin
        self.started = False

    async def async_connect(self):
        return None

    async def async_pairing_start(self):
        self.started = True

    async def async_pair(self, pin):
        if pin != self._good:
            raise PairingRequired("bad pin")
        self.username = "hauser"
        self.password = "hapass"
        return True

    async def async_close(self):
        return None


async def test_local_flow_pairs_and_creates_entry(hass, monkeypatch):
    """user → pair (PIN triggered) → pair_pin → entry with captured creds."""
    fake = _FakeLocal()
    monkeypatch.setattr(
        "custom_components.dish_receiver.config_flow.build_transport",
        lambda hass, tid, cfg: fake,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TRANSPORT: TRANSPORT_LOCAL_HTTP, CONF_HOST: "192.168.1.50", "name": "Den DISH"},
    )
    # Stage 1 triggered the PIN and advanced to PIN entry.
    assert result["step_id"] == "pair_pin"
    assert fake.started is True

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pin": "1234"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "192.168.1.50"
    assert result["data"]["username"] == "hauser"
    assert result["data"]["password"] == "hapass"
    # unique_id keyed on the receiver serial.
    assert result["result"].unique_id == "R0000000000-00"


async def test_pairing_wrong_pin_shows_error(hass, monkeypatch):
    fake = _FakeLocal(good_pin="1234")
    monkeypatch.setattr(
        "custom_components.dish_receiver.config_flow.build_transport",
        lambda hass, tid, cfg: fake,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TRANSPORT: TRANSPORT_LOCAL_HTTP, CONF_HOST: "192.168.1.50"},
    )
    assert result["step_id"] == "pair_pin"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pin": "0000"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "pairing_failed"


def _ssdp_info(**upnp):
    """Build an SsdpServiceInfo regardless of which HA version we're on."""
    try:
        from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo
    except ImportError:
        from homeassistant.components.ssdp import SsdpServiceInfo
    return SsdpServiceInfo(
        ssdp_usn="uuid:test-udn::urn:schemas-echostar-com:device:EchoStarDevice:1",
        ssdp_st="urn:schemas-echostar-com:device:EchoStarDevice:1",
        ssdp_location=upnp.pop("_location", "http://192.168.1.50:49316/device.xml"),
        upnp=upnp,
    )


async def test_ssdp_discovery_finds_and_pairs(hass, monkeypatch):
    """A real EchoStar SSDP announcement -> confirm card -> pairing flow."""
    fake = _FakeLocal()
    monkeypatch.setattr(
        "custom_components.dish_receiver.config_flow.build_transport",
        lambda hass, tid, cfg: fake,
    )

    # Uses the spec UPnP field names — the same keys the flow reads.
    discovery_info = _ssdp_info(
        serialNumber="R0000000000-00",
        modelName="HEVC Joey",
        friendlyName="Bedroom 1",
        UDN="uuid:test-udn",
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_SSDP}, data=discovery_info
    )
    assert result["step_id"] == "ssdp_confirm"

    # Confirming the discovery card jumps straight into the existing pairing flow.
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pair_pin"
    assert fake.started is True

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pin": "1234"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "192.168.1.50"
    # Name carries the model so multiple Joeys are distinguishable.
    assert result["data"]["name"] == "Bedroom 1 (HEVC Joey)"
    assert result["result"].unique_id == "R0000000000-00"


async def test_ssdp_discovery_dedupes_already_configured(hass, monkeypatch):
    """A second announcement for an already-set-up receiver aborts, not re-pairs."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="R0000000000-00",
        data={CONF_HOST: "192.168.1.50", CONF_TRANSPORT: TRANSPORT_LOCAL_HTTP},
    )
    entry.add_to_hass(hass)

    discovery_info = _ssdp_info(
        serialNumber="R0000000000-00",
        _location="http://192.168.1.51:49316/device.xml",
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_SSDP}, data=discovery_info
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # The host was updated to the newly-announced address.
    assert entry.data[CONF_HOST] == "192.168.1.51"


async def test_delegate_flow_skips_pairing(hass):
    """Delegate transport needs no receiver handshake."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TRANSPORT: TRANSPORT_DELEGATE, CONF_HOST: ""},
    )
    assert result["step_id"] == "delegate"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DELEGATE_ENTITY: "remote.harmony_hub"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TRANSPORT] == TRANSPORT_DELEGATE
    assert result["data"][CONF_DELEGATE_ENTITY] == "remote.harmony_hub"
