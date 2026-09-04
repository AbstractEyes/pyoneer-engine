<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; every claim below was measured against the working tree on 2026-08-29 -- the gid arithmetic and the growth refusals by tools/check_tileset.py and tools/check_tileset_verbs.py, the palette and the import view by tools/check_palette.py, the fold and the no-opinion chip by tools/check_collision_fold.py. The one unmeasured claim carries [UNVERIFIED] and says why. On 2026-09-03 two entries under Known holes were corrected: the tile-count divergence had named `tileset_geometry` as the wrong reader (it is pytmx, and the axis is margin, not spacing), and the grow/rename pointer had named NEXT.md by ORDINAL and had slid onto the wrong entry -- both now cite by title. On 2026-09-03 the grow/rename hole was closed and that entry is struck through here with the grep that measures the closing. -->

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
image on a fixed grid:

```xml
<tileset firstgid="1" name="TileA2" tilewidth="16" tileheight="16"
         tilecount="768" columns="16">
 <image source="../graphics/TileA2.png" width="256" height="768"/>
</tileset>
```

A painted cell stores a **gid**, and

    gid       = firstgid + local id
    local id  = row * columns + column

Those two lines are the whole risk surface. Move `firstgid` and every cell
that named this sheet names a different sheet. Change `columns` and every cell
after the first row names a different tile *of the same sheet*. **Neither
raises anywhere** — in Tiled, in pytmx, or in this engine — so the symptom is
a map full of wrong art, which reads as corruption rather than as a bug. Every
refusal in the rest of this document exists to keep one of those two numbers
still.

Read the declarations with `#TAG:MapDocument.tilesets`; the next free range is
`#TAG:MapDocument.next_tileset_firstgid`.

