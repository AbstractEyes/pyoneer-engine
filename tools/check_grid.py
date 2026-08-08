"""Verify GridComponent lays out, binds, sizes, and scrolls inside a Panel.

Before this, GridComponent had never executed: add_item recorded a cell
coordinate and never bound the component or gave it a pixel rect, so items
never entered the tree and nothing was drawn. row_height and max_rows were
stored and never read.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import sys

import pygame

pygame.init()
pygame.display.set_mode((1024, 768))

from pygame import Rect, Vector2

from scripts.core import blitpool
from scripts.core.errors import PyoneerLayoutError
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.ui.widget.behavior.grid import GridComponent
from scripts.core.ui.widget.containers.panel import Panel
from scripts.core.ui.widget.shape import ShapeComponent

failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<52} got={got} want={want}")
    if not ok:
        failures.append(label)


def raises(label, exc_type, fn):
    try:
        fn()
    except exc_type as exc:
        print(f"  ok   {label:<52} {type(exc).__name__}")
        return
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL {label:<52} raised {type(exc).__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<52} did not raise")
    failures.append(label)


def square(w, h):
    return ShapeComponent(bounds=Rect(0, 0, w, h))


def prepared(component):
    component.core_lifecycle_prepare(PyoneerEvent(GameEventType.PREPARE, sender=None, data={}))
    component.core_lifecycle_build(PyoneerEvent(GameEventType.BUILD, sender=None, data={}))
    return component


# --------------------------------------------------------------------------
print("items are BOUND, not just recorded")
# --------------------------------------------------------------------------
grid = GridComponent(bounds=Rect(0, 0, 0, 0), max_columns=2, spacing=(4, 4), padding=(6, 6))
first = square(80, 24)
grid.add_item(first)
expect("item is in the component tree", first in grid.components.values(), True)
expect("item's parent is the grid", first.parent is grid, True)
expect("grid reports its count", grid.count, 1)
expect("item() returns it", grid.item(0) is first, True)
expect("find() by uuid works", grid.find(first.uuid) is not None, True)

# --------------------------------------------------------------------------
print()
print("layout: wrapping, column/row measurement, spacing and padding")
# --------------------------------------------------------------------------
grid = GridComponent(bounds=Rect(0, 0, 0, 0), max_columns=2, spacing=(4, 4), padding=(6, 6))
for w, h in [(80, 24), (50, 30), (60, 24), (90, 20), (40, 24)]:
    grid.add_item(square(w, h))

rects = [n.component.local_bounds for n in grid._nodes]
cells = [(n.column, n.row) for n in grid._nodes]
expect("wraps at max_columns", cells, [(0, 0), (1, 0), (0, 1), (1, 1), (0, 2)])
# column 0 = max(80,60,40) = 80, so column 1 starts at 6 + 80 + 4 = 90
expect("column 1 x accounts for widest in column 0", rects[1].x, 90)
# row 0 = max(24,30) = 30, so row 1 starts at 6 + 30 + 4 = 40
expect("row 1 y accounts for tallest in row 0", rects[2].y, 40)
expect("row 2 y", rects[4].y, 68)
expect("content_size", grid.content_size(), (186, 98))
expect("grid grew to fit", (grid.local_bounds.width, grid.local_bounds.height), (186, 98))

print()
print("fixed row_height / column_width override measurement")
fixed = GridComponent(bounds=Rect(0, 0, 0, 0), max_columns=2,
                      row_height=20, column_width=50)
for _ in range(4):
    fixed.add_item(square(999, 999))
expect("items forced to the fixed cell size",
       [(r.width, r.height) for r in (n.component.local_bounds for n in fixed._nodes)],
       [(50, 20)] * 4)
expect("content sized from the fixed cells", fixed.content_size(), (100, 40))

print()
print("single row when max_columns is unbounded")
row = GridComponent(bounds=Rect(0, 0, 0, 0), max_columns=-1, spacing=(2, 0))
for _ in range(3):
    row.add_item(square(30, 10))
expect("all on row 0", [n.row for n in row._nodes], [0, 0, 0])
expect("laid out left to right", [n.component.local_bounds.x for n in row._nodes], [0, 32, 64])

print()
print("explicit cell placement pins an item")
pinned = GridComponent(bounds=Rect(0, 0, 0, 0), max_columns=2)
a, b, c = square(10, 10), square(10, 10), square(10, 10)
pinned.add_item(a)
pinned.add_item(b, cell=(1, 3))
pinned.add_item(c)
expect("pinned item keeps its cell", (pinned.find(b.uuid).column, pinned.find(b.uuid).row), (1, 3))
expect("auto items ignore the pinned slot",
       [(pinned.find(x.uuid).column, pinned.find(x.uuid).row) for x in (a, c)],
       [(0, 0), (1, 0)])

print()
print("removal re-flows the auto-placed items")
grid = GridComponent(bounds=Rect(0, 0, 0, 0), max_columns=2)
items = [square(10, 10) for _ in range(4)]
for item in items:
    grid.add_item(item)
expect("removal reports success", grid.remove_item(items[0]), True)
expect("removed item left the tree", items[0] in grid.components.values(), False)
expect("count dropped", grid.count, 3)
expect("survivors re-packed from the origin",
       [(grid.find(x.uuid).column, grid.find(x.uuid).row) for x in items[1:]],
       [(0, 0), (1, 0), (0, 1)])
expect("removing an unknown component is False", grid.remove_item(square(1, 1)), False)

grid.clear()
expect("clear empties the grid", grid.count, 0)
expect("clear unbinds everything", len(grid.components), 0)
expect("empty content_size is zero", grid.content_size(), (0, 0))

print()
print("max_rows raises instead of silently dropping the item")
capped = GridComponent(bounds=Rect(0, 0, 0, 0), max_columns=1, max_rows=2)
capped.add_item(square(10, 10))
capped.add_item(square(10, 10))
raises("third item on a 1x2 grid", PyoneerLayoutError,
       lambda: capped.add_item(square(10, 10)))
expect("the rejected item did not half-join", capped.count, 2)

# --------------------------------------------------------------------------
print()
print("inside a scrolling Panel")
# --------------------------------------------------------------------------
panel = prepared(Panel(bounds=Rect(0, 0, 200, 120), working_area=Rect(0, 0, 200, 120)))
grid = GridComponent(bounds=Rect(0, 0, 0, 0), max_columns=1, spacing=(0, 4))
for _ in range(12):
    grid.add_item(square(60, 20))
panel.attach_component("grid", grid)

# attach_component used to leave the parent unset (the bind_parent line was
# commented out). Every child the panel builds itself passes parent=self to its
# constructor, so the omission was invisible -- and a parentless component keeps
# world_bounds == local_bounds, draws in the wrong place and does not scroll,
# silently, because __update_world_bounds returns early when parent is None.
expect("attach_component sets the parent", grid.parent is panel, True)
expect("attached child is in the scroll content list", grid in panel.children, True)
expect("attached child is also bound", grid in panel.components.values(), True)

expect("grid is taller than the panel", grid.local_bounds.height > panel.world_bounds.height, True)
area = panel.fit_scroll_area()
expect("scroll area grew to the grid", area.height >= grid.local_bounds.height, True)
expect("vertical scrollbar measures it",
       panel.vertical_scroll.scrollable_bounds.height, area.height)
expect("vertical scrollbar is visible", panel.vertical_scroll.visible, True)

# Scrolling the panel must move the grid's ITEMS, via world_bounds inheritance.
item = grid.item(5)
before = item.world_bounds.y
panel.vertical_scroll.scroll_position = 40
panel.send_event_advanced(
    GameEventType.VIEWPORT_SCROLLED,
    PyoneerEvent(GameEventType.VIEWPORT_SCROLLED, sender=None, data={"x": 0, "y": 40}))
after = item.world_bounds.y
expect("grid offset by the scroll", tuple(grid.offset), (0, -40))
expect("a grid ITEM moved with it", after, before - 40)

print()
print("the grid actually draws")
blitpool.ORGANIZED_BLITS.clear()
event = PyoneerEvent(GameEventType.BLITS, sender=None,
                     data={"screen": pygame.display.get_surface().get_rect(),
                           "layer_depth": 100})
grid.core_render_blits(event)
tokens = sum(len(p) for d in blitpool.ORGANIZED_BLITS.values() for p in d.values())
expect("items queue blit tokens", tokens > 0, True)
# Fewer tokens than items is CORRECT, not a bug: the panel is 120px tall and
# each row is 20+4, so only ~6 rows are inside the viewport. The rest are culled
# by DrawComponent's clip against the panel. Assert the relationship rather than
# a bare count, so this stays meaningful if the fixture changes.
expect("fewer tokens than items, because the rest are clipped away",
       0 < tokens < grid.count, True)
expect("culling was recorded", blitpool.BlitPool.culled() > 0, True)
print(f"       {tokens} tokens from {grid.count} items, "
      f"{blitpool.BlitPool.culled()} culled")
blitpool.ORGANIZED_BLITS.clear()

# --------------------------------------------------------------------------
print()
print("snapping: uniform cells give stable pixel <-> cell conversion")
# --------------------------------------------------------------------------
snap = GridComponent(bounds=Rect(0, 0, 0, 0), max_columns=4, max_rows=4,
                     cell_size=32, spacing=(4, 4), padding=(2, 2))
expect("cell_size makes it uniform", snap.uniform, True)
expect("step is cell + spacing", snap.cell_step(), (36, 36))
expect("cell (0,0) origin is the padding", tuple(snap.cell_origin(0, 0)), (2, 2))
expect("cell (2,1) origin", tuple(snap.cell_origin(2, 1)), (2 + 72, 2 + 36))
expect("cell (1,1) rect", snap.cell_rect(1, 1), Rect(38, 38, 32, 32))

expect("point inside cell (0,0)", tuple(snap.cell_at((5, 5))), (0, 0))
expect("point inside cell (1,0)", tuple(snap.cell_at((40, 5))), (1, 0))
expect("point inside cell (2,3)", tuple(snap.cell_at((2 + 72 + 5, 2 + 108 + 5))), (2, 3))
expect("exact cell origin lands in that cell", tuple(snap.cell_at((38, 38))), (1, 1))
expect("last pixel of a cell stays in it", tuple(snap.cell_at((2 + 31, 2 + 31))), (0, 0))
# The spacing gap has to belong to SOMETHING or a drag over it snaps nowhere.
# It is attributed to the preceding cell.
expect("a point in the spacing gap falls to the preceding cell",
       tuple(snap.cell_at((34, 34))), (0, 0))

expect("above/left of the grid is outside", snap.cell_at((-5, -5)), None)
expect("past max_columns is outside", snap.cell_at((2 + 4 * 36 + 5, 5)), None)
expect("clamp pulls a negative point to (0,0)",
       tuple(snap.cell_at((-99, -99), clamp=True)), (0, 0))
expect("clamp pulls an overshoot to the last cell",
       tuple(snap.cell_at((9999, 9999), clamp=True)), (3, 3))

print()
print("measured cells refuse to pretend they have a single step")
measured = GridComponent(bounds=Rect(0, 0, 0, 0), max_columns=2)
measured.add_item(square(80, 24))
measured.add_item(square(50, 30))
expect("not uniform", measured.uniform, False)
raises("cell_step() on a measured grid", PyoneerLayoutError, measured.cell_step)
expect("cell_at still answers in measured mode",
       tuple(measured.cell_at((85, 5))), (1, 0))

print()
print("snap() places, moves, and reports collisions")
board = GridComponent(bounds=Rect(0, 0, 0, 0), max_columns=4, max_rows=4,
                      cell_size=32, spacing=(4, 4), padding=(2, 2))
piece = square(32, 32)
node = board.snap(piece, (40, 5))
expect("snapped into the cell under the point", (node.column, node.row), (1, 0))
expect("snapped item is bound", piece in board.components.values(), True)
# THE assertion that matters, and the one missing the first time round: the
# item must end up UNDER THE POINT. Comparing against cell_rect() only proved
# the layout agreed with itself -- and both sides were wrong, because measure()
# collapsed empty columns to 0 width while cell_at() computed from a fixed
# step. A drop at x=60 resolved to column 2 and landed at x=7.
expect("the item lands under the point that was dropped",
       piece.local_bounds.collidepoint((40, 5)), True)

print()
print("empty cells still occupy their slot, so gaps do not collapse")
sparse = GridComponent(bounds=Rect(0, 0, 0, 0), max_columns=6, cell_size=24,
                       spacing=(2, 2), padding=(3, 3))
far = square(24, 24)
sparse.snap(far, (60, 8))                      # column 2, with 0 and 1 empty
expect("column 2 origin honours the two empty columns",
       tuple(sparse.cell_origin(2, 0)), (3 + 2 * 26, 3))
expect("the item is under its drop point", far.local_bounds.collidepoint((60, 8)), True)
for point in [(5, 5), (30, 5), (60, 5), (5, 32), (60, 60), (120, 90)]:
    tile = square(24, 24)
    sparse.snap(tile, point, on_occupied="replace")
    if not tile.local_bounds.collidepoint(point):
        expect(f"drop at {point} lands under the cursor", False, True)
print("  ok   six scattered drops each landed under their cursor")

moved = board.snap(piece, (2 + 108 + 5, 2 + 72 + 5))
expect("snapping an existing item MOVES it", (moved.column, moved.row), (3, 2))
expect("it did not duplicate", board.count, 1)

blocker = square(32, 32)
raises("snapping onto an occupied cell", PyoneerLayoutError,
       lambda: board.snap(blocker, (2 + 108 + 5, 2 + 72 + 5)))
expect("occupancy query agrees", board.is_free(3, 2), False)
expect("free cell reports free", board.is_free(0, 0), True)
expect("occupant() finds it", board.occupant(3, 2) is piece, True)

same = board.snap(blocker, (2 + 108 + 5, 2 + 72 + 5), on_occupied="skip")
expect("skip returns the existing occupant's node", same.component is piece, True)
expect("skip changed nothing", board.count, 1)

board.snap(blocker, (2 + 108 + 5, 2 + 72 + 5), on_occupied="replace")
expect("replace evicts the old occupant", board.occupant(3, 2) is blocker, True)
expect("replace kept the count at one", board.count, 1)

print()
print("world_cell_at survives a scrolled panel")
host = prepared(Panel(bounds=Rect(200, 100, 200, 120), working_area=Rect(0, 0, 200, 120)))
tiles = GridComponent(bounds=Rect(0, 0, 0, 0), max_columns=4, cell_size=32, spacing=(0, 0))
# 40 tiles = 10 rows = 320px of content in a 120px panel, so there is genuinely
# room to scroll. An earlier version used 16 tiles (128px), only 8px taller than
# the panel -- Panel.__clamp_scroll capped the scroll at 8 and the assertion
# below failed for that reason rather than for a real one.
for _ in range(40):
    tiles.add_item(square(32, 32))
host.attach_component("tiles", tiles)
host.fit_scroll_area()

target = tiles.item(5)                        # cell (1,1)
point = target.world_bounds.center
expect("world_cell_at finds the cell under an unscrolled point",
       tuple(tiles.world_cell_at(point)), (1, 1))

host.vertical_scroll.scroll_position = 64
host.send_event_advanced(
    GameEventType.VIEWPORT_SCROLLED,
    PyoneerEvent(GameEventType.VIEWPORT_SCROLLED, sender=None, data={"x": 0, "y": 64}))
# Read the scroll the panel ACTUALLY applied rather than the one requested;
# clamping is legitimate and the assertion should not assume it did not happen.
applied = host.vertical_scroll.scroll_position
expect("the panel really scrolled", applied > 0, True)
moved_point = target.world_bounds.center
expect("the tile moved by the applied scroll", point[1] - moved_point[1], applied)
expect("world_cell_at still resolves the tile after scrolling",
       tuple(tiles.world_cell_at(moved_point)), (1, 1))
expect("the OLD screen point now resolves further down the grid",
       tuple(tiles.world_cell_at(point)), (1, 1 + applied // 32))

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
