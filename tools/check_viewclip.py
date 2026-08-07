"""Verify exact-pixel clipping and culling.

Implements the "blit camera revamp" from
scripts/core/ui/widget/component todo.txt. The three questions that section
says the engine could not answer:

    is this visible at all?          -> Containment.OUTSIDE
    is it FULLY contained?           -> Containment.CONTAINED vs PARTIAL
    which exact pixels get drawn?    -> ClippedBlit.source_area
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import sys

import pygame

pygame.init()
pygame.display.set_mode((1024, 768))

from pygame import Rect

import main as main_module
from scripts.core import blitpool
from scripts.core.viewclip import Containment, clip_to_view, containment

failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<52} got={got} want={want}")
    if not ok:
        failures.append(label)


CLIP = Rect(0, 0, 100, 100)

print("containment classification")
expect("fully inside", containment(Rect(10, 10, 20, 20), CLIP), Containment.CONTAINED)
expect("exactly the clip", containment(Rect(0, 0, 100, 100), CLIP), Containment.CONTAINED)
expect("straddling the right edge", containment(Rect(90, 10, 20, 20), CLIP), Containment.PARTIAL)
expect("straddling the top-left", containment(Rect(-5, -5, 20, 20), CLIP), Containment.PARTIAL)
expect("entirely left", containment(Rect(-50, 10, 20, 20), CLIP), Containment.OUTSIDE)
expect("entirely below", containment(Rect(10, 200, 20, 20), CLIP), Containment.OUTSIDE)
expect("touching but not overlapping", containment(Rect(100, 10, 20, 20), CLIP), Containment.OUTSIDE)

print()
print("clip_to_view returns the exact visible pixels")
inside = clip_to_view(Rect(10, 20, 30, 40), CLIP)
expect("contained keeps its destination", inside.destination, (10, 20))
expect("contained reads the whole source", inside.source_area, Rect(0, 0, 30, 40))

right = clip_to_view(Rect(90, 10, 20, 20), CLIP)
expect("right-clipped destination unchanged", right.destination, (90, 10))
expect("right-clipped source is narrowed", right.source_area, Rect(0, 0, 10, 20))

left = clip_to_view(Rect(-6, 10, 20, 20), CLIP)
expect("left-clipped destination moves to the edge", left.destination, (0, 10))
expect("left-clipped source skips the hidden pixels", left.source_area, Rect(6, 0, 14, 20))

top = clip_to_view(Rect(10, -8, 20, 30), CLIP)
expect("top-clipped destination moves to the edge", top.destination, (10, 0))
expect("top-clipped source skips the hidden rows", top.source_area, Rect(0, 8, 20, 22))

expect("outside returns None", clip_to_view(Rect(-99, -99, 10, 10), CLIP), None)

print()
print("source_origin offsets compose (component already inside a panel)")
offset = clip_to_view(Rect(-6, 10, 20, 20), CLIP, source_origin=(100, 200))
expect("origin is added to the clipped source", offset.source_area, Rect(106, 200, 14, 20))

print()
print("live scene: off-screen UI is culled, not queued")
game = main_module.MainGame(autostart=False)
game.begin(max_frames=2)
win = game.window
screen = pygame.display.get_surface().get_rect()


def frame_stats():
    captured = {}
    original = blitpool.BlitPool.get_blit_pool_pygame

    @staticmethod
    def spy(clear=True):
        tokens = []
        for depth in blitpool.ORGANIZED_BLITS.values():
            for prio in depth.values():
                tokens.extend(prio)
        outside = 0
        for t in tokens:
            if t.image is None:
                continue
            w = t.draw_area.width if (t.draw_area and t.draw_area.width) else t.image.get_width()
            h = t.draw_area.height if (t.draw_area and t.draw_area.height) else t.image.get_height()
            if not screen.colliderect(Rect(int(t.destination[0]), int(t.destination[1]), w, h)):
                outside += 1
        captured["total"] = len(tokens)
        captured["outside"] = outside
        captured["culled"] = blitpool.BlitPool.culled()
        return original(clear)

    blitpool.BlitPool.get_blit_pool_pygame = spy
    try:
        game.tick()
    finally:
        blitpool.BlitPool.get_blit_pool_pygame = original
    return captured


win.move(100, 100)
on = frame_stats()
print(f"       on-screen : {on['total']} tokens, {on['culled']} culled")
expect("nothing queued outside the screen", on["outside"], 0)
expect("on-screen window still draws", on["total"] > 12, True)

win.move(-900, 100)
off = frame_stats()
print(f"       off-screen: {off['total']} tokens, {off['culled']} culled")
expect("no off-screen tokens queued", off["outside"], 0)
expect("token count drops sharply", off["total"] < on["total"], True)
expect("culling is recorded, not silent", off["culled"] > 0, True)

win.move(100, 100)
back = frame_stats()
expect("returning on screen restores the tokens", back["total"], on["total"])

print()
print("a straddling window reports PARTIAL")
win.move(-200, 100)
frame_stats()
partials = []


def walk(c):
    if hasattr(c, "last_containment"):
        partials.append(c.last_containment)
    for ch in getattr(c, "components", {}).values():
        walk(ch)


walk(win)
expect("some component reports PARTIAL", Containment.PARTIAL in partials, True)
win.move(100, 100)
frame_stats()

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
