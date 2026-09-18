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

import math
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

# THREE OF THESE MOVED, AND THE REASON IS THE SAME ONE  #TAG:bases_read_as_what
# ---------------------------------------------------------------------------
# A base colour is only right if the material DRAWN from it reads as the
# thing it is named after, and three did not:
#
#   granite  was (152, 116, 119), a pink-mauve that drew as upholstery.
#            Granite is a pale warm GREY carrying dark and light flecks; the
#            pink belongs in the flecks, not in the body. The first attempt
#            at the grey went to (206, 168, 166) and was read as bubblegum;
#            this one keeps `red >= green >= blue` and 22 points of spread
#            between the ends, which is warm without being pink.
#   rust     was (176, 108, 51), a tan-orange. With a bimodal texture on top
#            of it the field read as desert sand. Oxide is redder and darker
#            than that, and the flakes are what is bright.
#   ember    was (72, 22, 20), nearly black -- so every step UP from it went
#            toward the shared cream and arrived at dull mauve. A coal's
#            light step has to be hot, so the base is the hot colour and the
#            crust is `_cold`, one step past `shadow`.
#
# AND ONE WAS ADDED, BECAUSE A NAME IS A MEANING
# `massif` is the far ridge of the parallax backdrop, and it used to be
# `ramp("granite")` -- which is how moving the granite terrain's colour
# repainted the sky on a machine that has the author's own tilesets and
# therefore loads NOTHING else from this pack. The ridge went from 15 of
# luminance below the sky behind it to 3.9, and the smoke frame hash moved
# for a reason nobody could name. What that call meant was "a distant
# grey-blue massif", so it says that now, and the terrain block is free to
# be whatever granite is.
#
# All four are what `docs/ASSETS.md` means by the pack being regenerated:
# nothing outside `tools/art/` names a base colour.
BASES: dict[str, RGB] = {
    "grass": (84, 141, 68),
    "tall_grass": (66, 116, 52),
    "moss": (66, 112, 84),
    "forest": (47, 93, 34),
    "swamp": (96, 106, 48),
    "leaf": (96, 152, 66),
    "bark": (108, 78, 54),
    "dirt": (132, 109, 54),
    "mud": (97, 77, 43),
    "clay": (182, 93, 70),
    "path": (193, 166, 131),
    "sand": (230, 198, 128),
    "gravel": (137, 132, 112),
    "stone": (147, 154, 159),
    "cobble": (104, 108, 128),
    "granite": (208, 194, 186),
    "massif": (112, 124, 152),   # #TAG:massif_is_not_granite
    "obsidian": (58, 52, 76),
    "void": (16, 15, 24),
    "ash": (84, 92, 88),
    "chalk": (206, 202, 190),
    "snow": (238, 248, 248),
    "ice": (140, 202, 214),
    "water": (64, 126, 200),
    "deep_water": (34, 66, 132),
    "shallow": (112, 178, 214),
    "lava": (234, 124, 38),
    "ember": (214, 74, 30),
    "wood": (136, 85, 59),
    "plank": (186, 158, 95),
    "brick": (166, 69, 62),
    "tile_floor": (161, 183, 155),
    "marble": (204, 194, 218),
    "rug": (146, 58, 96),
    "metal": (134, 146, 176),
    "rust": (188, 100, 18),
    "bone": (224, 216, 174),
    "crystal": (140, 176, 214),
    "gold": (214, 172, 70),
    "cloth": (92, 108, 156),
    "skin": (226, 176, 138),
    # THE URBAN FAMILY -- a second SET of materials, not a relight of the
    # first.                                          #TAG:urban_is_its_own_set
    # `side` and `topdown` are one set of thirty-two natural materials seen
    # two ways; `beatemup` walks a street, and a street is not grass under a
    # different lamp. These are its bases. The hard part is not naming them,
    # it is that an urban set is thirty shades of grey while
    # `TERRAIN_DISTANCE` is measured in CIELAB on the drawn field: packing
    # thirty-two of them at 14.0 needs real chroma on some of the rows, so
    # `road_paint`, `platform_edge`, `live_rail`, `brick_walk`,
    # `harbour_water` and `park_grass` carry saturation on purpose and not
    # for decoration. Real stages are not grey either.
    #
    # HOW THESE THIRTY WERE PICKED, AND THE RULE THAT PICKED THEM
    # By hand for intent, then repaired against the DRAWN field under a
    # leash, because the rule is measured on `field_colour` and not on the
    # base. The leash is the part worth keeping: a LIGHTNESS move is three
    # times cheaper than a HUE move, and every row whose name MEANS grey
    # carries an absolute chroma cap. Without that second half the repair
    # is arithmetically easy and artistically fatal -- run without the cap
    # it handed back a LILAC subway platform and a mauve rubble and called
    # the table legal, which is the paragraph above happening a second
    # time in the same file. As shipped the table clears 14.0 by 0.75 and
    # every capped row is under C* 14.5.
    "asphalt": (58, 50, 60),
    "asphalt_cracked": (92, 115, 113),
    "cobble_street": (99, 109, 122),
    "sidewalk": (223, 210, 190),
    "kerb": (168, 145, 143),
    "road_paint": (244, 237, 205),
    "brick_walk": (159, 73, 55),
    "oil_slick": (65, 26, 69),
    "concrete_slab": (180, 208, 209),
    "gravel_lot": (145, 157, 141),
    "dirt_lot": (134, 111, 62),
    "sand_lot": (231, 199, 164),
    "rubble": (107, 85, 85),
    "warehouse_floor": (138, 125, 108),
    "loading_dock": (71, 80, 66),
    "steel_deck": (155, 165, 175),
    "subway_platform": (193, 180, 196),
    "station_floor": (234, 252, 240),
    "platform_edge": (174, 121, 75),
    "rail_bed": (37, 49, 36),
    "live_rail": (245, 245, 156),
    "steam_vent": (206, 196, 244),
    "puddle": (57, 111, 133),
    "dock_plank": (202, 164, 128),
    "dock_wet": (89, 76, 38),
    "harbour_water": (37, 89, 146),
    "park_path": (171, 152, 86),
    "park_grass": (96, 138, 75),
    "park_dirt": (104, 66, 47),
    # THREE URBAN ROWS THAT USED TO BORROW A NATURAL BASE.
    #                                             #TAG:urban_borrows_nothing
    # `scorched`, `rusted_hatch` and `open_pit` were spelled `ember`, `rust`
    # and `void` -- entries the `side` and `topdown` tables draw as `embers`,
    # `rusted_plate` and `void`. Sharing the base means the urban repair
    # above cannot move a shared row without repainting two sheets it was
    # never looking at, and it is also how two of the thirty-two urban blocks
    # came to be the top-down sheet PIXEL FOR PIXEL (`_salt` is a hash of the
    # row NAME, and `_flat` ignores the salt entirely, so the same palette
    # plus the same texture is the same picture). One family, one set of
    # bases; `_verify_families_differ` is the rule that says so.
    "scorched": (123, 19, 43),
    "rusted_hatch": (179, 105, 37),
    "open_pit": (15, 14, 22),
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
# Colour science: the one implementation
# --------------------------------------------------------------------------
# Two rules are measured on colour rather than on pixels -- that no two
# materials read alike, and that a hazard never reads as a floor a player may
# stand on -- and both are measured by a generator AND by a check. They agree
# because they call THESE functions; a second copy of a CIELAB conversion in
# `tools/` would be a green assertion measuring a different colour space.

_D65 = (0.95047, 1.0, 1.08883)


def _linear(channel: int) -> float:
    """One 0..255 sRGB channel as linear light, 0..1."""
    value = channel / 255.0
    return (value / 12.92 if value <= 0.04045
            else ((value + 0.055) / 1.055) ** 2.4)


def _encode(value: float) -> int:
    """Linear light back to one 0..255 sRGB channel, clipped to the gamut."""
    value = 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)
    value = (12.92 * value if value <= 0.0031308
             else 1.055 * (value ** (1 / 2.4)) - 0.055)
    return round(value * 255)


