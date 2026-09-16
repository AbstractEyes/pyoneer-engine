<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; the behavioural claims are re-measured on every run by tools/check_demos.py and tools/check_prototype.py, and the six gaps were re-read against the working tree on 2026-09-16 (gap 6 by the grep printed in it). -->

# Demos -- four prototype games, and what each one proves

What a demo *proves* is a claim about the design, so this file is hand-written.
To START one, fill the form and follow the loop in
[`DESIGN_TEMPLATE.md`](DESIGN_TEMPLATE.md#the-loop-design---build---prove).

## What a demo is here

A `.tmx` file plus a subclass of `MainGame` that names it -- a class of a few
lines with no method of its own.

    demos/topdown.py     top-down, six objects, one player
    demos/sidestep.py    side-on platformer with gravity
    demos/patrol.py      a scripted body and a driven one
    demos/story.py       an opening cutscene over a scene flow

A demo is *not* a copy of `main.py`. `demos/runtime.py`'s `DemoGame` overrides
two of `MainGame`'s per-game hooks, `load_map` and `load_test_objects`, once for
all four, and `load_test_objects` calls `super()` first, so a demo boot gets the
shipped game's script join, dialogue host and action route. `tools/check_demos.py`
asserts by **identity** that `DemoGame.tick is MainGame.tick` and so on for the
whole spine, so a method copied into `runtime.py` and edited turns it red.

Beside them: `demos/mapgen.py` writes each map and its placeholder tilesets,
with every position, id and geometry number a named constant the checks derive
from; `demos/behaviors.py` registers `patrol_input` from outside the engine;
`demos/narrative.py` is the narrative kit (a dialogue box, the step adapter, the
hook that mounts a flow).

## Running one

    .venv/Scripts/python.exe -m demos.topdown
    .venv/Scripts/python.exe -m demos.sidestep
    .venv/Scripts/python.exe -m demos.patrol
    .venv/Scripts/python.exe -m demos.story

    --frames N        stop after N frames instead of running until quit

Controls come from `config/inputs.json`, and nothing in `demos/` names a key:
`w a s d` walk, `space` jumps (side-on only), `e` is the action verb (story:
advance the conversation), `left ctrl` sprints, `escape` quits. The checks press
whatever the running manager says a verb is bound to, so rebinding is checked
rather than assumed.

The first run writes the map into `demos/maps/`. After that the file is yours:
`ensure_map` writes only when the file is absent, so repainting one in Tiled
sticks. Delete a `.tmx`, or call `demos.mapgen.regenerate(name)`, to get the
generated one back.

## The four demos

### `demos.topdown` -- the map is enough, and `player_input` is the whole marker

Six `<object type="GamePlayer">` on one object layer, at one depth, from one
registry entry, all handed the same live input manager. Five carry
`pyoneer_behaviors="topdown_move,animation_drive"`; one carries
`pyoneer_behaviors="player_input,topdown_move,animation_drive"`. That token is
the entire difference between scenery and a player: no flag, no subclass. The
check walks the driven body with injected input **and** asserts the other five
stay on the exact pixel they spawned on. `main.py` itself now works the same
way -- its one body comes from `data/maps/starter.tmx` and it builds no entity
in Python -- so this demo is the same composition on a map small enough to
reason about.

### `demos.sidestep` -- genre lives in map data

Same class, tmx object type, object layer name and resolved depth as
`demos.topdown`; the check asserts all four are equal across the two live
games. Each behavior list differs by one token, `platformer_move` for
`topdown_move`, plus parameters the map carries as properties (`jump_verb`,
`gravity`, `move_speed`, `jump_velocity`, ...). The two movement behaviors
declare a conflict at the same `order`, which is why one replaces the other.

It is the only demo that needs the collision gate: its map declares a
`collision` tileset and a `FloorCollision` companion layer, so the engine bakes
a real field and hands it to every spawned body. The check does not trust
`grounded`, because the world edge also reports it: it asserts the body was
airborne, rests with its **feet** at exactly the derived floor pixel, and that
a second boot with the field cleared does none of that. A second body without
`player_input` falls and lands on the same row: `player_input` is about being
*steered*, not being *simulated*. The ground is five rows thick because a long
frame after the startup bake can step a falling body past a thinner floor.

### `demos.patrol` -- the intent seam is real, and the registry is open

`scripts/game/behavior/input.py` claims a movement behavior can be driven by
something other than a keyboard by attaching a different producer at the same
`order`. This map places `patrol_input,topdown_move,animation_drive` beside
`player_input,topdown_move,animation_drive`, and `topdown_move` is the same
registered spec object in both, asserted by identity. `patrol_input` is
registered in `demos/behaviors.py`, outside `scripts/`, so a game adds a
behavior without editing the engine's table; the import in `demos/patrol.py` is
load-bearing because tokens resolve while the map binds. With **nothing
pressed**, the patroller walks and the hero does not move a pixel. That makes
this the cheapest instrument in the tree for watching a body walk, which
`tools/smoke.py` cannot do because it presses nothing.

### `demos.story` -- a cutscene takes the steering and gives it back exactly

Two `GamePlayer` objects: the hero carries
`player_input,topdown_move,animation_drive,interact_action,action_relay`, the
keeper `topdown_move,animation_drive`. `interact_action` fires on the rising
edge of `action`; `action_relay` calls `entity.action_sink`, which
`SceneManager` has set to the scene's `ActionRouter`; the route ends at
`#TAG:SceneFlow.on_action`. The whole chain is calls, not events, so no handler
can silence another. The route is keyed by `(token, payload)` and the hero
carries `pyoneer_param_payload="keeper"`, so one verb can open different
conversations without an `if` in the handler.

The check presses movement and action **on the same frames** and asserts: the
hero moves zero pixels while held, and the action verb still advances; a timed
beat advances with nothing pressed, and an untimed one does not; steering comes
back to the value each body **had**, never to `True`; the routed payload
reaches the flow, and any other reaches nothing; the dialogue text queues a
blit only while the box is open; and a second boot with no script walks from
frame one. The form that designed this demo is the worked example in
[`DESIGN_TEMPLATE.md`](DESIGN_TEMPLATE.md), compared to the running game field
by field.

The finding it produced: a `FlowStep` carries no text, so handing every step
the same window reopens one box saying one thing. `StoryLine` in
`demos/narrative.py` sets the line and *then* opens the shared box, outside
`scripts/`. What it does not do: **branch** (a step has one successor), or
**wrap words** (`prepare_text` renders one string and shrinks the font).

## What a demo still has to say in Python

1. **A collision anchor cannot be authored per entity.** `main.py`'s
   `feet_anchor()` derives a centre-bottom anchor per animation category and
   `DemoGame` inherits it, so demo bodies are anchored at the feet by the
   shipped route. There is no property or behavior parameter for one body to
   differ. `SidestepDemo.COLLISION_OFFSET` survives only as the pair the check
   measures that derivation against.
2. **Demo maps spell their behavior lists out.** A genre pack's default list
   reaches an object through the editor, where `map.object.add` materialises it
   (`#TAG:behaviors_materialised_at_add`). `demos/mapgen.py` writes maps from
   Python, so it never passes through that door.
3. **No demo object names an actor row.** The engine reads
   `data/project/tables/` and `DemoGame` inherits the reader, but no demo map
   writes `pyoneer_actor`, so the side-on demo tunes gravity and jump with
   `pyoneer_param_*` on the object. The gap is the maps', not the engine's
   (`#TAG:actor_row`).
4. **The story demo's beats are Python.** They are a `SCRIPT` class attribute
   over `SceneFlow`, begun at boot. The data route now exists: `pyoneer_script`
   on a tmx object names a JSON document under `data/project/scripts/`, the
   `action` verb runs it, and `tools/check_demos.py` proves a demo map's
   scripted body runs its document through `main.py`'s own wire. The story demo
   predates that route and has not been moved onto it.
5. **A demo map is registered in Python.** `DemoGame.load_map` inserts it into
   the asset manager rather than editing `config/maps.json`, which is the
   shipped game's list; the check asserts that file is byte-identical after
   the demos boot.
6. **The side-on companion layer warns on every boot.**
   `map layer 'FloorCollision' has no depth mapping ... will NOT be drawn.` is
   printed once per `demos.sidestep` boot. The engine does read
   `LayerProfile.renders` now (`#TAG:renders_false_is_data`), and a layer
   declaring `pyoneer_renders=false` is skipped silently -- which is what
   `data/maps/starter.tmx`'s own companion does. `demos/mapgen.py` never writes
   that property, so the layer is kept off screen only because its name has no
   depth, and `tools/check_demos.py` currently asserts the warning appears
   exactly once. The fix is authoring `pyoneer_renders=false` in the generator
   and flipping that assertion in the same change; do **not** add
   `FloorCollision` to `scripts/core/depth.py`, which would draw the masks over
   the floor. Measured: `grep -n "renders" demos/mapgen.py` finds only prose,
   never a written property.

## The checks

    .venv/Scripts/python.exe tools/check_demos.py
    .venv/Scripts/python.exe tools/check_prototype.py

`check_demos` boots the top-down, side-on (twice: gated and ungated) and patrol
demos, plus fixture maps for the script wire. `check_prototype` owns the story
demo, because that demo is also the design form's worked example, and checks
the form and its loop. Both are in `tools/check_all.py`'s roster, and each
module's docstring lists the mutations that were run against it.

Both boot through the real `MainGame` spine and drive it by replacing
`pygame.key.get_pressed`, so the engine's own `pressed`/`held`/`released`
derivation runs unmodified. Both generate their maps into a temp directory, so
`demos/maps/*.tmx` stays the author's to repaint.
