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

    def core_build(self, event=None):
        pass

    def core_dispose(self, event=None):
        return True

    def core_inputs(self, event=None):
        return super().core_inputs(event)

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
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
