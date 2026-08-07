from __future__ import annotations

import pygame
from pygame import surface

from deprecated.state.widget_state_interactive import WidgetStateInteractive
from scripts.core.ui.deprecated.widget_drawable import WidgetDrawable
from scripts.core.ui.deprecated.widget_interactive import WidgetInteractive


# An update container for grouped deprecated
class WidgetDrawableGroup(WidgetInteractive):


    def __init__(self,
                 parent: WidgetDrawableGroup | WidgetDrawable | None = None,
                 children: list[WidgetDrawable | WidgetDrawableGroup] = None,
                 state: WidgetStateInteractive = None,
                 *args,
                 **kwargs):
        if state is not None:
            self.default_state: WidgetStateInteractive = WidgetStateInteractive().copy(state)
            self.state: WidgetStateInteractive = WidgetStateInteractive().copy(state)
        super().__init__(*args, **kwargs)
        self.parent = parent
        self.children: list[WidgetDrawableGroup] = children if children is not None else []

    def core_build(self):
        pass

    def core_dispose(self) -> bool:
        pass

    def core_image(self, surface_in: surface.Surface | None = None) -> surface:
        return super().core_image()

    def core_prepare(self) -> surface:
        pass

    def core_update(self, dt: float):
        super().core_update(dt)
        for widget in self.children:
            widget.core_update(dt)

    def add_child(self, child: WidgetDrawableGroup):
        self.children.append(child)
        child.parent = self
        self.children = sorted(self.children, key=lambda x: x.state.depth)

    def remove_child(self, child: WidgetDrawableGroup):
        self.children.remove(child)
        child.parent = None
        self.children = sorted(self.children, key=lambda x: x.state.depth)

    def _mouse_moved(self, x, y) -> bool:
        return False

    def _is_on_top(self, x, y) -> bool:
        return False

    def prepare_image(self):
        super().prepare_image()
        for child in self.children:
            # todo; draw by index order
            child.prepare_image()
        return self.core_image()

    def core_inputs(self, events: list[pygame.event.Event] | pygame.event.Event):
        pass