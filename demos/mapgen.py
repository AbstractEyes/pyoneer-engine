"""The demo maps and their art, written to disk once and then left alone.

WHY GENERATED AND NOT CHECKED IN AS A BLOB
-------------------------------------------
A `.tmx` is the demo. Hiding one inside a Python string would make the point
of these demos unreadable, so this module WRITES a real file into
`demos/maps/` and the demo then loads it from disk like any other map. Open
`demos/maps/demo_sidestep.tmx` in Tiled and it is an ordinary map; repaint
it and the demo plays your version.

WRITE-ONCE, DELIBERATELY
------------------------
`ensure_map` writes only when the file is ABSENT. Regenerating on every boot
would silently discard an author's repaint, which is the single failure this
repository is most careful about -- `data/maps/test.tmx` is repainted
constantly and no check may pin its content. Delete a file here to get the
generated version back; nothing else ever overwrites it.

The tileset PNGs are generated the same way and for a duller reason: they are
binary, they are placeholder colour swatches, and they are derivable from
four lines of code.

THE COLLISION TILESET IS NOT DECORATION
----------------------------------------
`scripts/core/collision_runtime.py` reads a mask as a gid relative to the
firstgid of a tileset NAMED `collision` (case-insensitively), so the mask
vocabulary needs a real 17-tile tileset in the map even though nothing ever
draws it. Tile index N in that tileset IS mask N: 0 is PASS_ALL, 15 is
BLOCK_ALL, 16 is STAR. The masks are written into a companion tile layer
named by the art layer's `pyoneer_passability` property.

WHAT THE ENGINE WILL SAY ABOUT THE COMPANION LAYER, AND WHY IT IS FINE
-----------------------------------------------------------------------
`LayerRenderer.__prepare_map_layers` warns once per boot that
`'FloorCollision'` has no depth mapping in `scripts/core/depth.py` and will
NOT be drawn -- which is exactly what a mask layer wants. `LayerProfile`
declares a `renders` flag for saying so properly and nothing in the engine
reads it (`grep -rn '\\.renders' scripts/` finds no consumer), so today the
mask layer is kept off the screen by the accident of its name being
unmapped. Do NOT act on the warning's advice and add `FloorCollision` to
`MAP_DEPTH`: that is the change that makes the masks draw on top of the
floor.
"""
from __future__ import annotations

import os

import pygame

MAPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maps")

TILE = 32
"""Pixels per cell in every demo map. One number, so a position written in a
demo's docstring means the same thing in all three."""

# The visible tileset: four flat colours, because a demo that needed art
# would be a demo about art.  index -> (name, colour)
ART_TILES = (
    ("sky",   (104, 152, 208)),
    ("grass", (86, 140, 78)),
    ("stone", (96, 96, 104)),
    ("mark",  (208, 168, 72)),
)
ART_FIRST_GID = 1
SKY = ART_FIRST_GID + 0
GRASS = ART_FIRST_GID + 1
STONE = ART_FIRST_GID + 2
MARK = ART_FIRST_GID + 3

# The mask tileset. 17 tiles because the vocabulary is 0..STAR inclusive, and
# tile index N in it IS mask N -- so `COLLISION_FIRST_GID + 0` is PASS_ALL,
# `+ 0xF` is BLOCK_ALL and `+ 0x10` is STAR. Only the solid one is named
# below, because an EMPTY companion cell already means "no opinion", which
# `CollisionField.bake` resolves with `undecided` -- PASS_ALL by default. A
# map that painted every open cell explicitly would say the same thing in
# 1200 more numbers.
COLLISION_FIRST_GID = ART_FIRST_GID + len(ART_TILES)
MASK_COUNT = 17
SOLID_GID = COLLISION_FIRST_GID + 0xF     # BLOCK_ALL

ART_IMAGE = "demo_tiles.png"
COLLISION_IMAGE = "demo_collision.png"


# ---------------------------------------------------------------------------
# Art
# ---------------------------------------------------------------------------

