"""What a body IS right now: the shared state record every behavior reads.

WHY THIS IS A RECORD AND NOT A PILE OF FLAGS ON THE ENTITY
-----------------------------------------------------------
`MoveIntent` says what an entity was ASKED to do this frame. `ActionIntent`
says what it DID this frame. Neither says what it currently IS, and that gap
is where the genre used to live: `PlayerState` carried seven fields, four of
which had exactly ONE reader -- `animation_drive` -- so it was not a shared
record at all. It was a private channel between the two movement behaviors
and the animator that happened to be spelled as an entity attribute, and a
third party (an action gate, a narrative trigger, a UI) had nothing to read.

`BodyState` is the same idea as the two intents, for the third question, and
it is designed for a reader that has not been written yet. That is the whole
difference: every axis below is named for what it MEANS rather than for the
one behavior that happens to write it, so an animation driver asking "is this
body supported" does not have to know that a platformer spells it `grounded`
and a top-down body does not spell it at all.

THE FIVE AXES, AND WHY NOT MORE
-------------------------------
    phase       idle | moving          what the body is doing
    facing      an open token          which way it is pointed
    support     grounded | airborne    whether something is holding it up
    life        alive | gone           whether it is still part of the world
    agency      three booleans         whether it may be simulated or steered

Cut deliberately, each with the reason:

  * `sprinting` is NOT an axis. It is a parameter of the current motion and
    it already lives on `MoveIntent.sprint`, which is where `topdown_move`
    reads it. The field survives below ONLY because `tools/check_input.py`
    and `tools/check_movement.py` assert it; it has one writer, no production
    reader, and it is the worked example of what a parameter-shaped thing
    looks like when it is given a state slot.
  * `crouching`, `submerged`, `climbing`, `stunned`, `invulnerable` are each
    ONE format's feature, and each is a token a game can add to `facing` or
    `phase`'s vocabulary the day it ships the behavior that writes it and the
    branch that reads it. The engine shipping them first is the shape
    docs/history/ORPHANS.md exists to record.
  * The LIFECYCLE axis (`alive | gone`) was held back one pass, on the rule
    that a two-valued axis whose second value nothing writes is a value that
    lies. It ARRIVED WITH ITS WRITER, which is the condition that was set:
    `scripts/game/behavior/lifecycle.py` writes `gone`, and
    `SceneManager.reap()` is what acts on it -- removing the body from its
    scene bucket and from its `EntityLayer`, which is what actually stops the
    blit tokens. `spawning` and `dying` are still cut, under the same rule:
    nothing transitions into either, and the frame on which a body dies is
    the frame it is reaped, so there is no interval for `dying` to describe.
  * `velocity` and the coyote CLOCK's tuning (`coyote_ms`) stay where they
    are. Velocity is a side-on integration variable -- meaningless in a
    visual novel, actively wrong in grid tactics where a unit interpolates
    between cells -- and `coyote_ms` is a parameter, not a state, which
    `platformer_move` already gets right.

WHICH VOCABULARIES ARE CLOSED, AND WHY THEY DIFFER
---------------------------------------------------
`phase` and `support` are CLOSED sets and assigning anything else RAISES.
`facing` is OPEN and any non-empty string is legal. That is not an
inconsistency, it is the difference between their readers:

    phase, support,  read by `if x == VALUE else ...`. An unrecognised value
    life             would silently take the other branch -- exactly the
                     defect measured in `GameEntity.allowed_move`, where an
                     unknown direction travels UNCLAMPED through cells that
                     block everything. A closed set is what turns that into
                     a raise at the write site. `life` is the sharpest case:
                     the reaper's test is `life == LIFE_GONE`, so a typo'd
                     value is a body that was declared dead and is never
                     removed, which presents as a leak rather than as a bug.
    facing           read by `"walk_{}".format(facing)`. Its vocabulary is
                     genuinely per-game: isometric wants eight tokens,
                     twin-stick wants an angle, and a side-on sheet has no
                     `up` row at all. Closing it here would mean the engine
                     deciding how many directions a game may have.

The matching hazard is real and belongs in one sentence: `facing` is NOT the
argument to `GameEntity.move_direction`, and it must never be passed as one.
`allowed_move` looks its `direction` up in `DIRECTION_BITS` and PASSES AN
UNKNOWN KEY STRAIGHT THROUGH unclamped -- measured: an entity on a 4x4 field
of all-BLOCK_ALL cells asking `allowed_move(Vector2(10, 10), "down_right")`
gets `[10, 10]` back. Separating facing from displacement is precisely what
makes the gate's four-token limit an honest boundary instead of a silent one.

WHY THE OLD NAMES ARE STILL HERE
--------------------------------
`moving`, `move_direction`, `last_direction`, `active`, `can_move` are
properties over the axes. They are aliases, not storage: there is one home
per fact and the old spelling reads it. Nine files and eight checks name
them, and a translation that moved every caller would be a redesign wearing a
rename as a disguise.
"""
from __future__ import annotations

