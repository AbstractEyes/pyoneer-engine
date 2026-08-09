from __future__ import annotations
from typing import Callable

import pygame
from pygame import Surface

from scripts.core.event_types import GameEventType
from scripts.core.game_object import PyoneerGameObject
from scripts.core.renderer import LayerRenderer
from scripts.core.scene.game_scene import GameScene
from scripts.game.entity.game_entity import GameEntity
from scripts.game.game_camera import GameCamera

from scripts.core.depth import OBJECT_CONVERTER, OBJECT_DEPTH, MAP_DEPTH

import scripts.core.event_manager as EventManager
from scripts.core.event_manager import PyoneerEvent
from scripts.core.errors import PyoneerSceneError


class SceneManager:
    def __init__(self, game):
        self.game = game
        self.scenes: dict[str, GameScene] = {}
        self.current_scene: GameScene | None = None
        self.renderer: LayerRenderer | None = None
        self.camera: GameCamera | None = None
        # event.type-keyed routes, unlike the scene fan-out in inputs(), which
        # dispatches everything under the constant INPUTS and lets
        # AsyncEventComponent re-key it. Must stay inside the class body: the
        # name mangling on __on_window_resize only resolves here.
        self.routes: dict[GameEventType, Callable] = {
            GameEventType.WINDOW_RESIZE: self.__on_window_resize,
        }

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
            raise PyoneerSceneError(
                f"no current scene to bind {type(game_object).__name__} into "
                f"at {depth_or_definition!r}; call set_scene() first"
            )

    def add_scene(self, name: str, scene: GameScene):
        self.scenes[name] = scene

    def set_scene(self, name: str):
        self.current_scene = self.scenes[name]

    def pre_update(self, delta: float):
        self.inputs()
        self.current_scene.core_frame_update_pre(delta)

    def update(self, delta: float):
        if self.camera:
            self.camera.update()
        self.current_scene.core_frame_update(delta)
        if self.renderer:
            self.renderer.update(delta)

    def post_update(self, delta: float):
        self.current_scene.core_frame_update_post(delta)

    def inputs(self):
        events = EventManager.get_pyo()
        for event in events:
            # A route runs IN ADDITION to the scene fan-out below, never
            # instead of it -- and MUST NOT call event.handle():
            # GameComponent.__send_event returns immediately on a handled
            # event, so consuming here would silently cut the entire
            # component tree out of that frame's input.
            route = self.routes.get(event.type)
            if route is not None:
                route(event)
            self.current_scene.core_input_receive(event)

    def __on_window_resize(self, event: PyoneerEvent):
        """Re-take the display surface at the new size and re-point everything
        that cached the old one. The renderer holding a stale surface is the
        failure mode that produces a black frame with no exception."""
        width, height = event.event.x, event.event.y
        self.game.screen = pygame.display.set_mode((width, height),
                                                   pygame.RESIZABLE)
        if self.renderer is not None:
            self.renderer.image(self.game.screen)
        if self.camera is not None:
            self.camera.view_area.size = (width, height)