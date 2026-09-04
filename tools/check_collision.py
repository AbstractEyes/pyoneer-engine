"""Verify the collision data model and the .blitmask format.

Pure data over plain numbers, so every case runs headlessly on a bare
clone. That matters because none of the interesting failures here are
visible at a glance -- they are all a value that LOOKS reasonable:

  * "no opinion" collapsing into "open", which silently unblocks every
    cell an upper layer did not happen to paint
  * a star being treated as no-data, which lets a tileset default leak
    back through an authored abstention
  * a flipped tile's mask not being mirrored, so the right half of a
    symmetrical room is walkable and the left half is not
  * NO_DATA (-1) run through the mirror arithmetic, which produces 31 --
    a plausible-looking mask outside the vocabulary entirely
  * a one-sided movement test: a wall you cannot walk out of but can
    walk into
  * a .blitmask row one cell short, shifting every later cell by one

Every fixture is built here. Nothing reads data/maps/starter.tmx: the author
paints in that file, and a check that pins what the map CONTAINS rather than
what the code DOES goes red for a repaint (law 4).
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import os
import sys
import tempfile

from scripts.core import collision_runtime as runtime
from editor.core.collision import (
    FLIP_DIAGONAL,
    FLIP_HORIZONTAL,
    FLIP_VERTICAL,
    NO_DATA,
    SUBCELL,
    companion_subcell,
    field_subcell,
    Blitmask,
    CollisionField,
    CollisionLayer,
    PyoneerBlitmaskError,
    Resolution,
    abstains,
    as_mapping,
    blitmask_from_companion,
    companion_gids,
    companion_reader,
    describe_opinion,
    describe_stack,
    blitmask_from_field,
    field_from_blitmask,
    gid_to_opinion,
    is_opinion,
    join_gid,
    opinion_to_gid,
    opinion_to_token,
    resolve,
    split_gid,
    tileset_reader,
    token_to_opinion,
    transform_mask,
    TilesetDefaults,
)
from editor.core.layers import (
    BLOCK_ALL,
    BLOCK_DOWN,
    BLOCK_LEFT,
    BLOCK_RIGHT,
    BLOCK_UP,
    PASS_ALL,
    STAR,
    gid_to_mask,
)

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<56} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception_type, fn):
    try:
        fn()
    except exception_type:
        print(f"  ok   {label:<56} raised {exception_type.__name__}")
        return
    except Exception as other:                      # noqa: BLE001
        print(f"  FAIL {label:<56} raised {type(other).__name__}, "
              f"wanted {exception_type.__name__}")
        failures.append(label)
        return
    print(f"  FAIL {label:<56} did not raise {exception_type.__name__}")
    failures.append(label)


FIRST = 1793            # a companion tileset's firstgid; any number would do


def reader(cells: dict[tuple[int, int], int]):
    """A gid reader over a sparse fixture, exactly like paint's."""
    return lambda x, y: cells.get((x, y), 0)


# --------------------------------------------------------------------------
print("no opinion is a value, and it is not 'open'")
# --------------------------------------------------------------------------
expect("NO_DATA is not PASS_ALL", NO_DATA == PASS_ALL, False)
expect("NO_DATA is not any mask in the vocabulary",
       NO_DATA in range(0, STAR + 1), False)
expect("but it IS an opinion", is_opinion(NO_DATA), True)
expect("every mask is an opinion",
       all(is_opinion(m) for m in range(0, STAR + 1)), True)
expect("nonsense is not", [is_opinion(v) for v in (-2, STAR + 1, 31, 99)],
       [False, False, False, False])
expect("and the two describe themselves differently",
       (describe_opinion(NO_DATA), describe_opinion(PASS_ALL)),
       ("no opinion", "open"))
expect("a star describes itself as deferral, not as open",
       describe_opinion(STAR).startswith("star"), True)

# --------------------------------------------------------------------------
print()
print("gid <-> opinion, beside the pinned gid <-> mask rather than over it")
# --------------------------------------------------------------------------
# The distinction this whole model rests on: layers.gid_to_mask must keep
# saying an empty cell is open (tools/check_editor.py pins it), while the
# sibling here says nobody spoke. Both are correct answers to different
# questions and both have to remain available.
expect("the pinned reading of an empty cell is unchanged",
       gid_to_mask(0, FIRST), PASS_ALL)
expect("the sibling reads the same cell as silence",
       gid_to_opinion(0, FIRST), NO_DATA)
expect("an authored open cell is NOT silence",
       gid_to_opinion(FIRST, FIRST), PASS_ALL)
expect("every mask round-trips through a gid",
       [gid_to_opinion(opinion_to_gid(m, FIRST), FIRST)
        for m in range(0, STAR + 1)], list(range(0, STAR + 1)))
