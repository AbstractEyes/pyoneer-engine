"""What an entity DID this frame: the action behaviors and their record.

An action is an occurrence, and it is still a CALL rather than an event,
because of one asymmetry in `GameScene`:

    core_frame_update    builds an event INSIDE the per-object loop, so every
                         bound object gets its OWN event
    core_input_receive   passes the SAME event to every bound object, and
                         `bind()` accepts `GameComponent`, so the whole UI
                         tree is in that list

`GameComponent.__send_event` returns immediately on `event.handled` and
consumption is not type-gated, so one `handle()` reached from an entity on
the input path would silence every sibling, widgets included, for the rest of
that pyo-event. So nothing here constructs a `PyoneerEvent` or calls
`handle()`: every spec declares `binds=()`, and `tools/check_action.py`
asserts both that the field is empty AND that this module's source contains
no `handle(` or `send_event`. The payoff is that N behaviors may read one
firing and none of them can stop another.

`action_relay`, at order 90, is the one thing that reaches outward, and it
does so by CALLING `entity.action_sink` -- a plain callable the scene
assigned. A sink that wants a bus event sends it from the scene, on the frame
path where every object has its own event.

A SLOT PER ACTION, NOT ONE SHARED RECORD
----------------------------------------
`ActionIntent` maps the ACTION TOKEN to that action's firing, and a behavior
touches only its own key, so there is no clearing order between four
behaviors in one `order` window to get wrong. It also makes each declared
`writes` literally true (`action_intent.attack_action`), which is what lets
four action behaviors share `order=15`: `EntityBehaviors.attach` refuses two
behaviors at one order whose `writes` intersect, so a shared
`writes=("action_intent",)` could not attach twice. The cooldown clock lives
on the behavior instance for the same reason.

WHAT AN ACTION IS THAT MOVEMENT IS NOT
--------------------------------------
    edge, not hold      `pressed()`, never `held()` -- `held()` here is the
                        machine-gun bug
    an occurrence       a record that exists for one frame, not a value that
                        persists
    rate-limited        `cooldown_ms` and `once`
    gated differently   by `state.enabled_inputs` and NOT by
                        `state.can_move`. A body frozen for a cutscene may
                        not WALK and must still press "continue".
                        `player_input` gates on both; the divergence is
                        asserted in both directions.

`payload` is here and `args` is not: `parse_args`/`format_args` live in
`editor/core/map_events.py`, which `scripts/` may never import. The four
parameter names are taken VERBATIM from that trigger vocabulary, so an action
and the trigger it fires speak one language.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from scripts.core.errors import PyoneerConfigError
from scripts.game.behavior.base import (BehaviorParam, BehaviorSpec,
                                        EntityBehavior)
from scripts.game.behavior.movement import MS_PER_DELTA

SLOT_PREFIX: str = "action_intent."
"""What a `writes` entry for one action looks like: `action_intent.<token>`.

