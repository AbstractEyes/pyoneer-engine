"""Which token means which behavior, and how a map declares a list of them.

The table at the bottom is hand-written: no scanning, no importlib, no
import-order-sensitive decorator. A scan cannot tell an abstract class from
one it has simply not seen yet, so its failures land at spawn time on the
author's map rather than here, in a file a human reads.

WHERE COMPOSITION IS DECLARED
-----------------------------
On a `pyoneer_behaviors` property on the tmx OBJECT, so that two objects of
one class on one map can differ. Not on the spawn registry (keyed by class),
not in an actors-table column (keyed by row, reached through a per-object
property anyway), and not in a genre pack (`editor/genres/` is under
`editor/`, which `scripts/` may never import, so the same map would play
differently depending on whether the editor had ever opened it). A pack still
declares a default list, but the editor MATERIALISES it into the object when
the object is added, so the .tmx stays the whole truth and this module never
needs to know a pack exists.

PARAMETERS NAME THE COLUMN THEY READ
------------------------------------
A behavior declares that it consumes `air_control`, which is also the
actors-table column name -- there is no private alias. Resolution runs
most-specific-first, the same shape as `resolve_depth`:

    1. `pyoneer_param_air_control` on the object   this object, this map
    2. the actors row's `air_control` column       this actor, everywhere
    3. `BehaviorParam.default`                     nobody said anything

THIS MODULE NEVER LOADS A ROW: the caller that has one hands it in as
`actors_row`. `scripts/loaders/table_file.py` reads
`data/project/tables/*.json`, `actor_row` turns an object's `pyoneer_actor`
into the row, and both spawn routes pass it. `None` skips step 2 and step 3
answers. A `required=True` parameter with nothing at either level raises,
naming the object, the behavior and the key.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from scripts.core.errors import (PyoneerAssetMissingError, PyoneerConfigError,
                                 warn_content)
from scripts.core.log import trace_assets
from scripts.game.behavior.base import (ACTOR, BEHAVIORS, KNOWN, ORDER_RULE,
                                        PARAM_PREFIX, PREFIX, TOKEN,
                                        BehaviorParam, BehaviorRequest,
                                        BehaviorSpec, EntityBehavior,
                                        category_label)
from scripts.game.behavior.state import (FACING_DEFAULT, LIVES, PHASES,
                                         SUPPORTS, BodyState)

BEHAVIOR_REGISTRY: dict[str, BehaviorSpec] = {}
"""Token -> the spec that describes and builds it. Populated at the bottom."""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(spec: BehaviorSpec,
             registry: MutableMapping[str, BehaviorSpec] | None = None) -> BehaviorSpec:
    """Bind one token to its spec.

    Re-registering a name replaces it, so a check can swap a behavior in and
    put the original back.

    Registering also STAMPS the spec onto the factory class when the class
    does not already carry one, so an instance built by hand still knows its
    own order. The first registration wins the class stamp; for an alias (two
    tokens, one class) the second token's instances are stamped per instance
    by `build`.
    """
    target = BEHAVIOR_REGISTRY if registry is None else registry
    target[spec.name] = spec
    factory = spec.factory
    if (isinstance(factory, type) and issubclass(factory, EntityBehavior)
            and factory.__dict__.get("spec") is None):
        factory.spec = spec
    return spec


def register_all(specs: Iterable[BehaviorSpec],
                 registry: MutableMapping[str, BehaviorSpec] | None = None) -> None:
    """Register a sequence of specs. Mirrors `spawn.register_all`."""
    for spec in specs:
        register(spec, registry)


def resolve(name: str,
            registry: Mapping[str, BehaviorSpec] | None = None) -> BehaviorSpec:
    """The spec for `name`, or raise naming it and listing the whole registry.

    Never falls back: a token that resolved to nothing would silently disarm
    every object carrying it, and would look exactly like the behavior
    working. The error carries the registry so a typo can be fixed without
    reading source.
    """
    table = BEHAVIOR_REGISTRY if registry is None else registry
    spec = table.get(name)
    if spec is None:
        raise PyoneerAssetMissingError(
            "entity behavior", name, available=table.keys(),
            hint="register it in scripts/game/behavior/registry.py, or fix "
                 "the object's %s property in Tiled" % BEHAVIORS,
        )
    return spec


# ---------------------------------------------------------------------------
# The two derived views: when a behavior runs, and what family it belongs to
#
# Both are functions of the table and nothing else. Neither reads a mapping,
# because there is no mapping: `BehaviorSpec.order` is authored beside the
# class and `BehaviorSpec.category` is the module the class is written in. A
# caller that wants to GROUP or to SEQUENCE calls one of these rather than
# re-deriving it, so `BEHAVIORS.md` and the editor's Behaviors panel cannot
# group a behavior two different ways.
# ---------------------------------------------------------------------------

def order_steps(registry: Mapping[str, BehaviorSpec] | None = None
                ) -> tuple[int, ...]:
    """The distinct `order` values in the table, low first: the frame's steps.

    A behavior's step number is its order's position here, one-based, and the
    step count is the length. Two behaviors that share an `order` share a
    STEP, which is the only honest rendering of them: their relative order is
    decided by the sequence they are listed in on the object and by nothing
    else, so numbering them 2 and 3 would invent a fact that the file does
    not contain.
    """
    table = BEHAVIOR_REGISTRY if registry is None else registry
    return tuple(sorted({spec.order for spec in table.values()}))


def step_of(spec: BehaviorSpec,
            registry: Mapping[str, BehaviorSpec] | None = None
            ) -> tuple[int, int]:
    """(which step this behavior runs in, how many steps the frame has).

    Raises rather than reporting step 0 for a spec whose order is absent from
    the table -- that means the spec was not registered, and a sequence
    number invented for something outside the sequence is exactly the
    plausible-wrong answer this repository refuses.
    """
    steps = order_steps(registry)
    if spec.order not in steps:
        raise PyoneerConfigError(
            "behavior %r declares order=%d, which is not one of the orders in "
            "this registry (%s); it has no step because it is not in the "
            "sequence" % (spec.name, spec.order,
                          ", ".join(str(o) for o in steps) or "<empty>"))
    return steps.index(spec.order) + 1, len(steps)


def run_order(names: Iterable[str],
              registry: Mapping[str, BehaviorSpec] | None = None
              ) -> tuple[BehaviorSpec, ...]:
    """The specs for `names`, in the order one frame will call them.

    The same sort key `EntityBehaviors._resort` uses -- declared `order`
    first, position in the sequence to break a tie -- applied to a list of
    TOKENS rather than to attached instances, so the editor can show an
    author what the frame will do before anything has been built. Restating
    that key is a second home for it, so `tools/check_behavior_ui.py`
    asserts the two agree by attaching real behaviors to a real
    `EntityBehaviors` and comparing; if they ever diverge, that goes red
    rather than a panel quietly showing the wrong sequence.

    Raises on an unknown token, like everything else that resolves one.
    """
    specs = [resolve(name, registry) for name in names]
    return tuple(spec for _, spec in
                 sorted(enumerate(specs),
                        key=lambda entry: (entry[1].order, entry[0])))


def categories(registry: Mapping[str, BehaviorSpec] | None = None
               ) -> tuple[tuple[str, tuple[BehaviorSpec, ...]], ...]:
    """Every registered behavior grouped by `BehaviorSpec.category`.

    Exactly one group per behavior and no empty group, both structurally: a
    group exists only because a behavior created it, and each behavior is
    appended once. That is the property `tools/check_behavior_ui.py` asserts
    against a substituted registry -- a behavior whose class lives in a
    module nothing has ever heard of gets its own group with no edit here.

    Groups come in RUN ORDER, keyed on the lowest order any of their members
    declares, so the families read top to bottom the way the frame runs them.
    A category still INTERLEAVES -- `action` holds both order 15 and order
    90 -- which is why grouping never replaces the sequence and the panel
    shows both.
    """
    table = BEHAVIOR_REGISTRY if registry is None else registry
    grouped: dict[str, list[BehaviorSpec]] = {}
    for spec in table.values():
        grouped.setdefault(spec.category, []).append(spec)
    return tuple(
        (name, tuple(sorted(specs, key=lambda s: (s.order, s.name))))
        for name, specs in sorted(
            grouped.items(),
            key=lambda item: (min(s.order for s in item[1]), item[0])))


# ---------------------------------------------------------------------------
# The token list: lenient read, strict write
#
# A hand-edited .tmx must not make the reader raise on whitespace, and the
# writer must never emit something the reader has to be lenient about.
# ---------------------------------------------------------------------------

def parse_list(value: Any) -> tuple[str, ...]:
    """Split an authored `pyoneer_behaviors` value into tokens. Never raises.

    Accepts None, a string, or an iterable of strings. Splits on commas and
    on whitespace, strips, lowercases, and drops empties, because Tiled's
    property editor is a free-text box.

    Duplicates are KEPT: this function says what the file says, and
    `validate_list` is the one that judges it.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        raw: Sequence[str] = value.replace(",", " ").split()
    elif isinstance(value, Iterable):
        raw = [str(item) for item in value]
    else:
        raw = [str(value)]
    tokens: list[str] = []
    for item in raw:
        for part in str(item).replace(",", " ").split():
            cleaned = part.strip().lower()
            if cleaned:
                tokens.append(cleaned)
    return tuple(tokens)


