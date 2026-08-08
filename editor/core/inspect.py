"""What to show when something is selected, as data.

The inspector is the panel that replaced a fixed table of actors, and it has
to render very different things -- a map object, a tile layer, a row of a
data table, the map itself. Writing a Qt widget per kind would mean four
places to add a field and four places to get the command wrong.

So the description is DATA and the widget is a renderer. `describe(session,
scope)` returns sections of fields; each field knows its type, its current
value, and how to turn a new value into a Command. The Qt layer builds
editors from the type and never touches a verb.

That split is also the only reason this is testable. A check can assert
"the inspector offers `x` as a float and editing it produces
map.object.move" without opening a window, and the first run of that check
found two fields wired to the wrong verb.

WHAT IS DELIBERATELY READ-ONLY
------------------------------
Fields whose editing is not yet expressible as a command are shown, greyed,
with a reason. Hiding them would make the editor look complete and behave
otherwise; the honest version is a visible gap. `Field.blocked_reason`
carries the text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from editor.core import layers
from editor.core.commands import Command
from editor.core.scope import Scope, code_locations

# A field turns a new value into the command that applies it. Returning None
# means "no change", which the UI treats as a silent no-op.
Emitter = Callable[[Any], "Command | None"]


@dataclass
class Field:
    key: str
    label: str
    kind: str                       # str | int | float | bool | choice | text
    value: Any
    doc: str = ""
    emit: Emitter | None = None     # None => read-only
    choices: tuple[Any, ...] = ()
    blocked_reason: str = ""
    removable: bool = False         # custom properties can be deleted
    remove: Emitter | None = None

    @property
    def editable(self) -> bool:
        return self.emit is not None and not self.blocked_reason


@dataclass
class Section:
    title: str
    fields: list[Field] = field(default_factory=list)
    note: str = ""
    collapsible: bool = True


@dataclass
class Inspection:
    """Everything the inspector shows for one scope."""

    scope: Scope
    heading: str
    subheading: str = ""
    sections: list[Section] = field(default_factory=list)
    sources: tuple[str, ...] = ()      # files to offer "open in IDE" for
    error: str = ""

    @property
    def empty(self) -> bool:
        return not self.sections and not self.error


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def describe(session, scope: Scope) -> Inspection:
    """Describe whatever `scope` points at. Never raises."""
    try:
        builder = _BUILDERS.get(scope.kind)
        if builder is None:
            return Inspection(scope, str(scope),
                              error=f"nothing to inspect for a "
                                    f"{scope.kind!r} scope")
        found = builder(session, scope)
        found.sources = code_locations(scope)
        return found
    except Exception as exc:                                    # noqa: BLE001
        # An inspector that throws takes the window with it. A selection can
        # always go stale -- an object deleted by an undo, a layer renamed
        # under it -- and the right answer is a message in the panel.
        return Inspection(scope, str(scope),
                          error=f"{type(exc).__name__}: {exc}",
                          sources=code_locations(scope))


# --------------------------------------------------------------------------
# Map objects -- the important one
# --------------------------------------------------------------------------

_OBJECT_ATTRIBUTES = ("name", "type", "width", "height", "gid")

# tmx attributes MapObject has no property for. They are written through the
# raw attribute path, so they ARE editable -- what is missing is only a typed
# reader, which is why the current value is read off the element here.
def _raw(obj, key: str, fallback: str = "") -> str:
    return obj.element.attrib.get(key, fallback)


def _describe_object(session, scope: Scope) -> Inspection:
    document = session.project.map(scope.require("map"))
    layer_name = scope.require("layer")
    layer = document.object_layer(layer_name)
    object_id = int(scope.require("object"))
    obj = layer.find(object_id)
    if obj is None:
        return Inspection(scope, f"object {object_id}",
                          error=f"object {object_id} is no longer in "
                                f"{layer_name!r} -- it may have been undone")

    pack = session.project.genre
    declared = pack.layer(layer_name)
    classes = tuple(declared.object_types) if declared else ()

    identity = Section("Identity", [
        Field("id", "id", "str", str(obj.id),
              doc="assigned by the document; stable across saves"),
        Field("name", "name", "str", obj.name,
              doc="instance name, for you and for the hierarchy",
              emit=lambda v: Command("map.object.set", scope,
                                     {"key": "name", "value": str(v)})),
        Field("type", "class", "choice" if classes else "str", obj.type,
              doc="the class the game resolves to a spawnable entity",
              choices=classes,
              emit=lambda v: Command("map.object.set", scope,
                                     {"key": "type", "value": str(v)})),
    ])
    if obj.type and classes and obj.type not in classes:
        identity.note = (f"class {obj.type!r} is not one the {layer_name!r} "
                         f"layer declares: {list(classes)}")

    transform = Section("Transform", [
        Field("x", "x", "float", obj.x, doc="world pixels from the left",
              emit=lambda v: Command("map.object.move", scope,
                                     {"x": float(v), "y": obj.y})),
        Field("y", "y", "float", obj.y, doc="world pixels from the top",
              emit=lambda v: Command("map.object.move", scope,
                                     {"x": obj.x, "y": float(v)})),
        Field("width", "width", "float", obj.width,
              doc="pixels; 0 means a point object",
              emit=lambda v: Command("map.object.set", scope,
                                     {"key": "width", "value": _number(v)})),
        Field("height", "height", "float", obj.height,
              doc="pixels; 0 means a point object",
              emit=lambda v: Command("map.object.set", scope,
                                     {"key": "height", "value": _number(v)})),
        Field("gid", "tile gid", "int", obj.gid,
              doc="non-zero when the object draws as a tile",
              emit=lambda v: Command("map.object.set", scope,
                                     {"key": "gid", "value": str(int(v))})),
    ])
    transform.fields.append(Field(
        "rotation", "rotation", "float", float(_raw(obj, "rotation", "0") or 0),
        doc="degrees clockwise; Tiled rotates about the object's origin",
        emit=lambda v: Command("map.object.set", scope,
                               {"key": "rotation", "value": _number(v)})))

    # tmx spells visibility "0"/"1". A checkbox that sent "false" would
    # produce visible="false", which Tiled does not read as false.
    transform.fields.append(Field(
        "visible", "visible", "bool", _raw(obj, "visible", "1") != "0",
        doc="unticking hides the object in Tiled and in any renderer that "
            "honours it",
        emit=lambda v: Command("map.object.set", scope,
                               {"key": "visible", "value": "1" if v else "0"})))

    if "template" in obj.element.attrib:
        transform.fields.append(Field(
            "template", "template", "str", _raw(obj, "template"),
            blocked_reason="this object comes from a Tiled template; editing "
                           "it here would detach it from the template",
            doc="preserved exactly on save"))

    shape = _shape_of(obj)
    if shape != "rectangle":
        transform.fields.append(Field(
            "shape", "shape", "str", shape,
            blocked_reason="shape geometry is preserved on save but not yet "
                           "editable here",
            doc="point, ellipse, polygon, polyline or text"))

    custom = Section("Properties", note="per-instance data the game reads")
    for key, value in sorted(obj.properties.as_dict().items()):
        custom.fields.append(_property_field(scope, key, value))

    tile = f"tile ({int(obj.x) // document.tile_width}, " \
           f"{int(obj.y) // document.tile_height})"
    return Inspection(
        scope,
        obj.name or f"object {obj.id}",
        f"{obj.type or 'no class'}   ·   {layer_name}   ·   {tile}",
        [identity, transform, custom])


def _property_field(scope: Scope, key: str, value: Any) -> Field:
    kind = {bool: "bool", int: "int", float: "float"}.get(type(value), "str")
    return Field(
        key, key, kind, value,
        doc=f"custom property ({kind})",
        emit=lambda v: Command("map.object.property.set", scope,
                               {"key": key, "value": v}),
        removable=True,
        remove=lambda _v: Command("map.object.property.remove", scope,
                                  {"key": key}))


_SHAPE_TAGS = ("point", "ellipse", "polygon", "polyline", "text")


def _shape_of(obj) -> str:
    """A tmx object's shape is decided by which child element it carries."""
    for child in obj.element:
        if child.tag in _SHAPE_TAGS:
            return child.tag
    return "rectangle"


