from __future__ import annotations
from typing import Optional

import pygame
from pygame import Rect

from scripts.core.game_object import PyoneerGameObject
from event_types import GameEventType
from component import Config
from scripts.core.ui.widget.draw import DrawComponent
from scripts.core.ui.widget_color import WidgetColor


class ShapeType:
    Rectangle = 0
    Circle = 1
    Triangle = 2


class ShapeComponent(DrawComponent):
    ShapeType = ShapeType


    def __init__(self,
                 background_color: WidgetColor | None = None,
                 visible: bool = None,
                 border_color: WidgetColor | None = None,
                 background_visible: bool = None,
                 border_visible: bool = None,
                 border_thickness: Rect = None,
                 shape: ShapeType = ShapeType.Rectangle,
                 *args,
                 **kwargs):
        super().__init__(*args, **kwargs)
        config = Config.config.get("theme")["widget"]
        self.background_color: WidgetColor = background_color if background_color is not None else WidgetColor().set_list(config["background"]["color"])
        self.border_color: WidgetColor = border_color if border_color is not None else WidgetColor().set_list(config["background"]["border_color"])
        self.visible: bool = visible if visible is not None else config["background"]["visible"]
        self.background_visible: bool = background_visible if background_visible is not None else config["background"]["background_visible"]
        self.border_visible: bool = border_visible if border_visible is not None else config["background"]["border_visible"]
        self.border_thickness: Rect = border_thickness if border_thickness is not None else Rect(config["background"]["border_thickness"])
        self.shape: ShapeType = shape
        self.bind_sync_listener(GameEventType.PREPARE, self.prepare_background)
        #self.bind_sync_listener(GameEventType.BLITS, self.blits_background)

    def prepare_background(self, sender: Optional[PyoneerGameObject]):
        self.core_image().fill((0, 0, 0, 0))
        if self.visible:
            #self._image.fill(self.border_color)
            if self.shape == ShapeType.Rectangle:
                if self.background_color.a > 0:
                    if self.border_visible:
                        pygame.draw.rect(self.core_image(), self.border_color.color(), (0, 0, self.world_bounds.width, self.world_bounds.height))
                    if self.background_visible:
                        pygame.draw.rect(self.core_image(), self.background_color.color(), (self.border_thickness.x, self.border_thickness.y,
                                                                                            self.world_bounds.width - self.border_thickness.w - self.border_thickness.x,
                                                                                            self.world_bounds.height - self.border_thickness.h - self.border_thickness.y))
                    self.core_image().convert_alpha()
            elif self.shape == ShapeType.Circle:
                if self.background_color.a > 0:
                    if self.border_visible:
                        pygame.draw.circle(self.core_image(), self.border_color.color(), (self.world_bounds.width // 2, self.world_bounds.height // 2), self.world_bounds.width // 2)
                    if self.background_visible:
                        pygame.draw.circle(self.core_image(),
                                           self.background_color.color(),
                                           (self.world_bounds.width / 2, self.world_bounds.height / 2),
                                           self.world_bounds.width / 2 - self.border_thickness.x)
                    self.core_image().convert_alpha()
            elif self.shape == ShapeType.Triangle:
                if self.background_color.a > 0:
                    if self.border_visible:
                        pygame.draw.polygon(self.core_image(), self.border_color.color(), [(self.world_bounds.width // 2, 0), (0, self.world_bounds.height), (self.world_bounds.width, self.world_bounds.height)])
                    if self.background_visible:
                        pygame.draw.polygon(self.core_image(), self.background_color.color(), [(self.world_bounds.width // 2, 0), (0, self.world_bounds.height), (self.world_bounds.width, self.world_bounds.height)])
                    self.core_image().convert_alpha()

    #def blits_background(self, event: Optional[PyoneerEvent]) -> list[tuple[Surface, Vector2]]:
    #    return [(self.image(), Vector2(self.bounds.x, self.bounds.y))] if self.visible else []