def format_list(names: Iterable[str]) -> str:
    """The canonical stored form of a token list. Strict: raises on nonsense.

    Comma-separated, no spaces, in the given order. The stored order is for
    humans only -- run order comes from `spec.order`, not from this list.
    """
    tokens = tuple(names)
    seen: set[str] = set()
    for token in tokens:
        if not isinstance(token, str) or not TOKEN.match(token):
            raise PyoneerConfigError(
                "%r is not a legal behavior token; tokens are written into "
                ".tmx files and must match %s" % (token, TOKEN.pattern))
        if token in seen:
            raise PyoneerConfigError(
                "behavior token %r appears twice; one entity holds at most "
                "one of each behavior" % (token,))
        seen.add(token)
    return ",".join(tokens)


def validate_list(value: Any,
                  registry: Mapping[str, BehaviorSpec] | None = None,
                  where: str = "") -> tuple[str, ...]:
    """Parse and judge a token list, returning it as authored.

    Raises on an unknown token, on a duplicate, and on a declared conflict.
    Does NOT reorder: run order belongs to `spec.order` and is applied in
    `EntityBehaviors`, so two orderings cannot disagree.
    """
    tokens = parse_list(value)
    blame = (" (%s)" % where) if where else ""
    seen: set[str] = set()
    specs: list[BehaviorSpec] = []
    for token in tokens:
        if token in seen:
            raise PyoneerConfigError(
                "behavior token %r appears twice in %s%s; one entity holds at "
                "most one of each behavior" % (token, BEHAVIORS, blame))
        seen.add(token)
        specs.append(resolve(token, registry))
    for index, spec in enumerate(specs):
        for other in specs[index + 1:]:
            if other.name in spec.conflicts or spec.name in other.conflicts:
                raise PyoneerConfigError(
                    "behaviors %r and %r declare that they conflict, and %s%s "
                    "lists both" % (spec.name, other.name, BEHAVIORS, blame))
    return tokens


