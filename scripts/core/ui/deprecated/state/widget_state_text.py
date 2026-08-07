from __future__ import annotations

from pygame import rect

from scripts.core.ui.widget_color import WidgetColor


class WidgetStateText:
    def __init__(self,
                 text: str = "",
                 font: str = "Arial",
                 text_size: int = 14,
                 text_padding: int = 0,
                 text_color: WidgetColor = WidgetColor(255, 255, 255, 255, 1),
                 text_offset: rect.Rect = rect.Rect(0, 0, 0, 0),
                 *args, **kwargs):
        self.text = text
        self.font = font
        self.text_size = text_size
        self.text_padding = text_padding
        self.text_color = text_color
        self.text_offset = text_offset
