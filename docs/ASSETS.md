<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; re-measured 2026-09-16 by the commands printed beside the claims -- tools/check_art.py PASS, the PNG headers and byte counts under data/art/, `git ls-files data/audio`, and the audio probe named under "Audio". -->

# Assets

**Art and audio ship. Both are tracked, and a fresh clone runs with no setup
step at all.**

What does *not* ship is the author's own art and audio. The art in his working
copy is the RPG Maker VX Ace RTP, and redistributing it is not permitted. So
each kind of asset has two roots, read in the same order.

## The two art roots

| root | what is in it | tracked? | wins? |
|---|---|---|---|
| `data/graphics/` | **your** art, or the author's | never, in whole or in part | yes, whenever it holds the file |
| `data/art/` | the generated pack | yes, every byte of it | only when the first does not |

`#TAG:resolve_art` is the whole rule: the declared path if a file is there,
its twin under `data/art/` if not, and the declared path back unchanged when
neither has it, so the error still names what the author wrote. The mapping is
one prefix swap -- `data/graphics/tilesets/System/TileA2.png` has its twin at
`data/art/tilesets/System/TileA2.png` -- spelled once, in
`#TAG:shipped_relative`.

Three readers go through it, which is every path by which a pixel enters the
engine: `tileset_image_loader` in `config/managers/map_data.py` (pytmx opens a
`<tileset>`'s image itself, so that hook is the only seam a tmx has),
`BlitmapRuntime`'s sheet load for a native `.blitmap`, and
`DataAnimationCategory`'s `file`, resolved once so the animation cache and
`#TAG:GameAnimationHandler.__init__` open the same image.

**Why two roots and not a `.gitignore` exception** (`#TAG:art_no_negation`):
a negation would have to name the exact path a licensed sheet occupies on the
author's machine, so `git add` would stage **his** file. `.gitignore` keeps one
unqualified `data/graphics/`, and `tools/check_art.py` asserts both halves with
`git check-ignore`: the licensed root is ignored, every shipped sheet is not.

## What ships

Six sheets, 66,524 bytes in total, every pixel computed by a function in
`tools/art/`. Nothing is copied, traced or recoloured from anything; the
generator is the asset and the `.png` is its output.

| `data/art/…` | size | what it is |
|---|---|---|
| `tilesets/System/TileA2.png` | 512×384 | terrain: 32 terrains as a Wang **corner** set satisfying `editor/core/autotile.py`'s QUADRANT table |
| `tilesets/System/TileC.png` | 512×512 | clutter and props on a straight 16px grid, including a 2×3 tree whose canopy sorts above a walking body |
| `tilesets/Characters/~Garet.png` | 176×256 | the four-direction body: eight sequences, 44×64 frames, on the grid `config/animations.json` declares |
| `tilesets/Characters/Sidestep.png` | 176×256 | a side-on body for a platformer. **Reachable by nothing yet** -- see below |
| `tilesets/System/Collision.png` | 272×16 | the mask palette, one 16px tile per mask. Nothing renders it; it exists because pytmx opens every `<image source>` it parses |
| `tilesets/System/Parallax.png` | 512×256 | a dusk band as a **tileset**, seamless in x; the Parallax layer is a tile layer, and nothing blits a background image |

    .venv/Scripts/python.exe -m tools.art                write the pack
    .venv/Scripts/python.exe -m tools.art --list         say what it would write
    .venv/Scripts/python.exe -m tools.art --force        redraw after editing a generator
    .venv/Scripts/python.exe -m tools.art.sprites        one module's sheets only

On a checkout that already carries the pack this writes nothing and says so.
`tools/check_art.py` fails if the tracked bytes are no longer the generator's
output. The CLI re-roots every sheet under `data/art/` before writing, so it
**cannot reach `data/graphics/`** and cannot change a pixel on a machine
holding real art.

## Audio

The same two-root rule, in `#TAG:scripts/core/audio.py`:

| root | what is in it | tracked? | wins? |
|---|---|---|---|
| `data/sound/` | **your** audio | never (`.gitignore`) | yes, whenever it holds the file |
| `data/audio/` | the shipped pack: `sfx/chime.wav`, `music/pleasant_moments.ogg` | yes | only when the first does not |

A script names a sound **root-free** -- `"sfx/chime.wav"` -- and
`#TAG:resolve_audio` picks the root; a name that is absolute or contains `..`
raises. Where each shipped file came from and under what licence is
[`data/audio/CREDITS.md`](../data/audio/CREDITS.md). Mixer settings are
`config/audio.json`.

A missing **file** and a missing **sound card** are different failures
(`#TAG:audio_two_failures`): a name neither root holds raises
`PyoneerAssetMissingError` listing both roots' contents, with or without a
card; no card warns once and every play returns False while the game keeps
running. The symptom-side walk is in [`DIAGNOSE.md`](DIAGNOSE.md).

## Supplying your own

Drop a file at the path under `data/graphics/` (or the name under
`data/sound/`) that the config, map or script declares. It wins outright, and
removing it falls back to the pack.

Nothing requires the pack's layout: frame rectangles are declared per sequence
in `config/animations.json`, and `#TAG:GameAnimation.slice_frames` raises
`ValueError` naming the sequence and frame if one falls outside the sheet. For
maps, Tiled needs the tileset images at the `<image source>` paths recorded in
the `.tmx`, which means under `data/graphics/`;
`scripts/loaders/map_document.py` can rewrite those paths without reflowing the
rest of the file.

## Why the author's own art is not here

The art in the author's working copy matches the RPG Maker VX Ace RTP by
filename (`Actor1-3`, `People1-5`, `TileA1-A5`, `TileB-E`, `IconSet`, …) and by
exact pixel dimensions. That licence permits using the art inside a project
built with RPG Maker, not redistributing it -- and a public push cannot be
undone, because clones and forks outlive a deletion. `data/graphics/` is not in
this repository or its history, and `git ls-files data/graphics` returning
nothing is an assertion in `tools/check_art.py`.

## Where the paths live

| what | where |
|---|---|
| entity spritesheet | `config/animations.json` → `entity.file` |
| map tilesets | `<image source=...>` inside each `<tileset>` of `data/maps/starter.tmx` |
| a tileset cropped in the editor | `data/maps/tilesets/<Name>.png` (`#TAG:CROP_DIR`); why it is never cleaned up is in [`TILESETS.md`](TILESETS.md) |
| map file list | `config/maps.json` → `data[].file` |
| the art roots | `#TAG:scripts/core/art.py` -- `GRAPHICS_ROOT`, `SHIPPED_ROOT` |
| the audio roots | `#TAG:scripts/core/audio.py` -- `SOUND_ROOT`, `AUDIO_ROOT` |

## How to re-measure

    .venv/Scripts/python.exe tools/check_art.py
    .venv/Scripts/python.exe tools/smoke.py --frames 60

Run both with `data/graphics` moved aside and again with it back. A bare
clone's `frame_hash` differs from the author's because the art differs; that
is the pack working, not a regression.

## Known holes

- **`Sidestep.png` is a sheet no map can select.** `main.py`'s
  `spawn_arguments` hardcodes the animation category `entity`, and
  `#TAG:GameAnimationHandler.__init__` starts `idle_down` before any behavior
  attaches. The sheet's `down` row is the right-facing walk to accommodate the
  second; closing either wall is an engine change, not an art one.
- **The clutter sheet leaves most of its rows transparent**, deliberately: a
  tileset is an address space, and a gid pointing there draws nothing.
- **No animated tiles.** Nothing reads a frame table for a tile.

The pre-strip history is retained locally as `refs/original/refs/heads/main`
in the author's clone, not pushed:
`git checkout refs/original/refs/heads/main -- data/graphics`.
