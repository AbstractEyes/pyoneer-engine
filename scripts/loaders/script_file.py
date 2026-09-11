"""Read `data/project/scripts/*.json` -- the engine side of an event script.

This is `scripts/loaders/table_file.py` for scripts: a read-only reader of an
authored document, joined to the editor's writer by the FILES and never by an
import. It parses, judges, and hands back frozen records; it runs nothing.
`scripts/game/flow/interpreter.py` is what runs them.

EVERYTHING VOCABULARY-SHAPED RAISES HERE, AT LOAD
-------------------------------------------------
The whole file is in hand, no frame has run, no display exists and nobody's
agency has been taken. Every one of these is a raise:

    format absent or wrong                  the document is not one of ours
    version absent, not an int, or newer    "is version 2; this build reads 1"
    ANY unknown key, at any depth           naming the key, its path and the
                                            accepted set
    a node with no `id`                     naming its position
    a duplicate `id` anywhere in the file   naming both positions
    an unknown `do`                         naming the vocabulary
    a `do` outside the declared `loadouts`  naming both
    an argument the op does not take        naming what it does take
    a condition with two operator keys      naming both
    an unknown comparator                   naming the closed six
    a variable nothing declares             naming the schema
    a `set` whose value is the wrong type   through `BehaviorParam.coerce`

The unknown-key rule is deliberately stricter than what is on disk elsewhere,
and the reason is measured: an off-schema row key survives the editor's
`DataTable.from_json` and then raises in the engine's `load_table` AT BOOT. A
key the writer keeps and the reader refuses is the 39-silently-dropped-tiles
shape with a delay fuse. New formats raise on both sides.

WHY EXECUTION CANNOT RAISE FOR A VOCABULARY REASON
--------------------------------------------------
By the time `ScriptRun` has a `Script`, every `do` is already a resolved
`OpSpec` -- an object, not a string -- and every variable name is already a
declared one. There is no dispatch-on-string at run time, so there is no
place left for a fallback to hide. A bad op discovered mid-cutscene has
already stolen the player's agency; this file is why that cannot happen.

THE VARIABLE SCHEMA COMES FROM THE SCENE, AND NONE IS NOT EMPTY
---------------------------------------------------------------
A scene owns `vars`; a script reads and writes them. So `load_script` takes
`variables=`, and the two absent cases are different mistakes, exactly as
`table_file.actor_row` distinguishes them:

    variables=None      nobody handed this load a schema. A script that names
                        ANY variable raises saying so -- a wiring error.
    variables=VarSchema({})   the scene declares no variables, so a script
                        naming one raises naming the (empty) schema -- an
                        authoring error.

Collapsing the two would let a schema-less load quietly accept every typo in
the document, which is the exact failure the declaration exists to prevent.

`VarDecl` lives here rather than in a scene reader that does not exist yet,
and the scene reader will import it instead of declaring a second one. The
last time two sides of a boundary each grew their own copy of one model it
cost 425 duplicated lines.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Optional, Sequence, Tuple, Union

from scripts.core.errors import PyoneerAssetMissingError, PyoneerConfigError
from scripts.core.layer_profile import PREFIX
from scripts.core.log import trace_assets
from scripts.game.behavior.base import PARAM_TYPES, TOKEN, BehaviorParam
from scripts.game.flow import ops as op_registry

SCRIPT_PROPERTY: str = PREFIX + "script"
"""The tmx object property naming the event script that object runs.

THE ONE DECLARATION. A FILE FORMAT string, minted by `docs/PLAN_SCENES.md`
4.6 and permanent under law 8, so both halves of the seam must spell it the
same way forever: `editor/ui/script_editor.py` WRITES it onto an object and
`main.py` READS it at boot to join a spawned body to its document. It lived
in both files for a day, which is law 2's corollary -- shared logic lives in
`scripts/` and the editor re-exports it -- and this is where that debt was
paid.

Here, and not in `scripts/core/layer_profile.py`, because that module's
`KNOWN` tuple is the LAYER vocabulary and a check asserts the editor declares
exactly it; this is an OBJECT property, like `BEHAVIORS` and `ACTOR`, which
live beside the code that reads them for the same reason.

