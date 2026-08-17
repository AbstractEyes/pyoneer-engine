"""The demo boot path, extracted once so a demo is not a copy of main.py.

WHAT WAS MEASURED BEFORE WRITING THIS
--------------------------------------
`main.py` is 135 code lines. About 90 of them are the engine spine --
`__init__`, `prepare`, `build`, `load_config`, `load_renderer`, `begin`,
`tick`, `quit`, `toggle_window`, and most of `prepare_test_scene` -- and
they are identical for every game. The genuinely per-game part is three
methods, and `MainGame` already calls all three as hooks:

    load_map()            which map, and the camera over it
    spawn_arguments()     constructor arguments a .tmx cannot carry
    load_test_objects()   entities built in Python rather than authored

So the extraction is a SUBCLASS, not a new framework. `DemoGame` overrides
two of those three -- `spawn_arguments` is inherited unchanged, because a
demo wants exactly the arguments `main.py` hands a `GamePlayer` -- and a
concrete demo below it is a map name and a docstring.

Nothing here is a second implementation of anything in `main.py`. If you
find yourself copying a method out of `MainGame` into this file, the method
wanted a hook and the hook is the change.

WHAT DemoGame ADDS THAT MainGame CANNOT
----------------------------------------
Exactly two values, and both are things a `.tmx` object has no way to say:

  the camera target   `main.py` attaches the camera to the player it built
                      itself. A map-spawned demo has no such handle, so the
                      target is derived from the composition: the entity
                      carrying `player_input` IS the one the human drives
                      (scripts/game/behavior/input.py says so), and
                      `SpawnedEntity.behaviors` already carries the resolved
                      list. No new property, no `pyoneer_player` flag.
  the collision anchor `GameEntity.collision_offset` defaults to (0, 0),
                      which is the sprite's TOP-LEFT -- a 64px character's
                      head. A side-on body wants feet. There is no tmx
                      property and no behavior parameter for it today, so a
                      demo that wants feet sets it here and says so. See
                      docs/DEMOS.md, "What a demo still has to say in
                      Python".

WHAT DemoGame DELIBERATELY DOES NOT DO
---------------------------------------
It does not assign `GameEntity.collision_field`, and it must not. Baking the
map's passability and handing it out is the ENGINE's job, and the engine does
it: `LayerRenderer.__bind_map` bakes once with `collision_runtime.field_from_map`
and gates every entity it binds, by both routes. A demo doing it privately
would make `demos/sidestep.py` work while every other map-driven game stayed
ungated, and would hide a gap instead of reporting it -- so if a body ever
falls forever here, that is the report working.
"""
from __future__ import annotations

import argparse

import pygame

from config.managers.map_data import MapData
from main import MainGame
from scripts.game.game_camera import GameCamera
from scripts.game.game_map import GameMap

from demos.mapgen import ensure_map


def driven_record(records):
    """The spawned record that carries `player_input`, or None.

    This is the whole "which object is the player" question, answered from
    the composition rather than from a flag. `SpawnedEntity.behaviors` holds
    the RESOLVED `BehaviorRequest`s, so the token is compared against
    `spec.name` -- the registry's own spelling -- and not against a substring
    of the raw property, which would also match `player_input_recorder`.
    """
    for record in records:
        if any(request.spec.name == "player_input"
               for request in record.behaviors):
            return record
    return None