def ensure_art() -> None:
    """Write the two placeholder tilesets if they are not already there.

    Needs a pygame display only in the sense that `pygame.image.save` does
    not -- but `pygame.Surface` does need `pygame.init()`, which every entry
    point into this package has already called.
    """
    os.makedirs(MAPS_DIR, exist_ok=True)
    art_path = os.path.join(MAPS_DIR, ART_IMAGE)
    if not os.path.exists(art_path):
        sheet = pygame.Surface((TILE * len(ART_TILES), TILE))
        for index, (_name, colour) in enumerate(ART_TILES):
            sheet.fill(colour, pygame.Rect(index * TILE, 0, TILE, TILE))
        pygame.image.save(sheet, art_path)

    mask_path = os.path.join(MAPS_DIR, COLLISION_IMAGE)
    if not os.path.exists(mask_path):
        # A readable-at-a-glance swatch: the four direction bits are drawn as
        # bars on the edges they block, in the engine's own bit order (down 1,
        # left 2, right 4, up 8). Nothing renders this; it is for the human
        # who opens the tileset in Tiled and wants to know which tile is which.
        sheet = pygame.Surface((TILE * MASK_COUNT, TILE), pygame.SRCALPHA)
        edges = ((0x1, (0, TILE - 6, TILE, 6)), (0x2, (0, 0, 6, TILE)),
                 (0x4, (TILE - 6, 0, 6, TILE)), (0x8, (0, 0, TILE, 6)))
        for mask in range(MASK_COUNT):
            left = mask * TILE
            sheet.fill((32, 32, 40, 160), pygame.Rect(left, 0, TILE, TILE))
            if mask == 0x10:                       # STAR: defer to the layer below
                sheet.fill((240, 220, 80, 255),
                           pygame.Rect(left + 10, 10, 12, 12))
                continue
            for bit, (x, y, w, h) in edges:
                if mask & bit:
                    sheet.fill((220, 60, 60, 255),
                               pygame.Rect(left + x, y, w, h))
        pygame.image.save(sheet, mask_path)


# ---------------------------------------------------------------------------
# TMX assembly
# ---------------------------------------------------------------------------

def _csv(grid: list[list[int]]) -> str:
    return ",\n".join(",".join(str(gid) for gid in row) for row in grid)


def _grid(width: int, height: int, fill: int = 0) -> list[list[int]]:
    return [[fill] * width for _ in range(height)]


def _properties(pairs: dict[str, tuple[str, str]], indent: str) -> str:
    """`{key: (type, value)}` as a `<properties>` block, or "" for none.

    A type of "" writes no `type=` attribute, which is what Tiled does for a
    string -- and is what `pytmx` needs in order not to hand an int property
    back as the string it was written as. `MapDocument` applies the same
    typing rules from the same attribute, which is why the engine reads
    properties through it rather than through pytmx.
    """
    if not pairs:
        return ""
    lines = [indent + "<properties>"]
    for key, (kind, value) in pairs.items():
        attribute = ' type="%s"' % kind if kind else ""
        lines.append('%s <property name="%s"%s value="%s"/>'
                     % (indent, key, attribute, value))
    lines.append(indent + "</properties>")
    return "\n".join(lines) + "\n"


def _object(object_id: int, name: str, type_name: str, x: float, y: float,
            width: float, height: float,
            properties: dict[str, tuple[str, str]]) -> str:
    head = ('  <object id="%d" name="%s" type="%s" x="%g" y="%g" '
            'width="%g" height="%g"' % (object_id, name, type_name, x, y,
                                        width, height))
    body = _properties(properties, "   ")
    if not body:
        return head + "/>\n"
    return head + ">\n" + body + "  </object>\n"


