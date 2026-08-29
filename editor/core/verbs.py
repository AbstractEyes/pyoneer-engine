"""The command vocabulary.

Importing this module is what populates the registry, so
`editor.core.commands.all_verbs()` is empty until something imports
`editor.core.verbs`. `editor/core/session.py` does it once; nothing else
should need to.

EVERY VERB RETURNS ITS INVERSE
------------------------------
Not a snapshot -- the actual command that undoes it. That is what makes the
undo stack readable, serialisable, and identical in kind to the forward
stream. If a verb cannot express its own inverse as a command, that is a
sign the vocabulary is missing a verb, and the fix is to add it (which is
why `table.column.restore` and `table.restore` exist).

WHERE HARD RULES BITE
---------------------
Three places, all of them "you are about to make the game unloadable":

  table.drop            on a table the genre marks required
  table.column.remove   on a column the genre marks required
  map.object.remove     never hard -- a map is allowed to be half-built

Everything else is a soft rule and surfaces in Problems.
"""
from __future__ import annotations

import os
import warnings
from typing import Any

from editor.core.commands import Command, Param, command
from editor.core.errors import (
    PyoneerCommandArgumentError,
    PyoneerRuleViolationError,
)
from editor.core.project import Column, DataTable, Project
from editor.core.scope import Scope
from editor.core import genre as genre_module
from editor.core import layers as layer_module
from editor.core import map_events as map_event_module
# The collision vocabulary through the editor's re-export, never a second
# copy of it. `BLITMASK_SUFFIX` is the extension the .tileset format already
# validates a mask reference against, so it is spelled once there.
from editor.core.collision import (
    DEFAULTS_PROPERTY,
    NO_DATA,
    Blitmask,
    TilesetDefaults,
    is_opinion,
)
from scripts.loaders.tileset_file import BLITMASK_SUFFIX
from scripts.game.behavior.base import BEHAVIORS
# The engine's own name->depth lookup, so `map.layer.add` asks exactly the
# question `MapDocument.add_layer` asks before it advises about a depth.
from scripts.core.depth import resolve_layer_depth
from scripts.core.errors import PyoneerContentWarning


def _layer_keys() -> list[str]:
    return [capability.key for capability in layer_module.CAPABILITIES]


def _action_keys() -> tuple[str, ...]:
    return tuple(capability.key for capability in map_event_module.FIELDS)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _tile_layer(project: Project, scope: Scope):
    document = project.map(scope.require("map"))
    return document.tile_layer(scope.require("layer"))


def _object_layer(project: Project, scope: Scope):
    document = project.map(scope.require("map"))
    return document.object_layer(scope.require("layer"))


def _object(project: Project, scope: Scope):
    layer = _object_layer(project, scope)
    raw_id = scope.require("object")
    try:
        object_id = int(raw_id)
    except ValueError:
        raise PyoneerCommandArgumentError(
            f"object id must be an integer, got {raw_id!r}",
            scope=str(scope)) from None
    found = layer.find(object_id)
    if found is None:
        raise PyoneerCommandArgumentError(
            f"object {object_id} is not in layer {layer.name!r}",
            scope=str(scope),
            present=[o.id for o in layer.objects()][:20])
    return found


def _layer_scope(scope: Scope) -> Scope:
    """`map:t/layer:L/object:3` -> `map:t/layer:L`."""
    return Scope.of(("map", scope.require("map")), ("layer", scope.require("layer")))


def _table_scope(scope: Scope) -> Scope:
    return Scope.of(("table", scope.require("table")))


# --------------------------------------------------------------------------
# Tiles
# --------------------------------------------------------------------------

@command(
    "map.tile.set",  # #TAG:map.tile.set
    summary="Set one tile's gid. gid 0 clears the tile.",
    scopes=["map:*/layer:*"],
    params=[
        Param("x", int, "column, 0-based from the left"),
        Param("y", int, "row, 0-based from the top"),
        Param("gid", int, "global tile id from the map's tilesets; 0 is empty"),
    ],
    example='{"verb": "map.tile.set", "scope": "map:test/layer:Floor",'
            ' "args": {"x": 4, "y": 7, "gid": 65}}',
)
def _tile_set(project: Project, cmd: Command) -> Command | None:
    layer = _tile_layer(project, cmd.scope)
    x, y, gid = cmd.args["x"], cmd.args["y"], cmd.args["gid"]
    previous = layer.get_tile(x, y)
    if not layer.set_tile(x, y, gid):
        return None
    return Command("map.tile.set", cmd.scope, {"x": x, "y": y, "gid": previous})


@command(
    "map.tile.set_many",  # #TAG:map.tile.set_many
    summary="Set many tiles at once. Cheaper and more readable than one "
            "command per tile, and it undoes as a single step.",
    scopes=["map:*/layer:*"],
    params=[
        Param("tiles", list, "a list of [x, y, gid] triples, all integers"),
    ],
    example='{"verb": "map.tile.set_many", "scope": "map:test/layer:Floor",'
            ' "args": {"tiles": [[0, 0, 65], [1, 0, 65], [2, 0, 66]]}}',
)
def _tile_set_many(project: Project, cmd: Command) -> Command | None:
    layer = _tile_layer(project, cmd.scope)
    triples = cmd.args["tiles"]
    parsed: list[tuple[int, int, int]] = []
    for index, item in enumerate(triples):
        if (not isinstance(item, (list, tuple)) or len(item) != 3
                or not all(isinstance(v, int) and not isinstance(v, bool) for v in item)):
            raise PyoneerCommandArgumentError(
                f"tiles[{index}] must be [x, y, gid] of three ints, got {item!r}",
                verb=cmd.verb)
        parsed.append((int(item[0]), int(item[1]), int(item[2])))

    undo: list[list[int]] = []
    for x, y, gid in parsed:
        previous = layer.get_tile(x, y)
        if layer.set_tile(x, y, gid):
            undo.append([x, y, previous])
    if not undo:
        return None
    return Command("map.tile.set_many", cmd.scope, {"tiles": undo})


@command(
    "map.tile.fill",  # #TAG:map.tile.fill
    summary="Set every tile in a rectangle. The rectangle is clipped to the "
            "layer, so an over-large brush is a partial fill, not an error.",
    scopes=["map:*/layer:*"],
    params=[
        Param("x", int, "left column"),
        Param("y", int, "top row"),
        Param("width", int, "columns"),
        Param("height", int, "rows"),
        Param("gid", int, "global tile id; 0 clears"),
    ],
    example='{"verb": "map.tile.fill", "scope": "map:test/layer:Floor",'
            ' "args": {"x": 0, "y": 0, "width": 8, "height": 4, "gid": 65}}',
)
def _tile_fill(project: Project, cmd: Command) -> Command | None:
    layer = _tile_layer(project, cmd.scope)
    x, y = cmd.args["x"], cmd.args["y"]
    width, height = cmd.args["width"], cmd.args["height"]
    if width < 0 or height < 0:
        raise PyoneerCommandArgumentError(
            f"fill needs a non-negative size, got {width}x{height}", verb=cmd.verb)

    left, top = max(0, x), max(0, y)
    right = min(layer.width, x + width)
    bottom = min(layer.height, y + height)

    undo: list[list[int]] = []
    for row in range(top, bottom):
        for column in range(left, right):
            previous = layer.get_tile(column, row)
            if previous != cmd.args["gid"]:
                undo.append([column, row, previous])

    if layer.fill((x, y, width, height), cmd.args["gid"]) == 0:
        return None
    return Command("map.tile.set_many", cmd.scope, {"tiles": undo})


# --------------------------------------------------------------------------
# Layers
# --------------------------------------------------------------------------

