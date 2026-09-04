<!-- pyoneer-doc: L0 -->
<!-- pyoneer-stamp: hand-written; the engine claims were re-measured against d8c303f on 2026-08-16, the `.blitmap` collision gap on 2026-08-18 by the greps it names. The tileset rows in `The constants`, the query playbook's TILESETS row, the fourth sighting in ACTIVE WARNINGS, the two new KNOWN GAPS bullets and the six new anchors were measured against the working tree on 2026-08-29. The first two KNOWN GAPS bullets were re-measured on 2026-09-03: README's three false gap claims and its stale check count are gone, so that bullet now names only the structural half it still owns, and the BEHAVIORS preamble bullet gained the second lie found in the same preamble that day. Also on 2026-09-03, at the finalize of the repair pass: the `map.tileset.grow`/`.rename` gap is struck through with the grep that closed it, and the fourth ACTIVE WARNING sighting was put into the past tense without being deleted -->

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

## Grep before guessing

You do not remember this repository. The files do. Before you write a name,
find out whether it already exists — and find out with one command, not with a
file read:

```
grep -rnE "#TAG:GameEntity(\s|$)"          the class alone -- 2 hits
grep -rn  "#TAG:GameEntity.allowed_move"   one method, wherever it now lives
grep -rn  "#TAG:topdown_move"              a behavior token's declaration, not its 40 mentions
grep -rn  "#TAG:map.tile.set"              an editor verb's declaration, same
grep -rn  "pyoneer_param_"                 a file-format string, everywhere it is spelled
```

**BOUND THE TAG OR IT IS NOT A LOOKUP.** A tag is a PREFIX of every tag under
it, so the bare form matches the whole subtree: measured, `#TAG:GameEntity`
returns **43** lines and `#TAG:GameEntity(\s|$)` returns **2**. Use the bare
form deliberately, when you want the subtree ("everything about this class");
use the bounded form when you want the declaration. A dotted tag
(`#TAG:GameEntity.allowed_move`) is a leaf and needs no bounding. Behavior
tokens and verbs are leaves too -- `#TAG:topdown_move` is 4 lines.

The third and fourth are the ones worth internalising. A behavior token and a
verb name are *strings*, spelled in specs, examples, docstrings, generated
tables and `.tmx` files, so grepping the bare name returns dozens of lines and
none of them is the declaration. The `#TAG:` form returns exactly one line in
the source — the line that defines the thing — plus the code map's entry for
it. Every registered behavior token and every editor verb carries one.

A `#TAG:` is this repository's stable address for a symbol. It replaced
line-number addressing for a measured reason: a five-line docstring edit once
turned the documentation check red because a quoted line had *moved down five
rows*. The anchor was correct, the document was current, and nothing about the
documented fact had changed. **A line number is not an address. A tag is.**

Nothing at all is written by hand in the map — [`tools/gen_map.py`](tools/gen_map.py)
walks the AST and emits it — so a tag cannot name something that does not
exist, and the tag for a symbol you just renamed disappears in the same run.

### The tag vocabulary — four shapes, one rule

**The rule: `#TAG:<value>`, no spaces, on the SAME LINE as the entry it
describes.** A tag on the line above is a tag `grep` hands you without the
thing you were looking for. (Angle brackets are the escape for a placeholder:
`tools/check_docs.py` asserts every *real* tag a document writes resolves, and
`#TAG:<value>` is a shape rather than a claim.)

| shape | value | example |
|---|---|---|
| a class | its bare name | `#TAG:GameEntity` |
| a function, a method, a module constant | its bare name; a method is `Owner.name` | `#TAG:resolve_layer_depth`, `#TAG:GameEntity.allowed_move` |
| a module | its repo-relative path | `#TAG:scripts/core/depth.py` |
| a topic with no Python name | `lower_snake_case`, chosen by hand, written as a trailing comment on the line it describes | `#TAG:delta_is_ms_over_60`, `#TAG:qt_takewidget_sequence` |
| a behavior token or an editor verb | the token or verb **exactly as authored**, because that string is the file format | `#TAG:topdown_move`, `#TAG:map.object.property.set` |

