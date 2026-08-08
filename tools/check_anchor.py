"""Verify anchor-based reflow: children adapt when their parent resizes.

Nothing reflowed before this. Measured: resizing a Panel 200x120 -> 320x220
left its background, both scrollbars and its dead corner at their original
sizes, and resizing a GameWindow left body, title bar, title text, close button
and both inner panels untouched -- which is why window resize was never
finished.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import sys

import pygame

pygame.init()
pygame.display.set_mode((1024, 768))

from pygame import Rect

from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.ui.anchor import Anchor, DEFAULT_ANCHOR, reflow
from scripts.core.ui.widget.containers.panel import Panel
from scripts.core.ui.widget.containers.window import GameWindow
from scripts.core.ui.widget.shape import ShapeComponent

failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<54} got={got} want={want}")
    if not ok:
        failures.append(label)


def prepared(component):
    component.core_lifecycle_prepare(PyoneerEvent(GameEventType.PREPARE, sender=None, data={}))
    component.core_lifecycle_build(PyoneerEvent(GameEventType.BUILD, sender=None, data={}))
    return component


# --------------------------------------------------------------------------
print("the reflow rule itself")
# --------------------------------------------------------------------------
start = Rect(10, 20, 100, 50)
expect("left-only: unchanged", reflow(start, Anchor.LEFT, 40, 30), Rect(10, 20, 100, 50))
expect("right-only: moves by the delta", reflow(start, Anchor.RIGHT, 40, 0), Rect(50, 20, 100, 50))
expect("both: stretches by the delta", reflow(start, Anchor.STRETCH_X, 40, 0), Rect(10, 20, 140, 50))
expect("bottom-only: moves down", reflow(start, Anchor.BOTTOM, 0, 30), Rect(10, 50, 100, 50))
expect("top+bottom: grows taller", reflow(start, Anchor.STRETCH_Y, 0, 30), Rect(10, 20, 100, 80))
expect("ALL fills in both axes", reflow(start, Anchor.ALL, 40, 30), Rect(10, 20, 140, 80))
expect("BOTTOM_RIGHT keeps its size and rides the corner",
       reflow(start, Anchor.BOTTOM_RIGHT, 40, 30), Rect(50, 50, 100, 50))
expect("default is a no-op", reflow(start, DEFAULT_ANCHOR, 40, 30), start)
# A parent shrinking past a stretched child would otherwise produce a negative
# width, and pygame raises on a negative Surface size frames later.
expect("shrinking never produces a degenerate rect",
       reflow(start, Anchor.ALL, -500, -500), Rect(10, 20, 1, 1))

# --------------------------------------------------------------------------
print()
print("default anchoring changes nothing, so this feature is opt-in")
# --------------------------------------------------------------------------
host = ShapeComponent(bounds=Rect(0, 0, 100, 100))
kid = ShapeComponent(parent=host, bounds=Rect(5, 5, 20, 20))
host.bind_component("kid", kid)
expect("default anchor", kid.anchor, DEFAULT_ANCHOR)
host.local_bounds = Rect(0, 0, 400, 400)
expect("an unanchored child does not move or resize", kid.local_bounds, Rect(5, 5, 20, 20))

# --------------------------------------------------------------------------
print()
print("a container reflows its children")
# --------------------------------------------------------------------------
host = ShapeComponent(bounds=Rect(0, 0, 100, 100))
fills = ShapeComponent(parent=host, bounds=Rect(0, 0, 100, 100))
fills.anchor = Anchor.ALL
corner = ShapeComponent(parent=host, bounds=Rect(80, 80, 20, 20))
corner.anchor = Anchor.BOTTOM_RIGHT
strip = ShapeComponent(parent=host, bounds=Rect(0, 0, 100, 10))
strip.anchor = Anchor.TOP | Anchor.STRETCH_X
host.bind_component("fills", fills)
host.bind_component("corner", corner)
host.bind_component("strip", strip)

host.local_bounds = Rect(0, 0, 260, 180)
expect("filling child matches the new size", (fills.local_bounds.width, fills.local_bounds.height), (260, 180))
expect("corner child kept its size", (corner.local_bounds.width, corner.local_bounds.height), (20, 20))
expect("corner child rode the corner", corner.local_bounds.topleft, (240, 160))
expect("strip spans the width, keeps its height",
       (strip.local_bounds.width, strip.local_bounds.height), (260, 10))

print()
print("a DrawComponent's SURFACE follows the reflow, not just its rect")
expect("filling child's surface reallocated", fills.image.get_size(), (260, 180))
expect("corner child's surface unchanged", corner.image.get_size(), (20, 20))

print()
print("reflow is recursive, and anchors hold MARGINS not parent size")
# Anchor.ALL keeps the distance to all four edges; it does not resize a child
# to equal its parent. A 100x100 child in a 260x180 parent has right/bottom
# margins of 160 and 80, and growing the parent by (40, 20) makes the child
# 140x120 -- preserving them. Asserting it should EQUAL the parent was this
# test's own mistake, not the code's. Fill = size it to the parent at
# construction, THEN anchor; the anchor maintains a fit, it does not create one.
inner = ShapeComponent(parent=fills, bounds=Rect(0, 0, 100, 100))
inner.anchor = Anchor.ALL
fills.bind_component("inner", inner)
before_inner = inner.local_bounds.size
before_fills = fills.local_bounds.size
host.local_bounds = Rect(0, 0, 300, 200)
delta = (fills.local_bounds.width - before_fills[0],
         fills.local_bounds.height - before_fills[1])
expect("the parent chain propagated a delta", delta, (40, 20))
expect("grandchild grew by the SAME delta, two levels down",
       inner.local_bounds.size, (before_inner[0] + 40, before_inner[1] + 20))

filled = ShapeComponent(parent=fills, bounds=fills.local_bounds.copy())
filled.local_bounds = Rect(0, 0, fills.local_bounds.width, fills.local_bounds.height)
filled.anchor = Anchor.ALL
fills.bind_component("filled", filled)
host.local_bounds = Rect(0, 0, 340, 240)
expect("a child sized to its parent then anchored DOES keep filling",
       filled.local_bounds.size, fills.local_bounds.size)

# --------------------------------------------------------------------------
print()
print("Panel chrome follows a resize")
# --------------------------------------------------------------------------
panel = prepared(Panel(bounds=Rect(0, 0, 200, 120), working_area=Rect(0, 0, 200, 120)))
before_corner = panel.dead_corner.local_bounds.topleft
panel.local_bounds = Rect(0, 0, 320, 220)
expect("background fills the panel",
       (panel.background.local_bounds.width, panel.background.local_bounds.height), (320, 220))
expect("vertical scrollbar spans the height", panel.vertical_scroll.local_bounds.height, 220)
expect("horizontal scrollbar spans the width", panel.horizontal_scroll.local_bounds.width, 320)
expect("dead corner kept its size",
       (panel.dead_corner.local_bounds.width, panel.dead_corner.local_bounds.height), (14, 14))
expect("dead corner moved by the resize delta",
       panel.dead_corner.local_bounds.topleft,
       (before_corner[0] + 120, before_corner[1] + 100))

# --------------------------------------------------------------------------
print()
print("GameWindow is now genuinely resizable")
# --------------------------------------------------------------------------
window = prepared(GameWindow(header_text="Test", bounds=Rect(0, 0, 400, 400)))
window.local_bounds = Rect(0, 0, 560, 300)
expect("body fills the window",
       (window.body.local_bounds.width, window.body.local_bounds.height), (560, 300))
expect("title bar spans the width, keeps its height",
       (window.header_bar.local_bounds.width, window.header_bar.local_bounds.height),
       (560, window.header_height))
expect("close button kept its size",
       (window.close_button.local_bounds.width, window.close_button.local_bounds.height), (30, 24))
expect("close button stayed pinned to the right edge",
       window.close_button.local_bounds.right, 560)
expect("inner panel widened", window.panel.local_bounds.width, 500)

print()
print("and shrinking does not invert anything")
window.local_bounds = Rect(0, 0, 120, 80)
expect("body shrank without going negative",
       window.body.local_bounds.width > 0 and window.body.local_bounds.height > 0, True)
expect("body surface matches its rect",
       window.body.image.get_size(),
       (window.body.local_bounds.width, window.body.local_bounds.height))

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
