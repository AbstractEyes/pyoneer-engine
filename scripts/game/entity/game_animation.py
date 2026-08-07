from typing import Optional

import pygame
import pytmx
from pygame import Surface, Rect
from pygame.draw import rect

from config.managers.animation_data import DataAnimationCategory, DataAnimation, DataAnimationFrame
from scripts.core.event_manager import PyoneerEvent


# takes in an individual animation sequence data, all sub animations within
class GameAnimation:
    def __init__(self, animation_data: DataAnimation = None):
        self.data = animation_data
        self.frames = animation_data.frames
        self.active = False
        self.current_frame = 0
        self.current_time = 0
        self.name = animation_data.name
        self._frame_changed = True

    def frame_changed(self) -> bool:
        changed = self._frame_changed
        self._frame_changed = False
        return changed

    def frame(self, order="left-to-right") -> Rect:
        data = self.frames[self.current_frame]
        if order == "left-to-right":
            return Rect(data.x + self.current_frame * data.width, data.y, data.width, data.height)
        elif order == "top-to-bottom":
            return Rect(data.x, data.y + self.current_frame * data.height, data.width, data.height)
        else:
            # default to left-to-right
            return Rect(data.x + self.current_frame * data.width, data.y, data.width, data.height)

    def set_frame(self, frame: int, time=0):
        self.current_frame = frame
        self.current_time = time

    def start(self, from_beginning=True):
        self.active = True
        if from_beginning:
            self.current_frame = 0
            self.current_time = 0

    def stop(self, reset=False):
        self.active = False
        if reset:
            self.current_frame = 0
            self.current_time = 0

    def update(self, event: PyoneerEvent):
        if not self.active:
            return
        self.current_time += event.data["delta"]
        if self.current_time > self.frames[self.current_frame].duration:
            self.current_time = 0
            self.current_frame += 1
            self._frame_changed = True
            if self.current_frame >= self.data.frame_count:
                self.current_frame = 0
                if not self.data.loop:
                    self.active = False
                    self._frame_changed = False


# houses the entire structure for a series of animations based on a single set of prepared data
class GameAnimationHandler:
    def __init__(self, animation_data: DataAnimationCategory):
        self._data = animation_data
        self._spritesheet: Surface = pygame.image.load(self._data.file)
        self._animations: dict[str, GameAnimation] = {}
        self._name = animation_data.name
        self._image: Surface | None = None
        self._build_animations()
        self.start('idle_down')

    def _build_animations(self):
        for sequence in self._data.sequences.values():
            animation = GameAnimation(animation_data=sequence)
            self._animations[sequence.name] = animation

    def _active_animation(self) -> GameAnimation | None:
        for animation in self._animations.values():
            if animation.active:
                return animation
        return None

    def image(self) -> Surface:
        # get the current frame of the active animation to return a surface
        active = self._active_animation()
        changed = active.frame_changed()
        if not active:
            if self._image:
                return self._image
            else:
                self._image = self._spritesheet.subsurface((0, 0, 0, 0))
                return self._image
        else:
            if changed:
                frame: Rect = active.frame()
                self._image = self._spritesheet.subsurface((frame.x, frame.y, frame.width, frame.height))
            return self._image

    def start(self, name=None):
        self.stop()
        if name:
            self._animations[name].active = True

    def stop(self, name=None):
        if name:
            self._animations[name].active = False
        else:
            for animation in self._animations.values():
                animation.active = False

    def pause(self):
        if self._active_animation():
            self._active_animation().stop(False)

    def resume(self):
        if self._active_animation():
            self._active_animation().stop(False)

    def set_frame(self, frame: int):
        if self._active_animation():
            self._active_animation().current_frame = frame

    def get_animation(self, name):
        return self._animations[name]

    def update(self, event: Optional[PyoneerEvent] = None):
        for animation in self._animations.values():
            if animation.active:
                animation.update(event)

    def dispose(self):
        self._animations.clear()

    def clear(self):
        self._animations.clear()