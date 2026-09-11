"""Boot the SHIPPED game and assert the map is what produces it.

WHY THIS EXISTS
---------------
Until this check's change, `data/maps/test.tmx` placed no objects at all and
`main.py`'s `load_test_objects` CONSTRUCTED six `GamePlayer`s in Python --
five inert decoys and the one the human drove. So "the engine spawns entities
from an object layer" and "the game you can actually run" were two different
code paths, and every repair to the first was unmeasured on the second: the
feet anchor landed in `spawn_arguments`, reached the hand-built six by being
read back out of it, and reached nothing the map spawned, because the map
spawned nothing.

`tools/check_spawn_runtime.py` already covers the spawn path itself, over its
own fixture. This check covers the OTHER half: that the shipped game is
actually on it. It boots `MainGame` for real -- `__init__` -> `prepare` ->
`build` -> `begin` -> `tick` -- and then presses a key, because
`tools/smoke.py` injects no input and cannot see anything that only happens
while walking.

WHAT IS ASSERTED, AND THE PAIR THAT GIVES EACH ONE TEETH
--------------------------------------------------------
One half of an invariant is the commonest toothless shape in this tree, so
every gate below is asserted in both directions:

    the map named in config/maps.json loads through the real manager
                    AND a name that file does not carry raises, listing what
                        it does carry
    the round trip is byte-identical
                    AND one changed csv token changes the bytes, so the
                        comparison is capable of noticing
    main.py builds no entity, by AST over its parse tree
                    AND the same detector finds one in a source that has one
    the spawn route delivers the feet anchor
                    AND a GamePlayer built WITHOUT it is anchored at its head,
                        which is what the route existing is worth
    the map's passability refuses a step into a wall
                    AND allows the same step away from it, from the same
                        pixel, so the gate is directional and not a freeze
                    AND allows it INTO the wall once the field is cleared, so
                        the clamp provably came from the map
    the authored action chain reaches the scene's router on a press
                    AND does not fire again while the verb is still held
                    AND that same press leaves a RUNNING script in the flow
                        slot, which was empty before anything was touched
                    AND `script_for` answers by identity: a stand-in that
                        claims equality with the hero gets no script
                    AND the route is registered in the hook a subclass
                        OVERRIDES and NOT in the one it inherits by identity,
                        read off main.py's parse tree -- the runtime row
                        above passes either way
    the driven-record pick is ONE function in `scripts/`, by a def count over
    every .py in the tree, and BOTH boot paths call it
                    AND the counter finds both defs in a source with two, and
                        counts an import, an `__all__` entry and a call as
                        none -- which is what makes the re-export safe
                    AND the one function agrees with the adoption: it returns
                        the record whose entity IS `main.py`'s player, and
                        None once the token is taken off every record
    a map whose ADOPTED body lacks `player_input` warns once, naming that
    object, its layer and the token
                    AND a map whose adopted body HAS it warns not at all --
                        on a fixture that still carries a SECOND, undriven
                        body, so "warned too broadly" fails this half
                    AND the warning is a warning: both maps still load, both
                        still spawn, both still adopt a player and run frames

WHAT THIS CHECK MAY PIN, AND WHAT IT MAY NOT
--------------------------------------------
Law 4 says a check asserts what the CODE does, never what a MAP contains, and
commit `333a77a` exists solely to undo two checks that pinned the author's
canvas. `data/maps/starter.tmx` is a different kind of file from the one that
cost: it is not a canvas anybody paints in, it is the DELIVERABLE `main.py`
boots into, named by `config/maps.json`, and "the shipped game still produces
a driven body" is a claim about the shipped game.

So the line drawn here is CONTRACT, never CONTENT. Nothing below names a
coordinate, a gid, a tile count, a layer name or a map size. The blocking
cell the gate is tested at is FOUND by scanning the baked field, the anchor
is compared against `main.feet_anchor`'s own return, the depth against
`OBJECT_CONVERTER`, and the behavior token against the registry's spelling.
Repaint the map, move the hero, redraw the pond: every assertion here still
holds. Delete the hero, or the collision, and it does not -- which is the
point.

    .venv/Scripts/python.exe tools/check_demo_map.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import ast
import dataclasses
import json
import os
import tempfile
import warnings

import pygame

pygame.init()

# ---------------------------------------------------------------------------
# The fake keyboard, installed BEFORE anything boots.
#
# `InputActionManager.update()` calls `pygame.key.get_pressed()` once per
# frame and indexes the result by keycode, so replacing that function drives
# the real manager through its real edge derivation. Nothing here
# re-implements an edge; `tools/check_input.py` owns that claim and
# `tools/check_demos.py` is the precedent for this harness.
# ---------------------------------------------------------------------------

HELD: set[int] = set()


class _FakeKeys:
    def __getitem__(self, code: int) -> bool:
        return code in HELD


pygame.key.get_pressed = lambda: _FakeKeys()   # noqa: E731

from scripts.core.collision_runtime import (BLOCK_ALL, EDGE_INSET,  # noqa: E402
                                            PASS_ALL, STAR)
from config.managers.map_data import MapData                      # noqa: E402
from scripts.core.depth import OBJECT_CONVERTER                  # noqa: E402
from scripts.core.errors import (PyoneerAssetMissingError,       # noqa: E402
                                 PyoneerContentWarning)
from scripts.core.input import KEYBOARD                           # noqa: E402
from scripts.core.renderer import EntityLayer                     # noqa: E402
from scripts.core.spawn import SPAWN_REGISTRY, spawn              # noqa: E402
from scripts.game.behavior import BEHAVIORS                       # noqa: E402
from scripts.game.game_camera import GameCamera                  # noqa: E402
from scripts.game.game_map import GameMap                        # noqa: E402
from scripts.loaders.map_document import MapDocument              # noqa: E402
from scripts.loaders.map_loader import driven_record              # noqa: E402

import main as main_module                                        # noqa: E402
from main import MainGame, feet_anchor                            # noqa: E402

REPO = _bootstrap.REPO_ROOT

failures: list[str] = []
asserted = 0


def expect(label, got, want):
    global asserted
    asserted += 1
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception, call, *fragments):
    """The call must raise `exception`, and its message must name each fragment.

    The fragments are the teeth: asserting only the exception TYPE passes for
    any raise anywhere inside the call, including a typo three frames down.
    """
    global asserted
    asserted += 1
    try:
        call()
    except exception as exc:
        text = str(exc)
        missing = [f for f in fragments if f not in text]
        ok = not missing
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} "
              f"raised {type(exc).__name__}: {text.splitlines()[0][:44]}")
        if not ok:
            failures.append(f"{label} (message lacks {missing})")
        return
    except Exception as exc:                      # noqa: BLE001 - reporting
        print(f"  FAIL {label:<62} raised {type(exc).__name__} not "
              f"{exception.__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<62} did not raise")
    failures.append(label)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def key_for(game, verb: str) -> int:
    """The keycode a verb is bound to, read off the RUNNING manager.

    Not from a literal: the manager was built from `config/inputs.json` and
    holds the parsed bindings, so this presses whatever that file says. A
    verb rebound from `e` to `f` changes what this presses and changes
    nothing else, which is the property that makes the verb layer data.
    """
    action = game.input.actions[verb]
    for kind, name in action.inputs:
        if kind in ("keyboard", "key"):
            return KEYBOARD[name]
    raise KeyError("verb %r has no keyboard binding; this check cannot press "
                   "a gamepad" % verb)


def hold(game, *verbs: str) -> None:
    """Replace what is held. Empty releases everything."""
    HELD.clear()
    for verb in verbs:
        HELD.add(key_for(game, verb))


def entity_constructions(source: str, names: set[str]) -> list[str]:
    """Every CALL in `source` to one of `names`, by walking the parse tree.

    A call, never a mention: `self.player: GamePlayer | None` is an
    annotation and `from ... import GamePlayer` is an import, and neither
    builds anything. A grep could not tell those apart, which is why this
    reads the AST.

    Attribute calls count too (`entity.GamePlayer(...)`), because the name at
    the end is what decides which class gets built.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = (func.id if isinstance(func, ast.Name)
                  else func.attr if isinstance(func, ast.Attribute) else "")
        if called in names:
            found.append(called)
    return sorted(found)


