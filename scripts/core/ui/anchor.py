"""Edge anchoring: how a child reacts when its parent resizes.

An anchor names the parent edges a child keeps its distance to, and that one
concept covers staying put, moving and stretching:

    LEFT                keep the distance to the parent's left edge  (stay put)
    RIGHT               keep the distance to the RIGHT edge          (move with it)
    LEFT | RIGHT        keep BOTH distances                          (stretch)

and the same vertically, so filling is just anchoring to both edges and there
is no size-policy interaction table.

The default `LEFT | TOP` means "do not move and do not resize", so anchoring
is opt-in.

    close_button.anchor = Anchor.TOP | Anchor.RIGHT     # rides the corner
    body.anchor         = Anchor.ALL                    # fills the window
    title_bar.anchor    = Anchor.TOP | Anchor.STRETCH_X # full width, fixed height

ANCHORS HOLD MARGINS, THEY DO NOT MEAN "MATCH THE PARENT". `Anchor.ALL` keeps
the distance to all four edges; it does NOT resize a child to equal its
parent. A 100x100 child inside a 260x180 parent has right/bottom margins of
160 and 80, so growing the parent to 300x200 makes the child 140x120, not
300x200.

To make a child FILL, give it the parent's size when you create it and then
anchor ALL -- the anchor maintains the fit, it does not establish it. That is
what Panel and GameWindow do.
"""
from __future__ import annotations

from enum import IntFlag

from pygame import Rect


class Anchor(IntFlag):
    """Which parent edges a child keeps its distance to."""

    NONE = 0
    LEFT = 1
    RIGHT = 2
    TOP = 4
    BOTTOM = 8

    STRETCH_X = LEFT | RIGHT
    """Hold both horizontal edges: the child widens with the parent."""
    STRETCH_Y = TOP | BOTTOM
    """Hold both vertical edges: the child grows taller with the parent."""
    ALL = LEFT | RIGHT | TOP | BOTTOM
    """Fill the parent in both directions."""

    TOP_LEFT = TOP | LEFT
    """The default: stay exactly where you are."""
    TOP_RIGHT = TOP | RIGHT
    BOTTOM_LEFT = BOTTOM | LEFT
    BOTTOM_RIGHT = BOTTOM | RIGHT


DEFAULT_ANCHOR = Anchor.TOP_LEFT


def reflow(local_bounds: Rect, anchor: Anchor,
           delta_width: int, delta_height: int,
           minimum: tuple[int, int] = (1, 1)) -> Rect:
    """A child's new local rect after its parent changed size.

    Purely a function of the DELTA, so no margins need storing and the result
    cannot drift out of sync with a parent whose size changed by another
    route.

        anchored left only    x unchanged, width unchanged
        anchored right only   x moves by the delta, width unchanged
        anchored both         x unchanged, width grows by the delta

    Never returns a degenerate rect: a child clamped to `minimum` instead,
    because pygame raises on a negative Surface size several frames later,
    far from the cause.
    """
    result = local_bounds.copy()

    holds_left = bool(anchor & Anchor.LEFT)
    holds_right = bool(anchor & Anchor.RIGHT)
    if holds_left and holds_right:
        result.width = max(minimum[0], result.width + delta_width)
    elif holds_right:
        result.x += delta_width
    # left-only, or neither: unchanged

    holds_top = bool(anchor & Anchor.TOP)
    holds_bottom = bool(anchor & Anchor.BOTTOM)
    if holds_top and holds_bottom:
        result.height = max(minimum[1], result.height + delta_height)
    elif holds_bottom:
        result.y += delta_height

    return result
