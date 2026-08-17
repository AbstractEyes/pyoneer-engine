"""How a body answers an intent: the two movement behaviors and the animator.

WHAT MOVED HERE, AND WHY IT IS A MOVE AND NOT A REWRITE
--------------------------------------------------------
`GamePlayer.input_move` was three jobs in one function: poll four verbs,
displace the entity, and rename the animation. That is precisely what made
the controller top-down -- not the class, not the sprite, but the fact that
the verb vocabulary, the displacement rule and the sequence naming could not
be separated. A platformer needed a different class because it could not
reuse any third of it.

`topdown_move` below is `input_move`'s middle third, verbatim: the same four
verbs in the same order, calling the same `GameEntity.move_direction` with
the same arguments, so `move_speed`, `sprint_mult` and the collision gate are
untouched arithmetic. `animation_drive` is its last third. The poll is in
`input.py`. Nothing about the demo's motion changes; what changes is that a
platformer can now swap the middle third out.

WHY topdown_move DECLARES NO move_speed PARAMETER
--------------------------------------------------
It reads `entity.move_speed`, which `GameEntity` already resolves from
`config/entity.json`. Declaring a parameter for it would give one number two
homes -- the config file and the behavior default -- and whichever one a
reader edited, the other would eventually win. The platformer body below
DOES declare speed parameters, because it does not go through
`move_direction` at all: it integrates a velocity, and its numbers are the
actors table's own columns, in the actors table's own units.

THE TWO UNIT SYSTEMS, WHICH ARE REAL AND MUST NOT BE MERGED BY HAND
-------------------------------------------------------------------
`event.data["delta"]` is NOT seconds. `main.py` computes it as
`(now_ms - then_ms) / target_tick_rate`, and `config/game.json` sets
`target_tick_rate` to 60 -- so delta is milliseconds/60, about 0.278 at
60fps, roughly 16.7x a second's worth.

  * `topdown_move` multiplies `move_speed` by delta RAW, because that is what
    `move_direction` has always done and `config/entity.json`'s `move_speed`
    of 20 is calibrated in those units. Changing it would move the demo.
  * `platformer_move` converts, because `editor/genres/platformer/RULES.md`
    says speeds are per second and durations end `_ms`, and the actors table
    is written that way: `gravity` 900 means 900 px/s^2. Used raw it would be
    ~16.7x wrong in the direction that still looks like it works.

`tools/check_movement.py` asserts `MS_PER_DELTA` against the config file, so
retuning the tick rate turns the check red instead of silently retuning
gravity.

SCREEN SPACE IS Y-DOWN
----------------------
Up is negative y. `jump_velocity` is stored POSITIVE in the actors table and
negated at the instant of use, exactly as platformer/RULES.md specifies, so a
designer reading the table is not doing sign arithmetic in their head.
"""
from __future__ import annotations

from typing import Any

from pygame import Vector2

from scripts.game.behavior.base import (BehaviorParam, BehaviorSpec,
                                        EntityBehavior)
from scripts.game.behavior.input import intent_of

MS_PER_DELTA: float = 60.0
"""Milliseconds in one unit of `event.data["delta"]`.

`main.py`: `delta_time = (current_time - self._prev_time) / self._tick_rate`,
and `_tick_rate` is `config/game.json -> target_tick_rate`. So one delta unit
is `target_tick_rate` milliseconds. This is the only place that number is
written down for a behavior to use, and `tools/check_movement.py` reads the
config and fails if the two ever disagree.
"""

SECONDS_PER_DELTA: float = MS_PER_DELTA / 1000.0
"""Seconds in one unit of delta -- 0.06. Derived, never typed twice."""

TOPDOWN_VERBS: tuple[str, ...] = ("up", "down", "left", "right")
"""The four verbs, in the order `GamePlayer.input_move` polled them.

THE ORDER IS LOAD-BEARING, in exactly one way: every held verb produces its
own move, but the LAST one held decides `state.move_direction`, and therefore
which walk animation plays. Holding up and right walks diagonally and faces
right. Reversing this tuple would leave every displacement identical and
change which sprite the player sees, which is the kind of difference that
gets attributed to the art.
"""