def lab(colour: RGB) -> tuple[float, float, float]:
    """CIELAB L*a*b* under D65.

    Not raw RGB: euclidean distance in RGB calls a dark blue and a dark green
    far apart and two mid greys close together, which is the opposite of what
    an author sees. Every colour rule here is measured in this space.
    """
    red, green, blue = (_linear(channel) for channel in colour)
    xyz = (red * 0.4124 + green * 0.3576 + blue * 0.1805,
           red * 0.2126 + green * 0.7152 + blue * 0.0722,
           red * 0.0193 + green * 0.1192 + blue * 0.9505)

    def f(ratio: float) -> float:
        return ratio ** (1 / 3) if ratio > 0.008856 else 7.787 * ratio + 16 / 116

    fx, fy, fz = (f(value / white) for value, white in zip(xyz, _D65))
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def distance(a: RGB, b: RGB) -> float:
    """How far apart two colours look, as CIE76 dE. About 2.3 is the JND."""
    la, lb = lab(a), lab(b)
    return math.dist(la, lb)


def luminance(colour: RGB) -> float:
    """L* alone, 0..100: the axis that survives every kind of colour blindness."""
    return lab(colour)[0]


DICHROMACIES = ("protan", "deutan")
"""The two red-green confusions. Together about 8% of men, which is why the
hazard rule below measures both and takes the WORSE of the two."""


