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

The engine reads these paths at runtime. Without them:

- `main.py` raises on boot. `config/animations.json` points the default entity
  animation at `data/graphics/tilesets/Characters/~Garet.png`, and
  `GameAnimationHandler.__init__` loads it eagerly.
- `data/maps/test.tmx` **is** tracked — it is the author's own map — but its two
  `<tileset>` elements reference `../graphics/tilesets/System/TileA2.png` and
  `TileC.png`, so `pytmx.load_pygame` cannot resolve its tiles.

`tools/check_all.py` needs the art for the same reason: eight of the twelve
checks boot the engine.

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
config describes it. `GameAnimation.slice_frames` clips every frame to the
sheet and raises `ValueError` naming the sequence and frame if one falls
outside, rather than silently producing an empty sprite.

For maps, Tiled needs the tileset images at the `source` paths recorded in the
`.tmx`. `scripts/loaders/map_document.py` can rewrite those paths
programmatically without reflowing the rest of the file.

## Recovering the original tree

The pre-strip history is retained locally as `refs/original/refs/heads/main`
in the author's clone. It is not pushed.

    git checkout refs/original/refs/heads/main -- data/graphics
