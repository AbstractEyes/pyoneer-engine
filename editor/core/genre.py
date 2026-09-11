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
  loadouts which op vocabularies a script authored under this genre may
           draw on -- `event_loadouts`, a grant of NAMES and never of an op
           list, because the membership of a loadout is written once, in the
           specs, and a pack repeating it is a second home for that fact
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
from typing import Any, Iterable, Mapping

from editor.core.errors import (
    PyoneerGenreError,
    PyoneerGenreMissingError,
)
from editor.core.scope import Scope
from scripts.core.errors import PyoneerError
from scripts.game.behavior import registry as behavior_registry
from scripts.game.behavior.base import ACTOR, BEHAVIORS
from scripts.game.flow import ops as op_registry
from scripts.loaders.script_file import SCRIPT_PROPERTY, script_of
from scripts.loaders.table_file import ACTORS, row_id

GENRES_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "genres")

EVENT_LOADOUTS: str = "event_loadouts"
"""The `genre.json` key naming the op vocabularies this pack GRANTS.

A FILE FORMAT string under law 8, spelled once here and nowhere else in
this module, so the packs on disk and the parser cannot drift apart by a
typo that reads as a pack simply staying silent.
"""

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
class GenreObjectClass:
    """One class on an object layer, and the behavior list a NEW one starts with.

    NOT A FALLBACK THE ENGINE RESOLVES. The editor MATERIALISES this list
    into `pyoneer_behaviors` on the object as it is added, and never looks at
    it again -- `scripts/` may not import `editor/`, so the engine cannot
    read a pack, and the `.tmx` staying the whole truth is what makes a map
    play the same whether or not the editor has ever opened it.

    So this is a STARTING VALUE, not a policy: an author who edits the
    object's list keeps that edit forever, because nothing reads this after
    the add.

    `behaviors` is validated at pack load against the live registry -- an
    unregistered token here would be written into every object placed from
    this pack and make each of those maps raise at load, which is the
    loudest possible way to be wrong at the latest possible moment.
    """

    type: str
    behaviors: tuple[str, ...] = ()
    doc: str = ""

    @property
    def behaviors_text(self) -> str:
        """The canonical `pyoneer_behaviors` value, from the engine's own formatter."""
        return behavior_registry.format_list(self.behaviors)


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
    object_classes: tuple[GenreObjectClass, ...] = ()   # per-class starting lists

    def object_class(self, object_type: str) -> GenreObjectClass | None:
        for declared in self.object_classes:
            if declared.type == object_type:
                return declared
        return None


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
    event_loadouts: tuple[str, ...] | None = None
    """Which op vocabularies a script authored under this pack may use.

    THREE STATES, and the difference between two of them is the whole
    compatibility promise:

      None   the pack is SILENT. Every pack that shipped before one filled
             this in is silent, and silence grants everything, so a pack
             that never mentions the key behaves exactly as it did.
      ()     the pack grants NOTHING. A deliberate statement -- this genre
             does not script -- and not the same fact as silence.
      (...)  the names it grants, as authored, already judged by
             `ops.validate_loadouts` at pack load.
    """

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

    def object_class(self, layer: str,
                     object_type: str) -> GenreObjectClass | None:
        """What a new `object_type` on `layer` starts as, if the pack says.

        `None` for every layer and class the pack is silent about, which is
        every pack that declares no `object_classes` at all -- silence is not
        an error, it is the state every pack shipped in until one filled the
        slot.
        """
        found = self.layer(layer)
        return found.object_class(object_type) if found else None

    # -- what a script authored here may say --------------------------------

    def grants(self, loadout: str) -> bool:
        """May a script under this pack draw on `loadout`?

        A silent pack answers True to everything, which is not generosity:
        it is the only answer that leaves a pack written before this key
        existed behaving the way it did yesterday.
        """
        if self.event_loadouts is None:
            return True
        return loadout in self.event_loadouts

    def granted_registry(
            self, registry: Mapping[str, op_registry.OpSpec] | None = None,
    ) -> Mapping[str, op_registry.OpSpec]:
        """The op table narrowed to what this pack grants.

        THE ONE SEAM A PICKER NEEDS. An op table is what every reader of the
        vocabulary already takes -- `ops.loadouts`, `ops.ops_in`,
        `ScriptDocument.commit`, the script editor's own palette -- so
        narrowing the TABLE offers the grant to all of them at once, and
        none of them grows a second opinion about membership.

        A silent pack returns the table it was handed, unchanged and by
        identity, so wiring this in cannot change what a pack that does not
        declare the key already shows.

        KNOW THIS BEFORE WIRING IT TO A READER: a pack granting `()` narrows
        to an EMPTY table, and a reader that judges documents against an
        empty table refuses every op in every script it opens. That is the
        truth about such a pack -- this genre does not script -- but it is a
        sentence a window has to say for itself ("this genre grants no
        scripting") rather than let a library report as ten broken ops.
        """
        table = op_registry.OP_REGISTRY if registry is None else registry
        if self.event_loadouts is None:
            return table
        allowed = set(self.event_loadouts)
        return {name: spec for name, spec in table.items()
                if spec.loadout in allowed}

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
        """Everything wrong with `project` under this genre, none of it fatal.

        The library is opened ONCE here and handed to both arms that want
        it. It used to be opened inside `__check_scripts`, behind that
        method's `event_loadouts is None` early return, so a pack that
        granted no loadout could not report a library that would not open
        at all -- and the object walk below needs the same library for an
        unrelated reason. Two reads would be two chances to disagree about
        what this project's scripts are.
        """
        found: list[RuleViolation] = []
        library, unreadable = _library_of(project)
        if unreadable:
            found.append(RuleViolation(
                "hard", Scope.of("project"),
                f"event scripts could not be read: {unreadable}"))
        found.extend(self.__check_layers(project))
        found.extend(self.__check_tables(project))
        found.extend(self.__check_scripts(library))
        found.extend(self.__check_object_links(project, library))
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

    def __check_scripts(self, library: Any) -> Iterable["RuleViolation"]:
        """Every script asking for a vocabulary this pack does not grant.

        This is where the grant reaches a human. It is a SOFT rule and it is
        deliberately soft: `event_loadouts` is a statement about where a
        script is meant to run, and a half-written project is allowed to
        have a script ahead of the pack that will grant it. The engine is
        the hard half -- `ops.check_loadout` raises at script load -- so
        making this raise too would only move the same refusal earlier and
        stop an author mid-sentence.

        A SILENT pack yields nothing at all, which is the same promise
        `_object_classes` makes about a missing key. A library that would
        not open yields nothing HERE either -- `validate` has already said
        so once, in its own sentence, and saying it twice is noise.
        """
        if self.event_loadouts is None or library is None:
            return
        granted = (", ".join(repr(l) for l in self.event_loadouts)
                   or "no loadout at all")
        for script_id in library.names():
            document = library.document(script_id)
            for loadout in document.loadouts:
                if self.grants(loadout):
                    continue
                yield RuleViolation(
                    "soft", Scope.of(("script", script_id)),
                    f"script {script_id!r} declares the {loadout!r} op "
                    f"loadout, which the {self.id!r} pack does not grant "
                    f"-- it grants {granted}",
                    fix=f'add "{loadout}" to this pack\'s '
                        f"{EVENT_LOADOUTS}, or use an op from a loadout it "
                        f"already grants")

    def __check_object_links(self, project: Any,
                             library: Any) -> Iterable["RuleViolation"]:
        """Every object naming a script, a row or a behavior that is not there.

        THE DELETE THAT BREAKS THE MAP. One click on `Delete` in the event
        screen takes a script out of the library and leaves every
        `pyoneer_script` naming it exactly where it is; the editor's own
        save then writes a project that does not boot. Measured before this
        loop existed: `problems()` was `[]` on both sides of that click, the
        map still said `pyoneer_script=signpost`, and the next
        `python main.py` raised `event script 'signpost' not found`. The one
        sentence that could have said so lived in `ObjectEditor.refresh_script`
        and fired only while the object screen happened to be open on that
        one object.

        SOFT, deliberately, for `__check_scripts`'s reason: a half-built
        project is allowed to name a document nobody has written yet, and
        the engine stays the hard half -- it still raises at map load. An
        editor that refused to OPEN such a project would argue with an
        author mid-sentence. So this says it; it does not forbid it.

        A map that will not parse is SKIPPED rather than reported, because
        `__check_layers` walks the same list and reports it once: two
        violations for one unreadable file is noise, not thoroughness.
        """
        for map_name in project.map_names():
            try:
                document = project.map(map_name)
            except Exception:                             # noqa: BLE001
                continue          # __check_layers reports it, in one place
            for layer_name in document.object_layer_names():
                for obj in document.object_layer(layer_name).objects():
                    properties = obj.properties.as_dict()
                    for prop in OBJECT_LINKS:
                        if prop not in properties:
                            continue
                        broken = _LINK_CHECKERS[prop](
                            properties[prop], project, library)
                        if broken is None:
                            continue
                        message, fix = broken
                        yield RuleViolation(
                            "soft",
                            Scope.of(("map", map_name), ("layer", layer_name),
                                     ("object", str(obj.id))),
                            message, fix=fix)

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
# The per-object joins -- a `pyoneer_` property that NAMES something the
# project has to contain
# --------------------------------------------------------------------------
#
# THREE PROPERTIES, ONE VOCABULARY, ONE WALK.  `pyoneer_script`,
# `pyoneer_actor` and `pyoneer_behaviors` each carry a name the engine
# resolves at map load and each RAISES there when the name resolves to
# nothing, so each of the three is a way for this editor to write a project
# that will not start.  All three were unvalidated together and all three are
# checked together here, out of ONE declared tuple, for the reason ACTIVE
# WARNINGS gives: a guard that lands on one route while its siblings grow
# without it is the shape this repository has now sighted nine times, and
# the one before this was three per-object properties with one guard between
# them.  A fourth such property is one entry in `_LINK_CHECKERS`; the walk in
# `__check_object_links` picks it up with no edit at all, which is the only
# form of "remember the siblings" that does not depend on remembering.
#
# THE JUDGEMENT IS ALWAYS THE ENGINE'S OWN READER and never a second opinion
# written here: `script_of` decides what counts as a dangling script,
# `row_id` decides what counts as a row id, `validate_list` decides what
# counts as a loadable token list.  So the editor cannot come to disagree
# with the game about WHICH projects are broken -- down to the details that
# drift first, like a present-and-empty value meaning "names none" for a
# script and being an error for an actor.  What the editor supplies is the
# SENTENCE: the words `ObjectEditor`'s Script and Actor rows already say, on
# the screen the author was looking at when they broke it.
#
# `fix` IS RENDERED VERBATIM by the Problems dock, so it says what to do and
# never repeats what is wrong.

