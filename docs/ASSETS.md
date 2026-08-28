<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; every claim re-measured on 2026-08-28 by moving data/graphics aside, running the whole roster and tools/smoke.py --frames 60 both ways, and moving it back. The two commands are named beside each claim -->

# Assets

**Art ships. It is generated, it is tracked, and a fresh clone runs with no
setup step at all.**

What does *not* ship is the art in the author's working copy: that is the RPG
Maker VX Ace RTP, and redistributing it is not permitted. So this repository
carries two roots and reads them in order.

## The two roots

| root | what is in it | tracked? | wins? |
|---|---|---|---|
| `data/graphics/` | **your** art, or the author's | never, in whole or in part | yes, whenever it holds the file |
| `data/art/` | the generated pack | yes, every byte of it | only when the first does not |

`#TAG:resolve_art` is the whole rule: the declared path if a file is there,
its twin under `data/art/` if not, and the declared path back unchanged when
neither has it, so the error still names what the author wrote. The mapping
between the two is one prefix swap — `data/graphics/tilesets/System/TileA2.png`
has its twin at `data/art/tilesets/System/TileA2.png` — spelled once, in
`#TAG:shipped_relative`.

Three readers go through it, which is every path by which a pixel enters this
engine: `#TAG:tileset_image_loader` (pytmx opens a `<tileset>`'s image itself,
so that hook is the only seam a tmx has), `BlitmapRuntime`'s sheet load for a
native `.blitmap`, and `DataAnimationCategory`'s `file`, resolved once so both
the animation cache and `#TAG:GameAnimationHandler.__init__` open the same
image.

### Why two roots and not a `.gitignore` exception

Measured, and it is the reason the licence rule is still one line anybody can
hold. A negation would have to name the exact path a licensed sheet occupies
on the author's machine — `!data/graphics/tilesets/System/TileA2.png` — so
`git add` would stage **his** file. Instead `.gitignore` keeps its single
unqualified `data/graphics/` and the pack lives somewhere else entirely.
`#TAG:art_no_negation` says the same thing next to the code, and
`tools/check_art.py` asserts both halves with `git check-ignore`: the licensed
root is ignored, every shipped sheet is not.

## What ships

Six sheets, 65 KB in total, every pixel of every one of them computed by a
function in `tools/art/`. Nothing is copied, traced, downsampled or recoloured
from anything; the generator is the asset and the `.png` is its output, and
the two generator checks prove it by making `pygame.image.load` raise for the
duration of a build.

| `data/art/…` | size | what it is |
|---|---|---|
| `tilesets/System/TileA2.png` | 512×384 | terrain. 8×4 blocks of 4×6 quadrants, 32 terrains, a Wang **corner** set satisfying `editor/core/autotile.py`'s QUADRANT table exactly |
| `tilesets/System/TileC.png` | 512×512 | clutter and props on a straight 16px grid, including a 2×3 tree whose canopy sorts above a walking body and whose trunk sorts below |
| `tilesets/Characters/~Garet.png` | 176×256 | the four-direction body: eight sequences, 44×64 frames, on the grid `config/animations.json` declares |
| `tilesets/Characters/Sidestep.png` | 176×256 | a side-on body for a platformer. **Reachable by nothing yet** — see below |
| `tilesets/System/Collision.png` | 272×16 | the mask palette, one 16px tile per mask. Nothing renders these pixels; the file has to exist because pytmx opens every `<image source>` it parses |
| `tilesets/System/Parallax.png` | 512×256 | a dusk band as a **tileset**, seamless in x. `MAP_DEPTH`'s Parallax layer is a tile layer drawn from map gids; nothing in this engine blits a background image |

### The one command

    .venv/Scripts/python.exe -m tools.art                write the pack
    .venv/Scripts/python.exe -m tools.art --list         say what it would write
    .venv/Scripts/python.exe -m tools.art --force        redraw after editing a generator
    .venv/Scripts/python.exe -m tools.art.sprites        one module's sheets only

On a checkout that already carries the tracked pack this writes nothing and
says so. `--force` is what to run after changing a generator, and
`tools/check_art.py` fails if the tracked bytes are no longer the generator's
output — so a generator edited without a redraw cannot ship art this tree
cannot reproduce.

It writes under `data/art/` and **cannot reach `data/graphics/`**: every sheet
key names the path the *engine* looks for, and the CLI re-roots each one
before writing. That is why running it on a machine holding real art cannot
change a single rendered pixel.

## Supplying your own

