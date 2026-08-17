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
The three gates. `simulated` (was `active`) still short-circuits the whole
frame here; `enabled_inputs` and `steerable` (was `can_move`) are read by
`player_input`, which is the behavior they were always about. Deliberate
consequence worth knowing: clearing `steerable` mid-walk now returns the
sprite to idle, where it used to freeze mid-stride playing the walk cycle
forever, because the movement behavior keeps running and simply receives an
empty intent.

WHAT DID MOVE: THE STATE RECORD, TO WHERE THE BEHAVIORS ARE
------------------------------------------------------------
`PlayerState` is now the name of `scripts.game.behavior.state.BodyState`,
which is the shared vocabulary the movement behaviors, the animator, the
action gates and anything narrative read. Every old field name survives as a
property over an axis, so no caller in this file, in `main.py`, in `demos/`
or in the eight checks that name them had to move. The one addition visible
here is `input_bound`; see `__init__`.

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
from scripts.game.behavior.state import BodyState
from scripts.game.entity.game_animation import GameAnimation, GameAnimationHandler
from scripts.game.entity.game_entity import GameEntity, GameAnimatedEntity
from scripts.game.entity.game_transform import Transform
from scripts.core.blitpool import BlitPool


PlayerState = BodyState
"""What this class used to be, kept as the name eight files already import.

`PlayerState` was seven fields on the player, four of which had exactly one
reader -- `animation_drive` -- so it was never a shared record: it was a
private channel between two movement behaviors and the animator, spelled as
an entity attribute. `BodyState`
(`scripts/game/behavior/state.py`) is the same record designed for a reader
that has not been written yet, and it keeps every one of those seven names as
a property over an axis, so nothing that says `state.can_move` or
`state.last_direction` had to move.

It is an ALIAS and not a subclass, deliberately: a subclass would be a second
type that `isinstance` checks could disagree about, and `state_of` decides
what counts as a body state in one place.

The record lives under `scripts/game/behavior/` rather than here for the same
reason `MoveIntent` and `ActionIntent` do -- it is the vocabulary behaviors
pass between themselves, and a player is only one of the things that carries
one.
"""


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
        self.state: BodyState = BodyState()
        self.state.input_bound = input_ is not None
        # This line used to read `if not self.action_manager:
        # self.state.enabled_inputs = False`, and that conflated two different
        # questions in one bit: "this entity has no input manager" and "a
        # dialogue box has taken input away". A narrative system toggling the
        # flag could not tell whether it was RESTORING input or GRANTING it to
        # an entity that never had any, and `demos/behaviors.py` carries a
        # written workaround for exactly that ambiguity. `input_bound` is the
        # wiring answer, set once here; `enabled_inputs` is left alone and is
        # now only ever the authored gate.
        #
        # Behavior-neutral, and the reason is worth having in writing:
        # `player_input.update` and every action behavior return on
        # `manager is None` BEFORE they reach the state gate, so no entity
        # that was affected by the old clearing ever consulted the flag.
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
        if not self.state.simulated:
            # Still the whole-entity switch, under the name that says what it
            # does: an unsimulated player neither moves nor animates -- it
            # returns before `super()`, so the animation clock stops too
            # (measured: five frames left `current_time` at 0.000). The finer
            # gates -- `input_bound`, `enabled_inputs`, `steerable` -- live in
            # the `player_input` behavior, because they are about being
            # steered rather than about being simulated.
            #
            # It is NOT a world pause and must not be reached for as one: it
            # is per-entity, there is no scene-level equivalent in this engine,
            # and nothing in production writes it.
            return
        # -> GameAnimatedEntity.core_frame_update -> GameEntity.core_frame_update
        #    -> self.behaviors.update(event), then the animation tick.
        super().core_frame_update(event)
