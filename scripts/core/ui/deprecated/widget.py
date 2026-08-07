from __future__ import annotations

from abc import ABC, abstractmethod

from pygame import surface

from scripts.core.game_object import PyoneerGameObject


class Widget(PyoneerGameObject, ABC):

    @abstractmethod
    def refresh(self): ...

    @abstractmethod
    def core_prepare(self) -> surface: ...

    @abstractmethod
    def show(self): ...

    @abstractmethod
    def hide(self): ...

    @abstractmethod
    def move(self, x: int, y: int): ...
