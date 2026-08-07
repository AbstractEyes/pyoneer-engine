"""Close/reopen, visibility cascade, and text-capture gating.

Guards three reported defects:
  1. The close button disabled the window but left it on screen: GameWindow
     is a plain GameComponent with no core_render_blits, so `visible=False` on it
     hid nothing -- each child checked only its own `visible`.
  2. No way to bring a closed window back (F1 now toggles it).
  3. The player walked around while the user was typing in a text box.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import sys

import pygame

import main as main_module
from scripts.core import blitpool

failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<52} got={got} want={want}")
    if not ok:
        failures.append(label)


game = main_module.MainGame(autostart=False)
game.begin(max_frames=2)
win = game.window
assert win is not None, "main.py did not expose self.window"

subtree = set()


def collect(c):
    subtree.add(id(c))
    for ch in getattr(c, "components", {}).values():
        collect(ch)


collect(win)


def window_tokens():
    """Blit tokens emitted by the window subtree during one real frame."""
    seen = {}
    original = blitpool.BlitPool.get_blit_pool_pygame

    @staticmethod
    def spy(clear=True):
        n = 0
        for depth in blitpool.ORGANIZED_BLITS.values():
            for prio in depth.values():
                for token in prio:
                    if id(token.sender) in subtree:
                        n += 1
        seen["n"] = n
        return original(clear)

    blitpool.BlitPool.get_blit_pool_pygame = spy
    try:
        game.tick()
    finally:
        blitpool.BlitPool.get_blit_pool_pygame = original
    return seen.get("n", -1)


print("window draws while open")
open_tokens = window_tokens()
expect("open window emits blit tokens", open_tokens > 0, True)
print(f"       {open_tokens} tokens from the window subtree")

print()
print("close() hides the WHOLE subtree, not just the root")
win.close()
expect("visible", win.visible, False)
expect("active", win.active, False)
closed_tokens = window_tokens()
expect("closed window emits ZERO blit tokens", closed_tokens, 0)

print()
print("closed window accepts no input")
expect("accepts_input", win.accepts_input, False)

print()
print("F1 brings it back")
game.toggle_window()
expect("visible again", win.visible, True)
expect("active again", win.active, True)
expect("draws again", window_tokens(), open_tokens)

print()
print("F1 toggles back off")
game.toggle_window()
expect("hidden again", win.visible, False)
game.toggle_window()  # leave it open for the remaining checks

print()
print("hidden-but-active still draws nothing yet still takes input")
win.visible = False
expect("no tokens while hidden", window_tokens(), 0)
expect("still accepts input (active)", win.accepts_input, True)
win.visible = True

print()
print("typing suppresses gameplay input")
inputs = game.input
text_box = win.text_box
expect("no capture initially", inputs.text_capture_active, False)

# Force an action down so held() would otherwise be True.
for action in inputs.actions.values():
    action.held = True
expect("held True before capture", inputs.held("left"), True)

win.set_focus(text_box)
expect("text box focused", text_box.focused, True)
expect("capture claimed", inputs.text_capture_active, True)
expect("capture owner is the text box", inputs.text_capture_owner is text_box, True)
expect("held() inert while typing", inputs.held("left"), False)
expect("pressed() inert while typing", inputs.pressed("left"), False)
expect("released() inert while typing", inputs.released("left"), False)

win.set_focus(None)
expect("capture released on blur", inputs.text_capture_active, False)
expect("held() live again", inputs.held("left"), True)

print()
print("player does not move while a text box holds focus")
player = game.player
player.state.can_move = True

# Hold "right" at the raw key layer. Forcing action.held directly would be
# overwritten by input.update() on the very next tick, which would make this
# assertion pass for the wrong reason.
real_is_down = inputs._is_down
inputs._is_down = lambda action: action.action_type == "right"


def run_frames(n):
    before = (player.transform.position.x, player.transform.position.y)
    for _ in range(n):
        game.tick()
    after = (player.transform.position.x, player.transform.position.y)
    return before != after


try:
    # Sanity: with nothing focused, the injected key really does move him.
    win.set_focus(None)
    expect("baseline - injected key moves the player", run_frames(5), True)

    win.set_focus(text_box)
    expect("player stays put while typing", run_frames(10), False)

    win.set_focus(None)
    expect("player moves again once focus is released", run_frames(5), True)
finally:
    inputs._is_down = real_is_down
    win.set_focus(None)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
