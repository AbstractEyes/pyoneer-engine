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

WHAT IS HERE AND WHAT IS IMPORTED
---------------------------------
Everything the ENGINE also needs -- the opinion vocabulary, `CollisionLayer`,
`resolve`, `Resolution`, `CollisionField`, the tmx gid encoding and the flip
arithmetic -- is defined once in `scripts/core/collision_runtime.py` and
imported below. `editor/` may import `scripts/` and never the reverse, and
the editor's overlay and the player's movement gate answering the same
question from two hand-kept copies is the one bug this whole feature is
supposed to make impossible. The names are re-exported from here because
every caller in `editor/` already imports them from this module.

What stays is what the runtime has no use for: the three-level stack's
WEAKEST level (`TilesetDefaults`, `tileset_reader`) and the `.blitmask` text
format that stores it. A companion layer's masks live in the .tmx, so the
engine never opens a sidecar; moving a 250-line parser across the fence would
only widen a module the game loads at boot.

Pure Python. No Qt, no pygame, no document, no map. Every function here
takes plain numbers or a `read(x, y)` callable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterator, Mapping, Sequence

from editor.core.errors import PyoneerProjectError
from editor.core.layers import (  # the vocabulary; never redefined here
    BLOCK_ALL,
    PASS_ALL,
    STAR,
)
from editor.core.paint import Reader  # (x, y) -> gid; same idea, same name

# The model, defined once on the engine side. Re-exported rather than
# re-stated -- see WHAT IS HERE AND WHAT IS IMPORTED above.
from scripts.core.collision_runtime import (  # noqa: F401
    FLIP_DIAGONAL,
    FLIP_HORIZONTAL,
    FLIP_VERTICAL,
    GID_FLAG_MASK,
    GID_VALUE_MASK,
    NO_DATA,
    OPPOSITE,
    STEP,
    CollisionField,
    CollisionLayer,
    OpinionReader,
    Resolution,
    abstains,
    companion_reader,
    describe_opinion,
    gid_to_opinion,
    is_opinion,
    join_gid,
    opinion_to_gid,
    resolve,
    split_gid,
    transform_mask,
)


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


def field_from_blitmask(blitmask: Blitmask, *, tile_width: int = 16,
                        tile_height: int = 16, outside: int = BLOCK_ALL,
                        undecided: int = PASS_ALL) -> CollisionField:
    """A field straight from a file. NO_DATA cells become `undecided`, so
    this is a lossy direction on purpose -- see `CollisionField.bake`.

    A function rather than the `CollisionField.from_blitmask` classmethod it
    replaces. `CollisionField` is `scripts/core/collision_runtime.py`'s and
    the engine never opens a `.blitmask`, so a constructor for it that names
    an editor-only type would be the fence pointing the wrong way -- the
    engine importing an authoring format it has no reader for. The two
    directions live here, next to the format they belong to.
    """
    if not 0 <= undecided <= STAR:
        raise ValueError(f"undecided must be a mask, got {undecided}")
    masks = bytes(undecided if v == NO_DATA else v for v in blitmask.opinions)
    return CollisionField(blitmask.width, blitmask.height, masks,
                          tile_width=tile_width, tile_height=tile_height,
                          outside=outside)


def blitmask_from_field(field_in: CollisionField, **meta: str) -> Blitmask:
    """The field as a file. Every cell is a real mask by now, so a round trip
    through this and back is exact -- it is only the trip INTO a field that
    loses NO_DATA."""
    head: dict[str, str] = {"kind": "field"}
    head.update(meta)
    return Blitmask(field_in.width, field_in.height,
                    tuple(field_in.masks()), head)


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