def _number(value: Any) -> str:
    """tmx attributes are text, and Tiled writes whole numbers without .0."""
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


# --------------------------------------------------------------------------
# Layers
# --------------------------------------------------------------------------

def _describe_layer(session, scope: Scope) -> Inspection:
    document = session.project.map(scope.require("map"))
    name = scope.require("layer")
    pack = session.project.genre
    declared = pack.layer(name)

    facts = Section("Layer", [
        Field("name", "name", "str", name,
              doc="renaming a layer is not yet a command",
              blocked_reason="MapDocument cannot rename layers yet"),
    ])
    if declared:
        facts.fields.append(Field("depth", "draw depth", "int", declared.depth,
                                  doc=declared.doc))
        facts.fields.append(Field("required", "required by genre", "bool",
                                  declared.required))
    else:
        facts.note = (f"{name!r} is not declared by genre {pack.id!r}. If "
                      f"scripts/core/depth.py does not map it either, it "
                      f"will not render at all.")

    if name in document.tile_layer_names():
        layer = document.tile_layer(name)
        gids = layer.gids()
        used = sorted({g for g in gids if g})
        stats = Section("Tiles", [
            Field("size", "size", "str", f"{layer.width} x {layer.height}"),
            Field("occupied", "occupied cells", "str",
                  f"{sum(1 for g in gids if g)} of {len(gids)}"),
            Field("distinct", "distinct gids", "int", len(used)),
        ])
        subheading = "tile layer"
    else:
        layer = document.object_layer(name)
        objects = layer.objects()
        classes: dict[str, int] = {}
        for obj in objects:
            classes[obj.type or "(none)"] = classes.get(obj.type or "(none)", 0) + 1
        stats = Section("Objects", [
            Field("count", "objects", "int", len(objects)),
        ] + [Field(f"class:{k}", k, "int", v) for k, v in sorted(classes.items())])
        subheading = "object layer"

    profile = layers.read_profile(layer)
    capabilities = Section(
        "Capabilities",
        note="what this layer declares about itself. Stored as tmx custom "
             "properties, so Tiled shows them too.")
    for capability in layers.CAPABILITIES:
        current = profile.values.get(capability.key, capability.default)
        declared = capability.key in profile.values
        capabilities.fields.append(Field(
            capability.key,
            capability.label + ("" if declared else "  (default)"),
            "choice" if capability.choices else capability.type,
            current,
            doc=capability.doc,
            choices=capability.choices,
            emit=(lambda k: lambda v: Command(
                "map.layer.set", scope, {"key": k, "value": v}))(capability.key),
            removable=declared,
            remove=(lambda k: lambda _v: Command(
                "map.layer.unset", scope, {"key": k}))(capability.key)))
    if not profile.is_static:
        capabilities.note += ("\n\nThis layer is DYNAMIC, so it is excluded "
                              "from the baked map composite and costs one "
                              "extra viewport blit per frame.")

    other = {k: v for k, v in sorted(layer.properties.as_dict().items())
             if k not in layers.BY_PROPERTY}
    custom = Section("Other properties",
                     note="authored properties the engine does not interpret")
    for key, value in other.items():
        custom.fields.append(Field(
            key, key, "str", value,
            blocked_reason="editing arbitrary layer properties is not yet a "
                           "command; use the capabilities above"))

    return Inspection(scope, name, subheading, [facts, stats,
                                                capabilities, custom])


