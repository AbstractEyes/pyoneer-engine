"""Exact pixel-space clipping for the blit pool.

WHY (from scripts/core/ui/widget/component todo.txt, "blit camera revamp")
---------------------------------------------------------------------------
Every blit was queued whether or not the object was inside the camera's view
space. That was fast and simple, and it worked because pygame's blits()
clips for you -- but it gave the engine no way to answer three questions it
needs to answer:

    is this object visible at all?
    is it FULLY contained, or straddling the edge?
    which exact pixels of it are going to be drawn?

Measured on the shipped scene: dragging the test window off the left edge
left 51 of 63 tokens fully off-screen, still constructed and still submitted
to SDL every frame.

This module answers all three from one calculation. `clip_to_view` returns
the destination and the source sub-rect already reduced to the pixels that
land inside the clip region, or None when nothing does -- so a caller both
culls and gets its exact draw area from a single call.

SPACES
------
Everything here is "whatever space the caller is working in", as long as
`target` and `clip` agree:

    entities     world space  -> clip is camera.view_area
    map layers   world space  -> clip is camera.view_area
    UI           screen space -> clip is the screen rect

That is the whole reason this is a free function and not a method on
GameCamera: UI has no camera, but it has the same problem.
"""
from __future__ import annotations

from enum import IntEnum
from typing import NamedTuple

from pygame import Rect


class Containment(IntEnum):
    """How much of a rect lies inside a clip region."""

    OUTSIDE = 0
    """No overlap. Nothing to draw."""
    PARTIAL = 1
    """Straddles an edge. Draw the intersection."""
    CONTAINED = 2
    """Entirely inside. Draw it whole; no clipping needed."""


def containment(target: Rect, clip: Rect) -> Containment:
    """Classify `target` against `clip` without allocating an intersection."""
    if not clip.colliderect(target):
        return Containment.OUTSIDE
    if (target.left >= clip.left and target.top >= clip.top
            and target.right <= clip.right and target.bottom <= clip.bottom):
        return Containment.CONTAINED
    return Containment.PARTIAL


class ClippedBlit(NamedTuple):
    """The exact pixels to draw, and where."""

    destination: tuple[int, int]
    """Top-left in clip space."""
    source_area: Rect
    """Sub-rect of the SOURCE surface to read from."""
    containment: Containment
    """CONTAINED or PARTIAL. OUTSIDE never produces a ClippedBlit."""


def clip_to_view(target: Rect,
                 clip: Rect,
                 source_origin: tuple[int, int] = (0, 0)) -> ClippedBlit | None:
    """Reduce a draw to the pixels that actually land inside `clip`.

    target        where the image would be drawn, in clip space
    clip          the visible region (camera view area, or the screen)
    source_origin top-left of the region of the SOURCE surface that `target`
                  corresponds to. Non-zero when the caller is already drawing
                  a sub-image, e.g. a component clipped to a scroll panel.

    Returns None when nothing is visible, so callers cull and clip in one
    step and cannot accidentally do one without the other.
    """
    how = containment(target, clip)
    if how is Containment.OUTSIDE:
        return None

    if how is Containment.CONTAINED:
        return ClippedBlit(
            destination=(target.x, target.y),
            source_area=Rect(source_origin[0], source_origin[1], target.width, target.height),
            containment=how,
        )

    visible = target.clip(clip)
    # How far into `target` the visible part starts; the same offset applies
    # into the source surface.
    dx = visible.x - target.x
    dy = visible.y - target.y
    return ClippedBlit(
        destination=(visible.x, visible.y),
        source_area=Rect(source_origin[0] + dx, source_origin[1] + dy,
                         visible.width, visible.height),
        containment=how,
    )
