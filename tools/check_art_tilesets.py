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

THE OTHER TWO AXES
------------------
A terrain is a colour, a texture and a FORM -- the silhouette its corners
draw -- and every one of the three has one rule it may not break.

FORM. A boundary that crosses a shared edge anywhere but its midpoint steps
at every join, looks perfectly well on the sheet, and surfaces in a painted
map. So every form in the vocabulary is drawn against every mask in the
table and read back off the PIXELS, which is 5 x 13 x 4 x 16 = 4,160 border
verdicts on top of the corner ones. Then the OTHER half, which is the one
that was missing: five forms that all drew the same shape would satisfy the
midpoint rule perfectly and cost a whole axis, so their drawn silhouettes
are measured against each other and held `FORM_DISTANCE` apart. The
assertion this replaced said only that no two were byte-identical -- and
passed a vocabulary whose closest pair differed by TWO pixels.

TEXTURE. `quadrant` draws one 16px cell and the renderer repeats it, so a
texture whose own rhythm does not fit in 16 pixels restarts at every cell
border and rules a grid over the field. Every structured texture is drawn in
tile-local and in global coordinates and the two have to agree exactly; the
hashed ones are exempt BY NAME, which is a decision rather than an omission.

COLOUR. Two rules, both over every pair of the thirty-two rather than over
the pairs that happen to touch: no two blocks may look alike in CIELAB on
the field they DRAW, and no block marked `hazard` may come close to a
walkable one under either simulated red-green dichromacy. The second is
there because this sheet once put `grass` 4.0 from `lava` for a protanope.

Every one of those guards is provoked rather than trusted, each with the
mutation that actually shipped.

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

import ast
import dataclasses
import hashlib
from fractions import Fraction
import inspect
import itertools
import os
import textwrap
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
from scripts.core.art import shipped_relative
from tools.art import write_sheets
from tools.art import palette as palette_art
from tools.art import terrain as terrain_art
from tools.art import tiles as tiles_art
from tools.art.palette import (DICHROMACIES, Ramp, dichromat,
                               distance, fall as palette_fall, luminance,
                               NEAR_FACE as palette_NEAR_FACE,
                               lowangle as palette_lowangle,
                               mass as palette_mass, mix as palette_mix,
                               noise, ramp)

pygame.init()

failures: list[str] = []

probe_grey = ramp("stone")
"""The one material every vocabulary rule is measured on, so a texture is
judged on its structure rather than on the ramp it happens to sit on."""


def _hand_lit_grout(material, x, y, salt):
    """`grout` as it was written before `_joint`: its own direction, by hand.

    The joint at index 0 and the lit wall at index 1, which happens to agree
    with `SHADOW_OFFSET` and does not read it -- so reversing the constant
    leaves it exactly where it was, and a sheet whose other textures turned
    round would have this one facing the wrong way with nothing to say so.
    """
    if x % 8 == 0 or y % 8 == 0:
        return material.shadow
    if x % 8 == 1 or y % 8 == 1:
        return material.light
    return material.base


def _raises(exception_type, fn) -> bool:
    """Did `fn` raise that? For an assertion that wants a boolean rather than
    a pass/fail line of its own."""
    try:
        fn()
    except exception_type:
        return True
    return False


def _with_face_drop(fn, *args):
    """Run `fn` with the NEAR FACE flattened to nothing, and the rim left
    alone. `_with_rim_drop` moves both, so it can only ever provoke whichever
    of the two rules runs first."""
    import tools.art.palette as palette_module
    kept = palette_module.face
    palette_module.face = lambda colour: colour
    try:
        return fn(*args)
    finally:
        palette_module.face = kept


def _with_rim_drop(value, fn, *args):
    """Run `fn` with `palette.RIM_DROP` moved. Restores it.

    Reached through `tools.art.palette`, because `terrain` imported the name
    and `overhead` reads the one in its own module.
    """
    import tools.art.palette as palette_module
    kept = palette_module.RIM_DROP
    palette_module.RIM_DROP = value
    terrain_art.RIM_DROP = value
    try:
        return fn(*args)
    finally:
        palette_module.RIM_DROP = kept
        terrain_art.RIM_DROP = kept


def _with_cracks(lines):
    """Run the crack guard over a different set of splits. Restores them."""
    kept_lines, kept_set = terrain_art.CRACK_LINES, terrain_art._CRACK
    terrain_art.CRACK_LINES = tuple(lines)
    terrain_art._CRACK = frozenset(lines)
    try:
        return terrain_art._verify_cracks()
    finally:
        terrain_art.CRACK_LINES, terrain_art._CRACK = kept_lines, kept_set


def _banded(material, x, y, salt):
    """A horizontal band every four rows: the shape the author named.

    Registered in the live vocabulary so the isotropy guard can be pointed
    at it by name, which is how every other view rule is provoked.
    """
    return material.shadow if y % 4 == 0 else material.base


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


def digest_surface(target):
    """The bytes of a surface, for comparing two drawings exactly."""
    return hashlib.sha256(pygame.image.tostring(target, "RGBA")).hexdigest()


PROBE = 4
"""How much of a corner to read.

One pixel would be a coin toss on a rounded edge and half the cell would
prove nothing. Four is decisive by construction, for EVERY form and not just
the circle: `terrain.CORNER_CLEAR` is this number, and `_verify_forms`
refuses at import any form that cuts into that patch. So a 4x4 patch at a
corner is either wholly inside the mass or wholly clear of it.
"""
assert PROBE == terrain_art.CORNER_CLEAR, (
    "the generator and this check disagree about how much of a corner is "
    "guaranteed solid, so the probe below is measuring something nothing "
    "promises")

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
ONE = Fraction(1)
HALF = Fraction(1, 2)

VIEWS = sorted(terrain_art.VIEWS)
SHEETS_BY_VIEW = {view: terrain_art.build_sheet(view) for view in VIEWS}
TABLES = {view: terrain_art.table_for(view) for view in VIEWS}
sheet = SHEETS_BY_VIEW[terrain_art.DEFAULT_VIEW]

# EVERY geometric assertion below walks BOTH sheets, not the one it was
# written for. A second sheet is the exact shape of CLAUDE.md's sibling
# warning -- a rule that judges the route that shipped while its twin grows
# beside it unchecked -- so the loops take the view rather than reading
# `TERRAINS`, and a third view would be covered by adding one table.
expect("this check knows about every view the generator draws",
       VIEWS, sorted(terrain_art.TABLES))
for view in VIEWS:
    expect(f"[{view}] the sheet is the size a 4x6-quadrant block grid makes",
           SHEETS_BY_VIEW[view].get_size(),
           (terrain_art.SHEET_WIDTH, terrain_art.SHEET_HEIGHT))
    expect(f"[{view}] which is the 512x384 an A2 tileset declares",
           SHEETS_BY_VIEW[view].get_size(), (512, 384))
    expect(f"[{view}] one terrain per block", len(TABLES[view]),
           terrain_art.BLOCKS_ACROSS * terrain_art.BLOCKS_DOWN)
    expect(f"[{view}] the editor finds that many autotile groups in it",
           len(block_origins(1, terrain_art.SHEET_COLUMNS,
                             terrain_art.SHEET_TILES)),
           len(TABLES[view]))
    expect(f"[{view}] every terrain name is distinct",
           len({t.name for t in TABLES[view]}), len(TABLES[view]))

# --------------------------------------------------------------------------
print()
print("every mask in QUADRANT has terrain at exactly the corners it claims")
# --------------------------------------------------------------------------
verdicts = 0
wrong: list[str] = []
for view in VIEWS:
    for block_index in range(len(TABLES[view])):
        name = f"[{view}] {TABLES[view][block_index].name}"
        for mask, (column, row) in sorted(QUADRANT.items()):
            for bit in (TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT):
                opaque = corner_opacity(SHEETS_BY_VIEW[view], block_index,
                                        column, row, bit)
                wanted = PROBE * PROBE if mask & bit else 0
                verdicts += 1
                if opaque != wanted:
                    wrong.append(
                        f"{name} mask {mask:04b} at column {column} row "
                        f"{row}: its {CORNER_NAME[bit]} corner is "
                        f"{opaque}/{PROBE * PROBE} opaque, wanted {wanted}")
for line in wrong[:12]:
    print(f"       {line}")
if len(wrong) > 12:
    print(f"       ... and {len(wrong) - 12} more")
expect(f"corner verdicts over {len(VIEWS)} sheets", verdicts,
       len(VIEWS) * len(terrain_art.TERRAINS) * len(QUADRANT) * 4)
expect("corners disagreeing with their mask", len(wrong), 0)

