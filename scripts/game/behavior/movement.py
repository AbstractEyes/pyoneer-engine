"""How a body answers an intent: the two movement behaviors and the animator.

`player_input` (in `input.py`) polls and publishes a `MoveIntent`; a movement
behavior here reads it and displaces the body; `animation_drive` names the
sequence from what the body ended up being. The three pass `state.phase` and
`state.facing` between them, on the shared `BodyState`.

WHY topdown_move DECLARES NO move_speed PARAMETER
--------------------------------------------------
It reads `entity.move_speed`, which `GameEntity` already resolves from
`config/entity.json`; a parameter would give one number two homes.
`platformer_move` DOES declare speed parameters, because it never goes
through `move_direction`: it integrates a velocity, in the actors table's own
columns and units.

THE TWO UNIT SYSTEMS, WHICH MUST NOT BE MERGED BY HAND
------------------------------------------------------
`event.data["delta"]` is NOT seconds. `main.py` computes it as
`(now_ms - then_ms) / target_tick_rate`, and `config/game.json` sets
`target_tick_rate` to 60 -- so delta is milliseconds/60, about 0.278 at
60fps, roughly 16.7x a second's worth.

  * `topdown_move` multiplies `move_speed` by delta RAW, matching what
    `move_direction` has always done and how `config/entity.json`'s
    `move_speed` of 20 is calibrated.
  * `platformer_move` CONVERTS, because `editor/genres/platformer/RULES.md`
    and the actors table are written per second: `gravity` 900 means
    900 px/s^2. Used raw it is ~16.7x wrong in the direction that still looks
    like it works.

`tools/check_movement.py` asserts `MS_PER_DELTA` against the config file, so
retuning the tick rate turns the check red instead of silently retuning
gravity.

SCREEN SPACE IS Y-DOWN
----------------------
Up is negative y. `jump_velocity` is stored POSITIVE in the actors table and
negated at the instant of use, as platformer/RULES.md specifies, so a
designer reading the table does no sign arithmetic.

FACING IS NOT DISPLACEMENT
--------------------------
`state.facing` is an open token that names a sprite row; `move_direction`
takes one of the four keys of `DIRECTION_BITS` and passes an unknown one
through the collision gate unclamped. They are separate vocabularies and one
must never be handed to the other.
"""
from __future__ import annotations

from typing import Any

from pygame import Vector2

from scripts.game.behavior.base import (BehaviorParam, BehaviorSpec,
                                        EntityBehavior)
from scripts.game.behavior.input import intent_of
from scripts.game.behavior.state import (FACING_DEFAULT, PHASE_IDLE,
                                         PHASE_MOVING, SUPPORT_AIRBORNE,
                                         SUPPORT_GROUNDED, ensure_state,
                                         state_of)

MS_PER_DELTA: float = 60.0
"""Milliseconds in one unit of `event.data["delta"]`.

`main.py` divides the elapsed milliseconds by `config/game.json ->
target_tick_rate`, so one delta unit is that many milliseconds. The only
place the number is written down for a behavior to use;
`tools/check_movement.py` fails if it and the config disagree.
"""

SECONDS_PER_DELTA: float = MS_PER_DELTA / 1000.0
"""Seconds in one unit of delta -- 0.06. Derived, never typed twice."""

TOPDOWN_VERBS: tuple[str, ...] = ("up", "down", "left", "right")
"""The four verbs, in the order `topdown_move` polls them.

THE ORDER IS LOAD-BEARING, in exactly one way: every held verb produces its
own move, but the LAST one held decides `state.facing` and therefore which
walk animation plays. Holding up and right walks diagonally and faces right.
Reversing this tuple leaves every displacement identical and changes which
sprite the player sees.

These four are also the DISPLACEMENT vocabulary -- the keys of
`collision_runtime.DIRECTION_BITS`, and the only strings
`GameEntity.move_direction` acts on. `state.facing` is written FROM one of
them and is not the same axis: facing may widen to eight tokens on its own,
but widening this tuple without widening `DIRECTION_BITS` sends an unknown
key straight through the collision gate unclamped.
"""


