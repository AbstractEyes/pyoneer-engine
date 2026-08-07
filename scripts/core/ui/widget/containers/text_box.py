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


class TextBox(DrawComponent):
    def __init__(self,
                 default_text: str = "",
                 focused: bool = False,
                 max_length: int = 80,
                 enter_enabled: bool = False,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_view = False
        self.__default_text: str = default_text
        # Typing target = focused, not active. `active` means the widget
        # participates in input at all; a text box that is not focused
        # must still receive clicks so it can BECOME focused.
        self.focused: bool = focused
        self.focusable: bool = True
        self.clickable: bool = True
        self.__enter_enabled: bool = enter_enabled
        self.text: str = self.__default_text
        self.__carat_flash_delay: float = 10
        self.__carat_flash_timer: float = 0
        self.max_length: int = max_length
        self.keyboard: KeyboardComponentAsync | None = None
        self.mouse: MouseComponentAsync | None = None
        self.component_type = "text_box"
        self.__make()

    def __make(self):
        background = ShapeComponent(parent=self,
                                    bounds=Rect(0, 0, self.world_bounds.width, self.world_bounds.height),
                                    depth=1,
                                    background_color=WidgetColor(10, 10, 10, 255, 1),
                                    border_color=WidgetColor(255, 255, 255, 255, 1))
        text = TextComponent(parent=self,
                             depth=2,
                             bounds=Rect(20, 20, self.world_bounds.width - 10, self.world_bounds.height - 10),
                             text=self.text,
                             font_size=24,
                             text_color=WidgetColor(255, 255, 255, 255, 1),
                             text_shadow_color=WidgetColor(120, 120, 120, 255, 1))
        #async_events = AsyncEventComponent(parent=self)
        self.keyboard = KeyboardComponentAsync(parent=self)

        self.mouse = MouseComponentAsync(parent=self)
        self.bind_component("keyboard", self.keyboard)
        self.bind_component("mouse", self.mouse)
        self.bind_component("background", background)
        self.bind_component("text", text)
        self.keyboard.bind_key_event(KeyBindingType.KeyDown, self.key_down)
        self.keyboard.bind_key_event(KeyBindingType.KeyRepeat, self.key_down_repeat)
        self.keyboard.bind_key_event(KeyBindingType.KeyUp, self.key_up)
        text.bind_sync_listener(GameEventType.UPDATE, self.update_carat)

    @staticmethod
    def __unpack_keys(event_args: list[pygame.event.Event]) -> str:
        return "".join([arg.unicode for arg in event_args])

    def update_carat(self, event: Optional[PyoneerEvent]):
        if not self.focused:
            component = self.get_component("text")
            if component.text.endswith("█"):
                component.text = component.text[:-1]
            return
        self.__carat_flash_timer += event.data["delta"]
        if self.__carat_flash_timer >= self.__carat_flash_delay:
            self.__carat_flash_timer = 0
            component = self.get_component("text")
            if component is not None and isinstance(component, TextComponent):
                if component.text.endswith("█"):
                    component.text = component.text[:-1]
                else:
                    component.text += "█"

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
        """Our test keyboard listener, meant to test the input buffer"""
        if event.event is None:
            pass
        if not self.focused:
            return False
        key_code = event.event.key
        keyboard = self.get_component("keyboard")
        key = pygame.key.name(key_code)
        if keyboard is not None and isinstance(keyboard, KeyboardComponentAsync):
            if key_code == pygame.K_BACKSPACE:
                if len(self.text) > 0:
                    self.text = self.text[:-1]
            elif len(self.text) < self.max_length:
                if key_code == pygame.K_RETURN:
                    pass
                else:
                    self.text += str(event.event.unicode)
            component = self.get_component("text")
            if component is not None and isinstance(component, TextComponent):
                component.text = self.text
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

