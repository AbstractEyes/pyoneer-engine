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

What deliberately did NOT move: the `.blitmask` text format, `TilesetDefaults`
and `Blitmask`. They are authoring shapes, the runtime path here does not
need them (a companion layer's masks live in the .tmx, not in a sidecar), and
moving a 250-line parser the engine never calls would only widen this module.
Level one of the three-level stack -- the tileset's own defaults -- is
therefore NOT read at runtime yet. See THE LEVELS below.

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
`editor/core/collision.py` documents three, weakest first: tileset defaults,
layer companion, per-cell override. This module reads the MIDDLE one, and
that is not a shortcut -- it is parity with what the editor currently
authors. `MapCanvas.collision_stack()` builds its `CollisionLayer`s with
`companion=` alone: no defaults, no overrides. So the overlay an author sees
while painting and the field a player walks through are resolved from the
same single level. When the editor starts writing tileset defaults, the
missing piece here is `tileset_reader` plus a `.blitmask` load, and
`CollisionLayer` already has the slot for it.

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

A map that declares no companion bakes nothing at all: `field_from_map`
returns None, `GameEntity.collision_field` stays None, and `move_direction`
runs the arithmetic it ran before this module existed, to the bit. That is
what lets `tools/smoke.py` stay on its baseline, and it is checked.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable, Mapping, Sequence

from scripts.core.depth import resolve_layer_depth
from scripts.core.errors import warn_content
from scripts.core.layer_profile import DEPTH, PASSABILITY
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


def companion_reader(read: Reader, first_gid: int) -> OpinionReader:
    """A companion tile layer's gids, as opinions."""
    return lambda x, y: gid_to_opinion(read(x, y), first_gid)


def abstains(opinion: int) -> bool:
    """Does this opinion pass the question to the layer BELOW?

    Both no-data and star do, for different reasons -- nothing was written,
    versus "ask below" was written -- and this is the one place the two are
    treated alike.
    """
    return opinion == NO_DATA or opinion == STAR


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
        ranked.append((layer_depth(document, name), index, name, companion))
    ranked.sort(key=lambda item: (-item[0], -item[1]))
    return [(name, companion) for _depth, _index, name, companion in ranked]


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


def collision_layers(document, tmx_data=None) -> list[CollisionLayer]:
    """The map's collision stack, TOPMOST FIRST, as lazy readers.

    Cells come from `tmx_data` when it is given -- the parsed map the engine
    already holds -- and from the document otherwise. Properties always come
    from the document; see the module docstring for why the two sources are
    split.
    """
    first_gid = collision_first_gid(document)
    if first_gid is None:
        return []
    stack: list[CollisionLayer] = []
    for name, companion in companion_pairs(document):
        read: Reader | None = None
        if tmx_data is not None:
            parsed = parsed_layer(tmx_data, companion)
            if parsed is not None:
                read = file_gid_reader(tmx_data, parsed)
        if read is None:
            read = document_gid_reader(document.tile_layer(companion))
        stack.append(CollisionLayer(
            name=name, companion=companion_reader(read, first_gid)))
    return stack


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

    stack = collision_layers(document, tmx_data)
    if not stack:
        return None
    field = CollisionField.bake(
        stack, document.width, document.height,
        tile_width=document.tile_width, tile_height=document.tile_height,
        outside=outside, undecided=undecided)
    counts = field.counts()
    trace_assets("collision field map=%s layers=%d %dx%d blocking=%d",
                 document.path, len(stack), field.width, field.height,
                 sum(n for mask, n in counts.items() if mask and mask != STAR))
    return field
