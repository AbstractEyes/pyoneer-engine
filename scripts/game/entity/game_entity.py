from __future__ import annotations

from abc import ABC
from typing import overload, Optional

import pygame
from pygame import rect, Surface

from config.managers.animation_data import DataAnimationCategory
from config.managers.entity_data import DataEntityMovement
from scripts.core.event_manager import PyoneerEvent

from scripts.core.blitpool import BlitPool
from scripts.core.collision_runtime import (CollisionField, DIRECTION_BITS,
                                            STEP, allowed_distance)
from scripts.game.entity.game_animation import GameAnimationHandler
from scripts.core.game_object import PyoneerGameObject
from scripts.game.behavior import EntityBehaviors
from scripts.game.behavior import state as behavior_state
from scripts.game.entity.game_transform import Transform
from pygame import Vector2


# A lightweight entity that contains only the most basic of data
class GameEntitySimple(PyoneerGameObject, ABC):

    def __init__(self,
                 transform: Transform = None,
                 position: tuple[int, int] = (0, 0),
                 rotation: float = 0,
                 scale: tuple[int, int] = (1, 1),
                 image_path: str = ""):
        super().__init__()
        self.transform: Transform = Transform(position=position, rotation=rotation, scale=scale)
        self._image = pygame.image.load(image_path) if len(image_path) > 0 else None

    def moveto(self, transform: Transform | tuple[float, float]):
        if isinstance(transform, tuple):
            self.transform.position = Vector2(transform)
        else:
            self.transform.copy(transform)


