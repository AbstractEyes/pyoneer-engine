from typing import Optional

from pygame import Rect, Vector2

from scripts.core.component import GameComponent
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType


class GameTransform(GameComponent):

    def __init__(self, host: GameComponent, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__host: GameComponent = host
        self.__local_bounds: Rect = Rect(0, 0, 0, 0)
        self.__world_bounds: Rect = Rect(0, 0, 0, 0)
        self.__offset: Vector2 = Vector2(0, 0)
        self.__rotation: float = 0.0
        self.__scale: Vector2 = Vector2(1, 1)
        self.__depth: int = 0

    def core_prepare(self, event: Optional[PyoneerEvent] = None):
        super().core_prepare(event)

        if not self.flags.get("prepared_transform", False):
            self.bind_sync_listener(GameEventType.TRANSFORM, self.__transform_event)
            self.flags["prepared_transform"] = True
        return self.send_event_to_children_advanced(GameEventType.PREPARE, event)

    def __transform_event(self, event: Optional[PyoneerEvent] = None):
        if event is not None:
            position = event.data.get("position", None)
            scale = event.data.get("scale", None)
            rotation = event.data.get("rotation", None)
            if position is Vector2:
                self.move(event.data["position"].x, event.data["position"].y)
            elif position is tuple:
                self.move(event.data["position"][0], event.data["position"][1])
            elif position is Rect:
                self.move(event.data["position"].x, event.data["position"].y)
            if scale is Vector2:
                self.scale(event.data["scale"])
            elif scale is tuple:
                self.scale(Vector2(event.data["scale"][0], event.data["scale"][1]))
            elif scale is float:
                self.scale(Vector2(event.data["scale"], event.data["scale"]))
            if rotation is float:
                self.rotate(event.data["rotation"])
            elif rotation is tuple:
                self.rotate(event.data["rotation"][0])
            elif rotation is int:
                self.rotate(event.data["rotation"] / 360.0)


    def move(self, x: int, y: int):
        self.__offset.x += x
        self.__offset.y += y
        self.__world_bounds.x += x
        self.__world_bounds.y += y