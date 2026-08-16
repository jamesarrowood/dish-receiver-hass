"""Canonical remote-key vocabulary for DISH receivers.

Every transport maps *from* this single namespace to whatever wire format it
speaks, so the entity layer only ever deals in these names. The set is modelled
on the DISH 54.0 remote (the Wally's remote) plus the shared DVR transport keys.
"""

from __future__ import annotations

from enum import Enum


class RemoteKey(str, Enum):
    """A key the user can ask a DISH receiver to act on.

    Inherits from str so a `RemoteKey` is directly usable as a dict key, in
    logs, and in service-call payloads without conversion.
    """

    # Power
    POWER_ON = "power_on"
    POWER_OFF = "power_off"
    POWER_TOGGLE = "power_toggle"

    # Digits (direct channel entry)
    NUM_0 = "0"
    NUM_1 = "1"
    NUM_2 = "2"
    NUM_3 = "3"
    NUM_4 = "4"
    NUM_5 = "5"
    NUM_6 = "6"
    NUM_7 = "7"
    NUM_8 = "8"
    NUM_9 = "9"
    DASH = "dash"  # the "-" key, for sub-channels like 140-01
    ENTER = "enter"

    # D-pad
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    SELECT = "select"

    # Navigation
    GUIDE = "guide"
    MENU = "menu"
    INFO = "info"
    DVR = "dvr"
    BACK = "back"
    EXIT = "exit"
    OPTIONS = "options"
    LIVE_TV = "live_tv"
    HOME = "home"
    SEARCH = "search"
    INPUT = "input"
    APPLICATIONS = "applications"
    HELP = "help"
    MICROPHONE = "microphone"
    KEYPAD = "keypad"
    BACKSPACE = "backspace"
    DELETE = "delete"
    FORMAT = "format"

    # Channel
    CH_UP = "channel_up"
    CH_DOWN = "channel_down"
    RECALL = "recall"  # jump to previous channel
    PAGE_UP = "page_up"
    PAGE_DOWN = "page_down"

    # DVR transport
    PLAY = "play"
    PAUSE = "pause"
    STOP = "stop"
    REWIND = "rewind"
    JUMP = "jump"  # skip forward (the Wally's only forward-skip key)
    RECORD = "record"

    # Colored keys (guide/app shortcuts)
    RED = "red"
    GREEN = "green"
    YELLOW = "yellow"
    BLUE = "blue"

    # Misc (confirmed on the Wally by live testing)
    MUTE = "mute"
    MODE = "mode"
    SPACE = "space"


# Digit convenience: map a single character to its RemoteKey.
DIGIT_KEYS: dict[str, RemoteKey] = {
    "0": RemoteKey.NUM_0,
    "1": RemoteKey.NUM_1,
    "2": RemoteKey.NUM_2,
    "3": RemoteKey.NUM_3,
    "4": RemoteKey.NUM_4,
    "5": RemoteKey.NUM_5,
    "6": RemoteKey.NUM_6,
    "7": RemoteKey.NUM_7,
    "8": RemoteKey.NUM_8,
    "9": RemoteKey.NUM_9,
    "-": RemoteKey.DASH,
}


def channel_to_keys(channel: str) -> list[RemoteKey]:
    """Turn a channel string like "140" or "140-01" into a key sequence.

    Used by transports that lack a native "tune" primitive: they replay the
    digits followed by ENTER, exactly as a person would on the remote.
    """
    keys: list[RemoteKey] = []
    for char in channel.strip():
        key = DIGIT_KEYS.get(char)
        if key is None:
            raise ValueError(f"invalid channel character {char!r} in {channel!r}")
        keys.append(key)
    keys.append(RemoteKey.ENTER)
    return keys


def parse_key(value: str) -> RemoteKey:
    """Resolve a user-supplied key name to a RemoteKey, case-insensitively.

    Accepts both the enum value ("channel_up") and the enum name ("CH_UP").
    """
    candidate = value.strip().lower()
    for key in RemoteKey:
        if key.value == candidate or key.name.lower() == candidate:
            return key
    valid = ", ".join(sorted(k.value for k in RemoteKey))
    raise ValueError(f"unknown key {value!r}; valid keys: {valid}")