expect("NO_DATA round-trips through the empty cell",
       gid_to_opinion(opinion_to_gid(NO_DATA, FIRST), FIRST), NO_DATA)
expect("NO_DATA writes gid 0, not a tile", opinion_to_gid(NO_DATA, FIRST), 0)
expect("star writes the last gid of the mask block",
       opinion_to_gid(STAR, FIRST), FIRST + STAR)
expect("a gid from some other tileset is silence, not 'open'",
       gid_to_opinion(65, FIRST), NO_DATA)
expect("and so is one just past the mask block",
       gid_to_opinion(FIRST + STAR + 1, FIRST), NO_DATA)
expect("a negative gid is silence", gid_to_opinion(-5, FIRST), NO_DATA)
expect_raises("writing a mask outside the vocabulary raises", ValueError,
              lambda: opinion_to_gid(STAR + 1, FIRST))

# --------------------------------------------------------------------------
print()
print("flip flags are stripped before arithmetic and applied to the mask")
# --------------------------------------------------------------------------
flipped = join_gid(FIRST + BLOCK_LEFT, FLIP_HORIZONTAL)
expect("a flipped gid splits back into bare and flags",
       split_gid(flipped), (FIRST + BLOCK_LEFT, FLIP_HORIZONTAL))
expect("the bare gid survives the flags", split_gid(flipped)[0],
       FIRST + BLOCK_LEFT)
expect("a left wall mirrored horizontally blocks from the right",
       gid_to_opinion(flipped, FIRST), BLOCK_RIGHT)
expect("mirroring is symmetric",
       transform_mask(BLOCK_RIGHT, FLIP_HORIZONTAL), BLOCK_LEFT)
expect("a vertical flip swaps up and down",
       (transform_mask(BLOCK_UP, FLIP_VERTICAL),
        transform_mask(BLOCK_DOWN, FLIP_VERTICAL)), (BLOCK_DOWN, BLOCK_UP))
expect("the diagonal flip transposes: up becomes left",
       transform_mask(BLOCK_UP, FLIP_DIAGONAL), BLOCK_LEFT)
expect("and down becomes right",
       transform_mask(BLOCK_DOWN, FLIP_DIAGONAL), BLOCK_RIGHT)
expect("a fully blocked tile is blocked whichever way it is turned",
       [transform_mask(BLOCK_ALL, f) for f in
        (0, FLIP_HORIZONTAL, FLIP_VERTICAL, FLIP_DIAGONAL,
         FLIP_HORIZONTAL | FLIP_VERTICAL)], [BLOCK_ALL] * 5)
expect("no flags is the identity",
       [transform_mask(m, 0) for m in range(0, STAR + 1)],
       list(range(0, STAR + 1)))
expect("a star has no direction to mirror",
       transform_mask(STAR, FLIP_HORIZONTAL | FLIP_DIAGONAL), STAR)
# -1 through the bit arithmetic yields STAR|BLOCK_ALL = 31, which is outside
# the vocabulary and would be accepted by anything that only checks bounds
# loosely. Found by the field's own validator, kept as a regression.
expect("mirroring silence stays silence, and does not become 31",
       [transform_mask(NO_DATA, f) for f in
        (0, FLIP_HORIZONTAL, FLIP_VERTICAL, FLIP_DIAGONAL)], [NO_DATA] * 4)

# --------------------------------------------------------------------------
print()
print("level one: a tileset says what its tiles mean, wherever stamped")
# --------------------------------------------------------------------------
# A 2x2 tileset: open floor, a wall, a one-way ledge, and one tile nobody
# has authored yet.
defaults = TilesetDefaults(
    first_gid=FIRST, columns=2, rows=2, name="TestA",
    opinions=(PASS_ALL, BLOCK_ALL, BLOCK_UP, NO_DATA))
expect("it knows its own size", (defaults.tile_count, defaults.last_gid),
       (4, FIRST + 3))
expect("it owns its gids and not the neighbours'",
       [defaults.holds(g) for g in (FIRST - 1, FIRST, FIRST + 3, FIRST + 4)],
       [False, True, True, False])
expect("a gid maps to a local tile id", defaults.local_id(FIRST + 2), 2)
expect("a foreign gid has no local id", defaults.local_id(99), -1)
expect("the wall tile means blocked", defaults.opinion_for_gid(FIRST + 1),
       BLOCK_ALL)
expect("the floor tile means explicitly open",
       defaults.opinion_for_gid(FIRST), PASS_ALL)
expect("the unauthored tile means silence",
       defaults.opinion_for_gid(FIRST + 3), NO_DATA)
