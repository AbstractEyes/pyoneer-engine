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
  * `scripts/` does not import `editor/`

No pygame, no Qt. Runs on a bare clone with no art.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import atexit
import json
import os
import shutil
import sys
import tempfile
import warnings

from editor.core import genre as genre_module
from editor.core.commands import Command, all_verbs, describe_all, verb_names
from editor.core.errors import (
    PyoneerCommandApplyError,
    PyoneerCommandArgumentError,
    PyoneerCommandScopeError,
    PyoneerCommandUnknownError,
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


def fixture_pack(*layers):
    """Write a throwaway pack; return a thunk that LOADS it.

    A thunk rather than a loaded pack, because half of what is asserted here
    is that loading REFUSES -- and a helper that loaded eagerly could only
    ever exercise the half that succeeds, which is the exact one-sided shape
    law 5 is about.
    """
    global _fixture_serial
    _fixture_serial += 1
    identifier = f"fixture{_fixture_serial}"
    root = os.path.join(GENRE_FIXTURES, identifier)
    os.makedirs(root)
    with open(os.path.join(root, "genre.json"), "w", encoding="utf-8") as handle:
        json.dump({"id": identifier, "title": "Fixture",
                   "layers": list(layers)}, handle)
    return lambda: genre_module.load(identifier, GENRE_FIXTURES)


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
    shutil.copy2(os.path.join(REPO, "data", "maps", "test.tmx"),
                 os.path.join(workspace, "data", "maps", "test.tmx"))
    with open(os.path.join(workspace, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [{"name": "test", "identifier": "test",
                             "file": "data/maps/test.tmx"}]}, handle)

    with open(os.path.join(workspace, "data", "maps", "test.tmx"), "rb") as handle:
        ORIGINAL = handle.read()

    session = Session.open(workspace, genre_id="topdown_rpg")
    expect("the map index loaded", session.project.map_names(), ["test"])
    expect("the map parses", session.project.map("test").width, 100)
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
           session.project.map("test").tile_layer("Hazard").width, 100)
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
    # arithmetic, not the fixture, so repainting test.tmx cannot make it red.
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
    # The whitespace before a layer lives in its previous sibling's tail, and
    # this file mixes tabs and spaces, so a recomputed indent is wrong
    # somewhere no matter what it computes. Each position exercises a
    # different branch: first child, middle child, last child, only child.
    for layer_name in ("Paralax", "GroundClutter", "Foreground", "entity"):
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
    expect("the entity layer starts empty",
           len(session.project.map("test").object_layer("entity").objects()), 0)
    session.run(Command("map.object.add", ENTITY, {
        "type": "GamePlayer", "name": "player_start", "x": 64.0, "y": 96.0,
        "properties": {"hp": 30, "playable": True},
    }))
    objects = session.project.map("test").object_layer("entity").objects()
    expect("one object exists now", len(objects), 1)
    expect("its class survived", objects[0].type, "GamePlayer")
    expect("an int property stayed an int",
           objects[0].properties["hp"], 30)
    expect("a bool property stayed a bool",
           objects[0].properties["playable"], True)
    session.undo()
    expect("undo removed it",
           len(session.project.map("test").object_layer("entity").objects()), 0)
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
    born = session.project.map("test").object_layer("entity").objects()[0]
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
    plain = session.project.map("test").object_layer("entity").objects()[0]
    expect("a class the pack does not name is born with NOTHING",
           plain.properties.as_dict(), {})
    session.undo()

    session.run(Command("map.object.add", ENTITY,
                        {"type": "GamePlayer", "x": 16.0, "y": 16.0,
                         "properties": {BEHAVIORS: "lifecycle_mark"}}))
    mine = session.project.map("test").object_layer("entity").objects()[0]
    expect("a list the CALLER supplied wins over the pack's",
           mine.properties[BEHAVIORS], "lifecycle_mark")
    session.undo()

    session.run(Command("map.object.add", ENTITY,
                        {"type": "GamePlayer", "x": 16.0, "y": 16.0,
                         "properties": {BEHAVIORS: ""}}))
    empty = session.project.map("test").object_layer("entity").objects()[0]
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
    first = session.project.map("test").object_layer("entity").objects()[0]
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
    second = session.project.map("test").object_layer("entity").objects()[1]
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
    created = session.project.map("test").object_layer("entity").objects()[0]
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
    created = session.project.map("test").object_layer("entity").objects()[0]
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
    expect("a valid project reports nothing", session.problems(), [])

    session.run([
        Command("map.object.add", ENTITY,
                {"type": "GamePlayer", "x": 0.0, "y": 0.0}),
        Command("map.object.add", ENTITY,
                {"type": "GamePlayer", "x": 32.0, "y": 0.0}),
        Command("map.object.add", ENTITY,
                {"type": "Wumpus", "x": 64.0, "y": 0.0}),
    ])
    problems = session.problems()
    expect("two players trip the unique-type rule",
           any("at most one" in p.message for p in problems), True)
    expect("an undeclared object class is flagged",
           any("Wumpus" in p.message for p in problems), True)
    expect("neither is hard -- a half-built map is allowed",
           [p for p in problems if p.severity == "hard"], [])
    expect("the violations point at where they are",
           all(p.scope.get("map") == "test" for p in problems), True)
    session.undo()
    expect("fixing it clears them", session.problems(), [])

    session.run(Command("project.genre.set", Scope.of("project"),
                        {"genre": "platformer"}))
    expect("the genre switched", session.project.genre.id, "platformer")
    session.undo()
    expect("and switched back", session.project.genre.id, "topdown_rpg")

finally:
    shutil.rmtree(workspace, ignore_errors=True)

# --------------------------------------------------------------------------
print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
