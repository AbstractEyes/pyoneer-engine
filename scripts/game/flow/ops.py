"""Which word means which op, and what one op is allowed to be handed.

This is `scripts/game/behavior/registry.py` for event scripts, and it is
deliberately shaped like it rather than beside it. The table at the bottom is
hand-written: no scanning, no importlib, no import-order-sensitive decorator,
because a scan cannot tell an op that is not written yet from one it has
simply not seen, and its failures would land on the author's script instead
of here, in a file a human reads.

WHAT AN OP IS
-------------
A name, a summary, a `run`, and a declaration of what it may be handed. It is
CALLED -- by `ScriptRun.update`, off `SceneManager.post_update`, after the
scene fan-out has returned. Nothing here constructs a `PyoneerEvent`, calls
`handle()`, or binds a listener, and `tools/check_ops.py` proves that from
this module's PARSE TREE with a planted decoy, because "the bus list is
empty" is an assertion that passes trivially forever.

A RUN RETURNS TRUE WHEN THE NODE IS FINISHED
--------------------------------------------
    run(script_run, args) -> bool

    True    the node is done. The interpreter moves to the next one in the
            SAME frame.
    False   the node is not done. The interpreter stops the frame here and
            calls the same run again next frame, with
            `script_run.first_step` False and `node_elapsed_ms` grown.

Only a spec declaring `yields=True` may return False. A non-yielding op that
returned False would stall the run with no beat to explain it, so the
interpreter RAISES naming the op -- the same choice as everywhere else here:
a stall that looks like a slow computer is the failure law 13 paid forty
silent minutes for.

THE ARGUMENTS ARE `BehaviorParam`, IMPORTED
-------------------------------------------
`params` is `tuple[BehaviorParam, ...]` -- the frozen dataclass from
`scripts/game/behavior/base.py`, imported and not re-declared. Its contract is
already exactly right: it RAISES rather than falling back, it tests `bool`
before `int` (in Python `True` IS an int), it widens `int` to `float`, and it
checks `choices`. Taking the class buys three things at once -- an op
argument and a behavior parameter cannot drift, the editor's `InspectionView`
already renders it, and the generated document's parameter table is the same
generator. Writing an `EventParam` "shaped verbatim like `BehaviorParam`" is
the move that cost this repository 425 duplicated lines.

Two shapes it cannot carry, and each has its own field rather than a widened
`BehaviorParam`:

    tri-state   a param whose declared DEFAULT is None means "absent, or an
                explicit JSON null, both mean DO NOT TOUCH". `hold`'s three
                axes are the only ones today. Any other value still goes
                through `coerce`.
    dynamic     `OpArg` -- a declared key whose type is not knowable from the
                declaration alone, because it depends on the document (`set`'s
                `to` is typed by the variable it names) or is not a scalar
                (`ask`'s `options` is a list). It carries NO coercion at all;
                the spec's own `check` validates it at LOAD, so op knowledge
                stays with the op and the reader stays generic.

NAMING IS FLAT AND THE LOADOUT IS A FIELD
-----------------------------------------
`say`, never `core.say`. `BehaviorSpec` already carries `genres` as a field
rather than as a prefix on the token, and the decisive argument on top of
that: a dotted name freezes the stratum into the permanent string, so
promoting an op from a loadout into core -- which happens the second time two
genres need the same thing -- becomes a RENAME, and law 8 forbids renaming a
file-format string. A design that makes its own most likely future edit
illegal has a bug in it.

The cost of flatness is that portability is not visible in a node. It is paid
three ways: `"loadouts"` at the head of the script file (a one-line diff where
a reviewer looks), the Loadout column of `docs/EVENTS.md`, and the picker's
badge. And it is CHECKABLE, which a prefix convention is not.

`register` RAISES on a duplicate name, naming both loadouts, so two packs
wanting `jump` collide once at registration instead of leaving a permanent
rename hazard on every promotion.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import (Any, Callable, Iterable, Mapping, MutableMapping,
                    Optional, Sequence, Tuple)

from scripts.core.errors import PyoneerAssetMissingError, PyoneerConfigError
from scripts.game.behavior.base import STATUSES, TOKEN, BehaviorParam
from scripts.game.flow.scene_flow import AGENCY_AXES

CORE: str = "core"
"""The loadout every game mode grants: the portable handful.

