"""Assert the authoring surfaces for map events and the collision tileset.

`check_map_events.py` proves the trigger vocabulary is correct in isolation.
This file covers the seams it cannot see:

  * `map.object.action.*` exists, validates at the authoring door, and its
    inverse carries the value it FOUND rather than one the validator would
    re-derive. That distinction is the whole reason `map.object.action.
    restore` exists, and it is the assertion with the most teeth here: a
    hand-authored `pyoneer_filter_tags="B,a"` must come back as `"B,a"` and
    not as the normalised `"a,b"`, and a hand-authored
    `pyoneer_trigger="entre"` must survive an undo instead of raising in the
    middle of one.
  * `ActionsDock` renders that vocabulary, emits those verbs, and says on
    screen -- in a QLabel, not a docstring and not a tooltip -- that the
    engine cannot execute any of it.
  * `MapCanvas` declares the collision tileset through `map.tileset.add`,
    with an exact inverse, inside the same transaction as the stroke that
    needed it -- and provisions the sheet it points at rather than asking.
    `tools/check_collision_mount.py` owns the teeth for that path.

Against its OWN fixture, never `data/maps/test.tmx` (law 4). The author
repaints that file constantly. The fixture here declares exactly what these
seams need: no
collision tileset (so the offer path runs), an object with no declaration,
an object whose declaration was HAND-AUTHORED badly and in a middle
position, and a tile object with no size (so the region reader's two
corrections are exercised).

Skips cleanly when PySide6 is absent.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import importlib.util
import json
import os
import sys
import tempfile

if importlib.util.find_spec("PySide6") is None:
    print("SKIP  PySide6 is not installed "
          "(pip install -r editor/requirements.txt)")
    sys.exit(0)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt                          # noqa: E402
from PySide6.QtGui import QColor, QImage, QMouseEvent                   # noqa: E402
from PySide6.QtWidgets import (                                         # noqa: E402
    QApplication,
    QLabel,
    QMainWindow,
)

from editor.core import layers as layer_module                          # noqa: E402
from editor.core import map_events                                      # noqa: E402
from editor.core.commands import Command, all_verbs, describe_all       # noqa: E402
from editor.core.paint import EditMode                                  # noqa: E402
from editor.core.scope import Scope                                     # noqa: E402
from editor.core.session import Session                                 # noqa: E402
from editor.ui.actions_panel import (                                   # noqa: E402
    NOT_WIRED,
    ActionsDock,
    declared_keys,
    describe_actions,
    removal_commands,
)
from editor.ui.canvas import (                                          # noqa: E402
    COLLISION_IMAGE,
    COLLISION_TILESET,
    COMPANION_SUFFIX,
    MapCanvas,
)
# Where those two constants are actually DEFINED. canvas.py re-exports them
# from here, and the assertions below check that it still does -- by identity,
# because a re-pasted copy is equal to the original on the day it is pasted.
from scripts.core import collision_runtime                              # noqa: E402

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={got} want={want}")
    if not ok:
        failures.append(label)


# --------------------------------------------------------------------------
# The fixture
# --------------------------------------------------------------------------

WIDTH, HEIGHT = 6, 4

#: Object 2 carries three properties and the two map-event ones are NOT
#: first, because "restoring a middle property re-appends it at the end" is a
#: stated limit of this vocabulary and a check that only ever removed the
#: last one would never see it.
FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" compressionlevel="-1" width="6" height="4" \
tilewidth="16" tileheight="16" infinite="0" nextlayerid="4" nextobjectid="4">
 <tileset firstgid="1" name="Art" tilewidth="16" tileheight="16" \
tilecount="256" columns="16">
  <image source="art.png" width="256" height="256"/>
 </tileset>
 <layer id="1" name="Floor" width="6" height="4">
  <data encoding="csv">
0,0,0,0,0,0,
0,0,0,0,0,0,
0,0,0,0,0,0,
0,0,0,0,0,0
</data>
 </layer>
 <objectgroup id="2" name="Triggers">
  <properties>
   <property name="pyoneer_trigger_layer" value="Floor"/>
  </properties>
  <object id="1" name="plain" type="GameEntity" x="0" y="0" width="16" \
height="16"/>
  <object id="2" name="hand" type="Trigger" x="32" y="16" width="32" \
height="16">
   <properties>
    <property name="hp" type="int" value="5"/>
    <property name="pyoneer_filter_tags" value="B,a"/>
    <property name="pyoneer_trigger" value="entre"/>
   </properties>
  </object>
  <object id="3" name="spot" type="Trigger" x="16" y="48" gid="5"/>
 </objectgroup>
</map>
"""


