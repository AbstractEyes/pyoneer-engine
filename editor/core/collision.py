"""Collision as authored data: three levels, one resolution, one baked field.

WHY
---
`editor/core/layers.py` says what a passability mask IS -- four direction
bits in RPG Maker's order, set means blocked, plus a star that abstains --
and how one mask is stored as a gid in a companion tile layer. This module
says where a mask COMES FROM:

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

A collision layer is empty almost everywhere, so if empty meant open,
stacking a second collision layer over the first would unblock the entire
map except where the upper layer happened to be painted, and a region of
blocked water would silently become walkable.

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

THE RUNTIME SHAPE
-----------------
`CollisionField` is the answer, not the question: bake once at load, then
every query is a bounds check and one flat index into a `bytes`. Baking is
where NO_DATA collapses to a decision, which is why it takes an explicit
`undecided` -- a game where unauthored means solid and one where it means
walkable are both reasonable, and neither should be a silent default buried
in a resolver.

Measured over 10,000 cells (100x100) and a three-layer stack, baking costs
24.6 ms once, after which `mask_at` is 0.31 us and `can_move` 0.72 us;
resolving the same stack per query costs 35.7 ms per full pass. Storage is
10,000 bytes flat.

WHAT IS HERE AND WHAT IS IMPORTED
---------------------------------
The opinion vocabulary, `CollisionLayer`, `resolve`, `Resolution`,
`CollisionField`, the tmx gid encoding, the flip arithmetic,
`TilesetDefaults`, `tileset_reader` and the whole `.blitmask` format are
defined once in `scripts/core/collision_runtime.py` -- whose THE .blitmask
FORMAT section is that format's spec -- and imported below. `editor/` may
import `scripts/` and never the reverse, and the editor's overlay and the
player's movement gate must never answer the same question from two
hand-kept copies. The names are re-exported from here because every caller
in `editor/` already imports them from this module.

What stays is what only an AUTHORING tool asks for: conversions between a
`Blitmask` and the two things the editor holds -- a baked `CollisionField`
and a companion tile layer's gids -- plus `describe_stack`, which exists to
put a sentence in a tooltip. None of it is on any path the game loads.

Pure Python. No Qt, no pygame, no document, no map. Every function here
takes plain numbers or a `read(x, y)` callable.
"""
from __future__ import annotations

from typing import Iterator, Mapping, Sequence

from editor.core.layers import (  # the vocabulary; never redefined here
    BLOCK_ALL,
    PASS_ALL,
    STAR,
)
from editor.core.paint import Reader  # (x, y) -> gid; same idea, same name

# The model AND the format, defined once on the engine side and re-exported.
from scripts.core.collision_runtime import (  # noqa: F401
    DEFAULTS_PROPERTY,
    FLIP_DIAGONAL,
    FLIP_HORIZONTAL,
    FLIP_VERTICAL,
    GID_FLAG_MASK,
    GID_VALUE_MASK,
    MAGIC,
    NO_DATA,
    NO_DATA_TOKEN,
    OPINIONS,
    OPPOSITE,
    STAR_TOKEN,
    STEP,
    SUBCELL,
    TOKENS,
    Blitmask,
    CollisionField,
    CollisionLayer,
    OpinionReader,
    PyoneerBlitmaskError,
    Resolution,
    TilesetDefaults,
    abstains,
    collision_first_gid,
    companion_pairs,
    companion_reader,
    companion_subcell,
    describe_opinion,
    field_subcell,
    gid_to_opinion,
    is_opinion,
    join_gid,
    opinion_to_gid,
    opinion_to_token,
    resolve,
    split_gid,
    tileset_defaults,
    tileset_reader,
    token_to_opinion,
    transform_mask,
    world_coordinate_fault,
)


def field_from_blitmask(blitmask: Blitmask, *, tile_width: int = 16,
                        tile_height: int = 16, outside: int = BLOCK_ALL,
                        undecided: int = PASS_ALL) -> CollisionField:
    """A field straight from a file. NO_DATA cells become `undecided`, so
    this is a lossy direction on purpose -- see `CollisionField.bake`.

    A function rather than a `CollisionField` constructor: the class belongs
    to `scripts/`, which never opens a `.blitmask`, so both directions of the
    conversion live on the editor side.
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
