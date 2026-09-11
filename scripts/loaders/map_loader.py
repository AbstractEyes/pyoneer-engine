"""Turn a map's `<objectgroup>` entries into constructed entities.

`spawn_objects` returns constructed, positioned entities paired with the
depth each one belongs at. It binds NOTHING -- binding needs a scene and a
renderer, so keeping it out leaves the map read path drivable without a
display or a full boot. The caller writes the two-line loop:

    for spawned in spawn_objects(document, defaults=...):
        scene.bind(spawned.depth, spawned.entity)

WHY IT READS MapDocument AND NOT pytmx
--------------------------------------
pytmx casts a custom property only when the file carries `type="int"`, so a
property Tiled wrote without one comes back as the string `'50'` -- truthy,
not `50`, and indexes nothing. `MapProperties` applies the same typing rules
from the same attribute and is also the module that WRITES those properties,
so read and write cannot drift apart.

pytmx is also the wrong reader here because it renumbers gids, and because
it injects a phantom layer for every per-tile collision `<objectgroup>`
inside an embedded tileset (it searches `.//objectgroup` from the map root).
This module takes object groups that are direct descendants of the map, which
is what TMX means by an object layer.

A `pytmx.TiledMap` is still accepted as an argument -- it is what the engine
has in hand at bind time -- but only its `filename` is used, and the
properties are re-read from disk through `MapDocument`.

THE Y-ORIGIN DECISION
---------------------
Tiled does not anchor all objects the same way, and the difference is one
sprite tall:

    rectangle / ellipse / point / polygon    (x, y) is the TOP-left
    tile object (a `gid` attribute)          (x, y) is the BOTTOM-left

`EntityLayer.core_render_blits` always builds its rect with
`image.get_rect(topleft=(position.x, position.y))`, so a gid-backed object is
lifted by its own height on the way in and everything else passes through.
`object_top_left` is that conversion.

The lift uses the OBJECT'S declared height and not the spawned sprite's,
because the object's height is the one an author can see while placing it in
Tiled -- anchoring to the sprite would move an entity the day its spritesheet
gained a row. For a Tiled-authored tile object the two agree anyway.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from scripts.core.errors import PyoneerConfigError, warn_content
from scripts.core.log import trace_assets
from scripts.core.spawn import SPAWN_REGISTRY, resolve_depth, spawn
from scripts.game.behavior import BehaviorRequest, read_requests
from scripts.loaders.map_document import MapDocument, MapObject
from scripts.loaders.table_file import ProjectTables, actor_row

PLAYER_TOKEN: str = "player_input"
"""The behavior token that means "the human drives this one".

Which object is the player is answered from its COMPOSITION rather than from
a flag: no class, no `pyoneer_player` property, no boolean. Two objects of
the same type built from the same config differ by this one string, and the
one carrying it is the one the camera follows.

HERE, in the engine half, and not in the boot file that used to own it. It
is read by `driven_record` below, by `main.py`'s adoption and by its
undriven-player diagnostic, and by the demo boot path -- three readers in
two packages, which is law 2's corollary asking for one spelling. The demo
package imports `main`, so a constant living there would have made the
engine's own record query depend on the game's entry point.

A FILE FORMAT string under law 8: it is what a `.tmx` object's
`pyoneer_behaviors` list spells, so it is stable once referenced and never
renamed. The registry's own declaration of it is the `name=` line in
`scripts/game/behavior/input.py`, and this constant is compared against
`BehaviorRequest.spec.name` -- the resolved spelling -- so the two cannot
drift into agreeing by accident.
"""


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
    behaviors: tuple[BehaviorRequest, ...] = ()
    """What the <object> declared in `pyoneer_behaviors`, resolved not built.

    Records rather than live behaviors, for the same reason this module
    returns entities and binds nothing: the caller acts. `()` for an object
    that declares none.
    """


# ---------------------------------------------------------------------------
# Reading the document
# ---------------------------------------------------------------------------

def as_document(source: Any) -> MapDocument:
    """Coerce a MapDocument, a pytmx.TiledMap or a path into a MapDocument.

    A `pytmx.TiledMap` is re-read FROM DISK via its `filename`, because
    pytmx's parse is what loses the property types. So an in-memory edit made
    through pytmx is NOT visible here; map edits go through `MapDocument` and
    come back via `load_assets(name, reload=True)`.
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


def has_tmx_document(source: Any) -> bool:
    """Can `as_document` re-read this source's .tmx? A native map cannot.

    A native `.blitmap` map also carries a `filename`, but it names a binary
    file, so handing it to `MapDocument.load` is an `ElementTree.ParseError`
    rather than a clean answer.

    The test is the METHOD `object_records`, not the class -- a duck test, so
    `scripts/loaders/` never has to import `config/` to tell the two apart.

    False is not an error: a caller re-reading the document for OPTIONAL
    information such as passability takes it as "this map declares none",
    which is what a `.tmx` with no companion layer answers too. A caller that
    needs the document calls `as_document` and still gets its raise.
    """
    return not callable(getattr(source, "object_records", None))


