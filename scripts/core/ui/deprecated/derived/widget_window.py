from __future__ import annotations

from scripts.core.ui.state import WidgetStateWindowInteractive
from scripts.core.ui.deprecated.widget_drawable import WidgetDrawable
from scripts.core.ui.deprecated.widget_drawable_group import WidgetDrawableGroup
from scripts.core.ui.deprecated.widget_interactive import WidgetInteractive


class WidgetDrawableWindow(WidgetInteractive, WidgetDrawableGroup):
    def __init__(self, state: WidgetStateWindowInteractive = None, *args, **kwargs):
        super().__init__(state)
        self.widgets = []

    def add_widget(self, widget: WidgetDrawable):
        self.widgets.append(widget)

    def remove_widget(self, widget: WidgetDrawable):
        self.widgets.remove(widget)

    def show(self):
        self.__state.visible = True
        for widget in self.widgets:
            widget.show_event()

    def hide(self):
        self.__state.visible = False
        for widget in self.widgets:
            widget.hide_event()

    def core_update(self, *args, **kwargs):
        super().core_update(*args, **kwargs)
        for widget in self.widgets:
            widget.update_event()

    def activate(self, *args, **kwargs):
        self.__state.active = True
        for widget in self.widgets:
            widget.activate_event(*args, **kwargs)

    def deactivate(self, *args, **kwargs):
        self.__state.active = False
        for widget in self.widgets:
            widget.deactivate_event(*args, **kwargs)

