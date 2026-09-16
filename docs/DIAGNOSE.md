<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; re-measured 2026-09-16 by the commands printed beside the claims -- every quoted error string and warning below was produced by executing the code that day, and tools/check_script_runtime.py and tools/check_collision_fold.py passed. -->

# Diagnose — "why doesn't my entity do the thing"

**This file is hand-written**, because a symptom is not derivable from a
registry. Read [`../CLAUDE.md`](../CLAUDE.md) first for the vocabulary, and
[`BEHAVIORS.md`](BEHAVIORS.md)'s measured integration table for what is
actually wired.

The single most useful fact: **failures here split into two opposite
families.** Some raise loudly at load, at attach or on the frame they happen;
others move zero pixels and say nothing. Knowing which family your symptom is
in halves the search.

| | raises | silent |
|---|---|---|
| unknown behavior token | ✔ at spawn | |
| unknown tmx object `type` | ✔ at map load | |
| behavior polls an unbound verb | ✔ at attach | |
| unknown animation sequence | ✔ at `start()` | |
| `pyoneer_script` naming no document | ✔ at boot | |
| a script names a sound neither audio root holds | ✔ when the node runs | |
| `ask` in a running script | ✔ when the node runs | |
| unknown movement **direction** | | ✔ moves zero |
| unmapped tile layer name | | ✔ never draws |
| no `player_input` token, on the body the game ADOPTED | warns at boot | ✔ never moves |
| no `player_input` token, on any other body | | ✔ never moves |
| a scripted map body missing `interact_action` or `action_relay` | warns at boot | ✔ press starts nothing |
| no sound card | warns once | ✔ plays nothing, game runs |
| another flow already running in the slot | | ✔ press starts nothing |
| collision field says BLOCK_ALL | | ✔ never moves |
| a stamped tile carries its own mask | | ✔ blocks with no cell painted |
| masks painted on a parallaxed layer | warns at load | ✔ never reach the field |

---

## "It raises at load and I never see a window"

**`PyoneerAssetMissingError: entity behavior 'X' not found; available: …`**
Your `pyoneer_behaviors` list names a token the registry does not hold. The
message prints the whole legal vocabulary. It raises rather than skipping, by
law 8.

**`PyoneerAssetMissingError: spawn type 'X' not found; available: GamePlayer`**
An object carries a `type` that is not in `SPAWN_REGISTRY`. See
[`PLACEABLE.md`](PLACEABLE.md), not `scripts/core/depth.py`'s
`OBJECT_CONVERTER`, which names four types that exist nowhere.

**`PyoneerConfigError: behaviors 'topdown_move' and 'platformer_move' declare
that they conflict, and pyoneer_behaviors lists both`** — one body model per
entity.

**`PyoneerConfigError: behavior token 'X' appears twice in pyoneer_behaviors`**
— run order comes from each spec's `order`, not from your list, so a repeat is
always a mistake.

**`PyoneerConfigError: behavior 'interact_action' on GamePlayer polls the verb
'action', which config/inputs.json does not bind.`** It raises at **attach**
on purpose; the alternative is a `KeyError` inside `core_frame_update` that
kills the frame for every sibling (law 10). Add the binding in the same change.

**`PyoneerAssetMissingError: event script 'X' not found; available: …`** — see
[the action-key walk](#pressed-the-action-key-and-no-script-ran--no-sound)
below.

**`PyoneerAssetMissingError: tileset image … not found`** — the map names a
sheet in NEITHER art root. `data/graphics/` wins whenever it holds the file,
`data/art/` answers otherwise, and a path missing from both raises naming what
was declared. If `data/art/` is empty, run
`.venv/Scripts/python.exe -m tools.art`. See [`ASSETS.md`](ASSETS.md).

---

## "Nothing happens when I press a key"

Walk this in order. It is the order the frame actually runs.

1. **Is `player_input` in the list?** It is the entire marker for "a human
   drives this"; a body with `topdown_move` and no `player_input` is a
   correct, inert body. For the one body the game adopts as the player the
   boot warns (`#TAG:MainGame.warn_undriven_player`), naming the `<object>`
   and the missing token. Every other body stays silent, so silence means the
   token is on the body the camera followed, not necessarily on yours.
2. **Is a key bound to the verb?** `config/inputs.json` is the whole binding
   surface; rebinding there changes the game and nothing else.
3. **Is an input manager attached?** `player_input` needs
   `entity.action_manager`. A `None` manager is legal and produces no intent,
   which is how a scripted body coexists with a driven one.
4. **Is the body steerable?** The agency fields on the shared body state gate
   the *producer*, not the world. `steerable` false stops walking;
   `enabled_inputs` false also silences every action behavior.
5. **Is a window eating the keys?**
   `#TAG:InputActionManager.begin_text_capture` makes `pressed`, `released`
   **and** `held` return False for **every** verb. A cutscene that wants a
   *continue* press must clear `steerable`, never call text capture.

---

## "Pressed the action key and no script ran" / "no sound"

The shipped game's action key runs an event script:
`.venv/Scripts/python.exe main.py`, press `e`. The chain has five links, and
`.venv/Scripts/python.exe tools/check_script_runtime.py` drives the real
keyboard through all of them. Walk them in order.

**1. The verb.** `grep -n '"action"' config/inputs.json` — shipped as
`keyboard:e` and `gamepad:b`. Unbound **raises** at attach (string above).
A press is also silently dropped when the body's `enabled_inputs` is false,
when it has no `action_manager`, or while text capture is on.

**2. The two tokens.** `interact_action` records the press and `action_relay`
CALLS the scene's router with it (`#TAG:interact_action`,
`#TAG:action_relay`). A map body naming a script without both **warns** at
boot and the press starts nothing:

> `PyoneerContentWarning: the map's <object id=1> on layer 'entity' names the
> event script 'starter_greeting' in pyoneer_script, and its pyoneer_behaviors
> list is missing 'action_relay' -- so nothing will ever start it.`

A body built through `SceneManager.spawn` gets no such warning, by design.

**3. The property and the document.** `pyoneer_script` on the tmx object is
read by `#TAG:script_of`, the one reader both spawn routes call, against
`data/project/scripts/*.json` as loaded by `#TAG:load_scripts` before the map
bind.

- empty value — names no script, **silent**, by design;
- an id with no document — **raises** at boot:
  `PyoneerAssetMissingError: event script 'starter_greting' not found;
  available: starter_greeting` via
  `asked_by="tmx object id=1 on layer 'entity' via pyoneer_script"`;
- a malformed document — **raises** at boot naming the node, e.g.
  `script op 'play_sond' not found; available: ask, call, hold, …`;
- the object has no `type` — nothing spawns (`#TAG:untyped_object_spawns_nothing`),
  so nothing is joined, **silent**.

Check with `grep -rn pyoneer_script data/maps/` and
`ls data/project/scripts/`.

**4. The flow slot.** `#TAG:MainGame.run_object_script` builds a `ScriptRun`
into `SceneManager.flow`. `SceneManager` holds ONE flow, and every outcome
here is **silent**:

- our own run still running — the press **advances** it rather than starting
  another;