# ---------------------------------------------------------------------------
# Reading a map object
# ---------------------------------------------------------------------------

def resolve_params(spec: BehaviorSpec,
                   properties: Mapping[str, Any] | None = None,
                   actors_row: Mapping[str, Any] | None = None,
                   where: str = "") -> dict[str, Any]:
    """The constructor keywords for one behavior on one object.

    Most specific first -- object property, then actors row, then the declared
    default -- with `source` deciding whether the middle step is consulted at
    all. A `source="object"` parameter is per-instance by declaration, so an
    actors row carrying that column WARNS rather than being ignored silently.
    """
    properties = properties or {}
    values: dict[str, Any] = {}
    blame = where or "object"
    for param in spec.params:
        raw = properties.get(param.property_name)
        if raw is not None:
            values[param.key] = param.coerce(
                raw, "%s behavior %r" % (blame, spec.name))
            continue
        if actors_row is not None and param.key in actors_row:
            if param.source == "object":
                warn_content(
                    "%s behavior %r declares %r as a per-object parameter, so "
                    "the actors row's %r column was not read. Set %s on the "
                    "object, or declare the parameter source='actors'."
                    % (blame, spec.name, param.key, param.key,
                       param.property_name))
            else:
                values[param.key] = param.coerce(
                    actors_row[param.key],
                    "%s behavior %r (actors row)" % (blame, spec.name))
                continue
        if param.required:
            raise PyoneerConfigError(
                "%s asks for behavior %r, which requires %r, and neither the "
                "object (%s) nor an actors row supplies it"
                % (blame, spec.name, param.key, param.property_name))
        values[param.key] = param.default
    return values


