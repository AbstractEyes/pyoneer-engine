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
from scripts.loaders.script_file import SCRIPT_PROPERTY, script_of
from scripts.loaders.table_file import actor_row

from scripts.core.depth import OBJECT_CONVERTER, OBJECT_DEPTH, MAP_DEPTH

import scripts.core.event_manager as EventManager
from scripts.core.event_manager import PyoneerEvent
from scripts.core.errors import PyoneerConfigError, PyoneerSceneError


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

        `properties` is a tmx-object-shaped mapping, and the claim this
        method makes is that EVERY per-object `pyoneer_` property the map
        route reads is read here too, so a runtime spawn and an authored one
        cannot disagree. The family has FIVE members and this is the whole
        roster, enumerated rather than described, because the last time it
        was described in prose a new member shipped on ONE route only and the
        prose went on reading as though it had not:

            `pyoneer_behaviors`   `read_requests`, the SAME function
            `pyoneer_param_*`     `read_requests` -> `resolve_params`, same
            `pyoneer_actor`       `actor_row`, the SAME function
            `pyoneer_depth`       `resolve_depth`, the SAME function -- and
                                  only when the caller named no `depth=`,
                                  since an explicit argument wins here as it
                                  does in `__constructor_arguments`
            `pyoneer_script`      `script_of`, through `__join_script` below
                                  -- the same function the map route calls,
                                  since the pass that wrote this roster owed a
                                  shared reader and the next one wrote it

        So the full parameter ladder applies: the properties' own
        `pyoneer_param_*`, then the actors row, then each parameter's
        declared default.

        The fifth row was a copy for one pass and is not one now. The map
        route's reader lives in the game module and `scripts/` may not import
        that -- it is the smoke baseline and the dependency runs the other way
        -- so the shared half went where the property NAME already lives:
        `scripts.loaders.script_file.script_of`, which both routes call the
        way both call `actor_row`. `tools/check_spawn_runtime.py` pins that
        they are one function and not two agreeing spellings.

        The constructor arguments come from the renderer's `spawn_defaults`,
        the SAME dict `spawn_objects` applies to a map-placed object, merged
        under `kwargs` -- see `__constructor_arguments` for the precedence and
        for what it cost to read that slot on one route only.

        `depth=None` resolves through `scripts.core.spawn.resolve_depth`:
        `pyoneer_depth` on the properties, then the per-class convention,
        then the default. The constructed class's own `__name__` is handed to
        that second rung, because a registry entry may be an alias ("Hero" ->
        GamePlayer) and the depth table is keyed by CLASS -- the map route
        passes it, so a runtime spawn of the same type must resolve the same
        depth rather than falling through to the default.

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
        entity = spawn(type_name, registry,
                       **self.__constructor_arguments(type_name, kwargs))
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
        # BEFORE the bind, and one step earlier than the map route can manage:
        # the map join has to run after `bind("MAP", ...)` because the spawn
        # RECORDS are what it joins on, while this route holds the object and
        # its properties in one hand. Earlier is strictly better for the same
        # reason `attach_all` sits above the bind -- a body naming a script
        # that is not there never reaches a layer -- and the observable is the
        # same: a raise naming the object and listing what does exist.
        self.__join_script(entity, props, where)
        self.bind(resolve_depth(type_name, props,
                                class_name=type(entity).__name__, where=where)
                  if depth is None else depth, entity)
        return entity

    def __join_script(self,
                      entity: Any,
                      properties: Mapping[str, Any],
                      where: str) -> str | None:
        """Join a runtime-spawned body to the event script it names.

        THE FIFTH MEMBER OF THE `pyoneer_` FAMILY, and the one that arrived on
        the map route alone. Measured before this existed: the same property,
        the same shaped mapping, and an absent script id raised `event script
        'x' not found` through the map bind while `SceneManager.spawn` built
        the entity and said nothing -- so a projectile, an NPC or a summon
        carrying `pyoneer_script` was silently inert, which is the shape law 8
        refuses and the shape a map object has been protected from since the
        property existed.

        Returns the script id it joined, or None for a body that names none.
        A body naming none is untouched, exactly as `__actor_row` leaves a
        spawn that names no row untouched.

        THE TABLE IS THE HOST'S, NOT A SECOND ONE OF THIS MANAGER'S OWN, on
        `__constructor_arguments`'s rule one layer up: the scripts are read
        once at boot, before the map is bound, and both routes must read that
        one mapping or a runtime body would resolve `greeting` against a table
        the authored body beside it never saw. `self.game` is the slot because
        that is where the boot puts them -- the renderer carries
        `spawn_defaults` and `tables` and does not carry these -- and it is
        read AT SPAWN TIME rather than copied when the manager was built, so a
        script table assigned after construction is the one a spawn resolves
        against.

        ABSENT AND EMPTY ARE DIFFERENT MISTAKES, as they are in `actor_row`,
        and `script_of` is where that split is drawn for both routes: a host
        with no `scripts` attribute at all is a WIRING error naming the
        attribute, while a table that is merely EMPTY is an AUTHORING error
        listing what does exist. The one refusal still spelled HERE is the
        other attribute -- a host holding a script table and no
        `object_scripts` list can read the document and has nowhere to record
        it -- which `script_of` cannot raise, because the map route fills that
        list at a different moment and the shared reader returns an id rather
        than performing a join.

        THE JOIN IS THE HALF THAT MAKES THE RAISE WORTH HAVING. Adding the
        guard and not the row would leave a runtime body that names a REAL
        script still unable to run it -- the capability complete, checked, and
        unreachable by the person who asked for it, which is this
        repository's signature defect. The row goes into the same list the map
        join fills, so the host's identity search answers for an authored body
        and a Python-built one alike.

        NOT WARNED ABOUT HERE: a body naming a script and missing the
        `interact_action` / `action_relay` tokens. The map route warns about
        that, deliberately, because on a map those two tokens are the ONLY
        wire from a key press to the run. A runtime caller holds the entity it
        just built and can route the firing itself, so the same warning would
        fire on a legitimate pattern -- and the two token names are the game
        module's own constants, which this package may not import. Stated
        rather than left to be discovered.
        """
        # THE SHARED READER, and not a copy of it any more. `script_of` does
        # the falsy test, the absent/empty split and both refusals; the map
        # route in the game module calls the same function with its own
        # `where`, so the two messages differ only in whom they blame.
        script_id = script_of(getattr(self.game, "scripts", None),
                              properties, where)
        if script_id is None:
            return None
        joined = getattr(self.game, "object_scripts", None)
        if joined is None:
            raise PyoneerConfigError(
                "%s declares %s=%r and its host game carries no "
                "`object_scripts` list, so the document can be read and not "
                "joined. The boot assigns it beside `scripts` before the map "
                "is bound -- the map join fills it -- and the two are the one "
                "pair the map spawn and `SceneManager.spawn` both read."
                % (where, SCRIPT_PROPERTY, script_id))
        joined.append((entity, script_id))
        return script_id

    def __constructor_arguments(self,
                                type_name: str,
                                kwargs: Mapping[str, Any]) -> dict[str, Any]:
        """`type_name`'s constructor arguments: the renderer's defaults under `kwargs`.

        THE RENDERER'S SLOT, NOT A SECOND ONE OF THIS MANAGER'S OWN, exactly
        as `__actor_row` reads `renderer.tables`. `spawn_defaults` carries
        what a .tmx object cannot -- an `InputActionManager`, a parsed
        animation category, the collision anchor `main.py` derives from the
        sheet -- and it is keyed by the same tmx TYPE NAME `spawn_objects`
        keys it by, so a body built here and a body Tiled placed beside it are
        constructed from one dict.

        Copying those defaults into a second table here is the move this
        repository has already paid 425 duplicate lines for; two tables would
        drift, and the symptom would be a runtime projectile anchored at its
        head while the authored NPC next to it stood on its feet. That was not
        hypothetical: until this method existed, `spawn_defaults` reached the
        map route and nothing else, so EVERY runtime spawn was head-anchored
        and walked 63.9990234375 pixels into a floor at y=64 for the shipped
        44x64 frame -- and looked, from outside, exactly like a body standing
        on it.

        PRECEDENCE: AN EXPLICIT KEYWORD WINS, PER KEY. `kwargs` is applied
        LAST, so a caller naming `collision_offset` gets the one it named and
        still inherits every default it did not name. The order is the ladder
        `resolve_depth` and `resolve_params` already climb -- most specific
        first -- and it is the only order that works in both directions: a
        default that overwrote an argument would make a deliberately placed
        collision point impossible to ask for, while no default at all is the
        defect this method exists to close.

        A missing default costs nothing, matching `tables`: no renderer, no
        entry for this type, or an entry omitting a key all leave the class's
        own constructor default in place. That is not a fallback hiding a
        contract violation -- an argument this dict cannot supply is one the
        class already declares a default for, and a class that truly needs one
        raises from its own `__init__` naming itself.
        """
        defaults = getattr(self.renderer, "spawn_defaults", None) or {}
        arguments = dict(defaults.get(type_name) or {})
        arguments.update(kwargs)
        return arguments

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

    def __forget_script_row(self, game_object) -> bool:
        """Drop `game_object`'s row from the host's object/script join list.

        Identity, never equality, on `__forget_spawn_record`'s rule and for
        its reason: `list.remove` uses `==`, and an entity that defined it
        would take a DIFFERENT body's row out -- which for this list means a
        live body silently losing its script.

        A host with no such list has nothing to forget and that is not an
        error: the same `getattr` shape `__join_script` uses, so a manager
        driven by a test double or by a game that never loaded a script
        despawns exactly as it did before this existed.
        """
        joined = getattr(self.game, "object_scripts", None)
        if not joined:
            return False
        kept = [row for row in joined if row[0] is not game_object]
        if len(kept) == len(joined):
            return False
        joined[:] = kept
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
        # The FOURTH removal, and it is unconditional for the same reason the
        # third is. `__join_script` puts a row in the host's join list and the
        # map bind puts one there for every authored body, so without this a
        # despawned entity stays reachable from that list for the life of the
        # scene -- a strong reference to a reaped body, and an identity search
        # that still answers for it.
        self.__forget_script_row(game_object)
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