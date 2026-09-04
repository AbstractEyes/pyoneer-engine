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

from config.managers.animation_data import DataAnimationCategory
from config.managers.core_asset_manager import CoreAssetManager
from scripts.core.audio import AudioManager
from scripts.core.errors import PyoneerConfigError
from scripts.core.input import InputActionManager
from scripts.game.entity.game_animation import GameAnimationHandler
from scripts.core.scene.scene_manager import SceneManager
from scripts.core.component import GameComponent
from scripts.core.ui.widget.containers.window import GameWindow
from scripts.loaders.table_file import load_tables
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

MAP_NAME: str = "starter"
"""Which entry of `config/maps.json` the shipped game boots into.

`data/maps/starter.tmx`, and the whole game is in it: tile layers at four
drawn depths, a passability companion that blocks, and an object layer whose
`<object type="GamePlayer">` IS the body the human walks around. There is no
Python in this file that builds an entity -- see `load_test_objects`.
"""

PLAYER_TOKEN: str = "player_input"
"""The behavior token that means "the human drives this one".

Which object is the player is answered from its COMPOSITION rather than from
a flag: no class, no `pyoneer_player` property, no boolean. Two objects of
the same type built from the same config differ by this one string, and the
one carrying it is the one the camera follows.
"""

INTERACT_SOUND: str = "sfx/chime.wav"
"""What `interact_action` plays, named the way an authored sound is named.

Root-free, exactly as `scripts/core/audio.py` takes it: `data/sound/` is
looked at first and `data/audio/` -- the shipped pack -- answers when the
author has put nothing there.
"""