**The other shape.** Tiled also writes a *collection of images* — a
`<tileset>` whose children are `<tile id="N"><image/></tile>` and which has no
`<image>` of its own. Both readers here handle it: `MapDocument` round-trips
one byte for byte and reports its extent correctly, and pytmx draws the loose
images at the right gids. This editor never writes one, `#TAG:TilesetAtlas`
draws colour swatches instead of art for it, and growth refuses it by name.
See [Known holes](#known-holes).

---

## The palette

One scrolling column holding **every** tileset the map declares
(`#TAG:TilePalette`). Each is a `#TAG:PaletteSection`: a header strip naming
the sheet and its tile count, then that sheet's grid at its own column count.
There is no chooser — *"which sheet holds this tile"* is a question the atlas
already answers (`#TAG:TilesetAtlas.entry_for`), and making the author answer
it before they could look was the cost of asking.

| gesture | what it does |
|---|---|
| click | a 1×1 brush |
| drag | a multi-tile stamp, **clamped to the section it started in** |
| ctrl+wheel | integer zoom, 1×–4× |
| plain wheel | scrolls the column |
| alt+click *on the map* | picks that tile and scrolls the palette to it (`#TAG:TilePalette.select_gid`) |

A drag that leaves its section extends down its own sheet instead of crossing
into the next one: a rectangle spanning two tilesets produces perfectly legal
gids and a nonsense picture.

**The selection is an address, not a coordinate** — a tileset *name* plus a
rectangle in that tileset's own local ids. Every command rebuilds this widget,
so a selection keyed on pixel position would vanish on the first stroke, and a
selection keyed on tileset *index* would slide onto another sheet's tiles the
moment a tileset above it was removed.

The caption names tiles rather than rectangles — `4×3 · 12 tiles from gid 68`,
and `(5 empty)` when the pick ran off the end of a ragged sheet. A pick that
lands entirely past the last tile sets no brush and says so; `#TAG:Stamp`
carries `-1` for "leave this cell alone", which is why a ragged pick is
correct and not merely tolerated.

The `collision` sheet does not appear here. It is a mask alphabet, not
scenery, and it is filtered by the engine's own predicate
(`#TAG:COLLISION_TILESET`) so there is one spelling of what that tileset is.
`#TAG:TilesetAtlas` still carries it, because the overlay and every gid sum
need it.

---

## Adding tiles from any image

`+ Add tiles…` at the top of the palette, or `Project ▸ Add a tileset…`. The
view is **not modal** (`#TAG:TilesetImportDialog`): it stays open across an
import, so cutting four regions out of one sheet is four drags.

1. Choose an image. Any format Qt reads — the editor measures it with `QImage`
   rather than the engine's PNG-header reader, because `scripts/` may never
   import Qt and someone will hand it a `.bmp`.
2. Set tile width and height. The proposed cut is drawn over the actual pixels
   (`#TAG:GridPreview`), and leftover pixels are named: a 16px sheet cut at 15
   produces perfectly legal TMX with a one-pixel seam of the neighbour on every
   tile, and nothing anywhere raises about it.
3. **Drag a region.** The band snaps to the tile grid, and eight handles plus a
   nine-way hit test decide whether a press moves the band or resizes it. The
   readout is
   `x=16 y=16  ·  3 x 2 = 5 tiles  ·  gids 42–46  (1 dropped off the end)` —
   the gid range makes the append visible *before* it happens.
4. Adjust, all three reversible by dragging back:
   - **offset** — drag the band, or type `x`/`y` in **pixels**, because a sheet
     with an odd border needs pixel precision and the tile grid is derived from
     `x`/`y` rather than from the image origin;
   - **resize** — drag a handle, or type `columns`/`rows`;
   - **truncate** — lower `tiles` below `columns × rows`. A ragged `tilecount`
     already draws as a short last row and `#TAG:TilesetAtlas.entry_for` already
     refuses a gid past the end, so truncation costs one field and no new
     machinery.
5. Name it. The name auto-fills from the file stem until you touch it, and a
   duplicate is refused before the button is enabled rather than rolled back
   after.
6. Commit. One `#TAG:map.tileset.add`, with an exact inverse.

### Why the region becomes a cropped PNG

Committing **crops the selected pixels into a file** — `#TAG:CROP_DIR` beside
the map, so `data/maps/tilesets/<Name>.png` for a map in `data/maps/` — and
declares a plain `margin=0 spacing=0` grid over that file. A selection that is
the whole sheet writes no crop and declares the source directly, so the common
case costs nothing.

The alternative — record the region as `margin`/`spacing`/`columns` over the
original image — is dead on measurement, twice over:

- **The editor's atlas and pytmx agree about which pixels a gid names only at
  margin 0, spacing 0 and a full-width column count.** At `margin=8` all six
  probed tiles disagreed; at `spacing=1`, five of six. Two readers disagreeing
  about what a gid looks like raises nowhere.
- **Tiled 1.9's per-tile source rect (`<tile x y width height>`) is discarded
  by pytmx 3.32.** Both sub-rect tiles came back as the full sheet surface, and
  the renderer blits whatever surface it gets at `cell × tile size`, so that
  shape overdraws its neighbours.

So offset, resize and truncate are editor-side operations on a *selection*, and
the file records only their result: the one geometry all three readers already
cut identically. `#TAG:tileset_geometry` — the same function
`#TAG:MapDocument.add_tileset` uses to write `columns` and `tilecount` — is
called with the **crop's** size, so the numbers in the file describe the sheet
the file actually names.

`#TAG:write_region` never overwrites different pixels: an existing file holding
exactly this crop is reused, and one holding anything else raises. Overwriting
would destroy art another map is declared against; reusing blindly would
declare a tileset over pixels nobody chose. `#TAG:relative_image_path` writes
the path relative to the `.tmx` with forward slashes, because Tiled resolves
`<image source>` against the map and `os.path.relpath` returns backslashes on
Windows — a path that opens on one machine and nowhere else.

Undo restores the `.tmx` byte for byte and **leaves the PNG on disk** — the
same bargain `#TAG:map.tileset.mask.set` strikes with its `.blitmask`. That is
asserted, not accidental.

---

## Growing a tileset

A tileset is not a fixed-size sheet. `#TAG:map.tileset.grow` points it at a
re-cut image and changes how many tiles it owns, rewriting exactly four values
— `<image source>`, `<image width>`, `<image height>` and `tilecount` — and
returning those four as its inverse.

### Rows only

`#TAG:growth_is_rows_only`. A taller sheet at the same width adds ids after
the last one and moves nothing. A **wider** sheet renumbers every id after row
0, because every reader takes the stride from the image's width: pytmx walks
the image in ranges over its pixel size, the editor's atlas divides by tile
width. Measured on a four-tile fixture, widening from 2 columns to 3 changed
the art under two of four painted cells with nothing raised. `columns` is
therefore not a parameter, and a new image whose width yields a different
column count is refused.

Shrinking is the same verb with a smaller count, and is refused while any tile
or tile object still points into the range it would drop. Clear those with
`#TAG:map.tile.set_many` first and the inverse stays exact.

### Headroom is what makes growth free

`#TAG:MapDocument.tileset_headroom` is the distance from a tileset's last gid
up to the lowest `firstgid` above it. Growth inside that hole moves nothing.
Growth past it is **refused**, and the refusal names what is in the way, how
much room the tileset does have, and what renumbering the survivors would cost
in painted cells.

Refusal is the right answer because the two ways past it are both worse:

- *Overlap the neighbour.* pytmx resolves an overlapping range two
  incompatible ways — by sorted `firstgid` in `get_tileset_from_gid`, by
  document order in `reload_images` — so the same file paints differently
  depending on which `<tileset>` was declared first. Measured: swapping two
  `<tileset>` elements and changing nothing else moved the art under two of
  seven painted cells.
- *Bump the neighbour's `firstgid`.* That is a whole-map renumber. It is
  expressible — `#TAG:map.tile.set_many` per tile layer plus
  `#TAG:map.object.set` with `key="gid"`, both with exact inverses — and it is
  expensive, and skipping the `<object gid=>` half or forgetting to mask the
  three flip bits off corrupts the map silently.

So **buy the headroom at add time.** `#TAG:MapDocument.add_tileset` accepts a
`first_gid` above the packed one, and `#TAG:map.tileset.add` exposes it, so a
map can be authored with a reserved hole under every range. A gid inside the
hole resolves to no tileset and the palette never offers it.

Measure what a tileset has, and what moving one would cost, before you decide:

```python
from scripts.loaders.map_document import MapDocument
doc = MapDocument.load("data/maps/test.tmx")
for ref in doc.tilesets():
    print(ref.name, ref.first_gid, "..", ref.last_gid,
          "headroom", doc.tileset_headroom(ref.name))
```

On the shipped map the bottom tileset has no headroom at all and the top one
has the rest of the gid space: growing the top costs nothing, and growing the
bottom would renumber every painted cell above it — five figures across every
tile layer. That asymmetry is the reason headroom exists.

### [UNVERIFIED] — measure this before relying on a reserved hole

**Does Tiled preserve a `firstgid` gap when it saves?** Not measurable here;
Tiled is not installed. Its writer is expected to assign `firstgid` by running
total over the tileset list and remap the layer data to match, which would be
lossless for the *art* and destructive to the *reservation*. Open a map
carrying a hole in Tiled, save, and diff the `firstgid` attributes. If Tiled
repacks them, headroom is a per-session convenience — the design survives
either way, because `tileset_headroom` is computed from the declarations every
time it is asked rather than stored.

---

## Naming a tileset

A tileset name is an address: it is the key every other tileset verb takes,
and it is stored **inside** a `.blitmask` header. `#TAG:map.tileset.rename`
moves the attribute and rewrites that header in the same transaction, because
`#TAG:tileset_defaults` refuses to load a map whose masks name a different
tileset — a rename that stopped at the `.tmx` would look perfect in the
hierarchy and make the map unloadable. It does **not** rename the sidecar
file: the tileset declares that path with `#TAG:DEFAULTS_PROPERTY` and a mask
file may be deliberately shared. The inverse is the verb with the two names
swapped, which puts both halves back.

No gid moves. A name is not part of the numbering.

---

## Making a tile solid

Passability resolves in three levels, weakest first, and the first level that
is not `NO_DATA` wins. `scripts/core/collision_runtime.py`'s module docstring
is the single definition; the part that matters here is **level one**:

> **A tile carries its own mask.** Stamping the tile *is* authoring the
> collision, so the companion layer stops being how you say "this is a wall"
> and becomes only how you say "not THIS one".

Level one lives in a `.blitmask` beside the map, named by the
`#TAG:DEFAULTS_PROPERTY` property on the `<tileset>` element and loaded by
`#TAG:tileset_defaults`. The mask grid is row-major over the sheet, so its
width must equal the tileset's `columns` — which is the other reason growth
adds rows and never columns. New rows simply read `NO_DATA` until authored, and
a mask shorter than the sheet is legal.

Three ways to author one, all landing on `#TAG:map.tileset.mask.set`:

| gesture | what it masks |
|---|---|
| pick a mask swatch, then **click a tile in the palette** | that tile, everywhere it is ever stamped |
| pick a mask swatch, then **shift+left on a map cell** | the tile under that cell — the wall you are looking at, without hunting the sheet for which of 768 tiles it was |
| `map.tileset.mask.set` | from a script or a response bundle |

`#TAG:MapCanvas.bake_tile_mask` owns every command and every refusal past the
gesture, so shift+left is a binding rather than a second authoring path. The
map display draws each placed tile's own mask dimmed over the art
(`#TAG:MapCanvas.inherited_cells`), so the wall appears under the click — and
the palette marks which tiles are already baked, since level one otherwise
lives in a file beside the `.tmx` with no readout.

**The mask alphabet** is four bits in RPG Maker's order — down 1, left 2,
right 4, up 8 — where a *set* bit means *blocked*, plus `STAR` (0x10), an
authored abstention meaning "ask the layer below". Seventeen values
(`#TAG:MASK_DOMAIN`), and that tuple cannot grow: it doubles as the physical
layout of `Collision.png`.

**The eighteenth swatch is not a mask.** `#TAG:no_data_is_a_brush_not_a_mask`
— `#TAG:BRUSH_DOMAIN` is what the *brush* may be set to, and it adds `NO_DATA`
(−1), which is not stored as a tile at all: on a cell it is gid 0, the empty
cell the eraser already writes, and on a tile it is the −1 the verb has always
documented as "no opinion". It is how you *clear* one.

`PASS_ALL` and `NO_DATA` are the two swatches that draw no glyph and mean
opposite things, so they carry a keyline instead — solid for the assertion,
dotted for the silence (`#TAG:CHIP_KEYLINE`). `PASS_ALL` is a claim: a hole in
the wall, a bridge over water, and it *ends* the resolve at that level. A cell
painted `PASS_ALL` over a tile whose default is `BLOCK_ALL` is open. A cell
carrying `NO_DATA` is not an answer, so it falls through to the tile's mask.

---

## Where the collision layer went

**Nowhere. The storage is unchanged; the row is gone.**

A per-cell mask is still a gid in a companion tile layer named by the art
layer's `#TAG:PASSABILITY` property, still `firstgid + mask` against the
`collision` tileset, still written by the same `Stroke` and the same
`#TAG:map.tile.set_many`. No `.tmx` byte moves, `#TAG:field_from_map` bakes
the identical field, and nothing under `scripts/` changed. What went away is
the *row in the hierarchy* (`#TAG:companion_folded_into_its_layer`).

That row was four wrong things at once: a visibility checkbox that changed
nothing, because a companion declares `pyoneer_renders=false` and neither the
engine nor the canvas draws it; a genre warning that was false for it; a
selectable target that accepted art strokes the runtime then read as no-data;
and a second name for a layer the author never wanted to name.

In its place the art layer carries a **badge** — how many of its cells decode
to an opinion, and the reason they do not reach the field when there is one.
Hiding the row without carrying the reason forward would hide a real fault: a
parallaxed layer moves under the camera, so `#TAG:world_coordinate_fault`
excludes it from the stack and every mask painted on it is dead. *"No visible
collision layer"* is not *"no visible collision"*.

The fold set comes from `#TAG:companion_pairs`, which reads the declarations —
**never** from the `Collision` name suffix. A layer somebody merely called
`RoofCollision` and never declared stays an ordinary paintable layer with its
row; a declaration naming a layer the map does not have folds nothing, so the
dangling case an author can actually fix stays on screen. If the declarations
cannot be read at all, nothing is folded and the map row says why.

Painting a cell is unchanged: select the **art** layer, pick a mask, drag.
`#TAG:PASSABILITY` stays in the layer inspector, which after the fold is the
only place the companion's name appears — as a property, which is what it is.
That is also the escape hatch for two art layers sharing one companion.

---

## Doing it from a script

Every gesture above is a verb, and a verb is reachable from a response bundle,
the history panel and a Python driver alike. The registry-generated reference
is [`COMMANDS.md`](COMMANDS.md); the tileset vocabulary is
`#TAG:map.tileset.add`, `#TAG:map.tileset.grow`, `#TAG:map.tileset.rename`,
`#TAG:map.tileset.remove`, `#TAG:map.tileset.restore`,
`#TAG:map.tileset.mask.set` and `#TAG:map.tileset.mask.restore`.

```jsonc
{"verb": "map.tileset.add", "scope": "map:test",
 "args": {"name": "Dungeon", "image": "tilesets/Dungeon.png",
          "tile_width": 16, "tile_height": 16, "first_gid": 4096}}
{"verb": "map.tileset.grow", "scope": "map:test",
 "args": {"name": "Dungeon", "image": "tilesets/Dungeon.png",
          "tile_count": 96}}
{"verb": "map.tileset.mask.set", "scope": "map:test",
 "args": {"name": "Dungeon", "tile": 12, "mask": 15}}
```

`first_gid` is the headroom purchase. Omit it and the tileset packs against
the one below, which is correct and means the next growth is refused.

---

## What is refused, and what the refusal buys

Every one of these is a silent catastrophe if it is allowed, which is why none
of them is a warning.

| refused | because |
|---|---|
| a sheet whose width changes the column count | renumbers every local id after row 0 |
| growth past the next `firstgid` | pytmx resolves the overlap two contradictory ways |
| shrinking below a placed gid | the inverse would have to invent the cells it dropped |
| growing a `margin`/`spacing` tileset | the three readers do not agree on its column count, so growth would move a different set of tiles in each |
| growing a collection-of-images tileset | it appends a `<tile>` child, a different edit with a different inverse |
| growing an external `<tileset source=…>` | its extent lives in a `.tsx`, outside this document's byte-exactness contract |
| an integer spelled `tilecount="04"` | the inverse writes `str(int(…))`, so undo would not reproduce the file byte for byte |
| a duplicate or empty tileset name | a name is an address |
| a `.blitmask` whose width is not `columns` | it shifts every row after the first and masks the wrong tiles |

---

## Known holes

- **A collection-of-images tileset draws as colour swatches in the palette.**
  It reads correctly in `MapDocument` and renders correctly through pytmx, and
  `#TAG:TilesetAtlas` builds no per-tile image map from `<tile><image>`. The
  editor and the engine therefore disagree about what that tileset looks like,
  with no warning. It is a secondary shape this editor never writes.
- **pytmx counts a MARGINED sheet's tiles differently from the other two
  readers.** `#TAG:tileset_geometry` is not the wrong half: it reduces
  algebraically to Tiled's own `columnCountForWidth`,
  `(W - margin + spacing) // (tile + spacing)`, and a sweep of 16,335 shapes
  finds zero disagreements between them. pytmx's count is
  margin-INDEPENDENT — it walks
  `range(margin, dim + margin - tiledim + 1, tiledim + spacing)`, where the two
  `margin` terms cancel — so at `margin > 0` it claims rows the other two say
  are not there, and at `margin 0` all three agree at every spacing. The editor
  can no longer *write* a margin, so it cannot reach this itself; a
  Tiled-authored margined sheet still gets a tile count pytmx disagrees about.
  `#TAG:TilesetAtlas` cuts the right pixels for such a sheet — the count pytmx
  derives is the part still wrong. [`NEXT.md`](NEXT.md)'s *"The editor and the
  engine disagree about a tileset's pixels in two places"* carries the sweep
  that measures it.
- **~~No editor control calls `map.tileset.grow` or `map.tileset.rename`~~ —
  paid off.** Right-clicking a tileset's header strip in the palette opens a
  menu of Rename / Grow / Remove; each entry that cannot act is disabled and
  carries the reason in its own label ("Grow… · no room before Spaced at gid
  37"). Growth is asked in ROWS and turned into a tile count here, so an
  over-ask is refused before a command exists rather than as a verb refusal.
  Measured 2026-09-03:
  `grep -rn "map.tileset.grow\|map.tileset.rename" editor/ui/ --include=*.py`
  returns 6 lines where it returned none, and `tools/check_palette.py` drives
  a real right-click, a real `QAction.trigger()` and a real undo.
- **A whole-map gid remap is not a verb.** Growth past a neighbour is refused
  and the refusal prices the alternative; nothing performs it. Headroom is the
  path that means nobody needs it.
- **A native `.blitmap` gets no per-cell collision.** `#TAG:declared_collision`
  lifts a tmx `<tileset>`'s `pyoneer_collision` into `TilesetFile.collision`,
  so a converted map's `.tileset` carries the reference — and nothing opens it.
  There are no companion layers in a `.blitmap` either.
- **A folded companion cannot be removed from the hierarchy.** With no row,
  the `−` button cannot reach it, and `map.layer.remove` on the art layer does
  not take its companion with it. Undo, a script, or Tiled.
