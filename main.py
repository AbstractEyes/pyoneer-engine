from __future__ import annotations

import pygame
import sys
import scripts.core.event_manager as EventManager

from pygame import Rect, Surface

from scripts.core.game_object import PyoneerGameObject
from scripts.core.renderer import LayerRenderer
from scripts.core.scene.game_scene import GameScene
from scripts.game.entity.game_entity import GameEntity
from scripts.game.game_map import GameMap
from scripts.game.game_camera import GameCamera
from scripts.game.entity.game_player import GamePlayer

from config.managers.core_asset_manager import CoreAssetManager
from scripts.core.input import InputActionManager
from scripts.core.scene.scene_manager import SceneManager
from scripts.core.component import GameComponent
from scripts.core.ui.widget.containers.window import GameWindow
from scripts.game.demo_window import DemoWindow

#from widget.factory.component_factory import ComponentFactory

"""
    Conceptually; the game requires a map, a camera, and a player.
    The camera must move based on the player's movement on the map.
    The player must move based on the player's input.
    The map must be rendered based on the camera's position.
    The player must be rendered based on the camera's position.

    Conceptually; this can be accomplished by:
    1. Creating a map object.
    2. Creating a camera object.
    3. Creating a player object.
    4. Binding the player to the map renderer


"""


# houses the global game state
class MainGame:
    def __init__(self, autostart: bool = True):
        pygame.init()
        self.started = False
        """Set while the main loop is running; clearing it stops the loop."""
        self.frame: int = 0
        """Frames completed since begin() was called."""
        self._prev_time: int = 0
        self._target_fps: float = 60.0
        self._tick_rate: float = 60.0
        #self.factory: ComponentFactory = ComponentFactory()
        #self.factory.register("GameComponent", GameComponent)
        self.assets: CoreAssetManager | None = None
        self.scene: SceneManager | None = None
        self.screen: Surface | None = None
        self.camera: GameCamera | None = None
        self.renderer: LayerRenderer | None = None
        self.player: GamePlayer | None = None
        self.window: DemoWindow | None = None
        """The test window. F1 toggles it; the close button hides it."""
        #self.test_entity = None
        self.input: InputActionManager | None = None
        #self.test_ui_element: WidgetDrawableGroup | None = None
        #self.test_ui_element2: WidgetDrawableGroup | None = None
        #self.test_elements: list[WidgetDrawableGroup] = []
        #self.test_players: list[GamePlayer] = []
        # Initialization
        pygame.display.set_caption("Pyoneer")
        self.clock = pygame.time.Clock()
        self.prepare()
        self.build()
        if autostart:
            self.begin()

    def prepare(self):
        self.load_config()
        self.load_renderer()
        self.prepare_test_scene()

    def build(self):
        self.scene.current_scene.core_lifecycle_build()

    def prepare_test_scene(self):
        self.scene = SceneManager(self)
        game_camera, game_map = self.load_map()
        self.scene.add_scene("test", GameScene("test"))
        self.scene.set_scene("test")
        self.scene.bind("renderer", self.renderer)
        self.scene.bind("camera", game_camera)
        self.scene.bind("MAP", game_map)
        test_objects = self.load_test_objects()
        for obj in test_objects:
            self.scene.bind(obj[0], obj[1])
        self.scene.current_scene.core_lifecycle_prepare_pre()
        self.scene.current_scene.core_lifecycle_prepare()
        self.scene.current_scene.core_lifecycle_prepare_post()

    def load_map(self) -> tuple[GameCamera, GameMap]:
        map_data = self.assets.maps.load_assets("test")
        camera = GameCamera(pygame.Vector2(self.screen.get_width(), self.screen.get_height()),
                            pygame.Rect(0, 0, map_data.tilewidth * map_data.width, map_data.tileheight * map_data.height),
                            scale=1)
        return camera, GameMap(map_data)

    def load_test_objects(self):
        bindable_objects: list[tuple[str | int,
                                     PyoneerGameObject | GameEntity | GamePlayer | GameComponent]] = []
        for i in range(0, 5):
            bindable_objects.append( (40, GamePlayer(input_=None,
                                                movement_config=self.assets.config.get('entity').get('default'),
                                                animation_config=self.assets.animations.get('entity'))) )
            bindable_objects[i][1].moveto((200 + i * 5, 200 + i * 5))
            bindable_objects[i][1].state.can_move = False
            #self.renderer.__bind_entity(self.test_players[i], f"ENTITY_2")
        player = GamePlayer(input_=self.input,
                            movement_config=self.assets.config.get('entity').get('default'),
                            animation_config=self.assets.animations.get('entity'))
        player.moveto((200, 200))
        player.state.can_move = True
        bindable_objects.append((41, player))
        self.player = player
        self.scene.camera.attach_target(player)
        #self.renderer.__bind_entity(self.player, "ENTITY_1")
        #self.camera.attach_target(bindable_objects[-1])
        #for i in range(0, 5):
            #bindable_objects.append( (100,
            #    WidgetDrawableGroup(state=WidgetStateInteractive(
            #    bounds=Rect(100 + i, 100 + i, 50, 50),
            #    background=WidgetColor(0, 255, 0, 255),
            #    visible=True,
            #    active=True,
            #    alpha=0.5
            #))) )
            #self.renderer.__bind_ui(self.test_elements[i], f"UI_LAYER_1")

        #component_container = WidgetContainer()
        #background_component = BackgroundComponent(
        #    bounds=Rect(500, 500, 200, 200),
        #    background_color=WidgetColor(0, 0, 0, 255, 1),
        #)
        #text_component = TextComponent(
        #    bounds=Rect(55, 0, 200, 200),
        #    text_shadow_visible=True,
        #    text_shadow_color=WidgetColor(55, 55, 0, 125, 1),
        #    text_color=WidgetColor(255, 255, 255, 255, 1),
        #    text_shadow_offset=pygame.Vector2(12, 5),
        #    text="Hello World!",
        #)
        #text_box = TextBox("", True, bounds=Rect(444, 444, 400, 50))
        #component_container.bind_component("background1", background_component)
        #component_container.bind_component("text1", text_component)
        #component_container.bind_component("textbox1", text_box)
        #bindable_objects.append((101, text_box))
        window = DemoWindow(bounds=Rect(100, 100, 400, 400))
        self.window = window
        self.scene.bind("UI_LAYER_1", window)
        return bindable_objects

    def load_config(self):
        self.assets = CoreAssetManager()
        self.input = self.assets.inputs
        # more config loading happens here in the future

    def load_renderer(self):
        bounds = self.assets.config.get('theme').get("window")["bounds"]
        self.screen = pygame.display.set_mode((bounds[2], bounds[3]))
        self.renderer: LayerRenderer = LayerRenderer(self.screen)
        #for i in range(0, 1000):
        #    self.test_players.append(GamePlayer(input_=None,
        #                                        movement_config=self.assets.config.get('entity').get('default'),
        #                                        animation_config=self.assets.animations.get('entity')))
        #    self.test_players[i].moveto((200 + i * 5, 200 + i * 5))
        #    self.test_players[i].state.can_move = False
        #    self.renderer.bind_entity(self.test_players[i], f"ENTITY_2")
        #self.player = GamePlayer(input_=self.input,
        #                         movement_config=self.assets.config.get('entity').get('default'),
        #                         animation_config=self.assets.animations.get('entity'))
        #self.player.moveto((200, 200))
        #self.renderer.bind_entity(self.player, "ENTITY_1")
        #self.camera.attach_target(self.player)
        #for i in range(0, 200):
        #    self.test_elements.append(WidgetDrawableGroup(state=WidgetStateInteractive(
        #        bounds=Rect(100 + i, 100 + i, 50, 50),
        #        background=WidgetColor(0, 255, 0, 255),
        #        visible=True,
        #        active=True,
        #        alpha=0.5
        #    )))
        #    self.renderer.bind_ui(self.test_elements[i], f"UI_LAYER_1")
        #state = WidgetStateInteractive(
        #    bounds=Rect(100, 100, 400, 400),
        #    visible=True,
        #    active=True,
        #    alpha=0.5
        #)
        #self.test_ui_element: WidgetDrawableGroup = WidgetDrawableGroup(state=state)
        #self.test_ui_element.add_child(WidgetDrawableGroup(state=WidgetStateInteractive(
        #    bounds=Rect(150, 150, 100, 100),
        #    background=WidgetColor(0, 255, 0, 255),
        #    visible=True,
        #    active=True,
        #    alpha=0.5
        #)))
        #self.layer_renderer.bind_ui(self.test_ui_element, "UI_LAYER_1")

    def quit(self):
        pygame.quit()
        sys.exit()

    def begin(self, max_frames: int | None = None):
        """Run the main loop.

        max_frames bounds the run so the engine can be driven headlessly by
        tools/smoke.py; None is the normal 'run until quit' game behaviour.
        """
        self._prev_time = pygame.time.get_ticks()
        self._target_fps = float(self.assets.config.get('game', 'target_fps'))
        self._tick_rate = float(self.assets.config.get('game', 'target_tick_rate'))
        self.scene.current_scene.begin()
        self.started = True
        while self.started:
            self.tick()
            self.frame += 1
            if max_frames is not None and self.frame >= max_frames:
                return

    def tick(self) -> float:
        """Advance exactly one frame. Returns the delta time used."""
        current_time = pygame.time.get_ticks()
        self.clock.tick(self._target_fps)
        delta_time = (current_time - self._prev_time) / self._tick_rate
        self._prev_time = current_time
        pygame.display.set_caption(f"Pyoneer - {int(self.clock.get_fps())}")

        EventManager.update(delta_time)
        self.input.update()
        self.handle_global_input()

        self.scene.pre_update(delta_time)
        self.scene.update(delta_time)
        self.scene.post_update(delta_time)

        self.screen.fill((0, 0, 0))
        # renders the 2d game's layers. SceneManager.update already ran
        # renderer.update for this frame; calling it again here only repeated
        # the no-op Layer.core_frame_update pass over every layer.
        self.renderer.render()
        pygame.display.flip()
        return delta_time

    def handle_global_input(self):
        """Application-level keys, handled before the scene sees anything."""
        if EventManager.get(pygame.QUIT, True):
            self.quit()

        if ev := EventManager.get(pygame.KEYDOWN, False):
            if isinstance(ev, pygame.event.Event):
                if ev.key == pygame.K_ESCAPE:
                    self.quit()
                if ev.key == pygame.K_F1:
                    self.toggle_window()
                if ev.key == pygame.K_LEFT:
                    self.player.rotate(-10)
                if ev.key == pygame.K_RIGHT:
                    self.player.rotate(10)

    def toggle_window(self):
        """F1: show or hide the test window.

        close() clears both visible and active, so a closed window neither
        draws nor eats input and there is otherwise no way back to it.
        """
        if self.window is None:
            return
        if self.window.visible:
            self.window.close()
        else:
            self.window.open()


if __name__ == "__main__":
    main = MainGame()