A FILE FORMAT string -- it is written into every script's `loadouts` array
and into a genre pack's `event_loadouts`. Never renamed.
"""

ASSIGN: str = "assign"
REPLACE_MODES: Tuple[str, ...] = (ASSIGN, "add")
"""How `set` combines its value with what is there. Closed, and both are
FILE FORMAT strings.

`add` exists so `coins - 100` is ONE invertible node rather than a
read-modify-write pair, and because there is deliberately no expression
language: a grammar in a game file is where silent truthiness lives.
"""


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpArg:
    """One argument whose type the DECLARATION cannot state.

    Carries no coercion, deliberately: the moment this class could coerce, it
    would be a second `BehaviorParam` and the two would drift. It declares
    that the key exists (so the unknown-key gate knows it and the generated
    document lists it) and the owning spec's `check` decides what it may be.
    """

    key: str
    label: str
    doc: str
    shape: str
    """What it must be, in words, for the document and for the error message.

    e.g. `"a list of at least two non-empty strings"`, or `"whatever type the
    variable it names was declared with"`.
    """

    required: bool = True
    default: Any = None

    def __post_init__(self) -> None:
        if not TOKEN.match(self.key):
            raise PyoneerConfigError(
                "op argument key %r is not snake_case; it is a key in an "
                "authored .json document and must match %s"
                % (self.key, TOKEN.pattern))


@dataclass(frozen=True)
class OpSpec:
    """Everything about an op that is true without running one.

    One object serves as the registry's record, the editor's picker source and
    the generated document's source, so `docs/EVENTS.md` cannot describe an op
    the interpreter does not have.
    """

    name: str
    summary: str
    run: Callable[[Any, Mapping[str, Any]], bool]
    params: Tuple[BehaviorParam, ...] = ()
    dynamic: Tuple[OpArg, ...] = ()
    loadout: str = CORE
    yields: bool = False
    status: str = "live"
    check: Optional[Callable[[dict, Any, str], Mapping[str, Any]]] = None
    """Load-time validation the declaration cannot express, or None.

    `check(values, variables, where) -> values`. Called by `resolve_args`
    AFTER every declared param has been coerced, with the whole argument dict,
    the variable schema in hand and the node's path for blame. It RAISES on a
    fault and returns the (possibly narrowed) values otherwise.

    This is where an op's own knowledge lives -- that `set`'s `to` is typed by
    the variable `var` names, that `ask` writes an int index -- so the reader
    never grows an `if spec.name == ...` ladder.
    """

    example: Optional[str] = None

    def __post_init__(self) -> None:
        if not TOKEN.match(self.name):
            raise PyoneerConfigError(
                "op name %r is not a legal token; it is written into .json "
                "script documents and must match %s"
                % (self.name, TOKEN.pattern))
        if not callable(self.run):
            raise PyoneerConfigError(
                "op %r declares a run that is not callable (%r)"
                % (self.name, self.run))
        if not TOKEN.match(self.loadout):
            raise PyoneerConfigError(
                "op %r declares loadout %r; a loadout name is written into a "
                "script's `loadouts` array and into a genre pack's "
                "`event_loadouts`, and must match %s"
                % (self.name, self.loadout, TOKEN.pattern))
        if self.status not in STATUSES:
            raise PyoneerConfigError(
                "op %r declares status %r; known statuses are %s"
                % (self.name, self.status, ", ".join(STATUSES)))
        if not isinstance(self.yields, bool):
            raise PyoneerConfigError(
                "op %r declares yields=%r; it says whether the run may stop "
                "the frame, and is a bool" % (self.name, self.yields))
        seen: set[str] = set()
        for key in [p.key for p in self.params] + [a.key for a in self.dynamic]:
            if key in seen:
                raise PyoneerConfigError(
                    "op %r declares argument %r twice; one key is one JSON "
                    "key on one node" % (self.name, key))
            seen.add(key)

    @property
    def arg_keys(self) -> Tuple[str, ...]:
        """Every key a node carrying this op may spell, params first."""
        return tuple([p.key for p in self.params] + [a.key for a in self.dynamic])

    def param(self, key: str) -> BehaviorParam | None:
        for candidate in self.params:
            if candidate.key == key:
                return candidate
        return None

    @property
    def tri_state_keys(self) -> Tuple[str, ...]:
        """Params whose declared default is None: absent and null both pass."""
        return tuple(p.key for p in self.params if p.default is None)


OP_REGISTRY: dict[str, OpSpec] = {}
"""Name -> the spec that describes and runs it. Populated at the bottom."""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(spec: OpSpec,
             registry: MutableMapping[str, OpSpec] | None = None) -> OpSpec:
    """Bind one name to its spec, or raise because the name is taken.

    NOT the behavior registry's replace-on-re-register: a behavior token is
    claimed by one class in one file, while an op name may be claimed by two
    genre packs that never read each other. Two packs both wanting `jump`
    must collide HERE, once, naming both loadouts -- the alternative is that
    the second import silently wins and every script written against the
    first one changes meaning.

    A check that wants to swap an op passes its own `registry` dict.
    """
    target = OP_REGISTRY if registry is None else registry
    existing = target.get(spec.name)
    if existing is not None:
        raise PyoneerConfigError(
            "op %r is already registered by the %r loadout, and the %r "
            "loadout declares it too. An op name is a FILE FORMAT string "
            "written into every script that uses it, so it cannot be "
            "qualified after the fact -- one of the two picks a different "
            "word." % (spec.name, existing.loadout, spec.loadout))
    target[spec.name] = spec
    return spec


def register_all(specs: Iterable[OpSpec],
                 registry: MutableMapping[str, OpSpec] | None = None) -> None:
    """Register a sequence of specs. Mirrors `behavior.register_all`."""
    for spec in specs:
        register(spec, registry)


def resolve(name: Any,
            registry: Mapping[str, OpSpec] | None = None,
            where: str = "") -> OpSpec:
    """The spec for `name`, or raise naming it and listing the vocabulary.

    Never falls back. `registry.resolve`'s reason applies word for word: an
    unknown token that is skipped LOOKS LIKE THE FEATURE WORKING, and a
    branch that only runs on Tuesday would ship broken.
    """
    table = OP_REGISTRY if registry is None else registry
    if not isinstance(name, str):
        raise PyoneerConfigError(
            "%s: `do` is %r (%s); it names an op and is a string"
            % (where or "a script node", name, type(name).__name__))
    spec = table.get(name)
    if spec is None:
        raise PyoneerAssetMissingError(
            "script op", name, available=table.keys(),
            asked_by=where or "<unknown>",
            hint="register it in scripts/game/flow/ops.py, or fix the node's "
                 "`do` key")
    return spec


def loadouts(registry: Mapping[str, OpSpec] | None = None) -> Tuple[str, ...]:
    """Every loadout the registry knows, sorted, `core` first if present.

    Derived from the specs, never declared: a loadout list written down
    separately is a second home for a fact and can disagree in silence.
    """
    table = OP_REGISTRY if registry is None else registry
    names = sorted({spec.loadout for spec in table.values()})
    if CORE in names:
        names.remove(CORE)
        names.insert(0, CORE)
    return tuple(names)


def ops_in(declared: Sequence[str],
           registry: Mapping[str, OpSpec] | None = None) -> Tuple[OpSpec, ...]:
    """Every op a document declaring these loadouts may use, name-sorted."""
    table = OP_REGISTRY if registry is None else registry
    wanted = set(declared)
    return tuple(sorted((s for s in table.values() if s.loadout in wanted),
                        key=lambda s: s.name))


def validate_loadouts(value: Any,
                      registry: Mapping[str, OpSpec] | None = None,
                      where: str = "") -> Tuple[str, ...]:
    """Judge a `loadouts` array and return it as authored.

    Raises on anything that is not a list of strings, on a duplicate, and on a
    name no registered op claims. This is the function
    `editor/core/genre.py` calls for a pack's `event_loadouts` -- the engine's
    own judge, not a second copy of it, exactly as `_object_classes` already
    calls `behavior_registry.validate_list`.

    An EMPTY list is legal and means "this document may use no op at all". It
    is not refused here, because the per-op gate refuses the first op with a
    far better message -- it names the op AND the empty list -- and one rule
    that fires precisely beats two that fire vaguely.
    """
    blame = where or "a document"
    if value is None or isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PyoneerConfigError(
            "%s: `loadouts` is %r (%s); it is a JSON array of loadout names, "
            "e.g. [\"core\"]" % (blame, value, type(value).__name__))
    known = loadouts(registry)
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise PyoneerConfigError(
                "%s: `loadouts` holds %r (%s); every entry is a loadout name"
                % (blame, item, type(item).__name__))
        if item in seen:
            raise PyoneerConfigError(
                "%s: `loadouts` names %r twice" % (blame, item))
        if item not in known:
            raise PyoneerAssetMissingError(
                "op loadout", item, available=known, asked_by=blame,
                hint="a loadout exists because an op declares it; grant one "
                     "the registry knows, or register an op with loadout=%r"
                     % (item,))
        seen.add(item)
        out.append(item)
    return tuple(out)


def check_loadout(spec: OpSpec, declared: Sequence[str], where: str = "") -> OpSpec:
    """Refuse an op the document's own `loadouts` do not grant.

    Raised at LOAD, never at execution: a script using a platformer op in a
    top-down scene must fail before a frame runs, because an op discovered
    mid-cutscene has already stolen the player's agency.
    """
    if spec.loadout not in tuple(declared):
        raise PyoneerConfigError(
            "%s: op %r belongs to the %r loadout, and this document declares "
            "%s. Add %r to its `loadouts`, or use an op from one it already "
            "has."
            % (where or "a script node", spec.name, spec.loadout,
               ", ".join(repr(d) for d in declared) or "<none>", spec.loadout))
    return spec


# ---------------------------------------------------------------------------
# Reading one node's arguments
# ---------------------------------------------------------------------------

def resolve_args(spec: OpSpec,
                 raw: Mapping[str, Any],
                 variables: Any = None,
                 where: str = "") -> dict[str, Any]:
    """The validated arguments for one node, or raise naming the key.

    Mirrors `registry.resolve_params`, minus the two levels a behavior has
    (a tmx property and an actors row) -- a node's arguments are written on
    the node and nowhere else.

    Unknown keys RAISE rather than being ignored (law 7): a key the writer
    keeps and the reader drops is the 39-silently-dropped-tiles shape with a
    delay fuse, and a misspelled `txt` would otherwise leave a `say` with no
    line and no complaint.
    """
    blame = where or "a script node"
    known = set(spec.arg_keys)
    stray = sorted(k for k in raw if k not in known)
    if stray:
        raise PyoneerConfigError(
            "%s: op %r was given %s, which it does not take. It takes %s."
            % (blame, spec.name, ", ".join(repr(k) for k in stray),
               ", ".join(spec.arg_keys) or "no arguments"))

    values: dict[str, Any] = {}
    for param in spec.params:
        tri_state = param.default is None
        if param.key not in raw or (raw[param.key] is None and tri_state):
            if param.required:
                raise PyoneerConfigError(
                    "%s: op %r needs %r (%s), and the node does not give it"
                    % (blame, spec.name, param.key, param.type))
            values[param.key] = param.default
            continue
        try:
            # The SAME coercion a behavior parameter gets, deliberately: an op
            # argument and a behavior parameter cannot drift because they are
            # one class. Its message spells `pyoneer_param_<key>`, which is
            # that class's own vocabulary rather than a script's, so the node
            # path and the JSON key are stated here in front of it.
            values[param.key] = param.coerce(raw[param.key])
        except PyoneerConfigError as exc:
            raise PyoneerConfigError(
                "%s: op %r argument %r must be %s and the node gives %r "
                "(%s). (%s)"
                % (blame, spec.name, param.key, param.type, raw[param.key],
                   type(raw[param.key]).__name__, exc.message)) from exc

    for arg in spec.dynamic:
        if arg.key not in raw:
            if arg.required:
                raise PyoneerConfigError(
                    "%s: op %r needs %r -- %s -- and the node does not give it"
                    % (blame, spec.name, arg.key, arg.shape))
            values[arg.key] = arg.default
            continue
        values[arg.key] = raw[arg.key]

    if spec.check is not None:
        values = dict(spec.check(values, variables, blame))
    return values


def _declared(variables: Any, name: Any, spec_name: str, key: str, where: str):
    """The declaration for a variable a node names, or raise saying why not.

    `variables is None` is a WIRING error and says so, exactly as
    `table_file.actor_row` distinguishes "no tables directory" from "nobody
    handed this pass a reader": an undeclared variable and an unchecked one
    have different fixes, and collapsing them would let a schema-less load
    quietly accept every typo in the document.
    """
    if not isinstance(name, str):
        raise PyoneerConfigError(
            "%s: op %r argument %r is %r (%s); it names a variable and is a "
            "string" % (where, spec_name, key, name, type(name).__name__))
    if variables is None:
        raise PyoneerConfigError(
            "%s: op %r names the variable %r and this load was given no "
            "variable schema, so nothing can say whether it exists or what "
            "type it is. Pass the scene's `vars` to the reader "
            "(`load_script(path, variables=...)`)."
            % (where, spec_name, name))
    return variables.declaration(name, where)


# ---------------------------------------------------------------------------
# The load-time checks the declarations cannot express
# ---------------------------------------------------------------------------

def _check_set(values: dict, variables: Any, where: str) -> dict:
    """`to` is typed by the variable `var` names, and `add` needs a number."""
    decl = _declared(variables, values["var"], "set", "var", where)
    values["var"] = decl.name
    if values["by"] == "add" and decl.type not in ("int", "float"):
        raise PyoneerConfigError(
            "%s: `set` asks to add to %r, which is declared %s. `add` is "
            "arithmetic; on a %s use by=\"assign\"."
            % (where, decl.name, decl.type, decl.type))
    values["to"] = decl.coerce(values["to"], where)
    return values


def _check_ask(values: dict, variables: Any, where: str) -> dict:
    """`options` is a real list, and `into` is a declared int variable."""
    options = values["options"]
    if (isinstance(options, (str, bytes)) or not isinstance(options, Sequence)
            or len(options) < 2):
        raise PyoneerConfigError(
            "%s: `ask` was given options=%r; it is %s. A choice with fewer "
            "than two options is a `say`."
            % (where, options, ASK_OPTIONS.shape))
    for index, option in enumerate(options):
        if not isinstance(option, str) or not option.strip():
            raise PyoneerConfigError(
                "%s: `ask` option %d is %r; every option is a non-empty "
                "string, and it is what the player reads"
                % (where, index, option))
    values["options"] = tuple(options)
    decl = _declared(variables, values["into"], "ask", "into", where)
    if decl.type != "int":
        raise PyoneerConfigError(
            "%s: `ask` writes the INDEX of the chosen option into %r, which "
            "is declared %s. Declare it int."
            % (where, decl.name, decl.type))
    values["into"] = decl.name
    return values


def _check_wait(values: dict, variables: Any, where: str) -> dict:
    """A wait of zero is a node whose runtime is a no-op."""
    if values["ms"] <= 0:
        raise PyoneerConfigError(
            "%s: `wait` declares ms=%r. A wait of zero or less elapses on the "
            "frame it is entered, which is indistinguishable from the node "
            "not being in the script -- and a node whose runtime is a no-op "
            "is the reason there is no `comment` op. Give it a real beat, or "
            "delete it." % (where, values["ms"]))
    return values


def _check_hold(values: dict, variables: Any, where: str) -> dict:
    """A hold that names no axis takes nothing and gives nothing back."""
    if all(values[axis] is None for axis in AGENCY_AXES):
        raise PyoneerConfigError(
            "%s: `hold` names no axis, so it would take no agency and its "
            "`release` would give none back. Name at least one of %s -- "
            "steerable=false is the cutscene hold, and it deliberately leaves "
            "enabled_inputs alone so the body can still press continue."
            % (where, ", ".join(AGENCY_AXES)))
    return values


# ---------------------------------------------------------------------------
# THE CORE EIGHT
#
# The test each member had to pass: does it mean the same thing in a top-down
# RPG, a platformer and a visual novel? A script written from core alone runs
# unchanged when the game mode changes.
#
# Control flow (if / elif / else, while) is SCHEMA, not vocabulary -- a node
# shape, as in most languages -- so it costs nothing against the eight.
#
# `enter_scene` is core and is NOT here: scene switching is measurably broken
# (a `set_scene` that is a one-line pointer swap, an outgoing scene that keeps
# drawing, an `active` flag no writer clears), so it registers in the stage
# that fixes it. An op whose `run` does nothing is the defect `play_sound` was
# rejected for.
# ---------------------------------------------------------------------------

def _run_say(run: Any, args: Mapping[str, Any]) -> bool:
    """Show a line and wait for the advance.

    Consumes a pending advance on the frame it opens, so a press that landed
    before the line was shown does not skip the line it was never given a
    chance to read.
    """
    if run.first_step:
        run.take_advance()
        run.host_say(args["who"], args["text"])
        return False
    if not run.take_advance():
        return False
    run.host_end_say()
    return True


def _run_ask(run: Any, args: Mapping[str, Any]) -> bool:
    """Refuse, naming what is missing. This op is `needs-host` and honest.

    A branch with nothing to branch ON is not a branching system, so `ask` is
    registered, authorable, picked and documented -- and NO WIDGET IN THIS
    ENGINE REPORTS A CLICK TO ANYTHING, which `scene_flow.py` states as the
    reason it has no branching either. Returning quietly, or writing a
    default index into `into`, would be a promise; a script would take the
    first arm forever and look like it was choosing.
    """
    raise PyoneerConfigError(
        "%s: `ask` needs a host that reports a CHOICE, and this engine has "
        "none -- no widget reports a click to anything, which is why the op "
        "ships with status \"needs-host\" and why `docs/EVENTS.md` measures "
        "its runtime as no. Prompt was %r with %d option(s)."
        % (run.blame, args["prompt"], len(args["options"])))


def _run_set(run: Any, args: Mapping[str, Any]) -> bool:
    """Write a variable. `by="add"` is arithmetic, checked at load."""
    name = args["var"]
    if args["by"] == "add":
        run.variables.set(name, run.variables.get(name) + args["to"])
    else:
        run.variables.set(name, args["to"])
    return True


def _run_wait(run: Any, args: Mapping[str, Any]) -> bool:
    """Hold this node for `ms` milliseconds of engine time.

    `node_elapsed_ms` is grown by `ScriptRun.update`, which converts the
    engine delta through `MS_PER_DELTA` exactly once. A conversion here would
    be the second one, and two of them is the ~16.7x error that still looks
    like it works.
    """
    return run.node_elapsed_ms >= args["ms"]


def _run_hold(run: Any, args: Mapping[str, Any]) -> bool:
    """Take agency, through the same `AgencyHold` a `SceneFlow` uses."""
    run.hold(steerable=args["steerable"],
             enabled_inputs=args["enabled_inputs"],
             simulated=args["simulated"])
    return True


def _run_release(run: Any, args: Mapping[str, Any]) -> bool:
    """Give back exactly what `hold` recorded. Never `True`."""
    run.release()
    return True


def _run_call(run: Any, args: Mapping[str, Any]) -> bool:
    """Run another script's body here, then carry on. Depth-capped at 16."""
    run.call_script(args["script"])
    return True