def dichromat(colour: RGB, kind: str) -> RGB:
    """`colour` as a protanope or a deuteranope sees it.

    Brettel/Vienot: convert to LMS, collapse the missing cone onto the plane
    the other two span, convert back. Raises on a kind it does not model
    rather than handing back the colour unchanged, which would silently make
    every colour-blindness assertion pass.
    """
    if kind not in DICHROMACIES:
        raise ValueError(f"no dichromacy {kind!r}; this models "
                         f"{', '.join(DICHROMACIES)}")
    red, green, blue = (_linear(channel) for channel in colour)
    long = 0.31399 * red + 0.63951 * green + 0.04649 * blue
    medium = 0.15537 * red + 0.75789 * green + 0.08670 * blue
    short = 0.01771 * red + 0.10944 * green + 0.87247 * blue
    if kind == "protan":
        long = 1.05118294 * medium - 0.05116099 * short
    else:
        medium = 0.95130920 * long + 0.04866992 * short
    return (_encode(5.47221206 * long - 4.64196010 * medium
                    + 0.16963708 * short),
            _encode(-1.12524190 * long + 2.29317094 * medium
                    - 0.16789520 * short),
            _encode(0.02980165 * long - 0.19318073 * medium
                    + 1.16364789 * short))


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


SHADOW_OFFSET = (1, 1)
"""Which way EVERY shadow falls on an overhead sheet: one pixel right, one down.

THE DIRECTION IS ARBITRARY; AGREEING ON IT IS NOT.     #TAG:one_shadow_direction
A sheet whose shadows disagree looks broken in a way nobody can point at --
each tile is fine and the field is wrong -- so the offset is a constant that
`overhead` and every raised feature in `tools/art/terrain.py` read, rather
than a number each texture picks.

Down-right, because up-left is where this package already puts the sun.
`bevel` lights the top and left edges and darkens the bottom and right;
`mass` lights the pixel with nothing above it; and `rivet`, drawn long before
there was a view axis, already sets its highlight at (4, 4) and its shadow at
(5, 5) -- exactly this offset. Choosing any other direction would have made
the one texture the author already likes the odd one out.

ONE pixel, not two or three. At 16px a two-pixel drop shadow beside a
four-pixel pebble is half the pebble again, and a field of them reads as
noise rather than as scattered stones.

AND A FORESHORTENED VIEW DOES NOT PROJECT IT.        #TAG:shadow_is_not_projected
`lowangle` draws a floor compressed to half depth, so keeping the sun at a
45 degree WORLD azimuth would want (2, 1) here and the implied world azimuth
of (1, 1) on that floor is 63.4 degrees instead. It stays (1, 1) anyway, for
three reasons in order of weight. A belt-scroll frame carries `side` art and
`beatemup` art AT ONCE -- the back wall is a vertical face and the floor is a
sheared plane, in the same frame -- so the player judges the sun ON SCREEN,
where `topdown` and `side` never coexist and world consistency across sheets
buys nothing observable. The paragraph above forbids the alternative outright:
(2, 1) IS the two-pixel shadow. And a `shadow_offset(k)` would be a second
place the sun gets decided, which is the whole thing this constant exists to
prevent. Nothing on screen shows the 63.4 degrees; this sentence is here so
the next reader does not re-derive (2, 1) and believe they found a bug.
"""