class DemoGame(MainGame):
    """A game that is a map plus two class attributes.

    Subclass, set `MAP_NAME`, and you have a running game. Everything else on
    this class exists to serve the three demos and is documented where it is
    not obvious.
    """

    MAP_NAME: str = ""
    """Key in `demos.mapgen.SOURCES`. Its .tmx is written on first use."""

    COLLISION_OFFSET: tuple[float, float] | None = None
    """Where every spawned entity's collision point sits in its sprite.

    None leaves `GameEntity`'s default of (0, 0) -- the sprite's top-left,
    which for a 44x64 character is the top of its head. `(22.0, 63.0)` is
    feet: half the sprite wide, one pixel above its bottom edge. Applied per
    entity in `load_test_objects` because there is no authoring surface for
    it; if one ever lands, delete this and put the number in the map.
    """

    # ---------------------------------------------------------------- hooks

    def load_map(self) -> tuple[GameCamera, GameMap]:
        """Register this demo's map with the asset manager, then load it.

        Through `AssetMapManager` and not through a bare `pytmx.load_pygame`,
        so a demo map is cached, reloadable and reports a missing file the
        same way a shipped map does -- one loader, not two. It is registered
        here rather than added to `config/maps.json` because that file is the
        shipped game's map list; a demo declaring its own map must not edit
        it, and `AssetMapManager.maps` is a plain dict for exactly this.
        """
        if not self.MAP_NAME:
            raise ValueError("%s declares no MAP_NAME; a demo is a map plus a "
                             "class" % type(self).__name__)
        path = ensure_map(self.MAP_NAME)
        self.assets.maps.maps[self.MAP_NAME] = MapData({
            "name": self.MAP_NAME,
            "identifier": self.MAP_NAME,
            "file": path,
        })
        map_data = self.assets.maps.load_assets(self.MAP_NAME)
        camera = GameCamera(
            pygame.Vector2(self.screen.get_width(), self.screen.get_height()),
            pygame.Rect(0, 0,
                        map_data.tilewidth * map_data.width,
                        map_data.tileheight * map_data.height),
            scale=1)
        return camera, GameMap(map_data)

    def load_test_objects(self):
        """Configure what the MAP spawned, and build nothing.

        `MainGame.prepare_test_scene` calls this AFTER `bind("MAP", ...)`, so
        `renderer.spawned_entities` is already populated. Returning an empty
        list is the point: every entity in a demo comes from the .tmx.
        """
        records = list(self.renderer.spawned_entities)
        if self.COLLISION_OFFSET is not None:
            for record in records:
                record.entity.collision_offset = self.COLLISION_OFFSET
        driven = driven_record(records)
        # Fall back to the first spawned entity so the camera has something to
        # follow on a map with no driven object, and so `main.py`'s arrow-key
        # handler -- which dereferences `self.player` unconditionally -- has an
        # entity rather than a None. A demo with an empty object layer leaves
        # both None, which is honest: there is nothing to watch.
        followed = driven or (records[0] if records else None)
        if followed is not None:
            self.player = followed.entity
            self.scene.camera.attach_target(followed.entity)
        return []

    # ------------------------------------------------------------ reporting

    @property
    def spawned(self):
        """Every record the map spawned, in document order."""
        return list(self.renderer.spawned_entities)

    def entity_of(self, object_id: int):
        """The entity spawned for the tmx `<object id="N">`, or None.

        The object id is the only stable handle a map gives an entity:
        `SpawnedEntity` is frozen and carries `object_id`, not `name`, and it
        belongs to `scripts/`, which this package may not edit. Tiled shows
        the id beside the object, so an author and a check address the same
        thing. Returns None rather than raising -- asking for an object a map
        does not have is a question, and a diagnostic should not crash.
        """
        for record in self.spawned:
            if record.object_id == object_id:
                return record.entity
        return None


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one Pyoneer demo. Close the window or press Escape "
                    "to quit; --frames bounds the run for a scripted one.")
    parser.add_argument("--frames", type=int, default=None,
                        help="stop after N frames instead of running until "
                             "quit. tools/check_demos.py drives the demos "
                             "this way.")
    return parser.parse_args(argv)


def run(game_class, argv=None) -> int:
    """Boot one demo class from the command line. The whole of a demo's main."""
    args = parse_args(argv)
    game = game_class(autostart=False)
    game.begin(max_frames=args.frames)
    return 0


__all__ = ["DemoGame", "driven_record", "run"]
