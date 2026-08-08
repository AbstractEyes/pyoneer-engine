"""Drive the editor's Qt window offscreen and assert it holds together.

Not a screenshot test. It builds the real window against a throwaway copy
of the real map, drives the real signal paths, and asserts what would
actually break:

  * every panel builds and refreshes without raising
  * a canvas DRAG is one transaction, not one per cell -- the property that
    makes undo usable
  * the terrain tool re-tiles cells the cursor never touched
  * selecting anything re-aims the hierarchy, the inspector and the prompt
  * a rejected edit reaches the user as a message, not a traceback
  * a response comes back through the same door a click does

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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt                          # noqa: E402
from PySide6.QtGui import QMouseEvent                                   # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox                 # noqa: E402

from editor.core.autotile import TerrainSet                             # noqa: E402
from editor.core.commands import Command                                # noqa: E402
from editor.core.paint import Stamp, Tool                               # noqa: E402
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


# Silence modal dialogs and record that the user was told.
warned: list[str] = []
QMessageBox.warning = staticmethod(
    lambda *a, **k: warned.append(str(a[2]) if len(a) > 2 else ""))
QMessageBox.critical = staticmethod(
    lambda *a, **k: warned.append(str(a[2]) if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

workspace = tempfile.mkdtemp(prefix="pyoneer_editor_ui_")
application = QApplication.instance() or QApplication([])


def mouse(window, kind, cell, button=Qt.LeftButton, buttons=None):
    """Drive the canvas the way a real mouse would, in CELL coordinates."""
    canvas = window.canvas
    scene_x = cell[0] * canvas.tile_width + canvas.tile_width / 2
    scene_y = cell[1] * canvas.tile_height + canvas.tile_height / 2
    point = QPointF(canvas.mapFromScene(scene_x, scene_y))
    held = buttons if buttons is not None else button
    event = QMouseEvent(kind, point, button, held, Qt.NoModifier)
    {QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
     QEvent.Type.MouseMove: canvas.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent}[kind](event)


def drag(window, cells, button=Qt.LeftButton):
    mouse(window, QEvent.Type.MouseButtonPress, cells[0], button)
    for cell in cells[1:]:
        mouse(window, QEvent.Type.MouseMove, cell, Qt.NoButton, button)
    mouse(window, QEvent.Type.MouseButtonRelease, cells[-1], button)
    application.processEvents()


def select_layer(window, name):
    window.selection.select(
        Scope.of(("map", window.map_name), ("layer", name)))
    application.processEvents()


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
    expect("the canvas composited something",
           len(window.canvas.scene().items()) > 0, True)
    expect("the tile palette found both tilesets",
           len(window.canvas.atlas.entries), 2)
    expect("it picked a paintable layer to start on",
           window.canvas.active_layer, "Paralax")

    # ----------------------------------------------------------------
    print()
    print("the hierarchy shows the authored tree, groups included")
    # ----------------------------------------------------------------
    tree = window.hierarchy.tree
    labels, addressable = [], []
    stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        labels.append(item.text(0))
        raw = item.data(0, Qt.UserRole)
        if raw:
            addressable.append(raw)
        stack.extend(item.child(i) for i in range(item.childCount()))
    expect("both Tiled groups are shown as structure",
           sum(1 for text in labels if text.startswith("▾")), 2)
    expect("but neither is addressable",
           any("layer:Graphic" in a or "layer:Entity" in a
               for a in addressable), False)
    expect("all seven real layers are",
           sum(1 for a in addressable if "/layer:" in a), 7)

    # ----------------------------------------------------------------
    print()
    print("one selection re-aims every panel that inspects")
    # ----------------------------------------------------------------
    select_layer(window, "Floor")
    expect("the canvas knows what it is painting",
           window.canvas.active_layer, "Floor")
    expect("the hierarchy followed",
           str(window.hierarchy.scope), "map:test/layer:Floor")
    expect("the inspector followed",
           str(window.inspector.scope), "map:test/layer:Floor")
    expect("and its prompt strip did too",
           str(window.inspector.strip.scope()), "map:test/layer:Floor")
    expect("Problems did NOT follow -- it is about the project",
           str(window.problems.scope), "project")

    # ----------------------------------------------------------------
    print()
    print("a canvas DRAG is one transaction, not one per cell")
    # ----------------------------------------------------------------
    layer = session.project.map("test").tile_layer("Floor")
    before = [layer.get_tile(x, 5) for x in range(3, 9)]
    window.canvas.stamp = Stamp.single(77)
    window.canvas.tool = Tool.BRUSH
    drag(window, [(3, 5), (5, 5), (8, 5)])
    expect("every cell along the drag was painted",
           [session.project.map("test").tile_layer("Floor").get_tile(x, 5)
            for x in range(3, 9)], [77] * 6)
    expect("as a SINGLE transaction", len(session.history()), 1)
    expect("which one undo takes back", True, True)
    window.undo()
    expect("the row is restored",
           [session.project.map("test").tile_layer("Floor").get_tile(x, 5)
            for x in range(3, 9)], before)
    expect("byte-identical", session.project.map("test").to_bytes() == ORIGINAL,
           True)

    print()
    print("a fast drag leaves no gaps")
    drag(window, [(20, 20), (26, 26)])
    painted = [(x, y) for x in range(20, 27) for y in range(20, 27)
               if session.project.map("test").tile_layer("Floor").get_tile(x, y) == 77]
    expect("the diagonal is contiguous, not two dots", len(painted), 7)
    window.undo()

    print()
    print("right-drag erases, and also as one step")
    drag(window, [(30, 30), (33, 30)], button=Qt.RightButton)
    expect("the cells were cleared",
           {session.project.map("test").tile_layer("Floor").get_tile(x, 30)
            for x in range(30, 34)}, {0})
    expect("one transaction", len(session.history()), 1)
    window.undo()
    expect("byte-identical again",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("the terrain tool re-tiles cells the cursor never touched")
    # ----------------------------------------------------------------
    # Paint on a layer this check CREATES, so the fixture is guaranteed
    # empty. Using a shipped layer failed as soon as the author painted in
    # it, and Floor cannot be used at all: it is filled with gid 65, a real
    # quadrant of the grass autotile block, so the terrain recogniser
    # correctly reads most of it as already-grass and a small stroke changes
    # almost nothing. Right behaviour, useless fixture.
    window.run(Command("map.layer.add", Scope.of(("map", "test")),
                       {"name": "TerrainProbe", "kind": "tile"}))
    select_layer(window, "TerrainProbe")
    window.canvas.tool = Tool.AUTOTILE
    window.canvas.stamp = Stamp.single(98)      # a TileA2 grass fill quadrant
    terrain = window.canvas._MapCanvas__terrain_for_brush()
    expect("the brush resolved to a terrain", isinstance(terrain, TerrainSet), True)
    expect("and to the right autotile block", terrain.origin, 1)
    expect("the layer starts empty",
           set(session.project.map("test").tile_layer("TerrainProbe").gids()),
           {0})

    before_stroke = len(session.history())
    drag(window, [(40, 40), (42, 40)])
    expect("the stroke is ONE transaction on top of the layer creation",
           len(session.history()) - before_stroke, 1)
    touched = session.history()[-1].commands[0].args["tiles"]
    xs = [x for x, _y, _g in touched]
    ys = [y for _x, y, _g in touched]
    # Corners of cells 40..42 span a 4x2 lattice, which tiles a 4x3 cell
    # block -- wider and taller than the three cells dragged over.
    expect("it wrote outside the dragged cells", min(ys) < 40 or max(ys) > 40,
           True)
    expect("and used more than one gid",
           len({g for _x, _y, g in touched}) > 1, True)
    window.undo()          # the stroke
    window.undo()          # the probe layer
    expect("terrain and the probe layer both undo byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)
    window.canvas.tool = Tool.BRUSH

    # ----------------------------------------------------------------
    print()
    print("objects: place, inspect, edit, delete, undo")
    # ----------------------------------------------------------------
    select_layer(window, "entity")
    window.canvas.object_class = "GamePlayer"
    mouse(window, QEvent.Type.MouseButtonPress, (4, 6))
    application.processEvents()
    objects = session.project.map("test").object_layer("entity").objects()
    expect("an object was placed", len(objects), 1)
    expect("with the chosen class", objects[0].type, "GamePlayer")

    window.selection.select(Scope.of(("map", "test"), ("layer", "entity"),
                                     ("object", str(objects[0].id))))
    application.processEvents()
    inspection = window.inspector.view.inspection
    fields = {f.key: f for section in inspection.sections for f in section.fields}
    expect("the inspector describes it", inspection.heading, "object 1")
    expect("it offers position as a number", fields["x"].kind, "float")
    expect("class as a constrained choice", fields["type"].kind, "choice")
    expect("rotation is editable now", fields["rotation"].editable, True)
    expect("and visible is a checkbox", fields["visible"].kind, "bool")

    window.run(fields["x"].emit(128.0))
    expect("editing through the inspector moved it",
           session.project.map("test").object_layer("entity")
           .find(objects[0].id).x, 128.0)
    window.undo()

    mouse(window, QEvent.Type.MouseButtonPress, (4, 6), Qt.RightButton)
    application.processEvents()
    expect("right-click deleted it",
           len(session.project.map("test").object_layer("entity").objects()), 0)
    window.undo()
    window.undo()
    expect("and everything unwound byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("a rejected edit is reported, not raised")
    # ----------------------------------------------------------------
    warned.clear()
    ok = window.run(Command("map.tile.set", Scope.parse("map:test/layer:Floor"),
                            {"x": 99999, "y": 0, "gid": 1}))
    expect("run() reported failure instead of throwing", ok, False)
    expect("the user was shown why", len(warned), 1)
    expect("nothing entered the history", len(session.history()), 0)
    expect("and the file is untouched",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("the database is a real window, generated from the genre")
    # ----------------------------------------------------------------
    window.open_database()
    application.processEvents()
    expect("it has a tab per declared table",
           sorted(window.database.pages), ["actors", "equipment", "items"])
    page = window.database.pages["actors"]
    expect("an uncreated table says so", page.exists, False)

    # Reported from a real run: "the database + buttons don't do anything."
    # They early-returned when the table did not exist -- which on a fresh
    # project is always -- so all three were dead clicks with no feedback.
    # A button that cannot act must LOOK like it cannot act.
    expect("+ is disabled before the table exists",
           page.add_button.isEnabled(), False)
    expect("and its tooltip says why",
           "create the actors table first" in page.add_button.toolTip(), True)
    expect("Duplicate is disabled too", page.duplicate_button.isEnabled(), False)
    expect("and remove", page.remove_button.isEnabled(), False)

    page._TablePage__on_create()
    application.processEvents()
    expect("creating it worked", session.project.has_table("actors"), True)
    expect("+ is live once the table exists", page.add_button.isEnabled(), True)
    expect("but Duplicate still needs a selected row",
           page.duplicate_button.isEnabled(), False)
    expect("and says so",
           "select a row" in page.duplicate_button.toolTip(), True)

    window.run(Command("table.row.add", Scope.of(("table", "actors")),
                       {"id": "hero", "values": {"display_name": "Hero"}}))
    window.database.refresh()
    application.processEvents()
    expect("the row appears in the list", page.list.count(), 1)
    expect("and the detail form is showing it",
           page.view.inspection.heading, "hero")
    expect("Duplicate and remove came alive with a selection",
           (page.duplicate_button.isEnabled(), page.remove_button.isEnabled()),
           (True, True))

    row_fields = {f.key: f for section in page.view.inspection.sections
                  for f in section.fields}
    expect("every genre column is a field", len(row_fields), 8)
    window.run(row_fields["hp"].emit(42))
    expect("editing a field changed the row",
           session.project.table("actors").rows["hero"]["hp"], 42)
    window.undo()
    expect("and it undoes",
           session.project.table("actors").rows["hero"]["hp"], 10)

    # ----------------------------------------------------------------
    print()
    print("prompt strips carry their own panel's scope")
    # ----------------------------------------------------------------
    select_layer(window, "Floor")
    window.hierarchy.strip.field.setText("this layer needs a market square")
    window.hierarchy.strip.stage()
    window.problems.strip.field.setText("what should happen on a bad map?")
    window.problems.strip.kind.setCurrentText("question")
    window.problems.strip.stage()
    application.processEvents()
    expect("two notes staged", len(session.manifest.notes), 2)
    expect("each on its own panel's scope",
           sorted(str(n.scope) for n in session.manifest.notes),
           ["map:test/layer:Floor", "project"])
    expect("and their kinds survived",
           sorted(n.kind for n in session.manifest.notes),
           ["change", "question"])

    # ----------------------------------------------------------------
    print()
    print("shipping and applying a response use the same door")
    # ----------------------------------------------------------------
    bundle = session.ship(title="ui smoke")
    window.refresh_manifest()
    expect("the bundle exists", os.path.isdir(bundle.directory), True)
    with open(bundle.response_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({
            "verb": "table.row.set", "scope": "table:actors/row:hero",
            "args": {"column": "hp", "value": 55}}) + "\n")
    window.apply_response(bundle.response_path)
    application.processEvents()
    expect("the response applied",
           session.project.table("actors").rows["hero"]["hp"], 55)
    expect("recorded as coming from a response",
           session.history()[-1].source, f"response:{bundle.identifier}")
    window.undo()

    # ----------------------------------------------------------------
    print()
    print("revealing code never raises, even with no IDE")
    # ----------------------------------------------------------------
    from editor.core import ide

    real_detect, real_open = ide.detect, ide.open_at
    try:
        ide.detect = lambda **k: []
        ide.open_at = lambda *a, **k: ide.LaunchResult(False, "no IDE (test)")
        window.reveal("main.py")
        window.reveal("scripts/core/component.py", symbol="GameComponent")
        print("  ok   reveal() with no IDE installed did not raise")
    except Exception as exc:                                    # noqa: BLE001
        print(f"  FAIL reveal() raised {type(exc).__name__}: {exc}")
        failures.append("reveal")
    finally:
        ide.detect, ide.open_at = real_detect, real_open

    expect("a symbol's line is found without importing it",
           ide.find_symbol_line(
               os.path.join(REPO, "scripts", "core", "component.py"),
               "GameComponent") is not None, True)

    # ----------------------------------------------------------------
    print()
    print("refreshing never orphans a widget into a top-level window")
    # ----------------------------------------------------------------
    # Reported from a real run: Ctrl+Z made "like 20 miniature windows"
    # appear and disappear. Cause was `widget.setParent(None)` while
    # clearing the inspector's layout -- in Qt that does not detach a widget,
    # it PROMOTES it to a top-level window, and `deleteLater()` only runs
    # once the event loop unwinds, so the orphans both flashed and
    # accumulated. Measured before the fix: 59 top-level widgets at rest,
    # 85 after one undo, and still 85 afterwards.
    #
    # Counting top-levels is the cheapest way to make that impossible to
    # reintroduce, and it catches the same mistake in any panel.
    def top_levels():
        return len([w for w in QApplication.topLevelWidgets()
                    if w is not window and w.parent() is None])

    window.selection.select(Scope.of(("map", "test"), ("layer", "Floor")))
    window.run(Command("map.tile.set", Scope.parse("map:test/layer:Floor"),
                       {"x": 1, "y": 1, "gid": 70}))
    application.processEvents()
    settled = top_levels()

    peak = settled
    import editor.ui.fields as fields_module
    original_show = fields_module.InspectionView.show_inspection

    def watched(self, inspection):
        # `global`, not `nonlocal`: this file is a script, so `peak` lives at
        # module scope and there is no enclosing function to bind to.
        global peak
        original_show(self, inspection)
        peak = max(peak, top_levels())

    fields_module.InspectionView.show_inspection = watched
    try:
        for _ in range(12):
            window.undo()
            application.processEvents()
            window.redo()
            application.processEvents()
    finally:
        fields_module.InspectionView.show_inspection = original_show

    expect("no orphan appears mid-rebuild", peak <= settled, True)
    expect("and none accumulate over 12 undo/redo cycles",
           top_levels() <= settled, True)
    window.undo()

    # ----------------------------------------------------------------
    print()
    print("a field never outlives its own signal (heap-corruption guard)")
    # ----------------------------------------------------------------
    # Reported from a real run as exit code 0xC0000374,
    # STATUS_HEAP_CORRUPTION, after toggling a layer capability. The fix for
    # the orphan-window bug above replaced the inspector body with
    # setWidget(), which DELETES the old one synchronously -- so toggling a
    # checkbox emitted a command, which refreshed, which freed that very
    # checkbox while its `toggled` signal was still on the stack. Qt then
    # returned into freed memory.
    #
    # Deferring the free with deleteLater() is the fix; this asserts it, and
    # asserts the two are compatible, since the naive cure for either one is
    # the cause of the other.
    from PySide6.QtWidgets import QCheckBox                       # noqa: E402

    window.selection.select(Scope.of(("map", "test"), ("layer", "Floor")))
    application.processEvents()
    boxes = window.inspector.view.findChildren(QCheckBox)
    expect("the layer inspector offers boolean capabilities",
           len(boxes) > 0, True)

    box = boxes[-1]
    destroyed_synchronously = []
    box.destroyed.connect(lambda *_a: destroyed_synchronously.append(1))
    box.setChecked(not box.isChecked())
    still_alive = True
    try:
        box.isChecked()
    except RuntimeError:
        still_alive = False
    expect("the widget survives emitting its own command", still_alive, True)
    expect("its destruction was deferred, not synchronous",
           destroyed_synchronously, [])
    application.processEvents()
    expect("the command still landed",
           "pyoneer_" in "".join(session.project.map("test")
                                 .tile_layer("Floor").properties.keys()), True)
    window.undo()
    application.processEvents()
    expect("and undoing it leaves the map byte-identical",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("settings are typed, validated, and survive a round trip")
    # ----------------------------------------------------------------
    from editor.core.settings import SETTINGS, EditorSettings      # noqa: E402

    class FakeStore:
        """Stands in for QSettings, and returns everything as TEXT the way
        the ini backend does -- which is exactly how a boolean preference
        silently stops working if nothing coerces it."""

        def __init__(self):
            self.data = {}

        def value(self, key, default=None):
            return self.data.get(key, default)

        def setValue(self, key, value):
            self.data[key] = str(value)

        def remove(self, key):
            self.data.pop(key, None)

    store = EditorSettings(FakeStore())
    expect("defaults come back typed",
           [type(store.get(s.key)).__name__ for s in SETTINGS],
           ["str", "str", "bool", "bool"])
    store.set("show_grid", False)
    expect("a bool survives a text backend", store.get("show_grid"), False)
    store.set("show_grid", True)
    expect("and back again", store.get("show_grid"), True)
    store.set("theme", "dark")
    expect("a choice round-trips", store.get("theme"), "dark")
    store.set("theme", "banana")
    expect("a value outside the choices falls back to the default",
           store.get("theme"), "system")
    store.reset()
    expect("reset restores every default", store.as_dict()["show_grid"], True)

    try:
        store.get("nonexistent")
        expect("an unknown setting is refused", False, True)
    except KeyError:
        print("  ok   an unknown setting raises rather than returning None")

    # ----------------------------------------------------------------
    print()
    print("switching theme repaints the window AND re-inks the icons")
    # ----------------------------------------------------------------
    from PySide6.QtGui import QPalette                             # noqa: E402
    from editor.ui import icons as icons_module                    # noqa: E402
    from editor.ui.theme import Theme                              # noqa: E402

    def ink_of(icon):
        """Sample the drawn glyph so a theme change is measured, not assumed."""
        image = icon.pixmap(22, 22).toImage()
        total, count = 0, 0
        for y in range(image.height()):
            for x in range(image.width()):
                pixel = image.pixelColor(x, y)
                if pixel.alpha() > 200:
                    total += pixel.lightness()
                    count += 1
        return total / count if count else -1

    window.apply_theme(Theme.LIGHT)
    application.processEvents()
    light_window = application.palette().color(QPalette.Window).lightness()
    light_ink = ink_of(icons_module.tool_icon("brush"))

    window.apply_theme(Theme.DARK)
    application.processEvents()
    dark_window = application.palette().color(QPalette.Window).lightness()
    dark_ink = ink_of(icons_module.tool_icon("brush"))

    expect("the window palette actually darkened", dark_window < light_window,
           True)
    # This is the bug that prompted the whole thing: icons were a hardcoded
    # near-white, invisible on the author's light theme. Ink must move the
    # OPPOSITE way to the background or the glyphs vanish on one of them.
    expect("and the icon ink moved the other way", dark_ink > light_ink, True)
    expect("dark mode uses a style that honours the palette",
           application.style().objectName(), "fusion")

    window.apply_theme(Theme.LIGHT)
    application.processEvents()
    expect("every tool still has a non-null icon",
           [t.value for t in Tool
            if icons_module.tool_icon(t.value).isNull()], [])

    # ----------------------------------------------------------------
    print()
    print("one broken panel does not take the window down")
    # ----------------------------------------------------------------
    def explode():
        raise RuntimeError("panel is unhappy")

    original = window.problems.refresh
    window.problems.refresh = explode
    try:
        window.refresh_all()
        print("  ok   refresh_all survived a panel that raised")
    except Exception as exc:                                    # noqa: BLE001
        print(f"  FAIL refresh_all propagated {type(exc).__name__}")
        failures.append("panel isolation")
    finally:
        window.problems.refresh = original

    window.close()

finally:
    shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
