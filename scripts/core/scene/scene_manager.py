from __future__ import annotations
from typing import Any, Callable, Mapping, Sequence

import pygame
from pygame import Surface

from scripts.core.event_types import GameEventType
from scripts.core.game_object import PyoneerGameObject
from scripts.core.renderer import LayerRenderer
from scripts.core.scene.game_scene import GameScene
from scripts.core.spawn import resolve_depth, spawn
# `scripts/core/` importing `scripts/game/` at module level is the established
# shape of this tree, not a new coupling introduced here. MEASURED: the two
# `scripts.core` imports above -- `renderer`, which imports `scripts.game
# .behavior`, `GameEntity`, `GameCamera` and `GameMap` itself, and `spawn`,
# which imports `GamePlayer` -- already put 16 `scripts.game` modules on this
# file's path, including every one named below except the flow. So five of the
# six names here cost nothing, and the sixth costs the three-module flow
# package, which is CONSTRUCTED here rather than merely annotated.
# The one-way rule this repository actually enforces is law 2, `scripts/` may
# never import `editor/`, and every tier-2 map file prints these names for
# exactly that audit; `tools/check_flow.py` asserts both halves. Deferring
# them into function bodies would hide 16 modules that load anyway and would
# trade an ImportError at boot for one on the first spawn.
from scripts.game.behavior import build as build_behaviors
from scripts.game.behavior import read_requests
from scripts.game.behavior.state import LIFE_GONE, state_of
from scripts.game.entity.game_entity import GameEntity
from scripts.game.flow.router import ActionRouter
from scripts.game.game_camera import GameCamera
from scripts.game.game_map import GameMap

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

        self.actions: ActionRouter = ActionRouter()
        """Where every action a bound entity fires arrives. The engine's host.

        `action_relay` reads an entity's action record and calls
        `entity.action_sink(entity, fired)`. Nothing in the repository had
        ever assigned one -- the behavior's registry status was `needs-host`
        for exactly that reason -- so a firing reached the end of the frame and
        stopped. This is the assignment, and `__sink` below hands it out on
        both binding routes for the same reason `LayerRenderer.__gate` hands
        out the collision field on both: a map-spawned entity and a hand-built
        one must not end up wired differently, and neither caller should have
        an ordering rule to get wrong.

        It is a CALL and not a dispatch. See `scripts/game/flow/router.py` for
        the measurement that makes that mandatory rather than stylistic.
        """

        self.flow: Any = None
        """The `SceneFlow` currently running, if any. Ticked in post_update.

        One slot, not a list. A narrative flow is modal by nature -- it takes
        the player's steering away -- and two running at once would each
        restore the agency the other had already changed. A game that wants a
        queue owns the queue and hands this one flow at a time.

        Duck-typed on `update(delta)`, and that method is the whole contract:
        a game may hand this slot a queue wrapper, a fade, or a test double,
        so the annotation says what is required rather than naming one class
        that happens to satisfy it.

        The reason is NOT an import-path argument, and the import-path
        argument is false here -- measured, and asserted by
        `tools/check_flow.py` in a subprocess so it cannot quietly become true
        again. `from scripts.game.flow.router import ActionRouter` at the top
        of this file executes `scripts/game/flow/__init__.py`, which imports
        `scene_flow`, so binding a scene already loads ALL THREE flow modules.
        Annotating `SceneFlow` here would add nothing to that path.
        """

    def __bind_renderer(self, renderer: LayerRenderer | None):
        self.renderer = renderer

    def __bind_camera(self, camera: GameCamera | None):
        self.renderer.bind_camera(camera)
        self.camera = camera

    def __require_scene(self, doing: str) -> GameScene:
        """The current scene, or raise naming what was being attempted.

        One sentence, one place. `bind` is not the only entry point that
        cannot proceed without a scene -- `spawn` asks FIRST, before it has
        constructed anything -- and two call sites spelling
        "call set_scene() first" is two chances for one of them to stop
        saying it.
        """
        if self.current_scene is None:
            raise PyoneerSceneError(
                f"no current scene to {doing}; call set_scene() first")
        return self.current_scene

    def bind(self, depth_or_definition: str | int, game_object: PyoneerGameObject | GameCamera | LayerRenderer):
        if isinstance(game_object, GameCamera):
            self.__bind_camera(game_object)
            return
        elif isinstance(game_object, LayerRenderer):
            self.__bind_renderer(game_object)
            return
        scene = self.__require_scene(
            f"bind {type(game_object).__name__} into "
            f"at {depth_or_definition!r}")
        scene.bind(depth_or_definition, game_object)
        self.renderer.bind(depth_or_definition, game_object)
        self.__sink(game_object)
        if isinstance(game_object, GameMap):
            self.__bind_spawned_entities()

    def __sink(self, game_object):
        """Hand `game_object` the scene's action router as its `action_sink`.

        The hand-built half. `__bind_spawned_entities` is the map-placed half,
        and both call this one method -- the argument `LayerRenderer.__gate`
        already makes for the collision field, quoted rather than re-derived:
        an entity that reached a frame through some second route and stayed
        unwired would not raise, would not warn, and would fire actions that
        reached nothing while everything around it worked.

        Assigns unconditionally, overwriting a previous scene's router, for
        the same reason the gate assigns None: whichever scene an entity is
        bound into is the scene whose routes it should reach.

        Only a `GameEntity`. A `GameComponent` has no action record and no
        relay; giving it the attribute would put a wire on 124 widgets that
        nothing reads.
        """
        if isinstance(game_object, GameEntity):
            game_object.action_sink = self.actions

    def __bind_spawned_entities(self):
        """Give the entities the map just spawned their frame updates.

        renderer.bind(GameMap) constructs every typed object on the map's
        object layers and binds it into an EntityLayer. That is enough to DRAW
        an entity and nothing else: EntityLayer.core_frame_update is a no-op,
        so one that lives only in the renderer holds its first animation frame
        forever and never moves. Everything main.py binds by hand goes into
        the scene as well, and a map-spawned entity is not a different kind of
        object -- it just had nobody to bind it until now.

        Into the SCENE only. The renderer already holds them, and binding them
        there a second time would queue every sprite twice per frame.
        """
        for record in self.renderer.spawned_entities:
            self.current_scene.bind(record.depth, record.entity)
            self.__sink(record.entity)

    # -- construct and destroy, at runtime ----------------------------------
    #
    # The two halves of "dynamic event creation/destruction". `spawn` is a
    # composition of parts that all already existed and needed a name;
    # `despawn` is the half that did not exist at all, because
    # `LayerRenderer` had no unbind and an entity taken out of the scene went
    # on queueing a blit token every frame forever.

    def spawn(self,
              type_name: str,
              position: Sequence[float] = (0.0, 0.0),
              *,
              depth: int | str | None = None,
              properties: Mapping[str, Any] | None = None,
              registry: Mapping[str, Callable] | None = None,
              **kwargs: Any) -> Any:
        """Construct, place, compose and bind one entity. The inverse of despawn.

        `properties` is a tmx-object-shaped mapping -- `pyoneer_behaviors` and
        `pyoneer_param_*` -- and is read through `scripts.game.behavior
        .read_requests`, the SAME reader a map-spawned object goes through.
        A runtime spawn and an authored one therefore cannot disagree about
        what a token means, and a game that builds a projectile in Python
        spells its behavior list exactly as Tiled would.

        `depth=None` resolves through `scripts.core.spawn.resolve_depth`, so
        `pyoneer_depth` on the properties, then the per-class convention, then
        the default -- one home for the depth ladder rather than a second copy
        of it here.

        The `moveto` is not optional and is not this method being helpful:
        `GameEntity.__init__` accepts a `transform` keyword and THROWS IT
        AWAY, so every constructor of an entity in this engine has to place it
        afterwards. Doing it here is what stops the next caller finding that
        out at (0, 0).

        THE SCENE IS ASKED FOR FIRST, BEFORE ANYTHING IS BUILT. `bind` at the
        bottom carries the same guard, and that was measured as the wrong
        place for it. With the guard only there, a spawn on a manager with no
        scene constructed the entity, moved it to the asked-for position and
        ran `attach_all` -- `behaviors.names` was already
        `('lifecycle_mark',)` -- before anyone was told the call could not
        succeed. Every behavior's `attach` hook had run by then, and an
        `attach` is where a behavior audits what it needs (law 10), so the
        first exception an author saw was whichever one of those fired.

        And when none did, the message still came out of `bind`, which knows
        the CLASS the registry built and not the tmx TYPE the caller typed:
        measured, `no current scene to bind Counted into at 50` for a
        `spawn("CountedProbe", ...)`. Asking here names `'CountedProbe'`.
        `tools/check_lifecycle.py` section 8 asserts the type name is in the
        message and that the construction counter is still zero.
        """
        self.__require_scene("spawn %r into" % type_name)
        props = dict(properties or {})
        where = "SceneManager.spawn(%r)" % type_name
        entity = spawn(type_name, registry, **kwargs)
        entity.moveto((float(position[0]), float(position[1])))
        requests = read_requests(props, where=where)
        if requests:
            # BEFORE the bind, exactly as `__prepare_entity_layers` composes
            # before binding: `attach_all` raises on a duplicate token, a
            # declared conflict, or two behaviors at one order writing one
            # field, and an entity that reached a frame half-composed would
            # present as a physics bug rather than as an authoring error.
            entity.behaviors.attach_all(build_behaviors(requests))
        self.bind(resolve_depth(type_name, props, where=where)
                  if depth is None else depth, entity)
        return entity

    def __forget_spawn_record(self, game_object) -> bool:
        """Drop `game_object`'s row from `renderer.spawned_entities`.

        The THIRD removal, and the one `despawn`'s "both removals" sentence
        used to be wrong about. `LayerRenderer.unbind` empties the layer, and
        `spawned_entities` -- the map bind's document-order list of what it
        constructed -- is a separate list that still holds a record, so a
        reaped body stayed reachable from the renderer for as long as the map
        was bound. Measured on a two-object fixture map: after
        `despawn(a)`, `len(renderer.spawned_entities)` was still 2 and
        `a` was one of them.

        RESURRECTION IS NOT REACHABLE, and this is not the fix for it.
        `__bind_spawned_entities` iterates that list and would re-bind
        anything in it, but `LayerRenderer.__prepare_entity_layers` REBINDS
        `spawned_entities` to a freshly spawned list on every map bind, and
        `SceneManager.bind` only reaches `__bind_spawned_entities` through
        `renderer.bind(GameMap)`, which is what runs it. Measured: after a
        second bind of the same map, a despawned entity is in neither the
        list nor the scene. What this method fixes is the RETENTION.

        Here rather than in `LayerRenderer.unbind` because `SceneManager` is
        the list's only engine-side reader -- `__bind_spawned_entities` is
        what turns a record into a live entity -- and `despawn` is the one
        method that has to undo that. Identity, never equality, for the
        reason `LayerRenderer.unbind` gives at length: `list.remove` uses
        `==`, and an entity that defined it would take a DIFFERENT record out.
        """
        renderer = self.renderer
        if renderer is None:
            return False
        kept = [record for record in renderer.spawned_entities
                if record.entity is not game_object]
        if len(kept) == len(renderer.spawned_entities):
            return False
        renderer.spawned_entities = kept
        return True

    def despawn(self, game_object: PyoneerGameObject) -> bool:
        """Take a bound object out of the scene AND out of the renderer.

        Returns whether anything was removed, so it is idempotent: a body
        despawned by hand and then reaped from its own `state.life` answers
        True once and False after.

        ALL THREE removals, which is the whole point. Measured before this
        method existed: `scene.unbind(50, entity)` emptied the scene bucket,
        the renderer still held the entity, and `EntityLayer.core_render_blits`
        went on queueing a token for it every frame -- an object that had
        stopped updating and would draw its final animation frame forever.
        The third is `__forget_spawn_record`, added after the first two
        because a map-spawned body that had stopped updating and stopped
        drawing was still held by `renderer.spawned_entities`. Any removal
        alone is a leak in one direction or another.

        The behaviors are detached, in reverse run order, because that is what
        `EntityBehaviors.detach_all` is for and because an action behavior's
        `detach` releases its slot in the record. `GameEntity
        .core_lifecycle_dispose` is still `pass` and is deliberately not
        called: nothing in the engine calls it today, and giving it a first
        caller inside a despawn would make this method the thing that decides
        what disposal means for every entity in the engine.

        The state record is marked `gone` on the way out, so a caller holding
        the entity can ask it rather than having to remember.
        """
        removed_from_scene = (self.current_scene is not None
                              and self.current_scene.discard(game_object) is not None)
        removed_from_render = (self.renderer is not None
                               and self.renderer.unbind(game_object))
        # Unconditionally, and BEFORE the early return, so a record can never
        # outlive the two bindings: an entity a caller had already taken out
        # of the layer by hand would otherwise leave its row behind forever
        # with no call left that would remove it.
        forgotten = self.__forget_spawn_record(game_object)
        if not (removed_from_scene or removed_from_render or forgotten):
            return False
        behaviors = getattr(game_object, "behaviors", None)
        if behaviors is not None and hasattr(behaviors, "detach_all"):
            behaviors.detach_all()
        state = state_of(game_object)
        if state is not None:
            state.life = LIFE_GONE
        return True

    def reap(self) -> tuple:
        """Despawn every bound object that has declared itself gone.

        The reader of `state.life`, and the only one that ACTS. Called once
        per frame from `post_update`, AFTER `GameScene.core_frame_update_post`
        has returned -- so nothing is removed from a list while that list is
        being iterated. That ordering is the reason `lifecycle_mark` marks
        instead of unbinding: measured on this engine, an object that removes
        itself from inside its own update makes the fan-out SKIP THE NEXT
        SIBLING, silently, for one frame.

        The scan walks `GameScene.contents()`, which is a snapshot, so
        despawning during the loop is safe by construction rather than by
        care. Returns the objects it reaped, for a trace or a check.
        """
        if self.current_scene is None:
            return ()
        gone = []
        for _bucket, game_object in self.current_scene.contents():
            state = state_of(game_object)
            if state is not None and state.gone:
                gone.append(game_object)
        for game_object in gone:
            self.despawn(game_object)
        return tuple(gone)

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
        # Both of these are DRAINS and both run here for one reason: the scene
        # fan-out has returned, so a flow that opens a window and a reap that
        # removes a body cannot mutate a list something is iterating. Moving
        # either into `update` would put them back inside that window.
        #
        # `delta` is passed through unconverted. It is milliseconds/60 and
        # `SceneFlow.update` converts; doing the arithmetic here would put the
        # ~16.7x error at the call site, which is where it always is.
        if self.flow is not None:
            self.flow.update(delta)
        self.reap()

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