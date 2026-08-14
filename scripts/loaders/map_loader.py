"""Turn a map's `<objectgroup>` entries into constructed entities.

This is the read side of the seam the editor has been authoring against.
`MapDocument` writes objects byte-exactly and the editor places them, but
`LayerRenderer.__prepare_map_layers` skips anything that is not a
`TiledTileLayer`, so until now an authored object had no runtime existence
at all.

WHAT THIS DOES AND DELIBERATELY DOES NOT DO
-------------------------------------------
`spawn_objects` returns constructed, positioned entities paired with the
depth each one belongs at. It binds NOTHING. Binding needs a scene and a
renderer, both of which are the caller's, and a loader that reached into
`SceneManager` would make the map read path untestable without a display,
a camera and a full boot. The caller writes the two-line loop:

    for spawned in spawn_objects(document, defaults=...):
        scene.bind(spawned.depth, spawned.entity)

WHY IT READS MapDocument AND NOT pytmx
--------------------------------------
pytmx casts a custom property only when the file carries `type="int"`, and
a property Tiled wrote without it comes back as the string `'50'`. That is
survivable for a colour and fatal for a depth, because `'50'` is truthy, is
not `50`, and indexes nothing. `MapProperties` applies the same typing rules
from the same attribute, and it is the module that WRITES those properties,
so read and write cannot drift apart.

Two more pytmx facts that make it the wrong reader here: it renumbers gids
(raw `layer.data` holds internal gids and `tiledgidmap` is needed to get
back to file gids), and it injects a phantom layer for every per-tile
collision `<objectgroup>` inside an embedded tileset, because it searches
with `.//objectgroup` from the map root. This module searches for object
groups that are direct descendants of the map and not of a tileset, which
is what TMX actually means by an object layer.

A `pytmx.TiledMap` is still accepted as an argument -- it is what the engine
already has in hand at bind time -- but it is used only for its `filename`,
and the properties are re-read from disk through `MapDocument`.

THE Y-ORIGIN DECISION
---------------------
Tiled does not anchor all objects the same way, and the difference is one
sprite tall:

    rectangle / ellipse / point / polygon    (x, y) is the TOP-left
    tile object (a `gid` attribute)          (x, y) is the BOTTOM-left

`EntityLayer.core_render_blits` builds its rect with
`image.get_rect(topleft=(position.x, position.y))`, unconditionally. So a
gid-backed object has to be lifted by its own height on the way in, and
everything else passes through. `object_top_left` is that conversion, and
it is a named function rather than two lines inline so it can be tested
against both shapes.

The lift uses the OBJECT'S declared height, not the spawned sprite's. That
is a choice, and the reason is that the object's height is the only one of
the two an author can see while placing the object in Tiled. Anchoring to
the sprite would mean the same map file spawns an entity in a different
place the day its spritesheet gains a row -- a position that moves because
of art the map does not mention. For a Tiled-authored tile object the two
agree anyway: Tiled writes the tile's display size into width/height.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from scripts.core.errors import PyoneerConfigError, warn_content
from scripts.core.log import trace_assets
from scripts.core.spawn import SPAWN_REGISTRY, resolve_depth, spawn
from scripts.loaders.map_document import MapDocument, MapObject


@dataclass(frozen=True)
class SpawnedEntity:
    """One constructed entity and everything the binder needs to place it.

    `depth` is the LAYER depth to bind into, not a value to assign to
    `entity.depth` -- `EntityLayer` queues at `entity.depth + layer_depth`,
    so doing both would draw the entity at twice its depth.

    Frozen, and it carries `object_id` and `layer_name`, so an error raised
    downstream can name the `<object>` in the .tmx that produced the entity
    rather than just its class.
    """

    entity: Any
    depth: int
    layer_name: str
    object_id: int
    type_name: str


# ---------------------------------------------------------------------------
# Reading the document
# ---------------------------------------------------------------------------

def as_document(source: Any) -> MapDocument:
    """Coerce a MapDocument, a pytmx.TiledMap or a path into a MapDocument.

    A `pytmx.TiledMap` is re-read FROM DISK via its `filename`. That is the
    point -- pytmx's parse is what loses the property types -- but it also
    means an in-memory edit made through pytmx is not visible here. Nothing
    in the engine makes such an edit today; map edits go through
    `MapDocument` and come back via `load_assets(name, reload=True)`.
    """
    if isinstance(source, MapDocument):
        return source
    if isinstance(source, (str, os.PathLike)):
        return MapDocument.load(os.fspath(source))
    filename = getattr(source, "filename", None)
    if filename:
        return MapDocument.load(str(filename))
    raise PyoneerConfigError(
        "spawn_objects needs a MapDocument, a path, or a parsed map that "
        "remembers the file it came from; got %s with no .filename"
        % type(source).__name__,
    )


def object_group_elements(document: MapDocument) -> list[ElementTree.Element]:
    """Every real `<objectgroup>` in the map, in document order.

    "Real" excludes the ones nested inside an embedded `<tileset>`: those
    are per-tile collision shapes, and TMX defines an object LAYER as a
    child of `<map>` (or of a `<group>` under it) and nowhere else. pytmx
    does not make this distinction -- it does `findall(".//objectgroup")`
    from the root and hands back a phantom layer named None for every tile
    that has a collision shape -- and inheriting that bug here would mean
    walking collision geometry looking for entities to spawn.
    """
    inside_tilesets = {element
                       for tileset in document.root.findall("tileset")
                       for element in tileset.iter("objectgroup")}
    return [element for element in document.root.iter("objectgroup")
            if element not in inside_tilesets]


def object_top_left(obj: MapObject, tile_height: int) -> tuple[float, float]:
    """The object's position translated to the top-left origin the renderer uses.

    See THE Y-ORIGIN DECISION in the module docstring. In short: a `gid`
    means Tiled anchored this at the bottom-left, so lift it by its height;
    anything else is already top-left.

    A gid object with no `height` is legal TMX that Tiled itself never
    writes -- it means "draw at the tile's native size". The map's own tile
    height is the closest thing this document can say without resolving the
    tileset, and it warns rather than guessing quietly, because a tile
    taller than the grid would land one grid cell low.
    """
    if not obj.gid:
        return obj.x, obj.y
    height = obj.height
    if height <= 0:
        height = float(tile_height)
        warn_content(
            "tmx object id=%d is a tile object with no height, so its "
            "bottom-left origin was lifted by the map's tile height (%d) "
            "instead. Give it a size in Tiled if its tile is not %dpx tall."
            % (obj.id, tile_height, tile_height)
        )
    return obj.x, obj.y - height


def _warn_unrotatable(obj: MapObject, layer_name: str) -> None:
    """Say so when a map asks for a rotation the render path cannot draw.

    `EntityLayer.core_render_blits` blits the sprite as-is;
    `LayerRenderer.rotate_image` exists but nothing on the entity path calls
    it. A silently-ignored rotation is authored content that did nothing,
    which is the failure this engine warns about rather than swallows.
    """
    raw = obj.element.get("rotation")
    if raw in (None, "", "0", "0.0"):
        return
    warn_content(
        "tmx object id=%d on layer %r declares rotation=%s; the entity "
        "render path does not rotate sprites, so it was ignored."
        % (obj.id, layer_name, raw)
    )


# ---------------------------------------------------------------------------
# The spawn pass
# ---------------------------------------------------------------------------

def spawn_objects(document_or_tmx: Any,
                  registry: Mapping[str, Callable[..., Any]] | None = None,
                  *,
                  defaults: Mapping[str, Mapping[str, Any]] | None = None,
                  layers: Sequence[str] | None = None) -> list[SpawnedEntity]:
    """Construct an entity for every typed object in the map's object groups.

    `registry` maps a tmx object type to its constructor; it defaults to
    `scripts.core.spawn.SPAWN_REGISTRY`. An unknown type raises -- see
    `resolve_factory` for why there is no fallback class.

    `defaults` supplies per-type constructor keyword arguments, because the
    map file cannot carry them. `GamePlayer` needs an `InputActionManager`,
    a movement block and an animation category, all of which live in the
    asset managers the caller owns:

        defaults={"GamePlayer": {"input_": None,
                                 "movement_config": assets.config.get("entity")["default"],
                                 "animation_config": assets.animations.get("entity")}}

    `layers` restricts the pass to named object groups; None means all.

    An object with NO type is skipped, and the skipped ids are reported once
    per layer. Untyped objects are ordinary in Tiled -- a rectangle marking
    a region is not a spawn request -- but a MISSPELLED type field also
    leaves the field looking empty in the file, and this project has already
    lost 39 authored tiles to exactly that kind of silence.
    """
    document = as_document(document_or_tmx)
    table = SPAWN_REGISTRY if registry is None else registry
    argument_sets = defaults or {}
    wanted = None if layers is None else set(layers)
    tile_height = document.tile_height

    spawned: list[SpawnedEntity] = []
    for group in object_group_elements(document):
        layer_name = group.get("name", "")
        if wanted is not None and layer_name not in wanted:
            continue
        untyped: list[int] = []
        for element in group.findall("object"):
            obj = MapObject(document, element)
            type_name = obj.type
            if not type_name:
                untyped.append(obj.id)
                continue
            where = "tmx object id=%d on layer %r" % (obj.id, layer_name)
            entity = spawn(type_name, table, **argument_sets.get(type_name, {}))
            # moveto AFTER construction, never through the constructor:
            # GameEntity accepts a `transform` keyword and discards it
            # (GameEntitySimple builds its own from position/rotation/scale
            # and never reads the argument), so a position passed in would
            # be silently dropped. main.py has always done it this way.
            entity.moveto(object_top_left(obj, tile_height))
            _warn_unrotatable(obj, layer_name)
            depth = resolve_depth(type_name,
                                  properties=obj.properties,
                                  layer_name=layer_name,
                                  class_name=type(entity).__name__,
                                  where=where)
            spawned.append(SpawnedEntity(entity=entity, depth=depth,
                                         layer_name=layer_name,
                                         object_id=obj.id,
                                         type_name=type_name))
        if untyped:
            warn_content(
                "object layer %r has %d object(s) with no Type and spawned "
                "nothing for them: ids %s. That is normal for region markers "
                "and is a typo if it was meant to be an entity."
                % (layer_name, len(untyped), untyped)
            )

    trace_assets("spawn_objects map=%s spawned=%d", document.path, len(spawned))
    return spawned


def spawn_counts(spawned: Iterable[SpawnedEntity]) -> dict[str, int]:
    """How many of each type a pass produced. For logging and for checks."""
    counts: dict[str, int] = {}
    for item in spawned:
        counts[item.type_name] = counts.get(item.type_name, 0) + 1
    return counts
