"""Verify event consumption, input gating and depth mutability.

Guards three repairs:
  1. mark_event_handled() actually consumes -- stops siblings, children and
     remaining listeners.
  2. Input is gated on `active`, NEVER on `visible`. A hidden but active
     component still receives input; that is the specified behaviour.
  3. GameComponent.depth is writable again.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import sys

import pygame

pygame.init()
pygame.display.set_mode((256, 256))

from pygame import Rect

from scripts.core.component import GameComponent
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.errors import PyoneerEventTypeError
from scripts.core.ui.widget.shape import ShapeComponent

failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<52} got={got} want={want}")
    if not ok:
        failures.append(label)


class Probe(GameComponent):
    """Minimal concrete component that records what it receives."""

    def __init__(self, tag, log, **kw):
        super().__init__(**kw)
        self.tag = tag
        self.log = log

    # Delegate rather than stub these out. An earlier version of this probe
    # overrode core_lifecycle_build with `pass`, which meant BUILD never
    # dispatched for it -- and made a real bind_component test fail against
    # working code.
    def core_lifecycle_build(self, event=None):
        return super().core_lifecycle_build(event)

    def core_lifecycle_dispose(self, event=None):
        return super().core_lifecycle_dispose(event)

    def core_input_receive(self, event=None):
        return super().core_input_receive(event)

    def listen(self, typ, consume=False):
        def handler(event, *a, **k):
            self.log.append(self.tag)
            if consume:
                self.mark_event_handled(event)
        self.bind_sync_listener(typ, handler)
        return self


def tree(log, **kw):
    root = Probe("root", log, bounds=Rect(0, 0, 100, 100), **kw)
    child = Probe("child", log, parent=root, bounds=Rect(0, 0, 50, 50))
    grand = Probe("grand", log, parent=child, bounds=Rect(0, 0, 20, 20))
    root.bind_component("child", child)
    child.bind_component("grand", grand)
    return root, child, grand


def fire(root, typ=GameEventType.UPDATE):
    root.send_event_advanced(typ, PyoneerEvent(typ, sender=None, data={}))


print("consumption stops the fan-out")
log = []
root, child, grand = tree(log)
root.listen(GameEventType.UPDATE)
child.listen(GameEventType.UPDATE, consume=True)
grand.listen(GameEventType.UPDATE)
fire(root)
expect("grandchild does not run after child consumes", log, ["root", "child"])

log.clear()
root, child, grand = tree(log)
root.listen(GameEventType.UPDATE, consume=True)
child.listen(GameEventType.UPDATE)
fire(root)
expect("children skipped when root consumes", log, ["root"])

print()
print("a second listener on the same component is skipped after consume")
log = []
root = Probe("root", log, bounds=Rect(0, 0, 10, 10))
root.listen(GameEventType.UPDATE, consume=True)
root.listen(GameEventType.UPDATE)  # second listener, same type
fire(root)
expect("only the consuming listener ran", len(log), 1)

print()
print("trickle overrides consumption")
log = []
root, child, grand = tree(log)
root.listen(GameEventType.UPDATE, consume=True)
child.listen(GameEventType.UPDATE)
ev = PyoneerEvent(GameEventType.UPDATE, sender=None, data={}, trickle=True)
root.send_event_advanced(GameEventType.UPDATE, ev)
expect("trickle=True still reaches children", log, ["root", "child"])

print()
print("input gating keys on active, NOT visible")
log = []
root, child, grand = tree(log)
root.listen(GameEventType.INPUTS)
child.listen(GameEventType.INPUTS)
root.visible = False           # hidden ...
root.active = True             # ... but still live
fire(root, GameEventType.INPUTS)
expect("hidden but active still receives input", log, ["root", "child"])

log.clear()
root, child, grand = tree(log)
root.listen(GameEventType.INPUTS)
child.listen(GameEventType.INPUTS)
root.visible = True
root.active = False            # disabled
fire(root, GameEventType.INPUTS)
expect("inactive subtree receives no input", log, [])

log.clear()
root, child, grand = tree(log)
root.listen(GameEventType.UPDATE)
child.listen(GameEventType.UPDATE)
root.active = False
fire(root, GameEventType.UPDATE)
expect("inactive still receives lifecycle events", log, ["root", "child"])

print()
print("structural mutation during dispatch")
log = []
root, child, grand = tree(log)


def spawn(event, *a, **k):
    log.append("spawn")
    root.bind_component("late", Probe("late", log, parent=root, bounds=Rect(0, 0, 5, 5)))


root.bind_sync_listener(GameEventType.UPDATE, spawn)
try:
    fire(root)
    print("  ok   binding a component mid-dispatch did not raise")
except RuntimeError as exc:
    print(f"  FAIL RuntimeError: {exc}")
    failures.append("bind during dispatch")

print()
print("depth is writable")
shape = ShapeComponent(bounds=Rect(0, 0, 10, 10))
try:
    shape.depth = 7
    expect("depth round-trips", shape.depth, 7)
except AttributeError as exc:
    print(f"  FAIL {exc}")
    failures.append("depth setter")

parent = Probe("p", [], bounds=Rect(0, 0, 10, 10))
kid = Probe("k", [], parent=parent, bounds=Rect(0, 0, 5, 5))
parent.depth = 100
kid.depth = 5
expect("child depth accumulates through parent", kid.depth, 105)

print()
print("a dispatch with event=None is delivered, not dropped")
log = []
solo = Probe("solo", log, bounds=Rect(0, 0, 10, 10))
solo.listen(GameEventType.UPDATE)
solo.send_event_advanced(GameEventType.UPDATE, None)
expect("event=None still reaches listeners", log, ["solo"])

log.clear()
root, child, grand = tree(log)
root.listen(GameEventType.UPDATE)
child.listen(GameEventType.UPDATE)
root.core_frame_update(None)
expect("lifecycle wrapper with None fans out", log, ["root", "child"])

print()
print("the synthesized event is usable by the listener")
seen = {}


def inspect_event(event, *a, **k):
    seen["type"] = event.type
    seen["sender"] = event.sender
    seen["data"] = event.data


probe = Probe("e", [], bounds=Rect(0, 0, 10, 10))
probe.bind_sync_listener(GameEventType.PREPARE, inspect_event)
probe.send_event_advanced(GameEventType.PREPARE, None)
expect("carries the right type", seen.get("type"), GameEventType.PREPARE)
expect("sender is the dispatching component", seen.get("sender") is probe, True)
expect("data is a dict, not None", isinstance(seen.get("data"), dict), True)

print()
print("bind_component now delivers PREPARE and BUILD to the child")
log = []
host = Probe("host", log, bounds=Rect(0, 0, 40, 40))
late = Probe("late", log, parent=host, bounds=Rect(0, 0, 10, 10))
late.listen(GameEventType.PREPARE)
late.listen(GameEventType.BUILD)
host.bind_component("late", late)
expect("child received both lifecycle events", sorted(log), ["late", "late"])

print()
print("an unroutable dispatch raises instead of returning silently")
try:
    Probe("x", [], bounds=Rect(0, 0, 4, 4)).send_event_advanced(None, None)
    expect("raises PyoneerEventTypeError", False, True)
except PyoneerEventTypeError as exc:
    print(f"  ok   raised: {str(exc).splitlines()[0]}")

print()
print("the manager gate does not deref a dict or None")
gated = Probe("g", [], bounds=Rect(0, 0, 10, 10))
gated.listen(GameEventType.UPDATE)
gated.manager = object()          # some other object manages it
try:
    gated.send_event_advanced(GameEventType.UPDATE, None)
    gated.send_event_advanced(GameEventType.UPDATE, {"k": 1})
    print("  ok   no AttributeError from the manager check")
except AttributeError as exc:
    print(f"  FAIL {exc}")
    failures.append("manager gate")

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