def _run_stop(run: Any, args: Mapping[str, Any]) -> bool:
    """End the run from inside any arm, releasing anything still held."""
    run.stop()
    return True


def _param(key: str, label: str, type_: str, default: Any, doc: str,
           choices: Tuple[Any, ...] = (), required: bool = False) -> BehaviorParam:
    """One op argument. `source` is fixed: a node is the only place it lives."""
    return BehaviorParam(key=key, label=label, type=type_, default=default,
                         doc=doc, choices=choices, source="object",
                         required=required)


ASK_OPTIONS = OpArg(
    key="options", label="options",
    doc="What the player may pick. The INDEX of the pick is written to "
        "`into`, so inserting an option renumbers every branch after it.",
    shape="a list of at least two non-empty strings")

SET_TO = OpArg(
    key="to", label="to",
    doc="The value. With by=\"assign\" it replaces; with by=\"add\" it is "
        "added, so -100 is how a purchase is written.",
    shape="whatever type the variable named by `var` was declared with")

SAY = OpSpec(
    name="say",                                                    # #TAG:say
    summary="Show a line and wait for the advance.",
    run=_run_say,
    params=(_param("text", "text", "str", "", "The line.", required=True),
            _param("who", "who", "str", "",
                   "Who is speaking. Empty is narration.")),
    yields=True,
    example='{"id": "n3", "do": "say", "who": "Keeper", '
            '"text": "The north gate is sealed."}')

