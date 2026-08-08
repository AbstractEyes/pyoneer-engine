from typing import Optional

import pygame
from pygame import Rect, Vector2

from scripts.core.game_object import PyoneerGameObject
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.component import GameComponent
from scripts.core.ui.widget.containers.button import Button
from scripts.core.ui.widget_color import WidgetColor


class ScrollDirection:
    Horizontal = 0
    Vertical = 1


class ScrollComponent(GameComponent):
    def __init__(self,
                 scrollable_bounds: Rect | None = None,
                 scroll_direction: ScrollDirection = ScrollDirection.Vertical,
                 scroll_width: int = 14,
                 scroll_height: int = 14,
                 corner_deadzone: int = 14,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__scroll_direction = scroll_direction
        self.scroll_width = scroll_width
        """The width of the scroll arrows and thumb."""
        self.scroll_height = scroll_height
        """The height of the scroll arrows and thumb."""
        self.corner_deadzone = corner_deadzone
        """The deadzone at the end of the scroll bar bar bounds to be ignored."""
        self.scroll_position = 0
        """Current scroll position based on percentage of the overall bounds."""
        self.scroll_rate = 20
        """Percentage of the of the bounds space scrolled when using the scroll wheel or arrow keys."""
        self.scrollable_bounds = scrollable_bounds if scrollable_bounds is not None else self.parent.working_area.copy()
        """Bounds of the scrollable space used to define the scroll."""
        self.dragging_scroll_thumb = False
        """Whether the scroll thumb is currently being dragged."""
        self.dragging_scroll_thumb_offset = Vector2(0, 0)
        """The offset of the mouse from the top left of the thumb when dragging."""
        self.scroll_bar: Button | None = None
        self.arrow_1: Button | None = None
        self.arrow_2: Button | None = None
        self.scroll_thumb: Button | None = None
        self.use_immediate_viewport = False
        self.needs_update = True

    def core_lifecycle_build(self, event: Optional[PyoneerEvent] = None):
        super().core_lifecycle_build(event)
        self.__make()

    def __scroll_bar_bounds(self) -> Rect:
        """Adjusts the scroll bar bounds to match the bounds available."""
        if self.__scroll_direction == ScrollDirection.Vertical:
            return Rect(self.world_bounds.width - self.scroll_width, 0, self.scroll_width, self.world_bounds.height - self.corner_deadzone - self.scroll_height)
        else:
            return Rect(0, self.world_bounds.height - self.scroll_height, self.world_bounds.width - self.corner_deadzone - self.scroll_height, self.scroll_height)

    def __scroll_bar_with_offsets(self) -> Rect:
        """Returns an adjusted offset area without the arrows."""
        if self.__scroll_direction == ScrollDirection.Vertical:
            return Rect(self.world_bounds.width - self.scroll_width, self.scroll_height, self.scroll_width, self.world_bounds.height - self.corner_deadzone - (self.scroll_height * 2))
        else:
            return Rect(self.scroll_width, self.world_bounds.height - self.scroll_height, self.world_bounds.width - self.corner_deadzone - (self.scroll_width * 2), self.scroll_height)

    def __arrow_1_bounds(self) -> Rect:
        """Adjusts the arrow 1 bounds to match the bounds available."""
        if self.__scroll_direction == ScrollDirection.Vertical:
            return Rect(self.world_bounds.width - self.scroll_width, 0, self.scroll_width, self.scroll_height)
        else:
            return Rect(0, self.world_bounds.height - self.scroll_height, self.scroll_width, self.scroll_height)

    def __arrow_2_bounds(self) -> Rect:
        """Adjusts the arrow 2 bounds to match the bounds available."""
        if self.__scroll_direction == ScrollDirection.Vertical:
            return Rect(self.world_bounds.width - self.scroll_width, self.world_bounds.height - (self.scroll_height * 2), self.scroll_width, self.scroll_height)
        else:
            return Rect(self.world_bounds.width - (self.scroll_width * 2), self.world_bounds.height - self.scroll_height, self.scroll_width, self.scroll_height)

    @property
    def scrollable_extent(self) -> int:
        """Content size along this scrollbar's own axis."""
        if self.__scroll_direction == ScrollDirection.Vertical:
            return self.scrollable_bounds.height
        return self.scrollable_bounds.width

    @property
    def visible_extent(self) -> int:
        """Viewport size along this scrollbar's own axis."""
        if self.__scroll_direction == ScrollDirection.Vertical:
            return self.world_bounds.height
        return self.world_bounds.width

    @property
    def has_overflow(self) -> bool:
        """Is there anything to scroll on this axis?

        A scrollbar with no overflow should not be interactive; its thumb fills
        the bar, so every ratio here divides by zero.
        """
        return self.scrollable_extent > self.visible_extent

    def __percentage_ratio(self) -> float:
        """Fraction of the content that is visible. 1.0 when it all fits.

        A zero-sized scrollable area is legal -- an empty Panel has one -- and
        used to divide by zero here.
        """
        extent = self.scrollable_extent
        if extent <= 0:
            return 1.0
        return self.visible_extent / extent

    def __working_percentage_ratio(self) -> float:
        """Same fraction, measured against the bar's usable length."""
        extent = self.scrollable_extent
        if extent <= 0:
            return 1.0
        area = self.__scroll_bar_with_offsets()
        length = area.height if self.__scroll_direction == ScrollDirection.Vertical else area.width
        return length / extent

    def __calculate_bar_fill(self) -> float:
        """Calculates the fill percentage the thumb covers within the scroll bar."""
        area_bounds = self.__scroll_bar_with_offsets()
        if self.__scroll_direction == ScrollDirection.Vertical:
            return area_bounds.height * self.__working_percentage_ratio()
        else:
            return area_bounds.width * self.__working_percentage_ratio()

    def __scroll_thumb_bounds(self) -> Rect:
        scroll_area = self.__scroll_bar_with_offsets()
        visible_ratio = self.__working_percentage_ratio()
        thumb_size = visible_ratio * (
            scroll_area.height if self.__scroll_direction == ScrollDirection.Vertical else scroll_area.width)

        # Ensure the thumb size does not become too small or too large.
        thumb_size = max(thumb_size, 5)  # Minimum thumb size to maintain interactivity
        thumb_size = min(thumb_size,
                         scroll_area.height if self.__scroll_direction == ScrollDirection.Vertical else scroll_area.width)

        # Calculate the position of the thumb within the scrollbar
        if self.__scroll_direction == ScrollDirection.Vertical:
            max_scroll_position = self.scrollable_bounds.height - self.world_bounds.height
            scroll_ratio = self.scroll_position / max_scroll_position if max_scroll_position != 0 else 0
            thumb_position = scroll_ratio * (scroll_area.height - thumb_size)
        else:
            max_scroll_position = self.scrollable_bounds.width - self.world_bounds.width
            scroll_ratio = self.scroll_position / max_scroll_position if max_scroll_position != 0 else 0
            thumb_position = scroll_ratio * (scroll_area.width - thumb_size)

        # Clamp the position to avoid the thumb moving out of bounds
        thumb_position = max(thumb_position, 0)
        if self.__scroll_direction == ScrollDirection.Vertical:
            thumb_position = min(thumb_position, scroll_area.height - thumb_size)
            return Rect(self.world_bounds.width - self.scroll_width,
                        scroll_area.y + thumb_position,
                        self.scroll_width,
                        thumb_size)
        else:
            thumb_position = min(thumb_position, scroll_area.width - thumb_size)
            return Rect(scroll_area.x + thumb_position,
                        self.world_bounds.height - self.scroll_height,
                        thumb_size,
                        self.scroll_height)

    def __make(self):
        self.scroll_bar = Button(parent=self,
                                 depth=0,
                                 bounds=self.__scroll_bar_bounds(),
                                 background_color=WidgetColor().set_list([28, 34, 40, 255]),
                                 border_color=WidgetColor().set_list([90, 96, 102, 255]))
        arrow1 = '/\\' if self.__scroll_direction == ScrollDirection.Vertical else '<'
        arrow2 = '\\/' if self.__scroll_direction == ScrollDirection.Vertical else '>'
        self.arrow_1 = Button(parent=self,
                              depth=2,
                              bounds=self.__arrow_1_bounds(),
                              background_color=WidgetColor().set_list([128, 134, 140, 255]),
                              font_size=12,
                              text=arrow1)
        self.arrow_2 = Button(parent=self,
                              depth=2,
                              bounds=self.__arrow_2_bounds(),
                              background_color=WidgetColor().set_list([128, 134, 140, 255]),
                              font_size=12,
                              text=arrow2)
        self.scroll_thumb = Button(parent=self,
                                   depth=1,
                                   text='',
                                   bounds=self.__scroll_thumb_bounds(),
                                   background_color=WidgetColor().set_list([128, 134, 140, 255]))
        self.bind_component("bar", self.scroll_bar)
        self.bind_component("arrow_1", self.arrow_1)
        self.bind_component("arrow_2", self.arrow_2)
        self.bind_component("thumb", self.scroll_thumb)
        # NOTE: there was a second bind of scroll_thumb here under the key
        # "scroll_bar". The real bar is already bound as "bar", so that line
        # registered the thumb twice: it and its three children received every
        # event twice (a listener on the thumb fired twice per dispatch) and
        # queued duplicate blit tokens, compositing the thumb on top of itself.
        #self.bind_sync_listener(GameEventType.UPDATE, self.__update_scroll)
        self.arrow_1.mouse.bind_mouse_listener(GameEventType.MOUSE_CLICK_INSIDE, self.__event__arrow_click_scroll_up)
        self.arrow_2.mouse.bind_mouse_listener(GameEventType.MOUSE_CLICK_INSIDE, self.__event__arrow_click_scroll_down)
        self.arrow_1.use_immediate_viewport = False
        self.arrow_2.use_immediate_viewport = False
        self.scroll_thumb.use_immediate_viewport = False
        self.scroll_bar.use_immediate_viewport = False
        self.scroll_bar.mouse.bind_mouse_listener(GameEventType.MOUSE_DOWN_INSIDE, self.__event__mouse_clicked_within_scroll_bar)
        self.scroll_thumb.mouse.bind_mouse_listener(GameEventType.MOUSE_DOWN_INSIDE, self.__event__mouse_down_scroll_thumb)
        self.scroll_thumb.mouse.bind_mouse_listener(GameEventType.MOUSE_UP, self.__event__mouse_up_scroll_thumb)
        self.scroll_thumb.mouse.bind_mouse_listener(GameEventType.MOUSE_DRAGGING, self.__event__mouse_drag_scroll_thumb)
        self.bind_sync_listener(GameEventType.VIEWPORT_SCROLLED, self.__event__update_scroll)

    def __event__update_scroll(self, event: Optional[PyoneerEvent] = None):
        """Recompute the bar and thumb geometry for the current scroll state.

        These two assignments are the reason the bounds cascade exists. The
        thumb's height is a function of `scrollable_bounds`, so it changes
        whenever the scrolled content changes size -- and before the cascade
        landed, writing `local_bounds` here updated a Rect and nothing else:
        the thumb's world bounds and the surface of the shape it actually
        draws both kept whatever size they were built with. Measured on a
        Panel(300x200, working_area 300x210): drive scrollable_bounds to
        h=4000 and local_bounds became h=6 while the surface stayed h=118.

        `local_bounds` now routes through GameComponent._on_bounds_changed,
        which rebases world bounds, walks the children and lands on
        DrawComponent.resize() for each surface. Nothing extra is needed
        here; the assignments below are the trigger.
        """
        self.scroll_bar.local_bounds = self.__scroll_bar_with_offsets()
        self.scroll_thumb.local_bounds = self.__scroll_thumb_bounds()
        #self.parent.send_event(GameEventType.TRANSFORM, PyoneerEvent(GameEventType.TRANSFORM, sender=self))

    def relayout(self):
        """Re-place the bar, thumb and BOTH ARROWS against the current bounds.

        Every one of those rects is derived from `world_bounds`, and nothing
        recomputed the arrows when the ScrollComponent itself was resized --
        __event__update_scroll only ever moved the bar and thumb, and only on a
        scroll event. Shrinking a window therefore left the arrows at their
        construction coordinates: measured x=362 in a panel that had shrunk to
        216 wide, so they hung off the right-hand edge of the frame.
        """
        if self.scroll_bar is None:
            return
        self.arrow_1.local_bounds = self.__arrow_1_bounds()
        self.arrow_2.local_bounds = self.__arrow_2_bounds()
        self.__event__update_scroll()

    def _on_size_changed(self, width: int | float, height: int | float):
        super()._on_size_changed(width, height)
        self.relayout()

    def __event__mouse_clicked_within_scroll_bar(self, event: Optional[PyoneerEvent] = None):

        """Event if the mouse is down, check if it's within the scroll bar."""
        if event and event.event.button == pygame.BUTTON_LEFT:
            click_position = Vector2(event.event.pos)
            thumb_bounds = self.scroll_thumb.world_bounds

            if self.__scroll_direction == ScrollDirection.Vertical:
                if click_position.y < thumb_bounds.y:
                    self.scroll_position -= self.__get_scroll_amount().y * 5
                elif click_position.y > thumb_bounds.y + thumb_bounds.height:
                    self.scroll_position += self.__get_scroll_amount().y * 5
            else:
                if click_position.x < thumb_bounds.x:
                    self.scroll_position -= self.__get_scroll_amount().x * 5
                elif click_position.x > thumb_bounds.x + thumb_bounds.width:
                    self.scroll_position += self.__get_scroll_amount().x * 5

            self.__clamp_scroll()
            self.__event__update_scroll()
            self.__send_panel_scrolled_event()

    def __event__mouse_down_scroll_thumb(self, event: Optional[PyoneerEvent] = None):
        """If the mouse is down within the scroll thumb this event is triggered."""
        if event is not None and event.event.button == pygame.BUTTON_LEFT:
            self.dragging_scroll_thumb = True
            self.dragging_scroll_thumb_offset = Vector2(event.event.pos) - self.scroll_thumb.world_bounds.topleft
            self.parent.force_update_transforms()

    def __event__mouse_drag_scroll_thumb(self, event: Optional[PyoneerEvent] = None):
        """Dragged after mouse is already clicked within the scroll thumb."""
        if self.dragging_scroll_thumb and event:
            # get the ratio of the current click position to the scroll bar bounds
            click_position = Vector2(event.event.pos)
            offset_scroll_bar = self.__scroll_bar_bounds()
            scroll_bar_bounds = self.scroll_bar.world_bounds.copy()
            scroll_bar_bounds.x += offset_scroll_bar.x
            scroll_bar_bounds.y += offset_scroll_bar.y
            # determine the new position of the thumb based on the current mouse position
            # travel = how far the thumb can actually move inside the bar. It is
            # ZERO when the content fits, because the thumb then fills the bar.
            # Both of these divided by it unguarded, so dragging the thumb of a
            # scrollbar with nothing to scroll raised ZeroDivisionError and
            # killed the frame. The sibling calculation in
            # __scroll_thumb_bounds already guarded this exact quantity
            # (`if max_scroll_position != 0 else 0`); the drag path did not.
            if self.__scroll_direction == ScrollDirection.Vertical:
                thumb_position = click_position.y - scroll_bar_bounds.y - self.dragging_scroll_thumb_offset.y
                max_scroll_position = self.scrollable_bounds.height - self.world_bounds.height
                travel = scroll_bar_bounds.height - self.scroll_thumb.world_bounds.height
            else:
                thumb_position = click_position.x - scroll_bar_bounds.x - self.dragging_scroll_thumb_offset.x
                max_scroll_position = self.scrollable_bounds.width - self.world_bounds.width
                travel = scroll_bar_bounds.width - self.scroll_thumb.world_bounds.width

            scroll_ratio = thumb_position / travel if travel > 0 else 0.0
            self.scroll_position = scroll_ratio * max(0, max_scroll_position)

            #self.__clamp_scroll()
            self.__event__update_scroll()
            self.__send_panel_scrolled_event()
            self.parent.force_update_transforms()

    def __event__mouse_up_scroll_thumb(self, event: Optional[PyoneerEvent] = None):
        """Mouse up releases the thumb at it's horizontal or vertical position and updates panel."""
        if self.dragging_scroll_thumb:
            self.dragging_scroll_thumb = False

    def __clamp_scroll(self):
        """Clamps the scroll position to the scrollable bounds."""
        if self.scroll_position < 0:
            self.scroll_position = 0
        elif self.scroll_position > self.scrollable_bounds.height - self.world_bounds.height:
            self.scroll_position = self.scrollable_bounds.height - self.world_bounds.height

    def __get_scroll_amount(self) -> Vector2:
        """Calculates the amount to scroll based on the scroll rate."""
        return Vector2((self.scroll_rate * self.world_bounds.width // 100, self.scroll_rate * self.world_bounds.height // 100))

    @property
    def scroll_amount(self) -> int | float:
        """Calculates the amount to scroll based on the scroll rate."""
        amount = self.__get_scroll_amount()
        if self.__scroll_direction == ScrollDirection.Vertical:
            return amount.y
        else:
            return amount.x

    def __event__arrow_click_scroll_up(self, event: Optional[PyoneerEvent]):
        """Scroll up by the scroll rate."""
        if event is not None and event.event.button == pygame.BUTTON_LEFT:
            self.scroll(-1)

    def __event__arrow_click_scroll_down(self, event: Optional[PyoneerEvent]):
        """Scroll down by the scroll rate."""
        if event is not None and event.event.button == pygame.BUTTON_LEFT:
            self.scroll(1)

    def __send_panel_scrolled_event(self, sender: Optional[PyoneerGameObject] = None):
        """Send the panel scrolled event."""
        if self.parent is not None:
            #self.parent.force_update_transforms()
            self.__event__update_scroll()
            self.parent.send_event_advanced(event_type=GameEventType.VIEWPORT_SCROLLED,
                                            event=PyoneerEvent(GameEventType.VIEWPORT_SCROLLED,
                                            data={"x": self.scroll_position if self.__scroll_direction == ScrollDirection.Horizontal else 0, "y": self.scroll_position if self.__scroll_direction == ScrollDirection.Vertical else 0},
                                            sender=sender))

    def scroll(self, scalar: float):
        """Scroll the panel by the self.scroll_amount * scalar with deployed events."""
        self.scroll_position += round(scalar * self.scroll_amount)
        self.__clamp_scroll()
        self.__send_panel_scrolled_event()
        self.parent.force_update_transforms()

    def scroll_to(self, position: int):
        """Scroll to a specific position."""
        self.scroll_position = position
        self.__clamp_scroll()
        self.__send_panel_scrolled_event()
        self.parent.force_update_transforms()