def _message(exc: Exception) -> str:
    """One line of a `PyoneerError`, without its `via` context trail."""
    return str(getattr(exc, "message", exc)).strip()


def _script_link(value: Any, project: Any, library: Any):
    """Does `pyoneer_script` name a document this project holds?"""
    if library is None:
        return None                 # unreadable library; `validate` said so
    names = list(library.names())
    try:
        script_of(dict.fromkeys(names), {SCRIPT_PROPERTY: value},
                  "this object")
    except PyoneerError:
        return (
            f"{SCRIPT_PROPERTY}={str(value)!r} is not a script in this "
            f"project ({len(names)} exist). The engine raises at map load "
            f"naming this object.",
            "pick one that exists on this object's Script row, or press "
            "New... there to write it")
    return None


def _actor_link(value: Any, project: Any, library: Any):
    """Does `pyoneer_actor` name a row the actors table holds?"""
    try:
        wanted = row_id(value, "this object")
    except PyoneerError as exc:
        return (_message(exc),
                f"give it the id of a row in the {ACTORS} table on this "
                f"object's Actor row, or clear that row to remove the "
                f"property")
    if not project.has_table(ACTORS):
        return (
            f"{ACTOR}={wanted!r} names an actors row and this project has "
            f"no {ACTORS!r} table. The engine raises at map load naming "
            f"this object.",
            f"create the {ACTORS} table in the Database window, or clear "
            f"this object's Actor row")
    rows = project.table(ACTORS).rows
    if wanted in rows:
        return None
    return (
        f"{ACTOR}={wanted!r} is not a row in the {ACTORS} table "
        f"({len(rows)} rows). The engine raises at map load naming this "
        f"object.",
        f"pick one that exists on this object's Actor row, or add the row "
        f"in the Database window")


