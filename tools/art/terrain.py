"""The autotile sheet: 32 Wang corner terrains, drawn from QUADRANT itself.

WHAT THIS PRODUCES
------------------
One 512x384 PNG laid out exactly as `editor/core/autotile.py` reads it: 8x4
blocks, each block 4x6 quadrants of 16px, each quadrant one map cell. Thirty-
two terrains, one per block, so two terrains meeting -- the thing the
autotile system exists for -- is a demo you can paint rather than a diagram.

THE ONE IDEA
------------
A quadrant's art is a pure function of its CORNER MASK. Nothing here knows
what a "concave top-left" tile looks like as a special case; it knows that a
corner is terrain or is not, and that where two adjacent corners disagree the
boundary crosses the shared edge at its midpoint. Run that over the 4x6
layout and the ring, the blob and the four concave notches fall out on their
own -- and they fall out AT the coordinates `QUADRANT` names, because the
layout is checked against that table at import (`_verify_layout`).

That check is the whole reason this file is worth more than a pretty picture.
A sheet whose fill quadrant is one row off looks completely fine and paints
garbage, and the failure surfaces as a seam in a map weeks later.

THREE AXES, NOT TWO
-------------------
A terrain is a COLOUR (`palette`), a SURFACE (`texture`) and a SILHOUETTE
(`form`). The third is what makes a material read at 16px: a tiled floor has
hard ninety-degree corners because somebody cut it, grass bulges into clumps,
snow drifts upward and a liquid sags downhill. Thirty-two terrains sharing
one corner curve are thirty-two colour swatches, however good the palette is.

Every axis has ONE rule it may not break, every one of the three is held at
import, and every one of the three was broken here at least once by somebody
who was watching a different axis at the time. They are, in order: a form may
not move where the boundary crosses a cell edge; a texture's rhythm must fit
in a cell; and no two blocks may look the same -- least of all a hazard and a
floor.

THE EDGE FORM, AND THE ONE RULE IT MAY NOT BREAK
------------------------------------------------
The mass in a quadrant has to meet its neighbour's mass exactly at the
shared edge, or every tile join shows a step. Two cells share two corners,
so the rule that makes it true is: ALONG ANY CELL BORDER, THE HALF NEAREST A
CORNER IS SOLID EXACTLY WHEN THAT CORNER IS SET. The boundary therefore
crosses every edge at its midpoint, and it does so for every mask and every
rotation, or the sheet is not shippable. It is a seam in a painted map weeks
later, and it looks perfectly fine on the sheet.

So a form does not get to say where the boundary meets the edge. A form
supplies a REACH -- how far from the corner point its silhouette wants to
sit, at this angle, at this pixel -- and `_inside` blends that reach back
toward `CORNER_RADIUS`, the plain quarter circle, by `_release`. Every form
goes through that one expression, and at a border pixel `_release` is
exactly zero, so every form IS the circle there. That is what makes "ragged
in the interior, exact at the crossings" structural rather than hoped for,
and it is why `round` still draws the sheet this file drew before forms
existed.

`_verify_forms` then measures what each form actually drew, over the whole
8x8 corner lattice, at import, and RAISES unless it is a STAIRCASE: mass
running unbroken from each cell border inward, never deeper than the column
before it. One shape, four failures -- a boundary crossing an edge off its
midpoint, a waist thinner than `EDGE_BAND`, a pinhole and a floating speck
-- and it is self-dual, so it covers the CONCAVE quadrant, which draws the
complement, without a second rule. A form that would draw a seam does not
get to draw at all.

FIVE FORMS, NOT EIGHT
---------------------
That gate says what a form may not do. It says nothing about whether anyone
can SEE a form, and for a while nothing did: this file carried eight, and its
closest pair differed by two pixels out of two hundred and fifty-six. Ten of
the twenty-eight pairs were six pixels apart or fewer. Painted as an island,
seven of the eight read as one shape.

The budget is the reason, and it is fixed, not a matter of trying harder. A
form's whole visible say is the far corner of its own 8x8 block -- everything
nearer the corner than `CORNER_RADIUS` is inside whatever it asks for, and
everything on a border is pinned to the circle -- so the passing silhouettes
run from an area of 36 to an area of 64, and eight shapes do not fit in 28
pixels of spread. Five do. `_verify_form_spread` is what holds that line, at
`FORM_DISTANCE`, and it replaced an assertion that only said the eight were
not byte-identical -- which cannot fail for a one-pixel difference.

What was cut: `bevel`, `step`, `cushion` and `jagged`. What replaced them is
`heave`, `drip` upside down, because a form that sags is only legible next to
one that rises.

ONE THING A FORM COSTS, WHICH THE SINGLE CIRCLE DID NOT
-------------------------------------------------------
A form is safe against any OTHER form along a shared edge -- that is
`_release`, and it holds. But two different forms are not complements of each
other: a `lobed` blob laid against a `square` notch at the same corner leaves
transparent pixels between them, up to 21 of 64. Within one terrain the blob
and the notch still complement exactly, and `editor/core/autotile.py` gives a
cell one gid, so nothing in the editor reaches this today. Two terrains
autotiled against one another on stacked layers would. The single-circle
sheet could not do it, so it is new, and it is written down rather than
guarded.

THE SURFACE, AND THE ONE RULE IT MAY NOT BREAK
-----------------------------------------------
`quadrant` draws ONE 16px cell and the renderer blits that same cell
everywhere, so a painted field shows the texture at (X % 16, Y % 16). A
texture with a rhythm of its own therefore has to FIT: a band every six rows
restarts at every cell border, and the field carries a hard line every
sixteen rows at a fixed pitch. That is the same failure the form rule exists
to prevent, arriving through the other axis while every assertion watched the
first one -- and it shipped, in `wave`, `ripple`, `plank` and `vein`.

`STRUCTURED_TEXTURES` are the ones with a rhythm, and `_verify_textures`
holds every one of them to a period that divides `TILE`, exactly, over a span
of tiles in each direction. `HASHED_TEXTURES` have no rhythm to break and are
listed as exempt by name, so an exemption is a decision somebody wrote down.

COLOUR, AND THE ONE PLAYER THE SHEET USED TO FAIL
--------------------------------------------------
`TERRAIN_DISTANCE` holds every pair of the thirty-two apart in CIELAB, on the
field each one DRAWS rather than on its base colour. Globally: the rule it
replaced compared blocks that touched on the sheet, which left eleven of the
twelve lookalike pairs unmeasured, `granite` and `cobble` 2.4 apart, and the
very pair the rule was written for still under its own floor.

WHERE THE VIEW AXIS SPENDS ITSELF, WHICH IS NOT THE LIGHTING
-------------------------------------------------------------
Measured over one block: shading the 24 quadrants with `mass` and with
`overhead` moves 6,532 of 104,576 drawn pixels, 6.2% -- and on the FULL mask
the two are byte-identical, because no pixel there has a neighbour outside
the grid. A painted field is almost all FULL tiles, so the lighting model is
invisible in the interior and visible only at an island's edge, which is
exactly where it works and where `RIM_FALL` measures it.

Everything else that makes a sheet read as ground from above is the TEXTURE
TABLE. That is where the next pass should spend its effort, and it is why
the surface rules -- `REPEAT_LIMIT`, `STRUCTURE_LIMIT`, `_verify_specks`,
`_verify_lighting` -- outnumber the lighting ones.

`HAZARD_CVD_DISTANCE` and `HAZARD_LUMA_DISTANCE` are the other half, and the
one that is not about the author. A terrain that says `hazard=True` is ground
a body must not be on, and for a red-green colourblind player hue does not
separate it from anything: `grass` and `lava` used to sit 64.5 apart in
normal vision and 4.0 apart under simulated protanopia. So a hazard clears
the rule by distance under BOTH simulated dichromacies, or by luminance,
which no kind of colour blindness takes away.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from typing import Callable

import pygame

from editor.core.autotile import (
    BLOCK_QUADRANT_COLUMNS,
    BLOCK_QUADRANT_ROWS,
    BOTTOM_LEFT,
    BOTTOM_RIGHT,
    DIAGONALS,
    EMPTY,
    FULL,
    QUADRANT,
    TOP_LEFT,
    TOP_RIGHT,
    block_origins,
)

from .palette import (RGB, FACE_SHOW, Ramp, RIM_DROP, SHADOW, SHADOW_OFFSET,
                      dichromat, distance, field, DICHROMACIES, lowangle,
                      luminance, mass, mix, noise, overhead, ramp, surface)

TILE = 16
"""One quadrant, one map cell. The sheet is unreadable at any other size."""

CORNER_RADIUS = TILE // 2

BLOCKS_ACROSS = 8
BLOCKS_DOWN = 4

BLOCK_WIDTH = BLOCK_QUADRANT_COLUMNS * TILE      # 64
BLOCK_HEIGHT = BLOCK_QUADRANT_ROWS * TILE        # 96
SHEET_WIDTH = BLOCKS_ACROSS * BLOCK_WIDTH        # 512
SHEET_HEIGHT = BLOCKS_DOWN * BLOCK_HEIGHT        # 384
SHEET_COLUMNS = SHEET_WIDTH // TILE              # 32 tiles across
SHEET_TILES = SHEET_COLUMNS * (SHEET_HEIGHT // TILE)

# The corner mask of every quadrant in a block, by [row][column].
#
# Rows 0-1 columns 0-1 are the isolated blob (four convex corners), rows 0-1
# columns 2-3 the four concave notches, and rows 2-5 a 4x4 ring whose edges,
# corners and interior supply everything else. `_verify_layout` asserts the
# thirteen QUADRANT entries land where this says they do.
BLOCK_MASKS: tuple[tuple[int, ...], ...] = (
    (0b0001, 0b0010, 0b0111, 0b1011),
    (0b0100, 0b1000, 0b1101, 0b1110),
    (0b0001, 0b0011, 0b0011, 0b0010),
    (0b0101, 0b1111, 0b1111, 0b1010),
    (0b0101, 0b1111, 0b1111, 0b1010),
    (0b0100, 0b1100, 0b1100, 0b1000),
)

# corner bit -> which half of the quadrant it hugs, as (column, row) in 0..1.
CORNERS: tuple[tuple[int, int, int], ...] = (
    (TOP_LEFT, 0, 0),
    (TOP_RIGHT, 1, 0),
    (BOTTOM_LEFT, 0, 1),
    (BOTTOM_RIGHT, 1, 1),
)
_BIT_AT = {(cx, cy): bit for bit, cx, cy in CORNERS}


def _verify_layout() -> None:
    """Refuse to draw a sheet the editor would read wrong.

    Both halves. Every mask QUADRANT names must sit at the coordinates it
    names, AND every quadrant this layout draws must be a mask the editor
    can ask for: a layout carrying a diagonal would produce art for a case
    `TerrainSet.gid_for` never looks up, so the pixels would be a lie about
    what the format supports.
    """
    if len(BLOCK_MASKS) != BLOCK_QUADRANT_ROWS:
        raise ValueError(f"a block is {BLOCK_QUADRANT_ROWS} quadrants tall; "
                         f"this layout has {len(BLOCK_MASKS)} rows")
    for row in BLOCK_MASKS:
        if len(row) != BLOCK_QUADRANT_COLUMNS:
            raise ValueError(f"a block is {BLOCK_QUADRANT_COLUMNS} quadrants "
                             f"wide; this layout has a row of {len(row)}")
    for mask, (column, row) in QUADRANT.items():
        found = BLOCK_MASKS[row][column]
        if found != mask:
            raise ValueError(
                f"QUADRANT puts mask {mask:04b} at column {column} row "
                f"{row}; this block draws {found:04b} there, so the sheet "
                f"would paint the wrong tile for that corner mask")
    for row, masks in enumerate(BLOCK_MASKS):
        for column, mask in enumerate(masks):
            if mask == EMPTY or mask in DIAGONALS:
                raise ValueError(
                    f"block column {column} row {row} carries mask "
                    f"{mask:04b}, which no terrain ever draws")


_verify_layout()


# --------------------------------------------------------------------------
# The form axis: the silhouette of a corner
# --------------------------------------------------------------------------

EDGE_HOLD = 1.5
"""Pixels of distance over which a form is released from the plain circle.

Exactly zero at a pixel touching a cell border, whole two pixels in. That
zero is the midpoint crossing: whatever a form asks for, the boundary AT the
border is `CORNER_RADIUS`, the same for every form, so two tiles drawn with
two different forms still meet without a step.
"""

EDGE_BAND = 2
"""How many pixels deep the mass must run along each cell border.

One would satisfy the crossing rule and still look wrong: a form that
contracts hard just inside the border leaves a single-pixel thread at the
waist of every blob, and two tiles joining thread-to-thread is a seam by
another name. `_verify_forms` refuses a form that thins below this.
"""

CORNER_CLEAR = 4
"""The corner patch `tools/check_art_tilesets.py` probes, in pixels.

A form must be solid across the whole of it, so that probe is a fact rather
than a judgement call about where a ragged edge happened to land.
"""

DEFAULT_FORM = "round"
"""The quarter circle. A `Terrain` that says nothing draws what it always did."""

LOBED_REACH = 5.5
"""`lobed`'s boundary: pinched hard enough that a blob swells into lobes."""

DRIP_SAG = 3.0
"""How far `drip` and `heave` move their boundary with gravity, in pixels.

Three is the whole budget, not a taste: at 3.5 the contracted half thins
past `EDGE_BAND` and `_verify_forms` refuses the form outright. So the two
gravity forms sit exactly as far from the circle as the quadrant allows.
"""

FORM_DISTANCE = 24
"""How many of a form's 512 silhouette pixels must differ from every other.

512 is the two convex corners a form draws -- one hanging DOWN from a top
corner and one standing UP from a bottom one -- so a form that is asymmetric
counts as different from a symmetric one even where their areas agree.

The number is not a taste either. `square` and `round` are both pinned:
`square` is the whole quadrant and `round` is the quarter circle this sheet
drew before forms existed, and they differ by exactly 24 pixels. That is the
widest separation a 16px quadrant with `CORNER_RADIUS` 8 can guarantee, so
no pair of forms may sit closer together than the two poles already are.

Measured: the eight forms this file carried before -- round, square, bevel,
step, jagged, cushion, lobed, drip -- had a closest pair of TWO pixels
(bevel against round, and step against bevel). Ten of their twenty-eight
pairs were six pixels apart or fewer, which is a third axis nobody can see.
Five forms that clear 24 beat eight that do not.
"""

@dataclass(frozen=True)
class Edge:
    """One pixel of one corner, in the corner's own frame.

    Built once per pixel and handed to a form's reach function, so a form is
    arithmetic on this record and cannot reach for the cell, the mask or the
    sheet -- which is what keeps it a pure function of the corner mask and
    the pixel position.
    """

    adx: float
    """Distance from the corner POINT along x, at the pixel centre: 0.5..7.5."""
    ady: float
    """The same along y."""
    radius: float
    """`hypot(adx, ady)`: how far out this pixel actually is."""
    turn: float
    """0.0 along the x axis, 1.0 along the y axis, 0.5 on the diagonal."""
    down: int
    """+1 when growing `ady` runs toward the BOTTOM of the cell, -1 upward.

    The one thing in this record that is not symmetric, and the only reason
    a form can know which way gravity points.
    """
    jx: int
    """Whole pixels from the corner along x, 0..7. For deterministic noise."""
    jy: int
    """The same along y."""


Reach = Callable[[Edge], float]
"""How far from the corner point a form wants its boundary, in pixels.

Only the part beyond `CORNER_RADIUS`, and only near the diagonal, survives
`_release` -- which is the honest shape of the budget. Every pixel closer to
the corner than 8 is inside whatever a form asks for, so a form's entire
visible say is the far corner of its own 8x8 block. Ask for 24 and get a
square; ask for 3 and get everything short of the edge bands cut away.
"""


def _edge(x: int, y: int, cx: int, cy: int) -> Edge:
    """The `Edge` for pixel (x, y) of the half-quadrant hugging corner (cx, cy)."""
    adx = abs((x + 0.5) - cx * TILE)
    ady = abs((y + 0.5) - cy * TILE)
    return Edge(adx=adx, ady=ady, radius=math.hypot(adx, ady),
                turn=math.atan2(ady, adx) / (math.pi / 2.0),
                down=1 if cy == 0 else -1,
                jx=int(adx - 0.5), jy=int(ady - 0.5))


def _reach_round(edge: Edge) -> float:
    """The quarter circle. Neutral, organic, and what the sheet always drew."""
    return float(CORNER_RADIUS)


def _reach_square(edge: Edge) -> float:
    """Past the far corner of the block, so nothing is cut: a hard ninety.

    Man-made ground: somebody cut this floor to a line and laid it.
    """
    return 3.0 * CORNER_RADIUS


def _reach_lobed(edge: Edge) -> float:
    """Pinched on the diagonal, so a blob swells into four soft lobes.

    Living ground cover: grass and moss grow in clumps, not in discs.
    """
    return LOBED_REACH


def _reach_drip(edge: Edge) -> float:
    """Heavy downhill: the mass sags toward the BOTTOM of the cell.

    `down` is the only asymmetric thing an `Edge` carries, and this is what
    it is for. A top corner hangs; a bottom corner is pulled thin. Liquid,
    ash, anything that runs.
    """
    return CORNER_RADIUS + DRIP_SAG * edge.down


def _reach_heave(edge: Edge) -> float:
    """`drip` upside down: the mass piles toward the TOP of the cell.

    Drifted snow, a mound, roots lifting a path. The pair is what makes
    gravity legible at all -- one form sagging looks like a rounder circle
    until something beside it is rising.
    """
    return CORNER_RADIUS - DRIP_SAG * edge.down


FORMS: dict[str, Reach] = {
    "square": _reach_square,
    "round": _reach_round,
    "lobed": _reach_lobed,
    "drip": _reach_drip,
    "heave": _reach_heave,
}


def form_reach(name: str) -> Reach:
    """The named form. Raises rather than quietly drawing a circle instead."""
    try:
        return FORMS[name]
    except KeyError:
        raise ValueError(
            f"no edge form {name!r}; this module draws "
            f"{', '.join(sorted(FORMS))}") from None


def _release(edge: Edge) -> float:
    """How much of its own reach a form is allowed at this pixel, in 0..1.

    Two factors, and each one buys off a different failure:

      * DISTANCE. Zero at a pixel on a cell border, whole `EDGE_HOLD` pixels
        in. This is the midpoint crossing itself -- at the border every form
        is the circle, so any two forms meet.
      * ANGLE. Zero along either axis, whole on the diagonal. Without it a
        contracting form eats the straight run out to the edge and leaves
        the one-pixel thread `EDGE_BAND` exists to forbid; with it,
        contraction is spent where the circle bulges furthest, which is the
        only place a silhouette is visible anyway.
    """
    near = (min(edge.adx, edge.ady) - 0.5) / EDGE_HOLD
    near = 0.0 if near < 0.0 else (1.0 if near > 1.0 else near)
    return near * math.sin(math.pi * edge.turn) ** 2


def _inside(reach: Reach, edge: Edge) -> bool:
    """THE gate. Every form, every pixel, every mask goes through this line."""
    return edge.radius <= CORNER_RADIUS + _release(edge) * (
        reach(edge) - CORNER_RADIUS)


def _corner_mass(reach: Reach, down: int) -> list[list[bool]]:
    """The 8x8 corner block a form draws, as [jx][jy] from the corner point.

    One corner is enough to judge a form: the other three are this one
    mirrored, because an `Edge` is built from absolute distances. `down` is
    the exception, and the only reason this takes an argument.
    """
    cy = 0 if down > 0 else 1
    return [[_inside(reach, _edge(jx, jy if cy == 0 else TILE - 1 - jy, 0, cy))
             for jy in range(CORNER_RADIUS)] for jx in range(CORNER_RADIUS)]


def _corner_profile(reach: Reach, down: int) -> tuple[int, ...]:
    """A form's corner mass as one number per column: how deep it runs.

    Raises if a column is not an unbroken run from the border inward,
    because then there is no such number -- and a column with a gap in it is
    a pinhole or a loose speck, which is the failure `_verify_forms` is
    really looking for.
    """
    solid = _corner_mass(reach, down)
    profile = []
    for jx in range(CORNER_RADIUS):
        depth = 0
        for jy in range(CORNER_RADIUS):
            if not solid[jx][jy]:
                continue
            if depth != jy:
                raise ValueError(
                    f"a form leaves a gap at ({jx}, {jy}) of its corner "
                    f"block: solid, cut, then solid again down one column is "
                    f"a pinhole in a convex tile and a loose speck in the "
                    f"concave one that removes the same shape")
            depth = jy + 1
        profile.append(depth)
    return tuple(profile)


def _verify_forms(forms: dict[str, Reach] = FORMS) -> None:
    """Refuse a form whose corner mass is not a STAIRCASE.

    Measured on the pixels a form actually produces, not on the algebra of
    its reach function -- a reach that is right on paper and wrong at
    `atan2` of half a pixel is exactly what this exists to catch.

    One shape, four failures. A staircase is a mass that runs unbroken from
    each cell border inward and never runs deeper than the column before it,
    and requiring it rules out, in order: the boundary crossing an edge away
    from its midpoint (which steps at every join), a waist thinner than
    `EDGE_BAND` (a one-pixel thread between two blobs), a pinhole, and a
    floating speck. It is also self-dual: the complement of a staircase is a
    staircase, and the complement is exactly what a CONCAVE quadrant draws,
    so one rule covers both ways round.
    """
    for name, reach in forms.items():
        for down in (1, -1):
            try:
                profile = _corner_profile(reach, down)
            except ValueError as exc:
                raise ValueError(f"form {name!r}: {exc}") from None
            if profile[0] != CORNER_RADIUS:
                raise ValueError(
                    f"form {name!r} runs only {profile[0]} of "
                    f"{CORNER_RADIUS} pixels along the cell border, so its "
                    f"boundary crosses that edge {CORNER_RADIUS - profile[0]} "
                    f"pixels short of the midpoint and every join with a "
                    f"neighbouring tile steps")
            if min(profile) < EDGE_BAND:
                raise ValueError(
                    f"form {name!r} thins to {min(profile)} pixels somewhere "
                    f"along a cell border ({profile}); at {EDGE_BAND} it is "
                    f"already a thread, and two tiles joining thread to "
                    f"thread is a seam by another name")
            for index in range(CORNER_RADIUS - 1):
                if profile[index] >= profile[index + 1]:
                    continue
                raise ValueError(
                    f"form {name!r} runs deeper at column {index + 1} than at "
                    f"column {index} ({profile}): the mass is not a staircase "
                    f"about its corner, so somewhere it overhangs a gap")
            for index in range(CORNER_CLEAR):
                if profile[index] >= CORNER_CLEAR:
                    continue
                raise ValueError(
                    f"form {name!r} leaves column {index} only "
                    f"{profile[index]} deep, inside the {CORNER_CLEAR}x"
                    f"{CORNER_CLEAR} corner patch; a corner probe there could "
                    f"not tell terrain from a ragged edge")


_verify_forms()


def form_silhouette(reach: Reach) -> tuple[bool, ...]:
    """The 512 pixels a form's two convex corners occupy.

    A corner hanging down from the TOP of a cell, then one standing up from
    the BOTTOM of it. Both, because `drip` and `heave` draw the same area and
    are opposites: a silhouette read from one corner alone would call them
    the same shape.
    """
    out: list[bool] = []
    for corner in (TOP_LEFT, BOTTOM_LEFT):
        for y in range(TILE):
            for x in range(TILE):
                cx = 0 if x < CORNER_RADIUS else 1
                cy = 0 if y < CORNER_RADIUS else 1
                out.append(bool(corner & _BIT_AT[(cx, cy)])
                           and _inside(reach, _edge(x, y, cx, cy)))
    return tuple(out)


