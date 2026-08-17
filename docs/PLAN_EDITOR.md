<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written architecture; counts re-checked at 5dd012d on 2026-08-16 -->

# The editor

An authoring environment where a human and an AI build a game together, and
the editor itself is one of the things they build.

This document is the architecture and the reasoning. `editor/` is the code.

---

## The one idea

**Every change goes through the same door.**

```
  a click on the canvas   ──┐
  a cell edited in a table ─┼──►  Command  ──►  validate  ──►  apply  ──►  inverse
  a line of response.jsonl ─┘                      │                          │
                                                   └── raise, roll back ──────┘
```

A `Command` is a verb, a scope, and arguments. Applying one returns *the
command that undoes it* — not a snapshot. Everything the editor is supposed
to be falls out of that single decision:

| requirement | how the command stream gives it |
|---|---|
| the AI can edit the project | it emits commands; no special path |
| the human can review what it did | the command log **is** the review surface |
| mistakes are cheap | undo is a list of commands, and it is exact |
| paved roads, fail-loud | one validator, one place to raise |
| the AI's instructions can't go stale | `COMMANDS.md` is generated from the registry that executes it |

That last one matters more than it sounds. A hand-written interface
document is the single most likely thing to drift out from under a model
that trusts it. Here, a verb that is not implemented cannot appear in the
docs, and an implemented verb cannot be missing from them — asserted by
`tools/check_editor.py`.

## Toolkit: PySide6

Chosen deliberately, and it is a one-way door, so the reasoning is on the
record:

| requirement from the brief | what Qt gives it |
|---|---|
| "components populated based on the need" | `QDockWidget` — panels that appear, dock, tear off, and remember layout |
| a tilemap canvas with layers | `QGraphicsView` — z-ordered scene, zoom, pan, rubber-band select |
| "a list of actors, their stats" | `QAbstractTableModel` — real model/view editing |
| undo across all of it | `QUndoStack` maps 1:1 onto the command stream |
| watch for `response.jsonl` | `QFileSystemWatcher` |
| licence sanity | LGPL, same as pygame and pytmx |

And the pointed one: **Tiled is Qt.** Building the replacement on the same
toolkit means the thing being replaced is the C++ and the age, not the
widget layer.

It is a separate dependency file (`editor/requirements.txt`) so the engine's
install stays `pygame` + `pytmx`.

The engine's own widget system is **not** used for the editor. It is a game
UI — deferred blits, depth sorting, custom scrollbars — and it is still
being repaired. An editor needs native text input, IME, accessibility, file
dialogs and a table view; that is a different job.

## Layout and the dependency rule

```
editor/
  _bootstrap.py        sys.path, same rule as tools/
  core/                headless. No Qt, no pygame. All of it testable.
    errors.py            PyoneerEditorError and below
    scope.py             the addressing scheme
    commands.py          Command, the registry, transactions, undo
    verbs.py             the vocabulary itself
    genre.py             genre packs and rule validation
    project.py           Project, DataTable — what is edited
    request.py           notes, manifests, bundles, response parsing
    session.py           the one object the GUI holds
  genres/
    topdown_rpg/         genre.json, RULES.md, ART.md
    platformer/
  ui/                  Qt. Views only; no authority.
  requests/            request bundles, in and out
```

The dependency direction is one-way and **asserted by the check**:

```
editor/  ──►  scripts/        allowed (MapDocument, errors)
scripts/ ──►  editor/         never
```

`python main.py` must work on a clone with `editor/` deleted.

## The contract with the engine

The editor does not talk to a running game. It writes the files the engine
already reads:

| what | where | via |
|---|---|---|
| maps | `data/maps/*.tmx` | `MapDocument`, byte-faithfully |
| data tables | `data/project/tables/*.json` | sorted keys, `\n`, trailing newline |
| which genre | `data/project/project.json` | |

That is the whole interface. Live reload is an optimisation to add later
(`renderer.invalidate()` and `AssetMapManager.load_assets(reload=True)`
already exist), not a dependency.

