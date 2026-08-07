from __future__ import annotations

from scripts.core.ui.widget_color import WidgetColor


class WidgetStateActive:
    def __init__(self,
                 active: bool = False,
                 hovered: bool = False,
                 clicking: bool = False,
                 hover_background_color: WidgetColor = WidgetColor(0, 0, 0, 0, 0),
                 hover_border_color: WidgetColor = WidgetColor(0, 0, 0, 0, 0),
                 click_background_color: WidgetColor = WidgetColor(0, 0, 0, 0, 0),
                 click_border_color: WidgetColor = WidgetColor(0, 0, 0, 0, 0),
                 hover_alpha: float = 0.0,
                 locked: bool = False,
                 *args, **kwargs):
        self.active: bool = active
        self.hovered: bool = hovered
        self.clicking: bool = clicking
        self.hover_background_color: WidgetColor = hover_background_color
        self.hover_border_color: WidgetColor = hover_border_color
        self.click_background_color: WidgetColor = click_background_color
        self.click_border_color: WidgetColor = click_border_color
        self.hover_alpha: float = hover_alpha
        self.locked: bool = locked

    def copy(self, state: WidgetStateActive) -> WidgetStateActive:
        self.active = state.active
        self.hovered = state.hovered
        self.clicking = state.clicking
        self.hover_background_color.copy(state.hover_background_color)
        self.hover_border_color.copy(state.hover_border_color)
        self.click_background_color.copy(state.click_background_color)
        self.click_border_color.copy(state.click_border_color)
        self.hover_alpha = state.hover_alpha
        self.locked = state.locked
        return self
