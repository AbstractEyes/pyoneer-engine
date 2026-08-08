# Pyoneer

A 2D game engine built on [pygame](https://www.pygame.org/), written by hand.

Its distinguishing idea is that **rendering is a sorted queue, not a surface
stack**. Nothing draws to the screen directly. Every drawable object pushes a
`BlitToken` into a global pool keyed by depth and priority, and the renderer
flattens the whole frame into a single `surface.blits()` call. Layers are a
sort key. That makes a frame *data* before it is pixels, which is why this repo
can assert things like "55 blit tokens across 9 depths, 4 culled" instead of
comparing screenshots.

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

Working, and honest about where it is not. ~12,350 lines of tracked Python.

| | |
|---|---|
| Runs | yes — headless or windowed, on pygame 2.6 / Python 3.11 |
| Tested | 12 check tools plus a frame-level regression harness |
| Stable API | **no.** Names are still moving. See [Known rough edges](#known-rough-edges) |
| Docs | design plans in [`docs/`](docs/), all reconciled against the code |

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

At this point `python main.py` **will fail**, because the art is missing. It
fails with a message that says so:

```
PyoneerAssetMissingError: tileset image
  'data/graphics/tilesets/System/TileA2.png' not found
    via map='test', tmx='data/maps/test.tmx',
        hint='the repository ships without art; see docs/ASSETS.md'
```

To get running immediately, generate placeholders:

```bash
.venv/Scripts/python.exe tools/make_placeholder_art.py
.venv/Scripts/python.exe main.py
```

Three checkerboard PNGs, sized to what the config and the map declare. The
engine boots and every check passes. Replace them with your own art at the
same paths whenever you like — nothing requires the original layout, because
animation frame rectangles are declared in `config/animations.json`.

Controls in the demo scene: **WASD** move, **F1** toggles the test window,
**←/→** rotate the player, **Esc** quits.

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
  un-normalized in that one case. Entity layers still interleave. Measured on
  the demo map: 6.21 ms → 3.25 ms per frame, byte-identical output.
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
doc.save()
```

Load-and-save of the shipped 133,940-byte map reproduces it exactly, including
its inconsistent indentation and CRLF endings, and add-object-then-remove
returns the original bytes. That matters because the intent is for a human to
edit in Tiled while a script edits programmatically — a writer that reflows the
file makes every subsequent human diff unreadable.

## Testing

```bash
.venv/Scripts/python.exe tools/check_all.py
```

12 checks plus a frame-level drift comparison, one exit code. They are not unit
tests; each one boots or drives real engine code and asserts measured
behaviour — token counts, dispatch counts, frame hashes, pixel equality.

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

Without art, 6 of the 12 checks pass; the other 6 boot the engine and need the
three image files. `tools/make_placeholder_art.py` is enough for all 12.

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
  scene/                      scene graph
  ui/widget/                  widgets, containers, mouse/keyboard behaviours
scripts/game/               entities, animation, camera, map
scripts/loaders/            MapDocument — TMX read/write
config/                     JSON: animations, entities, inputs, maps, theme
tools/                      checks, smoke harness, utilities
docs/                       design plans and the code review
archive/                    two superseded component generations, kept for reference
```

## Known rough edges

Stated plainly, because most of them are recorded with measurements in
[`docs/`](docs/):

- **`GameComponent` is a god class.** ~9 responsibilities in one file. Being
  split incrementally; `docs/IMPROVEMENT_PLAN.md` segment 8.
- **Boot costs ~640 ms**, up from ~230 ms, because map compositing proves its
  merges are lossless with `pygame.mask` work at startup. One-time cost buying
  2.6 ms per frame; pays back in ~150 frames. Not yet optimized.
- **Grid and listbox do not work.** `GridComponent` is stubs with no layout
  engine; `ListBoxComponent` depends on it and has never run.
- **Window resize is unimplemented.** Move and close work.
- **The scroll bar builds from the wrong formula** and shifts 14 px on its
  first scroll event.
- **The demo map has an invisible parallax layer** — its tiles sit beneath a
  fully opaque floor.
- **`archive/gen3_behavior_rewrite/`** is an unfinished redesign that never
  executed. It is kept because its direction was right; see
  `archive/README.md`.

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

The code has no licence file yet, so default copyright applies: all rights
reserved by the author until one is added. Ask before reusing it.

No third-party art is included. See [docs/ASSETS.md](docs/ASSETS.md).
