<!-- pyoneer-doc: L0 -->
<!-- pyoneer-stamp: hand-written; re-measured on 2026-09-16 during the markdown cleanup by tools/check_docs.py and the greps it names. -->
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
grep -rn  "#TAG:topdown_move"              a behavior token's declaration, not its 200+ mentions
grep -rn  "#TAG:map.tile.set"              an editor verb's declaration, same
grep -rn  "pyoneer_param_"                 a file-format string, everywhere it is spelled
```

**BOUND THE TAG OR IT IS NOT A LOOKUP.** A tag is a PREFIX of every tag under
it, so the bare form matches the whole subtree: measured, `#TAG:GameEntity`
returns **48** lines and `#TAG:GameEntity(\s|$)` returns **2**. Use the bare
form deliberately, when you want the subtree; use the bounded form when you
want the declaration. A dotted tag (`#TAG:GameEntity.allowed_move`) is a leaf
and needs no bounding. Behavior tokens and verbs are leaves too.

The third and fourth commands are the ones worth internalising. A behavior
token and a verb name are *strings*, spelled in specs, examples, docstrings,
generated tables and `.tmx` files, so grepping the bare name returns dozens of
lines and none of them is the declaration. The `#TAG:` form returns exactly one
line in the source — the line that defines the thing — plus the code map's
entry for it. Every registered behavior token and every editor verb carries
one.

A `#TAG:` is this repository's stable address for a symbol; law 14 says why a
line number is not. Nothing at all is written by hand in the map —
[`tools/gen_map.py`](tools/gen_map.py) walks the AST and emits it — so a tag
cannot name something that does not exist, and the tag for a symbol you just
renamed disappears in the same run.

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

**Bare by default**, because someone looking up `GameEntity` knows the class
name and does *not* yet know the module. **Qualified only on collision** — when
two things share a name the generator prefixes both with the module stem
(`#TAG:layer_profile.PREFIX`), and a property's setter takes `.setter`
(`#TAG:GameComponent.depth.setter`), because a bare `update` is claimed by 18
classes here and a tag returning 18 lines is not an address.

**A TAG IS A DECLARATION, NEVER A CITATION.** A hand-placed tag value may
appear exactly ONCE anywhere in the mapped tree, so a `see #TAG:<value>` inside
a docstring pointing back at the line that declares it makes
`tools/check_docs.py` report the value at two addresses. Cite it in prose
instead. `tools/` is not mapped, so a check module may name a tag as often as
it likes.

You do not write tags for symbols: the generator emits them. Write one by hand
**only** to name a line that is not a definition — a sentence inside a
docstring, a token inside a spec literal, a step inside a sequence — as a
trailing comment on that line. `tools/check_docs.py` refuses a hand-placed tag
that sits outside the symbol it names, and refuses two tags with the same value.
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
| 0 | this file | ~7.1k tokens | always, first, whole |
| 1 | `grep -rn "#TAG:<name>"` | one command | you know the name and want the address |
| 2 | [`docs/MAP.md`](docs/MAP.md) — tier 1 | ~16k tokens | starting a task; "what exists and where" |
| 3 | `docs/map/<dotted.module>.md` — tier 2 | ~0.6k tokens each; the largest (`editor.core.verbs`) is ~10k | you are about to touch ONE module and need real signatures |
| 4 | the source file | ~2.1k tokens for the median module, ~47k for the largest | you are about to EDIT it, or the map is not enough |
| 5 | a whole package | tens of thousands | last resort. Say out loud why levels 1–4 failed |

Level 3 is one file per module: `scripts/core/depth.py` maps to
[`docs/map/scripts.core.depth.md`](docs/map/scripts.core.depth.md). **Never
load them all** — the set is ~136k tokens, which is more than reading the
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

data/maps/starter.tmx               THE shipped map. main.py boots it, the
                                    smoke baseline is measured over it, and
                                    law 11 protects it
data/graphics/ then data/art/       art: the untracked override, then the
                                    tracked generated pack
