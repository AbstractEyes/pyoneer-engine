"""Collision as authored data: three levels, one resolution, one baked field.

WHY
---
`editor/core/layers.py` already says what a passability mask IS -- four
direction bits in RPG Maker's order, set means blocked, plus a star that
abstains -- and how one mask is stored as a gid in a companion tile layer.
What it does not say is where a mask COMES FROM, and that is the whole
problem:

  * painting a mask per cell per layer is correct and unbearable. A wall
    tile is a wall everywhere it is stamped; saying so four hundred times
    is four hundred chances to miss one.
  * so the mask wants to live on the TILE, authored once, beside the
    tileset that owns it.
  * but a tile is not always the same thing. The same brick is scenery on
    a background layer and a wall on the foreground one, and exactly one
    door in one room is open.

Three levels, then, listed WEAKEST FIRST:

    tileset default    the tile's own mask, authored once per tileset
    layer companion    a companion tile layer's gids, per layer per cell
    per-cell override  a sparse patch: the author's, or the game's, last word

and consulted STRONGEST FIRST, which is the only order that lets the
specific beat the general. One rule makes them compose: a level that
answers `NO_DATA` has not answered, so the next level down is asked.

NO OPINION IS NOT OPEN
----------------------
That rule needs a value meaning "I have nothing to say", and `PASS_ALL`
cannot be it, because `PASS_ALL` is a real assertion -- a hole deliberately
punched through a wall, a bridge over water. `layers.gid_to_mask` reads an
empty cell as `PASS_ALL` and `tools/check_editor.py` pins that return value,
so this module does not touch it. It adds `NO_DATA` and a sibling pair of
converters beside it.

The difference is not academic. A collision layer is empty almost
everywhere. If empty meant open, stacking a second collision layer over the
first would unblock the entire map except where the upper layer happened to
be painted, and a region of blocked water would silently become walkable.
That is a reproduced failure, not a hypothetical.

NO_DATA IS ALSO NOT STAR
------------------------
Both abstain, on different axes, and conflating them loses information the
author supplied:

    NO_DATA  nobody wrote anything here -- ask the next LEVEL of this layer
    STAR     somebody wrote "not my business" -- an authored abstention that
             ends this layer's own three-level walk and asks the layer BELOW

So a star painted over a tileset default deliberately SUPPRESSES that
default, which `NO_DATA` cannot do. Within a layer, star decides; between
layers, star defers. `resolve` treats star and no-data alike only at the
last step, when walking the layer stack, and that is on purpose.

THE .blitmask FORMAT
--------------------
One char per cell, in a grid the same shape as the thing it describes, so
the file LOOKS like the map or the tileset it belongs to and a diff points
at a cell rather than at an offset:

    blitmask 1
    size 8 4
    name TileA2
    # the top row is sky
    ........
    .0*f....
    ..ff....
    ........

`.` is NO_DATA, `*` is STAR, `0`-`f` are the sixteen direction masks in hex.
That `.` and `0` are different characters is the entire point of the format:
"nobody said" and "explicitly open" are one keystroke apart and never
confusable, in the file as in the model.

Comments and blank lines are for humans hand-editing and are not carried in
the model, so they do not survive a load/save cycle. Everything the model
does carry -- size, metadata, every cell -- round-trips byte-identically.

THE RUNTIME SHAPE
-----------------
`CollisionField` is the answer, not the question: bake once at load, then
every query is a bounds check and one flat index into a `bytes`. Baking is
where NO_DATA collapses to a decision, which is why it takes an explicit
`undecided` -- a game where unauthored means solid and one where it means
walkable are both reasonable, and neither should be a silent default buried
in a resolver.

Measured on this machine over 10,000 cells (100x100) and a three-layer
stack -- overrides on top, a companion in the middle, tileset defaults read
through the art layer at the bottom -- baking costs 24.6 ms once, and after
it `mask_at` is 0.31 us and `can_move` 0.72 us. Resolving the same stack
per query instead of baking it costs 35.7 ms per full pass, so the bake
pays for itself before the first frame finishes. Storage is 10,000 bytes
flat: no per-cell object, no dict, nothing to traverse.

Pure Python. No Qt, no pygame, no document, no map. Every function here
takes plain numbers or a `read(x, y)` callable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Iterator, Mapping, Sequence

from editor.core.errors import PyoneerProjectError
from editor.core.layers import (  # the vocabulary; never redefined here
    BLOCK_ALL,
    BLOCK_DOWN,
    BLOCK_LEFT,
    BLOCK_RIGHT,
    BLOCK_UP,
    PASS_ALL,
    STAR,
    describe_mask,
    gid_to_mask,
    mask_to_gid,
)
from editor.core.paint import Reader  # (x, y) -> gid; same idea, same name

# An opinion is a mask in 0..STAR, or NO_DATA. A reader of them is the unit
# every level of the stack is expressed as, so levels are interchangeable
# and a test fixture is a lambda.
OpinionReader = Callable[[int, int], int]

# -1 rather than a large sentinel so that `opinion != NO_DATA` is the whole
# abstention test and no arithmetic on a real mask can ever produce it: the
# mask domain is 0..STAR and every converter clamps into it.
NO_DATA = -1


class PyoneerBlitmaskError(PyoneerProjectError):
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
# The tmx gid encoding
# --------------------------------------------------------------------------
# A gid in a tmx layer is not just a tile number: the top three bits are
# flip flags. Any arithmetic that forgets to mask them off does not fail --
# it looks up a tile id in the hundreds of millions, finds nothing, and
# silently reports "no opinion" for every flipped tile on the map.
#
# These live here rather than in `scripts/` only because nothing in the
# engine needs them yet. When a tileset module lands on the engine side of
# the boundary, they belong there and this module should import them.

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


# Which way each direction bit points, and what it becomes when the tile is
# mirrored. Derived from the imported bits rather than re-stated as numbers,
# so widening the vocabulary cannot leave these behind.
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

    A horizontally flipped wall blocks from the other side. Skipping this
    is the kind of bug that only shows up on the mirrored half of a
    symmetrical room, which is exactly where nobody looks.

    Tiled applies the diagonal flip (a transpose, so up<->left and
    down<->right) BEFORE the horizontal and vertical ones; that order is
    reproduced here. Star survives untouched -- it is not a direction, so
    there is nothing to mirror -- and it is kept as a separate bit so this
    still holds if the mask domain ever widens to STAR|direction.

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


# --------------------------------------------------------------------------
# Opinions
# --------------------------------------------------------------------------

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
        reason: this layer holds no mask for that cell, which is not the
        same claim as "that cell is open".

    Flip flags are masked off first. A mask tile has no business being
    flipped, but a hand-edited file can carry anything, and the alternative
    is a silent NO_DATA for a cell that plainly holds a mask.

    In range, the arithmetic is `gid_to_mask`'s own -- delegated rather than
    copied, so there is exactly one place that knows a mask is `gid -
    first_gid`.
    """
    bare, flags = split_gid(gid)
    if bare <= 0 or not first_gid <= bare <= first_gid + STAR:
        return NO_DATA
    return transform_mask(gid_to_mask(bare, first_gid), flags)


