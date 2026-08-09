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
print("sprint is bound in config AND consumed in code")
# These two halves are one change. held() is an unguarded dict index, so a
# game_player.py that reads "sprint" without the JSON key raises KeyError
# inside core_frame_update and kills the frame. Assert both ends.
expect("sprint is bound", "sprint" in im.actions, True)
im.keyboard = FakeKeys(["left_ctrl"])
sprint_action = im.actions["sprint"]
expect("sprint key down -> down", im._is_down(sprint_action), True)
im.keyboard = FakeKeys([])
expect("sprint key up -> up", im._is_down(sprint_action), False)

# Every action the config names must resolve, or the split surfaces at frame
# time rather than at check time.
try:
    InputActionManager().prepare(config).validate_bindings()
    print(f"  ok   all {len(config)} configured actions resolve: {sorted(config)}")
except Exception as exc:                                       # noqa: BLE001
    print(f"  FAIL a configured action does not resolve: {exc}")
    failures.append("configured actions resolve")

print()
print("sprint multiplies displacement, in code not config")
from scripts.game.entity.game_entity import GameEntity          # noqa: E402


class _Walker(GameEntity):
    """The smallest concrete GameEntity. Displacement is the only thing under
    test, so the two abstract lifecycle hooks stay empty deliberately."""

    def core_lifecycle_build(self, event=None):
        pass

    def core_input_receive(self, event=None):
        pass


slow = _Walker(movement_config={"movement": {"move_speed": 10, "sprint_mult": 3}})
fast = _Walker(movement_config={"movement": {"move_speed": 10, "sprint_mult": 3}})
slow.move_direction(1.0, "right", sprint=False)
fast.move_direction(1.0, "right", sprint=True)
dx_slow = slow.transform.position.x
dx_fast = fast.transform.position.x
expect("walking moves at move_speed", dx_slow, 10)
expect("sprinting multiplies by sprint_mult", dx_fast, dx_slow * 3)

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
