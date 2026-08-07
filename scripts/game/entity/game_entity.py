from __future__ import annotations

from abc import ABC
from typing import overload, Optional

import pygame
from pygame import rect, Surface

from config.managers.animation_data import DataAnimationCategory
from config.managers.entity_data import DataEntityMovement
from scripts.core.event_manager import PyoneerEvent

from scripts.core.blitpool import BlitPool
from scripts.game.entity.game_animation import GameAnimationHandler
from scripts.core.game_object import PyoneerGameObject
from scripts.game.entity.game_transform import Transform
from pygame import Vector2


# A lightweight entity that contains only the most basic of data
class GameEntitySimple(PyoneerGameObject, ABC):

    def __init__(self,
                 transform: Transform = None,
                 position: tuple[int, int] = (0, 0),
                 rotation: float = 0,
                 scale: tuple[int, int] = (1, 1),
                 image_path: str = ""):
        super().__init__()
        self.transform: Transform = Transform(position=position, rotation=rotation, scale=scale)
        self._image = pygame.image.load(image_path) if len(image_path) > 0 else None

    def core_image(self, image_in: Surface = None) -> Surface:
        return self._image

    def moveto(self, transform: Transform | tuple[float, float]):
        if isinstance(transform, tuple):
            self.transform.position = Vector2(transform)
        else:
            self.transform.copy(transform)

    #def blits(self, event: Optional[PyoneerEvent]):
    #    BlitPool.blit_to_layer(self.depth, self.priority, self.image(), self.transform.position)


class GameEntity(GameEntitySimple, ABC):

    def __init__(self,
                 movement_config: dict[str, any] = None,
                 image_path: str = "",
                 transform: Transform = Transform()):
        super().__init__(image_path=image_path, transform=transform)
        self.move_speed = movement_config['move_speed'] if movement_config and 'move_speed' in movement_config.keys() else 16
        self.sprint_mult = movement_config['sprint_mult'] if movement_config and 'sprint_mult' in movement_config.keys() else 2
        self.__started = False
        self.__stopped = False

    @property
    def started(self) -> bool:
        return self.__started

    @property
    def stopped(self) -> bool:
        return self.__stopped

    def start(self):
        self.__started = True

    def stop(self):
        self.__stopped = True

    def core_pre_prepare(self, event: Optional[PyoneerEvent] = None):
        pass

    def core_prepare(self, event: Optional[PyoneerEvent] = None) -> Surface:
        pass

    def core_update(self, event: Optional[PyoneerEvent] = None):
        pass

    def core_dispose(self, event: Optional[PyoneerEvent] = None):
        pass

    def rotate(self, angle: float):
        self.transform.rotation += angle

    def move_direction(self, delta: float, direction: str, sprint: bool = False):
        changes = Transform()
        if direction == "left":
            changes.position.x += -1 * self.move_speed * delta
        elif direction == "right":
            changes.position.x += 1 * self.move_speed * delta
        elif direction == "up":
            changes.position.y += -1 * self.move_speed * delta
        elif direction == "down":
            changes.position.y += 1 * self.move_speed * delta
        if sprint:
            changes.position *= self.sprint_mult
        self.transform.position += changes.position


# the animated entity, is a type of entity that contains the potential for animation
class GameAnimatedEntity(GameEntity):

    def __init__(self,
                 movement_config: DataEntityMovement = None,
                 animation_config: DataAnimationCategory = None,
                 transform: Transform = Transform()):
        super().__init__(
            movement_config=movement_config,
            transform=transform)
        self.animation_data = animation_config
        self.animation: GameAnimationHandler = GameAnimationHandler(self.animation_data)
        self.__started: bool = False
        self.__stopped: bool = False

    def core_image(self, image_in: Surface = None) -> Surface:
        # get the current animation frame
        if self.animation:
            return self.animation.image()
        else:
            return super().core_image()

    def core_update(self, event: Optional[PyoneerEvent] = None):
        super().core_update(event)
        if self.animation:
            self.animation.update(event)