def _verify_form_spread(forms: dict[str, Reach] = FORMS) -> None:
    """Refuse a vocabulary whose forms are not TELLABLE APART.

    `_verify_forms` proves a form is drawable. This proves it is worth
    drawing: eight silhouettes that all differ from each other by one pixel
    satisfy every rule in this file, cost a whole axis of the design, and
    are invisible at 16px. "No two are byte-identical" is the half-invariant
    that let that happen -- it cannot fail for a one-pixel difference.
    """
    silhouettes = {name: form_silhouette(reach)
                   for name, reach in forms.items()}
    for first, second in combinations(sorted(silhouettes), 2):
        apart = sum(1 for a, b in zip(silhouettes[first], silhouettes[second])
                    if a != b)
        if apart < FORM_DISTANCE:
            raise ValueError(
                f"forms {first!r} and {second!r} draw silhouettes {apart} "
                f"pixels apart out of {len(silhouettes[first])}, under "
                f"{FORM_DISTANCE}; at this size that is not a second shape, "
                f"it is the same shape with a rounding error, and the whole "
                f"point of the form axis is that a player can see it")


_verify_form_spread()


# --------------------------------------------------------------------------
# The texture axis: the surface inside the mass
# --------------------------------------------------------------------------

Texture = Callable[[Ramp, int, int, int], RGB]
"""(material, x, y, salt) -> the body colour of one interior pixel."""


def _lattice(x: int, y: int, salt: int, cell: int) -> float:
    """Smooth value noise in [0, 1) WHOSE PERIOD IS EXACTLY `TILE`.

    The one primitive every patchy top-down surface is built on: soil
    mottle, broad water ripple, clumped growth, cleaved stone plates. A
    per-pixel hash draws grit and nothing else, and grit is the wrong scale
    for ground seen from above -- what you see from up there is PATCHES.

    Corner values are hashed on a `TILE // cell` lattice and read MODULO
    that lattice, so the field closes on itself at 16 pixels in both
    directions: `_verify_lattice` measures it rather than trusting the
    arithmetic, because this is the one place a top-down texture could
    quietly acquire the off-period rhythm `_verify_textures` exists to
    forbid -- and it would slip past that guard, which only ever sees the
    finished texture and cannot see a hash's argument.

    Sixteen is also the CEILING, and it is worth saying out loud: a texture
    is evaluated at (X % 16, Y % 16), so "a mottle at a scale larger than
    one tile" cannot exist in this format at all. The largest patch this
    can draw is one tile across, and that is why `_patch` mixes a coarse
    lattice with a fine one instead of reaching for a coarser one still --
    a single 8px blob per cell IS the repeat, and the eye finds it.
    """
    period = TILE // cell
    gx, gy = x // cell, y // cell
    fx = (x % cell + 0.5) / cell
    fy = (y % cell + 0.5) / cell
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)

    def corner(ix: int, iy: int) -> float:
        return noise(ix % period, iy % period, salt)

    top = corner(gx, gy) * (1.0 - fx) + corner(gx + 1, gy) * fx
    bottom = corner(gx, gy + 1) * (1.0 - fx) + corner(gx + 1, gy + 1) * fx
    return top * (1.0 - fy) + bottom * fy


PATCH_MIX = 0.58
"""How much of `_patch` is the FINE lattice rather than the coarse one.

Mostly fine, deliberately. A field built from the coarse lattice alone is
one blob per cell, and one blob per cell repeated across a lake IS the
sixteen-pixel repeat -- the eye finds the motif in about a second. Mixing a
2px lattice over a 4px one leaves patches you read as patches and a surface
you do not read as wallpaper.
"""


PATCH_JITTER = 0.22
"""How far a per-pixel hash ROUGHENS a `_patch` value before it is read.

The one defect `_patch` has is that it is SMOOTH, so a threshold on it draws
a blob with a clean boundary -- measured, 37 pixels of 256 on `snow` -- and
one dominant blob per cell IS the sixteen-pixel repeat. Roughening the value
first breaks that boundary into grit.

It is not enough on its own, and that is worth saying because it was tried:
percolation does not care about a ragged edge, so a field thresholded at a
quarter is connected at any scale that fits in a cell. `_mottle` therefore
does not threshold at all any more (`#TAG:mottle_is_a_stipple`), and this is
left for `_ripplet`, whose contour is thin enough that a ragged one reads as
broken light rather than as a drawn curve.
"""


def _patch(x: int, y: int, salt: int) -> float:
    """The shared ground field: two lattices, fine over coarse, in [0, 1).

    ONE function rather than a copy per texture, because the scale of the
    patches is the whole character of an overhead surface and a sheet whose
    textures disagree about it has no character at all.
    """
    return (PATCH_MIX * _lattice(x, y, salt, 2)
            + (1.0 - PATCH_MIX) * _lattice(x, y, salt + 31, 4))


def _verify_lattice() -> None:
    """Refuse a `_lattice` that does not close at `TILE`.

    `_verify_textures` cannot see this. It compares a TEXTURE at (x, y)
    against the same texture at (x % 16, y % 16), and every texture built
    on this takes a per-pixel hash as well, so it is exempt by name as a
    hashed texture -- and its lattice would carry an off-period rhythm into
    a painted field with no assertion anywhere in its way. So the primitive
    is measured on its own, over a span of tiles in each direction.
    """
    for cell in (2, 4):
        for salt in (0, 7, 31):
            for y in range(-TILE, 2 * TILE):
                for x in range(-TILE, 2 * TILE):
                    here = _lattice(x, y, salt, cell)
                    there = _lattice(x % TILE, y % TILE, salt, cell)
                    if here == there:
                        continue
                    raise ValueError(
                        f"_lattice(cell={cell}) draws {here:.4f} at "
                        f"({x}, {y}) and {there:.4f} at "
                        f"({x % TILE}, {y % TILE}): its period does not "
                        f"divide the {TILE}px tile, so every texture built "
                        f"on it breaks at each cell border")


_verify_lattice()


def _relief(feature, x: int, y: int) -> int:
    """+1 on a raised pixel, -1 in its drop shadow, 0 on flat ground.

    THE one place a raised feature's shadow is placed, for every texture in
    every view. A pebble, a leaf, a clump of growth and a lifted flake of
    oxide all cast their shadow the same way and the same distance, because
    they all come through here; `SHADOW_OFFSET` says why the direction is a
    shared constant rather than a number each texture picks.

    `feature` is asked about the pixel one offset BACK, not forward, so the
    shadow lands on the far side of the thing casting it.

    ALONG THE TWO AXES, NOT ALONG THE DIAGONAL.       #TAG:shadow_is_two_steps
    This used to ask one question -- is the pixel at (x - ox, y - oy) a
    feature -- which puts the whole shadow on a single diagonal step. Two
    things were wrong with it and they are the same thing. `overhead` was
    already written the other way, testing (x + ox, y) OR (x, y + oy), so
    the rim of an island and the shadow of a pebble on the same sheet were
    different shapes. And a shadow that exists ONLY at 45 degrees is a
    grain: with the feature lattice made regular, `clump` measured 0.296 of
    directional bias against a 0.25 limit, and the lean was the shadow
    rather than anything in the texture. Asking both axes puts the shadow
    down the right side and along the bottom of a thing -- which is what a
    drop shadow looks like -- and the same texture measures 0.108.
    """
    if feature(x, y):
        return 1
    ox, oy = SHADOW_OFFSET
    if feature(x - ox, y) or feature(x, y - oy):
        return -1
    return 0


SPECK_CELL = 2
"""How big one scattered FEATURE is: a stone, a leaf, a chip, a flake."""

SPECK_SPREADS: dict[int, tuple[tuple[int, int], ...]] = {
    1: ((1, 0), (-1, 0), (0, 1), (0, -1)),
    2: ((1, 0), (-1, 0), (0, 1), (0, -1),
        (1, 1), (1, -1), (-1, 1), (-1, -1)),
    3: ((1, 0), (-1, 0), (0, 1), (0, -1),
        (1, 1), (1, -1), (-1, 1), (-1, -1),
        (2, 0), (-2, 0), (0, 2), (0, -2)),
}
"""How far a feature suppresses its rivals, and therefore HOW MANY there are.

The rarity knob, and it is a neighbourhood rather than a threshold on
purpose. A threshold does not work here: a cell that beats all four of its
neighbours already scores about 0.83 on average, so every bar under 0.6 is
inert and a texture asking for "sparse" by raising one would get exactly
the field it had. Measured on a 16px cell: spread 1 draws 40 feature pixels
of 256, spread 2 draws 28 and spread 3 draws 16.

EVERY ENTRY CONTAINS THE FOUR NEIGHBOURS, which is what makes `SPECK_LIMIT`
structural at any spread: two cells sharing an edge are in each other's
neighbourhood, so they cannot both be strict maxima.
"""

SPECK_LIMIT = SPECK_CELL * SPECK_CELL
"""How large one scattered feature may be, in pixels: exactly one cell.

Not a tolerance -- an identity. `_speck` suppresses a candidate that touches
a stronger one, so two features can never share an edge, and a stone stays a
stone. `_verify_specks` flood-fills the wrapped mask and holds it AT this
number, which is the assertion the sheet did not have.
"""


