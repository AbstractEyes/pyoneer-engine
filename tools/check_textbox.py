"""Verify TextBox placeholder semantics and text auto-fitting.

Three defects, all reported from a real run:
  1. The font did not fit a resized box -- size was hardcoded to 24 and never
     re-fitted.
  2. The text offset was "janky": the display component was built at
     Rect(20, 20, w - 10, h - 10), so a 20px inset on a 32px-tall box pushed
     the text almost out of frame, and TextComponent centred horizontally by
     blitting at the TEXT's own centerx -- a number unrelated to the
     destination -- and never centred vertically at all.
  3. `default_text` was assigned straight into the value, so the prompt was
     indistinguishable from typed content.
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
from scripts.core.ui.widget.containers.text_box import TextBox
from scripts.core.ui.widget.text import TextComponent, get_font

failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<54} got={got} want={want}")
    if not ok:
        failures.append(label)


def press(box, unicode_char="", key=None):
    event = pygame.event.Event(pygame.KEYDOWN,
                               {"key": key if key is not None else ord(unicode_char or "a"),
                                "unicode": unicode_char})
    box.key_down(PyoneerEvent(GameEventType.KEY_DOWN, py_event=event, data={}))


def make(width=200, height=32, placeholder="Type here..."):
    return TextBox(bounds=Rect(0, 0, width, height), default_text=placeholder)


# --------------------------------------------------------------------------
print("placeholder is not the value")
# --------------------------------------------------------------------------
box = make()
expect("value starts empty", box.value, "")
expect("placeholder is stored separately", box.placeholder, "Type here...")
expect("showing the placeholder", box.showing_placeholder, True)
expect("display shows the placeholder", box.text_display.text, "Type here...")
expect("placeholder is drawn in the placeholder colour",
       box.text_display.text_color is box.placeholder_color, True)

print()
print("focusing clears the prompt so the user types into a blank field")
box.focused = True
expect("no longer showing the placeholder", box.showing_placeholder, False)
expect("display is blank", box.text_display.text, "")
expect("value is still empty", box.value, "")

print()
print("typing builds the value")
for char in "abc":
    press(box, char)
expect("value accumulated", box.value, "abc")
expect("display follows the value", box.text_display.text.rstrip("|"), "abc")
expect("text colour, not placeholder colour",
       box.text_display.text_color is box.text_color, True)

print()
print("blurring with content keeps the content")
box.focused = False
expect("value survives blur", box.value, "abc")
expect("still not showing the placeholder", box.showing_placeholder, False)
expect("display shows the value", box.text_display.text, "abc")

print()
print("re-focusing continues from the existing value")
box.focused = True
press(box, "d")
expect("typing appended, did not restart", box.value, "abcd")

print()
print("clearing it and blurring brings the placeholder back")
for _ in range(4):
    press(box, key=pygame.K_BACKSPACE)
expect("value emptied by backspace", box.value, "")
expect("focused and empty shows nothing, not the prompt", box.text_display.text.rstrip("|"), "")
box.focused = False
expect("blurred and empty shows the prompt again", box.text_display.text, "Type here...")
expect("and in the placeholder colour",
       box.text_display.text_color is box.placeholder_color, True)

print()
print("control keys do not enter the value")
box = make()
box.focused = True
press(box, "\x08", key=pygame.K_BACKSPACE)   # unicode for backspace
press(box, "\r", key=pygame.K_RETURN)
press(box, "", key=pygame.K_LSHIFT)
expect("no control characters accumulated", box.value, "")
press(box, "x")
expect("printable characters still work", box.value, "x")

print()
print("max_length is enforced")
box = TextBox(bounds=Rect(0, 0, 200, 32), default_text="", max_length=5)
box.focused = True
for char in "abcdefghij":
    press(box, char)
expect("stops at max_length", box.value, "abcde")

# --------------------------------------------------------------------------
print()
print("the caret never contaminates the value")
# --------------------------------------------------------------------------
box = make()
box.focused = True
press(box, "h")
for _ in range(4):
    box.update_carat(PyoneerEvent(GameEventType.UPDATE, data={"delta": 999}))
expect("value has no caret in it", box.value, "h")
box.focused = False
expect("blurring strips the caret from the display", box.text_display.text, "h")
expect("and the value is still clean", box.value, "h")

# --------------------------------------------------------------------------
print()
print("text is placed against the DESTINATION, not its own width")
# --------------------------------------------------------------------------
label = TextComponent(bounds=Rect(0, 0, 200, 40), text="hi", font_size=16,
                      center=True, center_vertical=True, text_shadow_visible=False)
font, _ = label.fitted_font()
rendered = font.render("hi", True, label.text_color)
x, y = label.text_position(rendered)
expect("horizontally centred in the box",
       x, (200 - rendered.get_width()) // 2)
expect("vertically centred in the box",
       y, (40 - rendered.get_height()) // 2)
expect("centred x is not the text's own centerx", x != rendered.get_width() // 2, True)

left = TextComponent(bounds=Rect(0, 0, 200, 40), text="hi", font_size=16,
                     center=False, center_vertical=True, text_shadow_visible=False)
lx, ly = left.text_position(rendered)
expect("left-aligned sits at the padding", lx, left.padding[0])
expect("but is still vertically centred", ly, (40 - rendered.get_height()) // 2)

# --------------------------------------------------------------------------
print()
print("auto-fit shrinks the font to fit, within the theme's clamp")
# --------------------------------------------------------------------------
big = TextComponent(bounds=Rect(0, 0, 400, 60), text="fits easily",
                    font_size=24, auto_fit=True, text_shadow_visible=False)
_, size_big = big.fitted_font()
expect("a roomy box keeps the requested size", size_big, 24)

tight = TextComponent(bounds=Rect(0, 0, 60, 14), text="a much longer piece of text",
                      font_size=24, auto_fit=True, text_shadow_visible=False)
_, size_tight = tight.fitted_font()
expect("a tight box shrinks", size_tight < 24, True)
expect("never below min_font_size", size_tight >= tight.min_font_size, True)

expect("auto_fit never grows past the requested size",
       TextComponent(bounds=Rect(0, 0, 900, 300), text="x", font_size=12,
                     auto_fit=True, text_shadow_visible=False).fitted_font()[1], 12)

print()
print("resizing a box re-fits its text")
box = make(width=400, height=48)
box.focused = True
for char in "a fairly long line of text":
    press(box, char)
before = box.text_display.font_size
box.local_bounds = Rect(0, 0, 90, 18)
after = box.text_display.font_size
expect("the display followed the box", box.text_display.local_bounds.size, (90, 18))
expect("the font shrank with it", after < before, True)
expect("and stayed legible", after >= box.text_display.min_font_size, True)

font_now = get_font(box.text_display.font, after)
width, height = font_now.size(box.text_display.text)
expect("the text now fits its box",
       width <= 90 and height <= 18, True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
