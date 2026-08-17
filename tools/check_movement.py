"""Verify the four concrete behaviors: input, top-down, platformer, animator.

The claims, every one of which the code is otherwise free to break with no
symptom until an entity silently stops doing something:

     1. the delta unit is milliseconds/60 and the conversion agrees with
        config/game.json, so a per-second number from a genre table is not
        16.7x wrong
     2. every declared parameter is a real constructor keyword, and the
        platformer's parameters are the actors table's own column names
     3. `jump` is bound, and the input behavior reads it as an EDGE
     4. an entity is the player iff it carries `player_input`; without one it
        reads the locked inert intent and cannot be steered
     5. top-down movement is what it was: eight directions, the last held verb
        faces, each held verb gated separately, sprint multiplies
     6. the animator fires on the CHANGE frame only, and its sequence naming
        is parameters rather than code
     7. the platformer falls, clamps at terminal velocity, lands, jumps,
        cannot double-jump, honours coyote time and stops at a wall
     8. composition comes off a tmx property mapping, runs in DECLARED order,
        and refuses a conflicting or duplicated list
     9. main.py's demo is composed from that same vocabulary
    10. an empty behavior set moves nothing, which is why this landed with no
        smoke drift

THE FIXTURES ARE THIS FILE'S OWN
--------------------------------
Every collision field below is built here from a few lines of ASCII.
`data/maps/test.tmx` is the author's canvas and is never read: a check that
pins map CONTENT goes red the next time he paints while the code it guards is
working perfectly, and that has cost this repo five red suites.

The platformer parameter DEFAULTS are deliberately NOT pinned against
`editor/genres/platformer/genre.json` -- retuning gravity is authoring, and a
check that goes red when a designer tunes a number is the same failure in a
different coat. The column NAMES and TYPES are pinned, because "consume the
table's own spelling, do not invent one" is a contract and not a taste.

    .venv/Scripts/python.exe tools/check_movement.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import inspect
import json
import sys

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

from scripts.core.collision_runtime import (BLOCK_ALL, EDGE_INSET, PASS_ALL,
                                            CollisionField)
from scripts.core.errors import PyoneerAssetMissingError, PyoneerConfigError
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.input import KEYBOARD, InputActionManager
from scripts.game.behavior import (BEHAVIOR_REGISTRY, BEHAVIORS, PARAM_PREFIX,
                                   build, read_requests, resolve, validate_list)
from scripts.game.behavior.input import NO_INTENT, PLAYER_INPUT, intent_of
from scripts.game.behavior.movement import (ANIMATION_DRIVE, MS_PER_DELTA,
                                            PLATFORMER_MOVE, SECONDS_PER_DELTA,
                                            TOPDOWN_MOVE, TOPDOWN_VERBS)
from scripts.game.entity.game_entity import GameEntity
from scripts.game.entity.game_player import GamePlayer, PlayerState

failures: list[str] = []
asserted: list[str] = []


def expect(label, got, want):
    asserted.append(label)
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<57} got={got!r} want={want!r}")
    if not ok:
        failures.append(label)


def expect_true(label, got):
    asserted.append(label)
    ok = bool(got)
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<57} got={got!r}")
    if not ok:
        failures.append(label)


def expect_close(label, got, want, tolerance=1e-6):
    asserted.append(label)
    ok = abs(float(got) - float(want)) <= tolerance
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<57} got={got!r} want~={want!r}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception, call, *fragments):
    """The call must raise, and the message must name each fragment.

    The fragments are the teeth: an assertion that checks only the exception
    TYPE passes for any raise anywhere inside the call, including a typo three
    frames down that has nothing to do with the claim.
    """
    asserted.append(label)
    try:
        call()
    except exception as exc:
        text = str(exc)
        missing = [f for f in fragments if f not in text]
        ok = not missing
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<57} "
              f"raised {type(exc).__name__}: {text.splitlines()[0][:54]}")
        if not ok:
            failures.append(f"{label} (message lacks {missing})")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<57} raised {type(exc).__name__} not "
              f"{exception.__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<57} did not raise")
    failures.append(label)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _RecordingAnimation:
    """A stand-in for GameAnimationHandler that records what it was asked for.

    Faithful in the one way that matters to a behavior: `start` RAISES for a
    sequence it does not know, exactly as the real handler does, which is the
    loud half of the pair whose quiet half is `move_direction` moving zero for
    a direction it does not know.

    A stub rather than the real handler so this whole check runs without the
    art -- the repository ships without `data/graphics` (see docs/ASSETS.md)
    and a movement check that cannot run in a fresh clone is a movement check
    nobody runs. The one section that does need a real spritesheet says so.
    """

    KNOWN = ("idle_up", "idle_down", "idle_left", "idle_right",
             "walk_up", "walk_down", "walk_left", "walk_right",
             "run_left", "run_right")

    def __init__(self):
        self.started: list[str] = []

    def start(self, name: str | None = None, from_beginning: bool = True):
        if name not in self.KNOWN:
            raise PyoneerAssetMissingError("animation", name,
                                           available=self.KNOWN)
        self.started.append(name)


class _Body(GameEntity):
    """The smallest concrete entity a movement behavior can drive.

    Carries the same `PlayerState` a GamePlayer does, because that is the
    record the movement behaviors write and the animator reads, and a check
    that invented its own would be asserting against a shape nothing ships.
    """

    def __init__(self, move_speed=10, sprint_mult=3, animation=True):
        super().__init__(movement_config={"movement": {
            "move_speed": move_speed, "sprint_mult": sprint_mult}})
        self.state = PlayerState()
        self.animation = _RecordingAnimation() if animation else None
        self.action_manager = None

    def core_lifecycle_build(self, event=None):
        pass

    def core_input_receive(self, event=None):
        pass


class _Keys:
    """A stand-in InputActionManager: exactly the three members a behavior uses.

    `actions` is a plain dict because that is what `attach` inspects to prove
    a verb is bound, and held/pressed are separate SETS so the difference
    between a hold and an edge is something this fixture can express -- a
    fixture where they were the same value could not tell a correct jump from
    the infinite-hover bug.
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

    def held(self, name):
        return name in self.down

    def pressed(self, name):
        return name in self.edge