Each spec spells its own out rather than deriving it, so the declaration
reads as data. `tools/check_action.py` proves it by MEASURING which slot the
behavior records into.
"""


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ActionFired:
    """One action, once, on the frame its verb went down.

    Frozen, so a behavior at order 90 cannot alter what a behavior at order
    20 already read.

    `name` is the BEHAVIOR TOKEN (`attack_action`), not the input verb; the
    key the player pressed is `verb`. The two are separate because the verb is
    rebindable data and the token is the stable name a consumer switches on.
    """

    name: str
    verb: str
    payload: str = ""

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        tail = " -> %s" % self.payload if self.payload else ""
        return "<ActionFired %s via %r%s>" % (self.name, self.verb, tail)


class ActionIntent:
    """Which of this entity's actions fired this frame, one slot per action.

    A mapping and not a list, so no shared clear exists to order wrongly.
    Every method takes the action's token, and a behavior only ever names its
    own.

    An allocated slot holding `None` means "this action is composed and did
    not fire"; no slot at all means "this action is not composed".
    """

    __slots__ = ("_fired", "_locked")

    def __init__(self, locked: bool = False):
        object.__setattr__(self, "_fired", {})
        object.__setattr__(self, "_locked", bool(locked))

    # -- the lock ----------------------------------------------------------

    def __setattr__(self, name: str, value: Any) -> None:
        """Refuse every write. `NO_ACTIONS` is the only instance that is locked.

        Every entity composing no action behavior borrows that one object, so
        a single careless write would report the same firing on all of them.
        """
        self._refuse(name)
        object.__setattr__(self, name, value)

    def _refuse(self, what: str) -> None:
        if self._locked:
            raise PyoneerConfigError(
                "NO_ACTIONS is the shared inert action record handed to an "
                "entity that carries no action behavior, and writing %r to it "
                "would report that firing on every such entity. Attach an "
                "action behavior, or allocate your own ActionIntent()."
                % (what,))

    @property
    def locked(self) -> bool:
        return self._locked

    # -- what a behavior does to its own slot ------------------------------

    def clear(self, name: str) -> None:
        """Allocate `name`'s slot and empty it. Called at the top of a poll."""
        self._refuse(name)
        self._fired[name] = None

    def record(self, name: str, fired: ActionFired) -> ActionFired:
        """Record that `name` fired this frame."""
        self._refuse(name)
        if not isinstance(fired, ActionFired):
            raise PyoneerConfigError(
                "action %r recorded %r, which is not an ActionFired; the "
                "record is what every consumer switches on and a stand-in "
                "shaped like it would diverge silently" % (name, fired))
        self._fired[name] = fired
        return fired

    def release(self, name: str) -> None:
        """Forget the slot entirely. Called from `detach`.

        Not `clear`: an empty slot left behind would keep answering "composed,
        did not fire" forever, so `slots` would stop describing what the
        entity carries.
        """
        self._refuse(name)
        self._fired.pop(name, None)

    # -- what a consumer reads ---------------------------------------------

    def fired(self, name: str) -> Optional[ActionFired]:
        """`name`'s firing this frame, or None. Never raises on an unknown name."""
        return self._fired.get(name)

    @property
    def fired_names(self) -> tuple[str, ...]:
        """Every action that fired this frame, SORTED.

        Sorted rather than in slot-allocation order, so two entities carrying
        the same actions report them the same way whatever order their
        behaviors attached in.
        """
        return tuple(sorted(k for k, v in self._fired.items() if v is not None))

    @property
    def records(self) -> tuple[ActionFired, ...]:
        return tuple(self._fired[name] for name in self.fired_names)

    @property
    def slots(self) -> tuple[str, ...]:
        """Every action composed onto this entity, fired or not. Sorted."""
        return tuple(sorted(self._fired))

    def __contains__(self, name: Any) -> bool:
        return self._fired.get(name) is not None

    def __len__(self) -> int:
        return sum(1 for v in self._fired.values() if v is not None)

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return "<ActionIntent %s>" % (",".join(self.fired_names) or "quiet")


NO_ACTIONS = ActionIntent(locked=True)
"""The record an entity that publishes none is read as: nothing fired, ever.

Locked, so one borrower cannot alter what every other borrower sees. It is
what makes "no action behavior" mean quiet rather than crash.
"""


def actions_of(entity: Any) -> ActionIntent:
    """The entity's own action record, or the shared inert one.

    The single reader used by every consumer, so "what happens for an entity
    with no actions" is answered in one place. Mirrors `intent_of`.
    """
    found = getattr(entity, "action_intent", None)
    return found if isinstance(found, ActionIntent) else NO_ACTIONS


def _own_intent(entity: Any) -> ActionIntent:
    """The entity's writable record, allocating one if it has none.

    Never hands back `NO_ACTIONS`: that object is locked and every caller of
    this function is about to write.
    """
    found = getattr(entity, "action_intent", None)
    if isinstance(found, ActionIntent) and not found.locked:
        return found
    fresh = ActionIntent()
    entity.action_intent = fresh
    return fresh


# ---------------------------------------------------------------------------
# The verb audit
# ---------------------------------------------------------------------------

