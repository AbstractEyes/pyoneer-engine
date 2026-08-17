"""Verify the action component system: the edge, the clock, and the record.

The claims, each one a line the code is otherwise free to break with no
symptom until an entity silently stops -- or never stops -- doing something:

     1. an action is a behavior like any other: registered, ordered, and its
        declared `writes` names the slot it actually records into
     2. it reaches the event bus at ZERO points, proved from the parse tree
        rather than from `binds` being empty (which passes trivially forever)
     3. the record is a slot per action, so four actions in one `order`
        window cannot erase each other, and the shared inert one is locked
     4. a firing is an EDGE -- it fires on the pressed frame and does NOT
        fire on the next frame while the key is still down
     5. `cooldown_ms` stops a firing DURING the window and lets one through
        after it, driven by a synthetic delta and never by sleeping
     6. `once` fires exactly one time across more than a hundred frames
     7. an unbound verb raises AT ATTACH naming the verb, a bound one
        attaches, and the refused behavior is not left half-attached
     8. an empty verb polls nothing -- proved against a manager that would
        KeyError if it were indexed at all
     9. `enabled_inputs` suppresses a firing and `can_move` deliberately does
        NOT: a body frozen for a cutscene may still press "continue"
    10. the relay CALLS its sink and never dispatches, and stays silent on a
        frame where nothing fired
    11. every verb a registered spec defaults to is bound in the real
        config/inputs.json, and no two verbs share a physical binding

EVERY ASSERTION IS A PAIR
-------------------------
The standing correction on this repo is that a gate gets proved to let
something through and never proved to stop it, so each rule above is written
as two assertions with opposite expectations. The pairs that matter most are
marked BOTH HALVES in the source, and the mutation table in the summary
records what each one turned red for.

THE FIXTURES ARE THIS FILE'S OWN
--------------------------------
`data/maps/test.tmx` is the author's canvas and is never read; the one map
this file needs is written into a tempdir. `config/inputs.json` IS read, but
only to assert a claim about the CODE agreeing with the CONFIG -- that a
verb a spec defaults to is bound -- never to pin which key it is bound to.

    .venv/Scripts/python.exe tools/check_action.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import ast
import dataclasses
import inspect
import json
import os
import sys
import tempfile

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

from scripts.core.errors import PyoneerAssetMissingError, PyoneerConfigError
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.input import KEYBOARD, InputActionManager
from scripts.game.behavior import (BEHAVIOR_REGISTRY, BEHAVIORS, PARAM_PREFIX,
                                   BehaviorSpec, EntityBehavior, build,
                                   read_requests, resolve, validate_list)
from scripts.game.behavior.action import (ACTION_RELAY, ACTION_SPECS,
                                          ATTACK_ACTION, INTERACT_ACTION,
                                          NO_ACTIONS, ORDER, PAUSE_ACTION,
                                          RELAY_ORDER, SLOT_PREFIX,
                                          ActionFired, ActionIntent,
                                          GameActionInputBehavior,
                                          GameActionRelayBehavior, actions_of,
                                          require_verbs)
from scripts.game.behavior.movement import MS_PER_DELTA
from scripts.game.entity.game_entity import GameEntity
from scripts.game.entity.game_player import PlayerState

ROOT = _bootstrap.REPO_ROOT
ACTION_SOURCE = os.path.join(ROOT, "scripts", "game", "behavior", "action.py")

failures: list[str] = []
asserted: list[str] = []


def expect(label, got, want):
    asserted.append(label)
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<60} got={got!r} want={want!r}")
    if not ok:
        failures.append(label)


def expect_true(label, got):
    asserted.append(label)
    ok = bool(got)
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<60} got={got!r}")
    if not ok:
        failures.append(label)


def expect_close(label, got, want, tolerance=1e-6):
    asserted.append(label)
    ok = abs(float(got) - float(want)) <= tolerance
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<60} got={got!r} want~={want!r}")
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
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<60} "
              f"raised {type(exc).__name__}: {text.splitlines()[0][:46]}")
        if not ok:
            failures.append(f"{label} (message lacks {missing})")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<60} raised {type(exc).__name__} not "
              f"{exception.__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<60} did not raise")
    failures.append(label)


def expect_no_raise(label, call):
    """The other half of every `expect_raises`. Returns whatever the call did.

    Written as its own helper because "it raised for the bad input" is half an
    invariant, and the half this repo keeps losing is "and it did NOT raise
    for the good one".
    """
    asserted.append(label)
    try:
        value = call()
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<60} raised {type(exc).__name__}: {exc}")
        failures.append(label)
        return None
    print(f"  ok   {label:<60} returned cleanly")
    return value


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _Slot:
    __slots__ = ("held", "pressed", "released")

    def __init__(self):
        self.held = False
        self.pressed = False
        self.released = False


class _Keys:
    """A stand-in InputActionManager with the ONE property that matters here.

    `held`/`pressed` are UNGUARDED dict indexes, exactly as the real manager's
    are. That is not incidental faithfulness: the whole reason an action
    audits its verb at attach is that an unbound one would KeyError from
    inside a frame, and a fixture that answered False for an unknown verb
    could not tell a working audit from a deleted one.
    """

    def __init__(self, *verbs):
        self.actions = {v: _Slot() for v in verbs}

    def tap(self, *verbs):
        """Set this frame's rising edges. Everything else goes quiet."""
        for name, slot in self.actions.items():
            slot.pressed = name in verbs
        return self

    def hold(self, *verbs):
        for name, slot in self.actions.items():
            slot.held = name in verbs
        return self

    def pressed(self, name):
        return self.actions[name].pressed

    def held(self, name):
        return self.actions[name].held


