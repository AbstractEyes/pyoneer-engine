from __future__ import annotations

from enum import Enum
from typing import Optional

import pygame
from pygame import Rect, Vector2

from scripts.core.component import GameComponent
from scripts.core.event_manager import PyoneerEvent

class ViewportAnchor(str, Enum):
    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


class ViewportCamera:
    """
        This is the camera that will be used to view anything in the game world.
        It will be attached to anything that requires a viewport.
    """

    def __init__(self,
                 view_area: Rect = Rect(0, 0, 0, 0),
                 full_area: Rect = Rect(0, 0, 0, 0),
                 target: GameComponent | None = None,
                 follow_target: bool = True,
                 target_offset: Vector2 = Vector2(0, 0),
                 parent: GameComponent | None = None,
                 full_follow_parent: bool = False,
                 lock_offset: Vector2 = Vector2(0, 0)):
        self.__view_area = view_area
        """The view area of the camera.\n
            This is the area of the screen that the camera will render to."""
        self.__full_area = full_area
        """This is the full area of the camera.\n
            This is the larger area camera will render a portion of."""
        self.zoom = 1
        """The zoom scalar of the camera."""
        self.__target: GameComponent | None = target
        self.__moved = False
        self.__last_target_position = pygame.Vector2(0, 0)
        self.__last_parent_position = pygame.Vector2(0, 0)

        self.__follow_target = follow_target
        """If the camera should follow the target, clamping the view edges as it can."""
        self.__target_offset = target_offset
        """The offset from the target to the camera's offset type, using the target's bounds."""

        self.__parent: GameComponent | None = parent
        self.__full_follow_parent = full_follow_parent
        """If the camera should follow the parent, locking the camera to an anchor offset."""
        self.__lock_offset = lock_offset
        """The offset from the parent to the camera's offset type, using the parent's bounds."""


    # Goals;
    # 1. Attach a target to the camera
    # 2. Attach a parent to the camera
    # 3. Move the area of the camera
    # 4. Move the view of the camera
    # 5. Slice a view from the full area
    # 6. Slice a view from the view area
    # 7. Update the camera position based on the target
    # 8. Update the area based on the parent
    # 9. Clamp the component to the intended rect
    # 10. Clamp the views based on the configuration

    # two primary use cases;
    # 1. entity followed by the camera
    # 2. camera used as a viewport for widgets or other draw components
        # solving this, solves the first use case


    def attach_target(self, target: GameComponent):
        """Attach a target to the camera as a focus point for view area management."""
        self.__target = target

    def attach_parent(self, parent: GameComponent):
        """Attaches a parent for full area management."""
        self.__parent = parent

    def move_area(self, x: int, y: int, w: int, h: int):
        """Moves the entire area of the camera. This is the area that the camera will slice squares from."""
        self.__full_area = Rect(x, y, w, h)

    def move_view(self, x: int, y: int, w: int, h: int):
        """Moves the view area of the camera. This is the area that the camera will render to."""
        self.__view_area = Rect(x, y, w, h)

    @property
    def view(self) -> Rect:
        """The clipped view area of the camera."""
        return self.__view_area.clip(self.__full_area)

    @property
    def area(self) -> Rect:
        """The full area of the camera."""
        return self.__full_area

    @property
    def view_bounds(self) -> Rect:
        """The bounds contained within the camera, safe for blitting"""
        return self.__view_area

    @property
    def full_bounds(self) -> Rect:
        """The full bounds of the camera, safe for blitting"""
        return self.__full_area

    def slice_view(self, rect: Rect) -> Rect:
        """Slices a view from the full area using the view area."""
        return self.__view_area.clip(rect)

    def slice_area(self, rect: Rect) -> Rect:
        """Slices a view from the full area using the full area."""
        return self.__full_area.clip(rect)

    @property
    def moved(self) -> bool:
        return self.__moved

    def update(self, event: Optional[PyoneerEvent] = None):
        """Update the camera position based on the target."""
        # update the target position with the view area
        if self.__target is not None:
            self.__clamp_component(self.__target, self.__view_area, self.__target_view_anchor)
        # update the parent position with the full area

