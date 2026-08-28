"""Verify that the engine reads authored masks and refuses a blocked step.

Eleven claims. Every one is something the code is otherwise free to
break with no visible symptom until a player walks through a wall in a room
nobody tests twice:

    the vocabulary is RPG Maker's, and an empty cell is not "open"
    a flipped mask blocks from the side it is drawn on
    the strongest level and the topmost layer decide, in that order
    the baked field's two cells both get a veto
    the gate stops an entity INSIDE the cell it was leaving, at any speed
    pytmx's renumbering is undone, flip flags and all
    an entity with no field moves by the arithmetic it moved by before
    editor/core/collision.py is still this module, and not a copy of it
    a companion may be four times the map, and an old one gates as it did
    a mask baked into a TILE gates wherever it is stamped, and loses to paint
    a layer that moves under the camera gates nothing, painted or not

WHAT SECTION 10 IS FOR
----------------------
Level one -- the mask a tileset carries for each of its own tiles -- is the
weakest of the three levels and the only one an author never repeats. It is
also a PRECEDENCE claim, and a precedence rule proved to APPLY but never
proved to be OVERRIDDEN passes just as happily when the levels are merged, or
reordered, or when the weakest one quietly wins. So section 10 states every
claim twice, in opposite directions.

Every fixture is written into a temp directory of its own, sidecar included,
for the reason THE FIXTURE IS THIS FILE'S OWN gives below -- and one extra:
half of these fixtures exist in order to be missing a file, and a shared
directory would let one of them fix another.

WHAT SECTION 9 IS FOR
---------------------
`pyoneer_subcell` is a file-format string, so both halves of it have to be
pinned or the migration is a hope. Section 9 asserts, on its own fixtures:

  * a DECLARED 4x companion bakes a field at 4x dimensions and a quarter tile
    size, and two sub-cells inside ONE map tile hold different masks -- which
    is the thing a whole-tile field cannot say. A body is stopped by one of
    them and passes through the other, one sub-cell apart.
  * an UNDECLARED oversized companion RAISES naming both shapes, rather than
    baking a truncated field and dropping every sub-cell outside the top-left
    corner in silence.
  * a 1x companion bakes the SAME BYTES it baked before any of this existed,
    and declaring `pyoneer_subcell="1"` explicitly changes nothing. That is
    the migration guarantee and it is the one that will actually break.
  * a stack mixing 1x and 4x puts the 1x layer's wall at the PIXELS it was
    painted at. Dropping the scale does not lose that layer, it moves it 40
    pixels up the map, which is worse: it still looks like collision working.

THE FIXTURE IS THIS FILE'S OWN
------------------------------
Everything is read from a .tmx written into a temp directory by `FIXTURE`
below. `data/maps/test.tmx` is repainted constantly and declares no
passability at all; a check that pinned map CONTENT would go red the next
time the author paints, while the code it guards worked perfectly (law 4).

The fixture needs no art. Its tilesets point at PNGs that do not exist, which
both pytmx and MapDocument parse happily as long as no tile IMAGE is
resolved -- and none is, because a mask is a number.

WHAT SECTION 8 IS FOR
---------------------
`scripts/core/collision_runtime.py` is the ONLY definition of the mask
vocabulary, the layer stack, `resolve` and `CollisionField`;
`editor/core/layers.py` and `editor/core/collision.py` import it and
re-export what their own callers name. Section 8 asserts IDENTITY rather than
equality: the editor's names must BE these objects, and neither editor module
may bind any shared name in its own source. A re-pasted copy is equal on the
day it is pasted; it is never identical.

Section 8 also asserts that the editor's genre packs and
`scripts/core/depth.MAP_DEPTH` rank a layer at the same height. Those are two
authored tables by design, and `resolve` walks topmost first, so disagreeing
about one layer means a different deciding layer in the overlay than in the
game.

    .venv/Scripts/python.exe tools/check_collision_runtime.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import ast
import os
import sys
import tempfile
import warnings

import pygame

pygame.init()

import pytmx

from pygame import Vector2

from scripts.core import collision_runtime as runtime
from scripts.core.collision_runtime import (
    BLOCK_ALL,
    BLOCK_DOWN,
    BLOCK_LEFT,
    BLOCK_RIGHT,
    BLOCK_UP,
    COMPANION_SUFFIX,
    SUBCELL,
    CollisionField,
    CollisionLayer,
    DIRECTION_BITS,
    EDGE_INSET,
    FLIP_DIAGONAL,
    FLIP_HORIZONTAL,
    FLIP_VERTICAL,
    NO_DATA,
    PASS_ALL,
    STAR,
    allowed_distance,
    at_world_coordinates,
    collision_first_gid,
    collision_layers,
    companion_pairs,
    companion_reader,
    companion_subcell,
    describe_mask,
    describe_opinion,
    document_gid_reader,
    field_from_map,
    field_subcell,
    file_gid_reader,
    gid_to_mask,
    gid_to_opinion,
    join_gid,
    mask_to_gid,
    move_point,
    parsed_layer,
    resolve,
    split_gid,
    tileset_defaults,
    transform_mask,
    world_coordinate_fault,
)
from scripts.core.depth import MAP_DEPTH, resolve_layer_depth
from scripts.core.errors import PyoneerConfigError
from scripts.game.entity.game_entity import GameEntity
from scripts.loaders.map_document import MapDocument

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_close(label, got, want, tolerance=1e-9):
    ok = abs(got - want) <= tolerance
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception, call, *fragments):
    """The call must raise `exception`, and its message must name each fragment.

    The fragments are the teeth. An assertion that only checks the exception
    TYPE passes for any raise anywhere inside the call, including one from a
    typo three frames down.
    """
    try:
        call()
    except exception as exc:
        text = str(exc)
        missing = [f for f in fragments if f not in text]
        ok = not missing
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} "
              f"raised {type(exc).__name__}: {text.splitlines()[0][:60]}")
        if not ok:
            failures.append(f"{label} (message lacks {missing})")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<58} raised {type(exc).__name__} not "
              f"{exception.__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<58} did not raise")
    failures.append(label)


# ---------------------------------------------------------------------------
# 1. The vocabulary
# ---------------------------------------------------------------------------
print("\nthe vocabulary")

# Written as literals, not as the module's own names. Asserting
# BLOCK_DOWN == BLOCK_DOWN is the assertion that cannot fail; the point of
# this line is that the numbers are RPG Maker's, because the .tmx files and
# the mask sheet are indexed by them and renumbering silently repaints every
# map ever authored.
expect("down/left/right/up are 1, 2, 4, 8",
       (BLOCK_DOWN, BLOCK_LEFT, BLOCK_RIGHT, BLOCK_UP), (1, 2, 4, 8))
expect("BLOCK_ALL is the four bits", BLOCK_ALL, 15)
expect("STAR is 0x10, outside the four bits", (STAR, STAR & BLOCK_ALL), (16, 0))
expect("PASS_ALL is zero", PASS_ALL, 0)
expect("the four movement verbs all map to a bit",
       sorted(DIRECTION_BITS), ["down", "left", "right", "up"])

expect("describe_mask names the set bits in bit order",
       describe_mask(BLOCK_DOWN | BLOCK_LEFT), "blocks down, left")
expect("describe_mask calls the empty mask open", describe_mask(PASS_ALL), "open")
expect("describe_opinion has a word for NO_DATA",
       describe_opinion(NO_DATA), "no opinion")

expect("a mask is firstgid + mask", mask_to_gid(BLOCK_LEFT | BLOCK_DOWN, 5), 8)
expect("and back again", gid_to_mask(8, 5), BLOCK_LEFT | BLOCK_DOWN)
expect_raises("a mask above STAR has no gid", ValueError,
              lambda: mask_to_gid(STAR + 1, 5), "outside 0..16")

# The single most load-bearing pair in the module. If these ever agree, a
# stack of collision layers stops composing: the top layer's empty cells
# assert "open" and blank every wall underneath them.
expect("gid_to_mask reads an empty cell as open", gid_to_mask(0, 5), PASS_ALL)
expect("gid_to_opinion reads the same cell as silence",
       gid_to_opinion(0, 5), NO_DATA)
expect("a gid from another tileset is silence too, not open",
       gid_to_opinion(1, 5), NO_DATA)
expect("a gid past the mask range is silence",
       gid_to_opinion(5 + STAR + 1, 5), NO_DATA)
expect("the last mask gid is still a mask",
       gid_to_opinion(5 + STAR, 5), STAR)


# ---------------------------------------------------------------------------
# 2. Flip flags
# ---------------------------------------------------------------------------
print("\nflip flags")

expect("split_gid separates value from flags",
       split_gid(join_gid(9, FLIP_HORIZONTAL)), (9, FLIP_HORIZONTAL))
expect("a mirrored wall blocks from the other side",
       transform_mask(BLOCK_RIGHT, FLIP_HORIZONTAL), BLOCK_LEFT)
expect("vertical mirrors up and down",
       transform_mask(BLOCK_UP, FLIP_VERTICAL), BLOCK_DOWN)
expect("horizontal leaves up alone",
       transform_mask(BLOCK_UP, FLIP_HORIZONTAL), BLOCK_UP)
expect("diagonal transposes up into left",
       transform_mask(BLOCK_UP, FLIP_DIAGONAL), BLOCK_LEFT)
# Tiled applies diagonal FIRST. up -> (diagonal) left -> (horizontal) right.
# The other order gives up -> (horizontal) up -> (diagonal) left, so this one
# assertion pins the order rather than merely the two mirrors.
expect("diagonal is applied before horizontal",
       transform_mask(BLOCK_UP, FLIP_DIAGONAL | FLIP_HORIZONTAL), BLOCK_RIGHT)
expect("star has no direction to mirror",
       transform_mask(STAR, FLIP_HORIZONTAL | FLIP_DIAGONAL), STAR)
# NO_DATA is -1, so the bit arithmetic would turn it into STAR|BLOCK_ALL = 31.
expect("silence stays silence rather than becoming 31",
       transform_mask(NO_DATA, FLIP_HORIZONTAL), NO_DATA)
expect("a flipped mask gid decodes mirrored",
       gid_to_opinion(join_gid(5 + BLOCK_RIGHT, FLIP_HORIZONTAL), 5),
       BLOCK_LEFT)


# ---------------------------------------------------------------------------
# 3. Levels and the layer stack
# ---------------------------------------------------------------------------
print("\nthree levels, then the stack")


def constant(value):
    """A level that says one thing everywhere."""
    return lambda x, y: value


levelled = CollisionLayer(name="levelled",
                          defaults=constant(BLOCK_ALL),
                          companion=constant(BLOCK_DOWN))
expect("companion beats the tileset default",
       levelled.opinion_at(0, 0), BLOCK_DOWN)
levelled.set_override(0, 0, BLOCK_UP)
expect("an override beats the companion", levelled.opinion_at(0, 0), BLOCK_UP)
expect("and only where it was written", levelled.opinion_at(1, 0), BLOCK_DOWN)
levelled.set_override(0, 0, NO_DATA)
expect("an override of NO_DATA is a removal, not a stored silence",
       (levelled.overrides, levelled.opinion_at(0, 0)), ({}, BLOCK_DOWN))

silent = CollisionLayer(defaults=constant(BLOCK_ALL), companion=constant(NO_DATA))
expect("a silent companion falls through to the default",
       silent.opinion_at(0, 0), BLOCK_ALL)
starred = CollisionLayer(defaults=constant(BLOCK_ALL), companion=constant(STAR))
expect("a star SUPPRESSES the default instead of falling through",
       starred.opinion_at(0, 0), STAR)

top = CollisionLayer(name="top", companion=lambda x, y: {
    0: NO_DATA, 1: STAR, 2: BLOCK_UP}[x])
bottom = CollisionLayer(name="bottom", companion=lambda x, y: {
    0: BLOCK_DOWN, 1: BLOCK_LEFT, 2: BLOCK_RIGHT}[x])
stack = [top, bottom]

expect("silence in the top layer asks the one below",
       resolve(stack, 0, 0).mask, BLOCK_DOWN)
expect("a star in the top layer also asks the one below",
       resolve(stack, 1, 0).mask, BLOCK_LEFT)
expect("an opinion in the top layer ends it",
       resolve(stack, 2, 0).mask, BLOCK_UP)
expect("and the resolution names which layer decided",
       (resolve(stack, 0, 0).layer, resolve(stack, 2, 0).layer), (1, 0))
expect("a disagreement below the decider is flagged",
       resolve(stack, 2, 0).conflicted, True)
expect("agreement below the decider is not",
       resolve([top, CollisionLayer(companion=constant(BLOCK_UP))],
               2, 0).conflicted, False)
# Reversing the stack has to change the answer, or "topmost first" is not
# being honoured by anything and the sort in companion_pairs is decoration.
expect("reversing the stack changes who decides",
       resolve(list(reversed(stack)), 2, 0).mask, BLOCK_RIGHT)

blank = [CollisionLayer(companion=constant(NO_DATA))]
expect("a stack that abstains everywhere is undecided",
       (resolve(blank, 0, 0).mask, resolve(blank, 0, 0).decided),
       (PASS_ALL, False))
expect("and the fallback is the caller's to choose",
       resolve(blank, 0, 0, undecided=BLOCK_ALL).mask, BLOCK_ALL)


# ---------------------------------------------------------------------------
# 4. The baked field
# ---------------------------------------------------------------------------
print("\nthe baked field")

# 4 wide, 3 tall. (1,1) is a full wall; (3,0) blocks only downward.
WALLS = bytes([
    0, 0, 0, BLOCK_DOWN,
    0, BLOCK_ALL, 0, 0,
    0, 0, 0, 0,
])
walls = CollisionField(4, 3, WALLS)

expect("bake resolves the stack once per cell",
       CollisionField.bake(stack, 3, 1).masks(),
       bytes([BLOCK_DOWN, BLOCK_LEFT, BLOCK_UP]))
expect("baking collapses NO_DATA into the caller's fallback",
       CollisionField.bake(blank, 2, 1, undecided=BLOCK_ALL).masks(),
       bytes([BLOCK_ALL, BLOCK_ALL]))
expect_raises("a field of the wrong size is refused", ValueError,
              lambda: CollisionField(4, 3, bytes(11)), "wants 12 masks")
expect_raises("a mask outside the vocabulary is refused", ValueError,
              lambda: CollisionField(1, 1, bytes([99])), "outside 0..16")

expect("mask_at reads row-major", walls.mask_at(1, 1), BLOCK_ALL)
expect("outside the field is blocked by default", walls.mask_at(-1, 0), BLOCK_ALL)
expect("unless the caller opens the border",
       CollisionField(4, 3, WALLS, outside=PASS_ALL).mask_at(-1, 0), PASS_ALL)
# int() truncates toward zero, so -1.0 would read as cell 0 and an entity a
# pixel off the left edge would think it was inside the map.
expect("cell_of floors rather than truncating",
       (walls.cell_of(-1.0, -1.0), walls.cell_of(15.9, 16.0)),
       ((-1, -1), (0, 1)))

# The pixel entry point. (3, 0) and (0, 3) are deliberately DIFFERENT answers
# -- one is the cell that blocks downward, the other is off the bottom of a
# 3-tall field -- so an x/y transpose in here cannot pass. A square fixture
# would have made this assertion decorative.
expect("mask_at_pixel reads the cell the pixel is in",
       (walls.mask_at_pixel(56.0, 8.0), walls.mask_at_pixel(24.0, 24.0)),
       (BLOCK_DOWN, BLOCK_ALL))
expect("and it floors, so anywhere inside one cell gives one mask",
       (walls.mask_at_pixel(48.0, 0.0), walls.mask_at_pixel(63.9, 15.9)),
       (BLOCK_DOWN, BLOCK_DOWN))
expect("a pixel outside the field answers the border",
       (walls.mask_at_pixel(-0.5, 8.0), walls.mask_at_pixel(8.0, 48.0)),
       (BLOCK_ALL, BLOCK_ALL))

# `blocks` is the SOURCE half of `can_move` on its own, and the difference
# between the two is the entire reason both exist. Nothing in the engine
# calls it yet, which is exactly why it needs its own assertions: an
# unexercised public method is one a refactor is free to empty out.
expect("blocks() reads the cell's own bit",
       (walls.blocks(1, 1, BLOCK_RIGHT), walls.blocks(1, 1, BLOCK_UP)),
       (True, True))
expect("a cell with one bit set blocks that way and no other",
       (walls.blocks(3, 0, BLOCK_DOWN), walls.blocks(3, 0, BLOCK_UP),
        walls.blocks(3, 0, BLOCK_LEFT)), (True, False, False))
# The half that separates the two questions: (0, 1) says nothing itself, so
# it blocks nothing -- and stepping out of it is still refused, by the
# DESTINATION. A `blocks` that answered `can_move`'s question would fail here.
expect("an open cell blocks nothing, even where can_move refuses",
       (walls.blocks(0, 1, BLOCK_RIGHT), walls.can_move(0, 1, BLOCK_RIGHT)),
       (False, False))
expect("outside the field blocks by the border",
       walls.blocks(-1, 0, BLOCK_RIGHT), True)
expect_raises("blocks refuses a value that is not a direction", ValueError,
              lambda: walls.blocks(0, 0, STAR), "not one of the four")

expect("an open cell may be left", walls.can_move(0, 0, BLOCK_RIGHT), True)
expect("the source cell vetoes on its own bit",
       walls.can_move(1, 1, BLOCK_RIGHT), False)
# The half that one-sided implementations forget: (0,1) says nothing at all,
# and the move is still refused because the DESTINATION blocks the reverse.
expect("the destination cell vetoes on the opposite bit",
       (walls.mask_at(0, 1), walls.can_move(0, 1, BLOCK_RIGHT)),
       (PASS_ALL, False))
expect("walking off the edge is refused by the border",
       walls.can_move(0, 0, BLOCK_LEFT), False)
# Every destination-veto assertion above steps into (1,1), which is BLOCK_ALL
# -- so it refuses whichever bit OPPOSITE hands it, and an OPPOSITE that
# stopped mirroring left into right would pass all of them. These two cells
# each close exactly ONE edge, so the veto only fires if the reverse of the
# direction is the bit that was actually set. Left/right and up/down are
# separate entries in that table and a copy-paste can break either alone.
# A row below the closed-top cell on purpose: without it, stepping down out
# of that cell leaves the field and the BORDER refuses, which would make the
# "open both ways" assertion below pass for the wrong reason.
one_way = CollisionField(3, 3, bytes([
    PASS_ALL, BLOCK_LEFT, PASS_ALL,
    PASS_ALL, BLOCK_UP, PASS_ALL,
    PASS_ALL, PASS_ALL, PASS_ALL,
]))
expect("a cell that closes only its LEFT edge cannot be entered from the left",
       one_way.can_move(0, 0, BLOCK_RIGHT), False)
expect("...and is still open from its right, because the bit names one edge",
       one_way.can_move(2, 0, BLOCK_LEFT), True)
expect("the same for a cell that closes only its TOP edge",
       (one_way.can_move(1, 1, BLOCK_UP), one_way.can_move(1, 0, BLOCK_DOWN)),
       (False, False))
expect("...whose bottom edge stays open both ways",
       one_way.can_move(1, 1, BLOCK_DOWN), True)
expect_raises("can_move refuses a value that is not a direction", ValueError,
              lambda: walls.can_move(0, 0, STAR), "not one of the four")
expect("counts sees every cell", sum(walls.counts().values()), 12)


# ---------------------------------------------------------------------------
# 5. The movement gate
# ---------------------------------------------------------------------------
print("\nthe movement gate")

# The anchor sits at (8, 24): the middle of cell (0, 1), whose right-hand
# neighbour (1, 1) is the full wall.
expect("an unblocked step travels the whole distance",
       allowed_distance(walls, 8.0, 40.0, BLOCK_RIGHT, 4.0), 4.0)
expect("a step that does not reach the boundary is never gated",
       allowed_distance(walls, 8.0, 24.0, BLOCK_RIGHT, 4.0), 4.0)

blocked_right = allowed_distance(walls, 8.0, 24.0, BLOCK_RIGHT, 12.0)
expect_close("a blocked step stops just short of the edge",
             blocked_right, 8.0 - EDGE_INSET)
expect("and the anchor is still in the cell it was leaving",
       walls.cell_of(*move_point(walls, 8.0, 24.0, BLOCK_RIGHT, 12.0)), (0, 1))
# Without the inset the anchor lands exactly on 16.0, which floors to cell 1
# -- the cell the mask just refused. This is the whole reason EDGE_INSET is
# not zero, so it gets its own assertion.
expect("landing exactly on the boundary would have entered the wall",
       walls.cell_of(16.0, 24.0), (1, 1))

# Leaving leftward is the mirror case and needs NO inset: arriving exactly on
# a cell's own left edge still floors into that cell.
left_walls = CollisionField(4, 3, bytes([
    0, 0, 0, 0,
    BLOCK_ALL, 0, 0, 0,
    0, 0, 0, 0,
]))
blocked_left = allowed_distance(left_walls, 24.0, 24.0, BLOCK_LEFT, 12.0)
expect("a blocked leftward step stops exactly on the boundary",
       blocked_left, 8.0)
expect("which is still inside the cell it was leaving",
       left_walls.cell_of(*move_point(left_walls, 24.0, 24.0, BLOCK_LEFT, 12.0)),
       (1, 1))

# Two boundaries in one step. From cell (0,1) rightward: (1,1) is the wall,
# so a 40px sprint stops at the FIRST refusal and not at the last boundary
# it crossed.
expect_close("a step longer than a tile stops at the first refusal",
             allowed_distance(walls, 8.0, 24.0, BLOCK_RIGHT, 40.0),
             8.0 - EDGE_INSET)
# ...and when the first boundary is open the walk carries on to the next one.
corridor = CollisionField(4, 3, bytes([
    0, 0, BLOCK_ALL, 0,
    0, 0, 0, 0,
    0, 0, 0, 0,
]))
expect_close("an open first boundary does not end the walk",
             allowed_distance(corridor, 8.0, 8.0, BLOCK_RIGHT, 40.0),
             24.0 - EDGE_INSET)
expect("so the anchor ends two cells along, not one",
       corridor.cell_of(*move_point(corridor, 8.0, 8.0, BLOCK_RIGHT, 40.0)),
       (1, 0))

expect("a zero step is a zero step",
       allowed_distance(walls, 8.0, 24.0, BLOCK_RIGHT, 0.0), 0.0)
expect_raises("the gate refuses a value that is not a direction", ValueError,
              lambda: allowed_distance(walls, 0.0, 0.0, STAR, 1.0),
              "not one of the four")

# An entity that starts outside the field is NOT frozen there. Reading
# `outside` from out there would refuse every direction forever.
expect("an anchor outside the field is not gated",
       allowed_distance(walls, -8.0, 24.0, BLOCK_RIGHT, 40.0), 40.0)
expect("but one inside it cannot walk out",
       allowed_distance(walls, 8.0, 24.0, BLOCK_LEFT, 12.0), 8.0)


class CountingField(CollisionField):
    """A field that remembers how many crossings the gate asked it about.

    The boundary walk is bounded by the border refusing to be crossed, which
    is true of the DEFAULT border and not of an open one. Counting the
    questions pins that as a number instead of as a check that hangs.
    """

    asked = 0

    def can_move(self, x, y, direction):
        self.asked += 1
        return super().can_move(x, y, direction)


open_border = CountingField(4, 3, bytes(12), outside=PASS_ALL)
expect("an open border lets a long step run right off the map",
       allowed_distance(open_border, 8.0, 8.0, BLOCK_RIGHT, 1000000.0),
       1000000.0)
expect("without asking one question per tile for a million pixels",
       open_border.asked <= 8, True)


# ---------------------------------------------------------------------------
# 6. Reading a map
# ---------------------------------------------------------------------------
print("\nreading a map")

# 4x3 at 16px. Two art layers, each with a companion, plus the mask tileset.
#
#   Floor            declares pyoneer_passability="FloorMasks"
#   Foreground       declares nothing, so the NAME convention finds
#                    "ForegroundCollision"
#
# The cells are chosen so that every resolution rule shows up as a different
# number in the baked field:
#
#   (1,0)  Floor blocks everything, Foreground is EMPTY above it   -> 15
#          (empty must mean silence; if it meant "open" the wall vanishes)
#   (3,0)  Floor holds BLOCK_RIGHT flipped horizontally            -> 2
#   (0,2)  Foreground blocks everything over an OPEN Floor cell    -> 15
#          (topmost wins, and the open cell below is a real assertion)
#   (2,2)  Foreground holds a STAR over Floor's BLOCK_DOWN         -> 1
#          (star defers BETWEEN layers)
#
# Foreground is written FIRST in the file, before Floor, and that is
# deliberate. `companion_pairs` has to order by draw depth, and a fixture
# whose document order already matched the depth order would pass just as
# happily if the sort were deleted -- or replaced with "reverse document
# order", which is what a tmx layer list usually means. Here document order,
# reverse document order and depth order are three different answers, and
# only one of them is right.
FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="4" height="3" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="9" nextobjectid="1">
 <tileset firstgid="1" name="probe" tilewidth="16" tileheight="16" tilecount="4" columns="2">
  <image source="no-such-art.png" width="32" height="32"/>
 </tileset>
 <tileset firstgid="5" name="collision" tilewidth="16" tileheight="16" tilecount="17" columns="17">
  <image source="no-such-masks.png" width="272" height="16"/>
 </tileset>
 <layer id="3" name="Foreground" width="4" height="3">
  <data encoding="csv">
0,0,0,0,
0,0,0,0,
0,0,0,0
</data>
 </layer>
 <layer id="4" name="ForegroundCollision" width="4" height="3">
  <data encoding="csv">
0,0,0,0,
0,0,0,0,
20,0,21,0
</data>
 </layer>
 <layer id="1" name="Floor" width="4" height="3">
  <properties>
   <property name="pyoneer_passability" value="FloorMasks"/>
  </properties>
  <data encoding="csv">
1,1,1,1,
1,1,1,1,
1,1,1,1
</data>
 </layer>
 <layer id="2" name="FloorMasks" width="4" height="3">
  <properties>
   <property name="pyoneer_renders" type="bool" value="false"/>
  </properties>
  <data encoding="csv">
0,20,0,2147483657,
0,0,0,0,
5,0,6,0
</data>
 </layer>
</map>
"""

