"""The parallax background: one picture, cut on the tile grid.

    .venv/Scripts/python.exe -m tools.art.parallax

WHY THIS IS A TILESET AND NOT A BACKDROP                #TAG:art_parallax_tiles
------------------------------------------------------------------------
`MAP_DEPTH` gives `Parallax` depth 1, and `data/maps/starter.tmx` declares it
on a TILE LAYER carrying `pyoneer_parallax_x`. Nothing in the engine
blits a standalone background image: the parallax band is gids like every
other layer, drawn from the map's own tilesets and scrolled at its own rate.

So this sheet is a 512x256 PICTURE cut on a 16px grid -- 32 columns by 16
rows. Import it in Tiled as a 16px tileset, stamp the block back in the
arrangement it came in, and the picture reassembles; the author is free to
take four tiles of sky and repeat them instead, which is the cheap version of
the same thing.

IT TILES HORIZONTALLY, AND THAT IS AN INVARIANT         #TAG:art_parallax_seam
------------------------------------------------------------------------
A parallax layer scrolls, so column 511 has to meet column 0 without a seam.
Every shape here is therefore periodic in x with period `WIDTH`: the ridges
are sums of sines at INTEGER frequencies, and a cloud is measured with a
wrapped horizontal distance so a puff crossing the edge comes out of the
other side. `palette.noise` is deliberately not used -- it is deterministic
but not periodic, and one speckle pass would put a visible vertical scar down
the join. `tools/check_art_sprites.py` measures the join against the
steepest column-to-column change in the interior, so the seam has to be no
worse than the picture's own worst edge.
"""
from __future__ import annotations

import math

import pygame

from tools.art import Builder, render_cli
from tools.art.palette import (SHADOW, Ramp, field, fill, mass, mix, ramp,
                               surface)

TAU = math.tau

WIDTH, HEIGHT = 512, 256
"""32 x 16 tiles at 16px. Both multiples of the tile size, because a picture
that does not divide by the grid cannot be stamped back."""

TILE = 16

HORIZON = 176
"""The row the sky stops at. Everything below is land."""

# (stop, colour name, step) -- the sky as four bands, top to horizon. Warm at
# the bottom and cold at the top, which is the whole reason a flat blue
# rectangle never reads as sky.
SKY_STOPS = (
    (0.00, ("deep_water", -2)),
    (0.42, ("water", 0)),
    (0.74, ("shallow", 1)),
    (1.00, ("sand", 1)),
)

SUN = (352, 148)
SUN_RADIUS = 13
SUN_GLOW = 34
"""Fully inside the picture: a disc crossing the join would need wrapping and
a sun cut in half is the one seam a viewer always notices."""

# (frequency, amplitude, phase). Frequencies are INTEGER cycles across
# WIDTH, which is what makes the ridge meet itself at the join.
FAR_RIDGE = ((1, 15.0, 0.10), (2, 7.0, 0.62), (5, 3.0, 0.31))
NEAR_RIDGE = ((1, 11.0, 0.55), (3, 6.0, 0.18), (7, 2.5, 0.74))

FAR_BASE = 150
NEAR_BASE = 196
GROUND = 228

CLOUDS = (
    # (centre x, centre y, radius x, radius y)
    (60, 74, 34, 9), (86, 68, 24, 8), (36, 78, 20, 6),
    (206, 52, 30, 8), (232, 58, 22, 7),
    (410, 92, 38, 10), (444, 86, 26, 8), (380, 96, 20, 6),
    (505, 62, 26, 8), (18, 60, 22, 7),      # straddles the join on purpose
)

TREE_PERIOD = 8
TREE_HEIGHT = 7
"""8 divides 512, so the treeline repeats a whole number of times and the
join lands between two trees rather than through one."""


def _wave(x: int, terms) -> float:
    """A periodic offset at column `x`. Integer frequencies only."""
    return sum(amp * math.sin(TAU * (freq * x / WIDTH + phase))
               for freq, amp, phase in terms)


