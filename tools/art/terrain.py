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

WHY THE BOUNDARY IS A CIRCLE OF RADIUS 8
----------------------------------------
The mass in a quadrant has to meet its neighbour's mass exactly at the shared
edge, or every tile join shows a step. Crossing each edge at its midpoint is
what makes that true, and the shape that does it while staying convex is a
quarter circle of radius `CORNER_RADIUS` -- half a tile -- centred on the
corner. It also leaves about seven pixels of clearance at every corner the
mask calls empty, which is what lets a check probe a corner and get a
straight answer instead of a judgement call.
"""
from __future__ import annotations

from dataclasses import dataclass

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

from .palette import Ramp, field, mass, noise, ramp, surface

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


@dataclass(frozen=True)
class Terrain:
    """One paintable material: which ramp, and how its surface is textured."""

    name: str
    palette: str
    texture: str = "speckle"

    def ramp(self) -> Ramp:
        return ramp(self.palette)


# One per block, read left to right then top to bottom -- the order
# `block_origins` returns, so block N here IS origin N there.
TERRAINS: tuple[Terrain, ...] = (
    Terrain("grass", "grass", "speckle"),
    Terrain("tall_grass", "tall_grass", "grain"),
    Terrain("moss", "moss", "speckle"),
    Terrain("forest_floor", "forest", "speckle"),
    Terrain("swamp", "swamp", "wave"),
    Terrain("dirt", "dirt", "speckle"),
    Terrain("mud", "mud", "wave"),
    Terrain("clay", "clay", "dither"),

    Terrain("sand", "sand", "speckle"),
    Terrain("gravel", "gravel", "speckle"),
    Terrain("stone", "stone", "dither"),
    Terrain("cobble", "cobble", "brick"),
    Terrain("granite", "granite", "dither"),
    Terrain("obsidian", "obsidian", "flat"),
    Terrain("ash", "ash", "speckle"),
    Terrain("chalk", "chalk", "dither"),

    Terrain("snow", "snow", "speckle"),
    Terrain("ice", "ice", "wave"),
    Terrain("water", "water", "wave"),
    Terrain("deep_water", "deep_water", "wave"),
    Terrain("shallow_water", "shallow", "wave"),
    Terrain("lava", "lava", "wave"),
    Terrain("embers", "ember", "speckle"),
    Terrain("bone_field", "bone", "speckle"),

    Terrain("wood_floor", "wood", "grain"),
    Terrain("planks", "plank", "grain"),
    Terrain("brickwork", "brick", "brick"),
    Terrain("tiled_floor", "tile_floor", "brick"),
    Terrain("marble", "marble", "dither"),
    Terrain("carpet", "rug", "dither"),
    Terrain("metal_plate", "metal", "flat"),
    Terrain("rusted_plate", "rust", "speckle"),
)

TEXTURES = ("flat", "speckle", "dither", "grain", "wave", "brick")


def covers(mask: int, x: int, y: int) -> bool:
    """Is pixel (x, y) of a quadrant terrain, for this corner mask?

    The rule, per half-quadrant, reading `own` as the corner it hugs and
    `across`/`down` as the two corners sharing an edge with it:

        own and (across or down)   solid   -- an interior or an edge tile
        own and neither            convex  -- a quarter circle at the corner
        not own and both           concave -- the same quarter circle removed
        not own, otherwise         empty

    which is the whole of the thirteen shapes. Raises on a mask no terrain
    draws rather than returning a plausible blank.
    """
    if mask == EMPTY or mask in DIAGONALS:
        raise ValueError(f"mask {mask:04b} has no terrain art; "
                         f"editor/core/autotile.py answers it with a policy")
    if not 0 <= x < TILE or not 0 <= y < TILE:
        raise ValueError(f"({x}, {y}) is outside a {TILE}px quadrant")
    if mask == FULL:
        return True
    cx, cy = (0 if x < CORNER_RADIUS else 1), (0 if y < CORNER_RADIUS else 1)
    own = mask & _BIT_AT[(cx, cy)]
    across = mask & _BIT_AT[(1 - cx, cy)]
    down = mask & _BIT_AT[(cx, 1 - cy)]
    if own and (across or down):
        return True
    if not own and not (across and down):
        return False
    # The rounded case, either way round: the distance from the corner POINT
    # -- the lattice point, not the corner pixel -- to this pixel's centre.
    dx = (x + 0.5) - cx * TILE
    dy = (y + 0.5) - cy * TILE
    inside = dx * dx + dy * dy <= CORNER_RADIUS * CORNER_RADIUS
    return bool(inside) if own else not inside


def _texture(terrain: Terrain, material: Ramp, x: int, y: int) -> tuple[int, int, int]:
    """The body colour of one terrain pixel, before edge shading."""
    kind = terrain.texture
    if kind == "flat":
        return material.base
    if kind == "speckle":
        value = noise(x, y, len(terrain.name))
        if value < 0.10:
            return material.dark
        if value > 0.92:
            return material.light
        return material.base
    if kind == "dither":
        return material.light if (x + y) % 2 == 0 else material.base
    if kind == "grain":
        if y % 4 == 0:
            return material.dark
        return material.light if noise(x // 3, y, 7) > 0.72 else material.base
    if kind == "wave":
        band = (y + (x // 4) % 2) % 6
        if band == 0:
            return material.light
        if band == 3:
            return material.dark
        return material.base
    if kind == "brick":
        row = y // 4
        offset = 4 * (row % 2)
        if y % 4 == 3 or (x + offset) % 8 == 7:
            return material.shadow
        return material.base
    raise ValueError(f"terrain {terrain.name!r} asks for texture {kind!r}; "
                     f"this module draws {TEXTURES}")


def quadrant(mask: int, terrain: Terrain) -> pygame.Surface:
    """One 16px cell of one terrain, for one corner mask.

    Shading is `palette.mass`, the same routine that shades a bush, which is
    why a terrain edge and a prop edge catch the light identically. It also
    guarantees the property the corner table depends on: every pixel drawn is
    inside `covers`. A highlight painted one pixel OUTSIDE the mass is how a
    generated Wang set quietly stops matching its own table -- it still looks
    right, and a corner the mask calls empty is no longer empty.
    """
    material = terrain.ramp()
    return mass(field(TILE, TILE, lambda x, y: covers(mask, x, y)), material,
                lambda x, y: _texture(terrain, material, x, y))


def block(terrain: Terrain) -> pygame.Surface:
    """One 64x96 autotile group: the 4x6 quadrants of `BLOCK_MASKS`."""
    out = surface(BLOCK_WIDTH, BLOCK_HEIGHT)
    for row, masks in enumerate(BLOCK_MASKS):
        for column, mask in enumerate(masks):
            out.blit(quadrant(mask, terrain), (column * TILE, row * TILE))
    return out


def build_sheet() -> pygame.Surface:
    """The whole 512x384 terrain sheet, one terrain per block."""
    if len(TERRAINS) != BLOCKS_ACROSS * BLOCKS_DOWN:
        raise ValueError(f"the sheet holds {BLOCKS_ACROSS * BLOCKS_DOWN} "
                         f"blocks and TERRAINS names {len(TERRAINS)}")
    out = surface(SHEET_WIDTH, SHEET_HEIGHT)
    for index, terrain in enumerate(TERRAINS):
        bx, by = index % BLOCKS_ACROSS, index // BLOCKS_ACROSS
        out.blit(block(terrain), (bx * BLOCK_WIDTH, by * BLOCK_HEIGHT))
    return out


SHEETS = {"data/graphics/tilesets/System/TileA2.png": build_sheet}


def origins(first_gid: int = 1) -> dict[str, int]:
    """terrain name -> the gid `TerrainSet(origin)` wants.

    Read through `block_origins` rather than re-multiplied here, so the sheet
    and the editor cannot come to disagree about where block 17 starts.
    """
    found = block_origins(first_gid, SHEET_COLUMNS, SHEET_TILES)
    if len(found) != len(TERRAINS):
        raise ValueError(f"the sheet holds {len(found)} blocks and TERRAINS "
                         f"names {len(TERRAINS)}")
    return {terrain.name: origin for terrain, origin in zip(TERRAINS, found)}


if __name__ == "__main__":
    from . import render_cli
    raise SystemExit(render_cli(SHEETS, "the terrain autotile sheet"))
