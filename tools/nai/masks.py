"""Infill masks and the local hard composite (brief 4.4).

OWNER: implementer B.

RESPONSIBILITY
--------------
Draw the mask that repaints exactly one layout cell, paste a returned cell
back into the original locally, and report whether a returned image changed
anything outside the cell (risk R11). Read a mask that came from a FILE back
into its rectangle (`rect_of`), holding it to the shape `cell_mask` draws.

INVARIANTS
----------
* ONE CELL, WHOLE CELL, ALIGNED. A mask is white (model.MASK_REPAINT_RGB)
  over exactly one cell's canvas rect and black (model.MASK_KEEP_RGB)
  everywhere else. No anti-aliasing, no feathering, no rect crossing a cell
  boundary, never two cells. Every edge is a multiple of model.MASK_ALIGN
  (a `Layout` already guarantees it; this module re-asserts and raises).
* A MASK IS RGBA WITH ALPHA 255 EVERYWHERE (PNG colour type 6), exactly
  layout.width x layout.height -- what the website's pipeline ends up
  sending.
* THE COMPOSITE IS LOCAL AND EXACT. `composite` starts from the original and
  pastes only the returned image's crop of `rect`, so every pixel outside
  `rect` is byte-identical to the original whatever the server did with
  add_original_image.
* SIZE MISMATCH RAISES. Two images of different sizes, or a rect outside the
  image, is ValueError -- never a resize.
* ONE RECT RULE. `composite`, `differs_outside` and `rect_of` validate
  their rect with the same private function, so none of them can disagree
  about what "inside the image" means.
* A MASK FROM A FILE IS THE MASK THIS MODULE DRAWS, OR IT IS REFUSED.
  `rect_of` accepts exactly what `cell_mask` produces -- RGBA, alpha 255,
  only the two colours, the white pixels filling one rectangle whose every
  edge is on MASK_ALIGN -- because that is the shape the local composite
  and `differs_outside_mask` are defined on. A feathered edge, a second
  rectangle or an L-shaped selection is refused, never approximated.
* Pillow and the standard library only.
"""
from __future__ import annotations

import io

from PIL import Image

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


def composite(original_png: bytes, returned_png: bytes, rect: Rect) -> bytes:
    """Paste returned_png's crop of `rect` into original_png; RGB PNG bytes.

    Both inputs are converted to RGB first. ValueError when their sizes
    differ or `rect` is empty or not inside them. Also used to paste a
    mannequin cell from a rendered init into an accepted strip before an
    infill (brief 4.4, "init image for infill").
    """
    original, returned = _pair(original_png, returned_png)
    box = _check_rect(rect, original.size)
    result = original.copy()
    result.paste(returned.crop(box), box[:2])
    return _png(result)


def differs_outside(original_png: bytes, returned_png: bytes, rect: Rect) -> bool:
    """True when any RGB pixel outside `rect` differs between the two images.

    Pixels inside `rect` are ignored. ValueError on a size mismatch or a
    rect not inside the images.
    """
    original, returned = _pair(original_png, returned_png)
    box = _check_rect(rect, original.size)
    a, b = original.copy(), returned.copy()
    a.paste(MASK_KEEP_RGB, box)
    b.paste(MASK_KEEP_RGB, box)
    return a.tobytes() != b.tobytes()


def rect_of(mask_png: bytes, size: tuple[int, int]) -> Rect:
    """The one rectangle `mask_png` repaints, as (x0, y0, x1, y1).

    ValueError unless the bytes are a PNG in mode RGBA of exactly `size`,
    alpha 255 at every pixel, every pixel MASK_REPAINT_RGB or MASK_KEEP_RGB,
    at least one repainted, the repainted pixels filling their bounding box
    exactly, and every edge of that box a multiple of MASK_ALIGN.
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
    box = rgb.convert("L").getbbox()
    x0, y0, x1, y1 = _check_rect(box, mask.size)
    if white != (x1 - x0) * (y1 - y0):
        raise ValueError(f"the repainted pixels do not fill one rectangle: "
                         f"{white} of the {(x1 - x0) * (y1 - y0)} inside "
                         f"({x0}, {y0}, {x1}, {y1}); a mask repaints exactly "
                         f"one")
    for edge in (x0, y0, x1, y1):
        if edge % MASK_ALIGN:
            raise ValueError(f"the mask's rectangle ({x0}, {y0}, {x1}, {y1}) "
                             f"has an edge at {edge}, not a multiple of "
                             f"{MASK_ALIGN}: NovelAI re-snaps an unaligned "
                             f"mask, so it could repaint more or less")
    return x0, y0, x1, y1