# --------------------------------------------------------------------------
# Data tables
# --------------------------------------------------------------------------

def _describe_row(session, scope: Scope) -> Inspection:
    table_name = scope.require("table")
    row_id = scope.require("row")
    table = session.project.table(table_name)
    row = table.require_row(row_id)

    values = Section(table.title or table_name, note=table.doc)
    for column in table.columns:
        values.fields.append(Field(
            column.name, column.name, column.type, row.get(column.name),
            doc=column.doc,
            emit=(lambda name: lambda v: Command(
                "table.row.set", scope, {"column": name, "value": v}))(column.name)))
    return Inspection(scope, row_id, f"row of {table_name}", [values])


def _describe_table(session, scope: Scope) -> Inspection:
    name = scope.require("table")
    if not session.project.has_table(name):
        declared = session.project.genre.table(name)
        return Inspection(
            scope, name, "not created yet",
            error=(f"the genre declares {name!r} but the project has not "
                   f"created it. Use table.create."
                   if declared else f"no table {name!r}"))
    table = session.project.table(name)
    schema = Section("Columns", note=table.doc)
    for column in table.columns:
        schema.fields.append(Field(
            column.name, column.name, "str",
            f"{column.type}   default {column.coerced_default()!r}",
            doc=column.doc))
    return Inspection(scope, table.title or name,
                      f"{len(table)} rows · {len(table.columns)} columns",
                      [schema])