ALL_VERBS = ("up", "down", "left", "right", "sprint", "jump")


def field(rows, tile=16, outside=BLOCK_ALL):
    """A CollisionField from ASCII: '#' blocks every direction, '.' is open."""
    masks = bytearray()
    for row in rows:
        for char in row:
            masks.append(BLOCK_ALL if char == "#" else PASS_ALL)
    return CollisionField(len(rows[0]), len(rows), bytes(masks),
                          tile_width=tile, tile_height=tile, outside=outside)


def compose(entity, tokens, **params):
    """Compose `entity` the way a spawned tmx object is composed.

    Goes through `read_requests` -> `build` -> `attach_all` with a property
    mapping shaped exactly like the one `spawn_objects` hands over, so this is
    the map's own path and not a private one that could drift from it.
    """
    properties = {BEHAVIORS: tokens}
    for key, value in params.items():
        properties[PARAM_PREFIX + key] = value
    entity.behaviors.attach_all(build(read_requests(
        properties, where="check_movement fixture")))
    return entity


def frame(entity, delta=1.0):
    """One frame, driven through the entity's own lifecycle entry point.

    `entity.core_frame_update(event)` and NOT `entity.behaviors.update(event)`:
    the wiring in `GameEntity.core_frame_update` is half of what this file
    claims, and a check that called the drive directly would keep passing with
    that method returned to `pass` -- which is to say with every composed
    entity in the engine silently inert.
    """
    entity.core_frame_update(PyoneerEvent(GameEventType.UPDATE,
                                          data={"delta": delta}))


# ===========================================================================
print("1. the delta unit, against the config that defines it")
# ===========================================================================
with open("config/game.json", encoding="utf-8") as fh:
    GAME_CONFIG = json.load(fh)

expect("one delta unit is target_tick_rate milliseconds",
       MS_PER_DELTA, float(GAME_CONFIG["target_tick_rate"]))
expect("seconds per delta is derived from it, never typed twice",
       SECONDS_PER_DELTA, MS_PER_DELTA / 1000.0)

# The end-to-end conversion, computed the way main.py computes delta. This is
# the assertion that catches a constant edited to a plausible-looking number:
# a real 60fps frame has to come back out as one sixtieth of a second.
_real_frame_ms = 1000.0 / 60.0
_delta = _real_frame_ms / float(GAME_CONFIG["target_tick_rate"])
expect_close("a real 60fps frame converts back to 1/60 of a second",
             _delta * SECONDS_PER_DELTA, 1.0 / 60.0, 1e-12)
expect_true("...and delta is NOT already seconds, by a factor of ~16.7",
            abs(_delta - 1.0 / 60.0) > 0.2)


# ===========================================================================
print("\n2. declared parameters are real constructor keywords")
# ===========================================================================
SPECS = (PLAYER_INPUT, TOPDOWN_MOVE, PLATFORMER_MOVE, ANIMATION_DRIVE)

for _spec in SPECS:
    # A behavior with no `__init__` of its own inherits object's, whose
    # signature is (*args, **kwargs) -- reading that as its keywords would let
    # a parameterless behavior claim two parameters it does not have.
    _init = _spec.factory.__init__
    _keywords = () if _init is object.__init__ else tuple(
        name for name, param in inspect.signature(_init).parameters.items()
        if name != "self"
        and param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY))
    expect(f"{_spec.name}: declared keys are exactly the ctor keywords",
           _spec.param_keys, _keywords)
    # `build` calls factory(**values); if the two above ever disagree this is
    # where Python says so, and it is the failure a spawned object would hit.
    _built = build((read_requests({BEHAVIORS: _spec.name},
                                  where="ctor check")[0],))
    expect(f"{_spec.name}: builds from its own defaults", len(_built), 1)
    expect(f"{_spec.name}: the instance is stamped with its spec",
           _built[0].spec.name, _spec.name)

expect("topdown_move deliberately declares no speed parameter",
       TOPDOWN_MOVE.params, ())
expect("...because GameEntity already owns move_speed from config",
       _Body(move_speed=17).move_speed, 17)

# The platformer's parameters ARE the actors table's columns. Not a private
# alias for them, not a renaming: the same spelling and the same type, so the
# six columns the genre pack has always declared stop being orphan data.
with open("editor/genres/platformer/genre.json", encoding="utf-8") as fh:
    GENRE = json.load(fh)
ACTORS = {f["name"]: f for table in GENRE["tables"] if table["name"] == "actors"
          for f in table["fields"]}
for _param in PLATFORMER_MOVE.params:
    expect(f"platformer_move consumes the actors column {_param.key!r}",
           (_param.key in ACTORS, ACTORS.get(_param.key, {}).get("type"),
            _param.source),
           (True, _param.type, "actors"))


# ===========================================================================
print("\n3. jump is bound, and it is read as an EDGE not a hold")
# ===========================================================================
with open("config/inputs.json", encoding="utf-8") as fh:
    INPUT_CONFIG = json.load(fh)
