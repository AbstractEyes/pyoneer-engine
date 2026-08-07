from deprecated.state.widget_state_interactive import WidgetStateInteractive


class WidgetStateWindowInteractive(WidgetStateInteractive):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.draggable: bool = False
        self.dragging: bool = False
        self.drag_offset: tuple[int, int] = (0, 0)
        self.drag_area: tuple[int, int, int, int] = (0, 0, 0, 0)