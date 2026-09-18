<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; re-measured 2026-09-18 by the commands printed beside the claims -- tools/check_art.py PASS, tools/check_art_tilesets.py PASS, tools/check_art_sprites.py PASS, the PNG headers under data/art/ (all THREE terrain sheets; TileA2_BeatEmUp.png was written and tracked this pass, which check_art asserts rather than merely asserting it is not ignored), `git ls-files data/audio`, and the audio probe named under "Audio". The byte total was dropped rather than corrected: nothing re-measures it. -->

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

Eight sheets, every pixel computed by a function in `tools/art/`. Nothing is
copied, traced or recoloured from anything; the generator is the asset and
the `.png` is its output.

There is deliberately **no byte total** here any more. The one that used to
be was 43 bytes out, because a total in a hand-written document goes stale
the first time anybody edits a generator and nothing in `tools/check_docs.py`
re-measures it -- `grep -n "byte count" tools/check_docs.py` returns nothing.
The DIMENSIONS below do not drift silently: `tools/check_art.py` opens every
sheet and asserts its size, so those are claims with a check behind them.

| `data/art/…` | size | what it is |
|---|---|---|
| `tilesets/System/TileA2.png` | 512×384 | terrain seen from the SIDE: 32 terrains as a Wang **corner** set satisfying `editor/core/autotile.py`'s QUADRANT table. Each one is a colour, a texture and a FORM -- the silhouette its corners cut. No two blocks that TOUCH share a texture or a form, no two of the thirty-two sit closer than `TERRAIN_DISTANCE` in CIELAB anywhere on the sheet, and every block marked `hazard` stays clear of every walkable one under both simulated red-green dichromacies |
| `tilesets/System/TileA2_TopDown.png` | 512×384 | the SAME 32 materials in the SAME block order, seen from ABOVE. Identical geometry -- a view changes the surface, never the silhouette, and the alpha of the two sheets is equal pixel for pixel -- but a different lighting model and a different texture family: a flat-lit top face with one short drop shadow, at the single `SHADOW_OFFSET` every feature on the sheet shares; clumps instead of blades, pavers instead of courses, and a dominant direction only where it means one, held under `ISOTROPY_LIMIT` (and under `PROFILE_LIMIT`, the whole-cell operator that sees a broad feature a gradient cannot) with the deliberate three exempt by name and asserted to exceed one of the two. Every rule the first sheet satisfies is measured again on this one -- `_verify_pack` runs them per view -- and four more are measured on this one alone, because they are about ground rather than about a face: no row keeps a findable shape once its cell is blurred (`REPEAT_LIMIT`), no two rows draw the same picture in different colours (`STRUCTURE_LIMIT`), every island edge falls (`RIM_FALL`), and every scattered feature is ONE feature and not a fused glyph (`_verify_specks`). The `_TopDown` suffix is deliberate: `resolve_art` answers with the declared path first, so a sheet named after an RPG Maker RTP file would be shadowed by the author's own art and never drawn |
| `tilesets/System/TileA2_BeatEmUp.png` | 512×384 | a THIRD 32, and the first sheet that is not the other thirty-two relit: urban ground for a belt-scroll stage -- streets, lots, subway platforms, dockyards, a park. Identical geometry again (the alpha of all three sheets is equal pixel for pixel, measured over 5 forms × 13 masks with a mutation that moves 240 pixels to prove the comparison can fail), and a THIRD lighting model: `palette.lowangle`, which is `overhead`'s one drop shadow plus a two-pixel NEAR FACE, the only thing on a 16px tile that says the camera is low. What makes it a floor rather than a plan view is the FORESHORTENING: it is a cabinet oblique at `k = 1/2`, so a world-square paving stone draws 16 across and 8 down, and a joint cut into that plane draws its full width where it runs away from the camera and half of it where it runs across. The ratio is DECLARED, in `FLOORS`, and the renderer is held to the declaration -- three statistics that try to recover it from a finished cell were measured and all three answer wrong, so there is no threshold anywhere in that rule, only equalities on integers. The table is a different FAMILY of materials, which is why `_verify_tables_agree` now runs per family and refuses two families that name the same 32; and `_BeatEmUp` is not an RTP stem, for the same reason `_TopDown` is not |
| `tilesets/System/TileC.png` | 512×512 | clutter and props on a straight 16px grid, including a 2×3 tree whose canopy sorts above a walking body. Its first tiles are the palette swatch strip, and that strip is FROZEN and append-only: it used to be `sorted(BASES)`, which made every clutter gid on the sheet a function of how many colours the palette happened to carry -- adding the 29 urban bases moved them all by 29, and `data/maps/starter.tmx` paints from this tileset. A colour that is not in the strip has to be drawn somewhere else, and `_verify_swatches` is what refuses one that is drawn nowhere |
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
