"""Verify that the engine reads authored masks and refuses a blocked step.

Eight claims. Every one of them is something the code is otherwise free to
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

THE FIXTURE IS THIS FILE'S OWN
------------------------------
Everything is read from a .tmx written into a temp directory by `FIXTURE`
below. `data/maps/test.tmx` is repainted constantly and declares no
passability at all; a check that pinned map CONTENT would go red the next
time the author paints, while the code it guards worked perfectly. That has
cost this repository five red suites.

The fixture needs no art. Its tilesets point at PNGs that do not exist, which
both pytmx and MapDocument parse happily as long as no tile IMAGE is
resolved -- and none is, because a mask is a number.

WHAT SECTION 8 IS FOR
---------------------
`scripts/core/collision_runtime.py` is the ONLY definition of the mask
vocabulary, the layer stack, `resolve` and `CollisionField`;
`editor/core/layers.py` and `editor/core/collision.py` import it and
re-export what their own callers name. Section 8 used to be a DIFFERENTIAL
between two copies -- and a differential is only ever as complete as the copy
it guards, which is why that one missed `OPPOSITE`, `can_move`, `blocks` and
`mask_at_pixel` and let four mutations through. It asserts IDENTITY now: the
editor's names must BE these objects, and neither editor module may bind any
shared name in its own source. A re-pasted copy is equal on the day it is
pasted; it is never identical.

Section 8 also asserts the thing the collapse cannot fix by itself -- that
the editor's genre packs and `scripts/core/depth.MAP_DEPTH` rank a layer at
the same height. Those are two authored tables by design, and `resolve`
walks topmost first, so disagreeing about one layer means a different
deciding layer in the overlay than in the game.

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
    collision_first_gid,
    companion_pairs,
    describe_mask,
    describe_opinion,
    document_gid_reader,
    field_from_map,
    file_gid_reader,
    gid_to_mask,
    gid_to_opinion,
    join_gid,
    mask_to_gid,
    move_point,
    parsed_layer,
    resolve,
    split_gid,
    transform_mask,
)
from scripts.core.depth import MAP_DEPTH, resolve_layer_depth
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
# This was a DIFFERENTIAL -- two copies of the vocabulary, imported side by
# side and compared constant for constant and cell for cell. It caught
# nothing it was pointed at and missed `OPPOSITE`, `can_move`, `blocks` and
# `mask_at_pixel` entirely, which is the trouble with guarding a duplicate
# instead of removing it: the guard has to be as complete as the copy, and it
# never is.
#
# There is one implementation now. `editor/core/layers.py` and
# `editor/core/collision.py` import it from here, so the interesting question
# stopped being "do the two agree" and became "is there still only one" --
# which is an IDENTITY test, not a value test. A pasted-back copy of
# `OPPOSITE` is a different dict object with equal contents; `==` would sail
# straight past it and `is` cannot.
#
# What the collapse means for coverage, confirmed by re-running the mutations
# that escaped the differential: `blocks() -> return False` and an x/y
# transpose in `mask_at_pixel` now fail section 4 above AND
# `tools/check_collision.py`; an `OPPOSITE` that stops mirroring left/right
# fails `check_collision`'s one-sided-collision assertions; a `mask_to_gid`
# off by one fails `check_editor`. Three suites see one change because there
# is one thing to change.
print("\nthe editor imports this module rather than copying it")

try:
    from editor.core import collision as editor_collision
    from editor.core import genre as editor_genre
    from editor.core import layers as editor_layers
except Exception as exc:                                        # noqa: BLE001
    # A FAILURE, not a skip. All three modules are pure Python -- no Qt, no
    # pygame, nothing optional -- so an import error here is a broken editor.
    # Printing SKIP and carrying on deleted the only guard standing between
    # two copies of one vocabulary while this file still printed OK and
    # exited 0, which is the worst of the three possible outcomes.
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
        "opinion_to_gid", "resolve", "split_gid", "transform_mask")
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
                  "resolve", "Resolution", "CollisionLayer", "CollisionField"}
    expect("layers.py defines none of the shared vocabulary itself",
           sorted(module_level_bindings(editor_layers) & vocabulary), [])
    expect("nor does collision.py",
           sorted(module_level_bindings(editor_collision) & vocabulary), [])
    expect("...and this module defines all of it",
           sorted(vocabulary - module_level_bindings(runtime)), [])
    # canvas.py held a third copy of the tileset name and the companion
    # suffix, and hand-mirrored `collision_first_gid` and `companion_name`
    # beside them. Checked by source rather than by importing the canvas,
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
    # And the reverse direction, which is the one that used to be silent: a
    # name MAP_DEPTH ranks and no pack declares. It is not an error -- the
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

print()
if failures:
    print(f"FAILED {len(failures)}:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("collision runtime OK")
