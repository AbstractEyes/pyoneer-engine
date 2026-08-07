from __future__ import annotations
import string
from enum import Enum
from typing import Optional, Callable

import pygame

from scripts.core.event_manager import PyoneerEvent
from event_types import GameEventType
from scripts.core.ui.widget.behavior.async_ import AsyncEventComponent
from component import Config


class KeyBindingSetting(int, Enum):
    ALL = 0
    ALPHA = 1
    NUMERIC = 2
    ALNUM = 3
    PUNCTUATION = 4
    WINSAFE = 5
    WHITESPACE = 6
    FUNCTION = 7
    CUSTOM = 10


class KeyBindingType(Enum):
    KeyDown = pygame.KEYDOWN
    KeyUp = pygame.KEYUP
    KeyRepeat = 69696969


def is_function_key(key: str) -> bool:
    return pygame.key.key_code(key) in [
        pygame.K_F1, pygame.K_F2, pygame.K_F3, pygame.K_F4, pygame.K_F5, pygame.K_F6,
        pygame.K_F7, pygame.K_F8, pygame.K_F9, pygame.K_F10, pygame.K_F11, pygame.K_F12,
        pygame.K_BACKSPACE, pygame.K_TAB, pygame.K_RETURN, pygame.K_ESCAPE, pygame.KMOD_SHIFT,
        pygame.K_LSHIFT, pygame.K_RSHIFT, pygame.KMOD_CTRL, pygame.K_LCTRL, pygame.K_RCTRL,
        pygame.KMOD_ALT, pygame.K_LALT, pygame.K_RALT, pygame.KMOD_META, pygame.K_LMETA,
        pygame.K_RMETA, pygame.K_CAPSLOCK, pygame.K_NUMLOCK, pygame.K_SCROLLOCK, pygame.K_INSERT,
        pygame.K_DELETE, pygame.K_HOME, pygame.K_END, pygame.K_PAGEUP, pygame.K_PAGEDOWN,
        pygame.K_PRINT, pygame.K_SYSREQ, pygame.K_PAUSE, pygame.K_BREAK, pygame.K_MENU,
        pygame.K_POWER, pygame.K_EURO, pygame.K_HELP
    ]