class _Body(GameEntity):
    """The smallest concrete entity an action behavior can be composed onto.

    Carries the same `PlayerState` a GamePlayer does, because the two gates
    under test (`enabled_inputs`, `can_move`) live on that record and a check
    that invented its own would be asserting against a shape nothing ships.
    """

    def __init__(self, *verbs, state=True):
        super().__init__(movement_config={"movement": {
            "move_speed": 10, "sprint_mult": 3}})
        self.state = PlayerState() if state else None
        self.action_manager = _Keys(*verbs) if verbs else _Keys()
        self.action_sink = None

    def core_lifecycle_build(self, event=None):
        pass

    def core_input_receive(self, event=None):
        pass


class _Watcher(EntityBehavior):
    """Reads the action record at order 20 -- where a movement body reads it.

    Exists to make the ORDER WINDOW measurable. A dash is an action a movement
    behavior consumes on the same frame it fires, and that is only true while
    the action polls at a LOWER order than the body. Moving the action's order
    above 20 leaves every declaration identical and every other assertion
    green, and this is the one that goes red.
    """

    def __init__(self):
        self.seen: list[tuple[str, ...]] = []

    def update(self, entity, event):
        self.seen.append(actions_of(entity).fired_names)


WATCHER_SPEC = BehaviorSpec(name="watch_actions", summary="check fixture",
                            factory=_Watcher, writes=("watch.seen",), order=20)


class _Sink:
    """Records every (entity, fired) pair the relay hands over."""

    def __init__(self):
        self.calls: list[tuple[str, ActionFired]] = []

    def __call__(self, entity, fired):
        self.calls.append((type(entity).__name__, fired))


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
        properties, where="check_action fixture")))
    return entity


MISSING = ActionFired("<nothing fired>", "<nothing fired>", "<nothing fired>")


def fired_or_missing(intent, name):
    """The firing, or a sentinel that fails an assertion instead of crashing.

    A run where the firing is absent is a run this file is supposed to
    REPORT. Reading `.name` off a bare None turns that report into an
    AttributeError three sections early, and every assertion after it
    silently never runs -- which is how a broken suite gets mistaken for a
    short one.
    """
    return intent.fired(name) or MISSING


def frame(entity, delta=1.0):
    """One frame, driven through the entity's own lifecycle entry point.

    `entity.core_frame_update(event)` and NOT `entity.behaviors.update(event)`:
    the wiring in `GameEntity.core_frame_update` is half of what an action
    system claims, and a check that called the drive directly would keep
    passing with that method returned to `pass` -- which is to say with every
    composed entity in the engine silently inert.
    """
    entity.core_frame_update(PyoneerEvent(GameEventType.UPDATE,
                                          data={"delta": delta}))


MS_PER_FRAME = MS_PER_DELTA          # one frame at delta=1.0, in milliseconds


# ===========================================================================
print("1. an action is an ordinary behavior, and `writes` names the real slot")
# ===========================================================================
expect("the three polling actions are registered under their own tokens",
       tuple(s.name for s in ACTION_SPECS),
       ("attack_action", "interact_action", "pause_action"))
for _spec in ACTION_SPECS + (ACTION_RELAY,):
    expect(f"{_spec.name}: the shipped registry resolves it",
           resolve(_spec.name) is _spec, True)
    expect(f"{_spec.name}: it declares no event-bus binding",
           _spec.binds, ())

# Declared keys are real constructor keywords. `build` calls factory(**values),
# so a drift between the two is a TypeError the first time a map spawns an
# object -- this is where Python says so first.
for _spec in ACTION_SPECS:
    _init = _spec.factory.__init__
    _keywords = tuple(
        name for name, param in inspect.signature(_init).parameters.items()
        if name != "self"
        and param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY))
    expect(f"{_spec.name}: declared keys are exactly the ctor keywords",
           _spec.param_keys, _keywords)
    expect(f"{_spec.name}: every parameter is per-object",
           tuple({p.source for p in _spec.params}), ("object",))

expect("all three poll in the same order window",
       tuple({s.order for s in ACTION_SPECS}), (ORDER,))
expect("...which sits between the movement intent and the body that reads it",
       (resolve("player_input").order < ORDER,
        ORDER < resolve("topdown_move").order), (True, True))
expect("the relay runs after the animator, last of everything",
       (RELAY_ORDER > resolve("animation_drive").order,
        ACTION_RELAY.order), (True, RELAY_ORDER))