class GameTopDownMoveBehavior(EntityBehavior):
    """Eight-direction axis-aligned movement -- the demo's controller, moved.

    Each held verb is applied as its own call to `GameEntity.move_direction`,
    so each one is gated separately by `collision_runtime.allowed_distance`.
    That is not an accident of the original code worth cleaning up: with a
    wall to the left, holding left+right must travel right, and a single
    combined vector would travel nowhere.

    Takes no parameters. `move_speed` and `sprint_mult` are the entity's,
    resolved from `config/entity.json` by `GameEntity.__init__` -- see the
    module docstring for why this behavior does not offer a second home for
    them.
    """

    def update(self, entity: Any, event: Any) -> None:
        if event is None:
            return
        delta = event.data["delta"]
        intent = intent_of(entity)
        sprint = intent.sprint
        moving = False
        direction = "none"
        for verb in TOPDOWN_VERBS:
            if not getattr(intent, verb):
                continue
            moving = True
            direction = verb
            entity.move_direction(delta, verb, sprint=sprint)
        state = getattr(entity, "state", None)
        if state is None:
            # A bare GameEntity has no PlayerState. It still moves; it simply
            # has nowhere to record what it did, and the animation behavior
            # has nothing to read. Both are honest for a pushed crate.
            return
        state.moving = moving
        state.move_direction = direction
        if moving:
            state.last_direction = direction


class GamePlatformerMoveBehavior(EntityBehavior):
    """A side-on body: gravity, a jump with coyote time, and air control.

    Velocity, grounded and the coyote clock live on the ENTITY, not on this
    object, so a sibling behavior (an animator wanting an airborne sequence, a
    damage behavior wanting fall speed) can read them without reaching into
    another behavior's internals. They are allocated in `attach`, which runs
    exactly once -- unlike `core_lifecycle_prepare`, which `GameScene.begin`
    calls a second time on every bound object.

    Resolution is axis by axis, horizontal first, as platformer/RULES.md
    prescribes, and each axis goes through `GameEntity.allowed_move` -- the
    same gate `move_direction` uses, reached through the same method rather
    than through a second copy of the boundary walk.

    WHAT THE COLLISION VOCABULARY CANNOT DO FOR THIS BODY, stated here so it
    is not discovered mid-level-design: blocking is per-cell and SYMMETRIC
    (`collision_runtime.CollisionField.can_move`), so a one-way platform --
    fall through it, land on top of it -- is not expressible. And an entity
    whose `collision_field` is None is UNGATED: it accelerates downward
    forever and never lands, which is the correct outcome for a body with
    no world to stand on and looks exactly like a physics bug. Nothing in
    production assigns `collision_field` yet.
    """

    def __init__(self,
                 move_speed: float = 120.0,
                 jump_velocity: float = 320.0,
                 gravity: float = 900.0,
                 max_fall_speed: float = 600.0,
                 air_control: float = 0.6,
                 coyote_ms: int = 90):
        self.move_speed = move_speed
        self.jump_velocity = jump_velocity
        self.gravity = gravity
        self.max_fall_speed = max_fall_speed
        self.air_control = air_control
        self.coyote_ms = coyote_ms

    def attach(self, entity: Any) -> None:
        entity.velocity = Vector2(0.0, 0.0)
        entity.grounded = False
        entity.coyote_left = 0.0

    def update(self, entity: Any, event: Any) -> None:
        if event is None:
            return
        delta = event.data["delta"]
        seconds = delta * SECONDS_PER_DELTA
        milliseconds = delta * MS_PER_DELTA
        intent = intent_of(entity)
        velocity = entity.velocity

        # 1. The coyote window. It is REFILLED while standing, and only counts
        #    down while airborne, so "how long since I left the ground" needs
        #    no separate timestamp and cannot drift out of step with grounded.
        if entity.grounded:
            entity.coyote_left = float(self.coyote_ms)
        else:
            entity.coyote_left = max(0.0, entity.coyote_left - milliseconds)

        # 2. The jump, read BEFORE gravity so a jump on the landing frame is
        #    not cancelled by the same frame's downward acceleration.
        #    Spending the window is what makes a second jump impossible: after
        #    this, grounded is False and coyote_left is 0 until something
        #    lands, and both of those are the only two ways in.
        if intent.jump and (entity.grounded or entity.coyote_left > 0.0):
            velocity.y = -self.jump_velocity      # y-down: negate at use
            entity.grounded = False
            entity.coyote_left = 0.0

        # 3. Horizontal, resolved first.
        control = 1.0 if entity.grounded else self.air_control
        velocity.x = intent.x * self.move_speed * control
        step_x = velocity.x * seconds
        if step_x:
            direction = "right" if step_x > 0.0 else "left"
            allowed = entity.allowed_move(Vector2(step_x, 0.0), direction)
            entity.transform.position += allowed
            if abs(allowed.x) < abs(step_x):
                velocity.x = 0.0

        # 4. Gravity, then the vertical resolve. `grounded` is recomputed from
        #    scratch every frame rather than remembered: an entity standing on
        #    a tile that was repainted mid-session must fall, and a flag that
        #    is only ever cleared by an event is a flag that eventually sticks.
        velocity.y = min(velocity.y + self.gravity * seconds,
                         self.max_fall_speed)
        step_y = velocity.y * seconds
        entity.grounded = False
        if step_y:
            direction = "down" if step_y > 0.0 else "up"
            allowed = entity.allowed_move(Vector2(0.0, step_y), direction)
            entity.transform.position += allowed
            if abs(allowed.y) < abs(step_y):
                # Something refused the step. Downward that is a floor and the
                # body has landed; upward it is a ceiling and the jump ends.
                velocity.y = 0.0
                entity.grounded = step_y > 0.0

        # 5. What the animator reads. A side-on body faces left or right and
        #    nothing else, so `walk_up` is never named -- which matters,
        #    because GameAnimationHandler.start RAISES for a sequence a sheet
        #    does not have, unlike move_direction which silently moves zero.
        state = getattr(entity, "state", None)
        if state is None:
            return
        horizontal = intent.x
        direction = "right" if horizontal > 0 else ("left" if horizontal < 0
                                                    else "none")
        state.moving = horizontal != 0
        state.move_direction = direction
        if state.moving:
            state.last_direction = direction


