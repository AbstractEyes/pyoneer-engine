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

import json
import os
import shutil
import sys
import tempfile

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

from editor.core.errors import PyoneerGenreMissingError

expect_raises("an unknown genre fails loudly", PyoneerGenreMissingError,
              lambda: genre_module.load("no_such_genre"))

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
    # This is a regression guard for a data-destroying bug. `map.object.remove`
    # used to invert to `map.object.add`, which rebuilds an object from eight
    # attributes -- so undo silently dropped rotation, visible, template and
    # every shape child (<polygon>, <polyline>, <point>, <ellipse>, <text>).
    #
    # The earlier byte-identity assertions did not catch it because the only
    # objects they ever removed were plain rectangles they had created
    # themselves two lines earlier: the test compared the code against itself.
    # Nothing in the shipped map has a shape, so this needs its own fixture.
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