def read_requests(properties: Mapping[str, Any] | None = None,
                  actors_row: Mapping[str, Any] | None = None,
                  *,
                  registry: Mapping[str, BehaviorSpec] | None = None,
                  where: str = "") -> tuple[BehaviorRequest, ...]:
    """Everything one tmx object declares about its behaviors.

    Reads the object's own properties: `pyoneer_behaviors` for the list and
    `pyoneer_param_*` for the overrides. Constructs NOTHING -- that is `build`
    -- so a map read stays drivable without a display, a scene or a full boot.

    A `pyoneer_param_*` property that no listed behavior declares WARNS: every
    legal key is generated into BEHAVIORS.md, so an unclaimed one is a typo,
    and a silently-ignored authored name is how this repo once lost 39 tiles.
    """
    properties = properties or {}
    tokens = validate_list(properties.get(BEHAVIORS), registry, where)
    requests: list[BehaviorRequest] = []
    claimed: set[str] = set()
    for token in tokens:
        spec = resolve(token, registry)
        claimed.update(spec.param_keys)
        requests.append(BehaviorRequest(
            spec=spec,
            values=resolve_params(spec, properties, actors_row, where),
            where=where))
    orphans = sorted(key[len(PARAM_PREFIX):] for key in properties
                     if isinstance(key, str) and key.startswith(PARAM_PREFIX)
                     and key[len(PARAM_PREFIX):] not in claimed)
    if orphans:
        warn_content(
            "%s carries %s%s, which no behavior in its %s list consumes, so "
            "%s ignored. Behaviors present: %s."
            % (where or "a tmx object",
               PARAM_PREFIX, (", " + PARAM_PREFIX).join(orphans), BEHAVIORS,
               "they were" if len(orphans) > 1 else "it was",
               ", ".join(tokens) or "<none>"))
    return tuple(requests)


def build(requests: Sequence[BehaviorRequest]) -> list[EntityBehavior]:
    """Construct one behavior per request. Nothing is attached.

    `spec.factory(**values)`, so a parameter the spec declares and the
    constructor does not accept is a `TypeError` naming the keyword the first
    time one is built. Passing the values as a dict instead would let the
    declaration and the signature drift apart unnoticed.
    """
    behaviors: list[EntityBehavior] = []
    for request in requests:
        behavior = request.spec.factory(**dict(request.values))
        if not isinstance(behavior, EntityBehavior):
            raise PyoneerConfigError(
                "behavior %r built a %s, which does not derive EntityBehavior"
                % (request.spec.name, type(behavior).__name__))
        behavior.spec = request.spec
        behaviors.append(behavior)
    trace_assets("built %d behavior(s) for %s",
                 len(behaviors), requests[0].where if requests else "<none>")
    return behaviors


# ---------------------------------------------------------------------------
# The generated document
# ---------------------------------------------------------------------------