def feet_anchor(animation_config: DataAnimationCategory) -> tuple[float, float]:
    """Where the collision point sits inside a body drawn with this sheet.

    `transform.position` is the sprite's TOP-LEFT, because `EntityLayer`
    blits with `get_rect(topleft=position)`. So `GameEntity`'s own default of
    (0, 0) tests the top-left pixel -- the top of a character's HEAD -- and a
    body gated there is allowed to walk a whole sprite height into a floor
    before the gate sees anything: measured, 63.9990234375 pixels down into a
    floor at y=64 for the shipped 44x64 frame. Centre-bottom is the honest
    anchor for a body standing on a map.

    DERIVED, never typed. It reads the sequence
    `GameAnimationHandler.DEFAULT_ANIMATION`, which is the one the handler
    starts unconditionally at construction, so this is the size of the frame
    the entity actually shows on the frame it spawns -- and re-cutting the
    sheet at a different frame size moves the anchor with it.

    RAISES when the category cannot answer, rather than returning (0, 0): the
    head anchor is precisely what a broken derivation looks like from the
    outside, so a fallback would be indistinguishable from this working.
    """
    wanted = GameAnimationHandler.DEFAULT_ANIMATION
    sequences = getattr(animation_config, 'sequences', None) or {}
    sequence = sequences.get(wanted)
    frames = getattr(sequence, 'frames', None) if sequence is not None else None
    if not frames:
        raise PyoneerConfigError(
            "cannot derive a collision anchor: the animation category %r has "
            "no %r frames to measure. config/animations.json declares the "
            "sequence GameAnimationHandler starts at construction; without it "
            "there is no frame size, and guessing one would silently anchor "
            "every body at its head."
            % (getattr(animation_config, 'name', animation_config), wanted),
        )
    first = frames[0]
    return (first.width / 2.0, float(first.height - 1))


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
        """The body the human drives, picked out of what the MAP spawned.

        Assigned in `load_test_objects` from the object carrying
        `player_input`, and None for a map whose object layer places nobody.
        Nothing in this file constructs it.
        """
        self.window: DemoWindow | None = None
        """The test window. F1 toggles it; the close button hides it."""
        #self.test_entity = None
        self.input: InputActionManager | None = None
        self.audio: AudioManager | None = None
        """The process's one mixer, opened in `load_config`.

        Absent hardware is not an error here: `prepare` warns once and every
        later play is a truthful no-op, so a machine with no sound card runs
        this game. A missing FILE still raises -- a filename is wrong on a
        silent machine too.
        """
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
        self.scene.add_scene(MAP_NAME, GameScene(MAP_NAME))
        self.scene.set_scene(MAP_NAME)
        self.scene.bind("renderer", self.renderer)
        self.scene.bind("camera", game_camera)
        # Before the map, not after: binding the map is what spawns the
        # objects on its object layers, and they are constructed with these.
        self.renderer.spawn_defaults = self.spawn_arguments()
        # Same ordering rule, same reason: `pyoneer_actor` on an authored
        # object is resolved during the map bind, so the tables have to be in
        # the renderer's hand before it. `load_tables()` reads
        # data/project/tables/ and returns an EMPTY set when the directory is
        # absent, so a clone with no Database boots identically.
        self.renderer.tables = load_tables()
        self.scene.bind("MAP", game_map)
        # AFTER the map, because that bind is what spawns and binds the map's
        # objects; this hook only configures what already exists.
        test_objects = self.load_test_objects()
        for obj in test_objects:
            self.scene.bind(obj[0], obj[1])
        self.scene.current_scene.core_lifecycle_prepare_pre()
        self.scene.current_scene.core_lifecycle_prepare()
        self.scene.current_scene.core_lifecycle_prepare_post()

    def spawn_arguments(self) -> dict[str, dict]:
        """Constructor arguments for the entity types a map may place.

        A .tmx object carries a type, a position and custom properties. It
        cannot carry an InputActionManager or a parsed animation category, so
        an authored `<object type="GamePlayer">` gets exactly what this file
        hands a GamePlayer it builds itself.

        EVERY spawned player may safely hold the live manager: polling is
        `player_input`'s job, and an entity without that token never reads the
        manager it was handed. The map decides which one the human drives by
        listing `player_input` in its `pyoneer_behaviors` property.

        `behaviors` is deliberately NOT among these defaults. A default here
        would be a per-CLASS list -- every object of a type composed the same
        way -- which is the subclass shape this system exists to end, and it
        would collide with an authored list, since attaching a duplicate token
        raises. The map is the whole truth for what an entity does.

        `collision_offset` IS among them, and for the opposite reason: it is
        not a statement about what an entity does, it is the pixel inside the
        sprite that the map's passability is tested at, and it is decided by
        the SHEET rather than by the object. Every body drawn from this
        category has the same feet, so one derived number for the class is
        the correct scope, and `feet_anchor` raises rather than guessing when
        the category cannot be measured.
        """
        animation_config = self.assets.animations.get('entity')
        return {
            "GamePlayer": {
                "input_": self.input,
                "movement_config": self.assets.config.get('entity').get('default'),
                "animation_config": animation_config,
                "collision_offset": feet_anchor(animation_config),
            },
        }

    def load_map(self) -> tuple[GameCamera, GameMap]:
        map_data = self.assets.maps.load_assets(MAP_NAME)
        camera = GameCamera(pygame.Vector2(self.screen.get_width(), self.screen.get_height()),
                            pygame.Rect(0, 0, map_data.tilewidth * map_data.width, map_data.tileheight * map_data.height),
                            scale=1)
        return camera, GameMap(map_data)

    def load_test_objects(self):
        """Configure what the MAP spawned, and build nothing.  #TAG:no_entity_is_built_here

        THIS METHOD USED TO BE THE GAME. It constructed six `GamePlayer`s --
        five inert decoys and the one the human drove -- and bound them at
        depths 40 and 41, while `data/maps/test.tmx` placed no objects at
        all. So for as long as that lasted, "the engine spawns entities from
        an object layer" and "the game you can actually run" were two
        different code paths, and every fix to the first one was unmeasured on
        the second: the feet anchor landed in `spawn_arguments`, reached the
        hand-built six by being read back out of it, and reached nothing the
        MAP spawned because the map spawned nothing.

        Now `data/maps/starter.tmx` carries the object layer, `bind("MAP",
        ...)` runs `spawn_objects` over it, and every body in the world comes
        through `SPAWN_REGISTRY` with `spawn_defaults` applied -- the same
        route `tools/check_spawn_runtime.py` already covers. Nothing is left
        here to construct, which is why this returns an empty list; the
        binding loop in `prepare_test_scene` still exists for a subclass that
        wants a hand-built object.

        `tools/check_demo_map.py` asserts by AST that no entity class is
        called anywhere in this file, so the bypass cannot quietly come back.
        """
        bindable_objects: list[tuple[str | int,
                                     PyoneerGameObject | GameEntity | GamePlayer | GameComponent]] = []
        # WHICH OBJECT IS THE PLAYER, answered from the composition. The
        # records carry RESOLVED `BehaviorRequest`s, so the token is compared
        # against the registry's own spelling (`spec.name`) and not against a
        # substring of the raw property -- which would also match a future
        # `player_input_recorder`.
        #
        # The demo boot path owns a second copy of this three-line pick, as
        # `driven_record`. It imports THIS module already, so the two should
        # become one import in that direction; they are kept apart today only
        # because that file belongs to another change. (Named by shape rather
        # than by path on purpose: the demo suite asserts this file does not
        # so much as SPELL that package's name, because it is the smoke
        # baseline and the dependency runs one way.)
        records = list(self.renderer.spawned_entities)
        driven = next((record for record in records
                       if any(request.spec.name == PLAYER_TOKEN
                              for request in record.behaviors)), None)
        # Fall back to the first spawned entity so a map with no driven object
        # still gives the camera something to follow. Both may be None on a
        # map with an empty object layer, and `handle_global_input` guards
        # for exactly that.
        followed = driven or (records[0] if records else None)
        if followed is not None:
            self.player = followed.entity
            self.scene.camera.attach_target(followed.entity)
        # THE ONE ROUTE THIS GAME WIRES, and the reason the map's hero carries
        # `interact_action,action_relay`: `action_relay` CALLS
        # `entity.action_sink(entity, fired)`, `SceneManager` assigns its own
        # `ActionRouter` as that sink on both binding routes, and this is the
        # handler at the end of it. Nothing fires during a bind -- an action
        # is produced on the frame path -- so registering here, after the map
        # has spawned, is in time.
        #
        # HERE rather than in `prepare_test_scene`, which is deliberate and
        # was measured: a subclass INHERITS that method by identity and
        # overrides this one, so a route registered there would be the shipped
        # game's wiring silently installed in every game built on this class.
        # Registered with the DEFAULT payload -- any payload -- so an author
        # who later adds a `pyoneer_param_payload` to that object still
        # reaches this; a route keyed to one payload string would go silent
        # the moment the map said something more specific.
        self.scene.actions.route("interact_action", self.play_interaction_sound)
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
        # `ConfigManager` scans `config/*.json`, so `config/audio.json` needed
        # no wiring anywhere: `prepare` reads its five mixer numbers and opens
        # the device. It never raises for an absent sound card -- that is an
        # optional capability, warned about once -- so this line is safe on a
        # headless runner and on the check suite.
        self.audio = AudioManager().prepare(self.assets.config.get('audio'))
        # more config loading happens here in the future

    def play_interaction_sound(self, entity, fired) -> None:
        """Make a noise when a body's `interact_action` fires.

        An `ActionRouter` handler: `(entity, fired)` is what `action_relay`
        passes, so this needs no adapter. Registered in `prepare_test_scene`.

        Unguarded on purpose. `self.audio` is assigned in `load_config`,
        which runs before any scene exists, so a None here is a WIRING bug and
        an AttributeError naming it is the correct report -- where a silent
        `return` would be indistinguishable from a machine with no sound card,
        which is the one case `play_sound` already answers truthfully with
        False. A missing FILE raises, deliberately, on a silent machine too.
        """
        self.audio.play_sound(INTERACT_SOUND)

    def load_renderer(self):
        bounds = self.assets.config.get('theme').get("window")["bounds"]
        self.screen = pygame.display.set_mode((bounds[2], bounds[3]),
                                              pygame.RESIZABLE)
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
                # Guarded: `self.player` is whatever the MAP spawned now, so a
                # map whose object layer places nobody leaves it None. It used
                # to be a body this file constructed unconditionally, and an
                # unguarded dereference was safe only because of that.
                if self.player is not None:
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