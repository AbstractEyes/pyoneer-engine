from __future__ import annotations
from pygame import surface

from event_types import GameEventType
from deprecated.state.widget_state_interactive import WidgetStateInteractive

from scripts.core.ui.deprecated.widget_drawable import WidgetDrawable
from scripts.core.ui.deprecated.widget_events import WidgetEvent


class WidgetInteractive(WidgetDrawable):
    def __init__(self, state: WidgetStateInteractive = None, *args, **kwargs):
        self.index = 0  # the index of the widget in the widget group
        if isinstance(state, WidgetStateInteractive):
            self.default_state: WidgetStateInteractive = WidgetStateInteractive().copy(state)
            self.state: WidgetStateInteractive = WidgetStateInteractive().copy(state)
        super().__init__(*args, **kwargs)
        # mouse events
        self.mouse_click_down_event: WidgetEvent = WidgetEvent(GameEventType.MOUSE_DOWN,
                                                               self.get_method('mouse_down'))
        self.mouse_click_up_event: WidgetEvent = WidgetEvent(GameEventType.MOUSE_UP,
                                                             self.get_method('mouse_up'))
        self.mouse_hold_event: WidgetEvent = WidgetEvent(GameEventType.MOUSE_HOLD,
                                                         self.get_method('mouse_hold'))
        self.mouse_move_event: WidgetEvent = WidgetEvent(GameEventType.MOUSE_MOVE,
                                                         self.get_method('mouse_move'))
        self.mouse_move_in_event: WidgetEvent = WidgetEvent(GameEventType.MOUSE_MOVE_IN,
                                                            self.get_method('mouse_move_in'))
        self.mouse_move_out_event: WidgetEvent = WidgetEvent(GameEventType.MOUSE_MOVE_OUT,
                                                             self.get_method('mouse_move_out'))
        # keyboard events
        self.key_down_event: WidgetEvent = WidgetEvent(GameEventType.KEY_DOWN,
                                                       self.get_method('key_down'))
        self.key_up_event: WidgetEvent = WidgetEvent(GameEventType.KEY_UP,
                                                     self.get_method('key_up'))
        self.key_hold_event: WidgetEvent = WidgetEvent(GameEventType.KEY_HOLD,
                                                       self.get_method('key_hold'))

        # gamepad events
        self.gamepad_button_pressed_event: WidgetEvent = WidgetEvent(GameEventType.GAMEPAD_BUTTON_PRESSED,
                                                                     self.get_method('gamepad_button_pressed'))
        self.gamepad_button_released_event: WidgetEvent = WidgetEvent(GameEventType.GAMEPAD_BUTTON_RELEASED,
                                                                      self.get_method('gamepad_button_released'))
        self.gamepad_button_held_event: WidgetEvent = WidgetEvent(GameEventType.GAMEPAD_BUTTON_HELD,
                                                                  self.get_method('gamepad_button_held'))
        self.gamepad_axis_event: WidgetEvent = WidgetEvent(GameEventType.GAMEPAD_AXIS,
                                                           self.get_method('gamepad_axis'))
        self.gamepad_hat_event: WidgetEvent = WidgetEvent(GameEventType.GAMEPAD_HAT,
                                                          self.get_method('gamepad_hat'))

    def prepare_background(self) -> surface:
        if self.state.background_color.o > 0 and self.state.background_color.a > 0:
            self.core_image().fill(self.state.background_color.color())
        return self.core_image()

    def prepare_image(self) -> surface:
        super().prepare_image()
        if self.state.active and self.state.hovered:
            if not self.state.clicking:
                # draws the hover border and background
                if self.state.hover_border_color.o > 0:
                    self.core_image().fill(self.state.hover_border_color.color())
                if self.state.hover_background_color.o > 0:
                    background_bounds = self.state.bounds.inflate(-self.state.border_width, -self.state.border_width)
                    self.core_image().fill(self.state.hover_background_color.color(), background_bounds)
            else:
                # draws the click border and background
                if self.state.click_border_color.o > 0:
                    self.core_image().fill(self.state.click_border_color.color())
                if self.state.click_background_color.o > 0:
                    background_bounds = self.state.bounds.inflate(-self.state.border_width, -self.state.border_width)
                    self.core_image().fill(self.state.click_background_color.color(), background_bounds)
        return self.core_image()

    def core_update(self, dt: float):
        super().core_update(dt)
