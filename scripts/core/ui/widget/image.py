from typing import Optional

import pygame
from pygame import Surface, Rect, Vector2

from scripts.core.ui.widget.draw import DrawComponent


class ImageComponent(DrawComponent):
    def __init__(self,
                 image_in: str | Surface | None,
                 piece: Rect | None = None,
                 scale: Rect | Vector2 | None = None,
                 rotation: float = 0,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.component_type = "ImageComponent"
        self.display_image: Optional[Surface] = None
        """The image that is modified for display."""
        self.base_image: Optional[Surface] = None
        """The base image that is not modified."""
        self.section: Rect | None = piece
        """The section of the image to display."""
        self.scale: Rect | Vector2 | None = scale
        """The scale of the image."""
        self.rotation: float = rotation
        """The rotation of the image."""
        if image_in is not None:
            self.set_image(image_in)

    def set_image(self, image: Surface | str | None,
                  scale_to_size: bool = True,
                  section: Rect | Vector2 | None = None,
                  rotation: float | None = None,
                  overridden_scale: Rect | Vector2 | None = None):
        if section is not None:
            self.section = section
        if overridden_scale is not None:
            if isinstance(overridden_scale, Vector2):
                self.scale = Rect(0, 0, overridden_scale.x, overridden_scale.y)
            else:
                self.scale = overridden_scale
        if rotation is not None:
            self.rotation = rotation
        if isinstance(image, str):
            self.base_image = pygame.image.load(image).convert_alpha()
        elif isinstance(image, Surface):
            self.base_image = image
        else:
            self.base_image = Surface((1, 1)).convert_alpha()
        self.display_image = self.base_image.copy()
        if self.section is not None:
            self.display_image = self.base_image.subsurface(self.section)
        if scale_to_size:
            self.__scale_image()
        if self.rotation != 0:
            self.display_image, _ = self.__rotate_image(self.display_image, self.world_bounds.center, self.world_bounds.center, self.rotation)

    @property
    def image(self) -> Surface | None:
        """The scaled/rotated result, not the source surface."""
        return self.display_image

    def __scale_image(self, width: int = 0, height: int = 0):
        if self.scale is not None:
            width = self.scale.width
            height = self.scale.height
        if width > 0 and height > 0:
            self.display_image = pygame.transform.scale(self.display_image, (width, height))
        else:
            self.display_image = pygame.transform.scale(self.display_image, (self.world_bounds.width, self.world_bounds.height))

    def __rotate_image(self, image_in, position, origin, angle) -> tuple[Surface, Rect]:
        if self.rotation == 0:
            return image_in, image_in.get_rect(center=position)
        # offset from pivot to center
        image_rect = image_in.get_rect(topleft=(position[0] - origin[0], position[1] - origin[1]))
        offset_center_to_pivot = pygame.math.Vector2(position) - image_rect.center

        # rotated offset from pivot to center
        rotated_offset = offset_center_to_pivot.rotate(-angle)

        # rotated image center
        rotated_image_center = (position[0] - rotated_offset.x, position[1] - rotated_offset.y)

        # get a rotated image
        rotated_image = pygame.transform.rotate(image_in, angle)
        rotated_image_rect = rotated_image.get_rect(center=rotated_image_center)

        return rotated_image, rotated_image_rect