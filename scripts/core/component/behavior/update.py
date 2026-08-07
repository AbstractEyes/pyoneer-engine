from typing import Optional

from behavior import Behavior
from event_manager import PyoneerEvent
from event_types import GameEventType
from simple_component import SimpleComponent


class Update(Behavior):

    def __init__(self, *args, **kwargs):
        super().__init__("update")

    def pre_update(self, event: Optional[PyoneerEvent]): ...

    def update(self, event: Optional[PyoneerEvent]): ...

    def post_update(self, event: Optional[PyoneerEvent]): ...

    def create(self, component: Optional[SimpleComponent]):
        self.bind_listener(GameEventType.PRE_UPDATE, self.pre_update)
        self.bind_listener(GameEventType.UPDATE, self.update)
        self.bind_listener(GameEventType.POST_UPDATE, self.post_update)