RIM_DROP = 0.30
"""How far an overhead rim pixel is pulled toward `SHADOW` from ITS OWN body.

RELATIVE, NOT A RAMP STEP, AND THAT IS THE WHOLE POINT.   #TAG:rim_is_relative
The rim used to be `material.dark`, a fixed step off the base, and on five
of the thirty-two terrains that is inside what the texture already draws:
69% of a `rusted_plate` interior was already at or below it, 53% of
`brickwork`, 50% of `cobble`. Those islands had no visible edge at all --
the silhouette dissolved into the field. On `embers` it INVERTED: `_cinder`
puts most of a cell one step below `shadow`, so the "shadow" rim was 23
luminance units BRIGHTER than the coals it was supposed to be the shadow of.

Shading the rim off the pixel the texture actually drew there cannot invert,
because it is always a step darker than its own neighbourhood, whatever the
neighbourhood is.

0.30 and not `Ramp.dark`'s own 0.22, which is where this started. A step
that size is plenty on a mid grey and nothing at all on `void`, whose base
is (16, 15, 24): there is about five of L* between that and black, and a
22% step spends one of them. At 0.30 every terrain on the sheet clears
`terrain.RIM_FALL`, `void` by the least of them.
"""


def fall(colour: RGB) -> RGB:
    """`colour` one step down: the ground falling away, whatever it is made of.

    Toward the shared `SHADOW` violet, like every other dark step here --
    EXCEPT on a material already darker than that violet, where mixing
    toward it would LIGHTEN the pixel. `void` is (16, 15, 24) against a
    shadow of (26, 22, 40): its rim came out brighter than its face, which
    is an edge lit from below. There the step is toward black instead, so
    "one step down" is down for every material the palette can hold.
    """
    toward = SHADOW if luminance(SHADOW) < luminance(colour) else (0, 0, 0)
    return mix(colour, toward, RIM_DROP)


FACE_SHOW = 2.3
"""How far a NEAR FACE has to move off the surface it stands on, in L*.

THE JND, NOT `RIM_FALL`.                              #TAG:face_show_is_a_jnd
`distance` says it in one line: about 2.3 dE is where a difference becomes a
difference somebody can see, and a dE is never smaller than its own L* term.
A rim is allowed less than that -- `terrain.RIM_FALL` is 1.5 -- for a reason
that does NOT apply here: a rim can only go down, and `void` has about five
of L* between it and black, so 1.5 is the most the darkest material on the
sheet can be asked for. A FACE can go either way (see `face`), so there is no
material on which the honest answer is "less than a player can see", and the
bar is the JND.

Measured, that is the difference between a rule and a rule-shaped comment.
With the face fixed downward, `scorched` moves 2.03 and `open_pit` 3.30 -- a
floor of 1.5 passes both, and the pit that reads as a black mat rather than a
hole goes green. At 2.3 the unsigned face is refused.

ONE constant, read by the shader that draws the face and by the rule that
measures it, so a face that moved and a face that counts as moved cannot
drift apart. It is a MAGNITUDE and not a signed drop, which is the whole
difference between the two rules.
"""