from typing import Any, Optional

from scripts.core.errors import PyoneerConfigError

# ---------------------------------------------------------------------------
# The vocabulary
#
# Every one of these is a value that is written into a state record and read
# by a branch or a format string. They are constants and not literals for the
# reason a behavior token is: a value spelled twice is a value that drifts,
# and a phase compared against a misspelled literal takes the other branch in
# silence.
# ---------------------------------------------------------------------------

PHASE_IDLE: str = "idle"
"""The body is not displacing. Was `PlayerState.moving is False`."""

PHASE_MOVING: str = "moving"
"""The body displaced this frame. Was `PlayerState.moving is True`."""

PHASES: tuple[str, ...] = (PHASE_IDLE, PHASE_MOVING)
"""Every legal `phase`. Assigning anything else raises.

There is no `acting`, and there deliberately is not one yet: `attack_action`
fires today and nothing writes a phase for it, so the value would exist with
no transition into it. It arrives in the same change as the behavior that
writes it AND the branch in `animation_drive` that reads it -- that pair is
the price of a third value, and it is not high.
"""

SUPPORT_GROUNDED: str = "grounded"
"""Something is holding this body up. Was `entity.grounded is True`."""

SUPPORT_AIRBORNE: str = "airborne"
"""Nothing is holding this body up. Was `entity.grounded is False`."""

SUPPORTS: tuple[str, ...] = (SUPPORT_GROUNDED, SUPPORT_AIRBORNE)
"""Every legal `support`. Exactly two, and assigning anything else raises.

Two because `platformer_move` reads it as
`control = 1.0 if grounded else air_control`, and a third value would take
the air branch with no complaint. A game that wants `swimming` wants a third
branch as well, and adding the value without the branch is how a body ends up
being air-controlled underwater and nobody can say why.
"""

LIFE_ALIVE: str = "alive"
"""This body is part of the world. Every body starts here."""

LIFE_GONE: str = "gone"
"""This body has been declared removed, and is waiting to be reaped.

DECLARED, not removed. Writing this axis is a statement and never an action:
the body is still bound, still drawn and still stepped on the frame the write
happens, and `SceneManager.reap()` is what takes it out of its scene bucket
and its `EntityLayer` on the same frame, after the fan-out has finished.

That split is the whole reason this is an axis rather than a method call. A
behavior that removed its own entity from the list `GameScene.core_frame_update`
is iterating SKIPS THE NEXT SIBLING -- measured on this engine: three objects
a, b, c with `a` unbinding itself ran ['a', 'c'] and b never updated that
frame. A body that declares itself gone cannot do that to its neighbour,
because a declaration mutates nothing but its own record.
"""

LIVES: tuple[str, ...] = (LIFE_ALIVE, LIFE_GONE)
"""Every legal `life`. Exactly two, and assigning anything else raises.

There is no `spawning` and no `dying`, for the reason the module header gives:
the reap happens on the same frame as the mark, so there is no interval either
value could describe, and a value nothing transitions into is a value that
lies. A game that wants a death animation gives the body a `lifetime_ms` on
`lifecycle_mark` and plays the animation during it -- which needs no new value
here, because "alive and playing its last sequence" is exactly `alive`.
"""

FACING_DEFAULT: str = "down"
"""What a body faces before anything has moved it.

ONE home for this string. It was `PlayerState.last_direction = "none"`, which
is not a legal sprite token: driving `animation_drive` with it raises
`PyoneerAssetMissingError: animation 'idle_none' not found`. It was
unreachable only because the two movement behaviors always wrote `moving` and
`last_direction` together and neither could report moving without a
direction -- and that accident is exactly why the animator read TWO fields
where one would do.

`GameAnimationHandler.DEFAULT_ANIMATION` is `"idle_down"` and is still spelled
independently in `scripts/game/entity/game_animation.py`. The two agree today
and nothing enforces it; `tools/check_state.py` pins that they agree, so the
day a two-row sheet forces one of them to move, the other is named.
"""


