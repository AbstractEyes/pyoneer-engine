from __future__ import annotations

from enum import Enum
from typing import Optional

import pygame


class EventPriority(Enum):
    """Event priority levels."""
    NO_PRIORITY = 0
    """No priority, will default to normal."""
    LOWEST = 1
    """Lowest priority."""
    LOWER = 2
    """A lower priority."""
    LOW = 3
    """Low priority."""
    BELOW_NORMAL = 4
    """Below normal priority."""
    NORMAL = 5
    """Normal priority."""
    ABOVE_NORMAL = 6
    """Above normal priority."""
    HIGH = 7
    """High priority."""
    HIGHER = 8
    """A higher priority."""
    TOP = 9
    """Top priority, will be processed first in order based on values added."""


class GameEventType(tuple[str, Optional[pygame.event.Event]], Enum):
    """Core event types."""

    # ---------------------------------------------------------------- #
    # SCENE managed events
    PYGAME = ("pygame", None)
    """A standard pygame event, mostly wrappered for custom events."""
    BUILD = ("build", None)
    """A scene or component is being built."""
    INPUTS = ("inputs", None)
    """Input events, distributed through the input manager."""

    PRE_PREPARE = ("pre_prepare", None)
    """A scene is being prepared, pre build event."""
    PREPARE = ("prepare", None)
    """A scene is being prepared, post build event."""
    POST_PREPARE = ("post_prepare", None)
    """A scene is being prepared, post build event."""

    PRE_UPDATE = ("pre_update", None)
    """An update if an object is required to update before the main update loop."""
    UPDATE = ("update", None)
    """The main update loop."""
    POST_UPDATE = ("post_update", None)
    """An update if an object is required to update after the main update loop."""

    PRE_DISPOSE = ("pre_dispose", None)
    """Preliminary action to a scene being disposed."""
    DISPOSE = ("dispose", None)
    """A scene is being disposed."""
    POST_DISPOSE = ("post_dispose", None)
    """A scene has been disposed."""

    REBUILD = ("rebuild", None)
    """A scene is being rebuilt."""
    BLITS = ("blits", None)
    """Blit events, distributed through the entity and ui component subsystems with the blit manager."""
    USE = ("use", None)
    CUSTOM_EVENT = ("custom_event", None)

    SHOW = ('show', None)
    HIDE = ('hide', None)

    ACTIVATE = ('activate', None)
    """A component or object being activated."""
    DEACTIVATE = ('deactivate', None)
    """A component or object being deactivated."""

    TRANSFORM = ('transform', None)
    """An object is transformed."""

    # standard pygame events to convert to custom events
    MOUSE_MOTION = ('mouse_motion', pygame.MOUSEMOTION)
    """Mouse moved event."""
    MOUSE_DOWN = ('mouse_down', pygame.MOUSEBUTTONDOWN)
    """Mouse button pressed."""
    MOUSE_UP = ('mouse_up', pygame.MOUSEBUTTONUP)
    """Mouse button released."""
    MOUSE_SCROLL = ('mouse_scroll', pygame.MOUSEWHEEL)
    """Mouse wheel scrolled."""
    MOUSE_CLICK = ('mouse_click', None)
    """Mouse button clicked anywhere."""
    MOUSE_DOUBLE_CLICK = ('mouse_double_click', None)
    """Mouse button double clicked anywhere."""

    # mouse events
    MOUSE_DOWN_INSIDE = ('mouse_down_inside', None)
    """Mouse button pressed inside the target component."""
    MOUSE_UP_INSIDE = ('mouse_up_inside', None)
    """Mouse button released inside the target component."""
    MOUSE_DOWN_OUTSIDE = ('mouse_down_outside', None)
    """Mouse button pressed outside the target component."""
    MOUSE_UP_OUTSIDE = ('mouse_up_outside', None)
    """Mouse button released outside the target component."""
    MOUSE_DRAGGING = ('mouse_dragging', None)
    """Mouse button held down and is currently dragging."""
    MOUSE_DRAG_BEGIN = ('mouse_drag_begin', None)
    """Mouse button held down and moved."""
    MOUSE_DRAG_END = ('mouse_drag_end', None)
    """When the mouse is released after dragging."""
    MOUSE_CLICK_INSIDE = ('mouse_click_inside', None)
    """Mouse button clicked inside the target component."""
    MOUSE_DOUBLE_CLICK_INSIDE = ('mouse_double_click_inside', None)
    """Mouse button double clicked inside the target component."""

    # viewport event
    VIEWPORT_SCROLLED = ('viewport_scrolled', None)
    """The current viewport was scrolled, the contents internally move and the viewports updated."""

    # parent/child specific events

    PARENT_CHANGED = ('parent_changed', None)
    """The parent object changed."""
    PARENT_RESIZED = ('parent_resized', None)
    """The parent object resized."""

    # component specific events
    MOUSE_ENTER = ('mouse_enter', None)
    """Mouse entered the component"""
    MOUSE_LEAVE = ('mouse_leave', None)
    """Mouse left the component"""

    # keyboard events
    KEY_DOWN = ('key_down', pygame.KEYDOWN)
    KEY_UP = ('key_up', pygame.KEYUP)
    KEY_REPEAT = ('key_repeat', None)

    # gamepad events
    GAMEPAD_BUTTON_PRESSED = ('gamepad_button_pressed', pygame.JOYBUTTONDOWN)
    GAMEPAD_BUTTON_RELEASED = ('gamepad_button_released', pygame.JOYBUTTONUP)
    GAMEPAD_BUTTON_HELD = ('gamepad_button_held', None)
    GAMEPAD_AXIS = ('gamepad_axis', pygame.JOYAXISMOTION)
    GAMEPAD_HAT = ('gamepad_hat', pygame.JOYHATMOTION)

    # pygame window events
    QUIT = ('quit', pygame.QUIT)
    WINDOW_RESIZE = ('window_resize', pygame.WINDOWRESIZED)
    WINDOW_FOCUS_LOST = ('window_focus', pygame.WINDOWFOCUSLOST)
    WINDOW_FOCUS_GAINED = ('window_focus', pygame.WINDOWFOCUSGAINED)
    USER_EVENT = ('user_event', pygame.USEREVENT)