def face(colour: RGB) -> RGB:
    """One step of NEAR FACE: DOWN, unless down cannot be seen.

    A SIGNED STEP, AND THE SIGN IS THE ONE RULE.          #TAG:face_has_a_sign
    `fall` cannot invert, which is why it was chosen, but on a near-black
    surface it also cannot MOVE: `void` is (16, 15, 24), so a 30% step toward
    black spends about 1.5 of the five L* it owns. Measured over all 13 masks,
    the near face moved `open_pit` 1.29 L*, `oil_slick` 2.20 and `scorched`
    2.90 against a table mean of 10.2 -- so on the three rows where an edge
    cue matters most, a pit read as a flat black mat rather than as a hole,
    and a hole is the one thing on a low-angle sheet whose near WALL the
    camera would see most of.

    A wall turned away from an overhead sun is darker than the top it belongs
    to, so DOWN is the answer wherever down is an answer at all. Where it is
    not -- where the drop would land under `FACE_SHOW` -- the front wall of a
    pit catches sky instead and the step goes up. The decision is the
    visibility rule itself rather than a second number: the only surfaces
    that take the other branch are the ones on which the first branch would
    draw nothing, and `_verify_surfaces` measures the result against that
    same constant.

    NOT "whichever direction moves further", which was tried and is wrong:
    `LIGHT` is far from every base in this palette and `SHADOW` is near, so
    that comparison lifts the face on `asphalt` as readily as on `void` and
    turns an ordinary tarmac kerb into a white line.

    ONE FUNCTION, so `lowangle` keeps one expression of the near face and
    `_verify_surfaces` has one thing to measure. The RIM is still `fall`: a
    rim is ground falling away and it must never be brighter than its body
    (`terrain.RIM_FALL` measures that), while a face is a wall and a wall lit
    by the sky is not a contradiction.
    """
    down = fall(colour)
    if abs(luminance(down) - luminance(colour)) >= FACE_SHOW:
        return down
    return mix(colour, LIGHT, RIM_DROP)


def overhead(field_grid: list[list[bool]], material: Ramp,
             texture=None) -> pygame.Surface:
    """Shade an occupancy grid as a TOP FACE: flat, with the ground falling
    away on the shadow side.

    The sibling of `mass`, and the whole difference between the two views.
    `mass` puts `hi` along the top of a shape and `shadow` along its bottom,
    which is a VERTICAL FACE catching overhead light -- the strongest "this
    is a wall" cue a 16px tile has. Seen from above there is no such face:
    the interior is evenly lit and the only shading is where the surface
    ends, on the side away from the light.

    So exactly one rim is drawn, at `SHADOW_OFFSET`, one step down FROM
    WHAT THE TEXTURE DREW THERE -- see `RIM_DROP` for why a fixed ramp step
    made five terrains lose their edge and one of them grow a highlight
    instead. The lit side gets nothing at all: a raised patch of ground
    does not glow along its upper edge, and drawing a highlight there is
    how a top-down tile starts looking like a boulder.

    TWO PROPERTIES IT SHARES WITH `mass`, BOTH LOAD-BEARING. A pixel on the
    GRID BORDER is never treated as an edge, so a mass running to the edge
    of its cell continues into the next cell with no rim down the seam. And
    nothing is written where `field_grid` is false, so THE ALPHA THIS
    PRODUCES IS THE ALPHA `mass` PRODUCES, pixel for pixel: a view changes
    the surface, never the silhouette, and every border verdict the autotile
    checks measure is untouched by construction.
    """
    ox, oy = SHADOW_OFFSET
    width, height = len(field_grid), len(field_grid[0])
    out = surface(width, height)
    for x in range(width):
        for y in range(height):
            if not field_grid[x][y]:
                continue
            body = material.base if texture is None else texture(x, y)
            ax, ay = x + ox, y + oy
            if ((0 <= ax < width and not field_grid[ax][y])
                    or (0 <= ay < height and not field_grid[x][ay])):
                body = fall(body)
            out.set_at((x, y), body)
    return out


