from abc import ABC

from event_types import GameEventType, EventPriority
from simple_component import SimpleComponent

class PyoneerGameCallable:
    def __init__(self, callable: callable):
        self.callable = callable

    def __call__(self, *args, **kwargs):
        self.callable(*args, **kwargs)


class Behavior(ABC):
    def __init__(self, name: str):
        self.name = name
        self.listeners: dict[GameEventType, list[callable]] = {}

    def bind_listener(self, event_type: GameEventType, callback: callable,
                      priority: EventPriority = EventPriority.NORMAL):
        if event_type not in self.listeners:
            self.listeners[event_type] = []
        self.listeners[event_type].append(callback)

    def call(self, event: GameEventType, *args, **kwargs):
        for listener in self.listeners[event]:
            listener(*args, **kwargs)

    def create(self, component: SimpleComponent): ...
    """Called when the behavior is created, must have valid component to modify."""
    def destroy(self): ...
    """Called when the behavior is destroyed."""
