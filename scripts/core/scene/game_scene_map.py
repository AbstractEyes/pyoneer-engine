from typing import Optional

from scripts.core.event_manager import PyoneerEvent
from scripts.core.scene.game_scene import GameScene


class GameSceneMap(GameScene):
    """A scene whose contents come from a map file.

    The entities are NOT loaded here: binding the GameMap is what loads them.
    `renderer.bind(GameMap)` rasterizes the tile layers, spawns every typed
    object on the object layers and binds it into an `EntityLayer`, and
    `SceneManager.bind` binds those same entities into the scene so they get
    frame updates -- all through the ordinary `scene.bind("MAP", game_map)`
    call, which is why this class adds nothing to it.

    Nothing says which spawned entity the camera should follow, because
    nothing in the tmx marks one. See MainGame.spawn_arguments.
    """

    def __init__(self, name: str):
        super().__init__(name)

    def core_lifecycle_build(self, event: Optional[PyoneerEvent] = None):
        super().core_lifecycle_build(event)