# --------------------------------------------------------------------------
# Map and project
# --------------------------------------------------------------------------

def _describe_map(session, scope: Scope) -> Inspection:
    name = scope.require("map")
    document = session.project.map(name)
    facts = Section("Map", [
        Field("size", "size in tiles", "str",
              f"{document.width} x {document.height}"),
        Field("tile", "tile size", "str",
              f"{document.tile_width} x {document.tile_height} px"),
        Field("pixels", "size in pixels", "str",
              f"{document.width * document.tile_width} x "
              f"{document.height * document.tile_height}"),
        Field("path", "file", "str", document.path or "(unsaved)"),
        Field("dirty", "unsaved changes", "bool", document.changed),
    ])
    layers = Section("Layers", [
        Field("tile_layers", "tile layers", "str",
              ", ".join(document.tile_layer_names()) or "none"),
        Field("object_layers", "object layers", "str",
              ", ".join(document.object_layer_names()) or "none"),
    ])
    return Inspection(scope, f"map: {name}", document.path or "", [facts, layers])


def _describe_project(session, scope: Scope) -> Inspection:
    project = session.project
    facts = Section("Project", [
        Field("genre", "genre", "choice", project.genre.id,
              doc=project.genre.summary,
              choices=tuple(_genres()),
              emit=lambda v: Command("project.genre.set", Scope.of("project"),
                                     {"genre": str(v)})),
        Field("root", "root", "str", project.root),
        Field("maps", "maps", "str", ", ".join(project.map_names()) or "none"),
        Field("tables", "tables", "str",
              ", ".join(project.table_names()) or "none"),
    ])
    return Inspection(scope, "project", project.genre.title, [facts])


def _describe_genre(session, scope: Scope) -> Inspection:
    pack = session.project.genre
    layers = Section("Declared layers", [
        Field(l.name, l.name, "str",
              f"{l.kind}   depth {l.depth}"
              f"{'   required' if l.required else ''}",
              doc=l.doc)
        for l in pack.layers])
    tables = Section("Declared tables", [
        Field(t.name, t.name, "str",
              f"{len(t.fields)} columns"
              f"{'   required' if t.required else ''}",
              doc=t.doc)
        for t in pack.tables])
    return Inspection(scope, pack.title, pack.id, [layers, tables])


def _genres() -> list[str]:
    from editor.core import genre as genre_module
    return genre_module.available()


_BUILDERS = {
    "object": _describe_object,
    "layer": _describe_layer,
    "row": _describe_row,
    "table": _describe_table,
    "map": _describe_map,
    "project": _describe_project,
    "genre": _describe_genre,
}
