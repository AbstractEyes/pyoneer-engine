"""Drive the editor's Qt window offscreen and assert it holds together.

Not a screenshot test. It builds the real window against a throwaway copy
of the real map, drives the real signal paths, and asserts the things that
would actually break:

  * every panel builds and refreshes without raising
  * a canvas click produces a COMMAND, not a direct mutation -- which is
    what makes undo work on hand edits
  * a rejected edit reaches the user as a message, not a traceback
  * the prompt strip on each panel carries that panel's scope, so a note
    lands where the panel is pointing
  * shipping writes a bundle and applying a response comes back through
    the same door

Skips cleanly when PySide6 is not installed; the engine does not depend on
it and a bare clone should not fail here.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import importlib.util
import json
import os
import shutil
import sys
import tempfile

if importlib.util.find_spec("PySide6") is None:
    print("SKIP  PySide6 is not installed "
          "(pip install -r editor/requirements.txt)")
    sys.exit(0)

# Must be set before QApplication exists.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt                                   # noqa: E402
from PySide6.QtGui import QMouseEvent                                   # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox                 # noqa: E402

from editor.core.commands import Command                                # noqa: E402
from editor.core.scope import Scope                                     # noqa: E402
from editor.core.session import Session                                 # noqa: E402
from editor.ui.main_window import EditorWindow                          # noqa: E402

REPO = _bootstrap.REPO_ROOT
failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<56} got={got} want={want}")
    if not ok:
        failures.append(label)


# Silence the modal dialogs the window raises on rejection, and record that
# they happened -- "the user was told" is the assertion, not the pixels.
warned: list[str] = []
QMessageBox.warning = staticmethod(
    lambda *a, **k: warned.append(str(a[2]) if len(a) > 2 else ""))
QMessageBox.critical = staticmethod(
    lambda *a, **k: warned.append(str(a[2]) if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

workspace = tempfile.mkdtemp(prefix="pyoneer_editor_ui_")
application = QApplication.instance() or QApplication([])

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

    # ----------------------------------------------------------------
    print("the window and every panel build")
    # ----------------------------------------------------------------
    window = EditorWindow(session)
    window.show()
    application.processEvents()
    expect("it opened the map", window.map_name, "test")
    expect("the canvas composited every visible layer",
           len(window.canvas.scene().items()) > 0, True)
    # The map nests its layers in two <group> elements, so layer_names()
    # returns 9 things of which only 7 are real layers. Groups are listed as
    # structure but must not be selectable: `map:test/layer:Graphic` is a
    # scope no verb can act on.
    expect("the layer list shows the authored structure",
           window.layers.list.count(), 9)
    selectable = [window.layers.list.item(i).data(Qt.UserRole)
                  for i in range(window.layers.list.count())]
    expect("groups are not selectable",
           sorted(n for n in selectable if n),
           ["Above1", "Floor", "Foreground", "GroundClutter", "Paralax",
            "PlayerDepth", "entity"])
    expect("the tile palette found the tilesets",
           len(window.canvas.atlas.entries), 2)
    expect("and reports the art is missing rather than pretending",
           window.canvas.atlas.has_art, False)

    # ----------------------------------------------------------------
    print()
    print("selecting a layer re-aims the canvas, the panels and the prompt")
    # ----------------------------------------------------------------
    for index in range(window.layers.list.count()):
        item = window.layers.list.item(index)
        if item.data(Qt.UserRole) == "Floor":
            window.layers.list.setCurrentItem(item)
            break
    application.processEvents()
    expect("the canvas knows what it is painting", window.canvas.active_layer, "Floor")
    expect("the layers panel re-scoped",
           str(window.layers.scope), "map:test/layer:Floor")
    expect("its prompt strip followed",
           str(window.layers.strip.scope()), "map:test/layer:Floor")
    expect("the objects panel followed too",
           str(window.objects.scope), "map:test/layer:Floor")

    # ----------------------------------------------------------------
    print()
    print("a canvas click is a command, so it undoes")
    # ----------------------------------------------------------------
    window.canvas.brush_gid = 77
    before = session.project.map("test").tile_layer("Floor").get_tile(3, 5)
    scene_point = window.canvas.mapFromScene(3 * 16 + 8, 5 * 16 + 8)
    click = QMouseEvent(QMouseEvent.MouseButtonPress, QPoint(scene_point),
                        Qt.LeftButton, Qt.LeftButton, Qt.AltModifier)
    window.canvas.mousePressEvent(click)
    application.processEvents()
    expect("the tile changed",
           session.project.map("test").tile_layer("Floor").get_tile(3, 5), 77)
    expect("through the command stream", len(session.history()), 1)
    expect("and the history panel says so",
           "map.tile.set" in window.history.view.toPlainText(), True)
    window.undo()
    expect("undo restored the tile",
           session.project.map("test").tile_layer("Floor").get_tile(3, 5), before)
    expect("byte-identical", session.project.map("test").to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("placing an object on the object layer works the same way")
    # ----------------------------------------------------------------
    for index in range(window.layers.list.count()):
        item = window.layers.list.item(index)
        if item.data(Qt.UserRole) == "entity":
            window.layers.list.setCurrentItem(item)
            break
    application.processEvents()
    window.canvas.object_class = "GamePlayer"
    point = window.canvas.mapFromScene(64, 96)
    window.canvas.mousePressEvent(QMouseEvent(
        QMouseEvent.MouseButtonPress, QPoint(point), Qt.LeftButton,
        Qt.LeftButton, Qt.AltModifier))
    application.processEvents()
    objects = session.project.map("test").object_layer("entity").objects()
    expect("an object was placed", len(objects), 1)
    expect("with the chosen class", objects[0].type, "GamePlayer")
    expect("the objects panel lists it", window.objects.tree.topLevelItemCount(), 1)
    window.undo()
    application.processEvents()
    expect("undo removed it",
           len(session.project.map("test").object_layer("entity").objects()), 0)
    expect("byte-identical again",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("a rejected edit is reported, not raised")
    # ----------------------------------------------------------------
    warned.clear()
    ok = window.run(Command("map.tile.set",
                            Scope.parse("map:test/layer:Floor"),
                            {"x": 99999, "y": 0, "gid": 1}))
    expect("run() reported failure instead of throwing", ok, False)
    expect("the user was shown why", len(warned), 1)
    expect("nothing entered the history", len(session.history()), 0)
    expect("and the file is untouched",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("the tables panel generates itself from the genre")
    # ----------------------------------------------------------------
    window.tables.picker.setCurrentText("actors")
    application.processEvents()
    expect("an uncreated table says so, honestly",
           "has not created it" in window.tables.note.text(), True)
    expect("and offers to create it", window.tables.create.isEnabled(), True)
    window.tables.create.click()
    application.processEvents()
    expect("the table now exists", session.project.has_table("actors"), True)
    expect("with the genre's columns", window.tables.table.columnCount(), 8)

    window.run(Command("table.row.add", Scope.of(("table", "actors")),
                       {"id": "hero", "values": {"display_name": "Hero"}}))
    application.processEvents()
    expect("the row shows up", window.tables.table.rowCount(), 1)

    # Edit a cell the way a user would, and confirm it became a command.
    item = window.tables.table.item(0, [c.name for c in
                                        session.project.table("actors").columns
                                        ].index("hp"))
    item.setText("40")
    application.processEvents()
    expect("editing a cell changed the value",
           session.project.table("actors").rows["hero"]["hp"], 40)
    window.undo()
    expect("and it undoes",
           session.project.table("actors").rows["hero"]["hp"], 10)

    warned.clear()
    window.tables.table.item(0, [c.name for c in
                                 session.project.table("actors").columns
                                 ].index("hp")).setText("not a number")
    application.processEvents()
    expect("a bad cell value is refused with a message", len(warned), 1)
    expect("and the value is unchanged",
           session.project.table("actors").rows["hero"]["hp"], 10)

    # ----------------------------------------------------------------
    print()
    print("the prompt strips stage notes against their own panel's scope")
    # ----------------------------------------------------------------
    window.layers.strip.field.setText("this layer needs a cliff edge")
    window.layers.strip.stage()
    window.tables.strip.field.setText("the hero should start tougher")
    window.tables.strip.stage()
    application.processEvents()
    expect("two notes staged", len(session.manifest.notes), 2)
    scopes = sorted(str(n.scope) for n in session.manifest.notes)
    # The tables panel is pointed at the TABLE, not a row -- nothing has been
    # selected in it. That is correct: the note is about the actors table.
    expect("each carries its panel's scope", scopes,
           ["map:test/layer:entity", "table:actors"])

    # Selecting a cell narrows the scope to that row, so the next note lands
    # on the row rather than the whole table.
    window.tables.table.setCurrentCell(0, 0)
    application.processEvents()
    expect("selecting a row narrows the prompt's scope",
           str(window.tables.strip.scope()), "table:actors/row:hero")
    expect("the manifest panel enabled shipping", window.manifest.ship.isEnabled(), True)
    expect("and the badge counts them", "2" in window.layers.strip.badge.text(), True)

    # ----------------------------------------------------------------
    print()
    print("shipping writes a bundle; a response comes back through run()")
    # ----------------------------------------------------------------
    bundle = session.ship(title="ui smoke")
    window.refresh_manifest()
    expect("the bundle exists", os.path.isdir(bundle.directory), True)
    expect("shipping cleared the strip badges", window.layers.strip.badge.text(), "")

    with open(bundle.response_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({
            "verb": "table.row.set", "scope": "table:actors/row:hero",
            "args": {"column": "hp", "value": 55}}) + "\n")
    window.apply_response(bundle.response_path)
    application.processEvents()
    expect("the response applied",
           session.project.table("actors").rows["hero"]["hp"], 55)
    expect("as one transaction the human can take back",
           session.history()[-1].source, f"response:{bundle.identifier}")
    window.undo()
    expect("and did take back",
           session.project.table("actors").rows["hero"]["hp"], 10)

    # ----------------------------------------------------------------
    print()
    print("switching genre re-shapes the panels without losing data")
    # ----------------------------------------------------------------
    window.run(Command("project.genre.set", Scope.of("project"),
                       {"genre": "platformer"}))
    application.processEvents()
    expect("the genre switched", session.project.genre.id, "platformer")
    expect("the actors table survived", session.project.has_table("actors"), True)
    expect("problems recomputed against the new rules",
           window.problems.list.count() >= 1, True)
    window.undo()
    application.processEvents()
    expect("and switched back", session.project.genre.id, "topdown_rpg")

    window.close()

finally:
    shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