def _sky_colour(y: int):
    """The sky at row `y`, interpolated between the four stops."""
    t = min(1.0, max(0.0, y / HORIZON))
    previous = SKY_STOPS[0]
    for stop in SKY_STOPS[1:]:
        if t <= stop[0]:
            span = stop[0] - previous[0]
            local = 0.0 if span <= 0 else (t - previous[0]) / span
            return mix(_stop_colour(previous[1]), _stop_colour(stop[1]), local)
        previous = stop
    return _stop_colour(SKY_STOPS[-1][1])


def _stop_colour(spec):
    name, step = spec
    return ramp(name).step(step)


def _wrapped_dx(x: int, centre: int) -> int:
    """Horizontal distance from `x` to `centre` the short way round.

    The reason a cloud sitting on the join is one cloud and not two halves.
    """
    delta = (x - centre) % WIDTH
    return delta - WIDTH if delta > WIDTH // 2 else delta


def _in_cloud(x: int, y: int) -> bool:
    for cx, cy, rx, ry in CLOUDS:
        dx = _wrapped_dx(x, cx) / rx
        dy = (y - cy) / ry
        if dx * dx + dy * dy <= 1.0:
            return True
    return False


def _tooth(x: int) -> int:
    """A triangular treeline, `TREE_PERIOD` wide and `TREE_HEIGHT` tall."""
    phase = x % TREE_PERIOD
    half = TREE_PERIOD // 2
    rise = phase if phase < half else TREE_PERIOD - phase
    return round(TREE_HEIGHT * rise / half)


def _band(target: pygame.Surface, top: int, bottom: int, inside,
          material, texture=None) -> None:
    """Shade one horizontal band through `palette.mass` and blit it.

    Only the band, not the whole picture: `mass` walks every cell it is
    given, and handing it 512x256 four times is four times the work for
    pixels that were never going to be occupied.
    """
    height = bottom - top
    grid = field(WIDTH, height, lambda x, y: inside(x, y + top))
    target.blit(mass(grid, material, texture), (0, top))


def parallax_sheet() -> pygame.Surface:
    """The whole 512x256 picture."""
    out = surface(WIDTH, HEIGHT)
    for y in range(HEIGHT):
        fill(out, (0, y, WIDTH, 1),
             _sky_colour(y) if y < HORIZON else _sky_colour(HORIZON - 1))

    # The sun, before the clouds, so a cloud crosses in front of it.
    gold = ramp("gold")
    for radius in range(SUN_GLOW, SUN_RADIUS, -1):
        haze = 1.0 - (radius - SUN_RADIUS) / (SUN_GLOW - SUN_RADIUS)
        pygame.draw.circle(out, mix(_sky_colour(SUN[1]), gold.hi, haze * 0.55),
                           SUN, radius)
    pygame.draw.circle(out, gold.light, SUN, SUN_RADIUS)
    pygame.draw.circle(out, gold.hi, SUN, SUN_RADIUS - 3)

    cloud = ramp("chalk")
    _band(out, 40, 112, _in_cloud, cloud,
          texture=lambda x, y: mix(cloud.base, gold.light, 0.18))

    # Aerial perspective: the far ridge is mixed most of the way to the sky
    # behind it, which is what puts it BEHIND rather than merely above.
    sky_at_ridge = _sky_colour(FAR_BASE)
    far = Ramp("granite", mix(ramp("granite").base, sky_at_ridge, 0.42))
    _band(out, FAR_BASE - 26, NEAR_BASE + 4,
          lambda x, y: y >= FAR_BASE + _wave(x, FAR_RIDGE), far)

    near = Ramp("forest", mix(ramp("forest").shadow, SHADOW, 0.18))
    _band(out, NEAR_BASE - 22, HEIGHT,
          lambda x, y: y >= NEAR_BASE + _wave(x, NEAR_RIDGE) - _tooth(x), near)

    ground = Ramp("swamp", mix(ramp("swamp").shadow, SHADOW, 0.35))
    _band(out, GROUND, HEIGHT, lambda x, y: y >= GROUND, ground)
    return out


SHEETS: dict[str, Builder] = {
    "data/graphics/tilesets/System/Parallax.png": parallax_sheet,
}


if __name__ == "__main__":
    raise SystemExit(render_cli(SHEETS, "the parallax background"))