# BOTH HALVES of the `writes` claim. Declaring the string is half; the other
# half is that the behavior records into THAT slot and no other, which is
# measured by firing one and reading the record back by the declared name.
for _spec in ACTION_SPECS:
    _probe = _Body(_spec.param("verb").default)
    compose(_probe, _spec.name)
    _probe.action_manager.tap(_spec.param("verb").default)
    frame(_probe)
    _slot = _spec.writes[0][len(SLOT_PREFIX):]
    expect(f"{_spec.name}: writes names one slot under the record",
           (len(_spec.writes), _spec.writes[0].startswith(SLOT_PREFIX)),
           (1, True))
    expect(f"{_spec.name}: ...and the firing lands in exactly that slot",
           (_probe.action_intent.fired_names, _slot in _probe.action_intent),
           ((_slot,), True))
expect("the relay writes nothing on the entity at all", ACTION_RELAY.writes, ())


# ===========================================================================
print("\n2. the action system reaches the event bus at zero points")
# ===========================================================================
# `binds == ()` is asserted above and passes trivially forever. This is the
# half with teeth: the module's PARSE TREE, so the docstring that explains why
# it never dispatches does not itself trip the scan.
with open(ACTION_SOURCE, encoding="utf-8") as _fh:
    _TREE = ast.parse(_fh.read())

_BUS_CALLS = {"handle", "mark_event_handled", "send_event", "send_event_advanced",
              "send_event_to_self", "bind_listener", "bind_sync_listener",
              "bind_async_listener"}
_called = sorted({
    node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
    for node in ast.walk(_TREE)
    if isinstance(node, ast.Call)
    and isinstance(node.func, (ast.Attribute, ast.Name))
    and (node.func.attr if isinstance(node.func, ast.Attribute)
         else node.func.id) in _BUS_CALLS})
expect("no bus call appears anywhere in the module's code", _called, [])

_imports = sorted({node.module or "" for node in ast.walk(_TREE)
                   if isinstance(node, ast.ImportFrom)}
                  | {alias.name for node in ast.walk(_TREE)
                     if isinstance(node, ast.Import) for alias in node.names})
expect("...and it imports no event module, so it could not construct one",
       [m for m in _imports if "event" in m or "component" in m], [])
# The other half: the scan is capable of finding one. A scan that matched
# nothing because the name list was wrong would look identical to a clean pass.
_DECOY = ast.parse("class X:\n    def go(self, e):\n        e.handle()\n")
expect("...and the same scan DOES find a bus call when one is there",
       sorted({n.func.attr for n in ast.walk(_DECOY)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in _BUS_CALLS}), ["handle"])
expect("scripts/ imports no editor module here either",
       [m for m in _imports if m.startswith("editor")], [])


# ===========================================================================
print("\n3. the record: one slot per action, and the inert one is locked")
# ===========================================================================
_quiet = _Body()
expect("an entity with no action behavior reads the shared inert record",
       actions_of(_quiet) is NO_ACTIONS, True)
expect("...which reports nothing fired, and no slots at all",
       (len(NO_ACTIONS), NO_ACTIONS.fired_names, NO_ACTIONS.slots),
       (0, (), ()))

# BOTH HALVES of the lock. Reading it works; every one of the three mutators
# refuses, and so does a raw attribute write.
expect_raises("record() on the shared inert one raises", PyoneerConfigError,
              lambda: NO_ACTIONS.record("attack_action",
                                        ActionFired("attack_action", "attack")),
              "NO_ACTIONS", "attack_action")
expect_raises("clear() on it raises too", PyoneerConfigError,
              lambda: NO_ACTIONS.clear("attack_action"), "NO_ACTIONS")
expect_raises("release() on it raises too", PyoneerConfigError,
              lambda: NO_ACTIONS.release("attack_action"), "NO_ACTIONS")
expect_raises("...and so does a raw attribute write", PyoneerConfigError,
              lambda: setattr(NO_ACTIONS, "_fired", {}), "NO_ACTIONS")
expect("...and it is still empty after all four attempts",
       (len(NO_ACTIONS), NO_ACTIONS.slots), (0, ()))
# The half that proves the lock is a LOCK and not a broken class: an unlocked
# record accepts every one of those calls.
_free = ActionIntent()
expect_no_raise("an unlocked record accepts the same three calls",
                lambda: (_free.clear("a"),
                         _free.record("a", ActionFired("a", "v")),
                         _free.release("a")))

# A slot that exists and is empty means "composed, did not fire"; no slot at
# all means "not composed". Two different questions, both answerable.
_three = _Body("attack", "action", "pause")
compose(_three, "attack_action,interact_action,pause_action")
expect("attach allocates one empty slot per composed action",
       (_three.action_intent.slots, _three.action_intent.fired_names),
       (("attack_action", "interact_action", "pause_action"), ()))
_three.action_manager.tap("attack")
frame(_three)
expect("one verb fires exactly one slot and leaves the siblings empty",
       (_three.action_intent.fired_names, len(_three.action_intent)),
       (("attack_action",), 1))
_three.action_manager.tap("attack", "pause")
frame(_three)
expect("...and two at once fire two, neither erasing the other",
       _three.action_intent.fired_names, ("attack_action", "pause_action"))