class BodyState:
    """The per-entity record of what a body currently IS.

    `__slots__`, so a misspelled axis raises `AttributeError` at the write
    instead of creating a field nobody reads. That is not defensive tidiness:
    a behavior writing `state.movnig = True` every frame would leave the
    animator reading a `phase` that never changes, which presents as an
    animation bug in a file that is correct.

    Unlike `MoveIntent` and `ActionIntent` there is no shared, locked inert
    instance. Those two are READ by entities that publish none, so a shared
    object is safe and saves every reader a branch. State is WRITTEN, so a
    shared instance would be one careless assignment away from telling every
    stateless entity on the map that it is facing left. `state_of` returns
    None instead and the two writers allocate their own in `attach`, which is
    the same thing `player_input.attach` does with the intent.
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
        supported. `platformer_move`'s coyote clock, which used to be
        `entity.coyote_left`.

        Honesty about this one: it is the weakest of the axes and it is here
        because "is this body supported" and "for how much longer does the
        engine pretend it is" are one fact split in two, and a jump gate that
        read `support` without the grace would refuse a jump the shipped
        behavior allows. It has exactly one writer and one reader today.
        Zero for a body with no grace concept, which is every body that is
        not a platformer.
        """

        self.simulated: bool = True
        """Whether this entity is stepped at all. Was `PlayerState.active`.

        `GamePlayer.core_frame_update` returns before `super()` when this is
        False, so it stops the behaviors AND the animation clock -- measured:
        five frames with `simulated=False` left the active animation's
        `current_time` at 0.000, and restoring it advanced the clock to 1.390.
        Nothing in production writes it. It is NOT a world pause and must not
        be sold as one: a pause is scene-level, this is per-entity, and there
        is no scene-level equivalent in this engine today.
        """

        self.steerable: bool = True
        """Whether this body may be STEERED. Was `PlayerState.can_move`.

        Read by `player_input` and by `patrol_input`, and deliberately NOT by
        the action behaviors: a body frozen for a cutscene may not walk and
        must still be able to press "continue".

        It does NOT pause the world, and the measurement is worth carrying
        here so nobody re-derives it: a side-on body with `steerable=False`
        still fell 13.772px in 10 frames. The gate is on the PRODUCER, so the
        intent is empty while gravity, terminal velocity and the vertical
        resolve all keep running. That is deliberate.
        """

        self.input_bound: bool = True
        """Whether this body is wired to a human's input at all.

        The de-conflation, and the one genuinely new field. `enabled_inputs`
        used to carry two different questions: `GamePlayer.__init__` cleared
        it whenever `input_` was None, so "this entity has no input manager"
        and "a dialogue box took input away" were the same bit. A narrative
        system toggling it could not tell whether it was RESTORING input or
        GRANTING it to an entity that never had any, and
        `demos/behaviors.py` carries a written workaround for exactly that.

        Set once, from the wiring: `GamePlayer.__init__` writes
        `input_ is not None`. Defaults True so a hand-built entity that was
        handed a manager directly behaves as it always did.

        This is also the field a focus/dialogue gate should write, because it
        is the one that means "this body is under someone's control" without
        also meaning "this body may walk".
        """

        self.enabled_inputs: bool = True
        """Whether input is currently PERMITTED. The authored gate.

        Read by `player_input` (with `steerable`) and by every action
        behavior (WITHOUT `steerable`) -- that divergence is asserted in both
        directions by `tools/check_action.py` and must not be collapsed. The
        survey that specified this module proposed deriving this from
        `input_bound and steerable`; that is measurably wrong. `check_action`
        sets `can_move = False` and requires an interaction to STILL fire, and
        a derived `enabled_inputs` would gate it. So it stays a field.
        """

        self.sprinting: bool = False
        """Mirror of `MoveIntent.sprint`, written by `player_input`.

        The one field on this record that is not an axis, kept because
        `tools/check_input.py` and `tools/check_movement.py` assert it. It has
        no production reader: `topdown_move` reads `intent.sprint`, which is
        the real home. Left as the worked example rather than deleted, and
        named as such in this module's header.
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

        Four tokens today because the shipped sheet has four rows, but the
        vocabulary belongs to the game: eight for isometric, an angle string
        for twin-stick, two for a side-on sheet whose `up` row does not exist
        and whose absence makes `GameAnimationHandler.start` RAISE.

        NEVER pass this to `GameEntity.move_direction` or `allowed_move`.
        Those take a DISPLACEMENT direction and their vocabulary is the four
        keys of `DIRECTION_BITS`; an unknown one is passed through the
        collision gate unclamped rather than raising.
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

        The axis `entity.grounded` became. It is on the shared record rather
        than on the entity because "is this body supported" is the archetypal
        thing a third party wants: an animator with an airborne sequence, an
        action gate that refuses a ground attack in the air, a narrative
        trigger that fires on landing. `platformer_move` put `grounded` on
        the ENTITY for exactly that reason and argued for it in its own
        docstring -- and nothing ever read it, because the animator's
        vocabulary had no room for a third fact. The axis is what makes that
        reader writable.
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

        The axis "differential construct and dynamic event creation/destruction"
        needs, and the reason a despawn is a DECLARATION rather than a null.
        Before it, an entity that wanted to remove itself had three bad
        options: leave a `None` in a list every consumer then has to guard,
        remove itself mid-fan-out and skip its neighbour, or be quietly hidden
        and go on costing a blit token forever (which is what
        `GameWindow.close` still does, deliberately, and says so).

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

    # -- compatibility, so that no caller moves ----------------------------
    #
    # Aliases over the axes above, never storage. Each one is the spelling
    # some existing reader uses, and each is here because moving that reader
    # would make a translation into a redesign.

    @property
    def moving(self) -> bool:
        """`phase is PHASE_MOVING`. Was the stored boolean."""
        return self._phase == PHASE_MOVING

    @property
    def move_direction(self) -> str:
        """The direction this body is displacing in, or `"none"` when idle.

        Read-only, and that is the point of the whole separation: the pair
        (`move_direction`, `last_direction`) was ONE fact -- which way the
        body is pointed -- stored twice, with the second copy existing only
        because the first had no legal value to hold while stopped. There is
        one copy now and this reads it. `"none"` is preserved verbatim for
        `tools/check_movement.py` and `tools/check_demos.py`, and it is the
        exact string that made `idle_none` raise, which is why `facing` never
        holds it.
        """
        return self._facing if self.moving else "none"

    @property
    def last_direction(self) -> str:
        """Was the second copy of `facing`. Now an alias for it."""
        return self._facing

    @last_direction.setter
    def last_direction(self, value: str) -> None:
        self.facing = value

    @property
    def active(self) -> bool:
        """Was the name of `simulated`."""
        return self.simulated

    @active.setter
    def active(self, value: bool) -> None:
        self.simulated = bool(value)

    @property
    def can_move(self) -> bool:
        """Was the name of `steerable`."""
        return self.steerable

    @can_move.setter
    def can_move(self, value: bool) -> None:
        self.steerable = bool(value)

    # -- diagnostics -------------------------------------------------------

    @property
    def axes(self) -> dict[str, Any]:
        """Every axis by name, for a trace, an editor row or a check.

        Deliberately the AXES and not the aliases: a caller diffing this
        across a frame is asking what changed, and an alias would report the
        same change twice under two names.
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

    The single reader, for the reason `intent_of` is one: "what happens to an
    entity with no state" is answered here rather than by five slightly
    different `getattr` calls that will eventually disagree about whether a
    non-`BodyState` object in that slot counts.

    Returns None rather than a shared inert record -- see `BodyState`'s own
    docstring for why a shared, writable record would be worse than a branch.
    """
    found = getattr(entity, "state", None)
    return found if isinstance(found, BodyState) else None


def ensure_state(entity: Any) -> BodyState:
    """The entity's `BodyState`, allocating one if it has none.

    Called from `attach` by every behavior that WRITES an axis -- the same
    contract `player_input.attach` has with `MoveIntent`: whoever publishes a
    record allocates it, so no entity class has to know which behaviors it
    might one day carry. `GamePlayer` allocates one in `__init__` as well,
    because its own `core_frame_update` reads `simulated` before any behavior
    has attached.
    """
    found = state_of(entity)
    if found is None:
        found = BodyState()
        entity.state = found
    return found


__all__ = ["FACING_DEFAULT", "LIFE_ALIVE", "LIFE_GONE", "LIVES", "PHASES",
           "PHASE_IDLE", "PHASE_MOVING", "SUPPORTS", "SUPPORT_AIRBORNE",
           "SUPPORT_GROUNDED", "BodyState", "ensure_state", "state_of"]