Byte-faithfulness is load-bearing, not fastidiousness. The intent is that a
human edits in Tiled while the editor and an AI edit programmatically. A
writer that reflows the file makes every subsequent human diff unreadable.
`check_editor.py` asserts the strongest available form of this: after
`add object → undo`, the 133,940-byte map is byte-identical, including the
`<objectgroup/>` going back to self-closing.

## Scopes — why a request knows where it lands

```
project
genre
map:test
map:test/layer:Floor
map:test/layer:entity/object:14
table:actors
table:actors/row:hero
```

Every dock declares a scope. Every note carries one. Every command targets
one. The same string appears in the panel title, the manifest, the
generated context, and the response.

Code paths are **not** encoded in scopes — they are looked up *from* a scope
by `code_locations()`. That keeps the address stable when code moves, and it
is what fills the "where do I edit?" section of a request. The table names
real paths and the check asserts every one exists, so it cannot rot the way
a comment would.

## The prompt paradigm

Each primary panel carries a prompt strip at the bottom. Typing there
leaves a **note** on that panel's scope — a code review comment on the
project rather than on a diff.

```
  1. type          note{scope, text, kind}       kind ∈ change|question|constraint
  2. accumulate    the Manifest panel, grouped by scope; reorder, delete
  3. ship          writes editor/requests/NNNN-slug/
  4. answer        an AI writes response.jsonl (+ NOTES.md, + code edits)
  5. apply         validated, applied as ONE transaction, one undo step
```

A shipped bundle is self-contained:

| file | what it is | generated from |
|---|---|---|
| `BRIEF.md` | the protocol and the response contract | fixed |
| `RULES.md` | genre conventions — the conditioning | the genre pack |
| `CONTEXT.md` | current state of every scope touched, plus open rule violations | the live project |
| `REQUEST.md` | the notes, grouped by scope, each with its likely files | the manifest |
| `COMMANDS.md` | the exact vocabulary | **the registry** |
| `manifest.json` | machine-readable | the manifest |

Why a bundle rather than a prompt string:

- **Location.** The scope becomes concrete file paths. No guessing where
  "the actors list" lives.
- **Conditioning without bloat.** The genre pack is a page, and it is the
  *same* page every time, so it is reviewable. That is what makes "make me a
  platformer with guns and aliens" affordable — the eight words carry the
  intent and the pack carries the rest.
- **No drift.** See above.

The response contract is strict on purpose: unknown verb, unknown argument,
missing argument, or wrong type rejects the **whole** response. Nothing is
half-applied. A typo costs the model a retry rather than costing the author
a corrupted project. Types are checked, never coerced — `"5"` is not `5`,
because a plausible wrong value is this codebase's documented failure mode.

Code changes are the escape hatch, not the norm. Some requests genuinely
need engine code — a jump arc, a targeting rule — and those are ordinary
diffs, reviewed as ordinary diffs. The bundle names the files; `RULES.md`
states what must not be touched.

## Genre packs

A pack is `genre.json` + `RULES.md` + `ART.md` (+ optional `template/`).

```jsonc
{
  "layers": [ { "name": "Floor", "kind": "tile", "depth": 10,
                "required": true, "collision": true, "doc": "..." } ],
  "tables": [ { "name": "actors", "required": true,
                "fields": [ { "name": "hp", "type": "int", "required": true } ] } ],
  "docks":  ["map", "layers", "objects", "tables", "problems", "manifest", "history"]
}
```

Two ship today: `topdown_rpg` (matches the layers already authored in
`test.tmx`) and `platformer`.

**Hard rules** raise and roll back — deleting a genre-required table or
column. **Soft rules** surface in the Problems panel and block nothing: a
project is allowed to be half-built, and an editor that argues with you at
every step is worse than one that keeps a list.

The pack declares a *starting* schema. The file is the authority afterwards,
so `table.column.add` can grow the model without an editor change. That is
the freedom requirement: adding `stat_modifier` to equipment is a command,
not a feature request.