expect("a foreign gid means silence", defaults.opinion_for_gid(4242), NO_DATA)
expect("a flipped ledge blocks from the other side",
       defaults.opinion_for_gid(join_gid(FIRST + 2, FLIP_VERTICAL)),
       BLOCK_DOWN)
expect("editing a tile returns a new table, leaving the old one alone",
       (defaults.with_local(0, BLOCK_ALL).opinion_for_local(0),
        defaults.opinion_for_local(0)), (BLOCK_ALL, PASS_ALL))
expect_raises("a wrong-sized opinion list is refused", ValueError,
              lambda: TilesetDefaults(FIRST, 2, 2, (0, 1, 2)))
expect_raises("an out-of-vocabulary opinion is refused", ValueError,
              lambda: TilesetDefaults(FIRST, 1, 2, (0, 99)))

art = reader({(0, 0): FIRST, (1, 0): FIRST + 1, (2, 0): FIRST + 3,
              (3, 0): 9999})
level_one = tileset_reader(art, [defaults])
expect("reading the ART layer gives the tile's own mask",
       [level_one(x, 0) for x in range(5)],
       [PASS_ALL, BLOCK_ALL, NO_DATA, NO_DATA, NO_DATA])

# --------------------------------------------------------------------------
print()
print("three levels, consulted strongest first")
# --------------------------------------------------------------------------
# Every cell of row 0 is authored by a different combination of levels, so
# one layer proves the whole precedence order.
companion = reader({
    (1, 0): opinion_to_gid(BLOCK_DOWN, FIRST),      # beats the tileset
    (2, 0): opinion_to_gid(STAR, FIRST),            # suppresses the tileset
})
layer = CollisionLayer(
    name="Floor",
    defaults=tileset_reader(reader({(0, 0): FIRST + 1, (1, 0): FIRST + 1,
                                    (2, 0): FIRST + 1, (3, 0): FIRST + 1}),
                            [defaults]),
    companion=companion_reader(companion, FIRST))
layer.set_override(3, 0, PASS_ALL)                  # beats everything

expect("with nothing above it, the tileset default stands",
       layer.opinion_at(0, 0), BLOCK_ALL)
expect("a companion cell beats the tileset default",
       layer.opinion_at(1, 0), BLOCK_DOWN)
expect("an override beats the companion and the tileset",
       layer.opinion_at(3, 0), PASS_ALL)
expect("a cell nobody authored at any level is silence",
       layer.opinion_at(9, 9), NO_DATA)
# The star case is the one that distinguishes the two abstentions. An
# authored star SUPPRESSES the tileset default under it -- if star behaved
# like no-data, the wall below would leak straight back through.
expect("an authored star stops the walk instead of falling through",
       layer.opinion_at(2, 0), STAR)
expect("which is not what the tileset under it says",
       defaults.opinion_for_gid(FIRST + 1), BLOCK_ALL)

expect("an override of NO_DATA removes the entry rather than storing it",
       (layer.set_override(3, 0, NO_DATA), (3, 0) in layer.overrides)[1],
       False)
expect("and the level below is heard again",
       layer.opinion_at(3, 0), BLOCK_ALL)
expect_raises("an override outside the vocabulary is refused", ValueError,
              lambda: layer.set_override(0, 0, 77))
expect("a layer with no levels at all answers silence everywhere",
       CollisionLayer("bare").opinion_at(0, 0), NO_DATA)

# --------------------------------------------------------------------------
print()
print("the layer stack: star and silence defer, everything else decides")
# --------------------------------------------------------------------------
expect("both abstentions abstain",
       (abstains(NO_DATA), abstains(STAR)), (True, True))
expect("an authored open cell does NOT abstain", abstains(PASS_ALL), False)
expect("nor does any block", abstains(BLOCK_ALL), False)

top = CollisionLayer("top")
middle = CollisionLayer("middle")
ground = CollisionLayer("ground")
stack = [top, middle, ground]                       # TOPMOST FIRST

ground.set_override(0, 0, BLOCK_ALL)
top.set_override(1, 0, BLOCK_LEFT)
ground.set_override(1, 0, BLOCK_ALL)
top.set_override(2, 0, STAR)
ground.set_override(2, 0, BLOCK_ALL)
top.set_override(3, 0, PASS_ALL)
ground.set_override(3, 0, BLOCK_ALL)

expect("with only the ground speaking, the ground decides",
       resolve(stack, 0, 0).mask, BLOCK_ALL)
expect("and it is recorded as the decider",
       resolve(stack, 0, 0).layer, 2)
expect("the top layer wins when it has an opinion",
       resolve(stack, 1, 0).mask, BLOCK_LEFT)
expect("a star on top hands the question down",
       (resolve(stack, 2, 0).mask, resolve(stack, 2, 0).layer),
       (BLOCK_ALL, 2))
