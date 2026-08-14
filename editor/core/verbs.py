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


def _layer_keys() -> list[str]:
    return [capability.key for capability in layer_module.CAPABILITIES]


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
    "map.tile.set",
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
    "map.tile.set_many",
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
    "map.tile.fill",
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
    "map.layer.add",
    summary="Add a tile or object layer. A tile layer is created at the "
            "map's size. Note that a layer only RENDERS if its name has a "
            "depth in scripts/core/depth.py.",
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
    ],
    example='{"verb": "map.layer.add", "scope": "map:test",'
            ' "args": {"name": "Hazard", "kind": "tile"}}',
)
def _layer_add(project: Project, cmd: Command) -> Command:
    document = project.map(cmd.scope.require("map"))
    before = document.root.get("nextlayerid", "1")
    document.add_layer(cmd.args["name"], cmd.args["kind"],
                       group=cmd.args["group"] or None,
                       index=cmd.args["index"],
                       fill=cmd.args["fill"])
    return Command("map.layer.remove",
                   cmd.scope.child("layer", cmd.args["name"]),
                   {"next_layer_id": before})


@command(
    "map.layer.remove",
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
    "map.layer.set",
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
    "map.layer.unset",
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
    "map.layer.restore",
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
# counts that block it. These verbs let that refusal through unchanged.
# Catching it to reword it would cost the caller the one piece of
# information that says how to proceed.
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
    "map.tileset.add",
    summary="Add an embedded tileset, appended above every gid range the "
            "map already uses. Anything left unset is measured rather than "
            "assumed: tile size defaults to the map's, the image is sized "
            "from its own header, and columns/tilecount fall out of the "
            "grid. Inserting BELOW an existing range is refused -- it would "
            "renumber every csv token in the file.",
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
    "map.tileset.remove",
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
    "map.tileset.restore",
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
    # force=True here, where map.tileset.add's inverse says False, and the
    # asymmetry is the whole point. An add creates a range that did not
    # exist, so taking it back can orphan tiles painted into it since --
    # the guard has real work to do. A restore only ever puts back what was
    # just taken out, so removing it again returns the document to a state
    # it was already in a moment ago, and anything that painted into the
    # range in between is a later command whose inverse runs FIRST. Without
    # force this is also unusable on an external tileset, whose extent
    # lives in the .tsx: the guard would refuse to undo its own undo.
    if name:
        return Command("map.tileset.remove", cmd.scope,
                       {"name": name, "force": True})
    return Command("map.tileset.remove", cmd.scope,
                   {"first_gid": first_gid, "force": True})


# --------------------------------------------------------------------------
# Objects -- the entity-spawn seam
# --------------------------------------------------------------------------

@command(
    "map.object.add",
    summary="Place an object on an object layer. `type` is the class name "
            "the game resolves to a spawnable entity, so it must be a name "
            "the spawn registry knows.",
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
                                  "written with an explicit tmx type attribute",
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
        properties=args["properties"] or None,
        object_id=args["object_id"] or None,
    )
    return Command("map.object.remove",
                   cmd.scope.child("object", str(created.id)))


@command(
    "map.object.remove",
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

    # The inverse used to be `map.object.add` rebuilt from eight attributes,
    # which SILENTLY DESTROYED rotation, visible, template and every shape
    # child (<polygon>, <polyline>, <point>, <ellipse>, <text>) on undo. The
    # byte-identity check missed it because the only objects it ever removed
    # were plain rectangles it had created itself two lines earlier.
    payload = {
        "xml": layer.serialize_object(found.id),
        "index": layer.object_index(found.id),
        "next_object_id": document.root.get("nextobjectid", "1"),
    }
    layer.remove_object(found.id)
    return Command("map.object.restore", _layer_scope(cmd.scope), payload)


@command(
    "map.object.restore",
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
    "map.object.move",
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
    "map.object.set",
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
    "map.object.unset",
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
    "map.object.property.set",
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
    "map.object.property.remove",
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
# Data tables
# --------------------------------------------------------------------------

@command(
    "table.create",
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
    "table.drop",
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
    "table.restore",
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
    "table.row.add",
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
    "table.row.remove",
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
    "table.row.set",
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
    "table.column.add",
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
    "table.column.remove",
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
    "table.column.restore",
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
    "project.genre.set",
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
