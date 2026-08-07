from scripts.core.ui.deprecated.widget_drawable_group import WidgetDrawableGroup
from scripts.core.ui.widget_color import WidgetColor
from deprecated.state.widget_state_active import WidgetStateActive
from deprecated.state.widget_state_text import WidgetStateText


class LabelState(WidgetStateActive, WidgetStateText):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.background_visible: bool = False
        self.text_shadow: WidgetColor = WidgetColor(0, 0, 0, 0, 0)
        self.text_shadow_visible: bool = False
        self.text_shadow_offset: float = 0.0
        self.text_shadow_depth: float = 0.0


class WidgetLabel(WidgetDrawableGroup):
    def __init__(self, state):
        super().__init__(state)

    def core_update(self, dt):
        pass

    def core_build(self):
        pass

    def core_dispose(self):
        pass

    def prepare_image(self):
        pass
