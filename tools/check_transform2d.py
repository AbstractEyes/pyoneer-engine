"""Verify Transform2D in isolation, and that GameComponent did not move.

`scripts/core/transform2d.py` is one slice taken out of the GameComponent god
class: local bounds, world bounds, the offset between them, and the
move/scale/rotate writes. The extraction is only worth anything if it is a
MOVE -- so this file checks two separate things and says which is which:

  1. the unit on its own, with no component tree and no event bus in sight;
  2. that every GameComponent accessor built on it still gives the same
     answer, including the offset contract.

The offset contract lived in tools/check_events.py, where it was pinned on a
CHILDLESS root and re-derived with `force_update_transforms()` -- which fans
out to children and therefore did nothing at all. Those two assertions could
not fail. They are re-taken here through a real parent, where a double-count
actually shows up.

    .venv/Scripts/python.exe tools/check_transform2d.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import ast
import os
import sys

import pygame

pygame.init()
pygame.display.set_mode((256, 256))

from pygame import Rect, Vector2

from scripts.core.component import GameComponent
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.transform2d import Transform2D
from scripts.core.ui.widget.shape import ShapeComponent

failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<52} got={got} want={want}")
    if not ok:
        failures.append(label)


def xywh(rect: Rect) -> tuple:
    return tuple(rect)


def as_xy(value):
    """Report a Vector2 as a plain pair, anything else unchanged.

    `tuple()` on a broken value (a leftover float) raises, and a check that
    dies with a TypeError instead of printing got/want is a worse instrument
    than one that prints the wrong number. Type is asserted separately --
    Vector2 compares equal to a tuple, so a value comparison alone cannot
    tell a coerced payload from a raw one.
    """
    return (value.x, value.y) if isinstance(value, Vector2) else value


# ==========================================================================
# PART 1 -- the unit, alone
# ==========================================================================
print("Transform2D: construction seeds two INDEPENDENT rects")
# The bounds are held in a NAMED rect, not built inline. A temporary is
# unreachable after the call, so `local is bounds` -- the constructor storing
# the caller's rect instead of copying it -- is invisible to every assertion
# that can be written about a temporary.
source = Rect(4, 5, 6, 7)
t = Transform2D(source)
expect("local takes the bounds", xywh(t.local), (4, 5, 6, 7))
expect("world takes the bounds too", xywh(t.world), (4, 5, 6, 7))
expect("but they are not the same object", t.local is t.world, False)
expect("and neither of them is the caller's rect",
       (t.local is source, t.world is source), (False, False))
# Identity is not enough on its own: what it buys is that the caller may go
# on using its own rect. Every GameComponent hands its constructor a rect it
# still holds, so an alias here means a widget that moves when something
# unrelated resizes the rect it was built from.
source.x, source.height = 99, 42
expect("so writing the source afterwards reaches neither",
       (xywh(t.local), xywh(t.world)), ((4, 5, 6, 7), (4, 5, 6, 7)))
t.local.x = 99
expect("so writing local leaves world alone", t.world.x, 4)
expect("no bounds means an empty rect, not None", xywh(Transform2D().local), (0, 0, 0, 0))
expect("offset starts at zero", (Transform2D().offset.x, Transform2D().offset.y), (0.0, 0.0))

print()
print("resolve(): world = local + parent.world + offset, exactly once")
# Every term is a different number, so dropping or duplicating any one of
# them lands somewhere this assertion can see.
t = Transform2D(Rect(10, 20, 4, 6))
t.offset = Vector2(3, 5)
parent_world = Rect(100, 200, 999, 999)
t.resolve(parent_world)
expect("all three terms are summed", xywh(t.world), (113, 225, 4, 6))
expect("size comes from LOCAL, not the parent", xywh(t.world)[2:], (4, 6))
t.resolve(parent_world)
expect("resolving twice is idempotent", xywh(t.world), (113, 225, 4, 6))
t.resolve(parent_world)
expect("and stays idempotent on a third pass", xywh(t.world), (113, 225, 4, 6))
expect("local is never written by resolve", xywh(t.local), (10, 20, 4, 6))

print()
print("resolve(None) is a NO-OP -- a root's world is owned elsewhere")
t = Transform2D(Rect(1, 1, 2, 2))
t.offset = Vector2(50, 60)
t.set_world(Rect(777, 888, 2, 2))
t.resolve(None)
expect("rootless resolve leaves world untouched", xywh(t.world), (777, 888, 2, 2))

print()
print("resync() is the entry point that DOES handle a root")
t = Transform2D(Rect(1, 1, 2, 2))
t.offset = Vector2(50, 60)
t.set_world(Rect(777, 888, 2, 2))
t.resync(Rect(10, 10, 2, 2), None)
expect("rootless resync rebuilds world from local + offset", xywh(t.world), (60, 70, 2, 2))
t.resync(Rect(10, 10, 2, 2), None)
expect("and does not accumulate the offset", xywh(t.world), (60, 70, 2, 2))
expect("resync uses the local it was HANDED, not self.local",
       xywh(t.local), (1, 1, 2, 2))
# The `local` parameter is honoured on the ROOTLESS branch only: the parented
# branch delegates to resolve(), which reads self.local. Both GameComponent
# callers hand it a rect equal to self.local, so this never bites -- but it is
# the sort of thing a later reader "tidies" into a general knob, so it is
# pinned here with self.local (1,1) deliberately disagreeing with the (10,10)
# that was passed.
t.resync(Rect(10, 10, 2, 2), Rect(100, 100, 0, 0))
expect("with a parent it delegates to resolve, using SELF.local",
       xywh(t.world), (151, 161, 2, 2))

print()
print("move(): local is what the caller asked for; offset lands on world")
# local and world are given DIFFERENT sizes first, because move() takes the
# new local size from local and the new world size from world. If it took
# both from one of them, this catches it.
t = Transform2D(Rect(0, 0, 20, 20))
t.set_world(Rect(0, 0, 33, 44))
t.offset = Vector2(7, 3)
t.move(10, 10, parented=False)
expect("local is exactly the requested point", xywh(t.local), (10, 10, 20, 20))
expect("world carries the offset, once", xywh(t.world), (17, 13, 33, 44))
t.resync(t.local, None)
expect("re-deriving does not add the offset again", xywh(t.world), (17, 13, 20, 20))

print()
print("move(parented=True) is asymmetric ON PURPOSE (the window drag path)")
t = Transform2D(Rect(10, 10, 20, 20))
t.offset = Vector2(7, 3)
t.move(30, 40, parented=True)
expect("a parented move does NOT write local", xywh(t.local), (10, 10, 20, 20))
expect("and writes world without the parent origin", xywh(t.world), (37, 43, 20, 20))

print()
print("set_world() copies; it does not alias the caller's rect")
t = Transform2D()
source = Rect(1, 2, 3, 4)
t.set_world(source)
source.x = 999
expect("mutating the source cannot reach the transform", t.world.x, 1)

print()
print("adopt_world_as_local() restates local IN PLACE")
t = Transform2D(Rect(1, 2, 3, 4))
local_identity = t.local
t.set_world(Rect(40, 50, 7, 8))
t.adopt_world_as_local()
expect("local now matches world", xywh(t.local), (40, 50, 7, 8))
expect("and it is still the SAME Rect object", t.local is local_identity, True)

print()
print("shift_point() crosses the same boundary, in place")
t = Transform2D()
t.offset = Vector2(7, 3)
point = Vector2(10, 10)
returned = t.shift_point(point)
expect("the point moved by the offset", (point.x, point.y), (17.0, 13.0))
expect("and the caller's own vector is what came back", returned is point, True)

print()
print("the module is a LEAF -- it imports pygame and stops")
# This is the guard that keeps the extraction from re-tangling. Five previous
# refactors in this repo died as sibling modules that imported the incumbent
# class back; scripts/ may not import editor/ either (tools/check_editor.py
# owns that rule, this one owns the narrower case).
source_path = os.path.join(_bootstrap.REPO_ROOT, "scripts", "core", "transform2d.py")
with open(source_path, "r", encoding="utf-8") as handle:
    tree = ast.parse(handle.read())
imported: list[str] = []
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imported.extend(alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        imported.append(node.module)
expect("transform2d imports nothing from scripts/ or editor/",
       sorted(n for n in imported if n.split(".")[0] in ("scripts", "editor")), [])
expect("it did import something (the scan is looking at real source)",
       "pygame" in imported, True)


# ==========================================================================
# PART 2 -- GameComponent did not move
# ==========================================================================
print()
print("GameComponent delegates to ONE transform, and hands out the real rects")
comp = ShapeComponent(bounds=Rect(2, 3, 8, 9))
expect("local_bounds IS the transform's local", comp.local_bounds is comp.transform.local, True)
expect("world_bounds IS the transform's world", comp.world_bounds is comp.transform.world, True)
expect("offset IS the transform's offset", comp.offset is comp.transform.offset, True)
expect("the transform accessor is stable", comp.transform is comp.transform, True)
expect("constructor bounds reach local", xywh(comp.local_bounds), (2, 3, 8, 9))
expect("constructor bounds reach world", xywh(comp.world_bounds), (2, 3, 8, 9))
expect("and local is not aliased to world", comp.local_bounds is comp.world_bounds, False)

print()
print("world_bounds setter still copies")
comp = ShapeComponent(bounds=Rect(0, 0, 4, 4))
handed = Rect(10, 11, 4, 4)
comp.world_bounds = handed
handed.x = 999
expect("the assigned rect was copied, not aliased", comp.world_bounds.x, 10)

print()
print("the bounds cascade is handed SNAPSHOTS, not live rects")
# `current` is explicitly `new_bounds.copy()`; `previous` is a copy for the
# same reason, and the reason is not symmetry. The setter stores the caller's
# rect WITHOUT copying it, so the rect a component was last assigned is the
# one it is still holding -- and that same object is what `previous` would be
# on the NEXT assignment. Handing it out live means a caller that reuses its
# own rect afterwards silently rewrites what every listener recorded.


class Recorder(ShapeComponent):
    """A ShapeComponent that keeps the two rects the cascade was given."""

    seen: list = []

    def _on_bounds_changed(self, previous, current):
        Recorder.seen.append((previous, current))
        super()._on_bounds_changed(previous, current)


recorder = Recorder(bounds=Rect(0, 0, 4, 4))
handed = Rect(1, 2, 10, 10)
recorder.local_bounds = handed
expect("the setter stores the caller's own rect, uncopied",
       recorder.local_bounds is handed, True)
Recorder.seen.clear()
recorder.local_bounds = Rect(30, 40, 10, 10)
expect("assigning different bounds fires the cascade once", len(Recorder.seen), 1)
seen_previous, seen_current = Recorder.seen[-1] if Recorder.seen else (None, None)
expect("previous is not the rect the caller handed over last time",
       seen_previous is handed, False)
expect("and current is not the rect the component is holding now",
       seen_current is recorder.local_bounds, False)
handed.x, handed.y = 999, 888
expect("so the caller reusing its rect cannot rewrite what was reported",
       xywh(seen_previous), (1, 2, 10, 10))

print()
print("offset is a LOCAL->WORLD shift, and move() does not fold it into local")
# Re-taken from check_events, through a REAL parent this time. The bug being
# guarded is move() writing `local = Rect(x + offset.x, ...)`: local absorbs
# the shift, and world -- derived as local + parent.world + offset -- then
# counts it a second time on the next resolve. A childless root never
# re-resolves, which is why the original form of this test could not fail.
root = ShapeComponent(bounds=Rect(100, 100, 200, 200))
kid = ShapeComponent(parent=root, bounds=Rect(10, 10, 20, 20))
root.bind_component("kid", kid)
expect("the child starts rebased on its parent", xywh(kid.world_bounds), (110, 110, 20, 20))

kid.offset = Vector2(7, 3)
root.force_update_transforms()
expect("world = local + parent.world + offset", xywh(kid.world_bounds), (117, 113, 20, 20))
root.force_update_transforms()
expect("a second resolve does not add the offset again", xywh(kid.world_bounds), (117, 113, 20, 20))
root.force_update_transforms()
expect("nor a third", xywh(kid.world_bounds), (117, 113, 20, 20))
expect("and local never absorbed the shift", xywh(kid.local_bounds), (10, 10, 20, 20))

kid.move(30, 40)
expect("a parented move leaves local alone", xywh(kid.local_bounds), (10, 10, 20, 20))
expect("and writes world without the parent origin", xywh(kid.world_bounds), (37, 43, 20, 20))
root.force_update_transforms()
expect("the next resolve puts it back on the parent", xywh(kid.world_bounds), (117, 113, 20, 20))

print()
print("a rootless component: move(), then a real re-derive")
drifter = ShapeComponent(bounds=Rect(0, 0, 20, 20))
drifter.offset = Vector2(7, 3)
drifter.move(10, 10)
expect("move(10,10) puts local at exactly (10,10)", xywh(drifter.local_bounds)[:2], (10, 10))
expect("and world carries the offset, once", xywh(drifter.world_bounds)[:2], (17, 13))
# local_bounds assignment is the path that actually re-derives a root's
# world -- unlike force_update_transforms(), which only fans out to children.
drifter.local_bounds = Rect(50, 60, 20, 20)
expect("re-deriving a root keeps the offset at one", xywh(drifter.world_bounds), (57, 63, 20, 20))
drifter.local_bounds = Rect(10, 10, 20, 20)
expect("and moving back lands where move() left it", xywh(drifter.world_bounds), (17, 13, 20, 20))

still = ShapeComponent(bounds=Rect(4, 5, 8, 8))
expect("a zero offset leaves local and world identical",
       (xywh(still.local_bounds)[:2], xywh(still.world_bounds)[:2]), ((4, 5), (4, 5)))
still.move(30, 40)
expect("and move() is then plain assignment",
       (xywh(still.local_bounds)[:2], xywh(still.world_bounds)[:2]), ((30, 40), (30, 40)))

print()
print("bind_parent(preserve_world_bounds=True) restates local from world")
host = ShapeComponent(bounds=Rect(0, 0, 10, 10))
guest = ShapeComponent(bounds=Rect(5, 6, 7, 8))
identity = guest.local_bounds
guest.world_bounds = Rect(40, 50, 7, 8)
guest.bind_parent(host, preserve_world_bounds=True)
expect("local was restated from world", xywh(guest.local_bounds), (40, 50, 7, 8))
expect("in place, so the bounds cascade never fired",
       guest.local_bounds is identity, True)
expect("world re-resolved against the new parent", xywh(guest.world_bounds), (40, 50, 7, 8))

print()
print("adjusted_position keeps its three-way contract")
shifter = ShapeComponent(bounds=Rect(0, 0, 10, 10))
shifter.offset = Vector2(7, 3)
vec = Vector2(1, 2)
out = shifter.adjusted_position(vec)
expect("a Vector2 is shifted by the offset", (out.x, out.y), (8.0, 5.0))
expect("and it is the caller's own vector", out is vec, True)
expect("a Rect converts to its topleft, UNSHIFTED",
       tuple(shifter.adjusted_position(Rect(1, 2, 3, 4))), (1.0, 2.0))
expect("a tuple converts, UNSHIFTED",
       tuple(shifter.adjusted_position((1, 2))), (1.0, 2.0))

print()
print("scale() and rotate() write through to the transform")
spinner = ShapeComponent(bounds=Rect(0, 0, 10, 10))
expect("scale starts at 1.0", spinner.transform.scale, 1.0)
expect("rotation starts at 0.0", spinner.transform.rotation, 0.0)
spinner.rotate(0.25)
expect("rotate() stores the angle", spinner.transform.rotation, 0.25)
spinner.scale(Vector2(2, 3))
expect("scale() stores the vector", as_xy(spinner.transform.scale), (2.0, 3.0))

print()
print("a TRANSFORM event still coerces every payload shape it advertises")
# core_lifecycle_prepare is REQUIRED: __transform_component is bound there,
# not in __init__. tools/check_events.py fires TRANSFORM at an unprepared
# ShapeComponent, so its four scale payloads reach no listener at all.
payloads = ShapeComponent(bounds=Rect(0, 0, 10, 10))
payloads.core_lifecycle_prepare(None)
expect("the TRANSFORM listener is actually bound",
       payloads.has_event_type(GameEventType.TRANSFORM), True)


def transform_event(**data):
    payloads.send_event_advanced(
        GameEventType.TRANSFORM,
        PyoneerEvent(GameEventType.TRANSFORM, sender=None, data=data))


transform_event(scale=Vector2(2, 3))
expect("Vector2 scale lands as-is", as_xy(payloads.transform.scale), (2.0, 3.0))
transform_event(scale=(4, 5))
expect("tuple scale carries the right numbers", as_xy(payloads.transform.scale), (4.0, 5.0))
# Value alone proves nothing here: Vector2(4, 5) == (4, 5) is True, so a
# handler that stored the raw tuple would pass the line above.
expect("and the tuple really was COERCED to a Vector2",
       isinstance(payloads.transform.scale, Vector2), True)
transform_event(scale=6)
expect("a bare number scales both axes", as_xy(payloads.transform.scale), (6.0, 6.0))
transform_event(scale=7.5)
expect("floats too", as_xy(payloads.transform.scale), (7.5, 7.5))

transform_event(rotation=0.5)
expect("a float rotation is stored raw", payloads.transform.rotation, 0.5)
transform_event(rotation=(1.25, 0))
expect("a tuple rotation takes element 0", payloads.transform.rotation, 1.25)
transform_event(rotation=180)
expect("an INT rotation is degrees, divided by 360", payloads.transform.rotation, 0.5)

transform_event(position=Vector2(11, 12))
expect("a position payload routes into move()", xywh(payloads.local_bounds)[:2], (11, 12))
transform_event(offset=Vector2(9, 9))
expect("an offset payload routes into the transform",
       (payloads.offset.x, payloads.offset.y), (9.0, 9.0))

print()
print("the bounds cascade still rebases children off the extracted world")
outer = ShapeComponent(bounds=Rect(10, 10, 40, 40))
inner = ShapeComponent(parent=outer, bounds=Rect(2, 2, 8, 8))
outer.bind_component("inner", inner)
expect("child starts rebased", xywh(inner.world_bounds), (12, 12, 8, 8))
outer.local_bounds = Rect(30, 30, 100, 50)
expect("the parent's own world followed", xywh(outer.world_bounds), (30, 30, 100, 50))
expect("and the child rebased onto it", xywh(inner.world_bounds), (32, 32, 8, 8))
expect("the child's local is untouched -- only positions rebase",
       xywh(inner.local_bounds), (2, 2, 8, 8))

print()
print("the public surface GameComponent advertises is all still there")
for name in ("local_bounds", "world_bounds", "offset", "move", "scale", "rotate",
             "adjusted_bounds", "adjusted_position", "force_update_transforms",
             "notify_parent_bounds_changed", "bind_parent"):
    expect(f"GameComponent.{name}", hasattr(GameComponent, name), True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
