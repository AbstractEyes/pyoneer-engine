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
    footprint,
    grid_lines,
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

# --------------------------------------------------------------------------
print()
print("a brush FOOTPRINT is one number in cells, and it is not a pattern")
# --------------------------------------------------------------------------
# `footprint` is the only producer of a sized brush, so both halves of every
# rule about sizing are assertable here without a window.
single = Stamp.single(7)
grown, offset = footprint(single, 3)
expect("size 3 grows a single stamp to 3x3", (grown.width, grown.height), (3, 3))
expect("uniformly, so it has no phase to disagree about",
       set(grown.gids), {7})
expect("and it is centred on the cursor, not hung off its corner",
       offset, (-1, -1))
expect("size 1 hands the stamp straight back",
       footprint(single, 1), (single, (0, 0)))
expect("an even size cannot centre, so it biases up and left",
       footprint(single, 2)[1], (0, 0))
expect("size 5 offsets by two", footprint(single, 5)[1], (-2, -2))
# The rule that keeps this from changing anything that already works: a
# PATTERN picked out of the palette is its own footprint, at any size.
grid_pattern = Stamp.from_rows([[1, 2], [3, 4]])
expect("a picked pattern is returned untouched at size 4",
       footprint(grid_pattern, 4), (grid_pattern, (0, 0)))
expect_raises("a size below 1 raises rather than being quietly fixed",
              ValueError, lambda: footprint(single, 0))
expect_raises("and Stamp.uniform refuses it too", ValueError,
              lambda: Stamp.uniform(7, 0))

print()
print("an NxN brush paints exactly NxN cells; a 1x1 still paints exactly one")
stamp, anchor = footprint(Stamp.single(7), 3)
stroke = Stroke(Tool.BRUSH, stamp, BOUNDS, empty, anchor=anchor)
stroke.begin(4, 4)
expect("one click with size 3 writes 9 cells", len(stroke.edits()), 9)
expect("the block is centred on the clicked cell",
       sorted((x, y) for x, y, _g in stroke.edits()),
       [(x, y) for x in (3, 4, 5) for y in (3, 4, 5)])
stamp, anchor = footprint(Stamp.single(7), 1)
stroke = Stroke(Tool.BRUSH, stamp, BOUNDS, empty, anchor=anchor)
stroke.begin(4, 4)
expect("one click with size 1 writes exactly one cell, at the cursor",
       stroke.edits(), [(4, 4, 7)])

print()
print("the eraser takes the same footprint, in both directions")
stamp, anchor = footprint(Stamp.single(1), 3)
stroke = Stroke(Tool.ERASER, stamp, BOUNDS, solid, anchor=anchor)
stroke.begin(5, 5)
expect("size 3 clears 9 cells around the cursor",
       sorted((x, y) for x, y, _g in stroke.edits()),
       [(x, y) for x in (4, 5, 6) for y in (4, 5, 6)])
expect("and clears them, rather than writing the footprint's gid",
       {gid for _x, _y, gid in stroke.edits()}, {0})
stamp, anchor = footprint(Stamp.single(1), 1)
stroke = Stroke(Tool.ERASER, stamp, BOUNDS, solid, anchor=anchor)
stroke.begin(5, 5)
expect("size 1 clears exactly one", stroke.edits(), [(5, 5, 0)])

print()
print("one press-drag-release is ONE stroke at any size, with no cell twice")
stamp, anchor = footprint(Stamp.single(7), 3)
stroke = Stroke(Tool.BRUSH, stamp, BOUNDS, empty, anchor=anchor)
stroke.begin(4, 4)
stroke.extend(6, 4)
stroke.extend(8, 4)
positions = [(x, y) for x, y, _g in stroke.edits()]
# Columns 3..9 by rows 3..5: a 3-wide trail swept across five cells.
expect("a size-3 drag covers a 3-wide trail", len(positions), 21)
expect("every cell appears exactly once, so one commit is one write",
       len(positions), len(set(positions)))