def _behaviors_link(value: Any, project: Any, library: Any):
    """Will `pyoneer_behaviors` survive the registry at spawn?"""
    try:
        behavior_registry.validate_list(value, where="this object")
    except PyoneerError as exc:
        return (f"{BEHAVIORS} will not load, so the engine raises at map "
                f"load naming this object: {_message(exc)}",
                "fix the token list on this object; docs/BEHAVIORS.md is "
                "generated from the registry and lists every token that "
                "exists")
    return None


_LINK_CHECKERS = {
    SCRIPT_PROPERTY: _script_link,
    ACTOR: _actor_link,
    BEHAVIORS: _behaviors_link,
}

OBJECT_LINKS: tuple[str, ...] = tuple(_LINK_CHECKERS)
"""Every per-object `pyoneer_` property that names something else.

DERIVED from the table, never retyped beside it: a list and a dispatch map
that agree today are two things a later pass can make disagree, and the
sibling shape this constant exists to stop is exactly that. Iterating this
tuple and indexing that map is the same fact read twice.
"""


def _library_of(project: Any):
    """`(library, "")`, or `(None, why it would not open)`.

    Imported here rather than at module scope: `editor.core.event_script`
    imports `editor.core.project`, which imports THIS module, so a top-level
    import would be a cycle.
    """
    from editor.core import event_script

    try:
        return event_script.scripts_of(project), ""
    except Exception as exc:                                  # noqa: BLE001
        return None, str(exc)


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
        event_loadouts=_event_loadouts(raw, genre_id, path),
    )