_PREAMBLE = """\
# Behaviors -- composing an entity out of data

**This file is generated.** `scripts/game/behavior/registry.py` holds the
table; `describe_all()` prints it. Edit the specs, not this file.

## What a behavior is

A small object attached to a `GameEntity` and updated once per frame, with
three methods and no event-bus presence:

    attach(entity)          once, when it joins the entity
    update(entity, event)   once per frame, in declared order
    detach(entity)          once, when it leaves

A behavior is CALLED, never dispatched to. `GameEntity` derives
`PyoneerGameObject`, is not a `GameComponent`, and is driven by a plain method
call from `GameScene.core_frame_update` -- so composing behavior onto one needs
no change to the event system at all. Do not make an entity a `GameComponent`
to get this; the machinery it drags in (bounds, anchor, viewport, a callbacks
dict) is machinery an entity does not want, and a behavior on the bus could
call `event.handle()` and silence every sibling for the rest of the frame.

## How an entity declares one

On the tmx OBJECT, not on the class and not in a table:

    <property name="{behaviors}" value="topdown_move,tile_collision"/>
    <property name="{param}move_speed" type="int" value="20"/>
    <property name="{actor}" value="hero"/>

The `pyoneer_` prefix is load-bearing: pytmx RAISES and makes the whole map
unloadable if a custom property shadows one of its own attribute names.

The list is comma-separated, snake_case, order-insensitive -- the run order
comes from each behavior's declared `order`, not from the list. The map file
is the whole truth: a genre pack may supply a default list, but the editor
materialises it into the object when the object is added, so an object plays
the same way whether or not the editor has ever opened the map.

## Where the parameters come from

Most specific first, the same shape as `resolve_depth`:

    1. `{param}<key>` on the object      this object, this map
    2. the `<key>` column of the actors row named by `{actor}`
    3. the parameter's declared default

Step 2 needs a row, and **the engine reads one.**
`scripts/loaders/table_file.py` loads `data/project/tables/*.json`, `actor_row`
turns an object's `{actor}` into that row, and both spawn routes -- the map
spawn and `SceneManager.spawn` -- hand it in. `LayerRenderer.tables` is the
one slot it lives in, assigned in `main.py` beside `spawn_defaults`.

Missing stays free, and only missing: no `tables/` directory, no `{actor}` on
the object, or a row that omits the column all fall through to step 3.
Everything else RAISES -- an unreadable or self-contradictory table file, and
a `{actor}` naming a row that is not there, which raises naming the object.
A parameter that quietly took its default because the row id was misspelled
would look exactly like a parameter nobody authored, which is the shape this
whole chain exists to refuse. A `required` parameter with nothing at any of
the three levels raises too.

## The per-frame call chain

    main.py frame loop
      -> SceneManager.update            camera.update() runs BEFORE this
        -> GameScene.core_frame_update  fan-out over every bound object
          -> GameEntity.core_frame_update
            -> EntityBehaviors.update(event)
              -> behavior.update(entity, event)   in `order` order, low first

Note the camera: `SceneManager` updates it *before* the scene's frame update,
so it sees the previous frame's position. Moving a position write to a
different point in the frame changes what the camera sees even when the
arithmetic is identical -- and `tools/smoke.py` will report the drift.

## Four traps that have each cost a session

1. **`event.data["delta"]` is milliseconds / 60, not seconds.** The genre
   tables document movement in pixels per second. A number used raw is about
   16.7x wrong in a way that still looks like it works.
2. **`InputActionManager.held()` is an unguarded dict index.** Polling a verb
   absent from `config/inputs.json` raises `KeyError` inside
   `core_frame_update` and kills the frame for every sibling in that bucket.
   Adding a behavior and adding its binding are ONE change.
3. **`move_direction` silently moves zero for a direction it does not know**
   -- there is no `else` branch -- while **`GameAnimationHandler.start` RAISES**
   for a sequence name it does not know. Opposite failures from one typo, so a
   behavior that swaps a direction vocabulary must swap the animation naming
   with it.
4. **`GameEntity.__init__` accepts a `transform` keyword and discards it.**
   Anything that builds an entity still has to `moveto()` afterwards.

## What the collision vocabulary cannot express

Taken from `scripts/core/collision_runtime.py`, not restated from memory: a
mask is per-CELL and tested at ONE anchor point rather than a box; blocking is
symmetric, so a one-way platform is not expressible; and an anchor outside the
field is ungated rather than blocked.

`GameEntity.collision_field` IS assigned in production: `LayerRenderer` bakes
the map's passability once at bind and hands it to every entity it binds, by
either route. A map that declares no passability layer bakes `None`, which
means ungated -- so a body on such a map still moves freely, and that is the
shipped demo's state rather than a missing wire. The measured integration
table below is the authority on this; this paragraph is prose and can rot.

## Adding a behavior

1. Write the class in `scripts/game/behavior/`, deriving `EntityBehavior`.
   Take the resolved parameters as constructor keywords named exactly for the
   keys the spec declares.
2. Register it at the bottom of `scripts/game/behavior/registry.py`:

       register(BehaviorSpec(
           name="topdown_move",
           summary="Four-way axis-aligned movement polled from input verbs.",
           factory=GameTopDownMoveBehavior,
           params=(BehaviorParam("move_speed", "move speed", "int", 16,
                                 "Pixels per delta unit.", source="actors"),),
           writes=("transform.position",),
           requires=("action_manager",),
           order=20,
           genres=("topdown_rpg",)))

3. Add a check, and add it to `tools/check_all.py`'s roster.
4. `describe_all()` picks the new entry up with no further edit.

Two invariants that are not negotiable: `scripts/` may never import
`editor/`, and the event system does not get restructured to accommodate a
behavior. A behavior that needs the bus is a behavior that needs a different
design.

## Reading the tables below

    order      lower runs first within a frame; a tie is legal only when the
               two behaviors write nothing in common. It is a position, not
               an id -- see "Run order" above
    frame step which of the frame's ordered steps it runs in, and how many
               there are. Two behaviors at one order share one step
    category   the module the behavior is declared in, derived from the class
               and declared nowhere, so a new behavior needs no entry in any
               table to appear under the right heading
    writes     which entity attributes it mutates -- this is what makes a
               collision between two composed behaviors visible in advance
    requires   what must be present on the entity for it to do anything;
               reported by `EntityBehaviors.missing_requirements()`, never
               enforced, because `input_=None` is a legal configuration
    hooks      derived from the class, not declared, so it cannot be stale
    binds      `GameEventType` members it listens for. Normally empty; a
               non-empty value means this behavior reaches the event bus and
               should be read carefully
    status     whether anything in the engine runs it
"""


