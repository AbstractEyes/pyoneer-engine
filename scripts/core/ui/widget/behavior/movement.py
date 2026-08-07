from logging import debug

from scripts.core.ui.widget.behavior.async_ import AsyncEventComponent
from scripts.core.event_types import GameEventType


class Movement(AsyncEventComponent):
    """A component designated to enable component movement."""

    EVENT_TYPES = {
        GameEventType.TRANSFORM_COMPONENT,
        GameEventType.RESIZE_COMPONENT,
        GameEventType.MOUSE_MOTION,
        GameEventType.MOUSE_DOWN,
        GameEventType.MOUSE_UP,
        GameEventType.MOUSE_SCROLL
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.movement_callbacks: dict[GameEventType, list[callable]] = {}
        """The movement callbacks for the movement component."""
        self.__make()

    def bind_movement_listener(self, event_type: GameEventType, callback: callable):
        if event_type in self.EVENT_TYPES:
            if event_type in self.movement_callbacks:
                self.movement_callbacks[event_type].append(callback)
            else:
                self.movement_callbacks[event_type] = [callback]
        else:
            debug("Invalid event type for movement listener.")

    def __make(self):
        self.bind_async_listener(GameEventType.MOUSE_MOTION, self.__mouse_move)
        self.bind_async_listener(GameEventType.MOUSE_DOWN, self.__mouse_down)
        self.bind_async_listener(GameEventType.MOUSE_UP, self.__mouse_up)
        self.bind_async_listener(GameEventType.MOUSE_SCROLL, self.__mouse_scroll)
        self.bind_async_listener(GameEventType.TRANSFORM_COMPONENT, self.__move_widget)
        self.bind_async_listener(GameEventType.RESIZE_COMPONENT, self.__resize_widget)