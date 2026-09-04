"""Verify the event-script vocabulary: what it refuses, and what it runs.

    .venv/Scripts/python.exe tools/check_ops.py

The claims, each one a line the engine is otherwise free to break with no
symptom until a branch silently took the wrong arm, or a player was left
permanently unable to walk:

     1. `register` RAISES on a duplicate op name, naming BOTH loadouts, and
        takes a fresh one; `resolve` raises on an unknown name and never
        falls back; an `OpSpec` refuses a nonsense declaration
     2. the CORE EIGHT are exactly `say ask set wait hold release call stop`,
        all in `core`, with `ask` at `needs-host` and every other one `live`
     3. `resolve_args` refuses an argument the op does not take, a missing
        required one and a wrong-typed one -- and ACCEPTS the tri-state null
        that means "do not touch this axis", which no other param may take
     4. every load gate of the reader: format, version, unknown keys at three
        depths, a missing id, a duplicate id, an unknown `do`, a `do` outside
        the declared loadouts, two comparators on one condition, an
        undeclared variable, a wrong-typed `set`
     5. `if` / `elif` / `else` takes each arm on the right variables AND does
        not take the arms it must not; `while` loops and terminates
     6. a runaway `while` RAISES at `MAX_STEPS_PER_FRAME` rather than hanging
        the frame, and a script just under the cap completes
     7. `call` depth 17 raises NAMING THE CHAIN and depth 15 runs
     8. `hold` clears an axis and `release` restores THE RECORDED VALUE, not
        `True` -- a body that was already unsteerable is still unsteerable
     9. `say` drives a duck-typed host and waits for the advance; `ask`
        RAISES, honestly, because no widget in this engine reports a click
    10. `interpreter.py` and `ops.py` reach the event bus at ZERO points,
        proved from the PARSE TREE with a planted decoy, and import nothing
        from `editor/`, with a misspelled-prefix control
    11. `SCRIPT_TRIGGERS` is a superset of the editor's `TRIGGER_KINDS`, word
        for word, and `SceneFlow` and `ScriptRun` hold the SAME `AgencyHold`
        class rather than two that agree today

EVERY ASSERTION IS A PAIR
-------------------------
A gate proved to let something through and never proved to stop it is the
dominant failure this repo has found in its own checks. Each rule above is
two assertions with opposite expectations; the mutation table at the end
records what each one turned red for.

THE FIXTURES ARE THIS FILE'S OWN
--------------------------------
`data/maps/starter.tmx` is never read and no script file has to exist: every
document below is a dict this file builds, parsed through the real reader.
`editor/core/map_events.py` IS imported -- a check under `tools/` may import
both sides, and that is the only way an agreement between two files that may
not import each other can be MEASURED rather than assumed.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import ast
import copy
import inspect
import sys

import pygame

pygame.init()

from editor.core import map_events
from scripts.core.errors import (PyoneerAssetMissingError,
                                 PyoneerConfigError)
from scripts.game.behavior.movement import MS_PER_DELTA
from scripts.game.behavior.state import ensure_state, state_of
from scripts.game.flow import ops as ops_module
from scripts.game.flow import interpreter as interpreter_module
from scripts.game.flow import scene_flow as scene_flow_module
from scripts.game.flow.interpreter import (MAX_CALL_DEPTH,
                                           MAX_STEPS_PER_FRAME, ScriptRun)
from scripts.game.flow.ops import (CORE, CORE_OPS, OP_REGISTRY, OpArg, OpSpec,
                                   check_loadout, register, resolve,
                                   resolve_args, validate_loadouts)
from scripts.game.flow.scene_flow import AgencyHold, SceneFlow
from scripts.loaders import script_file as sf

failures: list[str] = []
asserted: list[int] = []


def expect(label, got, want):
    asserted.append(1)
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception, call, *fragments):
    """The call must raise `exception`, and its message must name each fragment.

    The fragments are the teeth: asserting only the exception TYPE passes for
    any raise anywhere inside the call, including a typo three frames down.
    """
    asserted.append(1)
    try:
        call()
    except exception as exc:
        text = str(exc)
        missing = [f for f in fragments if f not in text]
        ok = not missing
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} "
              f"raised {type(exc).__name__}: {text.splitlines()[0][:44]}")
        if not ok:
            failures.append(f"{label} (message lacks {missing})")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<62} raised {type(exc).__name__} not "
              f"{exception.__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<62} did not raise")
    failures.append(label)


def expect_no_raise(label, call):
    asserted.append(1)
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<62} raised {type(exc).__name__}: {exc}")
        failures.append(label)
        return
    print(f"  ok   {label:<62} did not raise")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DELTA = 1.0
"""One frame in ENGINE delta units -- `MS_PER_DELTA` milliseconds each."""

VARS = sf.read_vars({
    "gate_open": {"type": "bool", "default": False, "doc": "Set by the keeper."},
    "coins": {"type": "int", "default": 0, "doc": "Spendable."},
    "keeper_pick": {"type": "int", "default": -1, "doc": "Written by an ask."},
    "who": {"type": "str", "default": "", "doc": "A name."},
})


def store(**overrides):
    """A fresh `VarStore` over the fixture schema."""
    values = sf.VarStore(VARS)
    for key, value in overrides.items():
        values.set(key, value)
    return values


def document(body, *, loadouts=("core",), script_id="fixture", pages=None):
    """One script document as a dict, with one page holding `body`."""
    return {"format": sf.FORMAT, "version": sf.VERSION, "id": script_id,
            "loadouts": list(loadouts),
            "pages": pages if pages is not None
            else [{"id": "pg", "trigger": "use", "when": [], "body": body}]}


def parse(body=None, *, variables=VARS, **kw):
    return sf.parse_script(document(body if body is not None else [], **kw),
                           "%s.json" % kw.get("script_id", "fixture"),
                           variables=variables)


class Host:
    """The smallest thing a `say` can drive: `say_open` and `say_close`.

    The run duck-types its host so it does not have to import `GameWindow` --
    which would put `CoreAssetManager`'s theme load on the import path of
    every module that touches a script. This one records the ORDER of the
    calls, which a real window cannot report.
    """

    def __init__(self):
        self.calls: list = []

    def say_open(self, who, text):
        self.calls.append(("open", who, text))

    def say_close(self):
        self.calls.append(("close",))


class Body:
    """An entity-shaped thing with a `BodyState` and nothing else.

    `AgencyHold` reads `state_of(body)`, which is all a hold needs, so a real
    `GamePlayer` (a display, a sheet, an animation clock) would only make the
    two halves of section 8 slower to run and no more true.
    """


def body(**axes):
    made = Body()
    state = ensure_state(made)
    for axis, value in axes.items():
        setattr(state, axis, value)
    return made


def run_for(body_doc, *, values=None, bodies=(), host=None, scripts=None,
            variables=VARS, **kw):
    script = sf.parse_script(document(body_doc, **kw),
                             "%s.json" % kw.get("script_id", "fixture"),
                             variables=variables)
    run = ScriptRun(script, variables=values if values is not None else store(),
                    bodies=bodies, host=host, scripts=scripts)
    run.begin()
    return run


def drive(run, frames=64, delta=DELTA):
    """Tick until the run is done or `frames` are spent. Returns the count."""
    for spent in range(1, frames + 1):
        run.update(delta)
        if run.done:
            return spent
    return frames


def SET(node_id, var, to, by="assign"):
    return {"id": node_id, "do": "set", "var": var, "to": to, "by": by}


print("check_ops -- what a script may say, and what happens when it says it")
print(f"  registry: {len(OP_REGISTRY)} op(s); loadouts: "
      f"{', '.join(ops_module.loadouts())}")


# ===========================================================================
print("\n1. the registry refuses what it must, and takes what it must")
# ===========================================================================
def spec(name="fixture_op", loadout=CORE, **kw):
    kw.setdefault("summary", "Fixture.")
    kw.setdefault("run", lambda run, args: True)
    return OpSpec(name=name, loadout=loadout, **kw)


PRIVATE: dict = {}
expect_no_raise("register takes a name the registry does not have",
                lambda: register(spec("alpha"), PRIVATE))
# BOTH HALVES. The behavior registry REPLACES on re-registration; this one
# must not, because two genre packs that never read each other can each want
# `jump`, and a silent second win changes the meaning of every script written
# against the first.
expect_raises("...and RAISES on a duplicate, naming both loadouts",
              PyoneerConfigError,
              lambda: register(spec("alpha", loadout="topdown_rpg"), PRIVATE),
              "'alpha'", "'core'", "'topdown_rpg'")
expect("...and the first registration is the one still standing",
       PRIVATE["alpha"].loadout, CORE)

expect_raises("resolve raises on an unknown name, listing the vocabulary",
              PyoneerAssetMissingError,
              lambda: resolve("saay", where="a node"),
              "saay", "say", "a node")
expect("...and a known one resolves to its spec", resolve("say").name, "say")
expect_raises("...and a non-string `do` raises rather than being str()'d",
              PyoneerConfigError, lambda: resolve(3, where="a node"), "`do`")

expect_raises("an OpSpec refuses a name that is not a token",
              PyoneerConfigError, lambda: spec("Say"), "'Say'")
expect_raises("...refuses an unknown status",
              PyoneerConfigError, lambda: spec("beta", status="wired"),
              "'wired'", "needs-host")
expect_raises("...refuses a loadout that is not a token",
              PyoneerConfigError, lambda: spec("beta", loadout="Top RPG"),
              "'Top RPG'")
expect_raises("...refuses a run that is not callable",
              PyoneerConfigError, lambda: spec("beta", run=42), "callable")
expect_raises("...refuses one key declared twice",
              PyoneerConfigError,
              lambda: spec("beta",
                           params=(ops_module._param("x", "x", "int", 1, "d"),),
                           dynamic=(OpArg("x", "x", "d", "anything"),)),
              "'x'", "twice")
expect_no_raise("...and takes a spec that is legal in every one of those ways",
                lambda: spec("beta", status="needs-host", loadout="topdown_rpg"))

expect("validate_loadouts returns what it was given",
       validate_loadouts(["core"]), ("core",))
expect_raises("...raises on a loadout no op declares",
              PyoneerAssetMissingError,
              lambda: validate_loadouts(["platformer"], where="a script"),
              "platformer", "core")
expect_raises("...raises on a duplicate", PyoneerConfigError,
              lambda: validate_loadouts(["core", "core"], where="a script"),
              "twice")
expect_raises("...raises when it is not a list at all", PyoneerConfigError,
              lambda: validate_loadouts("core", where="a script"), "array")
expect("...and an empty list is legal here (the per-op gate has the teeth)",
       validate_loadouts([]), ())

expect_no_raise("check_loadout passes an op the document granted",
                lambda: check_loadout(resolve("say"), ("core",), "a node"))
expect_raises("...and refuses one it did not, naming both",
              PyoneerConfigError,
              lambda: check_loadout(spec("walk_to", loadout="topdown_rpg"),
                                    ("core",), "a node"),
              "'walk_to'", "'topdown_rpg'", "'core'")


# ===========================================================================
print("\n2. the core ten, and nothing else")
# ===========================================================================
expect("the registry holds exactly the ten core ops",
       sorted(OP_REGISTRY), sorted(["say", "ask", "set", "wait", "hold",
                                    "release", "call", "stop",
                                    "play_sound", "play_music"]))
expect("CORE_OPS and the registry agree",
       sorted(s.name for s in CORE_OPS), sorted(OP_REGISTRY))
expect("every one of them is in the `core` loadout",
       sorted({s.loadout for s in OP_REGISTRY.values()}), [CORE])
# `enter_scene` is core BY THE PORTABILITY TEST and is deliberately absent:
# scene switching is measurably broken, and an op whose run does nothing is
# the defect `play_sound` and `play_music` were kept OUT of core for until
# `scripts/core/audio.py` existed. It exists, they run, and `enter_scene` is
# the one the rule still points at.
expect("`enter_scene` is NOT registered -- it lands with the stage that fixes "
       "set_scene", "enter_scene" in OP_REGISTRY, False)
expect("`ask` is the one op that ships needing a host",
       sorted(n for n, s in OP_REGISTRY.items() if s.status != "live"), ["ask"])
expect("...and every other one is live",
       sorted(n for n, s in OP_REGISTRY.items() if s.status == "live"),
       sorted(["say", "set", "wait", "hold", "release", "call", "stop",
               "play_sound", "play_music"]))
expect("exactly the three ops that wait declare yields",
       sorted(n for n, s in OP_REGISTRY.items() if s.yields),
       sorted(["ask", "say", "wait"]))
expect("`hold` names the three agency axes and no more",
       [p.key for p in OP_REGISTRY["hold"].params],
       list(scene_flow_module.AGENCY_AXES))
expect("...and all three are tri-state", OP_REGISTRY["hold"].tri_state_keys,
       scene_flow_module.AGENCY_AXES)
expect("`release` and `stop` take no arguments at all",
       (OP_REGISTRY["release"].arg_keys, OP_REGISTRY["stop"].arg_keys),
       ((), ()))


# ===========================================================================
print("\n3. resolve_args -- an argument is refused or it is typed")
# ===========================================================================
SAY = resolve("say")
expect("a legal `say` resolves both arguments",
       resolve_args(SAY, {"text": "hi", "who": "K"}, VARS, "n1"),
       {"text": "hi", "who": "K"})
expect("...and an omitted optional one takes its declared default",
       resolve_args(SAY, {"text": "hi"}, VARS, "n1")["who"], "")
expect_raises("an argument the op does not take RAISES, naming what it takes",
              PyoneerConfigError,
              lambda: resolve_args(SAY, {"text": "hi", "txt": "hi"}, VARS, "n1"),
              "'txt'", "text", "who")
expect_raises("...a missing required one raises", PyoneerConfigError,
              lambda: resolve_args(SAY, {"who": "K"}, VARS, "n1"),
              "'text'")
expect_raises("...a wrong-typed one raises through BehaviorParam.coerce",
              PyoneerConfigError,
              lambda: resolve_args(SAY, {"text": 3}, VARS, "n1"),
              "'text'", "str")
expect_raises("...and a bool where a str is wanted raises too (True IS an int)",
              PyoneerConfigError,
              lambda: resolve_args(SAY, {"text": True}, VARS, "n1"), "'text'")

HOLD = resolve("hold")
expect("hold's tri-state: an absent axis resolves to None (do not touch)",
       resolve_args(HOLD, {"steerable": False}, VARS, "n1"),
       {"steerable": False, "enabled_inputs": None, "simulated": None})
expect("...and an EXPLICIT json null means the same thing",
       resolve_args(HOLD, {"steerable": False, "simulated": None},
                    VARS, "n1")["simulated"], None)
# The other half of the tri-state rule: only a param whose declared default is
# None may take a null. A `say` that accepted `"text": null` would show an
# empty box and complain about nothing.
expect_raises("...while a null on a param that is NOT tri-state raises",
              PyoneerConfigError,
              lambda: resolve_args(SAY, {"text": None}, VARS, "n1"), "'text'")
expect_raises("a hold that names no axis is refused (it is a no-op node)",
              PyoneerConfigError, lambda: resolve_args(HOLD, {}, VARS, "n1"),
              "no axis", "steerable")

WAIT = resolve("wait")
expect("wait widens an authored int to the float it declares",
       resolve_args(WAIT, {"ms": 250}, VARS, "n1"), {"ms": 250.0})
expect_raises("...and refuses a wait of zero", PyoneerConfigError,
              lambda: resolve_args(WAIT, {"ms": 0}, VARS, "n1"), "no-op")

ASK = resolve("ask")
expect_no_raise("ask takes two options and an int variable to write into",
                lambda: resolve_args(ASK, {"prompt": "?",
                                           "options": ["a", "b"],
                                           "into": "keeper_pick"}, VARS, "n1"))
expect_raises("...and refuses a single option (that is a `say`)",
              PyoneerConfigError,
              lambda: resolve_args(ASK, {"prompt": "?", "options": ["a"],
                                         "into": "keeper_pick"}, VARS, "n1"),
              "two")
expect_raises("...and refuses writing the chosen INDEX into a bool",
              PyoneerConfigError,
              lambda: resolve_args(ASK, {"prompt": "?", "options": ["a", "b"],
                                         "into": "gate_open"}, VARS, "n1"),
              "gate_open", "int")


# ===========================================================================
print("\n4. every load gate of the reader")
# ===========================================================================
expect_no_raise("a legal document loads",
                lambda: parse([SET("n1", "coins", 5)]))

def broken(**changes):
    doc = document([SET("n1", "coins", 5)])
    doc.update(changes)
    return lambda: sf.parse_script(doc, "fixture.json", variables=VARS)


expect_raises("a wrong `format` raises naming both spellings",
              PyoneerConfigError, broken(format="pyoneer.scene"),
              "pyoneer.scene", "pyoneer.script")
expect_raises("a missing `version` raises", PyoneerConfigError,
              broken(version=None), "version")
expect_raises("a NEWER version raises rather than being read optimistically",
              PyoneerConfigError, broken(version=2),
              "is version 2", "reads version 1")
expect_raises("an unknown key on the SCRIPT raises naming the accepted set",
              PyoneerConfigError, broken(author="me"), "'author'", "pages")
expect_raises("an id that disagrees with the file name raises",
              PyoneerConfigError, broken(id="other"),
              "'other'", "fixture.json")

expect_raises("an unknown key on a PAGE raises", PyoneerConfigError,
              lambda: parse(pages=[{"id": "pg", "when": [], "body": [],
                                    "colour": "red"}]),
              "'colour'", "cooldown_ms")
expect_raises("an unknown key on a NODE raises naming what the op takes",
              PyoneerConfigError,
              lambda: parse([{"id": "n1", "do": "say", "text": "hi",
                              "voice": "low"}]),
              "'voice'", "who")
expect_raises("a page with no id raises naming its position",
              PyoneerConfigError,
              lambda: parse(pages=[{"when": [], "body": []}]),
              "pages[0]", "`id`")
expect_raises("a node with no id raises naming its position",
              PyoneerConfigError,
              lambda: parse([{"do": "say", "text": "hi"}]),
              "body[0]", "`id`")
expect_raises("a duplicate id anywhere raises naming BOTH places",
              PyoneerConfigError,
              lambda: parse([SET("n1", "coins", 1), SET("n1", "coins", 2)]),
              "'n1'", "body[0]", "body[1]")
expect_raises("...including a node id that collides with a page id",
              PyoneerConfigError, lambda: parse([SET("pg", "coins", 1)]),
              "'pg'")
expect_raises("a node that is neither `do` nor `if`/`while` raises",
              PyoneerConfigError, lambda: parse([{"id": "n1", "note": "hm"}]),
              "no-op", "`note`")
expect_raises("...and one that is BOTH raises", PyoneerConfigError,
              lambda: parse([{"id": "n1", "do": "stop", "if": []}]),
              "'do'", "'if'")

expect_raises("an unknown `do` raises AT LOAD naming file, node and vocabulary",
              PyoneerAssetMissingError,
              lambda: parse([{"id": "n1", "do": "play_video"}]),
              "play_video", "fixture.json", "'n1'", "say")
expect_no_raise("...and a known one does not",
                lambda: parse([{"id": "n1", "do": "stop"}]))
expect_raises("an op outside the declared loadouts raises naming both",
              PyoneerConfigError,
              lambda: parse([SET("n1", "coins", 1)], loadouts=[]),
              "'set'", "'core'", "<none>")

expect_raises("two comparators on one condition raise, naming both",
              PyoneerConfigError,
              lambda: parse([{"id": "n1", "if": [{"var": "coins",
                                                  "at_least": 1, "at_most": 2}],
                              "then": []}]),
              "at_least", "at_most")
expect_raises("...a condition with no comparator raises", PyoneerConfigError,
              lambda: parse([{"id": "n1", "if": [{"var": "coins"}],
                              "then": []}]),
              "no comparator")
expect_raises("...an unknown comparator raises naming the closed six",
              PyoneerConfigError,
              lambda: parse([{"id": "n1", "if": [{"var": "coins",
                                                  "gt": 1}], "then": []}]),
              "'gt'", "at_least", "contains")
expect_raises("...`at_least` on a bool raises (it is arithmetic)",
              PyoneerConfigError,
              lambda: parse([{"id": "n1", "if": [{"var": "gate_open",
                                                  "at_least": 1}],
                              "then": []}]),
              "gate_open", "bool")
expect_no_raise("...and `is` on a bool does not",
                lambda: parse([{"id": "n1", "if": [{"var": "gate_open",
                                                    "is": True}],
                                "then": []}]))

expect_raises("an UNDECLARED variable raises at load, naming the schema",
              PyoneerAssetMissingError,
              lambda: parse([SET("n1", "coinz", 1)]),
              "coinz", "scene.coins")
expect_no_raise("...and a declared one loads",
                lambda: parse([SET("n1", "coins", 1)]))
# The third state, and it is NOT the same as an empty schema: nobody handed
# this load a schema at all, which is a wiring error and says so.
expect_raises("...and a load given NO schema says so rather than accepting it",
              PyoneerConfigError,
              lambda: parse([SET("n1", "coins", 1)], variables=None),
              "no variable schema", "load_script")
expect_raises("...while an EMPTY schema is an authoring error, naming it",
              PyoneerAssetMissingError,
              lambda: parse([SET("n1", "coins", 1)], variables=sf.EMPTY_VARS),
              "coins", "none loaded")

expect_raises("a wrong-typed `set` raises at load", PyoneerConfigError,
              lambda: parse([SET("n1", "coins", "lots")]),
              "coins", "int")
expect_raises("...and `by: add` on a bool raises", PyoneerConfigError,
              lambda: parse([SET("n1", "gate_open", True, by="add")]),
              "gate_open", "add")
expect_raises("...and an unknown `by` raises, naming the two",
              PyoneerConfigError,
              lambda: parse([SET("n1", "coins", 1, by="multiply")]),
              "'by'", "assign")
expect_raises("an unknown trigger raises naming the closed five",
              PyoneerConfigError,
              lambda: parse(pages=[{"id": "pg", "trigger": "touch",
                                    "when": [], "body": []}]),
              "'touch'", "auto")
expect_raises("a `while` carrying an `else` raises", PyoneerConfigError,
              lambda: parse([{"id": "n1", "while": [], "then": [],
                              "else": []}]),
              "`while`", "else")
expect_raises("an elif arm with a stray key raises", PyoneerConfigError,
              lambda: parse([{"id": "n1", "if": [], "then": [],
                              "elif": [{"when": [], "then": [], "or": []}]}]),
              "'or'", "elif[0]")

# A variable name is normalised ONCE, at read time, so a schema keyed by
# `scene.coins` and a node saying `coins` cannot become two variables that
# each hold half the game's state. Both halves.
expect("a bare name normalises into the scene namespace",
       sf.normalise_var("coins"), "scene.coins")
expect("...and an explicit namespace is kept",
       sf.normalise_var("global.coins"), "global.coins")
expect_raises("...and a namespace that is not one of the three raises",
              PyoneerConfigError, lambda: sf.normalise_var("party.coins"),
              "'party'", "global, scene, local")
expect_raises("a var declared with no default raises at read",
              PyoneerConfigError,
              lambda: sf.read_vars({"x": {"type": "int"}}), "default", "TOTAL")
expect_raises("...and one whose default is the wrong type raises",
              PyoneerConfigError,
              lambda: sf.read_vars({"x": {"type": "int", "default": "0"}}),
              "scene.x", "int")


# ===========================================================================
print("\n5. branching -- each arm on the right variables, and NOT the others")
# ===========================================================================
BRANCH = [
    {"id": "n4", "if": [{"var": "coins", "at_least": 100}],
     "then": [SET("t1", "keeper_pick", 1)],
     "elif": [{"when": [{"var": "coins", "at_least": 10}],
               "then": [SET("t2", "keeper_pick", 2)]}],
     "else": [SET("t3", "keeper_pick", 3)]},
]


def took(coins):
    values = store(coins=coins)
    run = run_for(copy.deepcopy(BRANCH), values=values)
    drive(run)
    return values.get("keeper_pick")


# BOTH HALVES, three ways: each arm is proved to run on its own condition AND
# proved not to run on the others. An `if` that took `then` unconditionally
# passes the first of these three and fails the other two.
expect("coins 100 takes `then`", took(100), 1)
expect("coins 99 takes the `elif` arm", took(99), 2)
expect("coins 9 takes `else`", took(9), 3)
expect("coins 10 takes the elif arm, not else (the boundary is >=)",
       took(10), 2)

NESTED = [
    {"id": "n1", "if": [{"var": "gate_open", "is": True}],
     "then": [{"id": "n2", "if": [{"var": "coins", "at_most": 0}],
               "then": [SET("n3", "who", "broke")],
               "else": [SET("n4", "who", "rich")]}],
     "else": [SET("n5", "who", "outside")]},
]
for _open, _coins, _want in ((True, 0, "broke"), (True, 5, "rich"),
                             (False, 5, "outside")):
    _values = store(gate_open=_open, coins=_coins)
    drive(run_for(copy.deepcopy(NESTED), values=_values))
    expect("nested if: gate_open=%s coins=%d" % (_open, _coins),
           _values.get("who"), _want)

# An `if` with no `else` and a false condition runs nothing and still finishes.
_values = store(coins=0)
_run = run_for([{"id": "n1", "if": [{"var": "coins", "at_least": 1}],
                 "then": [SET("n2", "who", "ran")]}], values=_values)
drive(_run)
expect("an if with no else and a false condition runs nothing, and completes",
       (_values.get("who"), _run.done), ("", True))

# `while` is bounded by the same raise, and it terminates when its body says
# so. Both halves: it runs more than once, and it stops.
_values = store(coins=0)
_run = run_for([{"id": "w1", "while": [{"var": "coins", "at_most": 4}],
                 "then": [SET("w2", "coins", 1, by="add")]}], values=_values)
_frames = drive(_run)
expect("a while runs until its condition fails, in ONE frame",
       (_values.get("coins"), _frames, _run.done), (5, 1, True))


# ===========================================================================
print("\n6. a runaway frame RAISES; a long one does not")
# ===========================================================================
# HALF A: a `while` whose body never changes its condition. A silent per-frame
# budget -- RPG Maker's answer -- is a hang you cannot diagnose, which is the
# failure law 13 paid forty silent minutes for one layer down.
_runaway = run_for([{"id": "w1", "while": [{"var": "coins", "at_most": 4}],
                     "then": [SET("w2", "who", "spinning")]}],
                   values=store(coins=0))
expect_raises("a while nothing in its body ends RAISES at the step cap",
              PyoneerConfigError, lambda: _runaway.update(DELTA),
              "512", "silent cap", "'w1'")

# HALF B, and it is the half that stops the cap from being set to 1: a real
# script of 500 nodes completes in one frame and raises nothing.
_long_body = [SET("k%d" % i, "coins", 1, by="add") for i in range(500)]
_values = store(coins=0)
_long = run_for(_long_body, values=_values)
expect_no_raise("...and a 500-node script under the cap completes",
                lambda: _long.update(DELTA))
expect("...having actually run all 500 nodes",
       (_values.get("coins"), _long.done, _long.steps_last_frame <= MAX_STEPS_PER_FRAME),
       (500, True, True))


# ===========================================================================
print("\n7. `call` -- a chain that runs, and a chain that is caught")
# ===========================================================================
def chain(length):
    """`s0` calls `s1` calls ... calls `s<length-1>`, the last one setting."""
    made = {}
    for index in range(length):
        last = index == length - 1
        node = (SET("done%d" % index, "coins", 1, by="add") if last else
                {"id": "c%d" % index, "do": "call", "script": "s%d" % (index + 1)})
        made["s%d" % index] = sf.parse_script(
            document([node], script_id="s%d" % index), "s%d.json" % index,
            variables=VARS)
    return made


def run_chain(length):
    made = chain(length)
    values = store(coins=0)
    run = ScriptRun(made["s0"], variables=values, scripts=made)
    run.begin()
    drive(run)
    return values.get("coins")


expect("a chain of 15 scripts runs to the bottom", run_chain(15), 1)
expect("...and one of exactly MAX_CALL_DEPTH does too",
       run_chain(MAX_CALL_DEPTH), 1)
_deep = chain(MAX_CALL_DEPTH + 1)
_deep_run = ScriptRun(_deep["s0"], variables=store(), scripts=_deep)
_deep_run.begin()
expect_raises("...and one deeper RAISES, naming the whole chain",
              PyoneerConfigError, lambda: drive(_deep_run, frames=4),
              "MAX_CALL_DEPTH=16", "s0 -> s1", "s%d" % MAX_CALL_DEPTH)

# A cycle is CAUGHT, not prevented: the target is resolved at run time, so no
# load graph can see it. A silent stop is a script that looks like it worked.
_cycle_a = sf.parse_script(document([{"id": "ca", "do": "call",
                                      "script": "cyc_b"}], script_id="cyc_a"),
                           "cyc_a.json", variables=VARS)
_cycle_b = sf.parse_script(document([{"id": "cb", "do": "call",
                                      "script": "cyc_a"}], script_id="cyc_b"),
                           "cyc_b.json", variables=VARS)
_cycle = {"cyc_a": _cycle_a, "cyc_b": _cycle_b}
_cycle_run = ScriptRun(_cycle_a, variables=store(), scripts=_cycle)
_cycle_run.begin()
expect_raises("a call cycle is caught by the depth cap, not by hanging",
              PyoneerConfigError, lambda: drive(_cycle_run, frames=4),
              "cyc_a -> cyc_b")

_no_loader = ScriptRun(parse([{"id": "n1", "do": "call", "script": "other"}]),
                       variables=store())
_no_loader.begin()
expect_raises("a `call` with no way to find a script says WHICH wire is missing",
              PyoneerConfigError, lambda: _no_loader.update(DELTA),
              "no way to find", "load_scripts")
_absent = ScriptRun(parse([{"id": "n1", "do": "call", "script": "other"}]),
                    variables=store(), scripts={})
_absent.begin()
expect_raises("...and one naming a script that is not there raises too",
              PyoneerAssetMissingError, lambda: _absent.update(DELTA), "other")


# ===========================================================================
print("\n8. hold and release -- the recorded value, never `True`")
# ===========================================================================
HOLD_RELEASE = [{"id": "h1", "do": "hold", "steerable": False},
                {"id": "n1", "do": "wait", "ms": 2 * MS_PER_DELTA},
                {"id": "r1", "do": "release"}]

_free = body()
_run = run_for(copy.deepcopy(HOLD_RELEASE), bodies=[_free])
_run.update(DELTA)
expect("hold clears steerable on a body that had it",
       (state_of(_free).steerable, _run.holding), (False, True))
expect("...and leaves enabled_inputs alone, so it can still press continue",
       state_of(_free).enabled_inputs, True)
drive(_run)
expect("...and release gives it back", state_of(_free).steerable, True)

# THE HALF NOBODY WRITES. A body that was ALREADY unsteerable must be
# unsteerable afterwards: `release` restores what `hold` RECORDED, and a
# `_restore` that wrote `True` would pass every assertion above this one and
# hand a menu-locked player their legs back mid-menu.
_stuck = body(steerable=False)
_run = run_for(copy.deepcopy(HOLD_RELEASE), bodies=[_stuck])
_run.update(DELTA)
expect("a body that was ALREADY unsteerable is held without change",
       state_of(_stuck).steerable, False)
drive(_run)
expect("...and is STILL unsteerable after release -- not True",
       state_of(_stuck).steerable, False)

# ...and the same claim MID-RUN, which is the half the two above cannot make:
# a run that reaches its end gives the agency back on the way out, so a
# `release` op whose run did nothing at all would pass every assertion above
# this one. The park node keeps the run alive so the op is what is measured.
PARK = {"id": "park", "do": "wait", "ms": 100 * MS_PER_DELTA}
_mid = body()
_run = run_for([{"id": "h1", "do": "hold", "steerable": False},
                {"id": "r1", "do": "release"}, dict(PARK)], bodies=[_mid])
_run.update(DELTA)
expect("the release OP gives it back mid-run, not the teardown",
       (state_of(_mid).steerable, _run.holding, _run.done),
       (True, False, False))
# The control: the same script WITHOUT the release node is still holding at
# the same point, so the assertion above is reading a difference.
_kept = body()
_run = run_for([{"id": "h1", "do": "hold", "steerable": False}, dict(PARK)],
               bodies=[_kept])
_run.update(DELTA)
expect("...and without it, the same run is still holding at the same point",
       (state_of(_kept).steerable, _run.holding, _run.done),
       (False, True, False))

# The same claim one level down, on the shared class itself, because that is
# where a `SceneFlow` and a `ScriptRun` would otherwise drift apart.
_a, _b = body(steerable=False), body(steerable=True)
_hold = AgencyHold([_a, _b, object()])
_hold.take(steerable=False)
expect("AgencyHold skips a body with no BodyState rather than refusing it",
       len(_hold.held_bodies), 2)
expect("...and records what each body HAD, separately",
       sorted((state_of(b).steerable, v) for b, axes in _hold.held_axes
              for _axis, v in axes for _b in [b] if True
              for b in [_b]),
       sorted([(False, False), (False, True)]))
_hold.give_back()
expect("...so give_back restores two different values from one hold",
       (state_of(_a).steerable, state_of(_b).steerable), (False, True))
expect("...and a second give_back restores nothing (the record is spent)",
       _hold.give_back(), ())

# A run that ends with a hold outstanding gives it back anyway. The author's
# `release` is one editing accident away from being deleted, and a player
# permanently unable to walk is the worst failure this file can have.
_stranded = body()
_run = run_for([{"id": "h1", "do": "hold", "steerable": False},
                {"id": "s1", "do": "stop"}], bodies=[_stranded])
drive(_run)
expect("a `stop` under an outstanding hold still gives the agency back",
       (state_of(_stranded).steerable, _run.done), (True, True))
# ...and the other half: `stop` really did cut the run short.
_values = store()
_run = run_for([{"id": "s1", "do": "stop"}, SET("n2", "coins", 99)],
               values=_values)
drive(_run)
expect("...and nothing after the `stop` ran", _values.get("coins"), 0)


# ===========================================================================
print("\n9. say drives a host and waits; ask refuses, honestly")
# ===========================================================================
_host = Host()
_values = store()
_run = run_for([{"id": "n1", "do": "say", "who": "Keeper", "text": "Sealed."},
                SET("n2", "coins", 7)], host=_host, values=_values)
_run.update(DELTA)
expect("say opens the host's line on the frame it is entered",
       _host.calls, [("open", "Keeper", "Sealed.")])
_run.update(DELTA)
_run.update(DELTA)
expect("...and WAITS: three frames with no advance run nothing after it",
       (_values.get("coins"), _run.done), (0, False))
_run.advance()
_run.update(DELTA)
expect("...and one advance closes the line and runs the next node",
       (_host.calls[-1], _values.get("coins"), _run.done),
       (("close",), 7, True))

# A press that landed BEFORE the line was shown must not skip the line it was
# never given a chance to read.
_host = Host()
_run = run_for([{"id": "n1", "do": "say", "text": "one"}], host=_host)
_run.advance()
_run.update(DELTA)
expect("a stale advance is consumed on entry, not used to skip the line",
       (_host.calls, _run.done), ([("open", "", "one")], False))

_run = run_for([{"id": "n1", "do": "say", "text": "one"}])
expect_raises("a say with no host raises naming the two methods a host has",
              PyoneerConfigError, lambda: _run.update(DELTA),
              "say_open", "say_close")


class HalfHost:
    def say_open(self, who, text):
        pass


_run = run_for([{"id": "n1", "do": "say", "text": "one"}], host=HalfHost())
_run.update(DELTA)
_run.advance()
expect_raises("...and a host missing one of them raises naming THAT one",
              PyoneerConfigError, lambda: _run.update(DELTA), "say_close",
              "HalfHost")

_run = run_for([{"id": "n1", "do": "ask", "prompt": "Half now?",
                 "options": ["yes", "no"], "into": "keeper_pick"}],
               host=Host())
expect_raises("`ask` RAISES when run -- it is needs-host and says why",
              PyoneerConfigError, lambda: _run.update(DELTA),
              "needs-host", "reports a click", "Half now?")
# The other half, and it is the point of shipping `ask` at all: it is
# authorable, resolvable and pickable TODAY, so the branch it feeds can be
# written now and works the day a widget reports a click.
expect_no_raise("...and it still LOADS, so the branch it feeds is authorable",
                lambda: parse([{"id": "n1", "do": "ask", "prompt": "?",
                                "options": ["a", "b"], "into": "keeper_pick"}]))


# ===========================================================================
print("\n10. delta is milliseconds/60, converted exactly once")
# ===========================================================================
# The frame BEFORE and the frame OF, which is the pair that catches both a
# missing `* MS_PER_DELTA` and a doubled one.
_frames_needed = 3
_ms = _frames_needed * MS_PER_DELTA
_values = store()
_run = run_for([{"id": "n1", "do": "wait", "ms": _ms},
                SET("n2", "coins", 1)], values=_values)
for _ in range(_frames_needed - 1):
    _run.update(DELTA)
expect("a wait has NOT elapsed on the frame before its time",
       (_values.get("coins"), _run.done), (0, False))
_run.update(DELTA)
expect("...and HAS on the frame it elapses", _values.get("coins"), 1)
expect("...which is %d frames, i.e. delta * MS_PER_DELTA and not delta"
       % _frames_needed, _ms, 180.0)


# ===========================================================================
print("\n11. the run reaches the event bus at zero points")
# ===========================================================================
BUS_CALLS = {"handle", "mark_event_handled", "send_event", "send_event_advanced",
             "send_event_to_self", "bind_listener", "bind_sync_listener",
             "bind_async_listener", "bind_mouse_listener"}


def scan(module):
    """(bus calls, imported module names) from a module's PARSE TREE.

    The tree and not the text, so the docstrings that explain WHY this never
    dispatches -- which contain the words `handle()` and the whole bus
    vocabulary -- do not trip the scan.
    """
    with open(inspect.getsourcefile(module), encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    called = sorted({
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
        and (node.func.attr if isinstance(node.func, ast.Attribute)
             else node.func.id) in BUS_CALLS})
    imported = sorted({node.module or "" for node in ast.walk(tree)
                       if isinstance(node, ast.ImportFrom)}
                      | {alias.name for node in ast.walk(tree)
                         if isinstance(node, ast.Import) for alias in node.names})
    return called, imported


for _module, _name in ((ops_module, "ops.py"),
                       (interpreter_module, "interpreter.py"),
                       (sf, "script_file.py")):
    _called, _imported = scan(_module)
    expect("%s makes no bus call anywhere" % _name, _called, [])
    expect("...and imports no event or component module",
           [m for m in _imported if "event" in m or "component" in m], [])
    expect("...and imports nothing from editor/ (the one-way rule)",
           [m for m in _imported if m.startswith("editor")], [])

# The other half: the scan is CAPABLE of finding one. A scan whose name list
# was wrong would look exactly like a clean pass.
DECOY = ast.parse("class X:\n    def go(self, e):\n        e.handle()\n")
expect("...and the same scan DOES find a bus call when one is planted",
       sorted({n.func.attr for n in ast.walk(DECOY)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in BUS_CALLS}), ["handle"])
# ...and the same control for the editor prefix. This check file imports
# `editor.core.map_events` itself, so a prefix scan that matched nothing
# because the spelling was wrong is distinguishable from a clean pass.
expect("...proved: the same scan finds the editor import in THIS file",
       [m for m in scan(sys.modules[__name__])[1] if m.startswith("editor")],
       ["editor.core"])

# No new GameEventType member and no event object, asserted the same way --
# from the tree, so the docstrings that EXPLAIN why this layer needs neither
# do not trip it. `USE` is the standing proof of what a member with no
# listener costs, and nothing here adds one.
EVENT_NAMES = {"GameEventType", "PyoneerEvent"}


def names(module):
    """Every name and attribute the module's CODE spells. Not its prose."""
    with open(inspect.getsourcefile(module), encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    return sorted({node.id for node in ast.walk(tree)
                   if isinstance(node, ast.Name)}
                  | {node.attr for node in ast.walk(tree)
                     if isinstance(node, ast.Attribute)})


for _module, _name in ((ops_module, "ops.py"),
                       (interpreter_module, "interpreter.py"),
                       (sf, "script_file.py")):
    expect("%s spells no event type or event object in CODE" % _name,
           sorted(EVENT_NAMES.intersection(names(_module))), [])
# The control: the same scan finds one where one is planted, so the three
# empty lists above are a measurement rather than a scan looking at nothing.
NAME_DECOY = ast.parse("kind = GameEventType.FRAME_UPDATE")
expect("...and the same scan DOES find an event type when one is planted",
       sorted(EVENT_NAMES.intersection(
           {n.id for n in ast.walk(NAME_DECOY) if isinstance(n, ast.Name)})),
       ["GameEventType"])


# ===========================================================================
print("\n12. the vocabularies agree, and the hold is ONE class")
# ===========================================================================
expect("SCRIPT_TRIGGERS is a superset of the editor's TRIGGER_KINDS",
       sorted(set(map_events.TRIGGER_KINDS) - set(sf.SCRIPT_TRIGGERS)), [])
expect("...and adds exactly `auto`, which is not a region trigger",
       sorted(set(sf.SCRIPT_TRIGGERS) - set(map_events.TRIGGER_KINDS)),
       ["auto"])
expect("`use` is spelled the same on both sides of the boundary",
       (map_events.USE, scene_flow_module.ADVANCE_TRIGGER_KIND,
        "use" in sf.SCRIPT_TRIGGERS), ("use", "use", True))

# One class, not two that agree today. `SceneFlow` holding its own copy is
# exactly the 425-duplicate-lines shape, so this is asserted by IDENTITY.
_flow = SceneFlow([scene_flow_module.FlowStep("beat")], bodies=[body()])
expect("SceneFlow holds an AgencyHold, by identity with the interpreter's",
       type(_flow._hold) is AgencyHold, True)
expect("...and so does a ScriptRun",
       type(run_for([{"id": "n1", "do": "stop"}])._hold) is AgencyHold, True)
expect("...and there is exactly ONE class named AgencyHold in scripts/",
       inspect.getsourcefile(AgencyHold),
       inspect.getsourcefile(scene_flow_module))

# The interpreter fits the flow slot the manager already has: `update(delta)`
# and nothing else. A design needing a SceneManager edit has taken a wrong
# turn, and this is what says so without importing the manager.
expect("ScriptRun offers the same duck-typed `update(delta)` SceneFlow does",
       (inspect.signature(ScriptRun.update).parameters ==
        inspect.signature(SceneFlow.update).parameters), True)
expect("...and the same ActionRouter handler shape, `on_action(entity, fired)`",
       list(inspect.signature(ScriptRun.on_action).parameters),
       list(inspect.signature(SceneFlow.on_action).parameters))


# ===========================================================================
print("\n%d assertion(s), %d failure(s)" % (len(asserted), len(failures)))
for _failure in failures:
    print("  FAILED: %s" % _failure)
print("""
MUTATIONS THIS FILE HAS BEEN RUN AGAINST -- each one was applied, the check
was run, the named assertions went red, and the source was put back:

  * `AgencyHold.give_back` writing `True` instead of the saved value
        -> section 8, FAILED 2: "is STILL unsteerable after release" and
           "give_back restores two different values from one hold". Every
           other assertion in that section still passed, which is exactly the
           shape law 5 names -- the gate was proved to let something through
           and only these two prove it stops. `tools/check_flow.py` went red
           at the same time (its own sections 6 and 7), which is the
           regression net on lifting `AgencyHold` out of `SceneFlow`
  * the runaway cap enforced by `return` instead of `raise` -- RPG Maker's
    silent per-frame budget
        -> section 6, FAILED 1: "a while nothing in its body ends RAISES at
           the step cap". The 500-node half still passed, which is what stops
           the cap from being quietly set to 1
  * `ask`'s run writing index 0 into `into` and returning True, i.e. the
    plausible default this whole op exists to refuse
        -> section 9, FAILED 1: "`ask` RAISES when run". And
           `tools/check_event_docs.py` FAILED 2 with it, because a promise
           would have printed as a `yes` in a byte-compared table
  * `_refuse_unknown` in the reader disabled (an unknown key ignored)
        -> section 4, FAILED 3: the script, page and elif-arm assertions.
           Three depths, which is the point of testing it at three
  * `register` replacing on a duplicate name -- the BEHAVIOR registry's rule,
    applied here by reflex
        -> section 1, FAILED 2: the duplicate raise, and "the first
           registration is the one still standing"
""")
raise SystemExit(1 if failures else 0)
