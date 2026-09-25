"""Infill masks and the local hard composite (brief 4.4).

OWNER: implementer B.

RESPONSIBILITY
--------------
Draw the mask that repaints exactly one layout cell, paste a returned image
back into the original locally inside a mask, and report whether a returned
image changed anything outside it (risk R11). Read a mask that came from a
FILE (`region_of`), holding it to the one shape rule NovelAI itself has.

INVARIANTS
----------
* A CELL MASK IS ONE CELL, WHOLE CELL, ALIGNED. `cell_mask` draws white
  (model.MASK_REPAINT_RGB) over exactly one cell's canvas rect and black
  (model.MASK_KEEP_RGB) everywhere else. Every edge is a multiple of
  model.MASK_ALIGN (a `Layout` already guarantees it; this module re-asserts
  and raises).
* A MASK IS RGBA WITH ALPHA 255 EVERYWHERE (PNG colour type 6), exactly
  the image's size -- what the website's pipeline ends up sending.
* A MASK FROM A FILE MAY BE ANY SHAPE MADE OF WHOLE LATENT BLOCKS. NovelAI
  takes the whole image and a mask of any shape (the author, 2026-09-25:
  "it accepts masks ... you send the entire image and then mask the
  portion"), and repaints by the blocks of its latent grid, MASK_ALIGN
  pixels square. So `region_of` accepts white and black only, alpha 255,
  at least one white pixel, and every MASK_ALIGN block wholly white or
  wholly black: a head and a margin around it, two rectangles, an L. A
  block split between the two is refused, never approximated -- NovelAI
  would repaint all of it or none of it, which is not what was drawn -- and
  so is a feathered (grey) edge. It USED to accept one rectangle only,
  which was this module's own choice, not NovelAI's.
* THE COMPOSITE IS LOCAL AND EXACT. `composite` starts from the original and
  pastes the returned image only where the mask is white (a Rect is the
  mask it describes), so every pixel outside the mask is byte-identical to
  the original whatever the server did with add_original_image, INCLUDING
  the pixels inside the mask's bounding box but outside its shape.
* SIZE MISMATCH RAISES. Two images of different sizes, a rect outside the
  image, or a mask of another size is ValueError -- never a resize.
* ONE REGION RULE. `composite` and `differs_outside` read their region
  through the same private function, a Rect through `_check_rect` and a
  mask through `region_of`, so neither can disagree with the other, or
  with the file route, about what the mask covers.
* Pillow and the standard library only.
"""
from __future__ import annotations

import io

from PIL import Image, ImageChops

from tools.nai.model import (MASK_ALIGN, MASK_KEEP_RGB, MASK_REPAINT_RGB,
                             Layout, Rect)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _check_rect(rect: Rect, size: tuple[int, int]) -> tuple[int, int, int, int]:
    """`rect` as four ints; ValueError unless it is non-empty and inside."""
    if not isinstance(rect, (tuple, list)) or len(rect) != 4 or not all(
            isinstance(v, int) and not isinstance(v, bool) for v in rect):
        raise ValueError(f"rect must be four ints (x0, y0, x1, y1), got "
                         f"{rect!r}")
    x0, y0, x1, y1 = rect
    w, h = size
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise ValueError(f"rect {tuple(rect)} is empty or not inside a "
                         f"{w}x{h} image")
    return x0, y0, x1, y1


def _pair(original_png: bytes, returned_png: bytes
          ) -> tuple[Image.Image, Image.Image]:
    original = Image.open(io.BytesIO(original_png)).convert("RGB")
    returned = Image.open(io.BytesIO(returned_png)).convert("RGB")
    if original.size != returned.size:
        raise ValueError(f"image sizes differ: original {original.size}, "
                         f"returned {returned.size}")
    return original, returned


def cell_mask(layout: Layout, index: int) -> bytes:
    """The infill mask for cell `index` of `layout`, as RGBA PNG bytes.

    IndexError for an index outside the layout (a negative index included:
    -1 is not a cell); ValueError for a rect edge that is not a multiple of
    MASK_ALIGN. Deterministic bytes.
    """
    if not isinstance(index, int) or isinstance(index, bool):
        raise IndexError(f"cell index must be an int, got {index!r}")
    if not 0 <= index < layout.count:
        raise IndexError(f"layout {layout.name} has cells 0..{layout.count - 1}"
                         f", not {index}")
    rect = layout.cells[index].rect_canvas
    for edge in rect:
        if edge % MASK_ALIGN:
            raise ValueError(f"layout {layout.name}: cell {index} edge {edge} "
                             f"is not a multiple of {MASK_ALIGN}")
    x0, y0, x1, y1 = _check_rect(rect, (layout.width, layout.height))
    mask = Image.new("RGBA", (layout.width, layout.height),
                     MASK_KEEP_RGB + (255,))
    mask.paste(MASK_REPAINT_RGB + (255,), (x0, y0, x1, y1))
    return _png(mask)


def _inside(where: Rect | bytes, size: tuple[int, int]) -> Image.Image:
    """`where` as an "L" image of `size`, 255 where it repaints: a Rect (four
    ints) as the rectangle it names, or a mask's PNG bytes as `region_of`
    reads them -- its white pixels, whatever their shape."""
    if isinstance(where, (bytes, bytearray)):
        region_of(where, size)
        rgb = Image.open(io.BytesIO(bytes(where))).convert("RGB")
        return _white(rgb)
    box = _check_rect(where, size)
    inside = Image.new("L", size, 0)
    inside.paste(255, box)
    return inside


