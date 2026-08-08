from typing import Optional

import pygame
import pytmx
from pygame import Surface, Rect
from pygame.draw import rect

from config.managers.animation_data import DataAnimationCategory, DataAnimation, DataAnimationFrame
from scripts.core.event_manager import PyoneerEvent
from scripts.core.errors import PyoneerAssetMissingError


# takes in an individual animation sequence data, all sub animations within
class GameAnimation:
    """One named sequence ("walk_left") with its frames pre-sliced.

    Frames are cut from the spritesheet ONCE at construction into
    `self.surfaces`. Previously each frame was re-subsurfaced on demand and
    gated behind a self-consuming `_frame_changed` dirty flag, which is what
    made a switched-to animation render the previous animation's sprite: the
    flag had already been consumed, so nothing re-sliced. With the slices
    precomputed there is no dirty flag and no stale-frame failure mode.
    """

    def __init__(self, animation_data: DataAnimation = None,
                 spritesheet: Surface | None = None,
                 order: str = "left-to-right"):
        self.data = animation_data
        self.frames = animation_data.frames
        self.active = False
        self.current_frame = 0
        self.current_time = 0
        self.name = animation_data.name
        self.order = order
        self.surfaces: list[Surface] = []
        if spritesheet is not None:
            self.slice_frames(spritesheet)

    def frame_rect(self, index: int) -> Rect:
        """Source rect of one frame on the spritesheet."""
        data = self.frames[index]
        if self.order == "top-to-bottom":
            return Rect(data.x, data.y + index * data.height, data.width, data.height)
        # default, and the explicit "left-to-right" case
        return Rect(data.x + index * data.width, data.y, data.width, data.height)

    def slice_frames(self, spritesheet: Surface):
        """Cut every frame out of the sheet once, clipped to the sheet bounds."""
        self.surfaces = []
        sheet_rect = spritesheet.get_rect()
        for index in range(len(self.frames)):
            rect_ = self.frame_rect(index).clip(sheet_rect)
            if rect_.width <= 0 or rect_.height <= 0:
                raise ValueError(
                    f"animation {self.name!r} frame {index} at "
                    f"{self.frame_rect(index)} falls outside the spritesheet {sheet_rect}"
                )
            self.surfaces.append(spritesheet.subsurface(rect_))

    def image(self) -> Surface:
        return self.surfaces[self.current_frame]

    def set_frame(self, frame: int, time=0):
        self.current_frame = frame % max(1, len(self.surfaces))
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
            if self.current_frame >= self.data.frame_count:
                self.current_frame = 0
                if not self.data.loop:
                    self.active = False


# houses the entire structure for a series of animations based on a single set of prepared data
class GameAnimationHandler:
    """Owns one spritesheet and every sequence cut from it.

    Exactly one sequence is active at a time, tracked directly rather than
    rediscovered by scanning every sequence on each image() call.
    """

    DEFAULT_ANIMATION = 'idle_down'

    def __init__(self, animation_data: DataAnimationCategory):
        self._data = animation_data
        # convert_alpha() matches the sheet to the display's pixel format.
        # Without it every sprite blit takes SDL's per-pixel conversion path:
        # measured 36.3us vs 2.31us for a 44x64 sprite, a 15.7x penalty on the
        # single hottest operation in the entity render path. Subsurfaces
        # inherit the parent's format and cannot be converted individually,
        # so this must happen before any slicing.
        try:
            sheet = pygame.image.load(self._data.file)
        except FileNotFoundError as exc:
            # Say WHICH config key points at the missing file. A bare
            # FileNotFoundError on a relative path leaves the reader hunting
            # for whatever declared it.
            raise PyoneerAssetMissingError(
                "spritesheet", self._data.file, available=(),
                animation_category=self._data.name,
                declared_in="config/animations.json -> %s.file" % self._data.name,
                hint="the repository ships without art; see docs/ASSETS.md",
            ) from exc
        self._spritesheet: Surface = sheet.convert_alpha() if pygame.display.get_surface() else sheet
        self._animations: dict[str, GameAnimation] = {}
        self._name = animation_data.name
        self._active: GameAnimation | None = None
        self._paused: GameAnimation | None = None
        self._build_animations()
        self.start(self.DEFAULT_ANIMATION)

    def _build_animations(self):
        order = getattr(self._data, 'order', 'left-to-right')
        for sequence in self._data.sequences.values():
            self._animations[sequence.name] = GameAnimation(
                animation_data=sequence,
                spritesheet=self._spritesheet,
                order=order,
            )

    @property
    def active_animation(self) -> GameAnimation | None:
        return self._active

    def image(self) -> Surface | None:
        """Current frame, or None when nothing is playing.

        Returns None rather than a zero-size subsurface: a 0x0 surface is not
        a meaningful sprite and callers that blit it get an invisible entity
        with no indication why.
        """
        if self._active is None:
            return None
        return self._active.image()

    def start(self, name: str | None = None, from_beginning: bool = True):
        """Switch to `name`, restarting it from frame 0 by default.

        This used to set `active = True` on the target directly, bypassing
        GameAnimation.start(), so the frame counter and timer of the previous
        run were left in place and the sprite on screen did not change. The
        concrete symptom: releasing the movement keys called
        start('idle_down') and the player kept rendering the walk frame, for
        up to a full second, because idle_down's frame duration is 1000.
        """
        self.stop()
        if not name:
            return
        animation = self._animations.get(name)
        if animation is None:
            raise PyoneerAssetMissingError("animation", name,
                                          available=self._animations.keys(),
                                          category=self._name)
        animation.start(from_beginning=from_beginning)
        self._active = animation
        self._paused = None

    def stop(self, name: str | None = None):
        if name:
            animation = self._animations.get(name)
            if animation is not None:
                animation.stop()
                if self._active is animation:
                    self._active = None
        else:
            for animation in self._animations.values():
                animation.stop()
            self._active = None

    def pause(self):
        """Freeze the current sequence, remembering it so resume() can restore it."""
        if self._active is not None:
            self._paused = self._active
            self._active.stop(reset=False)

    def resume(self):
        """Resume the paused sequence at the exact frame it stopped on.

        This was a byte-for-byte copy of pause() and could never resume
        anything: both called stop(False), and the paused sequence was already
        unreachable because the lookup only ever returned *active* sequences.
        """
        if self._paused is not None:
            self._paused.start(from_beginning=False)
            self._active = self._paused
            self._paused = None

    def set_frame(self, frame: int):
        if self._active is not None:
            self._active.set_frame(frame)

    def get_animation(self, name):
        return self._animations[name]

    def update(self, event: Optional[PyoneerEvent] = None):
        if self._active is not None:
            self._active.update(event)

    def dispose(self):
        self._animations.clear()
        self._active = None
        self._paused = None

    def clear(self):
        self.dispose()