class GameAnimationDriveBehavior(EntityBehavior):
    """Name the animation from the movement state, on the frame it changes.

    The last third of `input_move`, with the two format strings and the
    opening sequence lifted out of the code and into parameters -- which is
    the whole point, because a platformer's sheet says `run_right` where a
    top-down sheet says `walk_right`, and that difference used to require a
    different class.

    It remembers what it saw rather than re-reading the entity's previous
    state, because by the time it runs the movement behavior has already
    overwritten it. The comparison is otherwise identical to the one
    `input_move` made against locals captured at its own top.

    `GameAnimationHandler.start` RAISES for a sequence it does not know. That
    is the loud half of a matched pair -- `move_direction` silently moves zero
    for a direction it does not know -- so a behavior list that changes the
    direction vocabulary MUST change the naming with it, and this is the
    parameter that does it.
    """

    def __init__(self,
                 walk_format: str = "walk_{}",
                 idle_format: str = "idle_{}",
                 initial_sequence: str = "idle_down"):
        self.walk_format = walk_format
        self.idle_format = idle_format
        self.initial_sequence = initial_sequence
        self._last_moving = False
        self._last_direction = "none"

    def attach(self, entity: Any) -> None:
        """Start the opening sequence, which used to be hardcoded in GamePlayer.

        `PlayerState` starts at moving=False, move_direction="none", so the
        remembered pair below matches a fresh entity exactly and the first
        frame is a no-change -- the same no-change `input_move` produced on
        its first frame, which is what keeps this swap frame-neutral.
        """
        animation = getattr(entity, "animation", None)
        if animation is not None and self.initial_sequence:
            animation.start(self.initial_sequence)

    def update(self, entity: Any, event: Any) -> None:
        state = getattr(entity, "state", None)
        animation = getattr(entity, "animation", None)
        if state is None or animation is None:
            return
        moving = state.moving
        direction = state.move_direction
        if moving == self._last_moving and direction == self._last_direction:
            return
        self._last_moving = moving
        self._last_direction = direction
        if moving:
            animation.start(self.walk_format.format(direction))
        else:
            animation.start(self.idle_format.format(state.last_direction))