# The report is SORTED, not in attach order. Two entities carrying the same
# actions must answer the same way whatever sequence they were composed in.
_forward = _Body("attack", "pause")
compose(_forward, "attack_action,pause_action")
_reverse = _Body("attack", "pause")
compose(_reverse, "pause_action,attack_action")
_forward.action_manager.tap("attack", "pause")
_reverse.action_manager.tap("attack", "pause")
frame(_forward)
frame(_reverse)
expect("the report does not depend on the order the actions attached",
       (_forward.action_intent.fired_names, _reverse.action_intent.fired_names),
       (("attack_action", "pause_action"), ("attack_action", "pause_action")))

# The firing itself is frozen: a consumer at order 90 cannot alter what a
# consumer at order 20 already read.
_record = fired_or_missing(_forward.action_intent, "attack_action")
expect("a firing names its behavior token and the verb that produced it",
       (_record.name, _record.verb), ("attack_action", "attack"))
expect_raises("...and it is frozen", dataclasses.FrozenInstanceError,
              lambda: setattr(_record, "name", "other"))
expect("...while reading it is unimpeded", _record.payload, "")
expect("a payload authored on the object reaches the record",
       compose(_Body("attack"), "attack_action",
               payload="door_north").behaviors.get("attack_action").payload,
       "door_north")

# One class, three tokens: each instance knows its own name, which is what
# keys its slot. Reading the name off the CLASS stamp would give all three the
# first registration's name and silently collapse them into one slot.
# An entity that was handed the shared inert record -- which is exactly what a
# caller does by writing back what `actions_of` returned -- must be given its
# own on attach. Writing to the locked one would raise on the first frame, on
# an entity nobody thinks of as having input.
_borrowed = _Body("attack")
_borrowed.action_intent = NO_ACTIONS
expect_no_raise("an entity holding the inert record is given its own at attach",
                lambda: compose(_borrowed, "attack_action"))
_borrowed.action_manager.tap("attack")
frame(_borrowed)
expect("...and it fires into that private one, not into the shared one",
       (_borrowed.action_intent is NO_ACTIONS,
        "attack_action" in _borrowed.action_intent, len(NO_ACTIONS)),
       (False, True, 0))

expect("three tokens off one factory class produce three distinct names",
       (tuple(b.name for b in _three.behaviors),
        len({type(b) for b in _three.behaviors})),
       (("attack_action", "interact_action", "pause_action"), 1))


# ===========================================================================
print("\n4. a firing is an EDGE, both halves")
# ===========================================================================
# Half one against the FIXTURE manager, so the behavior's own logic is under
# test; half two against the REAL InputActionManager, so the edge semantics
# being relied on are the manager's and not the fixture's.
_edge = _Body("attack")
compose(_edge, "attack_action")
_edge.action_manager.tap("attack")
frame(_edge)
expect("it fires on the frame the verb goes down", "attack_action" in
       _edge.action_intent, True)
# Still held, no new rising edge: the manager reports pressed=False.
_edge.action_manager.tap()
_edge.action_manager.hold("attack")
frame(_edge)
expect("...and does NOT fire again while the key is still down",
       (_edge.action_intent.fired_names, _edge.action_intent.slots),
       ((), ("attack_action",)))

with open(os.path.join(ROOT, "config", "inputs.json"), encoding="utf-8") as _fh:
    REAL_CONFIG = json.load(_fh)
_real = InputActionManager().prepare(REAL_CONFIG)


class _FakeKeys:
    def __init__(self, down=()):
        self.down = {KEYBOARD[k] for k in down}

    def __getitem__(self, code):
        return code in self.down


def _advance(manager, down=()):
    """The three lines `InputActionManager.update` runs, off a fake keyboard.

    Not `manager.update()`: that re-reads pygame.key.get_pressed(), so
    whatever is physically held while the check runs would decide the result.
    """
    manager.keyboard = _FakeKeys(down)
    for action in manager.actions.values():
        raw = manager._is_down(action)
        action.pressed = raw and not action.held
        action.released = action.held and not raw
        action.held = raw


# The key is derived from the spec's own default verb, never named here: this
# section is about the EDGE, and pinning which key `attack` is bound to would
# make it go red the next time someone rebinds a keyboard.
_ATTACK_VERB = ATTACK_ACTION.param("verb").default
_ATTACK_KEYS = [b.split(":", 1)[1] for b in REAL_CONFIG.get(_ATTACK_VERB, ())
                if b.startswith("keyboard:") and b.split(":", 1)[1] in KEYBOARD]
expect_true(f"{_ATTACK_VERB!r} has a keyboard binding this can drive",
            bool(_ATTACK_KEYS))
if _ATTACK_KEYS:
    _ATTACK_KEY = _ATTACK_KEYS[0]
    _realbody = _Body()
    _realbody.action_manager = _real
    compose(_realbody, "attack_action")
    _series = []
    for _hold in ([_ATTACK_KEY], [_ATTACK_KEY], [_ATTACK_KEY], [], [_ATTACK_KEY]):
        _advance(_real, _hold)
        frame(_realbody)
        _series.append("attack_action" in _realbody.action_intent)
    expect("against the REAL manager, a held key fires on the edge only",
           _series, [True, False, False, False, True])