data/sound/ then data/audio/        audio: the same two-root rule, same order
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
| "what can a script DO" · "what ops exist" · "what may I write in a `do`" · "does that op actually run" · "how do I script an event" · "what commands can a script use" | [`docs/EVENTS.md`](docs/EVENTS.md) — GENERATED, with no hand-written claim about the code: its runtime and reachability columns are measured on every run, so a row reading `no` is a wire somebody broke, not a feature nobody built yet |
| "how do I make a noise" · "where does audio come from" · "why is it silent" · "what am I allowed to ship" | [`data/audio/CREDITS.md`](data/audio/CREDITS.md) for the shipped assets and their licences; `#TAG:scripts/core/audio.py` for the two roots and the missing-card / missing-file split; [`docs/EVENTS.md`](docs/EVENTS.md) for the play ops |
| "my entity does not move" · "nothing happens when I press a key" · "it falls forever" · "it raises at load" · "I painted collision and nothing blocks" | [`docs/DIAGNOSE.md`](docs/DIAGNOSE.md) |
| "what can I place on an object layer" · "what goes in `type=`" · "why does my layer not draw" · "what key is bound to what" | [`docs/PLACEABLE.md`](docs/PLACEABLE.md) — GENERATED |
| "make me a platformer" · "make me a top-down RPG" | `editor/genres/<id>/RULES.md`, then `docs/BEHAVIORS.md` |
| "how do I make a tileset" · "how do I add tiles from an image" · "how do I add or remove a tile from a tileset" · "can I use part of this PNG" · "how do I make a tile solid" · "where did the collision layer go" · "why will this tileset not grow" | [`docs/TILESETS.md`](docs/TILESETS.md) |
| "how do I change project data from a script" · "what verbs exist" | [`docs/COMMANDS.md`](docs/COMMANDS.md) — GENERATED |
| "show me a game that works" · "start a new demo" | [`docs/DEMOS.md`](docs/DEMOS.md) |
| "design me a small game" · "I have an idea, what do I write down" · "what goes in the behavior list" · "what can I actually build with this today" · "how do I get from an idea to a running prototype" · "what is the loop here" · "what does one turn of the loop cost" | [`docs/DESIGN_TEMPLATE.md`](docs/DESIGN_TEMPLATE.md) — a fill-in form checked against the live registries, and the design → build → prove loop |
| "how do I run the checks" · "I wrote a check" | [`docs/CHECKS.md`](docs/CHECKS.md) — GENERATED — plus law 6 below |
| "how does the editor think" · "why is every change a command" · "what is a scope" · "how does the relay work" · "what do I type into the prompt strip" | [`docs/PLAN_EDITOR.md`](docs/PLAN_EDITOR.md) — the editor's architecture |
| "what is still unbuilt for scenes" · "what is a scene" · "how do I share a tileset between maps" · "is there a tileset editor screen" · "how will region triggers work" · "what is the relay back channel" · "why does `ask` not run" | [`docs/PLAN_SCENES.md`](docs/PLAN_SCENES.md) — the UNBUILT remainder of the scenes plan, with a status table at the top |
| "where is the art" · "why does it fail on a fresh clone" | [`docs/ASSETS.md`](docs/ASSETS.md) |
| "is this already written but unwired" | [`docs/BEHAVIORS.md`](docs/BEHAVIORS.md)'s measured integration column first; [`docs/history/ORPHANS.md`](docs/history/ORPHANS.md) only for the archaeology |
| "what should I do next" · "is this a known defect" | [`docs/NEXT.md`](docs/NEXT.md) — every entry carries the command that measured it; run it before acting. Item numbers are permanent ids |
| "the frame changed" · "smoke drifted" | `tools/smoke.py --frames 60`, then law 11 |
| "how many times has this mistake happened" · "when did that gap close" | [`docs/history/SIGHTINGS.md`](docs/history/SIGHTINGS.md) — the append-only ledger behind ACTIVE WARNINGS and the paid-off gaps |
| "what did the first review find" · "why was it built this way" · "was this planned once already" | everything under `docs/history/`: `docs/history/ENGINE_REVIEW.md`, `docs/history/IMPROVEMENT_PLAN.md`, `docs/history/NEXT_ce66ce5.md`, `docs/history/ORPHANS.md`, `docs/history/PLAN_EVENT_SYSTEM.md`, `docs/history/PLAN_MAPS.md`, `docs/history/PLAN_SCENES_2026-09-03.md`, `docs/history/PLAN_SINGLETONS.md`, `docs/history/SIGHTINGS.md` — each dated. **Never navigate by them.** |

