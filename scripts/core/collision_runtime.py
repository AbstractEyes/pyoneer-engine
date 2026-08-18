"""Runtime collision: read the masks the editor authors, and refuse a step.

WHY THIS FILE EXISTS
--------------------
`editor/core/collision.py` has been able to author, resolve and store
passability for two commits, and `ce66ce5` put a mode switch, a brush and a
mask palette in front of it. Until this file, `grep -rn collision scripts/`
found only the English word: the engine could not read one mask the editor
could write. This is the read side and the movement gate -- the smallest
thing that makes an authored mask do something a player can feel.

ONE IMPLEMENTATION, AND WHY IT IS THIS SIDE OF THE FENCE
-------------------------------------------------------
The vocabulary and the resolution order below are NOT new. They are the ones
`editor/core/layers.py` and `editor/core/collision.py` used to define, moved
to the engine side because the dependency only runs one way: `editor/` may
import `scripts/`, never the reverse (`tools/check_editor.py` asserts it).
`scripts/core/layer_profile.py` set this precedent for the layer-capability
names and the reason is the same -- two hand-kept copies of "a set bit means
blocked, in the order down, left, right, up" drift, and the failure is silent
in the worst way: a map that walks differently in the editor's overlay than
in the game.

This module is now the ONLY definition of all of it. `editor/core/layers.py`
imports the mask vocabulary from here and `editor/core/collision.py` imports
the opinions, the layer stack, `resolve` and `CollisionField`; both re-export
what their own callers already import by name, so nothing above them had to
change. `editor/ui/canvas.py` imports `COLLISION_TILESET`,
`COMPANION_SUFFIX`, `collision_first_gid` and `companion_name` from here for
the same reason. There is no differential to run any more because there is
nothing to differ; `tools/check_collision_runtime.py` section 8 asserts
IDENTITY instead -- the editor's names must be these objects -- which is what
fails the day somebody pastes a second copy back.

`TilesetDefaults`, `tileset_reader`, `Blitmask` and the `.blitmask` text
format moved here too, later and for the opposite reason to the rest. The
argument for leaving them on the editor side was that the runtime never
opened a sidecar, which was true until `field_from_map` started reading
level one; at that point the choice was to move 250 lines or to write a
second parser for a format whose whole job is to be read the same way twice.
Law 2's corollary already priced the second option at 425 duplicate lines.
What stayed behind is only what an AUTHORING tool asks for -- the
conversions between a `Blitmask` and the two shapes the editor holds, and
`describe_stack`, which exists to fill a tooltip.

THE ENCODING, IN ONE PARAGRAPH
------------------------------
A mask is four bits in RPG Maker's order -- down 1, left 2, right 4, up 8 --
and a SET bit means BLOCKED. `STAR` (0x10) is not a direction: it is an
authored abstention meaning "ask the layer below". `NO_DATA` (-1) is the
different thing of nobody having written anything at all, and keeping the two
apart is what lets a stack of collision layers compose instead of the top one
blanking everything under it. A mask is stored as a gid in a companion tile
layer, relative to the firstgid of a tileset named `collision`, which is why
a mask stroke in the editor is an ordinary tile stroke with ordinary undo.

THE LEVELS
----------
Three, weakest first: tileset defaults, layer companion, per-cell override.
This module reads the bottom TWO. Level one is a `.blitmask` beside the map,
named by a tileset's `pyoneer_collision` property and loaded by
`tileset_defaults`; level two is a companion tile layer in the .tmx. Level
three -- the sparse per-cell override -- is still authored by nobody and
read from no file, so `CollisionLayer.overrides` stays the empty dict at
runtime and is written only by a caller holding the object.

WHY LEVEL ONE IS WORTH THE READ. A wall tile is a wall everywhere it is
stamped, and saying so per cell per layer is four hundred chances to miss
one. With a tileset default, stamping the tile IS authoring the collision;
the companion layer stops being how you say "this is a wall" and becomes
only how you say "not THIS one" -- a door left open, a hole in a fence, a
brick that is scenery on the background layer.

PRECEDENCE IS THE WHOLE FEATURE, and it is `CollisionLayer.opinion_at` that
carries it: override, then companion, then defaults, first one that is not
NO_DATA wins. A painted companion cell therefore OVERRIDES the tile default
rather than merging with it -- painting PASS_ALL over a tile whose default is
BLOCK_ALL gives PASS_ALL, not BLOCK_ALL, and not the union -- and a STAR
painted over a default suppresses it and asks the layer BELOW instead. Both
directions are asserted in `tools/check_collision_runtime.py`, because a
precedence rule proved in one direction is half an invariant and half is the
dominant failure shape in this tree.

`MapCanvas.collision_stack()` still builds its `CollisionLayer`s with
`companion=` alone, so the editor's OVERLAY does not yet show level one. That
is a gap in the overlay, not in the model: the two call the same `resolve`
over the same `CollisionLayer`, and the overlay starts agreeing the day it
passes `defaults=tileset_defaults(document)` in.

THE READ PATH, AND THE TWO pytmx TRAPS
--------------------------------------
Properties come from `MapDocument`, cells come from pytmx, and each source is
chosen because the other one is wrong for that job.

  * pytmx casts a custom property only when the file carries `type="int"`, so
    `pyoneer_passability` is safe but a hand-written `pyoneer_depth` arrives
    as the string `'50'`. `MapDocument` applies the same typing rules as the
    code that WRITES those properties, so read and write cannot drift.
    `map_loader.as_document` is reused rather than reimplemented.
  * pytmx RENUMBERS gids. `layer.data` holds pytmx's own internal numbering
    and `tiledgidmap` maps it back to the file's. Reading `layer.data`
    directly resolves masks against the wrong firstgid, which does not fail
    -- it silently answers "no opinion" for every painted cell.
  * `tiledgidmap` alone is still not enough, and this is the trap inside the
    trap: pytmx splits the three flip bits off a gid BEFORE registering it,
    so `tiledgidmap` gives back a gid with its flip flags stripped. A
    horizontally flipped wall would then block from the side it does not.
    `imagemap` is keyed `(file gid, flags)` and is the complete inverse;
    `gid_inverse` below rebuilds the flags from it and falls back to
    `tiledgidmap` for anything it cannot see.

Cells come from the PARSED map rather than from disk on purpose: the engine's
tmx is loaded once through `CoreAssetManager` and cached, and re-reading the
grid from the file would let collision disagree with the tiles actually being
drawn the moment the author saves in Tiled while the game is running.

SUB-CELL RESOLUTION -- WHAT `pyoneer_subcell` BUYS AND WHAT IT DOES NOT
-----------------------------------------------------------------------
A companion layer may be authored FINER than the map it belongs to. A
companion carrying `pyoneer_subcell="4"` is 4x the map's width and height,
each of its cells is a quarter-tile square, and each still holds one gid of
`firstgid + mask` -- the same seventeen tiles, the same nibble, the same
editor stroke, the same undo. The property is on the COMPANION layer, is an
int, and ABSENT MEANS 1: every map authored before this existed is already
correct under it, so this is the file format's default rather than a
fallback.

Almost nothing here changed to allow it, and that is the point. `CollisionField`
never knew what a "tile" was: it stores `tile_width`/`tile_height` and
`cell_of` floors a pixel by them, so a field built at 4px cells gates on 4px
boundaries with no new vocabulary. Measured on a 16x16 field of 4px cells:
`cell_of` puts 3.999 in cell 0 and 4.0 in cell 1, and `allowed_distance`
walking down from y=2.0 into a wall at sub-cell row 7 returns 25.9990234375 --
it stops on the 4px boundary at y=28, minus EDGE_INSET. What DID change is the
three things below, and the middle one is the one that bites:

  * `field_from_map` baked at the DOCUMENT's dimensions. A 4x companion had
    100% of its authored sub-cells discarded in silence -- measured, 256
    painted sub-cells in, 0 blocking cells out, no exception and no warning.
    It bakes at the FINEST declared resolution in the stack now, and a
    companion LARGER than its declaration allows raises rather than being
    truncated.
  * a stack may MIX resolutions, and reading a 1x layer at sub-cell
    coordinates does not lose it -- it RELOCATES it. Measured before the fix:
    a 1x wall on map row 7 answered at sub-cell row 7, which is 84 pixels up
    the map, a wall in the wrong place rather than a wall that vanished. So
    every companion is read through a `scale`, and `companion_reader` takes
    it. A cell of the field maps to `(x // scale, y // scale)` of the layer.
  * a companion may still be SMALLER than `subcell x` the map -- reads past
    its edge answer 0, which is NO_DATA, which is the right answer. Only
    LARGER raises, because larger is the case where authored data is dropped.

What this does NOT buy is slopes. A 4x4 nibble field DESCRIBES a 4px-granular
surface, and nothing in the movement code climbs one: driven through this gate
four ways, a body walks DOWN a staircase of sub-cells cleanly and freezes
against the first riser going up, because BLOCK_ALL sets BLOCK_LEFT and the
next column refuses entry. A slope needs a step-up in the movement behavior --
retry a refused horizontal move lifted by N sub-cells, then drop -- which is a
different change in a different file. The honest promise of this section is
4px collision granularity.

THE GATE
--------
`allowed_distance` is a tile-grid test and nothing more. One anchor point per
entity, one axis per call, both cells get a veto (leaving downward is blocked
by this cell's DOWN bit or by the cell below's UP bit -- checking only the
source is the classic wall you cannot walk out of but can walk into).

Known and deliberate limits, so nobody discovers them as bugs:

  * one point, not a box. An entity wider than a tile can have its shoulders
    inside a wall. `collision_offset` on `GameEntity` moves the point; making
    it a box is a different feature and a different check.
  * blocking is symmetric. One bit governs both crossings of an edge, so a
    one-way platform cannot be expressed. That is a vocabulary change, not
    something to fake here.
  * an anchor OUTSIDE the field is ungated. `CollisionField.outside` defaults
    to BLOCK_ALL, which stops an entity walking out of the world -- but read
    from outside it would also freeze an entity that spawned there, forever,
    with no way back. The border is enforced on the way out, not on the way
    in.

COST
----
Measured on this machine against a 100x100 map -- the shipped map's size --
with two companion layers, seven runs each:

    field_from_map      23.0-28.5 ms, median 27.2, once at map load
    of which the bake   19.7-22.2 ms
    mask_at             0.30 us
    can_move            0.78 us
    allowed_distance    1.09 us
    move_direction      2.10 us ungated, 5.32 us gated
    storage             10,000 bytes flat, one per cell

So the gate adds ~3.2 us per direction per entity per frame -- nothing for
one player, worth knowing before gating three hundred entities -- and the
bake is a real 23 ms against a ~350 ms boot. That is the price of answering
every later query with one index into a `bytes`; resolving per query instead
would cost more than that on every full pass.

WHAT `pyoneer_subcell="4"` COSTS. Re-measured on the same machine, 100x100,
one companion, median of five: the .tmx grows 42,476 -> 364,205 bytes (8.6x),
`pytmx.TiledMap` goes 15.6 -> 82.8 ms, and the bake goes 10.7 -> 176.6 ms
because there are sixteen times as many cells to resolve. Every per-QUERY
number above is unchanged -- `mask_at` is still one index -- so this is boot
cost and nothing else, and it is roughly a doubling of boot per 4x companion.
Tell an author that before he repaints a 100x100 map at 4x. The per-cell bake
loop is where it goes, not the resolution itself: the same 160,000-cell field
built straight from a flat gid array through a 256-entry lookup is 24.8 ms
median of seven, so a fast path for the common stack (one companion, no
defaults, no overrides) has 7x in it. It has deliberately NOT been written
here: a second resolution walk that has to agree with `resolve` cell for cell
is the one thing this module is not allowed to grow, and it is worth doing
only with a check that asserts the two bakes are byte-identical.

A map that declares no companion bakes nothing at all: `field_from_map`
returns None, `GameEntity.collision_field` stays None, and `move_direction`
runs the arithmetic it ran before this module existed, to the bit. That is
what lets `tools/smoke.py` stay on its baseline, and it is checked.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable, ClassVar, Mapping, Sequence

from scripts.core.depth import resolve_layer_depth
from scripts.core.errors import PyoneerConfigError, warn_content
from scripts.core.layer_profile import (
    DEPTH,
    PASSABILITY,
    PREFIX,
    STATIC,
    read_properties as read_layer_properties,
)
from scripts.core.log import trace_assets

# A reader of gids at a cell. The unit every level of the stack is expressed
# as, so a document layer, a parsed layer and a two-line fixture are the same
# thing to everything below. `editor/core/paint.py` calls this `Reader` and
# means the same shape.
Reader = Callable[[int, int], int]

# A reader of OPINIONS: a mask in 0..STAR, or NO_DATA.
OpinionReader = Callable[[int, int], int]


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------
# RPG Maker's bit order, copied deliberately rather than invented: a set bit
# means BLOCKED, and the order is down, left, right, up. Star is NOT a
# direction -- it means "abstain, ask the layer below" -- so it gets its own
# value rather than being squeezed into the four bits.

BLOCK_DOWN = 0x1
BLOCK_LEFT = 0x2
BLOCK_RIGHT = 0x4
BLOCK_UP = 0x8
PASS_ALL = 0x0
BLOCK_ALL = BLOCK_DOWN | BLOCK_LEFT | BLOCK_RIGHT | BLOCK_UP
STAR = 0x10                    # defer to the layer below

DIRECTION_NAMES = {
    BLOCK_DOWN: "down", BLOCK_LEFT: "left",
    BLOCK_RIGHT: "right", BLOCK_UP: "up",
}

#: Direction as the four movement verbs the entity code speaks, so a caller
#: with the string "left" never has to know the bit. Built from the names
#: above rather than typed out again, because a fifth direction added there
#: and forgotten here would be a movement verb the gate silently ignores.
DIRECTION_BITS: dict[str, int] = {name: bit
                                  for bit, name in DIRECTION_NAMES.items()}

# Which way each direction bit points, and what it becomes when the tile is
# mirrored.
STEP = {
    BLOCK_DOWN: (0, 1),
    BLOCK_LEFT: (-1, 0),
    BLOCK_RIGHT: (1, 0),
    BLOCK_UP: (0, -1),
}
OPPOSITE = {
    BLOCK_DOWN: BLOCK_UP,
    BLOCK_UP: BLOCK_DOWN,
    BLOCK_LEFT: BLOCK_RIGHT,
    BLOCK_RIGHT: BLOCK_LEFT,
}


def describe_mask(mask: int) -> str:
    """Human-readable passability, for tooltips, traces and generated docs."""
    if mask == STAR:
        return "star (defer to the layer below)"
    if mask == PASS_ALL:
        return "open"
    if mask == BLOCK_ALL:
        return "blocked"
    blocked = [name for bit, name in sorted(DIRECTION_NAMES.items())
               if mask & bit]
    return "blocks " + ", ".join(blocked)


def mask_to_gid(mask: int, first_gid: int) -> int:
    """A passability mask as a gid in its companion layer."""
    if not 0 <= mask <= STAR:
        raise ValueError(f"passability mask {mask} is outside 0..{STAR}")
    return first_gid + mask


def gid_to_mask(gid: int, first_gid: int) -> int:
    """The inverse. gid 0 (an empty cell) reads as fully open.

    That return value is deliberate and is NOT what a collision layer wants
    -- see `gid_to_opinion`, which is the same arithmetic with the empty cell
    answering NO_DATA instead. Both exist because "this cell is open" and
    "this layer says nothing about this cell" are different claims, and
    `tools/check_editor.py` pins this one.
    """
    if gid <= 0:
        return PASS_ALL
    mask = gid - first_gid
    return mask if 0 <= mask <= STAR else PASS_ALL


# ---------------------------------------------------------------------------
# The tmx gid encoding
# ---------------------------------------------------------------------------
# A gid in a tmx layer is not just a tile number: the top three bits are flip
# flags. Any arithmetic that forgets to mask them off does not fail -- it
# looks up a tile id in the hundreds of millions, finds nothing, and silently
# reports "no opinion" for every flipped tile on the map.

GID_FLAG_MASK = 0xE0000000
GID_VALUE_MASK = 0x1FFFFFFF
FLIP_HORIZONTAL = 0x80000000
FLIP_VERTICAL = 0x40000000
FLIP_DIAGONAL = 0x20000000


def split_gid(raw: int) -> tuple[int, int]:
    """A raw tmx gid as (bare gid, flip flags)."""
    return raw & GID_VALUE_MASK, raw & GID_FLAG_MASK


def join_gid(bare: int, flags: int) -> int:
    """The inverse of `split_gid`."""
    return (bare & GID_VALUE_MASK) | (flags & GID_FLAG_MASK)


# Where each direction bit lands under each mirror. Written as names rather
# than as shifts: `(bits & BLOCK_LEFT) << 1` happens to be BLOCK_RIGHT today
# and would go on being a plausible-looking number on the day the bit layout
# moved.
_MIRROR_DIAGONAL = {BLOCK_UP: BLOCK_LEFT, BLOCK_LEFT: BLOCK_UP,
                    BLOCK_DOWN: BLOCK_RIGHT, BLOCK_RIGHT: BLOCK_DOWN}
_MIRROR_HORIZONTAL = {BLOCK_LEFT: BLOCK_RIGHT, BLOCK_RIGHT: BLOCK_LEFT,
                      BLOCK_UP: BLOCK_UP, BLOCK_DOWN: BLOCK_DOWN}
_MIRROR_VERTICAL = {BLOCK_UP: BLOCK_DOWN, BLOCK_DOWN: BLOCK_UP,
                    BLOCK_LEFT: BLOCK_LEFT, BLOCK_RIGHT: BLOCK_RIGHT}


def _mirror(bits: int, mapping: Mapping[int, int]) -> int:
    out = 0
    for source, target in mapping.items():
        if bits & source:
            out |= target
    return out


def transform_mask(mask: int, flags: int) -> int:
    """A mask as seen through a tile's flip flags.

    A horizontally flipped wall blocks from the other side. Skipping this is
    the kind of bug that only shows up on the mirrored half of a symmetrical
    room, which is exactly where nobody looks.

    Tiled applies the diagonal flip (a transpose, so up<->left and
    down<->right) BEFORE the horizontal and vertical ones; that order is
    reproduced here. Star survives untouched -- it is not a direction, so
    there is nothing to mirror.

    NO_DATA passes through unchanged. That guard is not defensive padding:
    NO_DATA is -1, so the bit arithmetic below turns it into STAR|BLOCK_ALL
    = 31, a value outside the vocabulary that nothing downstream would
    recognise. Mirroring a value that says nothing still says nothing.
    """
    if mask == NO_DATA:
        return NO_DATA
    star = mask & STAR
    bits = mask & BLOCK_ALL
    if flags & FLIP_DIAGONAL:
        bits = _mirror(bits, _MIRROR_DIAGONAL)
    if flags & FLIP_HORIZONTAL:
        bits = _mirror(bits, _MIRROR_HORIZONTAL)
    if flags & FLIP_VERTICAL:
        bits = _mirror(bits, _MIRROR_VERTICAL)
    return star | bits


# ---------------------------------------------------------------------------
# Opinions
# ---------------------------------------------------------------------------
# -1 rather than a large sentinel so that `opinion != NO_DATA` is the whole
# abstention test and no arithmetic on a real mask can ever produce it: the
# mask domain is 0..STAR and every converter clamps into it.
NO_DATA = -1


def is_opinion(value: int) -> bool:
    """True for NO_DATA or any mask this vocabulary defines."""
    return value == NO_DATA or 0 <= value <= STAR


def describe_opinion(opinion: int) -> str:
    """`describe_mask` extended by the one value it cannot describe."""
    if opinion == NO_DATA:
        return "no opinion"
    if not 0 <= opinion <= STAR:
        return f"invalid ({opinion})"
    return describe_mask(opinion)


def gid_to_opinion(gid: int, first_gid: int) -> int:
    """A companion-layer gid as an opinion. The sibling of `gid_to_mask`.

    Two branches differ, and both differ deliberately:

      * an empty cell (gid 0) is NO_DATA here, where `gid_to_mask` says
        PASS_ALL. A collision layer is empty almost everywhere, and reading
        that emptiness as an assertion is what makes a stack of layers
        meaningless.
      * a gid belonging to some other tileset is NO_DATA too, for the same
        reason: this layer holds no mask for that cell, which is not the same
        claim as "that cell is open".

    Flip flags are masked off first. A mask tile has no business being
    flipped, but a hand-edited file can carry anything, and the alternative
    is a silent NO_DATA for a cell that plainly holds a mask.
    """
    bare, flags = split_gid(gid)
    if bare <= 0 or not first_gid <= bare <= first_gid + STAR:
        return NO_DATA
    return transform_mask(gid_to_mask(bare, first_gid), flags)


def opinion_to_gid(opinion: int, first_gid: int) -> int:
    """The inverse: NO_DATA becomes the empty cell, everything else defers to
    `mask_to_gid` -- including its ValueError for a mask outside the
    vocabulary, which is a bug in the caller and should be loud."""
    if opinion == NO_DATA:
        return 0
    return mask_to_gid(opinion, first_gid)


def companion_reader(read: Reader, first_gid: int, *,
                     scale: int = 1) -> OpinionReader:
    """A companion tile layer's gids, as opinions.

    `scale` is how many FIELD cells one of this layer's own cells covers --
    the field's resolution divided by this layer's. It is 1 for every
    single-resolution map, which is why it is keyword-only with a default:
    the ordinary call is unchanged.

    It exists because a stack may mix resolutions, and asking a 1x layer for
    a sub-cell coordinate does not merely lose that layer -- it MOVES it.
    Measured before this argument existed, on a stack of one 4x companion and
    one 1x companion baked at 4x: the 1x layer's wall on map row 7 answered at
    sub-cell row 7, which is pixel row 28 rather than pixel row 112. A wall 84
    pixels up the map is strictly worse than a wall that vanished, because it
    still looks like collision working.

    `//` and not `/`, and floor and not truncate, for `cell_of`'s reason: a
    field cell at x = -1 belongs to layer cell -1, not to layer cell 0.
    """
    if scale == 1:
        return lambda x, y: gid_to_opinion(read(x, y), first_gid)
    if scale < 1:
        raise ValueError(f"scale is 1 or more, got {scale}")
    return lambda x, y: gid_to_opinion(read(x // scale, y // scale), first_gid)


def abstains(opinion: int) -> bool:
    """Does this opinion pass the question to the layer BELOW?

    Both no-data and star do, for different reasons -- nothing was written,
    versus "ask below" was written -- and this is the one place the two are
    treated alike.
    """
    return opinion == NO_DATA or opinion == STAR


# ---------------------------------------------------------------------------
# Level one: what a tile means, wherever it is stamped
# ---------------------------------------------------------------------------
# Moved here from `editor/core/collision.py`, whole, on the day the engine
# grew a reader for it. It was authored on the editor side because nothing
# in `scripts/` opened a sidecar; `field_from_map` does now, and a second
# copy of a 250-line parser is the one thing law 2's corollary already cost
# this repository 425 lines to undo. `editor/core/collision.py` imports
# every name below and re-exports it, so no caller over there changed.

class PyoneerBlitmaskError(PyoneerConfigError):
    """A .blitmask file is not the agreed format.

    Carries the offending line, because a 100-row grid with one bad
    character should not read as "the file is broken".
    """

    def __init__(self, message: str, *, line: int | None = None,
                 path: str | None = None, **context: Any):
        where = []
        if path:
            where.append(path)
            context["path"] = path
        if line is not None:
            where.append(f"line {line}")
            context["line"] = line
        if where:
            message = f"{' '.join(where)}: {message}"
        super().__init__(message, **context)
        self.line = line
        self.path = path


# --------------------------------------------------------------------------
# Level one: what a tile means, wherever it is stamped
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TilesetDefaults:
    """One mask per tile in a tileset, addressed by gid.

    `opinions` is row-major over the tileset's own grid, which is why the
    .blitmask that stores it has the tileset's shape: the file laid beside
    the image reads as the image.
    """

    first_gid: int
    columns: int
    rows: int
    opinions: tuple[int, ...]
    name: str = ""

    def __post_init__(self) -> None:
        if self.first_gid < 1:
            raise ValueError(f"a tileset firstgid is 1 or more, got "
                             f"{self.first_gid}")
        if self.columns <= 0 or self.rows <= 0:
            raise ValueError(f"a tileset is at least 1x1, got "
                             f"{self.columns}x{self.rows}")
        if len(self.opinions) != self.columns * self.rows:
            raise ValueError(
                f"tileset {self.name or '?'} is {self.columns}x{self.rows} = "
                f"{self.columns * self.rows} tiles but carries "
                f"{len(self.opinions)} opinions")
        bad = [v for v in self.opinions if not is_opinion(v)]
        if bad:
            raise ValueError(f"opinions outside 0..{STAR} and NO_DATA: "
                             f"{sorted(set(bad))[:8]}")

    @property
    def tile_count(self) -> int:
        return self.columns * self.rows

    @property
    def last_gid(self) -> int:
        return self.first_gid + self.tile_count - 1

    def holds(self, gid: int) -> bool:
        bare, _flags = split_gid(gid)
        return self.first_gid <= bare <= self.last_gid

    def local_id(self, gid: int) -> int:
        """The tile's index within this tileset, or -1 if it is not ours."""
        bare, _flags = split_gid(gid)
        if not self.first_gid <= bare <= self.last_gid:
            return -1
        return bare - self.first_gid

    def opinion_for_gid(self, gid: int) -> int:
        """What this tileset says about a tile, mirrored to match its flags."""
        local = self.local_id(gid)
        if local < 0:
            return NO_DATA
        _bare, flags = split_gid(gid)
        return transform_mask(self.opinions[local], flags)

    def opinion_for_local(self, tile_id: int) -> int:
        if not 0 <= tile_id < self.tile_count:
            return NO_DATA
        return self.opinions[tile_id]

    def with_local(self, tile_id: int, opinion: int) -> "TilesetDefaults":
        """A copy with one tile changed. Frozen, so editing is replacement --
        which is also what makes an undo step a stored reference."""
        if not 0 <= tile_id < self.tile_count:
            raise ValueError(f"tile {tile_id} is outside 0..{self.tile_count - 1}")
        if not is_opinion(opinion):
            raise ValueError(f"{opinion} is not an opinion")
        opinions = list(self.opinions)
        opinions[tile_id] = opinion
        return TilesetDefaults(self.first_gid, self.columns, self.rows,
                               tuple(opinions), self.name)

    def to_blitmask(self, **meta: str) -> "Blitmask":
        head = {"kind": "tileset", "firstgid": str(self.first_gid)}
        if self.name:
            head["name"] = self.name
        head.update(meta)
        return Blitmask(self.columns, self.rows, self.opinions, head)

    @classmethod
    def from_blitmask(cls, blitmask: "Blitmask", *,
                      first_gid: int | None = None,
                      name: str | None = None) -> "TilesetDefaults":
        """Read defaults back, taking firstgid and name from the file's own
        metadata unless the caller overrides them -- the file was written
        next to a tileset whose firstgid may since have moved."""
        if first_gid is None:
            raw = blitmask.meta.get("firstgid", "1")
            try:
                first_gid = int(raw)
            except ValueError:
                raise PyoneerBlitmaskError(
                    f"firstgid must be an integer, got {raw!r}") from None
        if name is None:
            name = blitmask.meta.get("name", "")
        return cls(first_gid, blitmask.width, blitmask.height,
                   blitmask.opinions, name)


