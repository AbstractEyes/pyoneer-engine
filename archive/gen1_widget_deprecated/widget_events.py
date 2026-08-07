from __future__ import annotations

from enum import Enum


class WidgetEventTypeOld(str, Enum):
    SHOW = 'show'
    HIDE = 'hide'
    UPDATE = 'update'
    ACTIVATE = 'activate'
    DEACTIVATE = 'deactivate'
    MOVE_WIDGET = 'move_widget'
    MOUSE_DOWN = 'mouse_down'
    MOUSE_UP = 'mouse_up'
    MOUSE_HOLD = 'mouse_hold'
    MOUSE_MOVE = 'mouse_move'
    MOUSE_MOVE_IN = 'mouse_move_in'
    MOUSE_MOVE_OUT = 'mouse_move_out'
    KEY_DOWN = 'key_down'
    KEY_UP = 'key_up'
    KEY_HOLD = 'key_hold'
    GAMEPAD_BUTTON_PRESSED = 'gamepad_button_pressed'
    GAMEPAD_BUTTON_RELEASED = 'gamepad_button_released'
    GAMEPAD_BUTTON_HELD = 'gamepad_button_held'
    GAMEPAD_AXIS = 'gamepad_axis'
    GAMEPAD_HAT = 'gamepad_hat'


class WidgetEventArgs:
    def __init__(self, sender: any, event_type: WidgetEventType, *args, **kwargs):
        self.sender = sender
        self.event_type = event_type
        self._args = args
        self._kwargs = kwargs


class WidgetEvent:
    def __init__(self, event_type: WidgetEventType, call=None):
        self.event_type = event_type
        self.call = call

    def __call__(self,  *args, **kwargs):
        if self.call:
            self.call(*args, **kwargs)
        else:
            print(f'Event {self.event_type} not bound to any function')