def boot():
    """Construct and run one frame of the shipped game, warnings counted."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        game = MainGame(autostart=False)
        game.begin(max_frames=1)
        return game, [str(w.message) for w in caught
                      if "pkg_resources" not in str(w.message)]


def open_cell_beside_a_wall(field):
    """(open cell, wall cell) sharing an edge, found by SCANNING the field.

    Found rather than typed. Nothing here knows where the map's collision was
    painted, so repainting it cannot make this check red -- only removing all
    of it can, and that is a real regression in what the shipped map
    demonstrates.

    (None, None) for a map that declares no passability at all, so this
    reports as a failed assertion above rather than as an AttributeError
    here -- which is what a reader gets when the companion link is broken.
    """
    if field is None:
        return None, None
    for y in range(field.height):
        for x in range(1, field.width):
            if field.mask_at(x, y) != BLOCK_ALL:
                continue
            if field.mask_at(x - 1, y) != PASS_ALL:
                continue
            if field.mask_at(x - 2, y) != PASS_ALL:
                continue      # so "away from the wall" is open too
            return (x - 1, y), (x, y)
    return None, None


print("=" * 70)
print("check_demo_map -- the shipped map IS the shipped game")
print("=" * 70)

# ---------------------------------------------------------------------------
print()
print("1. the map main.py boots is the one config/maps.json names")
# ---------------------------------------------------------------------------
with open(os.path.join(REPO, "config", "maps.json"), encoding="utf-8") as handle:
    declared = {entry["name"]: entry for entry in json.load(handle)["data"]}

expect("main.py names a map the config declares",
       main_module.MAP_NAME in declared, True)
MAP_PATH = os.path.join(REPO, *declared[main_module.MAP_NAME]["file"].split("/"))
expect("...and the file it points at is on disk", os.path.isfile(MAP_PATH), True)

# THE BYTE-EXACTNESS CONTRACT, on the new file from its first commit. It is
# why `MapDocument` exists: a programmatic edit must be a MINIMAL DIFF, or a
# human editing this map in Tiled and a command editing it stop being able to
# collaborate. Law 11 named this as the reason `data/maps/test.tmx` was not to
# be touched; the file changed, the contract did not.
with open(MAP_PATH, "rb") as handle:
    ORIGINAL = handle.read()

document = MapDocument.from_bytes(ORIGINAL, MAP_PATH)
expect("load -> save is byte identical", document.to_bytes() == ORIGINAL, True)

# The other half: a comparison that cannot fail is not a comparison. One tile
# moved must move the bytes -- and moving it back must restore them exactly.
first_layer = document.tile_layer(document.tile_layer_names()[0])
was = first_layer.get_tile(0, 0)
other = next(gid for gid in sorted(set(first_layer.gids())) if gid != was)
first_layer.set_tile(0, 0, other)
expect("...and one changed csv token changes them",
       document.to_bytes() == ORIGINAL, False)
first_layer.set_tile(0, 0, was)
expect("...and putting it back restores them exactly",
       document.to_bytes() == ORIGINAL, True)

# ---------------------------------------------------------------------------
print()
print("2. main.py builds no entity -- the object layer does")
# ---------------------------------------------------------------------------
# BY AST, so the bypass cannot come back quietly. `SPAWN_REGISTRY` supplies
# the spawnable names rather than a literal list, and the three abstract
# bases are added because a construction of one of those would be a bypass
# too (it would raise, but it would be a bypass in the source).
ENTITY_NAMES = set(SPAWN_REGISTRY) | {"GameEntity", "GameEntitySimple",
                                      "GameAnimatedEntity"}
with open(os.path.join(REPO, "main.py"), encoding="utf-8") as handle:
    MAIN_SOURCE = handle.read()

expect("main.py calls no entity constructor anywhere",
       entity_constructions(MAIN_SOURCE, ENTITY_NAMES), [])
# The teeth. Without this the assertion above passes for a detector that
# looks at nothing, which is exactly what a bad refactor of `ast.Call`
# handling would leave behind.
DECOY = ("class G:\n"
         "    def go(self, cfg):\n"
         "        body = GamePlayer(input_=None, movement_config=cfg)\n"
         "        other: GamePlayer | None = None\n"
         "        return body, other\n")
expect("...and the detector finds one in a source that has one",
       entity_constructions(DECOY, ENTITY_NAMES), ["GamePlayer"])
expect("...and is not fooled by an annotation, which builds nothing",
       entity_constructions("x: GamePlayer | None = None\n", ENTITY_NAMES), [])

# ---------------------------------------------------------------------------
print()
print("3. booting the shipped game")
# ---------------------------------------------------------------------------
game, boot_warnings = boot()
expect("it boots and runs a frame without warning about its own map",
       boot_warnings, [])

records = list(game.renderer.spawned_entities)
expect("the object layer spawned at least one body", len(records) >= 1, True)

driven = [record for record in records
          if any(request.spec.name == main_module.PLAYER_TOKEN
                 for request in record.behaviors)]
expect("exactly one of them carries the driving token", len(driven), 1)
expect("...and it is the one the camera follows",
       game.scene.camera.target is driven[0].entity, True)
expect("...and it is main.py's `player`", game.player is driven[0].entity, True)

# The depth is DERIVED from the table that decides it, not typed as 50.
want_depth = OBJECT_CONVERTER[driven[0].type_name]
expect("it landed at the depth its type resolves to",
       driven[0].depth, want_depth)
bound = [entity
         for layer in game.renderer.layers.get(want_depth, [])
         if isinstance(layer, EntityLayer)
         for entity in layer.entities]
expect("...and it is BOUND into an EntityLayer there, not merely built",
       driven[0].entity in bound, True)

# THE OTHER HALF OF ROW ONE, and it was missing: this file's preamble has
# promised since it was written that a name `config/maps.json` does not carry
# RAISES, listing what it does, and nothing asserted it. "The shipped name
# loads" passes just as well for a manager that loads anything you ask it
# for, which is law 5's dominant shape -- a gate proved to let something
# through and never proved to stop it. The fragments are derived, never
# typed: the available list must name whatever `main.MAP_NAME` currently is.
expect_raises("...and a name config/maps.json does not carry RAISES, listing "
              "what it does",
              PyoneerAssetMissingError,
              lambda: game.assets.maps.load_assets("no_such_map_at_all"),
              "no_such_map_at_all", main_module.MAP_NAME, "config/maps.json")

# ---------------------------------------------------------------------------
print()
print("4. the spawn route carries the feet anchor to the map's body")
# ---------------------------------------------------------------------------
arguments = game.spawn_arguments()[driven[0].type_name]
anchor = feet_anchor(game.assets.animations.get("entity"))
expect("spawn_arguments derives the anchor rather than typing one",
       arguments["collision_offset"], anchor)
expect("the MAP-SPAWNED body carries it",
       tuple(driven[0].entity.collision_offset), tuple(anchor))
expect("...so its collision point is a sprite-height below its top-left",
       driven[0].entity.collision_point()[1]
       - driven[0].entity.transform.position.y, anchor[1])

# The half that says what the route is WORTH: the class default is the top-
# left pixel -- the top of a character's HEAD -- so a body that never went
# through `spawn_defaults` is gated at the wrong pixel and looks fine.
bare_arguments = {key: value for key, value in arguments.items()
                  if key != "collision_offset"}
bare = spawn(driven[0].type_name, SPAWN_REGISTRY, **bare_arguments)
expect("...and one built WITHOUT it is anchored at its head",
       tuple(bare.collision_offset), (0.0, 0.0))
expect("...which is a different pixel, which is the whole point",
       tuple(bare.collision_offset) != tuple(anchor), True)

# ---------------------------------------------------------------------------
print()
print("5. the map's passability is baked, and it refuses a step")
# ---------------------------------------------------------------------------
field = driven[0].entity.collision_field
expect("the engine handed the spawned body the map's field",
       field is not None, True)
counts = field.counts() if field is not None else {}
blocking = sum(n for mask, n in counts.items() if mask and mask != STAR)
expect("...and the map declares real collision, not an empty one",
       blocking > 0, True)

open_cell, wall_cell = open_cell_beside_a_wall(field)
expect("a wall with open ground west of it was found by scanning",
       open_cell is not None, True)

if open_cell is not None:
    body = driven[0].entity
    # Stand the body's ANCHOR at the centre of the open cell, by moving the
    # sprite so that `collision_point()` lands there. Derived from the body's
    # own offset, so a re-cut spritesheet moves this with it.
    point_x = open_cell[0] * field.tile_width + field.tile_width / 2.0
    point_y = open_cell[1] * field.tile_height + field.tile_height / 2.0
    body.moveto((point_x - body.collision_offset[0],
                 point_y - body.collision_offset[1]))
    expect("the anchor really is in the open cell",
           field.cell_of(*body.collision_point()), open_cell)

    wanted = pygame.Vector2(float(field.tile_width), 0.0)
    into_wall = body.allowed_move(wanted, "right")
    room = wall_cell[0] * field.tile_width - point_x - EDGE_INSET
    expect("stepping INTO the wall is clamped to the edge of it",
           into_wall.x, room)
    expect("...which is less than it asked for", into_wall.x < wanted.x, True)

    # DIRECTIONAL, not a freeze: the same pixel, the same distance, away from
    # the wall. `allowed_move` returns the ARGUMENT ITSELF when nothing
    # clamps, so identity is the strongest form this half can take.
    away = body.allowed_move(wanted, "left")
    expect("...while stepping AWAY from it is the argument itself, unclamped",
           away is wanted, True)

    # And the clamp provably came from the MAP: clear the field and the same
    # move through the same wall is unclamped.
    body.collision_field = None
    expect("...and with no field at all the wall stops nothing",
           body.allowed_move(wanted, "right") is wanted, True)
    body.collision_field = field

# ---------------------------------------------------------------------------
print()
print("6. the authored action chain reaches the host, and it makes a noise")
# ---------------------------------------------------------------------------
# The map says `interact_action,action_relay`; `action_relay` CALLS
# `entity.action_sink(entity, fired)`; `SceneManager` assigned its own
# `ActionRouter` as that sink; `main.py` routes the token to the handler that
# starts the fired body's event script. This asserts the whole wire, at the
# seam a human can see: a key press.
expect("main.py registered exactly one handler for the token",
       [entry for entry in game.scene.actions.routes
        if entry[0] == "interact_action"], [("interact_action", "", 1)])

# WHERE it is registered, by AST, because the runtime row above passes either
# way and the difference is invisible until somebody subclasses this game.
# `run_object_script`'s docstring states the rule -- the route goes in the
# hook a subclass OVERRIDES, never in the method a subclass INHERITS BY
# IDENTITY -- and that sentence was wrong once already. Registered in the
# inherited method, the shipped game's wiring is silently installed in every
# game built on `MainGame`, including one whose map names no script at all.
# Nothing in this tree asserted the placement; this is that assertion, and it
# is both halves of it.


def route_calls_in(method_name: str) -> int:
    """How many `....route(...)` calls sit inside `MainGame.<method_name>`."""
    owner = next(node for node in ast.walk(ast.parse(MAIN_SOURCE))
                 if isinstance(node, ast.ClassDef) and node.name == "MainGame")
    method = next((node for node in owner.body
                   if isinstance(node, ast.FunctionDef)
                   and node.name == method_name), None)
    if method is None:
        return -1                 # a missing method is not "zero routes"
    return sum(1 for node in ast.walk(method)
               if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute)
               and node.func.attr == "route")


expect("...in the hook a subclass OVERRIDES, so a subclass does not inherit "
       "the shipped game's wiring",
       route_calls_in("load_test_objects"), 1)
expect("...and NOT in the method a subclass inherits by identity",
       route_calls_in("prepare_test_scene"), 0)

# A SECOND handler rather than replacing the first, because `route` appends:
# the real one still runs, and this one counts. Counting rather than reading
# the Sound cache on purpose -- `AudioManager` is truthfully unavailable on a
# runner with no sound card, and a row that read differently there would make
# this check machine-dependent.
fired: list = []
game.scene.actions.route("interact_action",
                         lambda entity, event: fired.append(event))

# Read BEFORE the press, so the rows at the end of this section compare a
# before against an after rather than asserting that a slot is full -- which
# would also pass for a boot that filled it, and a script starting at boot is
# a different defect wearing the same green tick.
before_flow = game.scene.flow
before_run = game.script_run

hold(game, "action")            # a rising edge, because HELD was empty
game.tick()
expect("pressing the action verb reaches the scene's router", len(fired), 1)
expect("...carrying the behavior token as its name",
       fired[0].name if fired else None, "interact_action")

game.tick()
expect("...and holding it does not fire again -- it is a rising edge",
       len(fired), 1)
hold(game)
game.tick()
expect("...and releasing it does not fire either", len(fired), 1)

# THE FAR END OF THE SAME WIRE, and it moved. This used to read the sound a
# module constant in `main.py` named, because the demo's noise came from a
# hard-wired handler; the noise comes through the script vocabulary now and
# that constant is gone. The AUDIO claims -- that `play_sound` reached the
# subsystem with the authored name, that the name resolves to a file, and
# that one neither root holds raises -- belong to the check that owns the
# script wire, which asserts all three over its own fixture.
#
# What is left here is the half NO fixture can cover, and it is this file's
# whole reason to exist: that the SHIPPED game is on that wire. Contract, not
# content -- no script id, no sound name, no line of dialogue is named below,
# so renaming the shipped script or rewriting what it says cannot make this
# red, and unwiring the press can.
expect("nothing is parked in the flow slot before a key is touched",
       (before_flow, before_run), (None, None))
expect("...and the press the rows above measured left a run in it",
       game.scene.flow is game.script_run and game.script_run is not None,
       True)
expect("...which is really running, not merely assigned",
       game.script_run.running if game.script_run else None, True)
expect("...and the shipped hero is a body that names a script",
       game.script_for(driven[0].entity) is not None, True)


class _Impostor:
    """Equal to everything, identical to nothing. The teeth on `script_for`.

    `script_for` documents that it searches by IDENTITY and never by `==`,
    because a reaped body's address is reusable and an entity that defined
    equality would answer for a DIFFERENT body's row. An `==` implementation
    would hand this the hero's script id; identity hands it None.
    """

    def __eq__(self, other):                      # noqa: D105
        return True

    def __hash__(self):                           # noqa: D105
        return 0


expect("...and a stand-in that claims equality with it gets no script, "
       "because the search is by identity",
       game.script_for(_Impostor()), None)

# ---------------------------------------------------------------------------
print()
print("7. a map whose adopted player cannot be driven says so, once")
# ---------------------------------------------------------------------------
# ON A FIXTURE, and law 4 is the whole reason: the claim is about what
# `MainGame` DOES when a map's adopted body carries no `player_input`, and
# `data/maps/starter.tmx` is a working map whose hero carries it. Editing the
# shipped map to make it fail would pin content and break law 11 besides, so
# this writes two maps of its own that differ in ONE property value.
#
# The subclass overrides `load_map` and nothing else -- the same hook
# `demos/runtime.py` overrides, and for the same reason. `prepare_test_scene`,
# `load_test_objects`, the adoption and the diagnostic are all the shipped
# ones, inherited by identity, so this measures main.py rather than a copy of
# it.

WORKSPACE = tempfile.mkdtemp(prefix="pyoneer_demo_map_")

DRIVEN_LIST = "%s,topdown_move,animation_drive" % main_module.PLAYER_TOKEN
UNDRIVEN_LIST = "topdown_move,animation_drive"
FIXTURE_LAYER = "entity"

FIXTURE_ROW = ",".join(["1"] * 8)
FIXTURE_HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="8" height="8" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="9" nextobjectid="9">
 <tileset firstgid="1" name="probe" tilewidth="16" tileheight="16" tilecount="4" columns="2">
  <image source="probe.png" width="32" height="32"/>
 </tileset>
 <layer id="1" name="Floor" width="8" height="8">
  <data encoding="csv">
%s
</data>
 </layer>
""" % (",\n".join([FIXTURE_ROW] * 8),)


