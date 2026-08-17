"""The controllable entity -- which is now the same class as an uncontrolled one.

WHAT LEFT THIS FILE, AND WHERE IT WENT
--------------------------------------
`input_move` used to be the whole top-down controller: it polled four verbs,
displaced the entity, and renamed the animation, in one function. That is
what made this class genre-specific -- not the name and not the sprite, but
the fact that those three jobs could not be separated, so a platformer needed
a different class.

They are now three behaviors, composed from data:

    player_input      scripts/game/behavior/input.py     polls, publishes intent
    topdown_move      scripts/game/behavior/movement.py  intent -> displacement
    animation_drive   scripts/game/behavior/movement.py  state  -> sequence name

A platformer player is THIS class with `platformer_move` in place of
`topdown_move`. There is deliberately no `GamePlatformerPlayer`, and adding
one would undo the point.

WHAT MAKES A PLAYER A PLAYER
----------------------------
Carrying `player_input`. Not the class, not a flag, and not who was handed an
`InputActionManager` -- holding a manager does nothing, reading one is what
moves an entity, and only that behavior reads it. This is what lets every
spawned `<object type="GamePlayer">` be handed the live manager while exactly
the one the map marked responds to a key.

WHAT DID NOT MOVE
-----------------
`PlayerState` and its three gates. `active` still short-circuits the whole
frame here; `enabled_inputs` and `can_move` are read by `player_input`, which
is the behavior they were always about. Deliberate consequence worth knowing:
clearing `can_move` mid-walk now returns the sprite to idle, where it used to
freeze mid-stride playing the walk cycle forever, because the movement
behavior keeps running and simply receives an empty intent.

THE ONE THING THAT DID CHANGE, MEASURED
---------------------------------------
Movement is arithmetically identical -- an A/B against the pre-extraction
tree, 55 frames through seven input phases, lands on the same pixel every
frame including sprint, diagonals and the left+right-cancels case.

The ANIMATION PHASE moved by one frame, and that is visible. `animation.start`
now runs from inside `core_frame_update` (behaviors) and therefore BEFORE
`GameAnimatedEntity`'s `animation.update`, where `input_move` used to run
after it. A sequence's clock is seeded at `delta` instead of 0 and stays one
engine frame ahead for the whole life of that sequence, so every rollover
boundary inside a held walk shows the next sprite one frame early:

    walk_right, before: [0,0,0,0,0, 1,1,1,1,1]
    walk_right, after:  [0,0,0,0,1, 1,1,1,1,2]

Measured at 9 of 55 frames, ~16% of frames during motion. `tools/smoke.py`
cannot see it and does not drift, because smoke injects no input and the
player never walks -- which is exactly why it is written down here instead.
The trade is deliberate: driving behaviors from `core_frame_update_post`
would fix the phase and move what the CAMERA sees, since `SceneManager`
updates the camera before the scene's frame update.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

import pygame

from config.managers.animation_data import DataAnimationCategory
from scripts.core.event_types import GameEventType
from scripts.core.event_manager import PyoneerEvent
from scripts.core.input import InputActionManager
from scripts.game.behavior import BEHAVIORS, build, read_requests
from scripts.game.entity.game_animation import GameAnimation, GameAnimationHandler
from scripts.game.entity.game_entity import GameEntity, GameAnimatedEntity
from scripts.game.entity.game_transform import Transform
from scripts.core.blitpool import BlitPool


class PlayerState:
    def __init__(self):
        self.can_move: bool = True
        self.enabled_inputs: bool = True
        self.active: bool = True

        self.moving: bool = False
        self.sprinting: bool = False
        self.move_direction: str = "none"
        self.last_direction: str = "none"


class GamePlayer(GameAnimatedEntity):

    def core_input_receive(self, events: list[pygame.event.Event] | pygame.event.Event):
        """Nothing, and that is the honest state rather than a missing feature.

        `SceneManager.inputs` calls this once per pyo-event for every bound
        object, so it looks like the player's input entry point and is not.
        Movement is POLLED, not event-driven: the `player_input` behavior asks
        `InputActionManager.held()` for each verb once per frame and publishes
        a `MoveIntent`, and a movement behavior turns that into displacement
        through `move_direction`/`allowed_move`, where the collision gate is.

        A rising-edge action (talk, use, open a menu) is what this method is
        for, and there is not one yet. `GameEventType.USE` is emitted exactly
        once in the whole engine and bound by nobody, which is the same hole
        seen from the other end.
        """
        return

    def __init__(self,
                 input_: InputActionManager=None,
                 movement_config=None,
                 world_transform=Transform(),
                 animation_config: DataAnimationCategory | None = None,
                 behaviors: str | Mapping[str, Any] | None = None):
        """`behaviors` is the same declaration a `<object>` carries, or None.

        Accepts either the raw `pyoneer_behaviors` string
        (`"player_input,topdown_move"`) or a full tmx-style property mapping,
        so a hand-built entity and a map-spawned one go through ONE reader --
        `scripts.game.behavior.read_requests` -- rather than two paths that
        will eventually disagree about what a token means.

        None composes nothing, and that is the default on purpose. A class
        default would say the class decides what an entity does, which is the
        shape this whole system exists to end, and it would collide with a map
        that declared its own list: `EntityBehaviors.attach` refuses a
        duplicate token, so a class default plus an authored list is a raise.

        NOTE that unlike `GameEntity`'s `transform` keyword -- which is
        accepted and silently DISCARDED, so every caller still has to
        `moveto()` afterwards -- this argument is actually used. It is
        asserted as an attachment, not as an argument, by
        tools/check_movement.py.
        """
        super().__init__(transform=world_transform,
                         movement_config=movement_config,
                         animation_config=animation_config)
        self.action_manager: InputActionManager = input_
        self.state: PlayerState = PlayerState()
        if not self.action_manager:
            self.state.enabled_inputs = False
        # After action_manager and state exist: `player_input.attach` reads
        # the manager to prove every verb it polls is bound, and reporting
        # "no manager" for a player that has one would be a lie about boot
        # order rather than about configuration.
        if behaviors:
            properties = (behaviors if isinstance(behaviors, Mapping)
                          else {BEHAVIORS: behaviors})
            self.behaviors.attach_all(build(read_requests(
                properties, where="%s()" % type(self).__name__)))

    def core_lifecycle_build(self, event: Optional[PyoneerEvent] = None):
        pass

    # core_image is inherited from GameAnimatedEntity; the override that used
    # to live here was identical apart from returning self._image directly
    # instead of going through super().

    def input_move(self, event: Optional[PyoneerEvent] = None):
        """Advance this player's composed behaviors by exactly one frame.

        Kept, with its name and signature, because it is a live entry point:
        `tools/check_input.py` drives a real player through it to prove the
        sprint binding is still consumed by something. It is now an alias for
        the drive rather than an implementation -- the poll, the displacement
        and the animation naming are three behaviors, and running them here
        runs all three in declared order.

        `core_frame_update` does NOT call this. It reaches the same drive
        through `super()` -> `GameEntity.core_frame_update`, and calling both
        would run every behavior twice per frame, which for a movement
        behavior means exactly double speed.
        """
        if event is None:
            return
        self.behaviors.update(event)

    def core_frame_update(self, event: Optional[PyoneerEvent] = None):
        if not self.state.active:
            # Still the whole-entity switch: an inactive player neither moves
            # nor animates. The two finer gates -- enabled_inputs, can_move --
            # live in the `player_input` behavior, because they are about
            # being steered rather than about being simulated.
            return
        # -> GameAnimatedEntity.core_frame_update -> GameEntity.core_frame_update
        #    -> self.behaviors.update(event), then the animation tick.
        super().core_frame_update(event)
