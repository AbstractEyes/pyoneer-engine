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
from scripts.core.ui.anchor import Anchor

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
        # `active` is inherited and defaults True: the window participates in
        # input from the moment it is constructed. It used to be forced False
        # here and flipped True on click, because `active` was doing duty as
        # the focus flag -- now that focus lives on `focused`, forcing it
        # False here would disable the entire window subtree, since input
        # dispatch is gated on `active`.
        # -------------------------------------------------
        # core components
        self.active_component: GameComponent | None = None
        """The descendant currently holding focus, if any."""
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
    def core_lifecycle_prepare(self, event: PyoneerEvent | None = None):
        super().core_lifecycle_prepare(event)
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
            # Anchors: this is what makes the window resizable at all. Before
            # them, resizing a GameWindow left body, title bar, title text,
            # close button and both inner panels at their original sizes.
            self.body.anchor = Anchor.ALL                    # fills the window
            self.header_bar.anchor = Anchor.TOP | Anchor.STRETCH_X
            self.header_text.anchor = Anchor.TOP | Anchor.STRETCH_X
            self.close_button.anchor = Anchor.TOP_RIGHT      # rides the corner
            if self.panel is not None:
                self.panel.anchor = Anchor.TOP | Anchor.STRETCH_X
            if self.panel2 is not None:
                self.panel2.anchor = Anchor.STRETCH_X | Anchor.BOTTOM

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
        """Begin a drag if the press landed on the header, but not on a button."""
        if not (self.header_visible and self.clickable and self.movable):
            return
        if self.dragging_component or event.event.button != pygame.BUTTON_LEFT:
            return
        if not self.header_bar.world_bounds.collidepoint(event.event.pos):
            self.__end_drag()
            return
        if self.close_button.world_bounds.collidepoint(event.event.pos):
            # The close button owns this press; do not start dragging.
            return
        self.dragging_component = True
        # Grab offset from the press to the window's top-left, so the window
        # does not jump to the cursor on the first drag frame.
        self.dragging_offset = Vector2(event.event.pos) - Vector2(self.world_bounds.topleft)

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

    def __end_drag(self):
        """Clear drag state. The offset resets to zero, not None.

        It used to be set to None on drag end and on a failed press, while
        __event_mouse_dragging_window subtracted it unguarded - so any
        MOUSE_DRAGGING that arrived while not dragging raised
        `TypeError: unsupported operand type(s) for -: 'Vector2' and 'NoneType'`.
        """
        self.dragging_component = False
        self.dragging_offset = Vector2(0, 0)

    def __event_mouse_up_dropping_window(self, event: PyoneerEvent):
        if self.dragging_component:
            self.__end_drag()

    def __event_mouse_dragging_window(self, event: PyoneerEvent):
        if not self.dragging_component or not self.movable:
            return
        target = Vector2(event.event.pos) - self.dragging_offset
        self.move(target.x, target.y)

    def __event__mouse_clicked_inside(self, event_: PyoneerEvent):
        """Resolve which descendant was clicked and move focus to it.

        Focus is tracked with `focused`, not `active`. `active` means "this
        window participates in input at all"; a window that is hidden but
        still active must keep eating clicks, so overloading it for
        click-focus made the two states impossible to express together.

        This no longer names a concrete child type. It previously branched on
        `self.text_box` in four places with no None guard, so removing the
        demo widgets from this class turned every left-click into an
        AttributeError.
        """
        if not self.clickable or event_.event.button != pygame.BUTTON_LEFT:
            self.set_focus(None)
            return

        widget = self.top_widget_at_position(Vector2(event_.event.pos),
                                             [self, self.mouse, self.keyboard])
        if not isinstance(widget, GameComponent) or not widget.is_clickable():
            self.set_focus(None)
            return

        self.focused = True
        self.set_focus(widget)

        if widget is self.close_button:
            self.close()
            self.mouse.mark_event_handled(event_)
        elif widget.accepts_focus:
            # The focused widget consumed the click; stop it reaching
            # anything underneath.
            self.mouse.mark_event_handled(event_)

    def set_focus(self, widget: GameComponent | None):
        """Give focus to `widget`, clearing it from whatever held it before."""
        if self.active_component is widget:
            return
        if self.active_component is not None:
            self.active_component.focused = False
        self.active_component = widget
        if widget is not None:
            widget.focused = True
        else:
            self.focused = False

    def close(self):
        """Hide the window, disable it, and drop focus.

        Clears `active` as well as `visible`. Hiding alone is not enough:
        input is gated on `active`, so a merely-invisible window would keep
        swallowing clicks in the rectangle it used to occupy -- which is the
        exact behaviour that is correct for a hidden-but-live window and
        wrong for a closed one.

        Deliberately hides rather than unbinding: LayerRenderer has no unbind
        path yet, so removing the component here would leave its layer
        blitting it every frame.
        """
        self.visible = False
        self.active = False
        self.set_focus(None)
        self.focused = False

    def open(self):
        """Show the window and re-enable it. Inverse of close()."""
        self.visible = True
        self.active = True



