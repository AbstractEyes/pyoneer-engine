from __future__ import annotations
from pygame import Surface

from scripts.core.game_object import PyoneerGameObject
from scripts.core.renderer import LayerRenderer
from scripts.core.scene.game_scene import GameScene
from scripts.game.entity.game_entity import GameEntity
from scripts.game.game_camera import GameCamera

from scripts.core.depth import OBJECT_CONVERTER, OBJECT_DEPTH, MAP_DEPTH

import scripts.core.event_manager as EventManager
from scripts.core.event_manager import PyoneerEvent


class SceneManager:
    def __init__(self, game):
        self.game = game
        self.scenes: dict[str, GameScene] = {}
        self.current_scene: GameScene | None = None
        self.renderer: LayerRenderer | None = None
        self.camera: GameCamera | None = None

    def __bind_renderer(self, renderer: LayerRenderer | None):
        self.renderer = renderer

    def __bind_camera(self, camera: GameCamera | None):
        self.renderer.bind_camera(camera)
        self.camera = camera

    def bind(self, depth_or_definition: str | int, game_object: PyoneerGameObject | GameCamera | LayerRenderer):
        if isinstance(game_object, GameCamera):
            self.__bind_camera(game_object)
            return
        elif isinstance(game_object, LayerRenderer):
            self.__bind_renderer(game_object)
            return
        if self.current_scene is not None:
            self.current_scene.bind(depth_or_definition, game_object)
            self.renderer.bind(depth_or_definition, game_object)
        else:
            raise Exception("No scene to bind to; ", depth_or_definition, game_object)

    def add_scene(self, name: str, scene: GameScene):
        self.scenes[name] = scene

    def set_scene(self, name: str):
        self.current_scene = self.scenes[name]

    def pre_update(self, delta: float):
        self.inputs()
        self.current_scene.core_pre_update(delta)

    def update(self, delta: float):
        if self.camera:
            self.camera.update()
        self.current_scene.core_update(delta)
        if self.renderer:
            self.renderer.update(delta)

    def post_update(self, delta: float):
        self.current_scene.core_post_update(delta)

    def inputs(self):
        events = EventManager.get_pyo()
        for event in events:
            self.current_scene.core_inputs(event)