expect("'jump' is bound in config/inputs.json", "jump" in INPUT_CONFIG, True)

# Against the REAL manager, because the edge semantics under test are its own.
# The keyboard is faked so the result does not depend on what is physically
# held while the check runs.
_real = InputActionManager().prepare(INPUT_CONFIG)


class _FakeKeys:
    def __init__(self, down=()):
        self.down = {KEYBOARD[k] for k in down}

    def __getitem__(self, code):
        return code in self.down


def _advance(manager, down=()):
    manager.keyboard = _FakeKeys(down)
    for action in manager.actions.values():
        raw = manager._is_down(action)
        action.pressed = raw and not action.held
        action.released = action.held and not raw
        action.held = raw


_jumper = _Body()
_jumper.action_manager = _real
compose(_jumper, "player_input", jump_verb="jump")

_edges = []
for _hold in (["space"], ["space"], ["space"], [], ["space"]):
    _advance(_real, _hold)
    frame(_jumper)
    _edges.append(_jumper.intent.jump)
expect("a held jump key fires on the edge only, not every frame",
       _edges, [True, False, False, False, True])


# ===========================================================================
print("\n4. the player is whoever carries player_input")
# ===========================================================================
_no_input = _Body()
expect("an entity with no input behavior reads the shared inert intent",
       intent_of(_no_input) is NO_INTENT, True)
expect_raises("...which is locked, so one entity cannot arm every other",
              PyoneerConfigError, lambda: setattr(NO_INTENT, "right", True),
              "NO_INTENT", "right")
expect("...and it is still clear after that attempt",
       (NO_INTENT.right, NO_INTENT.jump, NO_INTENT.x), (False, False, 0))

# Handed a live manager and composed WITHOUT player_input: still inert. This
# is the assertion that retires main.py's open question -- holding a manager
# is not what makes an entity controllable, reading one is.
_holds_manager = _Body()
_holds_manager.action_manager = _Keys(*ALL_VERBS).hold("right")
compose(_holds_manager, "topdown_move")
frame(_holds_manager)
expect("an entity handed a manager but no input behavior does not move",
       tuple(_holds_manager.transform.position), (0.0, 0.0))

_driven = _Body()
_driven.action_manager = _Keys(*ALL_VERBS).hold("right")
compose(_driven, "player_input,topdown_move")
frame(_driven)
expect("the same entity WITH player_input moves", _driven.transform.position.x,
       10.0)

# An unbound verb is caught at composition time, naming it, rather than as a
# KeyError from inside a frame that takes every sibling entity down with it.
def _attach_unbound():
    body = _Body()
    body.action_manager = _Keys("up", "down", "left", "right")   # no sprint
    compose(body, "player_input")


expect_raises("a verb config/inputs.json does not bind raises at attach",
              PyoneerConfigError, _attach_unbound,
              "'sprint'", "player_input", "KeyError", "down, left, right, up")

_gated = _Body()
_gated.action_manager = _Keys(*ALL_VERBS).hold("right")
compose(_gated, "player_input,topdown_move")
_gated.state.can_move = False
frame(_gated)
expect("can_move gates the POLL, so a frozen player publishes nothing",
       (_gated.intent.right, _gated.transform.position.x), (False, 0.0))
_gated.state.can_move = True
_gated.state.enabled_inputs = False
frame(_gated)
expect("enabled_inputs gates it too", _gated.transform.position.x, 0.0)
_gated.state.enabled_inputs = True
frame(_gated)
expect("and clearing both gates lets the same entity move again",
       _gated.transform.position.x, 10.0)

_sprinter = _Body()
_sprinter.action_manager = _Keys(*ALL_VERBS).hold("right", "sprint")
compose(_sprinter, "player_input")
frame(_sprinter)
expect("the poll mirrors sprint onto PlayerState for anything that reads it",
       (_sprinter.intent.sprint, _sprinter.state.sprinting), (True, True))

_detached = _Body()
_detached.action_manager = _Keys(*ALL_VERBS).hold("right")
compose(_detached, "player_input,topdown_move")
frame(_detached)
_detached.behaviors.detach("player_input")
_before = _detached.transform.position.x
frame(_detached)
expect("detaching the input leaves a CLEAN intent, not the last one held",
       _detached.transform.position.x, _before)


# ===========================================================================
print("\n5. top-down movement is what it was")
# ===========================================================================
def _walker(hold=(), field_=None, **params):
    body = _Body()
    body.action_manager = _Keys(*ALL_VERBS).hold(*hold)
    body.collision_field = field_
    compose(body, "player_input,topdown_move", **params)
    return body


# Each axis probed ALONE. A (1,1) diagonal probe agrees with itself under a
# transposed x/y, so the diagonal is asserted separately and last.
for _verb, _want in (("right", (10.0, 0.0)), ("left", (-10.0, 0.0)),
                     ("down", (0.0, 10.0)), ("up", (0.0, -10.0))):
    _b = _walker([_verb])
    frame(_b)
    expect(f"holding {_verb} alone moves only that axis",
           tuple(_b.transform.position), _want)

_diag = _walker(["up", "right"])
frame(_diag)
expect("eight directions: up+right moves both axes at full speed",
       tuple(_diag.transform.position), (10.0, -10.0))
expect("...and the LAST verb in TOPDOWN_VERBS order decides the facing",
       _diag.state.move_direction, "right")
_diag2 = _walker(["up", "left"])
frame(_diag2)
expect("...which for up+left is left, not up",
       _diag2.state.move_direction, "left")
expect("TOPDOWN_VERBS is the order input_move polled in",
       TOPDOWN_VERBS, ("up", "down", "left", "right"))

