"""Which token means which behavior, and how a map declares a list of them.

WHY THIS IS A HAND-WRITTEN TABLE
--------------------------------
The same reason `scripts/core/spawn.py` is one, and the argument is quoted
here rather than re-derived because it was already paid for: a scan cannot
tell an abstract class from one it simply has not seen yet, so the failure
lands at spawn time on the author's map instead of here, in a file a human
reads. No scanning, no importlib, no decorator that fires on import order. An
explicit table is a list of claims that are true when written and falsifiable
by `tools/check_behavior.py` afterwards.

WHERE COMPOSITION IS DECLARED, AND WHY IT IS THE MAP
----------------------------------------------------
A `pyoneer_behaviors` property on the tmx OBJECT. Four sites were possible
and three of them cannot do the job:

  the spawn registry      keyed by class, so every object of a type gets the
                          same list -- which is the "player is a more
                          specific class" shape this design exists to end,
                          wearing a dict as a disguise
  an actors-table column  differs per ROW, and the object -> row link is
                          `pyoneer_actor`, i.e. a per-object property -- the
                          tmx property in disguise. (The engine does read
                          `data/project/` now, via
                          `scripts/loaders/table_file.py`; that supplies
                          PARAMETERS per row, which is step 2 below, and is a
                          different question from which behaviors compose.)
  a genre-pack default    `editor/genres/` is under `editor/`, and `scripts/`
                          may never import `editor/`. A default only the pack
                          knows is a default the engine cannot apply, so the
                          same map would play differently depending on
                          whether the editor had ever opened it

The genre pack keeps its default -- but as one the editor MATERIALISES into
the object when the object is added, so the .tmx stays the whole truth and
this module never needs to know a pack exists. Two objects of one class on
one map can then differ, which is the property none of the other three has.

PARAMETERS NAME THE COLUMN THEY READ
------------------------------------
A behavior does not get a private alias. It declares that it consumes
`air_control`, which is an actors-table column name, and resolution runs
most-specific-first exactly like `resolve_depth`:

    1. `pyoneer_param_air_control` on the object   this object, this map
    2. the actors row's `air_control` column       this actor, everywhere
    3. `BehaviorParam.default`                     nobody said anything

Step 2 needs a row, and THIS MODULE NEVER LOADS ONE -- that has not changed
and is the point: the caller that has a row hands it in. What has changed is
that a caller now does. `scripts/loaders/table_file.py` reads
`data/project/tables/*.json`, `actor_row` turns an object's `pyoneer_actor`
into the row, and both spawn routes pass it as `actors_row`. `None` still
means step 2 is skipped and step 3 answers, which is what an object naming no
row resolves to -- every object on every map shipped today. A `required=True`
parameter with nothing at either level raises, naming the object, the
behavior and the key.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from scripts.core.errors import (PyoneerAssetMissingError, PyoneerConfigError,
                                 warn_content)
from scripts.core.log import trace_assets
from scripts.game.behavior.base import (ACTOR, BEHAVIORS, KNOWN, PARAM_PREFIX,
                                        PREFIX, TOKEN, BehaviorParam,
                                        BehaviorRequest, BehaviorSpec,
                                        EntityBehavior)
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

    Re-registering a name replaces it, deliberately and for the reason
    `spawn.register` gives: a check that swaps a behavior in and puts the
    original back is the only sanctioned way to drive this path without the
    concrete behaviors, and refusing the second call would make that
    impossible rather than safe.

    Registering also STAMPS the spec onto the factory class when the class
    does not already carry one, so an instance built by hand -- in a check, in
    `main.py` -- still knows its own order. The first registration wins the
    class stamp; an alias (two tokens, one class) leaves the second token's
    instances to `build`, which stamps per instance and is always right.
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

    Never falls back. A token that resolved to nothing would silently disarm
    every object carrying it -- the exact failure a rename six weeks later
    produces -- and unlike a missing behavior it looks like it worked.

    The error carries the registry because "topdown_mvoe is not a behavior"
    without the list is a message the author has to go read source to act on.
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
# The token list: lenient read, strict write
#
# The same pair `editor/core/map_events.py` uses for its argument lists, and
# for the same reason -- a hand-edited .tmx should not be able to make the
# reader raise on whitespace, and the writer should never emit something the
# reader has to be lenient about.
# ---------------------------------------------------------------------------

def parse_list(value: Any) -> tuple[str, ...]:
    """Split an authored `pyoneer_behaviors` value into tokens. Never raises.

    Accepts None, a string, or an iterable of strings. Splits on commas and
    on whitespace, strips, lowercases, and drops empties -- so
    `" TopDown_Move , tile_collision "` and `"topdown_move,tile_collision"`
    are the same list, which matters because Tiled's property editor is a
    free-text box.

    Duplicates are KEPT. This function's job is to say what the file says;
    `validate_list` is the one that judges it, and a duplicate that vanished
    here would be a typo nothing could report.
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

    Comma-separated, no spaces, in the given order -- order is authored data
    only for humans reading the file, since the run order comes from
    `spec.order` and not from this list.
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
    Does NOT reorder: run order is `spec.order`'s business and lives in
    `EntityBehaviors`, in one place, so that two orderings cannot disagree.
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
    default -- and `source` decides whether the middle step is consulted at
    all. A `source="object"` parameter is per-instance by declaration, so an
    actors row carrying that column is a value nothing can read, and this
    warns rather than ignoring it: authored content that did nothing is the
    failure mode this engine reports.
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
    -- for the same reason `spawn_objects` binds nothing: a map read that
    needed an entity in hand would not be drivable without a display, a scene
    and a full boot.

    A `pyoneer_param_*` property that no listed behavior declares WARNS. It is
    a typo by definition -- the parameter keys are generated into
    BEHAVIORS.md, so there is no such thing as an undocumented one -- and this
    repo has already lost 39 authored tiles to a silently-ignored name.
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

    `spec.factory(**values)` -- so a parameter the spec declares and the
    constructor does not accept is a `TypeError` naming the keyword, from
    Python itself, the first time one is built. That is why the resolved
    values are keywords and not a dict argument: a dict would let the
    declaration and the signature drift apart forever.
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

