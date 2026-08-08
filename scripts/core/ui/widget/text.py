from __future__ import annotations

from typing import Optional

import pygame
from pygame import Vector2

from scripts.core.game_object import PyoneerGameObject

from scripts.core.event_types import GameEventType
from scripts.core.component import Config
from scripts.core.ui.widget.draw import DrawComponent
from scripts.core.ui.widget_color import WidgetColor

_FONT_CACHE: dict[tuple[str, int, bool, bool], pygame.font.Font] = {}


def get_font(name: str, size: int, bold: bool = False, italic: bool = False) -> pygame.font.Font:
    """A SysFont, built once per (name, size, style).

    prepare_text used to call pygame.font.SysFont on EVERY text change, which
    walks the system font list and re-parses the face each time. Auto-fitting
    makes that far worse, since fitting probes several sizes per resize.
    """
    key = (name, int(size), bool(bold), bool(italic))
    font = _FONT_CACHE.get(key)
    if font is None:
        font = pygame.font.SysFont(name, int(size), bold=bold, italic=italic)
        _FONT_CACHE[key] = font
    return font


class TextComponent(DrawComponent):
    """A line of text drawn into its own bounds.

    ALIGNMENT AND FITTING WERE BOTH BROKEN
    prepare_text blitted centred text at `text.get_bounding_rect().centerx` --
    half the TEXT's own width, a number with no relationship to the
    destination, so "centred" text sat off to the right by half its length and
    was never centred vertically at all. `view_offset` was read from the theme
    and then never used. And the font size was fixed, so text in a box that had
    been resized smaller simply overflowed it.
    """

    def __init__(self,
                 text: str = "",
                 font: str = "comic",
                 font_size: int = None,
                 text_color: WidgetColor = None,
                 text_shadow_color: WidgetColor = None,
                 text_shadow_visible: bool = False,
                 text_shadow_offset: Vector2 = None,
                 view_offset: Vector2 = None,
                 center: bool = None,
                 center_vertical: bool = True,
                 auto_fit: bool = False,
                 min_font_size: int = None,
                 max_font_size: int = None,
                 padding=None,
                 *args,
                 **kwargs):
        super().__init__(*args, **kwargs)
        theme = Config.config.get("theme")["widget"]
        font_theme = theme["font"]
        self.__text: str = text if text is not None else theme["text"]
        self.font: str = font if font is not None else font_theme["font_type"]
        self.base_font_size: int = font_size if font_size is not None else font_theme["size"]
        """The size asked for. auto_fit may render smaller, never larger."""
        self.font_size: int = self.base_font_size
        """The size actually used by the last render."""
        self.min_font_size: int = min_font_size if min_font_size is not None else font_theme.get("min_size", 8)
        self.max_font_size: int = max_font_size if max_font_size is not None else font_theme.get("max_size", 32)
        self.auto_fit: bool = auto_fit
        """Shrink the font until the text fits, down to min_font_size."""
        self.padding: tuple[int, int] = tuple(padding if padding is not None
                                              else font_theme.get("padding", (0, 0)))
        self.text_color: WidgetColor = text_color if text_color is not None \
            else WidgetColor().set_list(font_theme["color"])
        self.text_shadow_color: WidgetColor = text_shadow_color if text_shadow_color is not None \
            else WidgetColor().set_list(font_theme["shadow_color"])
        self.text_shadow_visible: bool = text_shadow_visible if text_shadow_visible is not None \
            else font_theme["shadow_visible"]
        self.text_shadow_offset: Vector2 = text_shadow_offset if text_shadow_offset is not None \
            else Vector2(font_theme["shadow_offset"])
        self.center: bool = center if center is not None else font_theme["center"]
        self.center_vertical: bool = center_vertical
        self.view_offset: Vector2 = view_offset if view_offset is not None else Vector2(font_theme["offset"])
        self.bind_sync_listener(GameEventType.PREPARE, self.prepare_text)

    @property
    def text(self) -> str:
        return self.__text

    @text.setter
    def text(self, value: str):
        if value == self.__text:
            return
        self.__text = value
        self.prepare_text()

    def _on_size_changed(self, width: int | float, height: int | float):
        """Reallocate the surface, then re-fit and re-place the text in it."""
        super()._on_size_changed(width, height)
        self.prepare_text()

    # ------------------------------------------------------------------ #

    def fitted_font(self) -> tuple[pygame.font.Font, int]:
        """The largest font at or below base_font_size whose text fits, and its size.

        Never larger than asked for -- auto_fit shrinks to fit, it does not
        inflate small text to fill a big box, which would make every label jump
        around as its container resized. Clamped to min_font_size so text stays
        legible rather than vanishing into a 1px box.
        """
        size = max(self.min_font_size, min(self.base_font_size, self.max_font_size))
        if not self.auto_fit or not self.__text:
            return get_font(self.font, size), size

        available_w = max(1, self.local_bounds.width - self.padding[0] * 2)
        available_h = max(1, self.local_bounds.height - self.padding[1] * 2)
        while size > self.min_font_size:
            font = get_font(self.font, size)
            width, height = font.size(self.__text)
            if width <= available_w and height <= available_h:
                return font, size
            size -= 1
        return get_font(self.font, self.min_font_size), self.min_font_size

    def text_position(self, rendered: pygame.Surface) -> tuple[int, int]:
        """Where the rendered text goes inside this component's surface.

        Measured against the DESTINATION, which is what the old code failed to
        do: it used the text's own centerx as an x coordinate.
        """
        area = self.image.get_rect()
        pad_x, pad_y = self.padding
        if self.center:
            x = (area.width - rendered.get_width()) // 2
        else:
            x = pad_x
        if self.center_vertical:
            y = (area.height - rendered.get_height()) // 2
        else:
            y = pad_y
        return (int(x + self.view_offset.x), int(y + self.view_offset.y))

    def prepare_text(self, sender: Optional[PyoneerGameObject] = None):
        surface = self.image
        if surface is None:
            return
        surface.fill((0, 0, 0, 0))
        if not self.text or self.text_color.a <= 0:
            return

        font, self.font_size = self.fitted_font()
        rendered = font.render(self.text, True, self.text_color)
        position = self.text_position(rendered)

        if self.text_shadow_visible:
            shadow = font.render(self.text, True, self.text_shadow_color)
            surface.blit(shadow, (position[0] + int(self.text_shadow_offset.x),
                                  position[1] + int(self.text_shadow_offset.y)))
        surface.blit(rendered, position)