class Harness(QMainWindow):
    """The one thing a panel and the canvas ask of their window: `run`.

    Deliberately not `EditorWindow`. A failure here has to be a failure in
    the canvas or the panel rather than in whatever the toolbar happens to
    look like today, and `check_editor_ui.py` already drives the real window.
    """

    def __init__(self, session, map_name: str):
        super().__init__()
        self.session = session
        self.rejected: list[str] = []
        self.canvas = MapCanvas(session, map_name, self)
        self.setCentralWidget(self.canvas)

    def run(self, commands, *, label=None, source="editor") -> bool:
        try:
            self.session.run(commands, label=label, source=source)
        except Exception as exc:                                # noqa: BLE001
            self.rejected.append(str(exc))
            return False
        self.canvas.rebuild()
        return True

    def refresh_manifest(self) -> None:
        """`ScopedDock` wires its prompt strip to this."""


def press(canvas, cell, button=Qt.LeftButton):
    """One mouse press in CELL coordinates, the way a real one arrives."""
    scene_x = cell[0] * canvas.tile_width + canvas.tile_width / 2
    scene_y = cell[1] * canvas.tile_height + canvas.tile_height / 2
    point = QPointF(canvas.mapFromScene(scene_x, scene_y))
    canvas.mousePressEvent(
        QMouseEvent(QEvent.Type.MouseButtonPress, point, button, button,
                    Qt.NoModifier))


def release(canvas, cell, button=Qt.LeftButton):
    """The other half of a gesture. A stroke commits on the button coming
    UP, so a check that only presses proves nothing about what is written."""
    scene_x = cell[0] * canvas.tile_width + canvas.tile_width / 2
    scene_y = cell[1] * canvas.tile_height + canvas.tile_height / 2
    point = QPointF(canvas.mapFromScene(scene_x, scene_y))
    canvas.mouseReleaseEvent(
        QMouseEvent(QEvent.Type.MouseButtonRelease, point, button, button,
                    Qt.NoModifier))


def write_image(path: str, width: int, height: int) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    image.save(path, "PNG")


def props(document, object_id: int) -> dict:
    return document.object_layer("Triggers").find(object_id).properties.as_dict()


def order(document, object_id: int) -> list[str]:
    return list(document.object_layer("Triggers").find(object_id).properties)


workspace = tempfile.mkdtemp(prefix="pyoneer_actions_")
application = QApplication.instance() or QApplication([])