Two qualifications, and no more. **Bare by default**, because someone looking up
`GameEntity` knows the class name and does *not* yet know the module, so a
scheme demanding `game_entity.GameEntity` would demand the answer as the
question. **Qualified only on collision** — when two things in the tree share a
name the generator prefixes both with the module stem
(`#TAG:layer_profile.PREFIX`), and a property's setter takes `.setter`
(`#TAG:GameComponent.depth.setter`), because a bare `update` is claimed by 18
classes here and a tag returning 18 lines is not an address.

You do not write tags for symbols: the generator emits them. Write one by hand
**only** to name a line that is not a definition — a sentence inside a
docstring, a token inside a spec literal, a step inside a sequence — as a
trailing comment on that line. `tools/check_docs.py` refuses a hand-placed tag
that sits outside the symbol it names, and refuses two tags with the same value
anywhere.

Three families are already sown, and adding to a family is part of the change
that adds the thing: **every registered behavior token** (on its `name=` line
in the spec), **every editor verb** (on its name line in the `@command`
decorator), and **the invariants this file anchors** that live inside a
docstring or a body rather than at a definition.

## Access escalation — cheapest first, and stop as soon as you can answer

Every level below has been measured. Skipping to level 4 for a question level 1
answers is the single most expensive habit available here.

| level | read | cost | when |
|---|---|---|---|
| 0 | this file | ~6k tokens | always, first, whole |
| 1 | `grep -rn "#TAG:<name>"` | one command | you know the name and want the address |
| 2 | [`docs/MAP.md`](docs/MAP.md) — tier 1 | ~13k tokens | starting a task; "what exists and where" |
| 3 | `docs/map/<dotted.module>.md` — tier 2 | ~0.5k tokens each; the largest is ~5k | you are about to touch ONE module and need real signatures |
| 4 | the source file | ~1.7k tokens for the median module, ~22k for the largest | you are about to EDIT it, or the map is not enough |
| 5 | a whole package | tens of thousands | last resort. Say out loud why levels 1–4 failed |

Level 3 is one file per module: `scripts/core/depth.py` maps to
[`docs/map/scripts.core.depth.md`](docs/map/scripts.core.depth.md). **Never
load them all** — the set is ~100k tokens, which is more than reading the
source, and that is the exact failure two tiers exist to prevent.

## The constants — literal strings, not descriptions

