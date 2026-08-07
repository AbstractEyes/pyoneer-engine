"""Per-channel debug tracing.

The engine used to trace with bare `print()`. That has two problems: it is
all-or-nothing (you get every mouse motion across every component or you get
nothing), and turning it off means editing source.

This gives the same visibility on a switch, per subsystem:

    PYONEER_DEBUG=mouse python main.py
    PYONEER_DEBUG=mouse,events python main.py
    PYONEER_DEBUG=all python main.py

Or from code, before the engine starts:

    from scripts.core import log
    log.enable("mouse", "render")

Cost when disabled is one integer comparison per call site -- stdlib logging
defers message formatting until it knows the record will be emitted, so
`trace_mouse("down inside %s", self.parent)` never builds the string unless
the channel is on. Do not pass expensive expressions as arguments; those are
evaluated regardless.

CHANNELS
    mouse      hit testing, enter/leave, press/release/drag
    keyboard   key events, repeats, text capture
    events     dispatch, consumption, fan-out
    render     blit queueing, layer preparation
    input      action edges, binding resolution
    lifecycle  build / prepare / dispose
    assets     config, map and animation loading

This is for TRACING - the running commentary. It is not the reporting
channel for problems: contract violations raise (scripts/core/errors.py) and
recoverable content issues warn. Those are always on.
"""
from __future__ import annotations

import logging
import os
import sys

CHANNELS = ("mouse", "keyboard", "events", "render", "input", "lifecycle", "assets")

_ROOT = "pyoneer"
_configured = False


def _configure_once():
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
    root = logging.getLogger(_ROOT)
    root.addHandler(handler)
    root.setLevel(logging.WARNING)   # channels opt in individually
    root.propagate = False
    _configured = True


def channel(name: str) -> logging.Logger:
    """The logger for one channel. Unknown names are rejected loudly."""
    if name not in CHANNELS:
        raise ValueError(
            f"unknown debug channel {name!r}; valid channels: {', '.join(CHANNELS)}"
        )
    _configure_once()
    return logging.getLogger(f"{_ROOT}.{name}")


def enable(*names: str):
    """Turn on one or more channels, or 'all'."""
    _configure_once()
    targets = CHANNELS if "all" in names else names
    for name in targets:
        channel(name).setLevel(logging.DEBUG)


def disable(*names: str):
    _configure_once()
    targets = CHANNELS if (not names or "all" in names) else names
    for name in targets:
        channel(name).setLevel(logging.WARNING)


def enabled(name: str) -> bool:
    return channel(name).isEnabledFor(logging.DEBUG)


def _enable_from_environment():
    """Read PYONEER_DEBUG at import so `PYONEER_DEBUG=mouse python main.py` works."""
    raw = os.environ.get("PYONEER_DEBUG", "").strip()
    if not raw:
        return
    requested = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    unknown = [r for r in requested if r != "all" and r not in CHANNELS]
    if unknown:
        # A typo here silently buys you no output, which is the exact failure
        # mode this module exists to remove.
        raise ValueError(
            f"PYONEER_DEBUG names unknown channel(s) {unknown}; "
            f"valid: all, {', '.join(CHANNELS)}"
        )
    enable(*requested)


# Module-level channel handles, so call sites read as `trace_mouse(...)`
# rather than re-resolving a logger every frame.
_enable_from_environment()

trace_mouse = channel("mouse").debug
trace_keyboard = channel("keyboard").debug
trace_events = channel("events").debug
trace_render = channel("render").debug
trace_input = channel("input").debug
trace_lifecycle = channel("lifecycle").debug
trace_assets = channel("assets").debug