# ===========================================================================
print("\n5. cooldown_ms: it stops one DURING the window and passes one after")
# ===========================================================================
# The clock is driven with a synthetic delta. Nothing here sleeps: a check
# that waited on a wall clock would be slow AND flaky, and would prove the
# machine's timing rather than the behavior's arithmetic.
_COOLDOWN = int(MS_PER_FRAME * 3)          # three frames at delta=1.0
_cool = _Body("attack")
compose(_cool, "attack_action", cooldown_ms=_COOLDOWN)
_cool.action_manager.tap("attack")
frame(_cool)
expect("the first press fires", "attack_action" in _cool.action_intent, True)
expect_close("...and arms the clock for the full cooldown",
             _cool.behaviors.get("attack_action").cooldown_left, _COOLDOWN, 1e-9)

_during = []
for _ in range(2):
    _cool.action_manager.tap("attack")     # a fresh edge every frame
    frame(_cool)
    _during.append("attack_action" in _cool.action_intent)
expect("presses DURING the window are refused, every one of them",
       _during, [False, False])
expect_close("...and the clock still has its last frame left to run",
             _cool.behaviors.get("attack_action").cooldown_left,
             MS_PER_FRAME, 1e-9)
_cool.action_manager.tap("attack")
frame(_cool)
expect("...and the press on the frame it elapses fires, re-arming the clock",
       ("attack_action" in _cool.action_intent,
        _cool.behaviors.get("attack_action").cooldown_left),
       (True, float(_COOLDOWN)))

# cooldown_ms=0 is the documented "no limit", and it is the DEFAULT -- so the
# pair above would pass with the whole clock deleted if this half were absent.
_rapid = _Body("attack")
compose(_rapid, "attack_action")
_fires = []
for _ in range(4):
    _rapid.action_manager.tap("attack")
    frame(_rapid)
    _fires.append("attack_action" in _rapid.action_intent)
expect("cooldown_ms=0 means no limit: every edge fires",
       _fires, [True, True, True, True])
expect("...and 0 is the declared default, so this is the shipped path",
       ATTACK_ACTION.param("cooldown_ms").default, 0)

# The clock is WALL time: it ticks through the input gate. Otherwise a
# cooldown becomes "seconds of gameplay" and the same fixture gives two
# answers depending on whether a menu was open.
_ticking = _Body("attack")
compose(_ticking, "attack_action", cooldown_ms=_COOLDOWN)
_ticking.action_manager.tap("attack")
frame(_ticking)
_ticking.state.enabled_inputs = False
_ticking.action_manager.tap()
for _ in range(3):
    frame(_ticking)
expect_close("the cooldown ticks down while input is disabled",
             _ticking.behaviors.get("attack_action").cooldown_left, 0.0, 1e-9)

# Refused rather than clamped, and refused at COMPOSITION time.
expect_raises("a negative cooldown is refused, naming the property",
              PyoneerConfigError,
              lambda: compose(_Body("attack"), "attack_action",
                              cooldown_ms=-1),
              "cooldown_ms", "0 for no limit")
expect_raises("a boolean cooldown is refused -- in Python True IS an int",
              PyoneerConfigError,
              lambda: compose(_Body("attack"), "attack_action",
                              cooldown_ms=True),
              "pyoneer_param_cooldown_ms", "int")
expect_no_raise("...while a zero cooldown composes cleanly",
                lambda: compose(_Body("attack"), "attack_action",
                                cooldown_ms=0))


# ===========================================================================
print("\n6. once: exactly one firing, and it stays spent")
# ===========================================================================
_once = _Body("action")
compose(_once, "interact_action", once=True)
_count = 0
for _ in range(120):
    _once.action_manager.tap("action")     # a fresh edge on every frame
    frame(_once)
    _count += 1 if "interact_action" in _once.action_intent else 0
expect("once=True fires exactly one time across 120 edges", _count, 1)
expect("...and reports itself spent",
       _once.behaviors.get("interact_action").spent, True)

# The half that proves `once` is the thing doing it rather than some other
# refusal upstream: the same 120 frames without it fire 120 times.
_repeat = _Body("action")
compose(_repeat, "interact_action")
_count2 = 0
for _ in range(120):
    _repeat.action_manager.tap("action")
    frame(_repeat)
    _count2 += 1 if "interact_action" in _repeat.action_intent else 0
expect("...while the same fixture without it fires on all 120", _count2, 120)

# Documented: a detach/attach cycle does not re-arm it, or `once` would be
# bypassable by anything that swaps behaviors at runtime.
_spent = _once.behaviors.get("interact_action")
_once.behaviors.detach("interact_action")
expect("detaching an action releases its slot rather than emptying it",
       _once.action_intent.slots, ())
_once.behaviors.attach(_spent)
_once.action_manager.tap("action")
frame(_once)
expect("...and re-attaching a spent action does not re-arm it",
       ("interact_action" in _once.action_intent,
        _once.action_intent.slots), (False, ("interact_action",)))


# ===========================================================================
print("\n7. an unbound verb is caught AT ATTACH, and a bound one is not")
# ===========================================================================
def _attach_unbound():
    body = _Body("attack")                 # binds attack, NOT action
    compose(body, "interact_action")


