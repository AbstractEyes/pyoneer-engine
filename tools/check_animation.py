"""Verify GameAnimationHandler switching, pausing and resuming.

Regression guard for the stale-frame bug: start(name) used to set
`active = True` directly instead of calling GameAnimation.start(), so the
previous sequence's frame counter survived and image() kept returning the
old sprite -- for up to a second, since idle_down's frame duration is 1000ms.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import sys

import pygame

pygame.init()
pygame.display.set_mode((256, 256))

from config.managers.core_asset_manager import CoreAssetManager
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.game.entity.game_animation import GameAnimationHandler
from scripts.core.errors import PyoneerAssetMissingError

assets = CoreAssetManager()
handler = GameAnimationHandler(assets.animations.get('entity'))

failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<44} got={got} want={want}")
    if not ok:
        failures.append(label)


def offset_of(surface):
    """Where this frame sits on the parent spritesheet."""
    return surface.get_offset() if surface is not None else None


print("spritesheet format")
display_masks = pygame.display.get_surface().get_masks()
expect("sheet matches display pixel format",
       handler._spritesheet.get_masks()[:3], display_masks[:3])

print()
print("switching sequences updates the rendered frame")
handler.start('idle_down')
idle = offset_of(handler.image())
handler.start('walk_right')
walk = offset_of(handler.image())
expect("walk_right differs from idle_down", walk != idle, True)
handler.start('idle_down')
back = offset_of(handler.image())
expect("switching back restores idle_down", back, idle)

print()
print("re-entering a sequence restarts it from frame 0")
walk_anim = handler.get_animation('walk_right')
handler.start('walk_right')
walk_anim.current_frame = 3
handler.start('walk_right')
expect("current_frame reset to 0", walk_anim.current_frame, 0)

print()
print("frames are pre-sliced, not re-cut on demand")
handler.start('walk_right')
a = handler.image()
b = handler.image()
expect("image() returns the same object twice", a is b, True)
expect("every frame pre-sliced", len(walk_anim.surfaces), len(walk_anim.frames))

print()
print("pause / resume")
handler.start('walk_right')
walk_anim.current_frame = 2
frozen = handler.image()
handler.pause()
expect("paused sequence stops advancing", walk_anim.active, False)
# A paused sprite must stay on screen frozen, not disappear.
expect("image() still returns the frozen frame", handler.image() is frozen, True)
handler.update(PyoneerEvent(GameEventType.UPDATE, data={"delta": 10_000}))
expect("paused sequence ignores updates", walk_anim.current_frame, 2)
handler.resume()
expect("resumed sequence is active again", walk_anim.active, True)
expect("resumed at the same frame", walk_anim.current_frame, 2)

print()
print("no-active-animation path does not raise")
handler.stop()
expect("image() returns None, not AttributeError", handler.image(), None)

print()
print("unknown sequence fails loudly")
try:
    handler.start('does_not_exist')
    expect("raises PyoneerAssetMissingError", False, True)
except PyoneerAssetMissingError as exc:
    print(f"  ok   raised: {exc}")

print()
print("advancing time walks frames")
handler.start('walk_right')
ev = PyoneerEvent(GameEventType.UPDATE, data={"delta": 10_000})
before = walk_anim.current_frame
handler.update(ev)
expect("frame advanced after a long delta", walk_anim.current_frame != before, True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
