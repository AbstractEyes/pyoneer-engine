<!-- pyoneer-doc: L0 -->
<!-- pyoneer-stamp: hand-written; every claim below re-measured against 5dd012d on 2026-08-16 -->

# Pyoneer — read this first

This is the boot document. It is small on purpose: reading the whole thing is
never a bad decision. It carries nothing that a generated document already
carries — it exists to make the **second** file you open the right one.

## What this engine is, in three sentences

1. **Rendering is a sorted queue, not a surface stack.** Nothing draws
   directly; every drawable pushes a `BlitToken` into a global pool keyed by
   depth and priority, and the renderer flattens the frame into one
   `surface.blits()`. Layers are a sort key, so a frame is *data* before it is
   pixels — which is why the harness compares token histograms, not
   screenshots.
2. **An entity is ONE class carrying a list.** `pyoneer_behaviors` on the tmx
   object is read at spawn and its behaviors are attached before bind. Genre
   lives in map data, not in a subclass; a top-down game, a platformer and a
   scripted patrol are the same class carrying different lists. A behavior is
   **called**, never dispatched to.
3. **Every editor change is a `Command` that returns its own inverse.** Undo is
   a readable list of verbs, not a pile of snapshots, and an AI's edit and a
   human's edit are the same kind of thing.

## The constants — literal strings, not descriptions

```
.venv/Scripts/python.exe            the interpreter. Never bare `python`.
tools/check_all.py                  the suite. One command, one exit code.
tools/smoke.py --frames 60          the frame-drift instrument.

pyoneer_                            EVERY tmx custom property starts with this
pyoneer_behaviors                   comma-separated token list, ON THE OBJECT
pyoneer_param_<key>                 one behavior parameter, on the same object
pyoneer_actor                       actors-table row id (nothing reads it yet)
```

A minimal driven top-down body declares
`pyoneer_behaviors="player_input,topdown_move,animation_drive"` on its tmx
object — and `tools/check_docs.py` checks that string against the live registry
on every run. For the **complete** token list, each token's run order, and —
critically — whether a token is actually wired to anything, read
[`docs/BEHAVIORS.md`](docs/BEHAVIORS.md), which is generated from the registry.
That table is deliberately not copied here: a generated table pasted into the
boot document is the boot document rotting, and `tools/check_docs.py` refuses
the paste.

Input verbs bound in `config/inputs.json`: `left right up down action attack
sprint jump pause`. Polling a verb that is not in that file **raises**.

The only spawnable tmx object `type` is **`GamePlayer`**. See
[`docs/PLACEABLE.md`](docs/PLACEABLE.md) — `scripts/core/depth.py`'s
`OBJECT_CONVERTER` advertises five more and four of them exist nowhere.

## The query playbook

Literal question shapes, one destination each. Route by **question type**, not
by topic: "how does collision work" and "why doesn't my body land" are the same
topic, different layers, and different files.

| you are asking | go to |
|---|---|
| "what does this behavior do" · "how do I make it move" · "add a behavior" | [`docs/BEHAVIORS.md`](docs/BEHAVIORS.md) — GENERATED; trust its **measured integration table** over any prose, including its own preamble |
| "my entity does not move" · "nothing happens when I press a key" · "it falls forever" · "it raises at load" | [`docs/DIAGNOSE.md`](docs/DIAGNOSE.md) |
| "what can I place on an object layer" · "what goes in `type=`" · "why does my layer not draw" · "what key is bound to what" | [`docs/PLACEABLE.md`](docs/PLACEABLE.md) — GENERATED |
| "make me a platformer" · "make me a top-down RPG" | `editor/genres/<id>/RULES.md`, then `docs/BEHAVIORS.md` |
| "how do I change project data from a script" · "what verbs exist" | [`docs/COMMANDS.md`](docs/COMMANDS.md) — GENERATED |
| "show me a game that works" · "start a new demo" | [`docs/DEMOS.md`](docs/DEMOS.md) |
| "how do I run the checks" · "I wrote a check" | [`docs/CHECKS.md`](docs/CHECKS.md) — GENERATED — plus law 6 below |
| "how does the editor think" · "why is every change a command" | [`docs/PLAN_EDITOR.md`](docs/PLAN_EDITOR.md) |
| "where is the art" · "why does it fail on a fresh clone" | [`docs/ASSETS.md`](docs/ASSETS.md) |
| "is this already written but unwired" | [`docs/ORPHANS.md`](docs/ORPHANS.md) — dated archive |
| "what should I do next" | [`docs/NEXT.md`](docs/NEXT.md) — re-measure before trusting |
| "the frame changed" · "smoke drifted" | `tools/smoke.py --frames 60`, then law 11 |
| "what did the first review find" · "why was it built this way" | `docs/ENGINE_REVIEW.md`, `docs/IMPROVEMENT_PLAN.md`, `docs/PLAN_EVENT_SYSTEM.md`, `docs/PLAN_MAPS.md`, `docs/PLAN_SINGLETONS.md` — dated archives, each banner-gated. **Never navigate by them.** |