# This is the failure the whole NO_DATA distinction exists to prevent: an
# authored PASS_ALL on top MUST punch through the wall below, while an
# unpainted cell on top must not.
expect("an authored open cell on top punches through the wall below",
       resolve(stack, 3, 0).mask, PASS_ALL)
expect("but an unpainted cell on top does not",
       resolve(stack, 0, 0).mask, BLOCK_ALL)
expect("nobody speaking leaves it undecided",
       resolve(stack, 50, 50).decided, False)
expect("and undecided falls back to open by default",
       resolve(stack, 50, 50).mask, PASS_ALL)
expect("with no deciding layer to name", resolve(stack, 50, 50).layer, -1)
expect("a caller who wants unauthored to mean solid says so",
       resolve(stack, 50, 50, undecided=BLOCK_ALL).mask, BLOCK_ALL)
expect("which is still undecided, not a decision",
       resolve(stack, 50, 50, undecided=BLOCK_ALL).decided, False)
expect("a decided cell reports decided", resolve(stack, 0, 0).decided, True)

# Ordering is load-bearing and invisible if it flips: a tmx layer list is
# bottom-first, so a caller who forgets to reverse it gets a plausible,
# wrong answer everywhere two layers disagree.
expect("reversing the stack reverses who wins",
       resolve(list(reversed(stack)), 3, 0).mask, BLOCK_ALL)

expect("a lower layer disagreeing with the decider is flagged",
       resolve(stack, 3, 0).conflicted, True)
expect("agreement is not a conflict",
       resolve([top, ground], 0, 0).conflicted, False)
top.set_override(4, 0, BLOCK_UP)
middle.set_override(4, 0, BLOCK_UP)
expect("two layers saying the same thing is not a conflict",
       resolve(stack, 4, 0).conflicted, False)
expect("Resolution defaults to undecided and unconflicted",
       (Resolution(PASS_ALL).decided, Resolution(PASS_ALL).conflicted),
       (False, False))
expect("a stack description names every layer and the outcome",
       len(describe_stack(stack, 3, 0).splitlines()), 4)

# --------------------------------------------------------------------------
print()
print("baking: where 'no opinion' stops existing, on purpose")
# --------------------------------------------------------------------------
field = CollisionField.bake(stack, 8, 4)
expect("the field is the size it was asked for",
       (field.width, field.height), (8, 4))
expect("one flat byte per cell", len(field.masks()), 32)
expect("a decided cell keeps its mask", field.mask_at(0, 0), BLOCK_ALL)
expect("an undecided cell took the fallback", field.mask_at(6, 3), PASS_ALL)
expect("baking with a different fallback changes only those cells",
       CollisionField.bake(stack, 8, 4, undecided=BLOCK_ALL).mask_at(6, 3),
       BLOCK_ALL)
expect("while the decided cell is untouched by the fallback",
       CollisionField.bake(stack, 8, 4, undecided=BLOCK_ALL).mask_at(3, 0),
       PASS_ALL)
expect("no NO_DATA survives a bake",
       any(m < 0 for m in field.masks()), False)
expect("nor does a star -- it abstained its way off the stack",
       STAR in field.counts(), False)
expect_raises("a fallback outside the vocabulary is refused", ValueError,
              lambda: CollisionField.bake(stack, 4, 4, undecided=99))
expect_raises("a field with the wrong number of masks is refused", ValueError,
              lambda: CollisionField(4, 4, bytes(15)))
expect_raises("a zero-sized field is refused", ValueError,
              lambda: CollisionField(0, 4, b""))

# --------------------------------------------------------------------------
print()
print("the runtime lookup, including the two edges everyone gets wrong")
# --------------------------------------------------------------------------
#  . . . .    a solid block at (1,1), and at (2,1) a cell whose TOP EDGE is
#  . # ^ .    closed -- BLOCK_UP, which governs both crossings of that edge
#  . . . .
walls = CollisionField(4, 3, bytes([
    0, 0, 0, 0,
    0, BLOCK_ALL, BLOCK_UP, 0,
    0, 0, 0, 0,
]), tile_width=16, tile_height=16)

expect("a mask reads back where it was put", walls.mask_at(1, 1), BLOCK_ALL)
expect("an empty cell reads as open", walls.mask_at(0, 0), PASS_ALL)
expect("outside the map is solid by default", walls.mask_at(-1, 0), BLOCK_ALL)
expect("on all four sides",
       [walls.mask_at(x, y) for x, y in ((-1, 0), (4, 0), (0, -1), (0, 3))],
       [BLOCK_ALL] * 4)
expect("a caller who wants an open border says so",
       CollisionField(4, 3, bytes(12), outside=PASS_ALL).mask_at(-1, 0),
       PASS_ALL)
