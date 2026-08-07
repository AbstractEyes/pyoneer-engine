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
        movement = self.__movement_values(movement_config)
        self.move_speed = movement.get('move_speed', 16)
        self.sprint_mult = movement.get('sprint_mult', 2)
        self.__started = False
        self.__stopped = False

    @staticmethod
    def __movement_values(movement_config: dict[str, any] | None) -> dict[str, any]:
        """Accept either the entity block or the movement block itself.

        config/entity.json nests movement under a "movement" key, but callers
        (main.py) pass the whole entity block. The old lookup tested for
        'move_speed' at the TOP level, which is never there, so every entity
        silently fell back to the default 16 and the configured 20 was dead
        config. Both shapes now resolve.
        """
        if not movement_config:
            return {}
        if 'movement' in movement_config:
            return movement_config['movement'] or {}
        return movement_config

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

    def core_image(self, image_in: Surface = None) -> Surface | None:
        """Current animation frame, falling back to the static image.

        May return None when no animation is playing and no static image was
        set; the render path skips entities with no image rather than
        blitting a placeholder.
        """
        if self.animation is not None:
            frame = self.animation.image()
            if frame is not None:
                return frame
        return super().core_image()

    def core_update(self, event: Optional[PyoneerEvent] = None):
        super().core_update(event)
        if self.animation:
            self.animation.update(event)