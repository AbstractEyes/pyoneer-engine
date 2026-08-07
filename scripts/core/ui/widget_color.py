from __future__ import annotations

from pygame import Color


class WidgetColor(Color):
    def __init__(self, r: int = 0, g: int = 0, b: int = 0, a: int = 0, o: float = 1) -> object:
        super().__init__(r, g, b, a)
        self.o: float = o

    def set_list(self, color: list[int] | None):
        if color is None:
            return self
        self.r = color[0]
        self.g = color[1]
        self.b = color[2]
        self.a = color[3]
        self.o = 1
        return self
    def set(self, color: WidgetColor | None):
        if color is None:
            return self
        self.r = color.r
        self.g = color.g
        self.b = color.b
        self.a = color.a
        self.o = color.o
        return self

    # alias for set
    copy = set

    def set_r(self, red: int) -> WidgetColor:
        self.r = red
        return self

    def set_g(self, green: int) -> WidgetColor:
        self.g = green
        return self

    def set_b(self, blue: int) -> WidgetColor:
        self.b = blue
        return self

    def set_a(self, alpha: int) -> WidgetColor:
        self.a = alpha
        return self

    def scale_alpha(self, a: int | None = None, o: float | None = None) -> WidgetColor:
        self.a = a if a else self.a
        self.o = o if o else self.o
        return self

    def opacity(self, o: int | None = None) -> WidgetColor:
        self.o = o if o else self.o
        return self

    def color(self) -> Color:
        return Color(self.r, self.g, self.b, a=int(self.a * self.o))
