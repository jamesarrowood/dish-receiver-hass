#!/usr/bin/env python3
"""Build the SofaBaton X2 → DISH key map by pressing buttons.

The X2's Home Assistant device type publishes `{"device_id":N,"key_id":M}` to a
single MQTT topic on every press. The ids are handed out by the SofaBaton app and
can't be chosen, so the only way to learn which id is which button is to press it
and watch the broker. That's what this does — then it prints a `key_map:` block
ready to paste into the automation built from
`blueprints/automation/dish_receiver/sofabaton_x2.yaml`.

Find your topic (the hub's MAC + `/up`) and confirm the hub is publishing:
    python3 sofabaton_map.py --listen --host 192.168.10.5 --user ha --password s3cret

Capture a full map, one prompt per key:
    python3 sofabaton_map.py --host 192.168.10.5 --user ha --password s3cret \
        --topic aabbccddeeff/up

Actions understood by the blueprint (and validated here before they reach it):
    guide, up, select, live_tv, 5, …   a key name from keys.py
    tune:140 / tune:140-01             direct tune
    app:Netflix                        DIAL app launch
    fav_next / fav_prev                step through favorites
    wake                               nudge out of standby
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import queue
import select
import sys
import time
from pathlib import Path

# --- key vocabulary --------------------------------------------------------
# Load keys.py by path: it is dependency-free, and importing the package would
# drag in Home Assistant.
_KEYS_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "dish_receiver"
    / "keys.py"
)
_spec = importlib.util.spec_from_file_location("dish_keys", _KEYS_PATH)
_keys = importlib.util.module_from_spec(_spec)
sys.modules["dish_keys"] = _keys
_spec.loader.exec_module(_keys)
RemoteKey = _keys.RemoteKey
parse_key = _keys.parse_key

PSEUDO_ACTIONS = ("fav_next", "fav_prev", "wake")

# The order the interactive capture walks. Deliberately starts with the buttons
# you'd miss first, and skips keys the Wally doesn't honour over IP (power,
# channel/page step, which is what fav_next/fav_prev exist for).
CAPTURE_ORDER: tuple[str, ...] = (
    "wake",
    "up",
    "down",
    "left",
    "right",
    "select",
    "back",
    "exit",
    "guide",
    "menu",
    "info",
    "dvr",
    "options",
    "live_tv",
    "home",
    "search",
    "fav_next",
    "fav_prev",
    "recall",
    "play",
    "pause",
    "stop",
    "rewind",
    "jump",
    "record",
    "mute",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "0",
    "dash",
    "enter",
    "red",
    "green",
    "yellow",
    "blue",
    "app:Netflix",
    "app:YouTube",
)


def parse_action(value: str) -> tuple[str, str]:
    """Validate a blueprint action string, returning (kind, argument).

    Kinds: "key", "tune", "app", "fav_next", "fav_prev", "wake". Raises
    ValueError on anything the blueprint would silently drop — the whole point
    of validating here is that every downstream call site logs-and-ignores bad
    input, so a typo would otherwise surface as a dead button.
    """
    action = value.strip()
    if not action:
        raise ValueError("empty action")
    if action in PSEUDO_ACTIONS:
        return action, ""
    if action.startswith("tune:"):
        channel = action.split(":", 1)[1].strip()
        if not channel:
            raise ValueError("tune: needs a channel, e.g. tune:140")
        # Reuse the integration's own channel validation.
        _keys.channel_to_keys(channel)
        return "tune", channel
    if action.startswith("app:"):
        app = action.split(":", 1)[1].strip()
        if not app:
            raise ValueError("app: needs a name, e.g. app:Netflix")
        return "app", app
    # Anything else must be a real key; parse_key raises with the valid list.
    return "key", parse_key(action).value


# --- MQTT ------------------------------------------------------------------


def _connect(args, on_message):
    """Return a connected, subscribed, background-looping paho client."""
    try:
        import paho.mqtt.client as mqtt
    except ImportError:  # pragma: no cover - environment-dependent
        sys.exit("paho-mqtt is required: python3 -m pip install paho-mqtt")

    # paho 2.x requires an explicit callback API version; 1.x has no such arg.
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    except AttributeError:  # pragma: no cover - paho 1.x
        client = mqtt.Client()

    if args.user:
        client.username_pw_set(args.user, args.password)
    client.on_message = on_message
    client.connect(args.host, args.port, keepalive=60)
    client.subscribe(args.topic)
    client.loop_start()
    return client


def _decode(payload: bytes) -> tuple[str | None, str]:
    """Return (code, human) for a raw payload; code is None if unparseable."""
    raw = payload.decode("utf-8", "replace").strip()
    try:
        data = json.loads(raw)
        code = f"{data['device_id']}:{data['key_id']}"
    except (ValueError, KeyError, TypeError):
        return None, raw
    return code, raw


# --- modes -----------------------------------------------------------------


def run_listen(args) -> int:
    """Dump every message, so you can confirm the topic and payload shape."""
    print(f"Listening on {args.topic!r} at {args.host}:{args.port} — ^C to stop.")
    print("Press any button on the X2's Home Assistant device.\n")

    def on_message(_client, _userdata, msg):
        code, raw = _decode(msg.payload)
        label = f"code {code}" if code else "UNPARSED"
        print(f"  {msg.topic:<28} {label:<14} {raw}")

    client = _connect(args, on_message)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
    finally:
        client.loop_stop()
    return 0


def _drain(messages: queue.Queue) -> None:
    """Discard queued repeats so a held button doesn't answer the next prompt."""
    while True:
        try:
            messages.get_nowait()
        except queue.Empty:
            return