def tileset_reader(art: Reader, defaults: Sequence[TilesetDefaults], *,
                   scale: int = 1) -> OpinionReader:
    """Level one as an OpinionReader: read the ART layer's gid at a cell,
    ask whichever tileset owns that gid what the tile means.

    Note what this reads: the art, not a companion. That is the level's
    whole value -- painting a wall tile IS painting collision, with nothing
    else to author and nothing to keep in sync.

    `scale` is how many FIELD cells one of the art layer's cells covers, and
    it is `companion_reader`'s argument with the same meaning and the same
    arithmetic. An art layer has no sub-cell -- it is drawn, and the renderer
    draws one tile per map cell -- so where a companion's scale is the
    field's resolution divided by its own declaration, an art layer's is the
    field's resolution whole. Getting it wrong does not lose the level, it
    RELOCATES it, which is the failure `companion_reader` has the measured
    number for.
    """
    table = tuple(defaults)

    def at(x: int, y: int) -> int:
        raw = art(x, y)
        if raw <= 0:
            return NO_DATA
        for tileset in table:
            opinion = tileset.opinion_for_gid(raw)
            if opinion != NO_DATA:
                return opinion
        return NO_DATA

    if scale == 1:
        return at
    if scale < 1:
        raise ValueError(f"scale is 1 or more, got {scale}")
    return lambda x, y: at(x // scale, y // scale)


# --------------------------------------------------------------------------
# The .blitmask file
# --------------------------------------------------------------------------

MAGIC = "blitmask"
NO_DATA_TOKEN = "."
STAR_TOKEN = "*"
_HEX = "0123456789abcdef"

# One char per opinion. Built from the vocabulary rather than typed out, so
# it cannot drift from it.
TOKENS: dict[int, str] = {NO_DATA: NO_DATA_TOKEN, STAR: STAR_TOKEN}
TOKENS.update({mask: _HEX[mask] for mask in range(BLOCK_ALL + 1)})
OPINIONS: dict[str, int] = {token: opinion for opinion, token in TOKENS.items()}
OPINIONS.update({token.upper(): opinion for token, opinion in OPINIONS.items()
                 if token in _HEX})


def opinion_to_token(opinion: int) -> str:
    """One char for one opinion.

    Raises rather than substituting anything for an opinion outside the
    vocabulary. If the domain ever widens to STAR|direction -- 32 values
    instead of 17 -- a single char stops being enough and this is where
    that has to be noticed, loudly, rather than where a `*` silently
    swallowed a direction bit.
    """
    token = TOKENS.get(opinion)
    if token is None:
        raise PyoneerBlitmaskError(
            f"{opinion} has no .blitmask token; the format encodes NO_DATA, "
            f"STAR and masks 0..{BLOCK_ALL} as one character each")
    return token


def token_to_opinion(token: str) -> int:
    opinion = OPINIONS.get(token)
    if opinion is None:
        raise PyoneerBlitmaskError(
            f"{token!r} is not a .blitmask cell; expected one of "
            f"'.', '*' or a hex digit")
    return opinion


@dataclass(frozen=True)
class Blitmask:
    """A grid of opinions plus its metadata: the whole file, as a value.

    Frozen because it is the thing a command stores to make its own inverse
    -- an edit produces a new Blitmask and the old one IS the undo state,
    with nothing to copy defensively and nothing that can change underneath
    a stored reference.

    `at` answers NO_DATA outside the grid rather than raising, because a
    Blitmask is usable directly as an `OpinionReader` and a reader that
    raises at the border is a reader every caller has to wrap.
    """

    width: int
    height: int
    opinions: tuple[int, ...]
    meta: dict[str, str] = dataclass_field(default_factory=dict)

    VERSION: ClassVar[int] = 1

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise PyoneerBlitmaskError(
                f"a blitmask is at least 1x1, got {self.width}x{self.height}")
        if len(self.opinions) != self.width * self.height:
            raise PyoneerBlitmaskError(
                f"a {self.width}x{self.height} grid wants "
                f"{self.width * self.height} cells, got {len(self.opinions)}")
        bad = [v for v in self.opinions if not is_opinion(v)]
        if bad:
            raise PyoneerBlitmaskError(
                f"cells outside NO_DATA and 0..{STAR}: {sorted(set(bad))[:8]}")
        for key, value in self.meta.items():
            if not key or any(c.isspace() for c in key):
                raise PyoneerBlitmaskError(
                    f"metadata key {key!r} must be one word with no spaces")
            if key in ("size", MAGIC):
                raise PyoneerBlitmaskError(
                    f"{key!r} is structural and cannot be a metadata key")
            if "\n" in str(value) or "\r" in str(value):
                raise PyoneerBlitmaskError(
                    f"metadata {key!r} must be a single line")

    # -- building ----------------------------------------------------------

    @classmethod
    def blank(cls, width: int, height: int, *, fill: int = NO_DATA,
              **meta: str) -> "Blitmask":
        return cls(width, height, (fill,) * (width * height), dict(meta))

    @classmethod
    def from_rows(cls, rows: Sequence[Sequence[int]],
                  **meta: str) -> "Blitmask":
        if not rows or not rows[0]:
            raise PyoneerBlitmaskError("a blitmask needs at least one cell")
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise PyoneerBlitmaskError("blitmask rows must all be one length")
        flat = tuple(value for row in rows for value in row)
        return cls(width, len(rows), flat, dict(meta))

    # -- asking ------------------------------------------------------------

    def at(self, x: int, y: int) -> int:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.opinions[y * self.width + x]
        return NO_DATA

    def reader(self) -> OpinionReader:
        """The grid as a level of a `CollisionLayer`."""
        return self.at

    def row(self, y: int) -> tuple[int, ...]:
        return self.opinions[y * self.width:(y + 1) * self.width]

    def rows(self) -> list[tuple[int, ...]]:
        return [self.row(y) for y in range(self.height)]

    def with_cell(self, x: int, y: int, opinion: int) -> "Blitmask":
        if not 0 <= x < self.width or not 0 <= y < self.height:
            raise PyoneerBlitmaskError(
                f"({x}, {y}) is outside {self.width}x{self.height}")
        if not is_opinion(opinion):
            raise PyoneerBlitmaskError(f"{opinion} is not an opinion")
        opinions = list(self.opinions)
        opinions[y * self.width + x] = opinion
        return Blitmask(self.width, self.height, tuple(opinions),
                        dict(self.meta))

    def counts(self) -> dict[int, int]:
        out: dict[int, int] = {}
        for opinion in self.opinions:
            out[opinion] = out.get(opinion, 0) + 1
        return out

    # -- text --------------------------------------------------------------

    def render(self) -> str:
        """The file, as a string. Always ends in a newline: a text file
        whose last line has no terminator is the one every diff tool
        complains about."""
        lines = [f"{MAGIC} {self.VERSION}", f"size {self.width} {self.height}"]
        lines += [f"{key} {value}" for key, value in self.meta.items()]
        for y in range(self.height):
            lines.append("".join(opinion_to_token(v) for v in self.row(y)))
        return "\n".join(lines) + "\n"

    @classmethod
    def parse(cls, text: str, *, path: str | None = None) -> "Blitmask":
        """Read a .blitmask, refusing anything it cannot read exactly.

        The grammar has one rule that makes it unambiguous without any
        separator ceremony: a header line is `key value` and therefore
        CONTAINS A SPACE, and a grid row is cell characters and therefore
        does not. So the header ends at the first line with no space in it.
        """
        numbered = [(n, raw.strip()) for n, raw in enumerate(text.splitlines(), 1)]
        # Comments and blank lines are for humans and carry nothing, so they
        # are dropped here and do not survive a load/save cycle. Line numbers
        # are kept, which is the only reason the enumerate is up there.
        lines = [(n, s) for n, s in numbered if s and not s.startswith("#")]
        if not lines:
            raise PyoneerBlitmaskError("file is empty", path=path)

        number, first = lines[0]
        parts = first.split()
        if len(parts) != 2 or parts[0] != MAGIC:
            raise PyoneerBlitmaskError(
                f"expected {MAGIC!r} and a version, got {first!r}",
                line=number, path=path)
        try:
            version = int(parts[1])
        except ValueError:
            raise PyoneerBlitmaskError(
                f"version must be an integer, got {parts[1]!r}",
                line=number, path=path) from None
        if version != cls.VERSION:
            raise PyoneerBlitmaskError(
                f"version {version} is not readable by this build "
                f"(expected {cls.VERSION})", line=number, path=path)

        width = height = -1
        meta: dict[str, str] = {}
        index = 1
        while index < len(lines):
            number, line = lines[index]
            if " " not in line:
                break                       # the grid starts here
            key, value = line.split(" ", 1)
            value = value.strip()
            if key == "size":
                # Structural, so it never lands in `meta` and the duplicate
                # check below cannot see it. Without this, a second size line
                # silently wins and the grid is read against a shape the
                # author did not write last.
                if width >= 0:
                    raise PyoneerBlitmaskError("size appears twice",
                                               line=number, path=path)
                size = value.split()
                if len(size) != 2:
                    raise PyoneerBlitmaskError(
                        f"size wants width and height, got {value!r}",
                        line=number, path=path)
                try:
                    width, height = int(size[0]), int(size[1])
                except ValueError:
                    raise PyoneerBlitmaskError(
                        f"size wants two integers, got {value!r}",
                        line=number, path=path) from None
                if width <= 0 or height <= 0:
                    raise PyoneerBlitmaskError(
                        f"size must be positive, got {width}x{height}",
                        line=number, path=path)
            elif key in meta:
                raise PyoneerBlitmaskError(f"metadata {key!r} appears twice",
                                           line=number, path=path)
            else:
                meta[key] = value
            index += 1

        if width < 0:
            raise PyoneerBlitmaskError("no size line", path=path)

        grid = lines[index:]
        if len(grid) != height:
            number = grid[height][0] if len(grid) > height else lines[-1][0]
            raise PyoneerBlitmaskError(
                f"size says {height} rows, found {len(grid)}",
                line=number, path=path)
        opinions: list[int] = []
        for number, row in grid:
            if len(row) != width:
                raise PyoneerBlitmaskError(
                    f"size says {width} cells, row is {len(row)}",
                    line=number, path=path)
            for column, token in enumerate(row):
                try:
                    opinions.append(token_to_opinion(token))
                except PyoneerBlitmaskError as error:
                    raise PyoneerBlitmaskError(
                        f"column {column + 1}: {error.message}",
                        line=number, path=path) from None
        return cls(width, height, tuple(opinions), meta)

    # -- disk --------------------------------------------------------------

    @classmethod
    def load(cls, path: str) -> "Blitmask":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.parse(handle.read(), path=path)

    def save(self, path: str) -> None:
        """Write it. newline="" so the bytes are the bytes on every
        platform -- this repo's whole tmx contract is byte-exactness, and a
        sidecar that grows carriage returns on Windows and loses them on
        the next machine is a diff nobody authored."""
        directory = os.path.dirname(os.path.abspath(path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(self.render())

    def __str__(self) -> str:
        return self.render()


# ---------------------------------------------------------------------------
# One layer's levels, and the stack
# ---------------------------------------------------------------------------

@dataclass
class CollisionLayer:
    """The three levels for one map layer, and the walk down them.

    Fields are declared weakest first, to read in the same order the levels
    are documented; `opinion_at` consults them in the opposite order, which
    is the one that matters -- only strongest-first lets the specific beat
    the general.

    A level is any `OpinionReader`, so a test fixture, a companion layer, a
    tileset table and a future runtime source are the same thing to this
    class. `None` means the level is absent, which differs from a level that
    answers NO_DATA everywhere only in that it costs nothing.
    """

    name: str = ""
    defaults: OpinionReader | None = None      # weakest
    companion: OpinionReader | None = None
    overrides: dict[tuple[int, int], int] = dataclass_field(default_factory=dict)

    def opinion_at(self, x: int, y: int) -> int:
        """Strongest level that has something to say, or NO_DATA.

        STAR stops this walk. It is an authored abstention -- "not my
        business" -- and a level that says it has spoken, which is how a star
        painted over a tileset default suppresses that default instead of
        falling through to it.
        """
        opinion = self.overrides.get((x, y), NO_DATA)
        if opinion != NO_DATA:
            return opinion
        for level in (self.companion, self.defaults):
            if level is None:
                continue
            opinion = level(x, y)
            if opinion != NO_DATA:
                return opinion
        return NO_DATA

    def set_override(self, x: int, y: int, opinion: int) -> None:
        """Write the strongest level.

        An override of NO_DATA REMOVES the entry rather than storing it,
        because "this cell overrides nothing" and "there is no override for
        this cell" resolve identically -- storing both would be two spellings
        of one state, and the sparse dict is the fast shape precisely because
        it holds only what was said.
        """
        if not is_opinion(opinion):
            raise ValueError(f"{opinion} is not an opinion "
                             f"(NO_DATA or 0..{STAR})")
        if opinion == NO_DATA:
            self.overrides.pop((x, y), None)
        else:
            self.overrides[(x, y)] = opinion

    def clear_override(self, x: int, y: int) -> None:
        self.overrides.pop((x, y), None)

    def override_at(self, x: int, y: int) -> int:
        return self.overrides.get((x, y), NO_DATA)


@dataclass(frozen=True)
class Resolution:
    """What a cell resolves to, and who decided.

    `layer` and `conflicted` are not for the runtime -- the runtime wants the
    mask and nothing else. They are for the editor's overlay, which has to
    answer "why is this cell blocked" and "does a layer under this one
    disagree", neither of which survives being reduced to a mask.
    """

    mask: int
    layer: int = -1              # index of the deciding layer, -1 if none did
    conflicted: bool = False

    @property
    def decided(self) -> bool:
        """False when every layer abstained and `mask` is the fallback."""
        return self.layer >= 0

    def describe(self) -> str:
        if not self.decided:
            return f"{describe_mask(self.mask)} (undecided)"
        text = f"{describe_mask(self.mask)} (layer {self.layer})"
        return (text + " CONFLICT") if self.conflicted else text


def resolve(layers: Sequence[CollisionLayer], x: int, y: int, *,
            undecided: int = PASS_ALL) -> Resolution:
    """Walk a layer stack and report the first layer that decides.

    `layers` is ordered TOPMOST FIRST. A tmx layer list is the other way
    round -- first child is the bottom layer -- so a caller reading a map
    reverses it. `collision_layers` below does, and the check pins it.

    `undecided` is what a cell means when every layer abstained. It defaults
    to PASS_ALL because an unauthored map should be walkable, but it is a
    parameter rather than a constant: a game where unauthored means solid is
    just as reasonable and should not have to re-implement the walk.
    """
    decider = -1
    mask = undecided
    for index, layer in enumerate(layers):
        opinion = layer.opinion_at(x, y)
        if abstains(opinion):
            continue
        decider, mask = index, opinion
        break
    if decider < 0:
        return Resolution(mask, -1, False)
    # Conflict is a channel of its own: a layer BELOW the decider that says
    # something different is invisible in the resolved mask, and it is
    # exactly what you want flagged while hopping between layers.
    for lower in layers[decider + 1:]:
        opinion = lower.opinion_at(x, y)
        if not abstains(opinion) and opinion != mask:
            return Resolution(mask, decider, True)
    return Resolution(mask, decider, False)


# ---------------------------------------------------------------------------
# The baked runtime field
# ---------------------------------------------------------------------------

class CollisionField:
    """A resolved mask per cell, flat, immutable, and cheap to ask.

    This is the answer rather than the question: every NO_DATA has already
    collapsed, every layer has already been walked, and a query is a bounds
    check plus one index into a `bytes`. The cost of resolution is paid once
    at map load instead of once per query forever.

    `outside` is what a query beyond the edge returns, and it defaults to
    BLOCK_ALL because the alternative lets an entity walk out of the world.
    A caller who wants an open border passes PASS_ALL and means it.
    """

    __slots__ = ("width", "height", "tile_width", "tile_height",
                 "outside", "_masks")

    def __init__(self, width: int, height: int, masks: bytes | Sequence[int],
                 *, tile_width: int = 16, tile_height: int = 16,
                 outside: int = BLOCK_ALL) -> None:
        if width <= 0 or height <= 0:
            raise ValueError(f"a field is at least 1x1, got {width}x{height}")
        if tile_width <= 0 or tile_height <= 0:
            raise ValueError(f"tile size must be positive, got "
                             f"{tile_width}x{tile_height}")
        data = bytes(masks)
        if len(data) != width * height:
            raise ValueError(f"a {width}x{height} field wants "
                             f"{width * height} masks, got {len(data)}")
        bad = [m for m in data if not 0 <= m <= STAR]
        if bad:
            raise ValueError(f"masks outside 0..{STAR}: {sorted(set(bad))[:8]}")
        if not 0 <= outside <= STAR:
            raise ValueError(f"outside must be a mask, got {outside}")
        self.width = width
        self.height = height
        self.tile_width = tile_width
        self.tile_height = tile_height
        self.outside = outside
        self._masks = data

    # -- building ----------------------------------------------------------

    @classmethod
    def bake(cls, layers: Sequence[CollisionLayer], width: int, height: int,
             *, tile_width: int = 16, tile_height: int = 16,
             outside: int = BLOCK_ALL,
             undecided: int = PASS_ALL) -> "CollisionField":
        """Resolve every cell once. `layers` is topmost first, as `resolve`.

        Note what `undecided` does here: it is the moment "no opinion" stops
        existing. Everything above this line distinguishes silence from
        assent; nothing below it can, because a runtime answering "I don't
        know" to a movement query is not an answer.
        """
        if not 0 <= undecided <= STAR:
            raise ValueError(f"undecided must be a mask, got {undecided}")
        stack = tuple(layers)
        masks = bytearray(width * height)
        at = 0
        for y in range(height):
            for x in range(width):
                mask = undecided
                for layer in stack:
                    opinion = layer.opinion_at(x, y)
                    if not abstains(opinion):
                        mask = opinion
                        break
                masks[at] = mask
                at += 1
        return cls(width, height, bytes(masks), tile_width=tile_width,
                   tile_height=tile_height, outside=outside)

    # -- asking ------------------------------------------------------------

    def contains(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def mask_at(self, x: int, y: int) -> int:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self._masks[y * self.width + x]
        return self.outside

    def cell_of(self, pixel_x: float, pixel_y: float) -> tuple[int, int]:
        """Pixel to cell, floored.

        Floor rather than int(): int() truncates toward zero, so every pixel
        in the range -15..0 lands in cell 0 and an entity a pixel off the
        left edge reads as being inside the map.
        """
        return (int(pixel_x // self.tile_width),
                int(pixel_y // self.tile_height))

    def mask_at_pixel(self, pixel_x: float, pixel_y: float) -> int:
        x, y = self.cell_of(pixel_x, pixel_y)
        return self.mask_at(x, y)

    def blocks(self, x: int, y: int, direction: int) -> bool:
        """Does the cell itself refuse to be LEFT in this direction?

        One half of a movement test -- see `can_move` for why that is not the
        same question.
        """
        if direction not in STEP:
            raise ValueError(f"{direction} is not one of the four direction "
                             f"bits {sorted(STEP)}")
        return bool(self.mask_at(x, y) & direction)

    def can_move(self, x: int, y: int, direction: int) -> bool:
        """Can something step from (x, y) one cell in `direction`?

        Both cells get a veto, and they veto on opposite bits: leaving
        downward is blocked by this cell's DOWN or by the cell below's UP.
        Checking only the source is the classic one-sided collision bug -- a
        wall you cannot walk out of but can walk into. This is RPG Maker's
        own rule (`canPass` tests the source in `d` and the destination in
        the reverse of `d`), which is where the bit vocabulary came from.

        A consequence worth knowing before designing around it: because one
        bit governs both crossings of the same edge, blocking is SYMMETRIC
        and a one-way platform -- fall down through it, cannot climb back up
        -- cannot be expressed. That needs a per-edge pair rather than a
        per-cell nibble, which is a vocabulary change and not something to
        fake here.
        """
        if direction not in STEP:
            raise ValueError(f"{direction} is not one of the four direction "
                             f"bits {sorted(STEP)}")
        if self.mask_at(x, y) & direction:
            return False
        step_x, step_y = STEP[direction]
        return not self.mask_at(x + step_x, y + step_y) & OPPOSITE[direction]

    def counts(self) -> dict[int, int]:
        """How many cells hold each mask. For a summary line, and for
        spotting a map that resolved to nothing."""
        out: dict[int, int] = {}
        for mask in self._masks:
            out[mask] = out.get(mask, 0) + 1
        return out

    def masks(self) -> bytes:
        """The flat row-major store. `bytes`, so handing it out cannot let a
        caller mutate the field behind its back."""
        return self._masks

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CollisionField):
            return NotImplemented
        return (self.width == other.width and self.height == other.height
                and self.outside == other.outside
                and self.tile_width == other.tile_width
                and self.tile_height == other.tile_height
                and self._masks == other._masks)

    def __repr__(self) -> str:
        blocked = sum(1 for m in self._masks if m and m != STAR)
        return (f"CollisionField({self.width}x{self.height}, "
                f"{blocked} blocking cells)")


# ---------------------------------------------------------------------------
# The movement gate
# ---------------------------------------------------------------------------

#: How far short of a blocked edge the anchor is left, in pixels. A power of
#: two so it is exact in binary floating point, and four orders of magnitude
#: below a pixel so nothing can see it. It exists because the two edges of a
#: cell are not symmetric under flooring: arriving exactly ON the left edge
#: of cell N still floors to N, but arriving exactly on the RIGHT edge floors
#: to N+1 -- which is the cell the mask just said could not be entered.
EDGE_INSET = 1.0 / 1024


def allowed_distance(field: CollisionField, pixel_x: float, pixel_y: float,
                     direction: int, distance: float) -> float:
    """How far an anchor at (pixel_x, pixel_y) may actually travel.

    `direction` is one of the four bits, `distance` is a POSITIVE magnitude
    along it, and the answer is never more than what was asked for.

    The walk is over cell BOUNDARIES rather than over cells, which is what
    makes one call correct for a step longer than a tile: a sprinting entity
    at 20 fps crosses two cells in a frame, and a gate that only tested the
    first boundary would let it pass through a one-tile wall. Every boundary
    between here and there is asked, and the first refusal stops the entity
    inside the cell it was leaving.

    An anchor OUTSIDE the field is not gated at all. `CollisionField.outside`
    is BLOCK_ALL by default, so testing from out there would return False for
    every direction and freeze the entity permanently with no way back in.
    The border still stops an entity LEAVING the field, because that test is
    made from a cell inside it.
    """
    if direction not in STEP:
        raise ValueError(f"{direction} is not one of the four direction "
                         f"bits {sorted(STEP)}")
    if distance <= 0:
        return distance
    cell_x, cell_y = field.cell_of(pixel_x, pixel_y)
    if not field.contains(cell_x, cell_y):
        return distance

    step_x, step_y = STEP[direction]
    horizontal = step_x != 0
    size = field.tile_width if horizontal else field.tile_height
    sign = step_x if horizontal else step_y
    position = pixel_x if horizontal else pixel_y
    end = position + sign * distance
    cell = cell_x if horizontal else cell_y

    while True:
        if sign > 0:
            # Reaching (cell + 1) * size EXACTLY is already inside the next
            # cell, hence >= here and > in the branch below. That asymmetry
            # is the whole reason EDGE_INSET exists.
            boundary = (cell + 1) * size
            if end < boundary:
                return distance
            needed = boundary - position
        else:
            boundary = cell * size
            if end >= boundary:
                return distance
            needed = position - boundary
        if not field.can_move(cell_x, cell_y, direction):
            if sign > 0:
                needed -= EDGE_INSET
            return needed if needed > 0 else 0.0
        cell += sign
        cell_x += step_x
        cell_y += step_y
        if (not field.contains(cell_x, cell_y)
                and field.can_move(cell_x, cell_y, direction)):
            # Past the edge every cell answers `outside`, so this crossing and
            # every later one ask the same question and get the same answer.
            # With the default BLOCK_ALL border the branch above has already
            # returned; it is an OPEN border that needs this, or the loop runs
            # once per tile for however far the caller asked -- 62,500 times
            # for a million pixels, which is a frame hitch produced by a
            # boundary walk that has had nothing to decide since the first one.
            return distance


def move_point(field: CollisionField, pixel_x: float, pixel_y: float,
               direction: int, distance: float) -> tuple[float, float]:
    """`allowed_distance` applied: where the anchor actually ends up."""
    step_x, step_y = STEP[direction]
    allowed = allowed_distance(field, pixel_x, pixel_y, direction, distance)
    return pixel_x + step_x * allowed, pixel_y + step_y * allowed


# ---------------------------------------------------------------------------
# Reading a map
# ---------------------------------------------------------------------------

#: The tileset whose seventeen tiles ARE the masks, matched case-insensitively
#: by name. A mask is a gid like any other, so it has to belong to a declared
#: tileset; naming the tileset is how the map says which gids mean
#: passability. `editor/ui/canvas.py` imports this rather than spelling it a
#: second time: a map painted against one name and read against another has
#: collision the player cannot feel -- no error, no warning, just walls that
#: are not there.
COLLISION_TILESET = "collision"

#: Appended to a layer's name for the companion the editor creates when the
#: layer does not declare `pyoneer_passability`. The editor writes that
#: property as part of the same transaction, so the suffix is a fallback for
#: hand-authored maps rather than the normal path -- but it has to be here,
#: because a map whose author added `FloorCollision` in Tiled and no property
#: is a map the editor's overlay reads and the engine otherwise would not.
#: `editor/ui/canvas.py` imports it, for the reason above.
COMPANION_SUFFIX = "Collision"

#: A tmx `<tileset>`'s declaration of its own per-tile masks: the name of a
#: `.blitmask` file, resolved RELATIVE TO THE .tmx exactly as the tileset's
#: own `<image source>` is.
#:
#: One base for every path in a .tmx, with no exceptions to remember, which
#: is why it is not resolved beside the image even though beside the image is
#: where the file belongs. An author writing
#: `pyoneer_collision="../graphics/tilesets/System/TileA2.blitmask"` under an
#: `<image source="../graphics/tilesets/System/TileA2.png"/>` has written the
#: same prefix twice and can see that he has; an author writing
#: `"TileA2.blitmask"` against an image two directories away would be writing
#: a path whose base is different from the one on the line above it, and the
#: failure of guessing wrong is a mask that silently does not load.
#:
#: ABSENT MEANS NO DEFAULTS, and that is the whole of the optional case: a
#: tileset that declares nothing contributes nothing, every map authored
#: before this existed is unchanged, and `field_from_map` bakes exactly what
#: it baked before. PRESENT AND UNREADABLE RAISES -- see `tileset_defaults`,
#: which is where the line between "not authored" and "authored wrong" is
#: drawn, and why it is drawn there.
#:
#: It sits outside `layer_profile.KNOWN` for `SUBCELL`'s reason and one more:
#: KNOWN is the vocabulary the layer INSPECTOR offers, and this is not a
#: layer property at all.
DEFAULTS_PROPERTY = PREFIX + "collision"

#: How many sub-cells a companion layer divides each map TILE into, along each
#: axis. Declared on the COMPANION layer, `type="int"`, and ABSENT MEANS 1.
#:
#: That default is the load-bearing half. Every map in this repository and
#: every map the editor has ever written carries a companion at exactly the
#: map's size, so 1 is what the file format already says when it says nothing
#: -- it is not law 7's "plausible default" but the documented meaning of an
#: omitted property, in the same way an omitted `pyoneer_depth` means "use the
#: name". The value that would be a guess is the one this refuses to make:
#: inferring the ratio from the layer's DIMENSIONS cannot work, because a
#: companion SMALLER than the map is already legal and already supported
#: (`file_gid_reader` answers 0 past its edge on purpose), so 100x100 against a
#: 400x400 map is "half the map is authored at 1x" and 400x400 against a
#: 100x100 map is "the whole map is authored at 4x", and nothing but a
#: declaration separates them.
#:
#: It lives here rather than in `scripts/core/layer_profile.py` for the reason
#: `COLLISION_TILESET` and `COMPANION_SUFFIX` do: `layer_profile.KNOWN` is the
#: vocabulary the editor's layer INSPECTOR renders and `tools/check_editor.py`
#: asserts the two sides declare exactly the same set, so a property that only
#: a companion layer can carry would have to be offered on every layer to get
#: in there. `editor/core/map_events.py`'s `pyoneer_trigger_layer` set the
#: precedent and its check pins it as deliberately outside KNOWN.
SUBCELL = PREFIX + "subcell"

#: Where a layer sorts when nothing places it.
#:
#: THE TWO DEPTH TABLES, AND WHAT WAS DONE ABOUT THEM
#: --------------------------------------------------
#: This used to claim it "matches MapCanvas.__depth_of". It did not. The
#: engine ranks a layer through `resolve_layer_depth` -> `MAP_DEPTH` in
#: `scripts/core/depth.py`; the editor ranked it through
#: `session.project.genre.layer(name).depth` -> the genre pack JSON. Two
#: independently authored tables that agreed on the six shipped layer names
#: by coincidence. `resolve` walks TOPMOST FIRST, so a layer ranked by one
#: table and unranked (500) by the other makes the editor and the engine pick
#: a DIFFERENT deciding layer for the same cell -- exactly the "walks
#: differently in the editor than in the game" failure this module exists to
#: prevent, and it was reachable today: `ENTITY_1`..`ENTITY_3`,
#: `FOREGROUND_1`, `FOREGROUND_2` and `UI_LAYER_1` are in `MAP_DEPTH` and in
#: no genre pack.
#:
#: Both, in the end, because they answer different questions and only one of
#: them can be authoritative:
#:
#:   * UNIFIED the fallback. `MapCanvas.__depth_of` now defers to
#:     `depth_for_layer_name` below -- the engine's own table -- for any name
#:     its genre pack does not declare, so the two cannot disagree about a
#:     name only one of them ranks. The genre pack still wins where it
#:     declares a layer, because that is the editor's authored contract with
#:     the author and the engine has no business overriding it.
#:   * ASSERTED the overlap. `tools/check_collision_runtime.py` section 8
#:     walks every shipped genre pack and fails if a layer it declares sits
#:     at a depth `MAP_DEPTH` disagrees with. That is the only remaining way
#:     the two can drift, and it is now a red check rather than a wrong wall.
UNRANKED_DEPTH = 500


def depth_for_layer_name(layer_name: str | None) -> int:
    """Where a layer sorts by its NAME alone, unranked ones included.

    The one place either side of the fence answers "how high does a layer
    called this draw". `resolve_layer_depth` returns None for a name it does
    not know, which is the honest answer to a different question; sorting
    needs a number, and this is where the number comes from.
    """
    named = resolve_layer_depth(layer_name)
    return UNRANKED_DEPTH if named is None else named


def collision_first_gid(document) -> int | None:
    """The firstgid masks are stored relative to, or None if this map has no
    collision tileset. Everything collision-shaped checks this first, because
    without it a mask cannot be encoded OR decoded."""
    for tileset in document.tilesets():
        if tileset.name.lower() == COLLISION_TILESET:
            return tileset.first_gid
    return None


def companion_name(document, layer_name: str) -> str:
    """Which layer holds `layer_name`'s masks. Declared wins over convention.

    `MapCanvas.companion_name` calls this rather than mirroring it, so the
    engine reads what the editor wrote whichever of the two paths wrote it.
    The property is read through `MapDocument` and is therefore already
    a `str`; pytmx would hand back the same string here, but it would hand
    back `'50'` for a neighbouring int property, and one reader for all
    properties is one fewer thing to remember.
    """
    declared = document.tile_layer(layer_name).properties.get(PASSABILITY, "")
    return str(declared or "") or (layer_name + COMPANION_SUFFIX)


def companion_subcell(document, companion: str) -> int:
    """How finely `companion` divides a map tile, validated against the map.

    Returns 1 for a layer that declares nothing, which is every companion
    written before `SUBCELL` existed -- see that constant for why an absent
    property is the format's default rather than a fallback.

    Everything else RAISES, and each raise closes a way for authored collision
    to disappear or move without anybody being told:

      * a value that is not a positive integer. `int("banana")` cannot be
        guessed at, and treating it as 1 would silently discard fifteen
        sixteenths of a 4x companion.
      * a value the map's tile size is not divisible by. A 3-subcell on a 16px
        tile is a 5.33px cell; `CollisionField` would take the floor and every
        boundary in the field would drift off the pixels the author painted.
      * a companion LARGER than `subcell x` the map. That is the one case
        where the cells exist, the reader can see them, and the bake throws
        them away -- measured at HEAD before this function: 256 painted
        sub-cells in, 0 blocking cells out, no exception and no warning.
      * a companion that declares `subcell > 1` and is EXACTLY THE MAP'S
        SIZE. See below; that one is not an authoring choice at all.

    A companion smaller than `subcell x` the map but larger than the map is
    NOT an error and deliberately so. Reads past its edge answer 0,
    `gid_to_opinion` reads 0 as NO_DATA, and "this layer has masks for part
    of the map" is a real authoring shape that both `file_gid_reader` and
    `document_gid_reader` already support -- it WARNS, naming how many cells
    are unauthored, because at 4x that is easy to reach by accident.

    THE SHRUNKEN COMPANION.                          #TAG:tiled_shrinks_companion
    A finite map's layer width/height are SPEC'D to equal the map's, so Tiled
    may rewrite a 4x companion back to map size on the author's next save --
    and this author does round-trip through Tiled. Nobody here has been able
    to run Tiled to find out whether it actually does. So the case is
    DETECTED rather than resolved: a layer that says it is four times finer
    and is not finer at all is the one shape no author writes on purpose,
    and reading it as authored means silently walking a map with fifteen
    sixteenths of its collision gone. It raises, naming the declared factor,
    the size on disk and the size that factor requires -- so if Tiled ever
    does this, the author is told on the next load instead of discovering it
    as walls that are no longer there.
    """
    layer = document.tile_layer(companion)
    raw = layer.properties.get(SUBCELL, 1)
    try:
        subcell = int(raw)
    except (TypeError, ValueError):
        raise PyoneerConfigError(
            f"collision layer {companion!r} declares {SUBCELL}={raw!r}, which "
            f"is not an integer; it is how many sub-cells one map tile is "
            f"divided into along each axis, and an absent property means 1",
            source=getattr(document, "path", None)) from None
    if subcell < 1:
        raise PyoneerConfigError(
            f"collision layer {companion!r} declares {SUBCELL}={subcell}; it "
            f"is 1 or more (1 means one mask per map tile)",
            source=getattr(document, "path", None))
    if document.tile_width % subcell or document.tile_height % subcell:
        raise PyoneerConfigError(
            f"collision layer {companion!r} declares {SUBCELL}={subcell} but "
            f"the map's tiles are {document.tile_width}x"
            f"{document.tile_height}px, which {subcell} does not divide "
            f"evenly; a sub-cell has to land on whole pixels",
            source=getattr(document, "path", None))
    wide, tall = document.width * subcell, document.height * subcell
    if layer.width > wide or layer.height > tall:
        # The suggestion is a CEILING on both axes, not `layer.width //
        # document.width`: a 17x17 layer on a 4x4 map floors to 4 and 4x4 is
        # 16, so the "fix" the message offered would raise again on the next
        # load and read as the engine not knowing its own arithmetic.
        wants = max(-(-layer.width // document.width),
                    -(-layer.height // document.height))
        raise PyoneerConfigError(
            f"collision layer {companion!r} is {layer.width}x{layer.height} "
            f"but declares {SUBCELL}={subcell}, which allows at most "
            f"{wide}x{tall} on a {document.width}x{document.height} map; "
            f"either declare {SUBCELL}={wants} or resize the layer, because "
            f"the cells past that edge would be read by nothing",
            source=getattr(document, "path", None))
    if subcell > 1 and (layer.width, layer.height) == (document.width,
                                                       document.height):
        raise PyoneerConfigError(
            f"collision layer {companion!r} declares {SUBCELL}={subcell} but "
            f"is {layer.width}x{layer.height}, which is exactly the map's "
            f"size -- so it claims to be {subcell}x finer and is not finer at "
            f"all. That factor needs {wide}x{tall}, and reading it as it "
            f"stands would drop {wide * tall - layer.width * layer.height} of "
            f"its {wide * tall} cells. A tile layer in a finite map is spec'd "
            f"to be the map's size, so TILED MAY HAVE RESIZED IT on the last "
            f"save; recover the layer or drop the {SUBCELL} declaration, but "
            f"do not let this load quietly",
            source=getattr(document, "path", None))
    if subcell > 1 and (layer.width < wide or layer.height < tall):
        warn_content(
            f"collision layer {companion!r} declares {SUBCELL}={subcell} and "
            f"is {layer.width}x{layer.height}, where that factor allows "
            f"{wide}x{tall}: {wide * tall - layer.width * layer.height} of "
            f"{wide * tall} sub-cells have no mask and read as NO_DATA. That "
            f"is legal -- part of a map authored at {subcell}x -- and it is "
            f"said out loud because at {subcell}x it is easy to reach by "
            f"resizing rather than by deciding")
    return subcell


def field_subcell(document,
                  pairs: Sequence[tuple[str, str]] | None = None) -> int:
    """The resolution the whole stack has to bake at: the FINEST declared.

    Not the coarsest and not the first: a field baked at anything less than
    the finest layer throws that layer's detail away, which is the failure
    this whole function exists downstream of.

    Every other layer then has to divide it exactly, because a coarser layer
    is read at `x // (finest // its own)` and that arithmetic is only a
    containment when the division is exact. A stack declaring 2 and 3 raises
    naming both rather than silently picking 3 and reading the 2x layer at
    one-and-a-half of its own cells.

    `pairs` is `companion_pairs(document)` when the caller already has it --
    that call can WARN about a dangling companion, and asking for it twice
    would report the same authoring accident twice.
    """
    if pairs is None:
        pairs = companion_pairs(document)
    declared = [(companion, companion_subcell(document, companion))
                for _name, companion in pairs]
    finest = max((value for _c, value in declared), default=1)
    coarse = [(companion, value) for companion, value in declared
              if finest % value]
    if coarse:
        raise PyoneerConfigError(
            f"this map's collision layers declare {SUBCELL} values that do "
            f"not nest: the finest is {finest} and "
            + ", ".join(f"{c!r} declares {v}" for c, v in coarse)
            + f". Every {SUBCELL} in one map has to divide the finest one",
            source=getattr(document, "path", None))
    return finest


def layer_depth(document, layer_name: str) -> int:
    """Where a layer sits in the draw order, by the renderer's own rules.

    The NAME comes first because that is what `LayerRenderer` actually uses
    (`resolve_layer_depth`, and nothing else). `pyoneer_depth` is consulted
    second: the capability promises to override the name lookup, the renderer
    does not honour that promise yet, and ordering collision by a depth
    nothing draws at would be worse than agreeing with the pixels. When the
    renderer starts honouring it, this already agrees.
    """
    named = resolve_layer_depth(layer_name)
    if named is not None:
        return named
    # `depth_for_layer_name` would have collapsed the miss into UNRANKED_DEPTH
    # already, and the declared property has to be consulted in between.
    declared = document.tile_layer(layer_name).properties.get(DEPTH, -1)
    try:
        declared = int(declared)
    except (TypeError, ValueError):
        return UNRANKED_DEPTH
    return declared if declared >= 0 else UNRANKED_DEPTH


def layer_rank(document, layer_name: str, index: int) -> tuple[int, int]:
    """Sort key that puts a layer where `resolve` expects it: TOPMOST FIRST.

    Depth first, then reverse document order, both negated because a stack
    is walked from the top and `sorted` walks from the front. The tie-break
    is not arbitrary: the renderer appends same-depth layers into one list
    and draws it in order, so the layer written LAST in the file is the one
    drawn on top and therefore the one that decides first.

    One function rather than the expression written twice, because
    `collision_layers` ranks a DIFFERENT set of layers than `companion_pairs`
    does the moment a tileset declares defaults -- and two spellings of "which
    layer decides" is the failure this whole module is shaped to avoid.
    """
    return (-layer_depth(document, layer_name), -index)


def companion_pairs(document) -> list[tuple[str, str]]:
    """(art layer, companion layer) for every layer that has masks, TOPMOST
    FIRST -- which is `resolve`'s contract and the reverse of a tmx layer
    list, whose first child is the bottom layer.

    Ties are broken by reverse document order for the same reason: the
    renderer appends same-depth layers into one list and draws it in order,
    so the layer written LAST in the file is the one drawn on top.

    A layer that declares a companion which is not in the map is reported and
    skipped. That is a real authoring accident -- renaming a companion in
    Tiled leaves the property behind -- and it turns collision off for a
    whole layer, silently, which is the failure mode this engine warns about
    rather than swallows.
    """
    names = document.tile_layer_names()
    known = set(names)
    ranked: list[tuple[int, int, str, str]] = []
    for index, name in enumerate(names):
        companion = companion_name(document, name)
        if not companion or companion == name:
            continue
        if companion not in known:
            declared = document.tile_layer(name).properties.get(PASSABILITY, "")
            if declared:
                warn_content(
                    "map layer %r declares %s=%r but the map has no such "
                    "layer, so nothing blocks movement on it. Known layers: "
                    "%s" % (name, PASSABILITY, companion, sorted(known))
                )
            continue
        ranked.append((name, companion, layer_rank(document, name, index)))
    ranked.sort(key=lambda item: item[2])
    return [(name, companion) for name, companion, _rank in ranked]


def gid_inverse(tmx_data) -> dict[int, int]:
    """pytmx's internal gid -> the FILE gid, flip flags included.

    Two sources, and the order matters:

      * `imagemap` is keyed `(file gid, flags)` and valued `(internal, flags)`
        -- the complete inverse, flags and all. It is built by `register_gid`
        for every distinct (gid, flip) pair the file uses.
      * `tiledgidmap` is `internal -> file gid` with the flip bits ALREADY
        STRIPPED, because pytmx splits them off before registering. It is the
        documented handle and it is what every other reader reaches for, so
        it fills anything imagemap does not cover -- but on its own it would
        turn a mirrored wall into an unmirrored one.

    Both are plain attributes of `TiledMap`, and both are absent from a
    fixture that is not a real parsed map, so both are read defensively: a
    caller that hands this something else gets an empty table and reads every
    cell as empty, rather than an AttributeError three frames down.
    """
    table: dict[int, int] = {}
    for key, value in (getattr(tmx_data, "imagemap", None) or {}).items():
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        file_gid, flags = key
        internal = value[0] if isinstance(value, tuple) else value
        table[internal] = join_gid(int(file_gid), _flag_bits(flags))
    for internal, file_gid in (getattr(tmx_data, "tiledgidmap", None) or {}).items():
        table.setdefault(internal, int(file_gid))
    table[0] = 0
    return table


def _flag_bits(flags: Any) -> int:
    """A pytmx `TileFlags` triple as tmx flip bits.

    Read by attribute, not by index: `TileFlags` is a namedtuple whose field
    ORDER is pytmx's business, and `imagemap` also holds one plain `0` for
    the empty gid, which has no fields at all.
    """
    bits = 0
    if getattr(flags, "flipped_horizontally", False):
        bits |= FLIP_HORIZONTAL
    if getattr(flags, "flipped_vertically", False):
        bits |= FLIP_VERTICAL
    if getattr(flags, "flipped_diagonally", False):
        bits |= FLIP_DIAGONAL
    return bits


def parsed_layer(tmx_data, name: str):
    """The named tile layer of a parsed map, or None.

    `TiledMap.get_layer_by_name` raises for a missing name and also matches
    object groups, and this wants neither: a companion is a tile layer, and
    "not there" is an answer this module handles rather than an exception.

    "Tile layer" is tested as "has `data`" rather than by importing pytmx and
    asking isinstance. Only `TiledTileLayer` carries a grid -- an object group
    and an image layer both lack it -- so the duck test is exact, and it keeps
    this module readable by a fixture that is not a parsed map at all.
    """
    for layer in getattr(tmx_data, "layers", ()):
        if (getattr(layer, "name", None) == name
                and getattr(layer, "data", None) is not None):
            return layer
    return None


def file_gid_reader(tmx_data, layer) -> Reader:
    """A parsed tile layer as a reader of FILE gids.

    The whole point of this function is the translation. `layer.data` holds
    pytmx's renumbering, and resolving a mask against it means comparing an
    internal gid to the collision tileset's firstgid -- two numbers from
    different systems that happen to be the same kind of thing, which is why
    the failure is silence rather than an exception.

    Out-of-bounds reads answer 0. A companion layer may legitimately be
    smaller than the map, and `gid_to_opinion` reads 0 as NO_DATA, which is
    exactly the right answer past its edge.
    """
    table = gid_inverse(tmx_data)
    rows = [[table.get(gid, 0) for gid in row] for row in layer.data]
    height = len(rows)
    width = len(rows[0]) if height else 0

    def read(x: int, y: int) -> int:
        if 0 <= x < width and 0 <= y < height:
            return rows[y][x]
        return 0

    return read


def document_gid_reader(tile_layer) -> Reader:
    """A `MapDocument` tile layer as a reader of FILE gids.

    No translation: `MapDocument` never renumbers, so its csv values ARE the
    file's. Used when there is no parsed map to read from -- a check, a tool,
    or a caller holding only a path.
    """
    width, height = tile_layer.width, tile_layer.height
    values = tile_layer.gids()

    def read(x: int, y: int) -> int:
        if 0 <= x < width and 0 <= y < height:
            index = y * width + x
            if index < len(values):
                return values[index]
        return 0

    return read


def at_world_coordinates(document, layer_name: str) -> bool:
    """Are this layer's tile cells the same cells the collision field uses?

    No for a parallaxed layer and no for a `dynamic` one: both are drawn at
    an offset that changes with the camera, so cell (3, 4) of that layer is
    not over cell (3, 4) of the map, and gating on it would put a wall where
    nothing is drawn. This module's own docstring calls a wall 84 pixels off
    "strictly worse than a wall that vanished"; it is the same failure.

    Read through `layer_profile.read_properties` rather than by fetching
    `pyoneer_parallax_x` here, so "what counts as parallaxed" has one answer
    and the renderer owns it.

    Only `collision_layers` asks, and only about a layer that has NO
    companion. A layer that DECLARES `pyoneer_passability` is the author
    saying "collide against this one" in as many words, and this function is
    never consulted for it -- so nothing anybody authored is dropped here.
    What is filtered is the automatic half: which layers a TILESET default
    reaches without being asked.
    """
    profile = read_layer_properties(
        document.tile_layer(layer_name).properties.as_dict())
    return profile.motion == STATIC and not profile.parallaxed


def tileset_defaults(document) -> list[TilesetDefaults]:
    """Level one for this map: each tileset's own per-tile masks, loaded.

    A tileset declares them with `DEFAULTS_PROPERTY`, and the returned list
    is in the map's tileset order -- which would only matter for a map whose
    gid ranges overlap, and they cannot.

    WHERE THE LINE BETWEEN "NOT AUTHORED" AND "AUTHORED WRONG" IS
    -------------------------------------------------------------
    An ABSENT property returns nothing for that tileset and is not an error,
    and that is the entire optional case: every map in this repository
    declares no defaults, bakes exactly what it baked before, and
    `tools/smoke.py` cannot move. A PRESENT property that cannot be honoured
    RAISES, every time, because the alternative is the shape this repository
    has already paid for -- 39 authored tiles dropped for months because a
    name did not match and nothing said so. Six ways to be wrong, each of
    them silent if it is not caught here:

      * the document has no path, so a relative reference has no base. Only
        a document built from bytes can reach this.
      * the file is not there. A renamed or unshipped sidecar reads as a
        tileset with no collision at all, which looks exactly like a feature
        nobody turned on.
      * the tileset's extent is unknown -- an EXTERNAL `<tileset source=>`,
        or an embedded one with no `tilecount`. `TilesetRef.holds` answers
        False for those, and False here is indistinguishable from "that gid
        is not mine", so every tile would silently have no mask.
      * `columns` is missing or zero. The mask grid is row-major over the
        sheet, so with no column count there is no arithmetic from a gid to
        a cell of the mask.
      * the mask is a different WIDTH from the sheet. Every row after the
        first is then shifted, so the masks load, apply, and describe the
        wrong tiles -- the failure that still looks like the feature working.
      * the mask NAMES a different sheet. `to_blitmask` writes the tileset's
        name into the file, so a copied property pointing at another sheet's
        mask is caught by the file itself.

    A mask SHORTER than the sheet is legal and deliberate: `TilesetDefaults`
    is built at the file's own height and `opinion_for_local` answers NO_DATA
    past its end, so masking the first three rows of a 24-row sheet and
    stopping is an ordinary thing to author. Only a mask TALLER than the
    sheet raises, for `companion_subcell`'s reason -- taller is the case
    where the cells exist, were authored, and would be read by nothing.
    """
    path = getattr(document, "path", None)
    base = os.path.dirname(os.path.abspath(path)) if path else ""
    table: list[TilesetDefaults] = []
    for ref in document.tilesets():
        reference = str(document.properties_of(ref.element)
                        .get(DEFAULTS_PROPERTY, "") or "").strip()
        if not reference:
            continue
        label = ref.name or ref.source or ("the tileset at firstgid %d"
                                           % ref.first_gid)
        if not os.path.isabs(reference) and not base:
            raise PyoneerConfigError(
                "tileset %r declares %s=%r, but this map has no path to "
                "resolve it against -- it was built from bytes. Load the map "
                "from a file, or make the reference absolute"
                % (label, DEFAULTS_PROPERTY, reference))
        resolved = os.path.normpath(reference if os.path.isabs(reference)
                                    else os.path.join(base, reference))
        if not os.path.isfile(resolved):
            raise PyoneerConfigError(
                "tileset %r declares %s=%r, which resolves to %s and is not "
                "there. The reference is relative to the .tmx, the same as "
                "the tileset's own image source"
                % (label, DEFAULTS_PROPERTY, reference, resolved),
                source=path)
        if not ref.extent_known:
            raise PyoneerConfigError(
                "tileset %r declares %s=%r but this map cannot say which "
                "gids it owns: an external tileset keeps its tilecount in "
                "the .tsx, and an embedded one may omit it. Without an "
                "extent every tile would silently read as having no mask"
                % (label, DEFAULTS_PROPERTY, reference), source=path)
        if ref.columns <= 0:
            raise PyoneerConfigError(
                "tileset %r declares %s=%r but no columns, and a mask grid "
                "is row-major over the sheet -- with no column count there "
                "is no way from a gid to a cell of the mask"
                % (label, DEFAULTS_PROPERTY, reference), source=path)
        mask = Blitmask.load(resolved)
        rows = -(-ref.tile_count // ref.columns)        # ceiling division
        if mask.width != ref.columns:
            raise PyoneerConfigError(
                "tileset %r is %d columns wide and its masks %s are %d. A "
                "mask grid is row-major over the sheet, so a different width "
                "does not lose a column -- it shifts every row after the "
                "first and masks the wrong tiles"
                % (label, ref.columns, resolved, mask.width), source=path)
        if mask.height > rows:
            raise PyoneerConfigError(
                "masks %s are %dx%d but tileset %r is %d tiles in %d "
                "columns, which is %d rows. The %d cells past that edge were "
                "authored and would be read by nothing"
                % (resolved, mask.width, mask.height, label, ref.tile_count,
                   ref.columns, rows, (mask.height - rows) * mask.width),
                source=path)
        declared = str(mask.meta.get("name", "") or "")
        if declared and ref.name and declared != ref.name:
            raise PyoneerConfigError(
                "masks %s say they belong to tileset %r, and this map "
                "attached them to %r. One of the two is a copied reference; "
                "drop the mask's name line if the file is deliberately shared"
                % (resolved, declared, ref.name), source=path)
        table.append(TilesetDefaults.from_blitmask(
            mask, first_gid=ref.first_gid, name=ref.name))
        trace_assets("tileset defaults %s -> %s (%dx%d, firstgid %d)",
                     label, resolved, mask.width, mask.height, ref.first_gid)
    return table


def collision_layers(document, tmx_data=None, *, subcell: int | None = None,
                     pairs: Sequence[tuple[str, str]] | None = None,
                     defaults: Sequence[TilesetDefaults] | None = None
                     ) -> list[CollisionLayer]:
    """The map's collision stack, TOPMOST FIRST, as lazy readers.

    Cells come from `tmx_data` when it is given -- the parsed map the engine
    already holds -- and from the document otherwise. Properties always come
    from the document; see the module docstring for why the two sources are
    split.

    `subcell` is the resolution the FIELD will be baked at, so that every
    layer, whatever it declares for itself, answers in the field's own
    coordinates. It defaults to `field_subcell(document)`, which is the finest
    any layer declares -- so calling this with two arguments, as everything
    did before sub-cells existed, still returns a stack that composes.

    `defaults` is level one, `tileset_defaults(document)` by default. It
    changes WHICH LAYERS ARE IN THE STACK, and that is the one thing about
    this function worth reading twice:

      * with NO defaults, the stack comes out as `pairs` and nothing else,
        which is what it has always been -- not because unpaired layers are
        skipped early, but because a layer with no level to carry is dropped
        below. One rule decides membership rather than two agreeing. Every
        map in this repository takes this branch and bakes the same bytes it
        baked before level one existed.
      * with defaults, every tile layer that is not itself a companion joins
        -- because the whole point of a mask on the TILE is that stamping the
        tile is the only authoring step, and a layer nobody thought to give a
        companion is exactly the layer that would otherwise be missed.
        `at_world_coordinates` filters that automatic half; a layer that
        declares a companion is never filtered, whatever it declares.

    Both branches rank through `layer_rank`, so a layer's position in the
    stack does not depend on how it got there.
    """
    first_gid = collision_first_gid(document)
    if defaults is None:
        defaults = tileset_defaults(document)
    defaults = tuple(defaults)
    if first_gid is None and not defaults:
        return []
    if pairs is None:
        pairs = companion_pairs(document)
    if subcell is None:
        subcell = field_subcell(document, pairs)

    companion_of = dict(pairs)
    companions = {companion for _name, companion in pairs}
    entries: list[tuple[tuple[int, int], str, str]] = []
    for index, name in enumerate(document.tile_layer_names()):
        companion = companion_of.get(name, "")
        if not companion and (name in companions
                              or not at_world_coordinates(document, name)):
            continue
        entries.append((layer_rank(document, name, index), name, companion))
    entries.sort(key=lambda entry: entry[0])

    stack: list[CollisionLayer] = []
    for _rank, name, companion in entries:
        level_two: OpinionReader | None = None
        if companion and first_gid is not None:
            own = companion_subcell(document, companion)
            if subcell % own:
                raise PyoneerConfigError(
                    f"collision layer {companion!r} declares {SUBCELL}={own}, "
                    f"which does not divide the field's {subcell}",
                    source=getattr(document, "path", None))
            level_two = companion_reader(
                _gid_reader(document, tmx_data, companion), first_gid,
                scale=subcell // own)
        level_one: OpinionReader | None = None
        if defaults:
            # The ART layer, read at the field's resolution. An art layer is
            # always one cell per map tile -- it is drawn, and the renderer
            # has no sub-cell -- so its scale is the field's subcell whole,
            # where a companion's is the field's divided by its own.
            level_one = tileset_reader(
                _gid_reader(document, tmx_data, name), defaults, scale=subcell)
        if level_one is None and level_two is None:
            # THE rule that keeps every existing map on its old bytes. A layer
            # that reached this point with no companion and no defaults has
            # nothing to say at any cell, and an empty layer in the stack is
            # not harmless: `Resolution.layer` is an INDEX, so a silent layer
            # between two loud ones renumbers the deciding layer the editor's
            # overlay reports. Membership is decided by having a level, never
            # by being a tile layer.
            continue
        stack.append(CollisionLayer(name=name, defaults=level_one,
                                    companion=level_two))
    return stack


def _gid_reader(document, tmx_data, layer_name: str) -> Reader:
    """One tile layer's FILE gids, from the parsed map if there is one.

    The parsed map is preferred for `field_from_map`'s reason -- the engine
    holds it already and re-reading the grid from disk would let collision
    disagree with the tiles being drawn -- and the document is the fallback
    for a caller that has no parsed map, and for a layer the parse does not
    carry.
    """
    if tmx_data is not None:
        parsed = parsed_layer(tmx_data, layer_name)
        if parsed is not None:
            return file_gid_reader(tmx_data, parsed)
    return document_gid_reader(document.tile_layer(layer_name))


def field_from_map(source, *, document=None, undecided: int = PASS_ALL,
                   outside: int = BLOCK_ALL) -> CollisionField | None:
    """The map's passability, baked, or None when it declares none.

    None rather than an all-open field, and that is the load-bearing choice
    in this function: it is what lets a map with no collision cost nothing at
    all and behave EXACTLY as it did before this module existed. `GameEntity`
    treats a None field as "no gate" and runs its original arithmetic
    untouched, so `tools/smoke.py` cannot drift on a map that declares
    nothing -- which every map in this repository currently does.

    `source` is a `pytmx.TiledMap`, a `MapDocument` or a path. A parsed map
    supplies the cells and is re-read from disk through `MapDocument` for the
    properties, which is `scripts/loaders/map_loader.py`'s own arrangement
    and is reused rather than rebuilt.

    A NATIVE .blitmap ANSWERS None RATHER THAN RAISING
    --------------------------------------------------
    It has a `filename` like a parsed .tmx does, but it names a binary file
    `MapDocument` cannot parse, and the format carries no collision tileset to
    find in it. So "this map declares no passability" is both the true answer
    and the same answer a .tmx with no companion layer gets, and it is given
    here rather than left as a ParseError three frames down -- because this
    function is called on the map-bind path now, and a bind that raised for a
    format that draws perfectly well would be the wiring breaking the engine.
    A caller holding a path or a MapDocument is unaffected: only a source that
    answers its own `object_records` takes this exit.
    """
    # Imported here, not at module scope: `scripts.loaders.map_loader` pulls
    # in the spawn registry, which imports the entity classes, which import
    # this module's siblings. A top-level import would be a cycle the day an
    # entity wants to read a mask.
    from scripts.loaders.map_loader import as_document, has_tmx_document

    if document is None and not has_tmx_document(source):
        return None

    # A parsed map has `.layers`; a MapDocument and a path do not. Cheaper and
    # more honest than an isinstance chain, which would have to name every
    # accepted type and would quietly reject a subclass of one of them.
    tmx_data = source if getattr(source, "layers", None) is not None else None
    document = as_document(document if document is not None else source)

    # The field is sized by the FINEST companion, not by the map. Baking at
    # the map's dimensions is what silently discarded every sub-cell a 4x
    # companion held -- see `companion_subcell`, which has the number. The
    # tileset scan comes first so that a map declaring no collision at all
    # never reaches a property reader that can raise about one. Level one is
    # looked up in the same breath, because a map may declare tileset
    # defaults and no companion at all -- that is the ordinary shape of this
    # feature, not an edge case, and gating the whole read on the presence of
    # a `collision` TILESET would make the level nobody has to paint the one
    # level you cannot have without painting.
    stack: list[CollisionLayer] = []
    subcell = 1
    defaults = tileset_defaults(document)
    if collision_first_gid(document) is not None or defaults:
        pairs = companion_pairs(document)
        subcell = field_subcell(document, pairs)
        stack = collision_layers(document, tmx_data, subcell=subcell,
                                 pairs=pairs, defaults=defaults)
    if not stack:
        return None
    field = CollisionField.bake(
        stack, document.width * subcell, document.height * subcell,
        tile_width=document.tile_width // subcell,
        tile_height=document.tile_height // subcell,
        outside=outside, undecided=undecided)
    counts = field.counts()
    trace_assets("collision field map=%s layers=%d %dx%d subcell=%d blocking=%d",
                 document.path, len(stack), field.width, field.height, subcell,
                 sum(n for mask, n in counts.items() if mask and mask != STAR))
    return field
