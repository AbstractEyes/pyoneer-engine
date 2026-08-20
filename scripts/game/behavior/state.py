"""What a body IS right now: the shared state record every behavior reads.

`MoveIntent` says what an entity was ASKED to do this frame; `ActionIntent`
says what it DID. `BodyState` answers the third question -- what it currently
IS -- with each axis named for what it MEANS rather than for the behavior
that writes it, so an animator asking "is this body supported" need not know
that a platformer spells it `grounded` and a top-down body does not spell it
at all.

THE FIVE AXES
-------------
    phase       idle | moving          what the body is doing
    facing      an open token          which way it is pointed
    support     grounded | airborne    whether something is holding it up
    life        alive | gone           whether it is still part of the world
    agency      three booleans         whether it may be simulated or steered

`sprinting` is also stored, and is not an axis: it is a parameter of the
current motion whose real home is `MoveIntent.sprint`. Velocity and the
coyote clock's tuning stay on `platformer_move` for the same reason.

CLOSED VOCABULARIES, AND ONE OPEN ONE
-------------------------------------
`phase`, `support` and `life` are CLOSED sets and assigning anything else
RAISES, because each is read as `if x == VALUE else ...` and an unrecognised
value silently takes the other branch. `life` is the sharpest case: the
reaper's test is `life == LIFE_GONE`, so a typo'd value is a body declared
dead and never removed, which presents as a renderer leak.

`facing` is OPEN -- any non-empty string -- because it is read as
`"walk_{}".format(facing)` and its vocabulary is per-game: eight tokens for
isometric, an angle for twin-stick, two rows for a side-on sheet.

`facing` is NOT the argument to `GameEntity.move_direction` or
`allowed_move`, and must never be passed as one. Those take a DISPLACEMENT
direction from the four keys of `DIRECTION_BITS`, and an unknown key passes
through the collision gate UNCLAMPED -- measured, an entity on a 4x4 field of
all-`BLOCK_ALL` cells asking `allowed_move(Vector2(10, 10), "down_right")`
gets `[10, 10]` back.

`moving`, `move_direction`, `last_direction`, `active` and `can_move` are
properties over the axes -- aliases for older spellings, never storage.
"""
from __future__ import annotations

from typing import Any, Optional

from scripts.core.errors import PyoneerConfigError

# ---------------------------------------------------------------------------
# The vocabulary
#
# Each of these is written into a state record and read by a branch or a
# format string. They are constants rather than literals because a phase
# compared against a misspelled literal takes the other branch in silence.
# ---------------------------------------------------------------------------

PHASE_IDLE: str = "idle"
"""The body is not displacing."""

PHASE_MOVING: str = "moving"
"""The body displaced this frame."""

PHASES: tuple[str, ...] = (PHASE_IDLE, PHASE_MOVING)
"""Every legal `phase`. Assigning anything else raises.

A third value (`acting`, say) belongs in the same change as the behavior that
writes it and the branch in `animation_drive` that reads it.
"""

SUPPORT_GROUNDED: str = "grounded"
"""Something is holding this body up."""

SUPPORT_AIRBORNE: str = "airborne"
"""Nothing is holding this body up."""

SUPPORTS: tuple[str, ...] = (SUPPORT_GROUNDED, SUPPORT_AIRBORNE)
"""Every legal `support`. Exactly two, and assigning anything else raises.

`platformer_move` reads it as `1.0 if grounded else air_control`, so a third
value would silently take the air branch. A `swimming` state needs its branch
in the same change.
"""

LIFE_ALIVE: str = "alive"
"""This body is part of the world. Every body starts here."""

LIFE_GONE: str = "gone"
"""This body has been declared removed, and is waiting to be reaped.

DECLARED, not removed. Writing this axis is a statement and never an action:
the body is still bound, still drawn and still stepped on the frame the write
happens, and `SceneManager.reap()` takes it out of its scene bucket and its
`EntityLayer` on the same frame, after the fan-out has finished.

That split is why this is an axis rather than a method call. A behavior that
removed its own entity from the list `GameScene.core_frame_update` is
iterating SKIPS THE NEXT SIBLING -- measured: of three objects a, b, c with
`a` unbinding itself, only a and c updated that frame.
"""

LIVES: tuple[str, ...] = (LIFE_ALIVE, LIFE_GONE)
"""Every legal `life`. Exactly two, and assigning anything else raises.

There is no `spawning` or `dying`: the reap happens on the same frame as the
mark, so there is no interval either could describe. A death animation is a
`lifetime_ms` on `lifecycle_mark`, played while the body is still `alive`.
"""

FACING_DEFAULT: str = "down"
"""What a body faces before anything has moved it.

The one home for this string. It must stay a legal sprite token, since
`animation_drive` formats it into `idle_{}`.
`GameAnimationHandler.DEFAULT_ANIMATION` is spelled independently in
`scripts/game/entity/game_animation.py`; `tools/check_state.py` pins that the
two agree.
"""