## Generated vs written

| file | produced by | authoritative for |
|---|---|---|
| `docs/MAP.md`, `docs/map/*.md` | `tools/gen_map.py --write` | what exists, where it is, and every `#TAG:` |
| `docs/BEHAVIORS.md` | `tools/check_behavior_docs.py --write` | the behavior table and its **measured** integration status |
| `docs/EVENTS.md` | `tools/check_event_docs.py --write` | the op vocabulary and its **measured** runtime and reachability |
| `docs/PLACEABLE.md` | `tools/check_docs.py --write` | spawnable types, layer→depth, input verbs |
| `docs/CHECKS.md` | `tools/check_docs.py --write` | the check roster |
| `docs/COMMANDS.md` | `tools/check_docs.py --write` | the editor's verb vocabulary |
| everything else in `docs/` | hand-written, stamped | its own question shape only |

A generated file is regenerated and compared byte-for-byte by its check, so it
cannot drift from its generator. **A generator's hand-written preamble still
can** — read it against the code, because no check here can.

## The hard laws — each one states what it cost

A law with no cost attached gets ignored. Every cost below is in the tree.

1. **Every tmx custom property starts `pyoneer_`.** Cost: pytmx **raises and
   makes the whole map unloadable** if a property shadows one of its own
   attribute names (`opacity`, `visible`, `offsetx`, …). Import `PREFIX` from
   `scripts/core/layer_profile.py`; never retype it.
2. **`editor/` may import `scripts/`. `scripts/` may NEVER import `editor/`.**
   Cost: `python main.py` must work on a clone with `editor/` deleted.
   Corollary: shared logic lives in `scripts/` and the editor re-exports it —
   a second copy of the collision model cost **425 duplicate lines**, deleted
   in `29fbfc1`. Every tier-2 map file prints its module's first-party imports,
   so this law is auditable by reading.
3. **Do not restructure the event system.** Add types, listeners and components
   freely; do not touch dispatch, consumption or the listener registries. Cost:
   consumption is **not type-gated** — one stray `handle()` in a fan-out
   silences every sibling for the rest of the frame. That is *why* a behavior is
   called and never dispatched to.
4. **A check asserts what the CODE does, never what the MAP contains.** Write
   your own fixture. Cost: commit `333a77a` exists solely to undo two checks
   that pinned the shipped map's content, and `check_tmx_roundtrip` and
   `check_tileset` were later found measuring one map's CRLF and indentation
   rather than the writer — both now build a deliberately awkward fixture.
5. **An assertion that cannot fail is not an assertion.** The dominant failure
   shape is **one half of an invariant** — a gate proved to let something
   through and never proved to stop it. Break the code your check covers,
   confirm it goes red, and report the mutation and the result. Cost:
   `[UNVERIFIED]` 26 such assertions reported across review passes.
6. **A new check goes into `tools/check_all.py`'s roster in the SAME change.**
   Cost: three checks have been written, passed, and never run by the suite —
   one of them with 114 assertions.
7. **Raise; never fall back to a plausible default.** Cost: 39 authored tiles
   silently dropped for months because the renderer looked up `Parallax` and
   the retired canvas said `Paralax` (`#TAG:LAYER_NAME_ALIASES` still carries
   the alias). This is why `BehaviorParam.coerce` raises where
   `Capability.coerce` falls back, and why they are deliberately not one class.
8. **A behavior token, a table row id and a column name are FILE FORMAT
   strings** — stable once referenced, never renamed. Cost: a renamed token
   silently disarms every object carrying it *and looks like the behavior
   working*. `resolve()` raises on an unknown token for exactly this reason.