def require_verbs(manager: Any, verbs: Iterable[str], *,
                  behavior: str, entity: str) -> tuple[str, ...]:
    """Prove every named verb is bound, or raise at composition time.

    `InputActionManager.held()`/`pressed()` are `self.actions[name]` --
    unguarded dict indexes. A behavior polling a verb absent from
    `config/inputs.json` raises `KeyError` from inside `core_frame_update`,
    which kills the frame for every sibling in that scene bucket and names
    nothing useful. This turns that into one message naming the verb, the
    behavior and everything that IS bound.

    An EMPTY verb name is skipped rather than refused: "" is the documented
    way to say "this body has no such input".

    A None manager returns quietly, because `input_=None` is a legal
    configuration and an entity spawned before its manager exists is a normal
    boot order.

    Returns the verbs that will actually be polled, so a caller needs no
    second copy of the empty-name filter.
    """
    wanted = tuple(v for v in verbs if v)
    if manager is None:
        return wanted
    bound = getattr(manager, "actions", {})
    for verb in wanted:
        if verb not in bound:
            raise PyoneerConfigError(
                "behavior %r on %s polls the verb %r, which config/inputs.json "
                "does not bind. held()/pressed() are unguarded dict indexes, "
                "so this would have raised KeyError inside core_frame_update "
                "and killed the frame for every entity in the same bucket. "
                "Bound verbs: %s."
                % (behavior, entity, verb,
                   ", ".join(sorted(bound)) or "<none>"))
    return wanted


# ---------------------------------------------------------------------------
# The behaviors
# ---------------------------------------------------------------------------

class GameActionInputBehavior(EntityBehavior):
    """Poll one verb's RISING EDGE and record a firing for one action.

    One instance is one action. Four actions on one entity are four registered
    tokens pointing at this class, because a duplicate token is refused both
    by `EntityBehaviors.attach` and by `registry.format_list`.

    `pressed()` and never `held()` -- the whole difference between an action
    and movement. `held()` here reads as a working feature until someone
    notices the sword swinging sixty times a second.
    """

    def __init__(self,
                 verb: str = "",
                 cooldown_ms: int = 0,
                 once: bool = False,
                 payload: str = ""):
        if isinstance(cooldown_ms, bool) or not isinstance(cooldown_ms, int):
            raise PyoneerConfigError(
                "an action's cooldown_ms must be a whole number of "
                "milliseconds and got %r (%s); in Tiled, set the property's "
                "type" % (cooldown_ms, type(cooldown_ms).__name__))
        if cooldown_ms < 0:
            raise PyoneerConfigError(
                "an action declares cooldown_ms=%d; a negative cooldown would "
                "read as 'already elapsed' on every frame and is indis"
                "tinguishable from 0, so it is refused rather than clamped. "
                "Set pyoneer_param_cooldown_ms to 0 for no limit."
                % (cooldown_ms,))
        self.verb = verb
        self.cooldown_ms = cooldown_ms
        self.once = bool(once)
        self.payload = payload
        self._cooldown_left = 0.0
        self._spent = False

    # -- inspection --------------------------------------------------------

    @property
    def cooldown_left(self) -> float:
        """Milliseconds until this action may fire again. 0.0 when ready."""
        return self._cooldown_left

    @property
    def spent(self) -> bool:
        """True when `once` was declared and the one firing has happened."""
        return self._spent

    @property
    def ready(self) -> bool:
        return not self._spent and self._cooldown_left <= 0.0

    # -- lifecycle ---------------------------------------------------------

    def attach(self, entity: Any) -> None:
        """Prove the verb is bound, then allocate this action's slot.

        The audit runs FIRST: `EntityBehaviors.attach` rolls the entry back
        when a hook raises, and a slot left behind by a refused attach would
        make `slots` report an action the entity does not carry.
        """
        require_verbs(getattr(entity, "action_manager", None), (self.verb,),
                      behavior=self.name, entity=type(entity).__name__)
        _own_intent(entity).clear(self.name)

    def detach(self, entity: Any) -> None:
        """Forget the slot. The cooldown and `once` state stay on the instance.

        Not reset, so a detach/attach cycle cannot re-arm a spent `once` and
        bypass the authored intent.
        """
        found = getattr(entity, "action_intent", None)
        if isinstance(found, ActionIntent) and not found.locked:
            found.release(self.name)

    def update(self, entity: Any, event: Any) -> None:
        if event is None:
            return
        intent = _own_intent(entity)
        # Cleared BEFORE every gate below. Under a gate, an action fired on
        # the frame a cutscene starts would stand in the record for the whole
        # cutscene and every consumer would re-fire on it once per frame.
        intent.clear(self.name)
        if self._cooldown_left > 0.0:
            # The clock is wall time and ticks through every gate, so a menu
            # that pauses input does not also pause a weapon cooldown.
            self._cooldown_left = max(
                0.0, self._cooldown_left - event.data["delta"] * MS_PER_DELTA)
        if not self.verb:
            return
        manager = getattr(entity, "action_manager", None)
        if manager is None:
            return
        state = getattr(entity, "state", None)
        if state is not None and not state.enabled_inputs:
            # `enabled_inputs` and NOT `can_move`: an entity frozen
            # mid-cutscene may not walk and must still press "continue".
            return
        if not self.ready:
            return
        if not manager.pressed(self.verb):
            return
        self._cooldown_left = float(self.cooldown_ms)
        self._spent = self.once
        intent.record(self.name, ActionFired(name=self.name, verb=self.verb,
                                             payload=self.payload))


