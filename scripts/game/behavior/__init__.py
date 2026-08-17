"""Behavior components: what an entity DOES, composed from data.

The author's goal, in his words: "the system needs to be
component-modularized and documented as well for quick AI creation,
modification, and usage changing." Read as: movement, input and collision
response are COMPOSED onto an entity as swappable behaviors declared in a
map, not baked into a subclass. A platformer player is the same `GamePlayer`
class as a top-down one carrying a different behavior list.

WHAT IS HERE
------------
    base.py       the contract (`EntityBehavior`), the declarations
                  (`BehaviorSpec`, `BehaviorParam`, `BehaviorRequest`), the
                  tmx vocabulary, and the ordered per-frame drive
                  (`EntityBehaviors`)
    registry.py   the hand-written token table, the map read path, and the
                  generator for docs/BEHAVIORS.md
    input.py      `player_input` -- polls the bound InputActionManager and
                  publishes a `MoveIntent`. The entity carrying this one is
                  the entity the human drives; that is the whole marker.
    movement.py   `topdown_move` (the demo's controller, moved out of
                  `GamePlayer.input_move` unchanged), `platformer_move`
                  (gravity, jump, coyote time, air control) and
                  `animation_drive` (sequence naming as parameters).

WHAT IS DELIBERATELY NOT HERE
-----------------------------
Anything that decides a behavior list from a CLASS. A list keyed by class
name is the subclass shape wearing a dict as a disguise, and it cannot let
two objects of one type on one map differ. The list is authored per tmx
object, and an entity with an empty one runs exactly the code it ran before
this package existed -- which is why landing it moved no frame.

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
from scripts.game.behavior.input import (NO_INTENT, GamePlayerInputBehavior,
                                         MoveIntent, intent_of)
from scripts.game.behavior.movement import (MS_PER_DELTA, SECONDS_PER_DELTA,
                                            TOPDOWN_VERBS,
                                            GameAnimationDriveBehavior,
                                            GamePlatformerMoveBehavior,
                                            GameTopDownMoveBehavior)

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
    # the concrete behaviors and the intent they pass between them
    "MS_PER_DELTA", "NO_INTENT", "SECONDS_PER_DELTA", "TOPDOWN_VERBS",
    "GameAnimationDriveBehavior", "GamePlatformerMoveBehavior",
    "GamePlayerInputBehavior", "GameTopDownMoveBehavior", "MoveIntent",
    "intent_of",
]
