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


def drive(manager, down=()):
    """Advance `manager` one frame with `down` held.

    Deliberately not `manager.update()`: that re-reads
    pygame.key.get_pressed(), so whatever is really on the keyboard would
    decide the result. The three lines below are the edge derivation
    update() runs, off the fake keyboard instead.
    """
    manager.keyboard = FakeKeys(down)
    for action in manager.actions.values():
        raw = manager._is_down(action)
        action.pressed = raw and not action.held
        action.released = action.held and not raw
        action.held = raw


def step(down=()):
    drive(im, down)
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
print("sprint is bound in config")
# Half of one change. held() is an unguarded dict index, so a game_player.py
# that reads "sprint" without the JSON key raises KeyError inside
# core_frame_update and kills the frame. The other half -- that anything in
# the engine still reads the binding -- is asserted further down, against a
# real GamePlayer.
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
print("the player still reads the sprint binding")
# Everything above this line passes with the consumer deleted. move_direction
# takes sprint= as an argument, so the multiplier keeps working perfectly
# while nothing ever asks for it -- the binding resolves, the key reads as
# down, and the player walks. The only way to catch that is to run a real
# GamePlayer for one input frame and measure how far it moved.
from config.managers.core_asset_manager import CoreAssetManager   # noqa: E402
from scripts.core.event_manager import PyoneerEvent               # noqa: E402
from scripts.core.event_types import GameEventType                # noqa: E402
from scripts.game.entity.game_player import GamePlayer            # noqa: E402

MOVEMENT = {"movement": {"move_speed": 10, "sprint_mult": 3}}
ANIMATIONS = CoreAssetManager().animations.get("entity")


def after_holding(down):
    """A GamePlayer that has processed one input frame with `down` HELD.

    TWO manager frames before the player runs, and the second one is the
    whole point. `drive` computes `pressed = raw and not held`, so on the
    first frame after a key goes down `pressed` and `held` are both True and
    a consumer that reads `pressed("sprint")` where it means `held` is
    indistinguishable from a correct one. The second frame is where they
    diverge: `held` stays True, `pressed` falls to False. The label says
    "holding", so the fixture has to actually hold.

    A fresh manager per player: `held` carries across frames, so sharing one
    would make the second player's edges depend on the first player's run.
    """
    manager = InputActionManager().prepare(config)
    drive(manager, down)      # the rising edge
    drive(manager, down)      # still down: held, no longer pressed
    return manager


def after_one_frame(down):
    """A composed player that has processed one input frame with `down` HELD.

    `behaviors=` is not decoration. Polling the keyboard, displacing the
    entity and naming the animation are three composed behaviors now
    (`scripts/game/behavior/`), and a GamePlayer that composes none of them is
    inert BY DESIGN -- the class no longer decides what an entity does, the
    declaration does. So the fixture has to declare the same list a .tmx
    object would, and this string is exactly what one carries in its
    `pyoneer_behaviors` property. Without it the two assertions below measure
    an entity nothing is driving, which is a true fact about a differently
    configured player and not the claim this section makes.
    """
    manager = after_holding(down)
    player = GamePlayer(input_=manager, movement_config=MOVEMENT,
                        animation_config=ANIMATIONS,
                        behaviors="player_input,topdown_move")
    player.input_move(PyoneerEvent(GameEventType.UPDATE, data={"delta": 1.0}))
    return player


# The fixture is only honest if the two edges really did diverge, so assert
# it here rather than trusting `drive`.
_holding = after_holding(["d", "left_ctrl"])
expect("the fixture holds rather than taps (sprint)",
       (_holding.held("sprint"), _holding.pressed("sprint")), (True, False))
expect("the fixture holds rather than taps (right)",
       (_holding.held("right"), _holding.pressed("right")), (True, False))

walker = after_one_frame(["d"])                  # right
sprinter = after_one_frame(["d", "left_ctrl"])   # right + sprint
expect("holding sprint sets state.sprinting", sprinter.state.sprinting, True)
expect("releasing it clears state.sprinting", walker.state.sprinting, False)
expect("the walking player moved move_speed", walker.transform.position.x, 10)
expect("the sprinting player covered sprint_mult times that",
       sprinter.transform.position.x, walker.transform.position.x * 3)

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
