"""Boot every demo headless, drive it with injected input, and assert what it
proves.

WHY THIS EXISTS
---------------
A demo nobody runs rots the way anything unwired in this tree rots: it looks
fine right up until somebody runs it.

So each demo is booted for real -- `MainGame.__init__` -> `prepare` ->
`build` -> `begin` -> `tick` -- and then driven. `tools/smoke.py` is the
precedent for the harness and the reason this one has to exist alongside it:
SMOKE INJECTS NO INPUT, so it cannot see anything that only happens while
walking. This check presses keys.

WHAT IS ASSERTED, AND THE PAIRS THAT GIVE IT TEETH
---------------------------------------------------
Every gate below is asserted in BOTH directions, because one half of an
invariant is the commonest toothless shape in this tree -- a gate proved to
let something through and never proved to stop it:

    injected input      moves the entity carrying `player_input`
                    AND leaves every entity that does not, exactly where it
                        spawned -- same class, same depth, same manager
    no input            leaves the driven entity exactly where it was
                    AND still lets the patroller walk
    the collision gate  lands a side-on body on the authored mask, at the
                        exact derived pixel
                    AND with `collision_field` cleared, the SAME map and the
                        SAME behaviors fall past it forever
    the conflict rule   composes a legal behavior list
                    AND refuses `player_input` + `patrol_input`, naming both
    a bad route         raises at attach naming the step
                    AND a good one attaches
    write-once maps     `ensure_map` writes an absent map
                    AND does not touch a present one
    no second impl      `DemoGame` INHERITS main.py's spine by identity
                    AND overrides exactly the two hooks it claims to
    the script wire     a demo boot reaches main.py's OWN join, say host and
                        action route -- by identity, not by resemblance --
                        and a scripted demo body really runs its document
                    AND a demo map naming an absent script RAISES at boot
                        rather than building a body that looks scripted

THE MAPS THIS CHECK READS ARE ITS OWN
--------------------------------------
`demos/maps/*.tmx` is the AUTHOR's canvas, exactly as `data/maps/starter.tmx`
is, and a check that pinned their content would go red the first time
somebody repainted one. So `demos.mapgen.MAPS_DIR` is redirected to a temp
directory and the maps are generated fresh into it. Every number this file
expects is DERIVED from `demos.mapgen`'s named geometry and the engine's own
constants -- `SIDESTEP_GROUND_TOP * TILE - COLLISION_OFFSET[1] - EDGE_INSET`
-- and never typed as a literal, so the claim is about the physics and the
gate rather than about a number written down twice.

    .venv/Scripts/python.exe tools/check_demos.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import hashlib
import inspect
import json
import os
import shutil
import sys
import tempfile
import warnings

import pygame

pygame.init()

# ---------------------------------------------------------------------------
# The fake keyboard, installed BEFORE anything boots.
#
# InputActionManager.update() calls pygame.key.get_pressed() once per frame
# and indexes the result by keycode, so replacing that function drives the
# real manager through its real edge derivation -- `pressed`, `held` and
# `released` are all computed by the engine's own code against last frame's
# state. Nothing here re-implements an edge; check_input.py owns that claim.
# ---------------------------------------------------------------------------

HELD: set[int] = set()


class _FakeKeys:
    def __getitem__(self, code: int) -> bool:
        return code in HELD


pygame.key.get_pressed = lambda: _FakeKeys()   # noqa: E731

from scripts.core import blitpool                                # noqa: E402
from scripts.core.collision_runtime import EDGE_INSET            # noqa: E402
from scripts.core.errors import (PyoneerAssetMissingError,       # noqa: E402
                                 PyoneerConfigError)
from scripts.core.event_manager import PyoneerEvent              # noqa: E402
from scripts.core.event_types import GameEventType               # noqa: E402
from scripts.core.input import KEYBOARD                          # noqa: E402
from scripts.game.behavior import BEHAVIOR_REGISTRY              # noqa: E402
from scripts.game.entity.game_player import GamePlayer           # noqa: E402
from scripts.loaders import script_file                          # noqa: E402

from main import MainGame                                        # noqa: E402

import demos.behaviors                                           # noqa: E402,F401
from demos import mapgen                                         # noqa: E402
from demos.behaviors import GamePatrolInputBehavior              # noqa: E402
from demos.patrol import PatrolDemo                              # noqa: E402
from demos.runtime import DemoGame, driven_record                # noqa: E402
from demos.sidestep import SidestepDemo                          # noqa: E402
from demos.topdown import TopDownDemo                            # noqa: E402

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
              f"raised {type(exc).__name__}: {text.splitlines()[0][:48]}")
        if not ok:
            failures.append(f"{label} (message lacks {missing})")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
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

    Not from a literal and not from a second read of config/inputs.json: the
    manager was built from that file and holds the parsed bindings, so this
    presses whatever the config actually says. A verb rebound from `space` to
    `e` changes what this presses and changes nothing else -- which is the
    property that makes the verb layer data, and pinning `K_SPACE` here would
    quietly destroy it.
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


def advance(game, frames: int) -> None:
    for _ in range(frames):
        game.tick()


def boot(demo_class):
    """Construct and run one frame of a demo, warnings suppressed but counted.

    The 'FloorCollision has no depth mapping' warning is expected on every
    map that declares collision -- see demos/mapgen.py -- so it is captured
    rather than printed, and section 1 asserts it says what it should.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        game = demo_class(autostart=False)
        game.begin(max_frames=1)
        return game, [str(w.message) for w in caught]