_sprint = _walker(["right", "sprint"])
frame(_sprint)
expect("sprint multiplies by the entity's sprint_mult",
       _sprint.transform.position.x, 30.0)

_still = _walker([])
frame(_still)
expect("holding nothing moves nothing and records not moving",
       (tuple(_still.transform.position), _still.state.moving,
        _still.state.move_direction), ((0.0, 0.0), False, "none"))

# The movement gate, reached through move_direction -> allowed_move ->
# collision_runtime.allowed_distance. A blocked direction stops short of the
# boundary by EDGE_INSET and the other three are untouched.
WALL = field([
    "........",
    "........",
    "..#.....",     # cell (2,2) blocks everything
    "........",
    "........",
    "........",
    "........",
    "........",
])
_blocked = _walker(["right"], WALL)
_blocked.moveto((24.0, 40.0))            # cell (1,2), 8px short of the wall
frame(_blocked)
expect_close("a blocked direction stops AT the wall, not through it",
             _blocked.transform.position.x, 32.0 - EDGE_INSET, 1e-9)
expect_true("...and short of it, never on the blocked cell's edge",
            _blocked.transform.position.x < 32.0)

_open_dir = _walker(["down"], WALL)
_open_dir.moveto((24.0, 40.0))
frame(_open_dir)
expect("...while an unblocked direction from the same cell is untouched",
       tuple(_open_dir.transform.position), (24.0, 50.0))

# Each held verb is its OWN gated move. Collapsing the four into one (x, y)
# vector would make this pair identical, and it is not: with a wall on the
# left, holding left+right must travel right.
_both_free = _walker(["left", "right"])
_both_free.moveto((40.0, 40.0))
frame(_both_free)
expect("left+right with nothing in the way cancel out",
       _both_free.transform.position.x, 40.0)
_both_walled = _walker(["left", "right"], WALL)
_both_walled.moveto((48.0, 40.0))        # cell (3,2), wall at (2,2) to its left
frame(_both_walled)
expect("left+right with a wall on the LEFT travels right",
       _both_walled.transform.position.x, 58.0)


# ===========================================================================
print("\n6. the animator fires on the change frame, and names are parameters")
# ===========================================================================
_anim = _Body()
_anim.action_manager = _Keys(*ALL_VERBS)
compose(_anim, "player_input,topdown_move,animation_drive")
expect("attach plays the opening sequence, which used to be hardcoded",
       _anim.animation.started, ["idle_down"])

# TWO idle frames, because the animator only acts on a CHANGE and one frame
# from a fresh entity exercises neither branch of that test.
frame(_anim)
frame(_anim)
expect("two idle frames change nothing, so nothing is restarted",
       _anim.animation.started, ["idle_down"])

_anim.action_manager.hold("right")
frame(_anim)
expect("the frame movement starts names the walk sequence",
       _anim.animation.started, ["idle_down", "walk_right"])
frame(_anim)
frame(_anim)
expect("...and holding it does NOT restart the sequence every frame",
       _anim.animation.started, ["idle_down", "walk_right"])

_anim.action_manager.hold()
frame(_anim)
expect("releasing idles in the direction last faced",
       _anim.animation.started, ["idle_down", "walk_right", "idle_right"])

_named = _Body()
_named.action_manager = _Keys(*ALL_VERBS).hold("right")
compose(_named, "player_input,topdown_move,animation_drive",
        walk_format="run_{}", initial_sequence="idle_right")
frame(_named)
expect("the sequence naming is data: a sheet that says run_ gets run_",
       _named.animation.started, ["idle_right", "run_right"])

_unknown = _Body()
_unknown.action_manager = _Keys(*ALL_VERBS).hold("up")
compose(_unknown, "player_input,topdown_move,animation_drive",
        walk_format="strut_{}")
expect_raises("an unknown sequence RAISES -- the loud half of the pair",
              PyoneerAssetMissingError, lambda: frame(_unknown),
              "strut_up", "animation")


# ===========================================================================
print("\n7. the platformer body")
# ===========================================================================
FLOOR = field([
    "........",
    "........",
    "........",
    "........",
    "########",     # floor: top edge at y = 64
    "########",
    "########",
    "########",
])
LEDGE = field([
    "........",
    "........",
    "........",
    "........",
    "###.....",     # floor only under x < 48; open air beyond
    "........",
    "........",
    "........",
])
CEILING = field([
    "########",
    "########",     # ceiling: bottom edge at y = 32
    "........",
    "........",
    "########",
    "########",
    "########",
    "########",
])
WALL_AND_FLOOR = field([
    "........",
    "........",
    "........",
    "...#....",     # a wall at cell (3,3): its left edge is x = 48
    "########",
    "########",
    "########",
    "########",
])

PLATFORM = "player_input,platformer_move"


def _body(field_=FLOOR, at=(16.0, 16.0), hold=(), **params):
    body = _Body()
    body.action_manager = _Keys(*ALL_VERBS).hold(*hold)
    body.collision_field = field_
    compose(body, PLATFORM, jump_verb="jump", **params)
    body.moveto(at)
    return body


def _drop(body, limit=40):
    """Frame until it lands, or say so. Every loop here is BOUNDED.

    An unbounded `while not grounded` is a check that hangs instead of failing
    when the fixture is wrong, and a check that hangs is a check that gets
    removed from the roster.
    """
    for _ in range(limit):
        frame(body)
        if body.grounded:
            return body
    raise AssertionError("fixture never landed in %d frames" % limit)


