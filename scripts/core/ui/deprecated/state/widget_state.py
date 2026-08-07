from __future__ import annotations

import uuid

from pygame import rect

from scripts.core.ui.widget_color import WidgetColor
from scripts.core.utils import RectUtils


# the simplest widget state
class WidgetState:
    def __init__(self,
                 widget_id: uuid | str = uuid.uuid4(),
                 visible: bool = False,
                 bounds: rect.Rect = rect.Rect(0, 0, 0, 0),
                 background: WidgetColor = WidgetColor(255, 0, 0, 255, o=1),
                 border_color: WidgetColor = WidgetColor(r=0, g=0, b=0, a=0, o=0),
                 border_width: int = 2,
                 alpha: float = 1,
                 depth: int = 0,
                 *args, **kwargs):
        self.widget_id:         uuid = widget_id
        self.visible:           bool = visible
        self.bounds:            rect.Rect = bounds
        self.background_color:  WidgetColor = background
        self.border_color:      WidgetColor = border_color
        self.alpha:             float = alpha
        self.border_width:      int = border_width
        self.needs_prepare:     bool = True
        self.depth:             int = depth
        self.ready:             bool = False

    def bounds_difference(self, parent: WidgetState) -> rect.Rect:
        return RectUtils.bounds_difference(self.bounds, parent.bounds)

    def offset(self, parent: WidgetState | None = None) -> rect.Rect:
        return RectUtils.offset(self.bounds, parent.bounds)

    def copy(self, state: WidgetState) -> WidgetState:
        self.visible = state.visible
        self.bounds = state.bounds
        self.background_color = state.background_color
        self.border_color = state.border_color
        self.alpha = state.alpha
        self.border_width = state.border_width
        self.needs_prepare = state.needs_prepare
        self.depth = state.depth
        return self