expect("containment is exact",
       [walls.contains(x, y) for x, y in ((0, 0), (3, 2), (4, 2), (0, 3))],
       [True, True, False, False])

expect("the solid cell refuses to be left in every direction",
       [walls.blocks(1, 1, d) for d in
        (BLOCK_UP, BLOCK_DOWN, BLOCK_LEFT, BLOCK_RIGHT)], [True] * 4)
expect("the closed edge refuses only upward, one-sidedly",
       [walls.blocks(2, 1, d) for d in
        (BLOCK_UP, BLOCK_DOWN, BLOCK_LEFT, BLOCK_RIGHT)],
       [True, False, False, False])
expect_raises("blocks() rejects anything but a direction bit", ValueError,
              lambda: walls.blocks(0, 0, STAR))

# The one-sided-collision regression. Walking INTO the solid cell has to
# fail even though the cell being left says nothing at all.
expect("you cannot walk into a wall from the left",
       walls.can_move(0, 1, BLOCK_RIGHT), False)
expect("nor from above", walls.can_move(1, 0, BLOCK_DOWN), False)
expect("nor from below", walls.can_move(1, 2, BLOCK_UP), False)
expect("open ground moves freely", walls.can_move(0, 0, BLOCK_RIGHT), True)
# One bit governs BOTH crossings of the edge it names, exactly as RPG
# Maker's canPass does. So a direction bit is symmetric, and a one-way
# platform is not expressible in this vocabulary -- pinned here because it
# is the first thing anyone will try to build on top of it.
expect("a closed top edge cannot be left upward",
       walls.can_move(2, 1, BLOCK_UP), False)
expect("and cannot be entered from above either -- blocking is symmetric",
       walls.can_move(2, 0, BLOCK_DOWN), False)
expect("its bottom and right edges are still open",
       [walls.can_move(2, 1, d) for d in (BLOCK_DOWN, BLOCK_RIGHT)],
       [True, True])
expect("while going left runs into the wall next door, not into its own bit",
       walls.can_move(2, 1, BLOCK_LEFT), False)
expect("walking off the map edge is refused",
       walls.can_move(0, 0, BLOCK_LEFT), False)
expect_raises("can_move rejects anything but a direction bit", ValueError,
              lambda: walls.can_move(0, 0, PASS_ALL))

# The same one-sided edge, turned ninety degrees, and it is not decoration.
# Every assertion above uses either a cell with ALL FOUR bits set or a
# VERTICAL edge, so a destination veto that looked up the wrong bit
# horizontally -- an OPPOSITE table that stops mirroring left into right --
# answers every one of them correctly and lets an author walk in through the
# side of a wall. Both mirrors are taken, so neither direction of the pair is
# the one that happens to be right by accident.
#  . | .    (1,0)'s LEFT edge is closed
one_sided = CollisionField(3, 1, bytes([0, BLOCK_LEFT, 0]))
expect("a closed left edge cannot be crossed from the left",
       one_sided.can_move(0, 0, BLOCK_RIGHT), False)
expect("nor left out of the cell that owns it",
       one_sided.can_move(1, 0, BLOCK_LEFT), False)
expect("while that cell's right edge is open both ways",
       [one_sided.can_move(1, 0, BLOCK_RIGHT), one_sided.can_move(2, 0, BLOCK_LEFT)],
       [True, True])
#  . | .    (1,0)'s RIGHT edge is closed
other_side = CollisionField(3, 1, bytes([0, BLOCK_RIGHT, 0]))
expect("a closed right edge cannot be crossed from the right",
       other_side.can_move(2, 0, BLOCK_LEFT), False)
expect("nor right out of the cell that owns it",
       other_side.can_move(1, 0, BLOCK_RIGHT), False)
expect("while that cell's left edge is open both ways",
       [other_side.can_move(1, 0, BLOCK_LEFT), other_side.can_move(0, 0, BLOCK_RIGHT)],
       [True, True])

expect("pixels floor into cells", walls.cell_of(31, 17), (1, 1))
expect("the cell's first pixel is inside it", walls.cell_of(16, 16), (1, 1))
expect("its last pixel too", walls.cell_of(31.9, 31.9), (1, 1))
# int() truncates toward zero, so -1 would land in cell 0 and an entity a
# pixel off the left edge would read as being inside the map.
expect("a negative pixel floors outside, it does not truncate to 0",
       walls.cell_of(-1, -1), (-1, -1))
expect("so a pixel off the edge reads as the outside mask",
       walls.mask_at_pixel(-1, 0), BLOCK_ALL)
expect("and a pixel inside reads the cell under it",
       walls.mask_at_pixel(24, 24), BLOCK_ALL)
