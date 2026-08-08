"""Verify event consumption, input gating, depth mutability and bounds cascade.

Guards five repairs:
  1. mark_event_handled() actually consumes -- stops siblings, children and
     remaining listeners.
  2. Input is gated on `active`, NEVER on `visible`. A hidden but active
     component still receives input; that is the specified behaviour.
  3. GameComponent.depth is writable again.
  4. A local_bounds change cascades: world bounds, then children, then
     surfaces. DrawComponent.resize() REALLOCATES rather than stretching.
  5. No component reached through a parent's `components` dict defines a
     core_frame_update or core_render_blits override, because the event bus
     never calls them there.
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
from scripts.core.ui.widget_color import WidgetColor

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
print("a TRANSFORM carrying scale reaches a drawable without exploding")
# DrawComponent.scale(width, height, destination) used to OVERRIDE
# GameComponent.scale(scale, sender). component.py calls self.scale(scale,
# self) when a TRANSFORM carries scale data, so on any drawable that arrived
# as width=Vector2, height=self. Latent only because nothing wrote "scale"
# into TRANSFORM data -- this asserts it stays safe now that something can.
from pygame import Vector2

from scripts.core.ui.widget.draw import DrawComponent

drawable = ShapeComponent(bounds=Rect(0, 0, 20, 20))
expect("DrawComponent no longer shadows GameComponent.scale",
       DrawComponent.scale is GameComponent.scale, True)
expect("the surface operation kept a distinct name",
       hasattr(drawable, "scale_surface"), True)
for payload in (Vector2(2, 2), (2, 2), 2, 2.0):
    try:
        drawable.send_event_advanced(
            GameEventType.TRANSFORM,
            PyoneerEvent(GameEventType.TRANSFORM, sender=None, data={"scale": payload}))
    except TypeError as exc:
        print(f"  FAIL scale payload {payload!r}: {exc}")
        failures.append(f"scale {payload!r}")
print("  ok   Vector2 / tuple / int / float scale payloads all dispatch")

print()
print("drag events can actually be bound")
from scripts.core.ui.widget.behavior.mouse import MouseComponentAsync

host = Probe("host", [], bounds=Rect(0, 0, 40, 40))
mouse = MouseComponentAsync(parent=host)
for typ in (GameEventType.MOUSE_DRAG_BEGIN, GameEventType.MOUSE_DRAG_END,
            GameEventType.MOUSE_DRAGGING):
    mouse.bind_mouse_listener(typ, lambda e, *a, **k: None)
    expect(f"{typ.name} accepted", mouse.has_mouse_listener(typ), True)

print()
print("a freshly allocated drawable surface is TRANSPARENT, not opaque black")
blank = DrawComponent(bounds=Rect(0, 0, 8, 8))
expect("SRCALPHA is set", bool(blank.image.get_flags() & pygame.SRCALPHA), True)
expect("every pixel starts fully transparent", tuple(blank.image.get_at((0, 0))), (0, 0, 0, 0))

print()
print("resize() reallocates and repaints; it does not stretch")
box = ShapeComponent(bounds=Rect(0, 0, 20, 10),
                     background_color=WidgetColor(200, 0, 0, 255),
                     border_color=WidgetColor(0, 0, 200, 255))
box.send_event_advanced(GameEventType.PREPARE, None)
before_surface = box.image
expect("built at its bounds", box.image.get_size(), (20, 10))
expect("resize reports a real change", box.resize(60, 30), True)
expect("surface follows", box.image.get_size(), (60, 30))
expect("the surface object was REPLACED, not scaled in place",
       box.image is before_surface, False)
# A stretch would smear the 20x10 artwork over 60x30 and leave the far corner
# painted from the old pixels. A reallocate-and-repaint paints from
# world_bounds -- which is still 20x10 here, because resize() alone does not
# move bounds -- so everything past x=20 must be untouched transparent.
expect("repainted from world_bounds, not stretched",
       tuple(box.image.get_at((50, 25))), (0, 0, 0, 0))
expect("and the original region really was repainted",
       box.image.get_at((10, 5)) != pygame.Color(0, 0, 0, 0), True)
expect("a resize to the same size is a no-op", box.resize(60, 30), False)

print()
print("resize() re-fires PREPARE on ITSELF only, never on children")
seen_prepare = []
host = ShapeComponent(bounds=Rect(0, 0, 10, 10))
kid = ShapeComponent(parent=host, bounds=Rect(0, 0, 4, 4))
host.bind_component("kid", kid)
host.bind_sync_listener(GameEventType.PREPARE, lambda e, *a, **k: seen_prepare.append("host"))
kid.bind_sync_listener(GameEventType.PREPARE, lambda e, *a, **k: seen_prepare.append("kid"))
host.resize(12, 12)
expect("only the resized component repainted", seen_prepare, ["host"])

print()
print("a local_bounds size change cascades to world bounds, children, surfaces")
outer = ShapeComponent(bounds=Rect(10, 10, 40, 40))
inner = ShapeComponent(parent=outer, bounds=Rect(2, 2, 8, 8))
outer.bind_component("inner", inner)
expect("child world bounds start rebased", tuple(inner.world_bounds), (12, 12, 8, 8))
outer.local_bounds = Rect(30, 30, 100, 50)
expect("own world bounds followed", tuple(outer.world_bounds), (30, 30, 100, 50))
expect("own surface followed", outer.image.get_size(), (100, 50))
expect("child world bounds rebased onto the moved parent",
       tuple(inner.world_bounds), (32, 32, 8, 8))
expect("child surface untouched -- size is not inherited",
       inner.image.get_size(), (8, 8))

print()
print("a pure move does not reallocate the surface")
mover = ShapeComponent(bounds=Rect(0, 0, 16, 16))
kept = mover.image
mover.local_bounds = Rect(5, 5, 16, 16)
expect("same surface object", mover.image is kept, True)
expect("world bounds still moved", tuple(mover.world_bounds), (5, 5, 16, 16))

print()
print("a Button passes its own size down to its body and label")
from scripts.core.ui.widget.containers.button import Button

btn = Button(bounds=Rect(0, 0, 50, 20), text="hi")
expect("body built at the button size",
       btn.get_component("background").image.get_size(), (50, 20))
btn.local_bounds = Rect(0, 0, 90, 34)
expect("body surface followed", btn.get_component("background").image.get_size(), (90, 34))
expect("body world bounds followed",
       tuple(btn.get_component("background").world_bounds)[2:], (90, 34))
expect("label surface followed height",
       btn.get_component("text").image.get_height() > 20, True)

print()
print("the scroll thumb's surface follows its bounds (the reported bug)")
from pygame import Rect as _Rect

from scripts.core.ui.widget.containers.panel import Panel

panel = Panel(bounds=_Rect(0, 0, 300, 200), working_area=_Rect(0, 0, 300, 210))
panel.core_lifecycle_build(None)
thumb = panel.vertical_scroll.scroll_thumb
thumb_shape = thumb.get_component("background")
expect("bounds and surface agree at construction",
       (thumb.local_bounds.height, thumb_shape.image.get_height()), (118, 118))

panel.vertical_scroll.scrollable_bounds = _Rect(0, 0, 300, 4000)
panel.vertical_scroll.send_event_advanced(
    GameEventType.VIEWPORT_SCROLLED,
    PyoneerEvent(GameEventType.VIEWPORT_SCROLLED, sender=None, data={}))
expect("thumb shrank for the taller content", thumb.local_bounds.height, 6)
expect("its world bounds shrank too", thumb.world_bounds.height, 6)
expect("and so did the surface it actually draws",
       thumb_shape.image.get_height(), 6)

print()
print("no component with a parent overrides core_frame_update / core_render_blits")
# A GameComponent reached through a parent's `components` dict is driven by
# send_event_advanced, not by its core_* methods. Panel.core_frame_update
# measured 0 calls per frame for exactly this reason -- its whole body was
# dead code. Walk a real widget tree and refuse to let that come back.
#
# core_lifecycle_prepare* and core_lifecycle_build are NOT in the ban list:
# bind_component() invokes those four directly on the child, so overriding
# them there is legitimate and load-bearing (Panel and ScrollComponent build
# most of the UI from core_lifecycle_build).
from scripts.core.game_object import PyoneerGameObject
from scripts.core.ui.widget.containers.window import GameWindow
from scripts.game.demo_window import DemoWindow

BANNED = ("core_frame_update", "core_render_blits")


def bus_driven_overrides(component) -> list[str]:
    found = []
    for klass in type(component).__mro__:
        if klass in (GameComponent, PyoneerGameObject, object):
            break
        for name in BANNED:
            if name in klass.__dict__:
                found.append(f"{klass.__name__}.{name}")
    return found


def walk(component, seen=None):
    if seen is None:
        seen = set()
    if id(component) in seen:
        return
    seen.add(id(component))
    yield component
    for child in getattr(component, "components", {}).values():
        yield from walk(child, seen)


# DemoWindow, not GameWindow. The census needs a tree with Panels, scrollbars
# and a TextBox in it, and those moved out of GameWindow when the reusable
# chrome was separated from the demo content -- a bare GameWindow is now 10
# components, which would let this guard pass over almost nothing.
live_window = DemoWindow(bounds=Rect(0, 0, 400, 400))
live_window.core_lifecycle_prepare(PyoneerEvent(GameEventType.PREPARE, sender=None, data={}))
live_window.core_lifecycle_build(PyoneerEvent(GameEventType.BUILD, sender=None, data={}))

walked = list(walk(live_window))
classes = {type(c).__name__ for c in walked}
# Guard the guard: an empty or truncated walk must not pass silently.
expect("the walked tree is a real UI tree", len(walked) > 50, True)
for required in ("Panel", "ScrollComponent", "Button", "TextBox",
                 "ShapeComponent", "TextComponent", "MouseComponentAsync"):
    expect(f"{required} is in the walked tree", required in classes, True)

offenders = []
for component in walked:
    if component.parent is None:
        continue  # a root IS driven through core_*; that is its job
    for name in bus_driven_overrides(component):
        if name not in offenders:
            offenders.append(name)
expect("no bus-driven component overrides an unreachable core_* method",
       offenders, [])

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