def _event_loadouts(raw: dict, genre_id: str,
                    path: str) -> tuple[str, ...] | None:
    """Parse `event_loadouts`, the op vocabularies this pack GRANTS.

    ABSENT IS NOT AN ERROR, and absent is not the same as empty. A pack that
    never writes the key returns `None` and grants everything, because that
    is what every pack that shipped before this parser existed did; a pack
    that writes `[]` grants nothing, and means it. An explicit JSON `null`
    is neither, and is refused below with the rest of the nonsense.

    PRESENT AND UNKNOWN IS AN ERROR, loudly, at pack load -- the same timing
    and the same reason as `_object_classes` on an unregistered behavior
    token. A loadout exists because an op declares it, so a pack granting a
    name no op claims is granting a vocabulary that does not exist, and
    every script authored under it would be judged against nothing.

    The judge is `ops.validate_loadouts` -- the ENGINE's own, not a second
    copy -- for the same reason `_object_class` calls
    `behavior_registry.validate_list`: a list this accepts has to be a list
    the reader accepts, and two implementations of one rule disagree in
    silence.
    """
    if EVENT_LOADOUTS not in raw:
        return None
    try:
        return op_registry.validate_loadouts(
            raw[EVENT_LOADOUTS], where=f"genre pack {genre_id!r}")
    except PyoneerError as exc:
        detail = getattr(exc, "message", None) or str(exc)
        raise PyoneerGenreError(
            f"genre pack {genre_id!r} declares an {EVENT_LOADOUTS} the "
            f"engine refuses, so every script authored under this pack "
            f"would be judged against a vocabulary that does not exist: "
            f"{detail}", path=path) from exc


def _layer(item: dict, path: str) -> GenreLayer:
    kind = item.get("kind", "tile")
    if kind not in ("tile", "object"):
        raise PyoneerGenreError(
            f"layer {item.get('name')!r} has kind {kind!r}; "
            f"must be 'tile' or 'object'", path=path)
    name = item["name"]
    allowed = tuple(item.get("object_types", []))
    return GenreLayer(
        name=name,
        kind=kind,
        depth=int(item.get("depth", 0)),
        doc=item.get("doc", ""),
        required=bool(item.get("required", False)),
        collision=bool(item.get("collision", False)),
        object_types=allowed,
        unique_types=tuple(item.get("unique_types", [])),
        object_classes=_object_classes(item, name, kind, allowed, path),
    )


