"""What a map object COMPOSES, as data: the behavior list, its parameters,
the state axes it writes, and every reason the engine would refuse it.

WHY THIS IS DATA AND NOT A WIDGET
---------------------------------
Same argument `editor/core/inspect.py` makes and `editor/ui/actions_panel.py`
repeats: `describe_behaviors` returns an `Inspection`, so `InspectionView`
renders it with typed editors, per-field remove buttons and command emission
already written, and a check can assert "ticking `platformer_move` on a
top-down body emits nothing and names both sides" without opening a window.
The first run of the equivalent check on the Inspector found two fields wired
to the wrong verb.

THE ENGINE IS THE AUTHORITY, ALWAYS
-----------------------------------
Nothing here re-implements a rule. The checklist is `BEHAVIOR_REGISTRY`
itself, so a behavior registered tomorrow appears with no edit to this file
-- the same property that makes `docs/BEHAVIORS.md` generated. The parameter
rows are `BehaviorParam`, which was deliberately shaped like
`editor.core.layers.Capability` so this panel could be the layer inspector's
loop with a different tuple. The axis rows come from `BodyState().axes`.

And the refusals are the ENGINE'S refusals, obtained by RUNNING it:
`refusals()` calls `validate_list`, and then drives a real `EntityBehaviors`
with inert stand-ins carrying the real specs. That matters because the four
refusal rules are split across two files -- `validate_list` knows unknown,
duplicate and declared-conflict; `EntityBehaviors.attach` knows those three
PLUS "same order and intersecting writes", which needs the spec pair and
exists nowhere else. A panel that only called `validate_list` would bless
lists the engine rejects at load, which is worse than no panel; a panel that
re-spelled the fourth rule would be the second implementation this repo
deletes 425 lines of at a time. Driving the real judge is neither.

WHAT THIS MODULE COSTS
----------------------
Importing it imports `scripts.game.behavior.registry`, which imports
`pygame` (through `scripts.core.event_types`, which `base.py` needs to
validate `BehaviorSpec.binds`). `editor/requirements.txt` already lists
`pygame~=2.6.0`, so it costs nothing at runtime -- but this module is no
longer pygame-free and that is worth knowing before it is imported from
somewhere that assumed otherwise. It imports no Qt and must not: the
one-way rule is `editor/` may import `scripts/`, and `editor/core/` may not
import `editor/ui/`.

A BEHAVIOR REGISTERED BY THE GAME IS NOT IN THIS LIST
------------------------------------------------------
`demos/behaviors.py` registers `patrol_input` at import, and `docs/DEMOS.md`
calls that a proven extension point. The editor does not import `demos/`, so
such a token is not in `BEHAVIOR_REGISTRY` here. It renders as a ticked row
that can be UNTICKED, never silently dropped, and the section note says the
checklist is the engine's registry rather than an exhaustive list of what may
run.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Sequence

from editor.core.commands import Command
from editor.core.inspect import Field, Inspection, Section
from editor.core.scope import Scope

from scripts.core.errors import PyoneerError
from scripts.game.behavior import registry as behavior_registry
from scripts.game.behavior.base import (BEHAVIORS, PARAM_PREFIX, BehaviorParam,
                                        BehaviorSpec, EntityBehavior,
                                        EntityBehaviors)
from scripts.game.behavior.state import BodyState

#: How a spec spells "I write this axis of the shared body state".
#: `registry._state_axes()` spells the same prefix when it generates the axis
#: table into BEHAVIORS.md. Two spellings of one string is how a value drifts,
#: so `tools/check_behavior_ui.py` asserts that every `state.*` write declared
#: by every registered spec names an axis `BodyState` actually has -- which is
#: the falsifiable version of "these two agree".
STATE_PREFIX = "state."

#: One sentence per axis, borrowed from the table that generates BEHAVIORS.md
#: rather than re-written here -- there is one home for those sentences and a
#: second copy would rot against it. Read through `getattr` because the name
#: is private to a module this pass does not own: if it is ever renamed the
#: panel loses its tooltips, which is a degradation, where an ImportError
#: would be the whole editor failing to start.
_AXIS_DOC: Mapping[str, str] = getattr(behavior_registry, "_AXIS_DOC", {})

_NO_OBJECT = ("Select an object on an object layer. `pyoneer_behaviors` is a "
              "property of the OBJECT -- the map file is the whole truth, so "
              "there is nowhere else a composition can be declared.")

_CHECKLIST_NOTE = (
    "Every behavior the engine has registered, in the order they run within a "
    "frame. This is BEHAVIOR_REGISTRY itself, not a list kept here -- but a "
    "game may register its own at import (demos/behaviors.py registers "
    "`patrol_input`), and the editor does not import the game, so a token it "
    "does not recognise is shown ticked rather than dropped.")

_PARAM_NOTE = (
    "Stored per object as `{prefix}<key>` and resolved most-specific-first: "
    "this property, then the actors row named by `pyoneer_actor`, then the "
    "declared default. NOTHING IN scripts/ READS data/project/ -- there is no "
    "engine-side table reader -- so the middle step is skipped today and a "
    "`source=actors` parameter resolves from this property or from its "
    "default.").format(prefix=PARAM_PREFIX)

_AXES_NOTE = (
    "What this composition writes on the shared `BodyState` record. Two "
    "behaviors at the SAME order writing one axis is refused, because which "
    "one wins would depend on attach order -- that refusal is the whole "
    "reason a spec declares `state.<axis>` per axis instead of just `state`. "
    "Two at DIFFERENT orders is legal and the later one wins.")


class _Inert(EntityBehavior):
    """A stand-in that carries a real spec and does nothing.

    `EntityBehaviors.attach` needs an `EntityBehavior` with a `spec`; it reads
    the spec for every one of its four refusals and then calls the behavior's
    own `attach` hook, which here is the base class's no-op. So the judgement
    is the engine's, run against the real declarations, with none of the work
    -- no input manager polled, no `MoveIntent` allocated, no verb resolved
    against `config/inputs.json`.
    """

    def update(self, entity: Any, event: Any) -> None:      # pragma: no cover
        """Never called: nothing drives these."""


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def object_at(session, scope: Scope):
    """`(object_layer, object)` for an object scope, or `(None, None)`.

    Never raises. A selection goes stale constantly -- an object removed by an
    undo, a layer renamed under it -- and every caller wants the same answer
    for all of them.

    `editor/ui/actions_panel.py` carries a function of the same name and the
    same six lines. That one is in a Qt module, so it cannot be the shared
    home and this cannot import it (`editor/core/` may not import
    `editor/ui/`). This is the headless home; the panel's copy should be
    deleted in favour of this one the next time that file is touched.
    """
    if scope.kind != "object":
        return None, None
    try:
        document = session.project.map(scope.require("map"))
        layer = document.object_layer(scope.require("layer"))
        return layer, layer.find(int(scope.require("object")))
    except Exception:                                           # noqa: BLE001
        return None, None


def read_tokens(obj: Any) -> tuple[str, ...]:
    """The behavior tokens this object declares, exactly as authored.

    `parse_list`, so a hand-edited `" TopDown_Move , animation_drive "` reads
    as the two tokens it means -- Tiled's property editor is a free-text box.
    Duplicates are KEPT, because a duplicate is a typo and one that vanished
    here is a typo nothing could report.
    """
    if obj is None:
        return ()
    return behavior_registry.parse_list(obj.properties.as_dict().get(BEHAVIORS))


def is_vocabulary(key: str) -> bool:
    """Whether `key` is a tmx property this panel owns.

    `pyoneer_behaviors` and every `pyoneer_param_*`. Deliberately NOT
    `pyoneer_actor`: that names an actors-table row, nothing in `scripts/`
    reads `data/project/` yet, and it is an ordinary string the generic
    property editor handles correctly.
    """
    return key == BEHAVIORS or key.startswith(PARAM_PREFIX)


# --------------------------------------------------------------------------
# The refusals -- obtained by running the engine, never by re-stating it
# --------------------------------------------------------------------------

#: What `EntityBehaviors` is told it is composing onto. One instance, shared,
#: and safe to share because nothing writes to it: it is stored, passed to
#: `_Inert.attach` (which does nothing), and read only for
#: `type(...).__name__` in the one refusal message `validate_list` always
#: reaches first. Named for what an author would recognise all the same.
_CANDIDATE = type("entity", (object,), {})()


def refusals(tokens: Sequence[str],
             registry: Mapping[str, BehaviorSpec] | None = None
             ) -> tuple[str, ...]:
    """Every reason the engine would refuse this list, in the engine's words.

    Two calls, because the rules live in two places and neither knows all of
    them:

        validate_list           unknown token, duplicate, declared conflict
        EntityBehaviors.attach  those three, PLUS same order + intersecting
                                writes -- which needs the spec pair and is
                                implemented only there

    Returns at most one sentence: both authorities raise on the first problem
    they find rather than collecting, and a panel that invented a
    collect-everything pass would be inventing a judgement rather than
    reporting one.

    There is deliberately no `owner` argument. The only message that would use
    one is `attach`'s duplicate refusal, and `validate_list` reaches a
    duplicate first, so the name could never appear -- a parameter nothing can
    reach is the orphan shape this repo keeps a document about.
    """
    try:
        behavior_registry.validate_list(list(tokens), registry)
    except PyoneerError as error:
        return (str(error),)

    holder = EntityBehaviors(_CANDIDATE)
    for token in tokens:
        try:
            stand_in = _Inert()
            # Inside the guard, not above it. `resolve` raises for a token the
            # registry lacks, and while `validate_list` always reaches that
            # first today, a refusal reporter that can itself raise is a
            # reporter that takes the panel down instead of describing it.
            stand_in.spec = behavior_registry.resolve(token, registry)
            holder.attach(stand_in)
        except PyoneerError as error:
            # Stop at the first: the composition is now half-built, and every
            # further refusal would be reported against a set the author never
            # asked for.
            return (str(error),)
    return ()


def unknown_axes(registry: Mapping[str, BehaviorSpec] | None = None
                 ) -> tuple[tuple[str, str], ...]:
    """(behavior, write) for every `state.<axis>` naming an axis that is not one.

    The falsifiable half of "`STATE_PREFIX` above and `BodyState` agree". A
    behavior declaring `state.movnig` would produce an axis row for a field
    that does not exist and an animator reading a phase that never changes --
    an animation bug in a file that is correct.
    """
    table = (behavior_registry.BEHAVIOR_REGISTRY if registry is None
             else registry)
    known = set(BodyState().axes)
    strays: list[tuple[str, str]] = []
    for spec in sorted(table.values(), key=lambda s: (s.order, s.name)):
        for written in spec.writes:
            if (written.startswith(STATE_PREFIX)
                    and written[len(STATE_PREFIX):] not in known):
                strays.append((spec.name, written))
    return tuple(strays)


# --------------------------------------------------------------------------
# Describing
# --------------------------------------------------------------------------

def describe_behaviors(session, scope: Scope, *,
                       registry: Mapping[str, BehaviorSpec] | None = None,
                       on_error: Callable[[str], None] | None = None
                       ) -> Inspection:
    """What the behavior panel shows for one scope. Never raises.

    `on_error` receives the message when an emitter refuses to build a command
    -- a parameter coerced to the wrong type, a list that `format_list` will
    not spell. The emitters return None in that case, which the view treats as
    a silent no-op, so without a sink the author gets no explanation. The dock
    passes a label; a check passes a list.
    """
    _layer, obj = object_at(session, scope)
    if obj is None:
        return Inspection(
            scope, "Behaviors",
            error=(_NO_OBJECT if scope.kind != "object" else
                   f"object {scope.get('object')} is no longer on "
                   f"{scope.get('layer')!r} -- it may have been undone"))
    try:
        return _describe(session, scope, obj, registry, on_error or (lambda _m: None))
    except Exception as exc:                                    # noqa: BLE001
        return Inspection(scope, "Behaviors",
                          error=f"{type(exc).__name__}: {exc}")


def _describe(session, scope: Scope, obj: Any,
              registry: Mapping[str, BehaviorSpec] | None,
              on_error: Callable[[str], None]) -> Inspection:
    table = (behavior_registry.BEHAVIOR_REGISTRY if registry is None
             else registry)
    tokens = read_tokens(obj)
    raw = obj.properties.as_dict()
    genre = getattr(session.project.genre, "id", "")

    standing = refusals(tokens, registry)
    sections = [
        _checklist(scope, tokens, table, genre, standing, registry, on_error),
        _parameters(scope, tokens, table, raw, on_error),
        _axes(tokens, table),
    ]
    problems = _problems(tokens, table, raw, standing)
    if problems is not None:
        # First, not last. It is the reason this panel exists and burying it
        # under three sections is how a refusal ends up reported as the editor
        # "not saving my change" -- the same argument the layer inspector
        # makes for putting Capabilities above the read-only statistics.
        sections.insert(0, problems)

    return Inspection(
        scope, obj.name or f"object {obj.id}",
        (behavior_registry.format_list(dict.fromkeys(tokens)) if tokens
         else "composes nothing -- an object with no behaviors is inert"),
        sections)


def _checklist(scope: Scope, tokens: Sequence[str],
               table: Mapping[str, BehaviorSpec], genre: str,
               standing: Sequence[str],
               registry: Mapping[str, BehaviorSpec] | None,
               on_error: Callable[[str], None]) -> Section:
    """One tickable row per registered token, plus any the registry lacks."""
    section = Section("Behaviors", note=_CHECKLIST_NOTE)
    for spec in sorted(table.values(), key=lambda s: (s.order, s.name)):
        present = spec.name in tokens
        section.fields.append(Field(
            spec.name,
            _token_label(spec, present, genre, tokens),
            "bool", present,
            doc=_token_doc(spec, genre),
            emit=_toggle_emitter(scope, tokens, spec.name, present, on_error),
            blocked_reason=_toggle_block(tokens, spec, present,
                                         standing, registry)))

    # A token the registry does not know still has to be visible and still has
    # to be removable -- it is either a typo or a behavior the GAME registers,
    # and both are fixed by unticking or by leaving it alone.
    for token in dict.fromkeys(t for t in tokens if t not in table):
        section.fields.append(Field(
            token, f"{token}   ·   not in the editor's registry", "bool", True,
            doc="Either a typo -- in which case the panel's first section "
                "lists every token the engine does know -- or a behavior the "
                "game registers at import, which the editor never sees. "
                "Unticking removes it from the object.",
            emit=_toggle_emitter(scope, tokens, token, True, on_error)))
    return section


def _token_label(spec: BehaviorSpec, present: bool, genre: str,
                 tokens: Sequence[str]) -> str:
    label = f"{spec.name}   ·   order {spec.order}"
    if spec.status != "live":
        # The generated table excludes a non-live behavior from its "complete,
        # legal list" column for exactly this reason: `requires` is REPORTED
        # and never enforced, so a behavior whose host nothing assigns simply
        # does nothing and there is no crash to reveal it.
        label += f"   ·   {spec.status}"
    if genre and spec.genres and genre not in spec.genres:
        label += "   ·   genre " + "/".join(spec.genres)
    if present and list(tokens).count(spec.name) > 1:
        label += "   ·   LISTED TWICE"
    return label


def _token_doc(spec: BehaviorSpec, genre: str) -> str:
    parts = [spec.summary]
    if spec.writes:
        parts.append("writes " + ", ".join(spec.writes))
    if spec.requires:
        parts.append("requires " + ", ".join(spec.requires))
    if spec.conflicts:
        parts.append("conflicts with " + ", ".join(spec.conflicts))
    parts.append("genres: " + (", ".join(spec.genres) or "any"))
    if genre and spec.genres and genre not in spec.genres:
        parts.append(
            f"This project's genre is {genre!r}. `genres` is the pack's "
            f"advice and NOTHING IN THE ENGINE READS IT -- no loader gates on "
            f"it -- so this is offered rather than refused. A side-on body on "
            f"a top-down map is a strange map, not an illegal one.")
    return "\n".join(parts)


def _toggle_block(tokens: Sequence[str], spec: BehaviorSpec,
                  present: bool, standing: Sequence[str],
                  registry: Mapping[str, BehaviorSpec] | None) -> str:
    """Why this row cannot be ticked, or empty. Engine refusals ONLY.

    `blocked_reason` means one thing here: the engine would refuse the
    resulting list. It deliberately does NOT carry the genre mismatch, which
    the label and the tooltip carry instead -- `spec.genres` is read by
    `describe_all` and by nothing else in `scripts/`, so blocking on it would
    be the editor inventing a refusal the engine does not have, which is how a
    tool ends up reported as unable to do something it merely will not.

    Two rules, and the second is the subtle half:

      * removal is never blocked. Whatever is on the object has to be able to
        come off.
      * a tick is refused only when it INTRODUCES a refusal. While the
        authored list is ALREADY refused -- a hand-typed duplicate, a token
        that no longer resolves -- every row stays editable, because every
        toggle is then an attempt to repair it. Blocking on the candidate
        alone would deadlock a broken list: unticking any one token leaves the
        other problem in place, so nothing could be changed and the only
        repair left would be Tiled.
    """
    if present or standing:
        return ""
    return next(iter(refusals(tuple(tokens) + (spec.name,), registry)), "")


def _toggle_emitter(scope: Scope, tokens: Sequence[str], token: str,
                    present: bool, on_error: Callable[[str], None]):
    """Ticking or unticking one token, as one command over the whole list.

    `map.object.property.set`, not a new verb. `pyoneer_behaviors` IS an
    ordinary tmx custom property, that pair already writes any property and
    already returns the exact inverse -- a `.set` carrying the value it FOUND
    when the key existed, a `.remove` when it did not -- and it is under
    `tools/check_editor.py` already. A `map.object.behaviors.*` family would
    be a second door onto one property, and the only thing it could add is
    validation, which has to happen HERE anyway: a refused list must never
    reach the command stream, because a command that raises inside a
    transaction takes the rollback with it.
    """
    def emit(value: Any) -> Command | None:
        want = bool(value)
        if want == present:
            return None
        candidate = (tuple(t for t in tokens if t != token) if present
                     else tuple(tokens) + (token,))
        if not candidate:
            return Command("map.object.property.remove", scope,
                           {"key": BEHAVIORS})
        try:
            text = behavior_registry.format_list(candidate)
        except PyoneerError as error:
            # `format_list` is strict on purpose and refuses a duplicate. It
            # is reachable here only from an already-broken list, where every
            # row is deliberately left editable.
            on_error(str(error))
            return None
        return Command("map.object.property.set", scope,
                       {"key": BEHAVIORS, "value": text})
    return emit


# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------

def _parameters(scope: Scope, tokens: Sequence[str],
                table: Mapping[str, BehaviorSpec], raw: Mapping[str, Any],
                on_error: Callable[[str], None]) -> Section:
    """The union of the declared parameters of the TICKED tokens, and nothing else.

    Nothing else, because a parameter offered for a behavior the object does
    not carry is a property nothing reads: `read_requests` already WARNS about
    exactly that, and this repo has lost 39 authored tiles to a silently
    ignored property name. So the offer follows the list, and unticking a
    behavior withdraws its parameters.
    """
    section = Section("Parameters", note=_PARAM_NOTE)
    declared: dict[str, list[tuple[str, BehaviorParam]]] = {}
    for token in dict.fromkeys(tokens):
        spec = table.get(token)
        if spec is None:
            continue
        for param in spec.params:
            declared.setdefault(param.key, []).append((spec.name, param))

    for key, entries in declared.items():
        owner_names = [name for name, _ in entries]
        param = entries[0][1]
        present = param.property_name in raw
        value, problem = _current(param, raw.get(param.property_name))
        label = param.label + ("" if present else "   (default)")
        if param.required and not present:
            label += "   ·   REQUIRED"
        section.fields.append(Field(
            key, label,
            "choice" if param.choices else param.type, value,
            doc=_param_doc(param, owner_names, problem),
            choices=param.choices,
            emit=_param_emitter(scope, param, on_error),
            removable=present,
            remove=(lambda name: lambda _v: Command(
                "map.object.property.remove", scope, {"key": name}))(
                    param.property_name)))

    shared = sorted(k for k, e in declared.items() if len(e) > 1)
    if shared:
        # One property, N readers. `resolve_params` looks the property up per
        # SPEC, so `pyoneer_param_verb` set for `attack_action` is also read by
        # `interact_action` -- the three action behaviors declare identical
        # keys with different defaults, and that is not visible anywhere else.
        section.note += (
            "\n\nShared by more than one ticked behavior, so one property "
            "feeds them all: " + ", ".join(shared) + ". Each declares its own "
            "default, and the override here replaces every one of them.")
    if not declared:
        section.note += ("\n\nThe ticked behaviors declare no parameters." if
                         tokens else "\n\nTick a behavior to see what it reads.")

    orphans = _orphans(scope, tokens, table, raw)
    section.fields.extend(orphans)
    if orphans:
        section.note += (
            "\n\nBelow: properties spelled like a parameter that no ticked "
            "behavior consumes. The engine warns about these at load and then "
            "ignores them -- authored content that did nothing.")
    return section


def _current(param: BehaviorParam, raw: Any) -> tuple[Any, str]:
    """(what to show in the editor, what is wrong with the file), never raises.

    `BehaviorParam.coerce` RAISES where `Capability.coerce` falls back, and
    that difference is deliberate and documented: a `gravity` of `'9o'`
    quietly becoming 900 is the plausible-wrong-value failure this codebase
    refuses. So the panel cannot show "what the reader will make of it" the
    way the layer inspector does -- there is nothing the reader will make of
    it. It offers the DEFAULT as an editable legal value and names the file's
    actual contents in the doc, so the row is repairable rather than merely
    red.
    """
    if raw is None:
        return param.default, ""
    try:
        return param.coerce(raw), ""
    except PyoneerError as error:
        return param.default, str(error)


def _param_doc(param: BehaviorParam, owners: Sequence[str],
               problem: str) -> str:
    parts = [param.doc,
             f"{param.type} · default {param.default!r} · "
             f"source {param.source} · read by {', '.join(owners)}",
             f"stored as {param.property_name}"]
    if param.source == "actors":
        parts.append("`source=actors` means an actors row may supply it -- but "
                     "nothing in scripts/ reads data/project/, so today it "
                     "resolves from the property above or from the default.")
    if problem:
        parts.append("THE FILE SAYS SOMETHING THE ENGINE REFUSES: " + problem)
    return "\n".join(p for p in parts if p)


def _param_emitter(scope: Scope, param: BehaviorParam,
                   on_error: Callable[[str], None]):
    """Editing one parameter, through the ordinary property verb.

    The value is `coerce`d first, so what reaches the tmx file is what the
    engine will read back: an `int` widened to `float` where the parameter
    declares one, and a boolean handed to an int parameter REFUSED rather than
    stored as 1 (in Python `True` is an int, which is the whole reason that
    guard exists).
    """
    def emit(value: Any) -> Command | None:
        try:
            checked = param.coerce(value, "behavior parameter")
        except PyoneerError as error:
            on_error(str(error))
            return None
        return Command("map.object.property.set", scope,
                       {"key": param.property_name, "value": checked})
    return emit


def _orphans(scope: Scope, tokens: Sequence[str],
             table: Mapping[str, BehaviorSpec],
             raw: Mapping[str, Any]) -> list[Field]:
    """`pyoneer_param_*` properties no ticked behavior declares.

    They must be visible SOMEWHERE. This panel takes the whole vocabulary out
    of the Inspector's generic Properties section (`strip_vocabulary`), so a
    parameter that vanished from both would be an authored property with no
    surface at all -- which is worse than the raw text box this panel replaces.
    """
    claimed: set[str] = set()
    for token in tokens:
        spec = table.get(token)
        if spec is not None:
            claimed.update(spec.param_keys)
    fields: list[Field] = []
    for key in sorted(raw):
        if not key.startswith(PARAM_PREFIX) or key[len(PARAM_PREFIX):] in claimed:
            continue
        fields.append(Field(
            key, key[len(PARAM_PREFIX):] + "   ·   consumed by nothing",
            "str", raw[key],
            doc=f"{key} is authored on this object and no ticked behavior "
                f"declares {key[len(PARAM_PREFIX):]!r}. The engine warns and "
                f"ignores it. Either tick the behavior that reads it, or "
                f"remove it.",
            removable=True,
            remove=(lambda name: lambda _v: Command(
                "map.object.property.remove", scope, {"key": name}))(key)))
    return fields


# --------------------------------------------------------------------------
# The state axes
# --------------------------------------------------------------------------

def _axes(tokens: Sequence[str],
          table: Mapping[str, BehaviorSpec]) -> Section:
    """Which axes of the shared `BodyState` this composition writes, and by whom.

    Read-only: an axis is not authored, it is a consequence of the list. The
    section exists so the refusal above is legible -- "both write
    `state.phase` at order 20" means nothing to an author who has never been
    shown that `state.phase` is a thing an entity has.
    """
    section = Section("State axes", note=_AXES_NOTE)
    known = list(BodyState().axes)
    writers: dict[str, list[BehaviorSpec]] = {}
    for token in dict.fromkeys(tokens):
        spec = table.get(token)
        if spec is None:
            continue
        for written in spec.writes:
            if written.startswith(STATE_PREFIX):
                writers.setdefault(written[len(STATE_PREFIX):], []).append(spec)

    for axis in known:
        if axis not in writers:
            continue
        entries = writers[axis]
        section.fields.append(Field(
            axis, axis, "str",
            ", ".join(f"{s.name} (order {s.order})" for s in entries),
            doc=_AXIS_DOC.get(axis, "")))

    strays = sorted(set(writers) - set(known))
    if strays:
        section.note += (
            "\n\nDECLARED AND NOT AN AXIS: " + ", ".join(strays) +
            ". A behavior declaring an axis BodyState does not have writes a "
            "field nobody reads, and `__slots__` makes that an AttributeError "
            "at the write rather than a silent one.")
    silent = [a for a in known if a not in writers]
    if silent:
        section.note += ("\n\nNothing in this list writes: " +
                         ", ".join(silent) + ".")
    return section


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------

def _problems(tokens: Sequence[str], table: Mapping[str, BehaviorSpec],
              raw: Mapping[str, Any],
              standing: Sequence[str]) -> Section | None:
    """What the engine would say at load, said here instead. None when clean.

    Note-only, deliberately: there is nothing to edit in a refusal, and a
    Field with no emitter renders as a value with a label, which reads as a
    setting. The whole message goes in the note, where `InspectionView`
    renders it as a wrapped, visible QLabel rather than a tooltip.
    """
    lines = list(standing)
    for param in _declared_params(tokens, table):
        value = raw.get(param.property_name)
        if value is None:
            if param.required:
                lines.append(
                    f"{param.property_name} is required by a ticked behavior "
                    f"and neither this object nor an actors row supplies it; "
                    f"the object will refuse to spawn.")
            continue
        _current_value, problem = _current(param, value)
        if problem:
            lines.append(problem)
    if not lines:
        return None
    return Section(
        "Refused at load",
        note=("The engine would refuse this object. Fixing it here is "
              "cheaper than finding it as a map that will not open:\n\n• "
              + "\n\n• ".join(lines)))


def _declared_params(tokens: Sequence[str],
                     table: Mapping[str, BehaviorSpec]) -> Iterable[BehaviorParam]:
    seen: set[str] = set()
    for token in dict.fromkeys(tokens):
        spec = table.get(token)
        if spec is None:
            continue
        for param in spec.params:
            if param.key not in seen:
                seen.add(param.key)
                yield param


# --------------------------------------------------------------------------
# Folding into the Inspector
# --------------------------------------------------------------------------

def strip_vocabulary(inspection: Inspection) -> Inspection:
    """Take the behavior vocabulary out of a generic Properties section.

    The Inspector renders every custom property as an untyped text box. For
    `pyoneer_behaviors` that is the worst authoring surface in the editor --
    no completion, no types, and no refusal, so a conflicting list typed there
    would bypass every check this module performs and land in the file. Two
    doors onto one property where one of them validates is the same thing as
    no validation.

    Matches the Properties section the way `InspectionView` already does, by
    title and object scope (fields.py, where the "+ property" button is added
    under exactly that test). Mutates in place and returns the same object,
    because `describe` builds a fresh Inspection per call and there is nothing
    to preserve.
    """
    if inspection.scope.kind != "object":
        return inspection
    for section in inspection.sections:
        if section.title != "Properties":
            continue
        removed = [f for f in section.fields if is_vocabulary(f.key)]
        if not removed:
            continue
        section.fields = [f for f in section.fields
                          if not is_vocabulary(f.key)]
        section.note += (
            f"   {BEHAVIORS} and {PARAM_PREFIX}* are edited in the Behaviors "
            f"panel, which offers the registered tokens, refuses a conflict "
            f"before it reaches the file, and types each parameter.")
    return inspection


__all__ = ["STATE_PREFIX", "describe_behaviors", "is_vocabulary", "object_at",
           "read_tokens", "refusals", "strip_vocabulary", "unknown_axes"]