expect_raises("a verb config/inputs.json does not bind raises at attach",
              PyoneerConfigError, _attach_unbound,
              "'action'", "interact_action", "KeyError", "attack")
expect_no_raise("...and the same behavior attaches when the verb IS bound",
                lambda: compose(_Body("action"), "interact_action"))

# The rollback. `EntityBehaviors.attach` removes an entry whose hook raised;
# without that half the refused behavior is driven every frame by an entity
# whose composition was rejected.
_rolled = _Body("attack")
try:
    compose(_rolled, "interact_action")
except PyoneerConfigError:
    pass
expect("a refused action is not left half-attached",
       (len(_rolled.behaviors), _rolled.behaviors.names), (0, ()))
expect("...and it left no slot behind on the record either",
       actions_of(_rolled).slots, ())

# require_verbs itself, both directions, including the two documented ways it
# stays quiet.
expect_raises("require_verbs names the verb, the behavior and the entity",
              PyoneerConfigError,
              lambda: require_verbs(_Keys("up"), ("dash",),
                                    behavior="dash_action", entity="Hero"),
              "'dash'", "dash_action", "Hero", "up")
expect("a None manager is a legal configuration and audits nothing",
       require_verbs(None, ("anything",), behavior="b", entity="E"),
       ("anything",))
expect("an empty verb name is skipped rather than demanded",
       require_verbs(_Keys(), ("",), behavior="b", entity="E"), ())
def _message_of(call):
    """The message a PyoneerConfigError carried, or '' if it did not raise."""
    try:
        call()
    except PyoneerConfigError as exc:
        return str(exc)
    return ""


expect_true("a manager with no bindings says '<none>' rather than trailing off",
            "<none>" in _message_of(lambda: require_verbs(
                _Keys(), ("x",), behavior="b", entity="E")))


# ===========================================================================
print("\n8. an empty verb polls NOTHING -- proved against a tripwire manager")
# ===========================================================================
class _Tripwire(_Keys):
    """Binds its verbs so the attach audit passes, and refuses to be polled.

    This is what makes "verb='' polls nothing" evidence rather than a
    tautology: a manager that merely answered False would look identical
    whether the poll happened or not.
    """

    def pressed(self, name):
        raise AssertionError("the manager was polled for %r" % (name,))

    def held(self, name):
        raise AssertionError("the manager was polled for %r" % (name,))


_disabled = _Body()
_disabled.action_manager = _Tripwire("attack")
compose(_disabled, "attack_action", verb="")
expect_no_raise("verb='' runs a frame without touching the manager at all",
                lambda: frame(_disabled))
expect("...and records nothing, while keeping its slot",
       (_disabled.action_intent.fired_names, _disabled.action_intent.slots),
       ((), ("attack_action",)))
# The other half: the same tripwire with a real verb IS polled.
_polls = _Body()
_polls.action_manager = _Tripwire("attack")
compose(_polls, "attack_action")
expect_raises("...while a non-empty verb reaches the manager on every frame",
              AssertionError, lambda: frame(_polls), "polled", "attack")


# ===========================================================================
print("\n9. the gate: enabled_inputs suppresses, can_move deliberately does not")
# ===========================================================================
_gated = _Body("attack")
compose(_gated, "attack_action")
_gated.state.enabled_inputs = False
_gated.action_manager.tap("attack")
frame(_gated)
expect("enabled_inputs=False suppresses the firing",
       _gated.action_intent.fired_names, ())
_gated.state.enabled_inputs = True
_gated.action_manager.tap("attack")
frame(_gated)
expect("...and clearing it lets the same entity fire",
       "attack_action" in _gated.action_intent, True)

# THE DIVERGENCE FROM player_input, and the assertion most likely to be left
# out. `can_move=False` freezes walking; an entity frozen for a cutscene must
# still be able to press "continue".
_frozen = _Body("action")
compose(_frozen, "interact_action")
_frozen.state.can_move = False
_frozen.action_manager.tap("action")
frame(_frozen)
expect("can_move=False does NOT suppress an action -- it is not movement",
       "interact_action" in _frozen.action_intent, True)
expect("...and player_input gates on both, which is the pair that differ",
       (resolve("player_input").name, resolve("interact_action").name),
       ("player_input", "interact_action"))

# The clear runs BEFORE every gate. Without that ordering, an action fired on
# the frame a cutscene begins stays standing in the record for the whole
# cutscene and every consumer re-fires on it once per frame.
_midpress = _Body("attack")
compose(_midpress, "attack_action")
_midpress.action_manager.tap("attack")
frame(_midpress)
expect("a firing is present on its own frame",
       "attack_action" in _midpress.action_intent, True)
_midpress.state.enabled_inputs = False
frame(_midpress)
expect("...and freezing mid-press CLEARS it rather than leaving it standing",
       _midpress.action_intent.fired_names, ())

# An entity with no PlayerState at all is ungated, not crashed: a pushed crate
# has nowhere to record a gate and must still be composable.
_stateless = _Body("attack", state=False)
compose(_stateless, "attack_action")
_stateless.action_manager.tap("attack")
expect_no_raise("an entity with no PlayerState is ungated, not crashed",
                lambda: frame(_stateless))
