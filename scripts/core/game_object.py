from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from scripts.core.event_types import GameEventType
from scripts.core.event_manager import PyoneerEvent

if TYPE_CHECKING:
    from scripts.game.game_camera import GameCamera

from abc import ABC, abstractmethod, abstractproperty

import pygame
from pygame import surface, Rect

from scripts.core.utils import DEBUGGING, VERBOSE

class PyoneerGameObject(ABC):

    def __init__(self,
                 image: surface.Surface | None = None,
                 depth: int = 0,
                 priority: int = 0):
        self.__image: surface.Surface | None = image
        self.__depth: int = depth
        self.__priority: int = priority
        self.__flags: dict[str, bool] = {}
        self.uuid: str = uuid.uuid4().hex

    @property
    def flags(self):
        """Return the flags for the object."""
        return self.__flags

    @flags.setter
    def flags(self, value: dict[str, bool]):
        """Set the flags for the object."""
        self.__flags = value

    @property
    def depth(self) -> int:
        return self.__depth

    @depth.setter
    def depth(self, value: int) -> None:
        self.__depth = value

    @property
    def priority(self) -> int:
        return self.__priority

    @priority.setter
    def priority(self, value: int) -> None:
        self.__priority = value

    @abstractmethod
    def core_build(self, event: Optional[PyoneerEvent] = None):
        """Called when the object is created."""
        pass

    def core_pre_update(self, event: Optional[PyoneerEvent] = None):
        """Called before the update method."""
        if DEBUGGING:
            print(f"pre_update not implemented on object; ", self.__class__.__name__, " - ", self.__class__.__module__)

    @abstractmethod
    def core_update(self, event: Optional[PyoneerEvent] = None):
        """Called every frame. dt is the time in seconds since the last frame."""

    def core_post_update(self, event: Optional[PyoneerEvent] = None):
        """Called after the update method."""
        if DEBUGGING:
            print(f"post_update not implemented on object; ", self.__class__.__name__, " - ", self.__class__.__module__)

    def core_pre_dispose(self, event: Optional[PyoneerEvent] = None):
        """Called before the dispose method."""
        if DEBUGGING:
            print(f"pre_dispose not implemented on object; ", self.__class__.__name__, " - ", self.__class__.__module__)

    @abstractmethod
    def core_dispose(self, event: Optional[PyoneerEvent] = None) -> bool:
        """Called when the object is destroyed."""
        return True

    def core_post_dispose(self, event: Optional[PyoneerEvent] = None):
        """Called after the dispose method."""
        if DEBUGGING:
            print(f"post_dispose not implemented on object; ", self.__class__.__name__, " - ", self.__class__.__module__)

    def core_pre_prepare(self, event: Optional[PyoneerEvent] = None):
        """Called before the prepare method."""
        if DEBUGGING:
            print(f"pre_prepare not implemented on object; ", self.__class__.__name__, " - ", self.__class__.__module__)

    @abstractmethod
    def core_prepare(self, event: Optional[PyoneerEvent] = None) -> surface:
        """Called when the object is created."""

    def core_post_prepare(self, event: Optional[PyoneerEvent] = None):
        """Called after the prepare method."""
        if DEBUGGING:
            print(f"post_prepare not implemented on object; ", self.__class__.__name__, " - ", self.__class__.__module__)

    @abstractmethod
    def core_image(self, image_in: surface.Surface | None = None) -> surface.Surface:
        """Return the current surface image of the object."""

    def core_blits(self, event: Optional[PyoneerEvent]):
        """Return all prepared blits."""
        pass

    @abstractmethod
    def core_inputs(self, events: Optional[PyoneerEvent]):
        """Buffer the program events."""
        pass
