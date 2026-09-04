"""The hierarchy tree as a CONTROL: double-click, right-click, cut/copy/paste.

WHAT THIS IS FOR
----------------
The tree listed the map and did nothing else. Selecting a row was the only
gesture it had, so the author's two sentences -- "double clicking on the
already existing entity on the tree should focus on it" and "right clicking
on the entity in the tree should bring up; select, focus, edit, cut, copy,
paste" -- describe a panel that was a read-out pretending to be a control.

Three failure shapes, none of which raises anywhere:

  * A MENU THAT BLOCKS. `QMenu.exec` spins its own event loop and does not
    return until the menu closes, which is a modal by every definition law
    13 cares about -- the shape that once sat on this suite for 40+ minutes
    with zero output. So the seam is driven BOTH ways here: stubbed, to
    read the menu a real right-click built, and unstubbed with a watchdog,
    to prove the shipping call comes back with the menu still on screen.

  * A CONTROL THAT IS PRESENT AND REFUSES. An entry that cannot act has
    already spent the author's click by the time the refusal arrives, so
    every entry is asserted in BOTH directions -- live with its reason
    absent, and greyed with its reason in its own label.

  * A PASTE THAT LOOKS LIKE NOTHING HAPPENED. A duplicate at its source's
    own coordinates draws underneath it; a duplicate carrying its source's
    id lands on whatever object recycled that id; a duplicate quietly
    stripped of an unknown behavior token looks authored and does nothing.
    All three are asserted, and each with the half that would pass if the
    feature were absent as well as the half that would pass if it worked.

  * A MENU THAT ACTS ON A DIFFERENT OBJECT. The row is an ADDRESS and ids
    are RECYCLED, so every "does it still resolve" test in the panel passes
    for an id that now names somebody else -- and `popup` returns with the
    menu still on screen, so the document is free to change underneath it.
    Measured before the fix: the canvas refused the identical stale address
    and the tree deleted. Both directions are driven here, and the race is
    driven through the SHIPPING opener rather than a helper, because it was
    the absence of that assertion that let this ship.

ITS OWN FIXTURE, NEVER data/maps/starter.tmx (law 4). Two maps in a temporary
workspace -- one to work on and one to paste ACROSS to -- thrown away at the
end. Two maps, because "cross-map paste is allowed" and "a gid does not
survive the trip" are claims that cannot be made with one.

Skips cleanly when PySide6 is not installed.
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

from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt        # noqa: E402
from PySide6.QtGui import QColor, QImage, QMouseEvent                 # noqa: E402
from PySide6.QtWidgets import (                                       # noqa: E402
    QApplication,
    QMenu,
    QMessageBox,
    QTreeWidgetItemIterator,
)

from editor.core.commands import Command                              # noqa: E402
from editor.core.scope import Scope                                   # noqa: E402
from editor.core.session import Session                               # noqa: E402
from scripts.game.behavior.base import BEHAVIORS                      # noqa: E402
import editor.ui.canvas as canvas_module                              # noqa: E402
import editor.ui.hierarchy as hierarchy_module                        # noqa: E402
from editor.ui.hierarchy import HierarchyDock, ObjectClipping         # noqa: E402
import editor.ui.main_window as main_window_module                    # noqa: E402
from editor.ui.main_window import EditorWindow                        # noqa: E402

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} got={got} want={want}")
    if not ok:
        failures.append(label)


# RECORD every modal rather than merely silencing it. Silencing proves
# nothing in either direction: a box that opens is invisible to the suite,
# and so is a box that stops opening. `modals()` is the instrument behind
# "this gesture asked nothing", which is the stronger of the two claims.
opened_boxes: list[str] = []


def _record(answer=None):
    def stub(*a, **k):
        opened_boxes.append(str(a[2]) if len(a) > 2 else "")
        return answer
    return staticmethod(stub)


QMessageBox.warning = _record()
QMessageBox.critical = _record()
QMessageBox.information = _record()
QMessageBox.question = _record(QMessageBox.Yes)


def modals() -> list[str]:
    return list(opened_boxes)


def no_modals() -> None:
    opened_boxes.clear()


class FakeLayout:
    """The window's dock layout store. Stubbed for check_palette's two
    reasons: a real QSettings would rewrite the developer's own panel
    arrangement on the way out, and would read it back on the way in, making
    every geometry-dependent assertion below depend on how he last dragged a
    dock."""

    def __init__(self):
        self.data = {}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value


LAYOUTS = FakeLayout()
main_window_module.layout_store = lambda: LAYOUTS

application = QApplication.instance() or QApplication([])

# --------------------------------------------------------------------------
# The fixture
# --------------------------------------------------------------------------
# Two maps, five objects between them, and every object exists to make one
# assertion possible in BOTH directions:
#
#   hero    a full clipping -- a behavior list, a parameter and a property
#           the engine has never heard of. Its paste must be identical.
#   bad     carries a behavior token no registry entry answers, which is the
#           paste that MUST be refused by name (law 8).
#   tiled   carries a gid, which is a number in ITS map's tilesets and in no
#           other, and is the paste that must be refused across maps.
#   plain   carries nothing, so the genre pack's starting list materialises
#           onto its copy -- the one difference between a source and its
#           paste, and it has to be reported rather than silent.
#
# `plain` lives on the SECOND map so that neither map holds two GamePlayers
# before this file starts pasting: the pack declares GamePlayer unique per
# layer, and a fixture that opens with a rule violation makes every later
# reading of the Problems dock ambiguous.

TILE = 16


def paint_sheet(path: str, columns: int, rows: int) -> None:
    """A flat-coloured grid, so a map that draws has something to draw."""
    image = QImage(columns * TILE, rows * TILE, QImage.Format_ARGB32)
    image.fill(QColor(20, 20, 20))
    for row in range(rows):
        for column in range(columns):
            index = row * columns + column
            colour = QColor((index * 61) % 256, (index * 113 + 30) % 256,
                            (index * 37 + 80) % 256)
            for x in range(column * TILE, (column + 1) * TILE):
                for y in range(row * TILE, (row + 1) * TILE):
                    image.setPixelColor(x, y, colour)
    if not image.save(path, "PNG"):
        raise OSError(f"could not write the fixture sheet {path}")


FIXTURE_TMX = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" width="6" height="5" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="4" nextobjectid="4">
 <tileset firstgid="1" name="Alpha" tilewidth="16" tileheight="16" \
tilecount="4" columns="2">
  <image source="sheets/alpha.png" width="32" height="32"/>
 </tileset>
 <layer id="1" name="Floor" width="6" height="5">
  <data encoding="csv">
1,2,3,4,1,2,
0,0,0,0,0,0,
0,0,0,0,0,0,
0,0,0,0,0,0,
0,0,0,0,0,0
</data>
 </layer>
 <objectgroup id="2" name="entity">
  <object id="1" name="hero" type="GamePlayer" x="32" y="48" width="16" \
height="16">
   <properties>
    <property name="loot" value="potion"/>
    <property name="pyoneer_behaviors" \
value="player_input,topdown_move,animation_drive"/>
    <property name="pyoneer_param_walk_speed" type="int" value="3"/>
   </properties>
  </object>
  <object id="2" name="bad" type="Chest" x="64" y="32">
   <properties>
    <property name="pyoneer_behaviors" value="not_a_real_behavior"/>
   </properties>
  </object>
  <object id="3" name="tiled" type="Chest" gid="2" x="16" y="64" width="16" \
height="16"/>
 </objectgroup>
</map>
"""