def build_tmx(width: int, height: int,
              art: list[list[int]],
              collision: list[list[int]] | None,
              objects: list[str]) -> str:
    """One orthogonal map: a `Floor` art layer, an optional companion, objects.

    `collision=None` writes NO companion layer and no `pyoneer_passability`
    property, which is how a demo says "this map declares no collision".
    `field_from_map` returns None for such a map and every body on it is
    ungated -- deliberate for the two top-down demos, and the reason they
    boot identically whether or not the engine's collision wiring exists.
    """
    passability = ({"pyoneer_passability": ("", "FloorCollision")}
                   if collision is not None else {})
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<map version="1.10" tiledversion="1.11.0" '
             'orientation="orthogonal" renderorder="right-down" '
             'width="%d" height="%d" tilewidth="%d" tileheight="%d" '
             'infinite="0" nextlayerid="4" nextobjectid="%d">'
             % (width, height, TILE, TILE, len(objects) + 1),
             ' <tileset firstgid="%d" name="demo" tilewidth="%d" '
             'tileheight="%d" tilecount="%d" columns="%d">'
             % (ART_FIRST_GID, TILE, TILE, len(ART_TILES), len(ART_TILES)),
             '  <image source="%s" width="%d" height="%d"/>'
             % (ART_IMAGE, TILE * len(ART_TILES), TILE),
             ' </tileset>',
             ' <tileset firstgid="%d" name="collision" tilewidth="%d" '
             'tileheight="%d" tilecount="%d" columns="%d">'
             % (COLLISION_FIRST_GID, TILE, TILE, MASK_COUNT, MASK_COUNT),
             '  <image source="%s" width="%d" height="%d"/>'
             % (COLLISION_IMAGE, TILE * MASK_COUNT, TILE),
             ' </tileset>',
             ' <layer id="1" name="Floor" width="%d" height="%d">'
             % (width, height)]
    if passability:
        parts.append(_properties(passability, "  ").rstrip("\n"))
    parts.append('  <data encoding="csv">')
    parts.append(_csv(art))
    parts.append('</data>')
    parts.append(' </layer>')
    if collision is not None:
        parts.append(' <layer id="2" name="FloorCollision" width="%d" '
                     'height="%d">' % (width, height))
        parts.append('  <data encoding="csv">')
        parts.append(_csv(collision))
        parts.append('</data>')
        parts.append(' </layer>')
    parts.append(' <objectgroup id="3" name="entity">')
    parts.extend(text.rstrip("\n") for text in objects)
    parts.append(' </objectgroup>')
    parts.append('</map>')
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# The three maps
# ---------------------------------------------------------------------------

TOPDOWN_SIZE = (40, 30)
SIDESTEP_SIZE = (40, 24)
PATROL_SIZE = (40, 30)

TOPDOWN_BEHAVIORS = "player_input,topdown_move,animation_drive"
SCENERY_BEHAVIORS = "topdown_move,animation_drive"
SIDESTEP_BEHAVIORS = "player_input,platformer_move,animation_drive"
FALLER_BEHAVIORS = "platformer_move,animation_drive"
PATROL_BEHAVIORS = "patrol_input,topdown_move,animation_drive"

SPRITE = (44, 64)
"""The shipped `~Garet.png` frame size, from config/animations.json.

Written into every object's width/height so an author placing one in Tiled
sees a box the size of the sprite. It is NOT what positions the object --
these are plain rectangles, so their (x, y) IS the top-left the renderer
blits at. A tile object (one with a `gid`) would be anchored at its
BOTTOM-left instead and lifted by `map_loader.object_top_left`.
"""

# ---------------------------------------------------------------------------
# The geometry, named.
#
# EVERY number a check would otherwise have to write as a literal lives here,
# so `tools/check_demos.py` can DERIVE what it expects -- "the body rests at
# the top of the ground, minus its feet offset, minus one EDGE_INSET" -- from
# the same constants that built the map, and never from a number typed twice.
# That is also what lets the check generate its own copy of these maps into a
# temp directory rather than reading `demos/maps/`: the shipped .tmx files are
# the AUTHOR's to repaint, and a check that pinned their content would go red
# the first time somebody did.
# ---------------------------------------------------------------------------

