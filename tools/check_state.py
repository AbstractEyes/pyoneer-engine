"""Verify the shared state vocabulary: `BodyState`, and the two bodies on it.

WHAT THIS FILE CLAIMS
---------------------
     1. the record's axes have the declared defaults, the CLOSED vocabularies
        refuse a value outside them, and the OPEN one accepts a token the
        engine has never seen
     2. every old `PlayerState` name is an ALIAS over an axis and not a second
        copy -- proved in both directions, and by the writes that are refused
     3. `entity.grounded` and `entity.coyote_left` are the same aliases: one
        home, two spellings, and an external write reaches the axis
     4. `topdown_move` writes `phase` and `facing` and nothing else
     5. `platformer_move` writes `support` and `support_grace`, refills the
        grace on the ground and drains it in the air
     6. each spec's declared `writes` is EXACTLY the set of axes its behavior
        actually moves -- so an undeclared write fails AND a declaration that
        claims an axis it never touches fails
     7. two behaviors at one order writing one axis are REFUSED at attach,
        exactly as two writers of `transform.position` already are
     8. facing was separated from displacement without moving the frame, and
        the negative control -- an animator naming both branches from
        `move_direction` -- RAISES, so the identity is a measurement
     9. `facing` is NOT the displacement vocabulary, and the gate really does
        pass an unknown direction through unclamped, which is why
    10. `input_bound` de-conflates "no manager" from "input taken away", and
        `enabled_inputs` is still an independent field rather than a derived
        one -- `check_action` requires an interaction to fire while frozen
    11. `lifecycle_mark`'s `despawn_on` is audited against the registry's
        declared action SLOTS at construction -- an unwritable token raises,
        every declared one is still accepted, and a body whose authored list
        puts `lifecycle_mark` first still composes and still dies

THE FIXTURES ARE THIS FILE'S OWN
--------------------------------
Every collision field is built here from a few lines of ASCII and every body
is constructed in this file. `data/maps/test.tmx` is never read: a check that
pins map CONTENT goes red the next time the author paints, while the code it
guards is working perfectly (law 4).

    .venv/Scripts/python.exe tools/check_state.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

from pygame import Vector2                                        # noqa: E402

from scripts.core.collision_runtime import (BLOCK_ALL, DIRECTION_BITS,  # noqa: E402
                                            PASS_ALL, CollisionField)
from scripts.core.errors import (PyoneerAssetMissingError,        # noqa: E402
                                 PyoneerConfigError)
from scripts.core.event_manager import PyoneerEvent               # noqa: E402
from scripts.core.event_types import GameEventType                # noqa: E402
from scripts.game.behavior import (BEHAVIORS, PARAM_PREFIX, BehaviorSpec,  # noqa: E402
                                   EntityBehavior, build, read_requests)
from scripts.game.behavior.input import MoveIntent                # noqa: E402
from scripts.game.behavior.registry import _AXIS_DOC, _state_axes  # noqa: E402
from scripts.game.behavior.movement import (ANIMATION_DRIVE,      # noqa: E402
                                            PLATFORMER_MOVE, TOPDOWN_MOVE,
                                            TOPDOWN_VERBS,
                                            GameAnimationDriveBehavior)
from scripts.game.behavior.action import ACTION_SPECS               # noqa: E402
from scripts.game.behavior.lifecycle import (GameLifecycleMarkBehavior,  # noqa: E402
                                             _declared_action_tokens)
from scripts.game.behavior.state import (FACING_DEFAULT, LIFE_ALIVE,  # noqa: E402
                                         LIFE_GONE, PHASE_IDLE,
                                         PHASE_MOVING, PHASES,
                                         SUPPORT_AIRBORNE, SUPPORT_GROUNDED,
                                         SUPPORTS, BodyState, ensure_state,
                                         state_of)
from scripts.game.entity.game_animation import GameAnimationHandler  # noqa: E402
from scripts.game.entity.game_entity import GameEntity            # noqa: E402
from scripts.game.entity.game_player import GamePlayer, PlayerState  # noqa: E402

failures: list[str] = []
asserted: list[str] = []


def expect(label, got, want):
    asserted.append(label)
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={got!r} want={want!r}")
    if not ok:
        failures.append(label)


def expect_true(label, got):
    asserted.append(label)
    ok = bool(got)
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={got!r}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception, call, *fragments):
    """The call must raise, and the message must name each fragment.

    The fragments are the teeth. A test that checks only the exception TYPE
    passes for any raise anywhere inside the call, including a typo three
    frames down that has nothing to do with the claim being made.
    """
    asserted.append(label)
    try:
        call()
    except exception as exc:
        text = str(exc)
        missing = [f for f in fragments if f not in text]
        ok = not missing
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} "
              f"raised {type(exc).__name__}: {text.splitlines()[0][:50]}")
        if not ok:
            failures.append(f"{label} (message lacks {missing})")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<58} raised {type(exc).__name__} not "
              f"{exception.__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<58} did not raise")
    failures.append(label)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class Recorder:
    """A stand-in for `GameAnimationHandler` that RAISES for an unknown name.

    Faithful in the one way that matters here: `GameAnimationHandler.start`
    raises `PyoneerAssetMissingError` for a sequence a sheet does not have.
    That is what makes section 8's negative control a real control -- a
    recorder that quietly accepted `idle_none` would let the broken animator
    pass and the "identical" claim would be a tautology.
    """

    KNOWN = ("idle_up", "idle_down", "idle_left", "idle_right",
             "walk_up", "walk_down", "walk_left", "walk_right")

    def __init__(self):
        self.started: list[str] = []

    def start(self, name=None, from_beginning=True):
        if name not in self.KNOWN:
            raise PyoneerAssetMissingError("animation", name,
                                           available=self.KNOWN)
        self.started.append(name)

    def update(self, event=None):
        pass

    def image(self):
        return None


class Body(GameEntity):
    """The smallest concrete entity a movement behavior can drive.

    A `GameEntity` and not a `GamePlayer`, deliberately: the claims below are
    about the RECORD and the behaviors, and a body that needed a spritesheet
    would make them unrunnable in a fresh clone. The one section that needs a
    real `GamePlayer` says so and builds one.
    """

    def __init__(self, move_speed=10, sprint_mult=3, animation=True):
        super().__init__(movement_config={"movement": {
            "move_speed": move_speed, "sprint_mult": sprint_mult}})
        self.state = BodyState()
        self.animation = Recorder() if animation else None
        self.action_manager = None

    def core_lifecycle_build(self, event=None):
        pass

    def core_input_receive(self, event=None):
        pass


class Keys:
    """Exactly the three members an input behavior touches.

    `held` and `pressed` read SEPARATE sets, so a fixture can tell a hold from
    an edge; one shared set could not distinguish a correct jump from the
    infinite-hover bug.
    """

    def __init__(self, *verbs):
        self.actions = {v: None for v in verbs}
        self.down: set[str] = set()
        self.edge: set[str] = set()

    def hold(self, *verbs):
        self.down = set(verbs)
        return self

    def tap(self, *verbs):
        self.edge = set(verbs)
        return self

    def held(self, verb):
        return verb in self.down

    def pressed(self, verb):
        return verb in self.edge


ALL_VERBS = ("up", "down", "left", "right", "sprint", "jump")


def compose(entity, tokens, **params):
    properties = {BEHAVIORS: tokens}
    for key, value in params.items():
        properties[PARAM_PREFIX + key] = value
    entity.behaviors.attach_all(
        build(read_requests(properties, where="check_state")))
    return entity


def frame(entity, delta=1.0):
    entity.core_frame_update(
        PyoneerEvent(GameEventType.UPDATE, data={"delta": delta}))


def field(rows):
    """A collision field from ASCII. `#` blocks everything, `.` blocks nothing."""
    masks = bytes(BLOCK_ALL if char == "#" else PASS_ALL
                  for row in rows for char in row)
    return CollisionField(len(rows[0]), len(rows), masks,
                          tile_width=16, tile_height=16)


FLOOR = field(["........",
               "........",
               "........",
               "........",
               "########",
               "########"])

LEDGE = field(["........",
               "........",
               "........",
               "........",
               "###......"[:8]]
              + ["........"] * 15)
"""A three-cell ledge with a long drop under it.

