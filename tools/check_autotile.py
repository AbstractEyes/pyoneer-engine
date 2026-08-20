"""Verify directional fill (autotile).

The table in editor/core/autotile.py was derived from the pixels of
TileA2.png, not from memory, and this pins it: if any offset drifts, the
concrete gids asserted here stop matching and the failure names which mask.

The geometric assertions matter more than the table, though. Autotiling
fails in ways that look almost right:

  * editing ONE corner must re-tile FOUR cells, or the seam against
    existing terrain never updates
  * a painted region must be one cell LARGER than its corner block, because
    terrain lives on the lattice and tiles live on cells
  * the two diagonal masks have no art in any RPG Maker sheet and must hit
    a stated policy rather than a KeyError mid-stroke
  * recovering terrain from gids is lossy, and the collisions have to
    resolve deliberately

No Qt, no pygame, no map. Runs on a bare clone.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import sys

from editor.core.autotile import (
    BOTTOM_LEFT,
    BOTTOM_RIGHT,
    Bounds,
    Diagonal,
    FULL,
    PyoneerAutotileError,
    QUADRANT,
    TOP_LEFT,
    TOP_RIGHT,
    TerrainSet,
    block_origins,
    cells_touching,
    corner_field,
    mask_at,
    origin_for_gid,
    paint,
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
    print(f"  FAIL {label:<54} did not raise")
    failures.append(label)


GRASS = TerrainSet(origin=1, columns=32, name="grass")


def field_reader(cells: dict):
    return lambda x, y: cells.get((x, y), 0)


def render(cells, bounds):
    return [[cells.get((x, y), 0) for x in range(bounds.width)]
            for y in range(bounds.height)]


# --------------------------------------------------------------------------
print("the corner table matches the gids read off TileA2.png")
# --------------------------------------------------------------------------
# Verified against the actual sheet: block (0,0) of TileA2, firstgid 1.
VERIFIED = {0b1111: 98, 0b0111: 3, 0b1011: 4, 0b1101: 35, 0b1110: 36,
            0b0011: 66, 0b1100: 162, 0b0101: 97, 0b1010: 100,
            0b0001: 65, 0b0010: 68, 0b0100: 161, 0b1000: 164}
expect("all 13 masks resolve to the measured gids", GRASS.table(), VERIFIED)
expect("13 masks have art, 3 do not", len(QUADRANT), 13)
expect("the missing ones are 0000 and the two diagonals",
       sorted(set(range(16)) - set(QUADRANT)), [0b0000, 0b0110, 0b1001])

expect("a second terrain is the same table shifted",
       TerrainSet(origin=5, columns=32).table()[FULL], 102)
expect("column count changes the stride",
       TerrainSet(origin=1, columns=16).table()[FULL], 1 + 3 * 16 + 1)

expect_raises("a zero origin is refused", ValueError,
              lambda: TerrainSet(origin=0))
expect_raises("too few columns for a block is refused", ValueError,
              lambda: TerrainSet(origin=1, columns=2))

print()
print("a sheet's terrains are enumerable, and any gid names its own")
origins = block_origins(1, 32, 768)
expect("TileA2 holds 32 autotile groups", len(origins), 32)
expect("the first row of blocks", origins[:8], [1, 5, 9, 13, 17, 21, 25, 29])
expect("the second row starts a block-height down", origins[8], 193)
expect("a fill gid names its own block", origin_for_gid(98, 1, 32), 1)
expect("so does a corner gid", origin_for_gid(65, 1, 32), 1)
expect("a gid in another block names that one", origin_for_gid(200, 1, 32), 197)
expect_raises("a gid below the tileset is refused", ValueError,
              lambda: origin_for_gid(0, 1, 32))

# --------------------------------------------------------------------------
print()
print("painting a rectangle produces corners, edges and fill")
# --------------------------------------------------------------------------
bounds = Bounds(10, 8)
cells: dict = {}
read = field_reader(cells)
corners = {(x, y) for x in range(2, 7) for y in range(2, 6)}
edits, field = paint(read, bounds, GRASS, corners)
for x, y, gid in edits:
    cells[(x, y)] = gid

# 5x4 corners bound a 4x3 interior, and every neighbouring cell is affected,
# so the tiled result is 6x5. If this ever comes back as 4x3, the half-cell
# trap has been reintroduced.
expect("a 5x4 corner block tiles 6x5 cells", len(edits), 30)
grid = render(cells, bounds)
expect("top-left is a convex corner", grid[1][1], 65)
expect("top-right is the other convex corner", grid[1][6], 68)
expect("bottom-left convex", grid[5][1], 161)
expect("bottom-right convex", grid[5][6], 164)
expect("the top edge is one tile", set(grid[1][2:6]), {66})
expect("the bottom edge is another", set(grid[5][2:6]), {162})
expect("the left edge", {grid[y][1] for y in range(2, 5)}, {97})
expect("the right edge", {grid[y][6] for y in range(2, 5)}, {100})
expect("the interior is fill", {grid[y][x] for y in range(2, 5)
                                for x in range(2, 6)}, {98})
expect("and nothing outside was touched", grid[0], [0] * 10)

# --------------------------------------------------------------------------
print()
print("an L-shape produces a CONCAVE corner, which is the whole point")
# --------------------------------------------------------------------------
cells = {}
read = field_reader(cells)
block = {(x, y) for x in range(1, 6) for y in range(1, 4)}
block |= {(x, y) for x in range(1, 4) for y in range(4, 7)}
edits, field = paint(read, bounds, GRASS, block)
for x, y, gid in edits:
    cells[(x, y)] = gid
grid = render(cells, bounds)
concave = {v for row in grid for v in row} & {3, 4, 35, 36}
expect("at least one inner-corner tile was used", bool(concave), True)
# Derive the cell rather than guessing it. The wide arm covers corners
# x 1..5 at y<=3; the narrow arm covers x 1..3 at y>=4. So cell (3,3) has
# corners (3,3),(4,3),(3,4) set and (4,4) clear -> mask 1110 -> gid 36.
# The cell to its right, (4,3), has only its top two corners and is
# correctly a bottom EDGE, not a corner.
expect("the inner corner sits inside the elbow", grid[3][3], 36)
expect("the cell beyond the elbow is a plain bottom edge", grid[3][4], 162)

# --------------------------------------------------------------------------
print()
print("editing ONE corner re-tiles FOUR cells, not one")
# --------------------------------------------------------------------------
expect("a lone corner touches four cells",
       len(cells_touching([(4, 4)], bounds)), 4)
expect("a corner on the edge of the map touches two",
       len(cells_touching([(0, 4)], bounds)), 2)
expect("a corner at the origin touches one",
       len(cells_touching([(0, 0)], bounds)), 1)

cells = {}
read = field_reader(cells)
edits, field = paint(read, bounds, GRASS, [(4, 4)])
expect("painting a single corner emits four edits", len(edits), 4)
expect("each a different convex corner",
       sorted(gid for _x, _y, gid in edits), [65, 68, 161, 164])

# --------------------------------------------------------------------------
print()
print("erasing a corner re-tiles its neighbours too")
# --------------------------------------------------------------------------
cells = {}
read = field_reader(cells)
edits, field = paint(read, bounds, GRASS,
                     {(x, y) for x in range(2, 7) for y in range(2, 6)})
for x, y, gid in edits:
    cells[(x, y)] = gid
before = dict(cells)
edits, field = paint(read, bounds, GRASS, [(4, 4)], erase=True, field=field)
expect("erasing an interior corner changes four cells", len(edits), 4)
expect("and they become inner corners, not holes",
       sorted(gid for _x, _y, gid in edits), [3, 4, 35, 36])

# --------------------------------------------------------------------------
print()
print("terrain is recovered from the tiles, because nothing stores it")
# --------------------------------------------------------------------------
cells = {}
read = field_reader(cells)
edits, painted = paint(read, bounds, GRASS,
                       {(x, y) for x in range(2, 7) for y in range(2, 6)})
for x, y, gid in edits:
    cells[(x, y)] = gid
recovered = corner_field(read, bounds, GRASS)
expect("re-reading the layer recovers the same corner field",
       recovered, painted)
expect("a mask read back matches what was drawn",
       mask_at(recovered, 3, 3), FULL)

print()
print("an unrelated gid is simply not this terrain")
expect("a foreign gid contributes no corners",
       corner_field(field_reader({(0, 0): 1500}), bounds, GRASS), set())
expect("and neither does an empty cell",
       corner_field(field_reader({}), bounds, GRASS), set())

print()
print("the reverse map resolves its two inherent collisions toward more terrain")
reverse = GRASS.reverse()
expect("the fill gid reads back as full", reverse[98], FULL)
expect("a convex gid reads back as one corner", reverse[65], BOTTOM_RIGHT)
expect("every table gid is reversible",
       sorted(reverse) == sorted(set(GRASS.table().values())), True)

# --------------------------------------------------------------------------
print()
print("the two diagonal masks hit a stated policy, never a KeyError")
# --------------------------------------------------------------------------
diagonal = TOP_LEFT | BOTTOM_RIGHT
merge = TerrainSet(origin=1, diagonal=Diagonal.MERGE)
split = TerrainSet(origin=1, diagonal=Diagonal.SPLIT)
strict = TerrainSet(origin=1, diagonal=Diagonal.RAISE)
expect("MERGE draws it solid", merge.gid_for(diagonal), 98)
expect("SPLIT draws nothing", split.gid_for(diagonal), None)
expect_raises("RAISE says so out loud", PyoneerAutotileError,
              lambda: strict.gid_for(diagonal))
expect("the other diagonal behaves the same",
       merge.gid_for(TOP_RIGHT | BOTTOM_LEFT), 98)
expect("an empty mask never draws", merge.gid_for(0), None)

# --------------------------------------------------------------------------
print()
print("clearing is opt-in, so painting does not erase unrelated decoration")
# --------------------------------------------------------------------------
cells = {(x, y): 1500 for x in range(10) for y in range(8)}
read = field_reader(cells)
edits, field = paint(read, bounds, GRASS, [(4, 4)])
expect("only the four terrain cells change", len(edits), 4)
expect("the decoration outside is untouched", read(0, 0), 1500)

# clear_gid only bites when a cell LOSES its last corner, which happens on
# erase -- every cell touched by an add necessarily has at least one corner.
for x, y, gid in edits:
    cells[(x, y)] = gid
edits, field = paint(read, bounds, GRASS, [(4, 4)], erase=True,
                     field=field, clear_gid=0)
expect("erasing with clear_gid blanks the cells that lost their terrain",
       sorted(gid for _x, _y, gid in edits), [0, 0, 0, 0])

cells = {(x, y): 1500 for x in range(10) for y in range(8)}
read = field_reader(cells)
edits, field = paint(read, bounds, GRASS, [(4, 4)])
for x, y, gid in edits:
    cells[(x, y)] = gid
edits, field = paint(read, bounds, GRASS, [(4, 4)], erase=True, field=field)
expect("without clear_gid the old decoration is simply left in place",
       edits, [])

# --------------------------------------------------------------------------
print()
print("painting the same terrain twice is a no-op")
# --------------------------------------------------------------------------
cells = {}
read = field_reader(cells)
edits, field = paint(read, bounds, GRASS, [(4, 4)])
for x, y, gid in edits:
    cells[(x, y)] = gid
again, field = paint(read, bounds, GRASS, [(4, 4)], field=field)
expect("the second pass emits nothing", again, [])

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
