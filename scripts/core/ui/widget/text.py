from __future__ import annotations
from typing import Optional

import pygame
from pygame import Vector2

from scripts.core.game_object import PyoneerGameObject

from scripts.core.event_types import GameEventType
from scripts.core.component import Config
from scripts.core.ui.widget.draw import DrawComponent
from scripts.core.ui.widget_color import WidgetColor


class TextComponent(DrawComponent):

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
                 *args,
                 **kwargs):
        super().__init__(*args, **kwargs)
        theme = Config.config.get("theme")["widget"]
        self.__text: str = text if text is not None else theme["text"]
        self.font: str = font if font is not None else theme["font"]["font_type"]
        self.font_size: int = font_size if font_size is not None else theme["font"]["size"]
        self.text_color: WidgetColor = text_color if text_color is not None \
            else WidgetColor().set_list(theme["font"]["color"])
        self.text_shadow_color: WidgetColor = text_shadow_color if text_shadow_color is not None \
            else WidgetColor().set_list(theme["font"]["shadow_color"])
        self.text_shadow_visible: bool = text_shadow_visible if text_shadow_visible is not None \
            else theme["font"]["shadow_visible"]
        self.text_shadow_offset: Vector2 = text_shadow_offset if text_shadow_offset is not None \
            else Vector2(theme["font"]["shadow_offset"])
        self.center: bool = center if center is not None else theme["font"]["center"]
        self.view_offset: Vector2 = view_offset if view_offset is not None else Vector2(theme["font"]["offset"])
        self.bind_sync_listener(GameEventType.PREPARE, self.prepare_text)
        #self.bind_sync_listener(GameEventType.BLITS, self.__blits)
        #self.bind_sync_listener(GameEventType.BLITS, self.blits_text)

    @property
    def text(self) -> str:
        return self.__text

    @text.setter
    def text(self, value: str):
        self.__text = value
        self.prepare_text()

    def prepare_text(self, sender: Optional[PyoneerGameObject] = None):
        self.image.fill((0, 0, 0, 0))
        if len(self.text) > 0 and self.text_color.a > 0:
            font = pygame.font.SysFont(self.font, self.font_size)
            if self.text_shadow_visible:
                # draw the shadow first
                text = font.render(self.text, True, self.text_shadow_color)
                self.image.blit(text, (self.text_shadow_offset.x, self.text_shadow_offset.y))
            text = font.render(self.text, True, self.text_color)
            text_rect = text.get_bounding_rect()
            if self.center:
                self.image.blit(text, (text_rect.centerx, 0))
            else:
                self.image.blit(text, (0, 0))

    #def __blits(self, event: Optional[PyoneerEvent] = None):
    #    depth = self.depth
    #    if event is not None and event.data.get("layer_depth") is not None:
    #        depth += event.data["layer_depth"]
    #    BlitPool.blit_to_layer(self.depth, self.priority, self.image(), (self.bounds.x, self.bounds.y))

    #def blits_text(self, _) -> list[tuple[Surface, Vector2]]:
    #    return [(self.image(), Vector2(self.bounds.x, self.bounds.y))]

