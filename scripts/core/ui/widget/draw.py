from typing import Optional

import pygame
from pygame import Surface, surface, Vector2, Rect

from scripts.game.game_camera import GameCamera
from scripts.core.blitpool import BlitPool
from scripts.core.viewclip import clip_to_view, Containment
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.component import GameComponent


class DrawComponent(GameComponent):

    def __init__(self,
                 image_in: Surface | None = None,
                 camera: GameCamera | None = None,
                 view_offset: Vector2 | None = None,
                 *args,
                 **kwargs):
        super().__init__(*args, **kwargs)
        if image_in is not None:
            self._image = image_in
        else:
            clamped = self.world_bounds.copy()
            clamped.width = max(1, clamped.width)
            clamped.height = max(1, clamped.height)
            self._image = Surface((clamped.width, clamped.height)).convert_alpha()
        self.draws = True
        """Whether the current object is drawn."""
        self.last_containment: Containment = Containment.CONTAINED
        """How much of this component was visible on the last frame drawn.

        One of the three questions the blit revamp exists to answer:
        OUTSIDE, PARTIAL or CONTAINED against the screen.
        """
        self.is_view = False
        """Whether the current object's bounds are used as a viewport."""
        self.viewport_offset: Vector2 = view_offset if view_offset is not None else Vector2(0, 0)
        """The offset of the object on the viewport."""
        self.__make()

    def __parent_moved(self, event: PyoneerEvent): ...
        #if self.parent is not None:
        #    set_val = self.world_bounds.copy()
        #    if event.data.get("position") is not None:
        #        # position moved
        #        set_val.width = max(1, self.parent.world_bounds.width)
        #        set_val.height = max(1, self.parent.world_bounds.height)
        #        pass
        #    if event.data.get("size") is not None:
        #        # size changed
        #        set_val.x = self.world_bounds.x
        #        set_val.y = self.world_bounds.y
        #        pass
        #    self.world_bounds = set_val

    def __make(self):
        #self.viewport = GameCamera #Viewport(parent=self, bounds=self.bounds, full_bounds=self.bounds, offset=self.viewport_offset)
        self.bind_sync_listener(GameEventType.DISPOSE, self.dispose_drawable)
        self.bind_sync_listener(GameEventType.BLITS, self.__blits)
        #self.bind_sync_listener(GameEventType.PARENT_MOVED, self.__parent_moved)

    def scale(self, width: int, height: int, destination: Surface | None = None):
        self._image = pygame.transform.scale(self._image, (width, height), destination)

    def dispose_drawable(self):
        if self._image is not None:
            self._image = None

    def image_snip(self, area: Rect) -> surface.Surface:
        try:
            return self._image.subsurface(area.clip(self._image.get_rect()))
        except ValueError:
            return self._image

    def __blits(self, event: Optional[PyoneerEvent] = None):
        if not self.draws:
            return

        depth, priority = self.depth, self.priority
        if event is not None and event.data.get("layer_depth") is not None:
            depth += event.data["layer_depth"]

        if not self.visible:
            return

        image = self.image
        if image is None:
            # A token carrying image=None fails much later inside pygame's
            # blits() with nothing identifying which object queued it.
            return

        viewport_component = self.get_viewport_component

        if viewport_component is not None:
            """After the rewrite of working bounds, we are to treat everything as though it's viewport working bounds are law."""
            viewport_screen_bounds = viewport_component.working_area
            """x/y is an offset, width/height is a hard fixed width/height for the area"""
            viewport_world_bounds = viewport_component.world_bounds
            """This is the viewport's representative bounds. Meant to be additively offset from the viewport's working area."""
            world_bounds = self.world_bounds
            """This is the representative bounds from the world."""
            drawn_screen_section = world_bounds.clip(viewport_world_bounds)
            if drawn_screen_section.width <= 0 or drawn_screen_section.height <= 0:
                # Entirely outside its own panel.
                BlitPool.count_culled()
                return
            # Where in the SOURCE surface those visible pixels come from.
            source_origin = (drawn_screen_section.x - world_bounds.x + viewport_screen_bounds.x,
                             drawn_screen_section.y - world_bounds.y + viewport_screen_bounds.y)
        else:
            drawn_screen_section = self.world_bounds
            source_origin = (0, 0)

        # Second clip, against the screen. The viewport clip above only asks
        # "is this inside my panel" -- a panel can itself be off-screen, and
        # a component with no viewport was never clipped at all. Measured:
        # dragging the test window off the left edge left 51 of 63 tokens
        # fully outside the screen, still built and still handed to SDL.
        clip_region = None
        if event is not None and event.data is not None:
            clip_region = event.data.get("screen")

        if clip_region is None:
            # No clip supplied (a bare unit-test dispatch); draw unclipped
            # rather than silently drawing nothing.
            BlitPool.blit_to_layer(depth, priority, image,
                                   destination=(drawn_screen_section.x, drawn_screen_section.y),
                                   sender=self,
                                   draw_area=Rect(source_origin[0], source_origin[1],
                                                  drawn_screen_section.width,
                                                  drawn_screen_section.height))
            return

        clipped = clip_to_view(drawn_screen_section, clip_region, source_origin)
        if clipped is None:
            BlitPool.count_culled()
            return

        self.last_containment = clipped.containment
        BlitPool.blit_to_layer(depth, priority, image,
                               destination=clipped.destination,
                               sender=self,
                               draw_area=clipped.source_area)

    #def __blits(self, event: Optional[PyoneerEvent] = None):
        #if not self.draws:
        #    return
        #depth, priority = self.depth, self.priority
        #if event is not None and event.data.get("layer_depth") is not None:
        #    depth += event.data["layer_depth"]
        #viewport_component = self.get_viewport_component
        #if viewport_component is not None:
        #    viewport = viewport_component.world_bounds.copy()
        #    """This is the viewport's representative bounds."""
        #    world_bounds = self.world_bounds.copy()
        #    """This is the representative bounds from the world."""
        #    drawn_screen_section = world_bounds.clip(viewport)
        #    # now we need to get the local drawn offset and width/height for blitting the image to the larger image
        #    drawn_section = Rect(drawn_screen_section.x - world_bounds.x,
        #                         drawn_screen_section.y - world_bounds.y,
        #                         drawn_screen_section.width,
        #                         drawn_screen_section.height)
        #    BlitPool.blit_to_layer(depth, priority, self.image(), destination=world_bounds.topleft, sender=self, draw_area=drawn_section)
        #else: # no viewport, draw to the whatever
        #    BlitPool.blit_to_layer(depth, priority, self.image(), destination=self.world_bounds, sender=self, draw_area=self.image().get_rect())

