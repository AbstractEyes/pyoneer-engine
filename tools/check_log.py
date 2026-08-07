"""Verify the debug trace channels.

The engine traced with bare print() before: all-or-nothing, and silencing it
meant editing source. These assert the replacement is off by default, opt-in
per subsystem, and loud about a mistyped channel name -- a typo that silently
buys you no output is the exact failure this module exists to remove.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import io
import logging
import sys

from scripts.core import log

failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<50} got={got} want={want}")
    if not ok:
        failures.append(label)


print("silent by default")
log.disable()
for name in log.CHANNELS:
    if log.enabled(name):
        failures.append(f"{name} on by default")
expect("no channel is on until asked", [n for n in log.CHANNELS if log.enabled(n)], [])

print()
print("channels turn on individually")
log.enable("mouse")
expect("mouse on", log.enabled("mouse"), True)
expect("events still off", log.enabled("events"), False)
log.enable("events", "render")
expect("events on", log.enabled("events"), True)
expect("render on", log.enabled("render"), True)
log.disable("mouse")
expect("mouse back off", log.enabled("mouse"), False)
expect("events unaffected by disabling mouse", log.enabled("events"), True)

log.enable("all")
expect("'all' turns on every channel",
       [n for n in log.CHANNELS if not log.enabled(n)], [])
log.disable()
expect("bare disable() silences everything",
       [n for n in log.CHANNELS if log.enabled(n)], [])

print()
print("output actually reaches the handler")
buffer = io.StringIO()
handler = logging.StreamHandler(buffer)
handler.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
root = logging.getLogger("pyoneer")
root.addHandler(handler)
try:
    log.trace_mouse("should not appear %s", "x")
    expect("nothing emitted while disabled", buffer.getvalue(), "")
    log.enable("mouse")
    log.trace_mouse("down inside %s at %s", "Button", (1, 2))
    emitted = buffer.getvalue().strip()
    expect("emitted once enabled", "down inside Button at (1, 2)" in emitted, True)
    expect("tagged with its channel", emitted.startswith("[pyoneer.mouse]"), True)
finally:
    root.removeHandler(handler)
    log.disable()

print()
print("a mistyped channel fails loudly")
try:
    log.channel("moose")
    expect("raises on unknown channel", False, True)
except ValueError as exc:
    print(f"  ok   raised: {exc}")

print()
print("lazy formatting: args are not rendered while disabled")


class Loud:
    rendered = 0

    def __str__(self):
        Loud.rendered += 1
        return "expensive"


log.disable()
log.trace_mouse("value=%s", Loud())
expect("__str__ not called while disabled", Loud.rendered, 0)
log.enable("mouse")
log.trace_mouse("value=%s", Loud())
expect("__str__ called once enabled", Loud.rendered, 1)
log.disable()

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
