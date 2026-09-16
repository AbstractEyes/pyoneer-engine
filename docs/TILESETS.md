<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; re-measured 2026-09-16 by the commands printed beside the claims -- tools/check_tileset.py, tools/check_tileset_verbs.py, tools/check_palette.py and tools/check_collision_fold.py passed, the headroom snippet and the growth refusals were run on data/maps/starter.tmx, and the script examples were validated against the live verb registry. The one unmeasured claim carries [UNVERIFIED] and says why. -->

# Tilesets — the sheet, the palette, and what makes a tile solid

Five questions land here:

- *"how do I make a tileset"*
- *"how do I add tiles from an image"* / *"can I use part of this PNG"*
- *"how do I make a tile solid"*
- *"where did the collision layer go"*
- *"why will this tileset not grow"*

Read [`../CLAUDE.md`](../CLAUDE.md) first for the vocabulary. Everything the
editor does to a tileset is a `Command` with an exact inverse, so the verb
names below are also the script API — [`COMMANDS.md`](COMMANDS.md) is
generated from the registry that executes them and outranks any sentence here.

---

## A tileset, on disk

One `<tileset>` element per sheet, embedded in the `.tmx`, drawing from one
image on a fixed grid. The first one in `data/maps/starter.tmx`:

```xml
<tileset firstgid="1" name="TileA2" tilewidth="16" tileheight="16" tilecount="768" columns="32">
 <image source="../graphics/tilesets/System/TileA2.png" width="512" height="384"/>
</tileset>
```

A painted cell stores a **gid**, and

    gid       = firstgid + local id
    local id  = row * columns + column

Those two lines are the whole risk surface. Move `firstgid` and every cell
that named this sheet names a different sheet. Change `columns` and every cell
after the first row names a different tile *of the same sheet*. **Neither
raises anywhere** — in Tiled, in pytmx, or in this engine — so the symptom is
a map full of wrong art. Every refusal below exists to keep one of those two
numbers still.

Read the declarations with `#TAG:MapDocument.tilesets`; the next free range is
`#TAG:MapDocument.next_tileset_firstgid`.