class GameActionRelayBehavior(EntityBehavior):
    """Hand every firing to `entity.action_sink`, by CALLING it.

    The one behavior that reaches outside the entity, and it reaches by
    calling a plain callable rather than by dispatching.
    `action_sink(entity, fired)` is a normal function; a sink that wants a bus
    event sends it from the scene.

    Runs at order 90 -- after `animation_drive` at 80 -- so a firing may name
    an animation that has already played this frame.

    `SceneManager` assigns the scene's `ActionRouter`
    (`scripts/game/flow/router.py`) to every entity it binds, so this token
    reaches a real sink with no game code; a game that wants its own sink
    assigns one after the bind. The requirement is REPORTED and never
    enforced, so an entity with no sink is quiet rather than broken.
    """

    def update(self, entity: Any, event: Any) -> None:
        # `records` already drops every allocated-but-empty slot, so a quiet
        # frame is an empty loop and needs no guard of its own.
        sink = getattr(entity, "action_sink", None)
        if sink is None:
            return
        for fired in actions_of(entity).records:
            sink(entity, fired)


# ---------------------------------------------------------------------------
# The declarations
#
# Four tokens, one factory class -- the alias case `registry.register`
# describes. The first registration stamps the class; `build` stamps every
# instance, so each token's instance knows its own name, which keys its slot.
#
# All four share `order=15`, between `player_input` (10) and the movement
# bodies (20), so a movement behavior can consume an action on the SAME frame
# it fires -- a dash is an action a body reads. That is legal only because
# their `writes` are disjoint.
# ---------------------------------------------------------------------------

ORDER: int = 15
"""Where an action polls: after the movement intent, before a body reads it."""

RELAY_ORDER: int = 90
"""Where a firing is handed on: after the animator, last of everything."""


def _params(default_verb: str) -> tuple[BehaviorParam, ...]:
    """The four parameters every action takes, with this action's verb default.

    `cooldown_ms`, `once` and `payload` are spelled exactly as the trigger
    vocabulary spells them, so a `use` trigger and the action that fires it
    are one language. All four are `source="object"`, because neither genre
    pack declares an actors column for any of them and
    `tools/check_behavior_docs.py` refuses a `source="actors"` parameter
    naming a column no pack has.
    """
    return (
        BehaviorParam("verb", "input verb", "str", default_verb,
                      "Action name polled with pressed() -- a rising edge. "
                      "Must be bound in config/inputs.json; an unbound one "
                      "raises at attach rather than as a KeyError mid-frame. "
                      "Empty disables this action for this entity.",
                      source="object"),
        BehaviorParam("cooldown_ms", "cooldown (ms)", "int", 0,
                      "Minimum milliseconds between two firings. 0 means no "
                      "limit. The clock ticks through the input gate, so a "
                      "cooldown is wall time and not gameplay time.",
                      source="object"),
        BehaviorParam("once", "fire once", "bool", False,
                      "Disarm after the first firing, for the whole life of "
                      "this behavior. Survives a detach/attach cycle.",
                      source="object"),
        BehaviorParam("payload", "payload key", "str", "",
                      "An opaque key carried on the firing -- a door id, a "
                      "cutscene name, a quest step. Deliberately not "
                      "interpreted: the engine should not need a schema for "
                      "every game built on it.",
                      source="object"),
    )


