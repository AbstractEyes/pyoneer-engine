from __future__ import annotations
import pygame
from pygame import Vector2


class Transform:

    def __init__(self,
                 position: Vector2 | tuple[int | float, int | float] = None,
                 rotation: int | float = None,
                 scale: Vector2 | tuple[int | float, int | float] = None,
                 transform_in: Transform | None = None):
        self.position = position
        self.rotation = rotation
        self.scale = scale
        if transform_in is not None:
            self.copy(transform_in)

    # necessary for net code in the future.
    @property
    def position(self) -> Vector2:
        return self._position

    @position.setter
    def position(self, position_in: Vector2 | tuple[int | float, int | float] | None) -> None:
        if position_in is not None:
            if isinstance(position_in, tuple):
                self._position = Vector2(position_in)
            else:
                self._position = position_in
        else:
            self._position = Vector2(0, 0)

    @property
    def rotation(self) -> int | float:
        return self._rotation

    @rotation.setter
    def rotation(self, rotation_in: int | float | None) -> None:
        if rotation_in is not None:
            self._rotation = rotation_in
        else:
            self._rotation = 0

    @property
    def scale(self) -> Vector2:
        return self._scale

    @scale.setter
    def scale(self, scale_in: Vector2 | tuple[int | float, int | float] | None) -> None:
        if scale_in is not None:
            if isinstance(scale_in, tuple):
                self._scale = Vector2(scale_in)
            else:
                self._scale = scale_in
        else:
            self._scale = Vector2(1, 1)

    def copy(self, new_transform: Transform) -> Transform:
        self._position: Vector2 = Vector2(new_transform.position.copy())
        self._rotation: int | float = new_transform.rotation
        self._scale: Vector2 = Vector2(new_transform.scale.copy())
        return self

    def clone(self) -> Transform:
        return Transform(self.position.copy(), self.rotation, self.scale.copy())

    def center(self):
        return self.position

    def upper_left(self) -> Vector2:
        return self.position - self.scale / 2
    
    def upper_right(self):
        return self.position + Vector2(self.scale.x / 2, -self.scale.y / 2)

    def lower_left(self):
        return self.position + Vector2(-self.scale.x / 2, self.scale.y / 2)

    def lower_right(self):
        return self.position + self.scale / 2

    def __sub__(self, other: Transform):
        self._position -= other.position.copy()
        self._rotation -= other.rotation
        self._scale -= other.scale.copy()
        return self

    def __mul__(self, other: Transform):
        self._position *= other.position.copy()
        self._rotation *= other.rotation
        self._scale *= other.scale.copy()
        return self

    def __truediv__(self, other: Transform):
        self._position /= other.position.copy()
        self._rotation /= other.rotation
        self._scale /= other.scale.copy()
        return self

    def __add__(self, other: Transform):
        self._position += other.position.copy()
        self._rotation += other.rotation
        self._scale += other.scale.copy()
        return self
