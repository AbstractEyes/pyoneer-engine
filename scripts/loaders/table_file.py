"""Read `data/project/tables/*.json` -- the engine side of the Database.

WHY THIS MODULE EXISTS AT ALL
-----------------------------
Ten behavior parameters declare `source="actors"`. `resolve_params` has taken
an actors row as its third argument since the day it was written, and every
caller in the tree passed `None`, so the middle rung of the documented ladder

    1. `pyoneer_param_<key>` on the object      this object, this map
    2. the actors row's `<key>` column          this actor, everywhere
    3. `BehaviorParam.default`                  nobody said anything

could never fire. `hp`, `move_speed`, `gravity`, `jump_velocity` and
`coyote_ms` were authored in the editor's Database panel and every one of
them fell to its declared default. The seam was built; nothing supplied it.
This is the supply.

WHY IT IS NOT `editor.core.project.DataTable`
---------------------------------------------
`scripts/` may never import `editor/` (law 2), and the corollary paid for in
`29fbfc1` says the answer is to MOVE shared logic here rather than copy it.
This is neither a move nor a copy, because the two do different jobs and
share no lines worth sharing:

    DataTable       an EDITABLE document -- add_column, set_value, dirty,
                    to_json, from_genre, and a schema the file owns because
                    `table.column.add` may extend it
    ProjectTable    a READ of the same bytes -- rows, and the column names
                    needed to catch a row key the schema does not declare

The one thing that would be a genuine duplicate is type coercion, and this
module deliberately does not do any. `Column.check` types a value on the way
IN, against the schema the author is editing. On the way out the only type
that matters is the one declared by the parameter that will receive the
value, and `BehaviorParam.coerce` is where that lives -- so `hp: "three"`
raises there, naming the object, the behavior and the key, rather than here
naming a column no reader has been identified for yet. One coercion, at the
point of use. A column nothing consumes is never coerced, which is correct:
`display_name` is a string to the editor and nothing at all to the engine.

MISSING IS NOT AN ERROR. UNREADABLE AND CONTRADICTORY ARE.
----------------------------------------------------------
The line matters more here than anywhere else in this file, because getting
it wrong breaks every map that never asked for any of this:

    no `data/project/tables/` directory      an empty table set, no error
    a table with no rows                     an empty table, no error
    an object with no `pyoneer_actor`        `actor_row` returns None, and
                                             step 3 answers exactly as before
    a row that omits a column                `resolve_params` falls to the
                                             declared default, unchanged

    a file that is not JSON                  raises, naming the path
    a file whose `table` disagrees with its  raises: `table("actors")` would
      own filename                             otherwise miss it silently
    a row carrying a key the file declares   raises: the value WOULD be read
      no column for                            by `resolve_params`, which
                                             matches on key and not on
                                             schema, so an off-schema key is
                                             a live value hiding behind a
                                             file that says it does not exist
    `pyoneer_actor` naming an absent row     raises, naming the object

The last one is the whole point of the property. A `pyoneer_actor` that
resolved to nothing would look exactly like a working one -- every parameter
would quietly fall to its default -- which is the 39-silently-dropped-tiles
failure this repository refuses.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from scripts.core.errors import PyoneerAssetMissingError, PyoneerConfigError
from scripts.core.log import trace_assets
from scripts.game.behavior.base import ACTOR

TABLES_DIR: str = os.path.join("data", "project", "tables")
"""Where the editor writes its tables, relative to the repository root.

Spelled once. `editor/core/project.py` composes the same path from its own
`PROJECT_DIR` + `TABLES_DIR`, and the two are joined by the FILES, not by an
import -- that is the entire interface between the editor and the engine.
"""

ACTORS: str = "actors"
"""The table a `source="actors"` parameter reads, and the only one today.

