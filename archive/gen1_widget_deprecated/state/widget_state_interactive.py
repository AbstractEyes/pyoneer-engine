from __future__ import annotations

from deprecated.state.widget_state import WidgetState
from deprecated.state.widget_state_active import WidgetStateActive
from deprecated.state.widget_state_group import WidgetStateGroup


class WidgetStateInteractive(WidgetState, WidgetStateActive, WidgetStateGroup):
    def __init__(self, *args, **kwargs):
        WidgetState.__init__(self, *args, **kwargs)
        WidgetStateActive.__init__(self, *args, **kwargs)
        WidgetStateGroup.__init__(self, *args, **kwargs)

    def copy(self, state: WidgetStateInteractive) -> WidgetStateInteractive:
        WidgetState.copy(self, state)
        WidgetStateActive.copy(self, state)
        WidgetStateGroup.copy(self, state)
        return self