- a different flow still running (a narrative kit's cutscene) — the press
  reaches nothing, and the occupant keeps the slot;
- a finished flow — not an occupant: `#TAG:SceneManager.post_update` clears it,
  and the next press starts a fresh run over the same variable store;
- no page whose `when` passes — `begin` returns False and nothing starts.

**5. The ops.** `play_sound` and `play_music` go through
`#TAG:scripts/core/audio.py` (the two roots are in [`ASSETS.md`](ASSETS.md)).

- file in neither root — **raises** the frame the node runs, with or without
  a card: `PyoneerAssetMissingError: sound 'sfx/chme.wav' not found;
  available: music/pleasant_moments.ogg, sfx/chime.wav` with
  `hint='looked at data/sound/sfx/chme.wav then data/audio/sfx/chme.wav; …'`;
- no sound card — **warns once**, then every play returns False and the
  script carries on: `PyoneerWarning: audio is unavailable and the game will
  run silently: pygame.mixer.init(…) said …`. Reproduce with
  `SDL_AUDIODRIVER=nosuchdriver`;
- manager never prepared (a game class that skipped `main.py`'s
  `load_config`) — **raises**: `AudioManager was asked to play the sound
  'sfx/chime.wav' and nothing has prepared it.`;
- `ask` — **raises**: `` `ask` needs a host that reports a CHOICE, and this
  engine has none ``. Its status is `needs-host` in
  [`EVENTS.md`](EVENTS.md), which is where every op's measured status lives.

---

## "It moves, but not the way I asked"

| symptom | cause | address |
|---|---|---|
| animates, never translates | unknown direction string: `move_direction` has no `else`, while animation `start()` raises for the same typo | `#TAG:GameEntity.move_direction` |
| walks through walls | an unknown direction is also passed through `allowed_move` unclamped | `#TAG:GameEntity.allowed_move` |
| speed ~16.7× off | `event.data["delta"]` is milliseconds ÷ 60, not seconds (law 9) | `#TAG:delta_is_ms_over_60` |
| `transform=` ignored | discarded in the base constructor; use `moveto()` | `#TAG:GameEntitySimple.__init__` |

---

## "It falls forever" / "it will not land"

A side-on body's support comes from the collision field, so all three of these
look the same:

1. **The map declares no collision at all.** No companion layer and no tile
   masks bake `None`, which means **ungated**: every step is allowed and
   nothing is ever ground. The shipped `data/maps/starter.tmx` is NOT this
   case: its `Floor` layer declares `pyoneer_passability="FloorCollision"`,
   and that companion holds 340 cells of gid 2320, the `collision` tileset's
   `firstgid` 2305 plus `BLOCK_ALL` (15). Count any map's with
   `.venv/Scripts/python.exe -c "from collections import Counter; from scripts.loaders.map_document import MapDocument as M; print(Counter(g for g in M.load('data/maps/starter.tmx').tile_layer('FloorCollision').gids() if g))"`.
2. **The mask says open where you painted.** Erasing writes gid 0, which in a
   companion means `NO_DATA` — "nobody said anything here" — deliberately not
   the same claim as "open".
3. **The body is outside the field.** An anchor outside the map is **not
   gated at all** (`#TAG:allowed_distance`): the border stops a body *leaving*
   the field, never one outside it, so a body spawned below or beside the map
   falls or walks forever.

---

## "I painted collision and nothing blocks" / "this wall blocks and I never painted it"

Passability resolves in three levels and the first that is not `NO_DATA` wins,
so both surprises come from asking the wrong level.
[`TILESETS.md`](TILESETS.md) is how to author each one; this is how to find out
which one answered.

1. **The tile already had an opinion.** A tileset can carry a `.blitmask`
   naming a mask per tile (`#TAG:tileset_defaults`), so stamping the tile
   authors the collision. The map display draws each placed tile's own mask
   dimmed over the art, and the palette marks the tiles that carry one.
2. **A painted cell OVERRIDES that default rather than adding to it.**
   `PASS_ALL` over a `BLOCK_ALL` tile is open. To get the tile's answer back,
   clear the cell with the dotted no-opinion chip (`#TAG:BRUSH_DOMAIN`), which
   writes gid 0; the `PASS_ALL` swatch asserts *open* instead.
3. **The layer you painted on never reaches the field.** A layer that moves
   under the camera is excluded by `#TAG:world_coordinate_fault`, so masks on a
   parallax layer are stored and dead. The hierarchy badge and a load-time
   warning say so; nothing else does.
4. **There is no companion and no tile mask at all**, which bakes `None` —
   *ungated*, not *open*. See ["It falls forever"](#it-falls-forever--it-will-not-land).

The companion layer has no row in the hierarchy, deliberately: select the
**art** layer, and the badge after its depth is its live mask count.

---

## "My layer does not draw" / "my tiles vanished"

`#TAG:resolve_layer_depth` returns `None` for a name it does not know, and an
unmapped tile layer is silently not drawn: `resolve_layer_depth("Trees")` is
`None`. `resolve_layer_depth("Paralax")` is `1`, because `#TAG:LAYER_NAME_ALIASES`
carries the one-L spelling for someone else's map that may spell it that way —
`data/maps/starter.tmx` does not (`grep -c Paralax data/maps/starter.tmx` is
0), but both `editor/genres/*/genre.json` packs still declare a `Paralax`
layer. Legal layer names are generated into [`PLACEABLE.md`](PLACEABLE.md).

---

## "The animation is wrong / it raises `idle_none`"

- A sheet with no `idle_down` row raises inside the entity constructor, before
  any behavior attaches (`#TAG:GameAnimationHandler.__init__`).
- `#TAG:GameAnimationHandler.start` raises `PyoneerAssetMissingError` for an
  unknown sequence and prints every sequence it has. The name is built from a
  format string and the facing token, so `idle_{facing}` with an illegal
  facing is the usual cause.
- Sequence naming is **parameters, not code** — `walk_format`, `idle_format`
  and `initial_sequence` are declared, so a two-row sheet is a parameter
  change.

---

## "I changed something and the suite went red"

| verdict | means | do |
|---|---|---|
| `DRIFT smoke` | the rendered frame moved | name each field old → new and why before re-baselining (law 11) |
| `PASS smoke` | no drift **with no input injected** | it cannot see walking; `demos.patrol` walks a body deterministically |
| `HANG` | a check blocked, almost always on a modal dialog | law 13 |
| a check asserting what a MAP contains | wrong even when green | write a fixture (law 4) |

---

## When the answer is not here

Check [`BEHAVIORS.md`](BEHAVIORS.md)'s integration table and
[`EVENTS.md`](EVENTS.md)'s runtime and reachability columns before believing
any prose, including this file's: both are produced by running the code. If
the thing you want appears finished but inert,
[`history/ORPHANS.md`](history/ORPHANS.md) is the dated archive of
finished-and-unattached code — re-measure anything it says before acting.

Every address here is a `#TAG:`, so `grep -rn "#TAG:GameEntity.allowed_move"`
returns the definition, this citation and the code map's entry in one command.
