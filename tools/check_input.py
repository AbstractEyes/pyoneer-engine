"""Verify InputActionManager edge semantics by driving synthetic key state.

Regression guard for the latch bug: `released()` used to return True on the
very first frame and stay True forever, so there was no working edge trigger
anywhere in the engine.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import json
import sys

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

from scripts.core.input import InputActionManager, KEYBOARD, UnknownBindingError

with open("config/inputs.json", encoding="utf-8") as fh:
    config = json.load(fh)

im = InputActionManager().prepare(config)

# Drive the manager with a fake keyboard so this is deterministic.
class FakeKeys:
    def __init__(self, down=()):
        self.down = {KEYBOARD[k] for k in down}

    def __getitem__(self, code):
        return code in self.down


def step(down=()):
    im.keyboard = FakeKeys(down)
    for action in im.actions.values():
        raw = im._is_down(action)
        action.pressed = raw and not action.held
        action.released = action.held and not raw
        action.held = raw
    return (im.pressed("left"), im.held("left"), im.released("left"))


failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<34} got={got} want={want}")
    if not ok:
        failures.append(label)


print("frame-by-frame for action 'left' (bound to keyboard:a)")
expect("idle frame 1  (p,h,r)", step(), (False, False, False))
expect("idle frame 2  (p,h,r)", step(), (False, False, False))
expect("key down      (p,h,r)", step(["a"]), (True, True, False))
expect("key still down(p,h,r)", step(["a"]), (False, True, False))
expect("key still down(p,h,r)", step(["a"]), (False, True, False))
expect("key up        (p,h,r)", step(), (False, False, True))
expect("idle after up (p,h,r)", step(), (False, False, False))
expect("re-press      (p,h,r)", step(["a"]), (True, True, False))

print()
print("multi-binding self-cancel (action bound to two keys)")
im2 = InputActionManager().prepare({"fire": ["keyboard:a", "keyboard:b"]})
im2.keyboard = FakeKeys(["a"])
a = im2.actions["fire"]
raw = im2._is_down(a)
expect("one of two keys down -> down", raw, True)

print()
print("unknown binding fails at load, not mid-frame")
try:
    InputActionManager().prepare({"oops": ["keyboard:not_a_key"]})
    expect("raises UnknownBindingError", False, True)
except UnknownBindingError as exc:
    print(f"  ok   raised: {exc}")

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
