from __future__ import annotations

from logging import debug
from typing import Callable

import pygame
from pygame import Vector2

from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.ui.widget.behavior.async_ import AsyncEventComponent
import scripts.core.event_manager as EventManager


class MouseComponentAsync(AsyncEventComponent):
    EVENT_TYPES = [
        GameEventType.MOUSE_DOWN,
        GameEventType.MOUSE_UP,
        GameEventType.MOUSE_MOTION,
        GameEventType.MOUSE_SCROLL,
        GameEventType.MOUSE_ENTER,
        GameEventType.MOUSE_LEAVE,
        GameEventType.MOUSE_DOWN_INSIDE,
        GameEventType.MOUSE_UP_INSIDE,
        GameEventType.MOUSE_DOWN_OUTSIDE,
        GameEventType.MOUSE_UP_OUTSIDE,
        GameEventType.MOUSE_DRAGGING,
        GameEventType.MOUSE_CLICK_INSIDE,
        GameEventType.MOUSE_DOUBLE_CLICK_INSIDE,
    ]

    def __init__(self, whitelist: list[int] | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buttons: list[int] = [1, 2, 3, 4, 5, 6, 7, 8] if whitelist is None else whitelist
        """The button whitelist for mouse events, primarily left on all buttons."""
        self.mouse_down: bool = False
        """If the mouse is down anywhere."""
        self.mouse_inside: bool = False
        """If the mouse is inside the component."""
        self.mouse_down_inside: bool = False
        """If the mouse was set to down inside the component."""
        self.mouse_down_outside: bool = False
        """If the mouse was set to down outside of the component."""
        self.mouse_down_time: float = 0
        """The time in seconds the mouse has been down."""
        self.mouse_down_pos: Vector2 = Vector2(0, 0)
        """The position of the mouse when it was pressed down."""
        self.mouse_up_pos: Vector2 = Vector2(0, 0)
        """The position of the mouse when it was released."""
        self.dragging: bool = False
        """If the mouse is currently dragging."""
        # ---------------------------------------------------------------- #
        self.vertical_mouse_scroll: int = 0
        """The amount of scroll the mouse has input this event frame."""
        self.horizontal_mouse_scroll: int = 0
        """The amount of scroll the mouse has input this event frame."""
        # ---------------------------------------------------------------- #
        self.mouse_drag_delay: float = 0.5
        """The time in seconds before a mouse down is considered a drag."""
        self.mouse_drag_trigger_distance: float = 10
        """The distance in pixels the mouse must move to trigger a drag."""
        # ---------------------------------------------------------------- #
        self.click_trigger_time: float = 0.4
        """The max amount of time in seconds after a mousedown to consider mouseup as a click."""
        self.dclick_trigger_time: float = 1.0
        """The max amount of time in seconds between two clicks to consider a double click."""
        self.last_click_time: float = 0
        """The last successful click's stored timer."""
        # ---------------------------------------------------------------- #
        self.mouse_listeners: dict[GameEventType, list[Callable]] = {}
        self.core_prepare()
        self.core_build()

    def has_mouse_listener(self, event_type: GameEventType) -> bool:
        return event_type in self.mouse_listeners

    def bind_mouse_listener(self, event_type: GameEventType, callback: Callable):
        #self.bind_async_listener(event_type, callback)
        if event_type in self.EVENT_TYPES:
            if event_type in self.mouse_listeners:
                self.mouse_listeners[event_type].append(callback)
            else:
                self.mouse_listeners[event_type] = [callback]
        else:
            debug("Invalid event type for mouse listener.")

    def unbind_mouse_listener(self, event_type: GameEventType = None, callback: Callable = None):
        #self.unbind_async_listener(event_type, callback)
        if event_type is None:
            self.mouse_listeners.clear()
            return
        if callback is None:
            if event_type in self.mouse_listeners:
                self.mouse_listeners[event_type].clear()
                return
        if event_type in self.mouse_listeners:
            if callback in self.mouse_listeners[event_type]:
                self.mouse_listeners[event_type].remove(callback)

    def core_prepare(self, event: PyoneerEvent | None = None):
        super().core_prepare(event)
        if not self.flags.get("prepared_mouse", False):
            self.bind_async_listener(GameEventType.MOUSE_MOTION, self.__event__mouse_move)
            self.bind_async_listener(GameEventType.MOUSE_DOWN, self.__event__mouse_down)
            self.bind_async_listener(GameEventType.MOUSE_UP, self.__event__mouse_up)
            self.bind_async_listener(GameEventType.MOUSE_SCROLL, self.__event__mouse_scroll)
            self.flags["prepared_mouse"] = True

    def send_mouse_event(self, event: PyoneerEvent):
        self.buffer_custom_events(event)

    def __event__mouse_scroll(self, event: PyoneerEvent):
        if event is None or event.handled:
            return
        if self.mouse_inside:
            self.vertical_mouse_scroll = event.event.y
            self.horizontal_mouse_scroll = event.event.x
            if self.vertical_mouse_scroll != 0 or self.horizontal_mouse_scroll != 0:
                self.__execute_event_callbacks(GameEventType.MOUSE_SCROLL,
                                               PyoneerEvent(event_type=GameEventType.MOUSE_SCROLL,
                                                            data={
                                                                "horizontal_scroll": self.horizontal_mouse_scroll,
                                                                "vertical_scroll": self.vertical_mouse_scroll
                                                            }))

    @staticmethod
    def __unpack_mouse_move(data: list[PyoneerEvent]) -> list[Vector2]:
        return [vec.event.pos for vec in data]

    def __event__mouse_entered(self, event: PyoneerEvent):
        if event is None or event.handled:
            return
        if not self.mouse_inside and event is not None and not event.handled:
            self.mouse_inside = True
            self.__execute_event_callbacks(GameEventType.MOUSE_ENTER, event, False)

    def __execute_event_callbacks(self,
                                  event_type: GameEventType,
                                  event: list[PyoneerEvent] | PyoneerEvent,
                                  consumes: bool = False) -> None:
        if event_type not in self.mouse_listeners:
            return
        handled = False
        for callback in self.mouse_listeners[event_type]:
            if isinstance(event, list):
                for event in event:
                    if event.handled:
                        handled = True
                        break  # something else handled the event, so we break loop for this event type
                    callback(event)
                    if event.handled:
                        handled = True
                        break
                    if consumes:
                        self.mark_event_handled(event)
                if handled:
                    break
            else:
                if event.handled:
                    break
                callback(event)
                if consumes:
                    self.mark_event_handled(event)
                if event.handled:
                    break

    def __event__mouse_exited(self, event: PyoneerEvent):
        if event is None or event.handled:
            return
        if self.mouse_inside and event is not None and not event.handled:
            self.mouse_inside = False
            self.__execute_event_callbacks(GameEventType.MOUSE_LEAVE, event, False)

    def __event__mouse_down(self, event: PyoneerEvent | None):
        if event is None or event.handled is True:
            return
        self.mouse_down = True
        self.mouse_down_time = pygame.time.get_ticks()
        self.mouse_down_pos = Vector2(event.event.pos)
        if self.mouse_inside:
            self.mouse_down_outside = False
            self.mouse_down_inside = True
            self.__execute_event_callbacks(GameEventType.MOUSE_DOWN_INSIDE, event, False)
        elif not self.mouse_inside:
            self.mouse_down_inside = False
            self.mouse_down_outside = True
            self.__execute_event_callbacks(GameEventType.MOUSE_DOWN_OUTSIDE, event, False)
        self.__execute_event_callbacks(GameEventType.MOUSE_DOWN, event, False)

    def __event__mouse_up(self, event: PyoneerEvent | None):
        if event is None or event.handled:
            return
        position = Vector2(event.event.pos)
        self.mouse_up_pos = Vector2(position.x, position.y)
        if self.mouse_inside:
            # Mouse is inside and the mouse click was released.
            self.__execute_event_callbacks(GameEventType.MOUSE_UP_INSIDE, event, False)
            if self.mouse_down_inside:
                if pygame.time.get_ticks() - self.mouse_down_time < self.click_trigger_time * 1000:
                    if self.has_mouse_listener(GameEventType.MOUSE_DOUBLE_CLICK_INSIDE):
                        if pygame.time.get_ticks() - self.last_click_time < self.dclick_trigger_time * 1000:
                            self.last_click_time = 0
                            self.__execute_event_callbacks(GameEventType.MOUSE_DOUBLE_CLICK_INSIDE, event, False)
                        else:
                            self.last_click_time = pygame.time.get_ticks()
                            self.__execute_event_callbacks(GameEventType.MOUSE_CLICK_INSIDE, event, False)
                    else:
                        self.__execute_event_callbacks(GameEventType.MOUSE_CLICK_INSIDE, event, False)
                #print ("Mouse click completed inside: ", self.parent, self.mouse_down_pos)
                #self.__execute_event_callbacks(GameEventType.MOUSE_CLICK_INSIDE, event, False)
            else: ...
                # print ("Mouse drag finished outside of the original point: ", self.parent, self.mouse_down_pos, self.mouse_up_pos)
               # self.__execute_event_callbacks(GameEventType.MOUSE_DRAG_END, event, False)
        elif not self.mouse_inside:
            # Mouse is outside and the mouse button is released.
            if self.mouse_down_inside:
                # print ("Mouse click completed outside: ", self.parent, self.mouse_down_pos)
                self.__execute_event_callbacks(GameEventType.MOUSE_UP_OUTSIDE, event, False)
            else:
                ...
                #print ("Mouse drag completed outside: ", self.parent, self.mouse_click_pos, self.mouse_release_pos)
                #self.__execute_event_callbacks(GameEventType.MOUSE_UP_OUTSIDE, event, False)
        self.mouse_down_time = 0
        self.mouse_down = False
        self.mouse_down_inside = False
        self.mouse_down_outside = False
        self.__execute_event_callbacks(GameEventType.MOUSE_UP, event, False)
        self.__execute_event_callbacks(GameEventType.MOUSE_DRAGGING, event, False)
        if self.dragging:
            self.dragging = False
            self.__execute_event_callbacks(GameEventType.MOUSE_DRAG_END, event, False)
    def __event__mouse_move(self, event: PyoneerEvent | None):
        if event is None or event.handled or self.parent is None:
            return
        if event is not None and not event.handled:
            pos = event.event.pos

            if self.mouse_down_inside or self.mouse_down_outside:
                self.mouse_down_time += EventManager.FRAME_DELTA
            else:
                self.mouse_down_time = 0

            if pos is not None:
                if self.parent.world_bounds.collidepoint(pos[0], pos[1]) and not self.mouse_inside:
                    self.__event__mouse_entered(event)
                elif not self.parent.world_bounds.collidepoint(pos[0], pos[1]) and self.mouse_inside:
                    self.__event__mouse_exited(event)
                if self.mouse_down_inside and self.parent.draggable and (self.mouse_down_time > self.mouse_drag_delay or
                                               self.mouse_down_pos.distance_to(Vector2(pos)) > self.mouse_drag_trigger_distance):
                    if not self.dragging:
                        self.dragging = True
                        self.__execute_event_callbacks(GameEventType.MOUSE_DRAG_BEGIN, event, False)
                    self.__execute_event_callbacks(GameEventType.MOUSE_DRAGGING, event, False)

    def __reset_mouse(self):
        self.mouse_down_inside = False
        self.mouse_down_outside = False
        self.mouse_inside = False
        self.mouse_down_time = 0
        self.mouse_down_pos = Vector2(0, 0)
        self.mouse_up_pos = Vector2(0, 0)
        self.vertical_mouse_scroll = 0
        self.horizontal_mouse_scroll = 0