# (2,1) and (1,2) hold DIFFERENT masks, which is what makes this able to
# fail: every other pixel probe here lands on the diagonal or outside the
# field, where mask_at(x, y) and mask_at(y, x) answer the same thing, so an
# x/y transpose inside mask_at_pixel passed all of them.
expect("...and it is x then y, not y then x",
       (walls.mask_at_pixel(40, 24), walls.mask_at_pixel(24, 40)),
       (BLOCK_UP, PASS_ALL))
expect("counts add up to the cell total",
       sum(walls.counts().values()), 12)
expect("two fields with the same cells are equal",
       CollisionField(4, 3, walls.masks()) == walls, True)
expect("a different border makes them different",
       CollisionField(4, 3, walls.masks(), outside=PASS_ALL) == walls, False)

# --------------------------------------------------------------------------
print()
print(".blitmask: one char per cell, and '.' is not '0'")
# --------------------------------------------------------------------------
expect("silence and open are different characters",
       (opinion_to_token(NO_DATA), opinion_to_token(PASS_ALL)), (".", "0"))
expect("a star is a star", opinion_to_token(STAR), "*")
expect("fully blocked is the last hex digit",
       opinion_to_token(BLOCK_ALL), "f")
expect("every opinion has exactly one token",
       len({opinion_to_token(v) for v in [NO_DATA] + list(range(STAR + 1))}),
       18)
expect("tokens round-trip",
       [token_to_opinion(opinion_to_token(v))
        for v in [NO_DATA] + list(range(STAR + 1))],
       [NO_DATA] + list(range(STAR + 1)))
expect("uppercase hex is accepted on read", token_to_opinion("F"), BLOCK_ALL)
expect_raises("an unknown character is refused", PyoneerBlitmaskError,
              lambda: token_to_opinion("z"))
expect_raises("an opinion with no token raises rather than substituting",
              PyoneerBlitmaskError, lambda: opinion_to_token(31))

grid = Blitmask.from_rows([
    [NO_DATA, PASS_ALL, BLOCK_ALL, STAR],
    [BLOCK_DOWN, BLOCK_LEFT, BLOCK_RIGHT, BLOCK_UP],
    [NO_DATA, NO_DATA, NO_DATA, NO_DATA],
], name="Room", kind="companion")
expect("the grid measures itself", (grid.width, grid.height), (4, 3))
expect("a row renders as it reads",
       grid.render().splitlines()[-3], ".0f*")
expect("and the direction row is hex",
       grid.render().splitlines()[-2], "1248")
expect("the header carries the magic and version",
       grid.render().splitlines()[0], "blitmask 1")
expect("and the size", grid.render().splitlines()[1], "size 4 3")
expect("metadata keeps its order",
       grid.render().splitlines()[2:4], ["name Room", "kind companion"])
expect("the file ends in a newline", grid.render().endswith("\n"), True)
expect("a cell reads back", grid.at(2, 0), BLOCK_ALL)
expect("outside the grid is silence, not an exception", grid.at(99, 99),
       NO_DATA)
expect("counts distinguish silence from open",
       (grid.counts()[NO_DATA], grid.counts()[PASS_ALL]), (5, 1))
expect("editing returns a new grid and leaves the old one alone",
       (grid.with_cell(0, 0, BLOCK_ALL).at(0, 0), grid.at(0, 0)),
       (BLOCK_ALL, NO_DATA))
expect_raises("editing outside the grid is refused", PyoneerBlitmaskError,
              lambda: grid.with_cell(99, 0, PASS_ALL))
expect_raises("a ragged row list is refused", PyoneerBlitmaskError,
              lambda: Blitmask.from_rows([[0, 0], [0]]))
expect_raises("a grid whose cell count disagrees with its size is refused",
              PyoneerBlitmaskError, lambda: Blitmask(4, 3, (0, 0)))
expect_raises("a structural key cannot be metadata", PyoneerBlitmaskError,
              lambda: Blitmask(1, 1, (0,), {"size": "nope"}))
expect_raises("a metadata key with a space is refused", PyoneerBlitmaskError,
              lambda: Blitmask(1, 1, (0,), {"two words": "x"}))
expect("a blank grid is silence everywhere, not open everywhere",
       set(Blitmask.blank(3, 3).opinions), {NO_DATA})

