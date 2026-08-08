"""The test window: one live example of every control, added as it is built.

Separate from GameWindow on purpose. GameWindow is reusable chrome -- frame,
title bar, close button, drag, resize -- and it used to construct this entire
demo tree inline, which meant 113 components for an "empty" window and made it
unusable by anyone who wanted a different one. Bare GameWindow is now 10
components; everything below is demo content.

ADDING A CONTROL
Build it in a `__build_*` method, register it in build_content(), and give it
an anchor so it survives a window resize. Keep each section self-contained so
one broken control does not take the rest of the window with it.
"""
from __future__ import annotations

from pygame import Rect

from scripts.core.ui.anchor import Anchor
from scripts.core.ui.widget.behavior.grid import GridComponent
from scripts.core.ui.widget.containers.checkbox import Checkbox
from scripts.core.ui.widget.containers.panel import Panel
from scripts.core.ui.widget.containers.text_box import TextBox
from scripts.core.ui.widget.containers.window import GameWindow
from scripts.core.ui.widget.shape import ShapeComponent
from scripts.core.ui.widget.text import TextComponent
from scripts.core.ui.widget_color import WidgetColor

TILE_COLOURS = [
    (196, 84, 74), (206, 142, 70), (188, 186, 84), (104, 168, 96),
    (78, 150, 168), (96, 112, 184), (146, 100, 176), (176, 96, 138),
]


class DemoWindow(GameWindow):
    """Every control the engine has, in one resizable window."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("header_text", "Pyoneer - test window")
        super().__init__(*args, **kwargs)
        self.checkbox: Checkbox | None = None
        self.scroll_panel: Panel | None = None
        self.grid_panel: Panel | None = None
        self.text_box: TextBox | None = None
        self.checkboxes: list[Checkbox] = []
        self.grid: GridComponent | None = None
        self.grid_label: TextComponent | None = None

    # ------------------------------------------------------------------ #

    def build_content(self):
        """Called by GameWindow once the chrome exists."""
        top = self.header_height + 4
        self.__build_toggle(top)
        row = top + 44
        half = max(60, (self.local_bounds.height - row - 8) // 2)
        self.__build_scroll_panel(Rect(4, row, self.local_bounds.width - 24, half))
        self.__build_grid_panel(Rect(4, row + half + 4,
                                     self.local_bounds.width - 24, half - 4))

    # ------------------------------------------------------------------ #
    # controls
    # ------------------------------------------------------------------ #

    def __build_toggle(self, top: int):
        """A single checkbox, directly on the window."""
        self.checkbox = Checkbox(parent=self, depth=1, bounds=Rect(4, top, 40, 40))
        self.checkbox.anchor = Anchor.TOP_LEFT
        self.bind_component("checkbox", self.checkbox)

    def __build_scroll_panel(self, bounds: Rect):
        """A scrolling panel holding a text box and a column of checkboxes.

        Its working area is deliberately much taller than the panel so the
        vertical scrollbar has something to do.
        """
        self.scroll_panel = Panel(parent=self, depth=1, bounds=bounds,
                                  working_area=Rect(0, 0, bounds.width, 420))
        self.scroll_panel.anchor = Anchor.TOP | Anchor.STRETCH_X
        self.bind_component("scroll_panel", self.scroll_panel)

        self.text_box = TextBox(
            parent=self.scroll_panel, depth=0,
            bounds=Rect(4, 4, max(40, bounds.width - 30), 32),
            default_text="Type here (movement is suppressed while focused)",
            max_length=80,
        )
        self.scroll_panel.attach_component("text_box", self.text_box)

        self.checkboxes = []
        for index in range(4):
            box = Checkbox(parent=self.scroll_panel, depth=0,
                           bounds=Rect(4, 44 + index * 44, 40, 40))
            self.checkboxes.append(box)
            self.scroll_panel.attach_component(f"checkbox_{index}", box)
        self.scroll_panel.fit_scroll_area()

    def __build_grid_panel(self, bounds: Rect):
        """A GridComponent of snappable tiles inside a scrolling panel.

        The grid is UNIFORM (cell_size set), which is the mode that makes
        pixel<->cell conversion stable -- so grid.world_cell_at(mouse_pos)
        resolves correctly even after the panel has been scrolled.
        """
        self.grid_panel = Panel(parent=self, depth=1, bounds=bounds,
                                working_area=Rect(0, 0, bounds.width, bounds.height))
        self.grid_panel.anchor = Anchor.STRETCH_X | Anchor.BOTTOM
        self.bind_component("grid_panel", self.grid_panel)

        self.grid = GridComponent(
            parent=self.grid_panel,
            bounds=Rect(0, 0, 0, 0),
            max_columns=4,
            cell_size=28,
            spacing=(3, 3),
            padding=(4, 4),
        )
        for index, colour in enumerate(TILE_COLOURS):
            self.grid.add_item(ShapeComponent(
                bounds=Rect(0, 0, 28, 28),
                shape=ShapeComponent.ShapeType.Rectangle,
                background_color=WidgetColor(*colour, 255, 1),
            ), name=f"tile_{index}")
        self.grid_panel.attach_component("grid", self.grid)
        self.grid_panel.fit_scroll_area()

    # ------------------------------------------------------------------ #

    def cell_under(self, screen_point) -> tuple[int, int] | None:
        """Which grid cell a screen position falls in, or None.

        The call a drag-and-drop handler makes. Goes through world_cell_at, so
        it already accounts for the panel's scroll offset.
        """
        if self.grid is None:
            return None
        cell = self.grid.world_cell_at(screen_point)
        return None if cell is None else (int(cell.x), int(cell.y))
