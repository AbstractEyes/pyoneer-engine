"""Verify the generated tilesets: corner occupancy, containment, provenance.

WHAT A HUMAN CANNOT CHECK BY LOOKING
------------------------------------
An autotile sheet is thirteen shapes at thirteen coordinates, and every one
of the wrong arrangements still looks like grass. The failure only appears
when someone paints a seam, weeks later, in a map this suite may never see.

So this does not compare the sheet to a picture. For each of the thirteen
masks in `editor/core/autotile.py`'s QUADRANT table it goes to the quadrant
the TABLE names, probes the four corners of that 16px cell, and asserts the
occupancy the MASK claims:

    mask 0b0001 -- terrain in the bottom-right corner and NOWHERE else

Both halves, which is the point: a generator that filled every quadrant
solid would satisfy "terrain is present where the mask says" perfectly and
be completely useless. Across all 32 blocks that is 32 x 13 x 4 = 1,664
corner verdicts, and one wrong offset moves at least four of them.

THE OTHER TWO CLAIMS
--------------------
Containment: every opaque pixel on the clutter sheet lies inside a cell some
item declared. A prop that overhangs by one pixel smears onto an unrelated
gid, and nothing about the sheet looks wrong.

Provenance: `pygame.image.load` is made to RAISE while both sheets are
built. That is the licence promise from `docs/ASSETS.md` as an executable
statement -- these pixels come from arithmetic, and a generator that quietly
learned to open a file under `data/graphics/` would fail here rather than
ship somebody's RTP through the back door.

    .venv/Scripts/python.exe tools/check_art_tilesets.py

No map, no engine boot, no art on disk. Runs on a bare clone.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede the tools.art import)

import hashlib
import os
import shutil
import sys
import tempfile

import pygame

from editor.core.autotile import (
    BOTTOM_LEFT,
    BOTTOM_RIGHT,
    DIAGONALS,
    EMPTY,
    FULL,
    QUADRANT,
    TOP_LEFT,
    TOP_RIGHT,
    TerrainSet,
    block_origins,
)
from tools.art import write_sheets
from tools.art import terrain as terrain_art
from tools.art import tiles as tiles_art
from tools.art.palette import Ramp, noise, ramp

pygame.init()

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception_type, fn):
    try:
        fn()
    except exception_type as exc:
        print(f"  ok   {label:<62} raised {type(exc).__name__}")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<62} raised {type(exc).__name__}, wanted "
              f"{exception_type.__name__}")
        failures.append(label)
        return
    print(f"  FAIL {label:<62} did not raise")
    failures.append(label)


TILE = terrain_art.TILE
PROBE = 4
"""How much of a corner to read.

