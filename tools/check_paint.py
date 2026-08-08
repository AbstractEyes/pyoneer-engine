"""Verify the tile-painting logic.

Pure functions over plain numbers, so every edge case is testable without a
window. That matters because the interesting bugs here are all geometric and
none of them are visible at a glance:

  * a fast mouse move skipping cells, painting a dotted line
  * an area tool stamping its whole pattern at every cell instead of tiling
    it across the area (found by this file, on the first run)
  * a stamp spilling past the layer edge
  * a drag tool accumulating instead of redefining, so the rectangle can
    only ever grow
  * a stroke committing one transaction per cell, making undo useless

No Qt, no pygame, no map. Runs on a bare clone.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import sys

from editor.core.paint import (
    Bounds,
    FloodTooLargeError,
    Stamp,
    Stroke,
    Tool,
    edits_to_triples,
    flood,
    flood_or_raise,
    line,
    place,
    rectangle,
)

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<54} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception_type, fn):
    try:
        fn()
    except exception_type:
        print(f"  ok   {label:<54} raised {exception_type.__name__}")
        return
    print(f"  FAIL {label:<54} did not raise {exception_type.__name__}")
    failures.append(label)


BOUNDS = Bounds(10, 10)


def reader(cells: dict[tuple[int, int], int]):
    return lambda x, y: cells.get((x, y), 0)


def rows_of(edits, y):
    return [gid for x, yy, gid in sorted(edits) if yy == y]


# --------------------------------------------------------------------------
print("stamps validate their own shape")
# --------------------------------------------------------------------------
expect("a single stamp is 1x1", Stamp.single(5).width, 1)
expect("from_rows measures itself", (Stamp.from_rows([[1, 2, 3], [4, 5, 6]]).width,
                                     Stamp.from_rows([[1, 2, 3], [4, 5, 6]]).height),
       (3, 2))
expect_raises("ragged rows are refused", ValueError,
              lambda: Stamp.from_rows([[1, 2], [3]]))
expect_raises("an empty stamp is refused", ValueError,
              lambda: Stamp.from_rows([]))
expect_raises("a gid count that disagrees with the size is refused", ValueError,
              lambda: Stamp(2, 2, (1, 2, 3)))
expect("gid_at tiles by modulo",
       [Stamp.from_rows([[1, 2], [3, 4]]).gid_at(x, 0) for x in range(5)],
       [1, 2, 1, 2, 1])

# --------------------------------------------------------------------------
print()
print("lines have no gaps, which is what a fast drag depends on")
# --------------------------------------------------------------------------
expect("a horizontal run is contiguous", line(0, 0, 4, 0),
       [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)])
expect("a diagonal is 6 cells, not 2", len(line(0, 0, 5, 5)), 6)
diagonal = line(0, 0, 5, 5)
gaps = [i for i in range(1, len(diagonal))
        if abs(diagonal[i][0] - diagonal[i - 1][0]) > 1
        or abs(diagonal[i][1] - diagonal[i - 1][1]) > 1]
expect("no step jumps more than one cell", gaps, [])
expect("a steep line is still contiguous", len(line(0, 0, 2, 9)), 10)
expect("a zero-length line is one cell", line(3, 3, 3, 3), [(3, 3)])

# --------------------------------------------------------------------------
print()
print("rectangles work from any corner")
# --------------------------------------------------------------------------
expect("filled 3x3", len(rectangle(0, 0, 2, 2, filled=True)), 9)
expect("dragged upward-left gives the same rect",
       sorted(rectangle(2, 2, 0, 0, filled=True)),
       sorted(rectangle(0, 0, 2, 2, filled=True)))
expect("an outline is the perimeter only",
       sorted(rectangle(0, 0, 2, 2, filled=False)),
       [(0, 0), (0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1), (2, 2)])
expect("a 1x1 outline is one cell, not four",
       rectangle(4, 4, 4, 4, filled=False), [(4, 4)])
expect("a 1-wide outline does not double its column",
       sorted(rectangle(1, 0, 1, 2, filled=False)),
       [(1, 0), (1, 1), (1, 2)])

# --------------------------------------------------------------------------
print()
print("placement clips to the layer instead of writing outside it")
# --------------------------------------------------------------------------
big = Stamp.from_rows([[1, 1, 1], [1, 1, 1]])
expect("a stamp at the far corner keeps one cell",
       place(big, 9, 9, BOUNDS), [(9, 9, 1)])
expect("a stamp fully outside places nothing",
       place(big, 50, 50, BOUNDS), [])
# `big` is 3 wide and 2 tall, so anchoring it at (-1, -1) puts its whole
# TOP row off the layer and clips its bottom row to two cells. Getting this
# wrong in the test is easy; getting it wrong in the code writes outside the
# grid.
expect("negative coordinates are clipped, not wrapped",
       sorted(place(big, -1, -1, BOUNDS)), [(0, 0, 1), (1, 0, 1)])
holed = Stamp(2, 2, (7, -1, -1, 7))
expect("a -1 gid means leave the cell alone",
       sorted(place(holed, 0, 0, BOUNDS)), [(0, 0, 7), (1, 1, 7)])

# --------------------------------------------------------------------------
print()
print("flood fill respects regions and refuses to truncate silently")
# --------------------------------------------------------------------------
cells = {(x, 0): 1 for x in range(10)}
read = reader(cells)
expect("it fills the matching row only", len(flood(read, BOUNDS, 0, 0)), 10)
expect("and the rest of the layer separately",
       len(flood(read, BOUNDS, 0, 1)), 90)
expect("a click outside the layer fills nothing",
       flood(read, BOUNDS, 99, 99), [])

walled = reader({(5, y): 1 for y in range(10)})
left = flood(walled, BOUNDS, 0, 0)
expect("a wall divides the region", len(left), 50)
expect("and the fill does not cross it",
       any(x > 4 for x, _y in left), False)

expect_raises("an over-large fill raises instead of truncating",
              FloodTooLargeError,
              lambda: flood_or_raise(reader({}), Bounds(400, 400), 0, 0,
                                     limit=1000))

# --------------------------------------------------------------------------
print()
print("a stroke is ONE transaction, not one per cell")
# --------------------------------------------------------------------------
empty = reader({})
stroke = Stroke(Tool.BRUSH, Stamp.single(5), BOUNDS, empty)
stroke.begin(0, 0)
stroke.extend(4, 0)
expect("dragging across five cells yields five edits", len(stroke.edits()), 5)
expect("all in one list ready for map.tile.set_many",
       edits_to_triples(stroke.edits())[0], [0, 0, 5])

print()
print("a stroke that changes nothing produces no edits at all")
stroke = Stroke(Tool.BRUSH, Stamp.single(0), BOUNDS, empty)
stroke.begin(2, 2)
stroke.extend(5, 2)
expect("painting 0 onto empty cells is a no-op", stroke.edits(), [])
expect("but the preview still shows where the brush went",
       len(stroke.preview()), 4)

print()
print("scrubbing back over a cell does not queue it twice")
stroke = Stroke(Tool.BRUSH, Stamp.single(9), BOUNDS, empty)
stroke.begin(3, 3)
stroke.extend(6, 3)
stroke.extend(3, 3)
positions = [(x, y) for x, y, _g in stroke.edits()]
expect("each cell appears once", len(positions), len(set(positions)))

# --------------------------------------------------------------------------
print()
print("area tools TILE the stamp; point tools ANCHOR it")
# --------------------------------------------------------------------------
# This is the bug this file was written to catch. A filled rectangle used to
# stamp the entire pattern at every cell of the rectangle, which spilled one
# row and one column past the drag and produced a smeared pattern.
pattern = Stamp.from_rows([[1, 2], [3, 4]])
stroke = Stroke(Tool.FILLED_RECT, pattern, BOUNDS, empty)
stroke.begin(0, 0)
stroke.extend(3, 1)
edits = stroke.edits()
expect("a 4x2 rectangle touches exactly 8 cells", len(edits), 8)
expect("the pattern tiles across the top row", rows_of(edits, 0), [1, 2, 1, 2])
expect("and the second row", rows_of(edits, 1), [3, 4, 3, 4])
expect("nothing spilled past the drag",
       max(y for _x, y, _g in edits), 1)

print()
print("tiling is aligned to the map, so two rectangles line up")
stroke = Stroke(Tool.FILLED_RECT, pattern, BOUNDS, empty)
stroke.begin(2, 2)
stroke.extend(5, 3)
expect("an offset rectangle keeps the same phase",
       rows_of(stroke.edits(), 2), [1, 2, 1, 2])

print()
print("a brush anchors the whole stamp under the cursor")
stroke = Stroke(Tool.BRUSH, pattern, BOUNDS, empty)
stroke.begin(0, 0)
expect("one click places all four cells", len(stroke.edits()), 4)

# --------------------------------------------------------------------------
print()
print("a drag tool redefines its shape rather than accumulating")
# --------------------------------------------------------------------------
stroke = Stroke(Tool.RECTANGLE, Stamp.single(9), BOUNDS, empty)
stroke.begin(0, 0)
stroke.extend(5, 5)
grew = len(stroke.edits())
stroke.extend(1, 1)
expect("dragging back shrinks the rectangle", len(stroke.edits()) < grew, True)
expect("to exactly the smaller outline",
       sorted((x, y) for x, y, _g in stroke.edits()),
       [(0, 0), (0, 1), (1, 0), (1, 1)])

print()
print("the eraser writes 0 over its footprint, area or point")
solid = reader({(x, y): 5 for x in range(10) for y in range(10)})
stroke = Stroke(Tool.ERASER, Stamp.from_rows([[1, 1], [1, 1]]), BOUNDS, solid)
stroke.begin(1, 1)
expect("a 2x2 eraser clears four cells",
       sorted(stroke.edits()),
       [(1, 1, 0), (1, 2, 0), (2, 1, 0), (2, 2, 0)])
stroke = Stroke(Tool.ERASER, Stamp.from_rows([[1, 1], [1, 1]]), BOUNDS, solid)
stroke.begin(0, 0)
stroke.extend(3, 0)
expect("an erasing rectangle clears the area, not a pattern",
       {gid for _x, _y, gid in stroke.edits()}, {0})

print()
print("the fill tool paints the region it found with the pattern")
region = reader({(x, 0): 1 for x in range(10)})
fresh = Stamp.from_rows([[7, 8], [7, 8]])
stroke = Stroke(Tool.FILL, fresh, BOUNDS, region)
stroke.begin(0, 0)
expect("it covers the whole matching row", len(stroke.edits()), 10)
expect("with the pattern, not one flat gid",
       rows_of(stroke.edits(), 0), [7, 8, 7, 8, 7, 8, 7, 8, 7, 8])
expect("and does not leak into the rest of the layer",
       max(y for _x, y, _g in stroke.edits()), 0)

# The no-change filter is not cosmetic. Painting a pattern whose values
# already match some cells must not queue those cells: a tmx write that
# re-stamps an unchanged gid is a diff with no content, and the whole point
# of the byte-exact writer is that an unchanged region produces no diff.
stroke = Stroke(Tool.FILL, pattern, BOUNDS, region)
stroke.begin(0, 0)
expect("cells that already hold the pattern value are dropped",
       len(stroke.edits()), 5)
expect("the preview still shows the full region it covered",
       len(stroke.preview()), 10)

# --------------------------------------------------------------------------
print()
print("tool metadata is coherent")
# --------------------------------------------------------------------------
expect("only rectangles are drag-shaped",
       sorted(t.value for t in Tool if t.is_drag),
       ["filled_rect", "rectangle"])
expect("only the picker does not edit",
       sorted(t.value for t in Tool if not t.edits), ["picker"])
expect("every tool has a label",
       [t for t in Tool if not t.label], [])

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
