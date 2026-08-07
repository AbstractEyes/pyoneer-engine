from __future__ import annotations

import uuid

from behavior import Behavior
from event_types import GameEventType


class SimpleComponent:
    def __init__(self, behaviors: dict[uuid, Behavior]):
        self.behaviors = behaviors
        self.handled_events: list[GameEventType] = []
        """List of events that the component has had flagged this frame."""
        self.uuid: str = uuid.uuid4().hex

    def bind_behavior(self, behavior: Behavior, create: bool = True):
        self.behaviors[behavior.name] = behavior
        behavior.create(self) if create else None

    def unbind_behavior(self, behavior: Behavior):
        behavior.destroy()
        del self.behaviors[behavior.name]