def fixture_object(object_id: int, x: int, tokens: str) -> str:
    """One `<object type="GamePlayer">` declaring exactly one property."""
    return ('  <object id="%d" name="body%d" type="GamePlayer" x="%d" y="32" '
            'width="16" height="16">\n'
            '   <properties>\n'
            '    <property name="%s" value="%s"/>\n'
            '   </properties>\n'
            '  </object>\n' % (object_id, object_id, x, BEHAVIORS, tokens))


def write_fixture(key: str, first: str, second: str) -> str:
    """A two-body map. Body 1 is spawned first, so body 1 is the adopted one."""
    text = (FIXTURE_HEAD
            + ' <objectgroup id="4" name="%s">\n' % FIXTURE_LAYER
            + fixture_object(1, 16, first)
            + fixture_object(2, 80, second)
            + ' </objectgroup>\n</map>\n')
    path = os.path.join(WORKSPACE, key + ".tmx")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


# A real 2x2 sheet beside them, because pytmx loads the tileset image for
# real and a missing one raises before any of this is reached.
_sheet = pygame.Surface((32, 32))
for _index, _colour in enumerate(((180, 40, 40), (40, 180, 40),
                                  (40, 40, 180), (180, 180, 40))):
    _sheet.fill(_colour, pygame.Rect((_index % 2) * 16, (_index // 2) * 16,
                                     16, 16))
pygame.image.save(_sheet, os.path.join(WORKSPACE, "probe.png"))


class FixtureGame(MainGame):
    """The shipped game, booted on a map this check wrote.

    `MAP_KEY` and `MAP_FILE` are set per subclass so the asset manager's
    parse cache cannot hand one fixture's parsed map to the other.
    """

    MAP_KEY: str = ""
    MAP_FILE: str = ""

    def load_map(self):
        self.assets.maps.maps[self.MAP_KEY] = MapData({
            "name": self.MAP_KEY,
            "identifier": self.MAP_KEY,
            "file": self.MAP_FILE,
        })
        map_data = self.assets.maps.load_assets(self.MAP_KEY)
        camera = GameCamera(
            pygame.Vector2(self.screen.get_width(), self.screen.get_height()),
            pygame.Rect(0, 0,
                        map_data.tilewidth * map_data.width,
                        map_data.tileheight * map_data.height),
            scale=1)
        return camera, GameMap(map_data)


def boot_fixture(key: str, first: str, second: str):
    """Boot one fixture map. Returns the game and its CONTENT warnings."""
    path = write_fixture(key, first, second)
    cls = type("FixtureGame_" + key, (FixtureGame,),
               {"MAP_KEY": key, "MAP_FILE": path})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        booted = cls(autostart=False)
        booted.begin(max_frames=1)
    return booted, [str(entry.message) for entry in caught
                    if issubclass(entry.category, PyoneerContentWarning)]


def walked(booted, frames: int = 30) -> bool:
    """Hold `right` for `frames` and say whether the adopted body moved."""
    start = tuple(booted.player.transform.position)
    hold(booted, "right")
    for _ in range(frames):
        booted.tick()
    hold(booted)
    return tuple(booted.player.transform.position) != start


# --- half one: the adopted body has no `player_input` -----------------------
undriven, undriven_warnings = boot_fixture("undriven", UNDRIVEN_LIST,
                                           UNDRIVEN_LIST)
expect("a map whose adopted body lacks the token warns exactly ONCE",
       len(undriven_warnings), 1)
said = undriven_warnings[0] if undriven_warnings else ""
expect("...naming the <object> that was adopted",
       "<object id=1>" in said, True)
expect("...and the object layer it sits on", FIXTURE_LAYER in said, True)
expect("...and the token that is missing",
       main_module.PLAYER_TOKEN in said, True)
expect("...and the property an author has to add it to",
       BEHAVIORS in said, True)
# NARROWNESS, measured on the map that has TWO undriven bodies: a diagnostic
# that walked every record would name the second one too, and the count above
# would already be 2. Both halves of the same mistake, because a rewrite could
# produce one single warning that names everything.
expect("...and it does NOT name the body the game did not adopt",
       "id=2" in said, False)

# --- the warning is a WARNING, not a raise ---------------------------------
undriven_records = list(undriven.renderer.spawned_entities)
expect("the map still loaded and still spawned both bodies",
       len(undriven_records), 2)
expect("...the game still adopted one of them and ran its frame",
       (undriven.player is not None, undriven.frame), (True, 1))
expect("...and the camera still follows it",
       undriven.scene.camera.target is undriven.player, True)
expect("...the adopted one being the object the warning named",
       undriven.player is undriven_records[0].entity, True)
# WHAT THE WARNING IS ABOUT, measured rather than asserted: this is the
# silence the diagnostic exists to break.
expect("...and that body really cannot be driven: held frames move it nowhere",
       walked(undriven), False)

# --- half two: the adopted body HAS the token ------------------------------
# The fixture still carries a SECOND body without it -- a decoy, a patrol, a
# signpost -- so a diagnostic that warned about every undriven entity fails
# here rather than passing quietly.
driven_game, driven_warnings = boot_fixture("driven", DRIVEN_LIST,
                                            UNDRIVEN_LIST)
expect("a map whose adopted body HAS the token warns not at all",
       driven_warnings, [])
expect("...on a map that still carries an undriven second body",
       [record.object_id for record in driven_game.renderer.spawned_entities
        if not any(request.spec.name == main_module.PLAYER_TOKEN
                   for request in record.behaviors)], [2])
expect("...and the adopted body is the one carrying the token",
       driven_game.player is driven_game.renderer.spawned_entities[0].entity,
       True)
expect("...and THIS one does move when the same verb is held for the same "
       "number of frames", walked(driven_game), True)

# ---------------------------------------------------------------------------
print()
print("8. the driven-record pick is ONE function, called by both boot paths")
# ---------------------------------------------------------------------------
# WHY THIS IS ASSERTED BY AST AND NOT BY IMPORTING IT. Importing proves the
# name resolves; it cannot prove a SECOND implementation is not sitting in
# another file doing the same job under the same rule. That is exactly what
# was here: `main.py` picked the driven body with a three-line `next(...)`
# and the demo boot path picked its camera target with its own copy of the
# same loop. Law 2's corollary is that shape at package scale, and it was
# paid once at 425 DUPLICATE LINES, so the assertion that matters is a count
# over the whole tree rather than a successful import.
#
# The direction is forced and is asserted too: the one definition must be in
# `scripts/`. The demo package imports `main`, `main` may not spell the demo
# package's name at all (`tools/check_demos.py` owns that row, because this
# module is the smoke baseline), so the engine is the ONLY package both
# callers may name. A shared helper that landed in either of the other two
# would be a copy waiting to happen.

HELPER = "driven_record"
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".idea", ".vs"}


