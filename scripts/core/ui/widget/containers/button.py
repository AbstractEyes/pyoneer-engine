from pygame import Rect

from scripts.core.component import Config, GameComponent
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.ui.widget.behavior.mouse import MouseComponentAsync
from scripts.core.ui.widget.shape import ShapeComponent
from scripts.core.ui.widget.text import TextComponent
from scripts.core.ui.widget_color import WidgetColor


class Button(GameComponent):
    def __init__(self,
                 center_text: bool = True,
                 text: str = "",
                 text_color: WidgetColor = None,
                 text_shadow_color: WidgetColor = None,
                 background_color: WidgetColor = None,
                 border_color: WidgetColor = None,
                 border_thickness: Rect = None,
                 font_size: int = None,
                 font_color: WidgetColor = None,
                 consume_click: bool = False,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        theme = Config.config.get("theme")["widget"]
        self.__text: str = text
        self.__color: WidgetColor = background_color if background_color is not None else WidgetColor().set_list(theme["button"]["background_color"])
        self.__border_color: WidgetColor = border_color if border_color is not None else WidgetColor().set_list(theme["button"]["border_color"])
        self.__border_thickness: Rect = border_thickness if border_thickness is not None else Rect(theme["button"]["border_thickness"])
        self.__text_color: WidgetColor = text_color if text_color is not None else WidgetColor().set_list(theme["button"]["text_color"])
        self.__text_shadow_color: WidgetColor = text_shadow_color if text_shadow_color is not None else WidgetColor().set_list(theme["button"]["text_shadow_color"])
        self.__font_size: int = font_size if font_size is not None else theme["button"]["font_size"]
        self.__font_color: WidgetColor = font_color if font_color is not None else WidgetColor().set_list(theme["button"]["text_color"])
        self.__center_text: bool = center_text if center_text is not None else theme["button"]["center_text"]
        self.__consume_click: bool = consume_click

        self.body: ShapeComponent | None = None
        self.text: TextComponent | None = None
        self.mouse: MouseComponentAsync | None = None
        self.__make()

    def __make(self):
        theme = Config.config.get("theme")["widget"]
        self.body = ShapeComponent(parent=self,
                                   depth=1,
                                   bounds=Rect(0, 0, self.world_bounds.width, self.world_bounds.height),
                                   background_color=self.__color,
                                   border_color=self.__border_color)
        self.text = TextComponent(parent=self,
                                  depth=2,
                                  bounds=Rect(self.__border_thickness.x + 2,
                                              self.__border_thickness.y + 2,
                                              self.world_bounds.width - self.__border_thickness.w - self.__border_thickness.x,
                                              self.world_bounds.height - self.__border_thickness.h - self.__border_thickness.y),
                                  text=self.__text,
                                  font_size=self.__font_size,
                                  text_color=WidgetColor(255, 255, 255, 255, 1).set(self.__text_color),
                                  text_shadow_color=WidgetColor(120, 120, 120, 255, 1).set(self.__text_shadow_color),
                                  center=self.__center_text)
        self.mouse = MouseComponentAsync(parent=self)
        self.bind_component("mouse", self.mouse)
        self.bind_component("background", self.body)
        self.bind_component("text", self.text)
        self.bind_sync_listener(GameEventType.MOUSE_DOWN_INSIDE, self.__consume_mouse_click)

    def __consume_mouse_click(self, event: PyoneerEvent | None = None):
        if self.__consume_click and self.mouse.mouse_inside and self.mouse.mouse_down:
            event.handle()