Composed from the imported `PREFIX` and never retyped (law 1): pytmx raises
and makes the whole map unloadable if a custom property shadows one of its
own attribute names.
"""

FORMAT: str = "pyoneer.script"
"""The `format` key every event script opens with. A FILE FORMAT string."""

VERSION: int = 1
"""The document version this build reads. A newer one RAISES rather than
being read optimistically: `TilesetFile` carries the same field for the same
reason, and nothing under `data/project/` was versioned before this."""

SCRIPTS_DIR: str = os.path.join("data", "project", "scripts")
"""Where the editor writes event scripts, relative to the repository root.

The editor composes the same path from its own `PROJECT_DIR`. The two sides
are joined by the FILES, never by an import.
"""

_REPO_ROOT: str = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))


def default_scripts_dir() -> str:
    """`data/project/scripts` under the repo root, absolute."""
    return os.path.join(_REPO_ROOT, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# The closed vocabularies. Every one of these is permanent under law 8.
# ---------------------------------------------------------------------------

COMPARATORS: Tuple[str, ...] = ("is", "not", "at_least", "at_most",
                                "in", "contains")
"""The six comparators a condition may spell. CLOSED, and closed forever.

An expression language needs a grammar, and a grammar in a game file is where
silent truthiness lives -- `"0"` is truthy, `""` is falsy, and a typo'd name
resolves to nothing at all. A seventh comparator needs a design pass, not an
`elif`. A structured condition also renders as a form with zero parsing.
"""

SCRIPT_TRIGGERS: Tuple[str, ...] = ("use", "enter", "exit", "stay", "auto")
"""What can start a page. A superset of the editor's `TRIGGER_KINDS`.

`auto` is the one addition and is not a region trigger: it fires from a
scene's `on_enter`. The other four are taken WORD FOR WORD from
`editor/core/map_events.py`, which `scripts/` may never import --
`tools/check_ops.py` may import both sides and asserts the superset holds.
"""

NAMESPACES: Tuple[str, ...] = ("global", "scene", "local")
"""The three variable namespaces. CLOSED.

    global   the process
    scene    cleared on scene entry. THE DEFAULT: a bare name means this one
    local    per (map, object) -- RPG Maker's self-switch generalised to any
             value, and what lets one script sit on ten doors and have each
             remember its own state

Written into `vars` keys and into every `set`, so all three are FILE FORMAT
strings.
"""

DEFAULT_NAMESPACE: str = "scene"

SCRIPT_KEYS: Tuple[str, ...] = ("format", "version", "id", "title",
                                "loadouts", "pages")
PAGE_KEYS: Tuple[str, ...] = ("id", "note", "trigger", "payload", "once",
                              "cooldown_ms", "when", "body")
CONTROL_KEYS: Tuple[str, ...] = ("id", "note", "if", "while", "then",
                                 "elif", "else")
ARM_KEYS: Tuple[str, ...] = ("when", "then")
CONDITION_KEYS: Tuple[str, ...] = ("var",) + COMPARATORS
NODE_COMMON_KEYS: Tuple[str, ...] = ("id", "note", "do")

ID_CHARS = "letters, digits, '_' and '-', starting with a letter or a digit"


def _legal_id(value: Any) -> bool:
    return (isinstance(value, str) and bool(value)
            and value[0].isalnum() and value.replace("_", "")
            .replace("-", "").isalnum())


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

def normalise_var(name: Any, where: str = "") -> str:
    """`coins` -> `scene.coins`; `global.coins` stays. Raises on anything else.

    One spelling for one variable, decided at read time, so a schema keyed by
    `scene.coins` and a node saying `coins` cannot become two variables that
    each hold half the game's state.
    """
    blame = where or "a document"
    if not isinstance(name, str) or not name.strip():
        raise PyoneerConfigError(
            "%s: %r is not a variable name; a name is a non-empty string, "
            "optionally prefixed with one of %s"
            % (blame, name, ", ".join("%s." % n for n in NAMESPACES)))
    text = name.strip()
    namespace = DEFAULT_NAMESPACE
    bare = text
    if "." in text:
        namespace, _, bare = text.partition(".")
        if namespace not in NAMESPACES:
            raise PyoneerConfigError(
                "%s: variable %r names the %r namespace, and there are "
                "exactly three: %s. A bare name means %r."
                % (blame, text, namespace, ", ".join(NAMESPACES),
                   DEFAULT_NAMESPACE))
    if "." in bare:
        raise PyoneerConfigError(
            "%s: variable %r has more than one '.'; a name is at most "
            "<namespace>.<name>" % (blame, text))
    if not TOKEN.match(bare):
        raise PyoneerConfigError(
            "%s: variable %r is not snake_case after its namespace; it must "
            "match %s" % (blame, text, TOKEN.pattern))
    return "%s.%s" % (namespace, bare)


@dataclass(frozen=True)
class VarDecl:
    """One variable a scene declares: a normalised name, a type, a default.

    `BehaviorParam`'s shape, and its `coerce` does the actual typing -- built
    on demand rather than stored, so there is exactly one implementation of
    "bring an authored value to a declared type, or raise saying why" in the
    tree.
    """

    name: str
    type: str
    default: Any
    doc: str = ""

    def __post_init__(self) -> None:
        if self.name != normalise_var(self.name):
            raise PyoneerConfigError(
                "variable %r is not normalised; build it through "
                "`read_vars` or `normalise_var`" % (self.name,))
        if self.type not in PARAM_TYPES:
            raise PyoneerConfigError(
                "variable %r declares type %r; known types are %s"
                % (self.name, self.type, ", ".join(sorted(PARAM_TYPES))))
        # The default goes through the same gate every authored value does, so
        # a `{"type": "int", "default": "0"}` cannot seed the store with a
        # string that every later comparison silently loses to.
        self.coerce(self.default, "the declared default of %r" % (self.name,))

    @property
    def bare(self) -> str:
        """The name without its namespace. What `coerce` blames."""
        return self.name.split(".", 1)[1]

    def as_param(self) -> BehaviorParam:
        """This declaration as the class that already knows how to coerce."""
        return BehaviorParam(key=self.bare, label=self.bare, type=self.type,
                             default=self.default, doc=self.doc,
                             source="object")

    def coerce(self, value: Any, where: str = "") -> Any:
        """`value` at this variable's declared type, or raise saying why."""
        try:
            return self.as_param().coerce(value)
        except PyoneerConfigError as exc:
            raise PyoneerConfigError(
                "%s: variable %r is declared %s and was given %r (%s). (%s)"
                % (where or "a document", self.name, self.type, value,
                   type(value).__name__, exc.message)) from exc


