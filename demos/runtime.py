"""The demo boot path, extracted once so a demo is not a copy of main.py.

`MainGame` already calls the three per-game parts as hooks:

    load_map()            which map, and the camera over it
    spawn_arguments()     constructor arguments a .tmx cannot carry
    load_test_objects()   entities built in Python rather than authored

`DemoGame` is a subclass overriding two of them -- `spawn_arguments` is
inherited unchanged, since a demo wants the arguments `main.py` hands a
`GamePlayer` -- so a concrete demo below it is a map name and a docstring. If
you find yourself copying a method out of `MainGame` into this file, the
method wanted a hook and the hook is the change.

`DemoGame` supplies the ONE value a `.tmx` object has no way to say:

  the camera target    derived from the composition -- the entity carrying
                       `player_input` is the one the human drives -- rather
                       than from a flag.

It no longer supplies the collision anchor. `GameEntity.collision_offset` is
a constructor keyword now, `main.py`'s `spawn_arguments()` derives it from
the animation category with `feet_anchor`, and `spawn_arguments` is the one
hook `DemoGame` inherits UNCHANGED -- so every body a demo map spawns is
anchored at its feet by the same route that anchors the shipped game's
player. A demo that reassigned `collision_offset` afterwards would pass on
its own and hide a broken shared route from every other map-driven game,
which is exactly what it did while it was doing it.

It does not assign `GameEntity.collision_field` either: baking the map's passability
and handing it out is the engine's job, done once in
`LayerRenderer.__bind_map` via `collision_runtime.field_from_map`. A demo
that gated its own entities privately would hide the gap for every other
map-driven game.
"""
from __future__ import annotations

import argparse

import pygame

from config.managers.map_data import MapData
from main import MainGame
from scripts.game.game_camera import GameCamera
from scripts.game.game_map import GameMap
from scripts.loaders.map_loader import driven_record

from demos.mapgen import ensure_map

# RE-EXPORTED, NOT REIMPLEMENTED. This file used to carry its own copy of the
# three-line pick -- same rule, same token, a second spelling of it -- which
# is law 2's corollary at small scale, and that corollary was paid once at
# 425 duplicate lines. The one definition is in `scripts/`, the engine half,
# because that is the only package BOTH callers may name: this module already
# imports `main`, and `main` may not spell this package's name at all
# (`tools/check_demos.py` asserts it, because main.py is the smoke baseline).
#
# The name stays exported here so a demo and a check still say
# `from demos.runtime import driven_record`, which is the editor-re-exports
# shape the corollary prescribes, one package down.


class DemoGame(MainGame):
    """A game that is a map plus two class attributes.

    Subclass, set `MAP_NAME`, and you have a running game.
    """

    MAP_NAME: str = ""
    """Key in `demos.mapgen.SOURCES`. Its .tmx is written on first use."""

    # ---------------------------------------------------------------- hooks

    def load_map(self) -> tuple[GameCamera, GameMap]:
        """Register this demo's map with the asset manager, then load it.

        Through `AssetMapManager` rather than a bare `pytmx.load_pygame`, so a
        demo map is cached, reloadable and reports a missing file the way a
        shipped map does. Registered here rather than in `config/maps.json`,
        which is the shipped game's map list.
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

        It configures NO entity attributes. The collision anchor used to be
        reassigned here, per record, after the map had already built them;
        it now arrives through `spawn_arguments()` at construction, so this
        method only picks the camera's target.
        """
        records = list(self.renderer.spawned_entities)
        driven = driven_record(records)
        # Fall back to the first spawned entity so the camera has something to
        # follow on a map with no driven object, and so `main.py`'s arrow-key
        # handler -- which dereferences `self.player` unconditionally -- has an
        # entity rather than a None. An empty object layer leaves both None.
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

        The object id is the stable handle a map gives an entity, and the one
        Tiled shows beside the object, so an author and a check address the
        same thing. Returns None rather than raising: this is a diagnostic.
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