TOPDOWN_DECOY_IDS = (1, 2, 3, 4, 5)
TOPDOWN_HERO_ID = 6
TOPDOWN_DECOY_ORIGIN = (320.0, 320.0)
TOPDOWN_DECOY_STRIDE = 48.0
TOPDOWN_HERO_SPAWN = (320.0, 640.0)

SIDESTEP_HERO_ID = 1
SIDESTEP_FALLER_ID = 2
SIDESTEP_HERO_SPAWN = (320.0, 200.0)
SIDESTEP_FALLER_SPAWN = (832.0, 96.0)
SIDESTEP_GROUND_ROWS = 5
"""How many rows of solid ground sit at the bottom of `demo_sidestep`.

Five rather than one, and the reason is a real failure and not neatness. A
frame's `delta` is wall-clock, so the first frames after the ~280ms composite
bake are long ones; at terminal velocity a long frame steps further than a
tile and a one-row floor is something a body can pass straight through. The
gate is per-CELL at ONE anchor point -- it cannot detect a step that skipped
over the cell -- and `CollisionField.outside` is BLOCK_ALL, so a body that
tunnelled would come to rest at the world edge with `grounded` True, looking
exactly like a body that landed. 5 rows is 160px, which at 600px/s terminal
needs a 0.27s frame to cross.
"""
SIDESTEP_GROUND_TOP = SIDESTEP_SIZE[1] - SIDESTEP_GROUND_ROWS
"""Row index of the top of the ground. `SIDESTEP_GROUND_TOP * TILE` is the y
pixel a body's collision point comes to rest one EDGE_INSET above."""
SIDESTEP_PLATFORM_ROW = 14
SIDESTEP_PLATFORM_COLS = tuple(range(14, 23))

PATROL_PATROLLER_ID = 1
PATROL_HERO_ID = 2
PATROL_PATROLLER_SPAWN = (320.0, 320.0)
PATROL_HERO_SPAWN = (320.0, 640.0)
PATROL_ROUTE = "right,down,left,up"
PATROL_LEG_MS = 600


