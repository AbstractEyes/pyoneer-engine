"""The project document -- what the editor edits and the engine reads.

THE CONTRACT WITH THE ENGINE
----------------------------
The editor never talks to a running game. It writes the files the engine
already loads:

    data/maps/*.tmx          via MapDocument, byte-faithfully
    data/project/*.json      data tables, read by the game at boot
    data/project/project.json  which genre this project is

That is the entire interface. Consequences worth stating plainly, because
they are the reason it is built this way:

  * `python main.py` works on a clone with `editor/` deleted.
  * Nothing in the engine imports anything in the editor.
  * A human editing in Tiled and the editor editing the same map do not
    corrupt each other, because MapDocument does not reflow the file.
  * Live reload is an optimisation to add later, not a dependency.

DETERMINISTIC ON DISK
---------------------
Tables serialise with sorted keys and a trailing newline. An editor that
reorders JSON on every save makes every git diff unreadable, and this
project's whole review model is "the human reads what the AI changed".
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterator

from editor.core.errors import (
    PyoneerFieldMissingError,
    PyoneerProjectError,
    PyoneerRowMissingError,
    PyoneerTableMissingError,
)
from editor.core import genre as genre_module
from editor.core.genre import GenrePack, GenreTable
from scripts.loaders.map_document import MapDocument

PROJECT_DIR = os.path.join("data", "project")
PROJECT_FILE = "project.json"
TABLES_DIR = "tables"

_TYPES: dict[str, type] = {"int": int, "float": float, "str": str, "bool": bool}

# tmx elements that are layers, in Tiled's own vocabulary. `group` nests.
_LAYER_TAGS = ("layer", "objectgroup", "imagelayer", "group")
_TAG_KINDS = {"layer": "tile", "objectgroup": "object",
              "imagelayer": "image", "group": "group"}


@dataclass
class LayerNode:
    """One node of a map's authored layer tree.

    `MapDocument.layer_names()` returns a FLAT list that includes `<group>`
    elements alongside real layers, which is fine for lookup and useless for
    display -- it loses the nesting a designer authored in Tiled, and it
    invites treating a group as a layer. This preserves both.
    """

    name: str
    kind: str                       # tile | object | image | group
    children: list["LayerNode"] = field(default_factory=list)

    @property
    def selectable(self) -> bool:
        """A group holds layers but is not one; no verb can act on it."""
        return self.kind != "group"

    def walk(self) -> Iterator["LayerNode"]:
        yield self
        for child in self.children:
            yield from child.walk()


def layer_tree(document) -> list[LayerNode]:
    """The map's layers as authored, nesting preserved."""

    def build(element) -> list[LayerNode]:
        nodes: list[LayerNode] = []
        for child in element:
            if child.tag not in _LAYER_TAGS:
                continue
            node = LayerNode(child.get("name", ""), _TAG_KINDS[child.tag])
            if child.tag == "group":
                node.children = build(child)
            nodes.append(node)
        return nodes

    return build(document.root)


# --------------------------------------------------------------------------
# Data tables
# --------------------------------------------------------------------------

@dataclass
class Column:
    name: str
    type: str
    doc: str = ""
    default: Any = None

    def coerced_default(self) -> Any:
        if self.default is not None:
            return self.default
        return {"int": 0, "float": 0.0, "str": "", "bool": False}[self.type]

    def check(self, value: Any) -> Any:
        want = _TYPES[self.type]
        if want is float and isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        if want is not bool and isinstance(value, bool):
            raise PyoneerProjectError(
                f"column {self.name!r} wants {self.type}, got bool",
                column=self.name)
        if not isinstance(value, want):
            raise PyoneerProjectError(
                f"column {self.name!r} wants {self.type}, got "
                f"{type(value).__name__} ({value!r})", column=self.name)
        return value

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "type": self.type}
        if self.doc:
            out["doc"] = self.doc
        if self.default is not None:
            out["default"] = self.default
        return out