# -- gravity and terminal velocity -----------------------------------------
_faller = _body(field_=None)              # ungated: nothing to land on
frame(_faller)
expect_close("one frame of gravity is g * seconds, not g * delta",
             _faller.velocity.y, 900.0 * SECONDS_PER_DELTA, 1e-9)
expect_close("...and the step it produces is that velocity * seconds",
             _faller.transform.position.y,
             16.0 + 900.0 * SECONDS_PER_DELTA * SECONDS_PER_DELTA, 1e-9)
_before_y = _faller.transform.position.y
for _ in range(4):
    frame(_faller)
expect_true("it keeps falling, faster each frame",
            _faller.transform.position.y - _before_y
            > _before_y - 16.0)

_terminal = _body(field_=None, max_fall_speed=100.0)
_peak = 0.0
for _ in range(40):
    frame(_terminal)
    _peak = max(_peak, _terminal.velocity.y)
expect("terminal velocity clamps and is never exceeded",
       (_terminal.velocity.y, _peak), (100.0, 100.0))

# -- landing ---------------------------------------------------------------
_lander = _drop(_body())
expect_true("it lands on the floor rather than falling through",
            _lander.grounded)
expect_close("...at the floor's top edge, one EDGE_INSET short of it",
             _lander.transform.position.y, 64.0 - EDGE_INSET, 1e-9)
expect("...with its downward velocity spent", _lander.velocity.y, 0.0)
frame(_lander)
expect_true("...and it stays grounded on the next frame", _lander.grounded)
expect_close("...without sinking a pixel into the floor",
             _lander.transform.position.y, 64.0 - EDGE_INSET, 1e-9)

# -- the jump, and the double jump that must not happen --------------------
_jump = _drop(_body())
_ground_y = _jump.transform.position.y
_jump.action_manager.tap("jump")
frame(_jump)
expect_true("a grounded jump sends it upward", _jump.velocity.y < 0.0)
expect_close("...at jump_velocity, negated because screen space is y-down",
             _jump.velocity.y, -320.0 + 900.0 * SECONDS_PER_DELTA, 1e-9)
expect_true("...and it leaves the ground", not _jump.grounded
            and _jump.transform.position.y < _ground_y)

# The key is still asking for a jump every frame. Nothing may answer until it
# lands. Asserted as "every airborne frame adds exactly gravity and nothing
# else" rather than as "velocity never DECREASED": a second jump that reset the
# velocity to the same launch value each frame would leave it flat, which a
# decrease test reads as fine and which is the hover bug in its purest form.
_series = [_jump.velocity.y]     # SEEDED with the launch frame's own value:
# a second jump fires on the very NEXT frame, so a series that started after it
# would show five perfectly ordinary gravity steps and miss the one that was
# not. This is the difference between the assertion and its decoy.
for _ in range(5):
    frame(_jump)
    _series.append(_jump.velocity.y)
_steps = [b - a for a, b in zip(_series, _series[1:])]
expect_true("holding jump mid-air cannot produce a second one",
            all(step > 0.0 for step in _steps))
expect_close("...because gravity is the only vertical force after the launch",
             min(_steps), 900.0 * SECONDS_PER_DELTA, 1e-9)
expect_close("...and the same on the last airborne frame as the first",
             max(_steps), 900.0 * SECONDS_PER_DELTA, 1e-9)

_jump.action_manager.tap()
for _ in range(60):
    frame(_jump)
    if _jump.grounded:
        break
expect_true("it comes back down and lands again", _jump.grounded)
_jump.action_manager.tap("jump")
frame(_jump)
expect_true("...and once landed the SAME entity may jump again",
            _jump.velocity.y < 0.0)

# -- coyote time -----------------------------------------------------------
# Walk off a real ledge rather than teleporting: `grounded` is recomputed from
# the field every frame, so a fixture that faked it would prove nothing about
# the clock that the fake replaced.
def _run_off_ledge(**params):
    """Land on the ledge, then walk right until the floor runs out.

    It falls with NO horizontal input and only then starts walking: an entity
    that drifts sideways under air control while falling arrives past the edge
    and lands on the field's own border instead, which is a fixture that
    proves something about the border rather than about coyote time.
    """
    body = _drop(_body(field_=LEDGE, at=(16.0, 16.0), **params))
    body.action_manager.hold("right")
    for _ in range(20):                  # bounded: see _drop
        frame(body)
        if not body.grounded:
            return body                  # the first airborne frame just ran
    raise AssertionError("the ledge fixture never walked off the ledge")


_coyote = _run_off_ledge()
expect_true("it is airborne with the coyote window still open",
            not _coyote.grounded and _coyote.coyote_left > 0.0)
_coyote.action_manager.tap("jump")
frame(_coyote)
expect_true("a jump inside the coyote window still counts",
            _coyote.velocity.y < 0.0)

_late = _run_off_ledge()
_late.action_manager.tap()
for _ in range(3):
    frame(_late)
expect("the window closes after coyote_ms of air time", _late.coyote_left, 0.0)
_falling = _late.velocity.y
_late.action_manager.tap("jump")
frame(_late)
expect_true("...and a jump after it does nothing at all",
            _late.velocity.y > _falling)

_strict = _run_off_ledge(coyote_ms=0)
_strict.action_manager.tap("jump")
_strict_before = _strict.velocity.y
frame(_strict)
expect_true("coyote_ms=0 is strict: no grace frame at all",
            _strict.velocity.y > _strict_before)

# -- walls and ceilings ----------------------------------------------------
_walled = _drop(_body(field_=WALL_AND_FLOOR, at=(16.0, 16.0)))
_walled.action_manager.hold("right")
for _ in range(20):
    frame(_walled)