ASK = OpSpec(
    name="ask",                                                    # #TAG:ask
    summary="Offer a choice and write the chosen index into a variable.",
    run=_run_ask,
    params=(_param("prompt", "prompt", "str", "", "The question.",
                   required=True),
            _param("into", "into", "str", "",
                   "The int variable the chosen INDEX is written to.",
                   required=True)),
    dynamic=(ASK_OPTIONS,),
    yields=True,
    status="needs-host",
    check=_check_ask,
    example='{"id": "n8", "do": "ask", "prompt": "Half now?", '
            '"options": ["Pay half", "Walk away"], "into": "keeper_pick"}')

SET = OpSpec(
    name="set",                                                    # #TAG:set
    summary="Write a declared variable, by assignment or by addition.",
    run=_run_set,
    params=(_param("var", "variable", "str", "",
                   "The variable to write. Bare means the `scene.` "
                   "namespace.", required=True),
            _param("by", "by", "str", ASSIGN,
                   "assign replaces; add is arithmetic and needs a numeric "
                   "variable.", choices=REPLACE_MODES)),
    dynamic=(SET_TO,),
    check=_check_set,
    example='{"id": "n6", "do": "set", "var": "coins", "to": -100, '
            '"by": "add"}')

WAIT = OpSpec(
    name="wait",                                                   # #TAG:wait
    summary="Hold this node for a number of milliseconds.",
    run=_run_wait,
    params=(_param("ms", "milliseconds", "float", 0.0,
                   "Milliseconds, matching cooldown_ms and lifetime_ms "
                   "everywhere else. Must be above zero.", required=True),),
    yields=True,
    check=_check_wait,
    example='{"id": "n14", "do": "wait", "ms": 250}')