@command(
    "map.layer.add",  # #TAG:map.layer.add
    summary="Add a tile or object layer. A tile layer is created at the "
            "map's size unless width/height or subcell say otherwise. Note "
            "that a layer only RENDERS if its name has a depth in "
            "scripts/core/depth.py and it has not said renders=false.",
    scopes=["map:*"],
    params=[
        Param("name", str, "layer name; it is also the key the engine "
                           "resolves to a draw depth"),
        Param("kind", str, "what sort of layer", required=False,
              default="tile", choices=("tile", "object")),
        Param("group", str, "name of a Tiled <group> to put it in; empty "
                            "means beside the existing layers of its kind",
              required=False, default=""),
        Param("fill", int, "gid to fill a new tile layer with; 0 is empty",
              required=False, default=0),
        Param("index", int, "position among its siblings; omit to append",
              required=False, default=None),
        Param("width", int, "columns in a new tile layer; omit for the "
                            "map's own width. A passability companion is "
                            "wider than the map when it is finer than it",
              required=False, default=None),
        Param("height", int, "rows in a new tile layer; omit for the map's "
                             "own height",
              required=False, default=None),
        Param("subcell", int, "sub-cells per map tile along each axis. "
                              "Sizes the layer at subcell x the map AND "
                              "declares pyoneer_subcell on it, in one "
                              "command, because a layer that is one without "
                              "the other is a map that does not load",
              required=False, default=None),
        Param("renders", bool, "does this layer DRAW? False declares "
                               "pyoneer_renders=false on it in the same "
                               "command, which is what a passability "
                               "companion is: mask numbers, read as gids, "
                               "that paint the mask vocabulary over the map "
                               "if anything ever draws them. A layer created "
                               "this way is also not advised to get a depth, "
                               "because it has just said it does not draw",
              required=False, default=True),
    ],
    example='{"verb": "map.layer.add", "scope": "map:test",'
            ' "args": {"name": "Hazard", "kind": "tile"}}',
)
def _layer_add(project: Project, cmd: Command) -> Command:
    """Create a layer, at a size the caller may choose.

    `subcell` is why width and height are arguments at all: a 4x passability
    companion is four times the map on each axis.

    The inverse needs no new argument. `map.layer.remove` serializes the
    element it takes out -- its `width=`, its `height=`, its `<properties>`
    and its csv -- and restores that XML verbatim, so undo is byte-exact for
    a 4x companion as it is for a map-sized one, and for one carrying
    `pyoneer_renders`.

    `renders=False` declares AND silences, for the same reason `subcell`
    sizes and declares: a companion added without the declaration is a layer
    the engine is free to draw the day its name gains a depth, and the
    document's "give this name a depth" advice is wrong for a layer that is
    about to say it does not draw at all.
    """
    document = project.map(cmd.scope.require("map"))
    name = cmd.args["name"]
    before = document.root.get("nextlayerid", "1")
    # `add_layer` warns when the name resolves to no depth, which is right
    # for art and wrong here -- and it cannot tell the two apart, because
    # the declaration below does not exist yet when it runs. Narrowed to
    # the case where that one advisory is the only content warning the call
    # can raise: a layer that will not draw, whose name has no depth.
    silence = not cmd.args["renders"] and resolve_layer_depth(name) is None
    with warnings.catch_warnings():
        if silence:
            warnings.simplefilter("ignore", PyoneerContentWarning)
        layer = document.add_layer(name, cmd.args["kind"],
                                   group=cmd.args["group"] or None,
                                   index=cmd.args["index"],
                                   fill=cmd.args["fill"],
                                   width=cmd.args["width"],
                                   height=cmd.args["height"],
                                   subcell=cmd.args["subcell"])
    if not cmd.args["renders"]:
        # Through the same capability table `map.layer.set` writes, so the
        # property name and its type come from one declaration.
        capability = layer_module.BY_KEY["renders"]
        layer.properties[capability.property_name] = capability.coerce(False)
    return Command("map.layer.remove",
                   cmd.scope.child("layer", name),
                   {"next_layer_id": before})


@command(
    "map.layer.remove",  # #TAG:map.layer.remove
    summary="Remove a layer and everything on it. The inverse restores the "
            "whole element, its tiles included.",
    scopes=["map:*/layer:*"],
    params=[
        Param("next_layer_id", str, "restore the map's nextlayerid to this "
                                    "after removing; used by undo",
              required=False, default=""),
    ],
    destructive=True,
)
def _layer_remove(project: Project, cmd: Command) -> Command:
    document = project.map(cmd.scope.require("map"))
    name = cmd.scope.require("layer")
    payload = document.serialize_layer(name)
    if payload is None:
        raise PyoneerCommandArgumentError(
            f"no layer named {name!r} to remove",
            verb=cmd.verb, available=document.layer_names())
    if not document.remove_layer(name):
        raise PyoneerCommandArgumentError(
            f"layer {name!r} could not be removed", verb=cmd.verb)
    if cmd.args["next_layer_id"]:
        document.root.set("nextlayerid", cmd.args["next_layer_id"])
    return Command("map.layer.restore",
                   Scope.of(("map", cmd.scope.require("map"))),
                   {"payload": payload})


def _layer_element(project: Project, scope: Scope):
    """The TileLayer or ObjectLayer a layer scope points at."""
    document = project.map(scope.require("map"))
    name = scope.require("layer")
    if name in document.tile_layer_names():
        return document.tile_layer(name)
    if name in document.object_layer_names():
        return document.object_layer(name)
    raise PyoneerCommandArgumentError(
        f"no layer named {name!r}", scope=str(scope),
        available=document.layer_names())


@command(
    "map.layer.set",  # #TAG:map.layer.set
    summary="Declare a capability on a layer -- depth, motion, parallax, "
            "opacity, occlusion, passability, whether it renders at all. "
            "Stored as a tmx custom property, so Tiled shows it too.",
    scopes=["map:*/layer:*"],
    params=[
        Param("key", str, "capability name without the pyoneer_ prefix",
              choices=tuple(_layer_keys())),
        Param("value", object, "int, float, str or bool, matching the "
                               "capability's declared type"),
    ],
    example='{"verb": "map.layer.set", "scope": "map:test/layer:Paralax",'
            ' "args": {"key": "parallax_x", "value": 0.5}}',
)
def _layer_set(project: Project, cmd: Command) -> Command | None:
    layer = _layer_element(project, cmd.scope)
    key, value = cmd.args["key"], cmd.args["value"]
    try:
        checked = layer_module.validate_property(key, value)
    except ValueError as exc:
        raise PyoneerCommandArgumentError(str(exc), verb=cmd.verb) from None

    name = layer_module.PREFIX + key
    existing = layer.properties.as_dict()
    if name in existing and existing[name] == checked:
        return None
    layer.properties[name] = checked
    if name in existing:
        return Command("map.layer.set", cmd.scope,
                       {"key": key, "value": existing[name]})
    return Command("map.layer.unset", cmd.scope, {"key": key})


@command(
    "map.layer.unset",  # #TAG:map.layer.unset
    summary="Remove a declared capability, returning the layer to the "
            "default. The inverse of setting one that was not there.",
    scopes=["map:*/layer:*"],
    params=[Param("key", str, "capability name without the pyoneer_ prefix")],
    destructive=True,
)
def _layer_unset(project: Project, cmd: Command) -> Command | None:
    layer = _layer_element(project, cmd.scope)
    name = layer_module.PREFIX + cmd.args["key"]
    existing = layer.properties.as_dict()
    if name not in existing:
        return None
    del layer.properties[name]
    return Command("map.layer.set", cmd.scope,
                   {"key": cmd.args["key"], "value": existing[name]})


@command(
    "map.layer.restore",  # #TAG:map.layer.restore
    summary="Put a layer back from a serialised payload, at its original "
            "position and with its original whitespace. The exact inverse "
            "of map.layer.remove; rarely written by hand.",
    scopes=["map:*"],
    params=[Param("payload", dict, "as produced by MapDocument.serialize_layer")],
)
def _layer_restore(project: Project, cmd: Command) -> Command:
    document = project.map(cmd.scope.require("map"))
    name = document.restore_layer(cmd.args["payload"])
    return Command("map.layer.remove", cmd.scope.child("layer", name))


# --------------------------------------------------------------------------
# Tilesets
#
# The only edit in this vocabulary that can corrupt something it never
# touched. Every csv token and every `<object gid=...>` in a map is an index
# into the concatenated firstgid ranges, so pulling a tileset out from under
# a painted gid raises NOWHERE: pytmx sorts firstgids descending and returns
# the first one at or below the gid, which means an orphan silently resolves
# to the tileset underneath and paints the wrong art.
#
# MapDocument.remove_tileset refuses in that case and names the layers and
# counts that block it. These verbs let that refusal through unchanged:
# rewording it would cost the caller the part that says how to proceed.
# --------------------------------------------------------------------------

def _tileset_key(cmd: Command) -> str | int:
    """Which tileset a command addresses: its name, or its firstgid.

    Both forms, because a name alone cannot address every tileset a map can
    hold. An external `<tileset firstgid="9" source="foo.tsx"/>` carries no
    name in this file at all -- and those are exactly the tilesets whose
    contents the document cannot see, so being unable to name them is the
    worst possible combination.
    """
    name, first_gid = cmd.args["name"], cmd.args["first_gid"]
    if name:
        return name
    if first_gid > 0:
        return first_gid
    raise PyoneerCommandArgumentError(
        f"{cmd.verb} needs `name`, or `first_gid` for an external tileset "
        "that has none", verb=cmd.verb)


