from typing import Optional

import pygame

from config.managers.animation_data import DataAnimationCategory
from scripts.core.event_types import GameEventType
from scripts.core.event_manager import PyoneerEvent
from scripts.core.input import InputActionManager
from scripts.game.entity.game_animation import GameAnimation, GameAnimationHandler
from scripts.game.entity.game_entity import GameEntity, GameAnimatedEntity
from scripts.game.entity.game_transform import Transform
from scripts.core.blitpool import BlitPool


class PlayerState:
    def __init__(self):
        self.can_move: bool = True
        self.enabled_inputs: bool = True
        self.active: bool = True

        self.moving: bool = False
        self.sprinting: bool = False
        self.move_direction: str = "none"
        self.last_direction: str = "none"


class GamePlayer(GameAnimatedEntity):

    def core_inputs(self, events: list[pygame.event.Event] | pygame.event.Event):
        # todo; process input events for the player
        pass

    def __init__(self,
                 input_: InputActionManager=None,
                 movement_config=None,
                 world_transform=Transform(),
                 animation_config: DataAnimationCategory | None = None):
        super().__init__(transform=world_transform,
                         movement_config=movement_config,
                         animation_config=animation_config)
        self.action_manager: InputActionManager = input_
        self.state: PlayerState = PlayerState()
        self.animation.start("idle_down")
        if not self.action_manager:
            self.state.enabled_inputs = False

    def core_build(self, event: Optional[PyoneerEvent] = None):
        pass

    # core_image is inherited from GameAnimatedEntity; the override that used
    # to live here was identical apart from returning self._image directly
    # instead of going through super().

    def input_move(self, event: Optional[PyoneerEvent] = None):
        if event is None:
            return
        delta_time = event.data["delta"]
        last_direction = self.state.move_direction
        last_moving = self.state.moving
        moving = False
        direction = "none"
        # held(), not pressed(): movement is continuous while the key is down.
        # This used to read pressed(), which only worked because pressed()
        # latched True for the whole hold. pressed() is now a true rising edge.
        if self.action_manager.held("up"):
            moving = True
            direction = "up"
            self.move_direction(delta_time, "up")
        if self.action_manager.held("down"):
            moving = True
            direction = "down"
            self.move_direction(delta_time, "down")
        if self.action_manager.held("left"):
            moving = True
            direction = "left"
            self.move_direction(delta_time, "left")
        if self.action_manager.held("right"):
            moving = True
            direction = "right"
            self.move_direction(delta_time, "right")
        self.state.moving = moving
        self.state.move_direction = direction
        if self.state.moving:
            self.state.last_direction = direction
        if last_direction != self.state.move_direction or last_moving != self.state.moving:
            if self.state.moving:
                self.animation.start(f"walk_{direction}")
            else:
                self.animation.start(f"idle_{self.state.last_direction}")

    def core_update(self, event: Optional[PyoneerEvent] = None):
        # update movement lerp
        if not self.state.active:
            return
        super().core_update(event)
        if self.state.enabled_inputs and self.state.can_move:
            self.input_move(event)
        #self.move(delta_time, self.world_transform)

