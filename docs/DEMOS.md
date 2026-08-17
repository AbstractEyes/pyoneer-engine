# Demos -- three prototype games, and what each one proves

**This file is hand-written.** `docs/BEHAVIORS.md` is generated from the
behavior registry; this one is not, because what a demo *proves* is a claim
about the design and no table knows it. Every number below is measured, and
`tools/check_demos.py` re-measures all of it on every run.

## What a demo is here

A `.tmx` file plus a subclass of `MainGame` that names it. That is the whole
thing. The three demos are **7, 9 and 8 lines of code** respectively
(docstrings excluded), and none of them contains a method.

    demos/topdown.py     7 code lines    top-down, six objects, one player
    demos/sidestep.py    9 code lines    side-on platformer with gravity
    demos/patrol.py      8 code lines    a scripted body and a driven one

A demo is *not* a copy of `main.py`. `MainGame` already exposes three
per-game hooks -- `load_map`, `spawn_arguments`, `load_test_objects` -- and
`demos/runtime.py` overrides two of them once, for all three demos.
`tools/check_demos.py` asserts by **identity** that `DemoGame.tick is
MainGame.tick` and so on for the whole spine, so a method copied into
`runtime.py` and then edited turns the check red. That assertion is the alarm
for "a demo is 300 lines of boilerplate", which is the outcome these demos
exist to disprove.

## Running one

    .venv/Scripts/python.exe -m demos.topdown
    .venv/Scripts/python.exe -m demos.sidestep
    .venv/Scripts/python.exe -m demos.patrol

    --frames N        stop after N frames instead of running until quit