# --------------------------------------------------------------------------
print()
print("round trip through a real file on disk")
# --------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as directory:
    path = os.path.join(directory, "room.blitmask")
    grid.save(path)
    loaded = Blitmask.load(path)
    # Compared as a bool: Blitmask.__str__ renders the whole file, which is
    # useful at a debugger and unreadable in a one-line got/want.
    expect("the model survives the trip", loaded == grid, True)
    expect("including every cell", loaded.opinions, grid.opinions)
    expect("and the metadata", loaded.meta, grid.meta)

    first_bytes = open(path, "rb").read()
    loaded.save(path)
    expect("save/load/save is byte-identical",
           open(path, "rb").read(), first_bytes)
    expect("and carries no carriage returns on any platform",
           b"\r" in first_bytes, False)

    # A hand-edited file: comments, blank lines and stray indentation are
    # for humans and must not change what is read.
    hand = os.path.join(directory, "hand.blitmask")
    with open(hand, "w", encoding="utf-8", newline="") as handle:
        handle.write("# a room\n\nblitmask 1\nsize 4 3\nname Room\n"
                     "kind companion\n\n  .0f*\n1248\n# the floor\n....\n")
    expect("comments, blanks and indentation do not change the model",
           Blitmask.load(hand) == grid, True)

    nested = os.path.join(directory, "deep", "nested.blitmask")
    grid.save(nested)
    expect("saving creates the directory it was pointed at",
           os.path.isfile(nested), True)

    bad = os.path.join(directory, "bad.blitmask")
    with open(bad, "w", encoding="utf-8", newline="") as handle:
        handle.write("blitmask 1\nsize 4 3\n.0f*\n124\n....\n")
    expect_raises("a short row is refused rather than silently shifting",
                  PyoneerBlitmaskError, lambda: Blitmask.load(bad))
    try:
        Blitmask.load(bad)
    except PyoneerBlitmaskError as error:
        expect("and it names the offending line", error.line, 4)
        expect("and the file", error.path, bad)

# --------------------------------------------------------------------------
print()
print("malformed files are refused, with the line that is wrong")
# --------------------------------------------------------------------------


def parse_fails(label, text, line=None):
    try:
        Blitmask.parse(text)
    except PyoneerBlitmaskError as error:
        if line is not None and error.line != line:
            print(f"  FAIL {label:<56} line={error.line} want={line}")
            failures.append(label)
            return
        print(f"  ok   {label:<56} refused: {error.message[:44]}")
        return
    print(f"  FAIL {label:<56} was accepted")
    failures.append(label)


parse_fails("an empty file", "")
parse_fails("a file of nothing but comments", "# hello\n\n# world\n")
parse_fails("the wrong magic", "bitmask 1\nsize 1 1\n0\n", line=1)
parse_fails("a missing version", "blitmask\nsize 1 1\n0\n", line=1)
parse_fails("a non-numeric version", "blitmask x\nsize 1 1\n0\n", line=1)
parse_fails("a future version", "blitmask 2\nsize 1 1\n0\n", line=1)
parse_fails("no size line", "blitmask 1\nname x\n")
parse_fails("a one-number size", "blitmask 1\nsize 4\n0000\n", line=2)
parse_fails("a non-numeric size", "blitmask 1\nsize 4 x\n0000\n", line=2)
parse_fails("a zero size", "blitmask 1\nsize 0 0\n", line=2)
parse_fails("a negative size", "blitmask 1\nsize -4 3\n", line=2)
parse_fails("too few rows", "blitmask 1\nsize 2 3\n00\n00\n")
parse_fails("too many rows", "blitmask 1\nsize 2 1\n00\n00\n", line=4)
parse_fails("a long row", "blitmask 1\nsize 2 1\n000\n", line=3)
parse_fails("an unknown cell character", "blitmask 1\nsize 2 1\n0z\n", line=3)
parse_fails("a duplicated metadata key",
            "blitmask 1\nsize 1 1\nname a\nname b\n0\n", line=4)
parse_fails("a duplicated size line",
            "blitmask 1\nsize 1 1\nsize 2 2\n0\n", line=3)
expect("a legal file with no metadata at all is fine",
       Blitmask.parse("blitmask 1\nsize 2 1\n.*\n").opinions, (NO_DATA, STAR))

# --------------------------------------------------------------------------
print()
print("the format is the same grid the tmx holds, in the other spelling")
# --------------------------------------------------------------------------
companion_cells = {
    (0, 0): opinion_to_gid(BLOCK_ALL, FIRST),
    (1, 0): opinion_to_gid(PASS_ALL, FIRST),
    (2, 0): opinion_to_gid(STAR, FIRST),
}
exported = blitmask_from_companion(reader(companion_cells), 4, 2, FIRST,
                                   kind="companion")
expect("an exported companion keeps every authored cell",
       exported.render().splitlines()[-2], "f0*.")
expect("and its unpainted cells stay silent, not open",
       exported.row(1), (NO_DATA,) * 4)
expect("re-importing reproduces the gids exactly",
       {(x, y): g for x, y, g in companion_gids(exported, FIRST)
        if g != 0}, companion_cells)