OTHER_TMX = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" width="4" height="4" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="4" nextobjectid="2">
 <tileset firstgid="1" name="Beta" tilewidth="16" tileheight="16" \
tilecount="4" columns="2">
  <image source="sheets/beta.png" width="32" height="32"/>
 </tileset>
 <layer id="1" name="Floor" width="4" height="4">
  <data encoding="csv">
1,2,3,4,
0,0,0,0,
0,0,0,0,
0,0,0,0
</data>
 </layer>
 <objectgroup id="2" name="entity">
  <object id="1" name="plain" type="GamePlayer" x="16" y="16" width="16" \
height="16"/>
 </objectgroup>
</map>
"""


def build_workspace() -> str:
    root = tempfile.mkdtemp(prefix="pyoneer-hierarchy-")
    maps = os.path.join(root, "data", "maps")
    sheets = os.path.join(maps, "sheets")
    os.makedirs(sheets)
    os.makedirs(os.path.join(root, "config"))
    paint_sheet(os.path.join(sheets, "alpha.png"), 2, 2)
    paint_sheet(os.path.join(sheets, "beta.png"), 2, 2)
    for name, body in (("fixture", FIXTURE_TMX), ("other", OTHER_TMX)):
        with open(os.path.join(maps, f"{name}.tmx"), "w", encoding="utf-8",
                  newline="") as handle:
            handle.write(body)
    with open(os.path.join(root, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [
            {"name": "fixture", "identifier": "fixture",
             "file": "data/maps/fixture.tmx"},
            {"name": "other", "identifier": "other",
             "file": "data/maps/other.tmx"}]}, handle)
    return root


def ascii_fold(text: str) -> str:
    """The typography out, so a failure can be printed on any console."""
    for fancy, plain in (("·", "."), ("—", "-"), ("–", "-"), ("…", "...")):
        text = text.replace(fancy, plain)
    return " ".join(text.split())


workspace = build_workspace()
try:
    session = Session.open(workspace, genre_id="topdown_rpg")
    FIXTURE_BYTES = session.project.map("fixture").to_bytes()
    OTHER_BYTES = session.project.map("other").to_bytes()
    window = EditorWindow(session)
    # Big enough that the tree has real rows to point at. Every hit test
    # below is a coordinate, and a dock squeezed to three rows would make
    # "the author pointed here" a fact about this machine's default window
    # size rather than about the panel.
    window.resize(1500, 1100)
    window.show()
    application.processEvents()
    hierarchy = window.hierarchy
    tree = hierarchy.tree

    HERO = "map:fixture/layer:entity/object:1"
    BAD = "map:fixture/layer:entity/object:2"
    TILED = "map:fixture/layer:entity/object:3"
    ENTITY = "map:fixture/layer:entity"
    FLOOR = "map:fixture/layer:Floor"

    # -- driving the tree the way a hand does ------------------------------

    def item_for(address: str):
        iterator = QTreeWidgetItemIterator(tree)
        while iterator.value():
            if iterator.value().data(0, Qt.UserRole) == address:
                return iterator.value()
            iterator += 1
        return None

    def point_of(address: str) -> QPoint:
        """The centre of a row, in the VIEWPORT coordinates every hit test
        below is written in.

        Scrolls to it first, the way a hand does. A row that is off screen
        has a rect outside the viewport, and a point taken from it names no
        row at all -- which would make every menu assertion below pass or
        fail on where the tree happened to be scrolled.
        """
        item = item_for(address)
        if item is None:
            raise AssertionError(f"the tree has no row for {address}")
        tree.scrollToItem(item)
        application.processEvents()
        rect = tree.visualItemRect(item)
        if not rect.isValid() or rect.top() < 0:
            raise AssertionError(f"the row for {address} is not on screen")
        return rect.center()

    def tree_mouse(address: str, kind, button=Qt.LeftButton) -> None:
        point = QPointF(point_of(address))
        down = Qt.NoButton if kind == QEvent.Type.MouseButtonRelease else button
        event = QMouseEvent(kind, point, button, down, Qt.NoModifier)
        {QEvent.Type.MouseButtonPress: tree.mousePressEvent,
         QEvent.Type.MouseButtonRelease: tree.mouseReleaseEvent,
         QEvent.Type.MouseButtonDblClick: tree.mouseDoubleClickEvent}[kind](
             event)
        application.processEvents()

    def single_click(address: str) -> None:
        tree_mouse(address, QEvent.Type.MouseButtonPress)
        tree_mouse(address, QEvent.Type.MouseButtonRelease)

    def double_click(address: str) -> None:
        # Qt's own order, and the reason the single-click path is asserted
        # first: a double-click arrives as press, release, DoubleClick, so
        # anything the single click does happens on the way to every one.
        single_click(address)
        tree_mouse(address, QEvent.Type.MouseButtonDblClick)

    def labels(menu) -> list[str]:
        return [ascii_fold(action.text()) for action in menu.actions()]

    def entry(menu, text: str):
        for action in menu.actions():
            if ascii_fold(action.text()).startswith(text):
                return action
        raise AssertionError(f"no {text!r} entry in {labels(menu)}")

    def objects(map_name="fixture", layer="entity"):
        return session.project.map(map_name).object_layer(layer).objects()

    def ids(map_name="fixture", layer="entity"):
        return [obj.id for obj in objects(map_name, layer)]

    def by_id(object_id, map_name="fixture", layer="entity"):
        for obj in objects(map_name, layer):
            if obj.id == object_id:
                return obj
        return None

    # THE MENU SEAM, replaced on the one widget being driven. A real
    # `QMenu.exec` would sit here until the 600s timeout (law 13); the
    # unstubbed opener is driven once, on purpose, near the end.
    popped: list = []
    hierarchy.popup_menu = lambda menu, at: popped.append(menu)
    #: Qt wrappers this file must not let go of. A QMenu whose only
    #: reference is a Python temporary is collected while its QActions are
    #: still being read, and the read comes back as a crash rather than a
    #: failure.
    held: list = []

    def right_click(address: str) -> list:
        popped.clear()
        hierarchy.open_object_menu(point_of(address))
        held.extend(popped)
        return list(popped)

    # ----------------------------------------------------------------
    print("the hit test answers the row that was pointed at, or nothing")
    # ----------------------------------------------------------------
    expect("an object row carries its own object scope",
           str(hierarchy.row_scope(point_of(HERO))), HERO)
    expect("...a layer row carries the layer's",
           str(hierarchy.row_scope(point_of(ENTITY))), ENTITY)
    # THE SILENT HALF. A hit test that clamped -- as `TilePalette.locate`
    # does, deliberately, for a drag that strays -- would answer with the
    # nearest row for a point over nothing, and the menu would act on an
    # object the author never pointed at.
    last = item_for(TILED)
    tree.scrollToItem(last)
    application.processEvents()
    below = QPoint(4, tree.visualItemRect(last).bottom() + 12)
    expect("...and a point past the last row is no row at all",
           (hierarchy.row_scope(below), tree.itemAt(below)),
           (None, None))

    # ----------------------------------------------------------------
    print()
    print("a single click selects, and ONLY selects")
    # ----------------------------------------------------------------
    focused: list[str] = []

    class NoFocusCanvas:
        """A canvas from before the centring method existed. Held for one
        assertion and put back immediately."""

    # THE REFUSAL FIRST, and asserted by REMOVING the method rather than by
    # relying on its absence: `MapCanvas.focus_object` is being added in a
    # sibling file, and a check that proved the greyed half only while the
    # tree happened to lack it would go red the hour it lands -- for a panel
    # that had got better, which is the worst kind of red.
    real_canvas, window.canvas = window.canvas, NoFocusCanvas()
    expect("with no canvas focus_object, Focus refuses AND NAMES IT",
           "focus_object(scope)" in hierarchy.focus_refusal(Scope.parse(HERO)),
           True)
    expect("...the call refuses too, so a script cannot get past the greying",
           (hierarchy.focus_object(Scope.parse(HERO)),
            "focus_object(scope)" in hierarchy.last_notice), (False, True))
    window.canvas = real_canvas

    # THE OTHER HALF: with the contract's method in place, the tree calls it
    # -- as `self.window().canvas.focus_object(scope)` and nothing else.
    def fake_focus(scope) -> bool:
        focused.append(str(scope))
        return True

    window.canvas.focus_object = fake_focus
    expect("...and with one in place, Focus has no refusal left",
           hierarchy.focus_refusal(Scope.parse(HERO)), "")

    no_modals()
    focused.clear()
    window.selection.select(Scope.parse(FLOOR))
    single_click(HERO)
    expect("a single click on an object row selects it",
           (str(window.selection.scope), str(hierarchy.scope)), (HERO, HERO))
    expect("...AND MOVES NO CAMERA, opens no dialog and writes nothing",
           (focused, modals(), len(session.history())), ([], [], 0))

    # ----------------------------------------------------------------
    print()
    print("a double click on an object row focuses the canvas on it")
    # ----------------------------------------------------------------
    focused.clear()
    window.selection.select(Scope.parse(FLOOR))
    double_click(HERO)
    expect("the double click reached the canvas' focus_object, with the "
           "object's own scope", focused, [HERO])
    expect("...and it still selected, and still wrote nothing",
           (str(window.selection.scope), len(session.history()), modals()),
           (HERO, 0, []))

    # BOTH HALVES OF "an object row". A layer row is not one, and a
    # double-click there has to say what the gesture is for rather than
    # centring on whatever the layer's first object happens to be.
    focused.clear()
    double_click(ENTITY)
    expect("double-clicking a LAYER row centres nothing and says why",
           (focused, "double-click an object" in hierarchy.last_notice),
           ([], True))

    # -- THE REAL CANVAS METHOD, DRIVEN. NOT A STUB. -------------------
    # The recorder above proves the tree calls
    # `self.window().canvas.focus_object(scope)` and nothing else, which is
    # the contract -- and proves nothing about the far end. This drops the
    # instance attribute so the shipping method answers, and drives the
    # same double-click into it.
    del window.canvas.focus_object
    # Parked on a SIBLING object rather than on a layer: the window routes a
    # selection whose layer changed through `set_active_layer` instead of
    # `set_selection`, so starting on another layer would leave the canvas
    # card behind for a reason that has nothing to do with this gesture.
    window.selection.select(Scope.parse(BAD))
    application.processEvents()
    expect("the canvas is holding a different object first",
           str(window.canvas.selected_scope), BAD)
    double_click(HERO)
    expect("a double click reaches the REAL focus_object, and the canvas "
           "comes back holding the object",
           (str(window.canvas.selected_scope), str(window.selection.scope)),
           (HERO, HERO))
    # THE OTHER HALF, asked of the real method directly: an id the layer
    # does not hold answers False rather than scrolling somewhere and
    # claiming the object is there.
    expect("...while the same call for an id this map has not answers False",
           window.canvas.focus_object(
               Scope.parse("map:fixture/layer:entity/object:404")), False)
    window.canvas.focus_object = fake_focus

    # A canvas that cannot find the object answers False, and that answer
    # has to reach the author: a Focus that silently did nothing is the
    # same defect as a Focus that was never wired.
    window.canvas.focus_object = lambda scope: False
    expect("a canvas that resolves nothing is reported, not swallowed",
           (hierarchy.focus_object(Scope.parse(HERO)),
            "resolves to nothing" in hierarchy.last_notice), (False, True))
    window.canvas.focus_object = fake_focus

    # ----------------------------------------------------------------
    print()
    print("right-click opens a menu, on the two rows that have one")
    # ----------------------------------------------------------------
    HierarchyDock._clipboard = None
    HierarchyDock._paste_step = 0
    no_modals()
    menus = right_click(HERO)
    expect("an object row opens exactly one menu, of the seven verbs asked "
           "for", [[label.split(" . ")[0] for label in labels(menu)]
                   for menu in menus],
           [["Select", "Focus", "Edit...", "Cut", "Copy", "Paste", "Delete"]])
    expect("...and opened no dialog doing it (law 13)", modals(), [])

    # A LAYER ROW STILL OPENS ONE, and that is not a nicety: after a cut the
    # row the object was on is gone, so a menu that only ever opened over an
    # object would be a clipboard with nowhere to empty.
    layer_menu = right_click(ENTITY)[0]
    expect("an object LAYER row opens the same menu",
           [label.split(" . ")[0] for label in labels(layer_menu)],
           ["Select", "Focus", "Edit...", "Cut", "Copy", "Paste", "Delete"])
    expect("...with every object entry greyed AND carrying the reason",
           [(entry(layer_menu, name).isEnabled(),
             ascii_fold(entry(layer_menu, name).text()))
            for name in ("Edit", "Cut", "Copy", "Delete")],
           [(False, f"{name} . the 'entity' layer is not an object")
            for name in ("Edit...", "Cut", "Copy", "Delete")])

    # AND NOTHING OPENS ANYWHERE ELSE. A menu with every entry greyed is a
    # control that tells the author they missed without telling them what
    # they missed, so a tile layer, a group and empty space open nothing.
    expect("a tile layer row opens no menu at all, and says what to aim at",
           (right_click(FLOOR),
            "right-click an object" in hierarchy.last_notice), ([], True))
    popped.clear()
    tree.scrollToItem(item_for(TILED))
    application.processEvents()
    hierarchy.open_object_menu(
        QPoint(4, tree.visualItemRect(item_for(TILED)).bottom() + 12))
    expect("...and neither does the space past the last row", popped, [])

    # ----------------------------------------------------------------
    print()
    print("Select from the menu is the same selection a click makes")
    # ----------------------------------------------------------------
    window.selection.select(Scope.parse(FLOOR))
    menu = right_click(HERO)[0]
    entry(menu, "Select").trigger()
    application.processEvents()
    expect("Select points the whole editor at the row",
           (str(window.selection.scope), str(hierarchy.scope)), (HERO, HERO))
    expect("...and moves the tree's own cursor there too, so the row the "
           "author acted on is the row that is lit",
           tree.currentItem().data(0, Qt.UserRole), HERO)
    expect("...having written nothing", (len(session.history()), modals()),
           (0, []))

    # Edit goes through the window's ONE door, which is already the far end
    # of the canvas's double-click. Asserted by what it opens, not by a stub:
    # a second route to that window is the thing the contract forbids.
    entry(right_click(HERO)[0], "Edit").trigger()
    application.processEvents()
    expect("Edit opens the window's entity editor, aimed at this object",
           (window.object_editor is not None,
            str(window.object_editor.scope) if window.object_editor else None),
           (True, HERO))
    window.object_editor.close()
    application.processEvents()

    # ----------------------------------------------------------------
    print()
    print("copy and paste: the same object, a new id, somewhere visible")
    # ----------------------------------------------------------------
    hero_before = by_id(1).properties.as_dict()
    expect("the source carries a behavior list, a parameter and a property "
           "the engine never heard of",
           sorted(hero_before), ["loot", "pyoneer_behaviors",
                                 "pyoneer_param_walk_speed"])

    entry(right_click(HERO)[0], "Copy").trigger()
    application.processEvents()
    clip = HierarchyDock._clipboard
    expect("Copy takes a clipping and writes nothing at all",
           (isinstance(clip, ObjectClipping), len(session.history()),
            ids()), (True, 0, [1, 2, 3]))
    # THE ID IS THE FIELD THAT MUST NOT TRAVEL. Ids are recycled here --
    # `_release_object_id` rolls `nextobjectid` back so add-then-remove is
    # byte-exact -- so a clipping that carried one would paste onto whatever
    # object was handed that id in the meantime.
    expect("...and the clipping has no id field to carry",
           "id" in {f for f in ObjectClipping.__dataclass_fields__}, False)
    expect("...it carries the authored data instead",
           (clip.type, clip.name, clip.x, clip.y, clip.width, clip.height,
            clip.gid, dict(clip.properties) == hero_before),
           ("GamePlayer", "hero", 32.0, 48.0, 16.0, 16.0, 0, True))

    # WHERE IT LANDS, asserted as arithmetic before it is asserted as an
    # object: one tile down and right per paste, wrapped so it can neither
    # leave the map nor stack on the edge.
    document = session.project.map("fixture")
    expect("a paste steps one tile down and right of its source",
           HierarchyDock.paste_position(clip, document, 1), (48.0, 64.0))
    expect("...and the next one steps again rather than repeating",
           HierarchyDock.paste_position(clip, document, 2), (64.0, 0.0))
    expect("...never onto the source's own coordinates, which is the whole "
           "point", HierarchyDock.paste_position(clip, document, 1)
           == (clip.x, clip.y), False)

    no_modals()
    entry(right_click(HERO)[0], "Paste").trigger()
    application.processEvents()
    fresh = [i for i in ids() if i not in (1, 2, 3)]
    expect("Paste adds exactly one object, in ONE undo step",
           (len(fresh), len(session.history()),
            [len(t.commands) for t in session.history()]), (1, 1, [1]))
    made = by_id(fresh[0])
    expect("...with the SAME properties as its source",
           made.properties.as_dict(), hero_before)
    expect("...and a DIFFERENT id, at a DIFFERENT position",
           (made.id != 1, (made.x, made.y) != (32.0, 48.0),
            (made.x, made.y)), (True, True, (48.0, 64.0)))
    expect("...carrying the type, name and size over with it",
           (made.type, made.name, made.width, made.height),
           ("GamePlayer", "hero", 16.0, 16.0))
    expect("...selected, so the author can see which one is new",
           str(window.selection.scope),
           f"map:fixture/layer:entity/object:{made.id}")
    expect("...and reported, opening nothing",
           (f"#{made.id}" in hierarchy.last_notice, modals()), (True, []))

    second = len(ids())
    entry(right_click(ENTITY)[0], "Paste").trigger()
    application.processEvents()
    twice = [obj for obj in objects() if obj.id not in (1, 2, 3, made.id)]
    expect("a second paste lands somewhere else again, not on the first",
           (len(ids()) == second + 1, len(twice) == 1,
            (twice[0].x, twice[0].y)), (True, True, (64.0, 0.0)))

    while session.stream.can_undo:
        window.undo()
    application.processEvents()
    expect("...and both undo away, byte for byte",
           (session.project.map("fixture").to_bytes() == FIXTURE_BYTES,
            ids()), (True, [1, 2, 3]))

    # ----------------------------------------------------------------
    print()
    print("cut is copy plus remove, in ONE undo step")
    # ----------------------------------------------------------------
    no_modals()
    HierarchyDock._clipboard = None
    depth = len(session.history())
    entry(right_click(HERO)[0], "Cut").trigger()
    application.processEvents()
    expect("Cut takes the object off the map and onto the clipboard",
           (ids(), HierarchyDock._clipboard.label), ([2, 3], "hero (GamePlayer)"))
    expect("...as ONE transaction of ONE command, not two of one",
           (len(session.history()) - depth,
            [c.verb for c in session.history()[-1].commands]),
           (1, ["map.object.remove"]))
    # THE SELECTION HAS TO GO SOMEWHERE THAT RESOLVES. Left on the object it
    # would be an address nothing answers, which every inspector downstream
    # then has to re-derive nothing from.
    expect("...leaving the selection on the layer it came off, not on a "
           "scope that no longer resolves",
           (str(window.selection.scope), hierarchy.row_scope(point_of(ENTITY))
            is not None), (ENTITY, True))
    expect("...and saying so, without a dialog",
           ("Ctrl+Z" in hierarchy.last_notice, modals()), (True, []))

    window.undo()
    application.processEvents()
    expect("ONE Ctrl+Z restores the removal, byte for byte",
           (session.project.map("fixture").to_bytes() == FIXTURE_BYTES,
            ids()), (True, [1, 2, 3]))
    expect("...and the row is back, so the selection can return to it",
           item_for(HERO) is not None, True)

    # A CUT CLIPPING IS STILL A CLIPPING. The whole point of cut is that the
    # object is now in your hand, so pasting it back is the gesture that
    # completes the move -- and it must survive the undo above, which put a
    # second copy of the same object on the map.
    expect("the clipping survives an undo of its own removal",
           HierarchyDock._clipboard is not None, True)

    # ----------------------------------------------------------------
    print()
    print("a paste refuses a behavior token no registry entry answers")
    # ----------------------------------------------------------------
    # `resolve` raises on an unknown token by design (law 8): a token that
    # resolved to nothing would silently disarm the object carrying it and
    # look exactly like the behavior working. A paste that STRIPPED it would
    # produce an object that looks authored and does nothing at all.
    entry(right_click(BAD)[0], "Copy").trigger()
    application.processEvents()
    expect("the bad object copies fine -- copying is not authoring",
           dict(HierarchyDock._clipboard.properties),
           {BEHAVIORS: "not_a_real_behavior"})
    bad_menu = right_click(ENTITY)[0]
    expect("its Paste entry is greyed and NAMES THE TOKEN in its own label",
           (entry(bad_menu, "Paste").isEnabled(),
            "'not_a_real_behavior'" in entry(bad_menu, "Paste").text()),
           (False, True))
    depth, before = len(session.history()), ids()
    expect("...and the call refuses too, naming the token, so a script "
           "cannot get past the greying",
           (hierarchy.paste_object(Scope.parse(ENTITY)),
            "'not_a_real_behavior'" in hierarchy.last_notice,
            len(session.history()), ids()),
           (False, True, depth, before))

    # THE OTHER HALF, and it is the one that makes the refusal an assertion:
    # the SAME row, the same gesture, a clipping whose tokens all resolve.
    entry(right_click(HERO)[0], "Copy").trigger()
    good_menu = right_click(ENTITY)[0]
    expect("a clipping whose every token resolves has no refusal at all",
           (entry(good_menu, "Paste").isEnabled(),
            ascii_fold(entry(good_menu, "Paste").text())), (True, "Paste"))

    # ----------------------------------------------------------------
    print()
    print("a paste is a CREATION too, so a hidden layer refuses it as well")
    # ----------------------------------------------------------------
    # THE SAME HOLE `MapCanvas.__place_object` CLOSED, REACHED BY THE OTHER
    # DOOR. An object pasted onto an unticked layer is not drawn, cannot be
    # clicked, cannot be dragged and cannot be right-clicked, because
    # `__draw_objects` and `objects_under` both skip a hidden layer -- so it
    # is a creation that cannot be walked back by hand.
    #
    # Driven through the AUTHOR'S OWN CONTROL: the tick box on the layer
    # row, whose `visibility_changed` the window wires to
    # `MapCanvas.set_layer_visible`. Reaching into `canvas.hidden_layers`
    # directly would pass just as well for a panel whose tick box had come
    # unwired, which is half the claim gone.
    step_before = HierarchyDock._paste_step
    depth, before = len(session.history()), ids()
    item_for(ENTITY).setCheckState(0, Qt.Unchecked)
    application.processEvents()
    expect("unticking the layer row really hides that layer on the canvas",
           "entity" in window.canvas.hidden_layers, True)
    hidden_menu = right_click(ENTITY)[0]
    hidden_text = ascii_fold(entry(hidden_menu, "Paste").text())
    expect("Paste is greyed, and its own label names the layer AND the way "
           "back",
           (entry(hidden_menu, "Paste").isEnabled(), "'entity'" in hidden_text,
            "switch the layer back on in Layers first" in hidden_text),
           (False, True, True))
    expect("...and the call refuses too, so a script cannot get past the "
           "greying, and NOTHING is created",
           (hierarchy.paste_object(Scope.parse(ENTITY)),
            "hidden" in hierarchy.last_notice,
            len(session.history()), ids(), modals()),
           (False, True, depth, before, []))
    # An OBJECT row on the same hidden layer is the other way the author
    # reaches Paste, and it lands on that same layer. The sentence is
    # written out here rather than derived from the label, so the words the
    # canvas already uses are pinned and not merely echoed.
    HIDDEN_WORDS = ("a paste puts an object on a layer, and 'entity' is "
                    "hidden - switch the layer back on in Layers first")
    expect("...and an object row on that layer refuses it in the same words "
           "the canvas uses",
           (ascii_fold(hierarchy.paste_refusal(Scope.parse(HERO))),
            HIDDEN_WORDS in hidden_text), (HIDDEN_WORDS, True))

    # THE OTHER HALF, and it is what makes the refusal an assertion rather
    # than a panel that cannot paste: the SAME row, the SAME gesture, with
    # the tick put back.
    item_for(ENTITY).setCheckState(0, Qt.Checked)
    application.processEvents()
    live_menu = right_click(ENTITY)[0]
    expect("ticking it back leaves no refusal at all",
           ("entity" in window.canvas.hidden_layers,
            entry(live_menu, "Paste").isEnabled(),
            hierarchy.paste_refusal(Scope.parse(ENTITY))), (False, True, ""))
    entry(live_menu, "Paste").trigger()
    application.processEvents()
    expect("...and the very same gesture adds exactly one object, in ONE "
           "undo step, where the hidden layer added none",
           (len(ids()) - len(before), len(session.history()) - depth), (1, 1))
    window.undo()
    application.processEvents()
    HierarchyDock._paste_step = step_before
    expect("...which undoes away, byte for byte",
           (ids(), session.project.map("fixture").to_bytes() == FIXTURE_BYTES,
            len(session.history())), (before, True, depth))

    # ----------------------------------------------------------------
    print()
    print("across maps: an object travels, a gid does not")
    # ----------------------------------------------------------------
    OTHER_ENTITY = "map:other/layer:entity"
    expect("a gidless clipping is welcome on the other map",
           hierarchy.paste_refusal(Scope.parse(OTHER_ENTITY)), "")
    entry(right_click(TILED)[0], "Copy").trigger()
    application.processEvents()
    expect("...and the same clipping is fine on the map it came from",
           hierarchy.paste_refusal(Scope.parse(ENTITY)), "")
    # A GID IS A NUMBER IN ONE MAP'S TILESETS. `2` is Alpha's second tile
    # here and Beta's second tile there, and nothing raises on the swap: the
    # object draws different art, or none, and looks authored either way.
    refusal = hierarchy.paste_refusal(Scope.parse(OTHER_ENTITY))
    expect("...but a clipping carrying a gid is refused across maps, by "
           "number and by map name",
           ("gid 2" in refusal, "map:fixture" in refusal), (True, True))

    # And the refusal is real, not just a label: switch the window over
    # through the map picker -- the author's own gesture -- and try it.
    window.map_actions["other"].trigger()
    application.processEvents()
    # THE TREE HAS TO SWITCH WITH THE WINDOW. It did not: the panel refused
    # every scope naming another map, which was right while there was only
    # ever one, and became a tree listing rows for a document nobody was
    # looking at the day the map picker landed. Both halves below.
    expect("the window really is on the other map, and so is the tree",
           (window.map_name, hierarchy.scope.get("map")), ("other", "other"))
    expect("...with the other map's rows in it, and none of the first's",
           (item_for("map:other/layer:entity/object:1") is not None,
            item_for(HERO)), (True, None))
    hierarchy.on_selection_changed(Scope.parse(ENTITY))
    expect("...while a scope on a map this window is NOT showing still "
           "cannot drag the tree off the one that is",
           hierarchy.scope.get("map"), "other")
    depth = len(session.history())
    expect("the gid clipping is refused there, and writes nothing",
           (hierarchy.paste_object(Scope.parse(OTHER_ENTITY)),
            "gid 2" in hierarchy.last_notice, len(session.history()),
            ids("other")), (False, True, depth, [1]))

    # A CLIPPING OUTLIVES THE MAP IT CAME FROM. `hero` has no row in this
    # tree any more -- the window is showing the other map -- and the
    # clipboard is not a row: it is the authored data, which is exactly why
    # cross-map paste is possible at all.
    hierarchy.copy_object(Scope.parse(HERO))
    entry(right_click(OTHER_ENTITY)[0], "Paste").trigger()
    application.processEvents()
    expect("...while the gidless one crosses, keeping every property",
           (len(ids("other")),
            by_id(ids("other")[-1], "other").properties.as_dict()),
           (2, hero_before))
    window.undo()
    application.processEvents()
    expect("...and undoes away, byte for byte",
           session.project.map("other").to_bytes() == OTHER_BYTES, True)

    # ----------------------------------------------------------------
    print()
    print("the pack's starting list arrives NAMED, never in silence")
    # ----------------------------------------------------------------
    # `map.object.add` materialises a genre pack's behavior list onto a new
    # object that was given none -- documented precedence, and a paste is an
    # add. It is still a difference between a source and its copy, so the
    # report has to say so: a copy that quietly gained eight behaviors is
    # the shape this repository is built to refuse.
    PLAIN = "map:other/layer:entity/object:1"
    expect("the source on the other map carries no properties at all",
           by_id(1, "other").properties.as_dict(), {})
    entry(right_click(PLAIN)[0], "Copy").trigger()
    entry(right_click(PLAIN)[0], "Paste").trigger()
    application.processEvents()
    copy_id = ids("other")[-1]
    grown = by_id(copy_id, "other").properties.as_dict()
    expect("the copy is born with the pack's list, as the add verb says",
           (sorted(grown), grown.get(BEHAVIORS, "").split(",")[:2]),
           ([BEHAVIORS], ["player_input", "attack_action"]))
    expect("...and the report NAMES what appeared, rather than hiding it",
           (BEHAVIORS in hierarchy.last_notice,
            "topdown_rpg" in hierarchy.last_notice), (True, True))
    # THE HALF THAT PROVES IT IS PRECEDENCE AND NOT POLICY: an authored list
    # wins outright, so the hero's three tokens crossed intact above and did
    # not become the pack's eight.
    expect("...while an authored list is never overwritten by it",
           hero_before[BEHAVIORS].count(",") + 1, 3)
    window.undo()
    application.processEvents()

    # ----------------------------------------------------------------
    print()
    print("Delete goes through the verb that has an exact inverse")
    # ----------------------------------------------------------------
    window.map_actions["fixture"].trigger()
    application.processEvents()
    no_modals()
    depth = len(session.history())
    entry(right_click(BAD)[0], "Delete").trigger()
    application.processEvents()
    expect("Delete removes it through map.object.remove, asking nothing",
           (ids(), [c.verb for c in session.history()[-1].commands], modals()),
           ([1, 3], ["map.object.remove"], []))
    window.undo()
    application.processEvents()
    expect("...and one Ctrl+Z restores the whole element",
           (ids(), session.project.map("fixture").to_bytes() == FIXTURE_BYTES),
           ([1, 2, 3], True))

    # A ROW THAT NO LONGER RESOLVES CANNOT BE ACTED ON, and says why. This
    # is the recycled-id shape the canvas learned the expensive way, asked
    # of the tree: an address, not an object.
    gone = Scope.parse("map:fixture/layer:entity/object:404")
    expect("an object scope nothing answers greys every object entry",
           hierarchy.object_refusal(gone),
           "map:fixture/layer:entity/object:404 no longer resolves to an "
           "object on this map")
    depth = len(session.history())
    expect("...and refuses the calls as well, writing nothing",
           (hierarchy.delete_object(gone), hierarchy.copy_object(gone),
            hierarchy.edit_object(gone), len(session.history())),
           (False, False, False, depth))

    # ----------------------------------------------------------------
    print()
    print("A RECYCLED ID IS A DIFFERENT OBJECT, AND A MENU IS ABOUT AN OBJECT")
    # ----------------------------------------------------------------
    # THE ROW ABOVE IS THE EASY HALF: an id that answers NOTHING. This is
    # the half that made the canvas rewrite what a selection is.
    # `MapDocument._release_object_id` rolls `nextobjectid` back when the id
    # being removed is the one just handed out -- deliberately, because that
    # is what makes add-then-remove byte-exact -- so ids are REUSED, and a
    # recycled id RESOLVES. To somebody else. Measured before the fix, on
    # the identical stale address: the canvas refused and the tree deleted
    # "removed BOB (GamePlayer)".
    #
    # The fixture is byte-identical to disk at this line (asserted one row
    # up), and this section puts it back that way when it is done.
    SECTION_BASE = len(session.history())

    def add_object(name: str, cell, *, settle: bool = True):
        """Place an object WITHOUT selecting it, and answer the new one.

        By command, the way a script, a relayed AI response or a sibling
        panel places one -- never by the canvas gesture, which selects what
        it just made and so can never leave the stale address this whole
        section is about.
        """
        window.run(Command("map.object.add", Scope.parse(ENTITY),
                           {"type": "GamePlayer", "name": name,
                            "x": float(cell[0] * TILE),
                            "y": float(cell[1] * TILE),
                            "width": 16.0, "height": 16.0}))
        if settle:
            application.processEvents()
        return objects()[-1]

    add_object("alice", (1, 3))
    bob_temp = add_object("bob_temp", (3, 3))
    RECYCLED = bob_temp.id
    WAS_AT = (bob_temp.x, bob_temp.y)
    ADDRESS = f"map:fixture/layer:entity/object:{RECYCLED}"
    # The menu the author opened while that row still meant `bob_temp`.
    stale_menu = right_click(ADDRESS)[0]
    expect("the author opens the menu on bob_temp, and every entry is live",
           [entry(stale_menu, name).isEnabled()
            for name in ("Select", "Focus", "Edit", "Cut", "Copy", "Delete")],
           [True] * 6)

    window.undo()                       # bob_temp goes, and its id with it
    application.processEvents()
    bob = add_object("bob", (5, 3))     # ...and the next add is handed it
    expect("THE ID IS HANDED OUT AGAIN: it is a different object, with a "
           "different name, in a different place",
           (bob.id, bob.name, (bob.x, bob.y) == WAS_AT),
           (RECYCLED, "bob", False))
    expect("...and the stale menu's entries are STILL ENABLED, because "
           "greying asks whether the id resolves and a recycled id does",
           [entry(stale_menu, name).isEnabled()
            for name in ("Select", "Focus", "Edit", "Cut", "Copy", "Delete")],
           [True] * 6)

    # EVERY ENTRY THAT ACTS ON THE OBJECT, one after the other, on the menu
    # that was built before the recycle. Each is expected to refuse and to
    # name BOTH objects: the one the row meant, and the one the id answers
    # with now. A refusal that said only "that is not it any more" leaves
    # the author holding a menu and no idea what happened.
    no_modals()
    focused.clear()
    # THE RECORDER, RE-INSTALLED, and the reason is measured: the map picker
    # was driven two sections up and `EditorWindow.__switch_map` BUILDS A NEW
    # CANVAS, so the instance attribute set near the top of this file went
    # with the old one. Without this the "no camera moved" half below would
    # be asserting an empty list nothing could ever fill -- vacuous, which is
    # the failure shape law 5 names.
    window.canvas.focus_object = fake_focus
    window.selection.select(Scope.parse(FLOOR))
    clipping_before = HierarchyDock._clipboard
    depth, before = len(session.history()), ids()
    said = {}
    for name in ("Select", "Focus", "Edit", "Cut", "Copy", "Delete"):
        entry(stale_menu, name).trigger()
        application.processEvents()
        said[name] = ascii_fold(hierarchy.last_notice)
    expect("every entry REFUSES, and each names the object the row meant "
           "and the object the id means now",
           sorted(name for name, notice in said.items()
                  if "is not bob_temp" in notice
                  and "that id now names bob (GamePlayer)" in notice),
           ["Copy", "Cut", "Delete", "Edit", "Focus", "Select"])
    expect("...so the map, the history and the clipboard are untouched",
           (ids(), len(session.history()),
            HierarchyDock._clipboard is clipping_before),
           (before, depth, True))
    expect("...and no camera moved, no selection moved, no editor opened, "
           "and nothing asked",
           (focused, str(window.selection.scope),
            window.object_editor is None or not window.object_editor.isVisible(),
            modals()), ([], FLOOR, True, []))

    # PASTE IS THE CONTRAST THAT PROVES THIS IS NOT A DEAD MENU. It acts on
    # the LAYER the row is on, which a recycled id cannot change, so it
    # carries no card and stays live on the very same stale menu.
    grew = len(ids())
    entry(stale_menu, "Paste").trigger()
    application.processEvents()
    expect("...while Paste on that same stale menu still lands, because it "
           "acts on the layer and not on the object",
           len(ids()), grew + 1)
    window.undo()
    application.processEvents()

    # ----------------------------------------------------------------
    print()
    print("...and a LIVE card still does every one of those things")
    # ----------------------------------------------------------------
    # OTHERWISE THIS IS A DEAD MENU. The address below is the SAME STRING as
    # the stale one -- same map, same layer, same id -- which is the whole
    # argument in one line: an address cannot tell these two apart, and the
    # element can.
    expect("the live row's address is the very same string as the stale one",
           f"map:fixture/layer:entity/object:{bob.id}", ADDRESS)
    focused.clear()
    window.selection.select(Scope.parse(FLOOR))
    live_menu = right_click(ADDRESS)[0]
    entry(live_menu, "Select").trigger()
    application.processEvents()
    expect("Select on a live card selects", str(window.selection.scope), ADDRESS)
    entry(live_menu, "Focus").trigger()
    application.processEvents()
    expect("...Focus reaches the canvas with that scope", focused, [ADDRESS])
    # The shipping method back, so nothing below is driving a stub.
    del window.canvas.focus_object
    entry(live_menu, "Edit").trigger()
    application.processEvents()
    expect("...Edit opens the window's editor on it",
           (window.object_editor is not None,
            str(window.object_editor.scope) if window.object_editor else None),
           (True, ADDRESS))
    window.object_editor.close()
    application.processEvents()
    entry(live_menu, "Copy").trigger()
    application.processEvents()
    expect("...Copy takes the clipping",
           HierarchyDock._clipboard.label, "bob (GamePlayer)")
    depth = len(session.history())
    entry(live_menu, "Cut").trigger()
    application.processEvents()
    expect("...Cut removes it, in one transaction",
           (RECYCLED in ids(), len(session.history()) - depth), (False, 1))
    window.undo()
    application.processEvents()
    # A REBUILT MENU FOR DELETE, and not to be tidy: `map.object.restore`
    # builds a NEW element, so the card the menu above is holding is
    # legitimately stale now -- the object is back and it is not the same
    # `<object>`. Asking the old menu here would assert the guard rather
    # than the verb.
    delete_menu = right_click(ADDRESS)[0]
    depth = len(session.history())
    entry(delete_menu, "Delete").trigger()
    application.processEvents()
    expect("...and Delete on a live card removes it",
           (RECYCLED in ids(), len(session.history()) - depth), (False, 1))
    window.undo()
    application.processEvents()

    # A LEGITIMATE EDIT UNDER AN OPEN MENU MUST NOT DROP THE GESTURE, and
    # this is the assertion that stops the guard from being "refuse whenever
    # anything changed". A move keeps the element; only a recycle replaces
    # it, and the card follows the first and refuses the second.
    move_menu = right_click(ADDRESS)[0]
    window.run(Command("map.object.move", Scope.parse(ADDRESS),
                       {"x": 80.0, "y": 64.0}))
    application.processEvents()
    expect("an object MOVED under the open menu is still the same object",
           (by_id(RECYCLED).x, by_id(RECYCLED).y), (80.0, 64.0))
    depth = len(session.history())
    entry(move_menu, "Delete").trigger()
    application.processEvents()
    expect("...so that menu still acts on it: the ELEMENT is the identity, "
           "and a move does not replace it",
           (RECYCLED in ids(), len(session.history()) - depth), (False, 1))

    while len(session.history()) > SECTION_BASE:
        window.undo()
    application.processEvents()
    expect("and the whole recycle dance undoes away, byte for byte",
           (session.project.map("fixture").to_bytes() == FIXTURE_BYTES,
            ids()), (True, [1, 2, 3]))

    # ----------------------------------------------------------------
    print()
    print("THE REAL OPENER, DRIVEN. NOT A STUB.")
    # ----------------------------------------------------------------
    # Everything above replaced `popup_menu`, which is right for READING a
    # menu and proves nothing about the call the author's own right-click
    # makes. `QMenu.exec` does not return until the menu closes -- the
    # 40-minute shape law 13 is named after -- and a check that only ever
    # drove the stub could not see it.
    #
    # THE WATCHDOG IS WHAT MAKES THIS SAFE TO ASSERT. A zero-timer is armed
    # first: under a blocking opener it fires inside that nested loop,
    # closes the menu and lets the call return, so a regression is RED in
    # milliseconds instead of hanging this file for the full 600s. Under
    # `popup` nothing spins the loop before the assertion, so the timer
    # cannot have fired and a VISIBLE menu is proof nothing blocked.
    def close_any_popup():
        popup = QApplication.activePopupWidget()
        if popup is not None:
            popup.close()

    real_menus: list = []

    def watched_open(menu, at):
        real_menus.append(menu)
        canvas_module._exec_menu(menu, at)

    hierarchy.popup_menu = watched_open
    menus_before = len(tree.findChildren(QMenu))
    depth = len(session.history())
    no_modals()
    QTimer.singleShot(0, close_any_popup)
    # The whole wire, from the signal Qt emits for a real right-click.
    tree.customContextMenuRequested.emit(
        tree.viewport().mapTo(tree, point_of(HERO)))
    expect("the REAL right-click opened exactly one menu",
           [[label.split(" . ")[0] for label in labels(menu)]
            for menu in real_menus],
           [["Select", "Focus", "Edit...", "Cut", "Copy", "Paste", "Delete"]])
    live = real_menus[0]
    expect("...and RETURNED with it still on screen, so nothing blocked",
           (live.isVisible(), QApplication.activePopupWidget() is live),
           (True, True))
    expect("...having written nothing and asked nothing",
           (len(session.history()), modals()), (depth, []))
    expect("a menu that is still open is still alive",
           len(tree.findChildren(QMenu)), menus_before + 1)
    # AND IT STILL ACTS. An entry wired with `triggered` does not care
    # whether its menu blocked or popped -- but that is a claim, and Select
    # is the one entry that proves it without writing anything. No
    # processEvents around it: `triggered` arrives synchronously, and
    # spinning the loop here would let the watchdog close the menu.
    window.selection.select(Scope.parse(FLOOR))
    entry(live, "Select").trigger()
    expect("...and an entry on the LIVE menu still does what it says",
           str(window.selection.scope), HERO)
    live.close()
    application.processEvents()
    expect("...and the menu is freed once it is dismissed, not before",
           len(tree.findChildren(QMenu)), menus_before)

    # ----------------------------------------------------------------
    print()
    print("THE OPEN-MENU RACE, THROUGH THAT SAME REAL OPENER")
    # ----------------------------------------------------------------
    # THE ASSERTION WHOSE ABSENCE LET THIS SHIP. Everything above proves the
    # menu comes back with the loop running -- and that is exactly what
    # makes "the document cannot change between building this menu and
    # triggering it" false on the SHIPPING path. `EditorWindow` holds a
    # QFileSystemWatcher on `editor/requests/` and applies an AI response
    # from inside that same loop, so the change below is not contrived: it
    # is what a relayed response does, spelled as the commands it runs.
    #
    # NO WATCHDOG IS ARMED HERE, on purpose. A zero-timer fires on the first
    # `processEvents` below and would close the menu this section needs on
    # screen; the section above already proved the opener returns without
    # blocking, three assertions ago, with a watchdog armed.
    real_menus.clear()
    hierarchy.popup_menu = watched_open
    victim = add_object("victim", (1, 4))
    VICTIM = victim.id
    VICTIM_ADDRESS = f"map:fixture/layer:entity/object:{VICTIM}"
    tree.customContextMenuRequested.emit(
        tree.viewport().mapTo(tree, point_of(VICTIM_ADDRESS)))
    up = real_menus[-1]
    expect("the author's own right-click is up, on the object pointed at",
           (up.isVisible(), entry(up, "Delete").isEnabled()), (True, True))
    # THE DOCUMENT CHANGES UNDERNEATH IT. `settle=False`: nothing spins the
    # event loop, so the menu on screen is provably the one built above.
    window.undo()
    stranger = add_object("stranger", (3, 4), settle=False)
    expect("a change lands underneath it and the id now names somebody else",
           (stranger.id, stranger.name, up.isVisible()),
           (VICTIM, "stranger", True))
    expect("...and the entry is STILL ENABLED: it was greyed once, when the "
           "menu was built", entry(up, "Delete").isEnabled(), True)
    depth, before = len(session.history()), ids()
    no_modals()
    entry(up, "Delete").trigger()
    expect("...and triggering it removes NOTHING -- the wrong object lives",
           (ids(), len(session.history()), VICTIM in ids()),
           (before, depth, True))
    expect("...saying what the menu was opened on and what the id means now",
           ("is not victim" in ascii_fold(hierarchy.last_notice),
            "that id now names stranger (GamePlayer)"
            in ascii_fold(hierarchy.last_notice), modals()),
           (True, True, []))
    # AND THE SAME REAL GESTURE, REPEATED NOW, DELETES. Without this the
    # section above would pass on a menu that had simply stopped working.
    real_menus.clear()
    tree.customContextMenuRequested.emit(
        tree.viewport().mapTo(tree, point_of(VICTIM_ADDRESS)))
    fresh = real_menus[-1]
    entry(fresh, "Delete").trigger()
    expect("...while a right-click made AFTER the change deletes what it "
           "was made for",
           (VICTIM in ids(), len(session.history()) - depth), (False, 1))
    up.close()
    fresh.close()
    application.processEvents()
    while len(session.history()) > SECTION_BASE:
        window.undo()
    application.processEvents()
    expect("the race leaves the fixture byte-identical too",
           (session.project.map("fixture").to_bytes() == FIXTURE_BYTES,
            ids()), (True, [1, 2, 3]))

    hierarchy.popup_menu = canvas_module._exec_menu

    # ----------------------------------------------------------------
    print()
    print("the panel opens no dialog of its own on any of these paths")
    # ----------------------------------------------------------------
    expect("nothing above opened a box", modals(), [])
    expect("the panel still holds the two replaceable dialog seams",
           (callable(hierarchy.ask), callable(hierarchy.confirm)), (True, True))
    expect("...and the menu seam is the shared one, not a second spelling",
           hierarchy_module._exec_menu is canvas_module._exec_menu, True)

    # Closing a dirty window OFFERS TO SAVE (`EditorWindow.closeEvent`).
    # "No" is what a teardown means: close and write nothing, exactly as
    # `close()` behaved before that feature landed. Without this the fixture
    # would be flushed to disk on the way out.
    window.confirm = lambda *a, **k: False
    window.close()
finally:
    shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print(f"FAILED: {failures}")
    sys.exit(1)
print("PASS")
