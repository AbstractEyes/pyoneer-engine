from __future__ import annotations

from typing import Optional

from pygame import Rect

import scripts.core.component as widget_component
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.ui.widget.behavior.mouse import MouseComponentAsync
from scripts.core.ui.widget.shape import ShapeComponent, ShapeType
from scripts.core.ui.widget_color import WidgetColor


class Checkbox(widget_component.GameComponent):
    def __init__(self,
                clickable: bool = True,
                default_checked: bool = False,
                shape: ShapeType = ShapeType.Circle,
                *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.component_type: str = "checkbox"
        self.clickable: bool = clickable
        self.checked: bool = default_checked
        self.shape: ShapeType = shape
        self.checkbox_color: WidgetColor = WidgetColor(148, 152, 158, 255, 1)
        self.checkbox_border_color: WidgetColor = WidgetColor(0, 0, 0, 255, 1)
        self.checkmark_color: WidgetColor = WidgetColor(0, 0, 0, 255, 1)
        self.checkmark_border_color: WidgetColor = WidgetColor(0, 0, 0, 255, 1)
        self.checkmark: ShapeComponent | None = None
        self.background: ShapeComponent | None = None
        self.mouse: MouseComponentAsync | None = None
        self.__make()

    def __make(self):
        self.background = ShapeComponent(
            parent=self,
            bounds=Rect(0, 0, self.world_bounds.width, self.world_bounds.height),
            depth=self.depth + 1,
            background_color=self.checkbox_color,
            border_color=self.checkbox_border_color,
            visible=self.visible,
            shape=self.shape
        )
        self.checkmark = ShapeComponent(
            parent=self,
            bounds=Rect(8, 8, self.world_bounds.width - 16, self.world_bounds.height - 16),
            depth=self.depth + 2,
            background_color=self.checkmark_color,
            border_color=self.checkmark_border_color,
            visible=self.checked and self.visible,
            shape=self.shape
        )
        self.mouse = MouseComponentAsync(parent=self)
        self.bind_component("mouse", self.mouse)
        self.bind_component("checkbox", self.background)
        self.bind_component("checkmark", self.checkmark)

        self.mouse.bind_mouse_listener(GameEventType.MOUSE_CLICK_INSIDE, self.mouse_clicked_inside)

    def mouse_clicked_inside(self, event: Optional[PyoneerEvent] = None):
        if self.clickable and event is not None and event.event.button == 1:
            self.toggle()
            event.handle()

    def is_checked(self) -> bool:
        return self.checked

    def toggle(self):
        self.checked = not self.checked
        self.checkmark.visible = self.checked
        self.checkmark.prepare_background(self)
