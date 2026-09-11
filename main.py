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
from scripts.core.errors import PyoneerConfigError, warn_content
from scripts.core.input import InputActionManager
from scripts.game.behavior import BEHAVIORS
from scripts.game.entity.game_animation import GameAnimationHandler
from scripts.core.scene.scene_manager import SceneManager
from scripts.core.component import GameComponent
from scripts.core.ui.anchor import Anchor
from scripts.core.ui.widget.text import TextComponent
from scripts.core.ui.widget.containers.window import GameWindow
from scripts.game.flow.interpreter import ScriptRun
from scripts.loaders.map_loader import (PLAYER_TOKEN, as_document,
                                        driven_record,
                                        has_tmx_document)
from scripts.loaders.script_file import (SCRIPT_PROPERTY, VarStore,
                                         load_scripts, load_vars, script_of)
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

INTERACT_TOKEN: str = "interact_action"
"""The behavior token whose firing starts an object's event script.

The token, never the input verb. `interact_action` is what a tmx object's
`pyoneer_behaviors` list spells and what `ActionFired.name` carries, and
`ActionRouter` is keyed by it -- routing the verb `action` instead would key
nothing, which is the mistake `ActionRouter.route` raises about by name.
"""

RELAY_TOKEN: str = "action_relay"
"""The behavior that CALLS the sink. Named so a diagnostic can require it.

`interact_action` only RECORDS a firing into the entity's action record;
`action_relay` at order 90 is what hands it to `entity.action_sink`. An
object carrying the first and not the second produces firings nothing ever
reads, which looks exactly like a script that does not work.
"""

# `SCRIPT_PROPERTY` is IMPORTED, not declared: the string `pyoneer_script` is
# a file-format name under law 8 and the editor writes what this file reads,
# so it has exactly one declaration, in `scripts/loaders/script_file.py`
# beside the reader of the documents it names. It is re-exported here because
# a reader who has the boot open expects to find the property it joins on.

DIALOGUE_BOUNDS: Rect = Rect(120, 400, 560, 120)
"""Where a `say` line is shown. Bottom-ish and wide, like every dialogue box."""

DIALOGUE_LAYER: str = "UI_LAYER_1"
"""Which UI layer the dialogue box is bound into when one is first needed."""


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


