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
    from scripts.game.behavior import (BehaviorParam, BehaviorSpec,
                                       EntityBehavior, build, read_requests,
                                       register)

    class GameTopDownMoveBehavior(EntityBehavior):
        def __init__(self, move_speed: int = 16):
            self.move_speed = move_speed
        def update(self, entity, event):
            ...                                   # event.data["delta"]

    register(BehaviorSpec(
        name="topdown_move",                      # goes into the .tmx
        summary="Four-way axis-aligned movement polled from input verbs.",
        factory=GameTopDownMoveBehavior,
        params=(BehaviorParam("move_speed", "move speed", "int", 16,
                              "Pixels per delta unit.", source="actors"),),
        writes=("transform.position",),           # what it mutates
        requires=("action_manager",),             # what it needs to work
        order=20))                                # low runs first

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