HOLD = OpSpec(
    name="hold",                                                   # #TAG:hold
    summary="Take the bodies' agency, recording what to give back.",
    run=_run_hold,
    params=tuple(_param(axis, axis.replace("_", " "), "bool", None, doc)
                 for axis, doc in (
                     ("steerable",
                      "false stops the body walking. The gate is on the "
                      "producer, so a side-on body still falls."),
                     ("enabled_inputs",
                      "false silences the action behaviors too -- clearing "
                      "this AND steerable is how a dialogue locks itself out "
                      "of its own continue button."),
                     ("simulated",
                      "false stops a GamePlayer completely, animation clock "
                      "included. Per entity; there is no world pause."))),
    check=_check_hold,
    example='{"id": "n2", "do": "hold", "steerable": false}')

RELEASE = OpSpec(
    name="release",                                             # #TAG:release
    summary="Give back exactly the agency `hold` recorded. Never `true`.",
    run=_run_release,
    example='{"id": "n15", "do": "release"}')

CALL = OpSpec(
    name="call",                                                   # #TAG:call
    summary="Run another script's first passing page here, then carry on.",
    run=_run_call,
    params=(_param("script", "script", "str", "",
                   "The id of the script to run, which is also its file "
                   "stem.", required=True),),
    example='{"id": "n5", "do": "call", "script": "shop_intro"}')