class ScriptBox(GameWindow):
    """A `GameWindow` holding one line of dialogue. That is the whole widget.

    Derives `GameWindow` rather than wrapping one so `open()` and `close()`
    stay the inherited pair -- `visible`/`active` up, and
    `visible`/`active`/focus down. A wrapper that reimplements them is how a
    closed dialogue box goes on swallowing clicks in the rectangle it used to
    occupy.

    CONSTRUCTED CLOSED, and that is not cosmetic: rendering is gated on
    `visible`, so a closed box queues no `BlitToken` at all. Measured on the
    shipped map, 60 frames: 37 blit tokens with the box bound and closed,
    which is the baseline to the token, and 43 while a line is open.

    `who` goes in the header and `text` in the body, which is the only home
    `say`'s two arguments have in a one-line box.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("header_text", "")
        kwargs.setdefault("resizable", False)
        kwargs.setdefault("visible", False)
        kwargs.setdefault("active", False)
        super().__init__(*args, **kwargs)
        self.line_text: TextComponent | None = None
        self._line: str = ""

    def build_content(self):
        """Build the line of text. Called by `GameWindow` once chrome exists.

        Content belongs here rather than in `__init__`: `world_bounds` is not
        final until the component has a parent and has been prepared, so a
        child sized in the constructor is sized against the wrong rectangle.
        """
        self.line_text = TextComponent(
            parent=self, depth=2,
            bounds=Rect(10, self.header_height + 8,
                        self.local_bounds.width - 20,
                        self.local_bounds.height - self.header_height - 16),
            text=self._line,
            center=False,
            auto_fit=True)
        self.line_text.anchor = Anchor.ALL
        self.bind_component("line_text", self.line_text)

    @property
    def line(self) -> str:
        """The sentence currently shown. Assigning repaints it."""
        return self._line

    @line.setter
    def line(self, value: str) -> None:
        self._line = str(value)
        # Buffered until the chrome exists, because a caller may set the line
        # before the box has been bound and therefore prepared.
        if self.line_text is not None:
            self.line_text.text = self._line

    @property
    def speaker(self) -> str:
        """Who is talking, shown in the header. Empty is narration."""
        return self.text

    @speaker.setter
    def speaker(self, value: str) -> None:
        self.text = str(value)
        if self.header_text is not None:
            self.header_text.text = self.text


class ScriptDialogue:
    """The `say` host: two duck-typed methods, and a box built on FIRST USE.

    `ScriptRun` asks a host for exactly `say_open(who, text)` and
    `say_close()` -- named once in `scripts/game/flow/interpreter.py` as
    `SAY_OPEN` and `SAY_CLOSE` -- and a host missing either RAISES naming the
    method, because a `say` that showed nothing would be a line of dialogue
    the player never sees and no complaint.

    LAZY, AND THAT IS THE WHOLE REASON THIS IS A CLASS. `tools/smoke.py`
    injects no input, so no script ever starts under it; a box built only
    when a line is first spoken is therefore invisible to the frame
    instrument, where a box bound at boot moves four baseline fields at once.
    Measured on the shipped map: binding one at boot takes `ui_roots` from
    `["DemoWindow@100"]` to two roots, `ui_component_total` from 124 up, and
    both dispatch censuses with it -- all four while the box is CLOSED and
    drawing nothing, because a census counts the tree and not the pixels.

    Binding here is safe for the same reason `SceneManager.post_update` gives
    at the flow slot itself: `say_open` is reached from `flow.update`, which
    runs AFTER `core_frame_update_post` has returned, so opening a window
    cannot mutate a list something is iterating. Binding from the action
    route instead would do exactly that -- `action_relay` calls the sink from
    inside the entity's own frame update.

    Binding through `SceneManager.bind` also PREPARES the box: `UILayer.bind`
    calls `core_lifecycle_prepare` on what it is handed, which is what builds
    the chrome and runs `build_content`. A box merely appended to the scene
    would never be prepared and would draw nothing, which is the failure this
    paragraph exists to stop someone re-discovering.
    """

    __slots__ = ("game", "box")

    def __init__(self, game: "MainGame"):
        self.game = game
        self.box: ScriptBox | None = None
        """The dialogue box, or None until a script has said something."""

    def require_box(self) -> ScriptBox:
        """The box, building and binding it the first time one is asked for."""
        if self.box is None:
            self.box = ScriptBox(bounds=Rect(DIALOGUE_BOUNDS))
            self.game.scene.bind(DIALOGUE_LAYER, self.box)
        return self.box

    def say_open(self, who: str, text: str) -> None:
        """Show one line. Called on the frame a `say` node is entered."""
        box = self.require_box()
        box.speaker = who
        box.line = text
        box.open()

    def say_close(self) -> None:
        """Hide the line. Called on the frame the `say` completes.

        The only closer, and it is sufficient: a `say` node BLOCKS the run
        while it waits for the advance, so no other node -- `stop` included --
        can execute while a line is on screen. A box left open is therefore an
        exception escaping mid-run, which is not a state to paper over.

        Tolerates never having opened, so a host handed to a run that says
        nothing is not a special case.
        """
        if self.box is not None:
            self.box.close()


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
        self.scripts: dict = {}
        """Every `data/project/scripts/*.json`, keyed by id. Read at boot.

        ONE registry, and it is the loader's own return value rather than a
        class wrapping it: `load_scripts()` already answers "every script this
        project declares", and `ScriptRun` takes that same mapping as its
        `scripts=` argument so a `call` resolves through the dict the boot
        read and not through a second copy.

        HERE rather than on the renderer beside `tables` and `spawn_defaults`,
        and the difference is who reads it: those two are read INSIDE
        `scripts/` -- the map bind hands them to `spawn_objects` -- while
        nothing in `scripts/` opens a script document. A slot on a class that
        never touches it would be a monkey-patched attribute, which is worse
        than an honest one here.
        """
        self.script_vars: VarStore | None = None
        """The live value of every variable the scene documents declare.

        Built ONCE at boot, never per run, which is what makes the shipped
        script's `if` reach both arms: the second press reads what the first
        press `set`.
        """
        self.script_run: ScriptRun | None = None
        """The run currently in `SceneManager.flow`, or the last one to finish."""
        self.dialogue: ScriptDialogue | None = None
        """The `say` host. Its box is not built until a line is spoken."""
        self.object_scripts: list[tuple] = []
        """(entity, script id) for every spawned body carrying `pyoneer_script`.

        A LIST searched by identity, not a dict keyed by `id(entity)`: a
        reaped body's address can be reused by the next allocation, and a
        stale row under a recycled key would start the wrong conversation.
        """
        self.map_data = None
        """The parsed map, kept so the object scripts can be re-read.

        `SpawnedEntity` carries `object_id` and `layer_name` and NOT the
        object's properties, so the only way back to `pyoneer_script` is the
        document -- which is exactly what those two fields are for.
        """
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
        # Off the GameMap rather than out of `load_map`, and the difference is
        # inheritance: `load_map` is a HOOK -- the sibling demo runtime
        # overrides it, and so does any game booting a map of its own -- so an
        # assignment inside it is one every subclass silently drops, and the
        # symptom is a map whose `pyoneer_script` properties are simply never
        # seen. This line is in the method a subclass inherits by identity, so
        # it cannot be lost that way. Measured: written the other way first,
        # and the fixture boot in this change's own check found it.
        #
        # (Described by shape rather than by path, as the pick in
        # `load_test_objects` already is: this module is the smoke baseline,
        # and a check asserts main.py does not so much as SPELL that
        # package's name.)
        self.map_data = game_map.tmx_data
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
        # The scripts, on the same rule as the tables and for the same
        # reason: an absent `data/project/scripts/` is an empty mapping and
        # not an error, so a clone with no scripted events boots identically,
        # while a document that fails to PARSE raises here -- naming the file,
        # before a display exists, before a frame has run and before anybody's
        # agency has been taken. A script skipped for a stray comma would be a
        # keeper who silently does nothing, which is indistinguishable from a
        # keeper the author has not written yet.
        #
        # BEFORE the map bind, so a broken script cannot be reported after a
        # world has already been built around it.
        # THE SCHEMA COMES OFF DISK, and this line is what a Python dict
        # three hundred rows above it used to be. `main.SCENE_VARS`'s own
        # docstring promised it "MOVES to `data/project/scenes/starter.json`
        # the day that loader exists" -- the loader exists, so it moved. The
        # editor reads the same directory through `scripts_of`, which is the
        # whole point: while the schema lived here, the game could run a
        # script the editor could not open, because the editor cannot import
        # this module and had nothing else to read.
        #
        # Absent is silent, on `load_tables`' and `load_scripts`' rule: a
        # project with no scene document declares no variables, and a script
        # that then names one raises NAMING THE DIRECTORY a declaration would
        # have been read from.
        self.script_vars = VarStore(load_vars())
        self.scripts = load_scripts(variables=self.script_vars.schema)
        self.scene.bind("MAP", game_map)
        # AFTER the map, because that bind is what spawns and binds the map's
        # objects; this hook only configures what already exists.
        test_objects = self.load_test_objects()
        for obj in test_objects:
            self.scene.bind(obj[0], obj[1])
        # AFTER the hook, because the hook is what adopts a player, and HERE
        # rather than inside it for the reason the hook's own route comment
        # gives in reverse: a subclass inherits this method by identity and
        # overrides that one, so this is the only place a DIAGNOSTIC reaches
        # every game built on this class. That inheritance is wrong for
        # wiring -- `interact_action`'s route is registered in the hook
        # precisely so a subclass does not silently get it -- and right for a
        # warning, which is a report about the author's map and not
        # behaviour the subclass would have to opt out of.
        self.warn_undriven_player()
        self.scene.current_scene.core_lifecycle_prepare_pre()
        self.scene.current_scene.core_lifecycle_prepare()
        self.scene.current_scene.core_lifecycle_prepare_post()

    def warn_undriven_player(self) -> None:
        """Say so when the body this game adopted as the player cannot move.

        `player_input` is the ENTIRE marker for "this is the one the human
        drives" -- no class, no `pyoneer_player` flag, no boolean -- so an
        object the game adopts as the player and which does not carry that
        token is an authored body nothing will ever steer. Measured before
        this existed: the camera locked onto it, followed it faithfully, and
        holding a movement verb for 30 frames moved it zero pixels, with
        nothing said at boot.

        A WARNING, not a raise, and the split is the engine's own: a contract
        violation raises, unusable AUTHORED CONTENT warns. A map is edited
        halfway -- the object placed, the behavior list not typed yet -- and
        an engine that refused to load it would take the editor down with the
        author still working in it.

        NARROW ON PURPOSE. Only the adopted body is named. Every other entity
        on the map legitimately lacks the token -- a patrol, a decoy, a
        signpost -- and a warning that fired on all of them would be the
        noise that teaches an author to ignore this channel. Three silences
        follow from that and each is deliberate: nothing adopted (an empty
        object layer) names no object because there is none; a `self.player`
        no spawn record claims is a body some subclass BUILT in Python, which
        is not authored content and has no `<object>` to point at; and the
        adopted body carrying the token is the working case.

        The token is compared against the registry's own spelling
        (`request.spec.name`) rather than against the raw property text, so a
        future `player_input_recorder` is not mistaken for it -- the same
        comparison the adoption itself uses, because a diagnostic that
        disagrees with the pick it describes is worse than none.
        """
        if self.player is None:
            return
        record = next((entry for entry in self.renderer.spawned_entities
                       if entry.entity is self.player), None)
        if record is None:
            return
        if any(request.spec.name == PLAYER_TOKEN
               for request in record.behaviors):
            return
        warn_content(
            "the map's <object id=%d> on layer %r (type %s) is the body this "
            "game adopted as the player, and its %s list does not carry %r, "
            "which is the whole marker for \"the human drives this one\". "
            "Nothing will poll the keyboard for it: the camera will follow a "
            "body that never moves. Add %r to that object's %s property -- "
            "for a top-down body the usual list is %r."
            % (record.object_id, record.layer_name, record.type_name,
               BEHAVIORS, PLAYER_TOKEN, PLAYER_TOKEN, BEHAVIORS,
               "%s,topdown_move,animation_drive" % PLAYER_TOKEN)
        )

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
        # WHICH OBJECT IS THE PLAYER, answered from the composition -- and
        # answered by ONE function, in `scripts/`, that the demo boot path
        # calls too. It used to be this three-line `next(...)` here and a
        # second copy under another name over there, which is law 2's
        # corollary at small scale; the corollary was paid once at 425
        # duplicate lines. The direction the import runs is forced and is the
        # reason the shared half is in the engine rather than here: that
        # package imports THIS module, and a check asserts this file does not
        # so much as SPELL its name, because this module is the smoke
        # baseline and the dependency runs one way.
        records = list(self.renderer.spawned_entities)
        driven = driven_record(records)
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
        #
        # AND THE LIMIT OF THAT SENTENCE, MEASURED RATHER THAN ASSUMED.
        # `ActionRouter` resolves most-specific-first, so the any-payload row
        # is a FALLBACK: it is reached only while no route claims that exact
        # (token, payload) pair. Adding a payload to the object is therefore
        # free, as the sentence says -- and it stops being free the moment
        # some OTHER route claims the same string, which the narrative kit
        # does whenever a game sets its advance payload to the value its map
        # writes on the body. Driven on exactly that shape, a hero carrying
        # `pyoneer_param_payload` and a `pyoneer_script`:
        #
        #     handlers_for(interact_action, 'keeper') -> [SceneFlow.on_action]
        #     handlers_for(interact_action, '')       -> [run_object_script]
        #     eight presses                           -> script_run None, and
        #                                                no warning anywhere
        #
        # The body is joined, the document is loaded, and the press can never
        # reach it. NOT FIXABLE FROM THIS LINE: the resolution rule belongs to
        # the router and the second route belongs to the kit, and the only
        # wire this file could add instead -- one route per payload the map
        # spells -- would be this module reading map content at wiring time,
        # a larger claim than the one that is wrong. `read_object_scripts`'
        # warning cannot see it either: that body carries both tokens.
        self.object_scripts = self.read_object_scripts()
        self.dialogue = ScriptDialogue(self)
        self.scene.actions.route(INTERACT_TOKEN, self.run_object_script)
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

    def read_object_scripts(self) -> list[tuple]:
        """(entity, script id) for every spawned body naming a `pyoneer_script`.

        THE READER THE EDITOR HAS BEEN WRITING FOR. `editor/ui/script_editor.py`
        has been able to put that property on an object for as long as it has
        existed, and until this method nothing in a running game opened the
        document it named -- the capability complete, checked, and unreachable
        by the person who asked for it.

        Re-reads the .tmx because `SpawnedEntity` carries `object_id` and
        `layer_name` and NOT the object's properties. Those two fields exist
        so a downstream error can name the `<object>` that produced an entity,
        and joining on them here is the same use: the pair addresses the
        authored object, and the document answers what it declared.

        A map that is not a .tmx declares no object scripts, and that is the
        TRUTH rather than a fallback -- a native `.blitmap` has no property
        store this could read, so there is nothing to fail to find.

        RAISES for a `pyoneer_script` naming a document that is not there,
        listing what is, exactly as `actor_row` raises for a `pyoneer_actor`
        naming an absent row. Skipping it would leave an object that looks
        scripted and is silently inert, which is the shape law 8 exists to
        refuse. That refusal is not spelled here: it is `script_of`, the
        reader `SceneManager.spawn` also calls, so the guard this route grew
        first cannot differ from the one the runtime route grew second.

        WARNS -- and does not raise -- for a body whose script can never
        start, because that is unusable authored content and not a contract
        violation: a map edited halfway is a normal state, and an engine that
        refused to load it would take the editor down with the author still
        working in it. NARROW, on `warn_undriven_player`'s rule: only a body
        that actually spawned and actually names a script is named, because an
        untyped region marker carrying one is waiting for the `enter`/`exit`
        route, which is a different wire and is not built.
        """
        if self.map_data is None or not has_tmx_document(self.map_data):
            return []
        document = as_document(self.map_data)
        # The PROPERTIES, not the id read out of them: `script_of` does the
        # falsy test and both refusals, and it is the same function
        # `SceneManager.spawn` calls -- so the runtime route and this one
        # cannot drift apart in what they accept or in how they blame. It
        # lives in `scripts/loaders/script_file.py` beside the property name
        # for the reason law 2's corollary gives: shared logic goes down, and
        # this module may not be imported by anything it shares with.
        declared: dict[tuple, dict] = {}
        for layer_name in document.object_layer_names():
            for obj in document.object_layer(layer_name).objects():
                declared[(layer_name, obj.id)] = obj.properties
        pairs: list[tuple] = []
        for record in self.renderer.spawned_entities:
            properties = declared.get((record.layer_name, record.object_id))
            if properties is None:
                continue
            script_id = script_of(
                self.scripts, properties,
                "tmx object id=%d on layer %r" % (record.object_id,
                                                  record.layer_name))
            if script_id is None:
                continue
            tokens = {request.spec.name for request in record.behaviors}
            missing = [token for token in (INTERACT_TOKEN, RELAY_TOKEN)
                       if token not in tokens]
            if missing:
                warn_content(
                    "the map's <object id=%d> on layer %r names the event "
                    "script %r in %s, and its %s list is missing %s -- so "
                    "nothing will ever start it. %r is what records the "
                    "firing and %r is what CALLS the scene's router with it; "
                    "without both, pressing the action key reaches nothing "
                    "and the script looks like it does not work. Present: %s."
                    % (record.object_id, record.layer_name, script_id,
                       SCRIPT_PROPERTY, BEHAVIORS,
                       ", ".join(repr(token) for token in missing),
                       INTERACT_TOKEN, RELAY_TOKEN,
                       ", ".join(sorted(tokens)) or "<none>"))
            pairs.append((record.entity, script_id))
        return pairs

    def script_for(self, entity) -> str | None:
        """Which script `entity` names, or None. Searched by IDENTITY.

        Never `==`: an entity that defined equality would answer for a
        DIFFERENT body's row, which is the same trap `SceneManager` documents
        at `__forget_spawn_record` and at `GameScene.unbind`.
        """
        for candidate, script_id in self.object_scripts:
            if candidate is entity:
                return script_id
        return None

    def run_object_script(self, entity, fired) -> None:
        """Start the fired body's event script -- or advance the one running.

        An `ActionRouter` handler: `(entity, fired)` is what `action_relay`
        passes, so this needs no adapter. THE WHOLE WIRE, and every link of it
        already existed:

            press `action` -> `interact_action` records ActionFired
                           -> `action_relay` CALLS entity.action_sink
                           -> SceneManager.actions picks this handler
                           -> ScriptRun(...) and SceneManager.flow = it

        Zero changes to `SceneManager`, zero to `GameScene`, zero new
        `GameEventType` members, zero contact with the event bus. The flow
        slot is duck-typed on `update(delta)` and a `ScriptRun` fits it -- the
        same slot, and the same one line, the sibling narrative kit uses to
        start a `SceneFlow`. (Named by shape rather than by path for the
        reason the pick in `load_test_objects` gives: this module is the smoke
        baseline, and a check asserts it does not SPELL that package's name.)

        A LIVE FLOW THAT IS NOT OURS IS NOT EVICTED, AND A FINISHED ONE DOES
        NOT HOLD THE DOOR SHUT. If `SceneManager.flow` holds a RUNNING
        occupant that is not this game's own run -- a `SceneFlow` a narrative
        kit started, say -- the press reaches nothing and the occupant keeps
        the slot. Once that occupant has stopped running it is furniture, and
        the next press starts a run over it. The test is LIVENESS, not
        identity, and not emptiness.

        BOTH HALVES OF THAT REPAIR LANDED, in this order, and the second one
        does not make the first redundant. `SceneManager.post_update` now
        takes a stopped occupant OUT of the slot on the tick that stops it,
        which answers for every future reader of that slot rather than for
        this one caller. This guard still tests liveness rather than
        emptiness, because the two are not the same instant: the press is
        answered in `inputs`, and `post_update` runs after it, so a flow that
        ended earlier in the SAME frame is still sitting there when this line
        reads it. A manager nobody post-updates never empties the slot at
        all. An empty slot and a slot holding a finished flow have to mean
        the same thing here, and they do.

        A SECOND TRIGGER ARRIVING MID-RUN IS REFUSED AS A START AND SPENT AS
        THE ADVANCE. Not queued, and not dropped. Refused because
        `SceneManager.flow` is ONE slot on purpose: a narrative flow is modal,
        it takes the player's steering, and two runs would each restore the
        agency the other had already changed -- the second `release` would put
        back the first `hold`'s recorded value and strand the body. Not queued
        because a queue has to decide which run is next, nothing in this tree
        owns that decision, and an unreachable class shipped early is this
        repository's signature defect rather than a head start. Spent as the
        advance because that is what the key press MEANS while a line is on
        screen: `ScriptRun.on_action` reads neither of its arguments, exactly
        as `SceneFlow.on_action` does, since which action advances a run is
        the router's decision and re-testing the token here would be a second
        copy of the routing rule.

        A run that has FINISHED is not running, so the next press starts a
        fresh one over the same variable store -- which is what lets the
        shipped script's `if` reach its second arm.

        Registered in `load_test_objects`, and NOT in `prepare_test_scene`:
        a subclass INHERITS that method by identity and OVERRIDES this one, so
        a route registered in the caller is the shipped game's wiring silently
        installed in every game built on this class. (And do not name the
        sibling suite that measures it here: this module is the smoke
        baseline, so a check asserts main.py does not so much as SPELL that
        package's name.)

        Begins with `trigger="use"`, which is the trigger kind route A IS:
        `enter`, `exit` and `stay` are region triggers, reached by proximity,
        and that is a wire nothing in `scripts/` reads. The firing's payload
        is passed through, so a page declaring one answers only its own
        interaction while a page declaring none answers any -- the rule
        `ActionRouter` spells as `ANY_PAYLOAD`, written once on each side
        rather than as a second convention.
        """
        running = self.script_run
        if running is not None and running.running:
            running.on_action(entity, fired)
            return
        # THE SLOT IS THE THING THAT IS MODAL, and testing the run instead of
        # the slot is the guard reading the wrong variable. `SceneManager.flow`
        # holds ONE flow; the paragraph above refuses a second run because two
        # would each restore the agency the other changed -- and a `SceneFlow`
        # sitting in that slot is exactly the sibling it cites, so starting
        # over the top of one silently evicted it, never ticked it again, and
        # stranded the body under its `hold` with no way to release. Measured
        # on the shipped class before this line existed: `scene.flow is the
        # other flow` went True -> False in one press and the evicted flow's
        # `update()` was never called again.
        #
        # A FINISHED RUN OF OUR OWN IS NOT A FOREIGN OCCUPANT: the next press
        # has to be able to start a fresh one over the same variable store --
        # which is what lets the shipped script's `if` reach its second arm.
        #
        # AND A FINISHED FOREIGN FLOW IS NOT AN OCCUPANT AT ALL. This line
        # once read `occupant is not self.script_run` and nothing else, which
        # exempted exactly one kind of finished occupant -- our own -- and not
        # the sibling kind. Nothing cleared `SceneManager.flow` when a flow
        # ended, so on any game that played one cutscene the slot held a
        # `SceneFlow` whose `running` was False for the rest of the session,
        # and every later press was refused in silence: ONE CUTSCENE DISABLED
        # EVENT SCRIPTS PERMANENTLY. Measured on the narrative kit -- eight
        # presses after the opening flow ended started nothing, said nothing,
        # warned nothing. The never-cleared finished flow had been filed as
        # hygiene rather than as a defect, and it was, until a guard that was
        # correct in isolation turned it into a lock-out. It is the clearest
        # example in this tree of the shape the ACTIVE WARNINGS record: the
        # guard was right about the occupant it was written against and wrong
        # about the occupant standing beside it.
        #
        # `post_update` empties the slot now, so on the shipped loop this
        # line usually reads None where it used to read a corpse -- and the
        # liveness test stays anyway, because the two are not the same
        # instant: this runs in `inputs`, the clear runs after, and a manager
        # nobody post-updates never clears at all.
        #
        # `getattr(..., True)` and not `occupant.running`: the slot's contract
        # is `update(delta)` and nothing else -- `SceneManager` names a queue
        # wrapper, a fade and a test double as legitimate occupants -- so an
        # occupant that cannot say whether it is running is treated as
        # running. That refusal is the conservative half: it is the behaviour
        # that shipped, it never evicts anybody, and it keeps this file from
        # inventing a contract for an object it does not own.
        occupant = self.scene.flow
        if (occupant is not None and occupant is not self.script_run
                and getattr(occupant, "running", True)):
            return
        script_id = self.script_for(entity)
        if script_id is None:
            return
        run = ScriptRun(self.scripts[script_id],
                        variables=self.script_vars,
                        bodies=[record.entity
                                for record in self.renderer.spawned_entities],
                        host=self.dialogue,
                        scripts=self.scripts,
                        name=script_id)
        # Zero passing pages is not an error and starts nothing: a keeper with
        # nothing to say today is a real idiom. Leaving the flow slot alone in
        # that case matters -- a run that never began, parked in the slot,
        # would be ticked by `post_update` for ever to no effect.
        if run.begin(trigger="use", payload=getattr(fired, "payload", "")):
            self.script_run = run
            self.scene.flow = run

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