@command(
    "map.tileset.add",  # #TAG:map.tileset.add
    summary="Add an embedded tileset, appended above every gid range the "
            "map already uses. Anything left unset is measured rather than "
            "assumed: tile size defaults to the map's, the image is sized "
            "from its own header, and columns/tilecount fall out of the "
            "grid. Inserting BELOW an existing range is refused -- it would "
            "renumber every csv token in the file. Passing a first_gid "
            "ABOVE it is how a tileset is given room to grow into later.",
    scopes=["map:*"],
    params=[
        Param("name", str, "tileset name; unique within the map, and the key "
                           "the other tileset verbs address it by"),
        Param("image", str, "the sheet's path AS WRITTEN INTO THE FILE -- "
                            "relative to the .tmx, which is what Tiled and "
                            "the engine both resolve it against"),
        Param("tile_width", int, "tile width in pixels; omit to inherit the "
                                 "map's", required=False, default=None),
        Param("tile_height", int, "tile height in pixels; omit to inherit the "
                                  "map's", required=False, default=None),
        Param("margin", int, "border in pixels before the first tile",
              required=False, default=0),
        Param("spacing", int, "pixels between adjacent tiles",
              required=False, default=0),
        Param("image_width", int, "sheet width in pixels; omit and the PNG "
                                  "header is read", required=False, default=None),
        Param("image_height", int, "sheet height in pixels; omit and the PNG "
                                   "header is read", required=False, default=None),
        Param("columns", int, "override the derived column count; only for a "
                              "sheet whose grid the formula cannot describe",
              required=False, default=None),
        Param("tile_count", int, "override the derived tile count",
              required=False, default=None),
        Param("first_gid", int, "the range this tileset claims, instead of "
                                "the packed one. Above every range in use, "
                                "never below one -- the gap it leaves is "
                                "HEADROOM, and map.tileset.grow spends it "
                                "later without renumbering a single cell",
              required=False, default=0),
    ],
    example='{"verb": "map.tileset.add", "scope": "map:test", "args":'
            ' {"name": "Dungeon",'
            ' "image": "../graphics/tilesets/System/Dungeon.png"}}',
)
def _tileset_add(project: Project, cmd: Command) -> Command:
    document = project.map(cmd.scope.require("map"))
    added = document.add_tileset(
        cmd.args["name"], cmd.args["image"],
        tile_width=cmd.args["tile_width"],
        tile_height=cmd.args["tile_height"],
        margin=cmd.args["margin"],
        spacing=cmd.args["spacing"],
        columns=cmd.args["columns"],
        tile_count=cmd.args["tile_count"],
        image_width=cmd.args["image_width"],
        image_height=cmd.args["image_height"],
        first_gid=cmd.args["first_gid"] or None,
    )
    # force stays FALSE, deliberately. Taking an add back is only safe while
    # nothing points into the range it created, and the refusal IS the
    # signal that something does -- which happens when a later transaction
    # painted with the new sheet and this one is being unwound out of order.
    # An inverse that forced its way through would leave those tiles
    # resolving to the tileset below, and nothing downstream would say so.
    return Command("map.tileset.remove", cmd.scope,
                   {"name": added.name, "force": False})


@command(
    "map.tileset.remove",  # #TAG:map.tileset.remove
    summary="Remove a tileset by name, or by firstgid for an external one. "
            "REFUSED while any tile or tile-object still points into its "
            "gid range: an orphaned gid raises nowhere, it just paints the "
            "wrong art. The inverse restores the element verbatim, so undo "
            "brings back every <tile> child with it.",
    scopes=["map:*"],
    params=[
        Param("name", str, "tileset name; leave empty and pass first_gid for "
                           "an external <tileset source=...>, which carries "
                           "no name in this file",
              required=False, default=""),
        Param("first_gid", int, "address the tileset by its firstgid instead "
                                "of its name", required=False, default=0),
        Param("force", bool, "remove even though gids still point into the "
                             "range. Correct in exactly one situation: those "
                             "gids were zeroed EARLIER IN THE SAME "
                             "transaction, so undo puts the tileset back "
                             "before it puts the gids back. map.tile.set_many "
                             "is the verb that zeroes them and its inverse is "
                             "exact. Outside that, this silently repaints "
                             "every orphaned tile with the wrong art.",
              required=False, default=False),
    ],
    destructive=True,
    example='{"verb": "map.tileset.remove", "scope": "map:test",'
            ' "args": {"name": "Dungeon"}}',
)
def _tileset_remove(project: Project, cmd: Command) -> Command:
    document = project.map(cmd.scope.require("map"))
    key = _tileset_key(cmd)

    # Serialize BEFORE removing. The payload IS the inverse, and it has to
    # come off the live element rather than be rebuilt from a TilesetRef's
    # attributes: a rebuilt <tileset> carries no <tile> children, so undo
    # would drop per-tile animations, terrain definitions and collision
    # shapes without a word. That is the same way map.object.remove once
    # destroyed polygons.
    payload = document.serialize_tileset(key)
    if payload is None:
        raise PyoneerCommandArgumentError(
            f"no tileset {key!r} in this map",
            verb=cmd.verb,
            available=document.tileset_names(),
            first_gids=[ref.first_gid for ref in document.tilesets()])

    # The refusal travels out of here untouched.
    document.remove_tileset(key, force=cmd.args["force"])
    return Command("map.tileset.restore", cmd.scope, {"payload": payload})


@command(
    "map.tileset.restore",  # #TAG:map.tileset.restore
    summary="Put a tileset back from a serialised payload, at its original "
            "position and with its original whitespace. The exact inverse "
            "of map.tileset.remove; rarely written by hand.",
    scopes=["map:*"],
    params=[
        Param("payload", dict, "as produced by MapDocument.serialize_tileset; "
                               "must carry `first_gid`, which is the only key "
                               "that addresses every tileset a map can hold"),
    ],
)
def _tileset_restore(project: Project, cmd: Command) -> Command:
    document = project.map(cmd.scope.require("map"))
    payload = cmd.args["payload"]

    # Check the payload can be ADDRESSED before restoring it, not after. A
    # restore that succeeds and then cannot describe its own inverse leaves
    # a mutation the transaction has no way to roll back.
    try:
        first_gid = int(payload.get("first_gid", 0))
    except (TypeError, ValueError):
        first_gid = 0
    if first_gid <= 0:
        raise PyoneerCommandArgumentError(
            "a tileset payload needs a positive 'first_gid'; it is what the "
            "inverse addresses an external tileset by, since that kind has "
            "no name in this file",
            verb=cmd.verb, got=sorted(payload))

    name = document.restore_tileset(payload)
    # force=True here, where map.tileset.add's inverse says False. An add
    # creates a range that did not exist, so taking it back can orphan tiles
    # painted into it since, and the guard has real work to do. A restore
    # only puts back what was just taken out, and anything that painted into
    # the range meanwhile is a later command whose inverse runs FIRST.
    # Without force this would also be unusable on an external tileset, whose
    # extent lives in the .tsx: the guard would refuse to undo its own undo.
    if name:
        return Command("map.tileset.remove", cmd.scope,
                       {"name": name, "force": True})
    return Command("map.tileset.remove", cmd.scope,
                   {"first_gid": first_gid, "force": True})


# --------------------------------------------------------------------------
@command(
    "map.tileset.grow",  # #TAG:map.tileset.grow
    summary="Point a tileset at a re-cut sheet and change how many tiles it "
            "owns, without moving one placed gid. This is how a tileset "
            "stops being a fixed-size sheet: crop the region you want out of "
            "any image, write it under the old rows at the SAME WIDTH, and "
            "grow the count. Rows are the only safe axis -- a local tile id "
            "is row * columns + column and every reader takes that stride "
            "from the sheet's width, so a wider sheet renumbers every id "
            "after the first row and repaints the map with nothing raised. A "
            "wider sheet is refused, and so is growing into a range another "
            "tileset already owns, which pytmx resolves two contradictory "
            "ways. Shrinking is the same verb with a smaller count and is "
            "refused while any tile still points into the part that would go. "
            "The inverse restores the image path, both of its dimensions and "
            "the tile count -- the four values this writes and the only four.",
    scopes=["map:*"],
    params=[
        Param("name", str, "tileset name; leave empty and pass first_gid for "
                           "an external <tileset source=...>, which carries "
                           "no name in this file",
              required=False, default=""),
        Param("first_gid", int, "address the tileset by its firstgid instead "
                                "of its name", required=False, default=0),
        Param("image", str, "the sheet's new path AS WRITTEN INTO THE FILE, "
                            "relative to the .tmx; empty keeps the image it "
                            "already has and changes only the count",
              required=False, default=""),
        Param("image_width", int, "the new sheet's width in pixels; omit and "
                                  "the PNG header is read. It must still cut "
                                  "into the same number of columns",
              required=False, default=None),
        Param("image_height", int, "the new sheet's height in pixels; omit "
                                   "and the PNG header is read",
              required=False, default=None),
        Param("tile_count", int, "how many tiles the tileset owns afterwards; "
                                 "omit for every tile the new sheet holds, "
                                 "and pass a smaller number to truncate a "
                                 "ragged last row",
              required=False, default=None),
    ],
    example='{"verb": "map.tileset.grow", "scope": "map:test", "args":'
            ' {"name": "Dungeon", "image": "../graphics/Dungeon.png",'
            ' "tile_count": 96}}',
)
def _tileset_grow(project: Project, cmd: Command) -> Command | None:
    document = project.map(cmd.scope.require("map"))
    key = _tileset_key(cmd)
    previous = document.grow_tileset(
        key,
        image_source=cmd.args["image"] or None,
        image_width=cmd.args["image_width"],
        image_height=cmd.args["image_height"],
        tile_count=cmd.args["tile_count"])

    after = document.tileset(key)
    image = after.element.find("image")
    if (previous["image"] == image.get("source", "")
            and previous["image_width"] == int(image.get("width"))
            and previous["image_height"] == int(image.get("height"))
            and previous["tile_count"] == after.tile_count):
        # Nothing moved, so there is nothing to undo. A no-op that still
        # pushed an inverse would put a step in the undo list that reads
        # like an edit and restores the values it already found.
        return None

    # The inverse SHRINKS, and it goes through the same orphan guard the
    # forward call does. That is deliberate and it is the same bargain
    # map.tileset.add's inverse strikes: if a later command painted into the
    # rows this one added, its own inverse runs first and clears them. An
    # inverse that forced its way past the guard would leave those gids
    # resolving to the tileset below, silently, with the wrong art.
    return Command("map.tileset.grow", cmd.scope, {
        "name": cmd.args["name"], "first_gid": cmd.args["first_gid"],
        "image": previous["image"],
        "image_width": previous["image_width"],
        "image_height": previous["image_height"],
        "tile_count": previous["tile_count"]})