def python_sources() -> list[str]:
    """Every .py file in the working tree, repo-relative, sorted."""
    found: list[str] = []
    for root, dirs, names in os.walk(REPO):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if name.endswith(".py"):
                found.append(os.path.relpath(os.path.join(root, name), REPO)
                             .replace("\\", "/"))
    return found


def function_defs(source: str, name: str) -> int:
    """How many `def name(...)` this source DEFINES.

    A definition, never a mention: an `import name`, an `__all__` entry and a
    call are all the name appearing without anything being defined, and a
    grep could not tell those apart -- which is the whole reason the re-export
    this change leaves behind is safe.
    """
    return sum(1 for node in ast.walk(ast.parse(source))
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name == name)


defining: list[str] = []
for relative in python_sources():
    with open(os.path.join(REPO, relative), encoding="utf-8") as handle:
        try:
            count = function_defs(handle.read(), HELPER)
        except SyntaxError:
            # A file this interpreter cannot parse defines nothing as far as
            # this walk is concerned, and whichever check owns that file owns
            # the syntax error. Swallowing it here would be wrong only if it
            # could hide a copy, and a copy that does not parse is not one.
            continue
        if count:
            defining.extend([relative] * count)

# The teeth on the WALK, before the count that rests on it. "Exactly one
# definition" would also be satisfied by a walk that never reached the two
# files a copy would most likely be in, which is the failure mode of every
# tree scan: it passes loudest when it is looking at nothing.
SEEN = set(python_sources())
expect("the walk reaches both boot paths, so a copy in either is in scope",
       {"main.py", "demos/runtime.py"} <= SEEN, True)