9. **`event.data["delta"]` is milliseconds ÷ 60, not seconds.** Cost: a genre
   table's pixels-per-second number used raw is ~16.7× wrong **in a way that
   still looks like it works**.
10. **Adding a behavior that polls a verb and adding its binding are ONE
    change.** Cost: `InputActionManager.held()` is an unguarded dict index, so
    an unbound verb raises `KeyError` *inside* `core_frame_update`, killing the
    frame for every sibling in that scene bucket. The behaviors raise at
    **attach** instead — deliberately the opposite timing. Know which you are
    writing.
11. **Do not hand-edit `data/maps/starter.tmx` or `tools/baseline.json`; name a
    smoke drift field-by-field or do not bless it.** Edit the map through the
    editor or `MapDocument`, whose byte-exact round trip (measured under both
    LF and CRLF) a hand-edit destroys. Cost: that contract exists because a
    tmx mixing tab and space indentation under CRLF is reproduced by no
    pretty-printer — and **smoke injects no input**, so "no drift" never means
    "nothing changed".
12. **In a Qt panel, never `setParent(None)` to clear a layout, and never free
    the old body synchronously.** Cost, both measured: `setParent(None)`
    promotes a widget to a **top-level window** (59 top-level widgets at rest →
    85 after one undo → still 85), and `setWidget()` alone frees the old body
    while a field's own `toggled` signal is still on the stack — a hard
    **STATUS_HEAP_CORRUPTION (0xC0000374)** crash of the whole editor. The one
    correct sequence is `takeWidget()` → `setParent(self)` → `hide()` →
    `deleteLater()` → `setWidget(new)`.
13. **A check must never block on a modal dialog.** Cost:
    `check_collision_mount` hung on `QMessageBox.question` for **40+ minutes
    with zero output**, indistinguishable from a slow machine. `check_all.py`
    now carries a 600s per-check timeout and a `HANG` verdict.
14. **Address code by `#TAG:`, never by a line number.** Cost: a docstring edit
    five rows above a pinned line turned `check_docs` red with `it moved to
    line 241`, for a document that was entirely correct. `tools/check_docs.py`
    now refuses a bare line-number address in any live document.

## ACTIVE WARNINGS — mistake patterns caught more than once

A law says what the rule is; a warning says **what people actually do
instead**. Each entry is the move, the counter-move and a count. The record
behind every count is [`docs/history/SIGHTINGS.md`](docs/history/SIGHTINGS.md),
and it is **append-only**: a new sighting is appended to the ledger and the
count here is updated in the same change, and nothing is deleted from either,
because the whole value is the record of repetition. Add a warning the second
time you catch a shape, not the first; newest last.

- **You will reach for a sibling file** — `foo_v2.py`, `new_foo.py`, a clean
  reimplementation to switch over to later. Counter-move:
  `grep -rn "#TAG:<TheClass>"`, open the incumbent, edit it; shared logic goes
  in `scripts/` and the editor re-exports it (law 2). **6 sightings** --
  ledger: `docs/history/SIGHTINGS.md`.
- **You will read a finished plan as an instruction** — nothing about a stale
  plan announces itself, and it sits at the address readers are routed to.
  Counter-move: a plan whose work is done goes under `docs/history/` **the day
  it is done**, and any list of open work carries the command that measured
  it. **3 sightings** -- ledger: `docs/history/SIGHTINGS.md`.
- **You will forget to regenerate the map** after adding or renaming a module,
  so the next agent's `check_docs` run is red for your change. Counter-move:
  `tools/gen_map.py --write` in the same change; it names the first differing
  line. **1 sighting** -- ledger: `docs/history/SIGHTINGS.md`.