`platformer/RULES.md` is deliberately honest about what the engine does not
have — no gravity, no tile collision, no spawn system reading the object
layer. A pack that oversold the engine would produce answers that assume
machinery that is not there.

## Panels

| panel | what it is | follows selection |
|---|---|---|
| Hierarchy | the whole map as one tree — groups, layers, objects | yes |
| Inspector | every field of the selected thing, editable | yes |
| Tiles | one tileset at a time; drag a rectangle for a multi-tile stamp | — |
| Problems | soft rule violations; nothing here blocks | no |
| Manifest | staged notes, grouped by scope | no |
| History | every command that ran, human or AI | no |
| Database | **a second window** — actors, items, equipment, RPG Maker shape | — |

Selection is global (`editor/ui/selection.py`) and dock scope is per-panel.
Inspectors follow the selection; Problems and Manifest do not, because a note
typed into Problems is about the project and should not be dragged onto
whatever tile was last clicked.

## Painting

`editor/core/paint.py` is pure — no Qt, no document, `(x, y, gid)` in and
out — which is the only reason its edge cases are testable.

- **One stroke is one transaction.** Press-drag-release accumulates and
  commits a single `map.tile.set_many`. Before that, a forty-cell drag made
  forty undo steps and re-rendered the csv payload forty times.
- Bresenham between mouse samples, so a fast drag is a line and not a
  dotted line.
- A brush *anchors* its stamp under the cursor; an area tool *tiles* the
  stamp across the area, aligned to map coordinates so two rectangles
  painted with the same pattern line up.
- Left paints, right erases, middle or space pans, ctrl+wheel zooms, alt
  picks. Tiled's conventions, not invented ones.

**Terrain (autotile)** is `editor/core/autotile.py`, and it is a Wang
**corner** set rather than an orthogonal bitmask because the art demands it.
`TileA2.png` is an RPG Maker VX Ace A2 sheet — 8×4 = 32 groups, each a 4×6
grid of 16px quadrants — and since this map's cells are also 16px, one cell
is one quadrant. Thirteen of the sixteen corner masks have art; the two
diagonals have none in any RM sheet and hit a stated `Diagonal` policy
instead of a `KeyError` mid-stroke. A whole terrain is **one integer**, the
group's top-left gid, so choosing one is "click any tile of it".

The half-cell trap is the thing to keep in mind: terrain lives on the
`(W+1)×(H+1)` lattice of cell corners, so editing one corner re-tiles four
cells and a stroke rewrites cells the cursor never touched. That is not a
bug — it is how the seam against existing terrain updates.

## Crash resistance

The editor is a tool for changing a codebase that is being changed
underneath it, so the interesting question is what happens while the engine
is broken. Measured answer before `editor/preflight.py`: a syntax error in
any of the three engine modules the editor imports killed it with a bare
traceback *above* `QApplication`, so the existing error dialog never ran —
launched from a shortcut, that is a window that never appears.

Preflight `ast.parse`s those three files — parses, never imports, so nothing
executes — confirms each still declares the names the editor binds, and
reports file, line and message. It imports `os`, `ast` and `sys` and nothing
else, so it cannot be broken by what it checks. `tools/check_editor.py`
asserts the contract stays true, turning a startup crash into a failing
check.

It is honest about its limits: `ast` cannot see inheritance across files,
decorator side effects, dynamic registration, or module-level import
explosions. It catches the failure that actually stops startup.

## Opening code

`editor/core/ide.py`. Detection reads JetBrains Toolbox's own `state.json`
and known install locations, and treats **PATH as a last resort** — measured
on the author's machine, `shutil.which("pycharm")` resolves to PyCharm
Community 2023.3.3 while the running IDE, with this project open, is
Professional 2026.1.4 under a differently-numbered shim. The VS Code case is
worse: a stale shim does not error, it silently cold-starts an older second
instance.