# The same map with the mask tileset taken out, and its companions with it.
# A map that declares no collision must cost nothing and behave as before.
BARE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="4" height="3" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="9" nextobjectid="1">
 <tileset firstgid="1" name="probe" tilewidth="16" tileheight="16" tilecount="4" columns="2">
  <image source="no-such-art.png" width="32" height="32"/>
 </tileset>
 <layer id="1" name="Floor" width="4" height="3">
  <data encoding="csv">
1,1,1,1,
1,1,1,1,
1,1,1,1
</data>
 </layer>
</map>
"""

# The mask tileset declared and not one companion painted, which is what a
# map looks like the moment the author presses the collision-mode button and
# accepts the tileset offer. It has to bake nothing, not an open field.
UNPAINTED = BARE.replace(
    ' <layer id="1" name="Floor"',
    ' <tileset firstgid="5" name="collision" tilewidth="16" tileheight="16" '
    'tilecount="17" columns="17">\n'
    '  <image source="no-such-masks.png" width="272" height="16"/>\n'
    ' </tileset>\n'
    ' <layer id="1" name="Floor"')

# The tileset is declared but the companion the property names is not there.
# An author who renames a layer in Tiled leaves the property behind, and the
# result is a layer that silently stops blocking anything.
DANGLING = FIXTURE.replace('value="FloorMasks"', 'value="FloorMasksRenamed"')

scratch = tempfile.mkdtemp(prefix="pyoneer-collision-")
FIXTURE_PATH = os.path.join(scratch, "fixture.tmx")
BARE_PATH = os.path.join(scratch, "bare.tmx")
UNPAINTED_PATH = os.path.join(scratch, "unpainted.tmx")
DANGLING_PATH = os.path.join(scratch, "dangling.tmx")
for path, text in ((FIXTURE_PATH, FIXTURE), (BARE_PATH, BARE),
                   (UNPAINTED_PATH, UNPAINTED), (DANGLING_PATH, DANGLING)):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)

document = MapDocument.load(FIXTURE_PATH)
parsed = pytmx.TiledMap(FIXTURE_PATH)

expect("the collision tileset is found by name",
       collision_first_gid(document), 5)
expect("a map without one says so",
       collision_first_gid(MapDocument.load(BARE_PATH)), None)

expect("a declared companion is used, and one by convention is found",
       companion_pairs(document),
       [("Foreground", "ForegroundCollision"), ("Floor", "FloorMasks")])
expect("the convention is the layer name plus the suffix",
       "Foreground" + COMPANION_SUFFIX, "ForegroundCollision")
# companion_pairs must be TOPMOST FIRST, and "topmost" means DEPTH:
# Foreground is 60 in scripts/core/depth.py and Floor is 10. The fixture
# writes Foreground first, so reverse document order would answer "Floor" and
# a sort that ignored depth entirely would too.
expect("which puts the higher-drawing layer first",
       [name for name, _ in companion_pairs(document)][0], "Foreground")
expect("even though the file lists it before the layer it draws over",
       document.tile_layer_names().index("Foreground")
       < document.tile_layer_names().index("Floor"), True)

masks_layer = parsed_layer(parsed, "FloorMasks")
raw = [list(row) for row in masks_layer.data]
from_pytmx = file_gid_reader(parsed, masks_layer)
from_document = document_gid_reader(document.tile_layer("FloorMasks"))
grid_pytmx = [[from_pytmx(x, y) for x in range(4)] for y in range(3)]
grid_document = [[from_document(x, y) for x in range(4)] for y in range(3)]

# The trap this module exists to survive. pytmx numbers gids in the order it
# meets them, so the raw grid holds 2 where the file holds 20 -- and 2 is not
# even in the mask tileset's range, so reading it resolves every painted cell
# to "no opinion" without raising anything.
expect("pytmx really does renumber, so raw layer.data is not file gids",
       raw[0][1] != grid_document[0][1], True)
expect("the translated grid is the file's own",
       grid_pytmx, grid_document)
expect("including the flip bits, which tiledgidmap alone strips",
       grid_pytmx[0][3], 2147483657)
expect("the flip bits survive as a mirrored mask",
       gid_to_opinion(grid_pytmx[0][3], 5), BLOCK_LEFT)
expect("a cell outside the layer reads as empty", from_pytmx(9, 9), 0)

field = field_from_map(parsed)
# Everything below reads through `field`, and `field_from_map` answers None
# for a map whose stack came out empty. Stated first, so a change that empties
# this stack is a named failure rather than an AttributeError twelve lines on.
expect("the fixture bakes a field at all", field is not None, True)
expect("the field is the map's size and tile size",
       (field.width, field.height, field.tile_width, field.tile_height),
       (4, 3, 16, 16))
expect("an empty cell above a wall does not erase it",
       field.mask_at(1, 0), BLOCK_ALL)
expect("a flipped mask arrives mirrored", field.mask_at(3, 0), BLOCK_LEFT)
expect("the topmost layer wins over an open cell below it",
       field.mask_at(0, 2), BLOCK_ALL)
expect("a star in the top layer defers to the layer below",
       field.mask_at(2, 2), BLOCK_DOWN)
expect("everything unauthored is open",
       field.mask_at(0, 0), PASS_ALL)

expect("reading through the document alone gives the same field",
       field_from_map(document), field)
expect("and so does reading from a path", field_from_map(FIXTURE_PATH), field)

expect("a map with no collision tileset bakes nothing at all",
       field_from_map(pytmx.TiledMap(BARE_PATH)), None)
expect("nor does one with the tileset and nothing painted",
       (collision_first_gid(MapDocument.load(UNPAINTED_PATH)),
        field_from_map(pytmx.TiledMap(UNPAINTED_PATH))),
       (5, None))

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    dangling = field_from_map(MapDocument.load(DANGLING_PATH))
messages = " ".join(str(w.message) for w in caught)
expect("a companion that is not in the map is reported",
       "FloorMasksRenamed" in messages, True)
expect("and its layer simply stops blocking rather than crashing",
       dangling.mask_at(1, 0), PASS_ALL)
expect("while the layer that still has one keeps working",
       dangling.mask_at(0, 2), BLOCK_ALL)


# ---------------------------------------------------------------------------
# 7. The entity
# ---------------------------------------------------------------------------
print("\nthe entity")


class ProbeEntity(GameEntity):
    """A GameEntity that is actually constructible.

    GameEntity leaves core_lifecycle_build and core_input_receive abstract;
    filling those two in is the whole difference between the base class and
    something a scene may hold. No art: `image_path` stays empty, so nothing
    here needs a spritesheet the repository deliberately does not ship.
    """

    def core_lifecycle_build(self, event=None):
        pass

    def core_input_receive(self, events=None):
        pass


def probe(x, y, *, field=None, offset=(0.0, 0.0), speed=16):
    entity = ProbeEntity(movement_config={"move_speed": speed, "sprint_mult": 2})
    entity.moveto((x, y))
    entity.collision_field = field
    entity.collision_offset = offset
    return entity


# The ungated path must be untouched, to the bit. tools/smoke.py has a
# baseline for it and rule 8 says a pure addition must not move the frame.
ungated = probe(200.0, 200.0)
ungated.move_direction(0.25, "right")
expect("an entity with no field moves exactly as it always did",
       (ungated.transform.position.x, ungated.transform.position.y),
       (200.0 + 16 * 0.25, 200.0))
wanted = Vector2(3.0, 0.0)
expect("and the gate hands its argument back untouched, not a copy of it",
       ungated.allowed_move(wanted, "right") is wanted, True)
expect("an unknown direction is passed through rather than raising",
       ungated.allowed_move(wanted, "sideways") is wanted, True)
# Row 2 of `walls` is empty, so this probe has a field and nothing to clamp
# against. The unclamped path must still be a pass-through: rebuilding the
# vector from the magnitude and the step PROJECTS onto the direction axis,
# which is invisible for the four axis-aligned moves and loses a component
# for anything else.
unclamped = probe(8.0, 40.0, field=walls)
expect("a field that does not clamp still returns the caller's own vector",
       unclamped.allowed_move(wanted, "right") is wanted, True)
expect("so a vector off the axis is not silently projected onto it",
       tuple(unclamped.allowed_move(Vector2(3.0, 4.0), "right")), (3.0, 4.0))

# Cell (1,1) of `walls` is a full wall; the probe starts in the middle of
# (0,1) at pixel (8, 24) and walks right for longer than it takes to reach it.
walker = probe(8.0, 24.0, field=walls)
walker.move_direction(1.0, "right")
expect("walking into a wall stops inside the cell being left",
       walls.cell_of(walker.transform.position.x, walker.transform.position.y),
       (0, 1))
expect_close("just short of the boundary", walker.transform.position.x,
             16.0 - EDGE_INSET)
walker.move_direction(1.0, "right")
expect_close("and pressing on does not push through it",
             walker.transform.position.x, 16.0 - EDGE_INSET)
walker.move_direction(1.0, "up")
expect("while a direction the wall does not block still moves",
       walls.cell_of(walker.transform.position.x, walker.transform.position.y),
       (0, 0))

# All four verbs, one at a time, each into the border -- which is the cheapest
# wall there is and needs no fixture cells. A verb missing from DIRECTION_BITS
# would pass straight through the gate and walk out of the map.
box = CollisionField(1, 1, bytes([PASS_ALL]))
for verb, (start, want) in (("left", ((8.0, 8.0), (0.0, 8.0))),
                            ("up", ((8.0, 8.0), (8.0, 0.0))),
                            ("right", ((8.0, 8.0), (16.0 - EDGE_INSET, 8.0))),
                            ("down", ((8.0, 8.0), (8.0, 16.0 - EDGE_INSET)))):
    edge = probe(start[0], start[1], field=box, speed=64)
    edge.move_direction(1.0, verb)
    expect_close(f"{verb} is gated at the border (x)",
                 edge.transform.position.x, want[0])
    expect_close(f"{verb} is gated at the border (y)",
                 edge.transform.position.y, want[1])

# The offset says WHERE on the sprite the test happens. These two probes
# have the SAME collision point (8, 24) and sprites 16px apart, so the pair
# separates "the offset moved the test" from "the offset moved the sprite".
plain = probe(8.0, 24.0, field=walls, offset=(0.0, 0.0))
plain.move_direction(1.0, "right")
expect_close("with no offset the sprite's top-left is the tested point",
             plain.transform.position.x, 16.0 - EDGE_INSET)
shifted = probe(-8.0, 24.0, field=walls, offset=(16.0, 0.0))
shifted.move_direction(1.0, "right")
expect_close("an offset moves the tested point and not the sprite",
             shifted.transform.position.x, 0.0 - EDGE_INSET)

sprinter = probe(8.0, 40.0, field=walls, speed=16)
sprinter.move_direction(0.5, "right")
expect("sprint off travels speed * delta",
       sprinter.transform.position.x, 16.0)
sprinter = probe(8.0, 40.0, field=walls, speed=16)
sprinter.move_direction(0.5, "right", sprint=True)
expect("sprint on travels that times the multiplier",
       sprinter.transform.position.x, 24.0)
# Row 2 is empty, so the sprint above is unobstructed. Row 1 holds the wall,
# and a sprint has to be gated by the same boundary a walk is.
sprinter = probe(8.0, 24.0, field=walls, speed=16)
sprinter.move_direction(0.5, "right", sprint=True)
expect_close("and a sprint is gated by the same wall",
             sprinter.transform.position.x, 16.0 - EDGE_INSET)


# ---------------------------------------------------------------------------
# 8. One implementation: the editor's names ARE these objects
# ---------------------------------------------------------------------------
# There is one implementation. `editor/core/layers.py` and
# `editor/core/collision.py` import it from here, so the question is not "do
# the two agree" but "is there still only one" -- which is an IDENTITY test,
# not a value test. A pasted-back copy of `OPPOSITE` is a different dict
# object with equal contents; `==` sails straight past that and `is` cannot.
#
# A differential between two copies is only ever as complete as the copy it
# guards, which is why the one that stood here missed `OPPOSITE`, `can_move`,
# `blocks` and `mask_at_pixel`.
print("\nthe editor imports this module rather than copying it")

try:
    from editor.core import collision as editor_collision
    from editor.core import genre as editor_genre
    from editor.core import layers as editor_layers
except Exception as exc:                                        # noqa: BLE001
    # A FAILURE, not a skip. All three modules are pure Python -- no Qt, no
    # pygame, nothing optional -- so an import error here is a broken editor,
    # and skipping would delete the only guard against two copies of one
    # vocabulary while still printing OK and exiting 0.
    print(f"  FAIL {'the editors collision modules did not import':<58} {exc}")
    failures.append("editor/core/collision.py and layers.py must import")
    editor_collision = None

if editor_collision is not None:
    # `is`, not `==`. Every one of these is a function, a class or a dict, so
    # identity is available and equality is not enough: a re-pasted copy is
    # equal to the original on the day it is pasted and stops being equal on
    # some later day nobody is looking.
    shared_in_layers = ("describe_mask", "gid_to_mask", "mask_to_gid",
                        "DIRECTION_NAMES")
    expect("layers.py's mask vocabulary is this module's own objects",
           [name for name in shared_in_layers
            if getattr(editor_layers, name) is not getattr(runtime, name)],
           [])
    shared_in_collision = (
        "CollisionField", "CollisionLayer", "Resolution", "OpinionReader",
        "STEP", "OPPOSITE", "abstains", "companion_reader",
        "describe_opinion", "gid_to_opinion", "is_opinion", "join_gid",
        "opinion_to_gid", "resolve", "split_gid", "transform_mask",
        # Level one and the .blitmask format, which lived on the editor side
        # until `field_from_map` grew a reader for them. They are the newest
        # and therefore the likeliest to be pasted back.
        "Blitmask", "PyoneerBlitmaskError", "TilesetDefaults",
        "opinion_to_token", "token_to_opinion", "tileset_defaults",
        "tileset_reader")
    expect("collision.py's model is this module's own objects",
           [name for name in shared_in_collision
            if getattr(editor_collision, name) is not getattr(runtime, name)],
           [])
    # The plain numbers, which `is` cannot speak for: 0x1 and 0x10 are interned
    # by CPython, so a pasted `BLOCK_DOWN = 0x1` would pass an identity test on
    # a technicality. Read the editor's SOURCE instead and refuse a module-level
    # binding of any shared name -- which is the actual rule ("one definition
    # each, living in scripts/, imported by editor/") stated as a check.
    def module_level_bindings(module) -> set[str]:
        """Every name this module's own source assigns, defs or classes.

        Imports are deliberately not counted: importing a name is exactly what
        these two modules are supposed to do with it.
        """
        with open(module.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), module.__file__)
        bound: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                bound.add(node.name)
            elif isinstance(node, ast.Assign):
                bound.update(t.id for t in node.targets
                             if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                bound.add(node.target.id)
        return bound

    vocabulary = {"BLOCK_DOWN", "BLOCK_LEFT", "BLOCK_RIGHT", "BLOCK_UP",
                  "PASS_ALL", "BLOCK_ALL", "STAR", "NO_DATA",
                  "DIRECTION_NAMES", "GID_FLAG_MASK", "GID_VALUE_MASK",
                  "FLIP_HORIZONTAL", "FLIP_VERTICAL", "FLIP_DIAGONAL",
                  "STEP", "OPPOSITE", "describe_mask", "mask_to_gid",
                  "gid_to_mask", "opinion_to_gid", "gid_to_opinion",
                  "split_gid", "join_gid", "is_opinion", "describe_opinion",
                  "abstains", "companion_reader", "transform_mask",
                  "resolve", "Resolution", "CollisionLayer", "CollisionField",
                  "MAGIC", "NO_DATA_TOKEN", "STAR_TOKEN", "TOKENS",
                  "OPINIONS", "DEFAULTS_PROPERTY", "Blitmask",
                  "PyoneerBlitmaskError", "TilesetDefaults",
                  "opinion_to_token", "token_to_opinion", "tileset_defaults",
                  "tileset_reader"}
    expect("layers.py defines none of the shared vocabulary itself",
           sorted(module_level_bindings(editor_layers) & vocabulary), [])
    expect("nor does collision.py",
           sorted(module_level_bindings(editor_collision) & vocabulary), [])
    expect("...and this module defines all of it",
           sorted(vocabulary - module_level_bindings(runtime)), [])
    # canvas.py is the third module that could hold its own copy of the
    # tileset name, the companion suffix, `collision_first_gid` and
    # `companion_name`. Checked by source rather than by importing it,
    # because that module needs Qt and this file must run without it.
    canvas_source = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "editor", "ui", "canvas.py")
    with open(canvas_source, encoding="utf-8") as handle:
        canvas_bindings = set()
        for node in ast.parse(handle.read(), canvas_source).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                canvas_bindings.add(node.name)
            elif isinstance(node, ast.Assign):
                canvas_bindings.update(t.id for t in node.targets
                                       if isinstance(t, ast.Name))
    expect("canvas.py declares neither the tileset name nor the suffix",
           sorted(canvas_bindings & {"COLLISION_TILESET", "COMPANION_SUFFIX"}),
           [])

    # ---- the two depth tables ------------------------------------------
    # `layer_depth` here reads `scripts/core/depth.MAP_DEPTH`;
    # `MapCanvas.__depth_of` reads the genre pack's declared depth. Two
    # independently authored tables, and `resolve` walks TOPMOST FIRST, so a
    # layer they rank differently is a different DECIDING layer for the same
    # cell in the overlay than in the game. The canvas now falls back to
    # `depth_for_layer_name` for any name its pack does not declare, which
    # closes the "ranked here, unranked there" half; this closes the other
    # half, which is a pack declaring a depth the renderer disagrees with.
    print()
    print("the editor's genre packs and the renderer rank layers alike")
    packs = editor_genre.available()
    expect("there are genre packs to check", bool(packs), True)
    disagreements = []
    declared_names = set()
    for genre_id in packs:
        pack = editor_genre.load(genre_id)
        for layer in pack.layers:
            if layer.kind != "tile":
                continue        # object layers are placed by spawn.resolve_depth
            declared_names.add(layer.name)
            engine = resolve_layer_depth(layer.name)
            if engine is not None and engine != layer.depth:
                disagreements.append((genre_id, layer.name, layer.depth, engine))
    expect("every tile layer a pack declares sits where the renderer puts it",
           disagreements, [])
    # And the reverse direction: a name MAP_DEPTH ranks and no pack declares.
    # It is not an error -- the
    # packs describe what a genre EXPECTS, not everything a map may hold --
    # but the canvas has to answer with the renderer's number for it, not 500.
    unpacked = sorted(set(MAP_DEPTH) - declared_names)
    expect("names only the renderer ranks still get a real depth, not 500",
           [name for name in unpacked
            if runtime.depth_for_layer_name(name) != MAP_DEPTH[name]], [])
    expect("...and there really are some, so the line above is not vacuous",
           len(unpacked) >= 3, True)
    expect("a name neither table knows falls to UNRANKED_DEPTH",
           runtime.depth_for_layer_name("NoSuchLayerAnywhere"),
           runtime.UNRANKED_DEPTH)
    # test.tmx spells it "Paralax"; the alias is what keeps the pack (which
    # spells it the same way) and MAP_DEPTH (which does not) in agreement.
    expect("and the misspelled shipped layer resolves through the alias",
           runtime.depth_for_layer_name("Paralax"), MAP_DEPTH["Parallax"])


# ---------------------------------------------------------------------------
# 9. A companion finer than the map
# ---------------------------------------------------------------------------
print()
print("a companion may be finer than the map, and an old one is unchanged")

MASK_FIRST_GID = 5
BLOCK_ALL_GID = MASK_FIRST_GID + BLOCK_ALL


def rows_csv(values, columns):
    """A csv payload, one map row per text row, as Tiled writes it."""
    return ",\n".join(",".join(str(v) for v in values[y * columns:(y + 1) * columns])
                      for y in range(len(values) // columns))


def subcell_fixture(*, subcell=4, declare="4", painted=((4, 6),),
                    companion_cells=None, extra_layer=""):
    """A 4x4 map at 16px whose Floor companion is `subcell` times finer.

    `painted` is in the COMPANION's own cells, so `(4, 6)` at subcell 4 is
    the quarter-tile at pixels x 16..19, y 24..27 -- the left column, third
    row, of map tile (1, 1). Nothing about that square is expressible as a
    whole-tile mask, which is the entire point of the format.

    `declare` is written verbatim into the property so a check can author the
    values an author will actually mistype. `None` omits the property, which
    is the shape every map written before `pyoneer_subcell` existed has.
    """
    side = 4 * subcell if companion_cells is None else companion_cells
    cells = [0] * (side * side)
    for x, y in painted:
        cells[y * side + x] = BLOCK_ALL_GID
    prop = ""
    if declare is not None:
        prop = ('  <properties>\n   <property name="%s" type="int" '
                'value="%s"/>\n  </properties>\n' % (SUBCELL, declare))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="4" height="4" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="9" nextobjectid="1">
 <tileset firstgid="1" name="probe" tilewidth="16" tileheight="16" tilecount="4" columns="2">
  <image source="no-such-art.png" width="32" height="32"/>
 </tileset>
 <tileset firstgid="5" name="collision" tilewidth="16" tileheight="16" tilecount="17" columns="17">
  <image source="no-such-masks.png" width="272" height="16"/>
 </tileset>
{extra_layer} <layer id="1" name="Floor" width="4" height="4">
  <data encoding="csv">
{rows_csv([1] * 16, 4)}
</data>
 </layer>
 <layer id="2" name="FloorCollision" width="{side}" height="{side}">
{prop}  <data encoding="csv">
{rows_csv(cells, side)}
</data>
 </layer>
</map>
"""