Controls come from `config/inputs.json` and nothing in `demos/` names a key:

    w a s d       the verbs up / down / left / right
    space         the verb jump          (side-on demo only)
    left ctrl     the verb sprint
    escape        quit                   (main.py's hardcoded key, not a verb)

Rebinding a verb in `config/inputs.json` changes the demo and changes nothing
else. `tools/check_demos.py` presses whatever the *running manager* says a
verb is bound to rather than a keycode literal, so that property is checked
rather than assumed.

The first run of each demo writes its map into `demos/maps/`. After that the
file is yours: `ensure_map` writes only when the file is **absent**, so
repainting one in Tiled sticks. Delete a `.tmx` to get the generated version
back, or call `demos.mapgen.regenerate(name)`.

## The three demos

### `demos.topdown` -- six objects, one of which is the player

**Proves: the map is enough, and `player_input` is the whole marker.**

Six `<object type="GamePlayer">` on one object layer, at one depth, spawned
from one registry entry, constructed with one set of arguments, and handed
the *same live `InputActionManager`*. Five carry

    pyoneer_behaviors="topdown_move,animation_drive"

and one carries

    pyoneer_behaviors="player_input,topdown_move,animation_drive"

That one token is the entire difference between scenery and a player. There
is no flag, no `pyoneer_player` property, and no subclass. Holding an input
manager does nothing; **reading** one moves an entity, and only
`player_input` reads one.

*The measurement with teeth:* injected input walks the driven entity and
leaves the other five on the exact pixel they spawned on, facing `"none"`.
One half of that pair alone would pass for a game with no decoys at all.

*Why it exists when `main.py` already does this:* `main.py` builds the same
six entities in Python and is the frame `tools/smoke.py` measures drift
against, so it is not going to change. This is the same game with the Python
deleted, which turns "the composition model is faithful" into something
comparable instead of something you look at.

### `demos.sidestep` -- a platformer that is the same class

**Proves: genre lives in map data.**

Same class, same tmx object type, same object layer name, same resolved
depth as `demos.topdown` -- the check asserts all four are equal across the
two live games. The behavior lists differ by exactly one token each:

    demo_topdown     player_input , animation_drive , **topdown_move**
    demo_sidestep    player_input , animation_drive , **platformer_move**

plus parameters the map carries as properties (`jump_verb`,
`initial_sequence`, `gravity`, `move_speed`, `jump_velocity`). The two
movement behaviors declare that they conflict and sit at the same `order`,
which is *why* one replaces the other rather than joining it. There is no
`GamePlatformerPlayer` and adding one would undo the point.

This is the only demo that needs the collision gate. Its map declares a
`<tileset name="collision">` and a `FloorCollision` companion layer, so
`field_from_map` bakes a real field and `LayerRenderer.__bind_map`'s gating
sweep hands it to every spawned entity. (Not `__prepare_entity_layers` — that
one states in its own docstring that it does **not** gate what it binds.)

*The measurement with teeth, and the trap it avoids:* `grounded is True` is
**not** a sufficient assertion. `CollisionField.outside` is `BLOCK_ALL`, so a
body with no floor painted under it still stops at the world edge reporting
`grounded=True`. Measured: with the companion layer painted all-open, the body
comes to rest at 767.999 with `grounded=True` -- a check that asserted only
`grounded` would pass on a map with no collision in it at all. So the check
asserts, together:

  * the body was **airborne** on an early frame (kills "it never moved"),
  * its collision point rests at **exactly** `floor_top - EDGE_INSET` (kills
    the world-edge case, the ungated case and the wrong-floor case),
  * the point tested is the body's **feet**, and the sprite's bottom edge is
    on the floor rather than 64px under it (kills the head anchor, which
    satisfies the gate assertion perfectly),
  * `grounded` is True and the fall velocity is spent,
  * and, on a second boot of the same demo with `collision_field` cleared,
    **none** of those is true -- so the resting position is a measurement of
    the gate and not of the harness.

The second object carries `platformer_move,animation_drive` and no
`player_input`. It falls and lands on the same row as the driven one, which
is the sharper half of the claim: `player_input` is about being *steered*,
not about being *simulated*.

### `demos.patrol` -- one movement behavior, two drivers

**Proves: the intent seam is real, and the registry is open to a game.**

`scripts/game/behavior/input.py` claims that a movement behavior can be
driven by "a replay, a network peer, an AI -- by attaching a different
producer at `order` 10 and changing nothing else". Nothing exercised it, so
it was a claim about the design rather than a fact about the code. This map
places two objects:

    patroller    patrol_input , topdown_move , animation_drive
    hero         player_input , topdown_move , animation_drive

`topdown_move` is the *same registered spec object* in both -- asserted by
identity against `BEHAVIOR_REGISTRY["topdown_move"]`, not by class name --
and it does not know whether a keyboard or a clock wrote the `MoveIntent` it
reads.

`patrol_input` is declared and registered in **`demos/behaviors.py`**, which
is outside `scripts/`. That is the second thing this demo proves:
`scripts.game.behavior.register` is a real extension point and a game adds a
behavior without editing the engine's table. The import in `demos/patrol.py`
is load-bearing -- the token is resolved while the map is being *bound*, so a
registration that happened later would raise "unknown behavior token".

*The measurement with teeth:* with **nothing pressed at all**, the patroller
walks and the hero does not move a pixel. Both halves, because "the patroller
moved" alone is also satisfied by a harness that is silently pressing
something. The check additionally pins that `patrol_input` sits at the *same
order as* `player_input` and *before* `topdown_move` -- a producer that ran
after its consumer would still look like it worked, one frame stale.

This is also the only demo a check can drive deterministically with no key
injection, which makes it the cheapest instrument in the tree for watching a
player actually walk -- the blind spot `tools/smoke.py` has by construction,
since smoke presses nothing.

## What a demo is made of

    demos/runtime.py     `DemoGame(MainGame)`. 84 code lines, shared by all
                         three. Overrides `load_map` and `load_test_objects`
                         and nothing else.
    demos/mapgen.py      writes each `.tmx` and its two placeholder tilesets
                         into `demos/maps/`, once. Every number a check would
                         otherwise hardcode -- ground row, spawn positions,
                         object ids -- is a named constant here, so the check
                         DERIVES what it expects instead of typing it twice.
    demos/behaviors.py   `patrol_input`, registered from outside the engine.
    demos/<name>.py      the demo: a class with a `MAP_NAME`.

`DemoGame` adds exactly two things `MainGame` cannot, and both are values a
`.tmx` object has no way to say:

**The camera target.** `main.py` attaches the camera to the player it built
itself; a map-spawned demo has no such handle. `DemoGame` derives it from the
composition -- the record whose behaviors include `player_input` -- using
`SpawnedEntity.behaviors`, which already carries the resolved list. No new
property and no marker flag. It also sets `self.player`, because
`main.py.handle_global_input` dereferences that attribute unconditionally on
an arrow key and a demo that left it `None` would crash inside the frame loop.

**The collision anchor.** See below.

## What a demo still has to say in Python

These are the real gaps, in the order they cost the most:

1. **`collision_offset` has no authoring surface.** `GameEntity
   .collision_offset` defaults to `(0.0, 0.0)`, which is the sprite's
   *top-left* -- for the shipped 44x64 frame, the top of the character's
   head. A side-on body wants feet, so `SidestepDemo` sets `(22.0, 63.0)` as
   a class attribute and `DemoGame.load_test_objects` applies it to every
   spawned entity. There is no `pyoneer_collision_offset` property and no
   behavior parameter. This is the shortest item on this list and the one
   most worth closing: it is per-ENTITY data living in per-GAME code.
2. **A genre pack cannot supply the behavior list.** Every object in these
   maps spells its list out. `editor/genres/*/genre.json` may declare
   `layers[].object_classes[].behaviors`, and the editor is meant to
   MATERIALISE that into the object when the object is added -- so the `.tmx`
   stays the whole truth. Until it does, `demos/mapgen.py` writes the
   strings.
3. **Nothing reads `data/project/tables/actors.json`.** Every
   `source="actors"` parameter on `platformer_move` therefore resolves from
   the object property or the declared default, which is why the side-on
   demo tunes gravity and jump velocity with `pyoneer_param_*` on the object
   rather than with an actor row.
4. **A demo map is registered in Python.** `DemoGame.load_map` inserts a
   `MapData` into `AssetMapManager.maps` rather than adding an entry to
   `config/maps.json`, because that file is the shipped game's map list and
   a demo must not edit it. The check asserts `config/maps.json` is
   byte-identical after all three demos have booted.

## Known warts you will see and should not "fix"

**`map layer 'FloorCollision' has no depth mapping ... will NOT be drawn.`**
Printed once per boot of `demos.sidestep`, and it is correct behaviour
described by a misleading suggestion. A mask layer *must not* draw.
`LayerProfile.renders` exists to say so properly and **nothing in the engine
reads it** (`grep -rn '\.renders' scripts/` finds no consumer), so today the
mask layer is kept off the screen by the accident of its name being absent
from `MAP_DEPTH`. Do **not** take the warning's advice and add
`FloorCollision` to `scripts/core/depth.py`: that is the change that makes
the masks draw on top of the floor. The check asserts the warning appears
exactly once on the map that declares collision and not at all on the maps
that do not.

**`demo_sidestep`'s ground is five rows thick.** Not decoration. A frame's
`delta` is wall-clock, and the frames just after the ~280ms composite bake
are long; at terminal velocity a long frame steps further than a tile. The
gate tests one anchor POINT per axis per call, so it cannot see a step that
jumped over the blocking cell, and `CollisionField.outside` is `BLOCK_ALL`,
so a body that tunnelled would come to rest at the world edge with
`grounded=True` -- indistinguishable from landing, unless you assert the
exact pixel. Five rows is 160px, which needs a 0.27s frame to cross.

**The tileset PNGs are generated.** `demos/maps/demo_tiles.png` is four flat
colours and `demo_collision.png` is seventeen mask swatches. A demo about art
would be a demo about art.

## Starting a new demo

Four steps. The third is the only one with any thinking in it.

1. **A map source in `demos/mapgen.py`.** Copy `_topdown_source`, add it to
   `SOURCES`, and put every position, object id and geometry number in a
   named module constant beside the others -- `tools/check_demos.py` derives
   its expectations from those constants, and a number typed twice is a check
   that pins map content instead of code.
2. **A class in `demos/<name>.py`.**

       from demos.runtime import DemoGame, run

       class MyDemo(DemoGame):
           MAP_NAME = "demo_mine"

       if __name__ == "__main__":
           sys.exit(run(MyDemo))

   If it needs a method, stop: the method wanted a hook on `DemoGame`, or a
   hook on `MainGame`, and the check will refuse the demo either way.
3. **The behavior list, on each object.** `docs/BEHAVIORS.md` has the
   registry and a complete legal list per genre. Two rules the loader
   enforces at bind time rather than at frame time: one token appears at most
   once per object, and two behaviors that declare a conflict -- or that
   share an `order` and write the same attribute -- refuse to compose. A
   behavior polling a verb that `config/inputs.json` does not bind raises at
   attach, naming the verb.
4. **A section in `tools/check_demos.py`.** Boot it, drive it, and assert
   both halves of every gate. A demo nothing runs is the orphan problem this
   repository already has a document about.

## The check

    .venv/Scripts/python.exe tools/check_demos.py

**100 assertions, ~9 seconds**, four headless boots (the side-on demo twice:
once gated, once with the field removed as a negative control). It is in
`tools/check_all.py`'s roster.

It boots each demo through the real `MainGame` spine and drives it by
replacing `pygame.key.get_pressed`, so the engine's own edge derivation --
`pressed`, `held`, `released` -- runs unmodified; nothing here re-implements
an edge, which is `tools/check_input.py`'s claim to own.

**It reads its own maps.** `demos.mapgen.MAPS_DIR` is redirected to a temp
directory and every map is generated fresh into it, so `demos/maps/*.tmx`
stays the author's canvas exactly as `data/maps/test.tmx` does, and repainting
one cannot turn the check red.

Fourteen mutations were run against it and all fourteen turned it red:
`driven_record` matching any record; the feet offset removed; the side-on map
declaring no collision; the companion layer painted all-open; the route
validation deleted; the patrol producer publishing nothing; its declared
conflict removed; its `order` moved from 10 to 50; the hero losing
`player_input`; a decoy gaining it; the faller gaining it; the camera never
attached; `MainGame.tick` copied into `DemoGame`; and a demo class growing a
method.