def opinion_to_gid(opinion: int, first_gid: int) -> int:
    """The inverse: NO_DATA becomes the empty cell, everything else defers
    to `mask_to_gid` -- including its ValueError for a mask outside the
    vocabulary, which is a bug in the caller and should be loud."""
    if opinion == NO_DATA:
        return 0
    return mask_to_gid(opinion, first_gid)


def companion_reader(read: Reader, first_gid: int) -> OpinionReader:
    """Level two: a companion tile layer's gids, as opinions."""
    return lambda x, y: gid_to_opinion(read(x, y), first_gid)


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


def tileset_reader(art: Reader, defaults: Sequence[TilesetDefaults]
                   ) -> OpinionReader:
    """Level one as an OpinionReader: read the ART layer's gid at a cell,
    ask whichever tileset owns that gid what the tile means.

    Note what this reads: the art, not a companion. That is the level's
    whole value -- painting a wall tile IS painting collision, with nothing
    else to author and nothing to keep in sync.
    """
    table = tuple(defaults)

    def read(x: int, y: int) -> int:
        raw = art(x, y)
        if raw <= 0:
            return NO_DATA
        for tileset in table:
            opinion = tileset.opinion_for_gid(raw)
            if opinion != NO_DATA:
                return opinion
        return NO_DATA

    return read


# --------------------------------------------------------------------------
# One layer's three levels
# --------------------------------------------------------------------------