@command(
    "map.tileset.rename",  # #TAG:map.tileset.rename
    summary="Rename a tileset. No gid moves -- a name is not part of the "
            "numbering -- but it is the key every other tileset verb "
            "addresses one by, and a .blitmask stores it in its own header. "
            "The engine REFUSES to load a map whose masks name a different "
            "tileset, so when the sidecar names the old one this rewrites "
            "that line in the same transaction. It does not rename the "
            "sidecar FILE: the tileset declares its path with "
            "pyoneer_collision and a mask file may be deliberately shared. "
            "The inverse is this verb with the two names swapped, which puts "
            "the header back too.",
    scopes=["map:*"],
    params=[
        Param("name", str, "the tileset's current name; leave empty and pass "
                           "first_gid to address it by range",
              required=False, default=""),
        Param("first_gid", int, "address the tileset by its firstgid instead "
                                "of its name", required=False, default=0),
        Param("to", str, "the new name; unique within the map, and non-empty "
                         "because it is an address"),
    ],
    example='{"verb": "map.tileset.rename", "scope": "map:test", "args":'
            ' {"name": "TileA2", "to": "Village exteriors"}}',
)
def _tileset_rename(project: Project, cmd: Command) -> Command | None:
    document = project.map(cmd.scope.require("map"))
    key = _tileset_key(cmd)
    ref = document.tileset(key)
    previous, wanted = ref.name, cmd.args["to"]
    if wanted == previous:
        return None

    # Read the sidecar BEFORE the attribute moves, and write it AFTER. A
    # mask file that cannot be read then leaves the document exactly as it
    # was found, rather than leaving a .tmx whose name the masks contradict
    # -- which is a map `tileset_defaults` refuses to load at all.
    # `_mask_file_path` lives with the mask verbs below; it is the same
    # arithmetic they use, spelled once.
    reference = str(document.properties_of(ref.element)
                    .get(DEFAULTS_PROPERTY, "") or "").strip()
    grid, resolved = None, ""
    if reference:
        resolved = _mask_file_path(document, reference, cmd)
        if os.path.isfile(resolved):
            grid = Blitmask.load(resolved)
        else:
            warnings.warn(
                f"tileset {previous!r} declares {DEFAULTS_PROPERTY}="
                f"{reference!r}, which resolves to {resolved} and is not "
                f"there, so this rename cannot carry its masks with it. The "
                f"map already refuses to load until that file is restored or "
                f"the property removed.", PyoneerContentWarning)

    document.rename_tileset(key, wanted)

    if grid is not None and str(grid.meta.get("name", "") or "") == previous:
        # Assigning an existing key keeps its position in the dict, and
        # `render` walks the metadata in that order -- so this is one line of
        # the file, not a reshuffled header.
        meta = dict(grid.meta)
        meta["name"] = wanted
        Blitmask(grid.width, grid.height, grid.opinions, meta).save(resolved)

    # Addressed by the NEW name rather than by whatever this call was given:
    # a tileset that was addressed by firstgid still has a name afterwards,
    # and the name is the key that survives a firstgid this verb never reads.
    return Command("map.tileset.rename", cmd.scope,
                   {"name": wanted, "first_gid": 0, "to": previous})


# Tile masks -- level one of the collision stack, authored from the editor
#
# `scripts/core/collision_runtime.py` reads a tileset's per-tile masks out of
# a `.blitmask` named by the `pyoneer_collision` property on the `<tileset>`
# element, and `field_from_map` stacks that level UNDER every companion so a
# painted cell still wins. These two verbs author both halves: the property
# on the element, and the sidecar it names.
#
# THE FILE IS PROVISIONED, NOT ASKED ABOUT
# ----------------------------------------
# `map.tileset.mask.set` writes the `.blitmask` when it is not there, the
# same call the first collision stroke makes for `Collision.png`.
#
# WHAT HAS NO INVERSE, AND WHY THAT IS SOUND        #TAG:written_file_has_no_inverse
# ------------------------------------------
# Three things can change: one cell of the sidecar, the tmx property, and the
# sidecar's EXISTENCE. The first two are inverted exactly, and the inverse
# carries the opinion and the reference it FOUND rather than ones it could
# re-derive. The third is not inverted: undo leaves the file on disk,
# all-NO_DATA if this verb created it. A grid of no-data reads exactly as a
# tileset with no masks at all -- once the property is gone
# `tileset_defaults` never opens the file -- so the baked field is identical
# either way, and the .tmx, which is what undo is contracted to restore,
# comes back byte for byte. An undo that DELETED a file could destroy work
# the author put there.
#
# GROWING a short mask is in the same class. Masking only the first three
# rows of a 24-row sheet is legal, so setting a tile below that adds rows;
# the added rows are NO_DATA, and undo restores the cell rather than the row
# count.
#
# WHY TWO VERBS AND NOT ONE
# -------------------------
# `restore` is the exact inverse of `set` and of itself, because the cell and
# the declaration have to come back TOGETHER: putting the cell back without
# removing a declaration this call created leaves the tmx one property
# heavier than it was found.
# --------------------------------------------------------------------------

def _tileset_for_mask(project: Project, cmd: Command):
    """The `<tileset>` a mask verb addresses, and the document holding it.

    The two refusals are `tileset_defaults`' own, moved forward to authoring
    time so that nothing is written the engine would then refuse to load. A
    mask grid is row-major over the sheet, so with no `columns` there is no
    arithmetic from a tile id to a cell of it; and with no tile count nothing
    can say which gids the tileset owns, which is the state in which every
    tile silently reads as having no mask.
    """
    document = project.map(cmd.scope.require("map"))
    ref = document.tileset(_tileset_key(cmd))
    label = ref.name or ref.source or ref.first_gid
    if not ref.extent_known:
        raise PyoneerCommandArgumentError(
            f"tileset {label!r} does not say which gids it owns -- an "
            f"external tileset keeps its tilecount in the .tsx, and an "
            f"embedded one may omit it. Without an extent every tile would "
            f"silently read as having no mask",
            verb=cmd.verb, first_gid=ref.first_gid)
    if ref.columns <= 0:
        raise PyoneerCommandArgumentError(
            f"tileset {label!r} declares no columns, and a mask grid is "
            f"row-major over the sheet -- with no column count there is no "
            f"way from a tile id to a cell of the mask",
            verb=cmd.verb, first_gid=ref.first_gid)
    return document, ref


def _declared_mask_reference(document, ref, cmd: Command) -> str:
    """The tileset's `pyoneer_collision` value EXACTLY as the file spells it,
    or "" when it declares none.

    Exactly, because this string is what an inverse writes back, and a
    stripped or re-typed copy of it is a .tmx that does not come back byte
    for byte. The two shapes that cannot survive that round trip are refused
    here rather than quietly rewritten: a property present but blank would be
    indistinguishable from an absent one in the inverse, and one declared
    `type="int"` would come back as a string.
    """
    raw = document.properties_of(ref.element).get(DEFAULTS_PROPERTY)
    label = ref.name or ref.first_gid
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise PyoneerCommandArgumentError(
            f"tileset {label!r} declares {DEFAULTS_PROPERTY} as "
            f"{type(raw).__name__} ({raw!r}); a mask reference is a path, and "
            f"rewriting the property's type here would change bytes this verb "
            f"never meant to touch", verb=cmd.verb)
    if not raw.strip():
        raise PyoneerCommandArgumentError(
            f"tileset {label!r} declares {DEFAULTS_PROPERTY} with no value. "
            f"The engine reads that as no masks at all, and an undo could not "
            f"tell it apart from the property being absent -- remove it, or "
            f"give it a {BLITMASK_SUFFIX} path", verb=cmd.verb)
    return raw


def _conventional_mask_reference(ref, cmd: Command) -> str:
    """Where a tileset's masks go when it does not say: in the image's own
    directory, named after the TILESET.

    Beside the art, because that is where `TilesetDefaults` says the file
    belongs -- its grid is row-major over the sheet, so the file laid beside
    the image reads as the image -- and because a sheet shared by five maps
    then has ONE mask file rather than five copies that drift.

    Named after the TILESET and not after the image: two `<tileset>` elements
    may point at one sheet with different geometry and different firstgids,
    and one mask file cannot be both. `to_blitmask` stores the tileset's name
    in the file and `tileset_defaults` raises when it disagrees, so an
    image-derived name would let one tileset's first authored mask break the
    other's map. Path separators in the name are replaced rather than
    honoured, as `blitmap.tileset_reference` does: a tileset called
    `System/TileA2` must not write outside the directory it was given.
    """
    if not ref.image_source:
        raise PyoneerCommandArgumentError(
            f"tileset {ref.name or ref.first_gid!r} declares no image in this "
            f"map, so there is nowhere obvious to put its masks. Declare "
            f"{DEFAULTS_PROPERTY} on the tileset, or name the file with "
            f"map.tileset.mask.restore's `reference`", verb=cmd.verb)
    if not ref.name:
        raise PyoneerCommandArgumentError(
            f"the tileset at firstgid {ref.first_gid} has no name, and a mask "
            f"file is named after the tileset rather than after the sheet "
            f"(two tilesets may share one sheet). Name it, or declare "
            f"{DEFAULTS_PROPERTY} yourself", verb=cmd.verb)
    stem = ref.name.replace("/", "_").replace("\\", "_") + BLITMASK_SUFFIX
    # Forward slashes, because that is how a .tmx spells a path and how the
    # `<image source=>` sitting beside this reference is already spelled.
    directory = os.path.dirname(ref.image_source)
    return f"{directory}/{stem}" if directory else stem