- **You will ship your own layer and leave the wire to whoever owns the next
  file** — engine read, model, verb and check land, and the one-line seam goes
  into a handoff. Nobody owns a seam, so the capability is complete, checked,
  and unreachable by the person who asked. Counter-move: before calling a pass
  done, grep for a caller from the layer ABOVE what you built; zero hits means
  the author cannot get at it. If that file is held, file the seam in
  [`docs/NEXT.md`](docs/NEXT.md) with the grep as its command — and re-run the
  grep first. **7 sightings** -- ledger: `docs/history/SIGHTINGS.md`.
- **You will fix the route that ships and let its SIBLING route grow without
  the fix** — the other path spells the same property, so surely it was
  covered. Distance is not the cause: siblings have turned up in another file,
  in the same function, and in the same args dict. Counter-move: after you
  guard ONE input, enumerate EVERY OTHER input the same function accepts and
  give each a verdict out loud; where two routes share a rule, make the shared
  half ONE FUNCTION or one named tuple and delete the copy, so one mutation
  turns both red. If it cannot be one function, list every sibling you checked
  and why each is safe, in the handoff — and check `tools/` last, not never,
  because a wrong detector there is a green assertion. **19 sightings** --
  ledger: `docs/history/SIGHTINGS.md`.

## Known gaps — fill on sight

Things that are *missing*, not broken; each is a trap someone will hit. Each
address is a tag, so it stays true when the code moves. The work to close one
is filed in [`docs/NEXT.md`](docs/NEXT.md), which points here rather than
restating; a gap that closes moves to the ledger's *Gaps paid off* table.

- **`README.md` is hand-written and unchecked** — `grep -n README
  tools/check_docs.py` returns nothing. Keep it a front door that links (its
  rough edges are one link to `docs/NEXT.md`) rather than one that restates.
- **The `transform` keyword is accepted and discarded**
  (`#TAG:GameEntitySimple.__init__`, where `GameEntity`'s own `transform=`
  argument ends up). Pass position via `moveto`.
- **`allowed_move` swallows an unrecognised direction**
  (`#TAG:GameEntity.allowed_move`): a bad bit returns the wanted vector
  unclamped. Harmless only while `move_direction` is its sole caller.
- **`GameAnimationHandler` plays `idle_down` at construction**
  (`#TAG:GameAnimationHandler.__init__`), before any behavior attaches — the
  first wall a side-on-only or portrait-only sheet hits.
- **`GameEventType.POST_DISPOSE` is defined and never dispatched**;
  `CUSTOM_EVENT`, `REBUILD`, `PARENT_RESIZED` and `USE` are definition-only too
  (`USE` is emitted by a `TextBox` on Enter and bound by nobody). **Do not add
  an event member before a listener exists.**
- **A native `.blitmap` gets no collision at all.** `#TAG:field_from_map`
  answers None for a source serving its own `object_records`, and the
  `collision <ref>` line `#TAG:declared_collision` writes is opened by nothing.
- **The editor and the engine disagree about a collection-of-images tileset,
  silently.** pytmx draws its `<tile><image/></tile>` children;
  `#TAG:TilesetAtlas` draws swatches and reports nothing missing, and
  `#TAG:tileset_defaults` refuses the `columns <= 0` Tiled writes for it.
- **`tools/` is not in the code map**, deliberately, so `grep -rn "#TAG:"`
  answers nothing about the check suite; [`docs/CHECKS.md`](docs/CHECKS.md) is
  that index, and it is generated.

## TODO-VERIFY

Any claim in this file that was **not** confirmed by running something this
pass is prefixed `[UNVERIFIED]`. An unmarked claim is a claim someone executed.
There is exactly one:

- `[UNVERIFIED]` the aggregate "26 vacuous assertions found across review
  passes" in law 5 is carried from review reports, not re-counted here.

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
#TAG:no_event_pooling :: identity and is CONSTANT FALSE
#TAG:childless_parent_closes_itself :: if not list(parent) and not
#TAG:attribute_order_read_off_the_file :: READ OFF THE FILE, NEVER COMPUTED
#TAG:untyped_object_spawns_nothing :: if not obj.type
#TAG:text_the_reader_casts_back :: THE ONE PLACE THAT QUESTION IS ANSWERED
```
