"""Behavior components: what an entity DOES, composed from data.

Movement, input and action response are COMPOSED onto an entity as swappable
behaviors declared per tmx object, not baked into a subclass. A platformer
player is the same `GamePlayer` class as a top-down one carrying a different
behavior list; an entity with an empty list runs no behavior code at all.

WHAT IS HERE
------------
    base.py       the contract (`EntityBehavior`), the declarations
                  (`BehaviorSpec`, `BehaviorParam`, `BehaviorRequest`), the
                  tmx vocabulary, and the ordered per-frame drive
                  (`EntityBehaviors`)
    state.py      `BodyState` -- what a body IS: phase, facing, support and
                  agency. A behavior declares an axis it writes as
                  `state.<axis>`, so two writers of one axis are refused at
                  attach.
    registry.py   the hand-written token table, the map read path, and the
                  generator for docs/BEHAVIORS.md
    input.py      `player_input` -- polls the bound InputActionManager and
                  publishes a `MoveIntent`. The entity carrying this one is
                  the entity the human drives.
    movement.py   `topdown_move`, `platformer_move` (gravity, jump, coyote
                  time, air control) and `animation_drive` (sequence naming
                  as parameters).
    action.py     `attack_action`, `interact_action`, `pause_action` and
                  `action_relay` -- an occurrence rather than a value, with
                  the relay as the one behavior that reaches outward, by
                  CALLING `entity.action_sink`.
    lifecycle.py  `lifecycle_mark` -- writes `state.life = gone` and nothing
                  else. `SceneManager.reap()` is what removes; a behavior
                  that unbound its own entity would make the scene fan-out
                  skip the next sibling.

THE ONE-MINUTE VERSION
----------------------
    # In the family module, e.g. movement.py -- the spec sits BESIDE its class.
    from scripts.game.behavior.base import (BehaviorParam, BehaviorSpec,
                                            EntityBehavior)

    class GamePlatformerMoveBehavior(EntityBehavior):
        def __init__(self, gravity: float = 900.0, ...):
            self.gravity = gravity                # keyword == param key
        def update(self, entity, event):
            ...                                   # event.data["delta"]

    PLATFORMER_MOVE = BehaviorSpec(
        name="platformer_move",                   # goes into the .tmx
        summary="A side-on body: gravity, terminal velocity, ...",
        factory=GamePlatformerMoveBehavior,
        params=(BehaviorParam("gravity", "gravity", "float", 900.0,
                              "Downward pixels per second squared.",
                              source="actors"),),  # an actors column
        writes=("transform.position", "velocity"),  # what it mutates
        requires=("allowed_move", "transform"),   # reported, never enforced
        conflicts=("topdown_move",),
        order=20,                                 # low runs first
        genres=("platformer",))

    # In registry.py, at the bottom: the one token -> spec table.
    register_all((PLAYER_INPUT, TOPDOWN_MOVE, PLATFORMER_MOVE, ANIMATION_DRIVE))

    # At spawn, from the tmx object's own properties:
    entity.behaviors.attach_all(build(read_requests(obj.properties)))
"""
from __future__ import annotations

from scripts.game.behavior.base import (ACTOR, BEHAVIORS, KNOWN, PARAM_PREFIX,
                                        PARAM_SOURCES, PARAM_TYPES, PREFIX,
                                        STATUSES, TOKEN, BehaviorParam,
                                        BehaviorRequest, BehaviorSpec,
                                        EntityBehavior, EntityBehaviors)
from scripts.game.behavior.registry import (BEHAVIOR_REGISTRY, build,
                                            describe_all, format_list,
                                            parse_list, read_requests,
                                            register, register_all, resolve,
                                            resolve_params, validate_list)
from scripts.game.behavior.state import (FACING_DEFAULT, LIFE_ALIVE, LIFE_GONE,
                                         LIVES, PHASES, PHASE_IDLE,
                                         PHASE_MOVING, SUPPORTS,
                                         SUPPORT_AIRBORNE, SUPPORT_GROUNDED,
                                         BodyState, ensure_state, state_of)
from scripts.game.behavior.input import (NO_INTENT, GamePlayerInputBehavior,
                                         MoveIntent, intent_of)
from scripts.game.behavior.movement import (MS_PER_DELTA, SECONDS_PER_DELTA,
                                            TOPDOWN_VERBS,
                                            GameAnimationDriveBehavior,
                                            GamePlatformerMoveBehavior,
                                            GameTopDownMoveBehavior)
from scripts.game.behavior.lifecycle import GameLifecycleMarkBehavior

__all__ = [
    # vocabulary
    "ACTOR", "BEHAVIORS", "KNOWN", "PARAM_PREFIX", "PARAM_SOURCES",
    "PARAM_TYPES", "PREFIX", "STATUSES", "TOKEN",
    # declarations
    "BehaviorParam", "BehaviorRequest", "BehaviorSpec",
    # contract and drive
    "EntityBehavior", "EntityBehaviors",
    # registry
    "BEHAVIOR_REGISTRY", "build", "describe_all", "format_list", "parse_list",
    "read_requests", "register", "register_all", "resolve", "resolve_params",
    "validate_list",
    # the shared state vocabulary: what a body IS, as opposed to what it was
    # asked to do (MoveIntent) or what it did (ActionIntent)
    "FACING_DEFAULT", "LIFE_ALIVE", "LIFE_GONE", "LIVES", "PHASES",
    "PHASE_IDLE", "PHASE_MOVING", "SUPPORTS", "SUPPORT_AIRBORNE",
    "SUPPORT_GROUNDED", "BodyState", "ensure_state", "state_of",
    # the concrete behaviors and the intent they pass between them
    "MS_PER_DELTA", "NO_INTENT", "SECONDS_PER_DELTA", "TOPDOWN_VERBS",
    "GameAnimationDriveBehavior", "GameLifecycleMarkBehavior",
    "GamePlatformerMoveBehavior", "GamePlayerInputBehavior",
    "GameTopDownMoveBehavior", "MoveIntent", "intent_of",
]
