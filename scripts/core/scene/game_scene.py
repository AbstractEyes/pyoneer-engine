from __future__ import annotations
# A scene manager for the game's scene flow.

from pygame import Surface, surface

from scripts.core.event_manager import PyoneerEvent
from scripts.core.game_object import PyoneerGameObject
from typing import TYPE_CHECKING, Optional

from event_types import GameEventType

if TYPE_CHECKING:
    from component import GameComponent


class GameScene(PyoneerGameObject):

    def __init__(self, name: str):
        super().__init__()
        self.name: str = name
        self.__game_objects: dict[str, list[PyoneerGameObject]] = {}

    def core_build(self, event: Optional[PyoneerEvent] = None):
        for game_object_type, game_object_list in self.__game_objects.items():
            for game_object in game_object_list:
                if event is not None:
                    game_object.core_build(event)
                else:
                    game_object.core_build(self.__make_event(GameEventType.BUILD))

    def core_pre_prepare(self, event: Optional[PyoneerEvent] = None):
        for game_object_type, game_object_list in self.__game_objects.items():
            for game_object in game_object_list:
                if event is not None:
                    game_object.core_pre_prepare(event)
                else:
                    game_object.core_pre_prepare(self.__make_event(GameEventType.PRE_PREPARE))

    def core_prepare(self, event: Optional[PyoneerEvent] = None):
        for game_object_type, game_object_list in self.__game_objects.items():
            for game_object in game_object_list:
                if event is not None:
                    game_object.core_prepare(event)
                else:
                    game_object.core_prepare(self.__make_event(GameEventType.PREPARE))

    def core_post_prepare(self, event: Optional[PyoneerEvent] = None):
        for game_object_type, game_object_list in self.__game_objects.items():
            for game_object in game_object_list:
                game_object.core_post_prepare(self.__make_event(GameEventType.POST_PREPARE))

    def __make_event(self, event_type: GameEventType, data: dict = {}):
        return PyoneerEvent(event_type, sender=self, data=data)

    def bind(self, object_type: str | int, game_object: PyoneerGameObject | list[PyoneerGameObject] | GameComponent | list[GameComponent]):
        if object_type in self.__game_objects:
            if isinstance(game_object, list):
                self.__game_objects[object_type].extend(game_object)
            else:
                self.__game_objects[object_type].append(game_object)
        else:
            self.__game_objects[object_type] = [game_object]

    def unbind(self, object_type: str, game_object: PyoneerGameObject):
        if object_type in self.__game_objects:
            self.__game_objects[object_type].remove(game_object)

    def begin(self, event: Optional[PyoneerEvent] = None):
        if not self.flags.get("active"):
            for game_object_type, game_object_list in self.__game_objects.items():
                for game_object in game_object_list:
                    game_object.core_prepare(self.__make_event(GameEventType.PREPARE))
            self.flags["active"] = True

    def core_pre_dispose(self, event: Optional[PyoneerEvent] = None):
        for game_object_type, game_object_list in self.__game_objects.items():
            for game_object in game_object_list:
                game_object.core_pre_dispose(self.__make_event(GameEventType.PRE_DISPOSE))

    def core_dispose(self, event: Optional[PyoneerEvent] = None):
        for game_object_type, game_object_list in self.__game_objects.items():
            for game_object in game_object_list:
                game_object.core_dispose()

    def core_post_dispose(self, event: Optional[PyoneerEvent] = None):
        for game_object_type, game_object_list in self.__game_objects.items():
            for game_object in game_object_list:
                game_object.core_post_dispose()

    def core_pre_update(self, delta: float):
        for game_object_type, game_object_list in self.__game_objects.items():
            for game_object in game_object_list:
                game_object.core_pre_update(self.__make_event(GameEventType.PRE_UPDATE, data={"delta": delta}))

    def core_update(self, delta: float):
        for game_object_type, game_object_list in self.__game_objects.items():
            for game_object in game_object_list:
                game_object.core_update(self.__make_event(GameEventType.UPDATE, data={"delta": delta}))

    def core_post_update(self, delta: float):
        for game_object_type, game_object_list in self.__game_objects.items():
            for game_object in game_object_list:
                game_object.core_post_update(self.__make_event(GameEventType.POST_UPDATE, data={"delta": delta}))

    def core_blits(self, *args, **kwargs) -> list[tuple[Surface, tuple[float | int, float | int]]]:
        return []

    def core_image(self, image_in: surface.Surface | None = None) -> surface.Surface:
        # todo: to remove
        pass

    def core_inputs(self, event: Optional[PyoneerEvent] = None):
        for game_object_type, game_object_list in self.__game_objects.items():
            for game_object in game_object_list:
                game_object.core_inputs(event)