A FILE FORMAT string (law 8): it is the table's name inside the .json, the
stem of the file on disk, and the literal in `PARAM_SOURCES`. Never renamed.
`tools/check_behavior.py` asserts this constant is one of `PARAM_SOURCES`,
so the two spellings cannot drift apart.
"""

_REPO_ROOT: str = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))


def default_tables_dir() -> str:
    """`data/project/tables` under the repo root, absolute.

    Anchored to this file rather than to the working directory, for the same
    reason `config/managers/map_data.py` anchors REPO_ROOT that way: a game
    launched from a shortcut has whatever cwd the shortcut had.
    """
    return os.path.join(_REPO_ROOT, TABLES_DIR)


# ---------------------------------------------------------------------------
# The values
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProjectTable:
    """One `data/project/tables/<name>.json`, read.

    Frozen and holding plain dicts, because the engine never writes one. The
    editor is the only writer; a runtime that mutated a row would produce a
    game whose behaviour depended on how long it had been running, and would
    then not save it.
    """

    name: str
    path: str
    columns: tuple[str, ...]
    rows: Mapping[str, Mapping[str, Any]]

    def has(self, row_id: str) -> bool:
        return row_id in self.rows

    def row(self, row_id: str, where: str = "") -> Mapping[str, Any]:
        """One row, or raise naming the row, the table and the asker.

        No `.get`-shaped sibling that returns None, deliberately. Every
        caller of this reached it because something in a map NAMED this row,
        and a None would travel one frame further and arrive as a default.
        """
        if row_id not in self.rows:
            raise PyoneerAssetMissingError(
                "%s-table row" % self.name, row_id,
                available=sorted(self.rows)[:20],
                asked_by=where or "<unknown>", table_file=self.path,
                row_count=len(self.rows))
        return self.rows[row_id]

    def __len__(self) -> int:
        return len(self.rows)


@dataclass(frozen=True)
class ProjectTables:
    """Every table in one `tables/` directory. Possibly none of them."""

    directory: str
    tables: Mapping[str, ProjectTable]

    def __contains__(self, name: str) -> bool:
        return name in self.tables

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self.tables))

    def __len__(self) -> int:
        return len(self.tables)

    def names(self) -> list[str]:
        return sorted(self.tables)

    def table(self, name: str, where: str = "") -> ProjectTable:
        if name not in self.tables:
            raise PyoneerAssetMissingError(
                "data table", name, available=self.names(),
                asked_by=where or "<unknown>", directory=self.directory)
        return self.tables[name]

    def row(self, table: str, row_id: str, where: str = "") -> Mapping[str, Any]:
        """A row from a named table. Raises if either half is absent."""
        return self.table(table, where).row(row_id, where)


EMPTY: ProjectTables = ProjectTables(directory="", tables={})
"""What a project with no tables directory reads as.