Step 2 needs a row, and **nothing in `scripts/` reads `data/project/`** -- the
engine has no table reader yet. Until one exists, every parameter resolves
from step 1 or step 3, and a `required` parameter with neither raises.

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
               two behaviors write nothing in common
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

Not a docstring scrape: a scrape would silently produce an empty row the day
someone reflows a comment. `describe_all` cross-checks these keys against
`BodyState().axes` and says so in the document when the two disagree, so an
axis added without a sentence is visible in the generated file rather than
absent from it.
"""


def _state_axes() -> list[str]:
    """The `state.<axis>` vocabulary the writes column above is spelled in.

    Generated from `BodyState` itself. Without this table the writes column
    names `state.support` and `state.facing` to a reader who has no way to
    learn what either means, which is the breadcrumb this whole document
    exists to lay.
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


def describe_all(registry: Mapping[str, BehaviorSpec] | None = None) -> str:
    """Render BEHAVIORS.md from the same table the engine binds from.

    One source, so the document cannot describe a behavior the engine does not
    have, and cannot omit a parameter the editor will offer. Written to disk
    by whoever ships the docs bundle; this function only returns the text.
    """
    table = BEHAVIOR_REGISTRY if registry is None else registry
    lines = [_PREAMBLE.format(behaviors=BEHAVIORS, param=PARAM_PREFIX,
                              actor=ACTOR)]
    lines.extend(_state_axes())
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

    lines.append("| token | order | status | writes | summary |")
    lines.append("| --- | --- | --- | --- | --- |")
    for spec in sorted(table.values(), key=lambda s: (s.order, s.name)):
        lines.append("| `%s` | %d | %s | %s | %s |"
                     % (spec.name, spec.order, spec.status,
                        ", ".join("`%s`" % w for w in spec.writes) or "--",
                        spec.summary))
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
# One entry per concrete behavior, written by hand. No scanning, no importlib,
# no import-order-sensitive decorator: this is a list of claims that are true
# when written and falsifiable by `tools/check_behavior.py` and
# `tools/check_movement.py` afterwards.
#
# The specs themselves live BESIDE their classes, in the module that
# implements them, so a parameter and the constructor keyword it fills can be
# read in one screen. This is the only place that says which token means
# which spec, and the imports sit at the bottom because the modules they name
# import `base` -- putting them at the top would make this module import
# itself through the package.
#
# `describe_all()` picks up a new entry with no edit here or in BEHAVIORS.md.
# ---------------------------------------------------------------------------

from scripts.game.behavior.input import PLAYER_INPUT           # noqa: E402
from scripts.game.behavior.movement import (ANIMATION_DRIVE,   # noqa: E402
                                            PLATFORMER_MOVE, TOPDOWN_MOVE)
# Three tokens, ONE factory class -- the alias case `register` documents above.
# The first of them stamps the class; every instance `build` produces is
# stamped per instance, which is what keys each action's slot in the record.
from scripts.game.behavior.action import (ACTION_RELAY,        # noqa: E402
                                          ACTION_SPECS)
from scripts.game.behavior.lifecycle import LIFECYCLE_MARK      # noqa: E402

register_all((PLAYER_INPUT, TOPDOWN_MOVE, PLATFORMER_MOVE, ANIMATION_DRIVE))
register_all(ACTION_SPECS + (ACTION_RELAY, LIFECYCLE_MARK))

__all__ = [
    "ACTOR", "BEHAVIORS", "BEHAVIOR_REGISTRY", "KNOWN", "PARAM_PREFIX",
    "PREFIX", "BehaviorParam", "BehaviorRequest", "BehaviorSpec",
    "build", "describe_all", "format_list", "parse_list", "read_requests",
    "register", "register_all", "resolve", "resolve_params", "validate_list",
]
