# Art brief -- platformer

The art that ships is generated (see `docs/ASSETS.md`): `data/art/` is
tracked, and `.venv/Scripts/python.exe -m tools.art` redraws it. Your own
sheets go in `data/graphics/`, which wins over the pack.

Paste this to an image model when you need a real palette.

---

Produce a single PNG sprite sheet for a 2D side-scrolling platformer, pixel
art, **32x32 pixels per cell**, arranged on a strict grid with no padding.
Transparent background (true alpha, not magenta). Limited palette, at most
24 colours, flat shading with one light source from the upper left. No
anti-aliasing on outer edges. The character faces **right**; the engine
mirrors for left.

Sheet layout, left to right, top to bottom:

| row | contents |
|---|---|
| 1 | idle: 4 frames |
| 2 | run: 6 frames |
| 3 | jump: 2 frames (launch, apex) then fall: 2 frames |
| 4 | hurt: 1 frame, then death: 3 frames |

The character stands with its feet on the bottom edge of the cell and is
centred horizontally, so the anchor is bottom-centre.

Subject: `<describe the character here>`

---

For the tileset, a separate sheet, same 32x32 cell:

| row | contents |
|---|---|
| 1 | solid ground: left cap, centre, right cap, single |
| 2 | solid ground interior fill, 4 variants |
| 3 | thin platform: left, centre, right |
| 4 | hazard: spikes, 4 orientations |

Draw the tiles **edge to edge, no border and no gutter**: the editor and the
engine only agree about which pixels a gid names at margin 0 and spacing 0.

Nothing is solid because of where it is drawn -- solidity is a mask given to
the tile, so a decorative brick and a real wall are two tiles that must be
distinguishable at a glance or the map becomes a guessing game. Row 3 is a
*thin* platform, not a one-way one: blocking is symmetric here, so a ledge you
can jump up through and also land on is not expressible.

Frame rectangles are declared per sequence in `config/animations.json`
(`x`, `y`, `width`, `height`), so any layout works as long as the config
describes it.