class KeyboardComponentAsync(AsyncEventComponent):
    """Accepts and processes keyboard events."""

    def __init__(self,
                 settings=None,
                 keymap: list[str | int] | None = None,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = Config.config.get("theme")["input"]
        self.press_repeat_delay: float = float(config.get("keyboard")["timings"]["key_repeat_delay"])
        """The delay between key repeats."""
        self.settings: list[KeyBindingSetting] = settings if settings is not None else config.get("keyboard")["settings"]
        """The settings for the keyboard component."""
        self.keymap: list[int] = keymap
        """The keymap to define what is caught by the keyboard component."""
        self.keys_down: dict[int, list[PyoneerEvent]] = {}
        """The keys currently down."""
        self.key_callbacks: dict[KeyBindingType, list[Callable]] = {}
        """The key callbacks for the keyboard component."""
        self.__already_pressed: list[int] = []
        self.__make()

    def bind_keys(self, keys: list[str | int], unbind: bool = False):
        self.keymap = keys
        if unbind:
            self.settings.clear()
            self.settings.append(KeyBindingSetting.CUSTOM)
            return
        if KeyBindingSetting.CUSTOM not in self.settings:
            self.settings.append(KeyBindingSetting.CUSTOM)

    def unbind_keys(self, keys: list[str | int]):
        for key in keys:
            if key in self.keymap:
                self.keymap.remove(key)

    def bind_key_event(self, event_type: KeyBindingType, callback: Callable):
        if event_type in self.key_callbacks:
            self.key_callbacks[event_type].append(callback)
        else:
            self.key_callbacks[event_type] = [callback]

    def unbind_key_event(self, event_type: pygame.KEYDOWN | pygame.KEYUP = None, callback: Callable = None):
        if event_type is None and callback is None:
            self.key_callbacks.clear()
            return
        if callback is None:
            if event_type in self.key_callbacks:
                self.key_callbacks[event_type].clear()
                return
        if event_type in self.key_callbacks:
            if callback in self.key_callbacks[event_type]:
                self.key_callbacks[event_type].remove(callback)

    def unbind_all_key_events(self):
        self.key_callbacks.clear()

    def is_key_pressed(self, key_in: str | int) -> bool:
        out = False
        key = key_in if isinstance(key_in, str) else pygame.key.name(key_in)
        for setting in self.settings:
            match setting:
                case KeyBindingSetting.ALL:
                    return True
                case KeyBindingSetting.ALPHA:
                    out = key.isalpha() or out
                case KeyBindingSetting.NUMERIC:
                    out = key.isnumeric() or out
                case KeyBindingSetting.CUSTOM:
                    out = self.keymap is not None and key in self.keymap or out
                case KeyBindingSetting.ALNUM:
                    out = key.isalnum() or out
                case KeyBindingSetting.PUNCTUATION:
                    out = key.isalnum() or key in string.punctuation or out
                case KeyBindingSetting.WHITESPACE:
                    out = key.isspace() or out or key in string.whitespace
                case KeyBindingSetting.FUNCTION:
                    out = is_function_key(key) or out
        return out

    def __make(self):
        self.bind_async_listener(GameEventType.KEY_DOWN, self.__key_down)
        self.bind_async_listener(GameEventType.KEY_UP, self.__key_up)
        self.bind_sync_listener(GameEventType.UPDATE, self.__update_key_repeat)
        self.bind_sync_listener(GameEventType.POST_UPDATE, self.clear_keys)

    def clear_keys(self, _):
        self.__already_pressed.clear()

    def __update(self, event: Optional[PyoneerEvent] = None):
        for key, senders in self.keys_down.items():
            for sender in senders:
                for callback in self.key_callbacks[KeyBindingType.KeyDown]:
                    callback(key, sender)

    def __update_key_repeat(self, event: Optional[PyoneerEvent] = None):
        if KeyBindingType.KeyRepeat not in self.key_callbacks:
            return
        # if the key is still down, repeat the key press
        for key, stored_events in self.keys_down.items():
            if key not in self.__already_pressed:
                self.__already_pressed.append(key)
                for stored_event in stored_events:
                    stored_event.data[self.uuid + "key_repeat_timer"] += event.data["delta"]
                    if stored_event.data[self.uuid + "key_repeat_timer"] >= self.press_repeat_delay:
                        stored_event.data[self.uuid + "key_repeat_timer"] = 0
                        stored_event.data["delta"] = event.data["delta"]
                        #print ("Key repeat event;", stored_event)
                        for callback in self.key_callbacks[KeyBindingType.KeyRepeat]:
                            callback(stored_event)

    def __key_down(self, event: Optional[PyoneerEvent] = None):
        if KeyBindingType.KeyDown not in self.key_callbacks or event is None:
            return
        key = event.event.key
        if self.is_key_pressed(key) and key not in self.__already_pressed:
            self.__already_pressed.append(key)
            event.data[self.uuid + "key_repeat_timer"] = 0
            if key not in self.keys_down:
                self.keys_down[key] = [event]
            else:
                self.keys_down[key].append(event)
            # we finished the key down event, now we can call the key down callbacks
            for callback in self.key_callbacks[KeyBindingType.KeyDown]:
                callback(event)

    def __key_up(self, event: Optional[PyoneerEvent] = None):
        #if KeyBindingType.KeyUp not in self.key_callbacks:
        #    return
        #unpacked_keys = self.unpack(data)
        unpacked_key = event.event.key
        if unpacked_key in self.keys_down.keys():
            for key in self.keys_down[unpacked_key]:
                if KeyBindingType.KeyUp in self.key_callbacks:
                    for callback in self.key_callbacks[KeyBindingType.KeyUp]:
                        callback(event)
            del self.keys_down[unpacked_key]