def frame_blits(game) -> list[tuple[int, str]]:
    """(depth, sender class name) for every token ONE frame queues."""
    captured: list[tuple[int, str]] = []
    original = blitpool.BlitPool.get_blit_pool_pygame

    @staticmethod
    def spy(clear: bool = True):
        for depth in sorted(blitpool.ORGANIZED_BLITS):
            for priority in sorted(blitpool.ORGANIZED_BLITS[depth]):
                for token in blitpool.ORGANIZED_BLITS[depth][priority]:
                    captured.append((depth, type(token.sender).__name__))
        return original(clear)

    blitpool.BlitPool.get_blit_pool_pygame = spy
    try:
        game.tick()
    finally:
        blitpool.BlitPool.get_blit_pool_pygame = original
    return captured


def distinct_colours(stride: int = 8) -> int:
    """How many distinct colours a dense scan finds on the display surface.

    The cheap half of "it rendered": one colour means the frame is a flat
    fill, which is what a boot that drew nothing produces and what a
    frame-hash assertion cannot tell from a correct frame without a baseline
    this check deliberately does not own.

    DENSE, because a coarse sample of a tiled map measures the tile size
    rather than the render: a 12x12 grid lands entirely inside one tile
    colour, misses the 32px stripe and every 44x64 sprite, and reports one
    colour for a fully rendered map. 8px costs 11ms over 1024x768.
    """
    surface = pygame.display.get_surface()
    width, height = surface.get_size()
    seen = set()
    for y in range(0, height, stride):
        for x in range(0, width, stride):
            seen.add(tuple(surface.get_at((x, y))))
    return len(seen)


def frame_fingerprint() -> str:
    """A hash of what is actually on the display surface right now."""
    return hashlib.sha256(pygame.image.tostring(
        pygame.display.get_surface(), "RGB")).hexdigest()[:16]


def positions(game) -> dict[int, tuple[float, float]]:
    return {record.object_id: tuple(record.entity.transform.position)
            for record in game.spawned}


def summary(game) -> dict:
    """Everything a cross-demo comparison needs, as plain data.

    Plain data because two demos cannot be alive at once in a useful way --
    they share one display surface and one module-global BlitPool -- so the
    comparison happens after both have been run and put down.
    """
    return {
        "classes": sorted({type(r.entity).__name__ for r in game.spawned}),
        "depths": sorted({r.depth for r in game.spawned}),
        "layers": sorted({r.layer_name for r in game.spawned}),
        "types": sorted({r.type_name for r in game.spawned}),
        "tokens": sorted({q.spec.name for r in game.spawned
                          for q in r.behaviors}),
        "map_file": game.assets.maps.maps[game.MAP_NAME].file,
    }


WORKSPACE = tempfile.mkdtemp(prefix="pyoneer_demos_")
SHIPPED_MAPS_DIR = mapgen.MAPS_DIR
SHIPPED_SOURCES = mapgen.SOURCES
SHIPPED_SCRIPTS_DIR_FN = script_file.default_scripts_dir
CONFIG_MAPS = os.path.join(_bootstrap.REPO_ROOT, "config", "maps.json")
with open(CONFIG_MAPS, "rb") as _handle:
    CONFIG_MAPS_BEFORE = _handle.read()