One pixel would be a coin toss on a rounded edge and half the cell would
prove nothing. Four is decisive by construction: the boundary is a circle of
radius 8 centred on the corner, so a 4x4 patch at a corner is either wholly
inside the mass or at least 5px clear of it.
"""

CORNER_OFFSET = {
    TOP_LEFT: (0, 0),
    TOP_RIGHT: (TILE - PROBE, 0),
    BOTTOM_LEFT: (0, TILE - PROBE),
    BOTTOM_RIGHT: (TILE - PROBE, TILE - PROBE),
}
CORNER_NAME = {TOP_LEFT: "top-left", TOP_RIGHT: "top-right",
               BOTTOM_LEFT: "bottom-left", BOTTOM_RIGHT: "bottom-right"}


def corner_opacity(sheet, block_index, column, row, bit):
    """How many of a corner patch's pixels are opaque, out of PROBE squared."""
    bx, by = (block_index % terrain_art.BLOCKS_ACROSS,
              block_index // terrain_art.BLOCKS_ACROSS)
    left = bx * terrain_art.BLOCK_WIDTH + column * TILE
    top = by * terrain_art.BLOCK_HEIGHT + row * TILE
    ox, oy = CORNER_OFFSET[bit]
    opaque = 0
    for dy in range(PROBE):
        for dx in range(PROBE):
            if sheet.get_at((left + ox + dx, top + oy + dy))[3] > 0:
                opaque += 1
    return opaque


# --------------------------------------------------------------------------
print("the terrain sheet is the geometry the editor reads")
# --------------------------------------------------------------------------
sheet = terrain_art.build_sheet()
expect("the sheet is the size a 4x6-quadrant block grid makes",
       sheet.get_size(), (terrain_art.SHEET_WIDTH, terrain_art.SHEET_HEIGHT))
expect("which is the 512x384 an A2 tileset declares",
       sheet.get_size(), (512, 384))
expect("one terrain per block", len(terrain_art.TERRAINS),
       terrain_art.BLOCKS_ACROSS * terrain_art.BLOCKS_DOWN)
expect("the editor finds exactly that many autotile groups in it",
       len(block_origins(1, terrain_art.SHEET_COLUMNS,
                         terrain_art.SHEET_TILES)),
       len(terrain_art.TERRAINS))
expect("every terrain name is distinct",
       len({t.name for t in terrain_art.TERRAINS}),
       len(terrain_art.TERRAINS))

# --------------------------------------------------------------------------
print()
print("every mask in QUADRANT has terrain at exactly the corners it claims")
# --------------------------------------------------------------------------
verdicts = 0
wrong: list[str] = []
for block_index in range(len(terrain_art.TERRAINS)):
    name = terrain_art.TERRAINS[block_index].name
    for mask, (column, row) in sorted(QUADRANT.items()):
        for bit in (TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT):
            opaque = corner_opacity(sheet, block_index, column, row, bit)
            wanted = PROBE * PROBE if mask & bit else 0
            verdicts += 1
            if opaque != wanted:
                wrong.append(
                    f"{name} mask {mask:04b} at column {column} row {row}: "
                    f"its {CORNER_NAME[bit]} corner is {opaque}/{PROBE * PROBE} "
                    f"opaque, wanted {wanted}")
for line in wrong[:12]:
    print(f"       {line}")
if len(wrong) > 12:
    print(f"       ... and {len(wrong) - 12} more")
expect(f"corner verdicts over {len(terrain_art.TERRAINS)} terrains", verdicts,
       len(terrain_art.TERRAINS) * len(QUADRANT) * 4)
expect("corners disagreeing with their mask", len(wrong), 0)

# The other half of "the table is satisfied": a quadrant the table does NOT
# name must not be mistaken for one that it does. The fill mask sits at
# (1, 3); if the sheet were drawn one row up, (1, 2) would be solid -- and
# (1, 2) is the top-edge tile, whose top two corners are empty.
edge_column, edge_row = QUADRANT[0b0011]
expect("the tile above the fill is an EDGE, not more fill",
       corner_opacity(sheet, 0, edge_column, edge_row, TOP_LEFT), 0)
fill_column, fill_row = QUADRANT[FULL]
expect("and the fill tile itself is solid at every corner",
       [corner_opacity(sheet, 0, fill_column, fill_row, bit)
        for bit in (TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT)],
       [PROBE * PROBE] * 4)

# --------------------------------------------------------------------------
print()
print("adjacent tiles meet: a border reads its two corners and nothing else")
# --------------------------------------------------------------------------
# Corner occupancy alone does not make a sheet TILE. Two tiles join along a
# whole 16px edge, and the mass has to arrive at that edge in the same place
# from both sides or every join shows a step. The rule that guarantees it:
# along any border, the half nearest a corner is solid exactly when that
# corner is set -- so two tiles agreeing about a shared corner agree about
# the entire edge between them. Measured over every block, this is what a
# corner probe cannot see: a boundary curve of the wrong radius keeps all
# four corners correct and still steps at every seam.
BORDERS = (
    ("top", TOP_LEFT, TOP_RIGHT, lambda i: (i, 0)),
    ("bottom", BOTTOM_LEFT, BOTTOM_RIGHT, lambda i: (i, TILE - 1)),
    ("left", TOP_LEFT, BOTTOM_LEFT, lambda i: (0, i)),
    ("right", TOP_RIGHT, BOTTOM_RIGHT, lambda i: (TILE - 1, i)),
)
seams = 0
stepped: list[str] = []
for block_index in range(len(terrain_art.TERRAINS)):
    bx, by = (block_index % terrain_art.BLOCKS_ACROSS,
              block_index // terrain_art.BLOCKS_ACROSS)
    for mask, (column, row) in sorted(QUADRANT.items()):
        left = bx * terrain_art.BLOCK_WIDTH + column * TILE
        top = by * terrain_art.BLOCK_HEIGHT + row * TILE
        for side, near, far, at in BORDERS:
            for index in range(TILE):
                dx, dy = at(index)
                bit = near if index < TILE // 2 else far
                opaque = sheet.get_at((left + dx, top + dy))[3] > 0
                seams += 1
                if opaque != bool(mask & bit):
                    stepped.append(
                        f"{terrain_art.TERRAINS[block_index].name} mask "
                        f"{mask:04b} {side} border at {index}: "
                        f"{'opaque' if opaque else 'clear'}, wanted the "
                        f"opposite")
for line in stepped[:8]:
    print(f"       {line}")
if len(stepped) > 8:
    print(f"       ... and {len(stepped) - 8} more")
expect("border pixels measured", seams,
       len(terrain_art.TERRAINS) * len(QUADRANT) * 4 * TILE)
expect("border pixels that would step against a neighbour", len(stepped), 0)

# --------------------------------------------------------------------------
print()
print("the two diagonals stay blank, which is a policy and not a gap")
# --------------------------------------------------------------------------
drawn = {mask for row in terrain_art.BLOCK_MASKS for mask in row}
expect("no quadrant in the block draws a diagonal mask",
       sorted(drawn & set(DIAGONALS)), [])
expect("nor the empty mask", EMPTY in drawn, False)
for mask in DIAGONALS:
    expect_raises(f"covers() refuses the diagonal mask {mask:04b}",
                  ValueError, lambda m=mask: terrain_art.covers(m, 0, 0))
expect_raises("covers() refuses the empty mask", ValueError,
              lambda: terrain_art.covers(EMPTY, 0, 0))
expect_raises("covers() refuses a pixel outside the quadrant", ValueError,
              lambda: terrain_art.covers(FULL, TILE, 0))
# Every mask the editor CAN ask a TerrainSet for must be one this draws.
expect("every gid TerrainSet.table() names is inside the sheet",
       max(TerrainSet(1).table().values()) <= terrain_art.SHEET_TILES, True)

# --------------------------------------------------------------------------
print()
print("the layout guard fires when QUADRANT and the sheet disagree")
# --------------------------------------------------------------------------
# The guard is the only thing standing between a table edit and a sheet that
# paints garbage, so it is proved rather than trusted: move the fill mask in
# the live table and the generator must refuse to draw.
def _with_layout(layout):
    """Run the layout guard against a substitute block. Restores it."""
    keep = terrain_art.BLOCK_MASKS
    terrain_art.BLOCK_MASKS = layout
    try:
        terrain_art._verify_layout()
    finally:
        terrain_art.BLOCK_MASKS = keep


original = QUADRANT[FULL]
QUADRANT[FULL] = (0, 0)
try:
    expect_raises("_verify_layout refuses a table it does not match",
                  ValueError, terrain_art._verify_layout)
finally:
    QUADRANT[FULL] = original
expect_raises("_verify_layout refuses a mask no terrain draws", ValueError,
              lambda: _with_layout(((EMPTY,) * 4,) * 6))
expect("the real layout passes its own guard",
       terrain_art._verify_layout(), None)

# --------------------------------------------------------------------------
print()
print("thirty-two terrains, not one terrain thirty-two times")
# --------------------------------------------------------------------------
fills = []
for block_index in range(len(terrain_art.TERRAINS)):
    bx, by = (block_index % terrain_art.BLOCKS_ACROSS,
              block_index // terrain_art.BLOCKS_ACROSS)
    left = bx * terrain_art.BLOCK_WIDTH + fill_column * TILE
    top = by * terrain_art.BLOCK_HEIGHT + fill_row * TILE
    pixels = tuple(tuple(sheet.get_at((left + x, top + y)))
                   for y in range(TILE) for x in range(TILE))
    fills.append(pixels)
expect("no two blocks have the same fill tile", len(set(fills)), len(fills))

# A block being distinct is not the same as a block being textured. The fill
# quadrant has no edge in it, so whatever colours it carries came from the
# texture function -- and a terrain that declares one and renders as a flat
# swatch is a texture that silently stopped being called.
flat_declared = [t.name for t in terrain_art.TERRAINS if t.texture == "flat"]
untextured = [terrain_art.TERRAINS[i].name
              for i, pixels in enumerate(fills)
              if len(set(pixels)) == 1
              and terrain_art.TERRAINS[i].texture != "flat"]
patterned = [terrain_art.TERRAINS[i].name
             for i, pixels in enumerate(fills)
             if len(set(pixels)) > 1
             and terrain_art.TERRAINS[i].texture == "flat"]
expect("terrains declaring a texture and rendering flat", untextured, [])
expect("terrains declaring flat and rendering textured", patterned, [])
expect("and 'flat' is a real declaration somebody uses",
       len(flat_declared) > 0, True)

# --------------------------------------------------------------------------
print()
print("the clutter sheet keeps every tile inside its own cell")
# --------------------------------------------------------------------------
clutter = tiles_art.build_sheet()
expect("the clutter sheet is a 32x32 grid of 16px tiles", clutter.get_size(),
       (tiles_art.SHEET_WIDTH, tiles_art.SHEET_HEIGHT))
expect("which is the 512x512 the second tileset declares",
       clutter.get_size(), (512, 512))

claimed: set[tuple[int, int]] = set()
overlaps: list[str] = []
outside: list[str] = []
for place in tiles_art.PLACEMENTS:
    if (place.column + place.columns > tiles_art.SHEET_COLUMNS
            or place.row + place.rows > tiles_art.SHEET_ROWS):
        outside.append(place.name)
    for cy in range(place.row, place.row + place.rows):
        for cx in range(place.column, place.column + place.columns):
            if (cx, cy) in claimed:
                overlaps.append(f"{place.name} at cell ({cx}, {cy})")
            claimed.add((cx, cy))
expect("no placement runs off the sheet", outside, [])
expect("no two items claim the same cell", overlaps, [])

stray = 0
first_stray = None
for y in range(tiles_art.SHEET_HEIGHT):
    for x in range(tiles_art.SHEET_WIDTH):
        if clutter.get_at((x, y))[3] == 0:
            continue
        if (x // tiles_art.TILE, y // tiles_art.TILE) not in claimed:
            stray += 1
            if first_stray is None:
                first_stray = (x, y)
expect(f"opaque pixels outside a declared cell (first at {first_stray})",
       stray, 0)

silent = []
for place in tiles_art.PLACEMENTS:
    cell = place.rect()
    if not any(clutter.get_at((x, y))[3]
               for y in range(cell.top, cell.bottom)
               for x in range(cell.left, cell.right)):
        silent.append(place.name)
expect("declared items that drew nothing at all", silent, [])
expect("the sheet holds both singles and multi-tile props",
       sorted({(p.columns, p.rows) for p in tiles_art.PLACEMENTS})[-1] > (1, 1),
       True)
expect_raises("the packer refuses an item wider than the sheet", ValueError,
              lambda: tiles_art.layout(
                  [tiles_art.Item("too_wide", tiles_art.swatch("grass"),
                                  columns=tiles_art.SHEET_COLUMNS + 1)]))
expect_raises("and refuses more items than the sheet can hold", ValueError,
              lambda: tiles_art.layout(
                  [tiles_art.Item(f"x{i}", tiles_art.swatch("grass"), rows=2)
                   for i in range(tiles_art.SHEET_COLUMNS
                                  * tiles_art.SHEET_ROWS)]))

# --------------------------------------------------------------------------
print()
print("the palette raises rather than inventing a colour")
# --------------------------------------------------------------------------
expect_raises("an unknown material", KeyError, lambda: ramp("chartreuse"))
expect_raises("a shade outside the ramp", ValueError,
              lambda: ramp("grass").step(3))
grass = ramp("grass")
expect("a ramp runs dark to light",
       [sum(grass.step(i)) for i in (-2, -1, 0, 1, 2)]
       == sorted(sum(grass.step(i)) for i in (-2, -1, 0, 1, 2)), True)
expect("two materials do not collapse to the same shade",
       ramp("grass").base == ramp("water").base, False)
expect("noise is stable across calls", noise(3, 7, 1), noise(3, 7, 1))
expect("noise is not a constant",
       len({round(noise(x, 0, 0), 6) for x in range(64)}) > 32, True)
expect("Ramp is what the sprite half imports", isinstance(grass, Ramp), True)

# --------------------------------------------------------------------------
print()
print("nothing here reads an image file")
# --------------------------------------------------------------------------
# The licence claim, executed. If a builder ever learns to open a PNG under
# data/graphics/, this is where it stops being shippable art.
original_load = pygame.image.load


def _refuse(*args, **kwargs):
    raise AssertionError(f"a generator opened {args[:1]}")


pygame.image.load = _refuse
try:
    terrain_art.build_sheet()
    tiles_art.build_sheet()
    print("  ok   both sheets built with pygame.image.load disabled")
except AssertionError as exc:
    print(f"  FAIL a generator read a file: {exc}")
    failures.append("a generator read a file")
finally:
    pygame.image.load = original_load

# --------------------------------------------------------------------------
print()
print("building twice gives the same pixels")
# --------------------------------------------------------------------------
# A pack that differs per run cannot be compared, cached or blamed -- and a
# clone whose art depends on the day would drift `tools/smoke.py` for reasons
# that have nothing to do with the engine.
def digest(target):
    return hashlib.sha256(pygame.image.tostring(target, "RGBA")).hexdigest()[:16]


expect("the terrain sheet is reproducible",
       digest(terrain_art.build_sheet()), digest(sheet))
expect("the clutter sheet is reproducible",
       digest(tiles_art.build_sheet()), digest(clutter))
expect("and the two sheets are not the same picture",
       digest(sheet) == digest(clutter), False)

# --------------------------------------------------------------------------
print()
print("writing never clobbers art that is already there")
# --------------------------------------------------------------------------
# This is the property that keeps `tools/smoke.py` honest on a machine that
# HAS art: the generator provisions a missing file and leaves a present one
# alone, so running it changes nothing about what the engine renders.
scratch = tempfile.mkdtemp(prefix="pyoneer_art_")
try:
    sheets = dict(terrain_art.SHEETS)
    written, skipped = write_sheets(sheets, scratch)
    expect("a bare tree gets the sheet written", written, sorted(sheets))
    expect("and nothing is skipped", skipped, [])
    target = os.path.join(scratch, *next(iter(sheets)).split("/"))
    with open(target, "rb") as handle:
        before = hashlib.sha256(handle.read()).hexdigest()[:16]
    with open(target, "wb") as handle:
        handle.write(b"the author's own art")
    written, skipped = write_sheets(sheets, scratch)
    expect("a second run writes nothing", written, [])
    expect("and reports the skip", skipped, sorted(sheets))
    with open(target, "rb") as handle:
        expect("the file on disk is untouched", handle.read(),
               b"the author's own art")
    written, skipped = write_sheets(sheets, scratch, force=True)
    expect("--force is the only way past it", written, sorted(sheets))
    with open(target, "rb") as handle:
        expect("and it restores the generated bytes",
               hashlib.sha256(handle.read()).hexdigest()[:16], before)
finally:
    shutil.rmtree(scratch, ignore_errors=True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