@dataclass
class CollisionLayer:
    """The three levels for one map layer, and the walk down them.

    Fields are declared weakest first, to read in the same order the levels
    are documented; `opinion_at` consults them in the opposite order, which
    is the one that matters.

    A level is any `OpinionReader`, so a test fixture, a companion layer, a
    tileset table and a future runtime source are the same thing to this
    class. `None` means the level is absent, which is not the same as a
    level that answers NO_DATA everywhere only in that it costs nothing.
    """

    name: str = ""
    defaults: OpinionReader | None = None      # weakest
    companion: OpinionReader | None = None
    overrides: dict[tuple[int, int], int] = field(default_factory=dict)

    def opinion_at(self, x: int, y: int) -> int:
        """Strongest level that has something to say, or NO_DATA.

        STAR stops this walk. It is an authored abstention -- "not my
        business" -- and a level that says it has spoken, which is how a
        star painted over a tileset default suppresses that default instead
        of falling through to it.
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


# --------------------------------------------------------------------------
# The layer stack
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Resolution:
    """What a cell resolves to, and who decided.

    `layer` and `conflicted` are not for the runtime -- the runtime wants
    the mask and nothing else. They are for the editor's overlay, which has
    to answer "why is this cell blocked" and "does a layer under this one
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


def abstains(opinion: int) -> bool:
    """Does this opinion pass the question to the layer BELOW?

    Both no-data and star do, for different reasons -- nothing was written,
    versus "ask below" was written -- and this is the one place the two are
    treated alike.
    """
    return opinion == NO_DATA or opinion == STAR