def _mask_file_path(document, reference: str, cmd: Command) -> str:
    """A reference as an absolute path on this machine.

    The same arithmetic `tileset_defaults` does when it loads the file, and
    for the same reason: the reference is relative to the .tmx, exactly as
    the tileset's own image source is.
    """
    path = getattr(document, "path", None)
    if os.path.isabs(reference):
        return os.path.normpath(reference)
    if not path:
        raise PyoneerCommandArgumentError(
            f"this map has no path to resolve {reference!r} against -- it was "
            f"built from bytes. Load the map from a file, or make the "
            f"reference absolute", verb=cmd.verb)
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(path)), reference))


def _mask_grid(ref, resolved: str, cmd: Command) -> Blitmask:
    """The tileset's mask grid: the file when it is there, a blank one shaped
    to the sheet when it is not.

    The two shape refusals are `tileset_defaults`' again. A mask a different
    WIDTH from the sheet does not lose a column, it shifts every row after
    the first and masks the wrong tiles; a mask TALLER than the sheet holds
    cells that were authored and would be read by nothing.
    """
    # Ceiling division, the same line `tileset_defaults` uses to decide how
    # many rows a sheet's masks may occupy.
    rows = -(-ref.tile_count // ref.columns)
    if not os.path.isfile(resolved):
        return TilesetDefaults(ref.first_gid, ref.columns, rows,
                               (NO_DATA,) * (ref.columns * rows),
                               ref.name).to_blitmask()
    grid = Blitmask.load(resolved)
    label = ref.name or ref.first_gid
    if grid.width != ref.columns:
        raise PyoneerCommandArgumentError(
            f"tileset {label!r} is {ref.columns} columns wide and its masks "
            f"{resolved} are {grid.width}. A mask grid is row-major over the "
            f"sheet, so a different width does not lose a column -- it shifts "
            f"every row after the first and masks the wrong tiles",
            verb=cmd.verb)
    if grid.height > rows:
        raise PyoneerCommandArgumentError(
            f"masks {resolved} are {grid.width}x{grid.height} but tileset "
            f"{label!r} is {ref.tile_count} tiles in {ref.columns} columns, "
            f"which is {rows} rows. The "
            f"{(grid.height - rows) * grid.width} cells past that edge were "
            f"authored and would be read by nothing", verb=cmd.verb)
    return grid


def _grown_to(grid: Blitmask, rows: int) -> Blitmask:
    """The grid with enough rows to reach `rows`, padded with NO_DATA."""
    if rows <= grid.height:
        return grid
    pad = (NO_DATA,) * ((rows - grid.height) * grid.width)
    return Blitmask(grid.width, rows, grid.opinions + pad, dict(grid.meta))


def _mask_edit(project: Project, cmd: Command, *,
               wanted: str | None) -> Command | None:
    """One tile's mask written, and the declaration left where `wanted` says.

    `wanted` is None for `map.tileset.mask.set` -- "keep whatever the tileset
    declares, and declare the conventional file if it declares nothing" --
    and the exact reference for `map.tileset.mask.restore`, where "" means
    the property must go.
    """
    document, ref = _tileset_for_mask(project, cmd)
    tile, mask = cmd.args["tile"], cmd.args["mask"]
    label = ref.name or ref.first_gid
    if not is_opinion(mask):
        raise PyoneerCommandArgumentError(
            f"{mask} is not an opinion: {NO_DATA} is no-data, "
            f"{layer_module.STAR} is the star that abstains, and "
            f"0..{layer_module.BLOCK_ALL} are the direction bits",
            verb=cmd.verb)
    if not 0 <= tile < ref.tile_count:
        raise PyoneerCommandArgumentError(
            f"tile {tile} is outside 0..{ref.tile_count - 1}; a tile id is "
            f"local to its tileset, not a gid -- gid {tile} in this map is "
            f"tile {tile - ref.first_gid} of {label!r}",
            verb=cmd.verb, first_gid=ref.first_gid)

    declared = _declared_mask_reference(document, ref, cmd)
    if wanted is None:
        becomes = declared or _conventional_mask_reference(ref, cmd)
        target = becomes
    else:
        if declared and wanted and declared != wanted:
            raise PyoneerCommandArgumentError(
                f"tileset {label!r} already declares {declared!r} and this "
                f"would point it at {wanted!r}. Moving a tileset's masks is "
                f"two edits, not one -- the cell in the old file and the cell "
                f"in the new one cannot both be put back by a single inverse",
                verb=cmd.verb)
        target = wanted or declared
        if not target:
            raise PyoneerCommandArgumentError(
                f"tileset {label!r} declares no masks and no `reference` was "
                f"given, so there is no file to write the tile into",
                verb=cmd.verb)
        becomes = wanted

    resolved = _mask_file_path(document, target, cmd)
    existed = os.path.isfile(resolved)
    found = _mask_grid(ref, resolved, cmd)
    x, y = tile % ref.columns, tile // ref.columns
    previous = found.at(x, y)
    updated = _grown_to(found, y + 1).with_cell(x, y, mask)

    if existed and updated == found and declared == becomes:
        return None

    # The file first. A refused write then leaves the document exactly as it
    # was found, rather than leaving a declaration pointing at a file that is
    # not there -- the one state `tileset_defaults` raises on, and one the
    # author never authored.
    updated.save(resolved)

    if declared != becomes:
        view = document.properties_of(ref.element)
        if becomes:
            view[DEFAULTS_PROPERTY] = becomes
        else:
            del view[DEFAULTS_PROPERTY]
            # `MapProperties.__delitem__` drops an emptied `<properties>` and
            # `_remove_child` hands its whitespace back to the OWNER, so an
            # element the file wrote self-closing returns as
            # `<tileset ...>\n</tileset>`. An embedded tileset always carries
            # an `<image>` child, so this cannot bite today; it is the guard
            # `map.object.action.unset` had to learn the hard way and it costs
            # one line.
            if not list(ref.element):
                ref.element.text = None

    return Command("map.tileset.mask.restore", cmd.scope, {
        "name": cmd.args["name"], "first_gid": cmd.args["first_gid"],
        "tile": tile, "mask": previous, "reference": declared})


@command(
    "map.tileset.mask.set",  # #TAG:map.tileset.mask.set
    summary="Set one TILE's collision mask, once, for everywhere that tile "
            "is ever stamped. It is stored in the tileset's own .blitmask "
            "sidecar and declared on the <tileset> with pyoneer_collision, "
            "which is the level the engine stacks UNDER every companion "
            "layer -- so a cell painted in the collision overlay still "
            "wins. The mask is the vocabulary the overlay paints: -1 no "
            "opinion, 0 open, 1 down, 2 left, 4 right, 8 up, added together, "
            "15 blocked on all four sides, 16 the star that abstains and "
            "defers to the layer below. The sidecar is WRITTEN when it is "
            "not there, sized to the sheet, and nothing asks first. Undo "
            "restores the cell and the declaration exactly and leaves the "
            "file on disk -- a grid of no-data reads as no masks at all.",
    scopes=["map:*"],
    params=[
        Param("name", str, "tileset name; leave empty and pass first_gid for "
                           "an external <tileset source=...>, which carries "
                           "no name in this file",
              required=False, default=""),
        Param("first_gid", int, "address the tileset by its firstgid instead "
                                "of its name", required=False, default=0),
        Param("tile", int, "the tile's id WITHIN its tileset -- 0-based, "
                           "row-major over the sheet, which is a gid minus "
                           "the tileset's firstgid"),
        Param("mask", int, "-1 for no opinion, 0..15 for the direction bits "
                           "(1 down, 2 left, 4 right, 8 up), 16 for the star"),
    ],
    example='{"verb": "map.tileset.mask.set", "scope": "map:test", "args":'
            ' {"name": "Dungeon", "tile": 7, "mask": 15}}',
)
def _tileset_mask_set(project: Project, cmd: Command) -> Command | None:
    return _mask_edit(project, cmd, wanted=None)


@command(
    "map.tileset.mask.restore",  # #TAG:map.tileset.mask.restore
    summary="Write one tile's mask back AND put the tileset's "
            "pyoneer_collision declaration back to what it was, an empty "
            "`reference` removing it. The exact inverse of "
            "map.tileset.mask.set and of itself, and the only reason a set "
            "that had to declare the sidecar can be undone without leaving "
            "the .tmx one property heavier than it was found. Rarely written "
            "by hand -- use map.tileset.mask.set, which derives the "
            "reference and provisions the file.",
    scopes=["map:*"],
    params=[
        Param("name", str, "tileset name; leave empty and pass first_gid",
              required=False, default=""),
        Param("first_gid", int, "address the tileset by its firstgid instead "
                                "of its name", required=False, default=0),
        Param("tile", int, "the tile's id within its tileset"),
        Param("mask", int, "the opinion exactly as it was found; -1 is no "
                           "opinion"),
        Param("reference", str, "the pyoneer_collision value to leave on the "
                                "tileset, spelled exactly as the file spells "
                                "it. Empty removes the property, and the mask "
                                "is then written into whatever the tileset "
                                "declares now",
              required=False, default=""),
    ],
    example='{"verb": "map.tileset.mask.restore", "scope": "map:test", "args":'
            ' {"name": "Dungeon", "tile": 7, "mask": -1, "reference": ""}}',
)
def _tileset_mask_restore(project: Project, cmd: Command) -> Command | None:
    return _mask_edit(project, cmd, wanted=cmd.args["reference"])


# --------------------------------------------------------------------------
# Objects -- the entity-spawn seam
# --------------------------------------------------------------------------

@command(
    "map.object.add",  # #TAG:map.object.add
    summary="Place an object on an object layer. `type` is the class name "
            "the game resolves to a spawnable entity, so it must be a name "
            "the spawn registry knows. If the genre pack declares a default "
            "behavior list for that class on that layer, it is written onto "
            "the new object as `pyoneer_behaviors` here and never consulted "
            "again -- a starting value, not a policy.",
    scopes=["map:*/layer:*"],
    params=[
        Param("type", str, "the object's class, e.g. 'Chest' or 'PlayerStart'"),
        Param("x", float, "world pixels from the left"),
        Param("y", float, "world pixels from the top"),
        Param("name", str, "an instance name, unique within the layer by "
                           "convention but not enforced", required=False, default=""),
        Param("width", float, "pixels; omit for a point object",
              required=False, default=0.0),
        Param("height", float, "pixels; omit for a point object",
              required=False, default=0.0),
        Param("gid", int, "tile gid, if this object draws as a tile",
              required=False, default=0),
        Param("properties", dict, "custom properties; types are inferred and "
                                  "written with an explicit tmx type "
                                  "attribute. A `pyoneer_behaviors` given "
                                  "here WINS over the genre pack's default "
                                  "for this class, including an explicit "
                                  "empty one",
              required=False, default=None),
        Param("object_id", int, "force a specific id; leave unset and the "
                                "document assigns the next free one",
              required=False, default=0),
    ],
    example='{"verb": "map.object.add", "scope": "map:test/layer:entity",'
            ' "args": {"type": "Chest", "name": "chest_01", "x": 128, "y": 96,'
            ' "properties": {"locked": true, "loot": "potion"}}}',
)
def _object_add(project: Project, cmd: Command) -> Command:
    layer = _object_layer(project, cmd.scope)
    args = cmd.args
    created = layer.add_object(
        name=args["name"] or None,
        type=args["type"],
        x=args["x"],
        y=args["y"],
        width=args["width"] or None,
        height=args["height"] or None,
        gid=args["gid"] or None,
        properties=_born_with(project, cmd.scope, args),
        object_id=args["object_id"] or None,
    )
    # The inverse takes the WHOLE element away, materialised property and
    # all, so nothing about this needs its own undo step: a default that only
    # ever exists on an object that is being created is undone by uncreating
    # it.
    return Command("map.object.remove",
                   cmd.scope.child("object", str(created.id)))


def _born_with(project: Project, scope: Scope,
               args: dict[str, Any]) -> dict[str, Any] | None:
    """The custom properties a newly added object is born carrying.

    This is where a genre pack's `layers[].object_classes[].behaviors` stops
    being a declaration and becomes map data. The editor MATERIALISES it here
    and never consults it again -- `scripts/` may not import `editor/`, so
    there is no engine-side fallback, and the `.tmx` being the whole truth is
    what makes a map play the same whether or not the editor has ever opened
    it.

    PRECEDENCE:

      1. a `pyoneer_behaviors` the CALLER supplied wins outright, including
         an explicit empty one -- "this object does nothing" is a thing an
         author is allowed to say
      2. otherwise the pack's list for this layer and this class, if it
         declares one
      3. otherwise nothing at all

    Nothing re-asserts step 2 afterwards, so editing the list on the object is
    the last word: no later command reads the pack.
    """
    properties = dict(args["properties"] or {})
    if BEHAVIORS in properties:                # #TAG:behaviors_materialised_at_add
        return properties or None
    declared = project.genre.object_class(scope.require("layer"), args["type"])
    if declared is None or not declared.behaviors:
        return properties or None
    properties[BEHAVIORS] = declared.behaviors_text
    return properties


@command(
    "map.object.remove",  # #TAG:map.object.remove
    summary="Remove an object. Its inverse restores the whole XML element, "
            "so undo brings back shape, rotation and everything else.",
    scopes=["map:*/layer:*/object:*"],
    destructive=True,
    example='{"verb": "map.object.remove",'
            ' "scope": "map:test/layer:entity/object:14", "args": {}}',
)
def _object_remove(project: Project, cmd: Command) -> Command:
    found = _object(project, cmd.scope)
    layer = _object_layer(project, cmd.scope)
    document = project.map(cmd.scope.require("map"))

    # The whole XML element, not a rebuild from its attributes: rotation,
    # visible, template and every shape child (<polygon>, <polyline>,
    # <point>, <ellipse>, <text>) survive undo only this way.
    payload = {
        "xml": layer.serialize_object(found.id),
        "index": layer.object_index(found.id),
        "next_object_id": document.root.get("nextobjectid", "1"),
    }
    layer.remove_object(found.id)
    return Command("map.object.restore", _layer_scope(cmd.scope), payload)


@command(
    "map.object.restore",  # #TAG:map.object.restore
    summary="Put back an object from its serialised XML, at its original "
            "position among its siblings. The exact inverse of "
            "map.object.remove; rarely written by hand.",
    scopes=["map:*/layer:*"],
    params=[
        Param("xml", str, "the object's whole <object> element as XML text"),
        Param("index", int, "position among sibling objects; omit to append",
              required=False, default=None),
        Param("next_object_id", str, "the map's nextobjectid before removal",
              required=False, default=""),
    ],
)
def _object_restore(project: Project, cmd: Command) -> Command:
    layer = _object_layer(project, cmd.scope)
    document = project.map(cmd.scope.require("map"))
    restored = layer.restore_object(cmd.args["xml"], cmd.args["index"])
    if cmd.args["next_object_id"]:
        document.root.set("nextobjectid", cmd.args["next_object_id"])
    return Command("map.object.remove",
                   cmd.scope.child("object", str(restored.id)))


@command(
    "map.object.move",  # #TAG:map.object.move
    summary="Move an object to new world-pixel coordinates.",
    scopes=["map:*/layer:*/object:*"],
    params=[
        Param("x", float, "world pixels from the left"),
        Param("y", float, "world pixels from the top"),
    ],
)
def _object_move(project: Project, cmd: Command) -> Command | None:
    found = _object(project, cmd.scope)
    before = {"x": found.x, "y": found.y}
    if before["x"] == cmd.args["x"] and before["y"] == cmd.args["y"]:
        return None
    found.set("x", cmd.args["x"])
    found.set("y", cmd.args["y"])
    return Command("map.object.move", cmd.scope, before)


# Every built-in <object> attribute the editor may write. `class` is here
# because Tiled 1.9+ spells `type` that way, and an inverse command has to
# be able to name whichever one the file actually carries.
_OBJECT_ATTRIBUTES = ("name", "type", "class", "width", "height", "gid",
                      "rotation", "visible", "template")


def _object_attribute_name(found, key: str) -> str:
    """Which attribute this element actually spells `key` as.

    Tiled 1.9 renamed `type` to `class`. Writing `type` onto an element that
    already carries `class` leaves BOTH on the element -- the editor reads
    the new value and Tiled reads the old one, and the two views diverge
    permanently. So follow whatever the file already uses.
    """
    if key == "type" and "type" not in found.element.attrib \
            and "class" in found.element.attrib:
        return "class"
    return key


@command(
    "map.object.set",  # #TAG:map.object.set
    summary="Set a built-in attribute of an object. For anything else use "
            "map.object.property.set.",
    scopes=["map:*/layer:*/object:*"],
    params=[
        Param("key", str, "which attribute", choices=_OBJECT_ATTRIBUTES),
        Param("value", str, "the new value, as text; tmx attributes are text"),
    ],
)
def _object_set(project: Project, cmd: Command) -> Command | None:
    found = _object(project, cmd.scope)
    key, value = cmd.args["key"], cmd.args["value"]
    attribute = _object_attribute_name(found, key)

    # Read the RAW attribute, not the property. `str(getattr(found, key))`
    # raises AttributeError for any key MapObject does not model, and for an
    # ABSENT width it returns "0.0" -- so undo materialised a spurious
    # width="0.0" on an object that never had one.
    previous = found.element.attrib.get(attribute)
    if previous == value:
        return None

    found.element.set(attribute, value)
    found._document._touch()
    if previous is None:
        return Command("map.object.unset", cmd.scope, {"key": attribute})
    return Command("map.object.set", cmd.scope,
                   {"key": attribute, "value": previous})


@command(
    "map.object.unset",  # #TAG:map.object.unset
    summary="Remove a built-in attribute entirely, rather than blanking it. "
            "The inverse of setting an attribute that was previously absent.",
    scopes=["map:*/layer:*/object:*"],
    params=[Param("key", str, "which attribute to remove")],
    destructive=True,
)
def _object_unset(project: Project, cmd: Command) -> Command | None:
    found = _object(project, cmd.scope)
    key = cmd.args["key"]
    previous = found.element.attrib.pop(key, None)
    if previous is None:
        return None
    found._document._touch()
    return Command("map.object.set", cmd.scope,
                   {"key": key, "value": previous})


@command(
    "map.object.property.set",  # #TAG:map.object.property.set
    summary="Set a custom property on an object. The tmx type attribute is "
            "written from the Python type, so an int reads back as an int "
            "rather than the string '50'.",
    scopes=["map:*/layer:*/object:*"],
    params=[
        Param("key", str, "property name"),
        Param("value", object, "int, float, str or bool"),
    ],
    example='{"verb": "map.object.property.set",'
            ' "scope": "map:test/layer:entity/object:14",'
            ' "args": {"key": "hp", "value": 30}}',
)
def _object_property_set(project: Project, cmd: Command) -> Command | None:
    found = _object(project, cmd.scope)
    key, value = cmd.args["key"], cmd.args["value"]
    if not isinstance(value, (int, float, str, bool)):
        raise PyoneerCommandArgumentError(
            f"property {key!r} must be int, float, str or bool, got "
            f"{type(value).__name__}", verb=cmd.verb)
    existing = found.properties.as_dict()
    view = found.properties
    view[key] = value
    if key in existing:
        return Command("map.object.property.set", cmd.scope,
                       {"key": key, "value": existing[key]})
    return Command("map.object.property.remove", cmd.scope, {"key": key})


@command(
    "map.object.property.remove",  # #TAG:map.object.property.remove
    summary="Remove a custom property from an object.",
    scopes=["map:*/layer:*/object:*"],
    params=[Param("key", str, "property name")],
    destructive=True,
)
def _object_property_remove(project: Project, cmd: Command) -> Command | None:
    found = _object(project, cmd.scope)
    key = cmd.args["key"]
    existing = found.properties.as_dict()
    if key not in existing:
        return None
    del found.properties[key]
    return Command("map.object.property.set", cmd.scope,
                   {"key": key, "value": existing[key]})


# --------------------------------------------------------------------------
# Map events -- the trigger declaration on an object
#
# `editor/core/map_events.py` owns the vocabulary, the reader and the rules;
# these three verbs are the only door onto it. They are separate from
# map.object.property.* deliberately. That pair writes ANY property and
# checks nothing but the Python type, so a trigger authored through it can
# say `pyoneer_trigger="entre"` -- which reads back as no trigger at all and
# announces that in a warning nobody is watching for. Here the authoring
# door is where the mistake is cheap.
#
# NOTHING IN THE ENGINE EXECUTES ONE OF THESE. No MAP_TRIGGER_* event type
# exists and nothing under `scripts/` reads `pyoneer_trigger`, so a map
# authored with these plays exactly as it did before. That caveat is stated
# in three places -- here, in the generated COMMANDS.md through the summaries
# below, and on screen in the Actions panel -- because one that lives only in
# a docstring is one the AI writing a response never sees.
#
# ONE LIMIT, STATED. `MapProperties` can delete a `<property>` and append
# one, but cannot insert at an index, so taking a field back and putting it
# back again re-appends it at the END of `<properties>`. Every VALUE survives
# exactly; the element ORDER survives only while the field being taken back
# was the last one declared -- always true of a field this panel just added,
# and not of one hand-authored in Tiled above another. The same limit applies
# to `map.object.property.remove`.
# --------------------------------------------------------------------------

def _action_property(cmd: Command) -> str:
    """The tmx property name a map-event command addresses.

    `Param.choices` has already refused anything outside the vocabulary, so
    this cannot miss -- it exists so the three verbs never spell the
    `pyoneer_` prefix themselves.
    """
    return map_event_module.BY_KEY[cmd.args["key"]].property_name


def _action_inverse(scope: Scope, key: str, existing: dict[str, Any]) -> Command:
    """What puts one map-event field back exactly as it was found.

    `map.object.action.restore` rather than `.set`, and this is the whole
    reason `restore` exists. `map_events.validate` NORMALISES -- it sorts and
    case-folds a filter list, and it REFUSES a trigger kind it does not know
    -- so an inverse routed back through it would rewrite a hand-authored
    `pyoneer_filter_tags="B,a"` as `"a,b"`, and would raise mid-undo on
    `pyoneer_trigger="entre"`, taking the rollback with it. Both of those are
    values this vocabulary never wrote, which is exactly why the inverse has
    to carry the value it FOUND rather than one it can re-derive.
    """
    name = map_event_module.BY_KEY[key].property_name
    if name not in existing:
        return Command("map.object.action.unset", scope, {"key": key})
    return Command("map.object.action.restore", scope,
                   {"key": key, "value": existing[name]})


@command(
    "map.object.action.set",  # #TAG:map.object.action.set
    summary="Declare one field of an object's map-event trigger -- when it "
            "fires, which entities may fire it, whether it also blocks "
            "movement, and what it carries. Stored as a pyoneer_ tmx custom "
            "property, so Tiled edits it in the same dialog. NOTHING RUNS "
            "THIS YET: the engine has no collision detection, no "
            "MAP_TRIGGER_* event type and no reader for the object layer, so "
            "a map authored with these plays exactly as it did before. The "
            "authoring is real, reversible and readable; the firing is not "
            "built.",
    scopes=["map:*/layer:*/object:*"],
    params=[
        Param("key", str, "which field of the declaration",
              choices=_action_keys()),
        Param("value", object, "str, int or bool, matching the field's "
                               "declared type. A filter list is comma "
                               "separated ('player,npc'); args are "
                               "'key=value;key=value'."),
    ],
    example='{"verb": "map.object.action.set",'
            ' "scope": "map:test/layer:entity/object:14",'
            ' "args": {"key": "trigger", "value": "enter"}}',
)
def _action_set(project: Project, cmd: Command) -> Command | None:
    found = _object(project, cmd.scope)
    key = cmd.args["key"]
    try:
        checked = map_event_module.validate(key, cmd.args["value"])
    except ValueError as exc:
        raise PyoneerCommandArgumentError(str(exc), verb=cmd.verb) from None

    name = _action_property(cmd)
    existing = found.properties.as_dict()
    if name in existing and existing[name] == checked:
        return None
    found.properties[name] = checked
    return _action_inverse(cmd.scope, key, existing)


@command(
    "map.object.action.unset",  # #TAG:map.object.action.unset
    summary="Remove one field of a trigger declaration, returning it to its "
            "default. Deleting a whole trigger is one of these per declared "
            "field, emitted together -- so it lands as one transaction and "
            "undoes as one step.",
    scopes=["map:*/layer:*/object:*"],
    params=[Param("key", str, "which field", choices=_action_keys())],
    destructive=True,
)
def _action_unset(project: Project, cmd: Command) -> Command | None:
    found = _object(project, cmd.scope)
    name = _action_property(cmd)
    existing = found.properties.as_dict()
    if name not in existing:
        return None
    del found.properties[name]

    # `MapProperties.__delitem__` drops the `<properties>` container once it
    # empties, but `_remove_child` hands the whitespace back to the OWNER --
    # so an `<object .../>` the file wrote self-closing would come back as
    # `<object ...>\n</object>`: two lines of diff on a declare-then-undo
    # that must leave none. A childless object is written self-closing by
    # Tiled and by this document, so `text = None` returns it to the file's
    # own spelling, as `ObjectLayer.remove_object` does one level up.
    # Belongs in `MapProperties.__delitem__`, which is in scripts/.
    if not list(found.element):
        found.element.text = None

    return Command("map.object.action.restore", cmd.scope,
                   {"key": cmd.args["key"], "value": existing[name]})


@command(
    "map.object.action.restore",  # #TAG:map.object.action.restore
    summary="Write one map-event property back VERBATIM, without validating "
            "the value. The exact inverse of map.object.action.set and "
            "map.object.action.unset, and the only reason those two can take "
            "back a hand-authored value that the validator would reformat or "
            "reject. Rarely written by hand -- use map.object.action.set, "
            "which checks what you give it.",
    scopes=["map:*/layer:*/object:*"],
    params=[
        Param("key", str, "which field", choices=_action_keys()),
        Param("value", object, "the value exactly as it was found; a tmx "
                               "property holds a str, int, float or bool"),
    ],
)
def _action_restore(project: Project, cmd: Command) -> Command | None:
    found = _object(project, cmd.scope)
    value = cmd.args["value"]
    # The one thing still checked. `MapProperties.__setitem__` would hand a
    # list or a dict to `format_property` and write its repr into the file,
    # and nothing downstream would ever read it back as anything else.
    if not isinstance(value, (int, float, str, bool)):
        raise PyoneerCommandArgumentError(
            f"a tmx property holds a scalar; {cmd.args['key']!r} was handed "
            f"{type(value).__name__}", verb=cmd.verb)

    name = _action_property(cmd)
    existing = found.properties.as_dict()
    if name in existing and existing[name] == value:
        return None
    found.properties[name] = value
    return _action_inverse(cmd.scope, cmd.args["key"], existing)


# --------------------------------------------------------------------------
# Data tables
# --------------------------------------------------------------------------

@command(
    "table.create",  # #TAG:table.create
    summary="Create a data table. Prefer taking the genre's declared shape "
            "by leaving `columns` empty -- the pack already describes it.",
    scopes=["table:*"],
    params=[
        Param("title", str, "human label for the panel", required=False, default=""),
        Param("doc", str, "what this table is for", required=False, default=""),
        Param("columns", list, "list of {name, type, doc, default}; empty "
                               "means take the genre's declaration",
              required=False, default=None),
    ],
    example='{"verb": "table.create", "scope": "table:actors", "args": {}}',
)
def _table_create(project: Project, cmd: Command) -> Command:
    name = cmd.scope.require("table")
    declared = project.genre.table(name)
    if cmd.args["columns"]:
        table = DataTable(name=name,
                          title=cmd.args["title"] or name.title(),
                          doc=cmd.args["doc"])
        for item in cmd.args["columns"]:
            table.add_column(_column_from(item, verb=cmd.verb))
    elif declared is not None:
        table = DataTable.from_genre(declared)
        if cmd.args["title"]:
            table.title = cmd.args["title"]
        if cmd.args["doc"]:
            table.doc = cmd.args["doc"]
    else:
        raise PyoneerCommandArgumentError(
            f"table {name!r} is not declared by genre {project.genre.id!r}, "
            f"so `columns` is required",
            verb=cmd.verb,
            genre_tables=[t.name for t in project.genre.tables])
    project.create_table(table)
    return Command("table.drop", cmd.scope, {"confirm": True})


@command(
    "table.drop",  # #TAG:table.drop
    summary="Delete a table and its file. Refused for tables the genre "
            "marks required.",
    scopes=["table:*"],
    params=[Param("confirm", bool, "must be true; guards against a stray drop")],
    destructive=True,
)
def _table_drop(project: Project, cmd: Command) -> Command:
    name = cmd.scope.require("table")
    if not cmd.args["confirm"]:
        raise PyoneerCommandArgumentError(
            "table.drop needs confirm=true", verb=cmd.verb)
    declared = project.genre.table(name)
    if declared is not None and declared.required:
        raise PyoneerRuleViolationError(
            f"genre {project.genre.id!r} requires the {name!r} table; "
            f"dropping it would make the project unloadable",
            genre=project.genre.id, table=name,
            hint="change the genre first, or edit the pack")
    table = project.table(name)
    payload = table.to_json()
    project.drop_table(name)
    return Command("table.restore", cmd.scope, {"table": payload})


@command(
    "table.restore",  # #TAG:table.restore
    summary="Recreate a table from a full serialised payload. Exists so "
            "table.drop has an exact inverse; rarely written by hand.",
    scopes=["table:*"],
    params=[Param("table", dict, "the table's full JSON, as table.to_json()")],
)
def _table_restore(project: Project, cmd: Command) -> Command:
    table = DataTable.from_json(cmd.args["table"])
    table.dirty = True
    project.create_table(table)
    return Command("table.drop", cmd.scope, {"confirm": True})


@command(
    "table.row.add",  # #TAG:table.row.add
    summary="Add a row. Unlisted columns take their declared default.",
    scopes=["table:*"],
    params=[
        Param("id", str, "the row's stable key, e.g. 'hero' or 'plasma_rifle'"),
        Param("values", dict, "column -> value; every key must be an existing "
                              "column and every value the declared type",
              required=False, default=None),
    ],
    example='{"verb": "table.row.add", "scope": "table:actors", "args":'
            ' {"id": "hero", "values": {"display_name": "Hero", "hp": 30}}}',
)
def _row_add(project: Project, cmd: Command) -> Command:
    table = project.table(cmd.scope.require("table"))
    table.add_row(cmd.args["id"], cmd.args["values"] or {})
    return Command("table.row.remove",
                   cmd.scope.child("row", cmd.args["id"]))


@command(
    "table.row.remove",  # #TAG:table.row.remove
    summary="Remove a row. The inverse restores every value it held.",
    scopes=["table:*/row:*"],
    destructive=True,
)
def _row_remove(project: Project, cmd: Command) -> Command:
    table = project.table(cmd.scope.require("table"))
    row_id = cmd.scope.require("row")
    values = table.remove_row(row_id)
    return Command("table.row.add", _table_scope(cmd.scope),
                   {"id": row_id, "values": values})


@command(
    "table.row.set",  # #TAG:table.row.set
    summary="Set one cell.",
    scopes=["table:*/row:*"],
    params=[
        Param("column", str, "which column"),
        Param("value", object, "the new value; must match the column's type"),
    ],
    example='{"verb": "table.row.set", "scope": "table:actors/row:hero",'
            ' "args": {"column": "hp", "value": 42}}',
)
def _row_set(project: Project, cmd: Command) -> Command | None:
    table = project.table(cmd.scope.require("table"))
    row_id = cmd.scope.require("row")
    previous = table.set_value(row_id, cmd.args["column"], cmd.args["value"])
    if previous == cmd.args["value"]:
        return None
    return Command("table.row.set", cmd.scope,
                   {"column": cmd.args["column"], "value": previous})


@command(
    "table.column.add",  # #TAG:table.column.add
    summary="Add a column. Existing rows take the default. This is how a "
            "genre grows -- adding 'stat_modifier' to equipment does not "
            "need editor code.",
    scopes=["table:*"],
    params=[
        Param("name", str, "column name; snake_case by convention"),
        Param("type", str, "value type", choices=("int", "float", "str", "bool")),
        Param("doc", str, "what it means", required=False, default=""),
        Param("default", object, "value for existing rows; omit for the "
                                 "type's zero", required=False, default=None),
    ],
    example='{"verb": "table.column.add", "scope": "table:weapons", "args":'
            ' {"name": "damage", "type": "int", "doc": "hp removed per hit",'
            ' "default": 1}}',
)
def _column_add(project: Project, cmd: Command) -> Command:
    table = project.table(cmd.scope.require("table"))
    table.add_column(Column(cmd.args["name"], cmd.args["type"],
                            cmd.args["doc"], cmd.args["default"]))
    return Command("table.column.remove",
                   cmd.scope.child("field", cmd.args["name"]))


@command(
    "table.column.remove",  # #TAG:table.column.remove
    summary="Remove a column and every value in it. Refused for columns the "
            "genre marks required.",
    scopes=["table:*/field:*"],
    destructive=True,
)
def _column_remove(project: Project, cmd: Command) -> Command:
    table_name = cmd.scope.require("table")
    field_name = cmd.scope.require("field")
    if project.genre.is_field_required(table_name, field_name):
        raise PyoneerRuleViolationError(
            f"genre {project.genre.id!r} requires column {field_name!r} on "
            f"{table_name!r}; removing it would make the project unloadable",
            genre=project.genre.id, table=table_name, column=field_name)
    table = project.table(table_name)
    column = table.require_field(field_name)
    values = {rid: row[field_name] for rid, row in table.rows.items()
              if field_name in row}
    table.remove_column(field_name)
    return Command("table.column.restore", _table_scope(cmd.scope), {
        "name": column.name, "type": column.type, "doc": column.doc,
        "default": column.default, "values": values,
    })


@command(
    "table.column.restore",  # #TAG:table.column.restore
    summary="Re-add a column and put its values back. The inverse of "
            "table.column.remove; rarely written by hand.",
    scopes=["table:*"],
    params=[
        Param("name", str, "column name"),
        Param("type", str, "value type", choices=("int", "float", "str", "bool")),
        Param("doc", str, "what it means", required=False, default=""),
        Param("default", object, "default value", required=False, default=None),
        Param("values", dict, "row id -> value", required=False, default=None),
    ],
)
def _column_restore(project: Project, cmd: Command) -> Command:
    table = project.table(cmd.scope.require("table"))
    table.add_column(Column(cmd.args["name"], cmd.args["type"],
                            cmd.args["doc"], cmd.args["default"]))
    for row_id, value in (cmd.args["values"] or {}).items():
        if row_id in table.rows:
            table.set_value(row_id, cmd.args["name"], value)
    return Command("table.column.remove",
                   _table_scope(cmd.scope).child("field", cmd.args["name"]))


def _column_from(item: Any, *, verb: str) -> Column:
    if not isinstance(item, dict) or "name" not in item or "type" not in item:
        raise PyoneerCommandArgumentError(
            f"a column needs at least {{name, type}}, got {item!r}", verb=verb)
    if item["type"] not in ("int", "float", "str", "bool"):
        raise PyoneerCommandArgumentError(
            f"column {item['name']!r} has type {item['type']!r}; must be "
            f"int, float, str or bool", verb=verb)
    return Column(item["name"], item["type"],
                  item.get("doc", ""), item.get("default"))


# --------------------------------------------------------------------------
# Project
# --------------------------------------------------------------------------

@command(
    "project.genre.set",  # #TAG:project.genre.set
    summary="Switch the project's genre pack. Changes which layers and "
            "tables are expected and which panels the editor shows; does "
            "not delete anything.",
    scopes=["project"],
    params=[Param("genre", str, "a genre pack id, e.g. 'platformer'")],
    example='{"verb": "project.genre.set", "scope": "project",'
            ' "args": {"genre": "platformer"}}',
)
def _genre_set(project: Project, cmd: Command) -> Command | None:
    wanted = cmd.args["genre"]
    if wanted == project.genre.id:
        return None
    pack = genre_module.load(wanted)
    previous = project.set_genre(pack)
    return Command("project.genre.set", cmd.scope, {"genre": previous.id})
