"""Verify GameWindow drag, close and focus behaviour with synthetic input."""
from __future__ import annotations

import _bootstrap  # noqa: F401

import sys

import pygame

pygame.init()
pygame.display.set_mode((1024, 768))

from pygame import Rect, Vector2

from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.ui.widget.containers.window import GameWindow
from scripts.game.demo_window import DemoWindow

failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<50} got={got} want={want}")
    if not ok:
        failures.append(label)


def make_window():
    # DemoWindow: the focus assertions need a focusable child, and those
    # live in the demo tree now rather than on GameWindow itself.
    w = DemoWindow(bounds=Rect(100, 100, 400, 400))
    w.core_lifecycle_prepare(PyoneerEvent(GameEventType.PREPARE, sender=None, data={}))
    return w


def mouse_event(kind, pos, button=pygame.BUTTON_LEFT):
    py = pygame.event.Event(
        pygame.MOUSEBUTTONDOWN if kind != "motion" else pygame.MOUSEMOTION,
        {"pos": pos, "button": button},
    )
    return PyoneerEvent(GameEventType.MOUSE_DOWN, py_event=py, data={})


win = make_window()

print("window starts active so its subtree receives input")
expect("active", win.active, True)
expect("visible", win.visible, True)
expect("accepts_input", win.accepts_input, True)

print()
print("dragging by the header")
header = win.header_bar.world_bounds
grab = (header.x + 50, header.y + 5)
win._GameWindow__event_mouse_down_within_header(mouse_event("down", grab))
expect("drag started", win.dragging_component, True)
expect("offset captured", tuple(win.dragging_offset), (50.0, 5.0))

win._GameWindow__event_mouse_dragging_window(mouse_event("motion", (grab[0] + 30, grab[1] + 20)))
expect("window moved by the drag delta",
       (win.world_bounds.x, win.world_bounds.y), (130, 120))

win._GameWindow__event_mouse_up_dropping_window(mouse_event("down", (0, 0)))
expect("drag ended", win.dragging_component, False)

print()
print("a stray MOUSE_DRAGGING while not dragging does not raise")
try:
    win._GameWindow__event_mouse_dragging_window(mouse_event("motion", (500, 500)))
    print("  ok   no TypeError from a None drag offset")
except TypeError as exc:
    print(f"  FAIL {exc}")
    failures.append("stray drag")

print()
print("pressing the close button does not start a drag")
win2 = make_window()
close_rect = win2.close_button.world_bounds
win2._GameWindow__event_mouse_down_within_header(
    mouse_event("down", (close_rect.x + 5, close_rect.y + 5)))
expect("close button press did not drag", win2.dragging_component, False)

print()
print("close() hides AND disables")
win2.close()
expect("hidden", win2.visible, False)
expect("disabled", win2.active, False)
expect("stops accepting input", win2.accepts_input, False)

print()
print("hidden but still active keeps accepting input (the specified case)")
win3 = make_window()
win3.visible = False
expect("visible False", win3.visible, False)
expect("active still True", win3.active, True)
expect("still accepts input", win3.accepts_input, True)

print()
print("focus moves between widgets")
win4 = make_window()
tb = win4.text_box
win4.set_focus(tb)
expect("text box focused", tb.focused, True)
expect("tracked as active_component", win4.active_component is tb, True)
win4.set_focus(None)
expect("focus cleared", tb.focused, False)

print()
print("losing focus mid-drag does not leave the drag latched")
# A window that loses focus mid-drag never sees the MOUSEBUTTONUP, so
# dragging and mouse_down stay True forever and the next motion drags a
# window nobody grabbed. Delivered through the REAL path -- buffer, then the
# UPDATE fan-out -- so this asserts the bind exists, not just the body.
win5 = make_window()
mouse5 = win5.components["mouse"]
mouse5.dragging = True
mouse5.mouse_down = True
mouse5.mouse_down_inside = True
mouse5.mouse_inside = True

focus_lost = PyoneerEvent(GameEventType.PYGAME,
                          py_event=pygame.event.Event(pygame.WINDOWFOCUSLOST, {}),
                          data={})
expect("the pygame event translated", focus_lost.type,
       GameEventType.WINDOW_FOCUS_LOST)
mouse5.buffer_custom_events(focus_lost)
mouse5.core_frame_update(PyoneerEvent(GameEventType.UPDATE, sender=None,
                                      data={"delta": 0.016}))
expect("dragging cleared", mouse5.dragging, False)
expect("mouse_down cleared", mouse5.mouse_down, False)
expect("mouse_down_inside cleared", mouse5.mouse_down_inside, False)
expect("mouse_inside cleared", mouse5.mouse_inside, False)

# Assert the binds themselves, so deleting either one fails loudly even
# though __reset_mouse's body would still be correct.
expect("WINDOW_FOCUS_LOST is bound on the mouse component",
       GameEventType.WINDOW_FOCUS_LOST in mouse5.async_callbacks, True)
expect("DISPOSE is bound on the mouse component",
       GameEventType.DISPOSE in mouse5.callbacks, True)

print()
print("depth is settable on a window (bring-to-front)")
try:
    win4.depth = 250
    expect("depth set", win4.depth, 250)
except AttributeError as exc:
    print(f"  FAIL {exc}")
    failures.append("window depth")

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