# ---------------------------------------------------------------------------
# The declarations
#
# Registered by `registry.py`'s table, which is the one place that says which
# token means which of these. The specs live beside the classes so a parameter
# and the constructor keyword it fills are visible in one screen -- `build`
# calls `factory(**values)`, so a drift between them is a TypeError the first
# time an object is spawned, and `tools/check_movement.py` catches it before
# that by comparing the declared keys against the real signature.
# ---------------------------------------------------------------------------

TOPDOWN_MOVE = BehaviorSpec(
    name="topdown_move",
    summary="Eight-direction axis-aligned movement, each held verb gated "
            "separately. The demo's controller.",
    factory=GameTopDownMoveBehavior,
    writes=("transform.position", "state.moving", "state.move_direction",
            "state.last_direction"),
    requires=("move_direction", "transform"),
    conflicts=("platformer_move",),
    order=20,
    genres=("topdown_rpg",),
    example='<property name="pyoneer_behaviors" '
            'value="player_input,topdown_move,animation_drive"/>',
)

PLATFORMER_MOVE = BehaviorSpec(
    name="platformer_move",
    summary="A side-on body: gravity, terminal velocity, air control and a "
            "jump with coyote time. Reads the actors table's own columns.",
    factory=GamePlatformerMoveBehavior,
    params=(
        BehaviorParam("move_speed", "move speed", "float", 120.0,
                      "Horizontal pixels per SECOND at full run.",
                      source="actors"),
        BehaviorParam("jump_velocity", "jump velocity", "float", 320.0,
                      "Upward pixels per second at the instant of jump. "
                      "Stored POSITIVE and negated at use; screen space is "
                      "y-down.", source="actors"),
        BehaviorParam("gravity", "gravity", "float", 900.0,
                      "Downward pixels per second squared. Per-actor, so a "
                      "floaty boss is data and not a special case.",
                      source="actors"),
        BehaviorParam("max_fall_speed", "max fall speed", "float", 600.0,
                      "Terminal velocity, so nothing tunnels through a floor.",
                      source="actors"),
        BehaviorParam("air_control", "air control", "float", 0.6,
                      "Fraction of ground speed usable mid-air, 0 to 1.",
                      source="actors"),
        BehaviorParam("coyote_ms", "coyote time", "int", 90,
                      "Milliseconds after leaving a ledge during which a jump "
                      "still counts. 0 for strict.", source="actors"),
    ),
    writes=("transform.position", "velocity", "grounded", "coyote_left",
            "state.moving", "state.move_direction", "state.last_direction"),
    requires=("allowed_move", "transform"),
    conflicts=("topdown_move",),
    order=20,
    genres=("platformer",),
    example='<property name="pyoneer_behaviors" '
            'value="player_input,platformer_move,animation_drive"/>\n'
            '<property name="pyoneer_param_jump_verb" value="jump"/>\n'
            '<property name="pyoneer_param_gravity" type="float" value="900"/>',
)

ANIMATION_DRIVE = BehaviorSpec(
    name="animation_drive",
    summary="Names the animation from the movement state, on the frame it "
            "changes. The sequence naming is parameters, not code.",
    factory=GameAnimationDriveBehavior,
    params=(
        BehaviorParam("walk_format", "walk sequence", "str", "walk_{}",
                      "Format string for the moving sequence; {} is the "
                      "direction. A platformer sheet may want 'run_{}'.",
                      source="object"),
        BehaviorParam("idle_format", "idle sequence", "str", "idle_{}",
                      "Format string for the stopped sequence; {} is the last "
                      "direction moved.", source="object"),
        BehaviorParam("initial_sequence", "opening sequence", "str",
                      "idle_down",
                      "Played once at attach. A side-on body wants "
                      "'idle_right'; empty leaves whatever the handler "
                      "started.", source="object"),
    ),
    writes=("animation",),
    requires=("animation", "state"),
    order=80,
    example='<property name="pyoneer_param_walk_format" value="run_{}"/>',
)

__all__ = ["ANIMATION_DRIVE", "MS_PER_DELTA", "PLATFORMER_MOVE",
           "SECONDS_PER_DELTA", "TOPDOWN_MOVE", "TOPDOWN_VERBS",
           "GameAnimationDriveBehavior", "GamePlatformerMoveBehavior",
           "GameTopDownMoveBehavior"]