def _speck(x: int, y: int, salt: int, spread: int) -> bool:
    """Is this pixel part of a scattered feature -- one 2x2 stone, leaf, chip?

    THE ONE PLACE A HASH BECOMES DISCRETE THINGS.       #TAG:one_feature_lattice
    Every texture that scatters objects over ground carried its own copy of
    `noise(x // 2, y // 2, salt) > t`, and every copy had the same defect --
    the shape CLAUDE.md's sibling warning describes. At any useful density a
    plain lattice puts neighbouring cells above the threshold, they fuse,
    and the fused shape comes back every sixteen pixels: `gravel` drew a
    three-block L the author named on sight, `chip` drew a camouflage plate,
    and `scatter` -- written to FIX the gravel L -- rebuilt it at forty-four
    pixels, worse than the thing it replaced. Measured over 64 salts, a
    square lattice at 0.78 fuses to 44 pixels and staggering the courses
    only reaches 36; neither of those is a stone.

    So the rule is not a threshold at all. A cell is a feature when its
    hash is STRICTLY GREATER THAN EVERY NEIGHBOUR'S in its spread. Two
    4-adjacent cells are always in each other's neighbourhood, so they
    cannot both win, so no two features ever share an edge and a component
    is exactly one cell -- 4 pixels, structurally, at every salt and every
    spread. Diagonal neighbours may both win, and two cells touching at a
    corner are a stone beside a stone rather than one long one.

    How many there are is `spread`: see `SPECK_SPREADS` for why the rarity
    is a neighbourhood and not a bar on the hash.
    """
    try:
        neighbours = SPECK_SPREADS[spread]
    except KeyError:
        raise ValueError(
            f"_speck was asked for spread {spread!r}, which is not one of "
            f"{sorted(SPECK_SPREADS)}; every rarity the sheet draws is "
            f"named there so `_verify_specks` can walk it, and an unlisted "
            f"one is a feature field nothing has ever flood-filled"
        ) from None
    period = TILE // SPECK_CELL
    gx, gy = (x // SPECK_CELL) % period, (y // SPECK_CELL) % period
    here = noise(gx, gy, salt)
    return all(here > noise((gx + dx) % period, (gy + dy) % period, salt)
               for dx, dy in neighbours)


def _wrapped_components(mask: list[list[bool]]) -> list[int]:
    """Sizes of the connected parts of a wrapped `TILE` x `TILE` mask.

    Wrapped, because the field a player sees is this cell repeated: a shape
    that runs off the right edge and back on at the left is ONE shape, and
    measuring it inside the cell alone is how a fused glyph reads as two
    small ones and passes.
    """
    seen = [[False] * TILE for _ in range(TILE)]
    sizes: list[int] = []
    for sy in range(TILE):
        for sx in range(TILE):
            if not mask[sy][sx] or seen[sy][sx]:
                continue
            seen[sy][sx] = True
            stack, size = [(sx, sy)], 0
            while stack:
                x, y = stack.pop()
                size += 1
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = (x + dx) % TILE, (y + dy) % TILE
                    if mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            sizes.append(size)
    return sizes


SPECK_SALTS = 64
"""How many salts `_verify_specks` walks.

A span rather than the whole space -- a terrain's salt is a 16-bit hash of
its name -- and a span is enough because the property is STRUCTURAL: a
construction that lost the local-maximum rule fails at almost every salt,
and one that keeps it cannot fail at any.
"""


def _verify_specks() -> None:
    """Refuse a `_speck` whose features fuse. The measurement that was missing.

    Four defects on these two sheets were found by LOOKING and none of them
    by an assertion: `gravel`'s L, `chip`'s plate, `_patch`'s dominant blob
    and `scatter`'s bar. All four are one shape -- neighbouring lattice
    cells fusing into a glyph that returns every sixteen pixels -- and this
    is the line that fires on it.

    BOTH HALVES. A `_speck` that drew nothing at all would satisfy any
    size limit, so the field also has to be POPULATED -- at least one
    feature in every cell, at every salt and every spread.
    """
    for salt in range(SPECK_SALTS):
        for spread in sorted(SPECK_SPREADS):
            mask = [[_speck(x, y, salt, spread) for x in range(TILE)]
                    for y in range(TILE)]
            parts = _wrapped_components(mask)
            if not parts:
                raise ValueError(
                    f"_speck(salt={salt}, spread={spread}) draws no feature "
                    f"anywhere in a {TILE}px cell; an empty field passes "
                    f"every size limit and draws bare ground")
            worst = max(parts)
            if worst <= SPECK_LIMIT:
                continue
            raise ValueError(
                f"_speck(salt={salt}, spread={spread}) draws a connected "
                f"feature of {worst} pixels, over the {SPECK_LIMIT} one "
                f"cell holds: neighbouring cells have fused, and a fused "
                f"shape repeats every {TILE} pixels forever -- which is "
                f"`gravel`'s L and `scatter`'s bar")


_verify_specks()


def _joint(px: int, py: int, size: int, height: int | None = None) -> int:
    """-1 in a laid surface's JOINT, +1 on the lit far wall of it, 0 inside.

    The RECESS counterpart of `_relief`, and the half of `SHADOW_OFFSET`'s
    job that nothing read. A raised thing throws its shadow one pixel ALONG
    the offset; a groove does the opposite -- its far wall is the one the
    sun reaches -- so a paver's joint and a pebble's shadow are two
    consequences of one sun and they are NOT the same expression.

    Every laid texture wrote that expression out by hand, and nothing made
    them agree: measured, reversing `SHADOW_OFFSET` moved 6 of the 19
    overhead textures and left `grout`, `rivet`, `mosaic` and `setts`
    exactly where they were. They happened to draw a consistent direction;
    nothing said they had to, and the next one would not have.

    So the joint sits at the cell's FAR index and the lit wall at the near
    index of the cell beyond it, both read off the offset. Flip the constant
    and every laid surface on the sheet turns round with every raised one --
    which is what `LIT_TEXTURES` asserts, over the whole vocabulary rather
    than over a hand-listed five.

    RECTANGULAR, BECAUSE A FORESHORTENED STONE IS.    #TAG:joint_is_one_sun
    `height` defaults to `size`, so every square caller reads exactly as it
    read before; a `beatemup` slab passes both, because a world-square stone
    drawn at k = 1/2 is 16 across and 8 down and its joint has to run round
    the rectangle it actually is. The alternative was a second function
    beside this one, which is the sibling mistake CLAUDE.md counts: two
    expressions of one sun, and reversing the constant would turn only one
    of them round. One function, one mutation, both red.
    """
    ox, oy = SHADOW_OFFSET
    height = size if height is None else height
    gap_x, wall_x = (size - 1, 0) if ox > 0 else (0, size - 1)
    gap_y, wall_y = (height - 1, 0) if oy > 0 else (0, height - 1)
    if px == gap_x or py == gap_y:
        return -1
    if px == wall_x or py == wall_y:
        return 1
    return 0


CRUST_CHILL = 0.72
"""How much colder than `shadow` the crust on something molten goes.

The one material whose INTERIOR needs more range than a five-shade ramp:
a coal's whole read is a cold skin broken by a hot core, and a ramp built
around a hot orange puts its darkest step at a warm brick red. Mixing that
step further toward the shared `SHADOW` violet is still one light source --
it is `Ramp`'s own arithmetic taken one step on -- where `Ramp.step(-3)`
raises, deliberately, so that nobody gets a sixth shade by accident.
"""


def _cold(material: Ramp) -> RGB:
    """One step colder than `shadow`: the crust between the hot parts."""
    return mix(material.shadow, SHADOW, CRUST_CHILL)



def _flat(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Nothing at all: glass, still metal, anything that wants to be a plane."""
    return m.base


def _dither(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """The 2x2 checker: half a shade at tile resolution."""
    return m.light if (x + y) % 2 == 0 else m.base


def _wave(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Slow bands, offset in blocks of four: liquid at rest.

    The band period is EIGHT, not the six it used to be, and the reason is
    `_verify_textures`: six does not divide 16, so tiling put the band's own
    rhythm out of step at every cell border.
    """
    band = (y + 4 * ((x // 4) % 2)) % 8
    if band == 0:
        return m.light
    if band == 4:
        return m.dark
    return m.base


RIPPLE_LIFT = (0, 1, 2, 2, 1, 0, -1, -1)
"""How far each column lifts `ripple`'s crest, over eight columns.

A crest that steps by a constant per column is a diagonal, and a diagonal at
this scale is corduroy -- which is what a 4px block offset drew. This bows
instead, and it closes: column 7 hands back to column 0 without a jump, which
is the same property `VEIN_DRIFT` needs and for the same reason.
"""


def _ripple(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """`wave` with a crest that bows across it: liquid catching the light."""
    band = (y + RIPPLE_LIFT[x % 8]) % 8
    if band == 0:
        return m.hi
    if band == 1:
        return m.light
    if band == 4:
        return m.dark
    return m.base


def _brick(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Running bond: 8x4 courses, every other one offset by half."""
    row = y // 4
    offset = 4 * (row % 2)
    if y % 4 == 3 or (x + offset) % 8 == 7:
        return m.shadow
    return m.base


def _grout(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """A square grid of 8px tiles, jointed on the far edge: laid floor.

    Through `_joint`, so the joint and its lit far wall are read off
    `SHADOW_OFFSET` instead of written out here. The phase moved by one
    pixel when it was: the joint used to sit at index 0 and the highlight at
    index 1, which is the same picture a pixel over, and the same picture
    only while nobody ever turns the sun round.
    """
    seam = _joint(x % 8, y % 8, 8)
    if seam < 0:
        return m.shadow
    if seam > 0:
        return m.light
    return m.base


def _plank(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Boards eight deep, nailed down, which is what `grain` has not got.

    Five deep was the obvious number and the wrong one: it does not divide
    16, so one board in three ran six rows and carried two highlight rows,
    at a fixed pitch down every painted field. Eight does divide it.

    The end joints went with it. A joint can only recur at the tile's own
    period, so a board that shows one is 16 pixels long and 8 deep, which is
    a brick's aspect and reads as brickwork. Two nail heads read as a floor
    somebody laid; a board with no visible end reads as a long one.
    """
    board = (y % (2 * 8)) // 8
    if y % 8 == 7:
        return m.shadow
    if y % 8 == 0:
        return m.light
    if y % 8 == 2 and x % 16 in (2 + 8 * board, 13 - 8 * board):
        return m.shadow
    if y % 8 in (3, 5) and (x + 5 * board) % 8 < 3:
        return m.dark
    return m.base


def _crosshatch(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Two diagonals actually crossing: worked stone, engraving, scree.

    The counter-diagonal is `shadow`, not `dark`: at one shade apart the two
    families read as one set of stripes, which is a lattice nobody can see.
    """
    if (x + y) % 4 == 0:
        return m.light
    if (x - y) % 4 == 0:
        return m.shadow
    return m.base


def _weave(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Over and under in 2px blocks: cloth, rush matting, carpet."""
    if ((x // 2) + (y // 2)) % 2 == 0:
        return m.light if y % 2 == 0 else m.base
    return m.dark if x % 2 == 0 else m.base


VEIN_DRIFT = (0, 0, 1, 1, 2, 2, 3, 3, 3, 3, 2, 2, 1, 1, 0, 0)
"""How far a vein leans at each row of a tile. A CLOSED walk, not a hash.

It has to come back to where it started -- 0 at row 0 and 0 at row 15 -- or
the vein snaps sideways at every cell border. The version before this one
drifted with `2 * ((y // 3) % 3)`, whose period is 36: marble seamed on both
axes, and the staircase read as corduroy rather than as stone.
"""


def _vein(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """One bright vein that WANDERS, and one dark one half a tile away.

    Sparse on purpose. A line every nine pixels is a lattice; two lines in
    sixteen is a piece of marble.
    """
    lean = VEIN_DRIFT[y % 16]
    if (x + lean) % 16 == 0:
        return m.hi
    if (x + lean) % 16 == 1:
        return m.light
    if (x + VEIN_DRIFT[(y + 8) % 16]) % 16 == 8:
        return m.dark
    return m.base


RIVETS: tuple[tuple[int, int], ...] = ((4, 4), (11, 4), (4, 11), (11, 11))
"""Where the four studs of a bolted panel sit inside a 16px cell."""


def _rivet(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """A bolted panel: a seam round the cell, a lit inner edge, four rivets.

    `flat` plus `square` was a featureless grey rectangle -- a terrain with
    no interior at all, which is the one thing a 16px tile cannot afford.

    Both kinds of light on it now come from the one constant. The seam is a
    RECESS and goes through `_joint`; the studs are RAISED and go through
    `_relief`, which is why their shadow is no longer the hand-written
    (5, 5) that happened to agree with `SHADOW_OFFSET` and would not have
    moved with it.
    """
    px, py = x % 16, y % 16
    seam = _joint(px, py, 16)
    if seam < 0:
        return m.shadow
    if seam > 0:
        return m.light
    stud = _relief(lambda sx, sy: (sx % 16, sy % 16) in RIVETS, px, py)
    if stud > 0:
        return m.hi
    if stud < 0:
        return m.shadow
    return m.base


CRACK_LINES: tuple[tuple[int, int], ...] = (
    # Four short splits that all stop INSIDE the cell: two running mostly
    # across, two mostly down, wandering both ways so neither pair leans.
    (2, 3), (3, 3), (4, 2), (5, 2), (6, 3), (7, 3), (8, 4), (9, 4),
    (10, 3), (11, 3), (12, 2),
    (13, 6), (13, 7), (12, 8), (12, 9), (13, 10), (13, 11), (12, 12),
    (3, 7), (3, 8), (4, 9), (4, 10), (3, 11), (3, 12), (4, 13),
    (6, 12), (7, 12), (8, 13), (9, 13), (10, 12),
)
"""Where `crack` splits. Drawn by hand, because a hash draws gravel.

TWO EACH WAY, AND NOT ONE OF THEM REACHES THE EDGE.    #TAG:cracks_run_both_ways
Two failures, and the second was the FIX for the first. The original set
was three chains ALL running down and to the right at roughly one across in
one-and-a-half down: tiled, three near-parallel lines repeating every
sixteen pixels is not a cracked plate, it is a diagonal stripe, and `ice`
was the tile the author picked out as banded.

What replaced it was four chains that each CLOSED ACROSS THE WRAP, two
each way -- and that bought the straightness by turning the tile into a
chain-link net. A chain that closes in x and another that closes in y cut
the tiled plane into bounded cells, so the plate stopped being a plate and
became a lattice of identical octagons, repeating exactly every sixteen
pixels. `clay` drew the same glyph and the two rows correlated at 0.89.

So: four SHORT splits, none of which touches the tile border at all. A
crack that stops inside the cell has no seam to line up with the next
cell's, the plate between them stays one open plate rather than a closed
cell, and a wandering profile keeps both perpendicular pairs balanced.
`_verify_cracks` holds all three: the lean, the no-border rule, and that
the splits are spread over the cell rather than heaped in one corner.

The pale sparkle went with it. It was `(px + py) % 6`, whose lines run at
135 degrees -- and six does not divide sixteen, so every one of them was
CUT at the cell border, which is the second half of the banding. It slipped
past `_verify_textures` because this function takes `x % 16` itself before
using it, so the guard compared a tile-local pixel against itself and could
not fail. The replacement is a hash, which has no direction and no period
to break.
"""

_CRACK = frozenset(CRACK_LINES)


def _crack_adjacency() -> dict[tuple[int, int], int]:
    """How many crack pixels touch another in each of four directions.

    The direct measurement of "which way do these lines run": a chain
    running down-right has its pixels adjacent along (1, 1) and hardly ever
    along (1, -1). Read on the WRAPPED tile, because that is how a painted
    field reads them.
    """
    return {step: sum(1 for (x, y) in _CRACK
                      if ((x + step[0]) % TILE, (y + step[1]) % TILE) in _CRACK)
            for step in ((1, 0), (0, 1), (1, 1), (1, -1))}


CRACK_BREAK = 0.22
"""How much of a crack pixel's run is actually drawn: a bit over three
quarters. Enough that the split still reads as one split, little enough that
its outline is not a shape."""

CRACK_GLINT = 0.55
"""The same for the lit wall, and thinner still, because a continuous
highlight beside a continuous dark line is what made the tile a glyph."""

CRACK_LEAN = 0.45
"""How far `crack`'s chains may favour one direction over its perpendicular.

Measured as |a - b| / (a + b) over the two perpendicular pairs of
`_crack_adjacency`. The set that shipped scored 0.75 on the diagonal pair
-- fourteen adjacencies down-right against two down-left -- which is what
`ice` reading as stripes actually was, in a number.

It is a SECOND rule and not `ISOTROPY_LIMIT` because the two measure
different things. `directional_bias` reads the finished picture, where the
cracks are a tenth of the pixels and the plate between them is the rest;
this reads the chains themselves, which is where the lean lives.
"""


CRACK_QUARTERS = 4
"""How many of the cell's four quarters a crack set has to reach.

All of them. A set heaped in one corner is one motif, and one motif per
cell is the wallpaper repeat this file spends its whole texture axis
avoiding -- so the splits have to be spread, and spread is measurable.
"""


def _verify_cracks() -> None:
    """Refuse a crack set that leans, touches the border, or heaps up.

    THREE HALVES, and the middle one replaced its own opposite.
    A set that leans draws stripes. A set whose chains END ON the tile
    border draws dashes, with a gap down every seam -- but the rule that
    used to be here demanded the opposite, that a chain CROSS the border,
    and a chain that crosses in x while another crosses in y cuts the tiled
    plane into closed cells. So the rule is now: a crack pixel may not sit
    on the border at all, which forbids the dash and the lattice together.
    And a set that passes both while sitting in one corner is still one
    motif, which is what the quarter count is for.
    """
    counts = _crack_adjacency()
    for first, second in (((1, 0), (0, 1)), ((1, 1), (1, -1))):
        a, b = counts[first], counts[second]
        if a + b == 0:
            raise ValueError(
                f"no crack pixel touches another along {first} or {second}: "
                f"this is a scatter of dots, not a network of splits")
        lean = abs(a - b) / (a + b)
        if lean > CRACK_LEAN:
            raise ValueError(
                f"crack chains run {first} {a} times and {second} {b} "
                f"times, a lean of {lean:.2f} over {CRACK_LEAN}; tiled, "
                f"near-parallel lines repeating every {TILE} pixels read as "
                f"a stripe and not as a cracked plate")
    edge = sorted((x, y) for (x, y) in _CRACK
                  if x in (0, TILE - 1) or y in (0, TILE - 1))
    if edge:
        raise ValueError(
            f"crack pixel(s) {edge[:4]} sit on the tile border; a split that "
            f"reaches the edge either stops dead there -- a dash down every "
            f"seam -- or closes across the wrap, and a chain closing in x "
            f"beside one closing in y cuts the tiled plane into a lattice of "
            f"identical cells, which is what `ice` and `clay` were")
    half = TILE // 2
    quarters = {(x // half, y // half) for (x, y) in _CRACK}
    if len(quarters) < CRACK_QUARTERS:
        raise ValueError(
            f"the crack set reaches only {len(quarters)} of the cell's "
            f"{CRACK_QUARTERS} quarters; splits heaped in one corner are one "
            f"motif, and one motif per cell is the repeat a player finds")


_verify_cracks()


def _crack(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """A pale plate split by fine dark lines, lit on the far side of each.

    Ice. `ripple` made it read as one more colour of water, which is the
    commonest way a cold tile fails.

    The lit side is `SHADOW_OFFSET` away, which is where this package puts
    the light: a split in a plate is a groove, and the far wall of a groove
    is the one the sun reaches.

    BROKEN, AND WITH NO BRIGHT HALO.                    #TAG:crack_is_not_traced
    Drawn solid, with `hi` down the whole lit wall, a split is an OUTLINE:
    a closed high-contrast shape the eye reads as one glyph and then finds
    again in every cell. That is what `ice` and `clay` both were. A real
    crack is not traced -- it is deep in places and closed in others, and
    the light catches parts of its wall. So both the split and its glint
    are thinned by a hash, which leaves the same splits in the same places
    and nothing for the eye to lock onto.
    """
    px, py = x % TILE, y % TILE
    if (px, py) in _CRACK and noise(px, py, salt + 2) > CRACK_BREAK:
        return m.shadow if noise(px, py, salt + 6) > 0.5 else m.dark
    ox, oy = SHADOW_OFFSET
    if ((((px - ox) % TILE, py) in _CRACK
         or (px, (py - oy) % TILE) in _CRACK)
            and noise(px, py, salt + 8) > CRACK_GLINT):
        return m.light
    return m.hi if noise(px, py, salt + 4) > 0.90 else m.base


def _speckle(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Loose grit: single pixels up and down, no structure."""
    value = noise(x, y, salt)
    if value < 0.10:
        return m.dark
    if value > 0.92:
        return m.light
    return m.base


def _grain(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Fibre running across: sawn wood, matted leaf litter.

    The hash takes the terrain's `salt`, which it used to ignore in favour
    of a literal 7 -- so `forest_floor` and `wood_floor` drew the identical
    fibre, 0.997 correlated on luminance, and differed only in colour.
    """
    if y % 4 == 0:
        return m.dark
    return m.light if noise(x // 3, y, salt + 7) > 0.72 else m.base


def _gravel(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Aggregate: stones in STAGGERED courses, with grit between them.

    The version this replaced classified a square 2x2 lattice at 0.20/0.80,
    which put about thirteen dark cells and thirteen light ones in each
    tile -- enough for neighbouring cells of one class to fuse into a
    three-block L, and the same L came back sixteen pixels later, forever.
    `dirt_path` showed it worst, because a pale ground carries a dark glyph
    best; the author named it on sight.

    The stagger this used instead was the RIGHT IDEA AND NOT ENOUGH, and
    the number says so: measured over 64 salts a square lattice at 0.78
    fuses to 44 pixels and the staggered one still reaches 36. Both stones
    now come through `_speck`, whose local-maximum rule makes a fused
    feature impossible rather than unlikely, and a second lattice at a
    different phase supplies the grit so no single grid of 2x2 blocks is
    the whole picture for the eye to find again.
    """
    if _speck(x, y, salt, 2):
        return m.hi if noise(x, y, salt + 3) > 0.5 else m.light
    if _speck(x, y, salt + 17, 2):
        return m.shadow
    grit = noise((x + 1) // 2, (y + 1) // 2, salt + 23)
    if grit < 0.16:
        return m.dark
    if grit > 0.88:
        return m.light
    return m.dark if noise(x, y, salt + 3) < 0.12 else m.base


def _tuft(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Blades standing in clumps, lit at the tip: living ground cover.

    Four rows to a blade, so the clump has a direction. `speckle` next door
    is the same idea with no direction at all, and a field of grass that
    reads as grit is the commonest way a green tile fails.
    """
    clump = noise(x, y // 4, salt)
    if clump > 0.78:
        return m.hi if y % 4 == 0 else m.light
    if clump < 0.16:
        return m.shadow
    return m.dark if noise(x, y, salt + 9) < 0.14 else m.base


def _crust(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """A dark skin broken by a bright core: molten rock, coals, flaked oxide.

    The only texture here that is deliberately BIMODAL -- most of the cell
    sits at or below the base and a small part of it runs to `hi`. That is
    what makes lava read as a liquid with a crust on it rather than as
    orange brickwork, and it is also what carries the hazard's luminance.
    """
    core = noise(x // 3, y // 3, salt)
    if core > 0.80:
        return m.hi
    if core > 0.66:
        return m.light
    if core < 0.30:
        return m.shadow
    return m.dark if noise(x, y, salt + 11) < 0.35 else m.base


# --------------------------------------------------------------------------
# Surfaces that work from EITHER view, and the three side rows they fixed
# --------------------------------------------------------------------------
# A texture is not owned by a view. A bolted plate, a flake of oxide and a
# speckled granite are the same thing whichever way you look at them, and
# `VIEWS` below names a SUBSET of this one vocabulary per view rather than a
# second vocabulary per view -- which is the shape that stops one view's fix
# growing while its sibling keeps the defect.


def _chip(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Small angular chips with fine grit between: rough cut stone.

    `stone` drew `dither` -- a 2x2 checker between `base` and `light`, which
    on a mid grey is twenty-two values of difference averaging back to
    nothing. At any distance it was a flat swatch, and the author called it
    unfinished beside blocks that had a surface.

    The first replacement was PLATES, cut from `_lattice` and jointed where
    the plate index changed, and it was the `dirt_path` mistake again in a
    new place: a four-by-four lattice has only sixteen cells in a tile, so
    the plates fused into one motif and the same motif came back every
    sixteen pixels. It measured 0.21 for directional bias and looked like
    camouflage. Chips two pixels across, classified in three close tones
    with per-pixel grit over them, have no motif to find; the bias is 0.01
    and a field of it reads as rock. The classification is `_speck`'s, so
    the plate cannot come back: on `marble`, the ramp with the most contrast
    to spend, the old lattice still fused a bright run of thirty-eight
    pixels across the cell.

    Close tones on purpose. Stone is not high contrast, it is textured, and
    the difference between this and `gravel` is exactly that: `gravel` runs
    from `shadow` to `hi` because it is loose stones with air between them,
    and this stays near the base because it is one piece of rock.
    """
    grit = noise(x, y, salt + 5)
    if _speck(x, y, salt, 2):
        return m.hi if grit > 0.4 else m.light
    if _speck(x, y, salt + 13, 3):
        return m.dark if grit < 0.6 else m.base
    if grit < 0.13:
        return m.dark
    if grit > 0.88:
        return m.light
    return m.base


def _fleck(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Single-pixel flecks up and down from the body: granite, worked stone.

    Two flecks dark and two light, at about a quarter of the cell each, with
    no structure between them at all. That is what granite IS at this size --
    `crosshatch` drew it as an engraved lattice and the author read the
    result as mauve upholstery.
    """
    value = noise(x, y, salt)
    if value < 0.14:
        return m.shadow
    if value < 0.26:
        return m.dark
    if value > 0.90:
        return m.hi
    if value > 0.76:
        return m.light
    return m.base


def _flake(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Bright oxide lifting off a DARK corroded ground: rust.

    `rusted_plate` drew `crust`, which is bimodal the other way up -- most
    of the cell at or above the base and a small part running dark. On a
    tan-orange ramp that is a desert, and the author said so: "rusted reads
    as warm tan".

    So the ground here is the dark half and the flakes are the bright one,
    each lifted flake carrying its own shadow through `_relief` like every
    other raised thing on either sheet. Turning the bimodality over is the
    whole change; the palette moved with it, to a stronger oxide orange.

    The scabs are TWO PIXELS and sparse -- a `_patch` field put them at four
    and five and the plate read as autumn leaves. A quarter of the cell
    lifted, three quarters of it corroded dark, is the proportion that says
    rust rather than pattern.

    They come through `_speck` for the reason every scattered thing here
    does, and it is the fix for the second complaint about this tile as
    well: the scabs on the plain lattice ALIGNED, fusing along one diagonal
    into the chevron the reviewer called knitwear. A local maximum has no
    neighbour to align with.
    """
    def lifted(px: int, py: int) -> bool:
        return _speck(px, py, salt + 4, 1)

    relief = _relief(lifted, x, y)
    if relief > 0:
        return m.hi if noise(x, y, salt + 1) > 0.72 else m.light
    if relief < 0:
        return mix(m.shadow, SHADOW, 0.45)
    value = noise(x, y, salt + 6)
    if value < 0.42:
        return m.shadow
    return m.base if value > 0.94 else m.dark


COAL_CRUST = 0.80
"""How much of a `cinder` cell is cold crust rather than glowing core.

Over half, and that is the point. `embers` used `crust`, which puts most of
a cell at or above its base -- a bed of coals that is mostly ALIGHT is a
pool of lava, and next to `lava` itself the author read the difference as
"dark red weave" rather than as coals. A coal bed is mostly dark, with the
fire showing through the gaps.
"""


def _cinder(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """A cold crust broken by a hot core: coals, banked fire, clinker.

    The crust is `_cold`, one step past `shadow`, because a five-shade ramp
    built around a hot orange has no black in it and coals without black are
    lava. The core beneath it is `base` and `light`, and the crust casts its
    shadow the way every raised feature here does.

    Deliberately BIMODAL, which is also what carries the hazard's luminance:
    a terrain a body must not stand on has to separate from every floor for
    a player who cannot see red, and brightness is the axis colour blindness
    does not take away.
    """
    def crust(px: int, py: int) -> bool:
        return _patch(px, py, salt) < COAL_CRUST

    relief = _relief(crust, x, y)
    if relief > 0:
        return _cold(m) if noise(x, y, salt + 2) > 0.22 else m.shadow
    if relief < 0:
        return m.hi
    value = noise(x, y, salt + 8)
    return m.light if value > 0.72 else (m.base if value > 0.34 else m.dark)


# --------------------------------------------------------------------------
# Surfaces for the view from ABOVE
# --------------------------------------------------------------------------
# What changes from the side set, in the author's own order. Nothing here
# lights a vertical face; nothing here has a dominant direction unless the
# direction MEANS something; nothing here is a silhouette seen edge-on. Grass
# is clumps of tops rather than standing blades, brick is pavers rather than
# a course, a stone is a lit top face with a shadow on one side rather than a
# shaded sphere.


def _mottle(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Damp and dry patches in bare soil, seen from above.

    The workhorse of an overhead ground sheet and the thing the side set has
    no equivalent of: from up there, dirt is not grain or speckle, it is
    AREAS of slightly different colour with grit scattered over them.

    A STIPPLE WHOSE DENSITY IS THE PATCH, NOT A PATCH.  #TAG:mottle_is_a_stipple
    The obvious construction -- threshold the smooth field, paint what is
    under it dark -- draws one solid blob with a clean boundary, 37 pixels
    of 256 on `snow`, and one dominant blob repeated across a field IS the
    sixteen-pixel repeat. The author sees a lattice of grey ticks on white.
    Roughening the boundary is not enough either: percolation says a field
    that dense is connected at any scale that fits in a cell.

    So `_patch` sets the ODDS instead. Every pixel is drawn dark or light
    or base by its own hash, and the patch only moves how likely that is --
    damp ground is dense stipple, dry ground is sparse. The area still
    reads as an area, and there is no shape in it to recognise: measured on
    the blurred field, structure falls from 3.44 to 1.82.
    """
    value = _patch(x, y, salt)
    grit = noise(x, y, salt + 3)
    if grit > 0.52 + 0.46 * value:
        return m.shadow if noise(x, y, salt + 7) < 0.30 else m.dark
    if grit < 0.50 * value - 0.06:
        return m.hi if noise(x, y, salt + 9) > 0.85 else m.light
    return m.base


RIPPLET_LEVEL = 0.56
"""The height a ripple's glint sits at, as a `_patch` value.

Just above the middle of the field, so the contour is a long wandering
line rather than a ring round the one highest point -- which is what makes
it read as light travelling over water rather than as a blob of foam.
"""


def _ripplet(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Broad irregular ripple: water seen from above, going nowhere.

    Not `wave` and not `ripple`. Both of those are BANDS, which is what a
    body of water looks like from the shore, with a horizon behind it. From
    directly above there is no horizon and no swell, only patches of light
    where the surface happens to be tilted -- so the crest here is a closed
    patch, and the only thing left with a direction is `current`, which has
    one on purpose.

    A CONTOUR, NOT A CAP.                             #TAG:light_is_where_it_tilts
    Filling everything above a threshold drew one closed paisley per cell,
    and `swamp` and `water` drew the IDENTICAL one -- 0.98 correlated --
    so the pair read as a printed repeat rather than as two bodies of
    water. It is also wrong about water: from above you do not see the
    tops of the swell lit, you see a glint where the surface TILTS, which
    is the contour of the height field and not its cap. So the highlight
    is a thin band either side of `RIPPLET_LEVEL`, broken by a hash so it
    is a run of glints rather than a drawn curve, and the shaded troughs
    are stippled the way `_mottle` stipples. Measured on the blurred field,
    structure falls from 3.48 to 1.95.

    The jitter also makes this a hash rather than a periodic field, which
    is why it moved out of `STRUCTURED_TEXTURES`: it no longer has a
    rhythm to hold to the cell.
    """
    value = _patch(x, y, salt) + PATCH_JITTER * (noise(x, y, salt + 21) - 0.5)
    crest = abs(value - RIPPLET_LEVEL)
    grit = noise(x, y, salt + 13)
    if crest < 0.030 and grit > 0.25:
        return m.hi
    if crest < 0.075 and grit > 0.45:
        return m.light
    if value < 0.36 and grit < 0.34 + 0.9 * (0.36 - value):
        return m.dark
    return m.base


def _clump(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Growth seen from ABOVE: the tops of clumps, not the stalks.

    The single most important row on the sheet and the clearest case the
    author made. `tuft` draws four-row blades standing up, which is grass
    photographed from ground level; from above you see the crowns, lit on
    top, with the gaps between them in shade. Same material, different
    thing entirely.
    """
    def crown(px: int, py: int) -> bool:
        return _speck(px, py, salt, 1)

    relief = _relief(crown, x, y)
    if relief > 0:
        return m.hi if noise(x, y, salt + 5) > 0.66 else m.light
    if relief < 0:
        return m.shadow
    return m.dark if noise(x, y, salt + 9) < 0.18 else m.base


def _grit(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Isotropic fines: sand, dust, ash, anything with no grain to it.

    `speckle`'s overhead twin, and near enough to it that the difference is
    worth stating: `speckle` is two-sided about the base, this is three, and
    the extra step at the top is the glint you get looking straight down at
    loose mineral.
    """
    value = noise(x, y, salt)
    if value < 0.13:
        return m.dark
    if value > 0.93:
        return m.hi
    if value > 0.84:
        return m.light
    return m.base


def _litter(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Fallen leaves and needles lying flat, each with its own shadow.

    `grain` is fibre running ACROSS -- a sawn board or matted litter seen
    edge-on -- and it is the most directional thing on the side sheet, at
    0.88. This is the same material with the camera moved: pieces lying at
    every angle, which averages to no angle at all.
    """
    def leaf(px: int, py: int) -> bool:
        return _speck(px, py, salt, 2)

    relief = _relief(leaf, x, y)
    if relief > 0:
        return m.light if noise(x, y, salt + 2) > 0.4 else m.hi
    if relief < 0:
        return m.shadow
    value = noise(x, y, salt + 9)
    return m.dark if value < 0.22 else (m.light if value > 0.93 else m.base)


def _scatter(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Loose stones on ground, each a lit top face and one short shadow.

    The author's fourth point, drawn: a rock from above is not a shaded
    sphere. It has a flat top catching the light evenly and a shadow on one
    side, and every stone on the sheet puts that shadow in the same place.

    IT DREW THE DEFECT IT WAS WRITTEN TO REPLACE.        #TAG:scatter_rebuilt_it
    This function was the top-down answer to `gravel`'s fused L, and it was
    `noise(px // 2, py // 2, salt) > 0.78` -- the same square lattice at a
    higher threshold. On `gravel`'s own salt it fused eleven stones into a
    forty-four pixel bar that crossed the whole cell, against the thirty-six
    of the construction it replaced: the fix did not travel, it regressed,
    and nothing on the sheet measured a glyph. `_speck` is that fix made
    structural and `_verify_specks` is the measurement.
    """
    def stone(px: int, py: int) -> bool:
        return _speck(px, py, salt, 2)

    relief = _relief(stone, x, y)
    if relief > 0:
        return m.hi if (x % 2 == 0 and y % 2 == 0) else m.light
    if relief < 0:
        return m.shadow
    return m.dark if noise(x, y, salt + 7) < 0.12 else m.base


def _board(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """A laid floor seen from ABOVE: boards with a JOINT, not a lit edge.
    DELIBERATELY DIRECTIONAL.

    `plank` is the side sheet's board run and it stays there. What it draws
    is a bright row along the top of every board and a dark one along the
    bottom -- which is `mass`'s own rule, "lit on top, dark underneath", a
    vertical face catching overhead light, written into a texture. On a wall
    that is correct and it is what siding looks like. Carried onto the
    overhead sheet unchanged it was the single strongest wall cue left on
    it, measured at the largest lighting asymmetry of either sheet, and the
    isotropy exemption hid it: the exemption is about DIRECTION, and a floor
    somebody laid one way really does have one, so nothing ever looked at
    the lighting inside each board.

    From above, two boards meet in a GAP. There is no lit top edge, because
    there is no edge facing you -- the board's whole visible face is its
    flat top, evenly lit. So: one dark joint every eight rows, grain running
    along the board, and two sunk nail heads per board, staggered so the
    pair does not line up into a second rhythm across the run.
    """
    run = (y % (2 * 8)) // 8
    if y % 8 == 7:
        return m.dark
    if y % 8 == 3 and x % 16 in (2 + 8 * run, 13 - 8 * run):
        return m.shadow
    return m.light if noise(x // 3, y, salt + 7) > 0.80 else m.base


def _mosaic(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Small square tiles, 4px, lit on the near edge and grouted on the far.

    A laid floor from above. `grout` is the same idea at 8px, and the two
    differ by enough that a room floor and a courtyard are not one material.
    """
    seam = _joint(x % 4, y % 4, 4)
    value = noise((x // 4) % 4, (y // 4) % 4, salt)
    if seam < 0:
        return m.dark
    if seam > 0:
        return m.hi if value > 0.6 else m.light
    return m.hi if value > 0.72 else (m.base if value < 0.28 else m.light)


def _setts(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Small stones in staggered courses with wide dark joints: a paved road.

    The overhead answer to `brick`, and it exists because `grout` is not
    one. A brick COURSE seen face-on is a wall; the same brick seen from
    above is a paver, and a paver's joints are a quarter of what you see --
    `grout` puts 23% of a cell in joint and `brick` puts 48%, and a top-down
    sheet with only `grout` on it had no dark paving at all. `cobble` and
    `brickwork` were both a shade too close to something else for exactly
    that reason, and both cleared the moment this existed.

    Staggered by half a stone on alternate courses, with the period kept to
    4 across and 8 down so it still divides the tile -- the same rule
    `plank` was broken by.
    """
    shove = 2 * ((y // 4) % 2)
    px = (x + shove) % 4
    seam = _joint(px, y % 4, 4)
    value = noise(((x + shove) // 4) % 4, (y // 4) % 4, salt)
    if seam < 0:
        return m.shadow
    if seam > 0:
        return m.light if value > 0.80 else m.base
    return m.light if value > 0.92 else (m.dark if value < 0.45 else m.base)


FURROW_LIFT = (0.14, 0.099, 0.0, -0.099, -0.14, -0.099, 0.0, 0.099)
"""How far each column of a furrow tips the soil toward light or dark.

A CLOSED walk over eight columns, like `RIPPLE_LIFT` and `VEIN_DRIFT` and
for the same reason: column 7 hands back to column 0 without a jump, and
eight divides the tile, so a ploughed field does not carry a seam every
sixteen pixels.
"""


def _furrow(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Ploughed ground: soil TILTED into troughs and crests.
    DELIBERATELY DIRECTIONAL.

    Not a drawn line. Three versions of this drew the trench as a dark
    column one or two pixels wide, at a pitch of four and then of eight,
    and every one of them read as vertical planks -- at 16px a hard line
    every few pixels is a board, whatever it is called. What a ploughed
    field actually looks like from above is the SAME clodded soil as the
    field next to it, lit more on one side of each furrow than the other,
    so the mottle lines up in columns and nothing is a line at all.

    So the furrow is a bias ADDED TO `_patch` before it is thresholded:
    the clods are the same clods, and where they fall light or dark is
    what carries the direction.

THE AMPLITUDE WAS THE PICKET FENCE, NOT THE PITCH. #TAG:furrow_is_a_bias
    It was 0.26, against thresholds two tenths apart, so the lift did not
    bias the clods -- it DECIDED them, and a whole column came out one
    class. That is a drawn line after all, which is what the paragraph
    above says this construction exists to avoid, and the author read it
    as a picket fence. Widening the walk to sixteen columns only made the
    lines wider: the field went from a fence to a set of bands, and the
    blurred structure rose from 3.66 to 6.64.

    At 0.14 the lift tips the odds and the clods still decide, which is
    the whole idea. The pitch stays at eight because it is the pitch that
    LOOKS like ploughing at this size; measured, it scores 0.140 on the
    local operator, under the limit, and 0.497 on the whole-cell one, so
    the exemption is carried by `profile_bias` -- a furrow is a broad
    thing, and a broad thing is what a gradient cannot see.

    One of the three textures on the overhead sheet that is allowed a
    dominant direction, and it has one because a furrow IS a direction --
    somebody dragged a plough along it. `VIEWS` names it, `_verify_isotropy`
    exempts it BY NAME, and the same guard then asserts it actually exceeds
    the limit: an exemption for a texture that turned out isotropic is an
    exemption nobody needs and a row of the sheet wasted.
    """
    value = _patch(x, y, salt) + FURROW_LIFT[x % len(FURROW_LIFT)]
    if value < 0.26:
        return m.shadow
    if value < 0.42:
        return m.dark
    if value > 0.72:
        return m.light
    return m.base


def _current(m: Ramp, x: int, y: int, salt: int) -> RGB:
    """Streaks along the flow. DELIBERATELY DIRECTIONAL.

    Where water is going somewhere. The only reason a top-down sheet may
    draw a band at all: a river has a direction and hiding it would be the
    mistake, not showing it.

    A SHEAR, NOT A SET OF ROWS.                        #TAG:current_is_a_shear
    It used to key off `y % 4`, which puts a highlight on the same two rows
    of every cell for the whole width of the map: that is a venetian blind,
    and the author's word for it was blinds. Water moving does not draw
    rows, it draws a SHEAR -- each row slid a little further along than the
    one above it -- so the lane index is taken at `x + 2 * (y % 8)`, which
    leans the streaks over and breaks them across the cell. It still scores
    0.344 on the local operator, over the limit, so the exemption is still
    earned.
    """
    px, py = x % TILE, y % TILE
    lane = noise(((px + 2 * (py % 8)) // 3) % 8, (py // 4) % 4, salt)
    if lane > 0.78:
        return m.hi if noise(px, py, salt + 3) > 0.5 else m.light
    if lane > 0.62:
        return m.light
    if lane < 0.26:
        return m.dark
    return m.base


# --------------------------------------------------------------------------
# The foreshortened floor: a slab is DECLARED, and the renderer is held to it
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Slab:
    """One paved surface, declared by the SCREEN size of its stone.

    `w` and `h` are screen pixels and both divide `TILE`. The world stone is
    SQUARE, so `h / w` IS the view's foreshortening -- and that is the whole
    reason this is a record and not just another texture function.

    A STATISTIC ON A FINISHED CELL CANNOT STATE A RATIO. #TAG:ratio_is_declared
    Three were tried and all three are wrong, in three different directions.
    The edge-count ratio `E_x/E_y` returns 1/3 for an 8x4 stone AND for a
    16x8 one, which are both k = 1/2, because a slab has three bands down
    and two across. The period ratio `p_y/p_x` recovers the declaration on a
    BARE lattice and collapses to 1/1 the moment the stone carries per-stone
    colour variation, which every real paved floor does -- 2% of isotropic
    fines is enough. And `directional_bias`, the live continuous metric,
    answers 0.765 for a 16x8 and 0.835 for an 8x4 at the same declared
    ratio, while calling a 16x4 at a DIFFERENT ratio 0.915: no threshold
    separates those.

    So the ratio is DECLARED here, where `_verify_foreshortening` can read it
    off two integers that cannot lie about themselves, and everything that
    could still lie is held to `_slab_reference` -- an ORACLE written out of
    these six fields and `SHADOW_OFFSET` alone, compared with the drawn
    pixels. It shares no helper with the renderer, on purpose: the guard that
    stood here before rebuilt the lattice through the renderer's own
    `SLAB_PHASE` lookup and so compared the declaration with a second reading
    of the declaration. Measured, transposing two variables in `_slab_texture`
    made every floor draw a SQUARE stone at k = 1 -- the plan view this view
    exists to stop drawing -- and the whole pack still said GREEN.

    A DECLARED RATIO IS NOT A LEGIBLE ONE.            #TAG:ratio_is_not_legible
    Nothing below measures whether a viewer can SEE the camera in the stone,
    and nothing can: a 16x8 stone drawn beside a 16x16 and a 16x4 one reads
    as three tile proportions, not as one camera at three heights, because a
    real flagstone is often oblong and 2:1 on its own says nothing about
    where the eye is. What says it is the NEAR FACE (`front`, below) -- the
    front wall of the stone, which only a low camera sees at all. The ratio
    rule checks that the renderer draws what was declared; whether the
    declaration reads as depth is an art judgement, made by looking.

    `joint`, `front`, `units` and `rise` are the low-camera stone in four
    numbers. `joint` and `front` are ramp steps, not colours, and the bands
    they paint come out of `_joint`, which reads `SHADOW_OFFSET`: a slab does
    not get to choose which way the sun is. `units` is the groove's width in
    WORLD units and `rise` the stone's height above it, also in world units
    -- both are projected by `k` here rather than typed in screen pixels, so
    the 2px-away / 1px-across joint and the 2px near face are consequences of
    the camera instead of three numbers somebody liked.

    `grit` is isotropic fines scattered ON TOP and is deliberately OUTSIDE
    the ratio: it is what destroys any statistic taken on the drawn cell, so
    it is authored rather than measured, and the guard reads the lattice
    underneath it.
    """

    w: int
    h: int
    joint: int = -2
    """The ramp step in the groove between stones: a recess, so negative."""
    front: int = -1
    """The ramp step on the stone's NEAR FACE.

    IT USED TO BE A LIT LIP ON THE FAR EDGE.          #TAG:stone_has_a_near_face
    The first draft put `+1` at the stone's far index, which is a top face
    lit along its back edge -- the signature of a PLAN view lit from the
    upper left, and the reviewer's word for what it drew was "two walls of
    different brick meeting at a line" when a `side` wall was put above a
    `beatemup` floor in one frame. A low camera does not see a stone's back
    edge; it sees the front wall, standing between the top face and the
    groove. So the band moved to the near index and went DOWN a step, and
    the far edge is now the previous stone's groove -- a hairline recess.
    Negative, always: a wall facing the camera and away from an overhead sun
    is darker than the top it belongs to, on every material.
    """
    units: int = 2
    """How wide the groove is in WORLD units, before `k` compresses it."""
    rise: int = 2
    """How high the stone stands above its groove, in WORLD units."""
    grain: int = 8
    """How coarse the weathering on the TOP FACE is, in WORLD units.

    Projected like everything else here: a world-square patch of `grain`
    units draws `grain` across and `grain * k` down, so the patch lies in the
    plane the stone does. It is declared per floor and not shared, because
    the right answer is a fact about the material: `decking` wants ONE patch
    per stone, since a board has one colour along its length, and `flagstone`
    wants four, since a paving slab is weathered in patches. Measured, a
    `decking` at four patches per stone draws a chequerboard -- put a dock
    beside a plank wall in one frame and the floor reads as parquet while
    the WALL reads as the plank floor, which is the wrong way round.

    It must divide `TILE` on both axes after projection, or the patch grid
    strobes at the cell border for the same reason the stone would;
    `_verify_foreshortening` holds that.
    """
    grit: float = 0.0


FLOORS: dict[str, Slab] = {
    "flagstone": Slab(16, 8, joint=-1, front=-2, units=2, rise=2, grain=8,
                      grit=0.04),
    "paver": Slab(8, 4, joint=-2, front=-2, units=1, rise=1, grain=4,
                  grit=0.10),
    "decking": Slab(16, 8, joint=-1, front=-2, units=1, rise=1, grain=16,
                    grit=0.06),
    "treadplate": Slab(8, 4, joint=-1, front=-2, units=1, rise=2, grain=8,
                       grit=0.04),
}
"""The paved vocabulary, and it is TWO STONE SIZES because k = 1/2 allows two.

At `TILE = 16` a screen stone has to divide 16 on both axes (or the field
strobes), and it needs three bands down -- top face, near face, groove -- or
it is a stripe rather than a slab, so `h >= across + front + 1`. Enumerated
over the divisors of 16 that leaves k = 1 with three legal sizes (not a
foreshortening at all), k = 1/2 with two, k = 1/4 with one, and k = 1/8 and
below with NONE: they draw nothing. k = 1/2 is the only ratio that is both a
foreshortening and a vocabulary, which is why it is not a taste.

`flagstone` (16x8) is the workhorse and `paver` (8x4) is the accent.

THE SMALL STONE CARRIES A SMALLER WORLD JOINT.        #TAG:joint_is_world_width
`units` is 1 on all three of the small-budget floors and 2 on `flagstone`,
and that is the fix for measured corduroy. An 8-unit world stone with a
2-unit groove is 44% groove and 19% lip against 38% face, its face rectangle
is 5px by 2px, and FIVE of the thirty-two rows drew it: at 1x
`cobble_street`, `brick_walk`, `subway_platform`, `steel_deck` and
`live_rail` all read as corrugated siding rather than as paving. A 1-unit
groove leaves the same 8x4 stone at 12% groove, 22% near face and 66% top
face. It is a WORLD number and not a screen one, so the 2px-away /
1px-across cue survives wherever there is room for it and simply stops being
drawn where there is not, which is the only honest thing a 5px-wide stone
can say about depth.

AND THE SMALL STONE IS AN ACCENT, WHICH IS A TABLE FACT. The spec's own note
says `paver` must not be given a large area, and five of thirty-two rows is
not an accent. It is three now -- `cobble_street` and `brick_walk` on
`paver`, `live_rail` on `treadplate` -- because `subway_platform` is a
concrete platform (`chip`) and `steel_deck` a long plate (`decking`), which
is what those two materials are anyway.

Measured band budgets as declared: `flagstone` 23/22/55 groove/face/top,
`paver` 12/22/66, `decking` 6/12/82, `treadplate` 12/44/44.

THE NAMES ARE NOT THE SPEC'S. The design pass called these `sett`, `board`
and `tread`; `board` is already a registered hashed texture and `setts` is
already a registered structured one, and two textures called `sett` and
`setts` in one registry is a typo that picks the wrong surface silently.
Live names win over a document's.
"""

SLAB_PHASE: dict[int, tuple[tuple[int, ...], tuple[int, ...]]] = {
    size: (tuple(i % size for i in range(TILE)),
           tuple(i // size for i in range(TILE)))
    for size in (4, 8, 16)
}
"""For each legal stone size: which pixel of a stone, and which stone, per
tile column or row.

PRECOMPUTED SO THE ONLY MODULUS IN A SLAB'S BODY IS `% TILE`.
`tools/check_art_tilesets.py` reads the ARITHMETIC of every texture out of
its own source and refuses a modulus that does not divide the tile -- and
refuses one it cannot resolve, deliberately, because an unauditable modulus
is the only kind worth hiding a period in. A closure over `slab.w` is exactly
that unauditable modulus. Indexing a table by `x % TILE` says the same thing
in arithmetic the check can read.
"""

"""A PAVED FIELD IS STONES, AND A 16-WIDE STONE IS ONE STONE.
                                                    #TAG:face_grain_divides
The face shade used to be `noise(stone_x, stone_y)` -- one value per stone --
and the docstring said that made "a paved field stones rather than a grid".
Measured, that is true of the 8-wide floors (2x4 = 8 stones in a cell) and
FALSE of the 16-wide ones: at `w = TILE` there is exactly one stone column
per tile, so `flagstone` and `decking` had TWO face shades in the entire
world, alternating on a fixed 16px period. `warehouse_floor` kept 6.32 of L*
through the repeat blur and `subway_tile` 6.96, against a `REPEAT_LIMIT` of
2.45 they are exempt from -- five rows of hard light/dark striping that no
rule could see, because `REPEAT_LIMIT` only runs over `HASHED_TEXTURES`.

So the shade is taken per weathering PATCH, the patch is `Slab.grain` world
units square, and how many patches a stone gets is the material's own
decision rather than one number for all four floors. It does NOT abolish the
16px repeat -- nothing structured at this tile size can, and claiming
otherwise is how the last claim got written -- it lets a slab break its
course up and lets a board stay one board, and `grit` scatters isotropic
fines over both.
"""

FACE_SPREAD = 0.82
"""How often a weathering patch leaves the base shade, as a noise threshold.

A patch is `light` above this and `dark` below its complement, so 0.82 leaves
64% of a top face at the material's own base colour. It used to be 0.72,
which moves 56% of the face and -- measured at 1x on a 20x12 field of
`sidewalk` -- turns a pale pavement into a waffle: the patch noise lands at
the same scale as the joint lattice and the two read as one weave. The face
is meant to be weathering ON a stone, so most of the stone has to still be
the stone.
"""


def _slab_joint(slab: Slab) -> tuple[int, int]:
    """The groove's screen width: (running AWAY, running ACROSS), in pixels.

    THE JOINT'S OWN WIDTH IS FORESHORTENED TOO.      #TAG:joint_width_carries_k
    This is the cue the first draft of this sheet did not draw, and without
    it a field of 16x8 stones reads as a plan view of bathroom tiles -- which
    is exactly the picture the view exists to stop drawing. A world joint of
    `units` width, cut into a plane compressed by `k` in DEPTH, draws its
    full width where it runs AWAY from the camera and `k` times that where it
    runs ACROSS: at k = 1/2 and a 2-unit joint, two pixels down the screen
    and one across it. So the lines running away are the heavy ones, which is
    the oldest depth cue there is, and it is DERIVED from the same `k` the
    stone's aspect is rather than chosen to look nice.

    AND IT IS ALLOWED TO VANISH ACROSS.            #TAG:across_joint_can_vanish
    Rounded DOWN, not up and not clamped. A 1-unit groove at k = 1/2 projects
    to half a pixel across, and the honest thing to draw is nothing: at a low
    enough angle the stone in front occludes a narrow groove entirely, and
    what separates one course from the next is then the front wall of the
    stone behind it (`Slab.front`), which is the correct thing for it to be.
    Measured, that is the difference between paving and masonry on the 8x4
    floors -- a 1px black line every four rows across a 16px cell is a mortar
    course, and five of the thirty-two rows read as a brick WALL with it.
    There is no `max(1, ...)` here pushing an illegal declaration through as a
    plausible default (law 7): a stone whose bands do not fit its depth is
    refused by `_verify_foreshortening`, which names the budget that did not
    add up, and a stone with no near face either would have nothing left to
    separate its courses at all.
    """
    return slab.units, slab.units * slab.h // slab.w


def _slab_grain(slab: Slab) -> tuple[int, int]:
    """The weathering patch's screen size: (across, down), in pixels.

    `Slab.grain` is a world square, so it draws its full width across and `k`
    times that down, exactly as the groove and the stone do.
    """
    return slab.grain, slab.grain * slab.h // slab.w


def _slab_front(slab: Slab) -> int:
    """How many screen rows of NEAR FACE the stone shows, from `rise` and `k`.

    The same projection `palette.NEAR_FACE` is derived by, one scale down: a
    world height `H` seen at a pitch of `asin k` draws `H * cos(asin k)`
    screen rows, which is `H * sqrt(1 - k*k)`. At k = 1/2 a 2-unit flagstone
    shows 1.73 -> 2 rows and a 1-unit paver 0.87 -> 1. The geometry picks the
    number; nobody types it.
    """
    k = slab.h / slab.w
    return round(slab.rise * math.sqrt(1.0 - k * k))


def _slab_band(slab: Slab, sx: int, sy: int) -> int:
    """Which band of its stone pixel (sx, sy) is in: -1 groove, +1 near face,
    0 top face.

    Three bands running down the stone -- top face, near face, groove -- and
    two across it, face and groove. Going DOWN the screen that reads top,
    front wall, gap, top, front wall, gap, which is what a low camera sees of
    a paved plane; there is no lit band anywhere, because the one edge a plan
    view lights is the one a low camera cannot see (`Slab.front`).

    The sun still decides WHICH SIDE the gap is on -- `_joint` answers that,
    once, and is called per axis here with the other axis parked on index 1,
    a face index for every legal stone. `k` decides only how wide the gap is
    and how deep the face is; `_slab_joint` and `_slab_front` do that, and
    both read the declaration rather than a screen number.

    ONE function, and both readers use it: `_slab_lattice` measures it and
    `_slab_texture` colours the lattice `_slab_lattice` built. There is no
    second copy of this arithmetic in the drawing path at all -- the one
    other expression of it in this file is `_slab_reference`, which belongs
    to the guard and exists precisely in order to disagree with this one.
    """
    w, h = slab.w, slab.h
    away, across = _slab_joint(slab)
    front = _slab_front(slab)
    inward = 1 if SHADOW_OFFSET[0] > 0 else -1
    downward = 1 if SHADOW_OFFSET[1] > 0 else -1
    if any(_joint(sx + step * inward, 1, w, h) < 0 for step in range(away)):
        return -1
    if any(_joint(1, sy + step * downward, w, h) < 0
           for step in range(across)):
        return -1
    if any(_joint(1, sy + step * downward, w, h) < 0
           for step in range(across, across + front)):
        return 1
    return 0


def _slab_lattice(slab: Slab) -> list[list[int]]:
    """One tile of a slab's BAND CODES, [x][y]: -1 groove, +1 near face, 0 top.

    The bare lattice, with no colour variation and no grit on it. This is
    what `_lattice_period` measures, what `_verify_foreshortening` holds to
    the declaration, and -- since the duplicate was collapsed -- what
    `_slab_texture` actually colours, so there is exactly ONE lattice in the
    drawing path rather than a drawn one and a measured one.
    """
    across, _ = SLAB_PHASE[slab.w]
    down, _ = SLAB_PHASE[slab.h]
    return [[_slab_band(slab, across[x], down[y])
             for y in range(TILE)] for x in range(TILE)]


def _lattice_period(lattice: list[list[int]]) -> tuple[int, int]:
    """The smallest (px, py) dividing `TILE` that the lattice repeats on.

    Divisors only, and that is not a shortcut: a period that does not divide
    the tile is not a period at all here, because the renderer blits the same
    16px cell everywhere and anything else restarts at the cell border.
    """
    def period(axis: int) -> int:
        for step in range(1, TILE + 1):
            if TILE % step:
                continue
            shifted = (lambda x, y: lattice[(x + step) % TILE][y]) if axis == 0 \
                else (lambda x, y: lattice[x][(y + step) % TILE])
            if all(lattice[x][y] == shifted(x, y)
                   for x in range(TILE) for y in range(TILE)):
                return step
        return TILE

    return period(0), period(1)


def _slab_texture(slab: Slab) -> Texture:
    """The ONE renderer every floor goes through, built from a declaration.

    It colours `_slab_lattice`'s bands and adds nothing structural of its
    own: the groove at `slab.joint`, the near face at `slab.front`, and the
    top face carrying a per-patch weathering shade (`Slab.grain`). The bands
    come from `_joint` by way of the lattice, so a slab turns round with
    every other laid surface on the sheet when `SHADOW_OFFSET` is reversed --
    which is why the four floors are in `LIT_TEXTURES`, and why one mutation
    of that constant reddens them all.

    The lattice is rebuilt per `SHADOW_OFFSET` and cached rather than
    captured at build time, deliberately: capturing it would freeze the sun
    inside the closure and `_verify_lighting`'s reversal would stop moving
    these four textures, which is the assertion that says they read the
    constant at all.

    ONE function for all four floors, on purpose. The declaration is
    checkable and this is not, so the way to keep it honest is to leave
    exactly one thing that could draw something other than what was declared
    -- and then to hold that one thing to `_slab_reference`, pixel for pixel.
    """
    unknown = sorted({slab.w, slab.h} - set(SLAB_PHASE))
    if unknown:
        raise ValueError(
            f"a stone of {slab.w}x{slab.h} asks for the phase table(s) "
            f"{', '.join(str(size) for size in unknown)}, and this view's "
            f"stones are "
            f"{', '.join(str(size) for size in sorted(SLAB_PHASE))} -- the "
            f"sizes that divide the {TILE}px tile and leave three bands. A "
            f"KeyError here would say the same thing in a language nobody "
            f"reading the declaration speaks")
    cut, front, grit = slab.joint, slab.front, slab.grit
    wide, deep = _slab_grain(slab)
    cache: dict[tuple[int, int], list[list[int]]] = {}

    def texture(m: Ramp, x: int, y: int, salt: int) -> RGB:
        px, py = x % TILE, y % TILE
        lattice = cache.get(SHADOW_OFFSET)
        if lattice is None:
            lattice = cache[SHADOW_OFFSET] = _slab_lattice(slab)
        band = lattice[px][py]
        if band < 0:
            return m.step(cut)
        if band > 0:
            return m.step(front)
        if grit and noise(px * 3 + 1, py * 5 + 2, salt + 19) < grit:
            return m.dark
        value = noise(px // wide, py // deep, salt)
        return m.light if value > FACE_SPREAD else (
            m.dark if value < 1.0 - FACE_SPREAD else m.base)

    return texture


STRUCTURED_TEXTURES: dict[str, Texture] = {
    "flat": _flat,
    "dither": _dither,
    "wave": _wave,
    "ripple": _ripple,
    "brick": _brick,
    "grout": _grout,
    "plank": _plank,
    "crosshatch": _crosshatch,
    "weave": _weave,
    "vein": _vein,
    "rivet": _rivet,
    "crack": _crack,
    "mosaic": _mosaic,
    "setts": _setts,
    "furrow": _furrow,
    "current": _current,
    **{name: _slab_texture(slab) for name, slab in FLOORS.items()},
}
"""Textures with a RHYTHM, which `_verify_textures` holds to divide `TILE`.

The four floors are spread in from `FLOORS` rather than listed again, so
`VIEWS` still names a SUBSET of one vocabulary instead of carrying a second
one, and a floor that exists cannot be a floor nothing can draw."""

HASHED_TEXTURES: dict[str, Texture] = {
    "speckle": _speckle,
    "grain": _grain,
    "gravel": _gravel,
    "tuft": _tuft,
    "crust": _crust,
    "chip": _chip,
    "fleck": _fleck,
    "flake": _flake,
    "cinder": _cinder,
    "mottle": _mottle,
    "clump": _clump,
    "grit": _grit,
    "litter": _litter,
    "scatter": _scatter,
    "ripplet": _ripplet,
    "board": _board,
}
"""Textures with no rhythm to break. Named here, and EXEMPT for that reason.

A hash of the pixel has no period, so asking one to repeat every 16 pixels is
asking it to stop being a hash. Each one is exempt because it is listed here,
not because it quietly failed to be caught.
"""

TEXTURE_FNS: dict[str, Texture] = {**STRUCTURED_TEXTURES, **HASHED_TEXTURES}

TEXTURES = tuple(TEXTURE_FNS)


def _verify_textures(
        structured: dict[str, Texture] = STRUCTURED_TEXTURES) -> None:
    """Refuse a structured texture whose period does not divide `TILE`.

    `quadrant` draws ONE 16px cell and the renderer blits that same cell
    everywhere, so what a painted field shows at global (X, Y) is the texture
    evaluated at (X % 16, Y % 16). A texture whose own rhythm has a period of
    six therefore breaks at every cell border: the band that should have been
    two rows further on starts again, and the field carries a hard line every
    sixteen rows. It looks like a grid somebody drew on the floor.

    Exact, not a threshold -- the texture drawn in tile-local coordinates has
    to BE the texture drawn in global ones, over a span of tiles in every
    direction.

    What this cannot see: a pattern whose period divides 16 but whose SHAPE
    does not line up across the wrap -- a diagonal that restarts. That is why
    `VEIN_DRIFT` is a closed walk, and why the sheet still gets looked at.
    """
    probe = ramp("stone")
    for name, fn in structured.items():
        for y in range(-TILE, 3 * TILE):
            for x in range(-TILE, 3 * TILE):
                if fn(probe, x, y, 7) == fn(probe, x % TILE, y % TILE, 7):
                    continue
                raise ValueError(
                    f"texture {name!r} draws a different pixel at "
                    f"({x}, {y}) than at ({x % TILE}, {y % TILE}), so its "
                    f"period does not divide the {TILE}px tile; tiled, its "
                    f"own rhythm breaks at every cell border and the field "
                    f"carries a hard line every {TILE} pixels")


_verify_textures()


def texture_fn(name: str) -> Texture:
    """The named texture. Raises rather than falling back to the base colour."""
    try:
        return TEXTURE_FNS[name]
    except KeyError:
        raise ValueError(
            f"no texture {name!r}; this module draws "
            f"{', '.join(sorted(TEXTURE_FNS))}") from None


# --------------------------------------------------------------------------
# The view axis: which way the camera is, and therefore what a surface IS
# --------------------------------------------------------------------------

ISOTROPY_SPAN = 4
"""How many tiles across `directional_bias` reads a texture.

Four, so the measurement sees the texture REPEATED rather than seeing one
cell. A band that restarts at each border and a band that runs through are
the same picture inside one tile and different pictures across four.
"""

ISOTROPY_PAIRS: tuple[tuple[tuple[int, int], tuple[int, int]], ...] = (
    ((1, 0), (0, 1)),
    ((1, 1), (1, -1)),
)
"""The two PERPENDICULAR pairs a directional bias is measured over.

Pairs, not four separate directions, and that is the whole trick. Gradient
energy along a diagonal is not comparable with energy along an axis -- the
step is longer -- so comparing 0 against 90 and 45 against 135 compares
like with like, and a metric that never compares an axis with a diagonal
cannot be fooled by the step length.

It also gets the right answer about a GRID. `grout` and `mosaic` have
strong gradients along both axes and weak ones along both diagonals, which
is not a direction: pavers have no grain, they have joints. A metric
summing four directions and taking the spread would fail them, and a
top-down sheet with no laid floor on it is not a fix.
"""

ISOTROPY_LIMIT = 0.25
"""How far an overhead texture may favour one direction over its perpendicular.

0 is perfectly even and 1 is everything in one direction. Calibrated
against the side sheet rather than chosen from taste, and PRINTED BY THE
CHECK rather than transcribed -- `tools/check_art_tilesets.py` puts the top
four on stdout every run, because a number written down as measured that
nothing re-measures is the shape `CLAUDE.md`'s generated-vs-written table
exists to prevent. At the time the limit was set, on the drawn cell:

    grain 0.897  plank 0.804  board 0.498  vein 0.455  tuft 0.402
    brick 0.400  wave 0.352   current 0.344            <- the wall half
    crosshatch 0.293                                   <- the gap
    cinder 0.202  weave 0.186  ripple 0.143  furrow 0.140
    flake 0.134  scatter 0.096  chip 0.064  grout 0.011  flat 0.000

The gap runs from 0.202 to 0.293 and the limit sits in it. The top of the
list is exactly what the author named: horizontal courses, board runs and
wave bands reading as siding, strata and brickwork.

Two figures in the list this replaced were off by a tenth (`crosshatch`
0.33 for 0.29, `weave` 0.20 for 0.18) and they were the two that defined
the gap, because the list was measured on RAW coordinates -- see
`directional_bias`, which now reads the cell the renderer blits.
"""


def directional_bias(texture: Texture, material: Ramp, salt: int = 7,
                     span: int = ISOTROPY_SPAN) -> float:
    """How hard a texture leans in ONE direction, 0..1. Measured, not judged.

    Gradient energy -- the summed squared difference between a pixel and
    its neighbour one step along -- is computed in each of four directions
    over `span` tiles WRAPPED, then the two perpendicular pairs are compared
    as |a - b| / (a + b) and the worse pair is the score.

    On LUMINANCE rather than on raw channels, and ON THE CELL THE RENDERER
    BLITS: the texture is read at (x % TILE, y % TILE), because that is the
    field a painted map shows. It used to be read at raw coordinates, which
    is a different picture for every hashed texture -- `flake` measured
    0.167 raw and 0.247 drawn against a 0.25 limit, so the margin the rule
    reported was not the margin the player got.

    The material is the caller's. `_verify_isotropy` probes with one grey so
    that a texture is judged on its own structure, and `_verify_terrains`
    then measures the repeat on each row's OWN ramp and salt, which is where
    a low-contrast ramp earns its softer verdict.

    WHAT IT CANNOT SEE, said out loud because something has to be: this is
    a LOCAL measurement. A set of near-parallel lines whose own pixels are
    only weakly aligned still reads as a stripe once the tile repeats, and
    that is how `crack` scored 0.05 while `ice` was the tile the author
    picked out as banded. `CRACK_LEAN` is the second rule that catches it,
    and it measures the chains instead of the picture.
    """
    size = span * TILE
    lum = [[luminance(texture(material, x % TILE, y % TILE, salt))
            for y in range(size)] for x in range(size)]

    def energy(dx: int, dy: int) -> float:
        total = 0.0
        for x in range(size):
            for y in range(size):
                step = lum[x][y] - lum[(x + dx) % size][(y + dy) % size]
                total += step * step
        return total

    worst = 0.0
    for first, second in ISOTROPY_PAIRS:
        a, b = energy(*first), energy(*second)
        if a + b <= 0.0:
            continue
        worst = max(worst, abs(a - b) / (a + b))
    return worst


PROFILE_SALTS = 16
"""How many salts `profile_bias` averages over before it answers.

SIXTEEN, BECAUSE ONE IS NOISE.                        #TAG:profile_is_averaged
The operator compares sixteen column means with sixteen row means, and on a
HASHED texture those are sixteen samples of sixteen pixels each -- so a field
with no structure at all scores 0.2 or 0.3 by luck. That is not a rounding
error, it is the whole margin: measured, a `furrow` with its lift set to zero
-- a texture that has lost the direction its exemption is for -- scored 0.331
on one salt and would have kept the exemption. Averaged over sixteen it
scores 0.185 and loses it.

A structured texture's profile barely moves with the salt, so the averaging
costs it nothing; it is the hash that needs the samples.
"""

PROFILE_LIMIT = 0.26
"""How far a texture may lean under the GLOBAL operator, which is the second
one and exists because the first cannot see a broad feature.

`directional_bias` is a LOCAL measurement -- a pixel against its neighbour --
so a rhythm whose period is most of the cell barely registers on it: the
sixteen-wide `furrow` scores 0.152 there, under the limit, while a painted
field of it is unmistakably ploughed. `profile_bias` compares the spread of
the column means with the spread of the row means, which is the whole tile at
once, and answers 0.389 for the same texture.

Measured over `PROFILE_SALTS` salts, the two separate: the overhead textures
that declare no direction run from 0.000 to 0.214 (`setts`, whose staggered
courses are the nearest thing to a grain a paver has), and the three that
declare one score 0.306, 0.283 and 0.663. The limit sits in that gap, with
0.046 either side of it.

One number is not enough for both operators. A local gradient and a global
profile do not scale together -- `crosshatch` scores 0.283 locally and 0.000
on the profile, `ripple` scores 0.143 locally and 1.000 on it -- so each has
its own, read off its own distribution.
"""


def profile_bias(texture: Texture, material: Ramp, salt: int = 7) -> float:
    """How much more a texture varies down its columns than across its rows.

    The global companion of `directional_bias`, over the ONE cell the
    renderer blits. Column means and row means, spread against spread, as
    |a - b| / (a + b): a texture with a broad trough running down the tile
    has columns that differ and rows that do not, and this is the operator
    that sees it.

    It is deliberately NOT a replacement. It is blind to a crosshatch, which
    varies equally both ways and still has a grain, and it is noisy on a
    hash -- sixteen means of sixteen samples -- which is why it is averaged
    over `PROFILE_SALTS` salts and why its limit is its own number rather
    than the local one reused. `salt` is the FIRST of the salts it walks.
    """
    def spread(values: list[float]) -> float:
        mean = sum(values) / len(values)
        return (sum((value - mean) ** 2 for value in values)
                / len(values)) ** 0.5

    total = 0.0
    for step in range(PROFILE_SALTS):
        grid = [[luminance(texture(material, x % TILE, y % TILE,
                                   salt + 11 * step))
                 for x in range(TILE)] for y in range(TILE)]
        down = spread([sum(grid[y][x] for y in range(TILE)) / TILE
                       for x in range(TILE)])
        across = spread([sum(grid[y][x] for x in range(TILE)) / TILE
                         for y in range(TILE)])
        if down + across:
            total += abs(down - across) / (down + across)
    return total / PROFILE_SALTS


SHADOW_CONTRAST = 0.6
"""How far from the mean a pixel has to be to count as bright or dark, in
standard deviations, when `shadow_bias` asks which side the shadows are on."""

LIGHTING_TOLERANCE = 0.15
"""How much lighting a texture that declares none is allowed to have.

Read off the measured distribution: the nine overhead textures outside
`LIT_TEXTURES` score between 0.00 and 0.10, and the ten inside it score from
0.20 to 0.85. The limit sits in the gap.
"""


def shadow_bias(texture: Texture, material: Ramp, salt: int = 5) -> float:
    """Which side of a texture's bright pixels its dark ones sit on, -1..1.

    Positive means dark sits ALONG `SHADOW_OFFSET` from bright, which is a
    RAISED thing throwing a drop shadow. Negative means dark sits against
    the offset, which is a RECESS whose far wall is lit. Both are one sun
    and both are legal; what is not legal is a texture with a strong reading
    either way that has not said it is lit at all, because then nothing
    holds it to the shared direction and the next texture beside it will
    disagree.
    """
    grid = [[luminance(texture(material, x, y, salt)) for x in range(TILE)]
            for y in range(TILE)]
    flat = [value for row in grid for value in row]
    mean = sum(flat) / len(flat)
    spread = (sum((value - mean) ** 2 for value in flat) / len(flat)) ** 0.5
    hi = [(x, y) for y in range(TILE) for x in range(TILE)
          if grid[y][x] > mean + SHADOW_CONTRAST * spread]
    if not hi or spread == 0.0:
        return 0.0
    ox, oy = SHADOW_OFFSET

    def dark_at(dx: int, dy: int) -> int:
        return sum(1 for x, y in hi
                   if grid[(y + dy) % TILE][(x + dx) % TILE]
                   < mean - SHADOW_CONTRAST * spread)

    return (dark_at(ox, oy) - dark_at(-ox, -oy)) / len(hi)


LIT_TEXTURES = frozenset({
    # raised things, through `_relief`
    "clump", "litter", "scatter", "flake", "cinder",
    # laid things, through `_joint` -- `rivet` is both
    "grout", "mosaic", "setts", "rivet",
    # and a groove drawn by hand from the same constant
    "crack",
    # the four declared floors, all through `_joint` as well
    *FLOORS,
})
"""Every texture whose art is a function of `SHADOW_OFFSET`.

THE LIST IS THE ASSERTION, IN BOTH DIRECTIONS.    #TAG:lighting_is_declared
The guard that used to stand here reversed the constant and demanded that
all five `_relief` users change -- and it was green no matter what the other
fourteen did. Measured, they did plenty: `grout`, `rivet`, `mosaic` and
`setts` each wrote their own direction out by hand and did not move at all,
and `plank` carried the side sheet's lit-top-dark-bottom board straight onto
the overhead sheet.

So the rule runs over a view's WHOLE vocabulary. A texture named here must
change when the offset is reversed, which is only true if it read the
constant. A texture NOT named here must not change -- and must also measure
under `LIGHTING_TOLERANCE` on `shadow_bias`, which is the half that catches
the actual failure: a texture that hard-codes a direction does not move
either.
"""


@dataclass(frozen=True)
class View:
    """Which way the camera is, and everything that follows from it.

    ONE table names a view's whole say, for the reason the form and texture
    axes each have one: a lighting model here and a texture list somewhere
    else is two places to forget, and the thing that goes wrong -- an
    overhead sheet with one side-lit rim left on it -- is invisible per tile
    and obvious per field.

    A view chooses the LIGHTING MODEL and the SUBSET of the shared
    vocabularies it may draw with. It chooses nothing about geometry: every
    form, every mask and every border crossing is the same in both views,
    which is why the 6,656 border verdicts in
    `tools/check_art_tilesets.py` cover the second sheet without a line
    changing. A view is about SURFACE, not silhouette.
    """

    name: str
    shade: Callable
    """`(occupancy, material, texture) -> Surface`: `mass`, `overhead` or
    `lowangle`.

    A SHADER CANNOT CARRY A CAMERA ON A FULL CELL.     #TAG:shade_is_edges_only
    Measured over all 32 urban rows: shade one 16x16 all-true grid with each
    of the three and the three agree on 8,192 of 8,192 pixels. That is not a
    defect, it is what all three are FOR -- each of them writes nothing where
    the grid is false and treats a grid border as interior, which is the
    property that makes the alpha of every view identical and every autotile
    border verdict transferable. But it means a painted FIELD, which is
    almost entirely full cells, gets nothing at all from the shader: on a
    5x4-cell island everything `lowangle` adds over `overhead` is 159 pixels
    in one band along the near edge.

    So the camera is carried by the TEXTURE table, not here. `lowangle`'s
    near face is an EDGE cue and is honest about being one; the thing that
    says "low camera" across a filled street is the declared stone
    (`Slab`), its near face and its foreshortened joint. Do not reach for a
    fourth shader to fix a field -- there is nowhere on a full cell for it
    to draw.
    """
    textures: tuple[str, ...]
    """Every texture this view's table may name, and must between them use."""
    forms: tuple[str, ...]
    """The same for silhouettes."""
    isotropic: bool
    """Whether `ISOTROPY_LIMIT` is enforced on this view's textures at all.

    False for `side`, and that is not a loophole -- it is the finding. A
    horizontal course seen face-on is SIDING, and siding is what that sheet
    is for. The rule is about ground seen from above, so it is a property
    of the view and lives on the view.
    """
    family: str
    """Which set of MATERIALS this view draws, as opposed to which way the
    camera is.                                          #TAG:family_is_the_set

    `side` and `topdown` are both `"natural"`: ONE set of 32 materials seen
    two ways, so a map swaps between them and every gid still means what it
    meant -- which is exactly what `_verify_tables_agree` is protecting, and
    it is right to. `beatemup` is `"urban"`, a DIFFERENT 32, because a street
    is not a swamp under another lamp; and nobody swaps a street sheet for a
    swamp sheet by accident, because they are not two pictures of one thing.

    No default. A view that joined a family by falling into one is the
    silent repaint this field exists to prevent.
    """
    foreshortening: Fraction
    """How much the DEPTH axis is compressed in this view, as an exact ratio.

    `Fraction(1)` for a view that draws its plane square on, `Fraction(1, 2)`
    for `beatemup`, which is a cabinet oblique. A `Fraction` and never a
    float, because `_verify_foreshortening` compares it for EQUALITY against
    a declared stone's `h/w` -- two integers against two integers -- and
    `0.5` invites `0.4999999` into an assertion that has deliberately no
    threshold in it.
    """
    directional: tuple[str, ...] = ()
    """Textures exempt from the isotropy rule BY NAME, with a reason each.

    And asserted to EXCEED the limit, which is the half that is usually
    missing: an exemption list nobody checks is a list things get added to.
    """


DEFAULT_VIEW = "side"
"""What a `Terrain` that says nothing is. The sheet that already shipped."""

SIDE_TEXTURES = ("flat", "dither", "wave", "ripple", "brick", "grout",
                 "plank", "crosshatch", "weave", "vein", "rivet", "crack",
                 "speckle", "grain", "gravel", "tuft", "crust", "chip",
                 "fleck", "flake", "cinder")

TOPDOWN_TEXTURES = ("flat", "grout", "mosaic", "setts", "rivet", "chip",
                    "crack", "board", "mottle", "ripplet", "clump", "grit",
                    "litter", "scatter", "fleck", "flake", "cinder",
                    "furrow", "current")

BEATEMUP_TEXTURES = ("flagstone", "paver", "decking", "treadplate",
                     "flat", "chip", "crack", "mottle", "ripplet", "clump",
                     "grit", "litter", "scatter", "fleck", "flake", "cinder",
                     "current")
"""Seventeen, in THREE CLASSES each covered by exactly one rule.

The four floors carry the ratio and are held to it by
`_verify_foreshortening`; the twelve loose surfaces are held by the live
isotropy rule, unchanged, because gravel from a low angle really is
isotropic -- the foreshortening cue for a loose row comes from the SHADER
and not from its texture; and `current` is exempt by name and asserted to
exceed the limit, the live mechanism. `_verify_view_coverage` refuses a
texture in none of the three and a texture in two.

Cut from `topdown`'s list, each for one reason: `mosaic` and `grout` are
laid floors at k = 1 -- a square paver seen square on is the picture this
view exists to stop drawing -- `rivet` is an isotropic 16x16 lattice that
would read the same way, `furrow` is a field and not a street, and `board`
is replaced by `decking`, which declares its ratio instead of implying one.
"""

VIEWS: dict[str, View] = {
    "side": View(
        name="side",
        shade=mass,
        textures=SIDE_TEXTURES,
        forms=("square", "round", "lobed", "drip", "heave"),
        isotropic=False,
        family="natural",
        foreshortening=Fraction(1),
    ),
    "topdown": View(
        name="topdown",
        shade=overhead,
        textures=TOPDOWN_TEXTURES,
        forms=("square", "round", "lobed", "drip"),
        isotropic=True,
        family="natural",
        foreshortening=Fraction(1),
        directional=("furrow", "current", "board"),
    ),
    "beatemup": View(
        name="beatemup",
        shade=lowangle,
        textures=BEATEMUP_TEXTURES,
        forms=("square", "round", "lobed", "drip", "heave"),
        isotropic=True,
        family="urban",
        foreshortening=Fraction(1, 2),
        directional=("current",),
    ),
}
"""The three cameras.

WHY `heave` IS NOT IN THE OVERHEAD LIST AND `drip` IS  #TAG:gravity_forms_topdown
`heave` piles mass toward the top of a cell and `drip` sags it toward the
bottom. Seen from above there is no top and no bottom, so BOTH are wrong by
default and `heave` is simply cut: nothing about ground seen from overhead
rises northward, and a sheet where half the terrains lean north for no
reason is the silhouette version of the lighting mistake.

`drip` is kept for exactly the reason `current` is kept: a river HAS a
direction, and its bank is dragged downstream. It is drawn by the two
flowing rows and by nothing else, and the direction it leans is the same
direction `current` streaks, so the two agree about which way the water is
going. A directional form, like a directional texture, is legal only where
the direction means something.

WHY `beatemup` RESTORES `heave`, WHICH `topdown` CUT  #TAG:beatemup_has_a_north
Belt-scroll action; a cabinet oblique at k = 1/2, so screen_y is
`y0 - Y - k*Z` and the walking axis is unforeshortened. Ground seen from
straight above has no north, which is why `heave` is cut there -- but a
belt-scroll floor's north is AWAY. Mass piling toward the top of a cell is
mass heaped against the FAR side, which is rubble drifted at a wall and silt
at a dock edge, and a wall at the far edge with things heaped against it is
the genre's whole composition. `drip` keeps its meaning too, one plane
lower: a street is crowned, so water runs to the NEAR gutter.

AND WHY IT IS SPELLED `beatemup`. A view id is a file format string (law 8):
stable once referenced, never renamed, because a renamed one disarms every
map carrying it and looks like it working. `beltscroll` is the better name
for the camera -- a fishing minigame should not carry a token saying it is a
brawler -- and it loses anyway, because the author said beat-em-up and a
view nobody can grep for is a view nobody uses.
"""

FORESHORTENING: dict[str, Fraction] = {
    name: view.foreshortening for name, view in VIEWS.items()
}
"""Every view's depth compression, by name. DERIVED, so there is one of it.

The art is not the only thing that has to know `k`. A belt-scroll movement
behavior has to draw `dy_screen = k * dx_screen` or isotropic world movement
comes out twice too fast up the screen -- law 9's shape one level up, at 2x
instead of 16.7x and therefore even easier to mistake for working. That
behavior does not exist yet and is filed in `docs/NEXT.md`; when it lands,
law 2 says the constant moves into `scripts/` and this package imports it,
never the reverse. What must not happen in between is a second number
written down somewhere else, so this is a view of `VIEWS` and not a table
beside it.
"""


def view_of(name: str) -> View:
    """The named view. Raises rather than drawing the default's lighting.

    Falling back would be the worst possible failure here: an overhead
    terrain lit as a wall looks like art somebody drew, not like a bug.
    """
    try:
        return VIEWS[name]
    except KeyError:
        raise ValueError(
            f"no view {name!r}; this module draws "
            f"{', '.join(sorted(VIEWS))}") from None


def _verify_views(views: dict[str, View] = VIEWS) -> None:
    """Refuse a view whose vocabulary or exemption list is not real.

    Four ways this goes wrong and every one of them is silent: a view
    naming a texture nothing registered (which raises halfway through a
    sheet), a view exempting a texture it cannot draw, a view whose
    lighting model is the other view's, and -- the one that matters -- a
    DEFAULT that is not `mass`, which would move every pixel of a sheet
    that has already shipped.
    """
    if DEFAULT_VIEW not in views:
        raise ValueError(f"the default view {DEFAULT_VIEW!r} is not a view")
    if views[DEFAULT_VIEW].shade is not mass:
        raise ValueError(
            f"the default view {DEFAULT_VIEW!r} no longer shades with "
            f"`mass`; every terrain that says nothing about its view would "
            f"be relit, and the sheet in data/art/ has already shipped")
    seen: dict[int, str] = {}
    for name, view in views.items():
        if view.name != name:
            raise ValueError(f"view {name!r} calls itself {view.name!r}")
        unknown = sorted(set(view.textures) - set(TEXTURE_FNS))
        if unknown:
            raise ValueError(
                f"view {name!r} names the texture(s) "
                f"{', '.join(unknown)}, which nothing registered")
        unknown = sorted(set(view.forms) - set(FORMS))
        if unknown:
            raise ValueError(
                f"view {name!r} names the form(s) {', '.join(unknown)}, "
                f"which nothing registered")
        stray = sorted(set(view.directional) - set(view.textures))
        if stray:
            raise ValueError(
                f"view {name!r} exempts {', '.join(stray)} from the "
                f"isotropy rule and cannot draw them; an exemption for a "
                f"texture the view does not carry is a line nobody will "
                f"ever delete")
        if view.directional and not view.isotropic:
            raise ValueError(
                f"view {name!r} does not enforce isotropy and still lists "
                f"{', '.join(view.directional)} as exempt from it; an "
                f"exemption from a rule that is off reads as a rule")
        if id(view.shade) in seen:
            raise ValueError(
                f"views {seen[id(view.shade)]!r} and {name!r} shade with the "
                f"same function, so one of them is the other one under a "
                f"second name and the axis buys nothing")
        seen[id(view.shade)] = name


_verify_views()


Judgements = dict[str, dict[str, str]]
"""Per view, which RULE judged each texture -- recorded AT THE JUDGEMENT.

Every rule that measures a texture returns one of these, and
`_verify_view_coverage` asserts the merged ledger covers each view's
vocabulary exactly once. It is a LEDGER and not a set of predicates for one
measured reason: the rule that stood here scored coverage as
`(in floors) + (not in floors and not in directional) + (in directional)`,
whose middle term is the exact negation of the other two, so brute-forced
over every membership combination `covered` could only ever be 1 or 2 --
the "a surface nothing measures" half could not fire at all, and the check
that claimed to provoke it was exercising the `covered == 2` branch twice.
A rule that reports what it touched can report nothing, so the zero is
reachable the day somebody adds a `continue` to one of them.
"""


def _record(seen: dict[str, str], view: View, name: str, rule: str) -> None:
    """Note that `rule` judged `name` on this view, refusing a double entry.

    One rule judging one texture twice is a rule that lost track of its own
    domain, and it would otherwise cancel out against a missing rule
    elsewhere and leave the ledger looking complete.
    """
    if name in seen:
        raise ValueError(
            f"texture {name!r} in view {view.name!r} was judged by "
            f"{seen[name]} and then by {rule} in the same pass; a rule that "
            f"reports one texture twice hides a texture nothing reported")
    seen[name] = rule


def _merge_judgements(*ledgers: Judgements) -> dict[str, dict[str, list[str]]]:
    """Every rule's account of one sheet, side by side rather than summed."""
    merged: dict[str, dict[str, list[str]]] = {}
    for ledger in ledgers:
        for view_name, seen in ledger.items():
            rules = merged.setdefault(view_name, {})
            for name, rule in seen.items():
                rules.setdefault(name, []).append(rule)
    return merged


def _verify_isotropy(views: dict[str, View] = VIEWS,
                     floors: dict[str, Slab] = FLOORS) -> Judgements:
    """Hold every overhead texture under `ISOTROPY_LIMIT` -- and BOTH HALVES.

    Half one: a texture a view draws without exempting it must score under
    BOTH limits -- the local one and the whole-cell one, because a broad
    feature is invisible to a gradient. Half two: a texture a view EXEMPTS
    must score over at least one of them.

    The second half is the one that is normally missing, and it is not
    decoration. An exemption list is where a texture goes when somebody
    cannot get it under the limit, and once it is there nothing ever looks
    at it again -- so the list is only honest while being on it costs
    something. A `furrow` that quietly stopped drawing furrows would keep
    its exemption forever and the sheet would have a row of flat mud on it
    that every assertion agreed with.

    Returns its own `Judgements`: the names it actually applied a limit to,
    recorded where the limit is applied rather than derived from the
    arguments afterwards. That is what makes `_verify_view_coverage`'s
    "a surface nothing measures" half able to fire.
    """
    probe = ramp("stone")
    judged: Judgements = {}
    for view in views.values():
        seen = judged.setdefault(view.name, {})
        if not view.isotropic:
            # THE VIEW ITSELF IS THE JUDGEMENT.      #TAG:side_is_excused_once
            # `side` has said once, on the view, that this family of rules is
            # off for it, and that statement is `isotropic=False` with its own
            # paragraph. It is recorded here rather than skipped, so the
            # coverage rule reads an exemption somebody wrote down instead of
            # an absence it has to interpret.
            for name in view.textures:
                if name not in floors:
                    _record(seen, view, name, "the view's own exemption")
            continue
        for name in view.textures:
            if name in floors:
                # A DECLARED FLOOR IS THE OTHER RULE'S.   #TAG:slab_is_not_loose
                # A world-square stone drawn at k = 1/2 is 16 across and 8
                # down: it is anisotropic BY DECLARATION, and measuring it
                # here would mean either exempting it by name -- which is the
                # list that stops being honest -- or moving the limit until
                # it passed. `_verify_foreshortening` holds it instead, on
                # two integers, and asserts it exceeds this limit rather than
                # being excused from it. A floor that is ALSO on the
                # `directional` list is recorded as exempt as well, so the
                # coverage rule sees the two rules overlap and says so.
                if name in view.directional:
                    _record(seen, view, name, "the directional exemption")
                continue
            local = directional_bias(texture_fn(name), probe)
            whole = profile_bias(texture_fn(name), probe)
            if name in view.directional:
                if local <= ISOTROPY_LIMIT and whole <= PROFILE_LIMIT:
                    raise ValueError(
                        f"texture {name!r} is exempt from the isotropy rule "
                        f"in view {view.name!r} as deliberately directional, "
                        f"and scores {local:.3f} against the "
                        f"{ISOTROPY_LIMIT} local limit and {whole:.3f} "
                        f"against the {PROFILE_LIMIT} whole-cell one: it is "
                        f"not directional under either operator, so the "
                        f"exemption is a line that hides the next texture "
                        f"that fails")
                _record(seen, view, name, "the directional exemption")
                continue
            if local > ISOTROPY_LIMIT:
                raise ValueError(
                    f"texture {name!r} scores {local:.3f} for directional "
                    f"bias in view {view.name!r}, over {ISOTROPY_LIMIT}; "
                    f"ground seen from above has no horizon and no gravity, "
                    f"so a dominant direction is a mistake unless it means "
                    f"something -- and if it does, name it in the view's "
                    f"`directional` list with the reason")
            if whole > PROFILE_LIMIT:
                raise ValueError(
                    f"texture {name!r} scores {whole:.3f} on the whole-cell "
                    f"profile in view {view.name!r}, over {PROFILE_LIMIT}; "
                    f"its columns and its rows do not vary alike, so a "
                    f"painted field leans even though no two neighbouring "
                    f"pixels say so -- which is the lean `directional_bias` "
                    f"alone cannot see")
            _record(seen, view, name, "the isotropy limit")
    return judged


def _slab_reference(slab: Slab) -> Texture:
    """What a `Slab` SAYS it draws, written out of the declaration ALONE.

    THE GUARD'S ORACLE, AND A DELIBERATE SECOND EXPRESSION. #TAG:oracle_is_alone
    CLAUDE.md counts nineteen sightings of one route fixed while its sibling
    grew without the fix, and the counter-move is to make the shared half one
    function. This is the one place in this file where that is the WRONG
    move, and the measurement says why. The rule that stood here compared
    `_lattice_period(_slab_lattice(slab))` against `(slab.w, slab.h)` -- and
    `_slab_lattice` is the renderer's own helper, reading the renderer's own
    `SLAB_PHASE`. So the guard compared the declaration with a second reading
    of the declaration, and transposing two variables one function away made
    every floor draw a SQUARE stone at k = 1 -- the plan view this whole view
    exists to stop drawing -- while `_verify_foreshortening` said GREEN and
    the sheet built. The shipped provocation mutated `SLAB_PHASE`, the one
    table both sides read, which is the single mutation shape a duplicated
    expression cannot fail.

    So this imports nothing from the drawing path: not `_slab_band`, not
    `_slab_lattice`, not `_slab_joint`, not `_slab_front`, not `SLAB_PHASE`
    and not `_joint`. It reads the six declared fields and `SHADOW_OFFSET`,
    which is shared on purpose -- the sun IS one constant, and a reference
    that re-decided it would be asserting the sheet is lit the way the
    reference thinks rather than the way the package does.

    It pins the PHASE as well as the spacing, which the period rule wrote off
    as an unpinnable crack: a renderer rolling the whole lattice one row
    inside the cell still measures period `(w, h)` and used to pass.
    """
    w, h, cut, front = slab.w, slab.h, slab.joint, slab.front
    grit = slab.grit
    away = slab.units
    across = slab.units * h // w
    depth = round(slab.rise * math.sqrt(1.0 - (h / w) ** 2))
    wide, deep = slab.grain, slab.grain * h // w
    ox, oy = SHADOW_OFFSET

    def reference(m: Ramp, x: int, y: int, salt: int) -> RGB:
        px, py = x % TILE, y % TILE
        # The groove sits at the stone's HIGH index when the sun runs down
        # and right, and at its low index when the sun is reversed; flipping
        # the within-stone index says that once, for both axes.
        sx = px % w if ox > 0 else w - 1 - px % w
        sy = py % h if oy > 0 else h - 1 - py % h
        if sx >= w - away or sy >= h - across:
            return m.step(cut)
        if sy >= h - across - depth:
            return m.step(front)
        if grit and noise(px * 3 + 1, py * 5 + 2, salt + 19) < grit:
            return m.dark
        value = noise(px // wide, py // deep, salt)
        return m.light if value > FACE_SPREAD else (
            m.dark if value < 1.0 - FACE_SPREAD else m.base)

    return reference


def _verify_foreshortening(floors: dict[str, Slab] = FLOORS,
                           views: dict[str, View] = VIEWS) -> Judgements:
    """Refuse a floor that is not the view's ratio, and a RENDERER that does
    not draw the floor it was declared.

    FOUR HALVES, AND THE LAST TWO ARE THE ONES NORMALLY MISSING.
    The first reads two integers out of the source, which cannot lie about
    itself; it catches a floor somebody added at the wrong aspect.

    The second asserts the texture REGISTERED under a floor's name is the one
    `_slab_texture` builds from that floor's own declaration, pixel for
    pixel. Without it the whole rule reads a declaration that nothing on the
    sheet draws -- `TEXTURE_FNS["flagstone"] = _mottle` would leave every
    other assertion here green.

    The third is the one this rule rests on, and the one it did not have:
    the drawn pixels are compared with `_slab_reference`, an ORACLE written
    out of the declaration and sharing no helper with the renderer. The rule
    used to compare `_lattice_period(_slab_lattice(slab))` with `(w, h)`, and
    `_slab_lattice` is the renderer's own; measured, that let a transposed
    index draw an 8x8 stone under a 16x8 declaration with the whole pack
    green. The period comparison is kept below the oracle because it names
    the spacing failure in one line, but it is no longer what has teeth.

    The fourth asserts the floor EXCEEDS the isotropy limit it is excused
    from, so the exemption cannot quietly cover a floor that stopped drawing
    a rectangle.

    There is NO THRESHOLD anywhere in here. `Fraction(h, w) == k` and the
    pixel comparison are equalities, deliberately: any tolerance in this rule
    would be a number picked to make the current sheet pass.

    Returns its own `Judgements` -- the floors it actually judged, per view --
    which `_verify_view_coverage` merges with the isotropy rule's.
    """
    judged: Judgements = {}
    probe = ramp("stone")
    for view in views.values():
        seen = judged.setdefault(view.name, {})
        named = [name for name in view.textures if name in floors]
        if view.foreshortening != 1 and not named:
            raise ValueError(
                f"view {view.name!r} declares a foreshortening of "
                f"{view.foreshortening} and names no floor at all; the ratio "
                f"is carried by a declared stone, so a foreshortened view "
                f"with nothing to declare it is a number in a dataclass that "
                f"nothing on the sheet draws")
        for name in named:
            slab = floors[name]
            if TILE % slab.w or TILE % slab.h:
                raise ValueError(
                    f"floor {name!r} declares a {slab.w}x{slab.h} stone and "
                    f"one of those does not divide the {TILE}px tile; the "
                    f"renderer blits one cell everywhere, so a stone on any "
                    f"other period restarts at the cell border and the field "
                    f"strobes instead of paving")
            across = slab.units * slab.h // slab.w
            depth = round(slab.rise * math.sqrt(1.0 - (slab.h / slab.w) ** 2))
            wide, deep = _slab_grain(slab)
            if not deep or TILE % wide or TILE % deep:
                raise ValueError(
                    f"floor {name!r} declares a {slab.grain}-unit weathering "
                    f"patch, which projects to {wide}x{deep} screen pixels, "
                    f"and that does not divide the {TILE}px tile on both "
                    f"axes; the patch grid would restart at the cell border "
                    f"and strobe, for the same reason a stone on the wrong "
                    f"period would")
            if slab.h < across + depth + 1 or slab.w < slab.units + 1:
                raise ValueError(
                    f"floor {name!r} declares a {slab.w}x{slab.h} stone with "
                    f"a {slab.units}-unit groove and a {slab.rise}-unit rise, "
                    f"which project to a groove {slab.units} across and "
                    f"{across} down and a near face {depth} deep: that needs "
                    f"{across + depth + 1} rows and {slab.units + 1} columns "
                    f"and the stone has {slab.h} and {slab.w}. A slab reads "
                    f"as a slab only with a top face, a near face and a "
                    f"groove; drop one and it is a stripe")
            if Fraction(slab.h, slab.w) != view.foreshortening:
                raise ValueError(
                    f"floor {name!r} draws a {slab.w}x{slab.h} stone, so it "
                    f"depicts a world square at "
                    f"{Fraction(slab.h, slab.w)}, and view {view.name!r} is "
                    f"{view.foreshortening}; the stone is square in the "
                    f"world, so its SCREEN aspect IS the camera and two "
                    f"floors at two ratios on one sheet are two cameras")
            built = _slab_texture(slab)
            drawn = texture_fn(name)
            wrong = next(((x, y) for y in range(TILE) for x in range(TILE)
                          if drawn(probe, x, y, 7)
                          != built(probe, x, y, 7)), None)
            if wrong is not None:
                raise ValueError(
                    f"the texture registered as {name!r} is not the one "
                    f"`_slab_texture` builds from its own declaration -- "
                    f"they differ at {wrong}. `FLOORS` and `TEXTURE_FNS` are "
                    f"spread from one dict so this cannot drift by hand, and "
                    f"this is the assertion that says so: without it the "
                    f"ratio rule reads a declaration that nothing on the "
                    f"sheet is drawing")
            oracle = _slab_reference(slab)
            for probe_salt in (7, 23):
                wrong = next(((x, y) for y in range(TILE) for x in range(TILE)
                              if drawn(probe, x, y, probe_salt)
                              != oracle(probe, x, y, probe_salt)), None)
                if wrong is None:
                    continue
                raise ValueError(
                    f"floor {name!r} declares a {slab.w}x{slab.h} stone with "
                    f"a {slab.units}-unit groove and a {slab.rise}-unit rise "
                    f"and DRAWS something else: the pixel at {wrong} is "
                    f"{drawn(probe, *wrong, probe_salt)} where the "
                    f"declaration says {oracle(probe, *wrong, probe_salt)}. "
                    f"`_slab_reference` shares no helper with the renderer "
                    f"precisely so that this can be said; a guard that "
                    f"rebuilds the lattice through `_slab_lattice` is "
                    f"comparing the declaration with a second reading of it, "
                    f"and one transposed index made every floor on the sheet "
                    f"draw a square stone with the whole pack green")
            period = _lattice_period(_slab_lattice(slab))
            if period != (slab.w, slab.h):
                raise ValueError(
                    f"floor {name!r} declares a {slab.w}x{slab.h} stone and "
                    f"`_slab_lattice` builds a lattice with period {period}; "
                    f"the declaration is what the ratio rule reads, so a "
                    f"renderer that ignores it makes every floor on the "
                    f"sheet a lie that every assertion agrees with")
            local = directional_bias(texture_fn(name), probe)
            whole = profile_bias(texture_fn(name), probe)
            if local <= ISOTROPY_LIMIT and whole <= PROFILE_LIMIT:
                raise ValueError(
                    f"floor {name!r} is excused the isotropy rule because it "
                    f"declares a {slab.w}x{slab.h} stone, and measures "
                    f"{local:.3f} and {whole:.3f} against {ISOTROPY_LIMIT} "
                    f"and {PROFILE_LIMIT}: it is not drawing a rectangle at "
                    f"all, so the exemption is covering a floor that has "
                    f"quietly stopped being one")
            _record(seen, view, name, "the ratio rule")
    return judged


def _verify_view_coverage(views: dict[str, View] = VIEWS,
                          floors: dict[str, Slab] = FLOORS,
                          judged: dict[str, dict[str, list[str]]] | None = None
                          ) -> None:
    """Every texture a ground view draws is judged by EXACTLY ONE rule, and
    every rule SAYS SO ITSELF.

    Three rules and three classes: a declared floor is the ratio's, a loose
    surface is the isotropy rule's, a named exemption is its own -- and a
    whole non-isotropic view is the fourth, stated once on the view. This is
    the line that makes the split above safe rather than convenient: a
    surface NOTHING measures is where the next mistake goes, and a surface
    TWO rules measure is two rules that will one day disagree about it.

    IT READS A LEDGER, NOT THE ARGUMENTS.          #TAG:coverage_reads_a_ledger
    The rule used to score `(name in floors) + (name not in floors and name
    not in view.directional) + (name in view.directional)`, whose middle term
    is the exact negation of the other two. Brute-forced over every
    membership combination, `covered` could only be 1 or 2: the branch the
    docstring called the thing that makes the split airtight was arithmetically
    unable to fire, and the check's "a texture covered by NO rule is refused"
    was exercising the `covered == 2` branch a second time. So the rules now
    report what they touched (`Judgements`) and this compares the report with
    the vocabulary. Add a `continue` to `_verify_isotropy` and a real texture
    scores 0 here.
    """
    if judged is None:
        judged = _merge_judgements(_verify_foreshortening(floors, views),
                                   _verify_isotropy(views, floors))
    for view in views.values():
        seen = judged.get(view.name, {})
        for name in view.textures:
            rules = seen.get(name, [])
            if len(rules) == 1:
                continue
            raise ValueError(
                f"texture {name!r} in view {view.name!r} is judged by "
                f"{len(rules)} rules"
                + (f" ({', '.join(rules)})" if rules else "") +
                f"; a surface nothing measures is where the next mistake "
                f"goes, and a surface two rules measure is two rules that "
                f"will one day disagree")


def _verify_lighting(views: dict[str, View] = VIEWS) -> None:
    """Hold every overhead texture to the ONE shared sun -- and BOTH HALVES.

    Half one: every texture in `LIT_TEXTURES` must DRAW SOMETHING ELSE when
    `SHADOW_OFFSET` is reversed, which is only true of a texture that read
    the constant rather than writing its own direction out.

    Half two, and it is the one that was missing: every other texture the
    view draws must NOT move -- and must measure under `LIGHTING_TOLERANCE`
    on `shadow_bias`. A texture that hard-codes its own direction does not
    move either, so "did not move" alone is satisfied by exactly the defect
    this is looking for; the bias is what tells a flat hash apart from a
    board lit along its top edge.

    EVERY GROUND VIEW, NOT EVERY OVERHEAD ONE.     #TAG:lighting_is_per_ground
    A side sheet IS lit on a vertical face -- that is what it is for -- so
    `mass` and its textures are outside this rule, and `plank` keeping its
    lit board edge over there is correct. Everything else is ground, whatever
    it shades with. This used to read `if view.shade is not overhead`, which
    was true of exactly one view and would have let the third one grow beside
    it with none of this enforced -- the sibling shape CLAUDE.md counts
    nineteen times. The exemption is `mass`, named once, so a fourth shader
    is inside the rule the day it is written rather than the day somebody
    remembers.
    """
    global SHADOW_OFFSET
    probe = ramp("stone")

    def drawn(name: str) -> list[RGB]:
        fn = texture_fn(name)
        return [fn(probe, x, y, 5) for y in range(TILE) for x in range(TILE)]

    for view in views.values():
        if view.shade is mass:
            continue
        stray = sorted(set(LIT_TEXTURES) - set(TEXTURE_FNS))
        if stray:
            raise ValueError(
                f"LIT_TEXTURES names {', '.join(stray)}, which nothing "
                f"registered")
        for name in view.textures:
            before = drawn(name)
            kept = SHADOW_OFFSET
            SHADOW_OFFSET = (-kept[0], -kept[1])
            try:
                turned = drawn(name)
            finally:
                SHADOW_OFFSET = kept
            moved = turned != before
            if name in LIT_TEXTURES:
                if moved:
                    continue
                raise ValueError(
                    f"texture {name!r} says it is lit and draws the same "
                    f"pixels with {SHADOW_OFFSET} reversed, so it never read "
                    f"the constant: it has written a direction of its own, "
                    f"and the next texture beside it will write a different "
                    f"one -- which is what `grout`, `rivet`, `mosaic` and "
                    f"`setts` each did")
            if moved:
                raise ValueError(
                    f"texture {name!r} moves when {SHADOW_OFFSET} is "
                    f"reversed and is not in LIT_TEXTURES; a texture that "
                    f"reads the shared sun has to say so, or the list stops "
                    f"being the answer to `which of these are lit`")
            lean = shadow_bias(texture_fn(name), probe)
            if abs(lean) <= LIGHTING_TOLERANCE:
                continue
            raise ValueError(
                f"texture {name!r} declares no lighting and measures "
                f"{lean:+.3f} on `shadow_bias`, over {LIGHTING_TOLERANCE}: "
                f"its dark sits on one side of its bright, so it IS lit -- "
                f"by a direction written into itself that nothing holds to "
                f"the sheet's. That is `plank`, which carried the side "
                f"sheet's lit-top-dark-bottom board onto the overhead one")


_verify_lighting()


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------

TERRAIN_DISTANCE = 14.0
"""How far apart any two terrains must look, as CIELAB dE on the DRAWN field.

Three deliberate words. ANY TWO, not two that happen to touch on the sheet:
the rule used to run over right-and-below neighbours only, so eleven of the
twelve lookalike pairs sat under its own floor and it never looked at them.
`granite` and `cobble` were 2.4 apart -- under the just-noticeable difference
-- and the wood-floor-against-planks pair the rule was written for was fixed
by moving the blocks apart on the sheet rather than by enforcing anything.

CIELAB, not raw RGB, because euclidean RGB calls two mid greys close and a
dark blue and a dark green far apart, which is the opposite of what an author
sees.

THE DRAWN FIELD, not `ramp().base`: a texture moves a material. `crust` on a
dark red is not the dark red, and the colour the author picks a block by is
the one the block actually shows.

The number is read off the measured distribution, not chosen, and the check
prints that distribution's closest pair per sheet every run: `dirt_path`
against `gravel` at 14.3 on the side table and `cobble` against `ash` at
14.3 on the top-down one. The floor sits just under.
"""

HAZARD_DISTANCE = 12.0
# SEPARABILITY IS NOT LEGIBILITY, AND ONLY ONE OF THEM IS HERE.
#                                                  #TAG:hazard_is_separable
# All four urban hazards clear this comfortably and `scorched` still loses
# its MEANING under both simulated dichromacies: it keeps its distance from
# `park_dirt` and reads as dark olive mud rather than as embers, because the
# orange cinders that say "hot" are the part a red-green dichromat loses.
# The number below is honest about what it measures -- can these two be told
# apart -- and nothing here measures whether a hazard reads AS a hazard.
# That is a second property and it wants its own name before anybody writes
# a number for it; `live_rail` needing a stripe is the same gap from the
# other side. Do not widen this constant to cover it.
"""How far a HAZARD must sit from every floor a body may stand on --

-- AS A RED-GREEN COLOURBLIND PLAYER SEES IT. CIELAB dE again, on the drawn
field again, but measured after `dichromat` has collapsed the colour the way
a protanope's eye does and again the way a deuteranope's, worse of the two
counting.

This sheet used to put `grass` and `lava` 64.5 apart in normal vision and 4.0
apart under simulated protanopia, with 5.6 of luminance between them; twelve
hazard/floor pairs collapsed the same way. A player who cannot tell the
ground from the lava is not looking at an art problem.

There is deliberately no second rule about brightness, and that is not an
omission. `dichromat` leaves the L* axis alone -- that is what makes it the
axis colour blindness does not take away -- and L* is the first term of the
dE above, so a hazard separated from a floor by nothing BUT brightness
already clears this by brightness. A separate luminance floor would be a
branch that can never fire, since it would have to be larger than this
number to mean anything and a dE is never smaller than its own L* term.

Measured, and printed by `tools/check_art_tilesets.py` on every run so it
cannot go stale again: the tightest pair on the SIDE table is `lava`
against `planks` at 13.3, and on the TOP-DOWN table `embers` against `mud`
at 18.2. The overhead sheet is much the safer of the two here, because
`_cinder` makes its one red hazard mostly black.

The sentence this replaced named `lava` against `rusted_plate` at 13.1,
which stopped being the tightest pair two repaints ago.
"""

REPEAT_BLUR = 2
"""The radius of the box blur `repeat_bias` reads the field through: 5x5.

Big enough that a single pixel of grit disappears and a blob does not, which
is the scale the eye finds a motif at.
"""

REPEAT_LIMIT = 2.45
"""How much STRUCTURE an overhead row may leave at glyph scale, in L*.

The author's "does a field strobe at 16px", as a number. Blur the cell the
renderer blits, wrapped, and measure the spread of what survives: a surface
made of grit blurs to nothing, a surface with one dominant blob in it keeps
that blob, and the blob is what comes back every sixteen pixels forever.

Read off both ends of the measured distribution, which is what makes it a
limit rather than a preference. Above it: `_mottle` thresholding the smooth
patch again puts `clay` at 4.40, and `_ripplet` filling its crest again puts
`swamp` at 2.61 -- the two constructions this number was written to keep off
the sheet, both proved red by mutation. Below it: the worst row that ships
is `snow` at 2.34, then `granite` 2.23 and `carpet` 2.18, with `gravel` at
0.99 and `sand` at 1.08 at the clean end.

HASHED ROWS OF AN OVERHEAD SHEET ONLY, and both halves of that are
deliberate. A structured texture MEANS to carry something at this scale --
`furrow`'s one trough per tile measures 6.6 and is the whole point of it --
so the rule would be asking a paver not to have joints. And a side sheet is
allowed a motif for the same reason it is allowed a grain: it is drawing a
face, not ground.
"""

STRUCTURE_LIMIT = 0.60
"""How alike two rows of one table may DRAW, as luminance correlation.

The rule `_verify_terrains` did not have. It compared declarations -- two
rows naming different palettes are different rows -- and `swamp` and `water`
both drew `ripplet` at the same salt and came out 0.98 correlated: the same
picture in two colours, which is a wasted block however far apart the
colours are. `_salt` is the fix and this is the measurement that holds it.

Read off the distribution after that fix: the closest hashed pair on either
sheet is `grass`/`shallow_water` at 0.32 and `forest_floor`/`wood_floor` at
0.45, so the limit sits well clear, and an identical drawing scores 1.00.

Hashed rows only. Two rows may share a STRUCTURED texture on purpose --
`cobble` and `brickwork` are both pavers, `mud` and `water` were both
`wave` -- and a structured texture has no salt to tell them apart, so the
sameness there is a declaration the neighbour rule already governs.

WHAT THAT EXEMPTION COSTS ON THE URBAN SHEET, MEASURED.  #TAG:slabs_draw_alike
"On purpose" is a fair description of two rows; it was not a fair
description of nine. The first urban table put nine rows on four declared
floors and the exemption hid the lot: `warehouse_floor`/`subway_tile` at
0.942, `cobble_street`/`brick_walk` 0.926, `sidewalk`/`concrete_slab` 0.925,
`concrete_slab`/`dock_plank` 0.921, `steel_deck`/`live_rail` 0.889 -- and
FOUR of those five are pairs drawing DIFFERENT floors, which is not the
thing the exemption is for. Nine rows, four lattices, and a number that
never looked.

Re-measured after `Slab.grain` gave each floor its own weathering scale,
every pair on the urban sheet drawing two DIFFERENT textures is now at most
0.386 (`cobble_street`/`dock_plank`), against this 0.60; the flagstone-
against-decking pair that was 0.921 is -0.034. What remains over the limit
is five SAME-texture pairs and nothing else: the three `flagstone` rows
(0.961 to 0.976), the two `decking` rows that share a stone size (0.911 --
`dock_plank` is the third and correlates -0.03 with both, because its grain
is a whole board), and the two `paver` rows (0.707).

AND WHY THE RULE IS STILL NOT WIDENED TO STRUCTURED PAIRS. It was measured
both ways. Judging every pair whose two rows name DIFFERENT structured
textures passes on the urban sheet with room (0.386 against 0.60) -- and
lands the TOP-DOWN sheet at 0.599, on `wood_floor`/`tiled_floor`, which is
`grout` against `mosaic` and really is two grids. A rule shipped with a
0.001 margin on a sheet this pass never touched is a rule that goes red for
somebody else's palette tweak, and law 13's cost is what an unexplained red
check does to the next reader. So the number stays where it is and the
measurement is written down instead of assumed.
"""

RIM_FALL = 1.5
"""How much darker an overhead island's falling edge must be than its face.

Small, and the reason is `void`. The rule is not looking for a handsome
edge, it is looking for an edge AT ALL, and for the failure that had
actually happened: `overhead` shaded its rim `material.dark`, a fixed step
off the base and therefore inside what several textures already drew. 69%
of a `rusted_plate` interior sat at or below its own rim, 53% of
`brickwork`, 50% of `cobble` -- those islands had no silhouette. On
`embers` the rim came out 23.4 L* BRIGHTER than the coal bed it was the
shadow of.

With `palette.fall` shading each rim pixel off the pixel the texture drew
there, every row clears this; the binding one is `void` at 1.7, which has
about five of L* between it and black to spend. The limit is under that and
over zero, which is exactly the claim: the edge falls.
"""


@dataclass(frozen=True)
class Terrain:
    """One paintable material: its ramp, its surface, its silhouette -- and
    whether standing on it is meant to hurt."""

    name: str
    palette: str
    texture: str = "speckle"
    form: str = DEFAULT_FORM
    view: str = DEFAULT_VIEW
    """Which way the camera is: `side` (the default), `topdown` or `beatemup`.

    Defaulted, so every row of the table that already shipped still says
    exactly what it said and still draws exactly what it drew. It selects
    the lighting model and the vocabulary this row may pick from, and
    nothing else; see `VIEWS`.
    """
    hazard: bool = False
    """True for ground a body must not be on: lava, coals, deep water, a pit.

    It is on the terrain and not in a table off to the side because it is
    what `_verify_terrains` reads to decide which pairs have to survive
    colour blindness, and a flag nobody can see from the row it describes is
    a flag that goes stale.
    """

    def ramp(self) -> Ramp:
        return ramp(self.palette)

    def seen(self) -> View:
        """This row's view. Raises on a view nothing registered."""
        return view_of(self.view)

    def field_colour(self) -> RGB:
        """The mean colour of this terrain's FULL quadrant, as drawn.

        What the colour rules measure. One 16px cell of solid terrain, texture
        and all, averaged -- which is as close as arithmetic gets to "what does
        this block look like from across the room".
        """
        cell = quadrant(FULL, self)
        total = [0, 0, 0]
        for y in range(TILE):
            for x in range(TILE):
                pixel = cell.get_at((x, y))
                for channel in range(3):
                    total[channel] += pixel[channel]
        return tuple(round(value / (TILE * TILE)) for value in total)


# One per block, read left to right then top to bottom -- the order
# `block_origins` returns, so block N here IS origin N there.
#
# Four bands of eight: soft ground, mineral, cold and liquid, made and hot.
# Inside a band the order is whatever keeps every pair of touching blocks
# unlike in texture AND form, which `_verify_terrains` holds; colour is held
# over the whole table rather than between neighbours, so where a block sits
# no longer decides whether its colour is checked.
TERRAINS: tuple[Terrain, ...] = (
    Terrain("grass", "grass", "tuft", "lobed"),
    Terrain("forest_floor", "forest", "grain", "heave"),
    Terrain("moss", "moss", "tuft", "lobed"),
    Terrain("swamp", "swamp", "ripple", "drip"),
    Terrain("dirt", "dirt", "speckle", "round"),
    Terrain("mud", "mud", "wave", "drip"),
    Terrain("clay", "clay", "dither", "round"),
    Terrain("dirt_path", "path", "gravel", "heave"),

    Terrain("sand", "sand", "speckle", "drip"),
    Terrain("gravel", "gravel", "gravel", "round"),
    Terrain("granite", "granite", "fleck", "heave"),
    Terrain("cobble", "cobble", "brick", "round"),
    Terrain("stone", "stone", "chip", "square"),
    Terrain("bone_field", "bone", "crosshatch", "round"),
    Terrain("obsidian", "obsidian", "flat", "square"),
    Terrain("ash", "ash", "speckle", "drip"),

    Terrain("snow", "snow", "dither", "heave"),
    Terrain("ice", "ice", "crack", "lobed"),
    Terrain("marble", "marble", "vein", "square"),
    Terrain("water", "water", "wave", "drip"),
    Terrain("deep_water", "deep_water", "ripple", "round", hazard=True),
    Terrain("shallow_water", "shallow", "wave", "lobed"),
    Terrain("lava", "lava", "crust", "drip", hazard=True),
    Terrain("void", "void", "flat", "square", hazard=True),

    Terrain("wood_floor", "wood", "grain", "square"),
    Terrain("planks", "plank", "plank", "heave"),
    Terrain("brickwork", "brick", "brick", "round"),
    Terrain("tiled_floor", "tile_floor", "grout", "square"),
    Terrain("carpet", "rug", "weave", "lobed"),
    Terrain("rusted_plate", "rust", "flake", "heave"),
    Terrain("metal_plate", "metal", "rivet", "square"),
    Terrain("embers", "ember", "cinder", "heave", hazard=True),
)


# The SAME thirty-two materials, in the SAME order, seen from above.
#
# Same order is a rule and not a convenience (`_verify_tables_agree`). Block
# 17 of one sheet and block 17 of the other are `ice` either way, so a map
# swaps sheets without renumbering a single gid, `origins()` answers for both
# from one call, and an author comparing the two views is comparing the same
# material rather than hunting for it. It also makes the colour rules
# meaningful across the pair: if a material drifts far enough in one view
# that it collides with a different material there, that is a fact about the
# TEXTURE, and the two tables sharing names is what makes it visible.
#
# What changes, row by row, is the third and fourth columns. Grass is clumps
# of crowns instead of standing blades; brick is a paver instead of a course;
# wood is boards in a room, which is the one place a plank run still means
# something; loose stone is lit tops with one shadow each instead of shaded
# spheres. Three rows keep a direction and say why: `furrow` is a plough,
# `current` is a river, `plank` is a floor somebody laid one way.
TOPDOWN_TERRAINS: tuple[Terrain, ...] = tuple(
    Terrain(name, palette, texture, form, "topdown", hazard)
    for name, palette, texture, form, hazard in (
        ("grass", "grass", "clump", "lobed", False),
        ("forest_floor", "forest", "litter", "round", False),
        ("moss", "moss", "clump", "lobed", False),
        ("swamp", "swamp", "ripplet", "round", False),
        ("dirt", "dirt", "mottle", "lobed", False),
        ("mud", "mud", "furrow", "round", False),
        ("clay", "clay", "mottle", "square", False),
        ("dirt_path", "path", "scatter", "round", False),

        ("sand", "sand", "grit", "round", False),
        ("gravel", "gravel", "scatter", "lobed", False),
        ("granite", "granite", "fleck", "round", False),
        ("cobble", "cobble", "setts", "square", False),
        ("stone", "stone", "chip", "round", False),
        ("bone_field", "bone", "litter", "lobed", False),
        ("obsidian", "obsidian", "flat", "round", False),
        ("ash", "ash", "grit", "lobed", False),

        ("snow", "snow", "mottle", "lobed", False),
        ("ice", "ice", "crack", "round", False),
        ("marble", "marble", "chip", "square", False),
        ("water", "water", "ripplet", "lobed", False),
        ("deep_water", "deep_water", "current", "drip", True),
        ("shallow_water", "shallow", "scatter", "round", False),
        ("lava", "lava", "ripplet", "drip", True),
        ("void", "void", "flat", "square", True),

        ("wood_floor", "wood", "grout", "square", False),
        ("planks", "plank", "board", "lobed", False),
        ("brickwork", "brick", "setts", "round", False),
        ("tiled_floor", "tile_floor", "mosaic", "square", False),
        ("carpet", "rug", "fleck", "lobed", False),
        ("rusted_plate", "rust", "flake", "square", False),
        ("metal_plate", "metal", "rivet", "round", False),
        ("embers", "ember", "cinder", "lobed", True),
    )
)


# THIRTY-TWO URBAN MATERIALS, WHICH ARE NOT THE OTHER THIRTY-TWO RELIT.
#
# `topdown`'s table is `side`'s table seen from above: one set of materials,
# two cameras, and `_verify_tables_agree` holds them to the same names in the
# same order so a map swaps sheets without renumbering a gid. That rule is
# exactly right there and exactly wrong here, which is why `View.family`
# exists: a belt-scroll stage walks a street, a lot, a subway platform and a
# dockside, and none of those is `swamp` under a different lamp.
#
# Four bands of eight, in the sheet's reading order: the street, the lot and
# the yard, transit, waterfront and park. Only things LYING FLAT are terrain.
# A crate, a barrel, a lamppost, a chain fence and a hedge are STANDING
# objects -- `side` art at scale 1 with a k-ellipse contact shadow -- and
# they belong to `tools/art/tiles.py`. That is the line to hold when somebody
# asks for a fence terrain.
#
# THE COLOUR PROBLEM IS THE REAL COST OF THIS TABLE  #TAG:urban_needs_chroma
# A natural table spans grass to lava; an urban one is thirty shades of grey
# against a `TERRAIN_DISTANCE` of 14.0 measured on the DRAWN field. Measured
# on the sRGB cube, thirty-two rows at that distance do not fit under a
# chroma cap of 15 at all -- 21 rows is the ceiling -- and fit under a cap of
# 20 with 0.1 dE to spare. So the chroma on `road_paint`, `platform_edge`,
# `live_rail`, `brick_walk`, `harbour_water`, `park_grass` and the two browns
# is not decoration, it is the only thing that lets thirty-two rows exist.
# The failure this table is steering around is NOT a red check: it is a green
# check on a sheet that looks like upholstery, which is what an optimiser
# handed back when it was given a long enough leash -- purple asphalt, at
# 17.1 dE. No assertion here can tell that apart from art.
BEATEMUP_TERRAINS: tuple[Terrain, ...] = tuple(
    Terrain(name, palette, texture, form, "beatemup", hazard)
    for name, palette, texture, form, hazard in (
        ("asphalt", "asphalt", "mottle", "square", False),
        ("asphalt_cracked", "asphalt_cracked", "crack", "lobed", False),
        ("cobble_street", "cobble_street", "paver", "round", False),
        ("sidewalk", "sidewalk", "flagstone", "square", False),
        ("kerb", "kerb", "chip", "heave", False),
        ("road_paint", "road_paint", "grit", "square", False),
        ("brick_walk", "brick_walk", "paver", "lobed", False),
        ("oil_slick", "oil_slick", "flat", "drip", True),

        ("concrete_slab", "concrete_slab", "flagstone", "round", False),
        ("gravel_lot", "gravel_lot", "scatter", "square", False),
        ("dirt_lot", "dirt_lot", "mottle", "lobed", False),
        ("sand_lot", "sand_lot", "grit", "heave", False),
        ("rubble", "rubble", "scatter", "drip", False),
        ("warehouse_floor", "warehouse_floor", "decking", "round", False),
        ("loading_dock", "loading_dock", "chip", "square", False),
        ("steel_deck", "steel_deck", "decking", "heave", False),

        ("subway_platform", "subway_platform", "chip", "square", False),
        ("station_floor", "station_floor", "flagstone", "lobed", False),
        ("platform_edge", "platform_edge", "grit", "square", False),
        ("rail_bed", "rail_bed", "scatter", "round", False),
        ("live_rail", "live_rail", "treadplate", "square", True),
        ("steam_vent", "steam_vent", "fleck", "lobed", False),
        ("puddle", "puddle", "ripplet", "heave", False),
        ("rusted_hatch", "rusted_hatch", "flake", "round", False),

        ("dock_plank", "dock_plank", "decking", "lobed", False),
        ("dock_wet", "dock_wet", "mottle", "square", False),
        ("harbour_water", "harbour_water", "current", "drip", False),
        ("park_path", "park_path", "litter", "square", False),
        ("park_grass", "park_grass", "clump", "lobed", False),
        ("park_dirt", "park_dirt", "mottle", "heave", False),
        ("scorched", "scorched", "cinder", "drip", True),
        ("open_pit", "open_pit", "grit", "square", True),
    )
)

TABLES: dict[str, tuple[Terrain, ...]] = {
    "side": TERRAINS,
    "topdown": TOPDOWN_TERRAINS,
    "beatemup": BEATEMUP_TERRAINS,
}
"""Every sheet this module draws, by view. ONE map, so every rule below runs
over every sheet rather than over the one somebody remembered."""

HAZARDS: dict[str, frozenset[str]] = {
    "side": frozenset({"deep_water", "lava", "void", "embers"}),
    "topdown": frozenset({"deep_water", "lava", "void", "embers"}),
    "beatemup": frozenset({"oil_slick", "live_rail", "scorched", "open_pit"}),
}
"""Which blocks of each sheet HURT, written down once per view by name.

A FAMILY OF ONE HAS NO PARTNER TO BE CHECKED AGAINST. #TAG:hazard_is_declared
`_verify_tables_agree` compares the hazard column between the views of one
family (`#TAG:hazard_is_the_pair`), and that is the right rule for `side` and
`topdown`, which are one set of materials seen two ways. Measured, it judges
`beatemup` NOT AT ALL: family `urban` has one member, so `members[1:]` is
empty and nothing is compared. Dropping `hazard=True` from `live_rail` or
from `scorched` left the entire pack GREEN -- an electrified third rail
became ground a body may stand on, and the only rule that could have noticed
is the one that needs a sibling. That is the ACTIVE WARNING shape at nineteen
sightings: a rule widened per family, and the family with no sibling fell out
of it.

So the verdict is ANCHORED per table instead of compared between tables, and
`_verify_terrains` holds `{t.name for t in table if t.hazard}` to exactly the
set named here. It covers a family of one and a family of five alike, and it
is the pair rule's belt as well as its braces: two tables that disagree now
fail twice.

THE NAMES IN HERE ARE FILE-FORMAT STRINGS (law 8). They are the same row
names the tables spell, so a renamed row has to be renamed in both places --
which is the point: a rename that silently dropped a hazard flag is exactly
what this refuses.

`_verify_terrains`'s old population guard was `any(t.hazard for t in table)`,
which three remaining hazards satisfy while the fourth quietly leaves the
colour-blindness rule's domain -- 28 hazard/floor pairs per dropped flag,
removed rather than failed.
"""


def hazards_of(view: str, hazards: dict[str, frozenset[str]] = HAZARDS
               ) -> frozenset[str]:
    """The declared hazard names for a view. Raises on a view with none.

    No empty default: a sheet that fell through to "nothing here hurts" would
    pass the rule below by having nothing to hold, which is the shape law 7
    is about.
    """
    try:
        return hazards[view]
    except KeyError:
        raise ValueError(
            f"no hazard declaration for view {view!r}; every sheet says which "
            f"of its blocks hurt, by name, because a family of one has no "
            f"partner to be compared against -- see HAZARDS. The views "
            f"declared are {', '.join(sorted(hazards))}") from None


def _verify_tables_agree(tables: dict[str, tuple[Terrain, ...]] = TABLES,
                         views: dict[str, View] = VIEWS) -> None:
    """Refuse two views of ONE FAMILY that do not name the same materials, in
    the same order, with the same verdict about hurting -- and refuse two
    families that name the same materials.

    Block N is the same material in every view of one family or the pair is
    useless: an author who paints a map with one sheet and swaps to the other
    would get `marble` where he had `ice`, silently, because a gid carries no
    name. That is exactly right BETWEEN `side` AND `topdown`, which are one
    set of materials seen two ways. It is exactly wrong for `beatemup`, whose
    table is a different set -- and nobody swaps a street sheet for a swamp
    sheet by accident, because they are not two pictures of one thing.

    AND THE SAME VERDICT ABOUT HURTING.                 #TAG:hazard_is_the_pair
    The `hazard` flag is compared here rather than counted somewhere,
    because a flag dropped from ONE table is the shape that got through:
    `_verify_terrains`'s only population guard is "some row is a hazard",
    which three remaining hazards satisfy, and dropping a flag REMOVES
    pairs from the colour-blindness rule rather than failing it. Measured
    in a sandbox, turning `lava` into a floor on either table left the
    whole tileset suite green. Two tables that must agree are the one thing
    in this file that can catch it, and it is one line.

    THE SECOND HALF IS THE ONE THAT WOULD OTHERWISE ROT. #TAG:family_is_earned
    A family is a licence to have a different table, so the day somebody
    wants ONE row changed the cheap move is to invent a family for it; then
    two "different" families are the same 32 names, the gid-swap guarantee is
    quietly gone, and every assertion still passes. A family that duplicates
    another family's table IS that family, and this says so out loud.
    """
    by_family: dict[str, list[tuple[str, tuple]]] = {}
    for name, table in tables.items():
        rows = tuple((terrain.name, terrain.hazard) for terrain in table)
        by_family.setdefault(view_of(name).family, []).append((name, rows))
    for family, members in by_family.items():
        reference_view, reference = members[0]
        for view_name, rows in members[1:]:
            if rows == reference:
                continue
            first = next(index for index, (a, b)
                         in enumerate(zip(reference, rows)) if a != b)
            raise ValueError(
                f"view {reference_view!r} and view {view_name!r} are both in "
                f"family {family!r} and disagree at block {first}: "
                f"{reference[first]} against {rows[first]}. Block N must be "
                f"the same material AND the same verdict about hurting in "
                f"every view of one family, or swapping a map's sheet "
                f"repaints it -- or, worse, turns a hazard into ground a "
                f"body may stand on")
    signatures = {family: members[0][1] for family, members in by_family.items()}
    for (first_family, a), (second_family, b) in combinations(
            signatures.items(), 2):
        if a != b:
            continue
        raise ValueError(
            f"families {first_family!r} and {second_family!r} name the same "
            f"{len(a)} materials, so one of them is the other under a second "
            f"name and the split bought nothing except an exemption from the "
            f"rule above")


def _verify_terrains(table: tuple[Terrain, ...] = TERRAINS,
                     hazards: dict[str, frozenset[str]] = HAZARDS) -> None:
    """Refuse a table that would waste a block, hide a mistake, or hurt.

    Every one of these is silent otherwise: a texture or form nobody draws
    (which raises at draw time, halfway through a sheet), two rows that are
    the same material under two names, a vocabulary entry nothing uses, two
    blocks side by side that read alike, two blocks ANYWHERE that read alike,
    and -- the one that is not about the author at all -- a hazard a colour
    blind player cannot tell from a floor.

    ONE FUNCTION, EVERY TABLE.                      #TAG:one_rule_every_view
    It takes the table rather than reading `TERRAINS`, and `_verify_pack`
    calls it once per view, because a second sheet is exactly the shape
    CLAUDE.md's sibling warning describes: a rule that only ever judged the
    sheet it was written for, while the new one grows beside it with none
    of it enforced. Every rule in here -- the colour floor, the hazard
    floor, the unused-vocabulary rule, the neighbour rule -- runs over both
    sheets or over neither.
    """
    if len(table) != BLOCKS_ACROSS * BLOCKS_DOWN:
        raise ValueError(f"the sheet holds {BLOCKS_ACROSS * BLOCKS_DOWN} "
                         f"blocks and this table names {len(table)}")
    views = {terrain.view for terrain in table}
    if len(views) != 1:
        raise ValueError(
            f"this table mixes the views {', '.join(sorted(views))}; one "
            f"sheet is one camera, and a block lit the other way would be "
            f"the only wrong tile on a sheet that otherwise agrees")
    view = view_of(views.pop())
    seen: dict[tuple[str, str, str], str] = {}
    for terrain in table:
        form_reach(terrain.form)
        texture_fn(terrain.texture)
        ramp(terrain.palette)
        if terrain.texture not in view.textures:
            raise ValueError(
                f"terrain {terrain.name!r} draws the texture "
                f"{terrain.texture!r}, which view {view.name!r} does not "
                f"carry; a surface is a fact about which way the camera is, "
                f"and this one belongs to the other sheet")
        if terrain.form not in view.forms:
            raise ValueError(
                f"terrain {terrain.name!r} draws the form {terrain.form!r}, "
                f"which view {view.name!r} does not carry")
        key = (terrain.palette, terrain.texture, terrain.form)
        if key in seen:
            raise ValueError(
                f"terrain {terrain.name!r} and {seen[key]!r} are both "
                f"{key[0]}/{key[1]}/{key[2]}: two names for one material, "
                f"and one of the 32 blocks is wasted on the copy")
        seen[key] = terrain.name
    for axis, vocabulary in (("texture", view.textures), ("form", view.forms)):
        unused = sorted(set(vocabulary) - {getattr(t, axis) for t in table})
        if unused:
            raise ValueError(
                f"nothing on the {view.name} sheet uses the {axis}(s) "
                f"{', '.join(unused)}; a vocabulary entry no block draws is "
                f"art nobody has ever looked at, and it will be wrong when "
                f"somebody finally does")
    declared = hazards_of(view.name, hazards)
    flagged = {terrain.name for terrain in table if terrain.hazard}
    if not declared:
        raise ValueError(
            f"view {view.name!r} declares no hazard at all, so the "
            f"colour-blindness rule below has nothing to hold; a sheet with "
            f"no hazard on it cannot have passed that rule, it can only have "
            f"skipped it")
    if flagged != declared:
        dropped = sorted(declared - flagged)
        added = sorted(flagged - declared)
        raise ValueError(
            f"the {view.name} table flags "
            f"{', '.join(sorted(flagged)) or 'nothing'} as hurting and "
            f"HAZARDS declares {', '.join(sorted(declared))}"
            + (f" -- {', '.join(dropped)} lost the flag" if dropped else "")
            + (f" -- {', '.join(added)} gained one" if added else "")
            + f". A dropped flag REMOVES pairs from the colour-blindness "
            f"rule rather than failing it, so a hazard a body may now stand "
            f"on is silent unless the verdict is written down; see HAZARDS "
            f"for why the family comparison cannot catch it on a family of "
            f"one")
    for index, terrain in enumerate(table):
        column, row = index % BLOCKS_ACROSS, index // BLOCKS_ACROSS
        for dx, dy in ((1, 0), (0, 1)):
            nx, ny = column + dx, row + dy
            if nx >= BLOCKS_ACROSS or ny >= BLOCKS_DOWN:
                continue
            other = table[ny * BLOCKS_ACROSS + nx]
            for axis in ("texture", "form"):
                if getattr(terrain, axis) == getattr(other, axis):
                    raise ValueError(
                        f"{terrain.name!r} and {other.name!r} are next to "
                        f"each other on the sheet and share a {axis} "
                        f"({getattr(terrain, axis)!r}); move one, so an "
                        f"author picking a block by eye cannot take the "
                        f"wrong one")
    fields = {terrain.name: terrain.field_colour() for terrain in table}
    hazards = {terrain.name for terrain in table if terrain.hazard}
    for first, second in combinations(table, 2):
        a, b = fields[first.name], fields[second.name]
        apart = distance(a, b)
        if apart < TERRAIN_DISTANCE:
            raise ValueError(
                f"{first.name!r} and {second.name!r} are {apart:.1f} apart "
                f"in CIELAB, under {TERRAIN_DISTANCE}; anywhere on the sheet "
                f"that is one material under two names, and the author picks "
                f"whichever block his eye lands on first")
        if (first.name in hazards) == (second.name in hazards):
            continue
        blind = min(distance(dichromat(a, kind), dichromat(b, kind))
                    for kind in DICHROMACIES)
        if blind >= HAZARD_DISTANCE:
            continue
        hazard, floor = ((first, second) if first.name in hazards
                         else (second, first))
        raise ValueError(
            f"{hazard.name!r} is a hazard and {floor.name!r} is ground a "
            f"body stands on, and to a red-green colourblind player they are "
            f"{blind:.1f} apart, under {HAZARD_DISTANCE} -- with only "
            f"{abs(luminance(a) - luminance(b)):.1f} of luminance between "
            f"them. For about one man in twelve those are the same tile. "
            f"Darken or lighten one of them; hue will not fix it")


def _cell_luma(terrain: Terrain, mask: int = FULL) -> list[list[float]]:
    """The luminance of one drawn cell of a terrain, [y][x]."""
    cell = quadrant(mask, terrain)
    return [[luminance(cell.get_at((x, y))[:3]) for x in range(TILE)]
            for y in range(TILE)]


def _spread(values) -> float:
    values = list(values)
    mean = sum(values) / len(values)
    return (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5


def repeat_bias(terrain: Terrain) -> float:
    """How much structure a row's cell keeps once it is blurred, in L*.

    The measurement of a wallpaper repeat, and the one thing the sheet had
    nothing for. Blurred WRAPPED, because the field is this cell repeated:
    a blob that runs off the right edge and back on the left is the same
    blob, and blurring inside the cell alone would smear it into the border
    and report less than a player sees.
    """
    grid = _cell_luma(terrain)
    side = 2 * REPEAT_BLUR + 1
    return _spread(
        sum(grid[(y + dy) % TILE][(x + dx) % TILE]
            for dy in range(-REPEAT_BLUR, REPEAT_BLUR + 1)
            for dx in range(-REPEAT_BLUR, REPEAT_BLUR + 1)) / (side * side)
        for y in range(TILE) for x in range(TILE))


def structure_bias(first: Terrain, second: Terrain) -> float:
    """How alike two rows draw, as the correlation of their luminance.

    On luminance and not on colour, deliberately: the colour rule already
    holds every pair apart in CIELAB, so what is left to ask is whether the
    two are the same PICTURE painted twice.
    """
    a = [value for row in _cell_luma(first) for value in row]
    b = [value for row in _cell_luma(second) for value in row]
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    top = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    left = sum((x - mean_a) ** 2 for x in a) ** 0.5
    right = sum((y - mean_b) ** 2 for y in b) ** 0.5
    return top / (left * right) if left and right else 0.0


def rim_contrast(terrain: Terrain) -> float:
    """How much darker an island's falling edge is than its face, in L*.

    On a deliberately built island rather than on a sheet mask, so the rim
    and the interior are both big enough to average and the number does not
    depend on which quadrant somebody picked.

    THE FACE IS WHAT THE VIEW LEFT ALONE.            #TAG:face_is_unshaded
    Not "everything that is not the rim", which is what this said while
    there was one ground shader and exactly one thing it drew. `lowangle`
    darkens the two rows above a NEAR boundary as well, and those rows are
    shading, not face: counting them dragged the face mean down onto the rim
    mean and reported an island with no edge -- `brazier_ash` measured 0.4 of
    L* against a floor of 1.5, for art that has a perfectly good edge on it.
    So a face pixel is one the view drew at the TEXTURE'S OWN colour, which
    is the same set `overhead` had (it shades nothing but the rim, so every
    number on the top-down sheet is unchanged to the digit) and the right set
    for any shader anybody adds next.
    """
    material = terrain.ramp()
    inside = field(TILE, TILE, lambda x, y: 4 <= x < 12 and 4 <= y < 12)
    cell = terrain.seen().shade(
        inside, material, lambda x, y: _texture(terrain, material, x, y))
    ox, oy = SHADOW_OFFSET
    rim, face = [], []
    for x in range(TILE):
        for y in range(TILE):
            if not inside[x][y]:
                continue
            ax, ay = x + ox, y + oy
            edge = ((0 <= ax < TILE and not inside[ax][y])
                    or (0 <= ay < TILE and not inside[x][ay]))
            value = luminance(cell.get_at((x, y))[:3])
            if edge:
                rim.append(value)
            elif cell.get_at((x, y))[:3] == _texture(terrain, material, x, y):
                face.append(value)
    if not face:
        raise ValueError(
            f"{terrain.name!r} has no unshaded face left on an 8x8 island: "
            f"view {terrain.view!r} shades every pixel of it, so there is "
            f"nothing for the falling edge to be darker THAN")
    return sum(face) / len(face) - sum(rim) / len(rim)


# `FACE_SHOW` is `palette.FACE_SHOW`, imported rather than restated: the
# shader that draws the near face and the rule that measures it read ONE
# number.                                            #TAG:face_had_no_room
# It is here because nothing measured these pixels at all. With the face
# fixed downward, three of the four hazards barely moved -- `open_pit`
# 1.29 L*, `oil_slick` 2.20, `scorched` 2.90 against a table mean of 10.2 --
# and those are the rows where the edge cue matters most: a pit read as a
# flat black mat rather than as a hole. `rim_contrast` deliberately EXCLUDES
# the near face from both of its sets (`#TAG:face_is_unshaded`), so the one
# number on the sheet that looked at these pixels looked away from them.


def face_contrast(terrain: Terrain) -> float:
    """How far this row's NEAR FACE moves off its own surface, in L*.

    Built on the same island `rim_contrast` uses, and reading the same
    definition of a face pixel from the other side: a near-face pixel is one
    the view did NOT draw at the texture's own colour and that is not the
    rim. Unsigned, because `palette.face` is signed.
    """
    material = terrain.ramp()
    inside = field(TILE, TILE, lambda x, y: 4 <= x < 12 and 4 <= y < 12)
    cell = terrain.seen().shade(
        inside, material, lambda x, y: _texture(terrain, material, x, y))
    ox, oy = SHADOW_OFFSET
    moved = []
    for x in range(TILE):
        for y in range(TILE):
            if not inside[x][y]:
                continue
            ax, ay = x + ox, y + oy
            if ((0 <= ax < TILE and not inside[ax][y])
                    or (0 <= ay < TILE and not inside[x][ay])):
                continue
            own = _texture(terrain, material, x, y)
            drawn = cell.get_at((x, y))[:3]
            if drawn != own:
                moved.append(abs(luminance(drawn) - luminance(own)))
    return sum(moved) / len(moved) if moved else 0.0


def _verify_surfaces(table: tuple[Terrain, ...]) -> None:
    """The three things a GROUND row has to be true of, as drawn.

    Ground, not overhead: the test is `shade is mass`, the one vertical-face
    model, for `_verify_lighting`'s reason. A motif the eye can find, a row
    that is another row's picture recoloured, and an island with no edge are
    all faults of a surface seen from above the plane -- at any angle.

    Every one of them was found by somebody looking at the sheet rather
    than by an assertion, which is the whole reason they are here:

    - it must not carry a motif the eye can find (`REPEAT_LIMIT`),
    - it must not be another row's picture in a different colour
      (`STRUCTURE_LIMIT`),
    - its island must have an edge (`RIM_FALL`),
    - and where the view draws a NEAR FACE, that face has to be visible
      (`FACE_SHOW`) -- which is a different set of pixels from the rim, and
      the set nothing measured.

    Measured per ROW, on the terrain's own ramp and its own salt, which is
    the field a player actually sees -- the vocabulary rules above probe
    with one grey so that a texture is judged on its structure, and a low
    contrast ramp earns its softer verdict here instead.
    """
    if not table or table[0].seen().shade is mass:
        return
    for terrain in table:
        edge = rim_contrast(terrain)
        if edge < RIM_FALL:
            raise ValueError(
                f"an island of {terrain.name!r} is only {edge:.1f} of L* "
                f"darker at its falling edge than across its face, under "
                f"{RIM_FALL}" + (" -- the rim is BRIGHTER than the surface "
                                 "it is the shadow of" if edge < 0 else "") +
                f"; the silhouette dissolves into the field and the block "
                f"stops reading as raised ground at all")
        if terrain.seen().shade is lowangle:
            # THE DOMAIN IS THE SHADER THAT DRAWS ONE.   #TAG:face_rule_domain
            # Named the way the `mass` exemption above is named, and for the
            # same reason: `overhead` draws no near face at all, so its rows
            # would measure 0 and a rule that read 0 as "nothing to check"
            # would read an INVISIBLE face as nothing to check too. A fourth
            # shader that draws a face is inside this rule the day it is
            # written rather than the day somebody remembers.
            shown = face_contrast(terrain)
            if shown < FACE_SHOW:
                raise ValueError(
                    f"the near face of {terrain.name!r} moves {shown:.2f} of "
                    f"L* off the surface it stands on, under {FACE_SHOW}: "
                    f"view {terrain.view!r} draws a wall there and a player "
                    f"cannot see one. On a near-black row that is `fall` "
                    f"running out of room -- see `palette.face`, which is "
                    f"signed for exactly this -- and a pit whose near wall is "
                    f"invisible reads as a mat painted on the floor, not as "
                    f"a hole")
        if terrain.texture not in HASHED_TEXTURES:
            continue
        motif = repeat_bias(terrain)
        if motif > REPEAT_LIMIT:
            raise ValueError(
                f"{terrain.name!r} keeps {motif:.2f} of L* once its cell is "
                f"blurred, over {REPEAT_LIMIT}: it has a shape in it big "
                f"enough to recognise, and a shape in a {TILE}px cell comes "
                f"back every {TILE} pixels across the whole map")
    hashed = [t for t in table if t.texture in HASHED_TEXTURES]
    for first, second in combinations(hashed, 2):
        alike = structure_bias(first, second)
        if alike <= STRUCTURE_LIMIT:
            continue
        raise ValueError(
            f"{first.name!r} and {second.name!r} draw the same picture -- "
            f"{alike:.3f} correlated on luminance, over {STRUCTURE_LIMIT} -- "
            f"in two colours. A hashed texture is meant to give every row "
            f"its own field; if these two agree, their salts have collided "
            f"and one of the 32 blocks is spent on a recolour")


def _verify_families_differ(tables: dict[str, tuple[Terrain, ...]] = TABLES,
                            views: dict[str, View] = VIEWS) -> None:
    """No two rows in DIFFERENT families may draw the SAME full cell.

    THE FAMILY ANALOGUE OF `STRUCTURE_LIMIT`.       #TAG:families_draw_apart
    Every colour and structure rule in this file measures WITHIN one table,
    because that is where an author picks a block from. Nothing looked across
    tables at all, and measured, two of the thirty-two `beatemup` blocks were
    the `topdown` sheet pixel for pixel on a FULL cell: `rusted_plate` against
    `rusted_plate` at 0 of 256, and `open_pit` against `void` at 0 of 256.
    Same palette, same texture, and `_salt` is a hash of the NAME -- so two
    rows that share a name in two families draw one picture, and `_flat`
    ignores the salt entirely, so two rows drawing it collide whatever they
    are called. A player cannot tell which camera a block belongs to when it
    is the same block.

    A FULL cell and not a masked one, deliberately: the mask is the
    silhouette, which is the same in every view by construction
    (`palette.lowangle`), so comparing an edge tile would report a difference
    that is only the corner shape. The full cell is what a painted field is
    made of, and on a full cell the three shaders are byte-identical -- see
    `View.shade` -- so this measures exactly the texture and the colour.

    Within one family the rows are supposed to agree: `side` and `topdown`
    are one set of materials, and `#TAG:family_is_the_set` is the rule that
    says so. This runs across families only.
    """
    drawn: dict[str, list[tuple[str, bytes]]] = {}
    for view_name, table in tables.items():
        family = view_of(view_name).family
        for terrain in table:
            cell = quadrant(FULL, terrain)
            pixels = bytes(channel
                           for y in range(TILE) for x in range(TILE)
                           for channel in cell.get_at((x, y))[:3])
            drawn.setdefault(family, []).append(
                (f"{view_name}:{terrain.name}", pixels))
    for (one, first), (two, second) in combinations(drawn.items(), 2):
        for name, pixels in first:
            twin = next((other for other, theirs in second
                         if theirs == pixels), None)
            if twin is None:
                continue
            raise ValueError(
                f"{name} and {twin} are in families {one!r} and {two!r} and "
                f"draw the same {TILE}x{TILE} cell, pixel for pixel. Two "
                f"families exist because they are two different sets of "
                f"materials; a block that is in both is a block whose camera "
                f"a player cannot name, and the cheapest cause is a shared "
                f"row NAME (which is the whole of `_salt`) or a texture that "
                f"ignores the salt")


def _verify_pack(tables: dict[str, tuple[Terrain, ...]] = TABLES) -> None:
    """Every rule, over every sheet, in one call.

    The single entry point, so "did the new sheet get judged" is not a
    question anybody has to answer by reading. Adding a view to `VIEWS` and
    a table to `TABLES` is the whole of adding a sheet; nothing else has to
    be remembered, which is the point.
    """
    _verify_views()
    _verify_view_coverage(judged=_merge_judgements(_verify_foreshortening(),
                                                   _verify_isotropy()))
    _verify_lighting()
    _verify_tables_agree(tables)
    missing = sorted(set(VIEWS) - set(tables))
    if missing:
        raise ValueError(
            f"view(s) {', '.join(missing)} exist and no table draws them; a "
            f"view with no sheet is a lighting model nobody has looked at")
    for name, table in tables.items():
        if name not in VIEWS:
            raise ValueError(f"table {name!r} names a view nothing registered")
        _verify_terrains(table)
        _verify_surfaces(table)
    _verify_families_differ(tables)


# `_verify_pack` is run AFTER `quadrant` below, not here: its colour
# rules measure the field a terrain DRAWS, so it cannot run before the
# thing that draws one exists.


def covers(mask: int, x: int, y: int, form: str = DEFAULT_FORM) -> bool:
    """Is pixel (x, y) of a quadrant terrain, for this corner mask?

    The rule, per half-quadrant, reading `own` as the corner it hugs and
    `across`/`below` as the two corners sharing an edge with it:

        own and (across or below)   solid   -- an interior or an edge tile
        own and neither             convex  -- the form's arc at the corner
        not own and both            concave -- the same arc removed
        not own, otherwise          empty

    which is the whole of the thirteen shapes. Raises on a mask no terrain
    draws, and on a form nothing registered, rather than returning a
    plausible blank.
    """
    if mask == EMPTY or mask in DIAGONALS:
        raise ValueError(f"mask {mask:04b} has no terrain art; "
                         f"editor/core/autotile.py answers it with a policy")
    if not 0 <= x < TILE or not 0 <= y < TILE:
        raise ValueError(f"({x}, {y}) is outside a {TILE}px quadrant")
    reach = form_reach(form)
    if mask == FULL:
        return True
    cx, cy = (0 if x < CORNER_RADIUS else 1), (0 if y < CORNER_RADIUS else 1)
    own = mask & _BIT_AT[(cx, cy)]
    across = mask & _BIT_AT[(1 - cx, cy)]
    below = mask & _BIT_AT[(cx, 1 - cy)]
    if own and (across or below):
        return True
    if not own and not (across and below):
        return False
    # The rounded case, either way round: the form's own boundary, measured
    # from the corner POINT -- the lattice point, not the corner pixel.
    inside = _inside(reach, _edge(x, y, cx, cy))
    return inside if own else not inside


def _salt(name: str) -> int:
    """A terrain's texture salt: a hash of its NAME, not its length.

    IT USED TO BE `len(name)` AND NAMES COLLIDE.          #TAG:salt_is_the_name
    Two rows with the same texture and the same number of letters drew the
    same picture, pixel for pixel, in different colours: `swamp` and `water`
    are both five and both drew `ripplet`, correlating at 0.98 on luminance,
    and `dirt`, `snow` and `lava` are all four. The side sheet was worse --
    `clay` and `snow` both drew `dither` at 1.000. Nothing caught it,
    because `_verify_terrains` compared the DECLARATIONS and two rows
    declaring different palettes are different rows.

    Spelled out rather than `hash()`, because `hash()` of a string is salted
    per process and these sheets are compared byte for byte across machines.
    """
    value = 0
    for letter in name:
        value = (value * 131 + ord(letter)) & 0xFFFF
    return value


def _texture(terrain: Terrain, material: Ramp, x: int, y: int) -> RGB:
    """The body colour of one terrain pixel, before edge shading."""
    return texture_fn(terrain.texture)(material, x, y, _salt(terrain.name))


def quadrant(mask: int, terrain: Terrain) -> pygame.Surface:
    """One 16px cell of one terrain, for one corner mask.

    Shading is the VIEW's, `palette.mass` or `palette.overhead`. `mass` is
    the same routine that shades a bush, which is why a side terrain edge
    and a prop edge catch the light identically; `overhead` is its sibling
    and differs only in which rim it draws. Both write nothing outside the
    occupancy grid, so the alpha -- and therefore every border and corner
    verdict the autotile checks measure -- is the same either way. It also
    guarantees the property the corner table depends on: every pixel drawn is
    inside `covers`. A highlight painted one pixel OUTSIDE the mass is how a
    generated Wang set quietly stops matching its own table -- it still looks
    right, and a corner the mask calls empty is no longer empty.
    """
    material = terrain.ramp()
    return terrain.seen().shade(
        field(TILE, TILE, lambda x, y: covers(mask, x, y, terrain.form)),
        material, lambda x, y: _texture(terrain, material, x, y))


_verify_pack()


def block(terrain: Terrain) -> pygame.Surface:
    """One 64x96 autotile group: the 4x6 quadrants of `BLOCK_MASKS`."""
    out = surface(BLOCK_WIDTH, BLOCK_HEIGHT)
    for row, masks in enumerate(BLOCK_MASKS):
        for column, mask in enumerate(masks):
            out.blit(quadrant(mask, terrain), (column * TILE, row * TILE))
    return out


def table_for(view: str = DEFAULT_VIEW) -> tuple[Terrain, ...]:
    """The 32 terrains of one view. Raises on a view with no table."""
    try:
        return TABLES[view]
    except KeyError:
        raise ValueError(
            f"no terrain table for view {view!r}; this module draws "
            f"{', '.join(sorted(TABLES))}") from None


def build_sheet(view: str = DEFAULT_VIEW) -> pygame.Surface:
    """The whole 512x384 terrain sheet for one view, one terrain per block.

    Both sheets are the same size and the same layout, block for block and
    quadrant for quadrant, because a view changes SURFACE and never
    geometry. `editor/core/autotile.py` reads the second one with nothing
    added to it.
    """
    table = table_for(view)
    _verify_pack()
    out = surface(SHEET_WIDTH, SHEET_HEIGHT)
    for index, terrain in enumerate(table):
        bx, by = index % BLOCKS_ACROSS, index // BLOCKS_ACROSS
        out.blit(block(terrain), (bx * BLOCK_WIDTH, by * BLOCK_HEIGHT))
    return out


SHEET_PATHS: dict[str, str] = {
    "side": "data/graphics/tilesets/System/TileA2.png",
    "topdown": "data/graphics/tilesets/System/TileA2_TopDown.png",
    "beatemup": "data/graphics/tilesets/System/TileA2_BeatEmUp.png",
}
"""Where each view's sheet lands, as an ENGINE path. See `#TAG:art_write_once`
for why these are spelled under `data/graphics/` and written under `data/art/`.

WHY THE SECOND ONE IS CALLED THAT              #TAG:topdown_sheet_is_not_an_rtp
Three constraints, and only one name satisfies all three.

It keeps the `A2` stem, because it IS an A2 sheet: 512x384, 8x4 blocks of
4x6 quadrants, the exact geometry `editor/core/autotile.py` reads. A tileset
whose name says something else would be a second format to explain.

It keeps `tilesets/System/`, which is the subtree `resolve_art` mirrors and
the one every `<image source>` in the tree already points into.

And the suffix is NOT an RPG Maker VX Ace RTP filename. That is the part
that matters and it is easy to get wrong: `data/graphics/` is the author's
own art, and `resolve_art` returns whatever is at the declared path BEFORE
it falls back to the shipped twin. Call this sheet `TileA1` or `TileA3` and
on the author's machine the engine would load his licensed sheet and this
generator's 32 top-down terrains would never once be seen -- with nothing
anywhere reporting a problem. `TileA2_TopDown.png` is a name the RTP does
not use, so the fallback is the only thing that can answer for it.

`TileA2_BeatEmUp.png` is the third, by all three of the same constraints. It
is an A2 sheet -- same 512x384, same 8x4 blocks of 4x6 quadrants, read by
`editor/core/autotile.py` with nothing added -- it sits in the subtree
`resolve_art` mirrors, and `_BeatEmUp` is not an RTP stem either.
"""

SHEETS = {path: (lambda view=view: build_sheet(view))
          for view, path in SHEET_PATHS.items()}


def origins(first_gid: int = 1, view: str = DEFAULT_VIEW) -> dict[str, int]:
    """terrain name -> the gid `TerrainSet(origin)` wants.

    Read through `block_origins` rather than re-multiplied here, so the sheet
    and the editor cannot come to disagree about where block 17 starts.

    The `view` argument changes WHICH TABLE is named, and the numbers never:
    block origins are geometry, and every sheet is the same 512x384 in the
    same block order. WITHIN ONE FAMILY it also changes nothing about the
    NAMES -- `_verify_tables_agree` holds `side` and `topdown` to the same 32
    materials in the same order, so the answer is the same map either way and
    a caller with a view in hand does not have to know that. ACROSS families
    it does: `beatemup` is a different 32, so block 17 is `subway_tile` there
    and `ice` in the natural family, and a caller that swaps a map from one
    family to the other is repainting it on purpose. That is what
    `View.family` declares and what the rule refuses to let happen by
    accident.
    """
    table = table_for(view)
    found = block_origins(first_gid, SHEET_COLUMNS, SHEET_TILES)
    if len(found) != len(table):
        raise ValueError(f"the sheet holds {len(found)} blocks and the "
                         f"{view} table names {len(table)}")
    return {terrain.name: origin for terrain, origin in zip(table, found)}


if __name__ == "__main__":
    from . import render_cli
    raise SystemExit(render_cli(SHEETS, "the terrain autotile sheet"))