@dataclass(frozen=True)
class VarSchema:
    """Every variable a scene declares. Possibly none of them.

    A real, empty value rather than None, because "the scene declares no
    variables" and "nobody handed this load a schema" are different mistakes
    with different fixes -- `EMPTY_VARS` versus `None`, the same split
    `table_file.EMPTY` makes.
    """

    decls: Mapping[str, VarDecl]

    def __contains__(self, name: str) -> bool:
        return name in self.decls

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self.decls))

    def __len__(self) -> int:
        return len(self.decls)

    def names(self) -> list[str]:
        return sorted(self.decls)

    def declaration(self, name: Any, where: str = "") -> VarDecl:
        """The declaration for `name`, or raise naming the whole schema.

        There is deliberately no `.get`-shaped sibling returning None: every
        caller reached this because a document NAMED the variable, and a None
        would travel to the next frame and arrive as a default.
        """
        normalised = normalise_var(name, where)
        decl = self.decls.get(normalised)
        if decl is None:
            raise PyoneerAssetMissingError(
                "scene variable", normalised, available=self.names(),
                asked_by=where or "<unknown>",
                hint="declare it in the scene's `vars`, with a type and a "
                     "default; a variable this file cannot see is one a typo "
                     "would otherwise create at run time")
        return decl

    def defaults(self) -> dict[str, Any]:
        return {name: decl.default for name, decl in self.decls.items()}


EMPTY_VARS: VarSchema = VarSchema(decls={})
"""A scene that declares no variables. NOT the same as `variables=None`."""


def read_vars(raw: Any, where: str = "") -> VarSchema:
    """A scene's `vars` block as a schema, or raise saying which entry.

    Lives here rather than in a scene reader so that both readers, and every
    check, judge a declaration the same way.
    """
    blame = where or "a scene"
    if raw is None:
        return EMPTY_VARS
    if not isinstance(raw, Mapping):
        raise PyoneerConfigError(
            "%s: `vars` is a JSON object of name -> {type, default, doc}, "
            "not %s" % (blame, type(raw).__name__))
    decls: dict[str, VarDecl] = {}
    for name, body in raw.items():
        normalised = normalise_var(name, blame)
        if normalised in decls:
            raise PyoneerConfigError(
                "%s: `vars` declares %r twice (a bare name means the %r "
                "namespace)" % (blame, normalised, DEFAULT_NAMESPACE))
        if not isinstance(body, Mapping):
            raise PyoneerConfigError(
                "%s: var %r is %s, not an object with `type` and `default`"
                % (blame, normalised, type(body).__name__))
        stray = sorted(k for k in body if k not in ("type", "default", "doc"))
        if stray:
            raise PyoneerConfigError(
                "%s: var %r carries %s; a declaration takes type, default "
                "and doc" % (blame, normalised,
                             ", ".join(repr(k) for k in stray)))
        if "type" not in body:
            raise PyoneerConfigError(
                "%s: var %r declares no `type`; known types are %s"
                % (blame, normalised, ", ".join(sorted(PARAM_TYPES))))
        if "default" not in body:
            raise PyoneerConfigError(
                "%s: var %r declares no `default`. Reading a variable is "
                "TOTAL at run time -- that is what moves every failure to "
                "load -- so every variable has a value from the first frame."
                % (blame, normalised))
        decls[normalised] = VarDecl(name=normalised, type=body["type"],
                                    default=body["default"],
                                    doc=str(body.get("doc", "")))
    return VarSchema(decls=decls)