expect_close("a wall stops horizontal motion at its edge",
             _walled.transform.position.x, 48.0 - EDGE_INSET, 1e-9)
expect("...and the body's horizontal velocity is spent, not accumulating",
       _walled.velocity.x, 0.0)

_ceiling = _body(field_=CEILING, at=(40.0, 40.0))
_ceiling.grounded = True                 # standing, about to jump into it
_ceiling.action_manager.tap("jump")
frame(_ceiling)
expect("a ceiling stops the rise exactly at its lower edge",
       _ceiling.transform.position.y, 32.0)
expect("...spending the upward velocity", _ceiling.velocity.y, 0.0)
expect("...without pretending the body has landed", _ceiling.grounded, False)

# -- air control -----------------------------------------------------------
def _airborne_step(air_control):
    body = _body(field_=None, hold=("right",), air_control=air_control)
    start = body.transform.position.x
    frame(body)
    return body.transform.position.x - start


_full = _airborne_step(1.0)
expect_close("air_control 0.5 moves exactly half as far as 1.0",
             _airborne_step(0.5), _full / 2.0, 1e-9)
expect("air_control 0.0 is no steering at all", _airborne_step(0.0), 0.0)
expect_close("...and 1.0 is move_speed * seconds",
             _full, 120.0 * SECONDS_PER_DELTA, 1e-9)


# ===========================================================================
print("\n8. composition: declared order, refused conflicts, one class")
# ===========================================================================
_ordered = _Body()
_ordered.action_manager = _Keys(*ALL_VERBS)
# Attached in the WRONG order deliberately. If run order were attach order the
# animator would read a movement state written after it, one frame stale.
_ordered.behaviors.attach_all(build(read_requests(
    {BEHAVIORS: "animation_drive,topdown_move,player_input"},
    where="order fixture")))
expect("run order is the DECLARED order, not the attach order",
       _ordered.behaviors.names,
       ("player_input", "topdown_move", "animation_drive"))
expect("the declared orders are the ones that produce it",
       tuple(b.spec.order for b in _ordered.behaviors), (10, 20, 80))

expect("the conflict is declared on BOTH sides",
       (TOPDOWN_MOVE.conflicts, PLATFORMER_MOVE.conflicts),
       (("platformer_move",), ("topdown_move",)))
# One side is enough to make the refusal work -- the test is symmetric -- so
# nothing above catches a spec that drops it. What it would break is the
# generated document, which would describe one of the pair as composable with
# the other. Declared on both, asserted on both.
expect_raises("a conflicting pair is refused when the list is read",
              PyoneerConfigError,
              lambda: validate_list("topdown_move,platformer_move"),
              "topdown_move", "platformer_move", "conflict")
def _attach_conflicting():
    body = _Body()
    compose(body, "topdown_move")
    body.behaviors.attach_all(build(read_requests({BEHAVIORS: "platformer_move"},
                                                  where="conflict fixture")))


expect_raises("...and again at attach, for a hand-composed entity",
              PyoneerConfigError, _attach_conflicting,
              "topdown_move", "platformer_move", "conflict")
expect_raises("a duplicated token is a typo, not a stack",
              PyoneerConfigError,
              lambda: validate_list("topdown_move,topdown_move"),
              "topdown_move", "twice")
expect_raises("an unknown token names itself and lists the table",
              PyoneerAssetMissingError,
              lambda: validate_list("platformer_movement"),
              "platformer_movement", "platformer_move", "player_input")

# Parameters off the property mapping, resolved most-specific-first. The
# override and the default are DIFFERENT values, so reading the wrong level
# cannot pass.
_tuned = _Body()
_tuned.collision_field = None
compose(_tuned, "platformer_move", gravity=250.0)
frame(_tuned)
expect_close("a pyoneer_param_ override reaches the constructed behavior",
             _tuned.velocity.y, 250.0 * SECONDS_PER_DELTA, 1e-9)
# The other level, measured through the same code path rather than read off
# the spec: an assertion that the default IS the default cannot fail, but one
# that the un-overridden sibling accelerates differently can.
_default_g = _Body()
_default_g.collision_field = None
compose(_default_g, "platformer_move")
frame(_default_g)
expect_true("...and an un-overridden sibling accelerates differently",
            _default_g.velocity.y != _tuned.velocity.y)
expect_close("...at the declared default, which is what actually runs",
             _default_g.velocity.y,
             resolve("platformer_move").param("gravity").default
             * SECONDS_PER_DELTA, 1e-9)
expect_raises("a wrongly typed parameter raises instead of quietly defaulting",
              PyoneerConfigError,
              lambda: read_requests({BEHAVIORS: "platformer_move",
                                     PARAM_PREFIX + "gravity": "900"},
                                    where="object 7"),
              "object 7", "pyoneer_param_gravity", "float")

# THE AUTHOR'S ACTUAL GOAL: a platformer player is the same class as a
# top-down one carrying a different list. Asserted on the real GamePlayer,
# which is the only place it can be false.
from config.managers.core_asset_manager import CoreAssetManager   # noqa: E402

ANIMATIONS = CoreAssetManager().animations.get("entity")
MOVEMENT = {"movement": {"move_speed": 10, "sprint_mult": 3}}
_manager = _Keys(*ALL_VERBS)
_top = GamePlayer(input_=_manager, movement_config=MOVEMENT,
                  animation_config=ANIMATIONS,
                  behaviors="player_input,topdown_move,animation_drive")
_side = GamePlayer(input_=_manager, movement_config=MOVEMENT,
                   animation_config=ANIMATIONS,
                   behaviors={BEHAVIORS: "player_input,platformer_move",
                              PARAM_PREFIX + "jump_verb": "jump"})