def object_group_elements(document: MapDocument) -> list[ElementTree.Element]:
    """Every real `<objectgroup>` in the map, in document order.

    "Real" excludes the ones nested inside an embedded `<tileset>`: those are
    per-tile collision shapes, and TMX defines an object LAYER as a child of
    `<map>` (or of a `<group>` under it) and nowhere else. Searching
    `.//objectgroup` from the root instead -- which is what pytmx does --
    yields a phantom layer for every tile that has a collision shape.
    """
    inside_tilesets = {element
                       for tileset in document.root.findall("tileset")
                       for element in tileset.iter("objectgroup")}
    return [element for element in document.root.iter("objectgroup")
            if element not in inside_tilesets]


def object_top_left(obj: MapObject, tile_height: int) -> tuple[float, float]:
    """The object's position translated to the top-left origin the renderer uses.

    A `gid` means Tiled anchored this at the bottom-left, so lift it by its
    height; anything else is already top-left.

    A gid object with no `height` is legal TMX meaning "draw at the tile's
    native size". The map's own tile height is the closest answer available
    without resolving the tileset, and it WARNS rather than guessing quietly,
    because a tile taller than the grid would land one cell low.
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
    it, so an authored rotation would silently do nothing.
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
                  layers: Sequence[str] | None = None,
                  tables: ProjectTables | None = None) -> list[SpawnedEntity]:
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

    `tables` is the project's data tables, read by
    `scripts.loaders.table_file.load_tables`. An object naming a row with
    `pyoneer_actor` gets that row's columns as the MIDDLE rung of parameter
    resolution -- under its own `pyoneer_param_*` properties, over each
    parameter's declared default. None means the caller supplied no tables,
    which is legal until an object names a row; naming one then RAISES rather
    than falling to defaults.

    An object with NO type is skipped, and the skipped ids are reported once
    per layer: untyped objects are ordinary in Tiled, but a misspelled type
    also leaves the field looking empty in the file.
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
            # GameEntity accepts a `transform` keyword and DISCARDS it
            # (GameEntitySimple builds its own from position/rotation/scale),
            # so a position passed in would be silently dropped.
            entity.moveto(object_top_left(obj, tile_height))
            _warn_unrotatable(obj, layer_name)
            depth = resolve_depth(type_name,
                                  properties=obj.properties,
                                  layer_name=layer_name,
                                  class_name=type(entity).__name__,
                                  where=where)
            # Raises on an unknown, duplicated or conflicting token, naming
            # the object. No fallback: a token that resolved to nothing would
            # silently disarm every object carrying it and look like it
            # worked.
            #
            # `actor_row` is the rung between the object's own properties and
            # each parameter's default. It is resolved HERE rather than inside
            # read_requests, because that module never opens a file and this
            # one is the file layer; it answers None for an object with no
            # `pyoneer_actor`.
            behaviors = read_requests(obj.properties,  # #TAG:behaviors_read_at_spawn
                                      actor_row(tables, obj.properties, where),
                                      where=where)
            spawned.append(SpawnedEntity(entity=entity, depth=depth,
                                         layer_name=layer_name,
                                         object_id=obj.id,
                                         type_name=type_name,
                                         behaviors=behaviors))
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


def driven_record(spawned: Iterable[SpawnedEntity]) -> SpawnedEntity | None:
    """The spawned record that carries `PLAYER_TOKEN`, or None.

    "Which object is the player", answered from the composition rather than
    from a flag. A query over what `spawn_objects` returned, in the shape
    `spawn_counts` above already has: it reads records and builds nothing, so
    it is drivable without a scene, a renderer or a display.

    `SpawnedEntity.behaviors` holds RESOLVED `BehaviorRequest`s, so the token
    is compared against `spec.name` -- the registry's own spelling -- and not
    against a substring of the raw property, which would also match a future
    `player_input_recorder`.

    ONE DEFINITION, TWO CALLERS, AND THAT IS THE WHOLE REASON IT IS HERE.
    The boot path picks its player this way and the demo boot path picked its
    camera target the same way under its own name, which is law 2's corollary
    at three lines -- the corollary that was paid once at 425 duplicate
    lines. The copy is gone and both callers call this. The direction is the
    engine's: `demos/` imports `main`, `main` imports `scripts/`, and nothing
    in `scripts/` may name either, so the shared half can only live here.

    Returns None rather than raising, and for both empty cases: a map whose
    object layer places nobody, and one whose objects are all undriven. That
    is a real authored state -- a cutscene map, a title screen -- and the
    callers each decide what to do about it. `main.py` additionally WARNS
    when the body it adopted is not this one, which is the diagnostic half
    this query deliberately does not carry: a query that complained could not
    be used to ask a question.
    """
    for record in spawned:
        if any(request.spec.name == PLAYER_TOKEN
               for request in record.behaviors):
            return record
    return None