expect("and clears the cells the file calls silent",
       [g for x, y, g in companion_gids(exported, FIRST) if y == 1],
       [0, 0, 0, 0])
expect("the sparse mapping holds only what was said",
       as_mapping(exported), {(0, 0): BLOCK_ALL, (1, 0): PASS_ALL,
                              (2, 0): STAR})

# A blitmask is usable directly as a level of a layer.
patched = CollisionLayer("patched", companion=exported.reader())
expect("a blitmask can BE a level", patched.opinion_at(0, 0), BLOCK_ALL)
expect("and its silence still falls through",
       patched.opinion_at(3, 1), NO_DATA)

# --------------------------------------------------------------------------
print()
print("field <-> file, and what the trip into a field costs")
# --------------------------------------------------------------------------
sparse = Blitmask.from_rows([[NO_DATA, PASS_ALL], [BLOCK_ALL, STAR]])
baked = field_from_blitmask(sparse)
expect("an authored open cell stays open", baked.mask_at(1, 0), PASS_ALL)
expect("a silent cell becomes the fallback", baked.mask_at(0, 0), PASS_ALL)
expect("a caller can make silence mean solid instead",
       field_from_blitmask(sparse, undecided=BLOCK_ALL).mask_at(0, 0),
       BLOCK_ALL)
expect("which does not touch the authored open cell",
       field_from_blitmask(sparse, undecided=BLOCK_ALL).mask_at(1, 0),
       PASS_ALL)
expect("the trip into a field is lossy, and says so by losing the dots",
       blitmask_from_field(baked).render().splitlines()[-2], "00")
expect("but a field's own round trip is exact",
       field_from_blitmask(blitmask_from_field(baked)), baked)
expect("a whole stack bakes, writes, and reloads to the same field",
       field_from_blitmask(
           blitmask_from_field(CollisionField.bake(stack, 8, 4))),
       CollisionField.bake(stack, 8, 4))

# --------------------------------------------------------------------------
print()
print("a companion may be finer than the map, and level ONE may not")
# --------------------------------------------------------------------------
# The editor authors the companion (level two) and the sub-cell property, so
# both names have to reach `editor/` from the one module that defines them.
# Identity, not equality, for section 8 of check_collision_runtime's reason:
# a pasted copy is equal on the day it is pasted.
expect("the sub-cell property name is the engine's own object",
       (SUBCELL is runtime.SUBCELL,
        companion_subcell is runtime.companion_subcell,
        field_subcell is runtime.field_subcell), (True, True, True))
expect("and it is prefixed, so pytmx cannot refuse the map over it",
       SUBCELL, "pyoneer_subcell")

# The scale, through the editor's own re-export. A 4x field asking a 1x
# companion has to land on the layer cell that COVERS it -- the overlay is
# what an author reads to find out where a wall is, so a mis-scaled read
# draws walls in places nobody painted.
coarse_cells = {(0, 0): FIRST + BLOCK_ALL, (1, 0): FIRST + BLOCK_DOWN}
scaled = companion_reader(reader(coarse_cells), FIRST, scale=4)
unscaled = companion_reader(reader(coarse_cells), FIRST)
expect("four field cells across read one layer cell",
       [scaled(x, 0) for x in range(4)], [BLOCK_ALL] * 4)
expect("and the fifth reads the next one",
       (scaled(4, 0), scaled(7, 0)), (BLOCK_DOWN, BLOCK_DOWN))
expect("...while the unscaled reader over the same cells does not",
       (unscaled(3, 0), unscaled(4, 0)), (NO_DATA, NO_DATA))
expect("a scaled read is still bounded by the layer, not extended past it",
       (scaled(8, 0), scaled(0, 4)), (NO_DATA, NO_DATA))

# LEVEL ONE STAYS PER-TILE, and this is the assertion that says so out loud.
# A tileset default is addressed by GID, and a gid is stamped on the ART
# layer, which is at map resolution by definition -- there is no sub-tile art
# gid to look up. Sixteen opinions per tile would also break the .blitmask
# invariant that the file has the shape of the thing it describes, and
# `opinion_to_token` is written to make any widening of the opinion domain
# loud rather than free.
brick = TilesetDefaults(FIRST, 2, 2, (BLOCK_ALL, NO_DATA, NO_DATA, NO_DATA))
expect("a tileset holds one opinion per TILE, not one per sub-cell",
       (brick.tile_count, len(brick.opinions)), (4, 4))
expect("so one stamped tile means one thing over its whole square",
       brick.opinion_for_gid(FIRST), BLOCK_ALL)
expect_raises("and widening the opinion domain is refused, not encoded",
              PyoneerBlitmaskError, lambda: opinion_to_token(STAR | BLOCK_ALL))

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