def _object_classes(item: dict, layer_name: str, kind: str,
                    allowed: tuple[str, ...],
                    path: str) -> tuple[GenreObjectClass, ...]:
    """Parse `layers[].object_classes[]`, and draw the one line that matters.

    ABSENT IS NOT AN ERROR. A pack that declares no `object_classes` -- which
    is every pack that ever shipped before one did -- loads exactly as it did
    before and hands every placed object nothing. That is the whole
    compatibility promise, and it is why this returns `()` rather than
    raising on a missing key.

    PRESENT AND CONTRADICTORY IS AN ERROR, loudly, at load. A tile layer with
    object classes, an entry that is not an object, an entry with no `type`,
    the same class twice, a class the same layer's `object_types` forbids, a
    token the registry does not know -- each of those would otherwise be
    written into real maps by an editor that looked like it was working.
    """
    raw = item.get("object_classes", ())
    if raw is None or (isinstance(raw, (list, tuple)) and not raw):
        return ()
    if not isinstance(raw, (list, tuple)):
        raise PyoneerGenreError(
            f"layer {layer_name!r} declares object_classes as a "
            f"{type(raw).__name__}; it must be a list of "
            f'{{"type": ..., "behaviors": [...]}} entries', path=path)
    if kind != "object":
        raise PyoneerGenreError(
            f"layer {layer_name!r} is a {kind} layer and declares "
            f"object_classes; only an object layer holds objects, so this "
            f"default could never be materialised into anything", path=path)
    found = tuple(_object_class(entry, layer_name, allowed, path)
                  for entry in raw)
    duplicate = _first_duplicate([c.type for c in found])
    if duplicate:
        raise PyoneerGenreError(
            f"layer {layer_name!r} declares object class {duplicate!r} twice; "
            f"one class has one starting behavior list, and two would make "
            f"which one a new object gets depend on file order", path=path)
    return found


def _object_class(entry: Any, layer_name: str, allowed: tuple[str, ...],
                  path: str) -> GenreObjectClass:
    if not isinstance(entry, dict):
        raise PyoneerGenreError(
            f"layer {layer_name!r} has an object_classes entry that is a "
            f"{type(entry).__name__}, not an object carrying a 'type'",
            path=path)
    kind = entry.get("type", "")
    if not isinstance(kind, str) or not kind:
        raise PyoneerGenreError(
            f"layer {layer_name!r} has an object_classes entry with no "
            f"'type'; the type names the class the default belongs to",
            path=path, has=sorted(entry))
    if allowed and kind not in allowed:
        raise PyoneerGenreError(
            f"layer {layer_name!r} declares default behaviors for object "
            f"class {kind!r}, which the same layer's object_types does not "
            f"allow: {list(allowed)}", path=path)
    raw = entry.get("behaviors", ())
    if not isinstance(raw, (list, tuple, str)):
        raise PyoneerGenreError(
            f"layer {layer_name!r} gives object class {kind!r} a behaviors "
            f"value of type {type(raw).__name__}; it must be a list of "
            f"behavior tokens", path=path)
    # The engine's own judge, not a second copy of it: `validate_list` is
    # what a map load runs, so a list this accepts is a list every object
    # placed from this pack can carry.
    try:
        tokens = behavior_registry.validate_list(
            raw, where=f"genre layer {layer_name!r}, object class {kind!r}")
    except PyoneerError as exc:
        detail = getattr(exc, "message", None) or str(exc)
        raise PyoneerGenreError(
            f"layer {layer_name!r} gives object class {kind!r} a default "
            f"behavior list the engine refuses, so every object placed from "
            f"this pack would make its map raise at load: {detail}",
            path=path) from exc
    return GenreObjectClass(type=kind, behaviors=tokens,
                            doc=entry.get("doc", ""))


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
