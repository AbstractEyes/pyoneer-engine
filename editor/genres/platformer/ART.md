# Art brief -- platformer

This repository ships without art (see `docs/ASSETS.md`). Placeholders come
from `tools/make_placeholder_art.py`.

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
| 3 | one-way platform: left, centre, right |
| 4 | hazard: spikes, 4 orientations |

Only what lands on the `Floor` layer is solid, so keep visually-solid and
actually-solid tiles distinguishable at a glance -- a decorative brick that
looks like the real one is a bug factory.

Frame rectangles are declared per sequence in `config/animations.json`
(`x`, `y`, `width`, `height`), so any layout works as long as the config
describes it.