## Generated vs written

| file | produced by | authoritative for |
|---|---|---|
| `docs/BEHAVIORS.md` | `tools/check_behavior_docs.py --write` | the behavior table and its **measured** integration status |
| `docs/PLACEABLE.md` | `tools/check_docs.py --write` | spawnable types, layer→depth, input verbs |
| `docs/CHECKS.md` | `tools/check_docs.py --write` | the check roster |
| `docs/COMMANDS.md` | `tools/check_docs.py --write` | the editor's verb vocabulary |
| everything else in `docs/` | hand-written, stamped | its own question shape only |

A generated file is regenerated and compared byte-for-byte by its check, so it
cannot drift. **A generated file's hand-written preamble still can** — see
KNOWN GAPS.

## The hard laws — each one states what it cost

A law with no cost attached gets ignored. Every cost below is in the tree.

1. **Every tmx custom property starts `pyoneer_`.** Cost: pytmx **raises and
   makes the whole map unloadable** if a property shadows one of its own
   attribute names (`opacity`, `visible`, `offsetx`, …). Import `PREFIX` from
   `scripts/core/layer_profile.py`; never retype it.
2. **`editor/` may import `scripts/`. `scripts/` may NEVER import `editor/`.**
   Cost: `python main.py` must work on a clone with `editor/` deleted.
   *Corollary, paid in `29fbfc1`:* shared logic lives in `scripts/` and the
   editor re-exports it. A second implementation of the collision model shipped
   with 37 shared symbols, 35 textually identical; **425 duplicate lines** were
   deleted, and the "differential" guard meant to catch it compared 11 of 37
   symbols and missed the gate itself.
3. **Do not restructure the event system.** Add types, listeners and components
   freely; do not touch dispatch, consumption or the listener registries. Cost:
   consumption is **not type-gated** — one stray `handle()` in a fan-out
   silences every sibling for the rest of the frame. That is *why* a behavior is
   called and never dispatched to.
4. **A check asserts what the CODE does, never what the MAP contains.** Cost:
   red suites, and commit `333a77a` exists solely to undo two checks that pinned
   `data/maps/test.tmx` content. Write your own fixture.
5. **An assertion that cannot fail is not an assertion.** The dominant failure
   shape by far is **one half of an invariant** — a gate proved to let something
   through and never proved to stop it. Cost: `[UNVERIFIED]` 26 such assertions
   reported across review passes; `README.md` describes five. Break the code your
   check covers, confirm it goes red, and report the mutation and the result.
6. **A new check goes into `tools/check_all.py`'s roster in the SAME change.**
   Cost: three checks have been written, passed, and never run by the suite —
   one of them with 114 assertions.
7. **Raise; never fall back to a plausible default.** Cost: 39 authored tiles
   silently dropped for months because the renderer looked up `Parallax` and the
   map said `Paralax`. This is why `BehaviorParam.coerce` raises where
   `Capability.coerce` falls back, and why they are deliberately not one class.
8. **A behavior token, a table row id and a column name are FILE FORMAT
   strings** — stable once referenced, never renamed. Cost: a renamed token
   silently disarms every object carrying it *and looks like the behavior
   working*. `resolve()` raises on an unknown token rather than skipping it, for
   exactly this reason.
9. **`event.data["delta"]` is milliseconds ÷ 60, not seconds.** Cost: a genre
   table's pixels-per-second number used raw is ~16.7× wrong **in a way that
   still looks like it works**.
10. **Adding a behavior that polls a verb and adding its binding are ONE
    change.** Cost: `InputActionManager.held()` is an unguarded dict index, so an
    unbound verb raises `KeyError` *inside* `core_frame_update`, killing the
    frame for every sibling in that scene bucket. The behaviors raise at
    **attach** instead — deliberately the opposite timing. Know which you are
    writing.
11. **Do not touch `data/maps/test.tmx` or `tools/baseline.json`; name a smoke
    drift field-by-field or do not bless it.** Cost: measured, `test.tmx` mixes
    tab-indented and space-indented blocks and is CRLF throughout, so no
    pretty-printer reproduces it — only whitespace-preserving parsing does,
    which is why `MapDocument` exists and why a hand-edit destroys the
    byte-exactness contract. (Those line numbers are not quoted here on
    purpose: law 4 applies to documents too.) And **smoke injects no
    input**, so "no drift" never means "nothing changed": it cannot see anything
    that only happens while walking.
12. **In a Qt panel, never `setParent(None)` to clear a layout, and never free
    the old body synchronously.** Cost, both measured: `setParent(None)` promotes
    a widget to a **top-level window** — ~20 orphan windows flashed on every
    Ctrl+Z and leaked (59 top-level widgets at rest → 85 after one undo → still
    85); and `setWidget()` alone frees the old body while a field's own `toggled`
    signal is still on the stack, a hard **STATUS_HEAP_CORRUPTION (0xC0000374)**
    crash of the whole editor. The one correct sequence is `takeWidget()` →
    `setParent(self)` → `hide()` → `deleteLater()` → `setWidget(new)`.