# The other half of "the table is satisfied": a quadrant the table does NOT
# name must not be mistaken for one that it does. The fill mask sits at
# (1, 3); if the sheet were drawn one row up, (1, 2) would be solid -- and
# (1, 2) is the top-edge tile, whose top two corners are empty.
edge_column, edge_row = QUADRANT[0b0011]
fill_column, fill_row = QUADRANT[FULL]
for view in VIEWS:
    expect(f"[{view}] the tile above the fill is an EDGE, not more fill",
           corner_opacity(SHEETS_BY_VIEW[view], 0, edge_column, edge_row,
                          TOP_LEFT), 0)
    expect(f"[{view}] and the fill tile itself is solid at every corner",
           [corner_opacity(SHEETS_BY_VIEW[view], 0, fill_column, fill_row, bit)
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
for view in VIEWS:
    for block_index in range(len(TABLES[view])):
        bx, by = (block_index % terrain_art.BLOCKS_ACROSS,
                  block_index // terrain_art.BLOCKS_ACROSS)
        for mask, (column, row) in sorted(QUADRANT.items()):
            left = bx * terrain_art.BLOCK_WIDTH + column * TILE
            top = by * terrain_art.BLOCK_HEIGHT + row * TILE
            for side, near, far, at in BORDERS:
                for index in range(TILE):
                    dx, dy = at(index)
                    bit = near if index < TILE // 2 else far
                    opaque = SHEETS_BY_VIEW[view].get_at(
                        (left + dx, top + dy))[3] > 0
                    seams += 1
                    if opaque != bool(mask & bit):
                        stepped.append(
                            f"[{view}] {TABLES[view][block_index].name} mask "
                            f"{mask:04b} {side} border at {index}: "
                            f"{'opaque' if opaque else 'clear'}, wanted the "
                            f"opposite")
for line in stepped[:8]:
    print(f"       {line}")
if len(stepped) > 8:
    print(f"       ... and {len(stepped) - 8} more")
expect("border pixels measured", seams,
       len(VIEWS) * len(terrain_art.TERRAINS) * len(QUADRANT) * 4 * TILE)
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
print("every FORM crosses every shared edge at its midpoint, on the pixels")
# --------------------------------------------------------------------------
# The sheet check above proves it for the eight forms as the table happens to
# use them. This proves it for every form against every mask, whoever uses
# it, by drawing the quadrant and reading the border back -- so a form added
# for one terrain cannot be shipped untested against the twelve masks that
# terrain does not happen to sit next to yet.
PROBE_PALETTE = "stone"
probes = {name: terrain_art.Terrain(f"probe_{name}", PROBE_PALETTE, "flat",
                                    name)
          for name in terrain_art.FORMS}
form_seams = 0
form_stepped: list[str] = []
for form_name, probe in probes.items():
    for mask in sorted(QUADRANT):
        cell = terrain_art.quadrant(mask, probe)
        for side, near, far_bit, at in BORDERS:
            for index in range(TILE):
                dx, dy = at(index)
                bit = near if index < TILE // 2 else far_bit
                opaque = cell.get_at((dx, dy))[3] > 0
                form_seams += 1
                if opaque != bool(mask & bit):
                    form_stepped.append(
                        f"form {form_name} mask {mask:04b} {side} border at "
                        f"{index}: {'opaque' if opaque else 'clear'}, wanted "
                        f"the opposite")
for line in form_stepped[:8]:
    print(f"       {line}")
if len(form_stepped) > 8:
    print(f"       ... and {len(form_stepped) - 8} more")
expect("border pixels measured over every form and mask", form_seams,
       len(terrain_art.FORMS) * len(QUADRANT) * 4 * TILE)
expect("form border pixels that would step against a neighbour",
       len(form_stepped), 0)

# And the corner patch, per form rather than per terrain: a ragged form that
# nibbled its own corner would make every corner verdict above a guess.
ragged: list[str] = []
for form_name, probe in probes.items():
    for mask, (column, row) in sorted(QUADRANT.items()):
        cell = terrain_art.quadrant(mask, probe)
        for bit in (TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT):
            ox, oy = CORNER_OFFSET[bit]
            opaque = sum(1 for dy in range(PROBE) for dx in range(PROBE)
                         if cell.get_at((ox + dx, oy + dy))[3] > 0)
            if opaque != (PROBE * PROBE if mask & bit else 0):
                ragged.append(f"form {form_name} mask {mask:04b} "
                              f"{CORNER_NAME[bit]}: {opaque}/{PROBE * PROBE}")
for line in ragged[:8]:
    print(f"       {line}")
expect("corner patches a form left undecidable", ragged, [])

# The other half of "a form is a silhouette": five forms that all drew the
# same shape would satisfy every rule above perfectly, and for a while eight
# of them nearly did -- the closest pair differed by TWO pixels of 256, and
# the assertion standing here said only that no two were byte-identical,
# which cannot fail for a one-pixel difference.
#
# So this measures the distance instead, over the DRAWN quadrants, which
# also proves the wire -- `Terrain.form` reaching `covers` through
# `quadrant` -- rather than re-running the geometry by hand. Both convex
# corners, one hanging from the top of a cell and one standing on the
# bottom, because `drip` and `heave` cover the same area and are opposites.
CONVEX = (TOP_LEFT, BOTTOM_LEFT)


def drawn_silhouette(probe):
    """The 512 pixels a terrain's two convex corners actually put on a sheet."""
    out = []
    for mask in CONVEX:
        cell = terrain_art.quadrant(mask, probe)
        out.extend(cell.get_at((x, y))[3] > 0
                   for y in range(TILE) for x in range(TILE))
    return tuple(out)


silhouettes = {name: drawn_silhouette(probe) for name, probe in probes.items()}
expect("a silhouette is both convex corners, not one",
       len(next(iter(silhouettes.values()))), 2 * TILE * TILE)
spread = sorted(
    (sum(1 for a, b in zip(silhouettes[first], silhouettes[second]) if a != b),
     first, second)
    for first, second in itertools.combinations(sorted(silhouettes), 2))
for apart, first, second in spread[:3]:
    print(f"       closest: {first}/{second} {apart} px of {2 * TILE * TILE}")
expect(f"form pairs closer than {terrain_art.FORM_DISTANCE} px of "
       f"{2 * TILE * TILE}",
       [f"{a}/{b}" for apart, a, b in spread
        if apart < terrain_art.FORM_DISTANCE], [])
# And the floor is not a number somebody could quietly lower to fit one more
# form in: `square` and `round` are both pinned -- the whole quadrant and the
# quarter circle -- so the distance between THEM is the widest a 16px corner
# can guarantee, and the floor is exactly that.
expect("and the floor IS the distance between the two pinned forms",
       sum(1 for a, b in zip(silhouettes["square"], silhouettes["round"])
           if a != b), terrain_art.FORM_DISTANCE)
# CONVEX's first entry is TOP_LEFT, so the quarter circle is centred on
# (0, 0): the default has to be the shape the sheet drew before forms
# existed, or every map already painted with it moves.
circle = tuple((x + 0.5) ** 2 + (y + 0.5) ** 2
               <= terrain_art.CORNER_RADIUS ** 2
               for y in range(TILE) for x in range(TILE))
expect("and the default form is still the quarter circle the sheet had",
       sum(1 for drawn, wanted
           in zip(silhouettes[terrain_art.DEFAULT_FORM], circle)
           if drawn != wanted), 0)

# Provoked, not trusted -- and provoked with the mutation that matters,
# which is a form that is very nearly one the vocabulary already has. The
# assertion this replaced passed exactly this case.
expect_raises("the spread guard refuses a form that is round by a hair",
              ValueError,
              lambda: terrain_art._verify_form_spread(
                  {"round": terrain_art.FORMS["round"],
                   "__probe__": lambda edge: 8.2}))
expect("and accepts one that is genuinely a different shape",
       terrain_art._verify_form_spread(
           {"round": terrain_art.FORMS["round"],
            "__probe__": lambda edge: terrain_art.LOBED_REACH}), None)
expect("the five real forms pass their own spread guard",
       terrain_art._verify_form_spread(), None)
# The same guard against a REAL form nudged: `lobed` pinched one pixel less
# hard stops being a second shape and becomes a slightly small circle.
expect_raises("and refuses the real vocabulary with lobed opened up by 1px",
              ValueError,
              lambda: terrain_art._verify_form_spread(
                  {**terrain_art.FORMS, "lobed": lambda edge: 6.5}))

# --------------------------------------------------------------------------
print()
print("the generator refuses a form that would draw a seam")
# --------------------------------------------------------------------------
# `_verify_forms` is the only thing standing between an author's arithmetic
# and a sheet that steps at every join, so it is provoked rather than
# trusted -- once for each failure it claims to catch.
def _with_form(reach):
    """Run the form guard with one extra form installed. Restores it."""
    terrain_art.FORMS["__probe__"] = reach
    try:
        terrain_art._verify_forms()
    finally:
        del terrain_art.FORMS["__probe__"]


expect_raises("a form that thins to a thread just inside the border",
              ValueError,
              lambda: _with_form(lambda edge: 24.0 if edge.jx + edge.jy <= 6
                                 else 3.0))
expect_raises("a form that overhangs a gap instead of stepping down",
              ValueError,
              lambda: _with_form(lambda edge: 3.0 if 4 <= edge.jx <= 5
                                 else 24.0))
expect_raises("a form that leaves a pinhole in its own mass", ValueError,
              lambda: _with_form(
                  lambda edge: 3.0 if (edge.jx, edge.jy) == (5, 5) else 24.0))
expect_raises("a form that eats into the corner probe patch", ValueError,
              lambda: _with_form(lambda edge: 3.0 if edge.jx >= 1
                                 and edge.jy >= 3 else 24.0))

# No reach function can break the midpoint crossing -- `_release` pins the
# radius to CORNER_RADIUS at a border pixel whatever a form asks for, which
# is the point of having a gate. So the half that proves the rule is live
# breaks the GATE instead, on one contracting form, and the guard catches it.
kept_release = terrain_art._release
terrain_art._release = lambda edge: 1.0
try:
    expect_raises("the guard fires when the gate stops holding the edge",
                  ValueError, lambda: terrain_art._verify_forms(
                      {"lobed": terrain_art.FORMS["lobed"]}))
finally:
    terrain_art._release = kept_release
expect("and passes again with the gate restored",
       terrain_art._verify_forms({"lobed": terrain_art.FORMS["lobed"]}), None)
expect("the eight real forms pass their own guard",
       terrain_art._verify_forms(), None)
expect_raises("covers() refuses a form nothing registered", ValueError,
              lambda: terrain_art.covers(FULL, 0, 0, "trapezoid"))
expect_raises("and _texture refuses a texture nothing draws", ValueError,
              lambda: terrain_art._texture(
                  terrain_art.Terrain("x", "stone", "hessian"),
                  ramp("stone"), 0, 0))

# --------------------------------------------------------------------------
print()
print("the table spends its 32 blocks on 32 different materials")
# --------------------------------------------------------------------------
for view in VIEWS:
    table, seen = TABLES[view], terrain_art.view_of(view)
    expect(f"[{view}] every form named in the table exists",
           sorted({t.form for t in table} - set(terrain_art.FORMS)), [])
    expect(f"[{view}] every texture named in the table exists",
           sorted({t.texture for t in table} - set(terrain_art.TEXTURES)), [])
    expect(f"[{view}] and every texture named is one this VIEW carries",
           sorted({t.texture for t in table} - set(seen.textures)), [])
    expect(f"[{view}] and nothing in either vocabulary goes undrawn",
           sorted((set(seen.forms) | set(seen.textures))
                  - {t.form for t in table} - {t.texture for t in table}), [])
    expect(f"[{view}] no two terrains are the same colour, texture AND form",
           len({(t.palette, t.texture, t.form) for t in table}), len(table))
# The vocabularies are shared, so between them the views must draw all of it:
# a texture in `TEXTURE_FNS` that no VIEW lists is art nobody has looked at,
# one level further out than the per-view rule can see.
expect("and no texture exists that no view can draw",
       sorted(set(terrain_art.TEXTURE_FNS)
              - {name for view in terrain_art.VIEWS.values()
                 for name in view.textures}), [])
expect("nor a form",
       sorted(set(terrain_art.FORMS)
              - {name for view in terrain_art.VIEWS.values()
                 for name in view.forms}), [])

# Colour, measured over EVERY pair rather than over the pairs that happen to
# touch on the sheet. The rule this replaced walked right-and-below
# neighbours only, so eleven of the twelve lookalike pairs sat under its own
# floor unmeasured -- `granite` against `cobble` at 2.4, below the
# just-noticeable difference -- and the wood-floor-against-planks pair the
# rule was written for was "fixed" by moving the two blocks apart.
#
# Measured here on the DRAWN field and in CIELAB, through the same two
# functions the generator uses, because a second copy of a colour conversion
# in `tools/` is a green assertion about a different colour space.
# PER VIEW, which is the whole sibling-route point: the second sheet has
# its own textures, so its blocks land at their own colours, and a rule that
# only ever measured `TERRAINS` would have let a top-down lookalike ship.
# Measured, not assumed: the mutation below paints one TOP-DOWN block like
# another and this is what has to go red.
FIELDS = {view: {t.name: t.field_colour() for t in TABLES[view]}
          for view in VIEWS}
alike: list[str] = []
for view in VIEWS:
    fields = FIELDS[view]
    expect(f"[{view}] every block's field colour was measured", len(fields),
           len(TABLES[view]))
    closest = (10 ** 6, "", "")
    for first, second in itertools.combinations(TABLES[view], 2):
        apart = distance(fields[first.name], fields[second.name])
        if apart < closest[0]:
            closest = (apart, first.name, second.name)
        if apart < terrain_art.TERRAIN_DISTANCE:
            alike.append(f"[{view}] {first.name}/{second.name} are "
                         f"{apart:.1f} apart")
    print(f"       [{view}] closest pair: {closest[1]}/{closest[2]} at dE "
          f"{closest[0]:.1f}")
for line in alike[:8]:
    print(f"       {line}")
expect(f"pairs anywhere on EITHER sheet under dE "
       f"{terrain_art.TERRAIN_DISTANCE}", alike, [])
fields = FIELDS[terrain_art.DEFAULT_VIEW]
# Touching blocks still may not share a texture or a form: colour is now held
# globally, but the sheet is the author's index and two neighbours drawn the
# same way is still a wrong pick he will not notice.
shared: list[str] = []
for view in VIEWS:
    for index, item in enumerate(TABLES[view]):
        column, row = (index % terrain_art.BLOCKS_ACROSS,
                       index // terrain_art.BLOCKS_ACROSS)
        for dx, dy in ((1, 0), (0, 1)):
            if (column + dx >= terrain_art.BLOCKS_ACROSS
                    or row + dy >= terrain_art.BLOCKS_DOWN):
                continue
            other = TABLES[view][
                (row + dy) * terrain_art.BLOCKS_ACROSS + column + dx]
            for axis in ("texture", "form"):
                if getattr(item, axis) == getattr(other, axis):
                    shared.append(f"[{view}] {item.name}/{other.name} share "
                                  f"a {axis}")
expect("touching blocks that share a texture or a form", shared, [])

# --------------------------------------------------------------------------
print()
print("a hazard never reads as a floor, and not only to a player who sees red")
# --------------------------------------------------------------------------
# The finding that outranked every other one: `grass` and `lava` sat 64.5
# apart in normal vision, 4.0 apart under simulated protanopia, with 5.6 of
# luminance between them. Twelve hazard/floor pairs collapsed that way. For
# roughly one man in twelve the tile he must never step on was the tile he
# walks on.
unsafe: list[str] = []
pairs_measured = 0
for view in VIEWS:
    hazards = [t for t in TABLES[view] if t.hazard]
    floors = [t for t in TABLES[view] if not t.hazard]
    expect(f"[{view}] the table names at least one hazard",
           len(hazards) > 0, True)
    expect(f"[{view}] and most of it is still ground you may stand on",
           len(floors) > len(hazards), True)
    worst_blind = (10 ** 6, "", "")
    for hazard in hazards:
        for floor in floors:
            a, b = FIELDS[view][hazard.name], FIELDS[view][floor.name]
            blind = min(distance(dichromat(a, kind), dichromat(b, kind))
                        for kind in DICHROMACIES)
            pairs_measured += 1
            if blind < worst_blind[0]:
                worst_blind = (blind, hazard.name, floor.name)
            if blind < terrain_art.HAZARD_DISTANCE:
                unsafe.append(f"[{view}] {hazard.name}/{floor.name}: "
                              f"colour-blind dE {blind:.1f}, luminance "
                              f"{abs(luminance(a) - luminance(b)):.1f}")
    print(f"       [{view}] closest under dichromacy: {worst_blind[1]}/"
          f"{worst_blind[2]} at dE {worst_blind[0]:.1f}")
for line in unsafe[:8]:
    print(f"       {line}")
expect("hazard/floor pairs measured, over every sheet",
       pairs_measured, sum(len([t for t in TABLES[v] if t.hazard])
                           * len([t for t in TABLES[v] if not t.hazard])
                           for v in VIEWS))
expect("hazard/floor pairs a red-green colourblind player cannot separate",
       unsafe, [])
hazards = [t for t in terrain_art.TERRAINS if t.hazard]
# The simulation has to actually change something, or every pair above would
# clear the rule by arithmetic that does nothing.
expect("simulating dichromacy is not the identity",
       dichromat((220, 60, 40), "deutan") == (220, 60, 40), False)
expect("and it collapses a red/green pair that normal vision separates",
       distance(dichromat((200, 60, 40), "deutan"),
                dichromat((70, 150, 50), "deutan"))
       < distance((200, 60, 40), (70, 150, 50)) / 4, True)
expect_raises("and it refuses a dichromacy it does not model", ValueError,
              lambda: dichromat((1, 2, 3), "tritan"))


def _with_table(rows):
    """Run the table guard against a substitute table."""
    terrain_art._verify_terrains(tuple(rows))


rows = list(terrain_art.TERRAINS)
lookalike = terrain_art.Terrain(rows[0].name, rows[1].palette,
                                rows[0].texture, rows[0].form)
expect_raises("the table guard refuses two names for one material",
              ValueError,
              lambda: _with_table(rows[:-1] + [terrain_art.Terrain(
                  "twin", rows[0].palette, rows[0].texture, rows[0].form)]))
expect_raises("and a form the vocabulary carries but nothing draws",
              ValueError,
              lambda: _with_table(
                  [rows[0]] + [terrain_art.Terrain(t.name, t.palette,
                                                   t.texture, rows[0].form)
                               if t.form == "heave" else t
                               for t in rows[1:]]))
expect_raises("and two touching blocks that share a form", ValueError,
              lambda: _with_table(
                  [terrain_art.Terrain(rows[0].name, rows[0].palette,
                                       rows[0].texture, rows[1].form)]
                  + rows[1:]))
# The colour mutation that the OLD adjacency rule could not see: two blocks
# at opposite ends of the sheet painted the same colour. `grass` is block 0,
# the top left, and `carpet` is block 28, four rows down and four across, so
# they touch nothing in common. Palette AND texture are copied and the form
# is left alone, which is what makes it a LOOKALIKE rather than a duplicate
# -- the "two names for one material" guard keys on all three and would
# otherwise fire first, and then this assertion would be proving the wrong
# rule while passing.
def _painted_like(table, victim, model):
    """`victim` repainted in `model`'s colour and surface, form untouched."""
    source = next(t for t in table if t.name == model)
    return tuple(terrain_art.Terrain(t.name, source.palette, source.texture,
                                     t.form, t.view, t.hazard)
                 if t.name == victim else t for t in table)


expect_raises("and two blocks that read alike ANYWHERE, not just adjacent",
              ValueError,
              lambda: _with_table(_painted_like(rows, "carpet", "grass")))
# THE SIBLING HALF. Every rule above now runs per view, and the way that
# goes wrong is that it keeps running on the sheet it was written for. So
# the same mutation is made in the TOP-DOWN table and `_verify_pack` -- the
# one entry point -- has to go red for it. Without this, deleting the
# top-down table from `TABLES` would leave the whole suite green.
expect_raises("and the same lookalike made on the TOP-DOWN sheet",
              ValueError,
              lambda: terrain_art._verify_pack({
                  "side": terrain_art.TERRAINS,
                  "topdown": _painted_like(terrain_art.TOPDOWN_TERRAINS,
                                           "carpet", "grass")}))
expect_raises("and a TOP-DOWN hazard a colourblind player would lose",
              ValueError,
              lambda: terrain_art._verify_pack({
                  "side": terrain_art.TERRAINS,
                  "topdown": tuple(
                      terrain_art.Terrain(t.name, "grass", t.texture, t.form,
                                          t.view, True)
                      if t.name == "lava" else t
                      for t in terrain_art.TOPDOWN_TERRAINS)}))
expect("and the real pack passes that same entry point",
       terrain_art._verify_pack(), None)
# And the hazard rule, mutated the way the finding says it went wrong:
# re-lighten lava to a grass-green's luminance and give it a green hue, and
# the two become one tile for a deuteranope.
expect_raises("and a hazard re-lit until a colourblind player loses it",
              ValueError,
              lambda: _with_table(
                  [terrain_art.Terrain(t.name, "grass", t.texture, t.form,
                                       hazard=True) if t.name == "lava" else t
                   for t in rows]))
# The rule has ONE number and no second branch about brightness, because
# `dichromat` leaves L* alone and a dE is never smaller than its own L*
# term. That claim is the load-bearing one, so it is measured rather than
# asserted in a comment: a pair that is the same hue and differs ONLY in
# brightness still clears the hazard floor after simulation.
dim_grass = tuple(round(channel * 0.45) for channel in ramp("grass").base)
expect("simulation leaves brightness alone, so brightness alone clears it",
       min(distance(dichromat(dim_grass, kind),
                    dichromat(ramp("grass").base, kind))
           for kind in DICHROMACIES) >= terrain_art.HAZARD_DISTANCE, True)
expect("and the two really are one hue, so hue is not what saved them",
       distance(dichromat(dim_grass, "deutan"), dim_grass) < 24.0, True)
expect("the real table passes its own guard",
       terrain_art._verify_terrains(), None)

# --------------------------------------------------------------------------
print()
print("every structured texture's rhythm fits inside a cell")
# --------------------------------------------------------------------------
# The form axis was held hard and the texture axis was not held at all, which
# is the failure CLAUDE.md's sibling warning describes exactly. A texture is a
# function of the pixel's position WITHIN its cell, so a rhythm whose period
# does not divide 16 restarts at every cell border: `ripple` put two
# full-width crest rows next to each other at a fixed 16px pitch on every
# lake, `plank` ran one board in three six rows tall, and `wave` and `vein`
# were broken too and merely happened to look benign.
#
# One rule over all four routes, not four patched functions, so one mutation
# turns them all red. Exact -- no threshold: the texture drawn in tile-local
# coordinates has to BE the texture drawn in global ones.
material = ramp("stone")
off_period: list[str] = []
texture_pixels = 0
for texture_name, fn in terrain_art.STRUCTURED_TEXTURES.items():
    for y in range(-TILE, 3 * TILE):
        for x in range(-TILE, 3 * TILE):
            texture_pixels += 1
            if fn(material, x, y, 7) != fn(material, x % TILE, y % TILE, 7):
                off_period.append(f"{texture_name} at ({x}, {y})")
                break
        else:
            continue
        break
expect("pixels compared against their tile-local twin", texture_pixels > 0, True)
for line in off_period:
    print(f"       {line}")
expect("structured textures whose period does not divide the tile",
       off_period, [])
expect("and the vocabulary is split, not silently exempt",
       sorted(set(terrain_art.STRUCTURED_TEXTURES)
              & set(terrain_art.HASHED_TEXTURES)), [])
expect("with every texture in exactly one half",
       sorted(terrain_art.TEXTURE_FNS),
       sorted(set(terrain_art.STRUCTURED_TEXTURES)
              | set(terrain_art.HASHED_TEXTURES)))
# The hashed half is exempt because it is LISTED, so it has to be listed for
# a reason: a hash has no period, and if one of these did it would belong in
# the other half.
periodic_hashes = [name for name, fn in terrain_art.HASHED_TEXTURES.items()
                   if all(fn(material, x, y, 7)
                          == fn(material, x % TILE, y % TILE, 7)
                          for y in range(-TILE, 2 * TILE)
                          for x in range(-TILE, 2 * TILE))]
expect("textures exempted as hashes that are really periodic",
       periodic_hashes, [])

expect("the generator's own texture guard passes",
       terrain_art._verify_textures(), None)
# Provoked with the exact defect that shipped: `wave` back on a period of
# six. Nothing else about the sheet changes, and this is the only assertion
# in the suite that goes red for it.
expect_raises("and refuses a band period of six, the one that shipped",
              ValueError,
              lambda: terrain_art._verify_textures(
                  {"__probe__": lambda m, x, y, salt:
                   m.light if (y + (x // 4) % 2) % 6 == 0 else m.base}))
expect_raises("and refuses a board pitch of five, the other one",
              ValueError,
              lambda: terrain_art._verify_textures(
                  {"__probe__": lambda m, x, y, salt:
                   m.shadow if y % 5 == 4 else m.base}))
expect("but passes the same band on a period of eight",
       terrain_art._verify_textures(
           {"__probe__": lambda m, x, y, salt:
            m.light if (y + 4 * ((x // 4) % 2)) % 8 == 0 else m.base}), None)

# --------------------------------------------------------------------------
print()
print("every texture in the vocabulary draws something, and flat draws none")
# --------------------------------------------------------------------------
# The per-terrain version below can only speak for the textures the table
# happens to use. This one walks the vocabulary, so a texture that stopped
# being called shows up the run it breaks rather than the run somebody
# finally assigns it.
mute: list[str] = []
loud: list[str] = []
for texture_name in terrain_art.TEXTURES:
    material = ramp("stone")
    drawn = {terrain_art.texture_fn(texture_name)(material, x, y, 5)
             for y in range(TILE) for x in range(TILE)}
    if texture_name == "flat":
        if len(drawn) != 1:
            loud.append(texture_name)
    elif len(drawn) < 2:
        mute.append(texture_name)
expect("textures that render as a flat swatch", mute, [])
expect("and 'flat' rendering as anything but one colour", loud, [])

# --------------------------------------------------------------------------
print()
print("thirty-two terrains, not one terrain thirty-two times")
# --------------------------------------------------------------------------
fills_by_view = {}
for view in VIEWS:
    fills = []
    for block_index in range(len(TABLES[view])):
        bx, by = (block_index % terrain_art.BLOCKS_ACROSS,
                  block_index // terrain_art.BLOCKS_ACROSS)
        left = bx * terrain_art.BLOCK_WIDTH + fill_column * TILE
        top = by * terrain_art.BLOCK_HEIGHT + fill_row * TILE
        fills.append(tuple(
            tuple(SHEETS_BY_VIEW[view].get_at((left + x, top + y)))
            for y in range(TILE) for x in range(TILE)))
    fills_by_view[view] = fills
    expect(f"[{view}] no two blocks have the same fill tile",
           len(set(fills)), len(fills))
# Two sheets OF ONE FAMILY share a fill tile EXACTLY where the row draws the
# same texture on the same palette in both views -- `flat`, `rivet`, `fleck`
# and the rest of the surfaces that look the same whichever way you stand.
# The full quadrant has no edge in it, so the view's lighting has nothing to
# say there, and that is the correct answer rather than a miss: a view
# changes the RIM. Asserted as an equality, not as "few", so a view that
# quietly stopped changing anything shows up as 32.
#
# PER FAMILY, AND BY BLOCK INDEX. This used to compare VIEWS[0] against
# VIEWS[1] and match rows by NAME, which was the same thing while there were
# two sheets and one family. With three it compared `beatemup` against `side`
# -- two tables that share one name by coincidence -- and the prediction was
# out by the one pair it cannot see: `void`/`flat` and `open_pit`/`flat` draw
# the same fill under two names, because `_flat` ignores the salt. Inside a
# family block N IS the same material, so the pairing is the index and the
# accident cannot arise.
families: dict[str, list[str]] = {}
for view in VIEWS:
    families.setdefault(terrain_art.VIEWS[view].family, []).append(view)
compared_families = 0
for family, members in sorted(families.items()):
    if len(members) < 2:
        continue
    compared_families += 1
    first, second = members[0], members[1]
    expected_shared = sum(
        1 for a, b in zip(TABLES[first], TABLES[second])
        if a.palette == b.palette and a.texture == b.texture)
    expect(f"[{family}] the sheets share a fill tile exactly where they "
           f"share a surface",
           len(set(fills_by_view[first]) & set(fills_by_view[second])),
           expected_shared)
    expect(f"[{family}] and not for every block, which would mean the axis "
           f"draws nothing",
           expected_shared < len(TABLES[first]), True)
expect("families with two views to compare", compared_families > 0, True)
fills = fills_by_view[terrain_art.DEFAULT_VIEW]

# A block being distinct is not the same as a block being textured. The fill
# quadrant has no edge in it, so whatever colours it carries came from the
# texture function -- and a terrain that declares one and renders as a flat
# swatch is a texture that silently stopped being called.
flat_declared, untextured, patterned = [], [], []
for view in VIEWS:
    table = TABLES[view]
    flat_declared += [t.name for t in table if t.texture == "flat"]
    untextured += [f"[{view}] {table[i].name}"
                   for i, pixels in enumerate(fills_by_view[view])
                   if len(set(pixels)) == 1 and table[i].texture != "flat"]
    patterned += [f"[{view}] {table[i].name}"
                  for i, pixels in enumerate(fills_by_view[view])
                  if len(set(pixels)) > 1 and table[i].texture == "flat"]
expect("terrains declaring a texture and rendering flat", untextured, [])
expect("terrains declaring flat and rendering textured", patterned, [])
expect("and 'flat' is a real declaration somebody uses",
       len(flat_declared) > 0, True)

# --------------------------------------------------------------------------
print()
print("the view axis changes the SURFACE and never the silhouette")
# --------------------------------------------------------------------------
# The claim the second sheet rests on. A view picks a lighting model and a
# slice of the shared vocabularies; it does not touch `covers`, so the alpha
# it produces has to be the alpha the other view produces, pixel for pixel.
# If that holds, every corner and border verdict above covers both sheets by
# construction rather than by hope -- and if it ever stops holding, the
# autotile geometry has silently forked.
probe_masks = sorted(QUADRANT)
probe_ramp = ramp(PROBE_PALETTE)


def _leaky_lowangle(field_grid, material, texture=None, near=2):
    """THE MUTATION: `lowangle` with its near face hanging ONE ROW PAST the
    mass, which is the one plausible way to write this shader wrong.

    It is the whole of invariant A for every view that will ever be added, so
    it is asserted from both sides: the real shader moves no alpha at all,
    and this one -- which differs only in that the face may be drawn where
    `field_grid` is false -- moves a definite, non-zero number of pixels."""
    ox, oy = terrain_art.SHADOW_OFFSET
    width, height = len(field_grid), len(field_grid[0])
    out = terrain_art.surface(width, height)
    for x in range(width):
        for y in range(height):
            body = material.base if texture is None else texture(x, y)
            if field_grid[x][y]:
                steps = 1 if ((0 <= x + ox < width
                               and not field_grid[x + ox][y])
                              or (0 <= y + oy < height
                                  and not field_grid[x][y + oy])) else 0
                for depth in range(1, near + 1):
                    if y + depth < height and not field_grid[x][y + depth]:
                        steps = max(steps, near + 1 - depth)
                        break
            elif y > 0 and field_grid[x][y - 1]:
                steps = near
            else:
                continue
            for _ in range(steps):
                body = palette_fall(body)
            out.set_at((x, y), body)
    return out


alpha_checked = 0
alpha_wrong: list[str] = []
mutant_moved = 0
face_survival = 1.0
face_worst = None
eaten = 0
for form_name in sorted(terrain_art.FORMS):
    probes = [terrain_art.Terrain("p", PROBE_PALETTE, "flat", form_name, view)
              for view in ("side", "topdown", "beatemup")]
    for mask in probe_masks:
        drawn = [terrain_art.quadrant(mask, probe) for probe in probes]
        grid = terrain_art.field(
            TILE, TILE, lambda x, y: terrain_art.covers(mask, x, y, form_name))
        mutant = _leaky_lowangle(grid, probe_ramp)
        flat_face = 0
        mass_pixels = 0
        for y in range(TILE):
            for x in range(TILE):
                alpha_checked += 1
                solid = drawn[0].get_at((x, y))[3] > 0
                if any((cell.get_at((x, y))[3] > 0) != solid
                       for cell in drawn[1:]):
                    alpha_wrong.append(f"{form_name} {mask:04b} at ({x}, {y})")
                if (mutant.get_at((x, y))[3] > 0) != solid:
                    mutant_moved += 1
                if not solid:
                    continue
                mass_pixels += 1
                if drawn[2].get_at((x, y)) == drawn[1].get_at((x, y)):
                    flat_face += 1
        if mass_pixels:
            share = flat_face / mass_pixels
            if share < face_survival:
                face_survival, face_worst = share, f"{form_name} {mask:04b}"
            if share == 0.0:
                eaten += 1
for line in alpha_wrong[:8]:
    print(f"       {line}")
expect("alpha pixels compared across the three views", alpha_checked,
       len(terrain_art.FORMS) * len(probe_masks) * TILE * TILE)
expect("pixels where a view moved the silhouette", alpha_wrong, [])
# AND IT IS NOT VACUOUS. The same comparison against a shader that lets the
# near face hang one row past the mass, which is the mistake this is for.
expect("...and the leaky near face IS caught", mutant_moved, 240)
# `NEAR_FACE` never eats a cell -- measured where the damage would be, on the
# form that thins the near edge. It does NOT saturate; see the constant.
expect(f"worst top-face survival at NEAR_FACE={palette_NEAR_FACE} "
       f"({face_worst})", round(face_survival * 100, 1), 55.6)
expect("cells the near face ate whole", eaten, 0)

# THE NEAR FACE IS THE WHOLE OF THE THIRD VIEW, so it is measured rather
# than assumed. A solid cell has no near boundary inside it -- the grid
# border is never an edge -- so `lowangle` and `overhead` have to agree on it
# pixel for pixel; a cell with a row missing below has to differ.
solid_grid = terrain_art.field(TILE, TILE, lambda x, y: True)
notched = terrain_art.field(TILE, TILE, lambda x, y: y < TILE - 3)
expect("a cell with no near boundary is `overhead` exactly",
       digest_surface(palette_lowangle(solid_grid, probe_ramp)),
       digest_surface(terrain_art.overhead(solid_grid, probe_ramp)))
near_face = sum(
    1 for y in range(TILE) for x in range(TILE)
    if palette_lowangle(notched, probe_ramp).get_at((x, y))
    != terrain_art.overhead(notched, probe_ramp).get_at((x, y)))
expect("and a cell WITH one grows a near face",
       near_face, TILE * palette_NEAR_FACE)
expect_raises("a near face of no rows is `overhead` under a second name",
              ValueError,
              lambda: palette_lowangle(solid_grid, probe_ramp, near=0))

# The other half: it has to change SOMETHING, or the axis is a no-op that
# every assertion above would agree with. The same probe, same mask, same
# form -- only the lighting differs, and the rim is where it differs.
lit = terrain_art.quadrant(FULL ^ TOP_LEFT, terrain_art.Terrain(
    "p", PROBE_PALETTE, "flat", "round", "side"))
over = terrain_art.quadrant(FULL ^ TOP_LEFT, terrain_art.Terrain(
    "p", PROBE_PALETTE, "flat", "round", "topdown"))
different = sum(1 for y in range(TILE) for x in range(TILE)
                if lit.get_at((x, y)) != over.get_at((x, y)))
expect("and the two views really do shade that quadrant differently",
       different > 0, True)
print(f"       {different} of {TILE * TILE} pixels differ on one edge tile")

# THE DEFAULT IS PROVABLY THE SHEET THAT ALREADY SHIPPED. Not "looks the
# same": the default view's quadrant is compared against `palette.mass`
# called directly, so adding the axis is a measured no-op for `side`.
keep_view = terrain_art.DEFAULT_VIEW
expect("the default view is still 'side'", keep_view, "side")
expect("and it shades with palette.mass itself",
       terrain_art.VIEWS[keep_view].shade is palette_mass, True)
expect("and the two views do not share a lighting model",
       terrain_art.VIEWS["side"].shade is terrain_art.VIEWS["topdown"].shade,
       False)
undefaulted = terrain_art.Terrain("p", "grass", "tuft", "lobed")
expect("a Terrain that says nothing about its view IS the default",
       undefaulted.view, keep_view)
material = ramp("grass")
by_hand = palette_mass(
    terrain_art.field(TILE, TILE,
                      lambda x, y: terrain_art.covers(FULL ^ TOP_LEFT, x, y,
                                                      "lobed")),
    material,
    lambda x, y: terrain_art.texture_fn("tuft")(
        material, x, y, terrain_art._salt(undefaulted.name)))
through_axis = terrain_art.quadrant(FULL ^ TOP_LEFT, undefaulted)
expect("and the axis draws it byte for byte as `mass` alone would",
       digest_surface(by_hand), digest_surface(through_axis))

# Provoked: the guard that stops somebody relighting the shipped sheet.
expect_raises("the view guard refuses a default that is not `mass`",
              ValueError,
              lambda: terrain_art._verify_views(
                  {"side": terrain_art.View("side",
                                            terrain_art.VIEWS["topdown"].shade,
                                            terrain_art.SIDE_TEXTURES,
                                            ("round",), False, "natural",
                                            ONE)}))
expect_raises("and two views that shade with the same function", ValueError,
              lambda: terrain_art._verify_views(
                  {"side": terrain_art.VIEWS["side"],
                   "topdown": terrain_art.View(
                       "topdown", palette_mass,
                       terrain_art.TOPDOWN_TEXTURES, ("round",), True,
                       "natural", ONE, ("furrow",))}))
expect_raises("and a view naming a texture nothing registered", ValueError,
              lambda: terrain_art._verify_views(
                  {"side": terrain_art.View("side", palette_mass,
                                            ("hessian",), ("round",), False,
                                            "natural", ONE)}))
expect_raises("and a view exempting a texture it cannot draw", ValueError,
              lambda: terrain_art._verify_views(
                  {"side": terrain_art.VIEWS["side"],
                   "topdown": terrain_art.View(
                       "topdown", terrain_art.VIEWS["topdown"].shade,
                       ("flat",), ("round",), True, "natural", ONE,
                       ("furrow",))}))
expect_raises("and view_of() refuses a view nothing registered", ValueError,
              lambda: terrain_art.view_of("isometric"))
expect_raises("and a table that mixes two views in one sheet", ValueError,
              lambda: terrain_art._verify_terrains(
                  (terrain_art.TOPDOWN_TERRAINS[:1]
                   + terrain_art.TERRAINS[1:])))
expect("the real views pass their own guard", terrain_art._verify_views(),
       None)

# --------------------------------------------------------------------------
print()
print("a foreshortened floor DECLARES its ratio, and the renderer is held to it")
# --------------------------------------------------------------------------
# The claim the third sheet rests on, and it is the opposite shape to the
# isotropy rule above. A statistic on a finished 16px cell cannot state a
# ratio -- three were tried and all three answered wrong, in three different
# directions -- so the stone's SCREEN size is declared in `FLOORS`, where two
# integers cannot lie about themselves, and everything that could still lie
# is asserted here. No threshold appears anywhere below: every comparison is
# an equality on integers, deliberately, because any tolerance in this rule
# would be a number picked to make today's sheet pass.
Slab = terrain_art.Slab
BEAT = terrain_art.VIEWS["beatemup"]


def _floors_view(*names):
    """The real `beatemup` view, carrying only the floor names given."""
    return {"beatemup": terrain_art.View(
        BEAT.name, BEAT.shade, tuple(names), BEAT.forms, BEAT.isotropic,
        BEAT.family, BEAT.foreshortening, ())}


PROBE_FLOOR = "__floor__"


def _as_floor(slab, texture=None):
    """Run the guard over ONE probe floor, with its texture registered the
    way a real floor's is -- `FLOORS` and `TEXTURE_FNS` are spread from one
    dict, so a probe that skipped the registration would trip the wrong half
    of the rule and prove nothing about the half it was aimed at."""
    def run():
        terrain_art.TEXTURE_FNS[PROBE_FLOOR] = (
            texture if texture is not None else terrain_art._slab_texture(slab))
        try:
            return terrain_art._verify_foreshortening(
                {PROBE_FLOOR: slab}, _floors_view(PROBE_FLOOR))
        finally:
            del terrain_art.TEXTURE_FNS[PROBE_FLOOR]
    return run


expect("the real floors pass their own guard, and SAY which they judged",
       terrain_art._verify_foreshortening(),
       {"side": {}, "topdown": {},
        "beatemup": {name: "the ratio rule" for name in terrain_art.FLOORS}})
expect("and every one of them declares the view's ratio",
       sorted({Fraction(s.h, s.w) for s in terrain_art.FLOORS.values()}),
       [HALF])
expect("k is an exact Fraction, never a float",
       all(isinstance(v.foreshortening, Fraction)
           for v in terrain_art.VIEWS.values()), True)
expect("and the shared constant is a view OF the views, not a second table",
       terrain_art.FORESHORTENING,
       {name: view.foreshortening
        for name, view in terrain_art.VIEWS.items()})

# Two different stones at the SAME declared ratio both pass: the rule is
# about the ratio, not about one stone size, which is the whole reason
# k = 1/2 was picked over k = 1/4.
ONE_FLOOR = {"beatemup": {PROBE_FLOOR: "the ratio rule"}}
expect("a 16x8 stone at k = 1/2 passes", _as_floor(Slab(16, 8))(), ONE_FLOOR)
expect("and an 8x4 stone, which is the same ratio", _as_floor(Slab(8, 4))(),
       ONE_FLOOR)
# ...and every way of getting it wrong is refused.
expect_raises("an UNforeshortened stone is refused", ValueError,
              _as_floor(Slab(16, 16)))
expect_raises("and a doubly foreshortened one", ValueError,
              _as_floor(Slab(16, 4)))
# These two carry an explicit texture, because `_slab_texture` refuses an
# illegal stone at REGISTRATION -- which is the right place for it and the
# wrong place to provoke the rule from: a probe that let it raise there would
# report a ValueError without ever reaching the branch it is aimed at.
_FLAT_PROBE = terrain_art.TEXTURE_FNS["flat"]
expect_raises("and a stone whose bands do not fit its depth",
              ValueError, _as_floor(Slab(8, 2), _FLAT_PROBE))
expect_raises("and one whose screen size does not divide the tile",
              ValueError, _as_floor(Slab(6, 3), _FLAT_PROBE))
expect_raises("...and `_slab_texture` refuses it at registration as well",
              ValueError, lambda: terrain_art._slab_texture(Slab(8, 2)))
expect_raises("and a view that declares a ratio and names no floor at all",
              ValueError,
              lambda: terrain_art._verify_foreshortening({}, {
                  "beatemup": terrain_art.View(
                      BEAT.name, BEAT.shade, ("flat",), BEAT.forms,
                      BEAT.isotropic, BEAT.family, HALF, ())}))

# HALF THREE, AND IT IS THE ONE THE WHOLE VIEW RESTS ON.
# `_verify_foreshortening` used to compare `_lattice_period(_slab_lattice(
# slab))` with `(w, h)` -- and `_slab_lattice` is the RENDERER's own helper,
# reading the renderer's own `SLAB_PHASE`. So the guard compared the
# declaration with a second reading of the declaration: measured, transposing
# the two phase lookups in `_slab_texture` made every floor draw a SQUARE
# stone at k = 1 -- the plan view this view exists to stop drawing -- and the
# whole pack still said GREEN. The provocation kept further down mutates
# `SLAB_PHASE`, the one table BOTH sides read, which is the single mutation
# shape a duplicated expression cannot fail, and that is why the original
# battery came back clean.
#
# `_slab_reference` shares no helper with the drawing path, so every mutant
# renderer below is one the guard can now see. They are run through
# `_as_renderer`, which replaces `_slab_texture` ITSELF -- a renderer that
# drifted is not a registration that drifted, and registering a mutant under
# an honest `_slab_texture` would redden HALF TWO and prove nothing here.
PROBE = ramp(PROBE_PALETTE)


def _as_renderer(slab, texture):
    """Run the guard with `_slab_texture` ITSELF answering `texture`.

    Built before the swap, deliberately: a mutant that called the live
    `_slab_texture` would call itself."""
    def run():
        kept = terrain_art._slab_texture
        terrain_art._slab_texture = lambda declared: texture
        terrain_art.TEXTURE_FNS[PROBE_FLOOR] = texture
        try:
            return terrain_art._verify_foreshortening(
                {PROBE_FLOOR: slab}, _floors_view(PROBE_FLOOR))
        finally:
            terrain_art._slab_texture = kept
            del terrain_art.TEXTURE_FNS[PROBE_FLOOR]
    return run


def _transposed(slab):
    """The plainest copy-paste slip there is: the two axes swapped."""
    honest = terrain_art._slab_texture(slab)
    return lambda m, x, y, salt: honest(m, y, x, salt)


def _square_stone(slab):
    """A renderer drawing w x w where the declaration says w x h: k = 1."""
    return terrain_art._slab_texture(
        dataclasses.replace(slab, h=slab.w))


def _rolled(slab):
    """The crack the period rule wrote off: the lattice rolled one row."""
    honest = terrain_art._slab_texture(slab)
    return lambda m, x, y, salt: honest(m, x, y + 1, salt)


def _drawn_is_declared(slab, texture=None):
    """Does what is DRAWN agree with `_slab_reference`, pixel for pixel?"""
    drawn = texture if texture is not None else terrain_art._slab_texture(slab)
    oracle = terrain_art._slab_reference(slab)
    return all(drawn(PROBE, x, y, 7) == oracle(PROBE, x, y, 7)
               for y in range(TILE) for x in range(TILE))


expect("every real floor draws exactly what it declares",
       [name for name, slab in terrain_art.FLOORS.items()
        if not _drawn_is_declared(slab)], [])
FLAG = terrain_art.FLOORS["flagstone"]
expect("a renderer drawing a SQUARE stone under a 16x8 declaration differs",
       _drawn_is_declared(FLAG, _square_stone(FLAG)), False)
expect("...while the lattice the OLD rule measured does not move at all -- "
       "it was never a function of what got drawn",
       terrain_art._lattice_period(terrain_art._slab_lattice(FLAG)),
       (FLAG.w, FLAG.h))
expect_raises("...and the oracle refuses it", ValueError,
              _as_renderer(FLAG, _square_stone(FLAG)))
expect("a renderer with its two axes transposed differs",
       _drawn_is_declared(FLAG, _transposed(FLAG)), False)
expect_raises("...and the oracle refuses that too", ValueError,
              _as_renderer(FLAG, _transposed(FLAG)))
# The PHASE, which the period rule explicitly could not pin: a lattice rolled
# one row inside the cell still measures (16, 8) and used to pass.
expect("a lattice rolled one row still has the DECLARED period",
       terrain_art._lattice_period(
           [[terrain_art._slab_lattice(FLAG)[x][(y + 1) % TILE]
             for y in range(TILE)] for x in range(TILE)]),
       (FLAG.w, FLAG.h))
expect_raises("and the oracle refuses it anyway", ValueError,
              _as_renderer(FLAG, _rolled(FLAG)))
# From the other side: the DECLARATION moved and the renderer did not, which
# is the same lie told the other way round.
HONEST_FLAG = terrain_art._slab_texture(FLAG)
expect_raises("a stone declaring a narrower groove than it cuts", ValueError,
              _as_renderer(dataclasses.replace(FLAG, units=1), HONEST_FLAG))
expect_raises("and one declaring a shallower rise than it draws", ValueError,
              _as_renderer(dataclasses.replace(FLAG, rise=1), HONEST_FLAG))

# THE GROOVE IS A WORLD WIDTH AND IT IS ALLOWED TO VANISH ACROSS.
expect("a 2-unit groove at k = 1/2 draws 2 away and 1 across",
       terrain_art._slab_joint(Slab(16, 8, units=2)), (2, 1))
expect("and a 1-unit groove draws 1 away and NOTHING across",
       terrain_art._slab_joint(Slab(8, 4, units=1)), (1, 0))
expect("the near face is the rise PROJECTED, not a number somebody typed",
       [terrain_art._slab_front(Slab(16, 8, rise=rise))
        for rise in (1, 2, 3)], [1, 2, 3])
expect_raises("a stone with no top face left over is refused", ValueError,
              _as_floor(Slab(8, 4, units=2, rise=3), _FLAT_PROBE))

# HALF TWO: the texture REGISTERED under a floor's name is the one the
# declaration builds. Without this the rule reads a declaration that nothing
# on the sheet draws, and every other assertion here stays green.
expect_raises("a floor whose registered texture is somebody else's",
              ValueError,
              _as_floor(Slab(16, 8), terrain_art.TEXTURE_FNS["mottle"]))
expect("and the probe is gone again afterwards",
       PROBE_FLOOR in terrain_art.TEXTURE_FNS, False)

# HALF THREE: the RENDERER draws the stone it was declared. Provoked the way
# it would really go wrong -- the phase table the renderer indexes says one
# stone depth and the declaration says another -- so the lattice's period
# stops matching and every floor on the sheet reddens at once.
kept_phase = terrain_art.SLAB_PHASE[8]
try:
    terrain_art.SLAB_PHASE[8] = (tuple(i % 9 for i in range(TILE)),
                                 tuple(i // 9 for i in range(TILE)))
    expect("a renderer drawing a stone one row deeper is caught",
           terrain_art._lattice_period(
               terrain_art._slab_lattice(Slab(16, 8))) != (16, 8), True)
    expect_raises("...and the guard says so", ValueError,
                  _as_floor(Slab(16, 8)))
finally:
    terrain_art.SLAB_PHASE[8] = kept_phase
expect("and the real lattice is the declared stone again",
       [terrain_art._lattice_period(terrain_art._slab_lattice(s))
        for s in terrain_art.FLOORS.values()],
       [(s.w, s.h) for s in terrain_art.FLOORS.values()])

# REVERSING THE SUN TURNS THE WHOLE LATTICE ROUND, not half of it.
# `_verify_lighting` can only see whether a texture MOVED when `SHADOW_OFFSET`
# is reversed, and a slab that read the constant on ONE axis and wrote the
# other out by hand still moves -- measured, that mutation leaves the whole
# pack green. This says the stronger thing: the turned lattice IS the mirror
# of the kept one, which a half-hard-coded joint cannot satisfy.
def _turned_lattice(slab):
    kept = terrain_art.SHADOW_OFFSET
    terrain_art.SHADOW_OFFSET = (-kept[0], -kept[1])
    try:
        return terrain_art._slab_lattice(slab)
    finally:
        terrain_art.SHADOW_OFFSET = kept


def _mirror(lattice, slab):
    return [[lattice[(slab.w - 1 - x) % TILE][(slab.h - 1 - y) % TILE]
             for y in range(TILE)] for x in range(TILE)]


expect("every floor turns round as ONE lattice when the sun reverses",
       [name for name, slab in terrain_art.FLOORS.items()
        if _turned_lattice(slab) != _mirror(terrain_art._slab_lattice(slab),
                                            slab)], [])
expect("and the sun is back where it was", terrain_art.SHADOW_OFFSET, (1, 1))

# `rim_contrast`'s FACE is what the view left alone, not "everything that is
# not the rim". On a shader that darkens the near rows as well, the two are
# different sets -- and counting the shaded rows as face is what reported an
# island with no edge on art that has a perfectly good one.
face_only = terrain_art.rim_contrast(
    next(t for t in terrain_art.BEATEMUP_TERRAINS if t.name == "scorched"))
expect("a beatemup island's face excludes the near face it is measured against",
       face_only > terrain_art.RIM_FALL, True)

# HALF FOUR: a floor is EXCUSED the isotropy rule, so it has to be measurably
# anisotropic. An exemption nobody checks is a list things get added to --
# the same argument the `directional` list is held to, in the same file.
expect("every floor exceeds the isotropy limit it is excused from",
       [name for name in terrain_art.FLOORS
        if terrain_art.directional_bias(terrain_art.texture_fn(name),
                                        ramp(PROBE_PALETTE))
        <= terrain_art.ISOTROPY_LIMIT], [])
# The fixture DRAWS ITSELF FAITHFULLY -- a one-unit groove, a one-unit rise
# and 10% grit on a 16x8 stone -- so the oracle below is satisfied and the
# only thing left that can refuse it is half four. A `lambda: m.base` probe
# reddens half three instead and says nothing at all about this half.
FLAT_DECLARATION = Slab(16, 8, units=1, rise=1, grit=0.10)
expect("a floor that draws faithfully still reaches half four",
       _drawn_is_declared(FLAT_DECLARATION), True)
expect_raises("...and a floor that has quietly stopped drawing a rectangle",
              ValueError, _as_floor(FLAT_DECLARATION))

# EXACTLY ONE RULE PER TEXTURE, which is what makes the split above safe
# rather than convenient.
expect("the real views pass the coverage rule",
       terrain_art._verify_view_coverage(), None)
# THE ZERO HAS TO BE REACHABLE OR THE RULE IS HALF A RULE.
# Coverage was scored as `(in floors) + (not in floors and not in
# directional) + (in directional)`, whose middle term is the exact negation
# of the other two. Brute-forced over every membership combination `covered`
# could only ever be 1 or 2, so the "a surface nothing measures" half could
# not fire at all -- and the assertion that claimed to provoke it was
# exercising the `covered == 2` branch a second time: measured, that fixture
# reported "covered by 2 rules", not 0. So each rule now REPORTS what it
# judged, at the line where it judges it, and this reads the report.
LEDGER = terrain_art._merge_judgements(terrain_art._verify_foreshortening(),
                                       terrain_art._verify_isotropy())
expect("every beatemup texture is judged exactly once",
       sorted(name for name, rules in LEDGER["beatemup"].items()
              if len(rules) != 1), [])
expect("and the ledger covers the whole vocabulary, nothing more",
       sorted(LEDGER["beatemup"]), sorted(BEAT.textures))
expect("the real ledger passes the coverage rule",
       terrain_art._verify_view_coverage(judged=LEDGER), None)


def _ledger_without(view_name, texture):
    """The real ledger with one rule having quietly stopped reporting -- a
    `continue` added to `_verify_isotropy` is exactly this."""
    holed = {name: {key: list(value) for key, value in rules.items()}
             for name, rules in LEDGER.items()}
    del holed[view_name][texture]
    return holed


expect("`chip` really is judged by the isotropy rule today",
       LEDGER["beatemup"]["chip"], ["the isotropy limit"])
expect_raises("and a texture covered by NO rule is refused", ValueError,
              lambda: terrain_art._verify_view_coverage(
                  judged=_ledger_without("beatemup", "chip")))
# And the overlap, which IS reachable through the live rules: a declared
# floor that is also named on the `directional` list is judged by the ratio
# rule AND excused by name, and two rules that both own a texture are two
# rules that will one day disagree about it.
expect_raises("and one covered by TWO is refused as well", ValueError,
              lambda: terrain_art._verify_view_coverage(
                  {"beatemup": terrain_art.View(
                      BEAT.name, BEAT.shade, ("flagstone",), BEAT.forms,
                      True, BEAT.family, HALF, ("flagstone",))},
                  terrain_art.FLOORS))

# --------------------------------------------------------------------------
print()
print("a FAMILY is a licence to have a different table, and it is earned")
# --------------------------------------------------------------------------
# `_verify_tables_agree` holds every view of ONE family to the same materials
# in the same order, because a gid carries no name and an author swapping
# sheets would otherwise be repainting his map. `beatemup` is a different set
# of materials, so it is a different family -- and the second half is the one
# that would otherwise rot: a family is a licence, so the cheap way to change
# one row is to invent a family for it, and then two "different" families are
# the same 32 names with the guarantee quietly gone.
expect("the real tables pass the family rule",
       terrain_art._verify_tables_agree(), None)
expect("side and topdown are ONE family",
       terrain_art.VIEWS["side"].family,
       terrain_art.VIEWS["topdown"].family)
expect("and beatemup is not in it",
       terrain_art.VIEWS["beatemup"].family
       != terrain_art.VIEWS["side"].family, True)
renamed = ((terrain_art.Terrain("moved", terrain_art.TOPDOWN_TERRAINS[0].palette,
                                "clump", "lobed", "topdown"),)
           + terrain_art.TOPDOWN_TERRAINS[1:])
expect_raises("two views of one family that disagree about block 0",
              ValueError,
              lambda: terrain_art._verify_tables_agree(
                  {"side": terrain_art.TERRAINS, "topdown": renamed}))
unhurt = tuple(terrain_art.Terrain(t.name, t.palette, t.texture, t.form,
                                   "topdown", False)
               for t in terrain_art.TOPDOWN_TERRAINS)
expect_raises("...and two that disagree about which blocks HURT", ValueError,
              lambda: terrain_art._verify_tables_agree(
                  {"side": terrain_art.TERRAINS, "topdown": unhurt}))
borrowed = tuple(terrain_art.Terrain(t.name, t.palette, t.texture, t.form,
                                     "beatemup", t.hazard)
                 for t in terrain_art.TOPDOWN_TERRAINS)
expect_raises("and a second family that names the same 32 materials",
              ValueError,
              lambda: terrain_art._verify_tables_agree(
                  {"topdown": terrain_art.TOPDOWN_TERRAINS,
                   "beatemup": borrowed}))
expect_raises("and a table naming a view nothing registered", ValueError,
              lambda: terrain_art._verify_tables_agree(
                  {"isometric": terrain_art.TERRAINS}))

# A FAMILY OF ONE HAS NO PARTNER, AND THE PAIR RULE SAYS NOTHING ABOUT IT.
# `_verify_tables_agree` compares `members[1:]` against `members[0]`, so
# family `urban` -- one member -- compares NOTHING. Measured, dropping
# `hazard=True` from `live_rail` or from `scorched` left the entire pack
# GREEN: an electrified third rail became ground a body may stand on, and
# each dropped flag REMOVES 28 hazard/floor pairs from the colour-blindness
# rule rather than failing it. The population guard was `any(t.hazard ...)`,
# which the three remaining hazards satisfy. So the verdict is anchored per
# table in `HAZARDS`, and these are the four drops the pair rule could not
# see plus the two it could.
expect("the urban family really does have exactly one member",
       sorted(name for name, view in terrain_art.VIEWS.items()
              if view.family == terrain_art.VIEWS["beatemup"].family),
       ["beatemup"])
expect("and the pair rule therefore compares nothing for it",
       terrain_art._verify_tables_agree(
           {"beatemup": tuple(
               dataclasses.replace(t, hazard=False)
               for t in terrain_art.BEATEMUP_TERRAINS)}), None)


def _unflagged(table, row):
    """That table with one row's hazard flag dropped."""
    return tuple(dataclasses.replace(t, hazard=False) if t.name == row else t
                 for t in table)


for dropped in sorted(terrain_art.HAZARDS["beatemup"]):
    expect_raises("dropping the hazard flag from beatemup %r is refused"
                  % dropped, ValueError,
                  (lambda row: lambda: terrain_art._verify_terrains(
                      _unflagged(terrain_art.BEATEMUP_TERRAINS, row)))(dropped))
expect_raises("and adding one to a row that does not hurt", ValueError,
              lambda: terrain_art._verify_terrains(tuple(
                  dataclasses.replace(t, hazard=True) if t.name == "kerb" else t
                  for t in terrain_art.BEATEMUP_TERRAINS)))
expect_raises("and a view with no hazard declaration at all", ValueError,
              lambda: terrain_art._verify_terrains(
                  terrain_art.BEATEMUP_TERRAINS, {"side": frozenset({"lava"})}))
expect("the declared hazards ARE the flagged ones, on every sheet",
       {view: sorted(name for name in terrain_art.HAZARDS[view])
        for view in terrain_art.TABLES},
       {view: sorted(t.name for t in table if t.hazard)
        for view, table in terrain_art.TABLES.items()})

# AND NO TWO ROWS IN DIFFERENT FAMILIES MAY DRAW THE SAME CELL.
# Every colour and structure rule measures WITHIN one table, because that is
# where an author picks a block from -- so nothing looked across tables, and
# measured, two of the thirty-two beatemup blocks WERE the topdown sheet
# pixel for pixel: `rusted_plate`/`rusted_plate` at 0 of 256 and
# `open_pit`/`void` at 0 of 256. `_salt` is a hash of the NAME, so two rows
# sharing a name in two families draw one picture, and `_flat` ignores the
# salt entirely.
expect("the real pack has no block in two families",
       terrain_art._verify_families_differ(), None)
expect_raises("and a beatemup row renamed onto a topdown one is refused",
              ValueError,
              lambda: terrain_art._verify_families_differ({
                  "topdown": terrain_art.TOPDOWN_TERRAINS,
                  "beatemup": tuple(
                      dataclasses.replace(t, name="void", palette="void",
                                          texture="flat", form="square")
                      if t.name == "open_pit" else t
                      for t in terrain_art.BEATEMUP_TERRAINS)}))
expect("and two rows in the SAME family may agree, which is the pair rule",
       terrain_art._verify_families_differ(
           {"side": terrain_art.TERRAINS,
            "topdown": terrain_art.TERRAINS}), None)

# THE DOMAIN OF THE GROUND RULES IS `mass`, NOT `overhead`. Both of these
# used to test `shade is not overhead`, which was true of exactly one view
# and would have let the third one grow beside them with none of it enforced
# -- the sibling shape CLAUDE.md counts nineteen times. So each is provoked
# ON THE NEW VIEW: if the domain ever narrows back, these go green-to-red.
expect_raises("the lighting rule judges the BEATEMUP sheet too", ValueError,
              lambda: terrain_art._verify_lighting(
                  {"beatemup": terrain_art.View(
                      BEAT.name, BEAT.shade, ("plank",), BEAT.forms,
                      BEAT.isotropic, BEAT.family, HALF, ())}))
expect_raises("and the surface rules judge it as well", ValueError,
              lambda: _with_rim_drop(
                  0.0, terrain_art._verify_surfaces,
                  terrain_art.BEATEMUP_TERRAINS))
expect("and the real beatemup sheet passes both",
       (terrain_art._verify_lighting(),
        terrain_art._verify_surfaces(terrain_art.BEATEMUP_TERRAINS)),
       (None, None))

# THE NEAR FACE HAS A SIGN, AND NOTHING USED TO MEASURE IT AT ALL.
# `fall` cannot invert, which is why it was chosen, but on a near-black
# surface it cannot MOVE either: measured over all 13 masks the near face
# moved `open_pit` 1.29 L*, `oil_slick` 2.20 and `scorched` 2.90 against a
# table mean of 10.2 -- the three rows where an edge cue matters most, and a
# pit read as a flat black mat rather than as a hole. `rim_contrast`
# deliberately excludes the near face from BOTH of its sets, so the one
# number on the sheet that touched these pixels looked away from them.
expect("a mid grey's near face still steps DOWN",
       palette_art.luminance(palette_art.face((120, 118, 124)))
       < palette_art.luminance((120, 118, 124)), True)
expect("and it is exactly `fall` there, not a second expression of it",
       palette_art.face((120, 118, 124)), palette_art.fall((120, 118, 124)))
PIT = palette_art.BASES["open_pit"]
expect("a near-black surface has no room to fall",
       abs(palette_art.luminance(palette_art.fall(PIT))
           - palette_art.luminance(PIT)) < palette_art.FACE_SHOW, True)
expect("so its near face catches the sky instead",
       palette_art.luminance(palette_art.face(PIT))
       > palette_art.luminance(PIT), True)
expect("and that is a step a player can see, not a rounding",
       palette_art.luminance(palette_art.face(PIT))
       - palette_art.luminance(PIT) > palette_art.FACE_SHOW, True)
expect("every beatemup row's near face is visible",
       [t.name for t in terrain_art.BEATEMUP_TERRAINS
        if terrain_art.face_contrast(t) < palette_art.FACE_SHOW], [])
expect("and the pit's, which is the row the rule was written for",
       terrain_art.face_contrast(
           next(t for t in terrain_art.BEATEMUP_TERRAINS
                if t.name == "open_pit")) >= palette_art.FACE_SHOW, True)
expect_raises("a view whose near face cannot be seen is refused", ValueError,
              lambda: _with_face_drop(terrain_art._verify_surfaces,
                                      terrain_art.BEATEMUP_TERRAINS))
expect("and the rim still FALLS on every one of them, which is the other "
       "rule and the other set of pixels",
       [t.name for t in terrain_art.BEATEMUP_TERRAINS
        if terrain_art.rim_contrast(t) < terrain_art.RIM_FALL], [])

# --------------------------------------------------------------------------
print()
print("the overhead model lights a TOP FACE, and every shadow agrees")
# --------------------------------------------------------------------------
# What the author actually asked for. `mass` puts `hi` along the top of a
# shape and `shadow` along its bottom, which is a vertical face catching
# overhead light -- the strongest "this is a wall" cue a 16px tile has. The
# overhead model draws ONE rim, on the `SHADOW_OFFSET` side, and nothing at
# all on the lit side. Read off the pixels of a plain square block, so it is
# the drawn art being measured and not the arithmetic.
solid = [[True] * TILE for _ in range(TILE)]
island = [[4 <= x < 12 and 4 <= y < 12 for y in range(TILE)]
          for x in range(TILE)]
flat_material = ramp("stone")
side_island = palette_mass(island, flat_material)
top_island = terrain_art.overhead(island, flat_material)
ox, oy = terrain_art.SHADOW_OFFSET
expect("the shadow offset is one pixel, down and to the right",
       (ox, oy), (1, 1))
expect("side lighting puts `hi` on the TOP edge of a block",
       side_island.get_at((7, 4))[:3], flat_material.hi)
expect("...and `shadow` on its BOTTOM edge",
       side_island.get_at((7, 11))[:3], flat_material.shadow)
expect("overhead lighting draws NOTHING on the lit (top) edge",
       top_island.get_at((7, 4))[:3], flat_material.base)
expect("...nor on the lit (left) edge",
       top_island.get_at((4, 7))[:3], flat_material.base)
expect("...and darkens the shadow-side (bottom) edge",
       top_island.get_at((7, 11))[:3], palette_fall(flat_material.base))
expect("...and the shadow-side (right) edge",
       top_island.get_at((11, 7))[:3], palette_fall(flat_material.base))
# THE RIM IS A STEP OFF WHAT THE TEXTURE DREW, not off the ramp. A fixed
# `material.dark` is inside the range several textures already paint, so the
# island edge disappeared on five terrains and INVERTED on `embers`, whose
# `_cinder` crust sits below `shadow`: the rim came out 23 luminance units
# brighter than the coals it was the shadow of. Proved on a texture that
# paints ONE colour, so the expected rim is computable here.
one_note = ramp("lava").hi
lit_island = terrain_art.overhead(island, flat_material,
                                  lambda x, y: one_note)
expect("the rim falls from the TEXTURE's colour, not the material's",
       lit_island.get_at((7, 11))[:3], palette_fall(one_note))
expect("...so it is darker than what the texture drew beside it",
       luminance(lit_island.get_at((7, 11))[:3])
       < luminance(lit_island.get_at((7, 7))[:3]), True)
expect("...and the fixed ramp step it replaced was BRIGHTER than that",
       luminance(flat_material.dark) > luminance(one_note), False)
# And the step is down for a material darker than the shared shadow violet
# itself, which `void` is: mixing toward SHADOW there LIGHTENS the pixel.
void = ramp("void")
expect("a rim on a near-black material still falls",
       luminance(palette_fall(void.base)) < luminance(void.base), True)
expect("...though mixing it toward SHADOW alone would have raised it",
       luminance(palette_mix(void.base, terrain_art.SHADOW, 0.30))
       > luminance(void.base), True)
# The property tile art lives on, in BOTH models: a mass running to the edge
# of its cell gets no rim down the seam, or every join shows a line.
expect("a mass filling the cell gets no rim from `mass`",
       {palette_mass(solid, flat_material).get_at((x, y))[:3]
        for x in range(TILE) for y in range(TILE)}, {flat_material.base})
expect("nor from `overhead`",
       {terrain_art.overhead(solid, flat_material).get_at((x, y))[:3]
        for x in range(TILE) for y in range(TILE)}, {flat_material.base})
# And nothing is written where the grid is false, which is the alpha promise
# the whole second sheet rests on.
expect("overhead writes no pixel outside the occupancy grid",
       [(x, y) for x in range(TILE) for y in range(TILE)
        if (top_island.get_at((x, y))[3] > 0) != island[x][y]], [])

# ONE DIRECTION, SHARED -- OVER THE WHOLE VOCABULARY, NOT OVER FIVE NAMES.
# The guard that stood here reversed `SHADOW_OFFSET` and asserted that all
# five `_relief` users changed, which is green no matter what the other
# fourteen do. Measured, they did plenty: `grout`, `rivet`, `mosaic` and
# `setts` each wrote their own direction out by hand and did not move at
# all, and `plank` carried the side sheet's lit-top-dark-bottom board onto
# the overhead sheet, where it is the definition of the wall cue the whole
# view axis exists to remove.
top_view = terrain_art.view_of("topdown")


def drawn_cell(name):
    fn = terrain_art.texture_fn(name)
    return [fn(flat_material, x, y, 5)
            for y in range(TILE) for x in range(TILE)]


before = {name: drawn_cell(name) for name in top_view.textures}
kept_offset = terrain_art.SHADOW_OFFSET
terrain_art.SHADOW_OFFSET = (-1, -1)
try:
    turned = {name: drawn_cell(name) for name in top_view.textures}
finally:
    terrain_art.SHADOW_OFFSET = kept_offset
expect("textures that say they are lit and ignore the shared offset",
       sorted(name for name in top_view.textures
              if name in terrain_art.LIT_TEXTURES
              and turned[name] == before[name]), [])
expect("...and textures that read it without saying so",
       sorted(name for name in top_view.textures
              if name not in terrain_art.LIT_TEXTURES
              and turned[name] != before[name]), [])
expect("and every one of them draws what it drew once it is put back",
       sorted(name for name in top_view.textures
              if drawn_cell(name) != before[name]), [])
expect("the lit list is most of the vocabulary, not a handful",
       len(terrain_art.LIT_TEXTURES & set(top_view.textures)) >= 8, True)
# The half that catches a HARD-CODED direction, which "did not move" cannot:
# a texture with no lighting declared must measure no lighting.
leaning = sorted(
    f"{name} {terrain_art.shadow_bias(terrain_art.texture_fn(name), probe_grey):+.2f}"
    for name in top_view.textures
    if name not in terrain_art.LIT_TEXTURES
    and abs(terrain_art.shadow_bias(terrain_art.texture_fn(name),
                                    probe_grey))
    > terrain_art.LIGHTING_TOLERANCE)
expect("overhead textures that declare no lighting and are lit anyway",
       leaning, [])
expect("the real vocabulary passes its own lighting guard",
       terrain_art._verify_lighting(), None)
# Provoked with the exact texture that failed: the side sheet's board, lit
# along the top of each board and shadowed along the bottom.
expect("the side sheet's `plank` is what that rule is looking for",
       abs(terrain_art.shadow_bias(terrain_art.texture_fn("plank"),
                                   probe_grey))
       > terrain_art.LIGHTING_TOLERANCE, True)
expect_raises("and the guard refuses it on an overhead sheet",
              ValueError,
              lambda: terrain_art._verify_lighting(
                  {"topdown": terrain_art.View(
                      "topdown", terrain_art.overhead, ("plank",),
                      ("round",), True, "natural", ONE)}))
# And a texture that hard-codes the RIGHT direction is refused too, because
# it is right by accident: that is `grout` before it read `_joint`.
terrain_art.TEXTURE_FNS["__grout__"] = _hand_lit_grout
try:
    expect_raises("...and a laid texture that writes its own direction out",
                  ValueError,
                  lambda: terrain_art._verify_lighting(
                      {"topdown": terrain_art.View(
                          "topdown", terrain_art.overhead, ("__grout__",),
                          ("round",), True, "natural", ONE)}))
finally:
    del terrain_art.TEXTURE_FNS["__grout__"]
expect("and the probe is gone again afterwards",
       "__grout__" in terrain_art.TEXTURE_FNS, False)
# `_relief` itself: raised, shadowed, flat -- all three answers, so a version
# that always said "flat" would not pass by drawing nothing. The shadow is
# the two AXIS steps and not the diagonal one, which is the shape `overhead`
# already used for its rim and the reason a field of pebbles stopped
# measuring as a grain.
one = {(4, 4)}
expect("_relief calls a feature pixel raised",
       terrain_art._relief(lambda x, y: (x, y) in one, 4, 4), 1)
expect("...the pixel one step right of it, its shadow",
       terrain_art._relief(lambda x, y: (x, y) in one, 5, 4), -1)
expect("...and the pixel one step below it",
       terrain_art._relief(lambda x, y: (x, y) in one, 4, 5), -1)
expect("...the pixel one step BACK, open ground",
       terrain_art._relief(lambda x, y: (x, y) in one, 3, 4), 0)
expect("and the shadow is the same shape `overhead` draws its rim with",
       terrain_art._relief(lambda x, y: (x, y) in one, 5, 5), 0)
# `_joint`, the recess half: the gap at the far index, the lit wall at the
# near index of the next cell along, both read off the offset.
expect("_joint puts the gap at the far edge of a cell",
       (terrain_art._joint(7, 3, 8), terrain_art._joint(3, 7, 8)), (-1, -1))
expect("...the lit wall at the near edge",
       (terrain_art._joint(0, 3, 8), terrain_art._joint(3, 0, 8)), (1, 1))
expect("...and nothing in between", terrain_art._joint(3, 3, 8), 0)
terrain_art.SHADOW_OFFSET = (-1, -1)
try:
    flipped = (terrain_art._joint(7, 3, 8), terrain_art._joint(0, 3, 8))
finally:
    terrain_art.SHADOW_OFFSET = kept_offset
expect("and turning the sun round swaps them", flipped, (1, -1))

# --------------------------------------------------------------------------
print()
print("no overhead texture leans one way unless it means to")
# --------------------------------------------------------------------------
# The author's finding, as a number. Horizontal courses, board runs and wave
# bands read as siding, strata and brickwork; from above there is no horizon
# and no gravity, so a dominant direction is a mistake unless it MEANS
# something. `directional_bias` compares gradient energy along 0 against 90
# and 45 against 135 -- perpendicular PAIRS, so a step length is never
# compared with a longer one, and a square grid like `grout` correctly reads
# as having no grain rather than two.
probe = ramp("stone")
scores = {name: terrain_art.directional_bias(terrain_art.texture_fn(name),
                                             probe)
          for name in terrain_art.TEXTURES}
top_view = terrain_art.view_of("topdown")
over_limit = sorted(f"{name} {scores[name]:.3f}"
                    for name in top_view.textures
                    if name not in top_view.directional
                    and scores[name] > terrain_art.ISOTROPY_LIMIT)
# Under BOTH operators, because a broad feature is invisible to a local
# gradient: `furrow`'s one trough per tile scores 0.151 here and 0.389 on
# `profile_bias`, and it is the reason the second operator exists.
under_limit = sorted(
    f"{name} {scores[name]:.3f}"
    for name in top_view.directional
    if scores[name] <= terrain_art.ISOTROPY_LIMIT
    and terrain_art.profile_bias(terrain_art.texture_fn(name), probe)
    <= terrain_art.PROFILE_LIMIT)
for name in sorted(top_view.textures, key=lambda n: -scores[n])[:4]:
    print(f"       highest: {name} {scores[name]:.3f}"
          f"{'  (deliberate)' if name in top_view.directional else ''}")
expect(f"overhead textures over the {terrain_art.ISOTROPY_LIMIT} limit",
       over_limit, [])
# BOTH HALVES. An exemption list is where a texture goes when somebody could
# not get it under the limit, and once it is there nothing looks at it
# again -- so being on it has to cost something. A `furrow` that quietly
# stopped drawing furrows would keep its exemption forever.
expect("deliberately-directional textures that are not directional",
       under_limit, [])
expect("and the exemption list is not empty, or the rule proves nothing",
       len(top_view.directional) > 0, True)
# The measure has to SEPARATE. Calibrated against the side sheet, which is
# where the textures the author named actually live.
expect("the side sheet's board run scores as strongly directional",
       scores["plank"] > terrain_art.ISOTROPY_LIMIT, True)
expect("and its fibre grain, harder still",
       scores["grain"] > scores["plank"], True)
expect("while a plain hash scores near zero",
       scores["speckle"] < 0.05, True)
expect("and a square grid is not mistaken for a grain",
       scores["grout"] < terrain_art.ISOTROPY_LIMIT, True)
expect("flat has no direction because it has no gradient",
       scores["flat"], 0.0)
# Provoked, with the shape that actually fails: a band every four rows.
def _with_probe_texture(fn):
    """Run the isotropy guard with one extra texture registered. Restores it.

    Registered for the call only: a probe left in `TEXTURE_FNS` is a texture
    no view draws, and the vocabulary rules further down would report it as
    art nobody has looked at -- which is them working.
    """
    terrain_art.TEXTURE_FNS["__band__"] = _banded
    try:
        return fn()
    finally:
        del terrain_art.TEXTURE_FNS["__band__"]


expect_raises("the isotropy guard refuses a banded texture in the topdown view",
              ValueError,
              lambda: _with_probe_texture(lambda: terrain_art._verify_isotropy(
                  {"topdown": terrain_art.View(
                      "topdown", terrain_art.VIEWS["topdown"].shade,
                      ("__band__",), ("round",), True, "natural", ONE,
                      ("furrow",))})))
expect("and the probe is gone again afterwards",
       "__band__" in terrain_art.TEXTURE_FNS, False)
expect_raises("and refuses an exemption for a texture that is isotropic",
              ValueError,
              lambda: terrain_art._verify_isotropy(
                  {"topdown": terrain_art.View(
                      "topdown", terrain_art.VIEWS["topdown"].shade,
                      ("grit",), ("round",), True, "natural", ONE,
                      ("grit",))}))
# It RETURNS what it judged rather than None, and that is the whole of
# `_verify_view_coverage`'s teeth: a rule that reports nothing for a texture
# is a texture nothing measured. Every name it reports has to be one of the
# three verdicts it can reach.
ISOTROPY_LEDGER = terrain_art._verify_isotropy()
expect("the real vocabulary passes its own guard",
       sorted(ISOTROPY_LEDGER), sorted(terrain_art.VIEWS))
expect("and every verdict it hands back is one it can actually reach",
       sorted({rule for seen in ISOTROPY_LEDGER.values()
               for rule in seen.values()}),
       ["the directional exemption", "the isotropy limit",
        "the view's own exemption"])
expect("a non-isotropic view is excused ONCE, on the view",
       sorted({rule for rule in ISOTROPY_LEDGER["side"].values()}),
       ["the view's own exemption"])
expect("and the declared floors are NOT in it -- they are the ratio rule's",
       sorted(set(terrain_art.FLOORS) & set(ISOTROPY_LEDGER["beatemup"])), [])
# And the rule is a property of the VIEW, not of the package: the side sheet
# is FULL of directional textures on purpose, and turning the rule on for it
# has to go red. That is what makes `isotropic=False` a decision.
expect_raises("the same rule, turned on for the side sheet, refuses it",
              ValueError,
              lambda: terrain_art._verify_isotropy(
                  {"side": terrain_art.View(
                      "side", palette_mass, terrain_art.SIDE_TEXTURES,
                      terrain_art.VIEWS["side"].forms, True, "natural",
                      ONE)}))

# --------------------------------------------------------------------------
print()
print("a scattered feature is ONE feature, and nothing here repeats a glyph")
# --------------------------------------------------------------------------
# THE MEASUREMENT FOUR DEFECTS GOT PAST. `gravel`'s fused L, `chip`'s
# camouflage plate, `_patch`'s dominant blob and `scatter`'s bar were every
# one of them found by somebody looking at the sheet, and every one of them
# is the same shape: neighbouring cells of a feature lattice above the same
# threshold, fused into a glyph that comes back every sixteen pixels.
#
# `_speck` is the one place a hash becomes discrete things now, and its
# local-maximum rule makes the fusion impossible rather than unlikely: two
# 4-adjacent cells are in each other's neighbourhood, so they cannot both
# win. This flood-fills the WRAPPED mask and holds it at one cell.
worst_speck = 0
speck_pixels = 0
for salt in range(terrain_art.SPECK_SALTS):
    for spread in sorted(terrain_art.SPECK_SPREADS):
        mask = [[terrain_art._speck(x, y, salt, spread) for x in range(TILE)]
                for y in range(TILE)]
        speck_pixels += TILE * TILE
        worst_speck = max(worst_speck,
                          max(terrain_art._wrapped_components(mask),
                              default=0))
expect(f"feature pixels walked over {terrain_art.SPECK_SALTS} salts",
       speck_pixels, terrain_art.SPECK_SALTS
       * len(terrain_art.SPECK_SPREADS) * TILE * TILE)
expect("the largest connected feature `_speck` can draw",
       worst_speck, terrain_art.SPECK_LIMIT)
expect("the generator's own feature guard passes",
       terrain_art._verify_specks(), None)
# Provoked with the construction that actually shipped, at the salt that
# actually failed: a plain square lattice thresholded at 0.78, which is what
# `_scatter` was. It fuses eleven stones into a bar across the whole cell.
fused = [[noise(x // 2, y // 2, 6) > 0.78 for x in range(TILE)]
         for y in range(TILE)]
expect("the lattice `_scatter` used fuses into one long glyph",
       max(terrain_art._wrapped_components(fused)) > 10 * terrain_art.SPECK_LIMIT,
       True)
# And the wrapped flood fill has to SEE the wrap, or a glyph that runs off
# the edge reads as two small ones and passes.
ell = [[False] * TILE for _ in range(TILE)]
for spot in ((0, 0), (1, 0), (TILE - 1, 0), (TILE - 2, 0)):
    ell[spot[1]][spot[0]] = True
expect("a run crossing the cell border is ONE component, not two",
       terrain_art._wrapped_components(ell), [4])
expect("_speck refuses a spread nothing has ever flood-filled",
       _raises(ValueError, lambda: terrain_art._speck(0, 0, 0, 9)), True)
# Both halves: an empty field satisfies any size limit.
expect("...and every salt and spread draws SOME feature",
       [(salt, spread) for salt in range(terrain_art.SPECK_SALTS)
        for spread in sorted(terrain_art.SPECK_SPREADS)
        if not any(terrain_art._speck(x, y, salt, spread)
                   for y in range(TILE) for x in range(TILE))], [])

# --------------------------------------------------------------------------
print()
print("no overhead row carries a motif, repeats another row, or loses its edge")
# --------------------------------------------------------------------------
# The three things a row has to be true of AS DRAWN, on its own ramp and its
# own salt -- which is the field a player sees, and which the vocabulary
# rules above deliberately do not measure because they probe with one grey.
top_table = terrain_art.TABLES["topdown"]
side_table = terrain_art.TABLES["side"]
motifs = sorted(((terrain_art.repeat_bias(row), row.name)
                 for row in top_table
                 if row.texture in terrain_art.HASHED_TEXTURES),
                reverse=True)
for score, name in motifs[:3]:
    print(f"       most structure left after blurring: {name} {score:.2f}")
expect(f"overhead rows keeping more than {terrain_art.REPEAT_LIMIT} of L* "
       f"at glyph scale",
       [f"{name} {score:.2f}" for score, name in motifs
        if score > terrain_art.REPEAT_LIMIT], [])
# The measure has to SEPARATE, so it is calibrated against a field that IS
# one blob: a single 8px square in a 16px cell is the wallpaper repeat this
# rule is named after.
blob = terrain_art.Terrain("__blob__", "stone", "flat", "round", "topdown")
expect("a flat row leaves nothing at glyph scale",
       terrain_art.repeat_bias(blob) < 0.01, True)
expect("and the rule is not vacuous: `snow` measured 3.44 before the fix",
       max(score for score, _ in motifs) > 1.0, True)

alike = sorted(((terrain_art.structure_bias(a, b), a.name, b.name)
                for table in (top_table, side_table)
                for a, b in itertools.combinations(
                    [r for r in table
                     if r.texture in terrain_art.HASHED_TEXTURES], 2)),
               reverse=True)
print(f"       closest pair of drawings: {alike[0][1]}/{alike[0][2]} "
      f"{alike[0][0]:.3f}")
expect(f"rows drawing the same picture, over {terrain_art.STRUCTURE_LIMIT}",
       [f"{a}/{b} {score:.3f}" for score, a, b in alike
        if score > terrain_art.STRUCTURE_LIMIT], [])
# Provoked with the defect: the salt was `len(name)`, so `swamp` and `water`
# -- five letters each, both `ripplet` -- drew the identical field.
expect("a row correlates perfectly with itself, so the measure is real",
       round(terrain_art.structure_bias(top_table[3], top_table[3]), 6), 1.0)
# The probe is two rows that really do share a salt -- which is what the
# old `len(name)` handed `swamp` and `water`, five letters each and both
# `ripplet`. Same salt, different palette: one drawing in two colours.
twins = [terrain_art.Terrain("same", palette, "ripplet", "round", "topdown")
         for palette in ("swamp", "water")]
expect("two rows whose salts collide draw the same picture",
       terrain_art.structure_bias(*twins) > terrain_art.STRUCTURE_LIMIT, True)
expect("...and that is what `len(name)` did to `swamp` and `water`",
       len("swamp"), len("water"))
expect("...while a hash of the name keeps them apart",
       terrain_art._salt("swamp") != terrain_art._salt("water"), True)
expect("...spelled out rather than `hash()`, which is salted per process",
       terrain_art._salt("swamp"), 38928)

edges = sorted((terrain_art.rim_contrast(row), row.name) for row in top_table)
print(f"       faintest island edge: {edges[0][1]} {edges[0][0]:.1f} of L*")
expect(f"overhead rows whose island edge falls less than "
       f"{terrain_art.RIM_FALL} of L*",
       [f"{name} {score:.1f}" for score, name in edges
        if score < terrain_art.RIM_FALL], [])
expect("the generator's own surface guard passes",
       terrain_art._verify_surfaces(top_table), None)
# Provoked with the rim that shipped: a fixed `material.dark`, which on
# `embers` is BRIGHTER than the coal bed it is the shadow of.
kept_drop = terrain_art.RIM_DROP
expect_raises("and a rim that does not fall is refused",
              ValueError,
              lambda: _with_rim_drop(0.0, terrain_art._verify_surfaces,
                                     top_table))
expect("the rim drop is put back", terrain_art.RIM_DROP, kept_drop)

# --------------------------------------------------------------------------
print()
print("the two sheets agree about which blocks HURT, not only about names")
# --------------------------------------------------------------------------
# The sibling shape on the one rule that is not about the author. A `hazard`
# flag dropped from either table left the whole tileset suite green:
# `_verify_terrains`'s population guard is satisfied by the three remaining
# hazards, and dropping a flag REMOVES pairs from the colour-blindness rule
# rather than failing it. Two tables that must agree is the one line that
# catches it.
expect("every block is the same material AND the same verdict in both views",
       [(a.name, a.hazard, b.hazard)
        for a, b in zip(side_table, top_table)
        if (a.name, a.hazard) != (b.name, b.hazard)], [])
softened = tuple(
    terrain_art.Terrain(row.name, row.palette, row.texture, row.form,
                        row.view, False if row.name == "lava" else row.hazard)
    for row in top_table)
expect_raises("and a hazard quietly turned into a floor on ONE sheet",
              ValueError,
              lambda: terrain_art._verify_tables_agree(
                  {"side": side_table, "topdown": softened}))
expect("the real tables pass their own guard",
       terrain_art._verify_tables_agree(), None)

# --------------------------------------------------------------------------
print()
print("a crack is a split in a plate, not a stripe and not a chain-link net")
# --------------------------------------------------------------------------
# Two failures and the second was the FIX for the first. Chains that all ran
# one way drew a diagonal stripe, and `ice` was the tile the author named.
# Chains that CLOSED across the wrap fixed the lean and cut the tiled plane
# into a lattice of identical octagons instead -- `clay` drew the same glyph
# and the two rows correlated at 0.89.
expect("no crack pixel sits on the tile border",
       sorted(spot for spot in terrain_art.CRACK_LINES
              if spot[0] in (0, TILE - 1) or spot[1] in (0, TILE - 1)), [])
expect("the splits reach every quarter of the cell",
       len({(x // (TILE // 2), y // (TILE // 2))
            for x, y in terrain_art.CRACK_LINES}),
       terrain_art.CRACK_QUARTERS)
expect("the real crack set passes its own guard",
       terrain_art._verify_cracks(), None)
expect_raises("a chain that closes across the wrap is refused",
              ValueError,
              lambda: _with_cracks(
                  terrain_art.CRACK_LINES
                  + tuple((x, 15) for x in range(TILE))))
expect_raises("...and one heaped in a corner",
              ValueError,
              lambda: _with_cracks(tuple((x, y) for x in range(2, 7)
                                         for y in range(2, 4))))
expect("and the set is restored afterwards",
       terrain_art._CRACK, frozenset(terrain_art.CRACK_LINES))

# --------------------------------------------------------------------------
print()
print("a broad direction is measured by an operator that can SEE a broad one")
# --------------------------------------------------------------------------
# `directional_bias` is local -- a pixel against its neighbour -- so the
# sixteen-wide `furrow` scores 0.152 on it, under the limit, while a painted
# field of it is unmistakably ploughed. `profile_bias` compares the spread
# of the column means with the spread of the row means, which is the whole
# cell at once.
profiles = {name: terrain_art.profile_bias(terrain_art.texture_fn(name),
                                           probe_grey)
            for name in top_view.textures}
expect("deliberately-directional textures that lean under NEITHER operator",
       sorted(name for name in top_view.directional
              if profiles[name] <= terrain_art.PROFILE_LIMIT
              and terrain_art.directional_bias(terrain_art.texture_fn(name),
                                               probe_grey)
              <= terrain_art.ISOTROPY_LIMIT), [])
expect("and textures that declare none and lean on the whole-cell one",
       sorted(f"{name} {profiles[name]:.3f}" for name in top_view.textures
              if name not in top_view.directional
              and profiles[name] > terrain_art.PROFILE_LIMIT), [])
expect("the furrow is the case that needs the second operator",
       terrain_art.directional_bias(terrain_art.texture_fn("furrow"),
                                    probe_grey)
       <= terrain_art.ISOTROPY_LIMIT
       < profiles["furrow"], True)
expect("a flat texture has no profile either", profiles["flat"], 0.0)
expect("and a band every four rows is all profile",
       terrain_art.profile_bias(_banded, probe_grey) > 0.9, True)

# --------------------------------------------------------------------------
print()
print("every modulus inside a texture divides the tile -- read off the SOURCE")
# --------------------------------------------------------------------------
# THE HOLE `_verify_textures` CANNOT SEE, and it is not hypothetical: it is
# how `ice` came to band diagonally and stayed green.
#
# That guard compares `fn(x, y)` against `fn(x % 16, y % 16)`. A texture that
# takes `x % TILE` itself, as `crack` and `rivet` legitimately do to index a
# 16x16 table, makes the comparison compare a pixel with ITSELF -- the guard
# cannot fail for it, whatever it then does with the wrapped coordinate. And
# what `crack` then did was `(px + py) % 6`: lines at 135 degrees on a period
# that does not divide sixteen, so every one of them was cut at the cell
# border. Nothing measured it. `directional_bias` scored the finished tile at
# 0.15 because the sparkle is one shade on a tenth of the pixels; a wrap-seam
# metric was tried here and scored it 0.02, below `plank` and `grout`, which
# are correct.
#
# So this reads the ARITHMETIC instead of the picture. Every modulus a
# texture applies must divide `TILE`, because a rhythm on any other period
# restarts at the cell border -- and that is true whether or not the guard
# above can see it. Both halves: the real vocabulary passes, and a probe
# doing exactly what `crack` did is refused.
def texture_moduli(fn):
    """Every integer modulus in a texture's own body, as written.

    Resolved against the generator's namespace, so `x % TILE` and
    `y % (2 * 8)` are both read as numbers. A modulus this cannot resolve is
    REPORTED rather than skipped: an unauditable one is the only kind worth
    hiding a period in.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)):
            continue
        try:
            found.append(int(eval(compile(ast.Expression(node.right), "<m>",
                                          "eval"),
                                 vars(terrain_art), {})))
        except Exception:  # noqa: BLE001 - reporting tool
            found.append(ast.dump(node.right))
    return found


off_tile: list[str] = []
moduli_seen = 0
for texture_name in sorted(terrain_art.TEXTURE_FNS):
    for modulus in texture_moduli(terrain_art.TEXTURE_FNS[texture_name]):
        moduli_seen += 1
        if isinstance(modulus, int) and modulus > 0 and TILE % modulus == 0:
            continue
        off_tile.append(f"{texture_name} takes a modulus of {modulus}")
for line in off_tile:
    print(f"       {line}")
expect("moduli read off the texture sources", moduli_seen > 20, True)
expect("moduli inside a texture that do not divide the tile", off_tile, [])
# Provoked with the exact line that shipped, in the shape it shipped in: a
# texture that normalises its own coordinate -- which is what silences
# `_verify_textures` -- and then bands on a period of six.
def _sparkled(material, x, y, salt):
    px, py = x % TILE, y % TILE
    return material.light if (px + py) % 6 == 0 else material.base


def _sparkled_on_four(material, x, y, salt):
    px, py = x % TILE, y % TILE
    return material.light if (px + py) % 4 == 0 else material.base


def _unresolvable(material, x, y, salt):
    return material.light if x % (y + 3) == 0 else material.base


def off_period(fn):
    return [m for m in texture_moduli(fn)
            if not (isinstance(m, int) and m > 0 and TILE % m == 0)]


expect("_verify_textures cannot fail for a self-normalising texture",
       terrain_art._verify_textures({"__probe__": _sparkled}), None)
expect("but reading the arithmetic catches it", off_period(_sparkled), [6])
expect("and the same line on a period of four is not caught",
       off_period(_sparkled_on_four), [])
# And a modulus nobody can resolve is reported rather than waved through,
# which is the half that keeps the rule from being sidestepped by a variable.
expect("an unresolvable modulus is reported, not skipped",
       len(off_period(_unresolvable)), 1)

# --------------------------------------------------------------------------
print()
print("the lattice every overhead patch is built on closes at the tile")
# --------------------------------------------------------------------------
# `_verify_textures` cannot see this one. It compares a TEXTURE at (x, y)
# against the same texture at (x % 16, y % 16), and every texture built on
# `_lattice` carries a per-pixel hash as well, so it is exempt by name as a
# hashed texture -- and its lattice could carry an off-period rhythm into a
# painted field with no assertion anywhere in the way.
off = [(cell, x, y) for cell in (2, 4)
       for y in range(-TILE, 2 * TILE) for x in range(-TILE, 2 * TILE)
       if terrain_art._lattice(x, y, 7, cell)
       != terrain_art._lattice(x % TILE, y % TILE, 7, cell)]
expect("lattice samples that do not repeat at the tile", off[:4], [])
expect("the lattice is not a constant, or repeating is free",
       len({round(terrain_art._lattice(x, 3, 7, 4), 6)
            for x in range(TILE)}) > 4, True)
expect("_patch inherits the period", [
    (x, y) for y in range(-TILE, 2 * TILE) for x in range(-TILE, 2 * TILE)
    if terrain_art._patch(x, y, 7)
    != terrain_art._patch(x % TILE, y % TILE, 7)][:4], [])
expect("the generator's own lattice guard passes",
       terrain_art._verify_lattice(), None)
# Provoked: a cell size that does not divide the tile is exactly the failure,
# and it is the one `_verify_lattice` exists for.
expect("a lattice on a cell of 3 does NOT close at the tile",
       terrain_art._lattice(0, 0, 7, 3)
       == terrain_art._lattice(TILE, TILE, 7, 3), False)

# --------------------------------------------------------------------------
print()
print("ice is cracked, not striped: the chains run both ways and they close")
# --------------------------------------------------------------------------
# The author named `ice` as banding diagonally. It was: three chains all
# running down and to the right, fourteen adjacencies along (1, 1) against
# two along (1, -1) -- a lean of 0.75. `directional_bias` scored the
# finished picture at 0.05 and could not see it, because the cracks are a
# tenth of the pixels and the plate between them is the rest. So there is a
# second rule, and it measures the chains.
counts = terrain_art._crack_adjacency()
for pair in (((1, 0), (0, 1)), ((1, 1), (1, -1))):
    a, b = counts[pair[0]], counts[pair[1]]
    print(f"       {pair[0]} {a} against {pair[1]} {b}: lean "
          f"{abs(a - b) / (a + b):.2f}")
expect("crack chains that lean past the limit",
       [f"{p}" for p in (((1, 0), (0, 1)), ((1, 1), (1, -1)))
        if abs(counts[p[0]] - counts[p[1]])
        / (counts[p[0]] + counts[p[1]]) > terrain_art.CRACK_LEAN], [])
expect("the generator's own crack guard passes",
       terrain_art._verify_cracks(), None)
# Provoked WITH THE SET THAT SHIPPED. Not an invented failure: these are the
# exact 34 pixels `crack` drew when the author looked at it.
SHIPPED_CRACK = (
    (3, 0), (3, 1), (4, 2), (4, 3), (5, 4), (5, 5), (6, 6), (7, 6), (8, 7),
    (9, 7), (10, 8), (11, 9), (11, 10), (12, 11), (12, 12), (13, 13),
    (13, 14), (14, 15),
    (0, 9), (1, 9), (2, 10), (3, 10), (4, 11), (5, 11), (6, 12), (7, 13),
    (8, 13), (9, 14),
    (10, 3), (11, 3), (12, 2), (13, 2), (14, 1), (15, 1),
)
kept_crack = terrain_art._CRACK
terrain_art._CRACK = frozenset(SHIPPED_CRACK)
try:
    expect_raises("the crack guard refuses the set that the author saw stripe",
                  ValueError, terrain_art._verify_cracks)
    shipped_lean = terrain_art._crack_adjacency()
    print(f"       the shipped set: (1,1) {shipped_lean[(1, 1)]} against "
          f"(1,-1) {shipped_lean[(1, -1)]}")
finally:
    terrain_art._CRACK = kept_crack
expect("and passes again with the real set back",
       terrain_art._verify_cracks(), None)
# The other half: a set of dots that touch nothing, and a set that stops at
# the seam, are both refused too.
for bad_set, label in (
        (((0, 0), (4, 4), (8, 8), (12, 12)), "a scatter of dots"),
        (((2, 2), (3, 2), (4, 2), (5, 2), (2, 3), (2, 4), (2, 5)),
         "chains that stop at the tile border")):
    terrain_art._CRACK = frozenset(bad_set)
    try:
        expect_raises(f"and refuses {label}", ValueError,
                      terrain_art._verify_cracks)
    finally:
        terrain_art._CRACK = kept_crack
# And the fix is visible in the finished picture too, on the palette the
# author was looking at rather than on a probe grey.
ice_bias = terrain_art.directional_bias(terrain_art.texture_fn("crack"),
                                        ramp("ice"))
print(f"       crack on the ice ramp now scores {ice_bias:.3f}")
expect("crack on ice is inside the overhead limit, though it need not be",
       ice_bias <= terrain_art.ISOTROPY_LIMIT, True)

# --------------------------------------------------------------------------
print()
print("the two sheets are the same 32 materials, and land where the engine looks")
# --------------------------------------------------------------------------
expect("block N is the same material in every view",
       [t.name for t in terrain_art.TERRAINS],
       [t.name for t in terrain_art.TOPDOWN_TERRAINS])
expect("so origins() answers the same map for either view",
       terrain_art.origins(1, "side"), terrain_art.origins(1, "topdown"))
expect("the generator's own agreement guard passes",
       terrain_art._verify_tables_agree(), None)
expect_raises("and it refuses two views that name block 17 differently",
              ValueError,
              lambda: terrain_art._verify_tables_agree({
                  "side": terrain_art.TERRAINS,
                  "topdown": tuple(
                      terrain_art.Terrain("renamed", t.palette, t.texture,
                                          t.form, t.view, t.hazard)
                      if index == 17 else t
                      for index, t in enumerate(terrain_art.TOPDOWN_TERRAINS))
              }))
expect_raises("and _verify_pack refuses a view with no table at all",
              ValueError,
              lambda: terrain_art._verify_pack({"side": terrain_art.TERRAINS}))
expect_raises("and a table naming a view nothing registered", ValueError,
              lambda: terrain_art._verify_pack(
                  {**terrain_art.TABLES, "isometric": terrain_art.TERRAINS}))
expect_raises("and table_for() refuses a view with no table", ValueError,
              lambda: terrain_art.table_for("isometric"))

# Where the second sheet SHIPS. `resolve_art` answers with whatever is at the
# declared path before it falls back to the shipped twin, and
# `data/graphics/` is the author's own licensed art -- so a sheet named after
# an RPG Maker RTP file would be shadowed by HIS file on HIS machine, and
# these 32 terrains would never once be drawn, with nothing reporting a
# problem. The name has to be one the RTP does not use.
RTP_STEMS = ("TileA1", "TileA2", "TileA3", "TileA4", "TileA5", "TileB",
             "TileC", "TileD", "TileE")
expect("every view has a sheet path", sorted(terrain_art.SHEET_PATHS),
       sorted(terrain_art.VIEWS))
expect("and every path is a key of SHEETS", sorted(terrain_art.SHEETS),
       sorted(terrain_art.SHEET_PATHS.values()))
expect("no two views write the same file",
       len(set(terrain_art.SHEET_PATHS.values())),
       len(terrain_art.SHEET_PATHS))
for view, path in sorted(terrain_art.SHEET_PATHS.items()):
    stem = os.path.splitext(os.path.basename(path))[0]
    expect(f"[{view}] the sheet is declared under the licensed root",
           path.startswith("data/graphics/tilesets/System/"), True)
    expect(f"[{view}] ...so it has a shipped twin under data/art/",
           shipped_relative(path).startswith("data/art/"), True)
    if view == terrain_art.DEFAULT_VIEW:
        expect("[side] and the default sheet keeps the name it shipped with",
               stem, "TileA2")
        continue
    expect(f"[{view}] and its name is NOT one the RPG Maker RTP uses",
           stem in RTP_STEMS, False)
    expect(f"[{view}] while still saying A2, because that is its geometry",
           "A2" in stem, True)
expect("and each builder draws its own view's sheet",
       [digest_surface(terrain_art.SHEETS[terrain_art.SHEET_PATHS[view]]())
        for view in VIEWS],
       [digest_surface(SHEETS_BY_VIEW[view]) for view in VIEWS])

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
    """`digest_surface` short enough to print. ONE implementation, above."""
    return digest_surface(target)[:16]


for view in VIEWS:
    expect(f"[{view}] the terrain sheet is reproducible",
           digest(terrain_art.build_sheet(view)),
           digest(SHEETS_BY_VIEW[view]))
expect("the clutter sheet is reproducible",
       digest(tiles_art.build_sheet()), digest(clutter))
expect("and no two of the three sheets are the same picture",
       len({digest(clutter)} | {digest(s) for s in SHEETS_BY_VIEW.values()}),
       len(SHEETS_BY_VIEW) + 1)

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
    expect("a bare tree gets the sheet written", sorted(written),
           sorted(sheets))
    expect("and nothing is skipped", skipped, [])
    target = os.path.join(scratch, *next(iter(sheets)).split("/"))
    with open(target, "rb") as handle:
        before = hashlib.sha256(handle.read()).hexdigest()[:16]
    with open(target, "wb") as handle:
        handle.write(b"the author's own art")
    written, skipped = write_sheets(sheets, scratch)
    expect("a second run writes nothing", written, [])
    expect("and reports the skip", sorted(skipped), sorted(sheets))
    with open(target, "rb") as handle:
        expect("the file on disk is untouched", handle.read(),
               b"the author's own art")
    written, skipped = write_sheets(sheets, scratch, force=True)
    expect("--force is the only way past it", sorted(written),
           sorted(sheets))
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
