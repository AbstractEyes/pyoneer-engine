"""Verify the generated sprites, mask palette and parallax background.

    .venv/Scripts/python.exe tools/check_art_sprites.py

No map, no engine boot, no art on disk. Runs on a bare clone.

WHAT A HUMAN CANNOT CHECK BY LOOKING
------------------------------------
Three of the four claims here are invisible in a picture.

A walk cycle whose four frames are the same drawing looks perfectly fine as
a sheet and looks broken the instant it moves, so every row is proved
PAIRWISE distinct and the passing frame is proved to ride higher than the two
contacts. A frame that overhangs its 44x64 cell by one pixel smears onto the
neighbouring column, and the sheet still looks right -- so every frame's
border ring is proved empty AND the frame is proved not to be empty, because
a generator that drew nothing would pass the first half perfectly.

The mask palette is read as NUMBERS by the engine and nothing renders it, so
its pixels can be wrong forever. Each of the seventeen tiles is probed on all
four edges for the bar colour and asserted to carry it EXACTLY when its mask
sets that bit -- 68 verdicts, half of them absences, because "the blocked
edge is marked" is satisfied completely by marking every edge.

The parallax band scrolls, so its right column meets its left. That join is
measured against the steepest column-to-column change the picture makes
anywhere else, which is a threshold the picture sets for itself rather than
a number somebody tuned until it went green.

AND ONE THAT IS THE LICENCE
---------------------------
`pygame.image.load` is made to RAISE while every sheet is built, then proved
to still raise, so the guard cannot pass by being switched off. That is
`docs/ASSETS.md`'s promise as an executable statement: these pixels come from
arithmetic, and a generator that quietly learned to open a file under
`data/graphics/` fails here instead of shipping somebody's RTP.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede the tools.art import)

import hashlib
import json
import os
import sys

import pygame

from scripts.core.collision_runtime import (
    BLOCK_DOWN,
    BLOCK_LEFT,
    BLOCK_RIGHT,
    BLOCK_UP,
    PASS_ALL,
    STAR,
)
from tools.art import collision as collision_art
from tools.art import parallax as parallax_art
from tools.art import sprites as sprite_art

pygame.init()

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_true(label, got):
    expect(label, bool(got), True)


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


ROOT = _bootstrap.REPO_ROOT
FW, FH = sprite_art.FRAME_W, sprite_art.FRAME_H


def blob(surface: pygame.Surface) -> bytes:
    return pygame.image.tostring(surface, "RGBA")


def digest(surface: pygame.Surface) -> str:
    """A short hash of a surface's pixels.

    Comparisons print what they compared, and a 44x64 frame's raw RGBA is
    11,264 bytes -- printed twice per verdict that is megabytes of noise
    nobody reads, hiding the one line that matters.
    """
    return hashlib.sha256(blob(surface)).hexdigest()[:12]


def frame(sheet: pygame.Surface, column: int, row: int) -> pygame.Surface:
    return sheet.subsurface(pygame.Rect(column * FW, row * FH, FW, FH))


def opaque_count(surface: pygame.Surface) -> int:
    width, height = surface.get_size()
    return sum(1 for y in range(height) for x in range(width)
               if surface.get_at((x, y))[3] > 0)


def border_opaque(surface: pygame.Surface) -> int:
    """Opaque pixels on the one-pixel ring around a frame."""
    width, height = surface.get_size()
    ring = [(x, 0) for x in range(width)]
    ring += [(x, height - 1) for x in range(width)]
    ring += [(0, y) for y in range(height)]
    ring += [(width - 1, y) for y in range(height)]
    return sum(1 for x, y in ring if surface.get_at((x, y))[3] > 0)


def top_opaque_row(surface: pygame.Surface) -> int:
    width, height = surface.get_size()
    for y in range(height):
        for x in range(width):
            if surface.get_at((x, y))[3] > 0:
                return y
    return height


def row_opaque(surface: pygame.Surface, y: int) -> int:
    return sum(1 for x in range(surface.get_width())
               if surface.get_at((x, y))[3] > 0)


TOPDOWN = sprite_art.character_sheet()
SIDESTEP = sprite_art.sidestep_sheet()
MASKS = collision_art.mask_palette()
SKY = parallax_art.parallax_sheet()

SHEET_NAMES = (("topdown", TOPDOWN), ("sidestep", SIDESTEP))
ROW_NAMES = {sprite_art.ROW_DOWN: "down", sprite_art.ROW_LEFT: "left",
             sprite_art.ROW_RIGHT: "right", sprite_art.ROW_UP: "up"}


# --------------------------------------------------------------------------
print("the sheets are exactly the geometry config/animations.json declares")
# --------------------------------------------------------------------------
# Read the config rather than restating it. `GameAnimation.frame_rect` reads
# x + index*width for a left-to-right sequence, so the extents below are the
# ones the engine will actually slice.
with open(os.path.join(ROOT, "config", "animations.json"), encoding="utf-8") as handle:
    entity = json.load(handle)["entity"]

rects: dict[str, list[tuple[int, int, int, int]]] = {}
for name, sequence in entity["sequences"].items():
    width, height = sequence["width"], sequence["height"]
    rects[name] = [(sequence["x"] + index * width, sequence["y"], width, height)
                   for index in range(len(sequence["frames"]))]

extent_x = max(x + w for boxes in rects.values() for x, _y, w, _h in boxes)
extent_y = max(y + h for boxes in rects.values() for _x, y, _w, h in boxes)
expect("the declared frame width", {w for boxes in rects.values()
                                    for *_r, w, _h in boxes}, {FW})
expect("the declared frame height", {h for boxes in rects.values()
                                     for *_r, _w, h in boxes}, {FH})
expect("the sheet is EXACTLY the declared extent", (extent_x, extent_y),
       (sprite_art.SHEET_W, sprite_art.SHEET_H))
for label, sheet in SHEET_NAMES:
    expect(f"{label}: sheet size", sheet.get_size(),
           (sprite_art.SHEET_W, sprite_art.SHEET_H))

# The module's own row and column constants against the config's offsets.
for name, row in (("idle_down", sprite_art.ROW_DOWN),
                  ("idle_left", sprite_art.ROW_LEFT),
                  ("idle_right", sprite_art.ROW_RIGHT),
                  ("idle_up", sprite_art.ROW_UP)):
    expect(f"{name} sits on row {row}", entity["sequences"][name]["y"], row * FH)
expect("every idle_* is on the module's idle column",
       {sequence["x"] for name, sequence in entity["sequences"].items()
        if name.startswith("idle_")}, {sprite_art.IDLE_COLUMN * FW})
expect("every walk_* starts at column 0",
       {sequence["x"] for name, sequence in entity["sequences"].items()
        if name.startswith("walk_")}, {0})
expect("a walk_* is the module's whole column count",
       {len(sequence["frames"]) for name, sequence in entity["sequences"].items()
        if name.startswith("walk_")}, {sprite_art.COLUMNS})

# The pack writes to the slot the config NAMES. A generated sheet at a path
# of the generator's own choosing leaves a fresh clone raising on the file
# the config actually points at, which is the failure docs/ASSETS.md
# describes second.
expect("the config's entity.file is a path the pack writes",
       entity["file"] in sprite_art.SHEETS, True)
side_on = [path for path in sprite_art.SHEETS if path != entity["file"]]
expect("the side-on sheet has a slot of its own", len(side_on), 1)
expect("which is not the four-direction one",
       side_on[0] == entity["file"], False)
expect("and the two slots are two different pictures",
       digest(TOPDOWN) == digest(SIDESTEP), False)


# --------------------------------------------------------------------------
print()
print("no frame is the same drawing twice, and none of them is empty")
# --------------------------------------------------------------------------
for label, sheet in SHEET_NAMES:
    for row in range(sprite_art.ROWS):
        frames = [blob(frame(sheet, column, row))
                  for column in range(sprite_art.COLUMNS)]
        expect(f"{label} {ROW_NAMES[row]} row: 4 distinct frames",
               len(set(frames)), sprite_art.COLUMNS)

for label, sheet in SHEET_NAMES:
    for row in range(sprite_art.ROWS):
        for column in range(sprite_art.COLUMNS):
            cell = frame(sheet, column, row)
            coverage = opaque_count(cell) / (FW * FH)
            # Both halves. Empty passes "does not overhang" perfectly; solid
            # passes "is not empty" perfectly. Neither is a character.
            expect_true(f"{label} r{row}c{column}: 15%-65% opaque "
                        f"({coverage:.0%})", 0.15 <= coverage <= 0.65)
            expect(f"{label} r{row}c{column}: border ring clear",
                   border_opaque(cell), 0)

# The passing frame is the only one off the ground line. Without it the four
# poses are four leg positions and the body slides rather than walks.
for label, sheet in SHEET_NAMES:
    row = sprite_art.ROW_RIGHT
    tops = [top_opaque_row(frame(sheet, column, row))
            for column in range(sprite_art.COLUMNS)]
    expect_true(f"{label}: the passing frame rides higher than the stand",
                tops[1] < tops[2])
    expect(f"{label}: both contacts sit on the stand's line",
           (tops[0], tops[3]), (tops[2], tops[2]))


# --------------------------------------------------------------------------
print()
print("the four directions are four directions")
# --------------------------------------------------------------------------
idles = {row: blob(frame(TOPDOWN, sprite_art.IDLE_COLUMN, row))
         for row in range(sprite_art.ROWS)}
expect("topdown: the four idle frames are all different",
       len(set(idles.values())), sprite_art.ROWS)

for column in range(sprite_art.COLUMNS):
    left = frame(TOPDOWN, column, sprite_art.ROW_LEFT)
    right = frame(TOPDOWN, column, sprite_art.ROW_RIGHT)
    expect(f"topdown c{column}: left is the mirror of right",
           digest(left), digest(pygame.transform.flip(right, True, False)))
# The mirror test is only worth anything if it can fail. Front and back are
# both symmetrical-ish and still must not pass it.
down = frame(TOPDOWN, sprite_art.IDLE_COLUMN, sprite_art.ROW_DOWN)
up = frame(TOPDOWN, sprite_art.IDLE_COLUMN, sprite_art.ROW_UP)
expect_true("topdown: down is NOT the mirror of up",
            blob(down) != blob(pygame.transform.flip(up, True, False)))


# --------------------------------------------------------------------------
print()
print("the side-on sheet answers the idle_down trap  (#TAG:art_side_down_row)")
# --------------------------------------------------------------------------
for column in range(sprite_art.COLUMNS):
    expect(f"sidestep c{column}: the down row IS the right row",
           digest(frame(SIDESTEP, column, sprite_art.ROW_DOWN)),
           digest(frame(SIDESTEP, column, sprite_art.ROW_RIGHT)))
    expect_true(f"sidestep c{column}: the up row is neither",
                blob(frame(SIDESTEP, column, sprite_art.ROW_UP))
                not in (blob(frame(SIDESTEP, column, sprite_art.ROW_DOWN)),
                        blob(frame(SIDESTEP, column, sprite_art.ROW_LEFT))))

# Airborne means the ground line is empty. Both halves in one pair: the
# grounded rows have to MARK it, or "no ink at row 62" is satisfied by a
# sheet with no shadows at all.
for column in range(sprite_art.COLUMNS):
    grounded = row_opaque(frame(SIDESTEP, column, sprite_art.ROW_RIGHT),
                          sprite_art.GROUND)
    airborne = row_opaque(frame(SIDESTEP, column, sprite_art.ROW_UP),
                          sprite_art.GROUND)
    expect_true(f"sidestep c{column}: a grounded frame marks row "
                f"{sprite_art.GROUND}", grounded > 0)
    expect(f"sidestep c{column}: an airborne frame leaves it empty",
           airborne, 0)


# --------------------------------------------------------------------------
print()
print("the mask palette is the vocabulary, tile for tile")
# --------------------------------------------------------------------------
tile = collision_art.TILE
expect("the sheet is STAR+1 tiles wide, derived not typed",
       MASKS.get_size(), ((STAR + 1) * tile, tile))
expect("which is the size a .tmx has to declare", MASKS.get_size(), (272, 16))
# Bounded by what is actually there: a sheet one tile short must report the
# shortfall above, not die inside subsurface with no verdict list at all.
present = min(STAR + 1, MASKS.get_width() // tile)
expect("every tile is a different glyph",
       len({blob(MASKS.subsurface(pygame.Rect(i * tile, 0, tile, tile)))
            for i in range(present)}), STAR + 1)

BAR = collision_art.BAR.base
INSET = 2
"""One pixel in from the plate's own border, and inside a bar of thickness
`max(2, tile // 5)` = 3 at this size."""

PROBES = {
    BLOCK_UP: [(x, INSET) for x in range(4, tile - 4)],
    BLOCK_DOWN: [(x, tile - 1 - INSET) for x in range(4, tile - 4)],
    BLOCK_LEFT: [(INSET, y) for y in range(4, tile - 4)],
    BLOCK_RIGHT: [(tile - 1 - INSET, y) for y in range(4, tile - 4)],
}
BIT_NAME = {BLOCK_UP: "up", BLOCK_DOWN: "down",
            BLOCK_LEFT: "left", BLOCK_RIGHT: "right"}

for mask in range(present):
    cell = MASKS.subsurface(pygame.Rect(mask * tile, 0, tile, tile))
    for bit, points in PROBES.items():
        inked = any(cell.get_at(point)[:3] == BAR for point in points)
        want = bool(mask & bit) and mask != STAR
        expect(f"mask {mask:2d}: {BIT_NAME[bit]:<5} edge marked", inked, want)

star_cell = MASKS.subsurface(
    pygame.Rect(min(STAR, present - 1) * tile, 0, tile, tile))
expect("star blocks nothing, so it carries no bar",
       any(star_cell.get_at((x, y))[:3] == BAR
           for x in range(tile) for y in range(tile)), False)
open_cell = MASKS.subsurface(pygame.Rect(PASS_ALL * tile, 0, tile, tile))
expect("and neither does the open tile",
       any(open_cell.get_at((x, y))[:3] == BAR
           for x in range(tile) for y in range(tile)), False)
expect_true("but the two are not the same empty square",
            blob(star_cell) != blob(open_cell))
expect_raises("a mask outside the vocabulary refuses to draw", ValueError,
              lambda: collision_art.glyph(STAR + 1))


# --------------------------------------------------------------------------
print()
print("the parallax band tiles horizontally and has a sky in it")
# --------------------------------------------------------------------------
width, height = SKY.get_size()
expect("the picture's size", (width, height),
       (parallax_art.WIDTH, parallax_art.HEIGHT))
expect("it cuts on the tile grid", (width % parallax_art.TILE,
                                    height % parallax_art.TILE), (0, 0))

columns = [[SKY.get_at((x, y)) for y in range(height)] for x in range(width)]
expect("a background has no holes in it",
       sorted({pixel[3] for column in columns for pixel in column}), [255])


def step(a, b) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


# ROW BY ROW, not averaged down the column. A column mean drowns a localised
# break: a ridge that stops being periodic mismatches over the thirty rows it
# occupies and is diluted to nothing by the two hundred rows of flat sky
# above it. Each row is compared against the worst step THAT ROW makes
# anywhere else, so the threshold is the picture's own and a flat row has to
# join perfectly.
worst_row, worst_wrap, worst_interior = -1, 0, 0
for y in range(height):
    wrap = step(columns[width - 1][y], columns[0][y])
    interior = max(step(columns[x - 1][y], columns[x][y])
                   for x in range(1, width))
    if wrap - interior > worst_wrap - worst_interior:
        worst_row, worst_wrap, worst_interior = y, wrap, interior
expect_true(f"every row joins no worse than its own worst interior step "
            f"(row {worst_row}: {worst_wrap} <= {worst_interior})",
            worst_wrap <= worst_interior)


# The rendered join is the end-to-end half. This is the other one: every
# shape function has to REPEAT at WIDTH, measured directly, because a break
# can hide behind a busy row -- a treeline whose period stops dividing the
# width mismatches by two pixels at the join and two pixels is exactly what
# the teeth themselves do everywhere else.
SAMPLE_X = list(range(0, parallax_art.WIDTH, 7))
expect("the ridge waves repeat at WIDTH",
       [x for x in SAMPLE_X
        if abs(parallax_art._wave(x, parallax_art.FAR_RIDGE)
               - parallax_art._wave(x + parallax_art.WIDTH,
                                    parallax_art.FAR_RIDGE)) > 1e-6
        or abs(parallax_art._wave(x, parallax_art.NEAR_RIDGE)
               - parallax_art._wave(x + parallax_art.WIDTH,
                                    parallax_art.NEAR_RIDGE)) > 1e-6], [])
# Every column for the treeline, not a stride: a stride that happens to be a
# multiple of the tooth period samples the same phase every time and sees a
# flat line where the picture has teeth.
expect("the treeline repeats at WIDTH",
       [x for x in range(parallax_art.WIDTH)
        if parallax_art._tooth(x) != parallax_art._tooth(x + parallax_art.WIDTH)],
       [])
expect("the clouds repeat at WIDTH",
       [(x, y) for x in SAMPLE_X for y in range(40, 112, 6)
        if parallax_art._in_cloud(x, y)
        != parallax_art._in_cloud(x + parallax_art.WIDTH, y)], [])
# A constant is periodic too, so each of the three has to actually vary or
# the three lines above prove nothing about this picture.
expect_true("and none of the three is a flat line",
            len({round(parallax_art._wave(x, parallax_art.FAR_RIDGE))
                 for x in SAMPLE_X}) > 3
            and len({parallax_art._tooth(x)
                     for x in range(parallax_art.WIDTH)}) > 1
            and len({parallax_art._in_cloud(x, 74) for x in SAMPLE_X}) == 2)


def band_luma(top: int, bottom: int) -> float:
    total = 0.0
    for y in range(top, bottom):
        for x in range(0, width, 4):
            pixel = SKY.get_at((x, y))
            total += 0.299 * pixel[0] + 0.587 * pixel[1] + 0.114 * pixel[2]
    return total / (((bottom - top) * width) / 4)


sky_band = band_luma(0, 32)
land_band = band_luma(height - 32, height)
horizon_band = band_luma(parallax_art.HORIZON - 16, parallax_art.HORIZON)
expect_true(f"the ground is darker than the sky "
            f"({land_band:.0f} < {sky_band:.0f})", land_band < sky_band - 20)
# A plain top-to-bottom gradient passes the line above and is not a sky. The
# horizon has to be the BRIGHTEST band, which only a lit horizon produces.
expect_true(f"and the horizon is brighter than the zenith "
            f"({horizon_band:.0f} > {sky_band:.0f})",
            horizon_band > sky_band + 20)
expect_true("the picture is not two colours in a trenchcoat",
            len({pixel[:3] for column in columns for pixel in column}) > 40)


# --------------------------------------------------------------------------
print()
print("every pixel came from arithmetic  (docs/ASSETS.md, as an assertion)")
# --------------------------------------------------------------------------
BUILDERS = {
    "topdown": sprite_art.character_sheet,
    "sidestep": sprite_art.sidestep_sheet,
    "masks": collision_art.mask_palette,
    "parallax": parallax_art.parallax_sheet,
}

real_load = pygame.image.load


def refuse(*args, **kwargs):
    raise AssertionError("a generator opened a file")


pygame.image.load = refuse
try:
    for name, builder in BUILDERS.items():
        try:
            builder()
            print(f"  ok   {name + ': reads no file':<62} built")
        except AssertionError:
            print(f"  FAIL {name + ': reads no file':<62} opened a file")
            failures.append(f"{name}: reads no file")
    # The guard has to still be armed, or every line above passed by being
    # switched off rather than by being true.
    expect_raises("the guard is armed while all four are built",
                  AssertionError, lambda: pygame.image.load("anything.png"))
finally:
    pygame.image.load = real_load

for name, builder in BUILDERS.items():
    expect(f"{name}: two builds, same bytes", digest(builder()),
           digest(builder()))


# --------------------------------------------------------------------------
print()
print("the pack writes to the slots the rest of the tree names")
# --------------------------------------------------------------------------
expect("the parallax sheet has one slot", len(parallax_art.SHEETS), 1)
expect("the mask palette has one slot", len(collision_art.SHEETS), 1)
try:
    from editor.ui.canvas import COLLISION_IMAGE
except ImportError as exc:
    print(f"  ..   {'the editor path join is not measured here':<62} "
          f"{type(exc).__name__}: PySide6 absent")
else:
    # `COLLISION_IMAGE` is relative to the .tmx that declares it, and every
    # map in this repository lives in data/maps/. If the editor moves the
    # sheet, the pack has to move with it or a bare clone writes the file
    # somewhere nothing will look.
    joined = os.path.normpath(os.path.join("data/maps", COLLISION_IMAGE))
    expect("the pack writes where editor.ui.canvas points",
           joined.replace(os.sep, "/") in collision_art.SHEETS, True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
