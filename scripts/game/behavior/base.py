"""What a behavior IS: the contract, the declaration, and the per-frame drive.

WHY A BEHAVIOR IS NOT A GameComponent
-------------------------------------
`GameComponent` is the widget machinery -- bounds, anchor, viewport, a
`callbacks` dict, `bind_sync_listener`, `send_event_advanced`. An entity
wants none of it. `GameEntity` derives `PyoneerGameObject` and is driven by a
plain method call from `GameScene.core_frame_update`, not by the event bus,
so composing behavior onto an entity needs no event-system change at all --
which is the whole reason this file can exist without touching the rule that
says the event system does not get restructured.

A behavior therefore binds NO listeners and consumes NO events. It is called,
it is not dispatched to. That is not a limitation being worked around, it is
the property that makes it safe: consumption in this engine is not
type-gated, so one stray `event.handle()` inside a fan-out silences every
sibling for the rest of the frame. A behavior that can never reach the bus
can never do that. `BehaviorSpec.binds` exists to DECLARE the exception if
one is ever written, and `describe_all` prints it in the same sentence as the
behavior's name, so the exception is loud rather than discovered.

THE THREE-METHOD LIFECYCLE
--------------------------
    attach(entity)          once, when the behavior joins the entity
    update(entity, event)   once per frame, in declared order
    detach(entity)          once, when it leaves (or the entity is disposed)

`update` is abstract and the other two are not, because a behavior that does
nothing per frame is not a behavior -- it is a field assignment, and it
should be one.

There is no `prepare`. Deliberately: `GameScene.begin` calls
`core_lifecycle_prepare` a SECOND time on every bound object after `main.py`
has already run the full prepare triple, so anything that allocated in
prepare would allocate twice. `attach` runs exactly once, from
`EntityBehaviors.attach`, and is the place to allocate.

ORDER IS DECLARED, NEVER INCIDENTAL
-----------------------------------
Two behaviors on one entity run in `spec.order` order, low first. Attach
order breaks a tie -- but only when the tie is harmless, and this module
decides what harmless means rather than hoping: if two behaviors share an
`order` AND their declared `writes` sets intersect, attaching the second
RAISES. That is the exact failure the composition model has to refuse, since
two behaviors both writing `transform.position` with one silently winning is
indistinguishable from a physics bug for as long as it takes to find.

WHAT A BEHAVIOR MUST NOT ASSUME
-------------------------------
  * `event.data["delta"]` is milliseconds divided by 60, NOT seconds
    (`main.py`'s frame loop). A number taken from a genre table documented in
    pixels/second is ~16.7x wrong here in a way that still looks like it
    works.
  * `InputActionManager.held()` is an unguarded dict index. Polling a verb
    that is absent from `config/inputs.json` raises KeyError from inside
    `core_frame_update` and kills the frame for every sibling in that scene
    bucket. Adding the behavior and adding the binding are ONE change.
  * `GameEntity.move_direction` silently moves zero for a direction string it
    does not know, and `GameAnimationHandler.start` RAISES for a sequence
    name it does not know. The two failure modes are opposite; a behavior
    that swaps one vocabulary has to swap the other with it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Mapping, Optional

from scripts.core import layer_profile
from scripts.core.errors import PyoneerConfigError, PyoneerError
from scripts.core.event_types import GameEventType
from scripts.core.log import trace_lifecycle

# ---------------------------------------------------------------------------
# The vocabulary
#
# Every one of these is PREFIX + something, and PREFIX is IMPORTED rather than
# retyped. pytmx raises and makes the whole map unloadable if a custom
# property shadows one of its own attribute names, so the prefix is not a
# style choice, and two hand-kept copies of it would drift silently -- a
# property written under one spelling and read under another simply does
# nothing. `tools/check_behavior.py` asserts this package contains no literal
# copy of the prefix string.
#
# SPELLING: the tree is genuinely split between the American and British
# forms of this word -- counted at HEAD, neither is a clear majority, and the
# docstrings and the author's prose lean the other way from the directories.
# `pyoneer_behaviors` is a FILE FORMAT string: once one .tmx carries it,
# changing the spelling means touching maps. So it is settled here, once, and
# settled towards the form the tree already has PATHS in --
# `scripts/core/ui/widget/behavior/` is a real directory and
# `tools/check_imports.py` already names it -- because a path is the one
# spelling that cannot be fixed with a search and replace. Every module in
# this package uses that form and nothing else, and the check enforces it.
# ---------------------------------------------------------------------------

PREFIX: str = layer_profile.PREFIX

BEHAVIORS: str = PREFIX + "behaviors"
"""The tmx object property that lists which behaviors an object composes.

