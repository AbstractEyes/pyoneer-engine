"""Verify the entity behavior system: the contract, the table, the drive.

Thirteen claims, every one of which the code is otherwise free to break with
no visible symptom until an entity silently stops doing something:

     1. the tmx vocabulary is the file-format string it says it is, the
        prefix is imported rather than retyped, and one spelling is used
     2. a BehaviorSpec refuses to be declared incoherently
     3. `hooks` is DERIVED from the class, so it cannot go stale
     4. a parameter raises on a wrong type instead of quietly defaulting
     5. an unknown token raises and lists the registry -- never falls back
     6. the token list reads leniently and writes strictly
     7. parameters resolve object > actors > default, and `source` decides
        whether the middle step is read at all
     8. run order is the DECLARED order, not the attach order
     9. a same-order pair that writes the same attribute is REFUSED
    10. the drive runs a snapshot, honours `enabled`, and never swallows
    11. an empty behavior set is frame-neutral on a real GameEntity
    12. BEHAVIORS.md is generated from the table the engine binds from
    13. `scripts/` does not import `editor/`

THE FIXTURE IS THIS FILE'S OWN
------------------------------
Every behavior below is defined here and registered into a SCRATCH registry.
`data/maps/starter.tmx` is the shipped map and is never read here: a check that
pins map CONTENT goes red the next time he paints, while the code it guards
is working perfectly (law 4).

`BEHAVIOR_REGISTRY` itself is asserted for SHAPE, not for emptiness: the four
concrete behaviors that ship on top of this base -- `player_input`,
`topdown_move`, `platformer_move`, `animation_drive` -- are covered by
`tools/check_movement.py`, and section 5 only proves an unknown token still
raises against the real table and that a scratch registration cannot leak
into it.

    .venv/Scripts/python.exe tools/check_behavior.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import ast
import json
import os
import shutil
import tempfile
import warnings

import pygame

pygame.init()

from scripts.core import layer_profile
from scripts.core.component import GameComponent
from scripts.core.errors import (PyoneerAssetMissingError, PyoneerConfigError,
                                 PyoneerContentWarning, PyoneerError)
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.game.behavior import (ACTOR, BEHAVIOR_REGISTRY, BEHAVIORS,
                                   KNOWN, PARAM_PREFIX, PARAM_TYPES,
                                   BehaviorParam,
                                   BehaviorRequest, BehaviorSpec,
                                   EntityBehavior, EntityBehaviors, build,
                                   describe_all, format_list, parse_list,
                                   read_requests, register, resolve,
                                   resolve_params, validate_list)
from scripts.game.behavior.base import PARAM_SOURCES
from scripts.game.entity.game_entity import GameEntity
from scripts.loaders.table_file import (ACTORS, TABLES_DIR,
                                        ProjectTables, actor_row,
                                        load_tables, row_id)
# The one editor import in this file, and it exists to bind ONE fact: the
# path the Database panel writes to is the path the engine reads from.
# `editor/` may import `scripts/` and never the reverse (law 2); a CHECK
# stands outside both, and is the only place the two spellings of that
# path can be compared without either package learning about the other.
import editor.core.project as editor_project

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
    """The call must raise `exception`, and the message must name each fragment.

    The fragments are the teeth. An assertion that checks only the exception
    TYPE passes for any raise anywhere inside the call, including one from a
    typo three frames down.
    """
    asserted.append(label)
    try:
        call()
    except exception as exc:
        text = str(exc)
        missing = [f for f in fragments if f not in text]
        ok = not missing
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} "
              f"raised {type(exc).__name__}: {text.splitlines()[0][:64]}")
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


def expect_warns(label, call, *fragments):
    """The call must emit a PyoneerContentWarning naming each fragment."""
    asserted.append(label)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = call()
    texts = [str(w.message) for w in caught
             if issubclass(w.category, PyoneerContentWarning)]
    if not texts:
        print(f"  FAIL {label:<58} warned nothing "
              f"({len(caught)} other warning(s))")
        failures.append(label)
        return result
    joined = " || ".join(texts)
    missing = [f for f in fragments if f not in joined]
    ok = not missing
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} {joined[:64]}")
    if not ok:
        failures.append(f"{label} (warning lacks {missing})")
    return result


# ---------------------------------------------------------------------------
# The fixture entity. Concrete on purpose and with no art dependency:
# GamePlayer needs a spritesheet this repository deliberately does not ship,
# so driving the composition through it would make this check unrunnable on
# a clone.
# ---------------------------------------------------------------------------

class ProbeEntity(GameEntity):
    """A GameEntity that is actually constructible.

    GameEntity leaves core_lifecycle_build and core_input_receive abstract;
    filling those two in is the entire difference between the base class and
    something that can be stood up in a check.
    """

    def core_lifecycle_build(self, event=None):
        pass

    def core_input_receive(self, events=None):
        pass


def probe() -> ProbeEntity:
    """A fresh entity with a behavior set, exactly as the integration does it."""
    entity = ProbeEntity()
    entity.behaviors = EntityBehaviors(entity)
    return entity


def frame(delta: float = 1.0) -> PyoneerEvent:
    return PyoneerEvent(GameEventType.UPDATE, data={"delta": delta})


# ---------------------------------------------------------------------------
# The fixture behaviors.
# ---------------------------------------------------------------------------

LOG: list[str] = []


class _Recorder(EntityBehavior):
    """Overrides all three lifecycle methods, so `hooks` reports all three."""

    def attach(self, entity):
        LOG.append("attach:" + self.name)

    def update(self, entity, event):
        LOG.append("update:" + self.name)

    def detach(self, entity):
        LOG.append("detach:" + self.name)


class _Alpha(_Recorder):
    pass


class _Zed(_Recorder):
    pass


class _UpdateOnly(EntityBehavior):
    """Overrides update ALONE, so `hooks` must report exactly ('update',)."""

    def update(self, entity, event):
        LOG.append("update:" + self.name)


class _Solo(_Recorder):
    pass


class _Duo(_Recorder):
    pass


class _ClashA(_Recorder):
    pass


class _ClashB(_Recorder):
    pass


class _DisjointA(_Recorder):
    pass


class _DisjointB(_Recorder):
    pass


class _SelfDetach(_Recorder):
    def update(self, entity, event):
        LOG.append("update:" + self.name)
        entity.behaviors.detach(self)


class _RaisesPyoneer(_Recorder):
    def update(self, entity, event):
        raise PyoneerConfigError("fixture explosion")


class _RaisesValue(_Recorder):
    def update(self, entity, event):
        raise ValueError("a plain exception the engine did not invent")


class _RaisesOnAttach(_Recorder):
    """Refuses itself in `attach`, which is `player_input`'s designed path.

    Not a hypothetical: `player_input.attach` raises when a verb it polls is
    unbound, precisely so the failure names the verb instead of arriving as a
    KeyError from inside a frame. The set must not keep what the hook refused.
    """

    def attach(self, entity):
        raise PyoneerConfigError("fixture refuses to attach")


class _Nudge(EntityBehavior):
    """Moves the real entity through the real gate, so the drive is proven."""

    def __init__(self, direction: str = "right"):
        self.direction = direction

    def update(self, entity, event):
        entity.move_direction(event.data["delta"], self.direction)


class _Params(EntityBehavior):
    def __init__(self, gravity: float = 0.0, air_control: float = 0.0,
                 mode: str = "off"):
        self.gravity = gravity
        self.air_control = air_control
        self.mode = mode

    def update(self, entity, event):
        pass


class _Needs(EntityBehavior):
    def __init__(self, ghost: int = 0):
        self.ghost = ghost

    def update(self, entity, event):
        pass


class _NoKwargs(EntityBehavior):
    """Takes nothing. A spec that declares a parameter for it must blow up.

    The empty `__init__` is load-bearing: a class with no `__init__` at all
    reports "takes no arguments" and never names the offending keyword, so
    the failure would not tell an author which parameter was wrong.
    """

    def __init__(self):
        pass

    def update(self, entity, event):
        pass


class _Unregistered(EntityBehavior):
    """Never registered, therefore never spec-stamped, therefore unorderable."""

    def update(self, entity, event):
        pass


def _plain_factory():
    """A factory that is a function and not a class: `hooks` must say nothing."""
    return _UpdateOnly()


class _NotABehavior:
    """Deliberately not an EntityBehavior. `build` must refuse it."""


SCRATCH: dict[str, BehaviorSpec] = {}

ALPHA = BehaviorSpec("alpha", "Runs late.", _Alpha, order=90,
                     writes=("transform.position",))
ZED = BehaviorSpec("zed", "Runs early.", _Zed, order=10,
                   writes=("transform.position",))
UPDATE_ONLY = BehaviorSpec("update_only", "Only implements update.",
                           _UpdateOnly, order=50)
SOLO = BehaviorSpec("solo", "Refuses to share.", _Solo, order=50,
                    conflicts=("duo",))
DUO = BehaviorSpec("duo", "The one solo refuses.", _Duo, order=50)
CLASH_A = BehaviorSpec("clash_a", "Same order, same write.", _ClashA,
                       order=30, writes=("velocity",))
CLASH_B = BehaviorSpec("clash_b", "Same order, same write.", _ClashB,
                       order=30, writes=("velocity",))
DISJOINT_A = BehaviorSpec("disjoint_a", "Same order, different write.",
                          _DisjointA, order=30, writes=("velocity",))
DISJOINT_B = BehaviorSpec("disjoint_b", "Same order, different write.",
                          _DisjointB, order=30, writes=("state.facing",))
SELF_DETACH = BehaviorSpec("self_detach", "Leaves mid-frame.", _SelfDetach,
                           order=10)
RAISES_PYONEER = BehaviorSpec("raises_pyoneer", "Explodes.", _RaisesPyoneer)
RAISES_VALUE = BehaviorSpec("raises_value", "Explodes plainly.", _RaisesValue)
RAISES_ON_ATTACH = BehaviorSpec("raises_on_attach", "Refuses itself.",
                                _RaisesOnAttach, order=5)
NUDGE = BehaviorSpec("nudge", "Moves the entity one step per frame.", _Nudge,
                     order=20, writes=("transform.position",),
                     requires=("transform.position",))
PARAMS = BehaviorSpec(
    "params", "Carries one parameter of each resolution shape.", _Params,
    order=40,
    params=(
        BehaviorParam("gravity", "gravity", "float", 9.0,
                      "Falls back to 9.0.", source="actors"),
        BehaviorParam("air_control", "air control", "float", 0.25,
                      "Per-object only.", source="object"),
        BehaviorParam("mode", "mode", "str", "off",
                      "One of a fixed set.", choices=("off", "on")),
    ))
PARAMS_ALIAS = BehaviorSpec(
    "params_alias", "A second token for the same class.", _Params, order=41,
    params=(BehaviorParam("gravity", "gravity", "float", 9.0, "", source="actors"),))
NEEDS = BehaviorSpec(
    "needs", "Has a required parameter and an unmet requirement.", _Needs,
    order=60, requires=("action_manager",),
    params=(BehaviorParam("ghost", "ghost", "int", 0,
                          "Nothing supplies it.", required=True),))
GHOST_KWARG = BehaviorSpec(
    "ghost_kwarg", "Declares a parameter its constructor will not take.",
    _NoKwargs, order=61,
    params=(BehaviorParam("ghost", "ghost", "int", 0, "Not a kwarg."),))
BAD_BUILD = BehaviorSpec("bad_build", "Builds the wrong thing.",
                         _NotABehavior, order=62)
PLAIN = BehaviorSpec("plain", "Built by a function.", _plain_factory, order=63)

# PARAMS is registered BEFORE PARAMS_ALIAS on purpose: `register` stamps the
# factory class only when it is unstamped, so `_Params.spec` is PARAMS
# forever and an instance built from PARAMS_ALIAS can only know its own name
# if `build` stamped the INSTANCE. Without the alias, "the instance is
# stamped" is an assertion satisfied by the class attribute, and therefore one
# that cannot fail.
for _spec in (ALPHA, ZED, UPDATE_ONLY, SOLO, DUO, CLASH_A, CLASH_B,
              DISJOINT_A, DISJOINT_B, SELF_DETACH, RAISES_PYONEER,
              RAISES_VALUE, RAISES_ON_ATTACH, NUDGE, PARAMS, PARAMS_ALIAS,
              NEEDS, GHOST_KWARG,
              BAD_BUILD, PLAIN):
    register(_spec, SCRATCH)


# ===========================================================================
print("\n1. the tmx vocabulary, pinned against literals")
# ===========================================================================
# Compared against LITERAL strings, never against the module's own constants:
# `expect("x", BEHAVIORS, BEHAVIORS)` is the assertion this repo has now
# found eleven of. These are file-format strings -- once a .tmx carries one,
# changing it means touching maps -- so a literal is exactly right here.
expect("the behavior list property", BEHAVIORS, "pyoneer_behaviors")
expect("the actor-row property", ACTOR, "pyoneer_actor")
expect("the parameter override prefix", PARAM_PREFIX, "pyoneer_param_")
expect("KNOWN names the fixed properties and not the prefix",
       KNOWN, ("pyoneer_behaviors", "pyoneer_actor"))
expect("the prefix agrees with the layer vocabulary",
       BEHAVIORS[:len(layer_profile.PREFIX)], layer_profile.PREFIX)

PACKAGE = os.path.join(_bootstrap.REPO_ROOT, "scripts", "game", "behavior")
SOURCES: dict[str, str] = {}
for _name in sorted(os.listdir(PACKAGE)):
    if _name.endswith(".py"):
        with open(os.path.join(PACKAGE, _name), encoding="utf-8") as handle:
            SOURCES[_name] = handle.read()
SOURCES["tools/check_behavior.py"] = open(__file__, encoding="utf-8").read()
expect_true("the package has files to scan", len(SOURCES) >= 4)

# The prefix must be IMPORTED, not retyped. A text search would trip over the
# docstrings that legitimately quote `pyoneer_behaviors` in prose, so this
# reads the parse tree and asserts the module-level `PREFIX` assignment binds
# an ATTRIBUTE and not a string constant. Retyping `PREFIX = "pyoneer_"`
# would still pass an `is` comparison -- CPython interns that literal -- so
# identity is not teeth here and the AST is.
_base_tree = ast.parse(SOURCES["base.py"])
_prefix_values = [node.value for node in _base_tree.body
                  if isinstance(node, ast.AnnAssign)
                  and isinstance(node.target, ast.Name)
                  and node.target.id == "PREFIX"]
_prefix_values += [node.value for node in _base_tree.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "PREFIX"
                           for t in node.targets)]
expect("base.py binds PREFIX exactly once", len(_prefix_values), 1)
expect_true("PREFIX is an attribute reference, not a retyped literal",
            _prefix_values and not isinstance(_prefix_values[0], ast.Constant))
expect_true("base.py imports the layer vocabulary",
            any(isinstance(n, ast.ImportFrom) and n.module == "scripts.core"
                and any(a.name == "layer_profile" for a in n.names)
                for n in ast.walk(_base_tree)))

# One spelling. `pyoneer_behaviors` is a file-format string and the tree is
# split 21/17 on the two spellings, so the decision is pinned rather than
# inherited from whoever types next. The needle is built from pieces so this
# file can scan itself without matching its own assertion.
BRITISH = "behavi" + "our"
_misspelt = sorted(name for name, text in SOURCES.items()
                   if BRITISH in text.lower())
expect("one spelling across the owned surface", _misspelt, [])

# The fence: scripts/ may never import editor/.
for _name, _text in SOURCES.items():
    if _name.startswith("tools/"):
        continue
    for _node in ast.walk(ast.parse(_text)):
        _module = ""
        if isinstance(_node, ast.ImportFrom):
            _module = _node.module or ""
        elif isinstance(_node, ast.Import):
            _module = _node.names[0].name
        if _module == "editor" or _module.startswith("editor."):
            failures.append(f"{_name} imports {_module}")
            print(f"  FAIL {_name} imports {_module}")
print(f"  ok   {'no engine module imports editor/':<58} "
      f"{len(SOURCES) - 1} file(s) scanned")


# ===========================================================================
print("\n2. a BehaviorSpec refuses to be declared incoherently")
# ===========================================================================
expect_raises("a token that is not snake_case", PyoneerConfigError,
              lambda: BehaviorSpec("TopDown", "s", _Alpha),
              "TopDown", "^[a-z]")
expect_raises("a factory that is not callable", PyoneerConfigError,
              lambda: BehaviorSpec("nope", "s", 17), "not callable")
expect_raises("order given as a bool", PyoneerConfigError,
              lambda: BehaviorSpec("nope", "s", _Alpha, order=True),
              "order=True")
expect_raises("an unknown status", PyoneerConfigError,
              lambda: BehaviorSpec("nope", "s", _Alpha, status="soon"),
              "'soon'", "authoring-only")
expect_raises("the same parameter key twice", PyoneerConfigError,
              lambda: BehaviorSpec(
                  "nope", "s", _Alpha,
                  params=(BehaviorParam("g", "g", "int", 0, ""),
                          BehaviorParam("g", "g", "int", 1, ""))),
              "'g'", "twice")
expect_raises("binding an event type that does not exist", PyoneerConfigError,
              lambda: BehaviorSpec("nope", "s", _Alpha, binds=("NOT_AN_EVENT",)),
              "NOT_AN_EVENT", "GameEventType")
expect_raises("listing itself as a conflict", PyoneerConfigError,
              lambda: BehaviorSpec("nope", "s", _Alpha, conflicts=("nope",)),
              "itself")
expect_true("a real GameEventType member is accepted",
            BehaviorSpec("ok_binds", "s", _Alpha,
                         binds=("UPDATE",)).binds == ("UPDATE",))
expect_true("UPDATE really is a GameEventType member",
            hasattr(GameEventType, "UPDATE"))
expect_raises("a parameter key that is not snake_case", PyoneerConfigError,
              lambda: BehaviorParam("Move Speed", "l", "int", 0, ""),
              "Move Speed")
expect_raises("a parameter type the tmx cannot carry", PyoneerConfigError,
              lambda: BehaviorParam("g", "l", "vector", 0, ""), "vector")
expect_raises("a parameter source with nowhere to read from",
              PyoneerConfigError,
              lambda: BehaviorParam("g", "l", "int", 0, "", source="genre"),
              "genre", "object, actors")


# ===========================================================================
print("\n3. hooks are DERIVED from the class, so they cannot go stale")
# ===========================================================================
expect("a behavior overriding all three reports all three",
       ALPHA.hooks, ("attach", "update", "detach"))
expect("a behavior overriding update alone reports only update",
       UPDATE_ONLY.hooks, ("update",))
expect("a function factory reports nothing rather than guessing",
       PLAIN.hooks, ())
expect("_Nudge implements update alone", NUDGE.hooks, ("update",))
expect("param() finds a declared parameter",
       PARAMS.param("air_control").source, "object")
expect("param() returns None for one that was never declared",
       PARAMS.param("jump_velocity"), None)
expect("param_keys lists them in declaration order",
       PARAMS.param_keys, ("gravity", "air_control", "mode"))


# ===========================================================================
print("\n4. a parameter raises on a wrong type instead of quietly defaulting")
# ===========================================================================
_int = BehaviorParam("move_speed", "move speed", "int", 16, "")
_float = BehaviorParam("gravity", "gravity", "float", 9.0, "")
_choice = BehaviorParam("mode", "mode", "str", "off", "", choices=("off", "on"))
expect("an int arrives as an int", _int.coerce(20), 20)
expect_raises("an untyped tmx property is a string and raises",
              PyoneerConfigError, lambda: _int.coerce("20", "object 7"),
              "object 7", "pyoneer_param_move_speed", "'20'")
expect_raises("True is an int in Python and must not become 1",
              PyoneerConfigError, lambda: _int.coerce(True), "boolean")
expect("an int widens to a declared float", _float.coerce(900), 900.0)
expect("and it really is a float, not the int it arrived as",
       type(_float.coerce(900)).__name__, "float")
expect_raises("a value outside the declared choices", PyoneerConfigError,
              lambda: _choice.coerce("sideways"), "sideways", "'off'", "'on'")
expect("a value inside them passes through", _choice.coerce("on"), "on")
expect("the override property name is derived from the key",
       _int.property_name, "pyoneer_param_move_speed")


# ===========================================================================
print("\n5. an unknown token raises and lists the registry")
# ===========================================================================
_shipped = sorted(BEHAVIOR_REGISTRY)
# Pinned deliberately, and edited by hand when a behavior lands. The registry
# is CODE, not map content, so this is a legal thing to pin -- and what it
# catches is an accidental registration: a fixture registered into the shipped
# table instead of a scratch one, or a demo's behavior leaking into the
# engine's. `demos/behaviors.py` registers `patrol_input` and must NOT appear
# here, because it is a game's behavior and not the engine's.
expect("the shipped table is exactly the engine's own behaviors", _shipped,
       ["action_relay", "animation_drive", "attack_action", "interact_action",
        "lifecycle_mark", "pause_action", "platformer_move", "player_input",
        "topdown_move"])
expect_raises("an unknown token names itself and lists the SHIPPED table",
              PyoneerAssetMissingError, lambda: resolve("topdown_mvoe"),
              "topdown_mvoe", "entity behavior", "topdown_move",
              "player_input")
expect_raises("an unknown token lists its siblings", PyoneerAssetMissingError,
              lambda: resolve("topdown_mvoe", SCRATCH),
              "topdown_mvoe", "alpha", "zed")
expect_raises("and says where to register it", PyoneerAssetMissingError,
              lambda: resolve("nope", SCRATCH),
              "scripts/game/behavior/registry.py", "pyoneer_behaviors")
expect("a known token resolves to its spec", resolve("zed", SCRATCH).order, 10)

# Re-registration replaces, deliberately -- the same contract spawn.register
# documents, and the only sanctioned way to swap a behavior out in a check.
_swap: dict[str, BehaviorSpec] = {}
register(BehaviorSpec("dup", "first", _Alpha, order=1), _swap)
register(BehaviorSpec("dup", "second", _Zed, order=2), _swap)
expect("the second registration of a name wins",
       (resolve("dup", _swap).summary, resolve("dup", _swap).order),
       ("second", 2))
expect("registering into a scratch table leaves the real one alone",
       ("dup" in BEHAVIOR_REGISTRY, sorted(BEHAVIOR_REGISTRY)),
       (False, _shipped))
expect("register stamps the class so a hand-built instance knows its order",
       _Zed().spec.name, "zed")
expect("an unregistered class carries no spec", _NotABehavior().__dict__, {})


# ===========================================================================
print("\n6. the token list reads leniently and writes strictly")
# ===========================================================================
# The input here is deliberately NOT canonical. Round-tripping an
# already-canonical list through a normaliser proves nothing, because the
# normaliser is a no-op on it.
expect("mixed case, stray spaces, stray commas",
       parse_list("  Zed , alpha ,,  UPDATE_ONLY "),
       ("zed", "alpha", "update_only"))
expect("duplicates are KEPT so validate_list can report them",
       parse_list(" B , a ,a "), ("b", "a", "a"))
expect("whitespace alone separates too", parse_list("zed alpha"),
       ("zed", "alpha"))
expect("None is an empty list, not an error", parse_list(None), ())
expect("an empty string is an empty list", parse_list("   ,, "), ())
expect("a list of strings is accepted", parse_list([" Zed", "alpha"]),
       ("zed", "alpha"))
expect("format_list writes the canonical form",
       format_list(("zed", "alpha")), "zed,alpha")
expect("parse(format(parse(messy))) is stable",
       parse_list(format_list(dict.fromkeys(parse_list(" B , a ,a ")))),
       ("b", "a"))
expect_raises("format_list refuses a duplicate", PyoneerConfigError,
              lambda: format_list(("zed", "zed")), "'zed'", "twice")
expect_raises("format_list refuses a token a .tmx cannot carry",
              PyoneerConfigError, lambda: format_list(("Top Down",)),
              "Top Down")
expect("validate_list returns the list AS AUTHORED, not reordered",
       validate_list("alpha,zed", SCRATCH), ("alpha", "zed"))
expect_raises("validate_list refuses an unknown token",
              PyoneerAssetMissingError,
              lambda: validate_list("alpha,ghost", SCRATCH, "object id=7"),
              "ghost")
expect_raises("validate_list refuses a duplicate", PyoneerConfigError,
              lambda: validate_list("alpha,alpha", SCRATCH, "object id=7"),
              "'alpha'", "object id=7")
expect_raises("validate_list refuses a declared conflict", PyoneerConfigError,
              lambda: validate_list("solo,duo", SCRATCH, "object id=9"),
              "'solo'", "'duo'", "conflict")
expect("conflict is symmetric: only solo declares it",
       (SOLO.conflicts, DUO.conflicts), (("duo",), ()))


# ===========================================================================
print("\n7. parameters resolve object > actors > default")
# ===========================================================================
# Three DIFFERENT numbers at the three levels. Making them equal would let
# any reading order pass, which is failure number four on the reviewer's list.
OBJECT_VALUE, ACTORS_VALUE, DEFAULT_VALUE = 1.0, 2.0, 9.0
expect("the declared default is the third value",
       PARAMS.param("gravity").default, DEFAULT_VALUE)

_all_three = resolve_params(
    PARAMS,
    {"pyoneer_param_gravity": OBJECT_VALUE, "pyoneer_param_mode": "on"},
    {"gravity": ACTORS_VALUE}, "object id=1")
expect("the object override beats the actors row", _all_three["gravity"],
       OBJECT_VALUE)
expect("and a declared choice comes through", _all_three["mode"], "on")

_actors_only = resolve_params(PARAMS, {}, {"gravity": ACTORS_VALUE},
                              "object id=2")
expect("the actors row beats the default", _actors_only["gravity"],
       ACTORS_VALUE)

_neither = resolve_params(PARAMS, {}, None, "object id=3")
expect("with neither, the default answers", _neither["gravity"], DEFAULT_VALUE)
expect("and every declared key is present in the result",
       sorted(_neither), ["air_control", "gravity", "mode"])

# `source="object"` means per-instance BY DECLARATION, so an actors column of
# that name is a value nothing can read -- reported, not silently dropped.
_ignored = expect_warns(
    "an actors value for a per-object parameter warns",
    lambda: resolve_params(PARAMS, {}, {"air_control": 0.9}, "object id=4"),
    "air_control", "object id=4", "pyoneer_param_air_control")
expect("...and the per-object parameter keeps its default",
       _ignored["air_control"], 0.25)
expect("...while an object override for it is honoured",
       resolve_params(PARAMS, {"pyoneer_param_air_control": 0.5},
                      {"air_control": 0.9}, "object id=5")["air_control"], 0.5)

expect_raises("a required parameter with nothing anywhere", PyoneerConfigError,
              lambda: resolve_params(NEEDS, {}, None, "object id=6"),
              "object id=6", "'needs'", "'ghost'")
expect("a required parameter supplied by the object resolves",
       resolve_params(NEEDS, {"pyoneer_param_ghost": 3}, None,
                      "object id=6")["ghost"], 3)

# read_requests: the whole object, in one call.
_requests = read_requests({BEHAVIORS: " Zed , alpha "},
                          registry=SCRATCH, where="object id=8")
expect("read_requests produces one request per token", len(_requests), 2)
expect("in the order the map authored them",
       tuple(r.spec.name for r in _requests), ("zed", "alpha"))
expect("and carries where it came from", _requests[0].where, "object id=8")
expect_warns(
    "a param no listed behavior consumes is a typo and warns",
    lambda: read_requests({BEHAVIORS: "zed", "pyoneer_param_gravty": 4.0},
                          registry=SCRATCH, where="object id=9"),
    "gravty", "object id=9")
expect("an object with no behaviors property asks for nothing",
       read_requests({}, registry=SCRATCH), ())

# read_requests must go through validate_list, not merely parse. The two are
# tested separately above, and nothing bound them: swapping the call for the
# parser leaves `resolve` catching the UNKNOWN token, so the suite stayed
# green while duplicate and conflict -- the two contracts only validate_list
# enforces -- passed straight through to attach.
expect_raises("read_requests refuses a duplicated token, not just an unknown",
              PyoneerConfigError,
              lambda: read_requests({BEHAVIORS: "alpha,alpha"},
                                    registry=SCRATCH, where="object id=11"),
              "'alpha'", "object id=11")
expect_raises("read_requests refuses a declared conflict",
              PyoneerConfigError,
              lambda: read_requests({BEHAVIORS: "solo,duo"},
                                    registry=SCRATCH, where="object id=12"),
              "'solo'", "'duo'", "conflict")
expect_raises("read_requests refuses an unknown token",
              PyoneerAssetMissingError,
              lambda: read_requests({BEHAVIORS: "alpha,ghost"},
                                    registry=SCRATCH, where="object id=13"),
              "ghost")

# The type table itself, which every coercion test indexes THROUGH rather
# than at: with PARAM_TYPES["int"] set to float, `coerce` still runs every
# branch it is tested on and an int-declared column silently accepts 1.5 --
# which for coyote_ms is a duration that is not a whole millisecond.
expect("PARAM_TYPES maps each declarable name to that exact type",
       tuple(PARAM_TYPES[k] for k in ("int", "float", "str", "bool")),
       (int, float, str, bool))
expect_raises("...so an int-declared parameter refuses a fractional value",
              PyoneerConfigError,
              lambda: resolve_params(NEEDS, {"pyoneer_param_ghost": 1.5},
                                     None, "object id=14"),
              "pyoneer_param_ghost", "int", "float")


# ===========================================================================
print("\n8. the actors row comes off DISK, and is the middle rung")
# ===========================================================================
# Section 7 proves the ladder when a row arrives as a dict. This proves where
# the dict comes from -- `data/project/tables/*.json`, the files the editor's
# Database panel writes -- and it is the half that did not exist: ten
# parameters in the shipped registry declare `source="actors"`, and until
# `scripts/loaders/table_file.py` landed every caller passed None, so the
# middle rung was specified, covered by section 7, and never once supplied.
#
# THE FIXTURE IS THIS FILE'S OWN. `data/project/tables/actors.json` is the
# author's content, and a check that pinned its numbers would go red the next
# time they tune the player's speed -- law 4 wearing a different hat.
TABLES_ROOT = tempfile.mkdtemp(prefix="pyoneer_tables_")


def _tables_dir(name: str) -> str:
    """A directory of its own, so one malformed file cannot leak into a peer."""
    directory = os.path.join(TABLES_ROOT, name)
    os.makedirs(directory, exist_ok=True)
    return directory


def _write_table(directory: str, filename: str, payload) -> str:
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload if isinstance(payload, str)
                     else json.dumps(payload, indent=2))
    return directory


GOOD_ACTORS = {
    "table": "actors",
    "title": "Actors",
    "columns": [{"name": "gravity", "type": "float", "default": 9.0},
                {"name": "air_control", "type": "float", "default": 0.25},
                {"name": "display_name", "type": "str"}],
    "rows": {"hero": {"gravity": 2.0, "display_name": "Brent"},
             "boss": {"gravity": 3.0, "air_control": 0.9,
                      "display_name": "Boss"},
             "bare": {"display_name": "Nothing set"}},
}
GOOD = load_tables(_write_table(_tables_dir("good"), "actors.json",
                                GOOD_ACTORS))

# -- the spellings of one identifier, bound so they cannot drift ------------
# `ACTORS` is the table's name inside the file, the stem on disk, and the
# literal a parameter writes as `source=`. One FILE FORMAT string wearing
# three hats (law 8), so renaming any one of them has to go red here.
expect("the table a source='actors' parameter reads IS a declared source",
       ACTORS in PARAM_SOURCES, True)
expect("the editor writes exactly where the engine reads",
       os.path.join(editor_project.PROJECT_DIR, editor_project.TABLES_DIR),
       TABLES_DIR)
expect("...and the files are the whole interface: the reader imports no editor",
       [line.rstrip() for line in
        open(os.path.join(_bootstrap.REPO_ROOT, "scripts", "loaders",
                          "table_file.py"), encoding="utf-8")
        if line.startswith(("import editor", "from editor"))], [])

# -- MISSING IS NOT AN ERROR -----------------------------------------------
# Every line in this block describes a project that never asked for any of
# this, and every one has to behave exactly as it did before the reader
# existed. Getting this half wrong breaks every map that ships today.
_absent = load_tables(os.path.join(TABLES_ROOT, "no_such_directory"))
expect("a project with no tables directory reads as no tables",
       (len(_absent), _absent.names()), (0, []))
expect("...as a real value and not None, so no caller writes that branch",
       isinstance(_absent, ProjectTables), True)
expect("an empty tables directory is the same answer",
       len(load_tables(_tables_dir("empty"))), 0)
expect("a non-json file in the directory is not a table",
       len(load_tables(_write_table(_tables_dir("noise"), "README.txt",
                                    "not a table"))), 0)
expect("an object naming no actor resolves no row, with tables loaded",
       actor_row(GOOD, {"pyoneer_param_gravity": 1.0}, "object id=1"), None)
expect("...and with no tables at all, which is every caller before this",
       actor_row(None, {}, "object id=2"), None)

# The rung is skipped per KEY, not per row: `bare` exists and omits `gravity`,
# so the default answers for it while `hero` supplies one out of the same
# file. Both halves, because a reader that returned an empty row for
# everything would pass the first of these on its own.
expect("a row that omits the column falls to the declared default",
       resolve_params(PARAMS, {}, actor_row(GOOD, {ACTOR: "bare"}, "id=3"),
                      "object id=3")["gravity"], 9.0)
expect("...while a row in the SAME file that carries it supplies it",
       resolve_params(PARAMS, {}, actor_row(GOOD, {ACTOR: "hero"}, "id=4"),
                      "object id=4")["gravity"], 2.0)

# -- UNREADABLE AND CONTRADICTORY ARE ERRORS -------------------------------
# The other side of rule 7's line, and the side that decides whether this is a
# feature or a way to break every existing map. Each raise names the FILE,
# because a project has many and "a table is malformed" is not actionable.
expect_raises("a table file that is not JSON raises, naming the file",
              PyoneerConfigError,
              lambda: load_tables(_write_table(_tables_dir("badjson"),
                                               "actors.json", "{,}")),
              "actors.json", "not valid JSON")
expect_raises("a table file that is a JSON list is refused", PyoneerConfigError,
              lambda: load_tables(_write_table(_tables_dir("list"),
                                               "actors.json", "[]")),
              "actors.json", "JSON object")
expect_raises("a file with no 'table' key is refused", PyoneerConfigError,
              lambda: load_tables(_write_table(_tables_dir("nokey"),
                                               "actors.json", {"rows": {}})),
              "actors.json", "'table' key")
expect_raises("a file whose table name contradicts its own filename",
              PyoneerConfigError,
              lambda: load_tables(_write_table(
                  _tables_dir("mismatch"), "actors.json",
                  {"table": "actor", "rows": {}})),
              "'actor'", "'actors.json'", "same identifier")
expect_raises("'rows' that is not an object keyed by row id",
              PyoneerConfigError,
              lambda: load_tables(_write_table(
                  _tables_dir("rowslist"), "actors.json",
                  {"table": "actors", "rows": []})),
              "actors.json", "'rows'")
expect_raises("a row that is not an object of column -> value",
              PyoneerConfigError,
              lambda: load_tables(_write_table(
                  _tables_dir("rowscalar"), "actors.json",
                  {"table": "actors", "rows": {"hero": 3}})),
              "'hero'", "int")
expect_raises("'columns' that is not a list", PyoneerConfigError,
              lambda: load_tables(_write_table(
                  _tables_dir("colsdict"), "actors.json",
                  {"table": "actors", "columns": {}})),
              "'columns'")
expect_raises("a column with no name", PyoneerConfigError,
              lambda: load_tables(_write_table(
                  _tables_dir("noname"), "actors.json",
                  {"table": "actors", "columns": [{"type": "int"}],
                   "rows": {}})),
              "column 0", "'name'")
# The one refusal that is not tidiness: `resolve_params` matches a row on the
# parameter KEY and never consults the schema, so an off-schema key is a live
# value reaching a behavior out of a file whose own columns deny it exists --
# and the editor's Database panel, which renders columns, would show the
# author nothing at all.
expect_raises("a row key the table declares no column for", PyoneerConfigError,
              lambda: load_tables(_write_table(
                  _tables_dir("stray"), "actors.json",
                  {"table": "actors",
                   "columns": [{"name": "gravity", "type": "float"}],
                   "rows": {"hero": {"gravity": 5.0, "stamina": 7}}})),
              "'hero'", "'stamina'", "no column")
# ...and the half that proves the guard is not simply refusing everything.
expect("a well-formed file with every one of those shapes right loads",
       (GOOD.names(), sorted(GOOD.table(ACTORS).rows),
        GOOD.table(ACTORS).columns),
       ([ACTORS], ["bare", "boss", "hero"],
        ("gravity", "air_control", "display_name")))

# -- pyoneer_actor: what a row reference may say, and what it may not ------
expect("a row id written as a string finds the row",
       actor_row(GOOD, {ACTOR: "boss"}, "id=5")["gravity"], 3.0)
expect("...and one Tiled typed as int addresses the same row through str()",
       row_id(7), "7")
expect("...with surrounding whitespace taken off, because Tiled keeps it",
       row_id("  hero  "), "hero")
expect_raises("a bool row id is refused rather than addressing 'True'",
              PyoneerConfigError, lambda: row_id(True, "object id=6"),
              "pyoneer_actor", "bool", "object id=6")
expect_raises("a float row id is refused rather than addressing '1.0'",
              PyoneerConfigError, lambda: row_id(1.0, "object id=7"),
              "pyoneer_actor", "float")
expect_raises("a present but empty pyoneer_actor is refused",
              PyoneerConfigError, lambda: row_id("   ", "object id=8"),
              "pyoneer_actor", "empty", "object id=8")
expect_raises("a pyoneer_actor naming an absent row raises, NAMING the object",
              PyoneerAssetMissingError,
              lambda: actor_row(GOOD, {ACTOR: "ghost"}, "tmx object id=9"),
              "'ghost'", "tmx object id=9", "hero")
expect_raises("...and one naming a row in a table the project has not got",
              PyoneerAssetMissingError,
              lambda: actor_row(load_tables(_tables_dir("empty")),
                                {ACTOR: "hero"}, "tmx object id=10"),
              "data table", "'actors'", "tmx object id=10")
expect_raises("...and one on a pass handed no tables at all, which names the "
              "WIRING rather than a missing row", PyoneerConfigError,
              lambda: actor_row(None, {ACTOR: "hero"}, "tmx object id=11"),
              "tmx object id=11", "LayerRenderer.tables")

# -- the whole ladder, through a file, in one call -------------------------
# Three DIFFERENT numbers at the three levels, for the reason section 7 gives:
# equal values would let any reading order pass.
_ladder = read_requests({BEHAVIORS: "params", "pyoneer_param_gravity": 1.0},
                        actor_row(GOOD, {ACTOR: "hero"}, "object id=12"),
                        registry=SCRATCH, where="object id=12")
expect("object property beats the row that came off disk",
       _ladder[0].values["gravity"], 1.0)
_row_wins = read_requests({BEHAVIORS: "params"},
                          actor_row(GOOD, {ACTOR: "hero"}, "object id=13"),
                          registry=SCRATCH, where="object id=13")
expect("...the row off disk beats the declared default",
       _row_wins[0].values["gravity"], 2.0)
_default_wins = read_requests({BEHAVIORS: "params"},
                              actor_row(GOOD, {ACTOR: "bare"}, "object id=14"),
                              registry=SCRATCH, where="object id=14")
expect("...and the declared default answers when the row is silent",
       _default_wins[0].values["gravity"], 9.0)
expect("all three asked for the same behavior, so the number is the only "
       "thing that differed",
       {r[0].spec.name for r in (_ladder, _row_wins, _default_wins)},
       {"params"})
expect("...and the value really reaches the constructor, not just the request",
       build(_row_wins)[0].gravity, 2.0)

# `source="object"` IGNORES the row and says so -- proved against a row that
# really came off disk, because the file is the only place an author can
# write `air_control` for an actor, and the warning is the only thing that
# tells them it did nothing.
_off_schema = expect_warns(
    "a per-object parameter refuses a disk row's column, and warns",
    lambda: resolve_params(PARAMS, {},
                           actor_row(GOOD, {ACTOR: "boss"}, "object id=15"),
                           "object id=15"),
    "air_control", "object id=15", "pyoneer_param_air_control")
expect("...and keeps its declared default rather than the row's 0.9",
       _off_schema["air_control"], 0.25)
expect("...while the same row's source='actors' column is still read, so the "
       "refusal is per PARAMETER and not per row",
       _off_schema["gravity"], 3.0)

shutil.rmtree(TABLES_ROOT, ignore_errors=True)


# ===========================================================================
print("\n9. build constructs, stamps, and refuses the wrong thing")
# ===========================================================================
_built = build(read_requests({BEHAVIORS: "params",
                              "pyoneer_param_gravity": 3.5},
                             registry=SCRATCH, where="object id=10"))
expect("one behavior per request", len(_built), 1)
expect("the resolved value reached the constructor", _built[0].gravity, 3.5)
expect("an unmentioned parameter got its default", _built[0].mode, "off")
# Built through the ALIAS, whose class is stamped with the OTHER token. Only
# an instance stamp can answer "params_alias" here; a check that used the
# primary token would pass on the class attribute and could never fail.
expect("register stamped the class with the first token to claim it",
       _Params.spec.name, "params")
_aliased = build([BehaviorRequest(PARAMS_ALIAS, {"gravity": 1.0}, "object id=x")])
expect("the INSTANCE is stamped with the spec it was built from",
       _aliased[0].spec.name, "params_alias")
expect("...and its declared order comes from that spec, not the class's",
       _aliased[0].spec.order, 41)
expect_raises("a factory that builds a non-behavior", PyoneerConfigError,
              lambda: build([BehaviorRequest(BAD_BUILD, {}, "object id=11")]),
              "bad_build", "_NotABehavior")
expect_raises("a declared parameter the constructor will not take", TypeError,
              lambda: build([BehaviorRequest(GHOST_KWARG, {"ghost": 0}, "x")]),
              "ghost")


# ===========================================================================
print("\n10. run order is the DECLARED order, not the attach order")
# ===========================================================================
# The probe is off-diagonal on purpose. `zed` is declared to run FIRST
# (order 10) but is attached SECOND and sorts LAST alphabetically, so a sort
# by attach sequence and a sort by name both produce (alpha, zed) and only a
# sort by declared order produces (zed, alpha).
entity = probe()
LOG.clear()
entity.behaviors.attach(_Alpha())
entity.behaviors.attach(_Zed())
expect("declared order wins over attach order and over name",
       entity.behaviors.names, ("zed", "alpha"))
expect("attach ran once per behavior, as they were attached",
       list(LOG), ["attach:alpha", "attach:zed"])
expect("membership by token", "zed" in entity.behaviors, True)
expect("membership by object", _Alpha() in entity.behaviors, False)
expect("get() finds by token", entity.behaviors.get("alpha").name, "alpha")
expect("get() misses cleanly", entity.behaviors.get("nope"), None)
expect("len counts them", len(entity.behaviors), 2)

expect_raises("a behavior with no spec has no declared order",
              PyoneerConfigError,
              lambda: probe().behaviors.attach(_Unregistered()),
              "no BehaviorSpec", "order")
expect_raises("something that is not a behavior at all", PyoneerConfigError,
              lambda: probe().behaviors.attach(_NotABehavior()),
              "EntityBehavior")
expect_raises("the same behavior twice", PyoneerConfigError,
              lambda: entity.behaviors.attach(_Alpha()),
              "'alpha'", "second")

_conflicted = probe()
_conflicted.behaviors.attach(_Solo())
expect_raises("a declared conflict, detected at attach", PyoneerConfigError,
              lambda: _conflicted.behaviors.attach(_Duo()),
              "'solo'", "'duo'", "conflict")

# The refusal that earns its code: same order, same written attribute.
_clash = probe()
_clash.behaviors.attach(_ClashA())
expect_raises("same order + same write is ambiguous and is refused",
              PyoneerConfigError,
              lambda: _clash.behaviors.attach(_ClashB()),
              "'clash_a'", "'clash_b'", "order=30", "velocity")

# ...and the case that must stay legal, or `order` becomes a serial number.
_disjoint = probe()
_disjoint.behaviors.attach(_DisjointB())
_disjoint.behaviors.attach(_DisjointA())
expect("same order + different writes is legal",
       len(_disjoint.behaviors), 2)
expect("and attach order breaks that tie, since nothing else can",
       _disjoint.behaviors.names, ("disjoint_b", "disjoint_a"))
expect("describe() names order and writes for a trace",
       _disjoint.behaviors.describe(),
       "30 disjoint_b writes=state.facing; 30 disjoint_a writes=velocity")


# ===========================================================================
print("\n11. the drive: three frames, a snapshot, a gate, and no swallowing")
# ===========================================================================
# THREE frames, not one. A single frame cannot tell "ran once per frame" from
# "ran once at attach", and cannot see an interleave at all.
entity = probe()
entity.behaviors.attach(_Alpha())
entity.behaviors.attach(_Zed())
LOG.clear()
for _ in range(3):
    entity.behaviors.update(frame())
expect("every behavior ran on every frame, in declared order",
       list(LOG), ["update:zed", "update:alpha"] * 3)

# The gate. This is the shape of `state.can_move`, which is the only reason
# five of the six demo players are inert.
LOG.clear()
entity.behaviors.get("zed").enabled = False
entity.behaviors.update(frame())
entity.behaviors.update(frame())
expect("a disabled behavior is skipped", list(LOG),
       ["update:alpha", "update:alpha"])
expect("...but is still attached, not detached", len(entity.behaviors), 2)
entity.behaviors.get("zed").enabled = True
LOG.clear()
entity.behaviors.update(frame())
expect("...and re-enabling restores it", list(LOG),
       ["update:zed", "update:alpha"])

# The snapshot. A behavior that leaves mid-frame must not take its sibling's
# turn with it.
entity = probe()
entity.behaviors.attach(_SelfDetach())
entity.behaviors.attach(_Alpha())
LOG.clear()
entity.behaviors.update(frame())
expect("a behavior that detaches itself does not skip its sibling",
       list(LOG),
       ["update:self_detach", "detach:self_detach", "update:alpha"])
LOG.clear()
entity.behaviors.update(frame())
expect("and it is gone on the next frame", list(LOG), ["update:alpha"])
expect("the set shrank", entity.behaviors.names, ("alpha",))

# Failures. Loud, with the path, and without changing the exception's type.
entity = probe()
entity.behaviors.attach(_RaisesPyoneer())
expect_raises("a raising behavior names itself and its entity", PyoneerError,
              lambda: entity.behaviors.update(frame()),
              "fixture explosion", "behavior='raises_pyoneer'",
              "entity='ProbeEntity'")
entity = probe()
entity.behaviors.attach(_RaisesValue())
expect_raises("a non-engine exception propagates with its type intact",
              ValueError, lambda: entity.behaviors.update(frame()),
              "a plain exception")

# A hook that REFUSES must leave nothing behind. Without the rollback in
# `attach`, the entry is already in `_entries` and already sorted when the
# hook runs, so a refused behavior stays in the set and is driven every frame
# by an entity whose composition was rejected -- the failure looks like the
# refusal worked.
entity = probe()
entity.behaviors.attach(_Alpha())
LOG.clear()
expect_raises("a behavior that refuses itself in attach still raises",
              PyoneerConfigError,
              lambda: entity.behaviors.attach(_RaisesOnAttach()),
              "refuses to attach")
expect("...and is NOT left in the set", entity.behaviors.names, ("alpha",))
entity.behaviors.update(frame())
expect("...so it is never driven", list(LOG), ["update:alpha"])
expect("...and the survivors keep their order",
       tuple(b.name for b in entity.behaviors.ordered), ("alpha",))

# detach and detach_all
entity = probe()
entity.behaviors.attach(_Alpha())
entity.behaviors.attach(_Zed())
LOG.clear()
expect("detach by token returns the behavior that left",
       entity.behaviors.detach("zed").name, "zed")
expect("...and called its detach", list(LOG), ["detach:zed"])
expect("detaching something that was never there is not an error",
       entity.behaviors.detach("zed"), None)
LOG.clear()
entity.behaviors.attach(_Zed())
entity.behaviors.detach_all()
expect("detach_all tears down in reverse run order",
       list(LOG), ["attach:zed", "detach:alpha", "detach:zed"])
expect("and the set is empty", len(entity.behaviors), 0)


# ===========================================================================
print("\n12. the real entity: composition moves it, and empty is frame-neutral")
# ===========================================================================
# Driven against a real GameEntity through the real move_direction gate, so
# this is composition doing the engine's own work rather than a mock agreeing
# with itself.
entity = probe()
expect("GameEntity is NOT a GameComponent, and must not become one",
       issubclass(GameEntity, GameComponent), False)
expect("...so it carries no event-bus callbacks dict",
       hasattr(entity, "callbacks"), False)
expect("...and no listener binder", hasattr(entity, "bind_sync_listener"), False)

_start = (entity.transform.position.x, entity.transform.position.y)
for _ in range(3):
    entity.behaviors.update(frame())
expect("an empty behavior set moves nothing at all",
       (entity.transform.position.x, entity.transform.position.y), _start)

entity.behaviors.attach(_Nudge("right"))
for _ in range(3):
    entity.behaviors.update(frame(1.0))
expect("three frames of a movement behavior move three steps",
       entity.transform.position.x, 3.0 * entity.move_speed)
expect("...and nothing moved on the other axis",
       entity.transform.position.y, 0.0)
expect("...and the position object was mutated, never rebound",
       entity.transform.position is entity.transform.position, True)

# missing_requirements REPORTS, and reports the truth about a falsy value.
entity = probe()
entity.behaviors.attach(_Nudge())
expect("a requirement the entity satisfies is not reported",
       entity.behaviors.missing_requirements(), ())
expect("...even though the value at the origin is falsy",
       bool(entity.transform.position), False)
entity.behaviors.attach(build([BehaviorRequest(NEEDS, {"ghost": 1}, "x")])[0])
expect("a requirement the entity lacks is reported once, with its behavior",
       entity.behaviors.missing_requirements(),
       (("needs", "action_manager"),))
expect("but attaching it was still allowed, because input_=None is legal",
       "needs" in entity.behaviors, True)


# ===========================================================================
print("\n13. BEHAVIORS.md is generated from the table the engine binds from")
# ===========================================================================
_empty_doc = describe_all({})
expect_true("an empty registry says so instead of printing a bare heading",
            "registry is empty" in _empty_doc)
expect_true("...and says why that is honest rather than broken",
            "moved no frame" in _empty_doc)

_doc = describe_all(SCRATCH)
expect_true("a populated registry does not claim to be empty",
            "registry is empty" not in _doc)
# Structural, not a name-presence check: `zed` (order 10) must be printed
# BEFORE `alpha` (order 90), which is the opposite of both alphabetical and
# registration order. The summary table and the per-behavior sections are
# sorted by two separate expressions, so both are probed -- checking only the
# first occurrence of a token tests the table and lets the sections drift.
expect_true("the summary table is ordered by declared order, not by name",
            0 < _doc.index("| `zed` |") < _doc.index("| `alpha` |"))
expect_true("the sections are ordered by declared order too",
            0 < _doc.index("### `zed`") < _doc.index("### `alpha`"))
expect_true("...and the sections really do come after the table",
            _doc.index("| `zed` |") < _doc.index("### `zed`"))
expect_true("the derived hooks are printed, all three for a full behavior",
            "- **hooks** `attach`, `update`, `detach`" in _doc)
expect_true("...and exactly one for a behavior that overrides only update",
            "- **hooks** `update`\n" in _doc)
expect_true("a behavior on no event bus says so in words",
            "nothing (not on the event bus)" in _doc)
expect_true("the parameter table carries type, default and source",
            "| `air_control` | float | `0.25` | object | no |" in _doc)
expect_true("a required parameter is marked required",
            "| `ghost` | int | `0` | actors | yes |" in _doc)
expect_true("writes are printed, because that is what makes a clash visible",
            "`transform.position`" in _doc)
expect_true("the delta-unit trap is documented where an AI will read it",
            "milliseconds / 60" in _doc)
expect_true("the held() KeyError trap is documented",
            "unguarded dict index" in _doc)
expect_true("the discarded transform kwarg is documented",
            "discards it" in _doc)
expect_true("the property name is quoted from the constant, not retyped",
            "pyoneer_behaviors" in _doc and "pyoneer_param_" in _doc)
expect_true("the fence is restated where a behavior author will read it",
            "never import" in _doc)
expect_true("adding one is a numbered procedure, not prose",
            "## Adding a behavior" in _doc)

_flagged = dict(SCRATCH)
_flagged["later"] = BehaviorSpec("later", "Not wired yet.", _Alpha, order=99,
                                 status="authoring-only")
expect_true("an authoring-only behavior says so in the same place as its name",
            "**Status: authoring-only.**" in describe_all(_flagged))


# ===========================================================================
print("\n14. summary")
# ===========================================================================
print(f"\nassertions             : {len(asserted)}")
print(f"registry at HEAD       : {len(BEHAVIOR_REGISTRY)} behavior(s)")
print(f"fixture registry       : {len(SCRATCH)} behavior(s)")
print(f"package files scanned  : {len(SOURCES)}")
# A label used twice would silently hide one of the two in the failure list.
_dupes = sorted({label for label in asserted if asserted.count(label) > 1})
if _dupes:
    print(f"  FAIL duplicate assertion labels: {_dupes}")
    failures.extend(_dupes)

if failures:
    print(f"\nFAILED ({len(failures)}):")
    for item in failures:
        print(f"  - {item}")
    raise SystemExit(1)
print("\nALL BEHAVIOR CHECKS PASS")
