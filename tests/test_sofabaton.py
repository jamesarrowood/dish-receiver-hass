"""SofaBaton X2 bridge — pure logic, runs without Home Assistant.

Guards the two things that fail silently in production: an action string the
blueprint can't dispatch, and a blueprint/docs drift where the input names people
are told to fill in no longer exist.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BLUEPRINT = ROOT / "blueprints" / "automation" / "dish_receiver" / "sofabaton_x2.yaml"


def _load_tool():
    path = ROOT / "tools" / "sofabaton_map.py"
    spec = importlib.util.spec_from_file_location("sofabaton_map", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["sofabaton_map"] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _load_blueprint():
    """Parse the blueprint, tolerating Home Assistant's `!input` tag."""
    yaml = pytest.importorskip("yaml")

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor(
        "!input", lambda loader, node: {"__input__": loader.construct_scalar(node)}
    )
    return yaml.load(BLUEPRINT.read_text(), Loader=Loader)


# --- action strings --------------------------------------------------------


@pytest.mark.parametrize(
    "action,expected",
    [
        ("guide", ("key", "guide")),
        ("GUIDE", ("key", "guide")),
        ("live_tv", ("key", "live_tv")),
        ("LIVE_TV", ("key", "live_tv")),
        ("ch_up", ("key", "channel_up")),
        ("5", ("key", "5")),
        ("num_5", ("key", "5")),
        (" select ", ("key", "select")),
        ("tune:140", ("tune", "140")),
        ("tune:140-01", ("tune", "140-01")),
        ("app:Netflix", ("app", "Netflix")),
        ("fav_next", ("fav_next", "")),
        ("fav_prev", ("fav_prev", "")),
        ("wake", ("wake", "")),
    ],
)
def test_parse_action_accepts(action, expected):
    assert tool.parse_action(action) == expected


@pytest.mark.parametrize(
    "action",
    [
        "",
        "   ",
        "Cancel",  # README used to advertise this; parse_key rejects it
        "TV",  # ditto — the canonical name is live_tv
        "chanup",
        "tune:",
        "tune:14O",  # letter O, not zero
        "app:",
        "fav_up",
    ],
)
def test_parse_action_rejects(action):
    with pytest.raises(ValueError):
        tool.parse_action(action)


def test_capture_order_is_all_valid():
    """Every prompt the helper walks must be dispatchable by the blueprint."""
    for action in tool.CAPTURE_ORDER:
        tool.parse_action(action)


def test_capture_order_has_no_duplicates():
    assert len(set(tool.CAPTURE_ORDER)) == len(tool.CAPTURE_ORDER)


def test_capture_order_skips_keys_the_wally_ignores():
    """Power and channel/page step aren't sendable over IP — see README."""
    unusable = {"power_on", "power_off", "power_toggle", "channel_up", "channel_down"}
    assert unusable.isdisjoint(tool.CAPTURE_ORDER)


# --- rendering -------------------------------------------------------------


def test_render_yaml_quotes_keys_and_sorts_numerically():
    out = tool.render({"7:10": "guide", "7:2": "up", "1:1": "wake"})
    assert out.splitlines() == [
        "key_map:",
        '  "1:1": wake',
        '  "7:2": up',
        '  "7:10": guide',
    ]


def test_render_json():
    import json

    assert json.loads(tool.render({"7:1": "guide"}, as_json=True)) == {"7:1": "guide"}


# --- blueprint -------------------------------------------------------------


def test_blueprint_is_an_automation_blueprint():
    data = _load_blueprint()
    assert data["blueprint"]["domain"] == "automation"
    assert data["blueprint"]["source_url"].endswith("sofabaton_x2.yaml")


def test_blueprint_inputs_match_documented_names():
    """The docs and the helper both name these; renaming one breaks setup."""
    inputs = _load_blueprint()["blueprint"]["input"]
    assert set(inputs) == {
        "mqtt_topic",
        "dish_remote",
        "dish_media_player",
        "key_map",
        "app_names",
    }