class GameTopDownMoveBehavior(EntityBehavior):
    """Eight-direction axis-aligned movement -- the demo's controller.

    Each held verb is applied as its own call to `GameEntity.move_direction`,
    so each is gated separately by `collision_runtime.allowed_distance`: with
    a wall to the left, holding left+right travels right, where a single
    combined vector would travel nowhere.

    Takes no parameters. `move_speed` and `sprint_mult` are the entity's,
    resolved from `config/entity.json` by `GameEntity.__init__`.
    """

    def attach(self, entity: Any) -> None:
        """Allocate the state record this behavior publishes into.

        Whoever writes a record allocates it, so no entity class has to know
        which behaviors it might one day carry.
        """
        ensure_state(entity)

    def update(self, entity: Any, event: Any) -> None:
        if event is None:
            return
        delta = event.data["delta"]
        intent = intent_of(entity)
        sprint = intent.sprint
        moving = False
        direction = ""
        for verb in TOPDOWN_VERBS:
            if not getattr(intent, verb):
                continue
            moving = True
            direction = verb
            entity.move_direction(delta, verb, sprint=sprint)
        state = state_of(entity)
        if state is None:
            # `attach` allocates one, so this is the hand-constructed path: a
            # behavior driven without attaching, or an entity whose `state`
            # slot was cleared. It still moves, with nowhere to record what it
            # did and nothing for the animator to read.
            return
        state.phase = PHASE_MOVING if moving else PHASE_IDLE
        if moving:
            # Written only while moving, so `facing` persists through the stop
            # and the idle sequence still has a direction to name.
            state.facing = direction


