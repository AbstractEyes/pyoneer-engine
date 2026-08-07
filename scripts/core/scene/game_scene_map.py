from typing import Optional

from event_manager import PyoneerEvent
from scripts.core.scene.game_scene import GameScene


class GameSceneMap(GameScene):

    def __init__(self, name: str):
        super().__init__(name)

    def core_build(self, event: Optional[PyoneerEvent] = None):
        # load the map
        # load the entities
        # load the player
        # load the UI
        pass