@dataclass
class DataTable:
    """A named table of rows -- actors, weapons, levels, whatever the genre says.

    The *file* is the schema authority, not the genre pack. The pack declares
    a starting shape; `table.column.add` may extend it. That is deliberate:
    the user asked to be able to add equipment and stat modifiers without
    the editor arguing, and a schema locked to the pack would argue.
    """

    name: str
    title: str = ""
    doc: str = ""
    columns: list[Column] = field(default_factory=list)
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    dirty: bool = False

    # -- schema ------------------------------------------------------------

    def field(self, name: str) -> Column | None:
        for column in self.columns:
            if column.name == name:
                return column
        return None

    def require_field(self, name: str) -> Column:
        column = self.field(name)
        if column is None:
            raise PyoneerFieldMissingError(
                f"table {self.name!r} has no column {name!r}",
                table=self.name, columns=[c.name for c in self.columns])
        return column

    def add_column(self, column: Column) -> None:
        if self.field(column.name) is not None:
            raise PyoneerProjectError(
                f"table {self.name!r} already has a column {column.name!r}",
                table=self.name)
        self.columns.append(column)
        for row in self.rows.values():
            row.setdefault(column.name, column.coerced_default())
        self.dirty = True

    def remove_column(self, name: str) -> Column:
        column = self.require_field(name)
        self.columns.remove(column)
        for row in self.rows.values():
            row.pop(name, None)
        self.dirty = True
        return column

    # -- rows --------------------------------------------------------------

    def require_row(self, row_id: str) -> dict[str, Any]:
        if row_id not in self.rows:
            raise PyoneerRowMissingError(
                f"table {self.name!r} has no row {row_id!r}",
                table=self.name, rows=sorted(self.rows)[:20],
                row_count=len(self.rows))
        return self.rows[row_id]

    def add_row(self, row_id: str, values: dict[str, Any] | None = None) -> dict[str, Any]:
        if row_id in self.rows:
            raise PyoneerProjectError(
                f"table {self.name!r} already has a row {row_id!r}",
                table=self.name)
        row = {c.name: c.coerced_default() for c in self.columns}
        for key, value in (values or {}).items():
            row[key] = self.require_field(key).check(value)
        self.rows[row_id] = row
        self.dirty = True
        return row

    def remove_row(self, row_id: str) -> dict[str, Any]:
        row = dict(self.require_row(row_id))
        del self.rows[row_id]
        self.dirty = True
        return row

    def set_value(self, row_id: str, column: str, value: Any) -> Any:
        row = self.require_row(row_id)
        checked = self.require_field(column).check(value)
        previous = row.get(column)
        row[column] = checked
        self.dirty = True
        return previous

    def row_ids(self) -> list[str]:
        return sorted(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self) -> Iterator[tuple[str, dict[str, Any]]]:
        for row_id in self.row_ids():
            yield row_id, self.rows[row_id]

    # -- persistence -------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "table": self.name,
            "title": self.title,
            "doc": self.doc,
            "columns": [c.to_json() for c in self.columns],
            "rows": {rid: dict(sorted(row.items())) for rid, row in sorted(self.rows.items())},
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any], *, path: str = "") -> "DataTable":
        if "table" not in raw:
            raise PyoneerProjectError("a table file needs a 'table' key", path=path)
        columns = []
        for item in raw.get("columns", []):
            type_name = item.get("type", "str")
            if type_name not in _TYPES:
                raise PyoneerProjectError(
                    f"column {item.get('name')!r} has type {type_name!r}; "
                    f"must be one of {sorted(_TYPES)}", path=path)
            columns.append(Column(item["name"], type_name,
                                  item.get("doc", ""), item.get("default")))
        return cls(
            name=raw["table"],
            title=raw.get("title", raw["table"].title()),
            doc=raw.get("doc", ""),
            columns=columns,
            rows={str(k): dict(v) for k, v in raw.get("rows", {}).items()},
        )

    @classmethod
    def from_genre(cls, declared: GenreTable) -> "DataTable":
        return cls(
            name=declared.name,
            title=declared.title,
            doc=declared.doc,
            columns=[Column(f.name, f.type, f.doc, f.default) for f in declared.fields],
        )


# --------------------------------------------------------------------------
# The project
# --------------------------------------------------------------------------

