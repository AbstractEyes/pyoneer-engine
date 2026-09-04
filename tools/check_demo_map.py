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
import json
import os
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
from scripts.core.depth import OBJECT_CONVERTER                  # noqa: E402
from scripts.core.errors import PyoneerAssetMissingError          # noqa: E402
from scripts.core.input import KEYBOARD                           # noqa: E402
from scripts.core.renderer import EntityLayer                     # noqa: E402
from scripts.core.spawn import SPAWN_REGISTRY, spawn              # noqa: E402
from scripts.loaders.map_document import MapDocument              # noqa: E402

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
# `ActionRouter` as that sink; `main.py` routed the token to
# `play_interaction_sound`. This asserts the whole wire, at the seam a human
# can see: a key press.
expect("main.py registered exactly one handler for the token",
       [entry for entry in game.scene.actions.routes
        if entry[0] == "interact_action"], [("interact_action", "", 1)])

# A SECOND handler rather than replacing the first, because `route` appends:
# the real one still runs, and this one counts. Counting rather than reading
# the Sound cache on purpose -- `AudioManager` is truthfully unavailable on a
# runner with no sound card, and a row that read differently there would make
# this check machine-dependent.
fired: list = []
game.scene.actions.route("interact_action",
                         lambda entity, event: fired.append(event))

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

# The sound end of the same wire. `locate` RAISES for a name neither audio
# root holds, whether or not there is a card, so this row means the file was
# really found -- on a silent machine too.
expect("the sound main.py plays is a file one of the audio roots holds",
       os.path.isfile(game.audio.locate(main_module.INTERACT_SOUND)), True)
expect_raises("...and a name neither root holds RAISES rather than going quiet",
              PyoneerAssetMissingError,
              lambda: game.audio.locate("sfx/no_such_sound.wav"),
              "sfx/no_such_sound.wav")

# ---------------------------------------------------------------------------
print()
print("=" * 70)
if failures:
    print(f"FAILED ({len(failures)} of {asserted}):")
    for label in failures:
        print("  -", label)
    raise SystemExit(1)
print(f"PASS -- {asserted} assertions; the shipped map is the shipped game")
