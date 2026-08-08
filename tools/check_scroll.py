"""Verify scrollbars behave when there is nothing to scroll.

Regression guard for a crash that killed the engine on startup: dragging the
thumb of a scrollbar whose content FITS raised

    ZeroDivisionError: float division by zero
    scroll.py: scroll_ratio = thumb_position / (bar.width - thumb.width)

A thumb that fills its bar has zero travel, so that denominator is zero. The
sibling calculation in __scroll_thumb_bounds already guarded the same quantity
(`if max_scroll_position != 0 else 0`); the drag path did not.

It only surfaced when the demo window's panel was given a working area the same
width as the panel. The previous demo used 1000x1000, which always overflowed
both axes and hid the bug.
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
from scripts.core.ui.widget.containers.panel import Panel

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


def drag_thumb(scroll, dx=5, dy=5):
    """Drive the real drag handler, as a mouse move would."""
    scroll.dragging_scroll_thumb = True
    centre = scroll.scroll_thumb.world_bounds.center
    event = pygame.event.Event(pygame.MOUSEMOTION,
                               {"pos": (centre[0] + dx, centre[1] + dy),
                                "rel": (dx, dy), "buttons": (1, 0, 0)})
    scroll._ScrollComponent__event__mouse_drag_scroll_thumb(
        type("E", (), {"event": event})())


# --------------------------------------------------------------------------
print("a panel whose content fits has no usable scrollbars")
# --------------------------------------------------------------------------
fits = prepared(Panel(bounds=Rect(0, 0, 200, 150), working_area=Rect(0, 0, 200, 150)))
fits.fit_scroll_area()
for name, scroll in (("vertical", fits.vertical_scroll), ("horizontal", fits.horizontal_scroll)):
    expect(f"{name}: no overflow", scroll.has_overflow, False)
    expect(f"{name}: hidden", scroll.visible, False)
    expect(f"{name}: inactive, so it cannot be dragged", scroll.active, False)
    expect(f"{name}: does not accept input", scroll.accepts_input, False)

print()
print("dragging a no-overflow thumb does not raise")
for name, scroll in (("vertical", fits.vertical_scroll), ("horizontal", fits.horizontal_scroll)):
    try:
        drag_thumb(scroll)
        print(f"  ok   {name}: no exception, position stayed {scroll.scroll_position}")
        expect(f"{name}: position unchanged", scroll.scroll_position, 0)
    except ZeroDivisionError as exc:
        print(f"  FAIL {name}: ZeroDivisionError: {exc}")
        failures.append(f"{name} drag")

print()
print("a zero-sized scroll area is legal and does not divide by zero")
empty = prepared(Panel(bounds=Rect(0, 0, 120, 90), working_area=Rect(0, 0, 0, 0)))
try:
    empty.fit_scroll_area()
    drag_thumb(empty.vertical_scroll)
    print("  ok   empty panel survived fit_scroll_area and a drag")
except ZeroDivisionError as exc:
    print(f"  FAIL ZeroDivisionError: {exc}")
    failures.append("empty panel")

# --------------------------------------------------------------------------
print()
print("overflow on one axis only activates that axis")
# --------------------------------------------------------------------------
tall = prepared(Panel(bounds=Rect(0, 0, 200, 150), working_area=Rect(0, 0, 200, 600)))
# Attach real content. fit_scroll_area() measures ATTACHED CHILDREN, so calling
# it on a panel that merely DECLARED a large working_area collapses the area to
# the panel's own size -- which is what its name says it does, and what caught
# this test out on the first run. Pass `minimum` if a declared floor is wanted.
from scripts.core.ui.widget.shape import ShapeComponent
tall.attach_component("content", ShapeComponent(bounds=Rect(0, 0, 180, 600)))
tall.fit_scroll_area()
expect("vertical has overflow", tall.vertical_scroll.has_overflow, True)
expect("vertical is visible", tall.vertical_scroll.visible, True)
expect("vertical is active", tall.vertical_scroll.active, True)
expect("horizontal has none", tall.horizontal_scroll.has_overflow, False)
expect("horizontal is hidden", tall.horizontal_scroll.visible, False)

print()
print("the scrollable axis still scrolls")
before = tall.vertical_scroll.scroll_position
drag_thumb(tall.vertical_scroll, dx=0, dy=30)
expect("dragging a real scrollbar moves it", tall.vertical_scroll.scroll_position != before, True)
expect("and it stays within its range",
       0 <= tall.vertical_scroll.scroll_position <= 600 - 150, True)

print()
print("overflow appearing later re-enables the bar")
fits.screen_area = Rect(0, 0, 200, 900)
for scroll in (fits.vertical_scroll, fits.horizontal_scroll):
    scroll.scrollable_bounds = Rect(0, 0, 200, 900)
fits.send_event_advanced(GameEventType.UPDATE,
                         PyoneerEvent(GameEventType.UPDATE, sender=None, data={"delta": 1}))
expect("vertical came back", fits.vertical_scroll.visible, True)
expect("vertical is draggable again", fits.vertical_scroll.active, True)
expect("horizontal still has nothing to do", fits.horizontal_scroll.visible, False)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