def _topdown_source() -> str:
    """Six `GamePlayer` objects that differ by ONE token, and nothing else.

    Same type, same size, same object layer, same depth. Five of them omit
    `player_input`, so nothing polls a keyboard on their behalf and they
    stand still by construction rather than by a flag. This is `main.py`'s
    `load_test_objects` with the Python removed.
    """
    width, height = TOPDOWN_SIZE
    art = _grid(width, height, GRASS)
    for x in range(width):                       # a stripe, so motion is visible
        art[height // 2][x] = MARK
    objects = []
    for index, object_id in enumerate(TOPDOWN_DECOY_IDS):
        objects.append(_object(
            object_id, "decoy%d" % index, "GamePlayer",
            TOPDOWN_DECOY_ORIGIN[0] + index * TOPDOWN_DECOY_STRIDE,
            TOPDOWN_DECOY_ORIGIN[1] + index * TOPDOWN_DECOY_STRIDE,
            SPRITE[0], SPRITE[1],
            {"pyoneer_behaviors": ("", SCENERY_BEHAVIORS)}))
    objects.append(_object(
        TOPDOWN_HERO_ID, "hero", "GamePlayer",
        TOPDOWN_HERO_SPAWN[0], TOPDOWN_HERO_SPAWN[1], SPRITE[0], SPRITE[1],
        {"pyoneer_behaviors": ("", TOPDOWN_BEHAVIORS)}))
    return build_tmx(width, height, art, None, objects)


def _sidestep_source() -> str:
    """Two side-on bodies over a floor that is authored as collision masks.

    The driven one carries `player_input`; the other does not and therefore
    only falls. Both carry `platformer_move` -- the SAME behavior list as the
    top-down demo but for one token, on the same class, on the same kind of
    object layer.
    """
    width, height = SIDESTEP_SIZE
    art = _grid(width, height, SKY)
    collision = _grid(width, height, 0)

    def solid(x: int, y: int) -> None:
        art[y][x] = STONE
        collision[y][x] = SOLID_GID

    for y in range(SIDESTEP_GROUND_TOP, height):
        for x in range(width):
            solid(x, y)
    for y in range(height):                       # side walls
        solid(0, y)
        solid(width - 1, y)
    for x in SIDESTEP_PLATFORM_COLS:              # one platform to jump onto
        solid(x, SIDESTEP_PLATFORM_ROW)
        art[SIDESTEP_PLATFORM_ROW][x] = MARK

    objects = [
        _object(SIDESTEP_HERO_ID, "hero", "GamePlayer",
                SIDESTEP_HERO_SPAWN[0], SIDESTEP_HERO_SPAWN[1],
                SPRITE[0], SPRITE[1],
                {"pyoneer_behaviors": ("", SIDESTEP_BEHAVIORS),
                 "pyoneer_param_jump_verb": ("", "jump"),
                 "pyoneer_param_initial_sequence": ("", "idle_right"),
                 "pyoneer_param_move_speed": ("float", "160"),
                 "pyoneer_param_jump_velocity": ("float", "360"),
                 "pyoneer_param_gravity": ("float", "900")}),
        # Clear of the platform columns, so this body falls all the way to the
        # ground and rests at the SAME y as the driven one. That equality is
        # the demo's claim: `player_input` is the only difference between
        # them, and it is about being steered, not about being simulated.
        _object(SIDESTEP_FALLER_ID, "faller", "GamePlayer",
                SIDESTEP_FALLER_SPAWN[0], SIDESTEP_FALLER_SPAWN[1],
                SPRITE[0], SPRITE[1],
                {"pyoneer_behaviors": ("", FALLER_BEHAVIORS),
                 "pyoneer_param_initial_sequence": ("", "idle_right"),
                 "pyoneer_param_gravity": ("float", "900")}),
    ]
    return build_tmx(width, height, art, collision, objects)


def _patrol_source() -> str:
    """One scripted body and one driven body, sharing `topdown_move`.

    The only difference between them is which behavior sits at order 10 and
    writes the `MoveIntent`. `scripts/game/behavior/input.py` claims that seam
    exists; this map is what exercises it.
    """
    width, height = PATROL_SIZE
    art = _grid(width, height, GRASS)
    for x in range(8, 32):
        art[10][x] = MARK
    objects = [
        _object(1, "patroller", "GamePlayer", 320, 320, SPRITE[0], SPRITE[1],
                {"pyoneer_behaviors": ("", PATROL_BEHAVIORS),
                 "pyoneer_param_route": ("", "right,down,left,up"),
                 "pyoneer_param_leg_ms": ("int", "600")}),
        _object(2, "hero", "GamePlayer", 320, 640, SPRITE[0], SPRITE[1],
                {"pyoneer_behaviors": ("", TOPDOWN_BEHAVIORS)}),
    ]
    return build_tmx(width, height, art, None, objects)


SOURCES = {
    "demo_topdown": _topdown_source,
    "demo_sidestep": _sidestep_source,
    "demo_patrol": _patrol_source,
}


def map_path(name: str) -> str:
    """Where `name`'s .tmx lives. Absolute, because pytmx resolves its tileset
    images relative to the map file and the cwd is not guaranteed."""
    return os.path.join(MAPS_DIR, name + ".tmx")


def ensure_map(name: str) -> str:
    """The path to `name`'s map, writing it and its art only if absent."""
    if name not in SOURCES:
        raise KeyError("no demo map named %r; known: %s"
                       % (name, ", ".join(sorted(SOURCES))))
    ensure_art()
    path = map_path(name)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(SOURCES[name]())
    return path


def regenerate(name: str) -> str:
    """Overwrite `name`'s map from source. For a check that wants a known map,
    and for an author who wants the shipped version back. `ensure_map` never
    does this; the two are separated so no boot path can call this one."""
    path = map_path(name)
    if os.path.exists(path):
        os.remove(path)
    return ensure_map(name)


__all__ = ["COLLISION_FIRST_GID", "MAPS_DIR", "SOLID_GID", "SOURCES", "TILE",
           "build_tmx", "ensure_art", "ensure_map", "map_path", "regenerate"]