def write(name, text):
    path = os.path.join(scratch, name)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


FINE_PATH = write("fine.tmx", subcell_fixture())
fine = field_from_map(MapDocument.load(FINE_PATH))

expect("the declared resolution is read off the companion layer",
       companion_subcell(MapDocument.load(FINE_PATH), "FloorCollision"), 4)
expect("and the stack bakes at the finest one it holds",
       field_subcell(MapDocument.load(FINE_PATH)), 4)
expect("so the field is subcell x the map, at a quarter of the tile",
       (fine.width, fine.height, fine.tile_width, fine.tile_height),
       (16, 16, 4, 4))
# The half a whole-tile field cannot express: two cells of ONE map tile
# disagreeing. Both of these are inside tile (1, 1).
expect("a painted sub-cell blocks",
       fine.mask_at(4, 6), BLOCK_ALL)
expect("and its neighbour inside the SAME map tile does not",
       (fine.mask_at(4, 4), fine.mask_at(5, 6)), (PASS_ALL, PASS_ALL))
expect("...so one map tile really does hold more than one answer",
       len({fine.mask_at(x, y) for x in (4, 5) for y in (4, 6)}), 2)

# Driven through the real gate, one sub-cell apart. The two probes are 8
# pixels apart vertically -- half a tile -- and start in the same map tile
# column, so a field baked at whole-tile resolution answers both the same way
# whatever it holds.
stopped = probe(10.0, 26.0, field=fine, speed=16)
stopped.move_direction(1.0, "right")
expect_close("a body is stopped by a sub-cell wall",
             stopped.transform.position.x, 16.0 - EDGE_INSET)