```
.venv/Scripts/python.exe            the interpreter. Never bare `python`.
tools/check_all.py                  the suite. One command, one exit code.
tools/smoke.py --frames 60          the frame-drift instrument.
tools/gen_map.py --write            regenerate the code map after a rename.

pyoneer_                            EVERY tmx custom property starts with this
pyoneer_behaviors                   comma-separated token list, ON THE OBJECT
pyoneer_param_<key>                 one behavior parameter, on the same object
pyoneer_actor                       actors-table row id; READ, see below
pyoneer_collision                   ON A <tileset>: the .blitmask holding that
                                    sheet's per-tile masks -- collision level one
pyoneer_passability                 ON AN ART LAYER: the companion tile layer
                                    holding its per-cell masks -- level two
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
| "what exists" · "where does X live" · "is there already a function for this" | [`docs/MAP.md`](docs/MAP.md) — GENERATED tier 1, then one tier-2 file |
| "what does this behavior do" · "how do I make it move" · "add a behavior" | [`docs/BEHAVIORS.md`](docs/BEHAVIORS.md) — GENERATED; trust its **measured integration table** over any prose, including its own preamble |
| "what can a script DO" · "what ops exist" · "what may I write in a `do`" · "does that op actually run" | [`docs/EVENTS.md`](docs/EVENTS.md) — GENERATED, and it makes no hand-written claim about the code at all: its runtime and reachability columns are measured on every run, and today five of six reachability rows read `no` |
| "my entity does not move" · "nothing happens when I press a key" · "it falls forever" · "it raises at load" · "I painted collision and nothing blocks" | [`docs/DIAGNOSE.md`](docs/DIAGNOSE.md) |
| "what can I place on an object layer" · "what goes in `type=`" · "why does my layer not draw" · "what key is bound to what" | [`docs/PLACEABLE.md`](docs/PLACEABLE.md) — GENERATED |
| "make me a platformer" · "make me a top-down RPG" | `editor/genres/<id>/RULES.md`, then `docs/BEHAVIORS.md` |
| "how do I make a tileset" · "how do I add tiles from an image" · "can I use part of this PNG" · "how do I make a tile solid" · "where did the collision layer go" · "why will this tileset not grow" | [`docs/TILESETS.md`](docs/TILESETS.md) |
| "how do I change project data from a script" · "what verbs exist" | [`docs/COMMANDS.md`](docs/COMMANDS.md) — GENERATED |
| "show me a game that works" · "start a new demo" | [`docs/DEMOS.md`](docs/DEMOS.md) |
| "design a small game" · "design me a small game" · "I have an idea, what do I write down" · "write the spec before the code" · "what goes in the behavior list" · "what can I actually build with this today" | [`docs/DESIGN_TEMPLATE.md`](docs/DESIGN_TEMPLATE.md) — a fill-in form, five minutes, every field resolved against a live registry by a check |
| "how do I get from an idea to a running prototype" · "what is the loop here" · "what does one turn of the loop cost" | [`docs/PROTOTYPE.md`](docs/PROTOTYPE.md) — DESIGN → BUILD → PROVE, each step's cost measured |
| "how do I run the checks" · "I wrote a check" | [`docs/CHECKS.md`](docs/CHECKS.md) — GENERATED — plus law 6 below |
| "how does the editor think" · "why is every change a command" | [`docs/PLAN_EDITOR.md`](docs/PLAN_EDITOR.md) |
| "what is a scene" · "how do I share a tileset between maps" · "how do I add or remove a tile from a tileset" · "how do I script an event" · "what commands can a script use" · "how does the relay work" · "what do I type into the prompt strip" | [`docs/PLAN_SCENES.md`](docs/PLAN_SCENES.md) — the build spec; unbuilt until its stages say otherwise |
| "where is the art" · "why does it fail on a fresh clone" | [`docs/ASSETS.md`](docs/ASSETS.md) |
| "is this already written but unwired" | [`docs/BEHAVIORS.md`](docs/BEHAVIORS.md)'s measured integration column first; [`docs/history/ORPHANS.md`](docs/history/ORPHANS.md) only for the archaeology |
| "what should I do next" | [`docs/NEXT.md`](docs/NEXT.md) — every entry carries the command that measured it; run it before acting |
| "the frame changed" · "smoke drifted" | `tools/smoke.py --frames 60`, then law 11 |
| "what did the first review find" · "why was it built this way" · "was this planned once already" | everything under `docs/history/`: `docs/history/ENGINE_REVIEW.md`, `docs/history/IMPROVEMENT_PLAN.md`, `docs/history/NEXT_ce66ce5.md`, `docs/history/ORPHANS.md`, `docs/history/PLAN_EVENT_SYSTEM.md`, `docs/history/PLAN_MAPS.md`, `docs/history/PLAN_SINGLETONS.md` — each dated, each stamped with what superseded it. **Never navigate by them.** |

## Generated vs written

| file | produced by | authoritative for |
|---|---|---|
| `docs/MAP.md`, `docs/map/*.md` | `tools/gen_map.py --write` | what exists, where it is, and every `#TAG:` |
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
   symbols and missed the gate itself. Every tier-2 map file prints that
   module's first-party imports, so this law is now auditable by reading rather
   than by grepping.
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
    byte-exactness contract. And **smoke injects no input**, so "no drift" never
    means "nothing changed": it cannot see anything that only happens while
    walking.
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
14. **Address code by `#TAG:`, never by a line number.** Cost: measured this
    pass — a docstring edit five rows above a pinned line turned `check_docs`
    red with `no longer contains ... it moved to line 241`, for a document that
    was entirely correct. `tools/check_docs.py` now refuses a numbered anchor
    and pins the shrinking inventory of documents that still use one.

## ACTIVE WARNINGS — mistake patterns caught more than once

Append-only, newest last. A law says what the rule is; a warning says **what
people actually do instead**, so each entry names the move that looked
reasonable at the time. Add one the second time you catch a shape, not the
first — and never delete one, because the whole value is that it is a record
of repetition.

- **You will reach for a sibling file.** The move that looks safe is a new
  module beside the incumbent — `foo_v2.py`, `new_foo.py`, a "clean"
  reimplementation to switch over later. Measured here: **five** refactors were
  attempted that way and all five died; every refactor written *into* the
  incumbent class landed. Law 2's corollary is the same lesson at package
  scale — 425 duplicate lines. Counter-move: `grep -rn "#TAG:<TheClass>"`, open
  the incumbent, edit it.
- **You will read a finished plan as an instruction.** Caught again on
  2026-08-16 at `d8c303f`: [`docs/PLAN_EDITOR.md`](docs/PLAN_EDITOR.md)'s "not
  built yet" list named four things that had already shipped — including the
  object-layer spawn path, whose absence it gave as the reason not to build the
  action queue. Nothing about that document announced itself as stale, and it
  sits at the address a reader is routed to for editor architecture.
  Counter-move: a plan whose work is done goes under `docs/history/` **the day
  it is done**, and any list of open work carries the command that measured it.
- **You will forget to regenerate the map.** Observed the same day: two modules
  landed in `demos/` without `tools/gen_map.py --write`, so `docs/MAP.md` did
  not know they existed and the next agent's `check_docs` run would have been
  red for someone else's change. Counter-move: it is one command, it belongs in
  the same change as the rename, and it names the first differing line.
- **You will ship your own layer and leave the wire to whoever owns the next
  file.** The move that looks responsible is to land the engine read, the
  model, the verb and the check, then stop at the file a sibling agent is
  holding: the seam is one line, you wrote it down in the handoff, and not
  causing an edit conflict is good manners. Four sightings. Sub-cell collision
  landed in the engine at `b438c85` and a click could not address a sub-cell
  until the very next commit, `62c5677`. The editor's Database window has
  authored `data/project/tables/` since `2ddee3d` (2026-08-08) and no
  `scripts/` reader existed until `6794bde` (2026-08-18), so for ten days
  seventeen `source="actors"` parameters looked authored and were silently the
  declared default. And tile masks took FOUR passes to reach a click: the
  engine read at `6794bde`, then the overlay and a working
  `map.tileset.mask.set` at `8915ee0` -- where
  `grep -rn "map.tileset.mask" editor/ui/` still returned nothing, so the one
  thing the author had asked for could not be done -- and only the pass after
  that wired `Canvas.bake_tile_mask`. And `#TAG:map.tileset.grow` and
  `#TAG:map.tileset.rename` shipped with exact inverses, teeth on both
  refusals, and no control anywhere calling either -- for that whole time the
  tileset the author asked to be growable and nameable was neither from
  inside the window. (That one was closed on 2026-09-03 by the palette's
  header menu; the sighting stays here because the value of this list is the
  count, not the open items.) Note
  that the middle sighting runs the other way round: this is not "the editor
  lags the engine", it is that NOBODY owns a seam, so each pass ships a layer
  that is complete, checked, and unreachable by the person who asked for it.
  Counter-move: before you call a pass done, grep for a caller from the layer
  ABOVE the thing you just built -- zero hits means the capability exists and
  the author cannot get at it. When the file really is held, the unwired seam
  goes into [`docs/NEXT.md`](docs/NEXT.md) as an entry carrying that grep as
  its command, not into a commit message nobody greps. And run the grep again
  before you write the entry: this one was written naming the tile-mask click
  as missing, and re-measuring one minute later found `bake_tile_mask` landed
  in a sibling's working tree. A gap you did not re-measure is a gap you are
  about to file twice.

## Known gaps — fill on sight

Things that are *missing*, not broken. Each is a real hole someone will hit.
Each address below is a tag, so it stays true when the code moves.

- **`README.md` is the front door and its "Known rough edges" section is still
  hand-written.** The three false gap claims this bullet used to name are
  gone: README no longer says the engine cannot read a collision mask, that
  placing an object does not spawn an entity, or that `.blitmap` has no
  reader. Its check counts are correct too — two of them now, both agreeing
  with the roster [`docs/CHECKS.md`](docs/CHECKS.md) generates, which
  `tools/check_docs.py`'s rule 6 compares on every run. What is left is the
  structural half, and it is the half that will rot again: that section is
  prose sitting beside a generated roster, so nothing regenerates it and its
  next wrong sentence arrives silently, exactly as the last three did. It must
  become generated. **This file's own navigation deliberately does not route
  through `README.md`.** Re-measured 2026-09-03 by reading the section and by
  rule 6.
- **`docs/BEHAVIORS.md`'s preamble is hand-written prose inside the
  generator**, so it can lie while the file still matches its generator. It
  currently shows the token `tile_collision`, which is not registered and makes
  a map raise at load. Same string in `#TAG:scripts/game/behavior/base.py` and
  `#TAG:scripts/game/behavior/registry.py`. That preamble held a **second**
  lie until 2026-09-03 — it told every reader that nothing in `scripts/` reads
  `data/project/` and that the engine has no table reader, months after
  `#TAG:scripts/loaders/table_file.py` shipped — and the generated file matched
  its generator byte for byte the whole time. Two instances is the measure of
  how well this shape hides: check the preamble by reading it against the
  code, because no check here can.
- **~~No `needs_art` flag on the check roster~~ — paid off, by removing the
  thing it would have described.** Art SHIPS now: six generated sheets under
  `data/art/`, tracked, drawn by `tools/art/` and materialised by
  `.venv/Scripts/python.exe -m tools.art`. `#TAG:resolve_art` reads the two
  roots in order — `data/graphics/` wins whenever it holds the file, so a
  machine with real art renders byte-identically, and `data/art/` answers
  when it does not. Measured both ways by moving `data/graphics` aside:
  `tools/check_all.py` reports `FAILED: []` with no art directory at all, so
  the art-dependent subset is empty and there is no list to generate.
- **A native `.blitmap` gets no collision at all.** `field_from_map` returns
  None for any source answering its own `object_records`, so every body on a
  native map is ungated -- stated in its own docstring as the true answer, and
  it was, while the format carried no mask declaration to read. It carries one
  now: `#TAG:declared_collision` lifts a tmx `<tileset>`'s `pyoneer_collision`
  into `TilesetFile.collision`, so a converted map's `.tileset` says
  `collision <ref>` on its own line and nothing opens it. Level one is the only
  level the native path could serve today -- there are no companion layers in a
  `.blitmap` either. Measured: `grep -rn "collision" scripts/loaders/` names
  `tileset_file.py`'s own field and nothing that opens it.
- **~~No genre-pack default behavior list~~ — paid off.** `GenreLayer` now
  carries `object_classes`, both packs declare a real list for `GamePlayer` on
  their entity layer, and `map.object.add` MATERIALISES it into
  `pyoneer_behaviors` on the new object (`#TAG:behaviors_materialised_at_add`).
  It is a starting value, not a fallback: the engine never reads a pack, an
  author's own list wins outright — including an explicit empty one — and
  nothing re-asserts the default afterwards. A pack that declares no
  `object_classes` is unchanged; one that declares a token the registry does
  not know now RAISES at pack load rather than poisoning every map made from
  it. Measured: `.venv/Scripts/python.exe tools/check_editor.py`.
- **The `transform` keyword is accepted and discarded**
  (`#TAG:GameEntitySimple.__init__`, which is where `GameEntity`'s own
  `transform=` argument ends up). Pass position via `moveto`.
- **`allowed_move` swallows an unrecognised direction**
  (`#TAG:GameEntity.allowed_move`): a bad bit returns the wanted vector
  unclamped through cells that block everything. Harmless only while
  `move_direction` is its sole caller.
- **`GameAnimationHandler` plays `idle_down` unconditionally at construction**
  (`#TAG:GameAnimationHandler.__init__`), before any behavior attaches — the
  first wall a side-on-only or portrait-only sheet hits.
- **`GameEventType.POST_DISPOSE` is defined and never dispatched.**
  `CUSTOM_EVENT`, `REBUILD`, `PARENT_RESIZED` and `USE` are likewise
  definition-only — `USE` is emitted once, from a `TextBox` pressing Enter, and
  bound by nobody. **Do not add an event member before a listener exists**;
  `USE` is the standing proof of what that costs.
- **~~No engine-side reader for `data/project/tables/`~~ — paid off.**
  `#TAG:scripts/loaders/table_file.py` reads them; `#TAG:actor_row` turns an
  object's `pyoneer_actor` into the row and both spawn routes pass it, so the
  behaviour-parameter chain's step 2 fires and an `hp` column reaches the
  runtime. `LayerRenderer.tables` is the one slot, assigned in `main.py`
  beside `spawn_defaults` and read by the map spawn and `SceneManager.spawn`
  alike. Missing stays free (no `tables/` directory, no `pyoneer_actor`, a row
  omitting a column: all fall to the declared default); unreadable and
  contradictory raise, and a `pyoneer_actor` naming an absent row raises
  naming the object.
- **~~Two documents still address code by line number~~ — paid off.** Both are
  converted: DIAGNOSE's four became `#TAG:` addresses, and NEXT's seven went
  with the `ce66ce5`-era ranked list into `docs/history/NEXT_ce66ce5.md`, where
  an archive's numbers are history and exempt by design.
  `tools/check_docs.py`'s `LINE_ANCHOR_DEBT` is now the empty dict, which is
  the strongest form the rule can take: **any** bare `file.py:LINE` in a live
  document is a failure, with no exemption left to argue about.
- **The editor and the engine disagree about a collection-of-images tileset,
  in silence.** A `<tileset>` whose children are `<tile id="N"><image/></tile>`
  with no `<image>` of its own reads correctly in `MapDocument` (byte-exact
  round trip, correct extent) and pytmx draws its loose images at the right
  gids -- while `#TAG:TilesetAtlas` draws procedural colour swatches for it and
  does not even report it as missing art. `#TAG:tileset_defaults` also refuses
  `columns <= 0`, which is what Tiled writes for that shape, so such a tileset
  cannot carry per-tile masks as authored. This editor never writes the shape;
  a reader can still open a map that does. The two methods that would fix it
  are in `#TAG:editor/ui/tileset.py` and neither touches the format.
- **~~`#TAG:map.tileset.grow` and `#TAG:map.tileset.rename` have no caller in
  the window~~ -- paid off.** Right-clicking a tileset's header strip in the
  palette opens Rename / Grow / Remove; an entry that cannot act is DISABLED
  and carries the reason in its own label, and growth is asked in rows and
  refused against the headroom before a command exists. Measured 2026-09-03:
  `grep -rn "map.tileset.grow\|map.tileset.rename" editor/ui/ --include=*.py`
  returns **6** lines where it returned none, and `tools/check_palette.py`
  drives a real right-click, a real `QAction.trigger()` and a real undo. The
  sighting itself stays recorded in ACTIVE WARNINGS above, because that list
  is a record of repetition and closing an instance does not unmake it.
- **`tools/` is not in the code map**, deliberately — a check module is read
  whole or not at all. So `grep -rn "#TAG:"` answers nothing about the check
  suite; [`docs/CHECKS.md`](docs/CHECKS.md) is the index for that half of the
  tree, and it is generated too.
- **Landed recently, so verify before trusting a doc that says otherwise:** the
  whole tileset surface. `#TAG:MapDocument.grow_tileset` and
  `#TAG:MapDocument.rename_tileset` with `#TAG:MapDocument.tileset_headroom`
  under them; `#TAG:TilePalette` as one stacked column with the selection held
  as a tileset NAME plus a rectangle; `#TAG:TilesetImportDialog` as a non-modal
  region crop with `margin`/`spacing` gone; and the collision companion folded
  out of the hierarchy (`#TAG:companion_folded_into_its_layer`) with
  `#TAG:BRUSH_DOMAIN`'s no-opinion chip as the way to clear either level.
  [`docs/TILESETS.md`](docs/TILESETS.md) is the current account of all of it.
  Entries leave this list fast -- the previous four died in one afternoon and
  one of them died DURING the pass that was writing it down.
  **Re-measure this section; do not cite it.**

## TODO-VERIFY

Any claim in this file that was **not** confirmed by running something this
pass is prefixed `[UNVERIFIED]`. An unmarked claim is a claim someone executed.
There is exactly one:

- `[UNVERIFIED]` the aggregate "26 vacuous assertions found across review
  passes" in law 5 is carried from review reports, not re-counted here. The
  five in `README.md` are described there in detail.

## Anchors — machine-checked, do not edit by hand

Each line says: a `#TAG:`, and text that must still be inside the thing that
tag names. `tools/check_docs.py` resolves the tag to a file and a line range
from the AST on every run, then asserts the text is in that range **exactly
once**. So an edit above an anchor cannot break it, and a fact that moves to a
different function, gets duplicated, or disappears breaks it loudly.

A failure means the code moved or the fact changed — **fix the anchor's text or
its tag, never delete the anchor**. If a tag resolves nowhere, run
`.venv/Scripts/python.exe tools/gen_map.py --write` first: the symbol was
probably renamed.

```anchors
#TAG:layer_profile.PREFIX :: PREFIX = "pyoneer_"
#TAG:LAYER_NAME_ALIASES :: "Paralax": "Parallax"
#TAG:SPAWN_REGISTRY :: SPAWN_REGISTRY: dict
#TAG:registry.resolve :: raise PyoneerAssetMissingError
#TAG:delta_is_ms_over_60 :: milliseconds divided by 60
#TAG:collision_field_ungated :: None means ungated
#TAG:pyoneer_prefix_pytmx :: pytmx RAISES and makes the whole map unloadable
#TAG:InputActionManager.held :: return self.actions[action_name].held
#TAG:GameComponent.mark_event_handled :: def mark_event_handled
#TAG:BLOCK_ALL :: BLOCK_ALL = BLOCK_DOWN
#TAG:GameEntitySimple.__init__ :: self.transform: Transform = Transform(
#TAG:GameEntity.allowed_move :: if field is None or bit is None
#TAG:GameAnimationHandler.__init__ :: self.start(self.DEFAULT_ANIMATION)
#TAG:post_dispose_unwired :: POST_DISPOSE = ("post_dispose", None)
#TAG:qt_takewidget_sequence :: old = self.takeWidget()
#TAG:behaviors_read_at_spawn :: read_requests(obj.properties
#TAG:behaviors_attached_at_construction :: self.behaviors.attach_all
#TAG:behaviors_materialised_at_add :: if BEHAVIORS in properties
#TAG:topdown_move :: name="topdown_move"
#TAG:map.object.property.set :: "map.object.property.set"
#TAG:actor_row :: return tables.row(ACTORS, wanted, blame)
#TAG:resolve_params :: if actors_row is not None and param.key in actors_row
#TAG:growth_is_rows_only :: THE ONLY SAFE AXIS IS ROWS
#TAG:MapDocument.tileset_headroom :: the lowest firstgid above it
#TAG:companion_folded_into_its_layer :: A COMPANION IS NOT A LAYER YOU LOOK AT
#TAG:MASK_DOMAIN :: tuple(range(STAR + 1))
#TAG:BRUSH_DOMAIN :: MASK_DOMAIN + (NO_DATA,)
#TAG:CROP_DIR :: CROP_DIR = "tilesets"
```