class GameEntity(GameEntitySimple, ABC):

    def __init__(self,
                 movement_config: dict[str, any] = None,
                 image_path: str = "",
                 transform: Transform = Transform()):
        super().__init__(image_path=image_path, transform=transform)
        movement = self.__movement_values(movement_config)
        self.move_speed = movement.get('move_speed', 16)
        self.sprint_mult = movement.get('sprint_mult', 2)
        self.__started = False
        self.__stopped = False

        self.collision_field: CollisionField | None = None
        """The baked passability this entity's movement is gated by.

        None means ungated, and that is the default: a map declaring no  #TAG:collision_field_ungated
        companion layer bakes None, so `move_direction` clamps nothing.

        `LayerRenderer` ASSIGNS this by both binding routes -- a sweep at the
        end of `__bind_map` for map-placed objects, `__bind_entity` for
        hand-built ones -- so a body is gated by the map it was bound on
        without anyone remembering to do it.
        """

        self.collision_offset: tuple[float, float] = (0.0, 0.0)
        """Where this entity's collision point sits inside its sprite.

        `transform.position` is the sprite's TOP-LEFT -- `EntityLayer`
        blits with `get_rect(topleft=position)` -- so (0, 0) tests the
        top-left pixel, and the top-left of a 32px-tall character is its
        head. A game that wants feet sets this to roughly (width/2,
        height - 1) per entity.

        Not derived from the sprite: it may be None at construction, and a
        default that read the image would move an entity's collision point the
        day its spritesheet gained a row.
        """

        self.behaviors: EntityBehaviors = EntityBehaviors(self)
        """Behavior components composed onto this entity, in declared order.

        Empty by default and therefore frame-neutral: `core_frame_update`
        iterates nothing until something attaches. Populated from a tmx
        object's `pyoneer_behaviors` property via
        `scripts.game.behavior.read_requests` + `build`; see docs/BEHAVIORS.md.
        What an entity DOES lives here, not in a subclass.
        """

    @staticmethod
    def __movement_values(movement_config: dict[str, any] | None) -> dict[str, any]:
        """Accept either the entity block or the movement block itself.

        config/entity.json nests movement under a "movement" key, while
        callers such as main.py pass the whole entity block. Looking only at
        the top level would silently fall back to the defaults and leave the
        configured numbers dead.
        """
        if not movement_config:
            return {}
        if 'movement' in movement_config:
            return movement_config['movement'] or {}
        return movement_config

    @property
    def started(self) -> bool:
        return self.__started

    @property
    def stopped(self) -> bool:
        return self.__stopped

    def start(self):
        self.__started = True

    def stop(self):
        self.__stopped = True

    def core_lifecycle_prepare_pre(self, event: Optional[PyoneerEvent] = None):
        pass

    def core_lifecycle_prepare(self, event: Optional[PyoneerEvent] = None) -> Surface:
        pass

    def core_frame_update(self, event: Optional[PyoneerEvent] = None):
        # The per-frame drive for composed behaviors, and a no-op while the
        # set is empty. GameAnimatedEntity and GamePlayer both call super()
        # FIRST, so behaviors run before the animation update and a position
        # written here is the one the animation and the collision gate see
        # this frame. Moving the call to core_frame_update_post would change
        # what the CAMERA sees, since SceneManager updates the camera BEFORE
        # the scene's frame update.
        self.behaviors.update(event)

    def core_lifecycle_dispose(self, event: Optional[PyoneerEvent] = None):
        pass

    def rotate(self, angle: float):
        self.transform.rotation += angle

    def collision_point(self) -> tuple[float, float]:
        """The single pixel this entity's movement is tested at."""
        offset_x, offset_y = self.collision_offset
        return (self.transform.position.x + offset_x,
                self.transform.position.y + offset_y)

    # -- support, which is one fact with two spellings -----------------------
    #
    # `grounded` and `coyote_left` are ALIASES over `BodyState`'s `support`
    # and `support_grace` axes, never a second copy: `entity.grounded = True`
    # and `state.support = SUPPORT_GROUNDED` are the same write.

    @property
    def grounded(self) -> bool:
        """Whether something is holding this body up. `state.support`.

        Raises `AttributeError` for an entity carrying no `BodyState`, so
        `getattr(entity, "grounded", default)` answers `default` for a body
        that was never given one. Every COMPOSED body carries a record, so
        that fallback is reachable only for a bare entity with no behaviors.
        """
        found = behavior_state.state_of(self)
        if found is None:
            raise AttributeError(
                "%s carries no BodyState, so it has no support to report. A "
                "movement behavior allocates one in attach()."
                % type(self).__name__)
        return found.support == behavior_state.SUPPORT_GROUNDED

    @grounded.setter
    def grounded(self, value: bool) -> None:
        behavior_state.ensure_state(self).support = (
            behavior_state.SUPPORT_GROUNDED if value
            else behavior_state.SUPPORT_AIRBORNE)

    @property
    def coyote_left(self) -> float:
        """Milliseconds of remaining support grace. `state.support_grace`."""
        found = behavior_state.state_of(self)
        if found is None:
            raise AttributeError(
                "%s carries no BodyState, so it has no support grace."
                % type(self).__name__)
        return found.support_grace

    @coyote_left.setter
    def coyote_left(self, value: float) -> None:
        behavior_state.ensure_state(self).support_grace = float(value)

    def allowed_move(self, wanted: Vector2, direction: str) -> Vector2:
        """`wanted` as far as the map allows, which is `wanted` when ungated.

        Returns the ARGUMENT ITSELF when nothing clamps it, so an unclamped
        gate is incapable of changing anything. The CLAMPED path rebuilds the
        vector by PROJECTING onto the direction axis, so a caller handing in a
        vector that is not axis-aligned loses its other component -- that is
        outside this method's contract, and the unclamped path avoids it
        entirely.

        A direction this vocabulary does not know is passed through UNCLAMPED
        rather than raising, matching `move_direction`, which accepts any
        string and moves zero pixels for one it does not know.
        """
        field = self.collision_field
        bit = DIRECTION_BITS.get(direction)
        if field is None or bit is None:
            return wanted
        step_x, step_y = STEP[bit]
        # The signed magnitude along the direction. This dot product is exact
        # in floating point, because the step's factors are 0 and +/-1.
        distance = wanted.x * step_x + wanted.y * step_y
        pixel_x, pixel_y = self.collision_point()
        allowed = allowed_distance(field, pixel_x, pixel_y, bit, distance)
        if allowed >= distance:
            return wanted
        return Vector2(step_x * allowed, step_y * allowed)

    def move_direction(self, delta: float, direction: str, sprint: bool = False):
        changes = Transform()
        if direction == "left":
            changes.position.x += -1 * self.move_speed * delta
        elif direction == "right":
            changes.position.x += 1 * self.move_speed * delta
        elif direction == "up":
            changes.position.y += -1 * self.move_speed * delta
        elif direction == "down":
            changes.position.y += 1 * self.move_speed * delta
        if sprint:
            changes.position *= self.sprint_mult
        # += rather than a rebind: the position Vector2 is handed out by
        # `Transform.position` and mutated in place everywhere else in this
        # file, and replacing the object would break any holder of it.
        self.transform.position += self.allowed_move(changes.position, direction)


# the animated entity, is a type of entity that contains the potential for animation
class GameAnimatedEntity(GameEntity):

    def __init__(self,
                 movement_config: DataEntityMovement = None,
                 animation_config: DataAnimationCategory = None,
                 transform: Transform = Transform()):
        super().__init__(
            movement_config=movement_config,
            transform=transform)
        self.animation_data = animation_config
        self.animation: GameAnimationHandler = GameAnimationHandler(self.animation_data)
        self.__started: bool = False
        self.__stopped: bool = False

    @property
    def image(self) -> Surface | None:
        """Current animation frame, falling back to the static image.

        May return None when no animation is playing and no static image was
        set; the render path skips entities with no image rather than
        blitting a placeholder.
        """
        if self.animation is not None:
            frame = self.animation.image()
            if frame is not None:
                return frame
        return self._image

    def core_frame_update(self, event: Optional[PyoneerEvent] = None):
        super().core_frame_update(event)
        if self.animation:
            self.animation.update(event)