expect("and it is still a single edit list ready for map.tile.set_many",
       len(edits_to_triples(stroke.edits())), 21)

print()
print("the anchor moves a FOOTPRINT, never a shape the tool defined itself")
# The other half of centring. A brush is centred on the cursor; a flood
# starts from the cell that was clicked and a dragged rectangle keeps the
# corners the author dragged. Offsetting either would move the shape.
row_region = reader({(x, 0): 1 for x in range(10)})
stroke = Stroke(Tool.FILL, Stamp.single(7), BOUNDS, row_region, anchor=(-1, -1))
stroke.begin(5, 0)
expect("a flood fills the region under the CURSOR, offset or not",
       len(stroke.edits()), 10)
stroke = Stroke(Tool.FILLED_RECT, Stamp.single(7), BOUNDS, empty,
                anchor=(-1, -1))
stroke.begin(2, 2)
stroke.extend(4, 4)
expect("a dragged rectangle keeps the corners that were dragged",
       sorted((x, y) for x, y, _g in stroke.edits()),
       [(x, y) for x in (2, 3, 4) for y in (2, 3, 4)])

print()
print("the tools a size does NOT reach are proved inert, not just disabled")
# The load-bearing half. `uses_size` is only honest if the three tools it
# excludes really do ignore a footprint -- they read the stamp as a
# repeating pattern keyed on map coordinates, so a uniform NxN tiles to
# itself. If that ever stopped being true, greying the control would be
# hiding a feature rather than declining one.
expect("exactly three tools take a footprint",
       sorted(t.value for t in Tool if t.uses_size),
       ["autotile", "brush", "eraser"])
expect("uses_size is not a synonym for uses_stamp",
       sorted(t.value for t in Tool if t.uses_size != t.uses_stamp),
       ["autotile", "fill", "filled_rect", "rectangle"])
for inert in (Tool.FILLED_RECT, Tool.RECTANGLE, Tool.FILL):
    one = Stroke(inert, Stamp.single(7), BOUNDS, empty)
    one.begin(1, 1)
    one.extend(5, 4)
    many = Stroke(inert, Stamp.uniform(7, 3), BOUNDS, empty)
    many.begin(1, 1)
    many.extend(5, 4)
    expect(f"{inert.value}: a 3x3 footprint changes nothing at all",
           (sorted(many.edits()) == sorted(one.edits()), len(one.edits()) > 0),
           (True, True))
    expect(f"{inert.value}: and it is declared as taking no size",
           inert.uses_size, False)

# --------------------------------------------------------------------------
print()
print("the displayed grid may SKIP boundaries and may never invent one")
# --------------------------------------------------------------------------
expect("step 1 draws every boundary of a 10-cell run",
       grid_lines(10, 1), list(range(11)))
expect("step 4 draws every fourth, and still closes the far edge",
       grid_lines(10, 4), [0, 4, 8, 10])
expect("a step that divides exactly does not repeat the last line",
       grid_lines(8, 4), [0, 4, 8])
expect("a step larger than the map is just the two edges",
       grid_lines(3, 8), [0, 3])
expect("a zero-cell run is one line, not an index error",
       grid_lines(0, 4), [0])
# THE HONESTY INVARIANT, both halves. Every line drawn at any step is a real
# cell boundary -- a subset of the step-1 set, never a superset. A grid finer
# than the addressable cell would show the author boundaries no click can
# land on, and `cell_at` divides by the paint unit regardless of what is
# drawn, so the lie would be permanent.
for step in (1, 2, 3, 4, 8, 16):
    lines = grid_lines(37, step)
    expect(f"step {step}: every line is a real boundary",
           set(lines) <= set(range(38)), True)
    expect(f"step {step}: and the map's own edges are always drawn",
           (lines[0], lines[-1]), (0, 37))
expect("a coarser grid draws strictly fewer lines",
       len(grid_lines(37, 4)) < len(grid_lines(37, 1)), True)
expect_raises("a step below one raises rather than drawing nothing",
              ValueError, lambda: grid_lines(10, 0))

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
