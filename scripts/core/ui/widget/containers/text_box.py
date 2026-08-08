from typing import Optional

import pygame
from pygame import Rect

from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.ui.widget.behavior.keyboard import KeyBindingType, KeyboardComponentAsync
from scripts.core.ui.widget.behavior.mouse import MouseComponentAsync
from scripts.core.ui.widget.draw import DrawComponent
from scripts.core.ui.widget.shape import ShapeComponent
from scripts.core.ui.widget.text import TextComponent
from scripts.core.ui.widget_color import WidgetColor
from scripts.core.ui.anchor import Anchor

from config.managers.core_asset_manager import CoreAssetManager


class TextBox(DrawComponent):
    def __init__(self,
                 default_text: str = "",
                 focused: bool = False,
                 max_length: int = 80,
                 enter_enabled: bool = False,
                 *args, **kwargs):
        """A single-line text field with placeholder semantics.

        `default_text` is a PLACEHOLDER, not a value. It used to be assigned
        straight into self.text, which made it indistinguishable from typed
        content: focusing the box and typing appended to it, and an "empty"
        box reported its prompt as its value.

        Now `value` is what the user typed and `placeholder` is what is shown
        while `value` is empty and the box is not focused. Focusing shows the
        real value -- blank if there is none -- and typing continues from it.
        Blurring an empty box brings the placeholder back.
        """
        super().__init__(*args, **kwargs)
        theme = CoreAssetManager().config.get("theme")["widget"]
        box_theme = theme["textbox"]
        self.is_view = False
        self.placeholder: str = default_text
        self.__value: str = ""
        """What the user actually typed. Never the placeholder."""
        self.focusable: bool = True
        self.clickable: bool = True
        self.__enter_enabled: bool = enter_enabled
        self.__carat_flash_delay: float = box_theme["carat"]["delay"]
        self.__carat_flash_timer: float = 0
        self.__carat_visible: bool = False
        self.max_length: int = max_length
        self.text_color: WidgetColor = WidgetColor().set_list(
            box_theme.get("text_color", [255, 255, 255, 255, 1]))
        self.placeholder_color: WidgetColor = WidgetColor().set_list(
            box_theme.get("placeholder_color", [140, 140, 140, 255, 1]))
        self.auto_fit: bool = bool(box_theme.get("auto_fit", True))
        self.keyboard: KeyboardComponentAsync | None = None
        self.mouse: MouseComponentAsync | None = None
        self.text_display: TextComponent | None = None
        self.component_type = "text_box"
        self.__make()
        # Assigned last: the setter claims keyboard capture as a side effect,
        # and refresh() needs the children to exist.
        self.focused: bool = focused
        self.refresh()

    @property
    def value(self) -> str:
        """The typed content. Empty when the user has entered nothing."""
        return self.__value

    @value.setter
    def value(self, text: str):
        text = "" if text is None else str(text)[:self.max_length]
        if text == self.__value:
            return
        self.__value = text
        self.refresh()

    @property
    def text(self) -> str:
        """Alias for `value`, kept so existing call sites keep working."""
        return self.__value

    @text.setter
    def text(self, value: str):
        self.value = value

    @property
    def showing_placeholder(self) -> bool:
        return not self.__value and not self.focused

    def refresh(self):
        """Push the right string and colour into the display component.

        One place decides what is on screen, so the placeholder cannot leak
        into the value or survive a focus change.
        """
        if self.text_display is None:
            return
        if self.showing_placeholder:
            self.text_display.text_color = self.placeholder_color
            self.text_display.text = self.placeholder
            return
        self.text_display.text_color = self.text_color
        caret = "|" if (self.focused and self.__carat_visible) else ""
        self.text_display.text = self.__value + caret

    def __make(self):
        background = ShapeComponent(parent=self,
                                    bounds=Rect(0, 0, self.world_bounds.width, self.world_bounds.height),
                                    depth=1,
                                    background_color=WidgetColor(10, 10, 10, 255, 1),
                                    border_color=WidgetColor(255, 255, 255, 255, 1))
        background.anchor = Anchor.ALL
        # Fills the box and auto-fits. It used to be built at
        # Rect(20, 20, w - 10, h - 10) with a hardcoded font_size of 24 -- a
        # 20px inset on a 32px-tall box pushed the text almost entirely out of
        # frame, and 24pt could not fit regardless of how the box was resized.
        self.text_display = TextComponent(
            parent=self,
            depth=2,
            bounds=Rect(0, 0, self.world_bounds.width, self.world_bounds.height),
            text="",
            auto_fit=self.auto_fit,
            center=False,
            center_vertical=True,
            text_color=self.text_color,
            text_shadow_visible=False,
        )
        self.text_display.anchor = Anchor.ALL
        self.keyboard = KeyboardComponentAsync(parent=self)
        self.mouse = MouseComponentAsync(parent=self)
        self.bind_component("keyboard", self.keyboard)
        self.bind_component("mouse", self.mouse)
        self.bind_component("background", background)
        self.bind_component("text", self.text_display)
        self.keyboard.bind_key_event(KeyBindingType.KeyDown, self.key_down)
        self.keyboard.bind_key_event(KeyBindingType.KeyRepeat, self.key_down_repeat)
        self.keyboard.bind_key_event(KeyBindingType.KeyUp, self.key_up)
        self.bind_sync_listener(GameEventType.UPDATE, self.update_carat)

    def _on_focus_changed(self, focused: bool):
        """Claim or release the keyboard while this box is the typing target.

        Gameplay actions are POLLED from pygame.key.get_pressed(), not read
        from the event queue, so consuming a KEYDOWN here could never stop the
        player: typing "was" walked the player around the map. The input
        manager has to be told explicitly that the keyboard is spoken for.
        """
        inputs = CoreAssetManager().inputs
        if focused:
            inputs.begin_text_capture(self)
        else:
            inputs.end_text_capture(self)
            self.__carat_visible = False
        # Swap between placeholder and value. Focusing an empty box clears the
        # prompt so the user types into a blank field; blurring it empty brings
        # the prompt back. Focusing a box that HAS a value shows the value and
        # typing continues from it.
        self.refresh()

    @staticmethod
    def __unpack_keys(event_args: list[pygame.event.Event]) -> str:
        return "".join([arg.unicode for arg in event_args])

    def update_carat(self, event: Optional[PyoneerEvent] = None):
        """Blink the caret.

        Tracked as a flag and re-rendered by refresh(), rather than appending
        and stripping a block character on the DISPLAY component. That old
        approach mutated the same string the value was read from, so the caret
        could be typed into the value or left stranded in it on blur.
        """
        if not self.focused:
            if self.__carat_visible:
                self.__carat_visible = False
                self.refresh()
            return
        if event is None or not event.data:
            return
        self.__carat_flash_timer += event.data.get("delta", 0)
        if self.__carat_flash_timer >= self.__carat_flash_delay:
            self.__carat_flash_timer = 0
            self.__carat_visible = not self.__carat_visible
            self.refresh()

    def update_(self, event: Optional[PyoneerEvent] = None):
        pass

    def key_down_repeat(self, event: Optional[PyoneerEvent] = None):
        """Our test keyboard listener, meant to test the input buffer"""
        if not self.focused:
            return False
        return self.key_pressed(event)

    def key_down(self, event: Optional[PyoneerEvent] = None) -> bool:
        if not self.focused:
            return False
        """Our test keyboard listener, meant to test the input buffer"""
        return self.key_pressed(event)

    def key_pressed(self, event: Optional[PyoneerEvent] = None) -> bool:
        """Apply one key to the VALUE. Display follows via refresh()."""
        if not self.focused or event is None or event.event is None:
            return False
        key_code = event.event.key
        if key_code == pygame.K_BACKSPACE:
            self.value = self.__value[:-1]
        elif key_code == pygame.K_RETURN:
            if self.__enter_enabled:
                self.send_event_advanced(GameEventType.USE, None)
        elif len(self.__value) < self.max_length:
            character = str(event.event.unicode)
            # Printable only: control keys arrive with unicode set to things
            # like '' and used to be appended verbatim into the value.
            if character and character.isprintable():
                self.value = self.__value + character
        return True

    def key_up(self, event: Optional[PyoneerEvent]) -> bool:
        #"""Our test keyboard listener, meant to test the input buffer"""
        #keys = self.__unpack_keys(event_args)
        #if len(keys) > 0:
        #    for key in keys:
        #        if key in self.keys_down:
        #            del self.keys_down[key]
        #            return True
        return False

