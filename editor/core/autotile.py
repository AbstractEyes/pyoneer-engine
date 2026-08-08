"""Directional fill -- painting terrain that picks its own edge tiles.

WHAT THIS IS, AND WHY IT IS A CORNER SET
----------------------------------------
The art already in this project decides the design. `TileA2.png` is an RPG
Maker VX Ace A2 sheet: 512x384 at 16px, which is 8x4 = **32 autotile
groups**, each a 64x96 block = a 4x6 grid of 16x16 quadrants. And because
this map's cells are *also* 16px, one map cell is exactly one quadrant.

That makes the block a two-colour **Wang corner set** at map resolution:
terrain lives on the (W+1)x(H+1) lattice of cell CORNERS, and cell (x, y)
draws whichever of 16 tiles matches its four corners --
(x,y), (x+1,y), (x,y+1), (x+1,y+1).

Thirteen of the sixteen masks have art. The other three:

    0000   no terrain -- nothing to draw, the cell keeps its old gid
    1001   terrain on TL+BR only \\  the two diagonals. No RPG Maker sheet
    0110   terrain on TR+BL only /   draws these; see `Diagonal`.

An orthogonal 16-value bitmask (N/E/S/W) was the obvious alternative and is
wrong here: it cannot address the four concave/inner corner quadrants the
block ships, so every inside corner and T-junction would render with a hard
seam -- the exact defect the feature exists to remove.

A TERRAIN IS ONE INTEGER
------------------------
Every gid in a group is a fixed offset from the group's top-left gid, so a
terrain needs no authored data at all: `TerrainSet(origin)` derives the whole
13-entry table. There are 32 origins in TileA2 --
1, 5, 9, 13, 17, 21, 25, 29 / 193.. / 385.. / 577..

THE HALF-CELL TRAP
------------------
Terrain is on corners; tiles are on cells. Painting "at cell (x, y)" by
setting its four corners makes the visible mass appear half a cell up-left
of the cursor and one cell larger than the drag. This module therefore
works in CORNER coordinates throughout and the caller decides how a cursor
maps to a corner. `cells_touching()` is the bridge, and it is why an
autotile stroke rewrites cells *outside* its own footprint -- editing one
corner changes four cells, so the seam against existing terrain updates too.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable

Reader = Callable[[int, int], int]
Edit = tuple[int, int, int]
Corner = tuple[int, int]

# Corner occupancy bits. A cell's mask is the OR of the corners it owns.
TOP_LEFT = 8
TOP_RIGHT = 4
BOTTOM_LEFT = 2
BOTTOM_RIGHT = 1

FULL = TOP_LEFT | TOP_RIGHT | BOTTOM_LEFT | BOTTOM_RIGHT   # 15
EMPTY = 0
DIAGONALS = (TOP_LEFT | BOTTOM_RIGHT, TOP_RIGHT | BOTTOM_LEFT)   # 9, 6

# Where each mask's art sits inside the 4x6 quadrant block, as (column, row).
# Verified against the pixels of TileA2.png rather than recalled: the
# top-left 32x32 tile is the isolated blob (four convex corners), the
# top-right 32x32 tile is the four concave corners, and the bottom 2x2 tiles
# form one 64x64 rounded rectangle whose edges and corners supply the rest.
QUADRANT: dict[int, tuple[int, int]] = {
    FULL: (1, 3),                       # interior fill
    0b0111: (2, 0),                     # concave, notch at top-left
    0b1011: (3, 0),                     # concave, notch at top-right
    0b1101: (2, 1),                     # concave, notch at bottom-left
    0b1110: (3, 1),                     # concave, notch at bottom-right
    0b0011: (1, 2),                     # straight edge, terrain below
    0b1100: (1, 5),                     # straight edge, terrain above
    0b0101: (0, 3),                     # straight edge, terrain right
    0b1010: (3, 3),                     # straight edge, terrain left
    0b0001: (0, 2),                     # convex, terrain in bottom-right
    0b0010: (3, 2),                     # convex, terrain in bottom-left
    0b0100: (0, 5),                     # convex, terrain in top-right
    0b1000: (3, 5),                     # convex, terrain in top-left
}

BLOCK_QUADRANT_COLUMNS = 4
BLOCK_QUADRANT_ROWS = 6


class Diagonal(Enum):
    """What to draw where two terrain regions touch at a single corner.

    No RPG Maker sheet has art for it, so this is a policy, not a lookup.
    Silently indexing the table and raising KeyError mid-stroke is the
    failure mode this replaces.
    """

    MERGE = "merge"       # draw solid: the regions join. Reads best.
    SPLIT = "split"       # draw nothing: the regions pinch apart.
    RAISE = "raise"       # refuse, so a caller can nudge a corner instead


class PyoneerAutotileError(Exception):
    """A configuration this terrain cannot draw."""


@dataclass(frozen=True)
class TerrainSet:
    """One autotile group, identified by its top-left gid."""

    origin: int
    columns: int = 32
    name: str = ""
    diagonal: Diagonal = Diagonal.MERGE

    def __post_init__(self) -> None:
        if self.origin < 1:
            raise ValueError(f"a gid is 1-based; got origin {self.origin}")
        if self.columns < BLOCK_QUADRANT_COLUMNS:
            raise ValueError(
                f"a tileset needs at least {BLOCK_QUADRANT_COLUMNS} columns "
                f"to hold an autotile block; got {self.columns}")

    def gid_for(self, mask: int) -> int | None:
        """The tile for a corner mask, or None when nothing should be drawn."""
        if mask == EMPTY:
            return None
        if mask in DIAGONALS:
            if self.diagonal is Diagonal.MERGE:
                mask = FULL
            elif self.diagonal is Diagonal.SPLIT:
                return None
            else:
                raise PyoneerAutotileError(
                    f"terrain {self.name or self.origin} has no art for the "
                    f"diagonal corner mask {mask:04b}; two regions meet at a "
                    f"single point. Nudge one corner, or set "
                    f"diagonal=Diagonal.MERGE.")
        column, row = QUADRANT[mask]
        return self.origin + row * self.columns + column

    def table(self) -> dict[int, int]:
        """mask -> gid, for the 13 masks that have art."""
        return {mask: self.origin + row * self.columns + column
                for mask, (column, row) in QUADRANT.items()}

    def reverse(self) -> dict[int, int]:
        """gid -> mask, for recovering terrain from an existing layer.

        Lossy by construction and deliberately so. Two collisions are
        inherent to the format and both resolve toward the LARGER mask,
        because a tile that could be either is more usefully read as more
        terrain than less:

          * the fill quadrant appears four times in the ring interior
          * each single-corner convex mask appears twice -- once as a ring
            corner, once inside the isolated blob tile

        A gid that is not in the table means "not this terrain", which
        correctly includes gid 0.
        """
        out: dict[int, int] = {}
        for mask, gid in sorted(self.table().items()):
            out.setdefault(gid, mask)
            if bin(mask).count("1") > bin(out[gid]).count("1"):
                out[gid] = mask
        return out

    def contains(self, gid: int) -> bool:
        return gid in self.reverse()


# --------------------------------------------------------------------------
# Finding terrains in a sheet
# --------------------------------------------------------------------------

def block_origins(first_gid: int, columns: int, tile_count: int) -> list[int]:
    """Every autotile group origin in a sheet laid out as 4x6 blocks."""
    rows = tile_count // columns if columns else 0
    across = columns // BLOCK_QUADRANT_COLUMNS
    down = rows // BLOCK_QUADRANT_ROWS
    return [first_gid + (by * BLOCK_QUADRANT_ROWS) * columns
            + bx * BLOCK_QUADRANT_COLUMNS
            for by in range(down) for bx in range(across)]


def origin_for_gid(gid: int, first_gid: int, columns: int) -> int:
    """The autotile group a gid belongs to.

    Lets the UI say "the terrain is whatever block you clicked in" rather
    than making the user pick an origin out of a list of 32 integers.
    """
    local = gid - first_gid
    if local < 0:
        raise ValueError(f"gid {gid} is below this tileset's first gid "
                         f"{first_gid}")
    quadrant_column = local % columns
    quadrant_row = local // columns
    block_x = quadrant_column // BLOCK_QUADRANT_COLUMNS
    block_y = quadrant_row // BLOCK_QUADRANT_ROWS
    return (first_gid + (block_y * BLOCK_QUADRANT_ROWS) * columns
            + block_x * BLOCK_QUADRANT_COLUMNS)


# --------------------------------------------------------------------------
# The corner field
# --------------------------------------------------------------------------

@dataclass
class Bounds:
    width: int
    height: int

    def contains_cell(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def contains_corner(self, x: int, y: int) -> bool:
        # One more corner than cells on each axis.
        return 0 <= x <= self.width and 0 <= y <= self.height


def corner_field(read: Reader, bounds: Bounds, terrain: TerrainSet) -> set[Corner]:
    """Recover which lattice corners hold this terrain, from the tiles.

    Nothing on disk records terrain -- a tmx stores gids -- so it is read
    back out of the art every time. That is also why an unrelated gid is
    simply "not this terrain" rather than an error.
    """
    reverse = terrain.reverse()
    field: set[Corner] = set()
    for y in range(bounds.height):
        for x in range(bounds.width):
            mask = reverse.get(read(x, y))
            if not mask:
                continue
            if mask & TOP_LEFT:
                field.add((x, y))
            if mask & TOP_RIGHT:
                field.add((x + 1, y))
            if mask & BOTTOM_LEFT:
                field.add((x, y + 1))
            if mask & BOTTOM_RIGHT:
                field.add((x + 1, y + 1))
    return field


def mask_at(field: set[Corner], x: int, y: int) -> int:
    """The corner mask for cell (x, y)."""
    mask = 0
    if (x, y) in field:
        mask |= TOP_LEFT
    if (x + 1, y) in field:
        mask |= TOP_RIGHT
    if (x, y + 1) in field:
        mask |= BOTTOM_LEFT
    if (x + 1, y + 1) in field:
        mask |= BOTTOM_RIGHT
    return mask


def corners_of_cell(x: int, y: int) -> tuple[Corner, Corner, Corner, Corner]:
    return (x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)


def cells_touching(corners: Iterable[Corner], bounds: Bounds) -> set[tuple[int, int]]:
    """Every cell whose appearance depends on any of these corners.

    One corner is shared by up to four cells, so editing a single lattice
    point dirties four of them -- which is exactly why an autotile stroke
    cannot be expressed as "the cells the brush covered".
    """
    cells: set[tuple[int, int]] = set()
    for cx, cy in corners:
        for x, y in ((cx - 1, cy - 1), (cx, cy - 1), (cx - 1, cy), (cx, cy)):
            if bounds.contains_cell(x, y):
                cells.add((x, y))
    return cells


# --------------------------------------------------------------------------
# Resolving
# --------------------------------------------------------------------------

def resolve(read: Reader, bounds: Bounds, field: set[Corner],
            cells: Iterable[tuple[int, int]], terrain: TerrainSet,
            *, clear_gid: int | None = None) -> list[Edit]:
    """Re-tile `cells` from the corner field. Returns only real changes.

    `clear_gid` is what a cell with no terrain becomes. None -- the default
    -- leaves such cells alone, so painting terrain over a decorated floor
    does not erase the decoration outside the region.
    """
    edits: list[Edit] = []
    for x, y in sorted(cells):
        if not bounds.contains_cell(x, y):
            continue
        gid = terrain.gid_for(mask_at(field, x, y))
        if gid is None:
            if clear_gid is None:
                continue
            gid = clear_gid
        if read(x, y) != gid:
            edits.append((x, y, gid))
    return edits


def paint(read: Reader, bounds: Bounds, terrain: TerrainSet,
          corners: Iterable[Corner], *, erase: bool = False,
          field: set[Corner] | None = None,
          clear_gid: int | None = None) -> tuple[list[Edit], set[Corner]]:
    """Add (or remove) terrain at `corners` and re-tile everything affected.

    Returns the edits and the updated field, so a live stroke can keep
    painting without re-scanning the whole layer between mouse moves.
    """
    working = corner_field(read, bounds, terrain) if field is None else field
    touched: set[Corner] = set()
    for corner in corners:
        if not bounds.contains_corner(*corner):
            continue
        if erase:
            working.discard(corner)
        else:
            working.add(corner)
        touched.add(corner)
    if not touched:
        return [], working
    return resolve(read, bounds, working,
                   cells_touching(touched, bounds), terrain,
                   clear_gid=clear_gid), working


def corners_for_cell_brush(x: int, y: int) -> tuple[Corner, ...]:
    """The four corners a "fill this cell with terrain" gesture sets.

    Offered because cell-aiming is what most people expect from a brush,
    while corner-aiming is what the format actually wants. The caller picks;
    this module does not decide for them.
    """
    return corners_of_cell(x, y)