class GamePlatformerMoveBehavior(EntityBehavior):
    """A side-on body: gravity, a jump with coyote time, and air control.

    Support and the coyote clock live on the shared `BodyState` as
    `state.support` and `state.support_grace`, so a sibling behavior -- an
    animator wanting an airborne sequence, a damage behavior wanting fall
    speed -- can read them. `entity.grounded` and `entity.coyote_left` are
    aliases over those axes: one home, two spellings.

    Velocity stays on the entity: it is a side-on INTEGRATION variable, not a
    state another genre can read.

    Resolution is axis by axis, horizontal first, as platformer/RULES.md
    prescribes, and each axis goes through `GameEntity.allowed_move` -- the
    same gate `move_direction` uses.

    TWO LIMITS OF THE COLLISION VOCABULARY, worth knowing before level design:
    blocking is per-cell and SYMMETRIC
    (`collision_runtime.CollisionField.can_move`), so a one-way platform is
    not expressible; and an entity whose `collision_field` is None is UNGATED,
    so it accelerates downward forever and never lands. `LayerRenderer`
    assigns the field at bind, so None means the MAP declared no passability
    layer rather than a missing wire.
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
        state = ensure_state(entity)
        entity.velocity = Vector2(0.0, 0.0)
        # Written explicitly rather than left to the record's defaults:
        # `BodyState` starts SUPPORT_GROUNDED, because a body with no gravity
        # model IS supported, and a side-on body must declare itself
        # unsupported until the field says otherwise.
        state.support = SUPPORT_AIRBORNE
        state.support_grace = 0.0

    def update(self, entity: Any, event: Any) -> None:
        if event is None:
            return
        delta = event.data["delta"]
        seconds = delta * SECONDS_PER_DELTA
        milliseconds = delta * MS_PER_DELTA
        intent = intent_of(entity)
        velocity = entity.velocity
        # `ensure_state`, not `state_of`: this body's physics cannot run
        # without somewhere to keep its support.
        state = ensure_state(entity)
        grounded = state.support == SUPPORT_GROUNDED

        # 1. The coyote window. It is REFILLED while standing, and only counts
        #    down while airborne, so "how long since I left the ground" needs
        #    no separate timestamp and cannot drift out of step with support.
        if grounded:
            state.support_grace = float(self.coyote_ms)
        else:
            state.support_grace = max(0.0, state.support_grace - milliseconds)

        # 2. The jump, read BEFORE gravity so a jump on the landing frame is
        #    not cancelled by the same frame's downward acceleration.
        #    Spending the window is what makes a second jump impossible: after
        #    this, support is airborne and the grace is 0 until something
        #    lands, and both of those are the only two ways in.
        if intent.jump and (grounded or state.support_grace > 0.0):
            velocity.y = -self.jump_velocity      # y-down: negate at use
            grounded = False
            state.support = SUPPORT_AIRBORNE
            state.support_grace = 0.0

        # 3. Horizontal, resolved first.
        control = 1.0 if grounded else self.air_control
        velocity.x = intent.x * self.move_speed * control
        step_x = velocity.x * seconds
        if step_x:
            direction = "right" if step_x > 0.0 else "left"
            allowed = entity.allowed_move(Vector2(step_x, 0.0), direction)
            entity.transform.position += allowed
            if abs(allowed.x) < abs(step_x):
                velocity.x = 0.0

        # 4. Gravity, then the vertical resolve. Support is recomputed from
        #    scratch every frame rather than remembered: an entity standing on
        #    a tile that was repainted mid-session must fall, and a flag that
        #    is only ever cleared by an event is a flag that eventually sticks.
        velocity.y = min(velocity.y + self.gravity * seconds,
                         self.max_fall_speed)
        step_y = velocity.y * seconds
        state.support = SUPPORT_AIRBORNE
        if step_y:
            direction = "down" if step_y > 0.0 else "up"
            allowed = entity.allowed_move(Vector2(0.0, step_y), direction)
            entity.transform.position += allowed
            if abs(allowed.y) < abs(step_y):
                # Something refused the step. Downward that is a floor and the
                # body has landed; upward it is a ceiling and the jump ends.
                velocity.y = 0.0
                state.support = (SUPPORT_GROUNDED if step_y > 0.0
                                 else SUPPORT_AIRBORNE)

        # 5. What the animator reads. A side-on body faces left or right and
        #    nothing else, so `walk_up` is never named -- which matters,
        #    because GameAnimationHandler.start RAISES for a sequence a sheet
        #    does not have, unlike move_direction which silently moves zero.
        #    Facing is written only while moving, so a body that stops keeps
        #    the way it was pointed.
        horizontal = intent.x
        state.phase = PHASE_MOVING if horizontal else PHASE_IDLE
        if horizontal:
            state.facing = "right" if horizontal > 0 else "left"


class GameAnimationDriveBehavior(EntityBehavior):
    """Name the animation from the movement state, on the frame it changes.

    The two format strings and the opening sequence are parameters, because a
    platformer's sheet says `run_right` where a top-down sheet says
    `walk_right`.

    It remembers the phase and facing it last saw rather than re-reading the
    entity, because by the time it runs the movement behavior has already
    overwritten them. Both branches name `state.facing`, which always has a
    legal resting value.

    `GameAnimationHandler.start` RAISES for a sequence it does not know --
    the loud half of a matched pair, since `move_direction` silently moves
    zero for a direction it does not know. A behavior list that changes the
    direction vocabulary MUST change these formats with it.
    """

    IDLE_FORMAT: str = "idle_{}"
    WALK_FORMAT: str = "walk_{}"

    def __init__(self,
                 walk_format: str = WALK_FORMAT,
                 idle_format: str = IDLE_FORMAT,
                 initial_sequence: str = IDLE_FORMAT.format(FACING_DEFAULT)):
        self.walk_format = walk_format
        self.idle_format = idle_format
        self.initial_sequence = initial_sequence
        self._last_phase = PHASE_IDLE
        self._last_facing = FACING_DEFAULT

    def attach(self, entity: Any) -> None:
        """Start the opening sequence.

        `BodyState` starts at `phase=idle`, `facing=FACING_DEFAULT`, which is
        exactly the pair `__init__` remembers, so the first frame is a
        no-change.
        """
        animation = getattr(entity, "animation", None)
        if animation is not None and self.initial_sequence:
            animation.start(self.initial_sequence)

    def update(self, entity: Any, event: Any) -> None:
        state = state_of(entity)
        animation = getattr(entity, "animation", None)
        if state is None or animation is None:
            return
        phase = state.phase
        facing = state.facing
        if phase == self._last_phase and facing == self._last_facing:
            return
        self._last_phase = phase
        self._last_facing = facing
        template = (self.walk_format if phase == PHASE_MOVING
                    else self.idle_format)
        animation.start(template.format(facing))


# ---------------------------------------------------------------------------
# The declarations
#
# Registered by `registry.py`'s table, which is the one place that says which
# token means which of these. The specs live beside the classes so a parameter
# and the constructor keyword it fills read in one screen; `build` calls
# `factory(**values)`, and `tools/check_movement.py` compares the declared
# keys against the real signature before a spawn can.
# ---------------------------------------------------------------------------

TOPDOWN_MOVE = BehaviorSpec(
    name="topdown_move",  # #TAG:topdown_move
    summary="Eight-direction axis-aligned movement, each held verb gated "
            "separately. The demo's controller.",
    factory=GameTopDownMoveBehavior,
    # Three state writes became two, because `move_direction` and
    # `last_direction` were one fact. Declaring the AXES rather than the old
    # aliases is what makes the refusal work: `EntityBehaviors.attach` rejects
    # two behaviors at one order whose `writes` intersect, so a second body
    # behavior writing `state.facing` at order 20 is refused whether or not
    # anyone remembered to declare a `conflicts` pair.
    writes=("transform.position", "state.phase", "state.facing"),
    requires=("move_direction", "transform"),
    conflicts=("platformer_move",),
    order=20,
    genres=("topdown_rpg",),
    example='<property name="pyoneer_behaviors" '
            'value="player_input,topdown_move,animation_drive"/>',
)

PLATFORMER_MOVE = BehaviorSpec(
    name="platformer_move",  # #TAG:platformer_move
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
    writes=("transform.position", "velocity", "state.support",
            "state.support_grace", "state.phase", "state.facing"),
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
    name="animation_drive",  # #TAG:animation_drive
    summary="Names the animation from the movement state, on the frame it "
            "changes. The sequence naming is parameters, not code.",
    factory=GameAnimationDriveBehavior,
    params=(
        BehaviorParam("walk_format", "walk sequence", "str",
                      GameAnimationDriveBehavior.WALK_FORMAT,
                      "Format string for the moving sequence; {} is the "
                      "direction. A platformer sheet may want 'run_{}'.",
                      source="object"),
        BehaviorParam("idle_format", "idle sequence", "str",
                      GameAnimationDriveBehavior.IDLE_FORMAT,
                      "Format string for the stopped sequence; {} is the "
                      "direction the body is facing.", source="object"),
        BehaviorParam("initial_sequence", "opening sequence", "str",
                      GameAnimationDriveBehavior.IDLE_FORMAT.format(
                          FACING_DEFAULT),
                      "Played once at attach. A side-on body wants "
                      "'idle_right'; empty leaves whatever the handler "
                      "started.", source="object"),
    ),
    writes=("animation",),
    # The state axes it READS, named rather than the bare record. `requires`
    # is reported and never enforced, so this is the declaration that tells an
    # author which axes have to be produced for this behavior to say anything
    # -- and `missing_requirements()` names the axis, not just "state".
    requires=("animation", "state.phase", "state.facing"),
    order=80,
    example='<property name="pyoneer_param_walk_format" value="run_{}"/>',
)

__all__ = ["ANIMATION_DRIVE", "MS_PER_DELTA", "PLATFORMER_MOVE",
           "SECONDS_PER_DELTA", "TOPDOWN_MOVE", "TOPDOWN_VERBS",
           "GameAnimationDriveBehavior", "GamePlatformerMoveBehavior",
           "GameTopDownMoveBehavior"]
