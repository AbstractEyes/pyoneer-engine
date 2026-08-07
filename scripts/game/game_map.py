from typing import Optional

import pytmx
from pygame import surface

from scripts.core.event_manager import PyoneerEvent
from scripts.core.game_object import PyoneerGameObject


class GameMap(PyoneerGameObject):

    def __init__(self, tmx_data: pytmx.TiledMap):
        super().__init__()
        self.tmx_data = tmx_data
        self.width = tmx_data.width
        self.height = tmx_data.height
        self.depth_map = [[0 for x in range(self.width)] for y in range(self.height)]

    def create_depth_map(self):
        for layer in self.tmx_data.visible_layers:
            if isinstance(layer, pytmx.TiledTileLayer):
                for x, y, gid in layer:
                    self.depth_map[y][x] = gid

    def core_lifecycle_build(self, event: Optional[PyoneerEvent] = None):
        super().core_lifecycle_build(event)

    def core_input_receive(self, event: Optional[PyoneerEvent] = None):
        super().core_input_receive(event)

    def core_frame_update(self, event: Optional[PyoneerEvent] = None):
        super().core_frame_update(event)

    def core_lifecycle_dispose(self, event: Optional[PyoneerEvent] = None) -> bool:
        super().core_lifecycle_dispose(event)

    def core_lifecycle_prepare(self, event: Optional[PyoneerEvent] = None):
        super().core_lifecycle_prepare(event)
        self.create_depth_map()

    def core_lifecycle_prepare_pre(self, event: Optional[PyoneerEvent] = None) -> None:
        super().core_lifecycle_prepare_pre(event)

    def core_lifecycle_prepare_post(self, event: Optional[PyoneerEvent] = None) -> None:
        super().core_lifecycle_prepare_post(event)