passing = probe(10.0, 18.0, field=fine, speed=16)
passing.move_direction(1.0, "right")
expect("while one 8px higher -- same map tile -- walks straight through",
       passing.transform.position.x, 26.0)
expect("and the two really were in the same map tile to begin with",
       (int(10.0 // 16), int(26.0 // 16), int(18.0 // 16)), (0, 1, 1))

# --- the migration guarantee -------------------------------------------
# `field` is section 6's 1x fixture, baked before any of this existed. The
# bytes are written out rather than compared to a re-bake of themselves: a
# check that asserts bake(x) == bake(x) passes for every possible bake.
expect("a 1x map still bakes at the map's own size and tile size",
       (field.width, field.height, field.tile_width, field.tile_height),
       (4, 3, 16, 16))
expect("and to exactly the bytes it baked before sub-cells existed",
       field.masks(),
       bytes([PASS_ALL, BLOCK_ALL, PASS_ALL, BLOCK_LEFT,
              PASS_ALL, PASS_ALL, PASS_ALL, PASS_ALL,
              BLOCK_ALL, PASS_ALL, BLOCK_DOWN, PASS_ALL]))

PLAIN_PATH = write("plain.tmx",
                   subcell_fixture(subcell=1, declare=None, painted=((1, 1),)))
DECLARED_ONE_PATH = write("one.tmx",
                          subcell_fixture(subcell=1, declare="1",
                                          painted=((1, 1),)))
plain = field_from_map(MapDocument.load(PLAIN_PATH))
expect("an undeclared companion is 1x, which is the format's default",
       companion_subcell(MapDocument.load(PLAIN_PATH), "FloorCollision"), 1)
expect("declaring 1 explicitly bakes the identical field",
       field_from_map(MapDocument.load(DECLARED_ONE_PATH)) == plain, True)
expect("...and that field is the map's shape, not the companion's",
       (plain.width, plain.tile_width), (4, 16))
# The other half: the two paths are only identical because the DATA is the
# same. A 4x companion over the same map is a different field, so the
# assertion above is not passing on a field that ignores its input.
expect("while the 4x companion over the same map is a different field",
       fine == plain, False)

# --- a companion smaller than the map is still legal --------------------
SMALL_PATH = write("small.tmx", subcell_fixture(
    subcell=1, declare=None, companion_cells=2, painted=((0, 0),)))
small = field_from_map(MapDocument.load(SMALL_PATH))
expect("a companion smaller than the map is not an error",
       (small.width, small.height), (4, 4))
expect("its cells decide, and past its edge nothing does",
       (small.mask_at(0, 0), small.mask_at(3, 3)), (BLOCK_ALL, PASS_ALL))

# --- the silent drop, now loud -----------------------------------------
# The failure this section exists for: a 16x16 companion on a 4x4 map that
# declares nothing bakes a 4x4 field, discarding every sub-cell outside the
# top-left corner without raising or warning.
UNDECLARED_PATH = write("undeclared.tmx", subcell_fixture(declare=None))
expect_raises("an oversized companion that declares nothing is refused",
              PyoneerConfigError,
              lambda: field_from_map(MapDocument.load(UNDECLARED_PATH)),
              # the layer, its real shape, what it currently claims, what the
              # map allows, and what to declare instead. An error that named
              # only the layer would leave the author guessing the ratio.
              "'FloorCollision'", "16x16", f"{SUBCELL}=1", "4x4",
              f"{SUBCELL}=4")

for label, value, fragment in (
        ("a value that is not an integer", "banana", "not an integer"),
        ("a value below one", "0", "1 or more"),
        ("a value the tile size does not divide by", "3",
         "does not divide evenly")):
    path = write(f"bad-{value}.tmx", subcell_fixture(declare=value))
    expect_raises(f"{label} is refused", PyoneerConfigError,
                  lambda p=path: field_from_map(MapDocument.load(p)), fragment)

# --- a stack that mixes resolutions ------------------------------------
# Foreground draws at depth 60 and Floor at 10, so Foreground is TOPMOST and
# `resolve` asks it first. Its companion is 1x; Floor's is 4x. The wall is
# painted at map cell (0, 3) -- pixels y 48..63.
FOREGROUND = """ <layer id="3" name="Foreground" width="4" height="4">
  <data encoding="csv">
0,0,0,0,
0,0,0,0,
0,0,0,0,
0,0,0,0
</data>
 </layer>
 <layer id="4" name="ForegroundCollision" width="4" height="4">
  <data encoding="csv">
0,0,0,0,
0,0,0,0,
0,0,0,0,
20,0,0,0
</data>
 </layer>
"""
MIXED_PATH = write("mixed.tmx", subcell_fixture(extra_layer=FOREGROUND))
expect("a mixed stack's resolution is the FINEST, never the coarsest",
       field_subcell(MapDocument.load(MIXED_PATH)), 4)
mixed = field_from_map(MapDocument.load(MIXED_PATH))
expect("a mixed stack bakes at the FINEST layer, not the topmost",
       (mixed.width, mixed.tile_width), (16, 4))
# The load-bearing pair. Read the 1x layer at sub-cell coordinates and its
# wall does not vanish -- it MOVES, from pixel row 48 to pixel row 12. Both
# halves are needed: the first alone passes for a field with a wall
# everywhere, the second alone for a field with no wall at all.
expect("the 1x layer's wall is at the pixels it was painted at",
       mixed.mask_at_pixel(2.0, 56.0), BLOCK_ALL)
expect("and NOT 40 pixels up the map, where an unscaled read would put it",
       mixed.mask_at_pixel(2.0, 14.0), PASS_ALL)
expect("while the 4x layer under it still decides its own sub-cell",
       mixed.mask_at(4, 6), BLOCK_ALL)
expect("and the topmost layer really is the 1x one",
       [name for name, _c in companion_pairs(MapDocument.load(MIXED_PATH))][0],
       "Foreground")

NESTING_PATH = write("nesting.tmx", subcell_fixture(
    subcell=2, declare="2", painted=((0, 0),), extra_layer=FOREGROUND))
expect("1 divides 2, so a stack of the two bakes at the finer one",
       field_subcell(MapDocument.load(NESTING_PATH)), 2)
BAD_NEST = subcell_fixture(subcell=3, declare="3", painted=((0, 0),))
# 16 is divisible by neither 3 nor a stack containing it; use tile size 12 so
# the only complaint left is the nesting one.
BAD_NEST = BAD_NEST.replace('tilewidth="16" tileheight="16" infinite',
                            'tilewidth="12" tileheight="12" infinite')
BAD_NEST = BAD_NEST.replace(
    ' <layer id="1" name="Floor"',
    ' <layer id="3" name="Foreground" width="4" height="4">\n'
    '  <data encoding="csv">\n0,0,0,0,\n0,0,0,0,\n0,0,0,0,\n0,0,0,0\n</data>\n'
    ' </layer>\n'
    ' <layer id="4" name="ForegroundCollision" width="8" height="8">\n'
    '  <properties>\n   <property name="%s" type="int" value="2"/>\n'
    '  </properties>\n'
    '  <data encoding="csv">\n' % SUBCELL
    + rows_csv([0] * 64, 8) + '\n</data>\n </layer>\n'
    ' <layer id="1" name="Floor"')
BAD_NEST_PATH = write("badnest.tmx", BAD_NEST)
expect_raises("a stack whose resolutions do not nest is refused",
              PyoneerConfigError,
              lambda: field_from_map(MapDocument.load(BAD_NEST_PATH)),
              "do not nest", "finest is 3", "declares 2")

# --- the scale, on its own ---------------------------------------------
grid = {(0, 0): BLOCK_ALL_GID, (1, 1): MASK_FIRST_GID + BLOCK_DOWN}
cells = lambda x, y: grid.get((x, y), 0)                          # noqa: E731
coarse = companion_reader(cells, MASK_FIRST_GID, scale=4)
exact = companion_reader(cells, MASK_FIRST_GID)
expect("scale 4 spreads one layer cell over four field cells each way",
       [coarse(x, 0) for x in range(5)],
       [BLOCK_ALL, BLOCK_ALL, BLOCK_ALL, BLOCK_ALL, NO_DATA])
expect("and it is a different reader from the unscaled one",
       (exact(3, 0), coarse(3, 0)), (NO_DATA, BLOCK_ALL))
expect("scale floors on the negative side too, rather than truncating",
       (coarse(-1, -1), coarse(-4, -4)), (NO_DATA, NO_DATA))
expect("the second layer cell starts where the first one ends",
       (coarse(4, 4), coarse(7, 7), coarse(8, 8)),
       (BLOCK_DOWN, BLOCK_DOWN, NO_DATA))
expect_raises("a scale below one is refused", ValueError,
              lambda: companion_reader(cells, MASK_FIRST_GID, scale=0),
              "1 or more")


# ---------------------------------------------------------------------------
# 10. Level one: the mask baked into the TILE
# ---------------------------------------------------------------------------
# The claim: a mask authored once per tile, in a `.blitmask` beside the map
# and named by the tileset's own `pyoneer_collision`, gates a body wherever
# that tile is stamped -- UNDER anything a companion layer says about the
# same cell.
#
# Precedence is the whole of it, and precedence is the shape this repository
# gets wrong: a rule proved to APPLY and never proved to be OVERRIDDEN passes
# just as happily when the levels are merged, or reordered, or when the
# weakest one quietly wins. So every claim below is made in both directions:
#
#   a default gates where nothing was painted   AND  a paint beats a default
#   a paint beats a default                     AND  it REPLACES rather than
#                                                    merging with it
#   a star suppresses a default                 AND  the layer BELOW is asked
#   a map with no mask file is unchanged        AND  the same map with one is
#                                                    measurably different
#   an unpaired layer joins the stack           AND  only when defaults exist
#   a moving layer is left out                  AND  its static twin joins
#   painting a mask on a moving layer does      AND  the same mask on the
#     not buy it a place in the stack                static twin still gates
print()
print("level one: a mask baked into the tile")

# `.` is NO_DATA, so tile 0 says nothing at all -- which is what makes the
# "unauthored is open" cells below a real answer rather than an absence of
# tiles. Tile 1 blocks everything, tile 2 blocks down, tile 3 blocks right
# (chosen so a horizontal flip has something to mirror).
NL_ = chr(10)
PROBE_MASK = "blitmask 1\nsize 2 2\nname probe\n.f\n14\n"
# The second sheet exists to make a firstgid that is NOT 1 load-bearing:
# its tile 1 is gid 23, and a reader that fell back to the file's own
# `firstgid` metadata (1) would look up local id 22, find nothing, and
# answer silence for a cell the author plainly stamped.
CLUTTER_MASK = "blitmask 1\nsize 2 2\nname clutter\n.2\n..\n"

FLIPPED_RIGHT = 4 | FLIP_HORIZONTAL      # tile 3, mirrored: blocks LEFT

DEFAULTS = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="4" height="3" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="9" nextobjectid="1">
 <tileset firstgid="1" name="probe" tilewidth="16" tileheight="16" tilecount="4" columns="2">
  <properties>
   <property name="pyoneer_collision" value="probe.blitmask"/>
  </properties>
  <image source="no-such-art.png" width="32" height="32"/>
 </tileset>
 <tileset firstgid="5" name="collision" tilewidth="16" tileheight="16" tilecount="17" columns="17">
  <image source="no-such-masks.png" width="272" height="16"/>
 </tileset>
 <tileset firstgid="22" name="clutter" tilewidth="16" tileheight="16" tilecount="4" columns="2">
  <properties>
   <property name="pyoneer_collision" value="clutter.blitmask"/>
  </properties>
  <image source="no-such-clutter.png" width="32" height="32"/>
 </tileset>
 <layer id="1" name="Foreground" width="4" height="3">
  <data encoding="csv">
0,0,0,0,
0,0,0,0,
2,2,0,0
</data>
 </layer>
 <layer id="2" name="ForegroundCollision" width="4" height="3">
  <data encoding="csv">
0,0,0,0,
0,0,0,0,
0,21,0,0
</data>
 </layer>
 <layer id="3" name="Floor" width="4" height="3">
  <properties>
   <property name="pyoneer_passability" value="FloorMasks"/>
  </properties>
  <data encoding="csv">
1,2,3,2147483652,
2,2,2,2,
1,3,1,1
</data>
 </layer>
 <layer id="4" name="FloorMasks" width="4" height="3">
  <data encoding="csv">
0,0,0,0,
0,5,6,21,
0,0,0,0
</data>
 </layer>
 <layer id="6" name="GroundClutter" width="4" height="3">
  <data encoding="csv">
0,0,0,0,
0,0,0,0,
0,0,23,0
</data>
 </layer>
 <layer id="5" name="Paralax" width="4" height="3">
  <properties>
   <property name="pyoneer_parallax_x" type="float" value="1.4"/>
  </properties>
  <data encoding="csv">
0,0,0,0,
0,0,0,0,
0,0,0,2
</data>
 </layer>
</map>
"""

# The SAME map with the one property removed. Everything else -- every layer,
# every gid, the mask file still sitting on disk beside it -- is identical,
# so any difference between the two fields is this feature and nothing else.
NO_DEFAULTS = DEFAULTS
for _sheet in ("probe.blitmask", "clutter.blitmask"):
    NO_DEFAULTS = NO_DEFAULTS.replace(
        "  <properties>" + NL_ + '   <property name="pyoneer_collision" '
        + 'value="%s"/>' % _sheet + NL_ + "  </properties>" + NL_, "")
assert NO_DEFAULTS != DEFAULTS and "pyoneer_collision" not in NO_DEFAULTS

# Paralax at 1.0 is no longer parallaxed, so it is an ordinary world-
# coordinate layer and joins the stack with nothing declared on it at all.
WORLD_PARALLAX = DEFAULTS.replace('value="1.4"', 'value="1.0"')

# ---- the same layer, PAIRED, under each of the four declarations --------
# A companion for Paralax that actually says something: BLOCK_ALL at (0, 0),
# the one cell of this map every other layer abstains at, so "is Paralax in
# the stack" is readable in a single byte of the baked field. Paralax also
# holds a BLOCK_ALL tile at (3, 2), which asks the same question of LEVEL
# ONE -- a paired layer carries both levels, and excluding it has to take
# both.
PARALAX_MASKS = (
    ' <layer id="7" name="ParalaxMasks" width="4" height="3">\n'
    '  <data encoding="csv">\n20,0,0,0,\n0,0,0,0,\n0,0,0,0\n</data>\n'
    ' </layer>\n')
PARALAX_PROPS = ('  <properties>\n'
                 '   <property name="pyoneer_parallax_x" type="float" '
                 'value="1.4"/>\n'
                 '  </properties>\n')
assert PARALAX_PROPS in DEFAULTS
PARALLAX_X_PROP = ('   <property name="pyoneer_parallax_x" type="float" '
                   'value="1.4"/>\n')
DYNAMIC_PROP = '   <property name="pyoneer_motion" value="dynamic"/>\n'
PASSABILITY_PROP = ('   <property name="pyoneer_passability" '
                    'value="ParalaxMasks"/>\n')


def paired_parallax(*properties: str) -> str:
    """DEFAULTS with Paralax declaring exactly `properties`, plus a companion.

    One function rather than four hand-written maps: every byte outside that
    <properties> block is identical across the variants, so a difference
    between two of their fields is the declaration and nothing else.
    """
    text = DEFAULTS.replace(
        PARALAX_PROPS,
        '  <properties>\n%s  </properties>\n' % "".join(properties),
    ).replace('</map>', PARALAX_MASKS + '</map>')
    assert text != DEFAULTS and 'name="ParalaxMasks"' in text
    return text


# The control is PAIRED_STATIC: a paired layer declaring nothing else is an
# ordinary world-coordinate layer and its masks gate. The other three are the
# ways a layer stops being over the map -- parallax, motion, and both at
# once, which is the shape the map being painted carried when this was found.
PAIRED_STATIC = paired_parallax(PASSABILITY_PROP)
PAIRED_PARALLAX = paired_parallax(PARALLAX_X_PROP, PASSABILITY_PROP)
PAIRED_DYNAMIC = paired_parallax(DYNAMIC_PROP, PASSABILITY_PROP)
PAIRED_BOTH = paired_parallax(PARALLAX_X_PROP, DYNAMIC_PROP, PASSABILITY_PROP)

level_one_scratch = tempfile.mkdtemp(prefix="pyoneer-defaults-")


def write_level_one(name, text, *, mask=PROBE_MASK, mask_name="probe.blitmask"):
    """One .tmx plus the sidecar it names, in their own directory.

    A directory each, because half of these fixtures exist to be missing a
    file and the other half must not be affected by that.
    """
    room = os.path.join(level_one_scratch, name)
    os.makedirs(room, exist_ok=True)
    map_path = os.path.join(room, "map.tmx")
    with open(map_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    if mask is not None:
        with open(os.path.join(room, mask_name), "w",
                  encoding="utf-8", newline="") as handle:
            handle.write(mask)
    with open(os.path.join(room, "clutter.blitmask"), "w",
              encoding="utf-8", newline="") as handle:
        handle.write(CLUTTER_MASK)
    return map_path


DEFAULTS_PATH = write_level_one("with", DEFAULTS)
NO_DEFAULTS_PATH = write_level_one("without", NO_DEFAULTS)

# ---- the sidecar is found, read, and addressed by gid --------------------
table = tileset_defaults(MapDocument.load(DEFAULTS_PATH))
expect("every tileset that names a sidecar gets one entry, in map order",
       [(d.name, d.first_gid, d.columns, d.rows) for d in table],
       [("probe", 1, 2, 2), ("clutter", 22, 2, 2)])
# The second sheet is the one that makes the FIRSTGID load-bearing. Its
# file says `firstgid 1` nowhere, and the map's own 22 is what addresses
# it; a reader taking the number from the sidecar instead would read gid
# 23 as local id 22, find nothing, and answer silence.
expect("a sidecar is addressed by the MAP's firstgid, not by its own",
       [table[1].opinion_for_gid(gid) for gid in (22, 23, 24)],
       [NO_DATA, BLOCK_LEFT, NO_DATA])
expect("...and the two sheets do not answer for each other" + "'" + "s gids",
       (table[0].opinion_for_gid(23), table[1].opinion_for_gid(2)),
       (NO_DATA, NO_DATA))
expect("a tileset that names nothing contributes nothing",
       tileset_defaults(MapDocument.load(NO_DEFAULTS_PATH)), [])
expect("a tile's mask is addressed by its gid, not by its index",
       [table[0].opinion_for_gid(gid) for gid in (1, 2, 3, 4)],
       [NO_DATA, BLOCK_ALL, BLOCK_DOWN, BLOCK_RIGHT])
expect("a gid outside the tileset is silence, not open",
       table[0].opinion_for_gid(5), NO_DATA)
# The flip pair. A tileset default is read off the ART layer, and art is
# flipped constantly -- a mirrored wall that blocks from the side it is not
# drawn on is the bug that only shows on the mirrored half of a room.
expect("an unflipped tile blocks the way it was authored",
       table[0].opinion_for_gid(4), BLOCK_RIGHT)
expect("and the same tile mirrored blocks from the other side",
       table[0].opinion_for_gid(FLIPPED_RIGHT), BLOCK_LEFT)

# ---- the baked field -----------------------------------------------------
level_one_field = field_from_map(DEFAULTS_PATH)
plain_field = field_from_map(NO_DEFAULTS_PATH)

expect("the field is still the map's size; level one adds no resolution",
       (level_one_field.width, level_one_field.height,
        level_one_field.tile_width, level_one_field.tile_height),
       (4, 3, 16, 16))

# THE HEADLINE. Floor (1, 0) holds tile 1, whose tileset mask is BLOCK_ALL,
# and FloorMasks is EMPTY there -- nobody painted a companion cell.
expect("a tile default gates a cell nobody painted",
       level_one_field.mask_at(1, 0), BLOCK_ALL)
expect("...and the same cell of the same map without the sidecar is open",
       plain_field.mask_at(1, 0), PASS_ALL)
expect("a partly-blocking tile default keeps its own bits",
       level_one_field.mask_at(2, 0), BLOCK_DOWN)
expect("a flipped tile's default arrives mirrored in the field",
       level_one_field.mask_at(3, 0), BLOCK_LEFT)
expect("a tile whose mask is a dot still says nothing",
       level_one_field.mask_at(0, 0), PASS_ALL)

# THE OTHER HALF, and the one a merge would pass. Row 1 is tile 1 all the way
# across, so every cell in it has a BLOCK_ALL default underneath.
expect("row 1 really is defaulted to blocked before the paint lands",
       (level_one_field.mask_at(0, 1), plain_field.mask_at(0, 1)),
       (BLOCK_ALL, PASS_ALL))
expect("a painted OPEN cell beats the tile default rather than losing to it",
       level_one_field.mask_at(1, 1), PASS_ALL)
expect("a painted PARTIAL cell REPLACES the default, it does not merge",
       level_one_field.mask_at(2, 1), BLOCK_DOWN)
# The merge would be BLOCK_ALL | BLOCK_DOWN == BLOCK_ALL, which is also what
# no override at all gives. Saying it as its own assertion means the label
# names the failure rather than the value.
expect("...so the merged answer is exactly what did NOT happen",
       level_one_field.mask_at(2, 1) == (BLOCK_ALL | BLOCK_DOWN), False)

# A star is an authored abstention. Over a tileset default it SUPPRESSES it
# -- which NO_DATA cannot do -- and hands the question to the layer below.
expect("a star painted over a default suppresses it",
       level_one_field.mask_at(3, 1), PASS_ALL)
expect("and it hands the cell to the layer BELOW, whose default decides",
       level_one_field.mask_at(1, 2), BLOCK_DOWN)
expect("...which is not what the starred layer's own default said",
       table[0].opinion_for_gid(2), BLOCK_ALL)
expect("the topmost layer's default wins over a lower layer's",
       level_one_field.mask_at(0, 2), BLOCK_ALL)

# The whole field, as bytes. One line that fails if any cell above moved, and
# the pair below is the migration guarantee: a map with no sidecar bakes what
# it baked before level one existed, to the bit.
expect("the whole field is what the three levels say it is",
       list(level_one_field.masks()),
       [0, 15, 1, 2,
        15, 0, 1, 0,
        15, 1, 2, 0])
expect("a map with no sidecar bakes exactly the companion-only field",
       list(plain_field.masks()),
       [0, 0, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 0])
expect("...and the two are really different, so the line above is not vacuous",
       level_one_field == plain_field, False)

# ---- which layers level one reaches -------------------------------------
# GroundClutter declares nothing at all: no companion, no passability, no
# property of any kind. It holds one tile from the SECOND sheet, and that is
# the entire authoring step this feature exists to reduce the job to.
expect("a layer that declares nothing gates through its tiles alone",
       (level_one_field.mask_at(2, 2), plain_field.mask_at(2, 2)),
       (BLOCK_LEFT, PASS_ALL))
expect("...and it is really unpaired, so nothing but the tileset put it there",
       [name for name, _c in companion_pairs(MapDocument.load(DEFAULTS_PATH))],
       ["Foreground", "Floor"])
# ---- WHICH LAYERS ARE AT WORLD COORDINATES ------------------------------
# Four quadrants, and the bug that wrote this block lived in exactly one of
# them. A layer drawn at a camera-dependent offset is filtered out of the
# stack -- but the filter used to run only for a layer with NO companion, so
# PAINTING a mask on a parallax layer routed around it, and one background
# layer then gated every body on the map at every depth.
#
#               no companion                companion declared
#   static      joins (level one)           joins, and its masks gate
#   moving      left out, in silence        left out, and WARNS
#
# All four are asserted. A "fix" that drops every paired layer, or every
# layer, or that warns about a layer it still gates on, passes any one of
# them alone.

# Paralax draws at 1.4x the camera, so its cell (3, 2) is not over the map's
# cell (3, 2). It holds a BLOCK_ALL tile there and must not gate.
expect("a parallaxed layer's tiles do not gate the world",
       level_one_field.mask_at(3, 2), PASS_ALL)
world_field = field_from_map(write_level_one("world", WORLD_PARALLAX))
expect("the same layer at parallax 1.0 joins with nothing declared on it",
       world_field.mask_at(3, 2), BLOCK_ALL)
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    field_from_map(DEFAULTS_PATH)
expect("an UNPAIRED moving layer is dropped in silence: nothing was authored",
       [str(item.message) for item in caught], [])


def paired_field(name, text):
    """The baked field of one `paired_parallax` variant, and what it warned."""
    with warnings.catch_warnings(record=True) as caught_:
        warnings.simplefilter("always")
        baked = field_from_map(write_level_one(name, text))
    return baked, " ".join(str(item.message) for item in caught_)


def cell(baked, x, y):
    """`mask_at`, but readable when the map baked NO field at all.

    None is a real answer in this section -- emptying the stack is exactly
    what excluding the wrong layer does -- and an assertion that dies on it
    with an AttributeError names nothing.
    """
    return None if baked is None else baked.mask_at(x, y)


static_field, static_said = paired_field("paired_static", PAIRED_STATIC)
parallax_field, parallax_said = paired_field("paired_parallax", PAIRED_PARALLAX)
dynamic_field, dynamic_said = paired_field("paired_dynamic", PAIRED_DYNAMIC)
both_field, both_said = paired_field("paired_both", PAIRED_BOTH)

# The control half, and it has to be read at BOTH levels: a paired layer
# carries a companion AND its own tiles' defaults, and a filter that took
# only one of them would look right at whichever cell was asserted. (0, 0) is
# the companion's painted BLOCK_ALL -- the one cell of this map no other
# layer has an opinion about -- and (3, 2) is Paralax's own tile default.
expect("a static layer's companion gates, and so does its tile default",
       (cell(static_field, 0, 0), cell(static_field, 3, 2)),
       (BLOCK_ALL, BLOCK_ALL))
expect("...and that layer really is in the stack",
       [layer.name for layer in
        collision_layers(MapDocument.load(
            write_level_one("paired_static", PAIRED_STATIC)))],
       ["Foreground", "GroundClutter", "Floor", "Paralax"])

# The half that was broken. Declaring a companion must not buy a moving layer
# a place in the stack, by either level, under any of the three declarations.
MOVING = (("parallaxed", PAIRED_PARALLAX), ("dynamic", PAIRED_DYNAMIC),
          ("parallaxed+dynamic", PAIRED_BOTH))
for (_label, _text), _got in zip(MOVING, (parallax_field, dynamic_field,
                                          both_field)):
    expect(f"a {_label} layer is excluded THOUGH it declares a companion",
           (cell(_got, 0, 0), cell(_got, 3, 2)), (PASS_ALL, PASS_ALL))
    expect(f"...and the whole {_label} field is the one with no Paralax in it",
           _got and list(_got.masks()), list(level_one_field.masks()))
    expect(f"...and the {_label} layer is in no stack under any name",
           "Paralax" in [layer.name for layer in collision_layers(
               MapDocument.load(write_level_one("stack-" + _label, _text)))],
           False)

# ...and the two fields really do differ, so the lines above are not all
# passing because every variant bakes the same nothing. Exactly two cells:
# (0, 0) is index 0 and (3, 2) is index 11 of a 4-wide field.
expect("the static twin blocks exactly the two cells the moving one drops",
       [i for i, (a, b) in enumerate(zip(static_field.masks(),
                                         parallax_field.masks())) if a != b],
       [0, 11])

# THE WARNING IS THE DESIGN CHOICE. Raising would make an author's map
# unloadable over content the editor let him paint; silence is the Paralax
# misspelling that lost 39 tiles for months. So the message names the layer,
# the companion whose masks are being dropped, and the reason -- and the
# reason is read from the layer, so each variant names its own.
expect("the warning names the layer, its companion, and the fault it has",
       [(("Paralax" in said), ("ParalaxMasks" in said),
         ("pyoneer_parallax_x" in said), ("pyoneer_motion" in said))
        for said in (parallax_said, dynamic_said, both_said)],
       [(True, True, True, False),
        (True, True, False, True),
        (True, True, True, True)])
expect("...and the static twin, which still gates, says nothing at all",
       static_said, "")

paired_document = MapDocument.load(write_level_one("paired_both", PAIRED_BOTH))
expect("world_coordinate_fault spells both faults the way the map does",
       world_coordinate_fault(paired_document, "Paralax"),
       "parallaxed (pyoneer_parallax_x=1.4, pyoneer_parallax_y=1) and "
       "pyoneer_motion=dynamic")
expect("...and answers None for a layer whose cells ARE the map's cells",
       (world_coordinate_fault(paired_document, "Floor"),
        at_world_coordinates(paired_document, "Floor"),
        at_world_coordinates(paired_document, "Paralax")),
       (None, True, False))

# ---- the second-order effect: the stack can come out EMPTY ---------------
# The map this was reported on had its ONLY masks painted on the parallax
# layer, so excluding it leaves the stack empty -- and an empty stack bakes
# no field at all, which means every body is UNGATED. That is the correct
# answer for a map whose only collision was painted where collision cannot
# be, and it is the one answer that must not arrive quietly.
ONLY_PARALLAX = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="4" height="3" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="9" nextobjectid="1">
 <tileset firstgid="1" name="collision" tilewidth="16" tileheight="16" tilecount="17" columns="17">
  <image source="no-such-masks.png" width="272" height="16"/>
 </tileset>
 <layer id="1" name="Floor" width="4" height="3">
  <data encoding="csv">
0,0,0,0,
0,0,0,0,
0,0,0,0
</data>
 </layer>
 <layer id="2" name="Paralax" width="4" height="3">
  <properties>
   <property name="pyoneer_motion" value="dynamic"/>
   <property name="pyoneer_parallax_x" type="float" value="1.4"/>
   <property name="pyoneer_passability" value="ParalaxCollision"/>
  </properties>
  <data encoding="csv">
0,0,0,0,
0,0,0,0,
0,0,0,0
</data>
 </layer>
 <layer id="3" name="ParalaxCollision" width="4" height="3">
  <properties>
   <property name="pyoneer_renders" type="bool" value="false"/>
  </properties>
  <data encoding="csv">
16,0,0,0,
0,0,0,0,
0,0,0,0
</data>
 </layer>
</map>
"""
# The same map with the two motion properties gone. Identical everywhere
# else, the painted mask included, so the difference between the two fields
# is the declaration and nothing else.
SETTLED_PARALLAX = ONLY_PARALLAX.replace(
    '   <property name="pyoneer_motion" value="dynamic"/>\n'
    '   <property name="pyoneer_parallax_x" type="float" value="1.4"/>\n', "")
assert SETTLED_PARALLAX != ONLY_PARALLAX

only_field, only_said = paired_field("only-parallax", ONLY_PARALLAX)
expect("a map whose only masks are on a moving layer bakes NO field at all",
       only_field, None)
expect("...and says which layer, which masks, and what to do instead",
       ("Paralax" in only_said, "ParalaxCollision" in only_said,
        "NOTHING ON THIS LAYER GATES MOVEMENT" in only_said,
        "static, unparallaxed" in only_said),
       (True, True, True, True))
settled_field, settled_said = paired_field("settled-parallax",
                                           SETTLED_PARALLAX)
expect("the same map with those two properties gone bakes a field that blocks",
       (settled_field and settled_field.width, cell(settled_field, 0, 0)),
       (4, BLOCK_ALL))
expect("...and warns about nothing, so the None above is the motion and not "
       "a broken fixture", settled_said, "")

# The guard that keeps every existing map on its old bytes: an unpaired layer
# joins the stack only when there are defaults for it to carry.
expect("an unpaired layer joins the stack only when defaults exist",
       ([layer.name for layer in
         collision_layers(MapDocument.load(write_level_one("world2",
                                                           WORLD_PARALLAX)))],
        [layer.name for layer in
         collision_layers(MapDocument.load(NO_DEFAULTS_PATH))]),
       (["Foreground", "GroundClutter", "Floor", "Paralax"],
        ["Foreground", "Floor"]))

# ---- the gate, from a body's point of view -------------------------------
# A field is only worth baking if something refuses a step because of it.
expect_close("a body is stopped by a tile default it never painted",
             allowed_distance(level_one_field, 8.0, 8.0, BLOCK_RIGHT, 16.0),
             8.0 - EDGE_INSET)
expect("...and walks the same step freely without the sidecar",
       allowed_distance(plain_field, 8.0, 8.0, BLOCK_RIGHT, 16.0), 16.0)
walker = probe(8.0, 8.0, field=level_one_field, speed=64)
walker.move_direction(1.0, "right")
expect("and the entity path clamps against it too, not just the gate",
       walker.transform.position.x < 16.0, True)

# ---- level one under a 4x companion --------------------------------------
# An art layer has no sub-cells: it is drawn, one tile per map cell. So its
# default has to cover the whole map tile in a field baked four times finer,
# and a companion sub-cell inside that tile still has to beat it.
SUBCELL_DEFAULTS = DEFAULTS.replace(
    ' <layer id="4" name="FloorMasks" width="4" height="3">\n'
    '  <data encoding="csv">\n0,0,0,0,\n0,5,6,21,\n0,0,0,0\n</data>\n'
    ' </layer>\n',
    ' <layer id="4" name="FloorMasks" width="16" height="12">\n'
    '  <properties>\n   <property name="pyoneer_subcell" type="int" value="4"/>\n'
    '  </properties>\n  <data encoding="csv">\n'
    + ",\n".join(",".join("5" if (x, y) == (6, 2) else "0"
                          for x in range(16)) for y in range(12))
    + "\n</data>\n </layer>\n")
assert 'width="16" height="12"' in SUBCELL_DEFAULTS
subcell_field = field_from_map(write_level_one("subcell", SUBCELL_DEFAULTS))
expect("a 4x companion bakes a 4x field, and level one comes with it",
       (subcell_field.width, subcell_field.height, subcell_field.tile_width),
       (16, 12, 4))
expect("one stamped tile's default covers all four of its sub-cells across",
       [subcell_field.mask_at(x, 1) for x in (4, 5, 6, 7)],
       [BLOCK_ALL, BLOCK_ALL, BLOCK_ALL, BLOCK_ALL])
# ...except the one quarter-tile a companion cell was painted open in. Same
# map tile, same default, one sub-cell apart.
expect("and a painted sub-cell still beats it, inside that same tile",
       subcell_field.mask_at(6, 2), PASS_ALL)
expect("...while its neighbour a quarter-tile away keeps the default",
       subcell_field.mask_at(5, 2), BLOCK_ALL)

# ---- no companion, no collision tileset, and it still gates --------------
# The promise level one is FOR: an author who has painted nothing has no
# companion layer, and a map that has never been in collision mode has no
# `collision` tileset either. Gating the read on either of them would make
# the one level that needs no painting the one level you cannot have without
# painting -- so this map declares neither, and still gates.
LONE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="4" height="3" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="3" nextobjectid="1">
 <tileset firstgid="1" name="probe" tilewidth="16" tileheight="16" tilecount="4" columns="2">
  <properties>
   <property name="pyoneer_collision" value="probe.blitmask"/>
  </properties>
  <image source="no-such-art.png" width="32" height="32"/>
 </tileset>
 <layer id="1" name="Floor" width="4" height="3">
  <data encoding="csv">
1,2,3,2147483652,
0,0,0,0,
0,0,0,0
</data>
 </layer>
</map>
"""
lone_document = MapDocument.load(write_level_one("lone", LONE))
expect("a map may declare tile defaults and no collision tileset at all",
       collision_first_gid(lone_document), None)
expect("...and no companion layer either",
       companion_pairs(lone_document), [])
lone_field = field_from_map(lone_document)
expect("yet the tile defaults alone bake a field",
       lone_field is not None, True)
expect("which gates the stamped tiles, mirroring the flipped one",
       [lone_field.mask_at(x, 0) for x in range(4)],
       [PASS_ALL, BLOCK_ALL, BLOCK_DOWN, BLOCK_LEFT])
expect("and leaves the cells that hold no tile alone",
       [lone_field.mask_at(x, 1) for x in range(4)],
       [PASS_ALL, PASS_ALL, PASS_ALL, PASS_ALL])
expect("while the same map with the reference removed bakes nothing at all",
       field_from_map(write_level_one(
           "lone-plain",
           LONE.replace('<property name="pyoneer_collision" '
                        'value="probe.blitmask"/>', ''))),
       None)


# ---- a short sidecar is authored data, not a mistake ---------------------
# Masking the wall rows of a sheet and stopping is ordinary. Tiles past the
# end of the file say nothing; they do not block and they do not raise.
short_field = field_from_map(write_level_one(
    "short", DEFAULTS, mask="blitmask 1\nsize 2 1\nname probe\n.f\n"))
expect("a sidecar shorter than the sheet masks what it covers",
       short_field.mask_at(1, 0), BLOCK_ALL)
expect("and says nothing about the tiles past its last row",
       (short_field.mask_at(2, 0), short_field.mask_at(3, 0)),
       (PASS_ALL, PASS_ALL))


# ---- declared and not honourable: every one of them raises ---------------
# The line this whole feature turns on. An ABSENT property is the optional
# case and must cost nothing; a PRESENT one that cannot be honoured must be
# loud, because every failure below reads, from the player's side, as a
# feature nobody switched on.
print()
print("a declared sidecar that cannot be honoured raises")

expect_raises(
    "a sidecar that is not there is named, with the path it resolved to",
    PyoneerConfigError,
    lambda: field_from_map(write_level_one(
        "missing", DEFAULTS.replace('"probe.blitmask"', '"no-such.blitmask"'))),
    "pyoneer_collision", "no-such.blitmask", "is not there")

expect_raises(
    "a tileset whose extent this map cannot know is refused",
    PyoneerConfigError,
    lambda: field_from_map(write_level_one(
        "extent", DEFAULTS.replace(' tilecount="4" columns="2"', ' columns="2"'))),
    "probe", "no mask")

expect_raises(
    "a tileset with no columns is refused; a mask grid needs them",
    PyoneerConfigError,
    lambda: field_from_map(write_level_one(
        "columns", DEFAULTS.replace(' tilecount="4" columns="2"', ' tilecount="4"'))),
    "probe", "no columns")

expect_raises(
    "a sidecar a different WIDTH from the sheet is refused, not shifted",
    PyoneerConfigError,
    lambda: field_from_map(write_level_one(
        "width", DEFAULTS.replace(' tilecount="4" columns="2"',
                                  ' tilecount="4" columns="4"'))),
    "4 columns wide", "are 2", "shifts every row")

expect_raises(
    "a sidecar TALLER than the sheet is refused; those cells read by nothing",
    PyoneerConfigError,
    lambda: field_from_map(write_level_one(
        "taller", DEFAULTS.replace(' tilecount="4" columns="2"',
                                   ' tilecount="2" columns="2"'))),
    "read by nothing")

expect_raises(
    "a sidecar that names a DIFFERENT sheet is refused",
    PyoneerConfigError,
    lambda: field_from_map(write_level_one(
        "misnamed", DEFAULTS.replace('name="probe"', 'name="probe2"'))),
    "belong to tileset 'probe'", "attached them to 'probe2'")

expect_raises(
    "a relative reference with no document path is refused, not guessed",
    PyoneerConfigError,
    lambda: tileset_defaults(MapDocument.from_bytes(DEFAULTS.encode("utf-8"))),
    "no path to resolve it against", "pyoneer_collision")

# The vocabulary the format is spelled in. A property name is FILE FORMAT, so
# it is pinned as a literal rather than compared to itself.
expect("the declaration is a pyoneer_ property, so pytmx cannot refuse the map",
       runtime.DEFAULTS_PROPERTY, "pyoneer_collision")



# ---------------------------------------------------------------------------

print()
if failures:
    print(f"FAILED {len(failures)}:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("collision runtime OK")