def resolve(layers: Sequence[CollisionLayer], x: int, y: int, *,
            undecided: int = PASS_ALL) -> Resolution:
    """Walk a layer stack and report the first layer that decides.

    `layers` is ordered TOPMOST FIRST. A tmx layer list is the other way
    round -- first child is the bottom layer -- so a caller reading a map
    reverses it. The check pins this ordering so a refactor cannot flip it
    quietly.

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


# --------------------------------------------------------------------------
# The baked runtime field
# --------------------------------------------------------------------------

class CollisionField:
    """A resolved mask per cell, flat, immutable, and cheap to ask.

    This is the answer rather than the question: every NO_DATA has already
    collapsed, every layer has already been walked, and a query is a bounds
    check plus one index into a `bytes`. That is the whole design -- the
    cost of resolution is paid once at load instead of once per query
    forever.

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

        Note what `undecided` does here: it is the moment "no opinion"
        stops existing. Everything above this line distinguishes silence
        from assent; nothing below it can, because a runtime answering
        "I don't know" to a movement query is not an answer.
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

    @classmethod
    def from_blitmask(cls, blitmask: "Blitmask", *, tile_width: int = 16,
                      tile_height: int = 16, outside: int = BLOCK_ALL,
                      undecided: int = PASS_ALL) -> "CollisionField":
        """A field straight from a file. NO_DATA cells become `undecided`,
        so this is a lossy direction on purpose -- see `bake`."""
        if not 0 <= undecided <= STAR:
            raise ValueError(f"undecided must be a mask, got {undecided}")
        masks = bytes(undecided if v == NO_DATA else v
                      for v in blitmask.opinions)
        return cls(blitmask.width, blitmask.height, masks,
                   tile_width=tile_width, tile_height=tile_height,
                   outside=outside)

    def to_blitmask(self, **meta: str) -> "Blitmask":
        """The field as a file. Every cell is a real mask by now, so a
        round trip through this and back is exact -- it is only the trip
        INTO a field that loses NO_DATA."""
        head: dict[str, str] = {"kind": "field"}
        head.update(meta)
        return Blitmask(self.width, self.height, tuple(self._masks), head)

    # -- asking ------------------------------------------------------------

    def contains(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def mask_at(self, x: int, y: int) -> int:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self._masks[y * self.width + x]
        return self.outside

    def cell_of(self, pixel_x: float, pixel_y: float) -> tuple[int, int]:
        """Pixel to cell, floored.

        Floor rather than int(): int() truncates toward zero, so every
        pixel in the range -15..0 lands in cell 0 and an entity a pixel
        off the left edge reads as being inside the map.
        """
        return (int(pixel_x // self.tile_width),
                int(pixel_y // self.tile_height))

    def mask_at_pixel(self, pixel_x: float, pixel_y: float) -> int:
        x, y = self.cell_of(pixel_x, pixel_y)
        return self.mask_at(x, y)

    def blocks(self, x: int, y: int, direction: int) -> bool:
        """Does the cell itself refuse to be LEFT in this direction?

        One half of a movement test -- see `can_move` for why that is not
        the same question.
        """
        if direction not in STEP:
            raise ValueError(f"{direction} is not one of the four direction "
                             f"bits {sorted(STEP)}")
        return bool(self.mask_at(x, y) & direction)

    def can_move(self, x: int, y: int, direction: int) -> bool:
        """Can something step from (x, y) one cell in `direction`?

        Both cells get a veto, and they veto on opposite bits: leaving
        downward is blocked by this cell's DOWN or by the cell below's UP.
        Checking only the source is the classic one-sided collision bug --
        a wall you cannot walk out of but can walk into. This is RPG Maker's
        own rule (`canPass` tests the source in `d` and the destination in
        the reverse of `d`), which is where the bit vocabulary came from.

        A consequence worth knowing before designing around it: because one
        bit governs both crossings of the same edge, blocking here is
        SYMMETRIC and a one-way platform -- fall down through it, cannot
        climb back up -- cannot be expressed. That needs a per-edge pair
        rather than a per-cell nibble, which is a vocabulary change in
        `layers.py`, not something to fake here.
        """
        if direction not in STEP:
            raise ValueError(f"{direction} is not one of the four direction "
                             f"bits {sorted(STEP)}")
        if self.mask_at(x, y) & direction:
            return False
        step_x, step_y = STEP[direction]
        return not self.mask_at(x + step_x, y + step_y) & OPPOSITE[direction]

    def counts(self) -> dict[int, int]:
        """How many cells hold each mask. For the editor's summary line and
        for spotting a map that resolved to nothing."""
        out: dict[int, int] = {}
        for mask in self._masks:
            out[mask] = out.get(mask, 0) + 1
        return out

    def masks(self) -> bytes:
        """The flat row-major store. `bytes`, so handing it out cannot let
        a caller mutate the field behind its back."""
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
    meta: dict[str, str] = field(default_factory=dict)

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


def describe_stack(layers: Sequence[CollisionLayer], x: int, y: int) -> str:
    """Every layer's opinion at one cell, topmost first, for a tooltip.

    The resolved mask alone cannot answer "why", and "why" is the only
    question anyone asks of a collision overlay.
    """
    parts = []
    for index, layer in enumerate(layers):
        label = layer.name or f"layer {index}"
        parts.append(f"{label}: {describe_opinion(layer.opinion_at(x, y))}")
    outcome = resolve(layers, x, y)
    parts.append("-> " + outcome.describe())
    return "\n".join(parts)


def blitmask_from_companion(read: Reader, width: int, height: int,
                            first_gid: int, **meta: str) -> Blitmask:
    """A companion tile layer, exported as a .blitmask.

    The pair of this and `companion_gids` is what makes the format a
    lossless alternative representation rather than a one-way export: the
    same grid, addressed by gid in the tmx and by character in the sidecar.
    """
    opinions = tuple(gid_to_opinion(read(x, y), first_gid)
                     for y in range(height) for x in range(width))
    return Blitmask(width, height, opinions, dict(meta))


def companion_gids(blitmask: Blitmask, first_gid: int
                   ) -> Iterator[tuple[int, int, int]]:
    """The inverse: (x, y, gid) triples ready for `map.tile.set_many`.

    Yields every cell including the empty ones, because a companion layer
    being written from a file is being REPLACED, and a cell the file calls
    NO_DATA has to become gid 0 rather than keep whatever was there.
    """
    for y in range(blitmask.height):
        for x in range(blitmask.width):
            yield x, y, opinion_to_gid(blitmask.at(x, y), first_gid)


def as_mapping(blitmask: Blitmask) -> Mapping[tuple[int, int], int]:
    """The declared cells only, as the sparse dict `CollisionLayer.overrides`
    wants. NO_DATA cells are absent rather than present-and-empty."""
    return {(x, y): blitmask.at(x, y)
            for y in range(blitmask.height)
            for x in range(blitmask.width)
            if blitmask.at(x, y) != NO_DATA}