_AXIS_DOC: dict[str, str] = {
    "phase": "What the body is doing. CLOSED: %s. A branch reads it, so an "
             "unrecognised value would silently take the idle path."
             % ", ".join("`%s`" % p for p in PHASES),
    "facing": "Which way the body is pointed. OPEN -- any non-empty string, "
              "because isometric wants eight tokens and twin-stick wants an "
              "angle. Defaults to `%s`. It is the `{}` in `walk_{}` and it is "
              "NOT the argument to `move_direction`." % FACING_DEFAULT,
    "support": "Whether something is holding the body up. CLOSED: %s. Written "
               "by `platformer_move`; `entity.grounded` is an alias over it."
               % ", ".join("`%s`" % s for s in SUPPORTS),
    "life": "Whether the body is still part of the world. CLOSED: %s. Written "
            "by `lifecycle_mark` (and by any game code that wants a body "
            "gone); READ by `SceneManager.reap()`, which is what actually "
            "removes it from its scene bucket and its EntityLayer. Marking is "
            "a DECLARATION -- a behavior that unbound its own entity would "
            "make the scene fan-out skip the next sibling."
            % ", ".join("`%s`" % v for v in LIVES),
    "support_grace": "Milliseconds a body that has left its support is still "
                     "treated as supported -- the coyote clock. "
                     "`entity.coyote_left` is an alias over it.",
    "simulated": "Whether the entity is stepped at all. `GamePlayer` returns "
                 "before `super()` when this is false, so the animation clock "
                 "stops too. Per-entity; it is NOT a world pause.",
    "steerable": "Whether the body may be STEERED. Gates the input poll, not "
                 "the simulation -- a side-on body still falls while the "
                 "player is in a menu.",
    "input_bound": "Whether the body is wired to a human's input at all. Set "
                   "once from the wiring, so a narrative gate can tell "
                   "restoring input from granting it.",
    "enabled_inputs": "Whether input is currently permitted. The authored "
                      "gate. Read by `player_input` WITH `steerable` and by "
                      "the action behaviors WITHOUT it -- a body frozen for a "
                      "cutscene may not walk and must still press continue.",
    "sprinting": "A mirror of `MoveIntent.sprint`. Not an axis and has no "
                 "production reader; the real home is the intent.",
}
"""One sentence per axis, keyed by the field name `BodyState` actually has.

Written out rather than scraped from docstrings, which would produce an empty
row the day someone reflows a comment. `describe_all` cross-checks these keys
against `BodyState().axes`, so an axis with no sentence -- or a sentence with
no axis -- shows up in the generated file instead of vanishing from it.
"""


