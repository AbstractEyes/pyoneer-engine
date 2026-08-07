from typing import Optional

import pytmx
from pygame import surface

from event_manager import PyoneerEvent
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

    def core_build(self, event: Optional[PyoneerEvent] = None):
        super().core_build(event)

    def core_inputs(self, event: Optional[PyoneerEvent] = None):
        super().core_inputs(event)

    def core_update(self, event: Optional[PyoneerEvent] = None):
        super().core_update(event)

    def core_dispose(self, event: Optional[PyoneerEvent] = None) -> bool:
        super().core_dispose(event)

    def core_image(self, image_in: surface.Surface | None = None) -> surface.Surface:
        return super().core_image(image_in)

    def core_prepare(self, event: Optional[PyoneerEvent] = None):
        super().core_prepare(event)
        self.create_depth_map()

    def core_pre_prepare(self, event: Optional[PyoneerEvent] = None) -> None:
        super().core_pre_prepare(event)

    def core_post_prepare(self, event: Optional[PyoneerEvent] = None) -> None:
        super().core_post_prepare(event)