expect("...and it skips nothing it should not: it sees the engine half too",
       "scripts/loaders/map_loader.py" in SEEN, True)

expect("exactly one file in the tree DEFINES it", len(defining), 1)
expect("...and it is in the engine half, which is the only package both "
       "callers may name",
       defining[0].startswith("scripts/") if defining else None, True)

# The teeth on the counter. Without these, "exactly one" passes for a walker
# that finds nothing at all, and "one" would be indistinguishable from a
# tree where the function had been deleted outright.
TWO_DEFS = """
def driven_record(records):
    return None


class Keeper:
    def driven_record(self, records):
        return records
"""
NO_DEFS = """
from somewhere import driven_record

__all__ = ["driven_record"]
result = driven_record([])
"""
expect("...and the counter finds BOTH of a source that defines it twice",
       function_defs(TWO_DEFS, HELPER), 2)
expect("...and counts an import, an __all__ entry and a CALL as zero "
       "definitions, which is what makes a re-export safe",
       function_defs(NO_DEFS, HELPER), 0)

# BOTH CALLERS CALL IT, read off their parse trees by the same detector
# section 2 already falsified above -- it counts a Call and ignores an
# annotation, which is what stops `driven: Record | None` reading as use.
with open(os.path.join(REPO, "demos", "runtime.py"), encoding="utf-8") as handle:
    DEMO_SOURCE = handle.read()