def _state_axes() -> list[str]:
    """The `state.<axis>` vocabulary the writes column above is spelled in.

    Generated from `BodyState` itself, so the document explains every axis the
    writes column can name.
    """
    lines = ["", "## The state axes", "",
             "`BodyState` (`scripts/game/behavior/state.py`) is what a body "
             "IS, beside `MoveIntent` (what it was ASKED to do) and "
             "`ActionIntent` (what it DID). A behavior declares the axes it "
             "writes as `state.<axis>`, and two behaviors at one `order` "
             "writing one axis are REFUSED at attach -- which is the whole "
             "reason the declaration is spelled per axis rather than as "
             "`state`.", "",
             "| axis | meaning |", "| --- | --- |"]
    known = BodyState().axes
    for axis in sorted(known):
        lines.append("| `state.%s` | %s |"
                     % (axis, _AXIS_DOC.get(axis, "**undocumented** -- add a "
                                                  "sentence to `_AXIS_DOC` in "
                                                  "registry.py")))
    strays = sorted(set(_AXIS_DOC) - set(known))
    if strays:
        lines.append("")
        lines.append("> **%s described here and not on the record.** The "
                     "sentence outlived its axis." % ", ".join(strays))
    return lines


def _run_order_and_categories(table: Mapping[str, BehaviorSpec]) -> list[str]:
    """The two derived views, rendered from the helpers the editor also calls.

    Generated rather than written into the preamble: the preamble is prose
    living inside this generator, so it can lie while the file still matches
    it byte for byte, and it has done exactly that twice. Every line below is
    read off `table`.
    """
    if not table:
        return []
    steps = order_steps(table)
    lines = ["", "## Run order", "", ORDER_RULE, "",
             "This registry's frame has %d step%s, and every behavior at one "
             "step runs before every behavior at the next:"
             % (len(steps), "" if len(steps) == 1 else "s"), ""]
    for index, order in enumerate(steps, 1):
        sharing = sorted(spec.name for spec in table.values()
                         if spec.order == order)
        lines.append("%d. **order %d** -- %s%s"
                     % (index, order, ", ".join("`%s`" % n for n in sharing),
                        " (one step, so the object's own list decides which "
                        "of these goes first)" if len(sharing) > 1 else ""))
    lines.extend([
        "", "## The categories", "",
        "A behavior's category is the module it is declared in, and nothing "
        "else. There is no token-to-category table in this repository, so a "
        "behavior registered tomorrow appears under its own module here and "
        "in the editor's Behaviors panel -- which groups its checklist by "
        "exactly this -- with no edit to either. A category interleaves with "
        "the run order above rather than replacing it.", ""])
    for name, specs in categories(table):
        modules = sorted({spec.declared_in for spec in specs})
        lines.append("- **%s** -- %s -- %d behavior%s"
                     % (category_label(name),
                        ", ".join("`%s`" % module for module in modules),
                        len(specs), "" if len(specs) == 1 else "s"))
    return lines


