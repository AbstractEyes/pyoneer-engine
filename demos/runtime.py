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

AND `load_test_objects` CALLS `super()`, WHICH IS THE WHOLE OF THAT RULE.
It did not, for as long as it existed, and the cost was measured rather than
argued:

    MainGame  scripts=1  object_scripts=1  dialogue=True   routes=(('interact_action', '', 1),)
    DemoGame  scripts=1  object_scripts=0  dialogue=False  routes=()

The boot reads `data/project/scripts/` either way -- that happens in
`prepare_test_scene`, which a subclass inherits BY IDENTITY -- so every demo
paid to load every script and then could not run one, because the join, the
`say` host and the action route all live in the hook a demo overrides. Worse
than the missing feature: both of the map route's guards live there too, so a
demo map's `pyoneer_script` naming a document that is not there RAISED in the
shipped game and was SILENT in a demo. That is law 7's exact failure shape on
the route a new author is likeliest to copy. `demos/narrative.py` already
called `super()` and inherited the hole through this class, so this one call
fixes both.

What the override still exists to do is one deliberate subtraction, spelled
out below: the shipped game's debug window is put away on arrival.

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
        """Inherit the shipped game's hook whole, then put its debug window away.

        SUPER FIRST, AND SUPER FOR EVERYTHING. `MainGame.load_test_objects`
        picks the camera target out of the composition, joins every spawned
        body to the `pyoneer_script` it names, builds the `say` host and
        registers the one action route -- and this class used to do only the
        first of those, in three lines copied out of that method. Two costs,
        both real:

        * the copy itself. It was the same rule, the same `driven_record`
          call and the same fallback, spelled twice, which is law 2's
          corollary at small scale -- and that corollary has already been
          paid once here at 425 duplicate lines.
        * everything the copy did not copy. A demo loaded every event script
          at boot and could never start one, and the two guards the map route
          carries were absent, so a demo map naming an absent script built a
          body that looked scripted and was inert. Deleting the copy restores
          all four in one line.

        Returning what `super()` returns, unfiltered: a demo builds no entity
        of its own -- every body comes from the .tmx -- but the bindable list
        is the parent's to fill and swallowing it would be this class deciding
        what the shipped hook is allowed to bind.

        THE ONE SUBTRACTION, and it is deliberate rather than inherited by
        accident. `MainGame` binds a 400x400 `DemoWindow` holding a focusable
        `TextBox`, and a focused text box SUPPRESSES MOVEMENT: one stray click
        on the most clickable thing on screen and every key a demo is
        demonstrating does nothing, with no message and no way back but F1. A
        demo exists to show one map and one behavior list working, so the
        window arrives CLOSED. `close()` clears both `visible` and `active`,
        so it neither draws nor eats input, and F1 -- `MainGame.toggle_window`,
        inherited by identity -- still opens it. Subtracting it here rather
        than not binding it at all keeps that toggle working and keeps this
        class out of the business of re-implementing the hook.
        """
        bindable = super().load_test_objects()
        if self.window is not None:
            self.window.close()
        return bindable

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
