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
# shape of this tree: `renderer` and `spawn` above already put these modules on
# the path. The one-way rule is law 2 -- `scripts/` may never import `editor/`
# -- and `tools/check_flow.py` asserts it.
from scripts.game.behavior import build as build_behaviors
from scripts.game.behavior import read_requests
from scripts.game.behavior.state import LIFE_GONE, state_of
from scripts.game.entity.game_entity import GameEntity
from scripts.game.flow.router import ActionRouter
from scripts.game.game_camera import GameCamera
from scripts.game.game_map import GameMap
from scripts.loaders.table_file import actor_row

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
        `entity.action_sink(entity, fired)`. `__sink` below assigns this on
        both binding routes, so a map-spawned entity and a hand-built one
        cannot end up wired differently.

        It is a CALL and not a dispatch -- see `scripts/game/flow/router.py`.
        """

        self.flow: Any = None
        """The `SceneFlow` currently running, if any. Ticked in post_update.

        One slot, not a list. A narrative flow is modal -- it takes the
        player's steering away -- and two running at once would each restore
        the agency the other had already changed. A game that wants a queue
        owns the queue and hands this one flow at a time.

        Duck-typed on `update(delta)`, which is the whole contract: a queue
        wrapper, a fade or a test double are all acceptable here.
        """

    def __bind_renderer(self, renderer: LayerRenderer | None):
        self.renderer = renderer

    def __bind_camera(self, camera: GameCamera | None):
        self.renderer.bind_camera(camera)
        self.camera = camera

    def __require_scene(self, doing: str) -> GameScene:
        """The current scene, or raise naming what was being attempted."""
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

        Called from both binding routes -- here for a hand-built object,
        `__bind_spawned_entities` for a map-placed one -- because an entity
        that stayed unwired would not raise and not warn, it would just fire
        actions that reached nothing.

        Assigns unconditionally, overwriting a previous scene's router:
        whichever scene an entity is bound into is the one whose routes it
        should reach.

        Only a `GameEntity`. A `GameComponent` has no action record and no
        relay.
        """
        if isinstance(game_object, GameEntity):
            game_object.action_sink = self.actions

    def __bind_spawned_entities(self):
        """Give the entities the map just spawned their frame updates.

        `renderer.bind(GameMap)` constructs every typed object on the map's
        object layers and binds it into an `EntityLayer`, which is enough to
        DRAW an entity and nothing else: `EntityLayer.core_frame_update` is a
        no-op, so an entity that lives only in the renderer holds its first
        animation frame forever and never moves.

        Into the SCENE only. The renderer already holds them, and binding them
        there a second time would queue every sprite twice per frame.
        """
        for record in self.renderer.spawned_entities:
            self.current_scene.bind(record.depth, record.entity)
            self.__sink(record.entity)

    # -- construct and destroy, at runtime ----------------------------------

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
        `pyoneer_param_*` -- read through the SAME `read_requests` a
        map-spawned object goes through, so a runtime spawn and an authored
        one cannot disagree about what a token means. `pyoneer_actor` is read
        through the same `actor_row` as well, so the full ladder applies:
        the properties' own `pyoneer_param_*`, then the actors row, then each
        parameter's declared default.

        `depth=None` resolves through `scripts.core.spawn.resolve_depth`:
        `pyoneer_depth` on the properties, then the per-class convention,
        then the default.

        The `moveto` is not optional. `GameEntity.__init__` accepts a
        `transform` keyword and THROWS IT AWAY, so an entity has to be placed
        after construction or it sits at (0, 0).

        The scene is required FIRST, before anything is built: `attach_all`
        runs every behavior's `attach` hook, which is where a behavior audits
        what it needs (law 10), and those must not fire for a call that
        cannot succeed. Asking here also names the tmx TYPE the caller typed
        rather than the class the registry built.
        """
        self.__require_scene("spawn %r into" % type_name)
        props = dict(properties or {})
        where = "SceneManager.spawn(%r)" % type_name
        entity = spawn(type_name, registry, **kwargs)
        entity.moveto((float(position[0]), float(position[1])))
        requests = read_requests(props, self.__actor_row(props, where),
                                 where=where)
        if requests:
            # BEFORE the bind, as `__prepare_entity_layers` also composes
            # before binding: `attach_all` raises on a duplicate token or a
            # declared conflict, and an entity that reached a frame
            # half-composed would present as a physics bug rather than as an
            # authoring error.
            entity.behaviors.attach_all(build_behaviors(requests))
        self.bind(resolve_depth(type_name, props, where=where)
                  if depth is None else depth, entity)
        return entity

    def __actor_row(self,
                    properties: Mapping[str, Any],
                    where: str) -> Mapping[str, Any] | None:
        """The actors row `properties` names, read through the renderer's tables.

        The renderer's slot, not a second one of this manager's own: one
        slot with two readers, or a runtime projectile would resolve
        `move_speed` from a default while the object Tiled placed beside it
        read the row.

        With no renderer bound this passes None, and `actor_row` turns that
        into a raise NAMING the missing wiring -- but only for an object that
        declares `pyoneer_actor`. A spawn that names no row is untouched.
        """
        return actor_row(getattr(self.renderer, "tables", None),
                         properties, where)

    def __forget_spawn_record(self, game_object) -> bool:
        """Drop `game_object`'s row from `renderer.spawned_entities`.

        The third removal `despawn` makes. `LayerRenderer.unbind` empties the
        layer, but `spawned_entities` -- the map bind's document-order list of
        what it constructed -- is a separate list, so without this a reaped
        body stays reachable from the renderer for as long as the map is
        bound.

        Here rather than in `LayerRenderer.unbind` because `SceneManager` is
        the list's only engine-side reader. Identity, never equality:
        `list.remove` uses `==`, and an entity that defined it would take a
        DIFFERENT record out.
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

        ALL THREE removals, and any one alone is a leak in some direction:
        the scene bucket stops updating it, `LayerRenderer.unbind` stops
        `EntityLayer.core_render_blits` queueing a token for it every frame,
        and `__forget_spawn_record` stops the renderer retaining it.

        The behaviors are detached in reverse run order, because an action
        behavior's `detach` releases its slot in the record.
        `GameEntity.core_lifecycle_dispose` is deliberately NOT called:
        nothing in the engine calls it, and giving it a first caller here
        would make this method decide what disposal means engine-wide.

        The state record is marked `gone` on the way out, so a caller holding
        the entity can ask it.
        """
        removed_from_scene = (self.current_scene is not None
                              and self.current_scene.discard(game_object) is not None)
        removed_from_render = (self.renderer is not None
                               and self.renderer.unbind(game_object))
        # Unconditionally, and BEFORE the early return, so a record can never
        # outlive the two bindings: an entity already taken out of the layer
        # by hand would otherwise leave its row behind forever.
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
        has returned, so nothing is removed from a list while that list is
        being iterated. That ordering is why `lifecycle_mark` marks instead of
        unbinding: an object that removes itself from inside its own update
        makes the fan-out silently SKIP THE NEXT SIBLING for one frame.

        The scan walks `GameScene.contents()`, which is a snapshot, so
        despawning during the loop is safe. Returns the objects it reaped.
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
        # Both are DRAINS, and both run after the scene fan-out has returned
        # so that a flow opening a window and a reap removing a body cannot
        # mutate a list something is iterating.
        #
        # `delta` is passed through unconverted: it is milliseconds/60 and
        # `SceneFlow.update` is what converts.
        if self.flow is not None:
            self.flow.update(delta)
        self.reap()

    def inputs(self):
        events = EventManager.get_pyo()
        for event in events:
            # A route runs IN ADDITION to the scene fan-out below, never
            # instead of it -- and MUST NOT call event.handle():
            # GameComponent.__send_event returns immediately on a handled
            # event, so consuming here would cut the entire component tree out
            # of that frame's input.
            route = self.routes.get(event.type)
            if route is not None:
                route(event)
            self.current_scene.core_input_receive(event)

    def __on_window_resize(self, event: PyoneerEvent):
        """Re-take the display surface at the new size and re-point everything
        that cached the old one. A renderer holding a stale surface draws a
        black frame with no exception."""
        width, height = event.event.x, event.event.y
        self.game.screen = pygame.display.set_mode((width, height),
                                                   pygame.RESIZABLE)
        if self.renderer is not None:
            self.renderer.image(self.game.screen)
        if self.camera is not None:
            self.camera.view_area.size = (width, height)