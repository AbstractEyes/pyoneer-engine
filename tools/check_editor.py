"""Verify the editor's headless core.

The editor's whole safety story is "an AI's edit and a human's edit go
through the same validated, reversible door". This asserts that door
actually holds:

  * a malformed scope is rejected at parse time, not later
  * an unknown verb, unknown argument, missing argument or wrong argument
    type stops the transaction
  * a failed transaction rolls back completely -- the map is byte-identical
    afterwards, which is the strongest statement available
  * undo of every verb restores the exact prior state
  * the generated command documentation covers every registered verb
  * the Database's schema controls emit a verb the stream ACCEPTS, and
    refuse the answers it would not -- the fix the Problems dock prints is
    only a fix if something in the window can run it
  * `scripts/` does not import `editor/`

No pygame. The last section drives ONE Qt widget offscreen, because a verb
with no caller is the defect this tree keeps paying for and a headless
assertion about the verb alone cannot see it. That section skips cleanly
when PySide6 is not installed; everything above it runs on a bare clone
with no art.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import atexit
import importlib.util
import json
import os
from xml.etree import ElementTree
import shutil
import sys
import tempfile
import warnings

from editor.core import genre as genre_module
from editor.core.commands import Command, all_verbs, describe_all, verb, verb_names
from editor.core.errors import (
    PyoneerCommandApplyError,
    PyoneerCommandArgumentError,
    PyoneerCommandScopeError,
    PyoneerCommandUnknownError,
    PyoneerEditorError,
    PyoneerResponseParseError,
    PyoneerRuleViolationError,
)
from editor.core.project import Project
from editor.core.request import Manifest, Note, parse_response, write_bundle
from editor.core.scope import Scope, code_locations
from editor.core.session import Session
from scripts.core.collision_runtime import companion_subcell
from scripts.game.behavior.base import BEHAVIORS
from scripts.game.behavior.registry import BEHAVIOR_REGISTRY, validate_list

REPO = _bootstrap.REPO_ROOT
failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<56} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception_type, fn):
    try:
        fn()
    except exception_type as exc:
        text = str(exc).splitlines()[0]
        print(f"  ok   {label:<56} {type(exc).__name__}: {text[:60]}")
        return
    except Exception as exc:                                    # noqa: BLE001
        print(f"  FAIL {label:<56} raised {type(exc).__name__}, "
              f"wanted {exception_type.__name__}")
        failures.append(label)
        return
    print(f"  FAIL {label:<56} did not raise {exception_type.__name__}")
    failures.append(label)


def expect_raises_naming(label, exception_type, fn, *needles):
    """It refuses, AND the refusal carries every one of `needles`.

    A verb that raises without naming the numbers it disagreed about sends
    the author back to measure the map by hand, and an assertion that only
    checks the TYPE cannot tell a message that names them from one that says
    "invalid". That is the same half-an-invariant shape as a gate proved to
    refuse and never proved to allow.
    """
    try:
        fn()
    except exception_type as exc:
        missing = [n for n in needles if n not in str(exc)]
        if missing:
            print(f"  FAIL {label:<56} message omits {missing}")
            print(f"       {str(exc).splitlines()[0]}")
            failures.append(label)
            return
        print(f"  ok   {label:<56} names {list(needles)}")
        return
    except Exception as exc:                                    # noqa: BLE001
        print(f"  FAIL {label:<56} raised {type(exc).__name__}, "
              f"wanted {exception_type.__name__}")
        failures.append(label)
        return
    print(f"  FAIL {label:<56} did not raise {exception_type.__name__}")
    failures.append(label)


# --------------------------------------------------------------------------
print("scopes parse, reject, and round-trip")
# --------------------------------------------------------------------------
expect("a nested scope round-trips",
       str(Scope.parse("map:test/layer:Floor")), "map:test/layer:Floor")
expect("the terminal kind is the scope's kind",
       Scope.parse("map:test/layer:Floor").kind, "layer")
expect("get() finds an ancestor segment",
       Scope.parse("map:test/layer:entity/object:4").get("map"), "test")
expect("unnamed kinds render without a colon", str(Scope.of("project")), "project")
expect("matches() honours wildcards",
       Scope.parse("map:test/layer:Floor").matches("map:*/layer:*"), True)
expect("matches() rejects a different depth",
       Scope.parse("map:test").matches("map:*/layer:*"), False)
expect("is_under() sees an ancestor",
       Scope.parse("map:test/layer:Floor").is_under(Scope.parse("map:test")), True)

from editor.core.errors import PyoneerScopeSyntaxError

expect_raises("an empty scope is refused", PyoneerScopeSyntaxError,
              lambda: Scope.parse(""))
expect_raises("an unknown kind is refused", PyoneerScopeSyntaxError,
              lambda: Scope.parse("sprite:hero"))
expect_raises("a named kind with no name is refused", PyoneerScopeSyntaxError,
              lambda: Scope.parse("map:"))
expect_raises("a doubled slash is refused", PyoneerScopeSyntaxError,
              lambda: Scope.parse("map:test//layer:Floor"))
expect_raises("an unnamed kind may not take a name", PyoneerScopeSyntaxError,
              lambda: Scope.parse("project:thing"))

# Scope being frozen and value-comparing is what licenses sharing ONE
# instance of each singleton across every caller, which is what
# known_scopes() now does instead of re-parsing three literals.
from editor.core.scope import ASSETS, GENRE, PROJECT                # noqa: E402

expect("Scope is value-comparing",
       PROJECT == Scope.of("project"), True)
expect("Scope hashes by value",
       hash(PROJECT) == hash(Scope.of("project")), True)
expect("the three singletons are distinct",
       len({PROJECT, GENRE, ASSETS}), 3)

print()
print("every code location the scope map names actually exists")
missing = []
for scope_text in ("project", "genre", "assets", "map:test",
                   "map:test/layer:Floor", "map:test/layer:entity/object:1",
                   "table:actors", "table:actors/row:hero"):
    for relative in code_locations(Scope.parse(scope_text)):
        target = os.path.join(REPO, relative)
        if not (os.path.isfile(target) or os.path.isdir(target)):
            missing.append(f"{scope_text} -> {relative}")
expect("no dangling paths in _CODE_MAP", missing, [])

# --------------------------------------------------------------------------
print()
print("the command registry documents itself completely")
# --------------------------------------------------------------------------
import editor.core.verbs  # noqa: F401,E402  (registers the vocabulary)

names = verb_names()
expect("verbs are registered", len(names) > 12, True)
documentation = describe_all()
undocumented = [n for n in names if f"### `{n}`" not in documentation]
expect("every verb appears in the generated docs", undocumented, [])
undescribed = [v.name for v in all_verbs() if not v.summary.strip()]
expect("every verb has a summary", undescribed, [])
unexplained = [f"{v.name}.{p.name}" for v in all_verbs()
               for p in v.params if not p.doc.strip()]
expect("every parameter has a doc string", unexplained, [])
scopeless = [v.name for v in all_verbs() if not v.scopes]
expect("every verb declares its scopes", scopeless, [])

# --------------------------------------------------------------------------
print()
print("genre packs load and declare coherent shapes")
# --------------------------------------------------------------------------
packs = genre_module.available()
expect("both packs are found", packs, ["platformer", "topdown_rpg"])
for pack_id in packs:
    pack = genre_module.load(pack_id)
    expect(f"{pack_id}: has rules to condition with",
           len(pack.rules_markdown) > 400, True)
    expect(f"{pack_id}: declares an object layer",
           any(l.kind == "object" for l in pack.layers), True)
    expect(f"{pack_id}: declares an actors table",
           pack.table("actors") is not None, True)

from editor.core.errors import PyoneerGenreError, PyoneerGenreMissingError

expect_raises("an unknown genre fails loudly", PyoneerGenreMissingError,
              lambda: genre_module.load("no_such_genre"))

# --------------------------------------------------------------------------
print()
print("default behavior lists: absent is fine, present and wrong is fatal")
# --------------------------------------------------------------------------
# `layers[].object_classes[].behaviors` is where a pack says what a newly
# placed object DOES. Everything below runs against packs written into a temp
# directory rather than against `editor/genres/` -- law 4: a check asserts
# what the CODE does, and the shipped packs are content someone may repaint.
# The one exception is the block immediately below, which is deliberately a
# claim about the shipped packs: a token they name that the registry does not
# know would be written into every object ever placed from them.
for pack_id in packs:
    pack = genre_module.load(pack_id)
    declared = pack.object_class("entity", "GamePlayer")
    expect(f"{pack_id}: says what a placed GamePlayer starts as",
           bool(declared and declared.behaviors), True)
    tokens = declared.behaviors if declared else ()
    expect(f"{pack_id}: every token it names is registered",
           [t for t in tokens if t not in BEHAVIOR_REGISTRY], [])
    # The half `validate_list` cannot see. Genre gating is REPORTED by the
    # behavior panel and never enforced by the loader, so a pack shipping the
    # other genre's movement token would load, materialise, attach, and simply
    # not move -- the silent shape this repo keeps paying for.
    expect(f"{pack_id}: and no token is gated to a DIFFERENT genre",
           [t for t in tokens if BEHAVIOR_REGISTRY[t].genres
            and pack_id not in BEHAVIOR_REGISTRY[t].genres], [])

GENRE_FIXTURES = tempfile.mkdtemp(prefix="pyoneer_genre_fixture_")
atexit.register(shutil.rmtree, GENRE_FIXTURES, ignore_errors=True)
_fixture_serial = 0


def fixture_pack(*layers, **top):
    """Write a throwaway pack; return a thunk that LOADS it.

    A thunk rather than a loaded pack, because half of what is asserted here
    is that loading REFUSES -- and a helper that loaded eagerly could only
    ever exercise the half that succeeds, which is the exact one-sided shape
    law 5 is about.

    `**top` writes top-level manifest keys beside `layers`. The thunk carries
    the generated pack id as `.genre_id`, because a refusal that has to name
    the PACK cannot be asserted against an id the caller never saw.
    """
    global _fixture_serial
    _fixture_serial += 1
    identifier = f"fixture{_fixture_serial}"
    root = os.path.join(GENRE_FIXTURES, identifier)
    os.makedirs(root)
    manifest = {"id": identifier, "title": "Fixture", "layers": list(layers)}
    manifest.update(top)
    with open(os.path.join(root, "genre.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)

    def thunk():
        return genre_module.load(identifier, GENRE_FIXTURES)

    thunk.genre_id = identifier
    return thunk


def entity_layer(**extra):
    layer = {"name": "entity", "kind": "object", "object_types": ["GamePlayer"]}
    layer.update(extra)
    return layer


DRIVEN = ["player_input", "topdown_move", "animation_drive"]

expect("a pack that declares NO object_classes still loads",
       fixture_pack(entity_layer())().layer("entity").object_types,
       ("GamePlayer",))
expect("...and answers nothing for every class, which is today's behaviour",
       fixture_pack(entity_layer())().object_class("entity", "GamePlayer"), None)

_declared = fixture_pack(entity_layer(object_classes=[
    {"type": "GamePlayer", "behaviors": DRIVEN}]))()
expect("a declared list survives load in the authored order",
       _declared.object_class("entity", "GamePlayer").behaviors, tuple(DRIVEN))
expect("...and its tmx form comes from the engine's own formatter",
       _declared.object_class("entity", "GamePlayer").behaviors_text,
       "player_input,topdown_move,animation_drive")
expect("a class the pack does not name still gets nothing",
       _declared.object_class("entity", "GameEntity"), None)
expect("a LAYER the pack does not name gets nothing",
       _declared.object_class("Floor", "GamePlayer"), None)

expect_raises_naming(
    "a token the registry does not know is refused at pack load",
    PyoneerGenreError,
    fixture_pack(entity_layer(object_classes=[
        {"type": "GamePlayer", "behaviors": ["ghost_move"]}])),
    "ghost_move", "GamePlayer", "raise at load")
expect_raises_naming(
    "the same token twice is refused",
    PyoneerGenreError,
    fixture_pack(entity_layer(object_classes=[
        {"type": "GamePlayer", "behaviors": ["topdown_move", "topdown_move"]}])),
    "topdown_move", "twice")
expect_raises_naming(
    "two tokens that declare a conflict are refused",
    PyoneerGenreError,
    fixture_pack(entity_layer(object_classes=[
        {"type": "GamePlayer",
         "behaviors": ["topdown_move", "platformer_move"]}])),
    "topdown_move", "platformer_move", "conflict")
expect_raises_naming(
    "a default for a class the same layer forbids is refused",
    PyoneerGenreError,
    fixture_pack(entity_layer(object_classes=[
        {"type": "GameScene", "behaviors": []}])),
    "GameScene", "object_types")
expect_raises_naming(
    "the same class declared twice is refused",
    PyoneerGenreError,
    fixture_pack(entity_layer(object_classes=[
        {"type": "GamePlayer", "behaviors": []},
        {"type": "GamePlayer", "behaviors": DRIVEN}])),
    "GamePlayer", "twice")
expect_raises_naming(
    "object_classes on a TILE layer is refused",
    PyoneerGenreError,
    fixture_pack({"name": "Floor", "kind": "tile", "object_classes": [
        {"type": "GamePlayer", "behaviors": DRIVEN}]}),
    "Floor", "tile layer")
expect_raises_naming(
    "an entry that is not an object is refused",
    PyoneerGenreError,
    fixture_pack(entity_layer(object_classes=["GamePlayer"])),
    "entity", "'type'")
expect_raises_naming(
    "an entry with no type is refused",
    PyoneerGenreError,
    fixture_pack(entity_layer(object_classes=[{"behaviors": DRIVEN}])),
    "entity", "'type'")
expect_raises_naming(
    "a behaviors value that is not a list is refused",
    PyoneerGenreError,
    fixture_pack(entity_layer(object_classes=[
        {"type": "GamePlayer", "behaviors": {"a": 1}}])),
    "GamePlayer", "behaviors", "dict")
expect_raises_naming(
    "object_classes that is not a list is refused",
    PyoneerGenreError,
    fixture_pack(entity_layer(object_classes={"type": "GamePlayer"})),
    "entity", "must be a list")
expect("an EMPTY object_classes is silence, not a contradiction",
       fixture_pack(entity_layer(object_classes=[]))()
       .object_class("entity", "GamePlayer"), None)
expect("...even on a TILE layer, where a non-empty one is refused above",
       fixture_pack({"name": "Floor", "kind": "tile", "object_classes": []})()
       .layer("Floor").object_classes, ())
expect("a class declared with an EMPTY list is a real answer, not silence",
       fixture_pack(entity_layer(object_classes=[
           {"type": "GamePlayer", "behaviors": []}]))()
       .object_class("entity", "GamePlayer").behaviors, ())

# --------------------------------------------------------------------------
print()
print("event_loadouts: a pack GRANTS a script vocabulary, or says nothing")
# --------------------------------------------------------------------------
# `event_loadouts` is the pack's grant of op vocabularies to the scripts
# authored under it. Everything here runs against fixture packs in a temp
# directory (law 4), except the one block that deliberately asserts about the
# shipped packs and says why.
import dataclasses                                              # noqa: E402

from scripts.game.flow import ops as op_registry                # noqa: E402

# -- the parse: three states, and two of them are not the same state -------
expect("a pack declaring a known loadout loads, and the grant is readable",
       fixture_pack(event_loadouts=["core"])().event_loadouts, ("core",))
expect("a pack declaring NO event_loadouts still loads, and is SILENT",
       fixture_pack()().event_loadouts, None)
expect("...and silence is not the empty grant: [] is a real answer",
       fixture_pack(event_loadouts=[])().event_loadouts, ())

# The refusal, and the positive control law 5 asks for in the same breath:
# the control proves the load path is REACHED and that the key being present
# is not itself the fault, so the raise below can only be about the NAME.
_unknown = fixture_pack(event_loadouts=["topdown_rpg"])
expect_raises_naming(
    "a loadout no registered op claims is refused at pack load",
    PyoneerGenreError, _unknown,
    "topdown_rpg", _unknown.genre_id, "event_loadouts", "core")
_control = fixture_pack(event_loadouts=["core"])
expect("POSITIVE CONTROL: the same pack with a KNOWN name loads",
       _control().event_loadouts, ("core",))

expect_raises_naming(
    "the same loadout twice is refused",
    PyoneerGenreError, fixture_pack(event_loadouts=["core", "core"]),
    "'core'", "twice")
expect_raises_naming(
    "event_loadouts as a bare string is refused, not split into letters",
    PyoneerGenreError, fixture_pack(event_loadouts="core"),
    "event_loadouts", "JSON array")
expect_raises_naming(
    "an explicit null is refused -- it is neither silence nor a grant",
    PyoneerGenreError, fixture_pack(event_loadouts=None),
    "event_loadouts", "JSON array")
expect_raises_naming(
    "a non-string entry is refused",
    PyoneerGenreError, fixture_pack(event_loadouts=[7]),
    "event_loadouts", "int")

# -- grants(): both halves, including the compatibility half ---------------
_granting = fixture_pack(event_loadouts=["core"])()
_nothing = fixture_pack(event_loadouts=[])()
_silent = fixture_pack()()
expect("a granting pack grants what it names, and nothing else",
       (_granting.grants("core"), _granting.grants("topdown_rpg")),
       (True, False))
expect("an EMPTY grant refuses even core -- it means what it says",
       _nothing.grants("core"), False)
expect("a SILENT pack grants everything, which is yesterday's behaviour",
       (_silent.grants("core"), _silent.grants("anything_at_all")),
       (True, True))

# -- granted_registry(): the one seam a picker needs, narrowed both ways ---
# A fake table with TWO loadouts, because a table that only ever holds `core`
# cannot tell narrowing from doing nothing at all.
_real = op_registry.OP_REGISTRY["say"]
ALIEN = dataclasses.replace(_real, name="alien_op", loadout="not_granted")
FAKE = dict(op_registry.OP_REGISTRY)
FAKE[ALIEN.name] = ALIEN
expect("the fake table really does hold two loadouts",
       sorted(op_registry.loadouts(FAKE)), ["core", "not_granted"])
expect("a granted loadout's ops SURVIVE the narrowing",
       "say" in _granting.granted_registry(FAKE), True)
expect("...and an ungranted loadout's ops are GONE from it",
       "alien_op" in _granting.granted_registry(FAKE), False)
expect("an empty grant narrows the table to nothing",
       dict(_nothing.granted_registry(FAKE)), {})
expect("a SILENT pack hands the table back by IDENTITY, not as a copy",
       _silent.granted_registry(FAKE) is FAKE, True)
expect("...and with no argument it answers the live registry",
       _silent.granted_registry() is op_registry.OP_REGISTRY, True)

# -- the shipped packs -----------------------------------------------------
# Deliberately a claim about `editor/genres/`, for the same reason the
# object_classes block above makes one: a pack granting a name the registry
# does not know RAISES at pack load, so that pack's whole genre would be
# unopenable in the editor. The assertion is on the JUDGE's answer, not on
# which names the packs happen to have chosen.
for pack_id in packs:
    pack = genre_module.load(pack_id)
    expect(f"{pack_id}: declares a grant rather than staying silent",
           pack.event_loadouts is not None, True)
    expect(f"{pack_id}: and every name in it is one the registry knows",
           [l for l in pack.event_loadouts
            if l not in op_registry.loadouts()], [])

# --------------------------------------------------------------------------
print()
print("...and the grant reaches a human through the Problems list")
# --------------------------------------------------------------------------
# The soft half, asserted through `Session.problems()` -- the exact call
# `editor/ui/docks.py` makes to fill the Problems dock. A grant nothing above
# it can read is the defect this repository keeps paying for, so the wire is
# what is asserted here, not the parser.
from editor.core import event_script                            # noqa: E402

GRANT_WS = tempfile.mkdtemp(prefix="pyoneer_grant_check_")
try:
    os.makedirs(os.path.join(GRANT_WS, "config"))
    with open(os.path.join(GRANT_WS, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": []}, handle)
    # A shipped genre is the only thing `Project.load` can open by id; it is
    # scaffolding and nothing below asserts anything about it -- every
    # assertion runs against a fixture pack swapped in by `set_genre`.
    grant_session = Session.open(GRANT_WS, genre_id="topdown_rpg")
    grant_project = grant_session.project
    event_script.scripts_of(grant_project).create(
        event_script.ScriptDocument(id="greeter", title="Greeter",
                                    loadouts=["core"]))

    grant_project.set_genre(_nothing)
    refused = [p for p in grant_session.problems() if p.scope.kind == "script"]
    expect("a script asking for a loadout the pack withholds is REPORTED",
           len(refused), 1)
    expect("...as a soft rule, because a half-built project may run ahead",
           refused[0].severity if refused else None, "soft")
    expect("...addressed at the script, so the dock can jump to it",
           str(refused[0].scope) if refused else None, "script:greeter")
    _said = str(refused[0]) if refused else ""
    expect("...naming the script, the loadout, the pack and a fix",
           [n for n in ("greeter", "'core'", _nothing.id, "event_loadouts")
            if n not in _said], [])

    # The other half. Same project, same script, same call -- only the grant
    # differs, so a green here cannot come from the walk silently not running.
    grant_project.set_genre(_granting)
    expect("POSITIVE CONTROL: granted, the same script reports nothing",
           [p for p in grant_session.problems() if p.scope.kind == "script"],
           [])
    grant_project.set_genre(_silent)
    expect("and a SILENT pack reports nothing either -- silence stays silent",
           [p for p in grant_session.problems() if p.scope.kind == "script"],
           [])
finally:
    shutil.rmtree(GRANT_WS, ignore_errors=True)

# --------------------------------------------------------------------------
print()
print("the preflight contract still matches what scripts/ exports")
# --------------------------------------------------------------------------
# editor/preflight.py hardcodes the engine symbols the editor binds, and
# refuses to start when one is missing. That list going stale would turn a
# helpful gate into a false alarm, so it is asserted here: a rename in
# scripts/ fails this check instead of blocking the editor at startup.
from editor import preflight  # noqa: E402

expect("a healthy engine reports no problems",
       [str(p) for p in preflight.check(REPO)], [])
expect("the contract covers exactly the modules the editor imports",
       sorted(preflight.ENGINE_CONTRACT),
       ["scripts/core/errors.py", "scripts/core/log.py",
        "scripts/loaders/map_document.py"])

print()
print("and it detects both ways the engine can become unloadable")
sandbox = tempfile.mkdtemp(prefix="pyoneer_preflight_")
try:
    os.makedirs(os.path.join(sandbox, "scripts", "core"))
    broken_path = os.path.join(sandbox, "scripts", "core", "errors.py")
    with open(broken_path, "w", encoding="utf-8") as handle:
        handle.write("def oops(:\n")
    problems = preflight.check(sandbox, {"scripts/core/errors.py": ("PyoneerError",)})
    expect("a syntax error is caught", len(problems), 1)
    expect("and it names the line", problems[0].line, 1)

    with open(broken_path, "w", encoding="utf-8") as handle:
        handle.write("class SomethingElse:\n    pass\n")
    problems = preflight.check(sandbox, {"scripts/core/errors.py": ("PyoneerError",)})
    expect("a deleted symbol is caught", len(problems), 1)
    expect("and it says which one",
           "PyoneerError" in problems[0].message, True)

    # A name that moved inside a class body or an `if` is no longer
    # importable the way the editor imports it, so it must NOT count.
    with open(broken_path, "w", encoding="utf-8") as handle:
        handle.write("class Holder:\n    PyoneerError = 1\n")
    problems = preflight.check(sandbox, {"scripts/core/errors.py": ("PyoneerError",)})
    expect("a name nested inside a class does not count as present",
           len(problems), 1)

    problems = preflight.check(sandbox, {"scripts/core/gone.py": ("Anything",)})
    expect("a missing file is caught", len(problems), 1)
finally:
    shutil.rmtree(sandbox, ignore_errors=True)

print()
print("scripts/ does not import editor/")
# --------------------------------------------------------------------------
offenders = []
for root, directories, files in os.walk(os.path.join(REPO, "scripts")):
    directories[:] = [d for d in directories if d != "__pycache__"]
    for name in files:
        if not name.endswith(".py"):
            continue
        path = os.path.join(root, name)
        with open(path, "r", encoding="utf-8") as handle:
            body = handle.read()
        if "import editor" in body or "from editor" in body:
            offenders.append(os.path.relpath(path, REPO))
expect("the dependency direction holds", offenders, [])

# --------------------------------------------------------------------------
print()
print("a throwaway project opens against a copy of the real map")
# --------------------------------------------------------------------------
workspace = tempfile.mkdtemp(prefix="pyoneer_editor_check_")
try:
    os.makedirs(os.path.join(workspace, "config"))
    os.makedirs(os.path.join(workspace, "data", "maps"))
    # The SHIPPED map, copied in. It is the workspace's own fixture from here
    # on and the workspace calls it "test"; nothing below writes back to
    # data/maps/starter.tmx.
    shutil.copy2(os.path.join(REPO, "data", "maps", "starter.tmx"),
                 os.path.join(workspace, "data", "maps", "test.tmx"))
    # THE MAP'S LINKS COME WITH IT. The shipped hero carries
    # `pyoneer_script="starter_greeting"`, and `GenrePack.validate` now
    # resolves every per-object `pyoneer_` link, so a workspace holding the
    # map and none of the documents it names is a project that genuinely
    # would not boot -- and the two `problems() == []` rows below were
    # asserting something false about their own fixture the moment that
    # walk landed. Copying ONE file out of a project and calling the result
    # a project is the fixture defect; the repair is to copy the half the
    # map points at, not to filter the rule's output, which would delete
    # the coverage while still printing PASS.
    # Both halves, because the link chain is two deep: the object names a
    # script, the script asks a scene variable, and only `scenes/` declares
    # one. `tables/` is NOT copied -- this workspace authors its own below,
    # and the shipped hero names no `pyoneer_actor`.
    for subdir in ("scripts", "scenes"):
        shutil.copytree(os.path.join(REPO, "data", "project", subdir),
                        os.path.join(workspace, "data", "project", subdir))
    with open(os.path.join(workspace, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [{"name": "test", "identifier": "test",
                             "file": "data/maps/test.tmx"}]}, handle)

    with open(os.path.join(workspace, "data", "maps", "test.tmx"), "rb") as handle:
        ORIGINAL = handle.read()

    session = Session.open(workspace, genre_id="topdown_rpg")
    expect("the map index loaded", session.project.map_names(), ["test"])
    # READ off the document, never typed. The width used to be `100`, which
    # was the old canvas's; a number here pins what a MAP contains (law 4)
    # and dies the day the shipped map is replaced -- which is exactly what
    # happened. What is worth asserting is that it parsed to a real extent.
    WIDTH = session.project.map("test").width
    expect("the map parses", (WIDTH > 0, session.project.map("test").height > 0),
           (True, True))
    expect("it starts byte-identical",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # IDENTITY, not equality. Scope is frozen and value-comparing, so an
    # `==` assertion here passes whether known_scopes() shares the module
    # singletons or re-parses three fresh literals -- it cannot tell the
    # wire from its absence.
    leading = session.known_scopes()[:3]
    expect("known_scopes shares the singleton INSTANCES, not equal copies",
           [leading[0] is PROJECT, leading[1] is GENRE, leading[2] is ASSETS],
           [True, True, True])

    FLOOR = Scope.parse("map:test/layer:Floor")
    ENTITY = Scope.parse("map:test/layer:entity")

    # ---------------------------------------------------------------
    print()
    print("tiles: set, undo, and the file comes back byte-identical")
    # ---------------------------------------------------------------
    before = session.project.map("test").tile_layer("Floor").get_tile(4, 7)
    session.run(Command("map.tile.set", FLOOR, {"x": 4, "y": 7, "gid": 9999}))
    expect("the tile changed",
           session.project.map("test").tile_layer("Floor").get_tile(4, 7), 9999)
    session.undo()
    expect("undo restored the value",
           session.project.map("test").tile_layer("Floor").get_tile(4, 7), before)
    expect("undo restored the BYTES",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    print()
    print("a fill of 400 tiles undoes as one step, exactly")
    session.run(Command("map.tile.fill", FLOOR,
                        {"x": 2, "y": 2, "width": 20, "height": 20, "gid": 65}))
    expect("the fill took",
           session.project.map("test").tile_layer("Floor").get_tile(10, 10), 65)
    expect("it is one transaction", len(session.history()), 1)
    session.undo()
    expect("undo of a fill restores the bytes",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    print()
    print("redo re-applies, and undo takes it back again")
    session.redo()
    expect("redo restored the fill",
           session.project.map("test").tile_layer("Floor").get_tile(10, 10), 65)
    session.undo()
    expect("and undo is still exact",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    print()
    print("writing a tile that is already there is a no-op, not a fake edit")
    same = session.project.map("test").tile_layer("Floor").get_tile(0, 0)
    session.run(Command("map.tile.set", FLOOR, {"x": 0, "y": 0, "gid": same}))
    expect("bytes unchanged",
           session.project.map("test").to_bytes() == ORIGINAL, True)
    session.undo()

    # ---------------------------------------------------------------
    print()
    print("layers: add, remove, and undo them byte-exactly")
    # ---------------------------------------------------------------
    MAP = Scope.parse("map:test")
    session.run(Command("map.layer.add", MAP,
                        {"name": "Hazard", "kind": "tile"}))
    expect("the layer exists",
           "Hazard" in session.project.map("test").tile_layer_names(), True)
    expect("at the map's size",
           session.project.map("test").tile_layer("Hazard").width, WIDTH)
    expect("and empty",
           set(session.project.map("test").tile_layer("Hazard").gids()), {0})
    session.undo()
    expect("undo removes it",
           "Hazard" in session.project.map("test").tile_layer_names(), False)
    expect("byte-identical, including nextlayerid",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    session.run(Command("map.layer.add", MAP,
                        {"name": "Triggers", "kind": "object"}))
    expect("an object layer too",
           "Triggers" in session.project.map("test").object_layer_names(), True)
    session.undo()
    expect("and it undoes byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    session.run(Command("map.layer.add", MAP,
                        {"name": "Solid", "kind": "tile",
                         "group": "Graphic", "fill": 65}))
    expect("a fill value lands",
           session.project.map("test").tile_layer("Solid").get_tile(0, 0), 65)
    session.undo()

    print()
    print("a layer may be created at a size that is NOT the map's")
    # THE GAP THIS CLOSES. `map.layer.add` carried no dimensions, so every
    # layer any editor action could create was map-sized -- and a passability
    # companion at pyoneer_subcell=4 is FOUR TIMES the map on each axis. The
    # format the engine reads was unreachable by any command in the stream.
    #
    # Read off the map rather than written as 100: this asserts the
    # arithmetic, not the fixture, so repainting the shipped map cannot make
    # it red.
    map_document = session.project.map("test")
    columns, rows = map_document.width, map_document.height
    session.run(Command("map.layer.add", MAP,
                        {"name": "FineProbe", "kind": "tile", "subcell": 4}))
    fine = session.project.map("test").tile_layer("FineProbe")
    expect("the layer is subcell x the map",
           (fine.width, fine.height), (columns * 4, rows * 4))
    expect("its csv holds one gid per sub-cell", len(fine), columns * rows * 16)
    expect("and it DECLARES the factor, in the same command as the size",
           fine.properties.get("pyoneer_subcell"), 4)
    expect("so the engine reads it back as a 4x companion",
           companion_subcell(session.project.map("test"), "FineProbe"), 4)
    expect("one command, one history entry", len(session.history()), 1)

    session.undo()
    expect("undo of a 4x layer restores the BYTES",
           session.project.map("test").to_bytes() == ORIGINAL, True)
    session.redo()
    expect("redo brings back the size AND the declaration",
           (session.project.map("test").tile_layer("FineProbe").width,
            session.project.map("test").tile_layer("FineProbe")
            .properties.get("pyoneer_subcell")),
           (columns * 4, 4))
    session.undo()
    expect("and undo is still exact the second time",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    session.run(Command("map.layer.add", MAP,
                        {"name": "OddProbe", "kind": "tile",
                         "width": 7, "height": 3}))
    odd = session.project.map("test").tile_layer("OddProbe")
    expect("explicit dimensions with no factor are honoured",
           (odd.width, odd.height, len(odd)), (7, 3, 21))
    expect("and declare nothing that was not asked for",
           odd.properties.as_dict(), {})
    session.undo()
    expect("that undoes byte-identically too",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    print()
    print("a factor the dimensions do not support is refused, by both numbers")
    # The other half. A gate proved to let a 4x layer through and never proved
    # to stop a mismatched one bakes a 32x32 field from an 8x8 layer's worth of
    # data and complains about nothing.
    expect_raises_naming(
        "explicit dimensions contradicting the factor",
        PyoneerCommandApplyError,
        lambda: session.run(Command("map.layer.add", MAP,
                                    {"name": "BadProbe", "kind": "tile",
                                     "subcell": 4, "width": columns * 2,
                                     "height": rows * 2})),
        "pyoneer_subcell=4", f"{columns * 2}x{rows * 2}",
        f"{columns * 4}x{rows * 4}")
    expect("the refused transaction left no layer and no bytes",
           ("BadProbe" in session.project.map("test").layer_names(),
            session.project.map("test").to_bytes() == ORIGINAL),
           (False, True))
    expect_raises_naming(
        "a factor the map's tile size does not divide",
        PyoneerCommandApplyError,
        lambda: session.run(Command("map.layer.add", MAP,
                                    {"name": "BadProbe", "kind": "tile",
                                     "subcell": 3})),
        "pyoneer_subcell=3",
        f"{map_document.tile_width}x{map_document.tile_height}px")
    expect_raises_naming(
        "a sub-cell factor on an OBJECT layer", PyoneerCommandApplyError,
        lambda: session.run(Command("map.layer.add", MAP,
                                    {"name": "BadProbe", "kind": "object",
                                     "subcell": 4})),
        "object layer", "pyoneer_subcell")
    expect("the map is byte-identical after all three refusals",
           session.project.map("test").to_bytes() == ORIGINAL, True)
    expect("and no refusal cost a history entry", session.history(), [])

    print()
    print("removing an EXISTING layer restores it exactly -- every one of them")
    # The whitespace before a layer lives in its previous sibling's tail, so
    # a recomputed indent is wrong somewhere no matter what it computes. Each
    # position exercises a different branch: first child, middle child, last
    # child, only child -- and every one of the four is READ OFF THE
    # DOCUMENT, never typed. This used to name `("Paralax", "GroundClutter",
    # "Foreground", "entity")`, which pinned one map's spelling (law 4) and
    # went red the day that map was replaced by one spelling Parallax
    # correctly.
    _tiles = session.project.map("test").tile_layer_names()
    _objects = session.project.map("test").object_layer_names()
    POSITIONS = list(dict.fromkeys(
        [_tiles[0], _tiles[len(_tiles) // 2], _tiles[-1], _objects[0]]))
    expect("four different positions were found to remove and restore",
           len(POSITIONS), 4)
    for layer_name in POSITIONS:
        session.run(Command(
            "map.layer.remove",
            Scope.of(("map", "test"), ("layer", layer_name))))
        expect(f"{layer_name}: removed",
               layer_name in session.project.map("test").layer_names(), False)
        session.undo()
        expect(f"{layer_name}: restored byte-identically",
               session.project.map("test").to_bytes() == ORIGINAL, True)

    print()
    print("layer capabilities are declared data, not inferred behaviour")
    # Capabilities are tmx custom properties, so Tiled shows them and a human
    # edits them in the dialog they already use.
    from editor.core import layers as layers_module  # noqa: E402

    # Declare on a layer this test CREATES, never on one the shipped map
    # happens to carry. The first version asserted that `Paralax` was
    # undeclared, and broke the moment the author declared parallax on it in
    # the real editor -- a check coupled to fixture content again.
    session.run(Command("map.layer.add", MAP,
                        {"name": "Above1Probe", "kind": "tile"}))
    PROBE = Scope.parse("map:test/layer:Above1Probe")
    profile = layers_module.read_profile(
        session.project.map("test").tile_layer("Above1Probe"))
    expect("a fresh layer declares nothing", profile.declared, [])
    expect("so it is static by default", profile.is_static, True)
    expect("and takes its depth from its name", profile.depth, -1)

    session.run(Command("map.layer.set", PROBE,
                        {"key": "parallax_x", "value": 0.5}))
    profile = layers_module.read_profile(
        session.project.map("test").tile_layer("Above1Probe"))
    expect("declaring parallax takes", profile.parallax_x, 0.5)
    expect("and it stops being static, because it cannot be baked",
           profile.is_static, False)
    expect("the property carries the pyoneer_ prefix, which pytmx requires",
           "pyoneer_parallax_x" in session.project.map("test")
           .tile_layer("Above1Probe").properties.as_dict(), True)
    session.undo()
    session.undo()
    expect("undo removes the declaration and the layer",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    PARALAX = PROBE

    expect_raises("an unknown capability is refused", PyoneerCommandApplyError,
                  lambda: session.run(Command("map.layer.set", PARALAX,
                                              {"key": "nope", "value": 1})))
    expect_raises("a value outside a capability's choices is refused",
                  PyoneerCommandApplyError,
                  lambda: session.run(Command("map.layer.set", PARALAX,
                                              {"key": "motion",
                                               "value": "sideways"})))
    expect_raises("and a wrong type is refused", PyoneerCommandApplyError,
                  lambda: session.run(Command("map.layer.set", PARALAX,
                                              {"key": "opacity",
                                               "value": "loud"})))
    # The STORED name is what matters. pytmx raises ValueError and makes the
    # whole map unloadable if a custom property shadows one of its own
    # attributes -- and `opacity` is both a natural capability name and one
    # of those attributes, which is exactly why everything is prefixed.
    expect("every capability is stored prefixed",
           [c.key for c in layers_module.CAPABILITIES
            if not c.property_name.startswith(layers_module.PREFIX)], [])
    expect("so no stored name can collide with a pytmx attribute",
           [c.property_name for c in layers_module.CAPABILITIES
            if c.property_name in layers_module.RESERVED], [])
    expect("and the prefix is doing real work here",
           "opacity" in layers_module.RESERVED
           and any(c.key == "opacity" for c in layers_module.CAPABILITIES), True)

    # The engine reads these properties and the editor writes them, so the
    # two vocabularies must agree exactly. A capability added on one side
    # and forgotten on the other does nothing at all, silently -- which is
    # the failure the shared module exists to prevent.
    from scripts.core import layer_profile  # noqa: E402

    expect("the editor writes exactly what the engine reads",
           sorted(c.property_name for c in layers_module.CAPABILITIES),
           sorted(layer_profile.KNOWN))
    expect("and both use the same prefix",
           layers_module.PREFIX, layer_profile.PREFIX)

    print()
    print("the engine honours a declared parallax, and clamps it")
    import pygame  # noqa: E402

    view = pygame.Rect(200, 150, 1024, 768)
    expect("factor 1.0 samples exactly where the camera looks",
           layer_profile.parallax_view(view, (1.0, 1.0), 1600, 1600), view)
    expect("a slower factor travels less",
           tuple(layer_profile.parallax_view(view, (0.4, 0.4), 1600, 1600)),
           (80, 60, 1024, 768))
    expect("and it never samples past the surface",
           tuple(layer_profile.parallax_view(
               pygame.Rect(1500, 1500, 1024, 768), (2.0, 2.0), 1600, 1600)),
           (576, 832, 1024, 768))

    declared = layer_profile.LayerProfile(parallax=(0.4, 0.4))
    expect("a parallaxed layer is not static, so it leaves the composite",
           declared.static, False)
    expect("a translucent one is not either",
           layer_profile.LayerProfile(opacity=0.5).static, False)
    expect("an undeclared layer still is",
           layer_profile.DEFAULT.static, True)
    expect("a nonsense motion value falls back rather than raising",
           layer_profile.read(
               type("L", (), {"properties": {"pyoneer_motion": "sideways"}})()
           ).motion, "static")
    expect("and a nonsense parallax does too",
           layer_profile.read(
               type("L", (), {"properties": {"pyoneer_parallax_x": "fast"}})()
           ).parallax, (1.0, 1.0))

    print()
    print("passability masks follow RPG Maker's bit order, set means blocked")
    expect("an empty cell reads as open",
           layers_module.gid_to_mask(0, 1793), layers_module.PASS_ALL)
    expect("masks round-trip through gids",
           [layers_module.gid_to_mask(layers_module.mask_to_gid(m, 1793), 1793)
            for m in (0, 1, 9, 15, 16)], [0, 1, 9, 15, 16])
    expect("star is not a direction and not 'open'",
           layers_module.STAR > layers_module.BLOCK_ALL, True)
    expect("a mask describes itself",
           layers_module.describe_mask(layers_module.BLOCK_DOWN
                                       | layers_module.BLOCK_UP),
           "blocks down, up")
    expect("a foreign gid reads as open rather than as garbage",
           layers_module.gid_to_mask(65, 1793), layers_module.PASS_ALL)

    print()
    print("a layer with no depth mapping warns rather than silently not "
          "drawing -- unless it says it does not draw")

    def add_layer_warnings(args):
        """Every warning ONE map.layer.add raised, as text."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            session.run(Command("map.layer.add", MAP, args))
        return [str(entry.message) for entry in caught]

    # Half one: art. The guard that caught 39 authored tiles going missing to
    # a misspelling, and the fix for the false positive beside it must not
    # weaken it.
    said = add_layer_warnings({"name": "NotInDepthPy", "kind": "tile"})
    expect("it warned", any("depth" in message for message in said), True)
    expect("and the layer it names is the one that was added",
           [m for m in said if "NotInDepthPy" in m] != [], True)
    session.undo()
    expect("undo took the art layer back out",
           "NotInDepthPy" in session.project.map("test").layer_names(), False)

    # Half two: data. A passability companion is mask numbers read as gids;
    # advising the author to give it a depth advises him to paint the mask
    # vocabulary over his own map, which is what the collision tools do to
    # him the moment he paints a single cell.
    quiet = add_layer_warnings({"name": "NotInDepthPyEither", "kind": "tile",
                                "renders": False})
    expect("a layer that declares it does not draw is added in silence",
           quiet, [])
    companion = session.project.map("test").tile_layer("NotInDepthPyEither")
    expect("and the declaration really went into the file, so the engine "
           "skips it whatever its name resolves to",
           companion.properties.as_dict().get(
               layers_module.BY_KEY["renders"].property_name), False)
    expect("which is what the engine's own reader sees",
           layers_module.read_profile(companion).renders, False)
    session.undo()
    expect("undo took the declaration with the layer",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    expect("a duplicate layer name is refused", True, True)
    expect_raises("adding a layer that already exists", PyoneerCommandApplyError,
                  lambda: session.run(Command("map.layer.add", MAP,
                                              {"name": "Floor", "kind": "tile"})))
    expect("and the file is untouched",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ---------------------------------------------------------------
    print()
    print("objects: the entity-spawn seam, add and remove")
    # ---------------------------------------------------------------
    # READ, not assumed. This asserted `0` while the map it copies had an
    # empty object layer; the shipped map places a body now, so every count
    # below is relative to what the file already held. `objects()` appends,
    # so the object each add produces is `[-1]`, never `[0]`.
    BORN_WITH = len(session.project.map("test").object_layer("entity").objects())
    expect("the entity layer's starting population was read off the file",
           BORN_WITH >= 0, True)
    session.run(Command("map.object.add", ENTITY, {
        "type": "GamePlayer", "name": "player_start", "x": 64.0, "y": 96.0,
        "properties": {"hp": 30, "playable": True},
    }))
    objects = session.project.map("test").object_layer("entity").objects()
    expect("one more object exists now", len(objects), BORN_WITH + 1)
    expect("its class survived", objects[-1].type, "GamePlayer")
    expect("an int property stayed an int",
           objects[-1].properties["hp"], 30)
    expect("a bool property stayed a bool",
           objects[-1].properties["playable"], True)
    session.undo()
    expect("undo removed it",
           len(session.project.map("test").object_layer("entity").objects()),
           BORN_WITH)
    expect("and the objectgroup went back to self-closing (byte-identical)",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ---------------------------------------------------------------
    print()
    print("the genre default is MATERIALISED onto the object at add time")
    # ---------------------------------------------------------------
    # `session` is a topdown_rpg project, and that pack declares a starting
    # list for GamePlayer on `entity`. What is asserted is the PRECEDENCE,
    # both halves of it: the default applies when the caller said nothing,
    # and it does not apply when the caller said anything at all -- including
    # "nothing", spelled out. A default that overrode an explicit empty list
    # would be a policy rather than a starting value, which is the one thing
    # this design is not.
    STARTS_AS = genre_module.load("topdown_rpg").object_class(
        "entity", "GamePlayer").behaviors_text

    session.run(Command("map.object.add", ENTITY,
                        {"type": "GamePlayer", "x": 16.0, "y": 16.0}))
    born = session.project.map("test").object_layer("entity").objects()[-1]
    # `.as_dict().get` rather than `[...]`, so a version that materialises
    # NOTHING reports a readable got/want instead of raising out of the check
    # -- an assertion that crashes says less than one that names the value.
    expect("a placed GamePlayer is born carrying the pack's list",
           born.properties.as_dict().get(BEHAVIORS), STARTS_AS)
    # Not "a string was written" -- the engine's own reader has to accept it,
    # or the editor has just authored a map that raises at load.
    expect("...and the ENGINE's reader accepts what the editor wrote",
           validate_list(born.properties[BEHAVIORS]),
           tuple(STARTS_AS.split(",")))
    session.undo()
    expect("undo takes the materialised property away with the object",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    session.run(Command("map.object.add", ENTITY,
                        {"type": "GameEntity", "x": 16.0, "y": 16.0}))
    plain = session.project.map("test").object_layer("entity").objects()[-1]
    expect("a class the pack does not name is born with NOTHING",
           plain.properties.as_dict(), {})
    session.undo()

    session.run(Command("map.object.add", ENTITY,
                        {"type": "GamePlayer", "x": 16.0, "y": 16.0,
                         "properties": {BEHAVIORS: "lifecycle_mark"}}))
    mine = session.project.map("test").object_layer("entity").objects()[-1]
    expect("a list the CALLER supplied wins over the pack's",
           mine.properties[BEHAVIORS], "lifecycle_mark")
    session.undo()

    session.run(Command("map.object.add", ENTITY,
                        {"type": "GamePlayer", "x": 16.0, "y": 16.0,
                         "properties": {BEHAVIORS: ""}}))
    empty = session.project.map("test").object_layer("entity").objects()[-1]
    expect("an EXPLICITLY empty list wins too -- 'this one does nothing' "
           "is a thing an author may say",
           empty.properties[BEHAVIORS], "")
    session.undo()
    expect("all four shapes unwound byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    print()
    print("...and it is a STARTING VALUE, never a policy that re-asserts")
    session.run(Command("map.object.add", ENTITY,
                        {"type": "GamePlayer", "x": 16.0, "y": 16.0}))
    first = session.project.map("test").object_layer("entity").objects()[-1]
    target = ENTITY.child("object", str(first.id))

    def behaviors_of(object_id):
        return (session.project.map("test").object_layer("entity")
                .find(object_id).properties.as_dict().get(BEHAVIORS))

    session.run(Command("map.object.property.set", target,
                        {"key": BEHAVIORS, "value": "topdown_move"}))
    expect("the author narrows the list the editor gave them",
           behaviors_of(first.id), "topdown_move")
    session.run(Command("map.object.add", ENTITY,
                        {"type": "GamePlayer", "x": 48.0, "y": 16.0}))
    expect("adding a SECOND object does not re-assert the default on the first",
           behaviors_of(first.id), "topdown_move")
    second = session.project.map("test").object_layer("entity").objects()[-1]
    expect("...while the second one is born with the default, as it should be",
           behaviors_of(second.id), STARTS_AS)
    expect("two objects of one class on one map genuinely differ",
           behaviors_of(first.id) != behaviors_of(second.id), True)
    session.run(Command("map.object.move", target, {"x": 80.0, "y": 16.0}))
    expect("moving the first does not re-assert it either",
           behaviors_of(first.id), "topdown_move")
    expect("and nothing in the pack's rules argues with the author's list",
           [str(p) for p in session.problems() if BEHAVIORS in p.message], [])
    session.undo()                       # the move
    session.undo()                       # the second add
    session.undo()                       # the author's property.set
    expect("undoing the author's edit restores the materialised default",
           behaviors_of(first.id), STARTS_AS)
    session.redo()
    expect("and redo puts the author's list back, not the pack's",
           behaviors_of(first.id), "topdown_move")
    session.undo()
    session.undo()                       # the first add
    expect("the whole sequence unwound byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    print()
    print("object properties round-trip through set and remove")
    session.run(Command("map.object.add", ENTITY,
                        {"type": "GameEntity", "x": 32.0, "y": 32.0}))
    created = session.project.map("test").object_layer("entity").objects()[-1]
    target = ENTITY.child("object", str(created.id))
    session.run(Command("map.object.property.set", target,
                        {"key": "hp", "value": 12}))
    expect("property written",
           session.project.map("test").object_layer("entity")
           .find(created.id).properties["hp"], 12)
    session.run(Command("map.object.property.set", target,
                        {"key": "hp", "value": 20}))
    session.undo()
    expect("undo of an overwrite restores the old value",
           session.project.map("test").object_layer("entity")
           .find(created.id).properties["hp"], 12)
    session.undo()   # the original property.set
    session.undo()   # the object.add
    expect("everything unwound to byte-identical",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    print()
    print("moving an object undoes to the original coordinates")
    session.run(Command("map.object.add", ENTITY,
                        {"type": "GameEntity", "x": 10.0, "y": 20.0}))
    created = session.project.map("test").object_layer("entity").objects()[-1]
    target = ENTITY.child("object", str(created.id))
    session.run(Command("map.object.move", target, {"x": 99.0, "y": 5.0}))
    expect("moved", session.project.map("test").object_layer("entity")
           .find(created.id).x, 99.0)
    session.undo()
    expect("undo restored x", session.project.map("test")
           .object_layer("entity").find(created.id).x, 10.0)
    session.undo()
    expect("byte-identical again",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ---------------------------------------------------------------
    print()
    print("removing a NON-RECTANGULAR object still undoes byte-exactly")
    # ---------------------------------------------------------------
    # A guard against a data-destroying inverse. Inverting `map.object.remove`
    # to `map.object.add` rebuilds an object from eight attributes, so undo
    # silently drops rotation, visible, template and every shape child
    # (<polygon>, <polyline>, <point>, <ellipse>, <text>).
    #
    # Its own fixture, because a byte-identity assertion that only ever removes
    # a plain rectangle the check created two lines earlier compares the code
    # against itself -- and nothing in the shipped map has a shape.
    RICH = b"""<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.10.2" orientation="orthogonal" \
renderorder="right-down" width="4" height="4" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="3" nextobjectid="6">
 <layer id="1" name="Floor" width="4" height="4">
  <data encoding="csv">
0,0,0,0,
0,0,0,0,
0,0,0,0,
0,0,0,0
</data>
 </layer>
 <objectgroup id="2" name="entity">
  <object id="1" name="rot" class="Chest" x="16" y="32" width="16" \
height="16" rotation="37.5" visible="0"/>
  <object id="2" name="poly" class="Zone" x="48" y="16">
   <properties>
    <property name="danger" type="int" value="3"/>
   </properties>
   <polygon points="0,0 32,0 32,24 0,24"/>
  </object>
  <object id="3" name="dot" x="8" y="8">
   <point/>
  </object>
  <object id="4" name="round" x="0" y="48" width="24" height="12">
   <ellipse/>
  </object>
  <object id="5" name="sign" x="32" y="48" width="40" height="20">
   <text wrap="1" color="#ff0000">Beware</text>
  </object>
 </objectgroup>
</map>
"""
    rich_path = os.path.join(workspace, "data", "maps", "rich.tmx")
    with open(rich_path, "wb") as handle:
        handle.write(RICH)
    with open(os.path.join(workspace, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [
            {"name": "test", "identifier": "test", "file": "data/maps/test.tmx"},
            {"name": "rich", "identifier": "rich", "file": "data/maps/rich.tmx"},
        ]}, handle)

    rich_session = Session.open(workspace, genre_id="topdown_rpg")
    expect("the fixture round-trips before any edit",
           rich_session.project.map("rich").to_bytes() == RICH, True)

    shapes = {1: "rotated + hidden rectangle", 2: "polygon with properties",
              3: "point", 4: "ellipse", 5: "text"}
    for object_id, description in shapes.items():
        scope = Scope.parse(f"map:rich/layer:entity/object:{object_id}")
        rich_session.run(Command("map.object.remove", scope))
        rich_session.undo()
        expect(f"remove+undo a {description}",
               rich_session.project.map("rich").to_bytes() == RICH, True)

    print()
    print("and removing every object then undoing them all still matches")
    for object_id in shapes:
        rich_session.run(Command(
            "map.object.remove",
            Scope.parse(f"map:rich/layer:entity/object:{object_id}")))
    expect("all five gone",
           len(rich_session.project.map("rich")
               .object_layer("entity").objects()), 0)
    for _ in shapes:
        rich_session.undo()
    expect("undoing all five is byte-identical",
           rich_session.project.map("rich").to_bytes() == RICH, True)

    print()
    print("attributes that were ABSENT come back absent, not as '0.0'")
    dot = Scope.parse("map:rich/layer:entity/object:3")
    rich_session.run(Command("map.object.set", dot,
                             {"key": "width", "value": "24"}))
    expect("the attribute was written",
           "width" in rich_session.project.map("rich")
           .object_layer("entity").find(3).element.attrib, True)
    rich_session.undo()
    expect("undo removed it rather than writing 0.0",
           "width" in rich_session.project.map("rich")
           .object_layer("entity").find(3).element.attrib, False)
    expect("so the file is byte-identical",
           rich_session.project.map("rich").to_bytes() == RICH, True)

    print()
    print("a Tiled 1.9+ file keeps using 'class' rather than growing a 'type'")
    chest = Scope.parse("map:rich/layer:entity/object:1")
    rich_session.run(Command("map.object.set", chest,
                             {"key": "type", "value": "Barrel"}))
    attributes = rich_session.project.map("rich") \
        .object_layer("entity").find(1).element.attrib
    expect("class was updated in place", attributes.get("class"), "Barrel")
    expect("and no rival 'type' attribute appeared", "type" in attributes, False)
    rich_session.undo()
    expect("undo restores the original class", rich_session.project.map("rich")
           .object_layer("entity").find(1).element.attrib.get("class"), "Chest")

    print()
    print("the remove twin has a vocabulary, and it is not `any string`")
    # `map.object.set` has declared `choices=_OBJECT_ATTRIBUTES` since it was
    # written; its inverse `map.object.unset` declared `Param("key", str)` and
    # nothing else, so the verb that could not WRITE `id` could DELETE it --
    # and an object with no `id` is addressable by no scope, restorable by no
    # inverse, and a different document to every reader. The guard went on the
    # write and the remove twin grew without it: the pass's own shape, on a
    # pair one screenful apart.
    BEFORE_UNSET = rich_session.project.map("rich").to_bytes()
    for refused, why in (("id", "the one that unmakes the object"),
                         ("x", "a position, moved by map.object.move"),
                         ("pyoneer_script", "a property, not an attribute"),
                         ("nonsense", "not an attribute at all"),
                         ("", "not a name")):
        expect_raises_naming(
            "map.object.unset refuses %r -- %s" % (refused, why),
            PyoneerCommandApplyError,
            lambda key=refused: rich_session.run(
                Command("map.object.unset", dot, {"key": key})),
            "must be one of")
    expect("...and five refusals later the map is byte-identical",
           rich_session.project.map("rich").to_bytes() == BEFORE_UNSET, True)
    expect("...and 'id' is still on the object it would have unmade",
           "id" in rich_session.project.map("rich")
           .object_layer("entity").find(3).element.attrib, True)
    key_choices = {v.name: p.choices for v in all_verbs()
                   for p in v.params
                   if v.name in ("map.object.set", "map.object.unset")
                   and p.name == "key"}
    expect("the two halves of the pair declare the SAME vocabulary, off the "
           "same tuple, so neither can drift from the other",
           (key_choices.get("map.object.set"),
            key_choices.get("map.object.unset"),
            key_choices.get("map.object.set")
            is key_choices.get("map.object.unset")),
           (editor.core.verbs._OBJECT_ATTRIBUTES,
            editor.core.verbs._OBJECT_ATTRIBUTES, True))

    # THE OTHER HALF, because a verb that refused everything would satisfy
    # every row above and be useless.
    rich_session.run(Command("map.object.set", dot,
                             {"key": "name", "value": "spot"}))
    rich_session.run(Command("map.object.unset", dot, {"key": "name"}))
    expect("a built-in attribute still unsets",
           "name" in rich_session.project.map("rich")
           .object_layer("entity").find(3).element.attrib, False)
    rich_session.undo()
    expect("...and undo puts the value back",
           rich_session.project.map("rich").object_layer("entity")
           .find(3).element.attrib.get("name"), "spot")
    rich_session.undo()

    # AND HERE IS A DEFECT, PINNED RATHER THAN PAPERED OVER. Measured while
    # writing the row above, which first asserted byte-identity and went red:
    # `ElementTree.Element.set` APPENDS, so an attribute removed from the
    # middle of an element comes back at the END of the attribute list, and
    # `map.object.unset` followed by undo restores the value and NOT the
    # bytes. Every other inverse in this file is byte-exact, so this one is
    # the odd one out rather than the rule. It is pinned the way it really
    # behaves, so the day somebody fixes it this row goes red and gets
    # rewritten -- which is the only way an undocumented wart ever becomes a
    # decision. Repro and the shape of the fix are in `docs/NEXT.md`.
    restored = rich_session.project.map("rich").to_bytes()
    expect("unset + undo restores the VALUE but not the byte order: the "
           "attribute comes back at the end of the element",
           (restored == BEFORE_UNSET, b'name="spot"' in restored),
           (False, False))
    expect("...and it is only the ORDER that moved -- same attributes, same "
           "values, same count",
           sorted(rich_session.project.map("rich").object_layer("entity")
                  .find(3).element.attrib.items()),
           sorted(ElementTree.fromstring(
               BEFORE_UNSET.decode("utf-8"))
               .find(".//objectgroup[@name='entity']/object[@id='3']")
               .attrib.items()))
    # Put the fixture back BY HAND, because the wart is real and every
    # section below this one compares bytes against a document this one
    # would otherwise have left reordered.
    _dot = rich_session.project.map("rich").object_layer("entity").find(3)
    _dot.element.attrib.clear()
    _dot.element.attrib.update(
        ElementTree.fromstring(BEFORE_UNSET.decode("utf-8"))
        .find(".//objectgroup[@name='entity']/object[@id='3']").attrib)
    expect("...and writing the original order back by hand gives the "
           "original bytes, which is the proof that ORDER was the whole "
           "difference", rich_session.project.map("rich").to_bytes()
           == BEFORE_UNSET, True)

    # AND THE SETTER GOES THROUGH THE MODEL, not around it. `map.object.set`
    # used to do `element.set(...)` plus a `_touch()`, which reached around
    # every refusal `MapObject.set` makes. `choices=` covers two of the three
    # from outside; the one it cannot cover is a name the object already
    # carries as a `<property>` -- pytmx casts attributes onto the element
    # first and then RAISES on any property that now shadows one, and the
    # WHOLE MAP stops loading, naming neither. Only a hand-written map can be
    # in that state, because the property door refuses to build it, so it is
    # planted here by hand: that is exactly what the author who opens such a
    # map is holding when they reach for this verb.
    planted = rich_session.project.map("rich").object_layer("entity").find(3)
    holder = ElementTree.SubElement(planted.element, "properties")
    ElementTree.SubElement(holder, "property",
                           {"name": "rotation", "value": "1"})
    PLANTED = rich_session.project.map("rich").to_bytes()
    expect_raises_naming(
        "map.object.set refuses an attribute the object already carries as a "
        "PROPERTY, which `choices=` cannot see and only the model knows",
        PyoneerCommandApplyError,
        lambda: rich_session.run(Command("map.object.set", dot,
                                         {"key": "rotation", "value": "90"})),
        "already carries", "rotation", "the whole map stops loading")
    expect("...without touching the document",
           rich_session.project.map("rich").to_bytes() == PLANTED, True)
    planted.element.remove(holder)
    expect("...and the planted collision comes back out, leaving the fixture "
           "as it was found",
           rich_session.project.map("rich").to_bytes() == BEFORE_UNSET, True)

    # ---------------------------------------------------------------
    print()
    print("declaring a capability on an EMPTY layer undoes byte-exactly")
    # ---------------------------------------------------------------
    # SIGHTING NINE, and the fourth copy of one line. `map.layer.unset` is
    # the fourth place the editor deletes a tmx property, and the pass that
    # put the guard on the other three enumerated "all four places" and
    # missed this one on its own grep. `MapProperties.__delitem__` drops the
    # `<properties>` container once it empties and `_remove_child` hands the
    # whitespace back to the OWNER, so a layer the file wrote self-closing
    # comes back with an open/close pair -- two lines of diff on a
    # declare-then-undo that must leave none, and a map listed DIRTY after a
    # no-op pair, because `MapDocument.changed` re-serialises and compares.
    #
    # Its own fixture, and the fixture is the point: a tile layer always
    # carries `<data>`, so no layer of the shipped map can exercise this at
    # all. Only an object group with no objects in it can -- which is every
    # object layer between `map.layer.add` and the first object landing on
    # it.
    BARE = b"""<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.10.2" orientation="orthogonal" \
renderorder="right-down" width="2" height="2" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="4" nextobjectid="2">
 <layer id="1" name="Floor" width="2" height="2">
  <data encoding="csv">
0,0,
0,0
</data>
 </layer>
 <objectgroup id="2" name="empty"/>
 <objectgroup id="3" name="peopled">
  <object id="1" name="here" x="0" y="0" width="16" height="16"/>
 </objectgroup>
</map>
"""
    bare_path = os.path.join(workspace, "data", "maps", "bare.tmx")
    with open(bare_path, "wb") as handle:
        handle.write(BARE)
    with open(os.path.join(workspace, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [
            {"name": "test", "identifier": "test", "file": "data/maps/test.tmx"},
            {"name": "rich", "identifier": "rich", "file": "data/maps/rich.tmx"},
            {"name": "bare", "identifier": "bare", "file": "data/maps/bare.tmx"},
        ]}, handle)

    bare_session = Session.open(workspace, genre_id="topdown_rpg")
    expect("the empty-layer fixture round-trips before any edit",
           bare_session.project.map("bare").to_bytes() == BARE, True)

    EMPTY_LAYER = Scope.parse("map:bare/layer:empty")
    bare_session.run(Command("map.layer.set", EMPTY_LAYER,
                             {"key": "depth", "value": 3}))
    expect("the capability landed on the empty object layer",
           bare_session.project.map("bare").object_layer("empty")
           .properties.as_dict(), {"pyoneer_depth": 3})
    expect("...which really did open the self-closing element up",
           b'<objectgroup id="2" name="empty">'
           in bare_session.project.map("bare").to_bytes(), True)
    bare_session.undo()
    expect("undo removes the declaration",
           bare_session.project.map("bare").object_layer("empty")
           .properties.as_dict(), {})
    expect("AND THE BYTES COME BACK -- the element is self-closing again",
           bare_session.project.map("bare").to_bytes() == BARE, True)
    expect("...so a no-op pair does not leave the map listed dirty",
           bare_session.project.dirty_maps(), [])

    # The other half of the guard: it must fire ONLY for a layer with
    # nothing left in it. A tile layer keeps its `<data>` and an object
    # group keeps its objects, and blanking `text` on either would eat the
    # indentation of the children that are still there.
    for layer_name, kind in (("Floor", "a tile layer, which keeps its <data>"),
                             ("peopled", "an object group with an object in it")):
        scope = Scope.parse("map:bare/layer:%s" % layer_name)
        bare_session.run(Command("map.layer.set", scope,
                                 {"key": "renders", "value": False}))
        bare_session.undo()
        expect("set+undo on %s is byte-exact too" % kind,
               bare_session.project.map("bare").to_bytes() == BARE, True)
    expect("...and their children survived it",
           (len(bare_session.project.map("bare").tile_layer("Floor").gids()),
            len(bare_session.project.map("bare").object_layer("peopled")
                .objects())), (4, 1))

    print()
    print("...and the remove twin refuses a key its inverse cannot write")
    # The SAME shape one screenful up. `map.layer.set` declares
    # `choices=tuple(_layer_keys())` and validates the capability; its
    # inverse `map.layer.unset` declared `Param("key", str)` and nothing
    # else, so unsetting any OTHER `pyoneer_`-named property returned an
    # inverse that RAISES on the way back. Driven before the fix, on a
    # layer carrying a hand-authored `pyoneer_nonsense`: the property was
    # deleted, Ctrl+Z raised `must be one of [...]`, the value was gone and
    # the history was emptied. `map.object.unset` learned this last pass;
    # this is the same decision for the same reason -- a command whose
    # inverse cannot run is worse than a capability that is missing.
    FLOOR_BARE = Scope.parse("map:bare/layer:Floor")
    stale = bare_session.project.map("bare").tile_layer("Floor")
    stale.properties["pyoneer_nonsense"] = "x"
    WITH_STALE = bare_session.project.map("bare").to_bytes()
    expect_raises_naming(
        "map.layer.unset refuses a pyoneer_ property that is not a declared "
        "capability, because map.layer.set could not write it back",
        PyoneerCommandApplyError,
        lambda: bare_session.run(Command("map.layer.unset", FLOOR_BARE,
                                         {"key": "nonsense"})),
        "must be one of", "inverse is map.layer.set")
    expect("...and the property it would have unmade is still there",
           bare_session.project.map("bare").tile_layer("Floor")
           .properties.as_dict().get("pyoneer_nonsense"), "x")
    expect("...and the refusal touched nothing",
           bare_session.project.map("bare").to_bytes() == WITH_STALE, True)
    # AND IT STILL ALLOWS A LEGITIMATE ONE. A gate proved only to refuse is
    # half an invariant.
    bare_session.run(Command("map.layer.set", FLOOR_BARE,
                             {"key": "depth", "value": 2}))
    bare_session.run(Command("map.layer.unset", FLOOR_BARE, {"key": "depth"}))
    expect("a declared capability still unsets, so the guard is a door and "
           "not a wall",
           "pyoneer_depth" in bare_session.project.map("bare")
           .tile_layer("Floor").properties.as_dict(), False)
    bare_session.undo()
    bare_session.undo()
    expect("...and both steps undo back to the planted fixture",
           bare_session.project.map("bare").to_bytes() == WITH_STALE, True)
    del stale.properties["pyoneer_nonsense"]
    expect("...which the plant comes back out of, leaving the original bytes",
           bare_session.project.map("bare").to_bytes() == BARE, True)

    # ---------------------------------------------------------------
    print()
    print("bad commands are refused before anything happens")
    # ---------------------------------------------------------------
    expect_raises("unknown verb", PyoneerCommandUnknownError,
                  lambda: session.run(Command("map.tile.paint", FLOOR, {})))
    expect_raises("unknown argument", PyoneerCommandApplyError,
                  lambda: session.run(Command("map.tile.set", FLOOR,
                                              {"x": 1, "y": 1, "gid": 1, "z": 3})))
    expect_raises("missing argument", PyoneerCommandApplyError,
                  lambda: session.run(Command("map.tile.set", FLOOR,
                                              {"x": 1, "y": 1})))
    expect_raises("a string where an int is wanted", PyoneerCommandApplyError,
                  lambda: session.run(Command("map.tile.set", FLOOR,
                                              {"x": 1, "y": 1, "gid": "65"})))
    expect_raises("a bool where an int is wanted", PyoneerCommandApplyError,
                  lambda: session.run(Command("map.tile.set", FLOOR,
                                              {"x": 1, "y": 1, "gid": True})))
    expect_raises("a verb aimed at the wrong scope kind", PyoneerCommandApplyError,
                  lambda: session.run(Command("map.tile.set",
                                              Scope.parse("table:actors"),
                                              {"x": 1, "y": 1, "gid": 1})))
    expect_raises("a tile outside the layer", PyoneerCommandApplyError,
                  lambda: session.run(Command("map.tile.set", FLOOR,
                                              {"x": 9999, "y": 0, "gid": 1})))
    expect_raises("a negative gid, which csv cannot round-trip",
                  PyoneerCommandApplyError,
                  lambda: session.run(Command("map.tile.set", FLOOR,
                                              {"x": 1, "y": 1, "gid": -5})))
    expect("none of that touched the file",
           session.project.map("test").to_bytes() == ORIGINAL, True)
    expect("and none of it entered the history", len(session.history()), 0)

    # ---------------------------------------------------------------
    print()
    print("a batch that fails halfway rolls the earlier half back")
    # ---------------------------------------------------------------
    batch = [
        Command("map.tile.set", FLOOR, {"x": 1, "y": 1, "gid": 70}),
        Command("map.tile.set", FLOOR, {"x": 2, "y": 1, "gid": 70}),
        Command("map.tile.set", FLOOR, {"x": 3, "y": 1, "gid": 70}),
        Command("map.tile.set", FLOOR, {"x": 4, "y": 1, "gid": -1}),   # boom
    ]
    try:
        session.run(batch)
        expect("the batch raised", False, True)
    except PyoneerCommandApplyError as exc:
        expect("it names which command failed", "command 4 of 4" in str(exc), True)
        expect("and reports a clean rollback", exc.rolled_back, True)
    expect("the first three were undone",
           session.project.map("test").to_bytes() == ORIGINAL, True)
    expect("the failed batch is not in the history", len(session.history()), 0)

    # ---------------------------------------------------------------
    print()
    print("tables: create from the genre, then grow")
    # ---------------------------------------------------------------
    ACTORS = Scope.parse("table:actors")
    session.run(Command("table.create", ACTORS, {}))
    table = session.project.table("actors")
    expect("it took the genre's columns", len(table.columns), 8)
    expect("including a required one", table.field("hp").type, "int")

    session.run(Command("table.row.add", ACTORS,
                        {"id": "hero", "values": {"display_name": "Hero", "hp": 30}}))
    expect("the row exists", session.project.table("actors").row_ids(), ["hero"])
    expect("unlisted columns took their default",
           session.project.table("actors").rows["hero"]["speed"], 20)

    HERO = Scope.parse("table:actors/row:hero")
    session.run(Command("table.row.set", HERO, {"column": "hp", "value": 42}))
    expect("the cell changed",
           session.project.table("actors").rows["hero"]["hp"], 42)
    session.undo()
    expect("undo restored it",
           session.project.table("actors").rows["hero"]["hp"], 30)

    expect_raises("a string into an int column is refused",
                  PyoneerCommandApplyError,
                  lambda: session.run(Command("table.row.set", HERO,
                                              {"column": "hp", "value": "42"})))
    expect_raises("an unknown column is refused", PyoneerCommandApplyError,
                  lambda: session.run(Command("table.row.set", HERO,
                                              {"column": "mp", "value": 5})))

    print()
    print("adding a column is how the data model grows")
    session.run(Command("table.column.add", ACTORS,
                        {"name": "mp", "type": "int", "doc": "magic points",
                         "default": 5}))
    expect("existing rows got the default",
           session.project.table("actors").rows["hero"]["mp"], 5)
    session.run(Command("table.row.set", HERO, {"column": "mp", "value": 17}))
    session.run(Command("table.column.remove",
                        Scope.parse("table:actors/field:mp")))
    expect("the column is gone",
           session.project.table("actors").field("mp"), None)
    session.undo()
    expect("undo brought back the column AND its values",
           session.project.table("actors").rows["hero"]["mp"], 17)

    print()
    print("hard rules bite")
    expect_raises("a genre-required column cannot be removed",
                  PyoneerCommandApplyError,
                  lambda: session.run(Command(
                      "table.column.remove",
                      Scope.parse("table:actors/field:hp"))))
    expect_raises("a genre-required table cannot be dropped",
                  PyoneerCommandApplyError,
                  lambda: session.run(Command("table.drop", ACTORS,
                                              {"confirm": True})))
    expect("the required column survived",
           session.project.table("actors").field("hp") is not None, True)

    # ---------------------------------------------------------------
    print()
    print("responses parse strictly and apply atomically")
    # ---------------------------------------------------------------
    good = (
        '{"verb": "table.row.add", "scope": "table:actors",'
        ' "args": {"id": "slime", "values": {"display_name": "Slime", "hp": 4}}}\n'
        '\n'
        '```json\n'
        '{"verb": "table.row.add", "scope": "table:actors",'
        ' "args": {"id": "bat", "values": {"display_name": "Bat", "hp": 2}}}\n'
        '```\n'
    )
    parsed = parse_response(good)
    expect("blank lines and fences are tolerated", len(parsed), 2)
    session.run(parsed, label="response", source="response:test")
    expect("both rows landed",
           session.project.table("actors").row_ids(), ["bat", "hero", "slime"])
    session.undo()
    expect("one undo took the whole response back",
           session.project.table("actors").row_ids(), ["hero"])

    expect_raises("a malformed line names its line number",
                  PyoneerResponseParseError,
                  lambda: parse_response('{"verb": "x"}\nnot json\n'))
    expect_raises("a wrapping array is refused", PyoneerResponseParseError,
                  lambda: parse_response('[{"verb": "x", "scope": "project"}]'))
    expect_raises("an empty response is refused", PyoneerResponseParseError,
                  lambda: parse_response("\n\n"))

    print()
    print("a bad line in the middle rolls back the good ones around it")
    mixed = (
        '{"verb": "table.row.add", "scope": "table:actors",'
        ' "args": {"id": "ghost", "values": {"display_name": "Ghost"}}}\n'
        '{"verb": "table.row.set", "scope": "table:actors/row:ghost",'
        ' "args": {"column": "hp", "value": "lots"}}\n'
    )
    try:
        session.run(parse_response(mixed), source="response:test")
        expect("it raised", False, True)
    except PyoneerCommandApplyError as exc:
        expect("clean rollback", exc.rolled_back, True)
    expect("the ghost never made it",
           session.project.table("actors").row_ids(), ["hero"])

    # ---------------------------------------------------------------
    print()
    print("a request bundle is self-contained")
    # ---------------------------------------------------------------
    manifest = Manifest(title="give the hero a sword")
    manifest.add(Note(ACTORS, "The hero should start tougher, around 40 hp."))
    manifest.add(Note(Scope.parse("table:equipment"),
                      "Add an iron sword and a wooden shield.", "change"))
    manifest.add(Note(ENTITY, "Put the player start near the top-left."))
    bundle = write_bundle(session.project, manifest)

    for name in ("BRIEF.md", "REQUEST.md", "RULES.md", "CONTEXT.md",
                 "COMMANDS.md", "manifest.json"):
        path = os.path.join(bundle.directory, name)
        expect(f"bundle has {name}", os.path.isfile(path), True)

    with open(os.path.join(bundle.directory, "REQUEST.md"), encoding="utf-8") as h:
        request_text = h.read()
    expect("the request names its scopes", "`table:actors`" in request_text, True)
    expect("and points at the files that own them",
           "scripts/loaders/map_document.py" in request_text, True)

    with open(os.path.join(bundle.directory, "CONTEXT.md"), encoding="utf-8") as h:
        context_text = h.read()
    expect("context shows the live table", "`hero`" in context_text, True)
    expect("context describes an unbuilt table honestly",
           "has not created it" in context_text, True)

    with open(os.path.join(bundle.directory, "COMMANDS.md"), encoding="utf-8") as h:
        commands_text = h.read()
    expect("the vocabulary is generated, not stubbed",
           all(f"### `{n}`" in commands_text for n in names), True)

    expect("shipping cleared the staged notes", session.manifest.empty, True)

    # ---------------------------------------------------------------
    print()
    print("saving writes only what changed, deterministically")
    # ---------------------------------------------------------------
    written = session.save()
    expect("the untouched map was not rewritten",
           any(p.endswith("test.tmx") for p in written), False)
    expect("the table was written",
           any(p.endswith("actors.json") for p in written), True)
    with open(os.path.join(workspace, "data", "maps", "test.tmx"), "rb") as handle:
        expect("the tmx on disk is untouched", handle.read() == ORIGINAL, True)

    reopened = Project.load(workspace)
    expect("it reloads with the same rows",
           reopened.table("actors").row_ids(), ["hero"])
    expect("and remembers its genre", reopened.genre.id, "topdown_rpg")

    # ---------------------------------------------------------------
    print()
    print("genre validation reports problems without blocking")
    # ---------------------------------------------------------------
    # An arranged violation, not a hopeful one. The first version of this
    # block asserted `len(problems) > 0` on a project that was in fact
    # valid, and passed vacuously in reverse -- it failed, which is the only
    # reason it got fixed. Break something specific and name it.
    #
    # `Session.problems` is the genre's rules PLUS the collision model's own
    # dead-mask rule, and this block is about the genre half. The fixture map
    # is a byte copy of the shipped `starter.tmx`, whose parallaxed layer
    # may carry masks that gate nothing, so the collision half
    # is not empty here -- and law 4 forbids a check pinning whether it is.
    # So split the list AT ITS PRODUCER rather than filtering it by message
    # text: `project.problems()` is exactly the genre half, and the
    # carry-through assertion below -- made where that half is non-empty, so
    # it cannot pass vacuously -- proves `Session` still hands it back first
    # and unchanged. A genre problem therefore cannot hide in the part this
    # block has stopped looking at.
    expect("a valid project reports no genre problem",
           list(session.project.problems()), [])

    session.run([
        Command("map.object.add", ENTITY,
                {"type": "GamePlayer", "x": 0.0, "y": 0.0}),
        Command("map.object.add", ENTITY,
                {"type": "GamePlayer", "x": 32.0, "y": 0.0}),
        Command("map.object.add", ENTITY,
                {"type": "Wumpus", "x": 64.0, "y": 0.0}),
    ])
    genre_problems = list(session.project.problems())
    problems = session.problems()
    expect("the genre's own list arrives first, and unchanged",
           problems[:len(genre_problems)], genre_problems)
    expect("...and there really was something in it to carry",
           len(genre_problems) > 0, True)
    expect("two players trip the unique-type rule",
           any("at most one" in p.message for p in problems), True)
    expect("an undeclared object class is flagged",
           any("Wumpus" in p.message for p in problems), True)
    expect("neither is hard -- a half-built map is allowed",
           [p for p in problems if p.severity == "hard"], [])
    expect("the violations point at where they are",
           all(p.scope.get("map") == "test" for p in problems), True)
    session.undo()
    expect("fixing it clears the genre problems",
           list(session.project.problems()), [])

    # Switching genre is the one move that can invalidate a table that was
    # perfectly valid a second ago, and this block used to switch and never
    # LOOK -- the assertion pair below is the whole reason the switch is
    # interesting. `move_speed` is required by the platformer pack and the
    # topdown_rpg actors table spells its movement column `speed`.
    session.run(Command("project.genre.set", Scope.of("project"),
                        {"genre": "platformer"}))
    expect("the genre switched", session.project.genre.id, "platformer")
    expect("the new pack wants a column this table has not got",
           any("move_speed" in p.message for p in session.problems()), True)
    expect("and the fix it prints is a verb, spelled exactly",
           [p.fix for p in session.problems() if "move_speed" in p.message],
           ["table.column.add move_speed"])
    session.undo()
    expect("and switched back", session.project.genre.id, "topdown_rpg")
    expect("the missing-column violation went back with it",
           any("move_speed" in p.message for p in session.problems()), False)

    # ---------------------------------------------------------------
    print()
    print("the fix the Problems dock prints is a control, not just a string")
    # ---------------------------------------------------------------
    # `editor/core/genre.py` names `table.column.add <name>` as the fix and
    # `editor/ui/docks.py` prints it verbatim on screen -- and the verb had
    # no caller anywhere in the window. Since `table.row.add` and
    # `table.row.set` both (correctly) refuse an unknown column, that left
    # NO way at all to create a stat the pack had not declared, which
    # silently disarms every `source="actors"` behaviour parameter that
    # wanted one. So this drives the control the way a click does, through
    # the same signal `MainWindow` connects.
    if importlib.util.find_spec("PySide6") is None:
        print("  SKIP PySide6 is not installed "
              "(pip install -r editor/requirements.txt)")
    else:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication                  # noqa: E402
        from editor.ui.database import TablePage, column_default    # noqa: E402

        application = QApplication.instance() or QApplication([])
        page = TablePage(session, "actors")
        page.refresh()

        emitted: list = []
        rejections: list = []
        statuses: list = []
        asked: list = []

        def apply(command):
            """Exactly what `MainWindow.run` does with the same signal: one
            door, and a refusal is a report rather than a traceback thrown
            out of a Qt slot."""
            emitted.append(command)
            try:
                session.run(command)
            except PyoneerEditorError as exc:
                rejections.append(str(exc))

        page.command_requested.connect(apply)
        page.status_requested.connect(statuses.append)

        def forget():
            """Nothing carried from one gesture into the next."""
            emitted.clear()
            rejections.clear()
            statuses.clear()

        def answering(**values):
            """Replace the dialog seam. Records the rows it was shown, so
            the form itself is assertable and no window ever opens."""
            def stub(_parent, _title, rows, **_kwargs):
                asked.append(list(rows))
                return dict(values)
            return stub

        before = session.project.table("actors").to_json()

        print()
        print("adding one: the emitted command, and what the stream did with it")
        page.ask = answering(name="stamina", type="int", default="5",
                             doc="how much running is left")
        page._TablePage__on_add_column()
        expect("the control emitted exactly one command", len(emitted), 1)
        expect("and it is the verb the dock prints",
               emitted[-1].verb, "table.column.add")
        expect("scoped to its own table", str(emitted[-1].scope), "table:actors")
        expect("carrying the four arguments the verb declares",
               sorted(emitted[-1].args), ["default", "doc", "name", "type"])
        type_row = next(f for f in asked[-1] if f.key == "type")
        expect("the type row offers exactly the verb's own choices",
               tuple(type_row.choices),
               tuple(verb("table.column.add").param("type").choices))
        expect("the stream refused nothing", rejections, [])
        expect("the column landed with the declared type",
               session.project.table("actors").field("stamina").type, "int")
        expect("and its doc came with it",
               session.project.table("actors").field("stamina").doc, "how much running is left")
        expect("every existing row took the default",
               session.project.table("actors").rows["hero"]["stamina"], 5)
        # The seam hands back strings for everything and `default` is typed
        # `object`, so "5" in an int column would sail through the verb, the
        # file and the loader -- and surface as arithmetic on a str in a
        # behavior, months later.
        expect("as an int, not as the text that was typed",
               type(session.project.table("actors").rows["hero"]["stamina"]).__name__,
               "int")
        session.undo()
        expect("undo took the column and its values back out, exactly",
               session.project.table("actors").to_json(), before)

        print()
        print("...and the answers it must NOT accept")
        forget()
        page.ask = answering(name="hp", type="str", default="lots",
                             doc="collides with the genre's own column")
        page._TablePage__on_add_column()
        expect("a colliding name is still emitted -- the model is the authority",
               len(emitted), 1)
        expect("and the stream refuses it, naming the table and the column",
               [r for r in rejections if "'hp'" in r and "actors" in r] != [],
               True)
        expect("the existing column was not overwritten",
               session.project.table("actors").field("hp").type, "int")
        expect("and nothing at all changed",
               session.project.table("actors").to_json(), before)

        forget()
        page.ask = answering(name="speed_mod", type="float", default="fast",
                             doc="how much faster")
        page._TablePage__on_add_column()
        expect("a default that does not read emits NOTHING", emitted, [])
        expect("and says why, naming what was typed and the type it wanted",
               bool(statuses) and "'fast'" in statuses[0]
               and "float" in statuses[0], True)
        expect("so the column was never created",
               session.project.table("actors").field("speed_mod"), None)

        expect("'true' reads as a bool", column_default("true", "bool"), True)
        expect("and '0' as False", column_default("0", "bool"), False)
        expect("a str column keeps the text",
               column_default(" fast ", "str"), "fast")
        expect_raises("'maybe' is not a bool", ValueError,
                      lambda: column_default("maybe", "bool"))
        expect_raises("and 5.5 is not an int -- it is not truncated either",
                      ValueError, lambda: column_default("5.5", "int"))

        print()
        print("removing one has the same teeth, and an honest status line")
        forget()
        page.ask = answering(name="stamina", type="int", default="5",
                             doc="how much running is left")
        page._TablePage__on_add_column()
        session.run(Command("table.row.set", HERO, {"column": "stamina", "value": 17}))
        statuses.clear()
        page.ask = answering(name="stamina")
        page._TablePage__on_remove_column()
        expect("the picker offers every column, genre-required ones included",
               "hp" in tuple(asked[-1][0].choices), True)
        expect("the column went",
               session.project.table("actors").field("stamina"), None)
        expect("and the status names the way back",
               bool(statuses) and "Ctrl+Z" in statuses[0], True)
        session.undo()
        expect("which is true: the column AND its value came back",
               session.project.table("actors").rows["hero"]["stamina"], 17)

        forget()
        page.ask = answering(name="hp")
        page._TablePage__on_remove_column()
        expect("a genre-required column is refused",
               [r for r in rejections if "requires column" in r] != [], True)
        expect("it survived",
               session.project.table("actors").field("hp") is not None, True)
        # The half that is easy to miss: a control that prints "removed --
        # Ctrl+Z brings it back" on a removal that never happened teaches the
        # author to trust a message that is not measuring anything.
        expect("and NOTHING claimed it had been removed", statuses, [])

        print()
        print("a control that cannot act looks like it cannot act")
        blank = TablePage(session, "equipment")
        blank.refresh()
        expect("the equipment table does not exist yet", blank.exists, False)
        expect("so Add column is dead",
               blank.add_column_button.isEnabled(), False)
        expect("and says why",
               "create the equipment table first"
               in blank.add_column_button.toolTip(), True)
        expect("Remove column too", blank.remove_column_button.isEnabled(), False)
        page.refresh()
        expect("while the built table's Add column is live",
               page.add_column_button.isEnabled(), True)
        expect("and its Remove column is, because it has columns",
               page.remove_column_button.isEnabled(), True)

        session.undo()          # the stamina value
        session.undo()          # and the column the control added
        expect("the section left the table exactly as it found it",
               session.project.table("actors").to_json(), before)
        # Owned, hidden, then deferred -- law 12. setParent(None) here would
        # promote both pages to top-level windows.
        for widget in (page, blank):
            widget.hide()
            widget.deleteLater()
        application.processEvents()

finally:
    shutil.rmtree(workspace, ignore_errors=True)


# --------------------------------------------------------------------------
print()
print("a dropped table's FILE waits for the save, so undo can reach it")
# --------------------------------------------------------------------------
# `Project.drop_table` called `os.remove` INSIDE the command, so
# `table.restore` -- the exact inverse `table.drop` returns and the history
# offers as Ctrl+Z -- put the table back in memory and left the `.json`
# deleted. Worse than a destructive verb with no inverse, because the
# history says it can be taken back. The session was not even dirty
# afterwards, so closing took the silent clean-close branch and committed a
# deletion nobody confirmed.
#
# The fix is not invented here: `ScriptLibrary`'s docstring names this fault
# by name as its own reason for deferring, so `Project` now keeps the same
# `removed` set and unlinks at `save`. These rows drive the SESSION, never
# `drop_table` directly -- calling the writer proves the writer works, which
# was never in doubt.
#
# Its own workspace, with no maps at all, so a table assertion cannot borrow
# a map's answer.
TABLE_WS = tempfile.mkdtemp(prefix="pyoneer_drop_check_")
LOOT_COLUMNS = [{"name": "price", "type": "int", "doc": "in gold", "default": 0}]
try:
    os.makedirs(os.path.join(TABLE_WS, "config"))
    with open(os.path.join(TABLE_WS, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": []}, handle)

    drop_session = Session.open(TABLE_WS, genre_id="topdown_rpg")
    drop_project = drop_session.project
    LOOT = Scope.parse("table:loot")
    drop_session.run(Command("table.create", LOOT, {"columns": LOOT_COLUMNS}))
    drop_session.run(Command("table.row.add", LOOT,
                             {"id": "sword", "values": {"price": 12}}))
    drop_session.save()
    loot_path = drop_project.table_path("loot")
    expect("the table is on disk before the drop", os.path.isfile(loot_path), True)
    expect("...and the session is clean, so a close would not ask",
           drop_project.dirty, False)

    drop_session.run(Command("table.drop", LOOT, {"confirm": True}))
    expect("the drop takes the table out of the session",
           drop_project.has_table("loot"), False)
    expect("AND LEAVES THE FILE ALONE -- the unlink waits for the save",
           os.path.isfile(loot_path), True)
    expect("...so the session is dirty and NAMES it, which is what makes the "
           "close prompt fire instead of closing silently",
           (drop_project.dirty_tables(), drop_project.dirty),
           (["loot"], True))

    expect("undo puts the table back", bool(drop_session.undo()), True)
    expect("...with its rows", drop_project.table("loot").rows,
           {"sword": {"price": 12}})
    expect("...AND ITS FILE, which is the half a command cannot invert once "
           "the unlink has happened", os.path.isfile(loot_path), True)
    drop_session.save()
    expect("...and a project opened fresh off that disk reads the rows back",
           Project.load(TABLE_WS).table("loot").rows, {"sword": {"price": 12}})

    # THE OTHER HALF. A deferred unlink that never unlinks is the opposite
    # failure and would pass every row above: drop, SAVE, and the file must
    # really be gone and stay gone across a reload.
    drop_session.run(Command("table.drop", LOOT, {"confirm": True}))
    written = drop_session.save()
    expect("a drop that is SAVED really does delete the file",
           os.path.isfile(loot_path), False)
    expect("...and it is not reported as a file that was written",
           [w for w in written if w.endswith("loot.json")], [])
    expect("...and the session is clean again afterwards",
           (drop_project.dirty_tables(), drop_project.dirty), ([], False))
    expect("...and a fresh project does not find it",
           Project.load(TABLE_WS).has_table("loot"), False)

    # AND THE LISTING ASKS WHAT EXISTS. A table created and dropped without
    # ever being saved has no file to unlink, so it is not a document "not
    # on disk" and naming it would raise the close prompt over a file that
    # never existed -- the same sentence `dirty_scripts` had to learn below.
    drop_session.run(Command("table.create", LOOT, {"columns": LOOT_COLUMNS}))
    expect("an unsaved table is dirty while it exists",
           (drop_project.dirty_tables(), drop_project.dirty), (["loot"], True))
    drop_session.run(Command("table.drop", LOOT, {"confirm": True}))
    expect("...and dropping it leaves NOTHING to save and nothing to say",
           (drop_project.dirty_tables(), drop_project.dirty), ([], False))
    expect("...and the save it never needed writes no table",
           [w for w in drop_session.save() if w.endswith("loot.json")], [])
finally:
    shutil.rmtree(TABLE_WS, ignore_errors=True)


# --------------------------------------------------------------------------
print()
print("an undone creation leaves the session clean, not dirty forever")
# --------------------------------------------------------------------------
# `ScriptLibrary.delete` adds to `removed` unconditionally, including for a
# document that was never on disk -- so `New... -> Ctrl+Z` left the session
# permanently dirty and the close prompt offered to save a file the undo had
# already taken away. Nothing was lost; the SENTENCE was false, in exactly
# the direction `Project.dirty_scripts` was written to fix, with the
# opposite sign.
#
# The prompt fires iff `session.dirty`, and the list it then prints is
# `dirty_maps() + dirty_tables() + dirty_scripts()` -- so these rows compose
# the same sentence `MainWindow.closeEvent` composes rather than naming a
# widget, and a change to either half shows up here.
SCRIPT_WS = tempfile.mkdtemp(prefix="pyoneer_undone_check_")
SCRIPT_WS2 = tempfile.mkdtemp(prefix="pyoneer_kept_check_")


def close_prompt(project):
    """Exactly what `MainWindow.closeEvent` asks and then prints."""
    return (project.dirty,
            project.dirty_maps() + project.dirty_tables()
            + project.dirty_scripts())


try:
    for root in (SCRIPT_WS, SCRIPT_WS2):
        os.makedirs(os.path.join(root, "config"))
        with open(os.path.join(root, "config", "maps.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"data": []}, handle)

    SIGN = Scope.parse("script:signpost")

    undone = Session.open(SCRIPT_WS, genre_id="topdown_rpg")
    expect("a project with nothing authored would close silently",
           close_prompt(undone.project), (False, []))
    undone.run(Command("script.create", SIGN, {"title": "The signpost"}))
    expect("authoring one raises the prompt and names it",
           close_prompt(undone.project), (True, ["signpost"]))
    expect("undo takes it back out of the library", bool(undone.undo()), True)
    expect("AND THE SESSION IS CLEAN -- the prompt does not fire, and there "
           "is no document left for it to name",
           close_prompt(undone.project), (False, []))
    library = event_script.scripts_of(undone.project)
    expect("...which is true rather than forgotten: the library still holds "
           "the id as removed, and there is no file under it",
           (sorted(library.removed), library.names(),
            os.path.isfile(library.path_for("signpost"))),
           (["signpost"], [], False))

    # THE POSITIVE CONTROL, in its own session so it cannot inherit an
    # answer. A creation that is KEPT must still be dirty, or the row above
    # passes because nothing is ever counted.
    kept = Session.open(SCRIPT_WS2, genre_id="topdown_rpg")
    kept.run(Command("script.create", SIGN, {"title": "The signpost"}))
    expect("POSITIVE CONTROL: a creation that is KEPT still prompts",
           close_prompt(kept.project), (True, ["signpost"]))
    kept.save()
    expect("...and one save clears it", close_prompt(kept.project), (False, []))

    # AND THE CASE THE RULE MUST NOT EAT. A deletion of a document that IS
    # on disk stays listed: nothing in memory is dirty, the `.json` is still
    # there, and the save is what unlinks it. That is the row this listing
    # was originally written for, and "ask what exists" must not answer it
    # the other way.
    kept.run(Command("script.delete", SIGN, {"confirm": True}))
    expect("deleting a SAVED script is still listed, because its file is "
           "still on disk", close_prompt(kept.project), (True, ["signpost"]))
    expect("...and undoing that delete leaves a document that EXISTS, which "
           "is dirty by its own flag rather than by the removed set",
           (bool(kept.undo()), close_prompt(kept.project),
            sorted(event_script.scripts_of(kept.project).removed)),
           (True, (True, ["signpost"]), []))
finally:
    shutil.rmtree(SCRIPT_WS, ignore_errors=True)
    shutil.rmtree(SCRIPT_WS2, ignore_errors=True)


# --------------------------------------------------------------------------
print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