The drop is long on purpose. `CollisionField.outside` is BLOCK_ALL, so a body
that reaches the bottom of the field STOPS THERE and reports itself supported
-- the trap `tools/check_collision_field.py` calls out by name. A short field
would make "it is still unsupported" go green or red depending on how many
frames the loop happened to run, which is a fixture measuring itself.
"""

SEALED = field(["####", "####", "####", "####"])


# ===========================================================================
print("1. the axes: defaults, the closed vocabularies, and the open one")
# ===========================================================================
_fresh = BodyState()
expect("a fresh body is idle", _fresh.phase, PHASE_IDLE)
expect("...faces the one default direction", _fresh.facing, FACING_DEFAULT)
expect("...is supported, because a body with no gravity model is",
       _fresh.support, SUPPORT_GROUNDED)
expect("...with no support grace to spend", _fresh.support_grace, 0.0)
expect("...and is simulated, steerable, bound and enabled",
       (_fresh.simulated, _fresh.steerable, _fresh.input_bound,
        _fresh.enabled_inputs), (True, True, True, True))

# The closed vocabularies, BOTH halves. The "accepts" half alone would pass
# for a setter that accepts anything, which is what a plain attribute is.
for _value in PHASES:
    _fresh.phase = _value
expect("every declared phase is assignable", _fresh.phase, PHASES[-1])
for _value in SUPPORTS:
    _fresh.support = _value
expect("every declared support is assignable", _fresh.support, SUPPORTS[-1])

expect_raises("a phase outside the vocabulary is refused at the write",
              PyoneerConfigError,
              lambda: setattr(_fresh, "phase", "acting"),
              "'acting'", "'idle'", "'moving'")
expect_raises("...and so is a support the branch cannot read",
              PyoneerConfigError,
              lambda: setattr(_fresh, "support", "swimming"),
              "'swimming'", "'grounded'", "'airborne'")
expect_raises("...and the old boolean spelling, which would have been truthy",
              PyoneerConfigError,
              lambda: setattr(_fresh, "support", True),
              "grounded", "airborne")

# Facing is OPEN, and that is a claim in its own right: an isometric game
# needs eight tokens and a twin-stick one needs an angle, so the engine must
# not decide how many directions a game may have.
_fresh.facing = "down_right"
expect("facing accepts a token the engine has never seen", _fresh.facing,
       "down_right")
_fresh.facing = "0.7853981633974483"
expect("...including one that is not a direction word at all",
       _fresh.facing, "0.7853981633974483")
expect_raises("but an EMPTY facing is refused, because 'idle_' raises later",
              PyoneerConfigError,
              lambda: setattr(_fresh, "facing", ""),
              "non-empty", "idle_")
expect_raises("...and so is a non-string, which would format as its repr",
              PyoneerConfigError,
              lambda: setattr(_fresh, "facing", 3),
              "non-empty string", "3")

# __slots__: a misspelled axis must raise rather than create a field nobody
# reads. Both halves, because a record with no slots passes the first.
_fresh.sprinting = True
expect("a declared field assigns", _fresh.sprinting, True)
expect_raises("a MISSPELLED axis raises instead of silently becoming a field",
              AttributeError,
              lambda: setattr(_fresh, "movnig", True),
              "movnig")


# ===========================================================================
print("\n2. the old names are aliases over the axes, not a second copy")
# ===========================================================================
expect("PlayerState IS BodyState, so eight files' imports still resolve",
       PlayerState is BodyState, True)

_alias = BodyState()
_alias.facing = "left"
expect("an idle body reports move_direction 'none', as it always did",
       (_alias.moving, _alias.move_direction), (False, "none"))
expect("...while last_direction still answers which way it faces",
       _alias.last_direction, "left")
_alias.phase = PHASE_MOVING
expect("...and moving flips both readings from ONE write",
       (_alias.moving, _alias.move_direction), (True, "left"))

_alias.last_direction = "up"
expect("writing the old name writes the axis", _alias.facing, "up")
_alias.facing = "down"
expect("...and reading the old name reads the axis", _alias.last_direction,
       "down")

_alias.active = False
expect("active writes simulated", _alias.simulated, False)
_alias.simulated = True
expect("...and reads simulated back", _alias.active, True)
_alias.can_move = False
expect("can_move writes steerable", _alias.steerable, False)
_alias.steerable = True
expect("...and reads steerable back", _alias.can_move, True)

# The derived readings are READ-ONLY, and that is what proves there is one
# home: a settable `moving` would be a second place the phase could live.
expect_raises("moving cannot be written, because phase is the home",
              AttributeError, lambda: setattr(_alias, "moving", True))
expect_raises("...nor move_direction, for the same reason",
              AttributeError,
              lambda: setattr(_alias, "move_direction", "left"))

# `enabled_inputs` is NOT derived. The survey that specified this module
# proposed `input_bound and steerable`; tools/check_action.py sets
# can_move=False and requires an interaction to STILL fire, so a derived
# reading would gate it. Pinned here so the "simplification" is not made.
_alias.steerable = False
_alias.input_bound = False
expect("enabled_inputs is an independent field, not steerable AND bound",
       _alias.enabled_inputs, True)


# ===========================================================================
print("\n3. entity.grounded and entity.coyote_left are the same axis")
# ===========================================================================
_aliased = Body()
_aliased.grounded = False
expect("writing entity.grounded reaches the axis", _aliased.state.support,
       SUPPORT_AIRBORNE)
_aliased.state.support = SUPPORT_GROUNDED
expect("...and writing the axis reaches entity.grounded", _aliased.grounded,
       True)
_aliased.coyote_left = 42.5
expect("writing entity.coyote_left reaches the grace axis",
       _aliased.state.support_grace, 42.5)
_aliased.state.support_grace = 7.0
expect("...and back", _aliased.coyote_left, 7.0)

# The half that keeps tools/check_collision_field.py honest: a body that was
# never given a record must report no such flag, not a plausible False.
_stateless = Body()
_stateless.state = None
expect("an entity with no record has NO grounded flag at all",
       getattr(_stateless, "grounded", "<no such flag>"), "<no such flag>")
expect("...and no coyote_left either",
       getattr(_stateless, "coyote_left", "<no such flag>"), "<no such flag>")
expect("state_of answers None for it", state_of(_stateless), None)
_stateless.state = "not a record"
expect("...and for a slot holding something that is not a BodyState",
       state_of(_stateless), None)

_ensured = Body()
_ensured.state = None
_first = ensure_state(_ensured)
expect_true("ensure_state allocates one where there was none",
            isinstance(_first, BodyState))
expect("...and returns the SAME one next time rather than replacing it",
       ensure_state(_ensured) is _first, True)


# ===========================================================================
print("\n4. topdown_move writes phase and facing")
# ===========================================================================
_top = Body()
_top.action_manager = Keys(*ALL_VERBS)
compose(_top, "player_input,topdown_move")
expect("a body that has not moved is idle and facing the default",
       (_top.state.phase, _top.state.facing), (PHASE_IDLE, FACING_DEFAULT))

_top.action_manager.hold("right")
frame(_top)
expect("holding right moves it and faces it right",
       (_top.state.phase, _top.state.facing, _top.transform.position.x),
       (PHASE_MOVING, "right", 10.0))
expect("...and the old readings agree",
       (_top.state.moving, _top.state.move_direction,
        _top.state.last_direction), (True, "right", "right"))

_top.action_manager.hold()
frame(_top)
expect("releasing returns it to idle and KEEPS the facing",
       (_top.state.phase, _top.state.facing), (PHASE_IDLE, "right"))
expect("...which is what the second field used to be for",
       (_top.state.move_direction, _top.state.last_direction),
       ("none", "right"))

# The order of TOPDOWN_VERBS is load-bearing in exactly one way, and this is
# it. Both halves: the diagonal faces the LAST held verb, and the other
# diagonal faces the other one, so a reversed tuple fails rather than
# swapping two passing assertions.
_diag = Body()
_diag.action_manager = Keys(*ALL_VERBS).hold("up", "right")
compose(_diag, "player_input,topdown_move")
frame(_diag)
expect("a diagonal walks both ways and faces the LAST verb polled",
       (_diag.state.facing, tuple(_diag.transform.position)),
       ("right", (10.0, -10.0)))
_diag.action_manager.hold("left", "down")
frame(_diag)
expect("...and the other diagonal faces the other last verb",
       _diag.state.facing, "left")

# Facing must NEVER hold the string that made `idle_none` raise, at any point
# in a run that stops, starts and reverses.
_never = Body()
_never.action_manager = Keys(*ALL_VERBS)
compose(_never, "player_input,topdown_move")
_seen = set()
for _held in (("right",), (), ("up",), (), ("left", "right"), (), ("down",)):
    _never.action_manager.hold(*_held)
    for _ in range(2):
        frame(_never)
        _seen.add(_never.state.facing)
expect("facing is never 'none' and never empty across a whole run",
       sorted(_seen), ["down", "right", "up"])

# The record is ALLOCATED by whoever writes it -- `player_input.attach`'s
# contract with `MoveIntent`, applied to the state. Both halves: a body with
# no record gets one and reports its motion, and a body whose record is taken
# away afterwards still MOVES and simply has nowhere to write, which is the
# pushed-crate branch the behavior documents.
_crate = Body()
_crate.state = None
_crate.intent = MoveIntent()
compose(_crate, "topdown_move")
expect_true("attaching a movement behavior allocates the record it writes",
            isinstance(state_of(_crate), BodyState))
_crate.intent.right = True
frame(_crate)
expect("...and the freshly allocated record receives the motion",
       (_crate.state.phase, _crate.state.facing, _crate.transform.position.x),
       (PHASE_MOVING, "right", 10.0))
_crate.state = None
frame(_crate)
expect("a body whose record is taken away still moves, with nowhere to write",
       (_crate.transform.position.x, state_of(_crate)), (20.0, None))


# ===========================================================================
print("\n5. platformer_move writes support and the support grace")
# ===========================================================================
def side_on(field_=FLOOR, at=(16.0, 16.0), hold=(), **params):
    body = Body()
    body.action_manager = Keys(*ALL_VERBS).hold(*hold)
    body.collision_field = field_
    compose(body, "player_input,platformer_move", jump_verb="jump", **params)
    body.moveto(at)
    return body


def drop(body, limit=40):
    """Frame until it lands, or say so. Every loop here is BOUNDED.

    An unbounded `while airborne` is a check that HANGS instead of failing
    when the fixture is wrong, and a check that hangs gets removed from the
    roster.
    """
    for _ in range(limit):
        frame(body, delta=0.2777)
        if body.state.support == SUPPORT_GROUNDED:
            return body
    raise AssertionError("fixture never landed in %d frames" % limit)


_falling = side_on()
expect("a side-on body declares itself unsupported at attach",
       _falling.state.support, SUPPORT_AIRBORNE)
frame(_falling, delta=0.2777)
expect("...and is still unsupported while it falls",
       _falling.state.support, SUPPORT_AIRBORNE)
expect("...with no grace, because it never had support to leave",
       _falling.state.support_grace, 0.0)

_landed = drop(side_on())
expect("it lands, and the axis says so", _landed.state.support,
       SUPPORT_GROUNDED)
expect("...with no grace yet, because the refill reads the support it had "
       "at the TOP of the frame it landed on",
       _landed.state.support_grace, 0.0)
frame(_landed, delta=0.2777)
expect("...and the next standing frame refills it to coyote_ms",
       _landed.state.support_grace,
       float(PLATFORMER_MOVE.param("coyote_ms").default))
expect("...and entity.grounded, being the same axis, agrees",
       _landed.grounded, True)

# The grace DRAINS in the air and reaches zero -- the half a "refills on the
# ground" assertion alone cannot see, since a clock that never counted down
# would refill just as well.
def off_the_ledge(**params):
    """Land on the ledge, walk right until the floor runs out, then report.

    Falls with NO horizontal input first: a body that drifts under air control
    while falling arrives past the ledge and lands on the field's own border
    instead, which measures the border rather than the grace clock.
    """
    body = drop(side_on(field_=LEDGE, **params))
    frame(body, delta=0.2777)            # one standing frame, to refill
    body.action_manager.hold("right")
    for _ in range(30):                  # bounded: see `drop`
        frame(body, delta=0.2777)
        if body.state.support == SUPPORT_AIRBORNE:
            return body
    raise AssertionError("the ledge fixture never walked off the ledge")


_walked_off = off_the_ledge()
expect("walking off a ledge leaves the body unsupported",
       _walked_off.state.support, SUPPORT_AIRBORNE)
_airborne_grace = [_walked_off.state.support_grace]
for _ in range(12):                      # bounded: see `drop`
    frame(_walked_off, delta=0.2777)
    if _walked_off.state.support != SUPPORT_AIRBORNE:
        break
    _airborne_grace.append(_walked_off.state.support_grace)
expect_true("...its grace is still open on the first airborne frame",
            _airborne_grace[0] > 0.0)
expect_true("...it never increases while nothing is holding the body up",
            all(b <= a for a, b in zip(_airborne_grace, _airborne_grace[1:])))
expect_true("...and it actually counts DOWN rather than merely sitting still",
            _airborne_grace[1] < _airborne_grace[0])
expect("...closing at zero rather than going negative",
       _airborne_grace[-1], 0.0)

# A jump SPENDS the window, which is the only reason a second jump is
# impossible. Both halves: inside the window a jump launches, and after it
# the same body's jump does nothing.
_coyote = off_the_ledge()
_coyote.action_manager.tap("jump")
frame(_coyote, delta=0.2777)
expect_true("a jump inside the grace window launches", _coyote.velocity.y < 0.0)
expect("...and spending it empties the grace", _coyote.state.support_grace, 0.0)
_before = _coyote.velocity.y
_coyote.action_manager.tap("jump")
frame(_coyote, delta=0.2777)
expect_true("...so the next jump does nothing but fall further",
            _coyote.velocity.y > _before)


# ===========================================================================
print("\n6. the declared `writes` is exactly what each behavior moves")
# ===========================================================================
def moved_axes(body, plan, delta=1.0):
    """Every axis that CHANGED across a scripted run, as `state.<axis>` names.

    Diffs `BodyState.axes` frame by frame rather than start-to-end: an axis
    that is written and restored -- `support`, which is cleared to airborne
    and re-set every single frame -- is a real write and an end-to-end diff
    reports it as untouched.
    """
    seen: set[str] = set()
    before = dict(body.state.axes)
    for intent_fields in plan:
        intent = body.intent
        intent.clear()
        for name in intent_fields:
            setattr(intent, name, True)
        frame(body, delta=delta)
        after = dict(body.state.axes)
        seen.update("state.%s" % key for key in after
                    if after[key] != before[key])
        before = after
    return seen


def declared(spec):
    return {w for w in spec.writes if w.startswith("state.")}


_topdown_probe = Body()
_topdown_probe.intent = MoveIntent()
compose(_topdown_probe, "topdown_move")
_topdown_moved = moved_axes(_topdown_probe,
                            [("right",), (), ("up",), (), ("left",), ()])
expect("topdown_move moves exactly the axes it declares",
       sorted(_topdown_moved), sorted(declared(TOPDOWN_MOVE)))
expect("...which is the pair, spelled as axes", sorted(declared(TOPDOWN_MOVE)),
       ["state.facing", "state.phase"])

_side_probe = Body()
_side_probe.intent = MoveIntent()
_side_probe.collision_field = FLOOR
compose(_side_probe, "platformer_move")
_side_probe.moveto((16.0, 16.0))
_side_moved = moved_axes(_side_probe,
                         [()] * 12 + [("right",)] * 4 + [("right", "jump")]
                         + [("right",)] * 8 + [("left",)] * 4 + [()] * 6,
                         delta=0.2777)
expect("platformer_move moves exactly the axes it declares",
       sorted(_side_moved), sorted(declared(PLATFORMER_MOVE)))
expect("...which is support, its grace, and the same motion pair",
       sorted(declared(PLATFORMER_MOVE)),
       ["state.facing", "state.phase", "state.support", "state.support_grace"])

# THE IDLE HALF. `platformer_move` sets PHASE_MOVING if horizontal else
# PHASE_IDLE, and covering only the MOVING branch leaves a side-on body that
# stopped playing its walk cycle forever -- the exact bug `phase` exists to
# make impossible. The top-down twin of this assertion lives in check_movement.
_idle_probe = Body()
_idle_probe.intent = MoveIntent()
_idle_probe.collision_field = FLOOR
_idle_probe.animation = Recorder()
compose(_idle_probe, "platformer_move,animation_drive")
_idle_probe.moveto((16.0, 16.0))
for _ in range(20):                       # settle onto the floor, then walk
    frame(_idle_probe, delta=0.2777)
_idle_probe.intent.right = True
for _ in range(4):
    frame(_idle_probe, delta=0.2777)
expect("a side-on body that is walking reads PHASE_MOVING",
       state_of(_idle_probe).phase, PHASE_MOVING)
_idle_probe.intent.right = False
frame(_idle_probe, delta=0.2777)
expect("...and one that STOPS returns to PHASE_IDLE",
       state_of(_idle_probe).phase, PHASE_IDLE)
expect("...and the animator emits the idle sequence on that frame, which is "
       "what the axis is for",
       _idle_probe.animation.started[-1], "idle_right")

# The animator declares what it READS. `missing_requirements` names the AXIS
# rather than the bare record, which is the difference between "this needs a
# state" and "this needs something to publish a phase".
_unfed = Body()
_unfed.state = None
compose(_unfed, "animation_drive")
expect("an animator with no record reports the axes it cannot read",
       _unfed.behaviors.missing_requirements(),
       (("animation_drive", "state.phase"),
        ("animation_drive", "state.facing")))
_fed = Body()
compose(_fed, "animation_drive")
expect("...and reports nothing once something publishes them",
       _fed.behaviors.missing_requirements(), ())

# docs/BEHAVIORS.md's writes column is spelled in these axes, so the generated
# document has to explain them or the breadcrumb ends. Both halves: every axis
# on the record has a sentence, AND an axis without one is VISIBLE in the
# document rather than silently absent -- the failure a scrape would produce.
expect("every axis on the record has a sentence in the generated document",
       sorted(_AXIS_DOC), sorted(BodyState().axes))
_removed = _AXIS_DOC.pop("facing")
try:
    _thin = "\n".join(_state_axes())
finally:
    _AXIS_DOC["facing"] = _removed
expect_true("...and an axis with no sentence renders as undocumented",
            "| `state.facing` | **undocumented**" in _thin)
_AXIS_DOC["ghost"] = "an axis that was deleted"
try:
    _stale = "\n".join(_state_axes())
finally:
    del _AXIS_DOC["ghost"]
expect_true("...while a sentence that outlived its axis says so too",
            "ghost described here and not on the record" in _stale)


# ===========================================================================
print("\n7. two writers of one axis are refused at attach")
# ===========================================================================
class _Writer(EntityBehavior):
    def update(self, entity, event):
        pass


def _spec(name, order, writes):
    return BehaviorSpec(name=name, summary="fixture", factory=_Writer,
                        order=order, writes=writes)


def _attach(entity, *specs):
    for spec in specs:
        behavior = _Writer()
        behavior.spec = spec
        entity.behaviors.attach(behavior)


expect_raises("two behaviors at one order writing state.facing are refused",
              PyoneerConfigError,
              lambda: _attach(Body(),
                              _spec("face_a", 20, ("state.facing",)),
                              _spec("face_b", 20, ("state.facing",))),
              "face_a", "face_b", "order=20", "state.facing")
expect_raises("...and so are two writers of state.support",
              PyoneerConfigError,
              lambda: _attach(Body(),
                              _spec("hold_a", 20, ("state.support",)),
                              _spec("hold_b", 20, ("state.support",))),
              "state.support")

# The three halves that prove the refusal is not blanket. Without these, a
# rule of "refuse any two behaviors at one order" would pass every assertion
# above and break every legal composition in the tree.
_disjoint = Body()
_attach(_disjoint, _spec("face_c", 20, ("state.facing",)),
        _spec("hold_c", 20, ("state.support",)))
expect("same order, DIFFERENT axes is legal and stays legal",
       _disjoint.behaviors.names, ("face_c", "hold_c"))

_ordered = Body()
_attach(_ordered, _spec("face_d", 20, ("state.facing",)),
        _spec("face_e", 30, ("state.facing",)))
expect("...and so is one axis at two orders, because order decides the winner",
       _ordered.behaviors.names, ("face_d", "face_e"))

_real = Body()
_real.action_manager = Keys(*ALL_VERBS)
expect_raises("the two shipped bodies refuse each other by declared conflict",
              PyoneerConfigError,
              lambda: compose(_real, "topdown_move,platformer_move"),
              "topdown_move", "platformer_move", "conflict")


# ===========================================================================
print("\n8. facing was separated from displacement, and the frame did not move")
# ===========================================================================
# The exact sequence a scripted walk produces. This is the pinned half of the
# A/B that was run against the pre-translation tree: 32 frames, 8 verb
# phases, hold / stop / diagonal / reverse / cancel / stop / down / stop.
WALK = [(5, ("right",)), (4, ()), (5, ("up", "right")), (4, ("left",)),
        (3, ("left", "right")), (4, ()), (4, ("down",)), (3, ())]

EXPECTED_STARTS = ["idle_down", "walk_right", "idle_right", "walk_right",
                   "walk_left", "walk_right", "idle_right", "walk_down",
                   "idle_down"]


def walked(body):
    for count, held in WALK:
        body.action_manager.hold(*held)
        for _ in range(count):
            frame(body)
    return body


_animated = Body()
_animated.action_manager = Keys(*ALL_VERBS)
compose(_animated, "player_input,topdown_move,animation_drive")
try:
    walked(_animated)
except PyoneerAssetMissingError as _exc:
    # Reported as a named failure rather than allowed to abort the run: the
    # recorder raises for a sequence no sheet has, and "the check crashed" is
    # a worse report than "this claim is false, and here is the sequence".
    _animated.animation.started.append("RAISED %s" % _exc)
expect("naming both sequences from `facing` reproduces the pre-change run",
       _animated.animation.started, EXPECTED_STARTS)
expect("...and the animator still fires only on the frame something changed",
       len(_animated.animation.started), 9)


class _OldNaming(GameAnimationDriveBehavior):
    """The negative control: name BOTH branches from `move_direction`.

    This is the variant the separation replaced. It is written here rather
    than described, because "the two are identical" is only a measurement if
    the obvious wrong version is shown to differ -- and it does, loudly, on
    the first frame the body stops.
    """

    def update(self, entity, event):
        state = state_of(entity)
        animation = getattr(entity, "animation", None)
        if state is None or animation is None:
            return
        direction = state.move_direction
        if state.phase == self._last_phase and direction == self._last_facing:
            return
        self._last_phase = state.phase
        self._last_facing = direction
        template = (self.walk_format if state.phase == PHASE_MOVING
                    else self.idle_format)
        animation.start(template.format(direction))


def _drive_old_naming():
    body = Body()
    body.action_manager = Keys(*ALL_VERBS)
    compose(body, "player_input,topdown_move")
    control = _OldNaming()
    for count, held in WALK:
        body.action_manager.hold(*held)
        for _ in range(count):
            frame(body)
            control.update(body,
                           PyoneerEvent(GameEventType.UPDATE,
                                        data={"delta": 1.0}))


expect_raises("NEGATIVE CONTROL: naming idle from move_direction RAISES",
              PyoneerAssetMissingError, _drive_old_naming,
              "idle_none")

expect("the one default facing agrees with the animation handler's default",
       ANIMATION_DRIVE.param("idle_format").default.format(FACING_DEFAULT),
       GameAnimationHandler.DEFAULT_ANIMATION)
expect("...and that is the opening sequence the animator declares",
       ANIMATION_DRIVE.param("initial_sequence").default,
       GameAnimationHandler.DEFAULT_ANIMATION)
expect("the old sentinel is gone: no default names a sequence that raises",
       FACING_DEFAULT in Recorder.KNOWN[0].split("_")[1:] + ["down"], True)


# ===========================================================================
print("\n9. facing is NOT the displacement vocabulary, and here is the cost")
# ===========================================================================
expect("the four displacement verbs are exactly the gate's own keys",
       sorted(TOPDOWN_VERBS), sorted(DIRECTION_BITS))

# The measured defect the separation exists to fence off. BOTH halves on the
# same all-blocking field: a direction the gate knows is clamped, and one it
# does not is handed back untouched -- so an eight-way FACING leaking into
# `allowed_move` would travel through a wall with no error at all.
_gated = Body()
_gated.collision_field = SEALED
_gated.moveto((24.0, 24.0))
_known = _gated.allowed_move(Vector2(0.0, 10.0), "down")
_unknown = _gated.allowed_move(Vector2(10.0, 10.0), "down_right")
expect_true("a direction the gate knows is clamped by a BLOCK_ALL field",
            _known.y < 10.0)
expect("...while one it does not know passes through UNCLAMPED",
       tuple(_unknown), (10.0, 10.0))
_gated.state.facing = "down_right"
expect_true("which is legal on the record and must never reach the gate",
            _gated.state.facing not in DIRECTION_BITS)


# ===========================================================================
print("\n10. agency: input_bound de-conflates wiring from permission")
# ===========================================================================
from config.managers.core_asset_manager import CoreAssetManager    # noqa: E402

ANIMATIONS = CoreAssetManager().animations.get("entity")
MOVEMENT = {"movement": {"move_speed": 10, "sprint_mult": 3}}

_unwired = GamePlayer(input_=None, movement_config=MOVEMENT,
                      animation_config=ANIMATIONS)
_wired = GamePlayer(input_=Keys(*ALL_VERBS), movement_config=MOVEMENT,
                    animation_config=ANIMATIONS)
expect("a player built with no manager is not input-bound",
       _unwired.state.input_bound, False)
expect("...and one built with a manager is", _wired.state.input_bound, True)
expect("...while BOTH still report input as permitted, which is the point",
       (_unwired.state.enabled_inputs, _wired.state.enabled_inputs),
       (True, True))

# Two bits, not one: collapse "no manager" and "input taken away" into a
# single flag and a narrative system cannot tell RESTORING input from GRANTING
# it to a body that never had any.

_bound = Body()
_bound.action_manager = Keys(*ALL_VERBS).hold("right")
compose(_bound, "player_input,topdown_move")
frame(_bound)
expect("a bound, enabled, steerable body walks", _bound.transform.position.x,
       10.0)
_bound.state.input_bound = False
frame(_bound)
expect("...clearing input_bound stops it, and empties the intent",
       (_bound.transform.position.x, _bound.intent.right), (10.0, False))
_bound.state.input_bound = True
frame(_bound)
expect("...and restoring it starts the same body again",
       _bound.transform.position.x, 20.0)

# The other two terms of the gate, so no one of the three can be deleted with
# this section green.
_bound.state.enabled_inputs = False
frame(_bound)
expect("enabled_inputs gates it independently", _bound.transform.position.x,
       20.0)
_bound.state.enabled_inputs = True
_bound.state.steerable = False
frame(_bound)
expect("...and so does steerable", _bound.transform.position.x, 20.0)
_bound.state.steerable = True
frame(_bound)
expect("...with all three set, it moves again", _bound.transform.position.x,
       30.0)

# `simulated` is the whole-entity switch and still lives on GamePlayer, under
# the name that says what it does.
_frozen = GamePlayer(input_=Keys(*ALL_VERBS).hold("right"),
                     movement_config=MOVEMENT, animation_config=ANIMATIONS,
                     behaviors="player_input,topdown_move")
_frozen.state.simulated = False
frame(_frozen)
expect("simulated=False short-circuits the whole entity",
       _frozen.transform.position.x, 0.0)
_frozen.state.simulated = True
frame(_frozen)
expect("...and it is the same switch `active` used to be",
       _frozen.transform.position.x, 10.0)
_frozen.state.active = False
frame(_frozen)
expect("...reachable under the old name too", _frozen.transform.position.x,
       10.0)


# ===========================================================================
print("\n11. despawn_on names a REGISTERED action, and is refused otherwise")
# ===========================================================================
# `ActionIntent.fired` is documented never to raise on an unknown name, so an
# unaudited `despawn_on` was a body that could not die and said nothing about
# it -- the same silence a renamed token produces, which is why the audit
# exists at all. It runs in `__init__` and reads the registry's declared
# `writes`. BOTH halves are below: a gate proved only to refuse is this
# tree's dominant vacuous shape.

expect_raises("a despawn_on token nothing registers is refused",
              PyoneerConfigError,
              lambda: GameLifecycleMarkBehavior(despawn_on="interakt_action"),
              "interakt_action", "interact_action", "ACTION TOKEN")
expect_raises("...and so is a registered token that writes no action slot",
              PyoneerConfigError,
              lambda: GameLifecycleMarkBehavior(despawn_on="topdown_move"),
              "topdown_move", "attack_action")
expect_raises("...including action_relay, which READS firings and records none",
              PyoneerConfigError,
              lambda: GameLifecycleMarkBehavior(despawn_on="action_relay"),
              "action_relay")
expect_raises("...and an input VERB, the confusion the parameter warns about",
              PyoneerConfigError,
              lambda: GameLifecycleMarkBehavior(despawn_on="action"),
              "not an input verb")

# The permit half, at full width. An audit that refused everything would pass
# every line above, so every action the registry declares a writer for is
# constructed here -- and the audited set is measured against the ACTION specs
# rather than against the whole token list, which is what fails if the scan is
# ever widened to `BEHAVIOR_REGISTRY.keys()`.
expect("the audited set is the registry's action SLOTS, not its token list",
       _declared_action_tokens(),
       tuple(sorted(spec.name for spec in ACTION_SPECS)))
for _token in _declared_action_tokens():
    expect(f"...and {_token}, a declared action, is accepted",
           GameLifecycleMarkBehavior(despawn_on=_token).despawn_on, _token)
expect("an empty despawn_on stays legal -- the documented 'neither' form",
       (GameLifecycleMarkBehavior().despawn_on,
        GameLifecycleMarkBehavior(despawn_on="", lifetime_ms=250).lifetime_ms),
       ("", 250))

# WHY THE AUDIT IS NOT AT ATTACH, measured rather than argued. `build` keeps
# the AUTHORED token order, so this body attaches `lifecycle_mark` BEFORE the
# action it names; a sibling check at attach would refuse a legal map on the
# strength of where the author put a comma.
_authored = build(read_requests(
    {BEHAVIORS: "lifecycle_mark,interact_action",
     PARAM_PREFIX + "despawn_on": "interact_action"}, where="check_state"))
expect("build keeps the authored order, so lifecycle_mark attaches first",
       [b.name for b in _authored], ["lifecycle_mark", "interact_action"])
_early = Body()
_early.action_manager = Keys("action").tap("action")
_early.behaviors.attach_all(_authored)
frame(_early)
expect("...and that body still despawns on the action it named",
       _early.state.life, LIFE_GONE)
_quiet = Body()
_quiet.action_manager = Keys("action")
compose(_quiet, "lifecycle_mark,interact_action", despawn_on="interact_action")
frame(_quiet)
expect("...while an untapped verb leaves it alive, so the FIRING is the mark",
       _quiet.state.life, LIFE_ALIVE)


# ===========================================================================
print("\n12. summary")
# ===========================================================================
print(f"\nassertions             : {len(asserted)}")
print(f"axes on the record     : {sorted(BodyState().axes)}")
print(f"phases / supports      : {list(PHASES)} / {list(SUPPORTS)}")
_dupes = sorted({label for label in asserted if asserted.count(label) > 1})
if _dupes:
    print(f"  FAIL duplicate assertion labels: {_dupes}")
    failures.extend(_dupes)

if failures:
    print(f"\nFAILED ({len(failures)}):")
    for item in failures:
        print(f"  - {item}")
    raise SystemExit(1)
print("\nALL STATE CHECKS PASS")