A comma-separated list of registry tokens, e.g. `topdown_move,tile_collision`.
This is the declaration site: the map file is the whole truth, so an object
plays the same way whether or not the editor has ever opened the map.
"""

ACTOR: str = PREFIX + "actor"
"""The tmx object property naming which actors-table row supplies parameters.

Optional. Absent means "this object has no actor row", and every
`source="actors"` parameter then falls to its declared default unless the
object overrides it. NOTE that nothing in `scripts/` reads `data/project/`
today -- there is no engine-side table reader -- so the row has to be handed
in by whoever loaded it. This module never opens a file.
"""

PARAM_PREFIX: str = PREFIX + "param_"
"""Prefix for a per-object parameter override, e.g. `pyoneer_param_gravity`.

The suffix is the parameter key, which is also the actors-table COLUMN name.
A behavior does not get a private alias for a column: `air_control` is
`air_control`, and the behavior declares that it consumes it.
"""

KNOWN: tuple[str, ...] = (BEHAVIORS, ACTOR)
"""Every fixed property name this vocabulary defines.

`PARAM_PREFIX` is deliberately not in here -- it is a prefix, not a name, and
the set of valid suffixes is whatever the attached behaviors declare.
"""

TOKEN = re.compile(r"^[a-z][a-z0-9_]*$")
"""What a behavior token may look like: snake_case, starting with a letter.

Same stability rule the genre packs already give table row ids -- stable once
referenced, never renamed. A token renamed six weeks later silently disarms
every object carrying the old one, which is why `resolve` raises on an
unknown token instead of skipping it.
"""

PARAM_TYPES: dict[str, type] = {"int": int, "float": float,
                                "str": str, "bool": bool}
"""The declarable parameter types, matching what a tmx property can carry."""

PARAM_SOURCES: tuple[str, ...] = ("object", "actors")
"""Where a parameter's value may come from, and therefore where it is read.

    "object"  per-instance only: `pyoneer_param_<key>`, then the default.
              An actors row carrying the key is IGNORED and warns, because a
              value written where nothing can read it is authored content
              that did nothing.
    "actors"  `pyoneer_param_<key>` first, then the actors row, then the
              default -- most specific wins, the same shape as `resolve_depth`.
"""

STATUSES: tuple[str, ...] = ("live", "authoring-only", "needs-host")
"""Whether anything in the engine actually runs this behavior.

`authoring-only` is not a shameful state, it is an honest one. This repo has
shipped authoring ahead of runtime three times (`pyoneer_passability`, map
events, `.blitmap`) and every one of them wrote the caveat into the generated
surface rather than letting a reader assume.