class Project:
    """Everything the editor can address, rooted at a repo checkout."""

    def __init__(self, root: str, pack: GenrePack, meta: dict[str, Any] | None = None):
        self.root = os.path.abspath(root)
        self.genre = pack
        self.meta = meta or {}
        self.__maps: dict[str, str] = {}          # name -> absolute .tmx path
        self.__open_maps: dict[str, MapDocument] = {}
        self.__tables: dict[str, DataTable] = {}
        self.__load_map_index()
        self.__load_tables()

    # -- paths -------------------------------------------------------------

    def path(self, *parts: str) -> str:
        return os.path.normpath(os.path.join(self.root, *parts))

    @property
    def project_dir(self) -> str:
        return self.path(PROJECT_DIR)

    @property
    def tables_dir(self) -> str:
        return self.path(PROJECT_DIR, TABLES_DIR)

    # -- maps --------------------------------------------------------------

    def __load_map_index(self) -> None:
        config = self.path("config", "maps.json")
        if not os.path.isfile(config):
            return
        with open(config, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        for entry in raw.get("data", []):
            self.__maps[entry["name"]] = self.path(entry["file"])

    def map_names(self) -> list[str]:
        return sorted(self.__maps)

    def map_path(self, name: str) -> str:
        if name not in self.__maps:
            raise PyoneerProjectError(
                f"no map named {name!r}", available=self.map_names(),
                source="config/maps.json")
        return self.__maps[name]

    def map(self, name: str) -> MapDocument:
        """The editable document for a map, opened once and cached."""
        if name not in self.__open_maps:
            path = self.map_path(name)
            if not os.path.isfile(path):
                raise PyoneerProjectError(
                    f"map {name!r} points at {path}, which does not exist",
                    source="config/maps.json")
            self.__open_maps[name] = MapDocument.load(path)
        return self.__open_maps[name]

    def is_map_open(self, name: str) -> bool:
        return name in self.__open_maps

    def dirty_maps(self) -> list[str]:
        return sorted(n for n, d in self.__open_maps.items() if d.changed)

    # -- tables ------------------------------------------------------------

    def __load_tables(self) -> None:
        directory = self.tables_dir
        if not os.path.isdir(directory):
            return
        for entry in sorted(os.listdir(directory)):
            if not entry.endswith(".json"):
                continue
            path = os.path.join(directory, entry)
            with open(path, "r", encoding="utf-8") as handle:
                try:
                    raw = json.load(handle)
                except json.JSONDecodeError as exc:
                    raise PyoneerProjectError(
                        f"table file is not valid JSON: {exc}", path=path) from exc
            table = DataTable.from_json(raw, path=path)
            self.__tables[table.name] = table

    def table_names(self) -> list[str]:
        return sorted(self.__tables)

    def table(self, name: str) -> DataTable:
        if name not in self.__tables:
            raise PyoneerTableMissingError(
                f"no table named {name!r}", available=self.table_names(),
                hint="the genre declares it but the project has not created "
                     "it yet; use table.create")
        return self.__tables[name]

    def has_table(self, name: str) -> bool:
        return name in self.__tables

    def create_table(self, table: DataTable) -> DataTable:
        if table.name in self.__tables:
            raise PyoneerProjectError(
                f"table {table.name!r} already exists", table=table.name)
        table.dirty = True
        self.__tables[table.name] = table
        return table

    def drop_table(self, name: str) -> DataTable:
        table = self.table(name)
        del self.__tables[name]
        path = os.path.join(self.tables_dir, f"{name}.json")
        if os.path.isfile(path):
            os.remove(path)
        return table

    def dirty_tables(self) -> list[str]:
        return sorted(n for n, t in self.__tables.items() if t.dirty)

    # -- genre -------------------------------------------------------------

    def set_genre(self, pack: GenrePack) -> GenrePack:
        previous = self.genre
        self.genre = pack
        self.meta["genre"] = pack.id
        return previous

    def problems(self) -> list:
        return self.genre.validate(self)

    # -- persistence -------------------------------------------------------

    def save(self) -> list[str]:
        """Write every dirty document. Returns the paths written."""
        written: list[str] = []
        os.makedirs(self.tables_dir, exist_ok=True)

        for name, document in self.__open_maps.items():
            if document.changed:
                written.append(document.save())

        for name, table in self.__tables.items():
            if not table.dirty:
                continue
            path = os.path.join(self.tables_dir, f"{name}.json")
            payload = json.dumps(table.to_json(), indent=2, sort_keys=True)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload + "\n")
            table.dirty = False
            written.append(path)

        meta_path = os.path.join(self.project_dir, PROJECT_FILE)
        os.makedirs(self.project_dir, exist_ok=True)
        self.meta["genre"] = self.genre.id
        with open(meta_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(self.meta, indent=2, sort_keys=True) + "\n")
        written.append(meta_path)
        return written

    @property
    def dirty(self) -> bool:
        return bool(self.dirty_maps() or self.dirty_tables())

    # -- loading -----------------------------------------------------------

    @classmethod
    def load(cls, root: str, *, genre_id: str | None = None,
             genres_dir: str | None = None) -> "Project":
        """Open the project rooted at `root`.

        `genre_id` overrides what project.json says, which is how "switch
        this project to a platformer" works.
        """
        root = os.path.abspath(root)
        meta_path = os.path.join(root, PROJECT_DIR, PROJECT_FILE)
        meta: dict[str, Any] = {}
        if os.path.isfile(meta_path):
            with open(meta_path, "r", encoding="utf-8") as handle:
                try:
                    meta = json.load(handle)
                except json.JSONDecodeError as exc:
                    raise PyoneerProjectError(
                        f"project.json is not valid JSON: {exc}",
                        path=meta_path) from exc

        chosen = genre_id or meta.get("genre")
        if not chosen:
            options = genre_module.available(genres_dir)
            if not options:
                raise PyoneerProjectError(
                    "no genre packs are installed and the project does not "
                    "name one", looked_in=genre_module.GENRES_DIR)
            chosen = options[0]
        pack = genre_module.load(chosen, genres_dir)
        return cls(root, pack, meta)