expect("a platformer player is the SAME class as a top-down one",
       (type(_top) is type(_side), type(_top).__name__), (True, "GamePlayer"))
expect("...differing only in the list each one carries",
       (_top.behaviors.names, _side.behaviors.names),
       (("player_input", "topdown_move", "animation_drive"),
        ("player_input", "platformer_move")))
expect("the behaviors= keyword is USED, unlike GameEntity's transform= which "
       "is discarded", len(_side.behaviors), 2)
expect("...and the parameter it carried reached the instance",
       _side.behaviors.get("player_input").jump_verb, "jump")
expect("a GamePlayer that declares nothing composes nothing",
       len(GamePlayer(input_=None, movement_config=MOVEMENT,
                      animation_config=ANIMATIONS).behaviors), 0)


# ===========================================================================
print("\n9. main.py's demo is composed from that same vocabulary")
# ===========================================================================
import main as main_module                                        # noqa: E402

expect("main.py's player list resolves, token by token",
       validate_list(main_module.PLAYER_BEHAVIORS),
       ("player_input", "topdown_move", "animation_drive"))
expect("main.py's scenery list resolves too",
       validate_list(main_module.SCENERY_BEHAVIORS),
       ("topdown_move", "animation_drive"))
expect("the demo's player is the one carrying player_input",
       ("player_input" in validate_list(main_module.PLAYER_BEHAVIORS),
        "player_input" in validate_list(main_module.SCENERY_BEHAVIORS)),
       (True, False))
expect("the two lists differ by exactly that one token",
       tuple(t for t in validate_list(main_module.PLAYER_BEHAVIORS)
             if t not in validate_list(main_module.SCENERY_BEHAVIORS)),
       ("player_input",))


# ===========================================================================
print("\n10. an empty behavior set moves nothing")
# ===========================================================================
_inert = _Body()
_inert.moveto((123.0, 45.0))
for _ in range(10):
    frame(_inert)
expect("ten frames of an empty set leave the entity exactly where it was",
       (tuple(_inert.transform.position), len(_inert.behaviors)),
       ((123.0, 45.0), 0))
expect("...which is the state every entity in the shipped tree is in",
       _inert.behaviors.names, ())

# The drive is reached through the lifecycle method, not only through the set.
_wired = _Body()
_wired.action_manager = _Keys(*ALL_VERBS).hold("down")
compose(_wired, "player_input,topdown_move")
_wired.core_frame_update(PyoneerEvent(GameEventType.UPDATE,
                                      data={"delta": 1.0}))
expect("GameEntity.core_frame_update is what drives the set",
       _wired.transform.position.y, 10.0)

_reported = _Body()
_reported.action_manager = None
compose(_reported, "player_input")
expect("a behavior reports an unmet requirement instead of refusing to attach",
       _reported.behaviors.missing_requirements(),
       (("player_input", "action_manager"),))


# ===========================================================================
print("\n11. the gates, both sides -- and the halves nothing else probes")
# ===========================================================================
# Every assertion below covers a line that a mutation pass flipped with the
# whole suite staying green. Each one is one HALF of an invariant whose other
# half was already tested, which is the shape a toothless check takes here:
# the gate is proved to let movement through and never proved to stop it.

# The clear-before-gate ordering. The existing gate test sets can_move False
# on the FIRST frame, where the intent is already zero, so moving
# `intent.clear()` below the gate reads identically. The failure only appears
# mid-walk: the last intent stays standing and the entity walks forever in
# the direction it was heading when it was frozen.
_frozen = _Body()
_frozen.action_manager = _Keys(*ALL_VERBS).hold("right")
compose(_frozen, "player_input,topdown_move")
frame(_frozen)
expect("a walking entity has a live intent", _frozen.intent.right, True)
_frozen.state.can_move = False
frame(_frozen)
expect("...and freezing it mid-walk ZEROES that intent, not just the movement",
       (_frozen.intent.right, _frozen.intent.moving), (False, False))
expect("...so it stops where it was", _frozen.transform.position.x, 10.0)

# The EDGE half of the attach-time verb audit. The existing unbound test omits
# `sprint`, which is a HELD verb, so `+ self.edge_verbs` can be deleted with
# the suite green -- and `jump` is the binding this work added.
def _attach_unbound_edge():
    body = _Body()
    body.action_manager = _Keys("up", "down", "left", "right", "sprint")
    compose(body, "player_input", jump_verb="jump")


expect_raises("an unbound EDGE verb raises at attach too, not just a held one",
              PyoneerConfigError, _attach_unbound_edge,
              "'jump'", "player_input", "KeyError")

# An empty verb name is a DOCUMENTED capability -- `sprint_verb` says "Empty
# disables sprinting for this entity" and `jump_verb` defaults to "". Without
# the `if v` filter the empty string reaches the audit and every entity using
# the documented form raises.
_no_sprint = _Body()
_no_sprint.action_manager = _Keys("up", "down", "left", "right")
compose(_no_sprint, "player_input", sprint_verb="")
_no_sprint.action_manager.hold("right")
frame(_no_sprint)
expect("an empty verb name disables that poll instead of demanding a binding",
       (_no_sprint.intent.sprint, _no_sprint.intent.right), (False, True))

# MoveIntent.x is what the platformer body reads. Both horizontal verbs held
# must CANCEL; adding instead of subtracting doubles the walk speed and the
# top-down left+right test cannot see it, because that one reads booleans.
_axis = _Body()
_axis.action_manager = _Keys(*ALL_VERBS).hold("left", "right")
compose(_axis, "player_input")
frame(_axis)
expect("both horizontal verbs held cancel on the axis the platformer reads",
       _axis.intent.x, 0)
