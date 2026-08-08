"""Genre packs -- the rules that make a request short.

THE PROBLEM THEY SOLVE
----------------------
"Make me a platformer with guns and aliens and robots" is eight words. The
work behind it is thousands. Somebody has to supply the difference, and if
it is the prompt, every request is enormous and every answer is a fresh
invention with its own naming, its own layer names, its own idea of where
gravity lives.

A genre pack supplies the difference *once*. It declares:

  layers   what a map of this genre has, and what each one means
  tables   what data this genre keeps (actors, weapons, levels, ...)
  docks    which editor panels are relevant, so the UI is not a wall of
           tools for a genre you are not making
  rules    a markdown document that conditions the responding model --
           naming conventions, where engine code for this genre goes, what
           it must not touch
  template optional starting files copied into a new project

So the request becomes: eight words of intent, plus a pack the model can
read in a page. That is the whole trick.

HARD RULES AND SOFT RULES
-------------------------
A **hard** rule is one whose breach makes the game unloadable -- deleting
the layer the collision system reads by name. Commands that would break one
raise `PyoneerRuleViolationError` and the transaction rolls back.

A **soft** rule is a should -- "a platformer map usually has a PlayerStart".
Those surface as `RuleViolation` records in the Problems panel and never
block anything, because a project is allowed to be half-built. Making every
rule hard would turn the editor into a thing that argues with you.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

from editor.core.errors import (
    PyoneerGenreError,
    PyoneerGenreMissingError,
)
from editor.core.scope import Scope

GENRES_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "genres")

_FIELD_TYPES: dict[str, type] = {
    "int": int, "float": float, "str": str, "bool": bool,
}


# --------------------------------------------------------------------------
# Declarations
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class GenreField:
    """One column of a data table."""

    name: str
    type: str
    doc: str = ""
    default: Any = None
    required: bool = False

    @property
    def python_type(self) -> type:
        return _FIELD_TYPES[self.type]

    def coerced_default(self) -> Any:
        if self.default is not None:
            return self.default
        return {"int": 0, "float": 0.0, "str": "", "bool": False}[self.type]


@dataclass(frozen=True)
class GenreTable:
    """One data table the genre expects the project to keep."""

    name: str
    title: str
    doc: str = ""
    fields: tuple[GenreField, ...] = ()
    required: bool = False

    def field(self, name: str) -> GenreField | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None


@dataclass(frozen=True)
class GenreLayer:
    """One map layer the genre expects, and what it means."""

    name: str
    kind: str                    # "tile" | "object"
    depth: int = 0
    doc: str = ""
    required: bool = False
    collision: bool = False
    object_types: tuple[str, ...] = ()      # allowed classes on an object layer
    unique_types: tuple[str, ...] = ()      # classes that may appear at most once


@dataclass(frozen=True)
class GenrePack:
    """A loaded genre pack."""

    id: str
    title: str
    summary: str
    root: str
    layers: tuple[GenreLayer, ...] = ()
    tables: tuple[GenreTable, ...] = ()
    docks: tuple[str, ...] = ()
    rules_markdown: str = ""
    art_brief: str = ""

    # -- lookups -----------------------------------------------------------

    def layer(self, name: str) -> GenreLayer | None:
        for layer in self.layers:
            if layer.name == name:
                return layer
        return None

    def table(self, name: str) -> GenreTable | None:
        for table in self.tables:
            if table.name == name:
                return table
        return None

    @property
    def required_layers(self) -> tuple[GenreLayer, ...]:
        return tuple(l for l in self.layers if l.required)

    @property
    def template_dir(self) -> str | None:
        path = os.path.join(self.root, "template")
        return path if os.path.isdir(path) else None

    # -- hard rules --------------------------------------------------------

    def is_layer_required(self, name: str) -> bool:
        layer = self.layer(name)
        return bool(layer and layer.required)

    def is_field_required(self, table: str, field_name: str) -> bool:
        declared = self.table(table)
        if declared is None:
            return False
        f = declared.field(field_name)
        return bool(f and f.required)

    # -- soft rules --------------------------------------------------------

    def validate(self, project: Any) -> list["RuleViolation"]:
        """Everything wrong with `project` under this genre, none of it fatal."""
        found: list[RuleViolation] = []
        found.extend(self.__check_layers(project))
        found.extend(self.__check_tables(project))
        return found

    def __check_layers(self, project: Any) -> Iterable["RuleViolation"]:
        for map_name in project.map_names():
            try:
                document = project.map(map_name)
            except Exception as exc:                       # unreadable map
                yield RuleViolation(
                    "hard", Scope.of(("map", map_name)),
                    f"map could not be read: {exc}")
                continue
            present = set(document.layer_names())
            for layer in self.required_layers:
                if layer.name not in present:
                    yield RuleViolation(
                        "soft", Scope.of(("map", map_name)),
                        f"a {self.title} map wants a {layer.kind} layer "
                        f"named {layer.name!r} -- {layer.doc}",
                        fix=f"add it in Tiled, or the layer will not render")
            for layer in self.layers:
                if layer.kind != "object" or layer.name not in present:
                    continue
                if layer.name not in document.object_layer_names():
                    continue
                seen: dict[str, int] = {}
                for obj in document.object_layer(layer.name).objects():
                    kind = obj.type or ""
                    seen[kind] = seen.get(kind, 0) + 1
                    if layer.object_types and kind and kind not in layer.object_types:
                        yield RuleViolation(
                            "soft",
                            Scope.of(("map", map_name), ("layer", layer.name),
                                     ("object", str(obj.id))),
                            f"object class {kind!r} is not one this layer "
                            f"declares: {list(layer.object_types)}")
                for kind in layer.unique_types:
                    count = seen.get(kind, 0)
                    if count > 1:
                        yield RuleViolation(
                            "soft",
                            Scope.of(("map", map_name), ("layer", layer.name)),
                            f"{count} objects of class {kind!r}; this genre "
                            f"expects at most one")

    def __check_tables(self, project: Any) -> Iterable["RuleViolation"]:
        for declared in self.tables:
            if declared.name not in project.table_names():
                if declared.required:
                    yield RuleViolation(
                        "soft", Scope.of(("table", declared.name)),
                        f"a {self.title} project wants a {declared.name!r} "
                        f"table -- {declared.doc}",
                        fix="create it from the Tables panel")
                continue
            table = project.table(declared.name)
            for f in declared.fields:
                if f.required and table.field(f.name) is None:
                    yield RuleViolation(
                        "soft", Scope.of(("table", declared.name)),
                        f"required column {f.name!r} ({f.type}) is missing "
                        f"-- {f.doc}",
                        fix=f"table.column.add {f.name}")


@dataclass(frozen=True)
class RuleViolation:
    severity: str                # "hard" | "soft"
    scope: Scope
    message: str
    fix: str = ""

    def __str__(self) -> str:
        tail = f"  ({self.fix})" if self.fix else ""
        return f"[{self.severity}] {self.scope}: {self.message}{tail}"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def available(directory: str | None = None) -> list[str]:
    """Ids of every pack on disk."""
    base = directory or GENRES_DIR
    if not os.path.isdir(base):
        return []
    return sorted(
        name for name in os.listdir(base)
        if os.path.isfile(os.path.join(base, name, "genre.json")))


def load(genre_id: str, directory: str | None = None) -> GenrePack:
    base = directory or GENRES_DIR
    root = os.path.join(base, genre_id)
    manifest = os.path.join(root, "genre.json")
    if not os.path.isfile(manifest):
        raise PyoneerGenreMissingError(
            f"no genre pack {genre_id!r}",
            looked_in=base, available=available(base))
    with open(manifest, "r", encoding="utf-8") as handle:
        try:
            raw = json.load(handle)
        except json.JSONDecodeError as exc:
            raise PyoneerGenreError(
                f"genre.json is not valid JSON: {exc}", path=manifest) from exc
    return _build(genre_id, root, raw, manifest)


def _build(genre_id: str, root: str, raw: dict, path: str) -> GenrePack:
    def need(key: str) -> Any:
        if key not in raw:
            raise PyoneerGenreError(
                f"genre.json is missing required key {key!r}",
                path=path, has=sorted(raw))
        return raw[key]

    declared_id = need("id")
    if declared_id != genre_id:
        raise PyoneerGenreError(
            f"genre.json declares id {declared_id!r} but lives in a "
            f"directory named {genre_id!r}; they must match",
            path=path)

    layers = tuple(_layer(item, path) for item in raw.get("layers", []))
    tables = tuple(_table(item, path) for item in raw.get("tables", []))

    duplicate = _first_duplicate([l.name for l in layers])
    if duplicate:
        raise PyoneerGenreError(f"layer {duplicate!r} is declared twice", path=path)
    duplicate = _first_duplicate([t.name for t in tables])
    if duplicate:
        raise PyoneerGenreError(f"table {duplicate!r} is declared twice", path=path)

    rules_path = os.path.join(root, "RULES.md")
    rules = ""
    if os.path.isfile(rules_path):
        with open(rules_path, "r", encoding="utf-8") as handle:
            rules = handle.read()

    art_path = os.path.join(root, "ART.md")
    art = ""
    if os.path.isfile(art_path):
        with open(art_path, "r", encoding="utf-8") as handle:
            art = handle.read()

    return GenrePack(
        id=genre_id,
        title=need("title"),
        summary=raw.get("summary", ""),
        root=root,
        layers=layers,
        tables=tables,
        docks=tuple(raw.get("docks", [])),
        rules_markdown=rules,
        art_brief=art,
    )


def _layer(item: dict, path: str) -> GenreLayer:
    kind = item.get("kind", "tile")
    if kind not in ("tile", "object"):
        raise PyoneerGenreError(
            f"layer {item.get('name')!r} has kind {kind!r}; "
            f"must be 'tile' or 'object'", path=path)
    return GenreLayer(
        name=item["name"],
        kind=kind,
        depth=int(item.get("depth", 0)),
        doc=item.get("doc", ""),
        required=bool(item.get("required", False)),
        collision=bool(item.get("collision", False)),
        object_types=tuple(item.get("object_types", [])),
        unique_types=tuple(item.get("unique_types", [])),
    )


def _table(item: dict, path: str) -> GenreTable:
    fields = []
    for raw_field in item.get("fields", []):
        type_name = raw_field.get("type", "str")
        if type_name not in _FIELD_TYPES:
            raise PyoneerGenreError(
                f"table {item.get('name')!r} field "
                f"{raw_field.get('name')!r} has type {type_name!r}; "
                f"must be one of {sorted(_FIELD_TYPES)}", path=path)
        fields.append(GenreField(
            name=raw_field["name"],
            type=type_name,
            doc=raw_field.get("doc", ""),
            default=raw_field.get("default"),
            required=bool(raw_field.get("required", False)),
        ))
    return GenreTable(
        name=item["name"],
        title=item.get("title", item["name"].title()),
        doc=item.get("doc", ""),
        fields=tuple(fields),
        required=bool(item.get("required", False)),
    )


def _first_duplicate(names: list[str]) -> str | None:
    seen = set()
    for name in names:
        if name in seen:
            return name
        seen.add(name)
    return None