class VarStore:
    """The live value of every declared variable, seeded from the defaults.

    Wraps a `VarSchema` rather than copying it, and delegates `declaration`,
    so one object serves the load-time check and the run-time read.

    `get` is TOTAL and cannot raise for a name the document was loaded
    against -- that is what the load-time gate buys. It still raises for a
    name nothing declares, because a caller reaching past the loader is a
    caller with a bug, and a None would arrive somewhere else as a default.
    """

    def __init__(self, schema: VarSchema | None = None,
                 values: Mapping[str, Any] | None = None):
        self.schema: VarSchema = EMPTY_VARS if schema is None else schema
        self._values: dict[str, Any] = self.schema.defaults()
        for name, value in (values or {}).items():
            self.set(name, value, "the initial values")

    def declaration(self, name: Any, where: str = "") -> VarDecl:
        return self.schema.declaration(name, where)

    def get(self, name: Any, where: str = "") -> Any:
        decl = self.schema.declaration(name, where)
        return self._values[decl.name]

    def set(self, name: Any, value: Any, where: str = "") -> Any:
        """Write, at the declared type. A wrong type raises naming both."""
        decl = self.schema.declaration(name, where)
        self._values[decl.name] = decl.coerce(value, where)
        return self._values[decl.name]

    def snapshot(self) -> dict[str, Any]:
        return dict(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return "<VarStore %d var(s)>" % (len(self._values),)


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Condition:
    """One comparison, already typed against the variable it names.

    Never a string. `{"var": "coins", "at_least": 100}` renders as a form with
    zero parsing, which is what makes the condition editor free, and it is
    what stops `"0"` from being truthy.
    """

    var: str
    operator: str
    value: Any
    where: str = ""

    def test(self, store: Any) -> bool:
        """True if this holds right now. Cannot raise for a loaded script."""
        current = store.get(self.var, self.where)
        if self.operator == "is":
            return current == self.value
        if self.operator == "not":
            return current != self.value
        if self.operator == "at_least":
            return current >= self.value
        if self.operator == "at_most":
            return current <= self.value
        if self.operator == "in":
            return current in self.value
        if self.operator == "contains":
            return self.value in current
        raise PyoneerConfigError(                       # unreachable by design
            "%s: comparator %r survived the loader; the closed six are %s"
            % (self.where, self.operator, ", ".join(COMPARATORS)))

    def describe(self) -> str:
        return "%s %s %r" % (self.var, self.operator, self.value)


def _read_condition(raw: Any, variables: Any, where: str) -> Condition:
    if not isinstance(raw, Mapping):
        raise PyoneerConfigError(
            "%s: a condition is an object like "
            "{\"var\": \"coins\", \"at_least\": 100}, not %s"
            % (where, type(raw).__name__))
    stray = sorted(k for k in raw if k not in CONDITION_KEYS)
    if stray:
        raise PyoneerConfigError(
            "%s: condition carries %s. A condition takes `var` and exactly "
            "one of %s."
            % (where, ", ".join(repr(k) for k in stray),
               ", ".join(COMPARATORS)))
    if "var" not in raw:
        raise PyoneerConfigError(
            "%s: condition has no `var`; it names the variable to compare"
            % (where,))
    operators = [k for k in COMPARATORS if k in raw]
    if len(operators) > 1:
        raise PyoneerConfigError(
            "%s: condition on %r carries two comparators, %s and %s. One "
            "condition is one comparison; two conditions in the same `when` "
            "list are ANDed."
            % (where, raw["var"], operators[0], operators[1]))
    if not operators:
        raise PyoneerConfigError(
            "%s: condition on %r names no comparator; one of %s is required"
            % (where, raw["var"], ", ".join(COMPARATORS)))
    operator = operators[0]
    value = raw[operator]

    if variables is None:
        raise PyoneerConfigError(
            "%s: condition names the variable %r and this load was given no "
            "variable schema, so nothing can say whether it exists or what "
            "type it is. Pass the scene's `vars` "
            "(`load_script(path, variables=...)`)." % (where, raw["var"]))
    decl = variables.declaration(raw["var"], where)

    if operator in ("at_least", "at_most"):
        if decl.type not in ("int", "float"):
            raise PyoneerConfigError(
                "%s: %r compares %r, which is declared %s. `at_least` and "
                "`at_most` are arithmetic; on a %s use `is` or `not`."
                % (where, operator, decl.name, decl.type, decl.type))
        value = decl.coerce(value, where)
    elif operator == "in":
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise PyoneerConfigError(
                "%s: `in` compares against a LIST of values and was given %r "
                "(%s)" % (where, value, type(value).__name__))
        value = tuple(decl.coerce(item, where) for item in value)
    elif operator == "contains":
        if decl.type != "str":
            raise PyoneerConfigError(
                "%s: `contains` asks whether %r holds a substring, and it is "
                "declared %s. There are no list variables."
                % (where, decl.name, decl.type))
        if not isinstance(value, str):
            raise PyoneerConfigError(
                "%s: `contains` compares against a string and was given %r "
                "(%s)" % (where, value, type(value).__name__))
    else:
        value = decl.coerce(value, where)
    return Condition(var=decl.name, operator=operator, value=value,
                     where=where)


def _read_when(raw: Any, variables: Any, where: str) -> Tuple[Condition, ...]:
    """A `when` list. `[]` always passes and is the fallback."""
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise PyoneerConfigError(
            "%s: `when` is a JSON array of conditions, ANDed, not %s. There "
            "is no and/or nesting: a second page IS the or-arm."
            % (where, type(raw).__name__))
    return tuple(_read_condition(item, variables, "%s when[%d]" % (where, i))
                 for i, item in enumerate(raw))


def passes(conditions: Sequence[Condition], store: Any) -> bool:
    """Every condition holds. An empty list passes -- that is the fallback."""
    return all(condition.test(store) for condition in conditions)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DoNode:
    """An executable node: an op that is already an object, not a string."""

    id: str
    spec: Any
    args: Mapping[str, Any]
    note: str = ""
    where: str = ""

    @property
    def op(self) -> str:
        return self.spec.name

    def describe(self) -> str:
        return "%s %s" % (self.spec.name,
                          " ".join("%s=%r" % kv for kv in sorted(self.args.items())))


@dataclass(frozen=True)
class Arm:
    """One `elif` arm: its own condition list and its own body."""

    when: Tuple[Condition, ...]
    body: Tuple[Any, ...]
    where: str = ""


@dataclass(frozen=True)
class ControlNode:
    """An `if` or a `while`. One node with arms, not a flattened list.

    `elif` is a LIST of arms because a flat key holds one and the author will
    want three -- and because one node with arms means an added arm is ONE
    contiguous block in the diff, where flattened it is an insertion plus a
    re-indent of everything after it and the reviewer cannot see that the
    shape changed.
    """

    id: str
    kind: str
    when: Tuple[Condition, ...]
    body: Tuple[Any, ...]
    arms: Tuple[Arm, ...] = ()
    otherwise: Tuple[Any, ...] = ()
    note: str = ""
    where: str = ""

    def describe(self) -> str:
        return "%s %s" % (self.kind,
                          " and ".join(c.describe() for c in self.when) or "-")


Node = Union[DoNode, ControlNode]


@dataclass(frozen=True)
class Page:
    """One page: when it may run, what starts it, and what it does.

    Pages are ORDERED and the FIRST page whose `when` all pass runs. That is
    deliberately the opposite of RPG Maker, which evaluates bottom-up so the
    highest-numbered page shadows the rest -- a famous source of confusion.
    Here the list you read top to bottom is the order it runs, so a diff that
    inserts a page inserts it where it will fire.
    """

    id: str
    body: Tuple[Node, ...]
    when: Tuple[Condition, ...] = ()
    trigger: str = "use"
    payload: str = ""
    once: bool = False
    cooldown_ms: float = 0.0
    note: str = ""
    where: str = ""


@dataclass(frozen=True)
class Script:
    """One `data/project/scripts/<id>.json`, read and judged.

    Frozen and holding tuples: the script IS the document, and a script the
    machinery could edit is a script that changes while it is being read.
    """

    id: str
    pages: Tuple[Page, ...]
    loadouts: Tuple[str, ...]
    title: str = ""
    path: str = ""
    version: int = VERSION
    ids: Tuple[str, ...] = field(default=())
    """Every id in the document, pages and nodes alike, in read order.

    One namespace on purpose: a relay response addresses a page and a node the
    same way, so two things answering to `n4` would make that address
    ambiguous in exactly the batch where it matters.
    """

    def page(self, page_id: str) -> Page:
        for page in self.pages:
            if page.id == page_id:
                return page
        raise PyoneerAssetMissingError(
            "script page", page_id, available=[p.id for p in self.pages],
            asked_by=self.id, script_file=self.path)

    def first_passing(self, store: Any,
                      trigger: Optional[str] = None,
                      payload: Optional[str] = None) -> Optional[Page]:
        """The first page whose filters and `when` all pass, or None.

        A page with an EMPTY `payload` accepts any payload, which is
        `ActionRouter.ANY_PAYLOAD`'s rule spelled the same way on the
        authoring side rather than a second convention.

        Zero passing pages is NOT an error: a keeper who has nothing to say
        today is a real idiom, and raising would make every conditional NPC a
        crash waiting for the wrong game state.
        """
        for page in self.pages:
            if trigger is not None and page.trigger != trigger:
                continue
            if payload is not None and page.payload and page.payload != payload:
                continue
            if passes(page.when, store):
                return page
        return None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _bad(where: str, message: str) -> PyoneerConfigError:
    return PyoneerConfigError("%s: %s" % (where, message))


def _refuse_unknown(raw: Mapping[str, Any], allowed: Sequence[str],
                    where: str, what: str) -> None:
    """Law 7 at every depth: an unknown key raises, it is not ignored."""
    stray = sorted(k for k in raw if k not in allowed)
    if stray:
        raise _bad(where, "%s carries %s, which this format has no meaning "
                          "for. A %s takes %s."
                   % (what, ", ".join(repr(k) for k in stray), what,
                      ", ".join(allowed)))


class _Ids:
    """Every id seen so far, and where it was seen. Duplicates raise.

    An id is the address a relay response edits by. A relay response is an
    ordered BATCH, so two path-addressed inserts mis-land the second the
    moment the first shifts an index -- silently, with a valid-looking
    transaction and a clean undo. A wrong id is loud; a duplicated one would
    make "the node with id n4" ambiguous, which is the same silence.
    """

    def __init__(self) -> None:
        self.seen: dict[str, str] = {}

    def claim(self, raw: Mapping[str, Any], where: str, what: str) -> str:
        value = raw.get("id")
        if value is None:
            raise _bad(where, "this %s has no `id`. Every page and every node "
                              "carries a stable id: it is what a scripted "
                              "edit addresses, and a position shifts the "
                              "moment anything is inserted above it." % what)
        if not _legal_id(value):
            raise _bad(where, "%s id %r is not a legal id; an id is %s"
                       % (what, value, ID_CHARS))
        if value in self.seen:
            raise _bad(where, "id %r is already used at %s. An id is an "
                              "address and two of them make it ambiguous."
                       % (value, self.seen[value]))
        self.seen[value] = where
        return value


def _read_body(raw: Any, ctx: "_Ctx", where: str) -> Tuple[Node, ...]:
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise _bad(where, "a body is a JSON array of nodes, not %s"
                   % type(raw).__name__)
    return tuple(_read_node(item, ctx, "%s[%d]" % (where, index))
                 for index, item in enumerate(raw))


def _read_node(raw: Any, ctx: "_Ctx", where: str) -> Node:
    if not isinstance(raw, Mapping):
        raise _bad(where, "a node is a JSON object, not %s"
                   % type(raw).__name__)
    shapes = [k for k in ("do", "if", "while") if k in raw]
    if len(shapes) > 1:
        raise _bad(where, "node carries %s; a node is EITHER executable "
                          "(`do`) or control (`if` / `while`), never both"
                   % " and ".join(repr(s) for s in shapes))
    if not shapes:
        raise _bad(where, "node has no `do`, `if` or `while`. There are "
                          "exactly two node shapes, and a node that is "
                          "neither would be a comment -- and a node whose "
                          "runtime is a no-op can never be MEASURED as "
                          "integrated, which is why every node takes a "
                          "`note` key instead.")
    node_id = ctx.ids.claim(raw, where, "node")
    where = "%s '%s'" % (where, node_id)
    note = str(raw.get("note", ""))

    if shapes[0] == "do":
        spec = op_registry.resolve(raw["do"], ctx.registry, where)
        op_registry.check_loadout(spec, ctx.loadouts, where)
        _refuse_unknown(raw, NODE_COMMON_KEYS + spec.arg_keys, where,
                        "node `do: %s`" % spec.name)
        args = op_registry.resolve_args(
            spec, {k: v for k, v in raw.items()
                   if k not in NODE_COMMON_KEYS},
            ctx.variables, where)
        return DoNode(id=node_id, spec=spec, args=args, note=note, where=where)

    kind = shapes[0]
    _refuse_unknown(raw, CONTROL_KEYS, where, "node `%s`" % kind)
    if kind == "while" and ("elif" in raw or "else" in raw):
        raise _bad(where, "a `while` takes only `then`; `elif` and `else` "
                          "belong to an `if`, and a loop that fell through to "
                          "an else would run it on every exit")
    when = _read_when(raw[kind], ctx.variables, where)
    body = _read_body(raw.get("then"), ctx, "%s then" % where)
    arms: list[Arm] = []
    for index, entry in enumerate(raw.get("elif", ()) or ()):
        arm_where = "%s elif[%d]" % (where, index)
        if not isinstance(entry, Mapping):
            raise _bad(arm_where, "an elif arm is an object with `when` and "
                                  "`then`, not %s" % type(entry).__name__)
        _refuse_unknown(entry, ARM_KEYS, arm_where, "an elif arm")
        arms.append(Arm(when=_read_when(entry.get("when"), ctx.variables,
                                        arm_where),
                        body=_read_body(entry.get("then"), ctx,
                                        "%s then" % arm_where),
                        where=arm_where))
    otherwise = _read_body(raw.get("else"), ctx, "%s else" % where)
    return ControlNode(id=node_id, kind=kind, when=when, body=body,
                       arms=tuple(arms), otherwise=otherwise, note=note,
                       where=where)


class _Ctx:
    """What every level of the read needs: the registry, the schema, the ids."""

    def __init__(self, registry, variables, loadouts, ids: _Ids):
        self.registry = registry
        self.variables = variables
        self.loadouts = loadouts
        self.ids = ids


def parse_script(raw: Any, path: str = "", *,
                 variables: Any = None,
                 registry: Optional[Mapping[str, Any]] = None) -> Script:
    """Judge a decoded script document. `path` is used for blame and for the id.

    Split from `load_script` so a check, the editor's future writer and a
    relay response can all be judged by the same rules with no file on disk.
    """
    name = os.path.basename(path) if path else "<script>"
    where = name
    if not isinstance(raw, Mapping):
        raise _bad(where, "a script file is a JSON object, not %s"
                   % type(raw).__name__)
    _refuse_unknown(raw, SCRIPT_KEYS, where, "a script")

    declared_format = raw.get("format")
    if declared_format != FORMAT:
        raise _bad(where, "declares format %r; an event script declares %r. "
                          "The format key is how a reader knows the document "
                          "is one of ours before it trusts a single key in it."
                   % (declared_format, FORMAT))
    version = raw.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _bad(where, "declares version %r (%s); it is an integer"
                   % (version, type(version).__name__))
    if version > VERSION:
        raise _bad(where, "is version %d; this build reads version %d."
                   % (version, VERSION))

    script_id = raw.get("id")
    if not _legal_id(script_id):
        raise _bad(where, "declares id %r; an id is %s" % (script_id, ID_CHARS))
    if path:
        stem = os.path.splitext(name)[0]
        if script_id != stem:
            raise _bad(where, "declares id %r but is named %r; the file name "
                              "and the `id` key are the same identifier, and "
                              "`call` addresses a script by it."
                       % (script_id, name))

    loadouts = op_registry.validate_loadouts(raw.get("loadouts"), registry,
                                             where)
    pages_raw = raw.get("pages")
    if isinstance(pages_raw, (str, bytes)) or not isinstance(pages_raw, Sequence):
        raise _bad(where, "`pages` is a JSON array of pages, not %s"
                   % type(pages_raw).__name__)

    ids = _Ids()
    ctx = _Ctx(registry, variables, loadouts, ids)
    pages: list[Page] = []
    for index, entry in enumerate(pages_raw):
        page_where = "%s pages[%d]" % (where, index)
        if not isinstance(entry, Mapping):
            raise _bad(page_where, "a page is a JSON object, not %s"
                       % type(entry).__name__)
        _refuse_unknown(entry, PAGE_KEYS, page_where, "a page")
        page_id = ids.claim(entry, page_where, "page")
        page_where = "%s '%s'" % (page_where, page_id)
        trigger = entry.get("trigger", "use")
        if trigger not in SCRIPT_TRIGGERS:
            raise _bad(page_where, "trigger %r is not one of %s"
                       % (trigger, ", ".join(SCRIPT_TRIGGERS)))
        payload = entry.get("payload", "")
        if not isinstance(payload, str):
            raise _bad(page_where, "payload is %r (%s); it is an opaque "
                                   "string and is never interpreted"
                       % (payload, type(payload).__name__))
        once = entry.get("once", False)
        if not isinstance(once, bool):
            raise _bad(page_where, "once is %r (%s); it is a bool"
                       % (once, type(once).__name__))
        cooldown = entry.get("cooldown_ms", 0)
        if isinstance(cooldown, bool) or not isinstance(cooldown, (int, float)):
            raise _bad(page_where, "cooldown_ms is %r (%s); it is a number of "
                                   "milliseconds" % (cooldown,
                                                     type(cooldown).__name__))
        if cooldown < 0:
            raise _bad(page_where, "cooldown_ms is %r; a negative cooldown "
                                   "reads as 'already elapsed'" % (cooldown,))
        pages.append(Page(
            id=page_id,
            body=_read_body(entry.get("body"), ctx, "%s body" % page_where),
            when=_read_when(entry.get("when"), variables, page_where),
            trigger=trigger, payload=payload, once=once,
            cooldown_ms=float(cooldown),
            note=str(entry.get("note", "")), where=page_where))

    return Script(id=script_id, pages=tuple(pages), loadouts=loadouts,
                  title=str(raw.get("title", "")),
                  path=os.path.abspath(path) if path else "",
                  version=version, ids=tuple(ids.seen))


def load_script(path: str, *, variables: Any = None,
                registry: Optional[Mapping[str, Any]] = None) -> Script:
    """Read one script file, or raise saying which file and what is wrong.

    A script that fails to load is never skipped: a project whose
    `keeper_gate.json` has a stray comma would otherwise boot with a keeper
    who silently does nothing, which is indistinguishable from a keeper the
    author has not written yet.
    """
    with open(path, "r", encoding="utf-8") as handle:
        try:
            raw = json.load(handle)
        except json.JSONDecodeError as exc:
            raise _bad(os.path.basename(path), "not valid JSON (%s)" % exc) from exc
    return parse_script(raw, path, variables=variables, registry=registry)


def load_scripts(directory: str | None = None, *, variables: Any = None,
                 registry: Optional[Mapping[str, Any]] = None
                 ) -> dict[str, Script]:
    """Every `*.json` in a scripts directory, keyed by id.

    A missing directory is an empty dict and not an error: a project with no
    scripted events is not broken, exactly as a project with no `tables/` is
    not.
    """
    target = default_scripts_dir() if directory is None else directory
    if not os.path.isdir(target):
        trace_assets("load_scripts %s absent -> no scripts", target)
        return {}
    scripts: dict[str, Script] = {}
    for entry in sorted(os.listdir(target)):
        if not entry.endswith(".json"):
            continue
        script = load_script(os.path.join(target, entry), variables=variables,
                             registry=registry)
        scripts[script.id] = script
    trace_assets("load_scripts %s -> %d script(s): %s",
                 target, len(scripts), ", ".join(sorted(scripts)) or "<none>")
    return scripts


__all__ = [
    "COMPARATORS", "CONDITION_KEYS", "CONTROL_KEYS", "DEFAULT_NAMESPACE",
    "EMPTY_VARS", "FORMAT", "NAMESPACES", "PAGE_KEYS", "SCRIPTS_DIR",
    "SCRIPT_KEYS", "SCRIPT_TRIGGERS", "VERSION", "Arm", "Condition",
    "ControlNode", "DoNode", "Page", "Script", "VarDecl", "VarSchema",
    "VarStore", "default_scripts_dir", "load_script", "load_scripts",
    "normalise_var", "parse_script", "passes", "read_vars",
]