def _white(rgb: Image.Image) -> Image.Image:
    """255 where `rgb` is MASK_REPAINT_RGB, 0 elsewhere."""
    r, g, b = (rgb.getchannel(i).point(lambda v, c=c: 255 if v == c else 0)
               for i, c in enumerate(MASK_REPAINT_RGB))
    return ImageChops.multiply(ImageChops.multiply(r, g), b)


def composite(original_png: bytes, returned_png: bytes,
              where: Rect | bytes) -> bytes:
    """Paste returned_png into original_png wherever `where` repaints -- a
    Rect, or a mask's PNG bytes of any shape `region_of` accepts; RGB PNG
    bytes.

    Both inputs are converted to RGB first. ValueError when their sizes
    differ, a rect is empty or not inside them, or a mask breaks
    `region_of`'s rule. Also used to paste a mannequin cell from a rendered
    init into an accepted strip before an infill (brief 4.4, "init image for
    infill").
    """
    original, returned = _pair(original_png, returned_png)
    inside = _inside(where, original.size)
    result = original.copy()
    result.paste(returned, (0, 0), inside)
    return _png(result)


def differs_outside(original_png: bytes, returned_png: bytes,
                    where: Rect | bytes) -> bool:
    """True when any RGB pixel outside what `where` repaints (a Rect, or a
    mask's PNG bytes) differs between the two images.

    Pixels the mask repaints are ignored; a pixel inside a mask's bounding
    box but outside its shape is NOT. ValueError on a size mismatch, a rect
    not inside the images, or a mask `region_of` refuses.
    """
    original, returned = _pair(original_png, returned_png)
    inside = _inside(where, original.size)
    full = (0, 0) + original.size
    a, b = original.copy(), returned.copy()
    a.paste(MASK_KEEP_RGB, full, inside)
    b.paste(MASK_KEEP_RGB, full, inside)
    return a.tobytes() != b.tobytes()


def region_of(mask_png: bytes, size: tuple[int, int]) -> Rect:
    """The bounding rectangle of what `mask_png` repaints, (x0, y0, x1, y1).

    ValueError unless the bytes are a PNG in mode RGBA of exactly `size`,
    alpha 255 at every pixel, every pixel MASK_REPAINT_RGB or MASK_KEEP_RGB,
    at least one repainted, `size` a whole number of MASK_ALIGN blocks, and
    every MASK_ALIGN x MASK_ALIGN block of that grid wholly repainted or
    wholly kept. The repainted pixels may take any shape.
    """
    if not isinstance(mask_png, (bytes, bytearray)):
        raise ValueError(f"a mask must be PNG bytes, got "
                         f"{type(mask_png).__name__}")
    try:
        mask = Image.open(io.BytesIO(bytes(mask_png)))
        mask.load()
    except Exception as exc:  # Pillow raises several unrelated classes
        raise ValueError(f"the mask is not a readable image ({exc})") from None
    if mask.format != "PNG" or mask.mode != "RGBA":
        raise ValueError(f"a mask is an RGBA PNG (colour type 6), got "
                         f"{mask.format} {mask.mode}")
    if mask.size != tuple(size):
        raise ValueError(f"the mask is {mask.size[0]}x{mask.size[1]}; the "
                         f"request is {size[0]}x{size[1]}")
    lowest = mask.getchannel("A").getextrema()[0]
    if lowest != 255:
        raise ValueError(f"a mask is opaque everywhere; this one has alpha "
                         f"down to {lowest}")
    rgb = mask.convert("RGB")
    colours = rgb.getcolors(maxcolors=2)
    allowed = (MASK_REPAINT_RGB, MASK_KEEP_RGB)
    if colours is None or any(colour not in allowed for _n, colour in colours):
        raise ValueError(f"a mask holds only {MASK_REPAINT_RGB} (repaint) and "
                         f"{MASK_KEEP_RGB} (keep); this one holds other "
                         f"colours, so its edge would be a guess")
    white = sum(n for n, colour in colours if colour == MASK_REPAINT_RGB)
    if not white:
        raise ValueError("the mask repaints nothing: no pixel is "
                         f"{MASK_REPAINT_RGB}")
    w, h = mask.size
    if w % MASK_ALIGN or h % MASK_ALIGN:
        raise ValueError(f"a {w}x{h} mask is not a whole number of "
                         f"{MASK_ALIGN} px latent blocks")
    inside = _white(rgb)
    # each block's mean: 0 or 255 exactly when the block is one colour
    means = inside.reduce(MASK_ALIGN)
    for i, mean in enumerate(means.getdata()):
        if mean not in (0, 255):
            bx, by = (i % means.width) * MASK_ALIGN, (i // means.width) * MASK_ALIGN
            raise ValueError(f"the mask splits the {MASK_ALIGN} px latent block "
                             f"at ({bx}, {by}) between repaint and keep: "
                             f"NovelAI repaints a mask by whole blocks of its "
                             f"latent grid, so it could repaint more or less "
                             f"than was drawn")
    return _check_rect(inside.getbbox(), mask.size)