**The other shape.** Tiled also writes a *collection of images* — a
`<tileset>` whose children are `<tile id="N"><image/></tile>` with no
`<image>` of its own. `MapDocument` round-trips one byte for byte and pytmx
draws it correctly; this editor never writes one, `#TAG:TilesetAtlas` draws
colour swatches for it, and growth refuses it. See [Known holes](#known-holes).

---

## The palette

One scrolling column holding **every** tileset the map declares
(`#TAG:TilePalette`). Each is a `#TAG:PaletteSection`: a header strip naming
the sheet and its tile count, then that sheet's grid at its own column count.
There is no chooser — *"which sheet holds this tile"* is a question the atlas
already answers (`#TAG:TilesetAtlas.entry_for`).

| gesture | what it does |
|---|---|
| click | a 1×1 brush |
| drag | a multi-tile stamp, **clamped to the section it started in** |
| ctrl+wheel | integer zoom, 1×–4× |
| plain wheel | scrolls the column |
| alt+click *on the map* | picks that tile and scrolls the palette to it (`#TAG:TilePalette.select_gid`) |
| right-click a header strip | Rename… / Grow… / Remove; an entry that cannot act is disabled and says why in its own label |

A drag that leaves its section extends down its own sheet instead of crossing
into the next one: a rectangle spanning two tilesets produces legal gids and a
nonsense picture.

**The selection is an address, not a coordinate** — a tileset *name* plus a
rectangle in that tileset's local ids. Every command rebuilds this widget, so
a pixel-keyed selection would vanish on the first stroke, and an index-keyed
one would slide onto another sheet the moment a tileset above it was removed.

The caption names tiles — `4×3 · 12 tiles from gid 68`, and `(5 empty)` when
the pick ran off the end of a ragged sheet. A pick entirely past the last tile
sets no brush and says so; `#TAG:Stamp` carries `-1` for "leave this cell
alone", which is why a ragged pick is correct.

The `collision` sheet does not appear here: it is a mask alphabet, not
scenery, filtered by the engine's own predicate (`#TAG:COLLISION_TILESET`).
`#TAG:TilesetAtlas` still carries it, because the overlay and every gid sum
need it.

---

## Adding tiles from any image

`+ Add tiles…` at the top of the palette, or `Project ▸ Add a tileset…`. The
view is **not modal** (`#TAG:TilesetImportDialog`), so cutting four regions
out of one sheet is four drags.

1. Choose an image. Any format Qt reads — measured with `QImage`, because
   `scripts/` may never import Qt and someone will hand it a `.bmp`.
2. Set tile width and height. The cut is drawn over the actual pixels
   (`#TAG:GridPreview`) and leftover pixels are named: a 16px sheet cut at 15
   produces legal TMX with a one-pixel seam on every tile, and nothing raises.
3. **Drag a region.** The band snaps to the tile grid; eight handles and a
   nine-way hit test decide move versus resize. The readout
   `x=16 y=16  ·  3 x 2 = 5 tiles  ·  gids 42–46  (1 dropped off the end)`
   shows the append *before* it happens.
4. Adjust, all reversible:
   - **offset** — drag the band, or type `x`/`y` in **pixels**, because a sheet
     with an odd border needs pixel precision;
   - **resize** — drag a handle, or type `columns`/`rows`;
   - **truncate** — lower `tiles` below `columns × rows`; a ragged `tilecount`
     already draws as a short last row.
5. Name it. The name auto-fills from the file stem until you touch it, and a
   duplicate is refused before the button is enabled.
6. Commit. One `#TAG:map.tileset.add`, with an exact inverse.

### Why the region becomes a cropped PNG

Committing **crops the selected pixels into a file** — `#TAG:CROP_DIR` beside
the map, so `data/maps/tilesets/<Name>.png` for a map in `data/maps/` — and
declares a plain `margin=0 spacing=0` grid over it. A selection that is the
whole sheet writes no crop and declares the source directly. The crop goes
beside the map, not beside the source, because the source may be read-only,
outside the project, or on another drive.

Recording the region as `margin`/`spacing`/`columns` over the original image
instead is dead on measurement:

- **The editor's atlas and pytmx agree about which pixels a gid names only at
  margin 0, spacing 0 and a full-width column count.** At `margin=8` all six
  probed tiles disagreed; at `spacing=1`, five of six.
- **Tiled 1.9's per-tile source rect (`<tile x y width height>`) is discarded
  by pytmx 3.32**, which hands back the full sheet, so that shape overdraws its
  neighbours.

So offset, resize and truncate are editor-side operations on a *selection*,
and the file records only their result. `#TAG:tileset_geometry` — the function
`#TAG:MapDocument.add_tileset` uses to write `columns` and `tilecount` — is
called with the **crop's** size.

`#TAG:relative_image_path` writes the path relative to the `.tmx` with forward
slashes, because Tiled resolves `<image source>` against the map and
`os.path.relpath` returns backslashes on Windows.

**A cropped PNG is never cleaned up.** Undo restores the `.tmx` byte for byte
and **leaves the PNG on disk** — the same bargain `#TAG:map.tileset.mask.set`
strikes with its `.blitmask`, asserted rather than accidental.
`#TAG:write_region` reuses a file holding exactly this crop and raises for one
holding anything else, because that may be art another map is declared
against.

---

## Growing a tileset

`#TAG:map.tileset.grow` points a tileset at a re-cut image and changes how many
tiles it owns, rewriting exactly four values — `<image source>`,
`<image width>`, `<image height>` and `tilecount` — and returning those four as
its inverse. From the window: right-click the sheet's header strip, Grow…,
which asks in rows.

### Rows only

`#TAG:growth_is_rows_only`. A taller sheet at the same width adds ids after
the last one and moves nothing. A **wider** sheet renumbers every id after
row 0, because every reader takes the stride from the image's width; on a
four-tile fixture, widening from 2 columns to 3 changed the art under two of
four painted cells with nothing raised. `columns` is therefore not a
parameter, and a new image with a different column count is refused.

Shrinking is the same verb with a smaller count, refused while any tile or tile
object still points into the range it would drop. Clear those with
`#TAG:map.tile.set_many` first and the inverse stays exact.

### Headroom is what makes growth free

`#TAG:MapDocument.tileset_headroom` is the distance from a tileset's last gid
up to the lowest `firstgid` above it. Growth inside that hole moves nothing.
Growth past it is **refused**, naming what is in the way, how much room the
tileset has, and what renumbering the survivors would cost in painted cells.

Both ways past it are worse. *Overlapping the neighbour*: pytmx resolves an
overlap by sorted `firstgid` in `get_tileset_from_gid` and by document order in
`reload_images`, so swapping two `<tileset>` elements moved the art under two
of seven painted cells. *Bumping the neighbour's `firstgid`*: a whole-map
renumber through `#TAG:map.tile.set_many` plus `#TAG:map.object.set` with
`key="gid"`, silently corrupting if the `<object gid=>` half or the three flip
bits are forgotten.

So **buy the headroom at add time**: `#TAG:map.tileset.add` accepts a
`first_gid` above the packed one, leaving a reserved hole the palette never
offers.

Measure what each tileset has before you decide:

```python
from scripts.loaders.map_document import MapDocument
doc = MapDocument.load("data/maps/starter.tmx")
for ref in doc.tilesets():
    print(ref.name, ref.first_gid, "..", ref.last_gid,
          "headroom", doc.tileset_headroom(ref.name))
```

On the shipped map it prints:

    TileA2 1 .. 768 headroom 0
    Clutter 769 .. 1792 headroom 0
    Parallax 1793 .. 2304 headroom 0
    collision 2305 .. 2321 headroom 536868590

**No art tileset on `starter.tmx` can grow by a single row.** All three were
packed, and the only range with room is `collision` — the mask alphabet, which
cannot grow (see `#TAG:MASK_DOMAIN` below). The refusals price it: growing
`TileA2` would renumber 1816 painted gids, `Clutter` 1620, and `Parallax` 340
(the `FloorCollision` masks). A new tileset added with `first_gid` above 2321
is the only growable range this map can have.

### [UNVERIFIED] — measure this before relying on a reserved hole

**Does Tiled preserve a `firstgid` gap when it saves?** Not measurable here;
Tiled is not installed. Its writer is expected to assign `firstgid` by running
total and remap the layer data, which would keep the *art* and lose the
*reservation*. Open a map carrying a hole in Tiled, save, and diff the
`firstgid` attributes. The design survives either way, because
`tileset_headroom` is computed from the declarations every time it is asked.

---

## Naming a tileset

A tileset name is an address: every other tileset verb takes it, and it is
stored **inside** a `.blitmask` header. `#TAG:map.tileset.rename` moves the
attribute and rewrites that header in the same transaction, because
`#TAG:tileset_defaults` refuses to load a map whose masks name a different
tileset. It does **not** rename the sidecar file: the tileset declares that
path with `#TAG:DEFAULTS_PROPERTY`, and a mask file may be shared. The inverse
is the verb with the two names swapped. No gid moves.

---

## Making a tile solid

Passability resolves in three levels, and `scripts/core/collision_runtime.py`'s
module docstring is the single definition. **Level one is the tile's own
mask**: stamping the tile *is* authoring the collision, and the per-cell
companion becomes only how you say "not THIS one". When the result surprises
you — a wall you never painted, or paint that does not block —
[`DIAGNOSE.md`](DIAGNOSE.md#i-painted-collision-and-nothing-blocks--this-wall-blocks-and-i-never-painted-it)
walks which level answered.

Level one lives in a `.blitmask` beside the map, named by the
`#TAG:DEFAULTS_PROPERTY` property on the `<tileset>` and loaded by
`#TAG:tileset_defaults`. The mask grid is row-major over the sheet, so its
width must equal the tileset's `columns` — the other reason growth adds rows
only. New rows read `NO_DATA` until authored, and a mask shorter than the
sheet is legal.

Three ways to author one, all landing on `#TAG:map.tileset.mask.set`:

| gesture | what it masks |
|---|---|
| pick a mask swatch, then **click a tile in the palette** | that tile, everywhere it is ever stamped |
| pick a mask swatch, then **shift+left on a map cell** | the tile under that cell, without hunting the sheet for which of 768 it was |
| `map.tileset.mask.set` | from a script or a response bundle |

`#TAG:MapCanvas.bake_tile_mask` owns every command and refusal past the
gesture. The map display draws each placed tile's own mask dimmed over the art
(`#TAG:MapCanvas.inherited_cells`), and the palette marks which tiles are
already baked.

**The mask alphabet** is four bits in RPG Maker's order — down 1, left 2,
right 4, up 8 — where a *set* bit means *blocked*, plus `STAR` (0x10), an
authored abstention meaning "ask the layer below". Seventeen values
(`#TAG:MASK_DOMAIN`); that tuple cannot grow, because it doubles as the
physical layout of `Collision.png`.

**The eighteenth swatch is not a mask.** `#TAG:BRUSH_DOMAIN` adds `NO_DATA`
(−1) to what the *brush* may be set to (`#TAG:no_data_is_a_brush_not_a_mask`):
on a cell it writes gid 0, and on a tile it is the verb's "no opinion". It is
how you *clear* either level. `PASS_ALL` and `NO_DATA` both draw no glyph and
mean opposite things, so they carry a keyline — solid for the assertion,
dotted for the silence (`#TAG:CHIP_KEYLINE`).

---

## Where the collision layer went

**Nowhere. The storage is unchanged; the row is gone.**

A per-cell mask is still a gid in a companion tile layer named by the art
layer's `#TAG:PASSABILITY` property, still `firstgid + mask` against the
`collision` tileset, still written by `#TAG:map.tile.set_many`. No `.tmx` byte
moves and `#TAG:field_from_map` bakes the identical field. What went away is
the *row in the hierarchy* (`#TAG:companion_folded_into_its_layer`): its
visibility checkbox changed nothing (a companion declares
`pyoneer_renders=false`), and it accepted art strokes the runtime read as
no-data.

In its place the art layer carries a **badge** — how many of its cells decode
to an opinion, and why they do not reach the field when they do not. A
parallaxed layer moves under the camera, so `#TAG:world_coordinate_fault`
excludes it and every mask on it is dead. *"No visible collision layer"* is
not *"no visible collision"*.

The fold set comes from `#TAG:companion_pairs`, which reads the declarations —
**never** the `Collision` name suffix — so an undeclared `RoofCollision` keeps
its row, and unreadable declarations fold nothing and say why on the map row.

Painting a cell is unchanged: select the **art** layer, pick a mask, drag.
`#TAG:PASSABILITY` stays in the layer inspector, the one place the companion's
name appears.

**Removing a layer takes its companion with it** in the window: the
hierarchy's `−` button removes the art layer and its companion in one
transaction, so one Ctrl+Z restores both (`#TAG:companion_leaves_with_its_layer`,
driven by `tools/check_collision_fold.py`). A companion a second art layer
still declares is left alone. The **verb alone** does not do this:
`#TAG:map.layer.remove` on the art layer removes only that layer, and the
stranded companion then unfolds into the tree as its own row, where `−` can
reach it.

---

## Doing it from a script

Every gesture above is a verb, reachable from a response bundle, the history
panel and a Python driver alike. The tileset vocabulary is
`#TAG:map.tileset.add`, `#TAG:map.tileset.grow`, `#TAG:map.tileset.rename`,
`#TAG:map.tileset.remove`, `#TAG:map.tileset.restore`,
`#TAG:map.tileset.mask.set` and `#TAG:map.tileset.mask.restore`; arguments are
in [`COMMANDS.md`](COMMANDS.md). A scope names a map from `config/maps.json`,
whose only entry is `starter`; any other name raises `no map named …`.

```jsonc
{"verb": "map.tileset.add", "scope": "map:starter",
 "args": {"name": "Dungeon", "image": "tilesets/Dungeon.png",
          "tile_width": 16, "tile_height": 16, "first_gid": 4096}}
{"verb": "map.tileset.grow", "scope": "map:starter",
 "args": {"name": "Dungeon", "image": "tilesets/Dungeon.png",
          "tile_count": 96}}
{"verb": "map.tileset.mask.set", "scope": "map:starter",
 "args": {"name": "Dungeon", "tile": 12, "mask": 15}}
```

`image` is relative to the `.tmx` and its size is read from the PNG header, so
the file must exist. `first_gid` is the headroom purchase: omit it and the
tileset packs against the one below, which is correct and means the next
growth is refused. The grow here re-cuts the same path taller at the same
width.

---

## What is refused, and what the refusal buys

Every one of these is a silent catastrophe if allowed, which is why none of
them is a warning.

| refused | because |
|---|---|
| a sheet whose width changes the column count | renumbers every local id after row 0 |
| growth past the next `firstgid` | pytmx resolves the overlap two contradictory ways |
| shrinking below a placed gid | the inverse would have to invent the cells it dropped |
| growing a `margin`/`spacing` tileset | the three readers do not agree on its column count |
| growing a collection-of-images tileset | it appends a `<tile>` child, a different edit with a different inverse |
| growing an external `<tileset source=…>` | its extent lives in a `.tsx`, outside this document's byte-exactness contract |
| an integer spelled `tilecount="04"` | the inverse writes `str(int(…))`, so undo would not reproduce the file |
| a duplicate or empty tileset name | a name is an address |
| a `.blitmask` whose width is not `columns` | it shifts every row after the first and masks the wrong tiles |

---

## Known holes

- **A collection-of-images tileset draws as colour swatches in the palette.**
  `#TAG:TilesetAtlas` builds no per-tile image map from `<tile><image>`, so the
  editor and the engine disagree about what it looks like, with no warning.
- **pytmx counts a MARGINED sheet's tiles differently from Tiled and
  `#TAG:tileset_geometry`.** pytmx's count ignores the margin, so at
  `margin > 0` it claims rows the other two say are not there; at margin 0 all
  three agree. `tileset_geometry` is the correct half. The editor cannot write
  a margin, so only a Tiled-authored sheet reaches this;
  [`NEXT.md`](NEXT.md) carries the sweep that measures it.
- **A whole-map gid remap is not a verb.** Growth past a neighbour is refused
  and the refusal prices the alternative; headroom is the path that means
  nobody needs it.
- **A native `.blitmap` gets no per-cell collision.** `#TAG:declared_collision`
  lifts a tmx `<tileset>`'s `pyoneer_collision` into `TilesetFile.collision`,
  and nothing opens it; there are no companion layers in a `.blitmap` either.