def describe_all(registry: Mapping[str, BehaviorSpec] | None = None) -> str:
    """Render BEHAVIORS.md from the same table the engine binds from.

    One source, so the document cannot describe a behavior the engine does not
    have, nor omit a parameter the editor will offer. Returns the text; the
    caller writes it to disk.
    """
    table = BEHAVIOR_REGISTRY if registry is None else registry
    lines = [_PREAMBLE.format(behaviors=BEHAVIORS, param=PARAM_PREFIX,
                              actor=ACTOR)]
    lines.extend(_state_axes())
    lines.extend(_run_order_and_categories(table))
    lines.append("")
    lines.append("## The registry")
    lines.append("")
    if not table:
        lines.append(
            "**The registry is empty.** The base, the registry and the "
            "per-frame drive exist; no concrete behavior is registered yet, "
            "so every token raises. That is the honest state and not a "
            "generation failure -- an entity with an empty behavior list "
            "behaves exactly as it did before this system landed, which is "
            "why landing it moved no frame.")
        return "\n".join(lines) + "\n"

    lines.append("| token | order | frame step | category | status | writes "
                 "| summary |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for spec in sorted(table.values(), key=lambda s: (s.order, s.name)):
        lines.append("| `%s` | %d | %d of %d | %s | %s | %s | %s |"
                     % ((spec.name, spec.order) + step_of(spec, table)
                        + (category_label(spec.category), spec.status,
                           ", ".join("`%s`" % w for w in spec.writes) or "--",
                           spec.summary)))
    lines.append("")

    for spec in sorted(table.values(), key=lambda s: (s.order, s.name)):
        lines.append("### `%s`" % spec.name)
        lines.append("")
        lines.append(spec.summary)
        lines.append("")
        if spec.status != "live":
            lines.append("> **Status: %s.** Nothing in the engine runs this "
                         "yet." % spec.status)
            lines.append("")
        lines.append("- **class** `%s`" % getattr(spec.factory, "__name__",
                                                  repr(spec.factory)))
        lines.append("- **order** %d" % spec.order)
        lines.append("- **runs at** step %d of %d" % step_of(spec, table))
        lines.append("- **category** %s (derived from `%s`, declared nowhere)"
                     % (category_label(spec.category), spec.declared_in))
        lines.append("- **hooks** %s" % (", ".join("`%s`" % h for h in spec.hooks)
                                         or "--"))
        lines.append("- **binds** %s" % (", ".join("`%s`" % b for b in spec.binds)
                                         or "nothing (not on the event bus)"))
        lines.append("- **writes** %s" % (", ".join("`%s`" % w for w in spec.writes)
                                          or "--"))
        lines.append("- **requires** %s" % (", ".join("`%s`" % r for r in spec.requires)
                                            or "--"))
        lines.append("- **conflicts with** %s"
                     % (", ".join("`%s`" % c for c in spec.conflicts) or "--"))
        lines.append("- **genres** %s" % (", ".join(spec.genres) or "any"))
        lines.append("")
        if spec.params:
            lines.append("| parameter | type | default | source | required | meaning |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for param in spec.params:
                lines.append("| `%s` | %s | `%r` | %s | %s | %s |"
                             % (param.key, param.type, param.default,
                                param.source, "yes" if param.required else "no",
                                param.doc))
        else:
            lines.append("Takes no parameters.")
        lines.append("")
        if spec.example:
            lines.append("```")
            lines.append(spec.example)
            lines.append("```")
            lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# The table
#
# One entry per concrete behavior, written by hand and checked by
# `tools/check_behavior.py` and `tools/check_movement.py`.
#
# Each spec lives BESIDE its class, so a parameter and the constructor keyword
# it fills read in one screen; this is the only place that says which token
# means which spec. The imports sit at the BOTTOM because the modules they
# name import `base` -- at the top they would make this module import itself
# through the package.
#
# `describe_all()` picks up a new entry with no edit here or in BEHAVIORS.md.
# ---------------------------------------------------------------------------

from scripts.game.behavior.input import PLAYER_INPUT           # noqa: E402
from scripts.game.behavior.movement import (ANIMATION_DRIVE,   # noqa: E402
                                            PLATFORMER_MOVE, TOPDOWN_MOVE)
# Three tokens, ONE factory class -- the alias case `register` describes. The
# first stamps the class; `build` stamps every instance it produces, which is
# what keys each action's slot in the record.
from scripts.game.behavior.action import (ACTION_RELAY,        # noqa: E402
                                          ACTION_SPECS)
from scripts.game.behavior.lifecycle import LIFECYCLE_MARK      # noqa: E402

register_all((PLAYER_INPUT, TOPDOWN_MOVE, PLATFORMER_MOVE, ANIMATION_DRIVE))
register_all(ACTION_SPECS + (ACTION_RELAY, LIFECYCLE_MARK))

__all__ = [
    "ACTOR", "BEHAVIORS", "BEHAVIOR_REGISTRY", "KNOWN", "ORDER_RULE",
    "PARAM_PREFIX", "PREFIX", "BehaviorParam", "BehaviorRequest",
    "BehaviorSpec", "build", "categories", "category_label", "describe_all",
    "format_list", "order_steps", "parse_list", "read_requests", "register",
    "register_all", "resolve", "resolve_params", "run_order", "step_of",
    "validate_list",
]
