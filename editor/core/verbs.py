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
    summary="Remove an object. The inverse re-adds it with the same id, so "
            "undo restores the file byte-for-byte.",
    scopes=["map:*/layer:*/object:*"],
    destructive=True,
    example='{"verb": "map.object.remove",'
            ' "scope": "map:test/layer:entity/object:14", "args": {}}',
)
def _object_remove(project: Project, cmd: Command) -> Command:
    found = _object(project, cmd.scope)
    layer = _object_layer(project, cmd.scope)
    restore = {
        "type": found.type,
        "name": found.name,
        "x": found.x,
        "y": found.y,
        "width": found.width,
        "height": found.height,
        "gid": found.gid,
        "properties": found.properties.as_dict(),
        "object_id": found.id,
    }
    layer.remove_object(found.id)
    return Command("map.object.add", _layer_scope(cmd.scope), restore)


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


_OBJECT_ATTRIBUTES = ("name", "type", "width", "height", "gid")


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
    previous = str(getattr(found, key))
    if previous == value:
        return None
    found.set(key, value)
    return Command("map.object.set", cmd.scope, {"key": key, "value": previous})


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