`needs-host` is the third honest state, and it is NOT the same as either. The
behavior runs, and runs correctly -- but it requires something no part of the
ENGINE assigns, so it does nothing until the GAME provides it. `action_relay`
is the case: it calls `entity.action_sink`, and a sink is by definition the
game's. Such a behavior is excluded from the generated "a complete, legal
list" column, because that column is read as a recommendation and recommending
one silently does nothing -- `requires` is REPORTED, never enforced, so there
is no crash to reveal the mistake.
"""


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BehaviorParam:
    """One value a behavior consumes, declared so nothing has to read source.

    Shaped like `editor.core.layers.Capability` on purpose -- the editor
    already renders a layer's capabilities generically from that shape, so an
    inspector for behaviors is the same function with a different tuple. It is
    NOT that class: `Capability` lives under `editor/` and the engine may
    never import it, and the two disagree on the one thing that matters.
    `Capability.coerce` falls back to the default for a nonsense value,
    because a layer with a broken capability should still render. A behavior
    parameter RAISES, because a `gravity` of `'9o'` quietly becoming 900 is
    the plausible-wrong-value failure this codebase refuses.
    """

    key: str
    label: str
    type: str
    default: Any
    doc: str
    choices: tuple[Any, ...] = ()
    source: str = "actors"
    required: bool = False

    def __post_init__(self) -> None:
        if not TOKEN.match(self.key):
            raise PyoneerConfigError(
                "behavior parameter key %r is not snake_case; it is also an "
                "actors-table column name and a tmx property suffix, so it "
                "must match %s" % (self.key, TOKEN.pattern))
        if self.type not in PARAM_TYPES:
            raise PyoneerConfigError(
                "behavior parameter %r declares type %r; known types are %s"
                % (self.key, self.type, ", ".join(sorted(PARAM_TYPES))))
        if self.source not in PARAM_SOURCES:
            raise PyoneerConfigError(
                "behavior parameter %r declares source %r; known sources are %s"
                % (self.key, self.source, ", ".join(PARAM_SOURCES)))

    @property
    def property_name(self) -> str:
        """The tmx object property that overrides this parameter."""
        return PARAM_PREFIX + self.key

    def coerce(self, value: Any, where: str = "") -> Any:
        """Bring an authored value to the declared type, or raise saying why.

        `bool` is tested before `int` in both directions, because in Python
        `True` IS an int: without the guard a `gravity` property typed bool
        resolves to 1 and nothing complains. An `int` widens to `float`
        because Tiled writes `900` for a float-typed property and losing that
        would make every whole-number float an authoring error.
        """
        want = PARAM_TYPES[self.type]
        blame = ("%s: " % where) if where else ""
        if isinstance(value, bool) and want is not bool:
            raise PyoneerConfigError(
                "%s%s wants %s and got the boolean %r; in Python True is an "
                "int, so this would otherwise have resolved to 1"
                % (blame, self.property_name, self.type, value))
        if want is float and isinstance(value, int):
            value = float(value)
        if not isinstance(value, want):
            raise PyoneerConfigError(
                "%s%s wants %s and got %r (%s). In Tiled, set the property's "
                "type; an untyped property arrives as a string."
                % (blame, self.property_name, self.type, value,
                   type(value).__name__))
        if self.choices and value not in self.choices:
            raise PyoneerConfigError(
                "%s%s is %r, which is not one of %s"
                % (blame, self.property_name, value,
                   ", ".join(repr(c) for c in self.choices)))
        return value


@dataclass(frozen=True)
class BehaviorSpec:
    """Everything about a behavior that is true without constructing one.

    This is the registry's record, the editor's inspector source and the
    generated document's source, all one object -- so the document cannot
    describe a behavior the engine does not bind, and the inspector cannot
    offer a parameter the behavior does not read.

    `hooks` is deliberately NOT a field. It is derived from the factory class,
    so it cannot lie about which of the three lifecycle methods a behavior
    actually implements.
    """

    name: str
    summary: str
    factory: Callable[..., "EntityBehavior"]
    params: tuple[BehaviorParam, ...] = ()
    binds: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    order: int = 50
    genres: tuple[str, ...] = ()
    status: str = "live"
    example: Optional[str] = None

    def __post_init__(self) -> None:
        if not TOKEN.match(self.name):
            raise PyoneerConfigError(
                "behavior name %r is not a legal token; it is written into "
                ".tmx files and must match %s" % (self.name, TOKEN.pattern))
        if not callable(self.factory):
            raise PyoneerConfigError(
                "behavior %r declares a factory that is not callable (%r)"
                % (self.name, self.factory))
        if isinstance(self.order, bool) or not isinstance(self.order, int):
            raise PyoneerConfigError(
                "behavior %r declares order=%r; order sorts the per-frame run "
                "and must be an int" % (self.name, self.order))
        if self.status not in STATUSES:
            raise PyoneerConfigError(
                "behavior %r declares status %r; known statuses are %s"
                % (self.name, self.status, ", ".join(STATUSES)))
        if self.name in self.conflicts:
            raise PyoneerConfigError(
                "behavior %r lists itself in conflicts; a duplicate token is "
                "already refused by validate_list" % (self.name,))
        seen: set[str] = set()
        for param in self.params:
            if param.key in seen:
                raise PyoneerConfigError(
                    "behavior %r declares parameter %r twice; one key is one "
                    "property and one actors column" % (self.name, param.key))
            seen.add(param.key)
        for event_name in self.binds:
            if not hasattr(GameEventType, event_name):
                raise PyoneerConfigError(
                    "behavior %r says it binds %r, which is not a "
                    "GameEventType member" % (self.name, event_name))

    @property
    def hooks(self) -> tuple[str, ...]:
        """Which lifecycle methods this behavior actually implements.

        Read off the class, never declared, so it is incapable of being
        stale. `update` is abstract on the base, so every concrete behavior
        appears here with at least that -- the informative part is whether
        `attach` and `detach` show up, because those are the ones a reader
        would otherwise have to open the file to learn.

        Empty for a factory that is a plain function rather than a class:
        there is nothing to read, and guessing would be worse than silence.
        """
        target = self.factory
        if not (isinstance(target, type) and issubclass(target, EntityBehavior)):
            return ()
        return tuple(name for name in ("attach", "update", "detach")
                     if getattr(target, name) is not getattr(EntityBehavior, name))

    def param(self, key: str) -> BehaviorParam | None:
        """The declared parameter for `key`, or None."""
        for candidate in self.params:
            if candidate.key == key:
                return candidate
        return None

    @property
    def param_keys(self) -> tuple[str, ...]:
        return tuple(p.key for p in self.params)


@dataclass(frozen=True)
class BehaviorRequest:
    """One behavior an object asked for, with its parameters already resolved.

    Produced by reading a map; consumed by `build`. It is a record and not a
    behavior for the same reason `SpawnedEntity` is a record and not a bound
    entity: reading a map should be drivable without a display, a scene or an
    entity in hand, and a reader that constructed things would not be.

    `where` names the .tmx object that asked, so a failure four frames later
    can still say which `<object>` produced it.
    """

    spec: BehaviorSpec
    values: Mapping[str, Any]
    where: str = ""


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------

class EntityBehavior:
    """A small object attached to an entity and updated once per frame.

    Not an ABC by inheritance from `abc.ABC`: `GameEntity` is already an ABC
    with two abstract methods and the entity hierarchy is confusing enough.
    `update` raises `NotImplementedError` instead, which fails at the first
    frame rather than at construction -- an intentional trade, because the
    thing a reader needs to see is a stack trace naming the behavior, and
    `Can't instantiate abstract class` names only the class.

    Subclasses take their resolved parameters as CONSTRUCTOR KEYWORDS, named
    exactly for the keys the spec declares. `build` calls
    `spec.factory(**values)`, so the declaration and the signature are checked
    against each other by Python itself the first time one is built.
    """

    enabled: bool = True
    """Whether the drive calls this behavior at all.

    A class attribute, so a subclass that never calls `super().__init__()`
    still has one. Assigning `behavior.enabled = False` shadows it per
    instance. This is the equivalent of the `state.can_move` flag that keeps
    five of the six demo players inert -- a gate that suppresses the WORK
    without unpicking the composition.
    """

    spec: Optional[BehaviorSpec] = None
    """The registry record this behavior was built from.

    Stamped on the instance by `registry.build`, and on the class by
    `registry.register` for the benefit of hand-constructed instances. It is
    required by `EntityBehaviors.attach`, because a behavior with no spec has
    no declared `order` -- and an undeclared order is exactly the incidental
    ordering this design exists to end.
    """

    @property
    def name(self) -> str:
        return self.spec.name if self.spec is not None else type(self).__name__

    def attach(self, entity: Any) -> None:
        """Called once, when this behavior joins `entity`. Allocate here."""

    def update(self, entity: Any, event: Any) -> None:
        """Called once per frame, in declared order. `event.data['delta']`."""
        raise NotImplementedError(
            "%s must implement update(entity, event); a behavior that does "
            "nothing per frame should be a field assignment instead"
            % type(self).__name__)

    def detach(self, entity: Any) -> None:
        """Called once, when this behavior leaves `entity`. Release here."""

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return "<%s %s order=%s>" % (
            type(self).__name__, self.name,
            self.spec.order if self.spec else "?")


# ---------------------------------------------------------------------------
# The composition, and the per-frame drive
# ---------------------------------------------------------------------------

def _dotted(target: Any, path: str) -> Any:
    """Follow `a.b.c` from `target`, or None if any step is missing."""
    current = target
    for part in path.split("."):
        current = getattr(current, part, None)
        if current is None:
            return None
    return current


class EntityBehaviors:
    """The ordered set of behaviors composed onto one entity.

    One of these lives on `GameEntity` as `self.behaviors`, and
    `GameEntity.core_frame_update` -- which is `pass` today -- calls
    `self.behaviors.update(event)`. Both halves are two lines, and while the
    set is empty the call is frame-neutral, which is what makes landing this
    on every entity in the shipped tree a no-op the smoke baseline agrees
    with.

    It owns its entity rather than being handed one per call. That removes a
    whole failure mode -- a set attached to entity A and driven with entity B
    would move the wrong thing and raise nothing -- and it makes the
    integration one attribute instead of a loop the entity has to get right.
    The reference cycle entity -> behaviors -> entity is ordinary and
    collectable.
    """

    def __init__(self, owner: Any):
        self._owner = owner
        self._sequence: int = 0
        self._entries: list[tuple[int, EntityBehavior]] = []
        self._ordered: tuple[EntityBehavior, ...] = ()

    # -- inspection --------------------------------------------------------

    @property
    def owner(self) -> Any:
        return self._owner

    @property
    def ordered(self) -> tuple[EntityBehavior, ...]:
        """The behaviors in the order `update` will run them, low order first.

        A tuple, and rebuilt on mutation rather than sorted per frame: this is
        read once per entity per frame and sorting a three-element list 60
        times a second for every entity on the map is a cost with no reader.
        """
        return self._ordered

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(b.name for b in self._ordered)

    def get(self, name: str) -> EntityBehavior | None:
        for behavior in self._ordered:
            if behavior.name == name:
                return behavior
        return None

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[EntityBehavior]:
        return iter(self._ordered)

    def __contains__(self, item: Any) -> bool:
        if isinstance(item, str):
            return self.get(item) is not None
        return any(b is item for b in self._ordered)

    # -- composition -------------------------------------------------------

    def attach(self, behavior: EntityBehavior) -> EntityBehavior:
        """Compose `behavior` onto the owner, or raise saying why it cannot be.

        Three refusals, and each one is a bug that is otherwise invisible:

          no spec        an undeclared order is an incidental order
          same token     two of one behavior is a typo in the token list
          conflicts      the pair declared they must not be combined
          same order,
          same writes    both write the attribute and one silently wins

        The last is the one worth the code. Two behaviors at the same order
        with DISJOINT writes are fine and stay fine -- their relative order
        genuinely does not matter, and refusing them would make `order` a
        registration number instead of a statement.
        """
        if not isinstance(behavior, EntityBehavior):
            raise PyoneerConfigError(
                "cannot attach %r to %s: behaviors must derive EntityBehavior"
                % (behavior, type(self._owner).__name__))
        spec = behavior.spec
        if spec is None:
            raise PyoneerConfigError(
                "cannot attach %s to %s: it carries no BehaviorSpec, so it "
                "declares no order, and two behaviors with no declared order "
                "run in whatever sequence they happened to be attached in. "
                "Register it (scripts/game/behavior/registry.py) or build it "
                "through registry.build()." % (type(behavior).__name__,
                                               type(self._owner).__name__))
        for _, existing in self._entries:
            other = existing.spec
            if other.name == spec.name:
                raise PyoneerConfigError(
                    "%s already has a %r behavior; attaching a second one is "
                    "a duplicated token, not a stack"
                    % (type(self._owner).__name__, spec.name))
            if spec.name in other.conflicts or other.name in spec.conflicts:
                raise PyoneerConfigError(
                    "behaviors %r and %r declare that they conflict and must "
                    "not be composed onto the same entity (%s)"
                    % (other.name, spec.name, type(self._owner).__name__))
            shared = tuple(sorted(set(other.writes) & set(spec.writes)))
            if other.order == spec.order and shared:
                raise PyoneerConfigError(
                    "behaviors %r and %r both declare order=%d and both write "
                    "%s, so which one wins would depend on attach order. Give "
                    "one of them a different order."
                    % (other.name, spec.name, spec.order, ", ".join(shared)))
        self._entries.append((self._sequence, behavior))
        self._sequence += 1
        self._resort()
        # The entry goes in BEFORE the hook runs, so an `attach` that inspects
        # its siblings sees the finished set -- but a hook that RAISES must not
        # leave a half-attached behavior behind. `player_input.attach` is
        # designed to raise on an unbound verb, so this is the expected path,
        # not a defensive one: without the rollback the refused behavior stays
        # in `_entries` and is driven every frame by an entity whose
        # composition was rejected.
        try:
            behavior.attach(self._owner)
        except BaseException:
            self._entries = [e for e in self._entries if e[1] is not behavior]
            self._resort()
            raise
        trace_lifecycle("attached behavior %s to %s",
                        spec.name, type(self._owner).__name__)
        return behavior

    def attach_all(self, behaviors: Iterable[EntityBehavior]) -> tuple[EntityBehavior, ...]:
        """Attach a sequence, in the sequence's order. Ordering is by spec."""
        return tuple(self.attach(b) for b in behaviors)

    def detach(self, target: "EntityBehavior | str") -> EntityBehavior | None:
        """Remove one behavior by object or token, calling its `detach`.

        Returns the behavior that left, or None if there was nothing to
        remove. Silent on a miss rather than raising: `detach("x")` on an
        entity that never had `x` is a request that is already satisfied.
        """
        for index, (_, behavior) in enumerate(self._entries):
            hit = (behavior is target if not isinstance(target, str)
                   else behavior.name == target)
            if not hit:
                continue
            del self._entries[index]
            self._resort()
            behavior.detach(self._owner)
            return behavior
        return None

    def detach_all(self) -> None:
        """Remove every behavior, in reverse run order.

        Reverse because teardown mirrors setup: whatever ran last and may be
        holding something the earlier ones produced lets go of it first.
        """
        for behavior in reversed(self._ordered):
            self.detach(behavior)

    # -- the drive ---------------------------------------------------------

    def update(self, event: Any) -> None:
        """Run every enabled behavior once, in declared order.

        Iterates a SNAPSHOT. A behavior that detaches itself -- or attaches
        another -- from inside its own `update` is a normal thing to want (a
        one-shot spawn effect, a state machine swapping its own movement), and
        mutating the list being iterated would either skip its neighbour or
        raise. The snapshot means this frame runs the set as it was when the
        frame began, and the change lands on the next one.

        Failures are NOT swallowed. A behavior that raises takes the frame
        down, loudly, with the behavior and the entity named -- because an
        entity that silently stopped moving is the single hardest bug in this
        engine to trace back to its cause.
        """
        for behavior in self._ordered:
            if not behavior.enabled:
                continue
            try:
                behavior.update(self._owner, event)
            except PyoneerError as error:
                raise error.push_frame(behavior=behavior.name,
                                       entity=type(self._owner).__name__)

    # -- reporting ---------------------------------------------------------

    def missing_requirements(self) -> tuple[tuple[str, str], ...]:
        """(behavior name, requirement) for every declared need the owner lacks.

        Reported, never enforced, and the distinction is deliberate. A
        `GamePlayer` built with `input_=None` legitimately has
        `action_manager is None` -- that is how five of the six demo players
        stay inert -- so refusing to attach would break a shipped
        configuration to prevent a problem that has not happened. The editor
        and the generated document can show this; the drive does not read it.

        Dotted requirements (`transform.position`) are followed step by step.
        """
        missing: list[tuple[str, str]] = []
        for behavior in self._ordered:
            for requirement in behavior.spec.requires:
                if _dotted(self._owner, requirement) is None:
                    missing.append((behavior.name, requirement))
        return tuple(missing)

    def describe(self) -> str:
        """One line per behavior, in run order. For traces and for errors."""
        if not self._ordered:
            return "<no behaviors>"
        return "; ".join("%d %s writes=%s"
                         % (b.spec.order, b.name, ",".join(b.spec.writes) or "-")
                         for b in self._ordered)

    # -- internals ---------------------------------------------------------

    def _resort(self) -> None:
        """Rebuild the run order: declared order first, attach order to break ties.

        `sorted` is stable, so passing the attach sequence explicitly is
        belt-and-braces -- but only explicitly. A key of `spec.order` alone
        would leave the tie to whatever `list.sort` happened to do with the
        entries, which is the definition of incidental.
        """
        self._ordered = tuple(behavior for _, behavior in
                              sorted(self._entries,
                                     key=lambda entry: (entry[1].spec.order,
                                                        entry[0])))
