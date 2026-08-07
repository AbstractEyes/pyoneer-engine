from typing import Optional

from scripts.core.event_manager import PyoneerEvent
from scripts.core.scene.game_scene import GameScene


class GameSceneMap(GameScene):

    def __init__(self, name: str):
        super().__init__(name)

    def core_lifecycle_build(self, event: Optional[PyoneerEvent] = None):
        # load the map
        # load the entities
        # load the player
        # load the UI
        pass