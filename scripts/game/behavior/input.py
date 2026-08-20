"""Who is driving, and what they asked for: the input behavior and its intent.

WHICH SPAWNED OBJECT IS THE PLAYER
----------------------------------
Whichever entity carries `player_input`. Every spawned player may hold the
same live `InputActionManager`, because holding one is not what makes an
entity controllable -- reading it is, and only this behavior reads it. An
entity without it is inert by construction rather than by a special case.

INTENT, NOT DISPLACEMENT
------------------------
This behavior polls and publishes a `MoveIntent`; a movement behavior reads
the intent and decides what a body does with it. `topdown_move` walks four
ways, `platformer_move` walks two and jumps, and NEITHER knows a key exists.
The same split lets a replay, a network peer or an AI drive a movement
behavior by attaching a different producer at `order` 10.

THE UNGUARDED DICT INDEX, AND WHERE IT IS CAUGHT
------------------------------------------------
`InputActionManager.held()` is `self.actions[name].held`, an unguarded index.
Polling a verb absent from `config/inputs.json` raises `KeyError` from inside
`core_frame_update`, which kills the frame for every sibling in that scene
bucket. So every declared verb is checked ONCE, in `attach`, against the
manager's own table, and a missing one raises there naming the verb, the
behavior and every verb that IS bound.
"""
from __future__ import annotations

from typing import Any, Optional

from scripts.core.errors import PyoneerConfigError
from scripts.game.behavior.base import (BehaviorParam, BehaviorSpec,
                                        EntityBehavior)
from scripts.game.behavior.state import state_of


class MoveIntent:
    """What an entity has been ASKED to do this frame, in device-free terms.

    The four directions are SEPARATE booleans rather than an (x, y) pair,
    because `topdown_move` runs one gated move per held verb: with a wall on
    the left, holding left AND right travels right, where a collapsed
    `x = right - left` would travel nowhere. `x` is derived for the behaviors
    that want an axis, so both readings are available and only one is stored.
    """

    __slots__ = ("up", "down", "left", "right", "sprint", "jump", "_locked")

    def __init__(self, locked: bool = False):
        object.__setattr__(self, "_locked", False)
        self.clear()
        object.__setattr__(self, "_locked", bool(locked))

    def __setattr__(self, name: str, value: Any) -> None:
        """Refuse every write once locked. `NO_INTENT` is the only locked one.

        Without it, one careless `intent.jump = True` on the shared inert
        intent would make every entity on the map jump -- on entities that
        have no input behavior at all.
        """
        if getattr(self, "_locked", False):
            raise PyoneerConfigError(
                "NO_INTENT is the shared inert intent handed to an entity that "
                "carries no input behavior, and writing %r to it would give "
                "every such entity the same input. Attach an input behavior, "
                "or allocate your own MoveIntent()." % (name,))
        object.__setattr__(self, name, value)

    def clear(self) -> None:
        """Back to "nothing is being asked for". Called at the top of a poll."""
        self.up = False
        self.down = False
        self.left = False
        self.right = False
        self.sprint = False
        self.jump = False

    @property
    def x(self) -> int:
        """-1, 0 or +1. Both horizontal verbs held cancel, as a stick would."""
        return (1 if self.right else 0) - (1 if self.left else 0)

    # There is no vertical counterpart to `x`, because nothing would consume
    # it: `topdown_move` reads the four booleans and `platformer_move` reads
    # `x` alone, its vertical motion coming from gravity and the jump edge. A
    # ladder or a twin-stick shooter wants one; add it WITH its consumer, so
    # the sign convention is testable.

    @property
    def moving(self) -> bool:
        return self.up or self.down or self.left or self.right

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        held = [n for n in ("up", "down", "left", "right", "sprint", "jump")
                if getattr(self, n)]
        return "<MoveIntent %s>" % (",".join(held) or "idle")


NO_INTENT = MoveIntent(locked=True)
"""The intent an entity that publishes none is read as: nothing held, ever.

Locked, so one borrower cannot alter what every other borrower sees. It is
what makes "no input behavior" mean inert rather than crash -- a movement
behavior always has an intent to read.
"""


def intent_of(entity: Any) -> MoveIntent:
    """The entity's own intent, or the shared inert one.

    The single reader used by every movement behavior, so "what happens to an
    entity with no input" is answered in one place.
    """
    found = getattr(entity, "intent", None)
    return found if isinstance(found, MoveIntent) else NO_INTENT


