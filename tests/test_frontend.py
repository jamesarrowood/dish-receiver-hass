"""Frontend resource registration. HA-gated (imports homeassistant.components.frontend)."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.dish_receiver.frontend import (  # noqa: E402
    CARD_URL,
    async_register_frontend,
)


async def test_registers_static_path_and_js_url(hass, monkeypatch):
    registered_paths = []
    js_urls = []

    async def fake_async_register_static_paths(configs):
        registered_paths.extend(configs)

    monkeypatch.setattr(hass.http, "async_register_static_paths", fake_async_register_static_paths, raising=False)
    monkeypatch.setattr(
        "custom_components.dish_receiver.frontend.add_extra_js_url",
        lambda hass, url: js_urls.append(url),
    )

    await async_register_frontend(hass)

    assert js_urls == [CARD_URL]
    assert len(registered_paths) == 1
    assert registered_paths[0].url_path == "/dish_receiver_static"


async def test_idempotent_second_call_is_a_noop(hass, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "custom_components.dish_receiver.frontend.add_extra_js_url",
        lambda hass, url: calls.append(url),
    )

    async def fake_async_register_static_paths(configs):
        pass

    monkeypatch.setattr(hass.http, "async_register_static_paths", fake_async_register_static_paths, raising=False)

    await async_register_frontend(hass)
    await async_register_frontend(hass)

    assert calls == [CARD_URL]  # only the first call actually registered
