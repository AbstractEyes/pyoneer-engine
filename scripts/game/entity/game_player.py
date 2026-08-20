"""The controllable entity -- the same class as an uncontrolled one.

What a player DOES is the behavior list it carries, not this class. A driven
top-down body declares three tokens:

    player_input      scripts/game/behavior/input.py     polls, publishes intent
    topdown_move      scripts/game/behavior/movement.py  intent -> displacement
    animation_drive   scripts/game/behavior/movement.py  state  -> sequence name

A platformer player is this same class with `platformer_move` in place of
`topdown_move`.

What makes a player a player is carrying `player_input` -- not the class, and
not who was handed an `InputActionManager`. Holding a manager does nothing;
reading one is what moves an entity, and only that behavior reads it. So every
spawned `<object type="GamePlayer">` can hold the live manager while only the
one the map marked responds to a key.

Three gates live on the entity's `state`. `simulated` short-circuits the whole
frame here; `enabled_inputs` and `steerable` are read by `player_input`.
Clearing `steerable` mid-walk returns the sprite to idle rather than freezing
it mid-stride, because the movement behavior keeps running and receives an
empty intent.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

import pygame

from config.managers.animation_data import DataAnimationCategory
from scripts.core.event_types import GameEventType
from scripts.core.event_manager import PyoneerEvent
from scripts.core.input import InputActionManager
from scripts.game.behavior import BEHAVIORS, build, read_requests
from scripts.game.behavior.state import BodyState
from scripts.game.entity.game_animation import GameAnimation, GameAnimationHandler
from scripts.game.entity.game_entity import GameEntity, GameAnimatedEntity
from scripts.game.entity.game_transform import Transform
from scripts.core.blitpool import BlitPool


PlayerState = BodyState
"""The name eight files import for `scripts.game.behavior.state.BodyState`.

An ALIAS and not a subclass, so `isinstance` cannot disagree with `state_of`
about what counts as a body state.
"""


class GamePlayer(GameAnimatedEntity):

    def core_input_receive(self, events: list[pygame.event.Event] | pygame.event.Event):
        """Do nothing. Movement is polled, not event-driven.

        `SceneManager.inputs` calls this once per pyo-event for every bound
        object, so it looks like the player's input entry point and is not:
        `player_input` asks `InputActionManager.held()` for each verb once per
        frame and publishes a `MoveIntent`. This method is where a rising-edge
        action (talk, use, open a menu) would go, and there is not one yet.
        """
        return

    def __init__(self,
                 input_: InputActionManager=None,
                 movement_config=None,
                 world_transform=Transform(),
                 animation_config: DataAnimationCategory | None = None,
                 behaviors: str | Mapping[str, Any] | None = None):
        """`behaviors` is the same declaration an `<object>` carries, or None.

        Accepts either the raw `pyoneer_behaviors` string
        (`"player_input,topdown_move"`) or a full tmx-style property mapping,
        so a hand-built entity and a map-spawned one go through one reader,
        `scripts.game.behavior.read_requests`.

        None composes nothing; there is no class default, because
        `EntityBehaviors.attach` refuses a duplicate token and a class default
        plus an authored list would raise.

        `world_transform` reaches `GameEntity` as its `transform` keyword,
        which is accepted and silently DISCARDED -- position still has to be
        set with `moveto()` afterwards.
        """
        super().__init__(transform=world_transform,
                         movement_config=movement_config,
                         animation_config=animation_config)
        self.action_manager: InputActionManager = input_
        self.state: BodyState = BodyState()
        self.state.input_bound = input_ is not None
        # `input_bound` records whether a manager was handed in at all;
        # `enabled_inputs` stays the authored gate, so a narrative system
        # toggling it can tell "input was taken away" from "this entity never
        # had any". Behaviors attach after both, because `player_input.attach`
        # reads the manager to prove every verb it polls is bound.
        if behaviors:
            properties = (behaviors if isinstance(behaviors, Mapping)
                          else {BEHAVIORS: behaviors})
            self.behaviors.attach_all(build(read_requests(  # #TAG:behaviors_attached_at_construction
                properties, where="%s()" % type(self).__name__)))

    def core_lifecycle_build(self, event: Optional[PyoneerEvent] = None):
        pass

    def input_move(self, event: Optional[PyoneerEvent] = None):
        """Advance this player's composed behaviors by exactly one frame.

        A named entry point for callers that drive a player directly, such as
        `tools/check_input.py`. `core_frame_update` does NOT call this -- it
        reaches the same drive through `super()`, and calling both would run
        every behavior twice per frame (exactly double speed, for a movement
        behavior).
        """
        if event is None:
            return
        self.behaviors.update(event)

    def core_frame_update(self, event: Optional[PyoneerEvent] = None):
        if not self.state.simulated:
            # The whole-entity switch: an unsimulated player neither moves nor
            # animates, because returning before `super()` stops the animation
            # clock too. It is per-entity and NOT a world pause -- there is no
            # scene-level equivalent. The finer gates (`input_bound`,
            # `enabled_inputs`, `steerable`) live in `player_input`.
            return
        # -> GameAnimatedEntity.core_frame_update -> GameEntity.core_frame_update
        #    -> self.behaviors.update(event), then the animation tick.
        super().core_frame_update(event)
