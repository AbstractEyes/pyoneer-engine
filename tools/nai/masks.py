"""Infill masks and the local hard composite (brief 4.4).

OWNER: implementer B.

RESPONSIBILITY
--------------
Draw the mask that repaints exactly one layout cell, paste a returned cell
back into the original locally, and report whether a returned image changed
anything outside the cell (risk R11).

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
* ONE RECT RULE. `composite` and `differs_outside` validate their rect with
  the same private function, so the two cannot disagree about what "inside
  the image" means.
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
