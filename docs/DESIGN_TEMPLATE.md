<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; tools/check_prototype.py resolves every field of both forms against the live registries, boots the worked example, and checks the loop section's commands and files on every run. -->

# Design template — a small game, in one screen, executable

Fill the form. Every field resolves to something that **already exists** — a
genre pack id, a registered behavior token, a declared parameter key, a table
column, a bound input verb, a step field on the sequencer — so a filled form is
an instruction and not a wish list. `tools/check_prototype.py` resolves all of
them on every run, and boots the worked example at the bottom.

Five minutes is the budget. If a row takes longer than that, the row is
describing something the engine cannot do yet, and **that** is the finding.

This file is also where the loop lives: fill the form, build the demo, prove
it. See [the loop](#the-loop-design---build---prove) at the end.

## The blank form

One row per line. The first word is the row kind; nothing is indented; a `#`
line is a comment. Angle brackets mark a hole to fill.

```design
name    <demo_name>
genre   <genre_pack_id>
map     <width> x <height> tiles of <tile_px>

layer   <LayerName>         tile
layer   <object_layer>      object

object  <id>  <SpawnType>   <token,token,token>
object  <id>  <SpawnType>   <token,token>

param   <object_id>  <param_key> = <value>

actor   <object_id>  <column>=<value>  <column>=<value>

verb    <verb_name>   <what the player does with it>

flow    <flow_name>   <axis>=<true|false>
step    <step_name>   hold_ms=<milliseconds>
route   <action_token>  <payload>  -> <Handler.method>

prove   <what the check asserts> AND <the half that kills the false pass>
```

## What each row must resolve to, and where the list lives

| row | field | must be | the authority |
|---|---|---|---|
| `name` | the demo name | a key in `demos.mapgen`'s map sources | [`DEMOS.md`](DEMOS.md) |
| `genre` | pack id | a directory under `editor/genres/` | `editor/genres/<id>/genre.json` |
| `map` | three integers | width, height in tiles, and pixels per tile | your call |
| `layer` | name + `tile`/`object` | a layer the genre pack declares — and a **tile** layer must resolve to a depth or it is not drawn | [`PLACEABLE.md`](PLACEABLE.md) |
| `object` | spawn type | a key in `SPAWN_REGISTRY`. One type is spawnable today | [`PLACEABLE.md`](PLACEABLE.md) |
| `object` | token list | every token registered; no duplicates; no two that declare a conflict | [`BEHAVIORS.md`](BEHAVIORS.md) |
| `param` | key | a parameter one of that object's tokens declares | [`BEHAVIORS.md`](BEHAVIORS.md) |
| `actor` | column | a column the genre pack's `actors` table declares | `editor/genres/<id>/genre.json` |
| `verb` | verb name | bound in `config/inputs.json` — polling an unbound one raises | [`PLACEABLE.md`](PLACEABLE.md) |
| `flow` | axis | a keyword `SceneFlow` takes: `steerable`, `enabled_inputs`, `simulated` | `#TAG:SceneFlow.__init__` |
| `step` | field | a field on the step record: `name`, `window`, `hold_ms`, `payload` | `#TAG:FlowStep` |
| `route` | token | a registered token that FIRES an action | [`BEHAVIORS.md`](BEHAVIORS.md) |
| `route` | handler | a method the code map knows | [`MAP.md`](MAP.md) |
| `prove` | a sentence | must name **both halves** — the word `AND` is required | law 5 in [`../CLAUDE.md`](../CLAUDE.md) |

Four rows are optional and the rest are not: `param`, `actor`, `flow`/`step`
and `route` are for games that need parameters, table data or narrative. A
top-down walking prototype is `name`, `genre`, `map`, two `layer`s, one
`object` and one `prove`.

An `actor` row is read at runtime: an object carrying `pyoneer_actor` gets
that row's columns under its own `pyoneer_param_*` and over each declared
default (`#TAG:actor_row`), and a `pyoneer_actor` naming an absent row raises.

## Three things the form makes you say out loud

1. **Which object is the player is a token, not a flag.** `player_input` is the
   whole marker. An object without it is inert *by construction*, which is why
   the form has no `player:` field and never will.
2. **A `hold_ms` is milliseconds.** `event.data["delta"]` is milliseconds ÷ 60,
   and a genre table's per-second figure used raw is ~16.7× wrong in a way that
   still looks like it works. The sequencer converts; you write milliseconds.
3. **`prove` is a row, not an afterthought.** The dominant defect shape in this
   repository is one half of an invariant — a gate proved to let something
   through and never proved to stop it. A `prove` row with no `AND` in it is
   refused by the check, which is the cheapest possible enforcement of law 5.

## The worked example — `demos/story.py`, filled in before it was built

This is the form that produced the story demo. It is not a paraphrase of it:
`tools/check_prototype.py` parses this block, resolves every field against the
live registries, **and then boots the demo and compares** — the object ids, the
resolved behavior tokens, the map size, the step names and their holds, and the
route. A field changed here without changing the game turns the check red, and
so does the reverse.

```design
name    demo_story
genre   topdown_rpg
map     30 x 20 tiles of 32

layer   Floor      tile
layer   entity     object

object  hero    GamePlayer  player_input,topdown_move,animation_drive,interact_action,action_relay
object  keeper  GamePlayer  topdown_move,animation_drive

param   hero    payload = keeper

actor   hero    display_name=Wren  hp=10  speed=20

verb    action  advance the conversation
verb    up      walk
verb    down    walk
verb    left    walk
verb    right   walk

flow    opening   steerable=false
step    title     hold_ms=900
step    greet     hold_ms=0
step    close     hold_ms=0
route   interact_action  keeper  -> SceneFlow.on_action

prove   the cutscene refuses movement AND still advances on the action verb
prove   a timed step advances itself AND an untimed one waits
prove   steering comes back when the flow ends AND comes back to the value each body HAD
prove   the routed payload reaches the flow AND a different payload reaches nothing
```

Read that against [`DEMOS.md`](DEMOS.md)'s story section for what each `prove`
row cost to make true.

## Filling it in for a genre that is not top-down

Only two rows move. A side-on game swaps `topdown_move` for `platformer_move`
in the `object` row, and gains `param` rows for `gravity`, `jump_velocity` and
`jump_verb`. The class is the same, the spawn type is the same, the object
layer is the same, the depth is the same. That is the whole claim the demos
exist to make, and the form is shaped so that making it is easier than not.

## What the form cannot say yet

It has no row for an **event script** (`pyoneer_script` on an object, a JSON
document under `data/project/scripts/`, [`EVENTS.md`](EVENTS.md)) and none for
**audio** (`play_sound`, `play_music`). Both are live in the shipped game, and
the worked example predates them: its dialogue is a `flow` over Python beats.
A row kind needs a resolver in the check before it belongs in the form, so
until one lands, write a scripted game's script id and its sounds as a
comment line and resolve them by hand against `EVENTS.md`.

## The loop: design -> build -> prove

    DESIGN   fill the form above                     no code is written
    BUILD    a map source, plus demos/<name>.py      the game runs
    PROVE    a check that boots it and presses keys  the game stays running

**DESIGN.** Fill the blank form; the vocabulary is in
[`BEHAVIORS.md`](BEHAVIORS.md) and [`PLACEABLE.md`](PLACEABLE.md). It catches,
before any file exists, a token that would raise at load, a tile layer that
would not be drawn, and a verb a behavior would poll unbound.

**BUILD.** Two files, usually only one of them new. In `demos/mapgen.py`, copy
the nearest `_*_source` function, add it to `SOURCES`, and put every position,
object id and geometry number in a named module constant: the check derives
its expectations from those constants, so a number typed twice is a check
pinning map content. Then a class in `demos/<name>.py`:

    from demos.runtime import DemoGame, run

    class MyDemo(DemoGame):
        MAP_NAME = "demo_mine"

    if __name__ == "__main__":
        sys.exit(run(MyDemo))

A narrative demo derives `StoryGame` from `demos/narrative.py` and adds a
`SCRIPT`. If your class needs a method, stop: it wanted a hook on `DemoGame` or
`MainGame`. A genre pack's default behavior list reaches an object only through
the editor, where `map.object.add` materialises it
(`#TAG:behaviors_materialised_at_add`); `demos/mapgen.py` writes maps from
Python, so spell every list out.

**PROVE.** A section in a check that boots the demo headless, drives it with
injected input (smoke presses nothing), and asserts both halves of every
`prove` row, usually with a negative-control boot. Put the check in
`tools/check_all.py`'s roster in the same change. Every check generates its
own maps into a temp directory, so `demos/maps/*.tmx` stays yours to repaint.

    .venv/Scripts/python.exe -m demos.<name> --frames 60   # BUILD: it runs
    .venv/Scripts/python.exe tools/gen_map.py --write      # BUILD: map the new module
    .venv/Scripts/python.exe tools/check_<name>.py         # PROVE: both halves
    .venv/Scripts/python.exe tools/check_docs.py --write   # PROVE: CHECKS.md gains the row