_axis.action_manager.hold("right")
frame(_axis)
expect("...and one alone is a unit in that direction", _axis.intent.x, 1)

# The animator's DIRECTION half. `moving` changing is tested; turning while
# still moving is not, and without it a player who turns keeps playing the
# sequence for the way they used to be facing.
_turn = _Body()
_turn.action_manager = _Keys(*ALL_VERBS).hold("left")
compose(_turn, "player_input,topdown_move,animation_drive")
frame(_turn)
_turn.action_manager.hold("right")
frame(_turn)
expect("turning while still moving re-fires the animator",
       _turn.animation.started[-1], "walk_right")

# `state.active` is the one gate GamePlayer still owns after the extraction,
# and the file's docstring names it. Asserted on the real class.
_inactive = GamePlayer(input_=_Keys(*ALL_VERBS).hold("right"),
                       movement_config=MOVEMENT,
                       animation_config=ANIMATIONS,
                       behaviors="player_input,topdown_move")
_inactive.state.active = False
_inactive.core_frame_update(PyoneerEvent(GameEventType.UPDATE,
                                         data={"delta": 1.0}))
expect("state.active still short-circuits the whole entity",
       _inactive.transform.position.x, 0.0)
_inactive.state.active = True
_inactive.core_frame_update(PyoneerEvent(GameEventType.UPDATE,
                                         data={"delta": 1.0}))
expect_true("...and clearing it lets the same player move",
            _inactive.transform.position.x > 0.0)


# ===========================================================================
print("\n12. the wire: a map object's list reaches a live entity")
# ===========================================================================
# The tmx property is the DECLARATION SITE the design chose, and a declaration
# site nothing reads is a format, not a feature. This drives the real
# `spawn_objects` over a fixture map written here -- `data/maps/test.tmx` is
# the author's canvas, and a check that pinned its content would go red the
# next time he paints while the code it guards works perfectly.

import os
import tempfile

from scripts.loaders.map_loader import spawn_objects

_SPAWN_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="4" height="4" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="3" nextobjectid="4">
 <objectgroup id="2" name="entity">
  <object id="1" name="hero" type="Probe" x="0" y="0" width="16" height="16">
   <properties>
    <property name="pyoneer_behaviors" value="player_input,topdown_move"/>
   </properties>
  </object>
  <object id="2" name="decoy" type="Probe" x="32" y="0" width="16" height="16">
   <properties>
    <property name="pyoneer_behaviors" value="topdown_move"/>
   </properties>
  </object>
  <object id="3" name="scenery" type="Probe" x="64" y="0" width="16" height="16"/>
 </objectgroup>
</map>
"""

_workspace = tempfile.mkdtemp(prefix="pyoneer_behavior_")


def _fixture(name, text):
    path = os.path.join(_workspace, name)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


_spawned = spawn_objects(_fixture("behaviors.tmx", _SPAWN_FIXTURE),
                         {"Probe": _Body})
expect("every object spawns, whether or not it declares behaviors",
       len(_spawned), 3)
expect("the declared list is carried off the map, in authored order",
       tuple(r.spec.name for r in _spawned[0].behaviors),
       ("player_input", "topdown_move"))
expect("an object declaring nothing carries nothing, not a default",
       _spawned[2].behaviors, ())

# ...and those records become live behaviors that actually drive the entity.
# All three are handed the SAME manager, so what separates them is composition
# alone -- which is the claim the whole design rests on.
for _record in _spawned:
    _record.entity.action_manager = _Keys(*ALL_VERBS).hold("right")
    if _record.behaviors:
        _record.entity.behaviors.attach_all(build(_record.behaviors))
# Measured as a DELTA from where the map put each one, not against a literal:
# the fixture spawns them at three different x, and pinning the absolute value
# would make this assert the fixture's coordinates rather than the movement.
_before = [r.entity.transform.position.x for r in _spawned]
for _record in _spawned:
    frame(_record.entity)
_moved = [r.entity.transform.position.x - x
          for r, x in zip(_spawned, _before)]
expect("the object carrying player_input is the one that moves", _moved[0],
       10.0)
expect("...one with a body but no input holds a manager and stays put",
       _moved[1], 0.0)
expect("...and one carrying nothing composes nothing",
       len(_spawned[2].entity.behaviors), 0)

# An authoring error on the map raises AT LOAD, naming the object, rather than
# arriving later as something indistinguishable from a physics bug.
expect_raises("two conflicting bodies on one object raise at spawn, named",
              PyoneerConfigError,
              lambda: spawn_objects(
                  _fixture("conflict.tmx",
                           _SPAWN_FIXTURE.replace(
                               "player_input,topdown_move",
                               "topdown_move,platformer_move")),
                  {"Probe": _Body}),
              "topdown_move", "platformer_move", "id=1")
expect_raises("a mistyped token raises at spawn rather than doing nothing",
              PyoneerAssetMissingError,
              lambda: spawn_objects(
                  _fixture("typo.tmx",
                           _SPAWN_FIXTURE.replace(
                               "player_input,topdown_move",
                               "player_input,topdown_mvoe")),
                  {"Probe": _Body}),
              "topdown_mvoe")


# ===========================================================================
print("\n13. summary")
# ===========================================================================
print(f"assertions             : {len(asserted)}")
print(f"registry               : {sorted(BEHAVIOR_REGISTRY)}")
print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for item in failures:
        print(f"  - {item}")
    sys.exit(1)
print("ALL MOVEMENT CHECKS PASS")
