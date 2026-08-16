"""Test configuration.

Two tiers of tests live here:

* Pure-logic tests (`test_digest.py`, `test_keys.py`) import the modules under
  test directly by file path, so they run anywhere with just pytest — no Home
  Assistant, no custom-component test harness.
* Integration tests (`test_config_flow.py`, `test_entities.py`) need Home
  Assistant and pytest-homeassistant-custom-component; they `pytest.importorskip`
  those, so they skip cleanly where HA isn't installed and run where it is.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "dish_receiver"


def load_module(relative: str):
    """Import a component module in isolation, without the package __init__.

    `relative` is a path under the component dir, e.g. "transport/digest.py".
    Used by pure-logic tests so importing `keys` doesn't drag in Home Assistant
    via the package __init__.
    """
    path = COMPONENT / relative
    name = "dish_" + relative.replace("/", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses can resolve the module namespace.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Load the HA custom-component test plugin only when it's actually installed;
# declaring it unconditionally makes pytest fail collection where HA is absent.
import importlib.util as _il  # noqa: E402

if _il.find_spec("pytest_homeassistant_custom_component") is not None:  # pragma: no cover
    pytest_plugins = ["pytest_homeassistant_custom_component"]