def test_blueprint_default_key_map_is_dispatchable():
    inputs = _load_blueprint()["blueprint"]["input"]
    for action in inputs["key_map"]["default"].values():
        tool.parse_action(action)


def test_blueprint_triggers_on_the_configured_topic():
    data = _load_blueprint()
    trigger = data["trigger"][0]
    assert trigger["platform"] == "mqtt"
    assert trigger["topic"] == {"__input__": "mqtt_topic"}


# --- blueprint templates ---------------------------------------------------
# The templates carry the only real logic in the blueprint, and a mistake there
# shows up as a button that quietly does nothing. Render them directly.


def _render(source, **context):
    jinja2 = pytest.importorskip("jinja2")
    return jinja2.Environment().from_string(source).render(**context).strip()


def _fav_template():
    for branch in _load_blueprint()["action"][0]["choose"]:
        for step in branch["sequence"]:
            if isinstance(step, dict) and "variables" in step:
                return step["variables"]["target_source"]
    raise AssertionError("favorite-stepping branch not found")


@pytest.mark.parametrize(
    "trigger,expected",
    [
        ({"payload_json": {"device_id": 7, "key_id": 1}}, "7:1"),
        ({"payload_json": {"key_id": 1}}, ":1"),
        ({"payload": "not json"}, ":"),  # payload_json absent entirely
    ],
)
def test_code_template_never_raises(trigger, expected):
    code = _load_blueprint()["variables"]["code"]
    assert _render(code, trigger=trigger) == expected


@pytest.mark.parametrize(
    "key_map,code,expected",
    [
        ({"7:1": "guide"}, "7:1", "guide"),
        ({"7:1": "guide"}, "9:9", ""),  # unmapped press -> condition stops the run
        (None, "7:1", ""),  # empty map input
    ],
)
def test_command_lookup(key_map, code, expected):
    template = _load_blueprint()["variables"]["command"]
    assert _render(template, key_map=key_map, code=code) == expected


@pytest.mark.parametrize(
    "command,current,expected",
    [
        ("fav_next", "ESPN", "HBO"),
        ("fav_next", "TNT", "ESPN"),  # wraps forward past the apps
        ("fav_prev", "ESPN", "TNT"),  # wraps backward
        ("fav_prev", "HBO", "ESPN"),
        ("fav_next", None, "ESPN"),  # not on a favorite: enter at the front
        ("fav_prev", None, "TNT"),  # ...or the back
        ("fav_next", "Netflix", "ESPN"),  # an app is not a favorite
    ],
)
def test_favorite_stepping(command, current, expected):
    sources = ["ESPN", "HBO", "TNT", "Netflix", "YouTube"]

    def state_attr(_entity, attr):
        return sources if attr == "source_list" else current

    assert (
        _render(
            _fav_template(),
            command=command,
            app_names=["Netflix", "YouTube"],
            dish_media_player="media_player.x",
            state_attr=state_attr,
        )
        == expected
    )


@pytest.mark.parametrize("sources", [[], None, ["Netflix", "YouTube"]])
def test_favorite_stepping_without_favorites_is_a_noop(sources):
    """No favorites configured must yield '' so the next condition stops the run."""

    def state_attr(_entity, attr):
        return sources if attr == "source_list" else None

    assert (
        _render(
            _fav_template(),
            command="fav_next",
            app_names=["Netflix", "YouTube"],
            dish_media_player="media_player.x",
            state_attr=state_attr,
        )
        == ""
    )


def test_docs_key_table_is_dispatchable():
    """Every action shown in the docs must survive parse_action."""
    doc = (ROOT / "docs" / "SOFABATON_X2.md").read_text()
    actions = [
        line.split("|")[2].strip().strip("`")
        for line in doc.splitlines()
        if line.startswith("| ") and line.count("|") >= 3
    ]
    checked = 0
    for action in actions:
        if not action or action in {"Action", "---", ":---"} or action.startswith(":-"):
            continue
        tool.parse_action(action)
        checked += 1
    assert checked > 10, "docs table looks empty — did the column order change?"