expect("...and it fires", "attack_action" in _stateless.action_intent, True)


# ===========================================================================
print("\n10. composition: one order window, disjoint writes, refused overlaps")
# ===========================================================================
_window = _Body("attack", "action", "pause")
expect_no_raise("three actions at one order attach together (disjoint writes)",
                lambda: compose(_window,
                                "attack_action,interact_action,pause_action"))
expect("...and run in declared order after the input poll",
       _window.behaviors.names,
       ("attack_action", "interact_action", "pause_action"))

# The other half of that: `EntityBehaviors.attach` refuses two behaviors at one
# order whose writes intersect -- which is exactly why the record is a slot per
# action and not one shared attribute. Proved with a fixture spec that declares
# the collision the shared spelling would have had.
_COLLIDER = BehaviorSpec(name="collider_action", summary="check fixture",
                         factory=GameActionInputBehavior,
                         writes=("action_intent.attack_action",), order=ORDER)
_collide = _Body("attack")
compose(_collide, "attack_action")
_shared = GameActionInputBehavior(verb="attack")
_shared.spec = _COLLIDER
expect_raises("two actions at one order writing one slot are REFUSED",
              PyoneerConfigError,
              lambda: _collide.behaviors.attach(_shared),
              "attack_action", "collider_action", str(ORDER))

expect_raises("a duplicated token is a typo, not a stack", PyoneerConfigError,
              lambda: validate_list("attack_action,attack_action"),
              "attack_action", "twice")
expect_raises("a mistyped action token names itself and lists the table",
              PyoneerAssetMissingError,
              lambda: validate_list("attack_actoin"),
              "attack_actoin", "attack_action", "interact_action")
expect("no action declares a conflict, so any list may hold all of them",
       tuple(s.conflicts for s in ACTION_SPECS + (ACTION_RELAY,)),
       ((), (), (), ()))
expect_no_raise("...and a full list validates alongside a movement body",
                lambda: validate_list(
                    "player_input,topdown_move,animation_drive,"
                    "attack_action,interact_action,pause_action,action_relay"))

# The ORDER WINDOW, measured. A movement body at 20 must be able to consume an
# action on the frame it fires -- a dash is exactly that.
_watched = _Body("attack")
compose(_watched, "attack_action")
_watch = _Watcher()
_watch.spec = WATCHER_SPEC
_watched.behaviors.attach(_watch)
_watched.action_manager.tap("attack")
frame(_watched)
_watched.action_manager.tap()
frame(_watched)
expect("a reader at order 20 sees the firing on the SAME frame",
       _watch.seen, [("attack_action",), ()])


# ===========================================================================
print("\n11. the relay CALLS its sink, and stays quiet when nothing fired")
# ===========================================================================
_relayed = _Body("attack", "action")
compose(_relayed, "attack_action,interact_action,action_relay")
_sink = _Sink()
_relayed.action_sink = _sink
_relayed.action_manager.tap("attack", "action")
frame(_relayed)
expect("every firing on the frame reaches the sink, in report order",
       tuple(f.name for _, f in _sink.calls),
       ("attack_action", "interact_action"))
expect("...with the entity that fired it",
       tuple({name for name, _ in _sink.calls}), ("_Body",))
_relayed.action_manager.tap()
frame(_relayed)
expect("...and a frame where nothing fired calls the sink zero times",
       len(_sink.calls), 2)

# No sink is quiet, not broken -- the same contract `action_manager` has --
# and the unmet requirement is REPORTED.
_nosink = _Body("attack")
compose(_nosink, "attack_action,action_relay")
_nosink.action_sink = None
_nosink.action_manager.tap("attack")
expect_no_raise("an entity with no sink runs a frame quietly",
                lambda: frame(_nosink))
expect("...and the missing requirement is reported, never enforced",
       _nosink.behaviors.missing_requirements(),
       (("action_relay", "action_sink"),))
expect("...while the firing is still in the record for anything else to read",
       "attack_action" in _nosink.action_intent, True)

# A relay on an entity that composes no action at all reads the shared inert
# record and must not touch it -- the lock would raise if it tried.
_lonely = _Body()
compose(_lonely, "action_relay")
_lonely.action_sink = _Sink()
expect_no_raise("a relay with no actions beside it reads the inert record",
                lambda: frame(_lonely))
expect("...and calls nothing", len(_lonely.action_sink.calls), 0)
# The half the label above claims and never measured: WHICH record was read.
# Swapping actions_of(entity) for a private per-entity lookup leaves both
# assertions above green, because both are satisfied by "nothing happened".
expect("...and it is the SHARED inert record, not a private empty one",
       actions_of(_lonely) is NO_ACTIONS, True)
expect("...because a relay-only entity never gets a record of its own",
       hasattr(_lonely, "action_intent"), False)

# ActionIntent.record's type guard. A stand-in shaped like ActionFired is
# exactly what a future caller writes by accident, and the guard's message
# says the divergence would be silent -- so the guard itself must not be.
class _NotFired:
    name = "attack_action"
    verb = "attack"
    frame = 0