class BodyState:
    """The per-entity record of what a body currently IS.

    `__slots__`, so a misspelled axis raises `AttributeError` at the write
    instead of creating a field nobody reads.

    There is no shared inert instance, unlike `MoveIntent` and `ActionIntent`:
    state is WRITTEN, so one careless assignment to a shared record would tell
    every stateless entity on the map that it is facing left. `state_of`
    returns None instead, and a behavior that writes an axis allocates its own
    in `attach`.
    """

    __slots__ = ("_phase", "_facing", "_support", "_life", "support_grace",
                 "simulated", "steerable", "input_bound", "enabled_inputs",
                 "sprinting")

    def __init__(self) -> None:
        self._phase: str = PHASE_IDLE
        self._facing: str = FACING_DEFAULT
        self._support: str = SUPPORT_GROUNDED
        self._life: str = LIFE_ALIVE

        self.support_grace: float = 0.0
        """Milliseconds a body that has LEFT its support is still treated as
        supported: `platformer_move`'s coyote clock.

        It lives beside `support` because a jump gate reading `support` alone
        would refuse a jump the shipped behavior allows. Zero for any body
        with no grace concept, which is every body that is not a platformer.
        """

        self.simulated: bool = True
        """Whether this entity is stepped at all.

        `GamePlayer.core_frame_update` returns before `super()` when this is
        False, so it stops the behaviors AND the animation clock. It is
        per-entity and NOT a world pause -- there is no scene-level equivalent
        in this engine.
        """

        self.steerable: bool = True
        """Whether this body may be STEERED.

        Read by `player_input` and `patrol_input`, and deliberately NOT by the
        action behaviors: a body frozen for a cutscene may not walk and must
        still be able to press "continue".

        The gate is on the PRODUCER, so it empties the intent and does not
        stop physics -- a side-on body with `steerable=False` still falls,
        measured at 13.772px over 10 frames.
        """

        self.input_bound: bool = True
        """Whether this body is wired to a human's input at all.

        Set once from the wiring -- `GamePlayer.__init__` writes
        `input_ is not None` -- and kept separate from `enabled_inputs` so a
        narrative system can tell "input was taken away" from "this entity
        never had any". Defaults True for a hand-built entity.

        This is the field a focus or dialogue gate should write: it means
        "this body is under someone's control" without also meaning "this
        body may walk".
        """

        self.enabled_inputs: bool = True
        """Whether input is currently PERMITTED. The authored gate.

        Read by `player_input` (with `steerable`) and by every action behavior
        (WITHOUT `steerable`). That divergence is asserted in both directions
        by `tools/check_action.py` and must not be collapsed -- a body with
        `steerable = False` must still be able to fire an interaction, so this
        cannot be derived from `input_bound and steerable`.
        """

        self.sprinting: bool = False
        """Mirror of `MoveIntent.sprint`, written by `player_input`.

        Not an axis, and it has no production reader -- `topdown_move` reads
        `intent.sprint`, which is the real home. Kept because
        `tools/check_input.py` and `tools/check_movement.py` assert it.
        """

    # -- the axes ----------------------------------------------------------

    @property
    def phase(self) -> str:
        """What this body is doing: one of `PHASES`."""
        return self._phase

    @phase.setter
    def phase(self, value: str) -> None:
        if value not in PHASES:
            raise PyoneerConfigError(
                "phase %r is not one of %s. A phase is read as a branch, so "
                "an unrecognised one would silently take the idle path and "
                "present as an animation bug in a file that is correct. Add "
                "a value here in the same change as the behavior that writes "
                "it and the branch that reads it."
                % (value, ", ".join(repr(p) for p in PHASES)))
        self._phase = value

    @property
    def facing(self) -> str:
        """Which way this body is pointed. An OPEN token, never empty.

        The vocabulary belongs to the game: four tokens for the shipped sheet,
        eight for isometric, an angle string for twin-stick, two for a side-on
        sheet -- whose missing `up` row makes `GameAnimationHandler.start`
        RAISE.

        NEVER pass this to `GameEntity.move_direction` or `allowed_move`.
        Those take a DISPLACEMENT direction from the four keys of
        `DIRECTION_BITS`, and an unknown one passes through the collision gate
        unclamped rather than raising.
        """
        return self._facing

    @facing.setter
    def facing(self, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise PyoneerConfigError(
                "facing must be a non-empty string and got %r. It is the {} "
                "in `walk_{}` and `idle_{}`, and an empty one names the "
                "sequence 'idle_', which GameAnimationHandler.start raises "
                "for -- one frame after the write, in a different file."
                % (value,))
        self._facing = value

    @property
    def support(self) -> str:
        """Whether something is holding this body up: one of `SUPPORTS`.

        On the shared record rather than on the entity, so a third party can
        read it: an animator with an airborne sequence, an action gate that
        refuses a ground attack in the air, a narrative trigger on landing.
        """
        return self._support

    @support.setter
    def support(self, value: str) -> None:
        if value not in SUPPORTS:
            raise PyoneerConfigError(
                "support %r is not one of %s. It is read as "
                "`1.0 if grounded else air_control`, so a third value would "
                "air-control a body that is standing still and nothing would "
                "say so. A third state of support needs its branch first."
                % (value, ", ".join(repr(s) for s in SUPPORTS)))
        self._support = value

    @property
    def life(self) -> str:
        """Whether this body is still part of the world: one of `LIVES`.

        A despawn is a DECLARATION rather than a null, so no consumer has to
        guard a hole in a list and no body removes itself mid-fan-out.

        WHO WRITES IT
        -------------
            `lifecycle_mark`        the authorable writer: on a named action,
                                    or after a declared lifetime
            `SceneManager.despawn`  writes it when a caller removes a body by
                                    hand, so the record agrees with the world
                                    whichever end the removal started from
            game code               `state_of(entity).life = LIFE_GONE` is a
                                    complete, supported despawn request. That
                                    is the seam; `lifecycle_mark` is one
                                    behavior that uses it, not the only way in.

        WHO READS IT
        ------------
        `SceneManager.reap()`, once per frame, after the whole fan-out. It is
        the only reader that ACTS. Anything else -- an animator wanting a death
        sequence, a spawner counting live bodies -- reads it and does not have
        to know how the body was killed.
        """
        return self._life

    @life.setter
    def life(self, value: str) -> None:
        if value not in LIVES:
            raise PyoneerConfigError(
                "life %r is not one of %s. The reaper's test is "
                "`life == %r`, so a value it does not know is a body that was "
                "declared dead and is then never removed -- which presents as "
                "a leak in the renderer rather than as a bug at this line."
                % (value, ", ".join(repr(v) for v in LIVES), LIFE_GONE))
        self._life = value

    @property
    def gone(self) -> bool:
        """`life is LIFE_GONE`. The reaper's question, spelled once."""
        return self._life == LIFE_GONE

    # -- compatibility -----------------------------------------------------
    #
    # Aliases over the axes above, never storage. Each is the spelling some
    # existing reader uses.

    @property
    def moving(self) -> bool:
        """`phase is PHASE_MOVING`."""
        return self._phase == PHASE_MOVING

    @property
    def move_direction(self) -> str:
        """The direction this body is displacing in, or `"none"` when idle.

        Read-only, derived from `facing` and `phase`. `"none"` is not a legal
        sprite token -- `idle_none` raises -- which is why `facing` never
        holds it and this property is the only thing that produces it.
        """
        return self._facing if self.moving else "none"

    @property
    def last_direction(self) -> str:
        """Alias for `facing`."""
        return self._facing

    @last_direction.setter
    def last_direction(self, value: str) -> None:
        self.facing = value

    @property
    def active(self) -> bool:
        """Alias for `simulated`."""
        return self.simulated

    @active.setter
    def active(self, value: bool) -> None:
        self.simulated = bool(value)

    @property
    def can_move(self) -> bool:
        """Alias for `steerable`."""
        return self.steerable

    @can_move.setter
    def can_move(self, value: bool) -> None:
        self.steerable = bool(value)

    # -- diagnostics -------------------------------------------------------

    @property
    def axes(self) -> dict[str, Any]:
        """Every axis by name, for a trace, an editor row or a check.

        The AXES and not the aliases, so a caller diffing this across a frame
        does not see one change reported twice under two names.
        """
        return {"phase": self._phase, "facing": self._facing,
                "support": self._support, "life": self._life,
                "support_grace": self.support_grace,
                "simulated": self.simulated, "steerable": self.steerable,
                "input_bound": self.input_bound,
                "enabled_inputs": self.enabled_inputs,
                "sprinting": self.sprinting}

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return "<BodyState %s facing %s, %s, %s>" % (self._phase, self._facing,
                                                     self._support, self._life)


def state_of(entity: Any) -> Optional[BodyState]:
    """The entity's own `BodyState`, or None when it carries none.

    The single reader, so "what happens to an entity with no state" is
    answered in one place. Returns None rather than a shared inert record,
    because the record is writable.
    """
    found = getattr(entity, "state", None)
    return found if isinstance(found, BodyState) else None


def ensure_state(entity: Any) -> BodyState:
    """The entity's `BodyState`, allocating one if it has none.

    Called from `attach` by every behavior that WRITES an axis, so no entity
    class has to know which behaviors it might one day carry. `GamePlayer`
    allocates one in `__init__` as well, because its own `core_frame_update`
    reads `simulated` before any behavior has attached.
    """
    found = state_of(entity)
    if found is None:
        found = BodyState()
        entity.state = found
    return found


__all__ = ["FACING_DEFAULT", "LIFE_ALIVE", "LIFE_GONE", "LIVES", "PHASES",
           "PHASE_IDLE", "PHASE_MOVING", "SUPPORTS", "SUPPORT_AIRBORNE",
           "SUPPORT_GROUNDED", "BodyState", "ensure_state", "state_of"]
