from __future__ import annotations
from typing import Optional

import pygame
from pygame import Rect, Vector2

from scripts.core.ui.widget.image import ImageComponent
from scripts.core.event_manager import PyoneerEvent
from scripts.core.game_object import PyoneerGameObject
from scripts.core.component import GameComponent
from scripts.core.event_types import GameEventType
from scripts.core.ui.widget.containers.button import Button
from scripts.core.ui.widget.containers.checkbox import Checkbox
from scripts.core.ui.widget.containers.listbox import ListBoxComponent
from scripts.core.ui.widget.containers.panel import Panel
from scripts.core.ui.widget.containers.text_box import TextBox
from scripts.core.ui.widget.behavior.keyboard import KeyboardComponentAsync, KeyBindingType
from scripts.core.ui.widget.behavior.mouse import MouseComponentAsync
from scripts.core.ui.widget.shape import ShapeComponent
from scripts.core.ui.widget.text import TextComponent
from scripts.core.ui.widget_color import WidgetColor

from config.managers.core_asset_manager import CoreAssetManager

Config = CoreAssetManager()


class GameWindow(GameComponent):
    def __init__(self,
                 header_text: str = "Hello World",
                 header_visible: bool = True,
                 clickable: bool = True,
                 movable: bool = True,
                 resizable: bool = True,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = Config.config.get("theme")["widget"]
        self.active: bool = False
        """Whether the window is active or not."""
        # -------------------------------------------------
        # core components
        self.active_component: GameComponent | None = None
        """The active component within the window if any."""
        self.is_view: bool = True
        """Whether the component is considered a viewport or not."""
        self.header_bar: ShapeComponent | None = None
        """The title bar of the window."""
        self.body: ShapeComponent | None = None
        self.header_text: TextComponent | None = None
        self.close_button: Button | None = None
        # -------------------------------------------------
        # test components
        self.panel: Panel | None = None
        self.panel2: Panel | None = None
        self.list_box: ListBoxComponent | None = None
        self.checkbox: Checkbox | None = None
        self.checkboxes: list[Checkbox] = []
        self.text_box: TextBox | None = None
        self.image_test: ImageComponent | None = None
        # -------------------------------------------------
        self.mouse: MouseComponentAsync | None = None
        self.keyboard: KeyboardComponentAsync | None = None
        # -------------------------------------------------
        # behavioral properties
        self.text: str = header_text
        self.clickable: bool = clickable
        self.movable: bool = movable
        self.resizable: bool = resizable
        self.header_visible: bool = header_visible
        # -------------------------------------------------
        # test behavioral flags
        self.dragging_component: bool = False
        # whether or not this component is currently dragging.
        self.dragging_offset: Vector2 = Vector2(0, 0)
        # the position from the dragging position to the top left corner of the window.
        # -------------------------------------------------
        # baseline property configuration
        self.header_border_thickness: Rect = Rect(config["window"]["title"]["border_thickness"])
        self.header_height: int = config["window"]["title"]["height"]

    # -------------------------------------------------
    # utility functionality
    # -------------------------------------------------
    def core_prepare(self, event: PyoneerEvent | None = None):
        super().core_prepare(event)
        if not self.flags.get("prepared_window", False):
            config = Config.config.get("theme")["widget"]
            self.body = ShapeComponent(
                parent=self,
                depth=0,
                bounds=Rect(0, 0, self.world_bounds.width, self.world_bounds.height),
                background_color=WidgetColor().set_list(config["window"]["body"]["color"]),
                border_color=WidgetColor().set_list(config["window"]["body"]["border_color"]),
                border_thickness=Rect(config["window"]["body"]["border_thickness"])
            )
            self.header_bar = ShapeComponent(
                parent=self,
                depth=1,
                bounds=Rect(0, 0, self.world_bounds.width, self.header_height),
                background_color=WidgetColor(60, 63, 65, 255, 1).set_list(config["window"]["title"]["color"]),
                border_color=WidgetColor(100, 103, 105, 255, 1).set_list(config["window"]["title"]["border_color"]),
                border_thickness=Rect(config["window"]["title"]["border_thickness"])
            )
            self.header_text = TextComponent(
                parent=self,
                depth=2,
                bounds=Rect(4, 4, self.world_bounds.width, self.header_height),
                text=self.text,
                font_size=config["window"]["title"]["font_size"],
                text_color=WidgetColor(220, 223, 225, 255, 1).set_list(config["window"]["title"]["text_color"]),
                text_shadow_color=WidgetColor(120, 120, 120, 255, 1).set_list(config["window"]["title"]["text_shadow_color"]),
                text_shadow_visible=True
            )
            self.close_button = Button(
                parent=self,
                depth=2,
                bounds=Rect(self.local_bounds.width - 30, 0, 30, self.header_height),
                text="X",
                background_color=WidgetColor(255, 0, 0, 255, 1).set_list(config["window"]["close_button"]["color"]),
                border_color=WidgetColor(255, 255, 255, 255, 1).set_list(config["window"]["close_button"]["border_color"]),
                border_thickness=Rect(config["window"]["close_button"]["border_thickness"]),
                font_size=config["window"]["close_button"]["font_size"],
                center_text=True
            )
            # -------------------------------------------------
            self.checkbox = Checkbox(
                parent=self,
                depth=1,
                bounds=Rect(4, self.header_height + 4, 40, 40)
            )

            self.panel = Panel(
                parent=self,
                depth=1,
                bounds=Rect(4,
                            self.header_height + self.checkbox.local_bounds.h + 8,
                            self.local_bounds.width - 60,
                            (self.local_bounds.height - self.header_height - self.checkbox.local_bounds.h - 12) / 2),
                working_area=Rect(0, 0, 1000, 1000)
            )
            self.panel2 = Panel(
                parent=self,
                depth=1,
                bounds=Rect(4,
                            self.header_height + self.checkbox.local_bounds.h + 8 + self.panel.local_bounds.h + 4,
                            self.local_bounds.width - 60,
                            (self.local_bounds.height - self.header_height - self.checkbox.local_bounds.h - 12) / 2),
                working_area=Rect(0, 0, 200, 500)
            )
            self.text_box = TextBox(
                parent=self.panel,
                depth=0,
                bounds=Rect(4, 500, self.panel.local_bounds.width - 8, 40),
                default_text="Type here...",
                max_length=80
            )
            self.checkboxes: list[Checkbox] = [
                Checkbox(parent=self.panel, depth=0, bounds=Rect(4, self.header_height + 4 + 40 + 4, 40, 40)),
                Checkbox(parent=self.panel, depth=0, bounds=Rect(4, self.header_height + 4 + 40 + 4 + 40 + 4, 40, 40)),
                Checkbox(parent=self.panel, depth=0, bounds=Rect(4, self.header_height + 4 + 40 + 4 + 40 + 4 + 40 + 4, 40, 40)),
                Checkbox(parent=self.panel, depth=0, bounds=Rect(4, self.header_height + 4 + 40 + 4 + 40 + 4 + 40 + 4 + 40 + 4, 40, 40)),
            ]

            #self.image_test: ImageComponent = ImageComponent(
            #    parent=self,
            #    depth=500,
            #    bounds=Rect(4, self.header_height + self.text_box.local_bounds.h + 8, 128, 128),
            #    image_in="data/graphics/tilesets/Characters/~Garet.png",
            #    piece=Rect(0, 0, 128, 128),
            #    rotation=90
            #)
            #self.list_box = ListBoxComponent(
            #    parent=self,
            #    depth=4,
            #    bounds=Rect(4, self.header_height + self.text_box.bounds.h + self.checkbox.bounds.h + 8, self.bounds.width / 3, self.bounds.height - self.header_height - self.text_box.bounds.h - self.checkbox.bounds.h - 12),
            #)
            # -------------------------------------------------
            self.mouse = MouseComponentAsync(parent=self)
            self.mouse.bind_mouse_listener(GameEventType.MOUSE_CLICK_INSIDE, self.__event__mouse_clicked_inside)
            self.keyboard = KeyboardComponentAsync(parent=self)
            self.bind_component("body", self.body)
            self.bind_component("title", self.header_bar)
            self.bind_component("title_text", self.header_text)
            self.bind_component("close_button", self.close_button)
            self.bind_component("mouse", self.mouse)
            self.bind_component("keyboard", self.keyboard)
            # mouse components
            self.mouse.bind_mouse_listener(GameEventType.MOUSE_DOWN_INSIDE, self.__event_mouse_down_within_header)
            self.mouse.bind_mouse_listener(GameEventType.MOUSE_UP, self.__event_mouse_up_dropping_window)
            self.mouse.bind_mouse_listener(GameEventType.MOUSE_DRAGGING, self.__event_mouse_dragging_window)
            # test components --------------------------------
            self.bind_component("checkbox", self.checkbox)
            self.bind_component("panel", self.panel)
            self.bind_component("panel2", self.panel2)
            self.panel.attach_component("text_box", self.text_box)
            self.panel.attach_component("checkbox1", self.checkboxes[0])
            self.panel.attach_component("checkbox2", self.checkboxes[1])
            self.panel.attach_component("checkbox3", self.checkboxes[2])
            self.panel.attach_component("checkbox4", self.checkboxes[3])
            #self.bind_component("image_test", self.image_test)
            self.keyboard.bind_keys([pygame.K_LEFT, pygame.K_RIGHT])
            #self.keyboard.bind_key_event(KeyBindingType.KeyDown, self.__event__key_down)
            # -------------------------
            self.flags["prepared_window"] = True

    def __event_mouse_down_within_header(self, event: PyoneerEvent):
        # when the mouse is clicked within the header
        if (self.header_visible and self.clickable and self.movable
                and not self.dragging_component and event.event.button == pygame.BUTTON_LEFT):
            if self.header_bar.world_bounds.collidepoint(event.event.pos):
                if self.close_button.world_bounds.collidepoint(event.event.pos):
                    print("close button collided wih click")
                    return
                print("header collided without any issues, no close button clicked")
                # header is clicked, lets see if we're dragging.
                self.dragging_component = True
                # capture the relative position of the mouse from the world bounds position of the full window.
                self.dragging_offset = Vector2(event.event.pos) - self.world_bounds.topleft
                pass
            else:
                self.dragging_component = False  # potential fail state check for early debugging
                self.dragging_offset = None

    def top_widget_at_position(self, pos: Vector2,
                               exceptions: list[GameComponent] = []) -> Optional[PyoneerGameObject]:
        top_widget = None
        for widget in self.get_clickable_components_at(pos):
            if widget not in exceptions:
                # within widget, lets see if there's a component within this widget we can click.
                top_widget = widget if top_widget is None or top_widget.depth <= widget.depth else top_widget
        if top_widget is None:
            # check for header
            if self.header_bar.world_bounds.collidepoint(pos):
                top_widget = self.header_bar
        return top_widget

    def __event_mouse_up_dropping_window(self, event: PyoneerEvent):
        if self.movable and self.dragging_component:
            self.dragging_component = False
            self.dragging_offset = None

    def __event_mouse_dragging_window(self, event: PyoneerEvent):
        if self.dragging_component:
            val = Vector2(event.event.pos) - self.dragging_offset
            self.move(val.x, val.y)

    # -------------------------------------------------
    # use test functionality
    # -------------------------------------------------

    def __move_left(self, event_: PyoneerEvent):
        self.move(self.world_bounds.x - 10, self.world_bounds.y)

    def __move_right(self, event_: PyoneerEvent):
        self.move(self.world_bounds.x + 10, self.world_bounds.y)

    def __move_up(self, event_: PyoneerEvent):
        self.move(self.world_bounds.x, self.world_bounds.y - 10)

    def __move_down(self, event_: PyoneerEvent):
        self.move(self.world_bounds.x, self.world_bounds.y + 10)

    def __mouse_entered(self, data: PyoneerEvent):
        if self.clickable:
            self.body.background_color = WidgetColor(40, 41, 44, 255, 1)
            self.header_bar.background_color = WidgetColor(70, 73, 75, 255, 1)

    def __event__mouse_clicked_inside(self, event_: PyoneerEvent):
        consume = False
        if self.clickable and event_.event.button == pygame.BUTTON_LEFT:
            self.active = True
            widget = self.top_widget_at_position(Vector2(event_.event.pos), [self, self.mouse, self.keyboard])
            pass
            if isinstance(widget, GameComponent) and widget.is_clickable():
                if widget is self.close_button:
                    print("Close button clicked.")
                    consume = True
                elif widget is self.text_box:
                    self.text_box.active = True
                    consume = True
                #elif widget is self.checkbox:
                #    self.checkbox.toggle()
                #    consume = True
                elif widget is None:
                    self.active = False
                    self.text_box.active = False
            else:
                self.active = False
                self.text_box.active = False
        else:
            self.active = False
            self.text_box.active = False
        if consume:
            self.mouse.mark_event_handled(event_)

    def __mouse_up(self, event_: pygame.event.Event):
        pass



