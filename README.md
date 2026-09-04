# Pyoneer

A 2D game engine built on [pygame](https://www.pygame.org/), written by hand.

Its distinguishing idea is that **rendering is a sorted queue, not a surface
stack**. Nothing draws to the screen directly. Every drawable object pushes a
`BlitToken` into a global pool keyed by depth and priority, and the renderer
flattens the whole frame into a single `surface.blits()` call. Layers are a
sort key. That makes a frame *data* before it is pixels, which is why the
regression harness can record a blit-token histogram keyed by depth, and a
per-frame count of listener invocations, instead of comparing screenshots.

```
python main.py
```

is the whole entry point. It needs no `PYTHONPATH` and no install step.

> **This repository ships without art.** The engine reads three image files at
> runtime and none of them are here — see [Running it](#running-it). The
> previous art matched the RPG Maker VX Ace RTP, which cannot be redistributed,
> so it was removed from the repository and its history. See
> [docs/ASSETS.md](docs/ASSETS.md).

---

## Status

Working, and honest about where it is not. 78,094 lines of tracked Python
across 201 files — `tools/` 38,102, `scripts/` 20,068, `editor/` 17,348.

| | |
|---|---|
| Runs | yes — headless or windowed, on pygame 2.6 / Python 3.11 |
| Tested | 54 check tools plus a frame-level regression harness |
| Stable API | **no.** Names are still moving. See [Known rough edges](#known-rough-edges) |
| Docs | [`docs/`](docs/), reconciled against the code and layered: generated files regenerate from the registry that executes them, hand-written ones carry a dated stamp, and finished plans move to [`docs/history/`](docs/history/) with an exemption banner |

This is a personal engine being cleaned up in public, not a released library.
It is usable, and reading it will teach you something about deferred
rendering — but pin a commit if you build on it.

## Running it

```bash
git clone https://github.com/AbstractEyes/pyoneer-engine
cd pyoneer-engine
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # pygame, pytmx
```

That is the whole setup. `python main.py` runs:

```bash
.venv/Scripts/python.exe main.py
```

Art ships, and it is generated — six sheets under `data/art/`, tracked, every
pixel of them computed by a function in `tools/art/`. Replace any of them with
your own by dropping a file at the path the config or the map declares, under
`data/graphics/`: that root wins whenever it holds the file, and the pack
answers when it does not. Nothing requires the pack's layout, because
animation frame rectangles are declared in `config/animations.json`.
[`docs/ASSETS.md`](docs/ASSETS.md) is the whole story, including why the
author's own art is not in here.

Controls in the demo scene: **WASD** move, **Ctrl** sprint, **F1** toggles the
test window, **←/→** rotate the player, **Esc** quits. Bindings live in
`config/inputs.json` and are validated at load, so a typo raises rather than
producing a key that silently does nothing.

## How rendering works

The part worth understanding before reading anything else.

```
  entity / widget / map layer
        │  core_render_blits(event)
        ▼
  BlitPool.blit_to_layer(depth, priority, image, destination, draw_area)
        │
        ▼
  ORGANIZED_BLITS[depth][priority] → [BlitToken, ...]
        │  flattened in depth → priority → insertion order
        ▼
  surface.blits(...)          ← one call, once per frame
```

Consequences that surprise people:

- **Draw order is an integer, not a tree position.** A widget nested five deep
  can draw beneath the map by setting a lower depth. `GameComponent.depth`
  accumulates through the parent chain, so a subtree moves together.
- **Culling and clipping are one operation.** `scripts/core/viewclip.py` gives
  `clip_to_view(target, clip, source_origin)`, which returns the destination
  *and* the source sub-rect already reduced to visible pixels, or `None` when
  nothing is visible. A caller cannot cull without clipping or vice versa,
  which is how the two used to drift apart.
- **Static map layers are composited.** Runs of consecutive tile-only depths
  are flattened into one surface, but only when it is provably lossless —
  `composite_is_exact()` refuses a merge where partial alpha would land on
  partial alpha, because pygame's RGBA blitter writes the blended colour back
  un-normalized in that one case. Entity layers still interleave, and
  `check_maplayers` asserts the merged output is byte-identical to the
  unmerged one. (Earlier drafts of this file quoted a per-frame speedup for
  this; no measurement in the tree supports the figure, so it is not repeated
  here. The startup cost it buys **is** measured — see
  [Known rough edges](#known-rough-edges).)
- **Compositing is invalidatable.** `renderer.invalidate(band)` and
  `rebake_map()` exist so runtime map editing is possible; the bake is not
  hidden in a constructor.

## Lifecycle

Every engine object implements the same schema —
`core_<domain>_<action>[_<phase>]`, four domains:

| | |
|---|---|
| `core_lifecycle_` | `build`, `prepare`, `prepare_pre`, `prepare_post`, `dispose`, `dispose_pre`, `dispose_post` |
| `core_frame_` | `update`, `update_pre`, `update_post` |
| `core_render_` | `blits` |
| `core_input_` | `receive` |

The phase is a **suffix** so autocomplete groups each family together.

**These are not a general extension point**, and this is the single most
important thing to know before subclassing. They are entry points for objects
driven from *outside* the component graph — scenes, layers, entities, and the
root component bound into a layer. A `GameComponent` reached through a parent's
`components` dict is driven by the event bus, which never calls them. An
override there is dead code that neither runs nor errors. In-tree components
register behaviour instead:

```python
self.bind_sync_listener(GameEventType.UPDATE, self.__on_update)
```

The exception: `bind_component()` calls `core_lifecycle_prepare*` and
`core_lifecycle_build` on the child *directly*, so those specific overrides do
run at bind time — which is how most of the widget tree gets built.

## Failing loudly

The engine was originally quiet by default, which is right for prototyping and
wrong once someone else is reading. Now:

| | | |
|---|---|---|
| **raise** | contract violations | `scripts/core/errors.py` |
| **warn** | unusable authored content | `warnings` module |
| **trace** | running commentary | opt-in, off by default |

Every exception is prefixed `Pyoneer`, so the prefix enumerates the surface:
`PyoneerAssetMissingError`, `PyoneerEventDispatchError`,
`PyoneerListenerContractError`, `PyoneerImageMissingError`,
`PyoneerLayerError`, `PyoneerCameraMissingError`, `PyoneerBindTargetError`, …
grouped under catchable domain bases.

Errors accumulate context as they travel up a dispatch chain, so a failure
deep in a fan-out reads as a path:

```
map 'x' not found; available: test
    via source='config/maps.json'
    via component='Panel', child_slot='body'
    via parent='GameWindow', child_slot='panel'
```

Tracing is per-subsystem and costs nothing when off:

```bash
PYONEER_DEBUG=mouse python main.py
PYONEER_DEBUG=mouse,events,render python main.py
PYONEER_DEBUG=all python main.py
```

Channels: `mouse`, `keyboard`, `events`, `render`, `input`, `lifecycle`,
`assets`. A mistyped channel name raises rather than silently producing
nothing.

## Maps

`data/maps/test.tmx` is a [Tiled](https://www.mapeditor.org/) map. pytmx reads
it; pytmx cannot write it. So `scripts/loaders/map_document.py` is a
**byte-identical** TMX reader/writer on `xml.etree`:

```python
doc = MapDocument.load("data/maps/test.tmx")
doc.tile_layer("Floor").set_tile(4, 7, gid=65)
doc.object_layer("entity").add_object(name="chest", type="Chest", x=128, y=96)
doc.add_layer("Collision", kind="tile")
doc.add_tileset("props", "../graphics/props.png")   # geometry is measured
doc.grow_tileset("props", tile_count=96)            # rows only, headroom checked
doc.rename_tileset("props", "Village props")
doc.save()
```

Load-and-save of the shipped map reproduces it byte for byte, including its
inconsistent indentation and CRLF endings, and add-then-remove — of an object,
a layer or a tileset — returns the original bytes. That matters because the
intent is for a human to edit in Tiled while a script edits programmatically:
a writer that reflows the file makes every subsequent human diff unreadable.

There is also a **native format**, `scripts/loaders/blitmap.py` and
`tileset_file.py`: `.blitmap` and `.tileset` are tab-indented plain text that
parse with no pygame, no pytmx and no Qt, plus a converter that carries a
`.tmx` across losslessly and *names* in `Conversion.dropped` anything it
cannot. `config/managers/map_data.py` dispatches on the extension, so the
engine loads either one; `check_blitmap_engine.py` asserts the two readers
produce the same layers, gids, properties and tile pixels. What a `.blitmap`
does not carry is collision: it has no companion layers, and the
`pyoneer_collision` reference its `.tileset` records is opened by nothing.

## The editor

```bash
.venv/Scripts/python.exe -m pip install -r editor/requirements.txt
.venv/Scripts/python.exe editor/app.py
```

A separate PySide6 application for authoring maps, entities and game data —
and for handing work to an AI in a form it can act on. It is a different
process from the game; `File > Play` launches `main.py` as a subprocess.

Its one structural idea: **every change is a command.**

```
  a click on the canvas    ─┐
  a cell edited in a table ─┼──►  Command  ──►  validate  ──►  apply  ──►  inverse
  a line of response.jsonl ─┘                      │                         │
                                                   └── raise, roll back ─────┘
```

Applying a command returns *the command that undoes it*, so the undo stack is
a readable, serialisable list rather than a pile of snapshots. A human edit
and an AI's edit are indistinguishable in the history, because they are the
same kind of thing.

Every panel carries a prompt strip and knows its own scope
(`map:test/layer:Floor`, `table:actors/row:hero`). Typing there leaves a note
addressed to that scope — a code review comment on the project rather than on
a diff. Notes accumulate in the Manifest panel; shipping them writes a
self-contained request bundle:

| file | what it is |
|---|---|
| `BRIEF.md` | the response contract |
| `RULES.md` | the genre's conventions — the conditioning |
| `CONTEXT.md` | the live state of every scope the notes touch |
| `REQUEST.md` | the notes, grouped, each with the files that own them |
| `COMMANDS.md` | **generated from the registry that executes it** |

That last row is the point. A hand-written interface document is the thing
most likely to drift out from under a model that trusts it; here a verb the
editor cannot run cannot appear in the docs, and `tools/check_editor.py`
asserts it.

A response is applied as one transaction. Unknown verb, unknown argument,
missing argument or wrong type rejects the whole thing — nothing is ever
half-applied, and types are never coerced (`"5"` is not `5`).

### Tilesets, painting and collision

The tile palette is one scrolling column holding **every** tileset the map
declares, each under a header naming it and its tile count. A drag picks a
multi-tile stamp, clamped to the sheet it started in, and the selection is
remembered as a tileset *name* plus a rectangle in that sheet's own local ids
— so a command cannot slide the highlight onto a different sheet's tiles.

**A tileset is built from a region of any image.** Drag a rectangle over the
picture, nudge its offset, resize it, truncate a ragged last row, and commit:
the selected pixels are cropped to a PNG beside the map and declared as a
plain `margin=0 spacing=0` grid over that file. That is deliberate rather than
lazy — measured, the editor's atlas and pytmx agree about which pixels a gid
names *only* at margin 0, spacing 0 and a full-width column count, and two
readers disagreeing about what a gid looks like raises nowhere.

**A tileset grows** by pointing it at a taller sheet at the same width:
`map.tileset.grow` rewrites the image and the tile count and nothing else, so
no placed gid moves. A *wider* sheet is refused, because a local id is
`row * columns + column` and widening renumbers every id after the first row —
silently, with the right schema and the wrong art everywhere. Growth into
another tileset's gid range is refused for the same reason, and the refusal
prices the alternative; `map.tileset.add` takes an explicit `first_gid`, so a
map can reserve headroom under each range and make growth free.

**Collision is a brush, not a layer.** A mask is stored as `first_gid + mask`
in a companion tile layer — an ordinary gid — so a collision stroke reuses the
very same `paint.Stroke`, commits the very same `map.tile.set_many`, and
inherits one-drag-one-transaction undo and an exact inverse for free. The
companion is created by the first stroke that needs it, inside the same
transaction. It has no row in the hierarchy: it declares `pyoneer_renders=false`
and nothing draws it, so its row offered a checkbox that changed nothing and a
selectable target that swallowed art. The art layer carries a mask-count badge
instead, and the badge turns to a warning when those masks reach no field.

A tile can also carry its own mask, and that is the one that scales: stamping
the tile *is* authoring the collision, so a companion cell stops meaning "this
is a wall" and means only "not THIS one". Pick a mask swatch and click the
tile in the palette, or shift+click the wall on the map. Erasing writes gid 0,
which in a companion means `NO_DATA` — "nobody said anything here" —
deliberately not the same claim as "open", and the palette gives each of those
two its own keyline because they draw the same glyph and mean opposites.

Terrain painting is a Wang **corner** set rather than an orthogonal bitmask,
because the art demands it; a whole terrain is one integer, so choosing one is
"click any tile of it". See [`docs/PLAN_EDITOR.md`](docs/PLAN_EDITOR.md) for
the half-cell trap that follows from corner lattices.

The whole tileset surface — the palette, region import, growth, naming, tile
masks and where the collision layer went — is
[`docs/TILESETS.md`](docs/TILESETS.md).

Genre packs in `editor/genres/` declare what a genre's maps and data look
like, so "make me a platformer with guns and aliens" costs a page of
conditioning rather than a thousand-line prompt. Two ship: `topdown_rpg` and
`platformer`.

Design and reasoning: [`docs/PLAN_EDITOR.md`](docs/PLAN_EDITOR.md).

## Testing

```bash
.venv/Scripts/python.exe tools/check_all.py
```

54 checks plus a frame-level drift comparison, one exit code. They are not unit
tests; each one boots or drives real engine code and asserts measured
behaviour — token counts, dispatch counts, frame hashes, pixel equality.

A check here is expected to have **teeth**: the convention is that whoever
writes one breaks the code it covers and confirms it goes red. That is not
ceremony. Reviews of this repository have now found five assertions that
could not fail — one comparing a value against the constructor argument it
came from, one driving a single frame where the property under test only
appears on the second, one asserting identity against a pygame singleton that
`set_mode` mutates in place and returns unchanged.

`tools/smoke.py` is the instrument the rest rely on. It runs N frames headless
and reports a frame hash, the component census, the blit-token histogram by
depth, culled-draw count, and listener invocations per frame. A structural
change that leaves the frame hash identical is *not* automatically harmless —
the same pixels can be produced by a different amount of work — so the dispatch
counters exist to catch that.

Deliberate visual changes are re-baselined explicitly:

```bash
.venv/Scripts/python.exe tools/smoke.py --frames 60 --write-baseline
```

There is no art-dependent subset of the roster: the generated pack is
tracked, so a clone has art before it runs anything. Measured by moving
`data/graphics` aside and re-running the whole suite, not estimated.

`check_editor_ui` reports SKIP rather than PASS when PySide6 is absent — a
check that did not run has proved nothing.

## Layout

```
main.py                     entry point and the demo scene
scripts/core/               engine
  game_object.py              root ABC, the core_* lifecycle contract
  component.py                GameComponent — the UI base class (large; being split)
  blitpool.py                 the deferred blit queue
  renderer.py                 layers, map baking, compositing
  viewclip.py                 containment + exact-pixel clipping
  event_manager.py            pygame event → PyoneerEvent
  errors.py                   exception hierarchy
  log.py                      opt-in trace channels
  input.py                    action bindings, edge detection, text capture
  spawn.py                    tmx object class -> entity, and its depth
  scene/                      scene graph
  ui/widget/                  widgets, containers, mouse/keyboard behaviours
scripts/game/               entities, animation, camera, map
scripts/loaders/            no pygame, no Qt: bytes on disk <-> plain Python
  map_document.py             MapDocument — byte-faithful TMX read/write
  map_loader.py               a loaded map -> spawned entities
  blitmap.py                  the native .blitmap format and a tmx converter
  tileset_file.py             the native .tileset format and asset interning
config/                     JSON: animations, entities, inputs, maps, theme
editor/                     the authoring application (PySide6; separate process)
  core/                       headless: scopes, commands, genres, requests
    collision.py                masks, three-level resolution, .blitmask
    map_events.py               trigger vocabulary (authored; no runtime)
  genres/                     genre packs — layers, tables, rules, art briefs
  ui/                         Qt panels; views only, no authority
tools/                      checks, smoke harness, utilities
docs/                       layered docs; history/ holds the dated archives
```

`editor/` may import `scripts/`. `scripts/` may never import `editor/` —
`tools/check_editor.py` asserts it, so `python main.py` works on a clone with
the editor deleted.

## Known rough edges

Stated plainly, because most of them are recorded with measurements in
[`docs/`](docs/):

- **A collection-of-images tileset draws wrong in the editor.** A `<tileset>`
  built from `<tile><image/></tile>` children reads correctly in `MapDocument`
  and renders correctly through pytmx; the editor's atlas draws procedural
  colour swatches for it and warns about nothing. This editor never writes
  that shape, but Tiled does.
- **Map event triggers are authored and never executed.**
  `editor/core/map_events.py` is a complete, checked vocabulary and
  `editor/ui/actions_panel.py` now offers it — and nothing in `scripts/` reads
  a `pyoneer_trigger`, so an authored trigger is data with no runtime.
- **`GameComponent` is a god class.** ~9 responsibilities in one file. Being
  split incrementally; `docs/history/IMPROVEMENT_PLAN.md` segment 8.
- **Boot costs ~350 ms**, most of it map compositing proving its merges are
  lossless with `pygame.mask` work at startup. Measured headless on the demo
  map: five fresh processes, 330–446 ms to construct the game, of which one
  full `rebake_map()` is 243–252 ms. Not yet optimized, and do not optimize it
  by caching the proof — that was tried and it broke live map editing.
- **Listbox does not work.** `ListBoxComponent` has never run. The grid it
  needs now exists and it already builds one; what is missing is its own row
  selection (it declares three selection fields and assigns none), keyboard
  navigation and a row template.
- **The scroll bar builds from the wrong formula** and shifts 14 px on its
  first scroll event — measured live, `docs/history/IMPROVEMENT_PLAN.md`. The
  `Button`'s body surface keeps its construction-time size, so the graphic is
  drawn 14 px taller than its logical bounds as well as offset from them.
- **No drag-and-drop.** `GridComponent.snap()` places by pixel position and
  `MOUSE_DRAG_BEGIN`/`END` are bindable, but nothing wires them together.
- **The editor cannot edit shape geometry.** Polygon, ellipse and text
  objects are shown and preserved byte-exactly; their points are read-only.

`docs/NEXT.md` is the ranked list of what is actually next.

## Contributing

The bar is measurement. This codebase has a documented history of confident,
plausible, wrong claims — including in its own docs, several of which were
corrected by executing the code they described. So:

- Run `tools/check_all.py` before and after.
- If a smoke field moves, say which one, from what to what, and why. Do not
  re-baseline something you cannot explain.
- Prefer a raise over a fallback. A plausible wrong value is the failure mode
  this engine keeps producing.
- Make a test that can fail. Break the thing it covers and confirm it catches
  it — several assertions here passed vacuously until that was checked.

## Licence

[Apache License 2.0](LICENSE). Copyright 2023-2026 AbstractPhil.

Use it, fork it, ship a game with it, ship a closed-source game with it. The
conditions are the usual Apache ones: keep the licence and copyright notice,
state what you changed, and don't use the project's name to endorse yours.
Apache-2.0 rather than MIT because it grants patent rights explicitly, which
matters for something people build tools on top of.

**The licence covers the code, not content you load into it.** Art, audio and
maps carry whatever licence their author gave them. No third-party art is
included here — see [docs/ASSETS.md](docs/ASSETS.md) and [NOTICE](NOTICE).

pygame and pytmx are dependencies, not bundled, and are both LGPL. Linking to
them from Apache-2.0 code is fine; if you redistribute a build that bundles
them, their terms apply to those parts.