def _stdin_line() -> str | None:
    """Non-blocking read of one line of input, if any is waiting.

    Returns None when stdin isn't a terminal — polling a closed/piped stdin
    reports ready forever, which would spin the prompt loop.
    """
    if not sys.stdin.isatty():
        return None
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if not ready:
        return None
    return sys.stdin.readline().strip().lower()


def _capture_one(action: str, messages: queue.Queue, taken: dict[str, str]) -> str | None:
    """Prompt for one action; return its code, or None if skipped.

    Raises KeyboardInterrupt-alike control via the sentinel "" for 'finish'.
    """
    print(f"  press the button for  {action:<14} [s = skip, q = done] ", end="", flush=True)
    while True:
        typed = _stdin_line()
        if typed in ("s", "skip"):
            print("skipped")
            return None
        if typed in ("q", "quit", "done"):
            print("done")
            raise StopIteration
        try:
            _topic, payload = messages.get(timeout=0.2)
        except queue.Empty:
            continue
        code, raw = _decode(payload)
        if code is None:
            print(f"\n    ignoring unparseable payload: {raw}")
            print(f"  press the button for  {action:<14} [s = skip, q = done] ", end="", flush=True)
            continue
        if code in taken:
            print(f"\n    {code} is already mapped to {taken[code]!r} — press a different button")
            print(f"  press the button for  {action:<14} [s = skip, q = done] ", end="", flush=True)
            continue
        print(f"→ {code}")
        _drain(messages)
        return code


def run_capture(args) -> int:
    messages: queue.Queue = queue.Queue()

    def on_message(_client, _userdata, msg):
        messages.put((msg.topic, msg.payload))

    client = _connect(args, on_message)
    mapping: dict[str, str] = {}
    taken: dict[str, str] = {}

    actions = list(CAPTURE_ORDER)
    if args.only:
        actions = args.only
    for action in actions:
        parse_action(action)  # fail fast on a bad --only list

    print(f"Subscribed to {args.topic!r}. Assign each DISH action to a button.\n")
    try:
        for action in actions:
            try:
                code = _capture_one(action, messages, taken)
            except StopIteration:
                break
            if code is not None:
                mapping[code] = action
                taken[code] = action
        # Free-form extras: anything not in the standard walk.
        while True:
            print("\n  extra action (e.g. tune:140, app:Netflix) or blank to finish: ", end="", flush=True)
            extra = sys.stdin.readline().strip()
            if not extra:
                break
            try:
                parse_action(extra)
            except ValueError as err:
                print(f"    {err}")
                continue
            try:
                code = _capture_one(extra, messages, taken)
            except StopIteration:
                break
            if code is not None:
                mapping[code] = extra
                taken[code] = extra
    except KeyboardInterrupt:
        print()
    finally:
        client.loop_stop()

    if not mapping:
        print("\nNothing captured.")
        return 1
    print()
    print(render(mapping, as_json=args.json))
    return 0


def render(mapping: dict[str, str], as_json: bool = False) -> str:
    """Format a captured map for pasting into the blueprint's key_map input."""
    ordered = dict(
        sorted(
            mapping.items(),
            key=lambda item: tuple(int(part) for part in item[0].split(":")),
        )
    )
    if as_json:
        return json.dumps(ordered, indent=2)
    lines = ["key_map:"]
    lines += [f'  "{code}": {action}' for code, action in ordered.items()]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture SofaBaton X2 button ids into a DISH key map.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--host", required=True, help="MQTT broker host (your HA box)")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--user", default=None, help="broker username")
    parser.add_argument("--password", default=None, help="broker password")
    parser.add_argument(
        "--topic",
        default="+/up",
        help="topic to watch; default '+/up' matches any remote's MAC",
    )
    parser.add_argument("--listen", action="store_true", help="just dump messages")
    parser.add_argument("--json", action="store_true", help="emit JSON, not YAML")
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="ACTION",
        help="capture just these actions instead of the full walk",
    )
    args = parser.parse_args(argv)
    return run_listen(args) if args.listen else run_capture(args)


if __name__ == "__main__":
    raise SystemExit(main())