Drop a file at the path under `data/graphics/` that the config or the map
declares. It wins outright, and nothing has to be told. Removing it again
falls back to the pack.

Nothing requires the pack's layout: animation frame rectangles are declared in
`config/animations.json` (`x`, `y`, `width`, `height` per sequence), so any
sheet works as long as the config describes it, and
`#TAG:GameAnimation.slice_frames` clips every frame to the sheet and raises
`ValueError` naming the sequence and frame if one falls outside rather than
silently producing an empty sprite. For maps, Tiled needs the tileset images
at the `source` paths recorded in the `.tmx`, which means under
`data/graphics/`; `scripts/loaders/map_document.py` can rewrite those paths
programmatically without reflowing the rest of the file.

## Why the author's own art is not here

The art present in the author's working copy matches the RPG Maker VX Ace RTP,
by filename and by exact pixel dimensions:

| File | Size on disk | RTP spec |
|---|---|---|
| `TileA2.png` | 512×384 | match |
| `TileC.png` | 512×512 | match |
| `Actor1.png` | 384×256 | match |
| `People1.png` | 384×256 | match |
| `IconSet.png` | 384×3072 | match |

plus verbatim RTP filenames throughout — `Actor1-3`, `People1-5`, `Monster`,
`TileA1-A5`, `TileB-E`, `Balloon`, `Vehicle`, `Damage`, `Window`.

That licence permits using the art inside a project built with RPG Maker. It
does not permit redistributing the art itself, which is what publishing it in
a public repository would do — and unlike a bad commit, that cannot be undone,
because clones and forks outlive a deletion. `data/graphics/` is therefore not
in this repository and is not in its history, and `git ls-files data/graphics`
returning nothing is an assertion in `tools/check_art.py`.

## What was measured, and how to measure it again

Both cases, on 2026-08-28, by moving `data/graphics` aside and back:

- **A tree with no `data/graphics/` at all** boots and runs 60 frames, and
  `tools/check_all.py` reports `FAILED: []` — the whole roster, not a subset.
  Its `frame_hash` is not the baseline's, because the shipped art is different
  art from the author's; that is the pack working, not a regression.
- **The author's working copy** renders `frame_hash 8fb62986f72fc71c` and 43
  blit tokens, identical to `tools/baseline.json` in every field except the
  one `dispatch_during_boot` difference that is already there at `793b82d`
  before any of this. His three sheets keep their exact sha256 and their
  original mtimes: nothing in the pack writes into that directory.

**There is no longer an art-dependent subset of the roster.** A `needs_art`
flag on the roster has nothing left to describe: the pack is tracked, so every
check has art. Two checks reached past it and would have kept that claim
false — `check_blitmap`'s `REAL_IMAGE` and `check_blitmap_engine`'s staged
workspace copy both hard-coded a `data/graphics/` path — and both now go through
`#TAG:resolve_art`, so they read whichever real sheet the checkout has.

## Where the paths live

| What | Where |
|---|---|
| entity spritesheet | `config/animations.json` → `entity.file` |
| map tilesets | `<tileset source=...>` inside `data/maps/test.tmx` |
| map file list | `config/maps.json` → `data[].file` |
| the two roots | `#TAG:scripts/core/art.py` — `GRAPHICS_ROOT`, `SHIPPED_ROOT` |
| resolution | `config/managers/map_data.py` resolves relative to the repo root |

## Known holes

- **`Sidestep.png` is a sheet no map can select.** Two walls, neither of them
  art: `main.py`'s `spawn_arguments` hardcodes the animation category
  `entity`, so every `GamePlayer` on every map gets the same sheet; and
  `#TAG:GameAnimationHandler.__init__` starts `idle_down` before any behavior
  attaches, so a genuinely side-on category would raise inside the entity
  constructor. The sheet accommodates the second — its `down` row is the
  right-facing walk, pixel for pixel — and closing either wall is an engine
  change, not an art one.
- **The clutter sheet leaves most of its rows transparent.** Deliberate: a
  tileset is an address space and filler tiles only make gids harder to read.
  An existing map whose gids point into that region draws nothing there.
- **No animated water.** Nothing in this engine reads a frame table for a
  tile, so an animated terrain sheet would have no reader.
- **Sound is not covered.** `data/sounds/` is untouched by any of this.

## Recovering the original tree

The pre-strip history is retained locally as `refs/original/refs/heads/main`
in the author's clone. It is not pushed.

    git checkout refs/original/refs/heads/main -- data/graphics
