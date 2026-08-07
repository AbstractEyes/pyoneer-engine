from __future__ import annotations

from typing import Callable, Optional
import pygame

from scripts.core.event_manager import PyoneerEvent
from scripts.core.game_object import PyoneerGameObject
from scripts.core.event_types import GameEventType
from scripts.core.component import GameComponent
from scripts.core.log import trace_lifecycle


class AsyncEventComponent(GameComponent):
    """Accepts and processes input events."""
    def __init__(self,
                 listeners: dict[int, list[pygame.event.EventType]] | None = None,
                 *args,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.active: bool = True
        trace_lifecycle("buffered event component ready on %s",
                        type(self.parent).__name__ if self.parent else "<unparented>")
        """On/Off switch for this component's input functionality."""
        self.accepts_inputs: bool = True
        """Accepts input events currently."""
        self.auto_clear: bool = True
        """Automatically clears the event buffer on the post_update call, effectively dumping the events."""
        self.async_callbacks: dict[GameEventType, list[Callable]] = listeners if listeners is not None else {}
        self.event_buffer: dict[GameEventType, list[PyoneerEvent]] = {}
        """A list of pygame event types to listen for."""
        self.bind_sync_listener(GameEventType.INPUTS, self.buffer_custom_events)
        self.bind_sync_listener(GameEventType.UPDATE, self.__update_custom_events)
        self.bind_sync_listener(GameEventType.POST_UPDATE, self.__post_update_custom_events)

    def bind_async_listener(self, event_type: GameEventType, callback: Callable):
        """Bind a custom event to a callback."""
        if event_type in self.async_callbacks:
            self.async_callbacks[event_type].append(callback)
        else:
            self.async_callbacks[event_type] = [callback]

    def unbind_async_listener(self, event_type: GameEventType, callback: Callable = None):
        """Unbind a custom event from a callback."""
        if callback is None:
            if event_type in self.async_callbacks:
                self.async_callbacks[event_type].clear()
                return
        if event_type in self.async_callbacks:
            if callback in self.async_callbacks[event_type]:
                self.async_callbacks[event_type].remove(callback)

    def clear_custom_events(self):
        self.event_buffer.clear()

    def buffer_custom_events(self, event: PyoneerEvent | None, sender: Optional[PyoneerGameObject] = None):
        """
            A mid-level buffer point for input processing.
            TODO: Implement async input buffering in the future.
            for now this is meant to be updated every frame.
            may as well be a different type of update currently. \n
            \n
            Args:
            - data: A dictionary of pygame.event.Event object lists;-
                - the captured events are grabbed from the core EventManager.
        """
        if event is not None:
            if event.type in self.event_buffer:
                self.event_buffer[event.type].append(event)
            else:
                self.event_buffer[event.type] = [event]

    def __post_update_custom_events(self, dt: float, *args, **kwargs):
        if len(self.event_buffer) > 0:
            self.clear_custom_events()

    def __update_custom_events(self, event: Optional[PyoneerEvent]):
        """This needs a proper return value branching rewrite."""
        #super().update(event)
        if isinstance(self, AsyncEventComponent) and self.accepts_inputs and event is not None:
            if self.active and len(self.event_buffer) > 0 and len(self.async_callbacks) > 0:
                for event_type, event_list in self.event_buffer.items():
                    if event_type in self.async_callbacks:
                        for callback in self.async_callbacks[event_type]:
                            for event in event_list:
                                callback(event)
        return None

