"""The shared look: one palette, a handful of primitives, no framework.

Every sheet in this package is drawn from here, which is the only reason a
terrain block and a character walk cycle read as the same art rather than as
two people's guesses. Import what you need; do not grow this into a renderer.

WHY THE RAMPS ARE DERIVED AND NOT AUTHORED
------------------------------------------
A hand-authored five-shade ramp per colour is 38 chances to pick a shadow
that is bluer than its neighbour's, and the result looks like a palette
swap rather than one world. Here every ramp mixes toward the SAME `SHADOW`
and the SAME `LIGHT`, so unrelated materials share a light source without
anybody remembering to. `BASES` is therefore the whole palette: one RGB per
material, and the shading falls out.

DETERMINISM IS A CONTRACT
-------------------------
`noise` is an integer hash, not `random`. The sheets are regenerated on
other machines and compared pixel-for-pixel by `tools/check_art_tilesets.py`,
so a texture that depends on interpreter version or seeding order would be a
check that fails for the next person and nobody else.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import pygame

RGB = tuple[int, int, int]

# Every dark step mixes toward this violet and every light step toward this
# cream. Shared, so two materials lit side by side agree about the sun.
SHADOW: RGB = (26, 22, 40)
LIGHT: RGB = (255, 248, 220)

# The one line colour. Sprites outline; tiles mostly do not.
OUTLINE: RGB = (30, 26, 44)

BASES: dict[str, RGB] = {
    "grass": (86, 140, 62),
    "tall_grass": (66, 116, 52),
    "moss": (74, 118, 74),
    "forest": (46, 92, 58),
    "swamp": (78, 96, 56),
    "leaf": (96, 152, 66),
    "bark": (108, 78, 54),
    "dirt": (140, 104, 66),
    "mud": (98, 76, 54),
    "clay": (162, 100, 70),
    "sand": (214, 186, 122),
    "gravel": (150, 144, 132),
    "stone": (128, 128, 136),
    "cobble": (110, 112, 124),
    "granite": (96, 100, 112),
    "obsidian": (56, 54, 72),
    "ash": (86, 84, 86),
    "chalk": (206, 202, 190),
    "snow": (232, 238, 244),
    "ice": (162, 202, 226),
    "water": (72, 128, 196),
    "deep_water": (46, 84, 152),
    "shallow": (110, 172, 210),
    "lava": (206, 92, 46),
    "ember": (168, 62, 40),
    "wood": (150, 108, 66),
    "plank": (168, 130, 84),
    "brick": (170, 84, 68),
    "tile_floor": (176, 168, 152),
    "marble": (222, 218, 226),
    "rug": (150, 66, 84),
    "metal": (140, 148, 160),
    "rust": (150, 92, 58),
    "bone": (222, 212, 182),
    "crystal": (140, 176, 214),
    "gold": (214, 172, 70),
    "cloth": (92, 108, 156),
    "skin": (226, 176, 138),
}


def mix(a: RGB, b: RGB, amount: float) -> RGB:
    """`a` moved `amount` of the way toward `b`, rounded to whole channels."""
    return (round(a[0] + (b[0] - a[0]) * amount),
            round(a[1] + (b[1] - a[1]) * amount),
            round(a[2] + (b[2] - a[2]) * amount))


@dataclass(frozen=True)
class Ramp:
    """Five shades of one material, derived from its base colour.

    Indexed -2..2 by `step`, which is what a drawing routine wants: "one
    shade down from whatever I was handed" beats naming a field, because the
    caller usually does not know which material it is drawing.
    """

    name: str
    base: RGB

    @property
    def shadow(self) -> RGB:
        return mix(self.base, SHADOW, 0.45)

    @property
    def dark(self) -> RGB:
        return mix(self.base, SHADOW, 0.22)

    @property
    def light(self) -> RGB:
        return mix(self.base, LIGHT, 0.20)

    @property
    def hi(self) -> RGB:
        return mix(self.base, LIGHT, 0.42)

    def step(self, index: int) -> RGB:
        """Shade `index` steps from base. Raises outside -2..2.

        A clamp here would silently flatten a gradient someone thought they
        had written, which is exactly the failure that looks like art.
        """
        try:
            return (self.shadow, self.dark, self.base,
                    self.light, self.hi)[index + 2]
        except IndexError:
            raise ValueError(
                f"a ramp has five shades, -2..2; got step {index} for "
                f"{self.name!r}") from None


def ramp(name: str) -> Ramp:
    """The named material. Raises on a name the palette does not carry."""
    try:
        return Ramp(name, BASES[name])
    except KeyError:
        raise KeyError(
            f"no palette entry {name!r}; the palette is "
            f"{', '.join(sorted(BASES))}") from None


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------

def surface(width: int, height: int) -> pygame.Surface:
    """A fully transparent RGBA surface.

    Transparent, not black: a tile sheet's empty space has to composite over
    whatever is beneath it, and a black background only looks correct until
    something is drawn under it.
    """
    out = pygame.Surface((width, height), pygame.SRCALPHA)
    out.fill((0, 0, 0, 0))
    return out


def fill(target: pygame.Surface, rect, colour: RGB) -> None:
    target.fill(colour, pygame.Rect(rect))


def outline_rect(target: pygame.Surface, rect, colour: RGB) -> None:
    """A one-pixel border drawn INSIDE `rect`, never outside it.

    Every tile in a sheet owns exactly its own cell; an outline drawn on the
    outside edge bleeds into the neighbouring tile and shows up as a seam
    the author cannot delete.
    """
    pygame.draw.rect(target, colour, pygame.Rect(rect), 1)


def noise(x: int, y: int, salt: int = 0) -> float:
    """A deterministic value in [0, 1) for a pixel. Same everywhere, always."""
    h = (x * 374761393 + y * 668265263 + salt * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return h / 4294967296.0


def speckle(target: pygame.Surface, rect, colour: RGB, *,
            density: float, salt: int = 0) -> None:
    """Scatter single pixels across `rect` at a fixed density."""
    area = pygame.Rect(rect)
    for y in range(area.top, area.bottom):
        for x in range(area.left, area.right):
            if noise(x, y, salt) < density:
                target.set_at((x, y), colour)


def dither(target: pygame.Surface, rect, colour: RGB, *, phase: int = 0) -> None:
    """The 2x2 checker: half a shade, at tile resolution."""
    area = pygame.Rect(rect)
    for y in range(area.top, area.bottom):
        for x in range(area.left, area.right):
            if (x + y + phase) % 2 == 0:
                target.set_at((x, y), colour)


def bevel(target: pygame.Surface, rect, material: Ramp) -> None:
    """Light along the top and left, dark along the bottom and right.

    Inside the rect on all four sides, for the reason `outline_rect` gives.
    """
    area = pygame.Rect(rect)
    for x in range(area.left, area.right):
        target.set_at((x, area.top), material.hi)
        target.set_at((x, area.bottom - 1), material.shadow)
    for y in range(area.top, area.bottom):
        target.set_at((area.left, y), material.light)
        target.set_at((area.right - 1, y), material.shadow)


def field(width: int, height: int, inside) -> list[list[bool]]:
    """A [x][y] occupancy grid from a predicate on pixel indices."""
    return [[bool(inside(x, y)) for y in range(height)] for x in range(width)]


def mass(field_grid: list[list[bool]], material: Ramp, texture=None) -> pygame.Surface:
    """Shade an occupancy grid into a surface: lit on top, dark underneath.

    The one place edge shading is decided, so a terrain quadrant and a bush
    catch the light the same way. `texture(x, y)` colours the interior; the
    default is the flat base.

    A pixel on the GRID BORDER is never treated as an edge. That is the
    property tile art lives on: a mass that runs to the edge of its cell has
    to continue into the neighbouring cell without a rim drawn down the
    seam. It also means nothing is ever painted outside the grid, which is
    what keeps a tile inside its own 16px box.
    """
    width, height = len(field_grid), len(field_grid[0])
    out = surface(width, height)
    for x in range(width):
        for y in range(height):
            if not field_grid[x][y]:
                continue
            if y > 0 and not field_grid[x][y - 1]:
                colour = material.hi
            elif y < height - 1 and not field_grid[x][y + 1]:
                colour = material.shadow
            elif ((x > 0 and not field_grid[x - 1][y])
                    or (x < width - 1 and not field_grid[x + 1][y])):
                colour = material.dark
            else:
                colour = material.base if texture is None else texture(x, y)
            out.set_at((x, y), colour)
    return out


def save(target: pygame.Surface, path: str) -> None:
    """Write a PNG, making the directory if it is missing."""
    if not pygame.get_init():
        pygame.init()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    pygame.image.save(target, path)
