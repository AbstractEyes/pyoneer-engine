"""The collision mask palette: one tile per mask, in mask order.

    .venv/Scripts/python.exe -m tools.art.collision

NOTHING RENDERS THESE PIXELS, AND THE FILE STILL HAS TO EXIST
------------------------------------------------------------
A mask is stored as a gid: tile N of the tileset named `collision` IS mask N,
and `scripts/core/collision_runtime.py` reads the NUMBER. The editor draws its
own glyphs over the map from `editor.ui.collision_view`, and a companion
layer declares `pyoneer_renders=false` so `rebuild()` never blits it. But
pytmx opens every `<image source>` it parses, and `pygame.image.load` raises
`FileNotFoundError`, which stops the whole map loading -- so a map that
declares the tileset needs the file on disk at the declared size or it will
not open at all.

They are drawn legibly anyway, because someone opens it in Tiled eventually
and a sheet of blank squares tells them nothing about which tile is which.

THE VOCABULARY IS IMPORTED, NEVER RESPELLED               #TAG:art_mask_domain
------------------------------------------------------------------------
`STAR` and the four direction bits come from `scripts.core.collision_runtime`,
so the sheet is `STAR + 1` tiles wide by derivation rather than by anybody
typing 17. A mask added to that vocabulary widens this sheet in the same
change; a sheet that hard-coded its own count would instead go quietly one
tile short, and a mask a tileset cannot address is a wall the player walks
through.

THE SIZE IS THE MAP'S TILE SIZE, AND THIS PACK PINS 16    #TAG:art_mask_tile_16
------------------------------------------------------------------------
`editor.ui.canvas.write_mask_sheet` provisions the same file at the tile size
of the map being edited, and `Canvas.collision_tileset_offer` MEASURES a
sheet already on disk rather than assuming its shape. Both maps in this
repository are 16px, so `SHEETS` pins 16 and the two agree. On a map with a
different tile size the editor would measure this 16px sheet and derive the
wrong column count: delete the file there and let the first collision stroke
provision it, or call `mask_palette(tile)` with that map's size.
"""
from __future__ import annotations

import pygame

from scripts.core.collision_runtime import (
    BLOCK_DOWN,
    BLOCK_LEFT,
    BLOCK_RIGHT,
    BLOCK_UP,
    PASS_ALL,
    STAR,
)
from tools.art import Builder, render_cli
from tools.art.palette import fill, outline_rect, ramp, surface

TILE = 16
"""The tile size this pack writes. See `#TAG:art_mask_tile_16`."""

MASK_DOMAIN: tuple[int, ...] = tuple(range(STAR + 1))
"""Every mask that has a tile, in the order the tiles are laid out: mask N is
tile N, which is the arithmetic `collision_runtime` does to read one back."""

PLATE = ramp("obsidian")
BAR = ramp("ember")
OPEN = ramp("grass")
DEFER = ramp("gold")

PLATE_ALPHA = 150
"""The plate is translucent so the sheet reads as an overlay vocabulary
rather than as terrain somebody might paint with by mistake."""

#: Which edge each direction bit owns, as a function of the tile box. A bar
#: is drawn on the edge it BLOCKS, so `BLOCK_LEFT` puts ink down the left.
EDGES = {
    BLOCK_UP: lambda t, b: (1, 1, t - 2, b),
    BLOCK_DOWN: lambda t, b: (1, t - 1 - b, t - 2, b),
    BLOCK_LEFT: lambda t, b: (1, 1, b, t - 2),
    BLOCK_RIGHT: lambda t, b: (t - 1 - b, 1, b, t - 2),
}


def glyph(mask: int, tile: int = TILE) -> pygame.Surface:
    """One mask as a `tile` x `tile` surface.

    Raises for a mask outside the vocabulary, rather than drawing an empty
    plate that would read on the sheet as a legal "no opinion" tile.
    """
    if mask not in MASK_DOMAIN:
        raise ValueError(
            f"mask {mask} is outside the vocabulary 0..{STAR}; "
            f"collision_runtime stores a mask as a gid offset, so a tile "
            f"outside that range addresses nothing")
    out = surface(tile, tile)
    out.fill((*PLATE.shadow, PLATE_ALPHA))
    outline_rect(out, (0, 0, tile, tile), PLATE.dark)

    if mask == STAR:
        # Star abstains: it defers to the layer below. It gets the one glyph
        # with no edge in it, because it blocks no edge.
        _star(out, tile)
        return out
    if mask == PASS_ALL:
        _open(out, tile)
        return out

    bar = max(2, tile // 5)
    for bit, box in EDGES.items():
        if mask & bit:
            x, y, w, h = box(tile, bar)
            fill(out, (x, y, w, h), BAR.base)
            fill(out, (x, y, max(1, w // 4), 1), BAR.hi)
    return out


def _open(out: pygame.Surface, tile: int) -> None:
    """A hollow diamond: passable in every direction, and not empty."""
    mid = tile // 2
    arm = max(2, tile // 5)
    for step in range(arm + 1):
        for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            out.set_at((mid + sx * step, mid + sy * (arm - step)), OPEN.hi)


def _star(out: pygame.Surface, tile: int) -> None:
    """A four-point star: the one mask that is not a direction."""
    mid = tile // 2
    arm = max(3, tile // 2 - 2)
    fill(out, (mid - 1, mid - arm, 2, arm * 2), DEFER.base)
    fill(out, (mid - arm, mid - 1, arm * 2, 2), DEFER.base)
    for step in range(1, arm - 1):
        for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            out.set_at((mid + sx * step, mid + sy * step), DEFER.dark)
    fill(out, (mid - 1, mid - 1, 2, 2), DEFER.hi)


def mask_palette(tile: int = TILE) -> pygame.Surface:
    """The whole vocabulary in one strip, tile N at x = N * tile."""
    out = surface(len(MASK_DOMAIN) * tile, tile)
    for index, mask in enumerate(MASK_DOMAIN):
        out.blit(glyph(mask, tile), (index * tile, 0))
    return out


SHEETS: dict[str, Builder] = {
    # The path `editor.ui.canvas.COLLISION_IMAGE` proposes, resolved from
    # data/maps/ where the .tmx that declares it lives.
    "data/graphics/tilesets/System/Collision.png": mask_palette,
}


if __name__ == "__main__":
    raise SystemExit(render_cli(SHEETS, "the collision mask palette"))