expect_raises("recording something that is not an ActionFired raises",
              PyoneerConfigError,
              lambda: ActionIntent().record("attack_action", _NotFired()),
              "attack_action", "ActionFired")


# ===========================================================================
print("\n12. the code agrees with the config, without pinning which key")
# ===========================================================================
# A claim about the CODE and the CONFIG, not about a map and not about a
# keyboard layout: whatever verb a shipped spec DEFAULTS to must be bound, or
# every entity composing that action raises at attach.
for _spec in ACTION_SPECS:
    _verb = _spec.param("verb").default
    expect(f"{_spec.name}: its default verb {_verb!r} is bound",
           _verb in REAL_CONFIG, True)
expect("...and the manager accepts every binding in the file",
       sorted(InputActionManager().prepare(REAL_CONFIG).actions),
       sorted(REAL_CONFIG))

# Two verbs sharing one physical binding can never be told apart by any
# consumer. `jump` and `action` shipped identical, and every gamepad binding
# aliased onto the d-pad's own index space, so walking down fired `attack`.
from scripts.core.input import CONTROLLER                        # noqa: E402

_physical: dict[tuple[str, int], list[str]] = {}
for _verb, _binds in REAL_CONFIG.items():
    for _bind in _binds:
        _kind, _, _key = _bind.partition(":")
        _code = (KEYBOARD if _kind in ("keyboard", "key") else CONTROLLER)[_key]
        _physical.setdefault((_kind, _code), []).append(_verb)
_collisions = {k: sorted(v) for k, v in _physical.items() if len(v) > 1}
expect("no two verbs resolve to the same physical input", _collisions, {})
# The other half: the resolver above is capable of SEEING a collision. Without
# this, a bug in the loop that produced an empty table would read as a pass.
_probe: dict[tuple[str, int], list[str]] = {}
for _verb, _binds in {"a": ["gamepad:up"], "b": ["gamepad:button_0"]}.items():
    for _bind in _binds:
        _kind, _, _key = _bind.partition(":")
        _probe.setdefault((_kind, CONTROLLER[_key]), []).append(_verb)
expect("...and the same resolver reports one when it is there",
       {k: sorted(v) for k, v in _probe.items() if len(v) > 1},
       {("gamepad", 0): ["a", "b"]})


# ===========================================================================
print("\n13. the wire: a map object's action list reaches a live entity")
# ===========================================================================
# The tmx property is the declaration site, and a declaration site nothing
# reads is a format rather than a feature. Driven through the real
# `spawn_objects` over a fixture map written here -- `data/maps/test.tmx` is
# the author's canvas and is never opened.
from scripts.loaders.map_loader import spawn_objects              # noqa: E402

_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="4" height="4" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="3" nextobjectid="4">
 <objectgroup id="2" name="entity">
  <object id="1" name="hero" type="Probe" x="0" y="0" width="16" height="16">
   <properties>
    <property name="pyoneer_behaviors" value="attack_action,interact_action"/>
    <property name="pyoneer_param_payload" value="swing"/>
   </properties>
  </object>
  <object id="2" name="mute" type="Probe" x="32" y="0" width="16" height="16"/>
 </objectgroup>
</map>
"""

_workspace = tempfile.mkdtemp(prefix="pyoneer_action_")


def _fixture(name, text):
    path = os.path.join(_workspace, name)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


_spawned = spawn_objects(_fixture("actions.tmx", _FIXTURE), {"Probe": _Body})
expect("the authored action list is carried off the map, in authored order",
       tuple(r.spec.name for r in _spawned[0].behaviors),
       ("attack_action", "interact_action"))
expect("an object declaring nothing carries nothing, not a default",
       _spawned[1].behaviors, ())
for _record in _spawned:
    _record.entity.action_manager = _Keys("attack", "action")
    if _record.behaviors:
        _record.entity.behaviors.attach_all(build(_record.behaviors))
for _record in _spawned:
    _record.entity.action_manager.tap("attack")
    frame(_record.entity)
expect("the object that declared the actions is the one that fires",
       (actions_of(_spawned[0].entity).fired_names,
        actions_of(_spawned[1].entity).fired_names),
       (("attack_action",), ()))
expect("...and the parameter authored beside it reached the record",
       fired_or_missing(actions_of(_spawned[0].entity),
                        "attack_action").payload, "swing")
expect_raises("a mistyped action token raises AT SPAWN, naming the object",
              PyoneerAssetMissingError,
              lambda: spawn_objects(
                  _fixture("typo.tmx",
                           _FIXTURE.replace("attack_action,interact_action",
                                            "attack_actoin")),
                  {"Probe": _Body}),
              "attack_actoin")


# ===========================================================================
print("\n14. summary")
# ===========================================================================
print(f"assertions             : {len(asserted)}")
print(f"registry               : {sorted(BEHAVIOR_REGISTRY)}")
_dupes = sorted({label for label in asserted if asserted.count(label) > 1})
if _dupes:
    print(f"DUPLICATE LABELS       : {_dupes}")
print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for item in failures:
        print(f"  - {item}")
    sys.exit(1)
print("ALL ACTION CHECKS PASS")