class GamePlayerInputBehavior(EntityBehavior):
    """Poll the bound `InputActionManager` and publish this frame's intent.

    Every verb is a parameter, so the same class serves a top-down player
    reading `sprint` and a platformer reading `jump`. An EMPTY verb name means
    "this body has no such input" and is not polled at all.

    Requires `entity.action_manager`, but a None manager is a legal
    configuration: this reports itself as unsatisfied through
    `EntityBehaviors.missing_requirements()` and does nothing per frame,
    rather than refusing to attach.
    """

    def __init__(self,
                 up_verb: str = "up",
                 down_verb: str = "down",
                 left_verb: str = "left",
                 right_verb: str = "right",
                 sprint_verb: str = "sprint",
                 jump_verb: str = ""):
        self.up_verb = up_verb
        self.down_verb = down_verb
        self.left_verb = left_verb
        self.right_verb = right_verb
        self.sprint_verb = sprint_verb
        self.jump_verb = jump_verb

    # -- declaration -------------------------------------------------------

    @property
    def held_verbs(self) -> tuple[str, ...]:
        """The verbs polled with `held()`, in the order they are polled."""
        return tuple(v for v in (self.up_verb, self.down_verb, self.left_verb,
                                 self.right_verb, self.sprint_verb) if v)

    @property
    def edge_verbs(self) -> tuple[str, ...]:
        """The verbs polled with `pressed()` -- a true rising edge."""
        return tuple(v for v in (self.jump_verb,) if v)

    # -- lifecycle ---------------------------------------------------------

    def attach(self, entity: Any) -> None:
        """Allocate the intent, and prove every declared verb is bound.

        The verb check turns `KeyError: 'jump'` raised mid-frame -- which
        takes down every sibling entity in the same scene bucket and blames
        the movement code -- into one message at composition time naming the
        verb, the parameter that declared it and everything that IS bound.
        """
        entity.intent = MoveIntent()
        manager = getattr(entity, "action_manager", None)
        if manager is None:
            # Legal, not a refusal: `input_=None` is how a decoy stays inert,
            # and an entity spawned before its manager exists is a normal boot
            # order.
            return
        bound = getattr(manager, "actions", {})
        for verb in self.held_verbs + self.edge_verbs:
            if verb not in bound:
                raise PyoneerConfigError(
                    "behavior 'player_input' on %s polls the verb %r, which "
                    "config/inputs.json does not bind. held()/pressed() are "
                    "unguarded dict indexes, so this would have raised "
                    "KeyError inside core_frame_update and killed the frame "
                    "for every entity in the same bucket. Bound verbs: %s."
                    % (type(entity).__name__, verb,
                       ", ".join(sorted(bound)) or "<none>"))

    def detach(self, entity: Any) -> None:
        """Hand back a cleared intent, so a movement sibling reads zeroes.

        Not `del entity.intent`: a movement behavior left attached would keep
        reading the LAST intent published here and walk forever in the
        direction the key was held.
        """
        entity.intent = MoveIntent()

    def update(self, entity: Any, event: Any) -> None:
        intent = getattr(entity, "intent", None)
        if intent is None or intent is NO_INTENT:
            # attach() always allocates one; this is the hand-constructed path.
            intent = entity.intent = MoveIntent()
        intent.clear()
        manager = getattr(entity, "action_manager", None)
        if manager is None:
            return
        state = state_of(entity)
        if state is not None and not (state.input_bound and state.enabled_inputs
                                      and state.steerable):
            # The steering gate sits on the PRODUCER, not around the movement
            # behavior: an ungated body stops being steered, not simulated, so
            # a platformer body still falls while the player is in a menu
            # (measured at 13.772px over 10 frames).
            #
            # The three terms are distinct questions: `input_bound` is the
            # wiring one, `enabled_inputs` the authored one, `steerable`
            # whether this body may walk. An entity with no manager returned
            # two lines above and never reaches here.
            return
        if self.up_verb:
            intent.up = manager.held(self.up_verb)
        if self.down_verb:
            intent.down = manager.held(self.down_verb)
        if self.left_verb:
            intent.left = manager.held(self.left_verb)
        if self.right_verb:
            intent.right = manager.held(self.right_verb)
        if self.sprint_verb:
            intent.sprint = manager.held(self.sprint_verb)
        if self.jump_verb:
            # pressed(), not held(): a jump is an edge, and held() here is the
            # infinite-hover bug, which looks like a physics fault.
            intent.jump = manager.pressed(self.jump_verb)
        if state is not None:
            state.sprinting = intent.sprint


PLAYER_INPUT = BehaviorSpec(
    name="player_input",  # #TAG:player_input
    summary="Polls the bound input manager and publishes a MoveIntent. The "
            "entity carrying this one is the entity the human drives.",
    factory=GamePlayerInputBehavior,
    params=(
        BehaviorParam("up_verb", "up verb", "str", "up",
                      "Action name polled with held() for upward intent. "
                      "Empty means this body has no upward input.",
                      source="object"),
        BehaviorParam("down_verb", "down verb", "str", "down",
                      "Action name polled with held() for downward intent.",
                      source="object"),
        BehaviorParam("left_verb", "left verb", "str", "left",
                      "Action name polled with held() for leftward intent.",
                      source="object"),
        BehaviorParam("right_verb", "right verb", "str", "right",
                      "Action name polled with held() for rightward intent.",
                      source="object"),
        BehaviorParam("sprint_verb", "sprint verb", "str", "sprint",
                      "Action name polled with held() for sprint. Empty "
                      "disables sprinting for this entity.",
                      source="object"),
        BehaviorParam("jump_verb", "jump verb", "str", "",
                      "Action name polled with pressed() -- a rising edge -- "
                      "for jump. Empty by default because a top-down body has "
                      "no jump; a platformer sets it to 'jump'.",
                      source="object"),
    ),
    writes=("intent", "state.sprinting"),
    requires=("action_manager",),
    order=10,
    example='<property name="pyoneer_behaviors" '
            'value="player_input,topdown_move,animation_drive"/>',
)

__all__ = ["NO_INTENT", "PLAYER_INPUT", "GamePlayerInputBehavior", "MoveIntent",
           "intent_of"]
