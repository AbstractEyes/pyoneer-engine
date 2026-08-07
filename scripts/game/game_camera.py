import pygame
from pygame import Rect

from component import GameComponent
from scripts.game.entity.game_entity import PyoneerGameObject, GameEntity


class GameCamera:
    OFFSET_CENTER = "center"
    OFFSET_TOP_LEFT = "top_left"
    OFFSET_BOTTOM_RIGHT = "bottom_right"

    def __init__(self,
                 view_area: pygame.Vector2 | Rect,
                 full_area: Rect | None = None,
                 offset_value: pygame.Vector2 | None = None,
                 offset_type: str = "center",
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
        self.__offset_type: str = offset_type
        """ The type of offset that this camera will use the target position in order to clamp."""

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


class OldGameCamera:
    def __init__(self, camera_bounds: pygame.Vector2, clamping_bounds: pygame.Rect | None = None, scale: float = 1):
        self.viewport = pygame.Rect(0, 0, camera_bounds.x, camera_bounds.y)
        self.clamping: pygame.Rect | None = clamping_bounds
        self.scale: float = scale
        self.target: GameEntity | None = None
        self._moved: bool = False
        self.__last_position: pygame.Vector2 = pygame.Vector2(0, 0)
        self.offset: pygame.Vector2 = pygame.Vector2(0, 0) # the offset from the entity to the camera

    def attach_target(self, host: GameEntity):
        self.target = host
        pass
        
    def within_bounds(self, position: pygame.Vector2):
        if self.viewport.collidepoint(position):
            return True
        else:
            return False

    def moved(self):
        return self._moved

    def update(self, position=None):
        """if target; center camera over target"""
        self._moved = False
        if self.target is not None:
            if self.__last_position.x != self.target.transform.position.x or self.__last_position.y != self.target.transform.position.y:
                self.__last_position = self.target.transform.position
                self._moved = True
            self.viewport.center = self.target.transform.position
            self.viewport.x += self.offset.x
            self.viewport.y += self.offset.y
        else:
            if position is not None:
                self.viewport.center = position
                self._moved = True
        """clamp camera to map"""
        if self.viewport.x < 0:
            self.viewport.x = 0
        if self.viewport.y < 0:
            self.viewport.y = 0
        if self.viewport.x + self.viewport.width > self.clamping.width:
            self.viewport.x = self.clamping.width - self.viewport.width
        if self.viewport.y + self.viewport.height > self.clamping.height:
            self.viewport.y = self.clamping.height - self.viewport.height
                               