13. **A check must never block on a modal dialog.** Cost: `check_collision_mount`
    hung on `QMessageBox.question` for **40+ minutes with zero output**,
    indistinguishable from a slow machine. `check_all.py` now carries a 600s
    per-check timeout and a `HANG` verdict.

## Known gaps — fill on sight

Things that are *missing*, not broken. Each is a real hole someone will hit.

- **`README.md` is the front door and three of its headline gap claims are
  false at HEAD.** It says the engine cannot read a collision mask
  (`README.md:290`, `:385`), that placing an object does not spawn an entity
  (`:387`), and that `.blitmap` has no reader (`:393`); all three shipped. Its
  check counts (`:308`, `:333`, `:35`) name 29 against a roster that
  [`docs/CHECKS.md`](docs/CHECKS.md) generates and is now much larger. Its
  "Known rough edges" section must become generated. **This file's own
  navigation deliberately does not route through `README.md`.**
- **`docs/BEHAVIORS.md`'s preamble is hand-written prose inside the
  generator**, so it can lie while the file still matches its generator.
  It currently shows the token `tile_collision`, which is not registered and
  makes a map raise at load. Same string in `scripts/game/behavior/base.py:102`
  and `scripts/game/behavior/registry.py:145`, `:366`.
- **No `needs_art` flag on the check roster.** `docs/ASSETS.md` names seven
  art-dependent checks measured against an older, smaller roster; nothing
  re-measures it.
- **No genre-pack default behavior list.** Four documents name the slot
  `layers[].object_classes[].behaviors`; `GenreLayer` has no such field and
  only a check parses it.
- **`GameEntity.__init__` accepts a `transform` keyword and discards it**
  (`scripts/game/entity/game_entity.py:34`). Pass position via `moveto`.
- **`allowed_move` swallows an unrecognised direction**
  (`scripts/game/entity/game_entity.py:241`): a bad bit returns the wanted
  vector unclamped through cells that block everything. Harmless only while
  `move_direction` is its sole caller.
- **`GameAnimationHandler` plays `idle_down` unconditionally at construction**
  (`scripts/game/entity/game_animation.py:128`), before any behavior attaches —
  the first wall a side-on-only or portrait-only sheet hits.
- **`GameEventType.POST_DISPOSE` is defined and never dispatched**
  (`scripts/core/event_types.py:39`). `CUSTOM_EVENT`, `REBUILD`,
  `PARENT_RESIZED` and `USE` are likewise definition-only — `USE` is emitted
  once, from a `TextBox` pressing Enter, and bound by nobody. **Do not add an
  event member before a listener exists**; `USE` is the standing proof of what
  that costs.
- **No engine-side reader for `data/project/tables/`.** The behaviour-parameter
  chain's step 2 (the actors row) can therefore never fire, and no `hp` column
  reaches the runtime.
- **Landed while this file was written, so verify before trusting a doc that
  says otherwise:** an action router assigned as `entity.action_sink`
  (`scripts/core/scene/scene_manager.py:118`), `LayerRenderer.unbind`
  (`scripts/core/renderer.py:855`), and an editor behavior panel. Three of this
  list's entries died in one afternoon. **Re-measure this section; do not cite
  it.**

## TODO-VERIFY

Any claim in this file that was **not** confirmed by running something this
pass is prefixed `[UNVERIFIED]`. An unmarked claim is a claim someone executed.
There is exactly one:

- `[UNVERIFIED]` the aggregate "26 vacuous assertions found across review
  passes" in law 5 is carried from review reports, not re-counted here. The
  five in `README.md` are described there in detail.

## Anchors — machine-checked, do not edit by hand

`tools/check_docs.py` asserts that each file's numbered line still contains the
quoted text. A failure means the doc rotted or the code moved; fix the line
number, do not delete the anchor.

```anchors
scripts/core/layer_profile.py:24 :: PREFIX = "pyoneer_"
scripts/core/depth.py:42 :: "Paralax": "Parallax"
scripts/core/input.py:147 :: return self.actions[action_name].held
scripts/game/behavior/base.py:50 :: milliseconds divided by 60
scripts/game/entity/game_entity.py:34 :: self.transform: Transform = Transform(
scripts/game/entity/game_entity.py:241 :: if field is None or bit is None
scripts/game/entity/game_animation.py:128 :: self.start(self.DEFAULT_ANIMATION)
scripts/core/spawn.py:61 :: SPAWN_REGISTRY: dict
scripts/core/component.py:943 :: def mark_event_handled
scripts/core/collision_runtime.py:170 :: BLOCK_ALL = BLOCK_DOWN
editor/ui/fields.py:119 :: old = self.takeWidget()
```
