"""The clutter sheet: plain 16px tiles that are deliberately NOT terrain.

WHY A SECOND SHEET AT ALL
-------------------------
`terrain.py` draws ground, and ground is flat. A map made only of ground
proves nothing about this engine: depth sorting, the thing a top-down game
lives or dies on, is invisible until something stands ON the ground and a
body walks behind and in front of it. So this sheet is props -- bushes,
crates, fence posts, a tree tall enough that its canopy sorts above a walking
body and its trunk below.

THE GRID IS THE CONTRACT
------------------------
512x512 on a straight 16px grid, which is 32x32 = 1024 tiles, and every tile
is addressed by a gid computed from that grid. So the ONE invariant worth
checking is containment: a prop that paints a single pixel past its own cell
shows up as a smear on an unrelated tile, in a map nobody has drawn yet.
`PLACEMENTS` records where every item went and
`tools/check_art_tilesets.py` proves both halves of it -- nothing outside a
declared cell, and nothing declared that drew nothing.

Empty cells are normal and stay transparent. A tileset is an address space,
not a picture; filling it up to look busy would only make gids harder to
read.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pygame

from .palette import Ramp, bevel, field, mass, noise, ramp, surface

TILE = 16
SHEET_COLUMNS = 32
SHEET_ROWS = 32
SHEET_WIDTH = SHEET_COLUMNS * TILE       # 512
SHEET_HEIGHT = SHEET_ROWS * TILE         # 512

Draw = Callable[[int, int], pygame.Surface]


@dataclass(frozen=True)
class Item:
    """One drawable, sized in whole tiles. `draw(width, height)` in pixels."""

    name: str
    draw: Draw
    columns: int = 1
    rows: int = 1


@dataclass(frozen=True)
class Placement:
    """Where an item landed on the sheet, in tiles."""

    name: str
    column: int
    row: int
    columns: int
    rows: int

    def rect(self) -> pygame.Rect:
        return pygame.Rect(self.column * TILE, self.row * TILE,
                           self.columns * TILE, self.rows * TILE)


# --------------------------------------------------------------------------
# Shapes. Each returns its own surface and never draws outside it.
# --------------------------------------------------------------------------

def _ellipse(width: int, height: int, material: Ramp, *,
             cx: float | None = None, cy: float | None = None,
             rx: float | None = None, ry: float | None = None,
             texture=None) -> pygame.Surface:
    cx = width / 2 if cx is None else cx
    cy = height / 2 if cy is None else cy
    rx = width / 2 if rx is None else rx
    ry = height / 2 if ry is None else ry

    def inside(x: int, y: int) -> bool:
        dx, dy = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
        return dx * dx + dy * dy <= 1.0

    return mass(field(width, height, inside), material, texture)


def blob(colour: str, *, squash: float = 1.0, dots: int = 0) -> Draw:
    """A rounded mass -- bush, rock, boulder. The workhorse of this sheet."""
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        ry = (height / 2 - 0.5) * squash
        out = _ellipse(width, height, material,
                       cy=height - ry - 1, rx=width / 2 - 0.5, ry=ry)
        for index in range(dots):
            x = int(noise(index, 1, len(colour)) * (width - 4)) + 2
            y = int(noise(index, 2, len(colour)) * (height - 6)) + 3
            if out.get_at((x, y))[3]:
                out.set_at((x, y), material.shadow)
        return out
    return draw


def scatter(colour: str, count: int, size: int) -> Draw:
    """Pebbles, embers, bones: several small blobs on one tile."""
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        out = surface(width, height)
        for index in range(count):
            x = int(noise(index, 5, count) * (width - size - 1)) + 1
            y = int(noise(index, 9, count) * (height - size - 1)) + 1
            out.blit(_ellipse(size, size, material), (x, y))
        return out
    return draw


def tuft(colour: str, blades: int = 5) -> Draw:
    """Upright blades. Reads as grass at 16px, which nothing rounder does."""
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        out = surface(width, height)
        for index in range(blades):
            x = 1 + int((width - 2) * (index + 0.5) / blades)
            tall = 4 + int(noise(index, 3, blades) * (height // 2))
            lean = 1 if index % 2 else -1
            for step in range(tall):
                y = height - 2 - step
                bend = x + (lean if step > tall - 3 else 0)
                if 0 <= bend < width and 0 <= y < height:
                    out.set_at((bend, y),
                               material.hi if step == tall - 1 else material.base)
        return out
    return draw


def flower(stem: str, petal: str) -> Draw:
    def draw(width: int, height: int) -> pygame.Surface:
        out = tuft(stem, blades=3)(width, height)
        bloom = ramp(petal)
        cx, cy = width // 2, height // 2 - 1
        for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
            out.set_at((cx + dx, cy + dy), bloom.base)
        out.set_at((cx, cy), bloom.hi)
        return out
    return draw


def mushroom(cap: str, stalk: str) -> Draw:
    def draw(width: int, height: int) -> pygame.Surface:
        out = surface(width, height)
        body = ramp(stalk)
        for y in range(height // 2, height - 2):
            out.set_at((width // 2 - 1, y), body.base)
            out.set_at((width // 2, y), body.dark)
        out.blit(_ellipse(width - 4, height // 2, ramp(cap)), (2, 3))
        return out
    return draw


def crate(colour: str) -> Draw:
    """A braced box. Bevelled, so it reads as standing on the ground."""
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        out = surface(width, height)
        box = pygame.Rect(1, 2, width - 2, height - 3)
        out.fill(material.base, box)
        bevel(out, box, material)
        for step in range(min(box.width, box.height) - 2):
            out.set_at((box.left + 1 + step, box.top + 1 + step), material.dark)
            out.set_at((box.right - 2 - step, box.top + 1 + step), material.dark)
        return out
    return draw


def barrel(body: str, band: str) -> Draw:
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(body)
        out = _ellipse(width - 4, height - 2, material, rx=width / 2 - 2)
        hoop = ramp(band)
        for y in (3, height - 6):
            for x in range(width - 4):
                if out.get_at((x, y))[3]:
                    out.set_at((x, y), hoop.base)
        wide = surface(width, height)
        wide.blit(out, (2, 1))
        return wide
    return draw


def pot(colour: str) -> Draw:
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        out = _ellipse(width, height, material,
                       cy=height * 0.62, rx=width / 2 - 2, ry=height * 0.34)
        neck = ramp(colour)
        for y in range(3, 6):
            for x in range(width // 2 - 2, width // 2 + 2):
                out.set_at((x, y), neck.dark if y == 3 else neck.base)
        return out
    return draw


def chest(body: str, trim: str) -> Draw:
    def draw(width: int, height: int) -> pygame.Surface:
        material, metal = ramp(body), ramp(trim)
        out = surface(width, height)
        box = pygame.Rect(2, 5, width - 4, height - 7)
        out.fill(material.base, box)
        bevel(out, box, material)
        lid = pygame.Rect(1, 3, width - 2, 3)
        out.fill(material.light, lid)
        bevel(out, lid, material)
        out.set_at((width // 2, height - 5), metal.hi)
        out.set_at((width // 2, height - 6), metal.base)
        return out
    return draw


def post(colour: str, *, rail: str = "") -> Draw:
    """A fence post, optionally with a rail running across the tile."""
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        out = surface(width, height)
        if rail:
            bar = ramp(rail)
            for y in (height // 2 - 1, height // 2 + 2):
                for x in range(width):
                    out.set_at((x, y), bar.base if y % 2 else bar.dark)
        stem = pygame.Rect(width // 2 - 2, 2, 4, height - 3)
        out.fill(material.base, stem)
        bevel(out, stem, material)
        return out
    return draw


def sign(colour: str, board: str) -> Draw:
    def draw(width: int, height: int) -> pygame.Surface:
        out = post(colour)(width, height)
        plank = ramp(board)
        face = pygame.Rect(2, 2, width - 4, height // 2 - 1)
        out.fill(plank.base, face)
        bevel(out, face, plank)
        for x in range(face.left + 2, face.right - 2, 2):
            out.set_at((x, face.centery), plank.shadow)
        return out
    return draw


def torch(colour: str, flame: str) -> Draw:
    def draw(width: int, height: int) -> pygame.Surface:
        out = post(colour)(width, height)
        fire = ramp(flame)
        out.blit(_ellipse(6, 7, fire), (width // 2 - 3, 0))
        return out
    return draw


def wall(colour: str, *, courses: int = 4) -> Draw:
    """A full-tile masonry face. Tiles seamlessly left-right and up-down."""
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        out = surface(width, height)
        course = max(2, height // courses)
        for y in range(height):
            row = y // course
            offset = (course * (row % 2))
            for x in range(width):
                if y % course == course - 1 or (x + offset) % (course * 2) == course * 2 - 1:
                    colour_here = material.shadow
                elif y % course == 0:
                    colour_here = material.light
                else:
                    colour_here = material.base
                out.set_at((x, y), colour_here)
        return out
    return draw


def planks(colour: str) -> Draw:
    """A full-tile board floor, grain running across."""
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        out = surface(width, height)
        for y in range(height):
            for x in range(width):
                if y % 5 == 4:
                    colour_here = material.shadow
                elif noise(x, y // 5, 11) > 0.86:
                    colour_here = material.dark
                else:
                    colour_here = material.base
                out.set_at((x, y), colour_here)
        return out
    return draw


def stairs(colour: str) -> Draw:
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        out = surface(width, height)
        step = max(2, height // 4)
        for y in range(height):
            for x in range(width):
                out.set_at((x, y), material.hi if y % step == 0
                           else material.shadow if y % step == step - 1
                           else material.base)
        return out
    return draw


def cracks(colour: str) -> Draw:
    """Damage: dark pixels on transparent, to lay over any floor."""
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        out = surface(width, height)
        x = width // 2
        for y in range(2, height - 2):
            x = max(1, min(width - 2, x + (1 if noise(x, y, 13) > 0.5 else -1)))
            out.set_at((x, y), material.shadow)
            if noise(x, y, 17) > 0.72:
                out.set_at((x + 1, y), material.dark)
        return out
    return draw


def coin(colour: str) -> Draw:
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        out = _ellipse(width - 8, height - 8, material)
        wide = surface(width, height)
        wide.blit(out, (4, 4))
        return wide
    return draw


def gem(colour: str) -> Draw:
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)

        def inside(x: int, y: int) -> bool:
            dx = abs(x + 0.5 - width / 2)
            dy = abs(y + 0.5 - height / 2)
            return dx / (width / 2 - 3) + dy / (height / 2 - 2) <= 1.0

        out = mass(field(width, height, inside), material)
        out.set_at((width // 2 - 1, height // 2 - 2), material.hi)
        return out
    return draw


def puddle(colour: str) -> Draw:
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        return _ellipse(width, height, material, ry=height / 3.2,
                        cy=height * 0.62)
    return draw


def tree(trunk: str, canopy: str) -> Draw:
    """Two tiles wide, three tall: the depth-sorting prop.

    Its trunk sits in the bottom tile and its canopy in the top two, so a
    body walking behind it is occluded and one walking in front is not --
    which is the whole demonstration.
    """
    def draw(width: int, height: int) -> pygame.Surface:
        bark, leaves = ramp(trunk), ramp(canopy)
        out = surface(width, height)
        stem = pygame.Rect(width // 2 - 2, height - TILE - 2, 4, TILE + 2)
        out.fill(bark.base, stem)
        bevel(out, stem, bark)
        crown = _ellipse(width, height - TILE, leaves,
                         texture=lambda x, y: (leaves.light
                                               if noise(x, y, 23) > 0.78
                                               else leaves.base))
        out.blit(crown, (0, 0))
        return out
    return draw


def pine(trunk: str, canopy: str) -> Draw:
    def draw(width: int, height: int) -> pygame.Surface:
        bark, needles = ramp(trunk), ramp(canopy)
        out = surface(width, height)
        stem = pygame.Rect(width // 2 - 1, height - TILE, 3, TILE)
        out.fill(bark.base, stem)

        def inside(x: int, y: int) -> bool:
            if y >= height - TILE + 2:
                return False
            span = (y + 4) * (width / 2) / (height - TILE + 2)
            return abs(x + 0.5 - width / 2) <= span

        out.blit(mass(field(width, height, inside), needles), (0, 0))
        return out
    return draw


def pillar(colour: str) -> Draw:
    """One tile wide, three tall: a ruin, and a second occluder shape."""
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        out = surface(width, height)
        shaft = pygame.Rect(3, 3, width - 6, height - 4)
        out.fill(material.base, shaft)
        bevel(out, shaft, material)
        cap = pygame.Rect(1, 1, width - 2, 3)
        out.fill(material.light, cap)
        bevel(out, cap, material)
        for y in range(shaft.top + 2, shaft.bottom - 1, 4):
            for x in range(shaft.left + 1, shaft.right - 1):
                out.set_at((x, y), material.dark)
        return out
    return draw


def swatch(colour: str) -> Draw:
    """A flat fill of one palette entry, outlined so its cell is visible.

    The plainest thing on the sheet and the most used: a backdrop, a block-out
    floor, a colour to point at while deciding what a map should look like.
    """
    def draw(width: int, height: int) -> pygame.Surface:
        material = ramp(colour)
        out = surface(width, height)
        out.fill(material.base)
        for x in range(width):
            out.set_at((x, 0), material.light)
            out.set_at((x, height - 1), material.dark)
        return out
    return draw


# --------------------------------------------------------------------------
# The catalogue
# --------------------------------------------------------------------------

def _swatches() -> list[Item]:
    from .palette import BASES
    return [Item(f"swatch_{name}", swatch(name)) for name in sorted(BASES)]


CLUTTER: tuple[Item, ...] = (
    Item("bush", blob("leaf", dots=3)),
    Item("bush_dark", blob("forest", dots=3)),
    Item("shrub", blob("moss", squash=0.7, dots=2)),
    Item("rock", blob("stone", squash=0.8, dots=2)),
    Item("rock_dark", blob("granite", squash=0.8, dots=2)),
    Item("clay_mound", blob("clay", squash=0.6)),
    Item("snow_drift", blob("snow", squash=0.5)),
    Item("pebbles", scatter("gravel", 4, 4)),
    Item("bones", scatter("bone", 3, 4)),
    Item("embers", scatter("ember", 5, 3)),
    Item("crystals", scatter("crystal", 3, 5)),
    Item("grass_tuft", tuft("grass")),
    Item("reeds", tuft("tall_grass", blades=3)),
    Item("dry_tuft", tuft("sand", blades=4)),
    Item("flower_red", flower("grass", "ember")),
    Item("flower_gold", flower("grass", "gold")),
    Item("flower_blue", flower("grass", "cloth")),
    Item("flower_white", flower("moss", "chalk")),
    Item("mushroom_red", mushroom("brick", "chalk")),
    Item("mushroom_pale", mushroom("chalk", "bone")),
    Item("crate", crate("wood")),
    Item("crate_old", crate("bark")),
    Item("barrel", barrel("plank", "metal")),
    Item("barrel_rust", barrel("wood", "rust")),
    Item("pot", pot("clay")),
    Item("pot_stone", pot("stone")),
    Item("chest", chest("wood", "gold")),
    Item("chest_iron", chest("metal", "gold")),
    Item("fence_post", post("bark")),
    Item("fence_rail", post("bark", rail="bark")),
    Item("fence_post_stone", post("stone")),
    Item("fence_rail_stone", post("stone", rail="stone")),
    Item("signpost", sign("bark", "plank")),
    Item("torch", torch("bark", "lava")),
    Item("brazier", torch("metal", "ember")),
    Item("wall_brick", wall("brick")),
    Item("wall_stone", wall("cobble")),
    Item("wall_granite", wall("granite", courses=2)),
    Item("floor_planks", planks("plank")),
    Item("floor_boards", planks("wood")),
    Item("stairs_stone", stairs("stone")),
    Item("stairs_wood", stairs("wood")),
    Item("cracks", cracks("ash")),
    Item("cracks_ice", cracks("ice")),
    Item("puddle", puddle("water")),
    Item("puddle_mud", puddle("mud")),
    Item("coin", coin("gold")),
    Item("gem", gem("crystal")),
    Item("gem_red", gem("brick")),
)

PROPS: tuple[Item, ...] = (
    Item("tree", tree("bark", "leaf"), columns=2, rows=3),
    Item("tree_autumn", tree("bark", "clay"), columns=2, rows=3),
    Item("pine", pine("bark", "forest"), columns=2, rows=3),
    Item("boulder", blob("granite", squash=0.8, dots=5), columns=2, rows=2),
    Item("big_bush", blob("forest", dots=6), columns=2, rows=2),
    Item("pillar", pillar("marble"), columns=1, rows=3),
    Item("pillar_broken", pillar("chalk"), columns=1, rows=2),
)


def catalogue() -> list[Item]:
    """Everything the sheet holds, in the order it is laid out."""
    return _swatches() + list(CLUTTER) + list(PROPS)


def layout(items: list[Item] | None = None) -> list[Placement]:
    """Pack items left to right in shelves. Deterministic, and it RAISES.

    A packer that silently dropped the overflow would produce a sheet
    missing whichever prop was added last, and the author would go looking
    for a drawing bug.
    """
    items = catalogue() if items is None else items
    placements: list[Placement] = []
    column = row = shelf = 0
    for item in items:
        if item.columns > SHEET_COLUMNS:
            raise ValueError(f"{item.name} is {item.columns} tiles wide and "
                             f"the sheet is {SHEET_COLUMNS}")
        if column + item.columns > SHEET_COLUMNS:
            row += shelf
            column = shelf = 0
        if row + item.rows > SHEET_ROWS:
            raise ValueError(
                f"{item.name} does not fit: the sheet is {SHEET_COLUMNS}x"
                f"{SHEET_ROWS} tiles and this is row {row}")
        placements.append(Placement(item.name, column, row,
                                    item.columns, item.rows))
        column += item.columns
        shelf = max(shelf, item.rows)
    return placements


PLACEMENTS: tuple[Placement, ...] = tuple(layout())


def build_sheet() -> pygame.Surface:
    """The whole 512x512 clutter sheet."""
    items = catalogue()
    out = surface(SHEET_WIDTH, SHEET_HEIGHT)
    for item, place in zip(items, PLACEMENTS):
        cell = place.rect()
        drawn = item.draw(cell.width, cell.height)
        if drawn.get_size() != (cell.width, cell.height):
            raise ValueError(
                f"{item.name} drew {drawn.get_width()}x{drawn.get_height()} "
                f"into a {cell.width}x{cell.height} cell; a tile that "
                f"overhangs its cell smears onto an unrelated gid")
        out.blit(drawn, cell.topleft)
    return out


SHEETS = {"data/graphics/tilesets/System/TileC.png": build_sheet}


if __name__ == "__main__":
    from . import render_cli
    raise SystemExit(render_cli(SHEETS, "the clutter and prop tile sheet"))
