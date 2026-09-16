<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written architecture, re-measured against the working tree on 2026-09-16 (layout by `ls editor/core editor/ui`, panels by reading `EditorWindow.__init__`, scopes against `config/maps.json`); unbuilt work lives in docs/PLAN_SCENES.md and docs/NEXT.md, never here. -->

# The editor

An authoring environment where a human and an AI build a game together, and
the editor itself is one of the things they build. This is the architecture
and the reasoning; `editor/` is the code. It deliberately carries **no status
and no "not built yet" list** — one that sat here was read as instructions for
work that had already shipped. Unbuilt work is in
[`PLAN_SCENES.md`](PLAN_SCENES.md) and [`NEXT.md`](NEXT.md).

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
command that undoes it* — not a snapshot. Everything else falls out of that:

| requirement | how the command stream gives it |
|---|---|
| the AI can edit the project | it emits commands; no special path |
| the human can review what it did | the command log **is** the review surface |
| mistakes are cheap | undo is a list of commands, and it is exact |
| paved roads, fail-loud | one validator, one place to raise |
| the AI's instructions can't go stale | `COMMANDS.md` is generated from the registry that executes it |

A hand-written interface document is the thing most likely to drift out from
under a model that trusts it. Here an unimplemented verb cannot appear in
[`COMMANDS.md`](COMMANDS.md) and an implemented one cannot be missing —
asserted by `tools/check_editor.py`.

## Toolkit: PySide6

A one-way door, so the reasoning is recorded: `QDockWidget` panels that dock
and remember layout, a zoomable `QGraphicsView` map, `QAbstractTableModel`
data editing, `QFileSystemWatcher` for arriving responses, LGPL like pygame —
and **Tiled is Qt**. Its own `editor/requirements.txt` keeps the engine's
install at `pygame` + `pytmx`. The engine's widget system is a game UI and is
not used.

## Layout and the dependency rule

```
editor/
  app.py            launcher: editor/app.py [--genre id] [--root path]
  _bootstrap.py     sys.path, same rule as tools/
  preflight.py      parses the engine modules the editor binds, before Qt
  core/             headless. No Qt, no pygame. All of it testable.
    scope.py          the addressing scheme, and code_locations()
    commands.py       Command, the registry, transactions, undo
    verbs.py          the vocabulary itself
    project.py        Project, DataTable -- what is edited
    genre.py          genre packs and rule validation
    request.py        notes, manifests, bundles, the response gate
    session.py        the one object the GUI holds
    event_script.py   event-script documents, the authoring half of data/project/scripts/
    map_events.py     authorable region triggers (no runtime reader yet)
    collision.py      collision as authored data: three levels, one baked field
    layers.py         per-layer capabilities, as declared data
    inspect.py        what to show for a selection, as data
    behavior_view.py  what a map object composes, as data
    paint.py          what a drag means, as pure logic
    autotile.py       terrain that picks its own edge tiles
    settings.py       editor preferences
    ide.py            open a file at a line in the IDE actually in use
    errors.py         PyoneerEditorError and below
  genres/           topdown_rpg/, platformer/ -- genre.json, RULES.md, ART.md
  ui/               Qt. Views only; no authority. One module per panel or window.
  requests/         request bundles, written on demand
```

Inside `core/`, the `inspect`, `*_view` and `paint` modules answer "what should
the screen show / what does this gesture mean" as data, so a check asserts it
with no window open. The dependency direction is one-way and asserted:
`editor/` may import `scripts/` (shared logic lives there and the editor
re-exports it); `scripts/` never imports `editor/`, so `python main.py` runs
with `editor/` deleted.

## The contract with the engine

The editor never talks to a running game. It writes the files the engine
reads:

| what | where | via |
|---|---|---|
| maps | `data/maps/*.tmx`, listed in `config/maps.json` | `MapDocument`, byte-faithfully |
| data tables | `data/project/tables/*.json` | sorted keys, `\n`, trailing newline |
| event scripts | `data/project/scripts/*.json` | `ScriptLibrary`: created and deleted in memory, written at save |
| scene variables | `data/project/scenes/*.json` | read, not yet authored |
| which genre | `data/project/project.json` | |

Byte-faithfulness is load-bearing: a human edits in Tiled while the editor and
an AI edit programmatically, and a writer that reflows the file makes every
later diff unreadable. `tools/check_editor.py` asserts that after `add object
→ undo` the map is byte-identical, down to `<objectgroup/>` self-closing again.

## Scopes — why a request knows where it lands

```
project                              table:actors
genre                                table:actors/row:1
map:starter                          script:starter_greeting
map:starter/layer:Floor
map:starter/layer:entity/object:1
```

Every dock declares a scope, every note and command carries one, and the same
string appears in the panel title, the manifest, the bundle and the response.
A verb declares the scope patterns it accepts and `Verb.validate` refuses any
other address before anything runs. Code paths are **not** encoded in scopes
— `code_locations()` looks them up *from* a scope, so the address stays stable
when code moves, and a check asserts every path it names exists.

## The prompt paradigm — how the relay works

Every panel carries a prompt strip; typing there leaves a **note** on that
panel's scope — a review comment on the project rather than on a diff. Two
grains:

```
  Stage + Ship   collect notes across panels in the Manifest dock, then write one
                 bundle with the whole vocabulary -- for a change that crosses the project
  Ask            one note, one bundle, cut to this panel's address, now (Session.ask)
  then           an AI writes response.jsonl (+ NOTES.md, + code edits)
  apply          validated, applied as ONE transaction, one undo step
```