ATTACK_ACTION = BehaviorSpec(
    name="attack_action",  # #TAG:attack_action
    summary="Fires on the rising edge of the 'attack' verb, with a cooldown. "
            "Records an ActionFired; reaches no event bus.",
    factory=GameActionInputBehavior,
    params=_params("attack"),
    writes=("action_intent.attack_action",),
    requires=("action_manager",),
    order=ORDER,
    example='<property name="pyoneer_behaviors" '
            'value="player_input,topdown_move,attack_action"/>\n'
            '<property name="pyoneer_param_cooldown_ms" type="int" value="400"/>',
)

INTERACT_ACTION = BehaviorSpec(
    name="interact_action",  # #TAG:interact_action
    summary="Fires on the rising edge of the 'action' verb -- talk, use, open. "
            "The explicit interaction a `use` map trigger is waiting for.",
    factory=GameActionInputBehavior,
    params=_params("action"),
    writes=("action_intent.interact_action",),
    requires=("action_manager",),
    order=ORDER,
    example='<property name="pyoneer_behaviors" '
            'value="player_input,topdown_move,interact_action"/>\n'
            '<property name="pyoneer_param_payload" value="door_north"/>',
)

PAUSE_ACTION = BehaviorSpec(
    name="pause_action",  # #TAG:pause_action
    summary="Fires on the rising edge of the 'pause' verb. The entity-side "
            "half of a pause; what it MEANS is the sink's business.",
    factory=GameActionInputBehavior,
    params=_params("pause"),
    writes=("action_intent.pause_action",),
    requires=("action_manager",),
    order=ORDER,
    example='<property name="pyoneer_behaviors" '
            'value="player_input,topdown_move,pause_action"/>',
)

ACTION_RELAY = BehaviorSpec(
    name="action_relay",  # #TAG:action_relay
    summary="Calls entity.action_sink(entity, fired) for every action that "
            "fired this frame. The only behavior that reaches outward, and it "
            "calls rather than dispatches. SceneManager assigns the sink: it "
            "is the scene's ActionRouter (scripts/game/flow/router.py).",
    factory=GameActionRelayBehavior,
    writes=(),
    requires=("action_sink",),
    # WAS "needs-host", and the condition that status describes has been met:
    # `SceneManager` now constructs an `ActionRouter` and assigns it as
    # `entity.action_sink` on BOTH binding routes -- `bind()` for a hand-built
    # entity and `__bind_spawned_entities` for a map-placed one -- exactly as
    # `LayerRenderer.__gate` hands out the collision field. So the engine does
    # assign it, an entity bound into a scene reaches a real sink, and the
    # generated recommended-list column may offer this token.
    #
    # `requires=("action_sink",)` stays and is still REPORTED, never enforced:
    # an entity built in a check and never bound legitimately has none, which
    # is the same contract `action_manager` and `collision_field` have.
    status="live",
    order=RELAY_ORDER,
    example='<property name="pyoneer_behaviors" '
            'value="player_input,interact_action,action_relay"/>',
)

ACTION_SPECS: tuple[BehaviorSpec, ...] = (ATTACK_ACTION, INTERACT_ACTION,
                                          PAUSE_ACTION)
"""Every spec that polls a verb and records a firing. The relay is not one."""

__all__ = ["ACTION_RELAY", "ACTION_SPECS", "ATTACK_ACTION", "INTERACT_ACTION",
           "NO_ACTIONS", "ORDER", "PAUSE_ACTION", "RELAY_ORDER", "SLOT_PREFIX",
           "ActionFired", "ActionIntent", "GameActionInputBehavior",
           "GameActionRelayBehavior", "actions_of", "require_verbs"]