STOP = OpSpec(
    name="stop",                                                   # #TAG:stop
    summary="End the run from inside any arm, releasing anything held.",
    run=_run_stop,
    example='{"id": "n13", "do": "stop"}')

CORE_OPS: Tuple[OpSpec, ...] = (SAY, ASK, SET, WAIT, HOLD, RELEASE, CALL, STOP)
"""The portable handful, in the order `docs/EVENTS.md` argues for them."""


# ---------------------------------------------------------------------------
# The generated document's registry half
# ---------------------------------------------------------------------------

def describe_all(registry: Mapping[str, OpSpec] | None = None) -> str:
    """Render the registry half of `docs/EVENTS.md` from the registry itself.

    Every count and every row is derived. `tools/check_event_docs.py` adds the
    half this table cannot see -- what each op DOES when it is actually run,
    and whether the editor's picker offers it -- and writes the file.

    There is no hand-written prose here about what the code does, only about
    what the FORMAT is. `docs/BEHAVIORS.md`'s preamble carried two lies while
    matching its generator byte for byte, which is the local proof that a
    generated file's prose is the one part of it that can rot.
    """
    table = OP_REGISTRY if registry is None else registry
    specs = sorted(table.values(), key=lambda s: (s.loadout != CORE,
                                                  s.loadout, s.name))
    known = loadouts(registry)
    lines = [
        "# Event script ops -- the vocabulary a script may spell",
        "",
        "**This file is generated.** `scripts/game/flow/ops.py` holds the "
        "table. Edit the specs, not this file.",
        "",
        "%d op(s) in %d loadout(s): %s."
        % (len(table), len(known), ", ".join("`%s`" % n for n in known)
           or "none"),
        "",
        "## The protocol",
        "",
        "A script is `data/project/scripts/<id>.json`. It declares which "
        "loadouts it uses; every op it spells must belong to one of them, "
        "and the check is at LOAD, never at execution.",
        "",
        "```json",
        '{"format": "pyoneer.script", "version": 1, "id": "keeper_gate",',
        ' "loadouts": ["core"],',
        ' "pages": [{"id": "pg", "trigger": "use", "when": [],',
        '            "body": [{"id": "n1", "do": "say", "text": "Hello."}]}]}',
        "```",
        "",
        "A node is one of exactly two shapes: executable "
        "`{\"id\", \"do\", ...arguments}`, or control "
        "`{\"id\", \"if\"|\"while\", \"then\", \"elif\", \"else\"}`. Any node "
        "may carry a `note`. Nothing else parses, and an unknown key raises "
        "naming its path.",
        "",
        "## The registry",
        "",
    ]
    if not table:
        lines.append("**The registry is empty.** Every `do` raises.")
        return "\n".join(lines) + "\n"

    lines.append("| op | loadout | arguments | yields | status | summary |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for spec in specs:
        lines.append("| `%s` | `%s` | %s | %s | %s | %s |"
                     % (spec.name, spec.loadout,
                        ", ".join("`%s`" % k for k in spec.arg_keys) or "--",
                        "yes" if spec.yields else "no", spec.status,
                        spec.summary))
    lines.append("")

    for spec in specs:
        lines.append("### `%s`" % spec.name)
        lines.append("")
        lines.append(spec.summary)
        lines.append("")
        if spec.status != "live":
            lines.append("> **Status: %s.** It is registered, authorable and "
                         "documented, and something outside the engine has to "
                         "exist before it can do its job." % spec.status)
            lines.append("")
        lines.append("- **loadout** `%s`" % spec.loadout)
        lines.append("- **yields** %s"
                     % ("yes -- it can stop the frame and resume on the next"
                        if spec.yields else
                        "no -- it completes in the frame it is entered"))
        lines.append("")
        if spec.params or spec.dynamic:
            lines.append("| argument | type | default | required | meaning |")
            lines.append("| --- | --- | --- | --- | --- |")
            for param in spec.params:
                lines.append(
                    "| `%s` | %s | %s | %s | %s |"
                    % (param.key, param.type,
                       "*(tri-state: absent or null means do not touch)*"
                       if param.default is None else "`%r`" % (param.default,),
                       "yes" if param.required else "no", param.doc))
            for arg in spec.dynamic:
                lines.append("| `%s` | %s | %s | %s | %s |"
                             % (arg.key, arg.shape,
                                "`%r`" % (arg.default,) if not arg.required
                                else "--",
                                "yes" if arg.required else "no", arg.doc))
        else:
            lines.append("Takes no arguments.")
        lines.append("")
        if spec.example:
            lines.append("```json")
            lines.append(spec.example)
            lines.append("```")
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# The table
#
# One entry per op, written by hand. A loadout beyond `core` registers from
# its own module, imported at the bottom of this one -- a registry populated
# by importing the modules that declare into it, which is how
# `behavior/registry.py` already gets its specs.
# ---------------------------------------------------------------------------

register_all(CORE_OPS)

__all__ = [
    "ASSIGN", "CORE", "CORE_OPS", "OP_REGISTRY", "REPLACE_MODES", "OpArg",
    "OpSpec", "check_loadout", "describe_all", "loadouts", "ops_in",
    "register", "register_all", "resolve", "resolve_args", "validate_loadouts",
]