try:
    # Every map this check reads is generated into here, so the shipped
    # demos/maps/*.tmx are never read, written or pinned.
    mapgen.MAPS_DIR = WORKSPACE

    # =====================================================================
    print("1. every demo boots headless and draws a frame with tiles AND "
          "entities in it")
    # =====================================================================
    topdown, topdown_warnings = boot(TopDownDemo)
    blits = frame_blits(topdown)
    senders = {name for _depth, name in blits}
    expect("the map's tile layer drew", "MapLayer" in senders or
           "MapComposite" in senders, True)
    expect("...and so did the spawned entities", "GamePlayer" in senders, True)
    expect("every spawned entity queued exactly one token",
           len([1 for _d, name in blits if name == "GamePlayer"]),
           len(topdown.spawned))
    expect("the entities draw above the floor",
           min(d for d, name in blits if name == "GamePlayer")
           > max(d for d, name in blits
                 if name in ("MapLayer", "MapComposite")), True)

    # `DemoGame.spawn` sets self.player, and main.py's arrow-key handler
    # dereferences it unconditionally, so leaving it None crashes inside the
    # frame loop. Asserted rather than observed, because booting one frame
    # never presses a key.
    expect("boot leaves self.player pointing at a real entity",
           topdown.player is not None, True)
    expect("...and it is the object carrying player_input, not merely the "
           "first one spawned",
           "player_input" in topdown.player.behaviors.names, True)
    expect("...the same entity the camera was told to follow",
           topdown.scene.camera.target is topdown.player, True)
    expect("the frame is not a flat fill", distinct_colours() > 1, True)
    expect("a map with no companion layer warns about nothing",
           [w for w in topdown_warnings if "FloorCollision" in w], [])

    # =====================================================================
    print()
    print("2. injected input moves the driven entity, and ONLY the driven "
          "entity")
    # =====================================================================
    hero = topdown.entity_of(mapgen.TOPDOWN_HERO_ID)
    decoys = [topdown.entity_of(i) for i in mapgen.TOPDOWN_DECOY_IDS]
    expect("the map spawned one driven entity and five that are not",
           (hero is not None, sum(d is not None for d in decoys)), (True, 5))
    expect("...and the camera followed the driven one, from the composition "
           "alone", topdown.scene.camera.target is hero, True)
    expect("the driven one is the same class as the five that are not",
           {type(e).__name__ for e in decoys + [hero]}, {"GamePlayer"})
    expect("...and every one of them was handed the SAME live input manager",
           {e.action_manager is topdown.input for e in decoys + [hero]},
           {True})

    before = positions(topdown)
    hold(topdown)                       # nothing held
    advance(topdown, 20)
    expect("with nothing held, nothing moves at all",
           positions(topdown), before)
    idle_frame = frame_fingerprint()

    hold(topdown, "right")
    advance(topdown, 40)
    walked = positions(topdown)
    expect("...and the screen shows it: the frame is not the idle one",
           frame_fingerprint() != idle_frame, True)
    expect("holding `right` walks the driven entity right",
           walked[mapgen.TOPDOWN_HERO_ID][0] > before[mapgen.TOPDOWN_HERO_ID][0],
           True)
    expect("...along x only", walked[mapgen.TOPDOWN_HERO_ID][1],
           before[mapgen.TOPDOWN_HERO_ID][1])
    expect("...and it faces the way it walked", hero.state.move_direction,
           "right")
    # The other half, and the one that is the demo's actual claim. Same class,
    # same depth, same manager, one token fewer -- and the key does nothing.
    expect("...while every entity without `player_input` has not moved a pixel",
           {i: walked[i] for i in mapgen.TOPDOWN_DECOY_IDS},
           {i: before[i] for i in mapgen.TOPDOWN_DECOY_IDS})
    expect("...and none of them is even facing anywhere",
           {e.state.move_direction for e in decoys}, {"none"})

    hold(topdown, "up")
    advance(topdown, 40)
    climbed = positions(topdown)
    expect("a different verb walks a different way",
           (climbed[mapgen.TOPDOWN_HERO_ID][1]
            < walked[mapgen.TOPDOWN_HERO_ID][1],
            climbed[mapgen.TOPDOWN_HERO_ID][0]
            == walked[mapgen.TOPDOWN_HERO_ID][0]), (True, True))

    hold(topdown)
    advance(topdown, 10)
    expect("releasing stops it on the same pixel it stopped on",
           positions(topdown)[mapgen.TOPDOWN_HERO_ID],
           climbed[mapgen.TOPDOWN_HERO_ID])
    expect("...and returns it to idle", hero.state.moving, False)
    topdown_summary = summary(topdown)

    # =====================================================================
    print()
    print("3. the side-on demo: the same class falls, lands on the authored "
          "mask, and jumps")
    # =====================================================================
    hold(topdown)
    sidestep, sidestep_warnings = boot(SidestepDemo)
    expect("the mask layer is not drawn, and the engine says so once",
           len([w for w in sidestep_warnings
                if "FloorCollision" in w and "will NOT be drawn" in w]), 1)

    body = sidestep.entity_of(mapgen.SIDESTEP_HERO_ID)
    faller = sidestep.entity_of(mapgen.SIDESTEP_FALLER_ID)
    expect("both bodies spawned", (body is not None, faller is not None),
           (True, True))
    expect("both were handed the map's baked passability",
           [b.collision_field is not None for b in (body, faller)],
           [True, True])

    spawn_y = body.transform.position.y
    advance(sidestep, 8)
    expect("the body is AIRBORNE early -- it is not merely sitting still",
           (body.transform.position.y > spawn_y, body.grounded), (True, False))

    advance(sidestep, 240)
    # DERIVED, never typed, and split into the gate's claim and the anchor's.
    #
    # `anchor_y` is what the COLLISION GATE decides: the tested point comes to
    # rest one EDGE_INSET above the top of the ground. It is true whatever the
    # anchor is, which is why it cannot be the only assertion here: a body
    # anchored at its head satisfies it while standing a whole sprite below
    # the floor.
    anchor_y = mapgen.SIDESTEP_GROUND_TOP * mapgen.TILE - EDGE_INSET
    resting = anchor_y - body.collision_offset[1]
    expect("the tested point came to rest exactly on top of the authored floor",
           body.collision_point()[1], anchor_y)
    expect("...and knows it is standing on it", body.grounded, True)
    expect("...with its fall velocity spent", body.velocity.y, 0.0)
    # The anchor, which the gate above cannot see. Both halves: the demo's
    # declared offset reached the entity, AND the visible consequence -- the
    # sprite's bottom edge is on the floor rather than 64px under it.
    expect("...and the point it tested is the body's FEET",
           body.collision_offset, SidestepDemo.COLLISION_OFFSET)
    expect("...so the sprite stands ON the floor rather than inside it",
           abs((body.transform.position.y + mapgen.SPRITE[1])
               - mapgen.SIDESTEP_GROUND_TOP * mapgen.TILE) <= 1.0, True)
    # The sharper half: the body with NO player_input landed on the same row.
    # Same class, same map, same platformer_move -- `player_input` is about
    # being steered, not about being simulated.
    expect("the body that carries no `player_input` landed too, on the same row",
           faller.transform.position.y, resting)
    expect("...and it never moved sideways, because nothing steered it",
           faller.transform.position.x, mapgen.SIDESTEP_FALLER_SPAWN[0])

    grounded_x = body.transform.position.x
    hold(sidestep, "right")
    advance(sidestep, 20)
    expect("holding `right` runs the side-on body right",
           body.transform.position.x > grounded_x, True)
    expect("...without leaving the floor", body.grounded, True)
    expect("...and the unsteered body still has not moved",
           faller.transform.position.x, mapgen.SIDESTEP_FALLER_SPAWN[0])

    hold(sidestep)
    advance(sidestep, 4)
    hold(sidestep, "jump")              # a rising edge, because HELD was empty
    sidestep.tick()
    # Asserted on the jump frame itself, not N frames later. `delta` is
    # wall-clock, so "6 frames after the jump" is 50ms on this machine and
    # could be 600ms -- past the apex and back on the floor -- on a slower
    # one. The impulse and the first upward step happen inside one update, so
    # one frame is both sufficient and timing-independent.
    expect("pressing `jump` leaves the ground",
           (body.grounded, body.velocity.y < 0.0), (False, True))
    expect("...and the body is already above where it was standing",
           body.transform.position.y < resting, True)
    expect("...while the unsteered body is still on the floor",
           (faller.transform.position.y, faller.grounded), (resting, True))
    hold(sidestep)
    advance(sidestep, 120)
    expect("it comes back down to the same pixel",
           body.transform.position.y, resting)
    sidestep_summary = summary(sidestep)

    # ------------------------------------------------------------------
    # The negative control. Everything above would also pass if the resting
    # position came from somewhere other than the collision gate -- and it
    # nearly can: `CollisionField.outside` is BLOCK_ALL, so a body with no
    # floor painted under it still stops at the world edge with grounded
    # True. This boots the SAME demo on the SAME map with the field taken
    # away, and asserts every one of those three numbers moves.
    # ------------------------------------------------------------------
    print()
    print("   ...and with the gate removed, the same map and the same "
          "behaviors do NOT land")
    hold(sidestep)
    ungated, _warnings = boot(SidestepDemo)
    for record in ungated.spawned:
        record.entity.collision_field = None
    loose = ungated.entity_of(mapgen.SIDESTEP_HERO_ID)
    advance(ungated, 240)
    expect("an ungated body is nowhere near the floor",
           loose.transform.position.y > resting, True)
    expect("...and never reports itself grounded", loose.grounded, False)
    expect("...and is still accelerating at terminal velocity",
           loose.velocity.y > 0.0, True)
    del ungated, loose

    # =====================================================================
    print()
    print("4. the two demos are the same class carrying different lists")
    # =====================================================================
    expect("both demos spawn exactly one class, and it is the same one",
           (topdown_summary["classes"], sidestep_summary["classes"]),
           (["GamePlayer"], ["GamePlayer"]))
    expect("...which is the class main.py builds by hand",
           topdown_summary["classes"], [GamePlayer.__name__])
    expect("both name the same tmx object type",
           topdown_summary["types"], sidestep_summary["types"])
    expect("both spawn onto the same object layer name",
           topdown_summary["layers"], sidestep_summary["layers"])
    expect("both resolve to the same depth",
           topdown_summary["depths"], sidestep_summary["depths"])
    # The whole point, as a set difference. Everything the two have in common
    # is composition; everything they differ by is one token at order 20.
    shared = set(topdown_summary["tokens"]) & set(sidestep_summary["tokens"])
    only_topdown = set(topdown_summary["tokens"]) - shared
    only_sidestep = set(sidestep_summary["tokens"]) - shared
    expect("they share `player_input` and `animation_drive`",
           sorted(shared), ["animation_drive", "player_input"])
    expect("and differ by exactly one token each",
           (sorted(only_topdown), sorted(only_sidestep)),
           (["topdown_move"], ["platformer_move"]))
    expect("...which are the two behaviors that declare they conflict",
           (BEHAVIOR_REGISTRY["topdown_move"].conflicts,
            BEHAVIOR_REGISTRY["platformer_move"].conflicts),
           (("platformer_move",), ("topdown_move",)))
    expect("...and sit at the same order, which is why one replaces the other",
           BEHAVIOR_REGISTRY["topdown_move"].order,
           BEHAVIOR_REGISTRY["platformer_move"].order)

    # =====================================================================
    print()
    print("5. the patrol demo: one movement behavior, two different producers")
    # =====================================================================
    hold(topdown)
    patrol, _warnings = boot(PatrolDemo)
    patroller = patrol.entity_of(mapgen.PATROL_PATROLLER_ID)
    driven = patrol.entity_of(mapgen.PATROL_HERO_ID)
    expect("both bodies spawned", (patroller is not None, driven is not None),
           (True, True))
    expect("...and the camera followed the one carrying `player_input`",
           patrol.scene.camera.target is driven, True)

    start = positions(patrol)
    hold(patrol)                        # NOTHING is pressed for this section
    advance(patrol, 90)
    moved = positions(patrol)
    expect("with no input at all, the scripted body walks",
           moved[mapgen.PATROL_PATROLLER_ID]
           != start[mapgen.PATROL_PATROLLER_ID], True)
    # The other half. Without it, "the patroller moved" is also satisfied by a
    # harness that is silently pressing something.
    expect("...and the body driven by a keyboard does not",
           moved[mapgen.PATROL_HERO_ID], start[mapgen.PATROL_HERO_ID])
    expect("the scripted body is facing a real direction, so it animates",
           patroller.state.move_direction in ("up", "down", "left", "right"),
           True)

    hold(patrol, "left")
    advance(patrol, 30)
    expect("pressing a key moves the driven body",
           positions(patrol)[mapgen.PATROL_HERO_ID][0]
           < start[mapgen.PATROL_HERO_ID][0], True)
    hold(patrol)

    # Identity, not equality. This is the claim: it is the SAME registered
    # behavior object type, built from the SAME spec, running for both.
    def behavior_named(entity, token):
        for item in entity.behaviors:
            if item.spec.name == token:
                return item
        return None

    scripted_move = behavior_named(patroller, "topdown_move")
    driven_move = behavior_named(driven, "topdown_move")
    expect("both bodies really do carry topdown_move",
           (scripted_move is not None, driven_move is not None), (True, True))
    expect("...it is the same class in both",
           type(scripted_move) is type(driven_move), True)
    expect("...built from the registry's one spec, by identity",
           (scripted_move.spec is BEHAVIOR_REGISTRY["topdown_move"],
            driven_move.spec is BEHAVIOR_REGISTRY["topdown_move"]),
           (True, True))
    expect("...and the only difference is what sits at order 10",
           (type(behavior_named(patroller, "patrol_input")).__name__,
            type(behavior_named(driven, "player_input")).__name__),
           ("GamePatrolInputBehavior", "GamePlayerInputBehavior"))
    # WHERE it sits, which is what makes it a producer at all. A behavior that
    # writes the intent AFTER the movement behavior has read it still looks
    # like it works -- the body walks, one frame stale -- so this is asserted
    # rather than observed. Relative, not `== 10`: the claim is that the two
    # producers occupy the same slot and that the slot is before the consumer,
    # which stays true if the engine renumbers its orders.
    expect("the scripted producer sits at the same order as the keyboard one",
           (BEHAVIOR_REGISTRY["patrol_input"].order
            == BEHAVIOR_REGISTRY["player_input"].order), True)
    expect("...which is before the movement behavior that reads what they write",
           (BEHAVIOR_REGISTRY["patrol_input"].order
            < BEHAVIOR_REGISTRY["topdown_move"].order), True)
    expect("...and both write the same attribute, so composing the two is "
           "refused by the order rule even without the declared conflict",
           (BEHAVIOR_REGISTRY["patrol_input"].writes,
            BEHAVIOR_REGISTRY["player_input"].writes[:1]),
           (("intent",), ("intent",)))
    expect("the scripted producer is registered from OUTSIDE scripts/",
           BEHAVIOR_REGISTRY["patrol_input"].factory.__module__,
           "demos.behaviors")
    expect("...and declares itself off the event bus, like every other one",
           BEHAVIOR_REGISTRY["patrol_input"].binds, ())
    patrol_summary = summary(patrol)
    expect("the patrol demo is the same class and depth as the other two",
           (patrol_summary["classes"], patrol_summary["depths"]),
           (topdown_summary["classes"], topdown_summary["depths"]))

    # =====================================================================
    print()
    print("6. `patrol_input` refuses what it must, and accepts what it must")
    # =====================================================================
    def compose(**values):
        entity = GamePlayer(
            input_=None,
            movement_config=patrol.assets.config.get("entity").get("default"),
            animation_config=patrol.assets.animations.get("entity"))
        entity.behaviors.attach(GamePatrolInputBehavior(**values))
        return entity

    ok_entity = compose(route=mapgen.PATROL_ROUTE, leg_ms=mapgen.PATROL_LEG_MS)
    expect("a legal route attaches and allocates an intent",
           ok_entity.intent.moving, False)
    expect_raises("an unknown direction raises, naming it and the four legal ones",
                  PyoneerConfigError,
                  lambda: compose(route="up_left", leg_ms=100),
                  "'up_left'", "move_direction", "up, down, left, right")
    expect_raises("an empty route raises rather than publishing nothing forever",
                  PyoneerConfigError, lambda: compose(route="", leg_ms=100),
                  "empty route")
    expect_raises("a zero leg raises rather than advancing every frame",
                  PyoneerConfigError,
                  lambda: compose(route="left", leg_ms=0), "leg_ms=0")

    # And the composition rule, both ways.
    legal = GamePlayer(
        input_=None,
        movement_config=patrol.assets.config.get("entity").get("default"),
        animation_config=patrol.assets.animations.get("entity"),
        behaviors=mapgen.PATROL_BEHAVIORS)
    expect("the demo's own list composes",
           sorted(b.spec.name for b in legal.behaviors),
           sorted(mapgen.PATROL_BEHAVIORS.split(",")))
    expect_raises("...and two producers at order 10 are refused, naming both",
                  PyoneerConfigError,
                  lambda: GamePlayer(
                      input_=None,
                      movement_config=patrol.assets.config.get("entity").get("default"),
                      animation_config=patrol.assets.animations.get("entity"),
                      behaviors="player_input,patrol_input,topdown_move"),
                  "player_input", "patrol_input", "conflict")

    # The freeze gate, BOTH directions, or the whole `can_move` branch could
    # be replaced with `if False:` and leave this check green. The gate reads
    # `can_move` but deliberately NOT
    # `enabled_inputs`, so both halves of that choice are pinned here, since a
    # patroller that honoured `enabled_inputs` would be the harder bug: it
    # would freeze only on maps whose spawner happens to pass input_=None.
    # `legal` carries the demo's WHOLE list -- patrol_input publishes an
    # intent and topdown_move is what displaces on it, so a patroller composed
    # of the input behavior alone never moves and would make every assertion
    # below pass for the wrong reason.
    def travelled(entity, frames):
        before = (entity.transform.position.x, entity.transform.position.y)
        for _ in range(frames):
            entity.core_frame_update(
                PyoneerEvent(GameEventType.UPDATE, data={"delta": 1.0}))
        return (entity.transform.position.x - before[0],
                entity.transform.position.y - before[1])

    expect("a patroller walks with nothing holding it",
           travelled(legal, 3) != (0.0, 0.0), True)
    legal.state.can_move = False
    expect("...can_move=False freezes it", travelled(legal, 20), (0.0, 0.0))
    expect("...and the published intent is EMPTY, not the stale last leg",
           legal.intent.moving, False)
    legal.state.can_move = True
    expect("...and clearing the freeze starts it again",
           travelled(legal, 3) != (0.0, 0.0), True)
    legal.state.enabled_inputs = False
    expect("...while enabled_inputs does NOT freeze it: a scripted body has "
           "no human input to disable",
           travelled(legal, 3) != (0.0, 0.0), True)

    # =====================================================================
    print()
    print("7. the maps are written once, under demos/, and nothing else moved")
    # =====================================================================
    for name in sorted(mapgen.SOURCES):
        expect("%s was generated into this check's workspace" % name,
               os.path.dirname(os.path.abspath(mapgen.map_path(name))),
               os.path.abspath(WORKSPACE))
    for label, game in (("topdown", topdown_summary),
                        ("sidestep", sidestep_summary),
                        ("patrol", patrol_summary)):
        expect("the %s demo loaded that generated file and no other" % label,
               os.path.dirname(os.path.abspath(game["map_file"])),
               os.path.abspath(WORKSPACE))

    # Write-once, both halves, in a directory of its own so the shipped maps
    # and this check's own workspace are both left alone.
    once_dir = tempfile.mkdtemp(prefix="pyoneer_demos_once_")
    previous_dir = mapgen.MAPS_DIR
    try:
        mapgen.MAPS_DIR = once_dir
        first = mapgen.ensure_map("demo_topdown")
        expect("ensure_map writes a map that is not there", os.path.exists(first),
               True)
        with open(first, "a", encoding="utf-8") as handle:
            handle.write("<!-- the author was here -->\n")
        with open(first, encoding="utf-8") as handle:
            painted = handle.read()
        again = mapgen.ensure_map("demo_topdown")
        with open(again, encoding="utf-8") as handle:
            after = handle.read()
        # Compared as booleans, not as text: `expect` prints both sides, and
        # printing two 40x30 CSV maps buries every other line of this check.
        expect("...and does NOT overwrite one that is", after == painted, True)
        with open(mapgen.regenerate("demo_topdown"), encoding="utf-8") as handle:
            fresh = handle.read()
        expect("only regenerate() replaces it", fresh == painted, False)
        expect("...and what it writes is the generated source",
               fresh == mapgen.SOURCES["demo_topdown"](), True)
    finally:
        mapgen.MAPS_DIR = previous_dir
        shutil.rmtree(once_dir, ignore_errors=True)

    with open(CONFIG_MAPS, "rb") as handle:
        expect("booting three demos did not edit config/maps.json",
               handle.read() == CONFIG_MAPS_BEFORE, True)
    expect("the shipped demo maps live under demos/, not under data/",
           os.path.abspath(SHIPPED_MAPS_DIR).startswith(
               os.path.join(os.path.abspath(_bootstrap.REPO_ROOT), "demos")),
           True)

    # =====================================================================
    print()
    print("8. a demo is a subclass of main.py's game, not a copy of it")
    # =====================================================================
    # Identity, not equality: a method COPIED into runtime.py and then edited
    # would still be `callable` and still have the right name, and only `is`
    # catches it. This is the assertion that fails the day a demo starts
    # being 300 lines of boilerplate, which is the outcome these demos exist
    # to disprove.
    inherited = ("prepare", "build", "prepare_test_scene", "spawn_arguments",
                 "load_config", "load_renderer", "begin", "tick", "quit",
                 "handle_global_input", "toggle_window", "__init__")
    copied = [name for name in inherited
              if getattr(DemoGame, name) is not getattr(MainGame, name)]
    expect("DemoGame inherits main.py's whole spine, by identity", copied, [])
    expect("...including the spawn arguments, so a demo's GamePlayer is "
           "constructed exactly as main.py's",
           DemoGame.spawn_arguments is MainGame.spawn_arguments, True)
    overridden = sorted(name for name in vars(DemoGame)
                        if callable(vars(DemoGame)[name])
                        and not name.startswith("__"))
    expect("...and overrides exactly the hooks it claims to",
           overridden, ["entity_of", "load_map", "load_test_objects"])
    for demo_class in (TopDownDemo, SidestepDemo, PatrolDemo):
        methods = sorted(name for name, value in vars(demo_class).items()
                         if callable(value) and not name.startswith("__"))
        expect("%s is class attributes and no code" % demo_class.__name__,
               methods, [])
        expect("...and names a map that exists in the generator",
               demo_class.MAP_NAME in mapgen.SOURCES, True)

    # `driven_record` is what turns a composition into a camera target, and it
    # is the one piece of logic runtime.py owns. Both halves.
    expect("driven_record finds the record carrying player_input",
           driven_record(topdown.spawned).object_id, mapgen.TOPDOWN_HERO_ID)
    expect("...and returns None when no record carries it",
           driven_record([r for r in topdown.spawned
                          if r.object_id != mapgen.TOPDOWN_HERO_ID]), None)
    expect("...and returns None for nothing at all", driven_record([]), None)

    # =====================================================================
    print()
    print("9. the dependency runs one way: demos/ imports scripts/, never the "
          "reverse")
    # =====================================================================
    def mentions_demos(root: str) -> list[str]:
        hits = []
        for base, _dirs, names in os.walk(root):
            if "__pycache__" in base:
                continue
            for name in names:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                if "import demos" in text or "from demos" in text:
                    hits.append(os.path.relpath(path, _bootstrap.REPO_ROOT))
        return sorted(hits)

    engine = os.path.join(_bootstrap.REPO_ROOT, "scripts")
    expect("nothing under scripts/ imports demos/", mentions_demos(engine), [])
    expect("...nor does the editor",
           mentions_demos(os.path.join(_bootstrap.REPO_ROOT, "editor")), [])
    with open(os.path.join(_bootstrap.REPO_ROOT, "main.py"),
              encoding="utf-8") as handle:
        main_text = handle.read()
    expect("...nor main.py, which is the smoke baseline",
           "demos" in main_text, False)
    # The other half: the instrument has to be able to find an import, or the
    # three empty lists above are three assertions that cannot fail.
    expect("...and the same walk DOES find them inside demos/",
           mentions_demos(os.path.join(_bootstrap.REPO_ROOT, "demos")) != [],
           True)

    # =====================================================================
    print()
    print("10. a demo boots main.py's script wire: the join, the say host "
          "and the action route")
    # =====================================================================
    # THE DEFECT THIS SECTION EXISTS FOR, measured before it was fixed:
    #
    #     MainGame  scripts=1 object_scripts=1 dialogue=True  routes=(('interact_action','',1),)
    #     DemoGame  scripts=1 object_scripts=0 dialogue=False routes=()
    #
    # `prepare_test_scene` is inherited BY IDENTITY and is what reads
    # `data/project/scripts/`, so every demo paid to load every script; the
    # join, the `say` host and the one action route all live in
    # `load_test_objects`, which `DemoGame` overrode WITHOUT calling super().
    # So a demo could never run a script it had already loaded -- and both of
    # the map route's guards were absent on that route, which means a demo
    # map's `pyoneer_script` naming a document that is not there produced a
    # body that looked scripted and was silently inert. Law 7's failure shape
    # on the route a new author is likeliest to copy.
    #
    # THE SCRIPTS AND THE MAPS BELOW ARE THIS CHECK'S OWN (law 4).
    # `data/project/scripts/` is the author's project exactly as
    # `demos/maps/` is the author's canvas, and a check that read either
    # would be asserting what a DATA FILE contains. `default_scripts_dir` is
    # redirected at a generated directory and restored in the `finally`, and
    # the three fixture maps are registered into `mapgen.SOURCES` and removed
    # the same way.
    FIXTURE_SCRIPT = "demo_greeting"
    FIXTURE_LINE = "THE DEMO ROUTE REACHED A SCRIPT."
    FIXTURE_SPEAKER = "Fixture"
    ABSENT_SCRIPT = "no_such_document_at_all"

    scripts_dir = os.path.join(WORKSPACE, "project_scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    with open(os.path.join(scripts_dir, FIXTURE_SCRIPT + ".json"), "w",
              encoding="utf-8") as handle:
        json.dump({
            "format": script_file.FORMAT,
            "version": script_file.VERSION,
            "id": FIXTURE_SCRIPT,
            "title": "One line, so a demo press has something to show",
            "loadouts": ["core"],
            "pages": [{
                "id": "only",
                "trigger": "use",
                "when": [],
                "body": [{"id": "line", "do": "say",
                          "who": FIXTURE_SPEAKER, "text": FIXTURE_LINE}],
            }],
        }, handle)
    script_file.default_scripts_dir = lambda: scripts_dir

    def _grid_of(width, height):
        return [[mapgen.GRASS] * width for _ in range(height)]

    def scripted_source(script_id: str, behaviors: str):
        """One hero on a bare map, carrying `pyoneer_script=script_id`.

        Built from `mapgen`'s own helpers and geometry, so the object is the
        same shape the shipped demo maps place and nothing here is a second
        spelling of the tmx.
        """
        width, height = mapgen.TOPDOWN_SIZE

        def source() -> str:
            return mapgen.build_tmx(
                width, height, _grid_of(width, height), None,
                [mapgen._object(
                    mapgen.TOPDOWN_HERO_ID, "hero", "GamePlayer",
                    mapgen.TOPDOWN_HERO_SPAWN[0], mapgen.TOPDOWN_HERO_SPAWN[1],
                    mapgen.SPRITE[0], mapgen.SPRITE[1],
                    {"pyoneer_behaviors": ("", behaviors),
                     "pyoneer_script": ("", script_id)})])
        return source

    TALKER_BEHAVIORS = (mapgen.TOPDOWN_BEHAVIORS
                        + ",interact_action,action_relay")
    mapgen.SOURCES = dict(
        SHIPPED_SOURCES,
        check_talker=scripted_source(FIXTURE_SCRIPT, TALKER_BEHAVIORS),
        check_absent=scripted_source(ABSENT_SCRIPT, TALKER_BEHAVIORS),
        check_mute=scripted_source(FIXTURE_SCRIPT, mapgen.TOPDOWN_BEHAVIORS))

    class TalkerDemo(DemoGame):
        MAP_NAME = "check_talker"

    class AbsentScriptDemo(DemoGame):
        MAP_NAME = "check_absent"

    class MuteDemo(DemoGame):
        MAP_NAME = "check_mute"

    # -- half one: the wire is there, and it is MAIN.PY'S, not a lookalike --
    talker, talker_warnings = boot(TalkerDemo)
    talker_hero = talker.entity_of(mapgen.TOPDOWN_HERO_ID)
    expect("a demo boot loaded the script table",
           sorted(talker.scripts), [FIXTURE_SCRIPT])
    expect("...and JOINED the body that names one, which is what was missing",
           [(entity is talker_hero, script_id)
            for entity, script_id in talker.object_scripts],
           [(True, FIXTURE_SCRIPT)])
    expect("...so the host's identity search answers for it",
           talker.script_for(talker_hero), FIXTURE_SCRIPT)
    # IDENTITY, not resemblance. A demo that grew its own dialogue host and
    # its own handler would satisfy "there is a host" and "there is a route"
    # while being the second implementation this file exists to refuse.
    expect("the `say` host a demo got is main.py's ScriptDialogue",
           type(talker.dialogue).__module__, "main")
    routed = talker.scene.actions.handlers_for("interact_action")
    expect("exactly one handler is on the token, with any payload",
           len(routed), 1)
    # Reported as data rather than indexed, so the mutation that empties the
    # route above fails THIS line too instead of raising an IndexError and
    # taking every assertion below it with it.
    expect("...and it IS main.py's own run_object_script, bound to this game",
           [(handler.__func__ is MainGame.run_object_script,
             handler.__self__ is talker) for handler in routed],
           [(True, True)])
    expect("a scripted demo map warns about nothing",
           [w for w in talker_warnings if FIXTURE_SCRIPT in w], [])

    # -- and it RUNS: the press a demo author would make ---------------------
    def spoken(game):
        """(speaker, line) for whatever box the host built, or None.

        Through `getattr`, so the mutation that removes the host entirely
        FAILS these lines rather than raising and taking the rest of the
        section with it.
        """
        box = getattr(game.dialogue, "box", None)
        return None if box is None else (box.speaker, box.line)

    expect("nothing is running before the key goes down",
           (talker.script_run, spoken(talker)), (None, None))
    hold(talker, "action")
    advance(talker, 1)
    expect("one press starts the run", talker.script_run is not None
           and talker.script_run.running, True)
    expect("...and the line is on screen, from this check's own document",
           spoken(talker), (FIXTURE_SPEAKER, FIXTURE_LINE))
    expect("...and the run is in the scene's one flow slot, being ticked",
           talker.scene.flow is talker.script_run, True)
    hold(talker)
    advance(talker, 1)
    hold(talker, "action")
    advance(talker, 1)
    expect("a second press advances it to the end rather than starting a "
           "second run", getattr(talker.script_run, "running", None), False)
    hold(talker)

    # -- the other half of "the route is installed": a demo with NO script --
    # The route and the host are unconditional -- they are the shipped game's
    # wiring and a demo inherits it whole -- while the JOIN is a pure function
    # of what the map declares. Without this pair, "object_scripts is [x]"
    # above could be a list that is never empty.
    expect("a demo map declaring no script still gets the host and the route",
           (type(topdown.dialogue).__module__,
            len(topdown.scene.actions.handlers_for("interact_action"))),
           ("main", 1))
    expect("...and joins nothing, so the join reads the map and not the class",
           topdown.object_scripts, [])

    # -- half two: the guards came with it -----------------------------------
    # THE TEETH. Before the super() call these two were silent on the demo
    # route and loud on the shipped one -- the same property, the same
    # document, two answers.
    expect_raises("a demo map naming an absent script RAISES at boot, naming "
                  "the object", PyoneerAssetMissingError,
                  lambda: AbsentScriptDemo(autostart=False),
                  ABSENT_SCRIPT, "id=%d" % mapgen.TOPDOWN_HERO_ID,
                  script_file.SCRIPT_PROPERTY, FIXTURE_SCRIPT)
    mute, mute_warnings = boot(MuteDemo)
    scripted_warnings = [w for w in mute_warnings if FIXTURE_SCRIPT in w]
    expect("a scripted demo body missing the two tokens WARNS, once",
           len(scripted_warnings), 1)
    expect("...naming both tokens and the object it is on",
           [fragment for fragment in ("interact_action", "action_relay",
                                      "id=%d" % mapgen.TOPDOWN_HERO_ID)
            if not any(fragment in text for text in scripted_warnings)], [])
    expect("...and it is a WARNING: the body still spawned and still joined",
           mute.script_for(mute.entity_of(mapgen.TOPDOWN_HERO_ID)),
           FIXTURE_SCRIPT)

    # -- the copy is gone, which is the other reason super() is the fix -----
    # `load_test_objects` used to carry main.py's three-line camera pick
    # verbatim. That is law 2's corollary at small scale, and the corollary
    # has already been paid here at 425 duplicate lines.
    hook = inspect.getsource(DemoGame.load_test_objects)
    expect("DemoGame's hook CALLS the shipped one",
           "super().load_test_objects()" in hook, True)
    expect("...and no longer re-spells its camera pick",
           "driven_record(" in hook, False)
    expect("...while main.py's hook is still where that pick lives",
           "driven_record(" in inspect.getsource(MainGame.load_test_objects),
           True)
    expect("the one thing the demo hook still decides is the debug window",
           (talker.window is not None, getattr(talker.window, "visible", None),
            getattr(talker.window, "active", None)), (True, False, False))

finally:
    mapgen.MAPS_DIR = SHIPPED_MAPS_DIR
    mapgen.SOURCES = SHIPPED_SOURCES
    script_file.default_scripts_dir = SHIPPED_SCRIPTS_DIR_FN
    HELD.clear()
    shutil.rmtree(WORKSPACE, ignore_errors=True)

print()
if failures:
    print(f"FAILED ({len(failures)} of {asserted}):", failures)
    sys.exit(1)
print(f"PASS -- {asserted} assertions, five demos booted and driven, "
      "one refused to boot")