Command construction is pure and therefore testable; launching is detached
and returns a result rather than raising. Revealing code is read-only by
construction and cannot affect the project, the game, or the editor.

## Status

Asserted by `tools/check_editor.py`, `check_paint.py`, `check_autotile.py`
and `check_editor_ui.py`. The suite's size is generated into
[`CHECKS.md`](CHECKS.md) and the verb vocabulary into [`COMMANDS.md`](COMMANDS.md);
both numbers were stale in this paragraph before those files existed. What
those four checks cover:

- scopes, command stream, transactions, exact undo/redo, atomic rollback
- every registered verb, across tiles, objects, tables and project settings
- genre packs, hard and soft rule validation
- notes, manifests, bundle writing, strict response parsing
- painting: strokes, stamps, flood fill, clipping, drag semantics
- autotile: the pixel-verified corner table, terrain recovery, diagonals
- the Qt window driven offscreen: panels, selection sync, canvas edits as
  commands, the database window, response application

Not built yet:

- **`map.layer.add` / `map.layer.remove`.** `MapDocument` can read and write
  layers but cannot create or delete them. This is the next `MapDocument`
  feature and the reason "include or remove layers" is not yet a command.
- **The object layer → entity spawn path.** The editor can *place* objects;
  the renderer still skips `TiledObjectGroup` entirely.
- **The event action queue.** Deliberately deferred, not forgotten — see
  below.
- **Live reload**, so a command shows up in a running `main.py`.
- **Layer properties** (opacity, offset, tint). `TileLayer` reads only
  name/id/width/height, and there is no `map.layer.*` verb.
- **Shape geometry editing.** Polygons, ellipses and text objects are
  displayed and **preserved byte-exactly**, but their points are not
  editable.

## Why the action queue is not built yet

An "attach an ordered list of actions to an object, triggered by an engine
event" panel is the right idea and it is authoring data, so it invalidates
nothing. But investigation found the runtime cannot execute it yet:

- `GameEntity` derives `PyoneerGameObject`, **not** `GameComponent`. It has
  no `callbacks`, no `bind_sync_listener`, no `send_event_advanced` — it is
  not on the event bus at all, and only receives direct `core_*` calls.
- Of 54 `GameEventType` members, only about ten are ever dispatched through
  the bus. Every `MOUSE_*` and `KEY_*` member reaches components through a
  *separate* registry, so a raw event-type picker would be mostly dead
  options.
- There is no collision detection between entities (`BoundingBox` is defined
  and used nowhere), and `GamePlayer.core_input_receive` is `pass  # todo`.
- Above all: the object layer is skipped at runtime, so a queue attached to
  a map object would have nothing to attach *to* when the game runs.

Building the panel now would produce a feature that looks complete and does
nothing — the exact failure this project is built to avoid. The order is:
spawn path first (`docs/NEXT.md` item 1), then a small
`EntityActionComponent` on the bus, then the panel. The design is settled:
semantic triggers (`on_touch`, `on_interact`, `on_spawn`, `on_frame`) rather
than raw event types, stored as a JSON string in a tmx custom property,
authored through `map.object.action.*` verbs so it inherits undo, rollback
and generated docs for free.

## Open design questions

1. **Response transport.** Today: the editor writes a bundle, something
   answers it, the editor picks up `response.jsonl`. A "Send" button that
   shells out to `claude -p` is a convenience on top of that primitive, not
   a different design. The file drop stays the contract because it works
   with an interactive session, a headless run, or a different model
   entirely.
2. **How much the AI may restructure.** `RULES.md` currently says "do not
   restructure the event system" in prose. It could be mechanical — a check
   that fails if dispatch changed. Prose first; mechanise when it is
   violated once.
3. **Per-genre engine code.** A pack can ship `template/`, but nothing
   copies it yet. Open question whether a genre should ship runnable
   systems (a platformer body) or only condition an AI to write them. The
   current lean is: ship the rules, let the AI write the code, because a
   shipped system that nobody reads is the thing that rots.
