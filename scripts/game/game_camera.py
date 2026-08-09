import pygame
from pygame import Rect

from scripts.core.component import GameComponent
from scripts.game.entity.game_entity import PyoneerGameObject, GameEntity


class GameCamera:
    """The camera that views part of the game world.

    Goals:
        1. Attach a target to the camera
        2. Attach a parent to the camera
        3. Move the area of the camera
        4. Move the view of the camera
        5. Slice a view from the full area
        6. Slice a view from the view area
        7. Update the camera position based on the target
        8. Update the area based on the parent
        9. Clamp the component to the intended rect
        10. Clamp the views based on the configuration

    Two primary use cases:
        1. entity followed by the camera
        2. camera used as a viewport for widgets or other draw components
           -- solving this, solves the first use case
    """

    def __init__(self,
                 view_area: pygame.Vector2 | Rect,
                 full_area: Rect | None = None,
                 offset_value: pygame.Vector2 | None = None,
                 target: any = None,
                 scale: float = 1):
        self.view_area: Rect = pygame.Rect(0, 0, 0, 0)
        """The view area of the camera. This is the area of the screen that the camera will render to."""
        if isinstance(view_area, pygame.Vector2):
            self.view_area = pygame.Rect(0, 0, view_area.x, view_area.y)
        elif isinstance(view_area, Rect):
            self.view_area = view_area.copy()
        elif view_area is None:
            self.view_area = pygame.Rect(0, 0, pygame.display.get_window_size()[0], pygame.display.get_window_size()[1])
        self.full_area: pygame.Rect | None = full_area if full_area is not None else pygame.Rect(0, 0, self.view_area.width, self.view_area.height)
        """The full area of the camera. This is the larger area camera will render a portion of."""
        self.scale: float = scale
        self.attach_target(target)
        self._moved: bool = False
        self.__last_position: pygame.Vector2 = pygame.Vector2(0, 0)
        self.offset: pygame.Vector2 = pygame.Vector2(0, 0) if offset_value is None else offset_value
        """ The offset from the target to the camera's offset type."""

    def attach_target(self, host):
        self.target = host
        pass

    def within_bounds(self, position: pygame.Vector2):
        if self.view_area.collidepoint(position):
            return True
        else:
            return False

    def moved(self):
        return self._moved

    def update(self, position=None, move_full_area: bool = False):
        """if target; center camera over target"""
        self._moved = False
        if self.target is not None and isinstance(self.target, GameEntity):
            if self.__last_position.x != self.target.transform.position.x or self.__last_position.y != self.target.transform.position.y:
                self.__last_position = self.target.transform.position
                self._moved = True
            if move_full_area:
                self.full_area.center = self.target.transform.position
                self.full_area.x += self.offset.x
                self.full_area.y += self.offset.y
            else:
                self.view_area.center = self.target.transform.position
                self.view_area.x += self.offset.x
                self.view_area.y += self.offset.y
        elif self.target is not None and isinstance(self.target, pygame.Rect):
            if self.__last_position.x != self.target.x or self.__last_position.y != self.target.y:
                self.__last_position = self.target.topleft
                self._moved = True
            if move_full_area:
                self.full_area.center = self.target.topleft
                self.full_area.x += self.offset.x
                self.full_area.y += self.offset.y
            else:
                self.view_area.center = self.target.topleft
                self.view_area.x += self.offset.x
                self.view_area.y += self.offset.y
        elif self.target is not None and isinstance(self.target, GameComponent):
            if self.__last_position.x != self.target.world_bounds.x or self.__last_position.y != self.target.world_bounds.y:
                self.__last_position = pygame.Vector2(self.target.world_bounds.x, self.target.world_bounds.y)
                self._moved = True
            if move_full_area:
                self.full_area.center = pygame.Vector2(self.target.world_bounds.x, self.target.world_bounds.y)
                self.full_area.x += self.offset.x
                self.full_area.y += self.offset.y
            else:
                self.view_area.center = pygame.Vector2(self.target.world_bounds.x, self.target.world_bounds.y)
                self.view_area.x += self.offset.x
                self.view_area.y += self.offset.y
        elif self.target is not None and isinstance(self.target, pygame.Vector2):
            if self.__last_position.x != self.target.x or self.__last_position.y != self.target.y:
                self.__last_position = self.target
                self._moved = True
            if move_full_area:
                self.full_area.center = self.target
                self.full_area.x += self.offset.x
                self.full_area.y += self.offset.y
            else:
                self.view_area.center = self.target
                self.view_area.x += self.offset.x
                self.view_area.y += self.offset.y
        else:
            if position is not None:
                if isinstance(position, pygame.Vector2):
                    self.view_area.center = position
                elif isinstance(position, Rect):
                    self.view_area.center = position.topleft
                self._moved = True
        """clamp camera to map"""
        if self.view_area.x < 0:
            self.view_area.x = 0
        if self.view_area.y < 0:
            self.view_area.y = 0
        if self.view_area.x + self.view_area.width > self.full_area.width:
            self.view_area.x = self.full_area.width - self.view_area.width
        if self.view_area.y + self.view_area.height > self.full_area.height:
            self.view_area.y = self.full_area.height - self.view_area.height