try:
    os.makedirs(os.path.join(workspace, "config"))
    os.makedirs(os.path.join(workspace, "data", "maps"))
    fixture_path = os.path.join(workspace, "data", "maps", "fixture.tmx")
    with open(fixture_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(FIXTURE)
    with open(os.path.join(workspace, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [{"name": "fixture", "identifier": "fixture",
                             "file": "data/maps/fixture.tmx"}]}, handle)

    session = Session.open(workspace, genre_id="topdown_rpg")
    document = session.project.map("fixture")
    ORIGINAL = document.to_bytes()

    PLAIN = Scope.of(("map", "fixture"), ("layer", "Triggers"), ("object", "1"))
    HAND = Scope.of(("map", "fixture"), ("layer", "Triggers"), ("object", "2"))
    SPOT = Scope.of(("map", "fixture"), ("layer", "Triggers"), ("object", "3"))
    LAYER = Scope.of(("map", "fixture"), ("layer", "Triggers"))

    def last():
        return session.history()[-1]

    def run(verb, scope, args):
        return session.run(Command(verb, scope, args))

    def refused(verb, scope, args) -> str:
        try:
            session.run(Command(verb, scope, args))
        except Exception as exc:                                # noqa: BLE001
            return type(exc).__name__
        return "nothing raised"

    # ----------------------------------------------------------------
    print("the map-event vocabulary is registered and documents itself")
    # ----------------------------------------------------------------
    registered = {v.name: v for v in all_verbs()}
    expect("all three verbs are in the registry",
           sorted(n for n in registered if n.startswith("map.object.action")),
           ["map.object.action.restore", "map.object.action.set",
            "map.object.action.unset"])
    expect("they reach an object and nothing else",
           registered["map.object.action.set"].scopes,
           ("map:*/layer:*/object:*",))
    expect("`key` is restricted to the declared fields",
           registered["map.object.action.set"].param("key").choices,
           tuple(c.key for c in map_events.FIELDS))
    documentation = describe_all()
    expect("the generated docs say the engine cannot run one",
           "NOTHING RUNS THIS YET" in documentation, True)
    # The verb summary is a SECOND copy of the panel's banner, and it rotted
    # in exactly the same way and outlived the fix to the first one: it was
    # still telling every reader of docs/COMMANDS.md that the engine has no
    # collision detection and no object-layer reader, months after both
    # shipped. Pin the same two absences here that NOT_WIRED pins below, so
    # the mirror cannot drift away from the face of the panel again.
    expect("...and the summary does not claim a gap the engine has closed",
           [phrase for phrase in
            ("no collision detection", "no reader for the object layer")
            if phrase in documentation], [])
    expect("...naming instead what really is unread",
           "pyoneer_trigger" in documentation
           and "MAP_TRIGGER_*" in documentation, True)
    expect("removing a field is marked destructive",
           registered["map.object.action.unset"].destructive, True)

    # ----------------------------------------------------------------
    print()
    print("authoring a trigger is a command, and undo is byte-exact")
    # ----------------------------------------------------------------
    transaction = run("map.object.action.set", PLAIN,
                      {"key": "trigger", "value": "enter"})
    expect("the property landed under its prefix",
           props(document, 1).get("pyoneer_trigger"), "enter")
    expect("the inverse of a NEW field removes it",
           (transaction.inverses[0].verb, transaction.inverses[0].args),
           ("map.object.action.unset", {"key": "trigger"}))
    session.undo()
    expect("undo took it back out", "pyoneer_trigger" in props(document, 1), False)
    expect("and the file is byte-identical, <properties> and all",
           document.to_bytes() == ORIGINAL, True)

    run("map.object.action.set", PLAIN,
        {"key": "filter_tags", "value": "Player, NPC ,"})
    expect("a filter list is normalised on the way in",
           props(document, 1).get("pyoneer_filter_tags"), "npc,player")
    session.undo()
    expect("and that undoes byte-exactly too",
           document.to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("the inverse carries what it FOUND, not what validate would make")
    # ----------------------------------------------------------------
    # `validate` sorts and case-folds a filter list. An inverse rebuilt
    # through it would put "a,b" back where the author wrote "B,a" -- a
    # silent rewrite of a value this vocabulary never authored.
    transaction = run("map.object.action.set", HAND,
                      {"key": "filter_tags", "value": "ghost"})
    expect("overwriting an existing field inverts through restore",
           transaction.inverses[0].verb, "map.object.action.restore")
    expect("carrying the value verbatim, unnormalised",
           transaction.inverses[0].args, {"key": "filter_tags", "value": "B,a"})
    session.undo()
    expect("so undo reproduces the authored spelling",
           props(document, 2).get("pyoneer_filter_tags"), "B,a")
    expect("and the bytes with it", document.to_bytes() == ORIGINAL, True)

    # `validate` REFUSES an unknown trigger kind. An inverse rebuilt through
    # it would raise in the middle of an undo and take the rollback with it.
    run("map.object.action.set", HAND, {"key": "trigger", "value": "enter"})
    undone = "raised"
    try:
        session.undo()
        undone = props(document, 2).get("pyoneer_trigger")
    except Exception as exc:                                    # noqa: BLE001
        undone = f"raised {type(exc).__name__}"
    expect("undo puts back a value validate would have rejected",
           undone, "entre")
    expect("byte-exactly, because it was the last property declared",
           document.to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("the authoring door refuses what the reader could not read back")
    # ----------------------------------------------------------------
    expect("set refuses an invented trigger kind",
           refused("map.object.action.set", PLAIN,
                   {"key": "trigger", "value": "entre"}),
           "PyoneerCommandApplyError")
    expect("and changed nothing", document.to_bytes() == ORIGINAL, True)
    expect("set refuses a duplicated argument key",
           refused("map.object.action.set", PLAIN,
                   {"key": "args", "value": "door=1;door=2"}),
           "PyoneerCommandApplyError")
    expect("set refuses a negative cooldown",
           refused("map.object.action.set", PLAIN,
                   {"key": "cooldown_ms", "value": -5}),
           "PyoneerCommandApplyError")
    expect("set refuses a field this vocabulary does not declare",
           refused("map.object.action.set", PLAIN,
                   {"key": "colour", "value": "red"}),
           "PyoneerCommandApplyError")
    expect("restore refuses a value a tmx property cannot hold",
           refused("map.object.action.restore", PLAIN,
                   {"key": "payload", "value": [1, 2]}),
           "PyoneerCommandApplyError")
    # restore is the unvalidated twin ON PURPOSE -- that is what lets it put
    # a hand-authored value back. Assert the asymmetry rather than assuming it.
    run("map.object.action.restore", PLAIN, {"key": "trigger", "value": "entre"})
    expect("restore writes what set refused",
           props(document, 1).get("pyoneer_trigger"), "entre")
    session.undo()
    expect("and undoes it", document.to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("removing fields: values always exact, bytes when it was last")
    # ----------------------------------------------------------------
    transaction = run("map.object.action.unset", PLAIN, {"key": "trigger"})
    expect("removing a field that was never there is a no-op",
           transaction.inverses[0].verb, "noop")

    run("map.object.action.unset", HAND, {"key": "trigger"})
    expect("the last-declared field goes",
           "pyoneer_trigger" in props(document, 2), False)
    session.undo()
    expect("and comes back byte-exactly",
           document.to_bytes() == ORIGINAL, True)

    # The stated limit: `MapProperties` cannot insert at an index, so a
    # middle property comes back at the end. The VALUE is the contract and
    # it holds; nothing is lost, and this is why there is no `clear` verb.
    run("map.object.action.unset", HAND, {"key": "filter_tags"})
    session.undo()
    expect("a middle field's value survives exactly",
           props(document, 2).get("pyoneer_filter_tags"), "B,a")
    expect("and no property is lost on the way",
           sorted(order(document, 2)),
           ["hp", "pyoneer_filter_tags", "pyoneer_trigger"])

    # ----------------------------------------------------------------
    print()
    print("a whole declaration is removed, and restored, as one step")
    # ----------------------------------------------------------------
    keys = declared_keys(document.object_layer("Triggers").find(2))
    expect("the declared fields are read in FIELDS order",
           keys, ("trigger", "filter_tags"))
    batch = removal_commands(HAND, keys)
    expect("one unset per declared field",
           [c.verb for c in batch],
           ["map.object.action.unset", "map.object.action.unset"])
    before = len(session.history())
    session.run(batch, label="Remove the trigger declaration")
    expect("applied as ONE transaction", len(session.history()) - before, 1)
    expect("nothing map-event is left",
           [k for k in props(document, 2) if k.startswith("pyoneer_")], [])
    expect("and the object's other properties are untouched",
           props(document, 2), {"hp": 5})
    session.undo()
    expect("one undo brings the whole declaration back",
           (props(document, 2).get("pyoneer_trigger"),
            props(document, 2).get("pyoneer_filter_tags")), ("entre", "B,a"))

    # ----------------------------------------------------------------
    print()
    print("the panel describes the declaration as data")
    # ----------------------------------------------------------------
    inspection = describe_actions(session, LAYER)
    expect("a non-object scope is refused, in words",
           "region is an object" in inspection.error, True)

    inspection = describe_actions(session, PLAIN)
    expect("three sections, trigger first",
           [s.title for s in inspection.sections], ["Trigger", "Region", "Anchor"])
    trigger_section = inspection.sections[0]
    expect("every declared field is offered, in FIELDS order",
           [f.key for f in trigger_section.fields],
           [c.key for c in map_events.FIELDS])
    expect("an undeclared object says so rather than showing nothing",
           "declares nothing" in trigger_section.note, True)
    expect("nothing is removable on an object that declares nothing",
           [f.key for f in trigger_section.fields if f.removable], [])

    field = {f.key: f for f in trigger_section.fields}["trigger"]
    expect("editing the kind emits the authoring verb",
           field.emit("enter"),
           Command("map.object.action.set", PLAIN,
                   {"key": "trigger", "value": "enter"}))
    blocks = {f.key: f for f in trigger_section.fields}["blocks"]
    expect("and a flag emits the same verb with a bool",
           blocks.emit(True),
           Command("map.object.action.set", PLAIN,
                   {"key": "blocks", "value": True}))

    inspection = describe_actions(session, HAND)
    trigger_section = inspection.sections[0]
    fields = {f.key: f for f in trigger_section.fields}
    expect("only the authored fields are removable",
           sorted(f.key for f in trigger_section.fields if f.removable),
           ["filter_tags", "trigger"])
    expect("removing one emits the removal verb",
           fields["filter_tags"].remove(None),
           Command("map.object.action.unset", HAND, {"key": "filter_tags"}))
    # `entre` is what the FILE says; `""` is what the reader makes of it, and
    # the form has to show the second or it teaches the author a lie.
    expect("a value the reader rejects shows as the default",
           fields["trigger"].value, "")
    # Stated as the RULE rather than as today's answer, so adding
    # `trigger_layer` to editor/core/layers.py lights the field up and this
    # keeps passing -- a check that pinned `editable is False` would have to
    # be edited by whoever finished the feature, which is how a check starts
    # being treated as an obstacle.
    anchor_field = inspection.sections[2].fields[0]
    expect("the anchor is editable exactly when map.layer.set accepts it",
           anchor_field.editable, "trigger_layer" in layer_module.BY_KEY)
    expect("and it shows the objectgroup's declaration either way",
           anchor_field.value.startswith("Floor"), True)

    spot = describe_actions(session, SPOT)
    expect("a zero-sized object is named as a cell, not a region",
           "authored CELL" in spot.sections[1].note, True)
    expect("and a tile object's bottom-left anchor is named",
           "BOTTOM-left" in spot.sections[1].note, True)

    # ----------------------------------------------------------------
    print()
    print("the panel says on screen that none of it runs")
    # ----------------------------------------------------------------
    window = Harness(session, "fixture")
    dock = ActionsDock("Actions", session, PLAIN, window)
    window.addDockWidget(Qt.RightDockWidgetArea, dock)
    dock.refresh()
    application.processEvents()

    shown = [label.text() for label in dock.findChildren(QLabel)]
    expect("the warning is in a visible label, not a docstring",
           NOT_WIRED in shown, True)
    # BOTH halves of the banner's contract, because a banner has two ways to
    # be wrong and only one of them used to be checked.
    #
    # Half one, which was always here: it must NAME what is missing. A banner
    # that hedges ("some of this may not work yet") is a banner nobody can act
    # on. The three phrases below are the gap as it stands at HEAD.
    expect("it names what is missing rather than hedging",
           [phrase for phrase in
            ("MAP_TRIGGER_", "pyoneer_trigger", "event bus")
            if phrase not in NOT_WIRED], [])
    # Half two, which is new and is why this pin was edited: it must not claim
    # a gap the engine has already closed. Both of these were on the face of
    # the panel while the renderer was already doing them, and an OVERSTATED
    # gap costs exactly what an understated one costs -- it sends a reader off
    # to build something that is there. The absence is pinned so re-adding
    # either phrase goes red instead of reading as extra honesty.
    expect("...and does not claim a gap the engine has already closed",
           [phrase for phrase in
            ("no collision detection", "skips object layers")
            if phrase in NOT_WIRED], [])
    # ...and the absence above is only meaningful while those two really ARE
    # closed, so assert the closing rather than trusting the day it was
    # measured. Read as text rather than imported: `scripts/core/renderer.py`
    # drags pygame in, and this check must still SKIP cleanly on a machine
    # that has the editor's requirements and not the engine's.
    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "scripts", "core", "renderer.py"),
            encoding="utf-8") as handle:
        renderer_source = handle.read()
    expect("the renderer really does bake a collision field "
           "(LayerRenderer.__bind_map)",
           "field_from_map(tmx_data)" in renderer_source, True)
    expect("...and really does spawn an object layer's objects "
           "(LayerRenderer.__prepare_entity_layers)",
           "spawn_objects(tmx_data" in renderer_source, True)

    expect("an object with no declaration cannot be un-declared",
           dock.remove.isEnabled(), False)
    expect("but can be given a trigger", dock.add_trigger.isEnabled(), True)

    before = len(session.history())
    dock.add_trigger.click()
    application.processEvents()
    expect("the button ran exactly one command",
           [c.verb for c in session.history()[-1].commands],
           ["map.object.action.set"])
    expect("declaring one", props(document, 1).get("pyoneer_trigger"), "enter")
    expect("and the panel re-read the document",
           dock.add_trigger.isEnabled(), False)
    expect("which is now removable", dock.remove.isEnabled(), True)
    session.undo()
    dock.refresh()
    expect("undo returns the panel to its empty state",
           (dock.remove.isEnabled(), len(session.history())), (False, before))
    expect("and the map to its bytes", document.to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("the collision tileset is declared by the stroke that needs it")
    # ----------------------------------------------------------------
    canvas = window.canvas
    canvas.set_active_layer("Floor")
    canvas.set_mode(EditMode.COLLISION)
    application.processEvents()
    expect("this fixture has no mask tileset",
           canvas.collision_first_gid, None)

    offer = canvas.collision_tileset_offer()
    expect("the offer names the tileset the canvas looks for",
           offer.name, COLLISION_TILESET)
    expect("one row of seventeen, at the map's tile size",
           (offer.columns, offer.tile_count, offer.tile_width, offer.tile_height),
           (17, 17, 16, 16))
    expect("sized from the mask domain, since the sheet is absent",
           (offer.exists, offer.image_width, offer.image_height),
           (False, 272, 16))
    expect("it can hold every mask", offer.sufficient, True)
    expect("the path written into the tmx is the relative one",
           offer.command_args()["image"], COLLISION_IMAGE)
    # add_tileset reads the PNG header when these are absent and RAISES when
    # the file is not there, which is the normal case for this offer.
    expect("the dimensions are handed over rather than measured",
           sorted(offer.command_args()),
           ["columns", "image", "image_height", "image_width", "name",
            "tile_count", "tile_height", "tile_width"])

    # The two assertions above compare the offer against COLLISION_TILESET
    # and COLLISION_IMAGE -- which are imported FROM the module that builds
    # the offer, so they agree by construction and neither can fail. Rename
    # either constant and the offer renames with it, silently. What actually
    # has to hold is below.
    #
    # COLLISION_TILESET is the name a map is PAINTED against in the editor and
    # the name the ENGINE reads it back by, and canvas.py imports the engine's
    # one -- so asserting they MATCH would compare an object with itself. Both
    # halves of the real contract instead: the exact string, which every
    # already-painted map is stored against, and the fact that the canvas is
    # re-exporting rather than declaring.
    expect("the tileset a map is painted against is spelled 'collision'",
           COLLISION_TILESET, "collision")
    expect("and a companion layer is the layer's name plus 'Collision'",
           COMPANION_SUFFIX, "Collision")
    expect("...and the canvas re-exports the engine's, rather than its own",
           (COLLISION_TILESET is collision_runtime.COLLISION_TILESET,
            COMPANION_SUFFIX is collision_runtime.COMPANION_SUFFIX),
           (True, True))
    # Not just the constants: the function that names the companion this
    # canvas will paint into has to name the layer the engine reads masks out
    # of. The fixture's Floor declares no pyoneer_passability, so this is the
    # convention branch -- the one a hand-authored map depends on.
    expect("an undeclared layer's companion is named by that convention",
           canvas.companion_name("Floor"), "FloorCollision")
    expect("...which is the answer the engine gives for the same layer",
           collision_runtime.companion_name(canvas.document, "Floor"),
           "FloorCollision")
    # COLLISION_IMAGE has no second definition to compare with. Its exact
    # spelling IS the contract with every map the offer has already touched:
    # the string is written verbatim into the tmx, so changing it re-points
    # those maps at a sheet that is not there. Pinned as a literal for that
    # reason, and only that reason.
    expect("the offer proposes the System collision sheet by name",
           COLLISION_IMAGE, "../graphics/tilesets/System/Collision.png")
    expect("...relative, and with forward slashes, so the tmx stays portable",
           (os.path.isabs(COLLISION_IMAGE), "\\" in COLLISION_IMAGE),
           (False, False))
    # ...and the offer resolves it against the MAP's directory, which is what
    # Tiled and the engine both do with an <image source>.
    expect("the offer resolves that relative path against the map",
           os.path.normcase(offer.absolute),
           os.path.normcase(os.path.normpath(os.path.join(
               os.path.dirname(canvas.document.path), COLLISION_IMAGE))))

    # The offer is not a QUESTION: there is no `confirm` seam on the canvas to
    # answer, and a dialog on a paint click is what
    # `tools/check_collision_mount.py` owns the teeth against. What this file
    # asserts is the seam it has always covered -- that a press reaches
    # `map.tileset.add` with an exact inverse.
    expect("the canvas carries no consent seam at all",
           hasattr(canvas, "confirm"), False)
    sheet = os.path.normpath(
        os.path.join(os.path.dirname(fixture_path), COLLISION_IMAGE))
    expect("and the sheet it will declare is not on disk yet",
           os.path.exists(sheet), False)

    before = len(session.history())
    press(canvas, (0, 0))
    release(canvas, (0, 0))
    application.processEvents()
    expect("one stroke, one transaction, tileset first",
           [c.verb for c in last().commands],
           ["map.tileset.add", "map.layer.add", "map.layer.set",
            "map.layer.set", "map.tile.set_many"])
    expect("through the command path, with the guarded inverse",
           (last().inverses[0].verb, last().inverses[0].args["force"]),
           ("map.tileset.remove", False))
    expect("the map now has a gid range for masks",
           canvas.collision_first_gid, 257)
    expect("and the file the declaration points at was written",
           os.path.isfile(sheet), True)
    session.undo()
    canvas.rebuild()
    expect("undo takes the whole declaration back out",
           (canvas.collision_first_gid, document.to_bytes() == ORIGINAL),
           (None, True))
    expect("...and leaves the PNG alone, which is what undo owes it",
           os.path.isfile(sheet), True)

    # ----------------------------------------------------------------
    print()
    print("a sheet already on disk is measured, and refused when too small")
    # ----------------------------------------------------------------
    write_image(sheet, 272, 16)
    offer = canvas.collision_tileset_offer()
    expect("an existing sheet is measured, not assumed",
           (offer.exists, offer.image_width, offer.tile_count), (True, 272, 17))

    write_image(sheet, 80, 16)
    offer = canvas.collision_tileset_offer()
    expect("a sheet with five tiles cannot hold seventeen masks",
           (offer.tile_count, offer.sufficient), (5, False))
    before = len(session.history())
    expect("so provisioning refuses rather than overwriting the author's",
           canvas.provision_collision_tileset(), None)
    expect("without a command, and without touching the file",
           (len(session.history()), QImage(sheet).width()), (before, 80))

finally:
    application.processEvents()

print()
if failures:
    print(f"FAILED: {failures}")
    raise SystemExit(1)
print("ALL CHECKS PASS")
