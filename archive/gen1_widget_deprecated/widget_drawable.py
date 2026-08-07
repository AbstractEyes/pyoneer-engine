from __future__ import annotations

import pygame
from pygame import surface, rect

from event_types import GameEventType
from deprecated.state.widget_state import WidgetState
from scripts.core.ui.deprecated.widget import Widget
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from scripts.core.ui.deprecated.widget_events import WidgetEvent


class WidgetDrawable(Widget):

    def __init__(self, state: WidgetState = None, *args, **kwargs):
        super().__init__()
        if state is not None:
            self.default_state = WidgetState().copy(state)
            self.state: WidgetState = WidgetState().copy(state)
            self._image = surface.Surface((state.bounds.width, state.bounds.height), pygame.BLEND_RGBA_MIN)
        if self.state is not None:
            self._image = surface.Surface((self.state.bounds.width, self.state.bounds.height), pygame.BLEND_RGBA_MIN)
        # fires when this widget is shown
        self.show_event: WidgetEvent = WidgetEvent(GameEventType.SHOW, self.get_method('show'))
        # fires when this widget is hidden
        self.hide_event: WidgetEvent = WidgetEvent(GameEventType.HIDE, self.get_method('hide'))
        # fires when this widget is updated
        self.update_event: WidgetEvent = WidgetEvent(GameEventType.UPDATE, self.get_method('update'))
        # fires when this widget is activated
        self.activate_event: WidgetEvent = WidgetEvent(GameEventType.ACTIVATE, self.get_method('activate'))
        # fires when this widget is deactivated
        self.deactivate_event: WidgetEvent = WidgetEvent(GameEventType.DEACTIVATE, self.get_method('deactivate'))
        # fires when this widget is moved
        self.move_event: WidgetEvent = WidgetEvent(GameEventType.TRANSFORM_COMPONENT, self.get_method('move'))

    def core_prepare(self) -> surface:
        return self._image

    def core_dispose(self) -> bool:
        pass

    def core_image(self, new_surface: surface.Surface | None = None) -> surface.Surface:
        return self._image

    def core_build(self):
        pass

    def core_update(self, dt: float):
        if self.state.needs_prepare:
            self.refresh()

    def show(self):
        self.state.visible = True

    def hide(self):
        self.state.visible = False

    def move(self, x: int, y: int):
        if self.state.bounds.x != x or self.state.bounds.y != y:
            self.state.needs_prepare = True
        self.state.bounds.move_ip(x, y)

    def refresh(self):
        # prepare the surface again, only call when needed
        self.prepare_image()
        self.state.needs_prepare = False

    def has_method(self, name) -> bool:
        return callable(getattr(self, name, None))

    def get_method(self, name, default=None):
        return getattr(self, name, default)

    def prepare_background(self):
        # this determines the alpha of the overall surface
        self.core_image().set_alpha(int(self.state.alpha * 255), pygame.SRCALPHA)
        # -----------------------------------------------------
        pygame.draw.rect(self.core_image(),
                         self.state.border_color,
                         rect.Rect(0, 0, self.state.bounds.width, self.state.bounds.height))
        self.core_image().convert_alpha()
        # if the background alpha is not 0
        if self.state.background_color.a > 0:
            pygame.draw.rect(self.core_image(),
                             self.state.background_color,
                             rect.Rect(self.state.border_width,
                                       self.state.border_width,
                                       self.state.bounds.width - self.state.border_width * 2,
                                       self.state.bounds.height - self.state.border_width * 2))

    # slow method, only call when needed, not every frame
    def prepare_image(self) -> pygame.surface.Surface:
        if self.state.needs_prepare:
            self.state.needs_prepare = False
            self.core_image().fill((0, 0, 0, 0))
            if self.state.visible:
                self.prepare_background()
        return self.core_image().convert_alpha()

# if the text is not empty
# TODO: enable this for text drawing in the label widget
# if len(self.__params.text) > 0:  # draw the text
#    font_color: None | Color = self.__params.font_color() if self.__params.font_color().a > 0 else None
#    font_background_color: None | Color = self.__params.font_background_color() if self.__params.font_background_color().a > 0 else None
#    text = pygame.font.SysFont(self.__params.font, self.__params.font_size).render(
#        self.__params.text, True, font_color, font_background_color)
#    self.surface.blit(text, (self.__params.font_offset[0], self.__params.font_offset[1]))