A real, empty value rather than None, so `load_tables` has one return type
and a caller never has to write the `is None` branch this constant exists to
delete. `actor_row` still distinguishes the two, and for a reason stated
there: `None` means nobody wired a reader, `EMPTY` means the project has no
tables, and those two mistakes have different fixes.
"""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _bad(path: str, message: str, **context: Any) -> PyoneerConfigError:
    return PyoneerConfigError(
        "%s: %s" % (os.path.basename(path), message), path=path, **context)


def load_table(path: str) -> ProjectTable:
    """Read one table file, or raise saying which file and what is wrong.

    Every raise below names the file. A table that fails to load is not
    skipped: a project whose `actors.json` has a stray comma would otherwise
    boot with every actor at its default, which looks precisely like a game
    where the numbers do not matter.
    """
    with open(path, "r", encoding="utf-8") as handle:
        try:
            raw = json.load(handle)
        except json.JSONDecodeError as exc:
            raise _bad(path, "not valid JSON (%s)" % exc) from exc

    if not isinstance(raw, dict):
        raise _bad(path, "a table file is a JSON object, not %s"
                   % type(raw).__name__)

    name = raw.get("table")
    if not isinstance(name, str) or not name:
        raise _bad(path, "needs a 'table' key naming the table")

    stem = os.path.splitext(os.path.basename(path))[0]
    if name != stem:
        # Contradictory, not merely untidy: `Project.save` writes
        # `<table.name>.json` and `table('actors')` looks the name up, so a
        # file called actors.json declaring `"table": "actor"` is a table
        # nothing can address under either spelling.
        raise _bad(path, "declares table %r but is named %r; the file name "
                         "and the 'table' key are the same identifier"
                   % (name, stem + ".json"))

    declared = raw.get("columns", [])
    if not isinstance(declared, list):
        raise _bad(path, "'columns' is a list, not %s"
                   % type(declared).__name__)
    columns: list[str] = []
    for index, entry in enumerate(declared):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise _bad(path, "column %d has no 'name' string" % index)
        columns.append(entry["name"])

    raw_rows = raw.get("rows", {})
    if not isinstance(raw_rows, dict):
        raise _bad(path, "'rows' is a JSON object keyed by row id, not %s"
                   % type(raw_rows).__name__)
    known = set(columns)
    rows: dict[str, Mapping[str, Any]] = {}
    for row_id, values in raw_rows.items():
        if not isinstance(values, dict):
            raise _bad(path, "row %r is %s, not an object of column -> value"
                       % (row_id, type(values).__name__))
        stray = sorted(k for k in values if k not in known)
        if stray:
            # `resolve_params` matches an actors row on the parameter KEY, so
            # an off-schema key is not inert -- it is a value that reaches a
            # behavior out of a file whose own schema denies it exists.
            raise _bad(path, "row %r carries %s, which this table declares no "
                             "column for; columns are %s"
                       % (row_id, ", ".join(repr(k) for k in stray),
                          ", ".join(sorted(known)) or "<none>"))
        rows[str(row_id)] = dict(values)

    return ProjectTable(name=name, path=os.path.abspath(path),
                        columns=tuple(columns), rows=rows)


def load_tables(directory: str | None = None) -> ProjectTables:
    """Every `*.json` in a tables directory. A missing directory is empty.

    `directory=None` means `default_tables_dir()`. A project that ships no
    `data/project/tables/` is not broken and not unusual -- it is every map
    that predates the Database -- so it reads as `EMPTY` and every
    `source="actors"` parameter answers from its declared default, exactly as
    it did before this module existed.
    """
    target = default_tables_dir() if directory is None else directory
    if not os.path.isdir(target):
        trace_assets("load_tables %s absent -> no tables", target)
        return ProjectTables(directory=os.path.abspath(target), tables={})
    tables: dict[str, ProjectTable] = {}
    for entry in sorted(os.listdir(target)):
        if not entry.endswith(".json"):
            continue
        table = load_table(os.path.join(target, entry))
        tables[table.name] = table
    trace_assets("load_tables %s -> %d table(s): %s",
                 target, len(tables), ", ".join(sorted(tables)) or "<none>")
    return ProjectTables(directory=os.path.abspath(target), tables=tables)


# ---------------------------------------------------------------------------
# The tmx object -> row link
# ---------------------------------------------------------------------------

def row_id(value: Any, where: str = "") -> str:
    """`pyoneer_actor`'s value as a row id, or raise saying why it is not one.

    Row ids are STRINGS in the file (`Project.save` writes `str(k)`), and a
    tmx property may arrive as `int` when Tiled typed it, so both are
    accepted and normalised. `bool` and `float` are not: `True` would address
    a row called `'True'` and `1.0` a row called `'1.0'`, and both would fail
    the lookup with a message about a missing row rather than about the
    typed property that is actually wrong.
    """
    blame = (" (%s)" % where) if where else ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise PyoneerConfigError(
            "%s is %r, a %s; an actors row id is written as a string or a "
            "whole number%s" % (ACTOR, value, type(value).__name__, blame))
    text = str(value).strip()
    if not text:
        raise PyoneerConfigError(
            "%s is present and empty%s; remove the property, or give it the "
            "id of a row in the %s table" % (ACTOR, blame, ACTORS))
    return text


def actor_row(tables: ProjectTables | None,
              properties: Mapping[str, Any] | None,
              where: str = "") -> Mapping[str, Any] | None:
    """The actors row a tmx object names, or None when it names none.

    THE THIRD ARGUMENT `resolve_params` HAS ALWAYS TAKEN. Two callers reach
    this -- `map_loader.spawn_objects` for an authored object and
    `SceneManager.spawn` for a runtime one -- and they reach the same
    function rather than each reading `pyoneer_actor` themselves, so a
    projectile built in Python and an object placed in Tiled cannot disagree
    about what naming a row means.

    None comes back for an object with no `pyoneer_actor`, which is every
    object on every map shipped today, and step 2 is then skipped exactly as
    it always was.

    `tables is None` is NOT the same as an empty table set, and the
    difference is which mistake was made. `EMPTY` means the project has no
    `actors` table, so an object naming a row is naming one that does not
    exist -- an authoring error. `None` means nobody handed this spawn pass a
    reader at all -- a wiring error, in Python, and the message says so.
    Collapsing them would report a missing row to someone who forgot a line
    in their boot sequence.
    """
    raw = None if properties is None else properties.get(ACTOR)
    if raw is None:
        return None
    wanted = row_id(raw, where)
    blame = where or "a tmx object"
    if tables is None:
        raise PyoneerConfigError(
            "%s names %s=%r and this spawn pass was given no data tables, so "
            "the row cannot be read. Load them with "
            "`scripts.loaders.table_file.load_tables()` and assign them to "
            "`LayerRenderer.tables` before the map is bound; that is the one "
            "slot both the map spawn and `SceneManager.spawn` read."
            % (blame, ACTOR, wanted))
    return tables.row(ACTORS, wanted, blame)