expect("main.py calls it rather than carrying its own copy of the loop",
       entity_constructions(MAIN_SOURCE, {HELPER}), [HELPER])
expect("...and so does the demo boot path",
       entity_constructions(DEMO_SOURCE, {HELPER}), [HELPER])
expect("...and neither of them still defines one",
       (function_defs(MAIN_SOURCE, HELPER),
        function_defs(DEMO_SOURCE, HELPER)), (0, 0))

# AND IT IS THE SAME OBJECT AT RUN TIME, not merely the same name in three
# files. The AST rows above cannot see a module that re-binds the name to
# something else after importing it; this row cannot see a duplicate
# definition. Together they close both.
import demos.runtime as demo_runtime                              # noqa: E402
from scripts.loaders import map_loader                            # noqa: E402

expect("the demo package re-exports the engine's function, not a lookalike",
       demo_runtime.driven_record is map_loader.driven_record, True)
expect("...and main.py holds that same object too",
       main_module.driven_record is map_loader.driven_record, True)
expect("...and the token it reads is the engine's one spelling",
       main_module.PLAYER_TOKEN is map_loader.PLAYER_TOKEN, True)

# WHAT IT ANSWERS, on the shipped boot, in both directions. The positive is
# that the function and `main.py`'s adoption agree -- a shared helper that
# picked a DIFFERENT record than the game adopts would pass every row above.
expect("it picks the body the shipped game adopted as the player",
       driven_record(game.renderer.spawned_entities).entity is game.player,
       True)
expect("...and returns None once the driving token is taken away, so the "
       "token is really what it reads",
       driven_record([dataclasses.replace(record, behaviors=())
                      for record in game.renderer.spawned_entities]), None)
expect("...and returns None for nothing at all", driven_record([]), None)

# ---------------------------------------------------------------------------
print()
print("=" * 70)
if failures:
    print(f"FAILED ({len(failures)} of {asserted}):")
    for label in failures:
        print("  -", label)
    raise SystemExit(1)
print(f"PASS -- {asserted} assertions; the shipped map is the shipped game")
