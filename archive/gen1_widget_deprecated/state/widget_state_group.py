from __future__ import annotations

from pygame import Vector2


class WidgetStateGroup:
    def __init__(self,*args, **kwargs):
        self.anchor: Vector2 = Vector2(0, 0)

    def copy(self, state: WidgetStateGroup) -> WidgetStateGroup:
        self.anchor = state.anchor.copy()
        return self