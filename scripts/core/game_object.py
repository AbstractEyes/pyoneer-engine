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

from scripts.core.errors import PyoneerImageMissingError
from scripts.core.utils import DEBUGGING, VERBOSE

class PyoneerGameObject(ABC):
    """Root of everything the engine drives.

    LIFECYCLE CONTRACT
    ------------------
    Methods are named `core_<domain>_<action>[_<phase>]`:

        core_lifecycle_build          once, after construction
        core_lifecycle_prepare_pre    \\
        core_lifecycle_prepare         > allocate surfaces, bind listeners
        core_lifecycle_prepare_post   /
        core_frame_update_pre         \\
        core_frame_update              > once per frame
        core_frame_update_post        /
        core_render_blits             once per frame, queues into BlitPool
        core_input_receive            input delivery
        core_lifecycle_dispose_pre    \\
        core_lifecycle_dispose         > teardown
        core_lifecycle_dispose_post   /

    The phase is a SUFFIX so autocomplete groups each family together;
    `core_pre_prepare` and `core_post_prepare` used to sort apart from
    `core_prepare`, which hid the relationship.

    WHO MAY OVERRIDE THESE
    ----------------------
    These are entry points for objects driven from OUTSIDE the component
    graph: GameScene, the Layer family, entities, and the single root
    component bound into a GameComponentLayer.

    A GameComponent reached through a parent's `components` dict is driven by
    the event bus, which calls `send_event_advanced`, NOT these methods. An
    override on such a class is dead code that never runs and never errors.
    Those classes bind behaviour with `bind_sync_listener` instead. See
    docs/PLAN_EVENT_SYSTEM.md.
    """

    def __init__(self,
                 image: surface.Surface | None = None,
                 depth: int = 0,
                 priority: int = 0):
        self._image: surface.Surface | None = image
        """The object's surface, if it owns one.

        Single-underscore and declared exactly once in the hierarchy. There
        used to be three name-mangled slots down one MRO --
        _PyoneerGameObject__image, _GameComponent__image and
        _DrawComponent__image -- so `image` meant a different variable
        depending on which class's code was executing, and
        GameComponent.image read a slot that was never assigned
        anywhere and raised AttributeError for any subclass that did not
        override it.
        """
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
    def core_lifecycle_build(self, event: Optional[PyoneerEvent] = None):
        """Called when the object is created."""
        pass

    def core_frame_update_pre(self, event: Optional[PyoneerEvent] = None):
        """Called before the update method."""
        if DEBUGGING:
            print(f"pre_update not implemented on object; ", self.__class__.__name__, " - ", self.__class__.__module__)

    @abstractmethod
    def core_frame_update(self, event: Optional[PyoneerEvent] = None):
        """Called every frame. dt is the time in seconds since the last frame."""

    def core_frame_update_post(self, event: Optional[PyoneerEvent] = None):
        """Called after the update method."""
        if DEBUGGING:
            print(f"post_update not implemented on object; ", self.__class__.__name__, " - ", self.__class__.__module__)

    def core_lifecycle_dispose_pre(self, event: Optional[PyoneerEvent] = None):
        """Called before the dispose method."""
        if DEBUGGING:
            print(f"pre_dispose not implemented on object; ", self.__class__.__name__, " - ", self.__class__.__module__)

    @abstractmethod
    def core_lifecycle_dispose(self, event: Optional[PyoneerEvent] = None) -> bool:
        """Called when the object is destroyed."""
        return True

    def core_lifecycle_dispose_post(self, event: Optional[PyoneerEvent] = None):
        """Called after the dispose method."""
        if DEBUGGING:
            print(f"post_dispose not implemented on object; ", self.__class__.__name__, " - ", self.__class__.__module__)

    def core_lifecycle_prepare_pre(self, event: Optional[PyoneerEvent] = None):
        """Called before the prepare method."""
        if DEBUGGING:
            print(f"pre_prepare not implemented on object; ", self.__class__.__name__, " - ", self.__class__.__module__)

    @abstractmethod
    def core_lifecycle_prepare(self, event: Optional[PyoneerEvent] = None) -> surface:
        """Called when the object is created."""

    def core_lifecycle_prepare_post(self, event: Optional[PyoneerEvent] = None):
        """Called after the prepare method."""
        if DEBUGGING:
            print(f"post_prepare not implemented on object; ", self.__class__.__name__, " - ", self.__class__.__module__)

    @property
    def image(self) -> surface.Surface | None:
        """The surface this object contributes to the frame, or None.

        An accessor, not a lifecycle step -- which is why it is a property
        rather than `core_image()`. The old method took an optional
        `image_in` argument and was a getter and setter wearing one name,
        so a call site could not be read as one or the other.

        Subclasses that compute their surface (an animation frame, a clipped
        sub-image) override the getter.
        """
        return self._image

    @image.setter
    def image(self, value: surface.Surface | None):
        self._image = value

    def require_image(self) -> surface.Surface:
        """Return the image, or raise naming the object that lacks one.

        For the render path, where a None surface otherwise fails much later
        inside pygame's blits() with no clue which object queued it.
        """
        current = self.image
        if current is None:
            raise PyoneerImageMissingError(self)
        return current

    def core_render_blits(self, event: Optional[PyoneerEvent]):
        """Return all prepared blits."""
        pass

    @abstractmethod
    def core_input_receive(self, events: Optional[PyoneerEvent]):
        """Buffer the program events."""
        pass