| bundle file | what it is | generated from |
|---|---|---|
| `BRIEF.md` | the protocol and response contract — protocol claims only | fixed |
| `RULES.md` | genre conventions; dropped from an Ask on content (a layer, object, row, script), which a pack says nothing about | the genre pack |
| `CONTEXT.md` | current state of every scope touched, plus live rule violations | the live project |
| `REQUEST.md` | the notes by scope, each with its likely files | the notes |
| `COMMANDS.md` | the vocabulary — all of it for a Ship, only what the address accepts for an Ask | **the registry** |
| `manifest.json` | machine-readable; a scoped bundle adds `scoped` and `verbs` | the notes |

A scoped bundle is a **promise the editor keeps**: `BundleContract`, inside
`read_response`, refuses a response using a verb the bundle did not ship or
aiming at an address it did not declare, before anything applies. Both apply
paths — the window's Apply-a-response and `Session.apply_response` — read
through that one gate. `also=` widens an Ask to a second address explicitly
(attaching a script is `script.create` plus `map.object.property.set`).

The response contract is strict: an unknown verb, unknown or missing argument,
or wrong type rejects the **whole** response, and types are never coerced
(`"5"` is not `5`). A typo costs the model a retry, not the author a corrupted
project. Engine code is the escape hatch — ordinary diffs, with the bundle
naming the files.

## Genre packs

A pack is `genre.json` + `RULES.md` + `ART.md` (+ an optional `template/`).
`genre.json` declares `layers` (kind, depth, required, collision), `tables`
and their fields, the relevant `docks`, `object_classes` (the starting
`pyoneer_behaviors` that `map.object.add` materialises onto a new object) and
`event_loadouts` (the op vocabularies its scripts may use — names, never op
lists). Two ship: `topdown_rpg`, matching `data/maps/starter.tmx`, and
`platformer`. A pack naming an unregistered behavior token or loadout raises
**at pack load**, judged by the engine's own registries.

**Hard rules** raise and roll back (deleting a required table or column).
**Soft rules** land in Problems and block nothing — a project may be
half-built. The pack declares a *starting* schema; the file is the authority
afterwards, so `table.column.add` grows the model without an editor change.

## Panels

| panel | what it is | follows selection |
|---|---|---|
| Hierarchy | the whole map as one tree — groups, layers, objects | yes |
| Inspector | every field of the selected thing, editable | yes |
| Behaviors | the object's `pyoneer_behaviors` as a grouped checklist with parameters, refusals and the per-frame run order | yes |
| Actions | the object's region-trigger declaration via `map.object.action.*`, under a banner saying nothing runs it yet | yes |
| Tiles, Collision | the stacked tile palette and the mask palette — [`TILESETS.md`](TILESETS.md) | — |
| Problems | soft rule violations; nothing blocks | no |
| Manifest | staged notes by scope, and Ship | no |
| History | every command that ran, human or AI | no |
| Database | **window** — actors, items, equipment, RPG Maker shape | — |
| Object editor | **window** — one entity: identity, placement, behaviors, actors row; opens on creating or double-clicking an object | one object |
| Script editor | **window**, Ctrl+E — pages, the indented command tree, the op picker, a strip aimed at the script | one script |

Behaviors and Actions tab onto the Inspector: all three answer "what is this
selected thing". Selection is global (`editor/ui/selection.py`); scope is per
panel. Problems and Manifest ignore selection, because a note typed there is
about the project. Panels open dialogs only through `editor/ui/ask.py`'s seams,
so a check can assert the routine path opened nothing.

## Painting and terrain

`editor/core/paint.py` is pure — `(x, y, gid)` in and out — which is why its
edge cases are testable. **One stroke is one transaction**: press-drag-release
commits one `map.tile.set_many`, Bresenham-joined so a fast drag is a line. A
brush anchors its stamp; an area tool tiles it, aligned to map coordinates.
Mouse, wheel and palette bindings are in [`TILESETS.md`](TILESETS.md) and the
window's status bar.

**Terrain** (`editor/core/autotile.py`) is a Wang **corner** set, because the
art demands it: `TileA2.png` is an RPG Maker A2 sheet whose 16px quadrants are
this map's 16px cells. A terrain is **one integer**, its group's top-left gid.
The trap: terrain lives on the `(W+1)×(H+1)` lattice of cell corners, so one
corner re-tiles four cells and a stroke rewrites cells the cursor never
touched — that is how the seam against existing terrain updates.

## Crash resistance and opening code

A syntax error in an engine module the editor imports used to kill it above
`QApplication`, so launched from a shortcut the window never appeared.
`editor/preflight.py` `ast.parse`s those modules (never imports), confirms
each still declares the names the editor binds, and reports file, line and
message; it imports only `os`, `ast` and `sys`, and `tools/check_editor.py`
asserts its contract. It cannot see inheritance across files or dynamic
registration; it catches what stops startup.

`editor/core/ide.py` finds the IDE from JetBrains Toolbox's `state.json` and
known install locations, with **PATH as a last resort** — measured, PATH named
an older PyCharm than the one running, and a stale VS Code shim silently
cold-starts a second, older instance. Command construction is pure; launching
is detached and returns a result rather than raising.

## Where the rest lives

Generated, so read counts there and never in prose: the check roster in
[`CHECKS.md`](CHECKS.md), verbs in [`COMMANDS.md`](COMMANDS.md), ops in
[`EVENTS.md`](EVENTS.md). Unbuilt scene, tileset-screen, trigger and
relay-review work: [`PLAN_SCENES.md`](PLAN_SCENES.md). Everything else open:
[`NEXT.md`](NEXT.md).