NEAR_FACE = 2
"""How many screen rows of NEAR FACE a raised surface shows to a low camera.

DERIVED, NOT PICKED.                                   #TAG:near_face_is_derived
A world step of height H seen at a pitch of `asin k` shows `H * cos(asin k)`
screen pixels, so the 2-unit kerb this view is built around shows 1.73 at
k = 1/2, which is 2 px. The geometry picks the number; the measurement only
says it is affordable. Over 5 forms x 13 masks the worst cell keeps 55.6% of
its mass as top face and NO cell is eaten whole. The worst form is `heave`,
which is the one form that thins the near edge, so the measurement looked
where the damage would be.

IT DOES NOT SATURATE, and the design pass that proposed this shader recorded
that it did. Measured on THIS implementation, worst-cell top-face survival is
55.6% at near = 2, 38.9% at near = 3 and 27.8% at near = 4: the face keeps
eating inward, because a `heave` cell is thin near the camera all the way up.
So 2 is not "the largest safe value", it is the derived value, and the safety
margin above it is 17 points of a cell rather than infinite.
"""


def lowangle(field_grid: list[list[bool]], material: Ramp, texture=None,
             near: int = NEAR_FACE) -> pygame.Surface:
    """Shade an occupancy grid as a GROUND PLANE SEEN FROM A LOW CAMERA.

    The third of the three, and it is `overhead` plus one thing: from a low
    camera you see the NEAR FACE of anything raised, and that face is the
    whole low-angle cue. So this draws `overhead`'s single rim at
    `SHADOW_OFFSET`, one step down from what the texture drew there, and
    then darkens the last `near` rows above a near boundary again -- two
    steps at the boundary itself, one the row above it.

    RELATIVE STEPS, NOT RAMP STEPS, for `RIM_DROP`'s measured reason: a
    fixed `material.shadow` face is inside what five of the thirty-two
    textures already draw, and on `void` it INVERTS. The rim steps with
    `fall`, which cannot invert; the near FACE steps with `face`, which is
    signed -- see there for why a wall on a near-black surface has to go the
    other way, and why that is measured rather than thresholded. Where a
    pixel is both rim and face it takes the face's step, and it takes the
    same NUMBER of steps it always did, so the count is unchanged and only
    the direction on a black material is. WHERE A PIXEL IS BOTH, THE RIM
    WINS: the silhouette own edge has to keep falling or `RIM_FALL` is
    measuring a rim that rose, and on a pit that leaves the lit wall one row
    in from the edge -- a light lip and then black, which is what a hole
    looks like.

    THE FACE RUNS INWARD FROM THE SILHOUETTE, AND THAT IS THE WHOLE SAFETY
    ARGUMENT. Nothing is written where `field_grid` is false, so THE ALPHA
    THIS PRODUCES IS THE ALPHA `mass` PRODUCES, pixel for pixel -- measured,
    16,640 comparisons over 5 forms x 13 masks with 0 disagreements, and the
    one plausible mutation (letting the face hang one row PAST the mass)
    moves pixels and is asserted to. A view changes the surface, never the
    silhouette.

    And a pixel whose neighbour is off the GRID is not a boundary, the same
    rule `mass` and `overhead` keep: a floor running to the edge of its cell
    continues into the next cell with no face drawn down the seam.
    """
    if near < 1:
        raise ValueError(
            f"a near face of {near} rows draws nothing, so this view would "
            f"be `overhead` under a second name; see NEAR_FACE for why the "
            f"number is 2")
    ox, oy = SHADOW_OFFSET
    width, height = len(field_grid), len(field_grid[0])
    out = surface(width, height)
    for x in range(width):
        for y in range(height):
            if not field_grid[x][y]:
                continue
            body = material.base if texture is None else texture(x, y)
            ax, ay = x + ox, y + oy
            steps = 1 if ((0 <= ax < width and not field_grid[ax][y])
                          or (0 <= ay < height and not field_grid[x][ay])) else 0
            wall = 0
            for depth in range(1, near + 1):
                below = y + depth
                if below < height and not field_grid[x][below]:
                    wall = near + 1 - depth
                    break
            rim, steps = steps, max(steps, wall)
            step = fall if rim else face
            for _ in range(steps):
                body = step(body)
            out.set_at((x, y), body)
    return out


def save(target: pygame.Surface, path: str) -> None:
    """Write a PNG, making the directory if it is missing."""
    if not pygame.get_init():
        pygame.init()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    pygame.image.save(target, path)
