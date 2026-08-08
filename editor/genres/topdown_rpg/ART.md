# Art brief -- top-down RPG

This repository ships without art (see `docs/ASSETS.md`). Placeholders come
from `tools/make_placeholder_art.py`.

When you need a real palette, this is the template to hand to an image
model. It is written to be pasted as-is.

---

Produce a single PNG sprite sheet for a top-down 2D RPG, pixel art,
**32x32 pixels per cell**, arranged on a strict grid with no padding and no
drop shadows outside the cell. Transparent background (true alpha, not
magenta). Limited palette, at most 24 colours, flat shading with one light
source from the upper left. No anti-aliasing on outer edges.

Sheet layout, left to right, top to bottom:

| row | contents |
|---|---|
| 1 | walk cycle facing down: 4 frames |
| 2 | walk cycle facing left: 4 frames |
| 3 | walk cycle facing right: 4 frames |
| 4 | walk cycle facing up: 4 frames |

The character is centred horizontally in each cell with its feet on the
bottom edge, so the sprite's anchor is bottom-centre.

Subject: `<describe the character here>`

---

Once you have the sheet, tell the engine its geometry rather than
reshaping the sheet: frame rectangles are declared per sequence in
`config/animations.json` as `x`, `y`, `width`, `height`. Any layout works
as long as the config describes it, and `GameAnimation.slice_frames`
raises naming the sequence and frame if a rectangle falls outside the
sheet.

For tilesets, keep the same 32x32 cell and give Tiled the image at the
`source` path recorded in the `.tmx`.
