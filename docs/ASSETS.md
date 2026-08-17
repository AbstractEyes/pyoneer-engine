<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; art paths re-read at 5dd012d on 2026-08-16, addresses converted to #TAG: at d8c303f, and the art-dependent check list is still [UNVERIFIED] below -->

# Assets

`data/graphics/` is **not in this repository** and is not in its history.

## Why

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
because clones and forks outlive a deletion.

So the engine ships without art. Replacing it with generated or
properly-licensed assets is planned work.

## What a fresh clone is missing

The engine reads exactly **three** image files at runtime. Without them,
`main.py` fails in this order (verified against a real fresh clone):

1. **The map, first.** `main.py` calls `load_map()` before it builds any
   entity, and `data/maps/test.tmx` — which **is** tracked, being the author's
   own map — declares two `<tileset>` elements pointing at
   `../graphics/tilesets/System/TileA2.png` (512×384) and `TileC.png`
   (512×512). `#TAG:AssetMapManager.load_assets` raises
   `PyoneerAssetMissingError` naming the file and pointing here.
2. **Then the entity spritesheet.** `config/animations.json` points the default
   entity animation at `data/graphics/tilesets/Characters/~Garet.png` and
   `#TAG:GameAnimationHandler.__init__` loads it eagerly, raising
   `PyoneerAssetMissingError` naming the config key that declared it.

The roster is generated into [`CHECKS.md`](CHECKS.md); do not restate its size
here, because that number has been stale in this file twice.

Seven checks boot the engine and so need the art: `animation`, `maplayers`,
`singletons`, `tmx_roundtrip`, `viewclip`, `window_close`, `window_events`.

That split was MEASURED, not estimated -- the art directory is moved
aside and the suite re-run. The previous figure here named ten checks
including `anchor`, `events` and `window`, none of which actually need
it; it was arithmetic carried forward as the suite grew rather than
anything anyone had run.

**[UNVERIFIED] — the seven were measured against a much smaller roster and
nothing re-measures them.** The roster has roughly doubled since; read its
current size from [`CHECKS.md`](CHECKS.md), which is generated, and treat the
seven as a lower bound rather than a list. The roster carries no `needs_art`
flag, so this list cannot be generated; adding that flag is the fix, and it is
listed as a known gap in [`../CLAUDE.md`](../CLAUDE.md). Re-measuring it costs
one move of `data/graphics` aside and one full suite run — which is why nobody
has, and why the marker above stays until somebody does.

The two editor checks are among those that do not: the editor reads maps
through `MapDocument`, which is pure XML, and its canvas falls back to
deterministic colour swatches per gid when a tileset image is absent. So the
editor is usable on a bare clone — visibly unfinished, but usable.

The fastest fix is `tools/make_placeholder_art.py`, which writes all three at
the required sizes; with it, the whole roster passes.

## Where the paths live

| What | Where |
|---|---|
| entity spritesheet | `config/animations.json` → `entity.file` |
| map tilesets | `<tileset source=...>` inside `data/maps/test.tmx` |
| map file list | `config/maps.json` → `data[].file` |
| resolution | `config/managers/map_data.py` resolves relative to the repo root |

## Supplying your own

Drop replacements at the paths above. Nothing requires the RTP layout — the
animation frame rectangles are declared in `config/animations.json`
(`x`, `y`, `width`, `height` per sequence), so any sheet works as long as the
config describes it. `#TAG:GameAnimation.slice_frames` clips every frame to the
sheet and raises `ValueError` naming the sequence and frame if one falls
outside, rather than silently producing an empty sprite.

For maps, Tiled needs the tileset images at the `source` paths recorded in the
`.tmx`. `scripts/loaders/map_document.py` can rewrite those paths
programmatically without reflowing the rest of the file.

## Recovering the original tree

The pre-strip history is retained locally as `refs/original/refs/heads/main`
in the author's clone. It is not pushed.

    git checkout refs/original/refs/heads/main -- data/graphics
