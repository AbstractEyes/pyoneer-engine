from typing import Optional

import pygame
from pygame import Rect, Vector2

from scripts.core.ui.widget.behavior.keyboard import KeyboardComponentAsync, KeyBindingType
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.ui.widget.behavior.mouse import MouseComponentAsync
from scripts.core.component import GameComponent
from scripts.core.ui.widget.containers.scroll import ScrollComponent, ScrollDirection
from scripts.core.ui.widget.draw import DrawComponent
from scripts.core.ui.widget.shape import ShapeComponent
from scripts.core.ui.widget_color import WidgetColor


class Panel(DrawComponent):
    def __init__(self,
                 working_area: Rect | None = None,
                 *args,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.is_view = True
        self.draws = True
        self.screen_area = working_area if working_area is not None else self.world_bounds.copy()
        """The bounds of the scrollable space used to define the scroll bars."""
        self.vertical_scroll: ScrollComponent | None = None
        self.horizontal_scroll: ScrollComponent | None = None
        self.background: ShapeComponent | None = None
        self.mouse: MouseComponentAsync | None = None
        self.keyboard: KeyboardComponentAsync | None = None
        self.dead_corner: ShapeComponent | None = None
        self.children: list[GameComponent] = []

    def core_lifecycle_build(self, event: Optional[PyoneerEvent] = None):
        super().core_lifecycle_build(event)
        self.background = ShapeComponent(
            parent=self,
            depth=0,
            bounds=Rect(0, 0, self.screen_area.width, self.screen_area.height),
            shape=ShapeComponent.ShapeType.Rectangle
        )
        self.vertical_scroll = ScrollComponent(
            parent=self,
            depth=1,
            bounds=Rect(0, 0, self.local_bounds.copy().width, self.local_bounds.copy().height),
            scrollable_bounds=self.screen_area,
            scroll_direction=ScrollDirection.Vertical
        )
        self.horizontal_scroll = ScrollComponent(
            parent=self,
            depth=1,
            bounds=Rect(0, 0, self.local_bounds.copy().width, self.local_bounds.copy().height),
            scrollable_bounds=self.screen_area,
            scroll_direction=ScrollDirection.Horizontal
        )
        self.bind_component("vertical_scroll", self.vertical_scroll)
        self.bind_component("horizontal_scroll", self.horizontal_scroll)
        self.dead_corner = ShapeComponent(
            parent=self,
            depth=2,
            bounds=Rect(self.local_bounds.width - self.horizontal_scroll.arrow_1.local_bounds.width,
                        self.local_bounds.height - self.vertical_scroll.arrow_2.local_bounds.height,
                        self.horizontal_scroll.arrow_1.local_bounds.width,
                        self.vertical_scroll.arrow_1.local_bounds.height),
            shape=ShapeComponent.ShapeType.Rectangle,
            background_color=WidgetColor(0, 0, 0, 50)
        )
        self.mouse = MouseComponentAsync(parent=self)
        self.bind_component("mouse", self.mouse)

        self.keyboard = KeyboardComponentAsync(parent=self)
        self.bind_component("keyboard", self.keyboard)
        self.keyboard.bind_key_event(KeyBindingType.KeyDown, self.__event__scroll_key_down)
        self.keyboard.bind_key_event(KeyBindingType.KeyRepeat, self.__event__scroll_key_down)

        self.bind_component("background", self.background)
        self.bind_component("dead_corner", self.dead_corner)
        #self.bind_sync_listener(GameEventType.UPDATE, self.__update_scroll)
        self.mouse.bind_mouse_listener(GameEventType.MOUSE_SCROLL, self.__event__mouse_scroll)
        #self.child_mouse.bind_mouse_listener(GameEventType.MOUSE_SCROLL_DOWN, self.__event__mouse_scroll_down)
        self.bind_sync_listener(GameEventType.VIEWPORT_SCROLLED, self.__event__viewport_scrolled)
        self.bind_sync_listener(GameEventType.UPDATE, self.__event__update)
        #self.bind_sync_listener(GameEventType.VIEWPORT_SCROLLED, self.__update_scroll)
        working_area = self.working_area.copy()
        working_area.width -= self.horizontal_scroll.arrow_1.local_bounds.width
        working_area.height -= self.vertical_scroll.arrow_1.local_bounds.height
        self.working_area = working_area
        #self.horizontal_scroll.bind_sync_listener(GameEventType.VIEWPORT_SCROLLED, self.__panel_scroll_event)
        #self.vertical_scroll.bind_sync_listener(GameEventType.VIEWPORT_SCROLLED, self.__panel_scroll_event)

    def __event__scroll_key_down(self, event_: PyoneerEvent):
        if self.mouse.mouse_inside:
            if event_.event.key == pygame.K_LEFT:
                self.scroll(-1, 0)
            elif event_.event.key == pygame.K_RIGHT:
                self.scroll(1, 0)
            elif event_.event.key == pygame.K_UP:
                self.scroll(0, -1)
            elif event_.event.key == pygame.K_DOWN:
                self.scroll(0, 1)
            self.send_event(GameEventType.VIEWPORT_SCROLLED,
                            {"x": self.horizontal_scroll.scroll_position, "y": self.vertical_scroll.scroll_position})

    @property
    def screen_area(self) -> Rect:
        return self.__screen_area

    @screen_area.setter
    def screen_area(self, value: Rect) -> None:
        self.__screen_area = value

    def attach_component(self, name: str, obj: GameComponent,
                         depth: int | None = None, offset: Vector2 | None = None):
        """Put a component in the panel's scrollable content area.

        Use this rather than bind_component for content: only attached children
        are offset when the panel scrolls, and only they are measured by
        content_bounds()/fit_scroll_area(). bind_component is for the panel's
        own chrome.

        Sets the parent. It previously did not -- the line was commented out --
        and every child the panel builds for itself passes `parent=self` to its
        constructor instead, so the omission was invisible. Anything attached
        from outside was left parentless, and
        GameComponent.__update_world_bounds returns immediately when parent is
        None: the component kept world_bounds == local_bounds, drew at the wrong
        place, and did not move when the panel scrolled. Nothing errored.
        """
        obj.bind_parent(self, preserve_world_bounds=False)
        if depth is not None:
            obj.depth = depth
        if offset is not None:
            obj.offset = offset
        self.bind_component(name, obj)
        self.__add_child(obj)
        return obj

    def __add_child(self, obj: GameComponent):
        self.children.append(obj)

    def get_components_at(self, point_in: Vector2 | Rect | tuple[int | float, int | float]) -> list[GameComponent]:
        """
            Overrides the get_components_at from Component.
            Returns a list of components that collide with the point including the scroll offset from the panel.
        """
        # recursively get the components at the point
        point = self.adjusted_position(point_in)
        components = []
        for child in self.children:
            if child.world_bounds.collidepoint(point):
                components.append(child)
                components.extend(child.get_components_at(point))
        return components

    def __offset_children(self):
        """Offset the children based on the scroll position."""
        for child in self.children:
            child.offset = Vector2(-self.horizontal_scroll.scroll_position, -self.vertical_scroll.scroll_position)
        self.force_update_transforms()

    def get_clickable_components_at(self, bounds: Rect | Vector2 | tuple[int | float, int | float]) -> list[GameComponent]:
        """
            Overrides the get_clickable_components_at from Component.
            Returns a list of clickable components that collide with the point including the scroll offset from the panel.
        """
        # recursively get the clickable components at the point
        point = self.adjusted_position(bounds)
        components = []
        for child in self.children:
            if child.world_bounds.collidepoint(point.x, point.y) and child.is_clickable():
                components.append(child)
                components.extend(child.get_clickable_components_at(point))
        return components

    def __event__viewport_scrolled(self, event: PyoneerEvent):
        """Update the scroll position based on the event."""
        horizontal = event.data.get("x", 0)
        if horizontal != 0:
            self.horizontal_scroll.scroll_position = horizontal
        vertical = event.data.get("y", 0)
        if vertical != 0:
            self.vertical_scroll.scroll_position = vertical
        self.__clamp_scroll()
        self.__offset_children()

    def __event__mouse_scroll(self, event: Optional[PyoneerEvent] = None):
        """Scroll the panel up."""
        if event is None:
            return
        vertical = event.data.get("vertical_scroll", 0) * -1
        horizontal = event.data.get("horizontal_scroll", 0) * -1
        self.scroll(horizontal, vertical)

    def __clamp_scroll(self):
        """Clamp the scroll position to the scrollable bounds."""
        new_horizontal = max(0, min(self.horizontal_scroll.scroll_position, self.screen_area.width - self.world_bounds.width))
        new_vertical = max(0, min(self.vertical_scroll.scroll_position, self.screen_area.height - self.world_bounds.height))
        self.horizontal_scroll.scroll_position = new_horizontal
        self.vertical_scroll.scroll_position = new_vertical


    def __hide_unhide_scroll(self):
        """Hide or unhide the scroll bars based on the scrollable bounds."""
        self.vertical_scroll.visible = self.screen_area.height > self.world_bounds.height
        # todo; add active hook

    def __event__update(self, event: Optional[PyoneerEvent] = None):
        """Per-frame scroll clamp, scrollbar visibility and transform refresh.

        This was a `core_frame_update` override, which measured 0 calls per
        frame: a Panel is reached through GameWindow's `components` dict, so
        it is driven by the event bus and its core_* methods are never
        invoked. The whole body was dead. Bound to UPDATE it actually runs.
        """
        self.__clamp_scroll()
        self.__hide_unhide_scroll()
        self.force_update_transforms()

    def content_bounds(self) -> Rect:
        """Union of every attached child's local rect, in panel-local space.

        Measures `children` -- the components attached via attach_component --
        and deliberately not `components`, which also holds the panel's own
        chrome (scrollbars, background, dead corner). Including the chrome
        would make the scroll area at least as large as the panel itself no
        matter how little content there is.
        """
        union: Rect | None = None
        for child in self.children:
            rect = child.local_bounds
            union = rect.copy() if union is None else union.union(rect)
        return union if union is not None else Rect(0, 0, 0, 0)

    def fit_scroll_area(self, minimum: Rect | None = None) -> Rect:
        """Resize the scrollable area to the attached content, and refresh.

        Call after adding content, e.g. after filling a GridComponent. Without
        it the scrollbars keep measuring whatever `working_area` was passed to
        the constructor, so a grid that grew past the panel cannot be scrolled
        to -- the content is there and unreachable.
        """
        content = self.content_bounds()
        width = max(content.right, self.world_bounds.width)
        height = max(content.bottom, self.world_bounds.height)
        if minimum is not None:
            width = max(width, minimum.width)
            height = max(height, minimum.height)

        area = Rect(0, 0, int(width), int(height))
        self.screen_area = area
        for scroll in (self.vertical_scroll, self.horizontal_scroll):
            if scroll is not None:
                scroll.scrollable_bounds = area.copy()
        self.__clamp_scroll()
        self.__hide_unhide_scroll()
        self.__offset_children()
        return area

    def scroll(self, dir_x: float, dir_y: float):
        """Scroll the panel by the given direction scalar."""
        self.horizontal_scroll.scroll(dir_x)
        self.vertical_scroll.scroll(dir_y)

    def scroll_to(self, x: int, y: int):
        """Scroll the panel to the given position."""
        self.horizontal_scroll.scroll_to(x)
        self.vertical_scroll.scroll_to(y)