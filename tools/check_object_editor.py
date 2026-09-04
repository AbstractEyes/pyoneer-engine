"""The entity editing screen: what it shows, what it emits, what it saves.

The author asked for a screen that opens when an entity is created or
double-clicked, and said "closing this popup should automatically save the
entity". This file is written against the five ways that could be false
without anything on screen looking wrong:

  * IT COULD SHOW THE WRONG OBJECT. Re-aiming a held window at a second
    object is the one path where a stale scope survives -- so both halves are
    asserted: the first object's values are there AND gone once it is
    re-aimed, and the window is proved to be the SAME window rather than a
    second one stacked on top. The counter that proves "one window" is itself
    proved able to count two.
  * IT COULD LOSE THE LAST EDIT. `InspectionView` commits a text field on
    `editingFinished`, and closing a window is neither focus leaving a field
    nor Enter. So the hazard is reproduced exactly -- a value typed into a
    field the caret is still inside -- and asserted to be ABSENT from the
    document before the close and PRESENT in it afterwards. Reaching the
    document, not a signal firing: a signal that fires into a refused command
    loses the work just as completely.
  * IT COULD SAVE IT TWICE. Committing rebuilds the form, and rebuilding
    re-parents the retired body, which makes Qt emit `editingFinished` a
    second time from the widget that has already spoken. That lands the same
    command twice and one Ctrl+Z then appears not to work -- so the commands
    are COUNTED, and one undo is asserted to put the value back.
  * IT COULD SAVE IT TWICE FROM THE WIDGET ITSELF, one layer lower, where
    every form in the editor would inherit it. An editable `QComboBox` has
    no single commit signal -- Qt re-emits `activated` from the very
    `editingFinished` the view also listens to -- so one gesture landed up
    to FOUR identical commands and the copies were EMPTY transactions, which
    is why the symptom was "Ctrl+Z did nothing" rather than a wrong value.
    All four real gestures are therefore driven as REAL key and mouse events
    and counted, with a plain text row as a control whose counter is proved
    able to say two; and the same gesture is driven again through the REAL
    Inspector dock, where one Ctrl+Z is asserted to put the value back. That
    last assertion is the one whose absence let this ship.
  * THE SNAP PREFERENCE COULD REACH NOTHING. It is asserted ON by default,
    asserted to arrive on the canvas the window mounts, and asserted to
    arrive as OFF when it is turned off -- the half that a preference read
    once at startup and never again would fail.

Plus the two standing structural properties of any window in `editor/ui/`:
it opens nothing modal (law 13), and it is reachable -- `EditorWindow`
really does connect the canvas's `edit_object_requested` to it.

Against its OWN fixture, never `data/maps/starter.tmx` (law 4).

Skips cleanly when PySide6 is absent.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile

if importlib.util.find_spec("PySide6") is None:
    print("SKIP  PySide6 is not installed "
          "(pip install -r editor/requirements.txt)")
    sys.exit(0)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt, Signal          # noqa: E402
from PySide6.QtGui import QKeySequence                                  # noqa: E402
from PySide6.QtTest import QTest                                        # noqa: E402
from PySide6.QtWidgets import (                                         # noqa: E402
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from editor.core.commands import Command                                # noqa: E402
from editor.core.inspect import Field, Inspection, Section              # noqa: E402
from editor.core.scope import Scope                                     # noqa: E402
from editor.core.session import Session                                 # noqa: E402
from editor.core.settings import BY_KEY, EditorSettings                 # noqa: E402
from editor.ui.canvas import MapCanvas                                  # noqa: E402
from editor.ui.fields import InspectionView                             # noqa: E402
from editor.ui.object_editor import ACTOR_MOVED, ObjectEditor           # noqa: E402
import editor.ui.main_window as main_window_module                      # noqa: E402
from editor.ui.main_window import EditorWindow                          # noqa: E402
from scripts.game.behavior.base import ACTOR, BEHAVIORS                 # noqa: E402

REPO = _bootstrap.REPO_ROOT
failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} got={got!r} want={want!r}")
    if not ok:
        failures.append(label)


# RECORD every modal rather than silencing it: "this path asked nothing" is
# the stronger claim of the two and it needs an instrument that could have
# said otherwise.
warned: list[str] = []
asked: list[str] = []
informed: list[str] = []


def _record(bucket, answer=None):
    def stub(*a, **k):
        bucket.append(str(a[2]) if len(a) > 2 else "")
        return answer
    return staticmethod(stub)


QMessageBox.warning = _record(warned)
QMessageBox.critical = _record(warned)
QMessageBox.information = _record(informed)
QMessageBox.question = _record(asked, QMessageBox.Yes)


def modals() -> list[str]:
    return warned + asked + informed


def no_modals() -> None:
    for bucket in (warned, asked, informed):
        bucket.clear()


def settle() -> None:
    """Let Qt finish, INCLUDING the deferred deletes.

    `processEvents` alone does not run `deleteLater`: those are delivered
    when an event loop unwinds, and this file never starts one. Without this
    a closed window is still in `topLevelWidgets()` and a retired form is
    still a child of its view -- so "exactly one window" and "the form was
    replaced" would both be measured against corpses.
    """
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    application.processEvents()


class FakeStore:
    """Stands in for QSettings, returning everything as TEXT the way the ini
    backend does -- which is exactly how a boolean preference silently stops
    working if nothing coerces it. Also keeps this check off the developer's
    own preferences."""

    def __init__(self, **initial):
        self.data = {k: str(v) for k, v in initial.items()}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = str(value)

    def remove(self, key):
        self.data.pop(key, None)


class FakeLayout:
    """The dock-layout store. A real one would be read AND written by every
    window this file opens, so the verdict would depend on how the developer
    last dragged a panel."""

    def __init__(self):
        self.data = {}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value


LAYOUTS = FakeLayout()
main_window_module.layout_store = lambda: LAYOUTS


# --------------------------------------------------------------------------
# The cross-track contract
#
#     edit_object_requested = Signal(Scope)     on MapCanvas
#
# The canvas EMITS it; the window CONNECTS it. This file owns neither half of
# the canvas, so when the emitting half has not landed yet it is supplied
# here -- the connect is still asserted, against a canvas that carries the
# contract, which is the only half this window is responsible for. Announced
# out loud either way, because a check that quietly substitutes the thing it
# is testing is a check that always passes.
# --------------------------------------------------------------------------
CONTRACT = "edit_object_requested"
CANVAS_HAS_CONTRACT = hasattr(MapCanvas, CONTRACT)

if not CANVAS_HAS_CONTRACT:
    class ContractCanvas(MapCanvas):
        """MapCanvas with the contract signal, for as long as it lacks one."""

        edit_object_requested = Signal(object)

    main_window_module.MapCanvas = ContractCanvas


class Harness(QMainWindow):
    """The one thing `ObjectEditor` asks of its window: run a command.

    Deliberately not `EditorWindow` for the sections about the screen itself
    -- a failure there has to be a failure in this window rather than in
    whatever the toolbar looks like today. `EditorWindow` is driven for real
    further down, where the wiring is the subject.
    """

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.applied: list = []
        self.rejected: list[str] = []
        self.undone = 0

    def run(self, commands, *, label=None, source="editor") -> bool:
        self.applied.append(commands)
        try:
            self.session.run(commands, label=label, source=source)
        except Exception as exc:                                # noqa: BLE001
            self.rejected.append(str(exc))
            return False
        return True

    def undo(self) -> None:
        self.undone += 1
        self.session.undo()


# --------------------------------------------------------------------------
# Reading a rendered form back
# --------------------------------------------------------------------------

_EDITORS = (QCheckBox, QComboBox, QAbstractSpinBox, QLineEdit)


def _editor(widget: QWidget) -> QWidget:
    """The editor inside a form row, past the holder a remove button adds."""
    if isinstance(widget, _EDITORS):
        return widget
    for child in widget.findChildren(QWidget):
        if isinstance(child, _EDITORS):
            return child
    return widget


def rows(view) -> dict[str, QWidget]:
    """{row label: the widget in it} for every form row this view rendered.

    Reads the rendered widgets rather than the `Inspection` behind them, so
    it answers what an author can actually reach. A read-only row renders a
    QLabel and is included: "this value is shown but not editable" is a
    property worth being able to see from here.
    """
    found: dict[str, QWidget] = {}
    # THE LIVE BODY ONLY. `InspectionView` retires the form it replaces with
    # `deleteLater`, which does not run until an event loop unwinds -- so a
    # refreshed view still has every previous form hanging off it as a hidden
    # child, and `findChildren` on the view returns all of them. Reading a
    # retired row is how a re-aimed window looks like it never moved.
    body = view.widget()
    if body is None:
        return found
    for form in body.findChildren(QFormLayout):
        for index in range(form.rowCount()):
            label = form.itemAt(index, QFormLayout.LabelRole)
            field = form.itemAt(index, QFormLayout.FieldRole)
            if label is None or field is None:
                continue
            owner, editor = label.widget(), field.widget()
            if isinstance(owner, QLabel) and editor is not None:
                found[owner.text()] = _editor(editor)
    return found


def row(view, prefix: str) -> QWidget | None:
    """One row by the start of its label -- a behavior's label carries its
    order and its genre after the token."""
    for label, widget in rows(view).items():
        if label == prefix or label.startswith(prefix + " "):
            return widget
    return None


def headings(view) -> list[str]:
    body = view.widget()
    return [] if body is None else [w.text() for w in
                                    body.findChildren(QLabel)]


FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" compressionlevel="-1" width="4" height="4" \
tilewidth="16" tileheight="16" infinite="0" nextlayerid="4" nextobjectid="4">
 <tileset firstgid="1" name="Art" tilewidth="16" tileheight="16" \
tilecount="16" columns="4">
  <image source="art.png" width="64" height="64"/>
 </tileset>
 <layer id="1" name="Floor" width="4" height="4">
  <data encoding="csv">
1,1,1,1,
1,1,1,1,
1,1,1,1,
1,1,1,1
</data>
 </layer>
 <objectgroup id="2" name="entity">
  <object id="1" name="hero" type="GamePlayer" x="16" y="16" width="16" \
height="16">
   <properties>
    <property name="hp" type="int" value="5"/>
    <property name="pyoneer_actor" value="hero"/>
    <property name="pyoneer_behaviors" value="player_input,topdown_move"/>
   </properties>
  </object>
  <object id="2" name="chest" type="GamePlayer" x="48" y="0" width="16" \
height="16"/>
 </objectgroup>
</map>
"""

ACTORS_TABLE = {
    "table": "actors",
    "title": "Actors",
    "columns": [{"name": "hp", "type": "int", "default": 10}],
    "rows": {"hero": {"hp": 30}, "slime": {"hp": 5}},
}

workspace = tempfile.mkdtemp(prefix="pyoneer_object_editor_")
application = QApplication.instance() or QApplication([])

try:
    os.makedirs(os.path.join(workspace, "config"))
    os.makedirs(os.path.join(workspace, "data", "maps"))
    os.makedirs(os.path.join(workspace, "data", "project", "tables"))
    with open(os.path.join(workspace, "data", "maps", "fixture.tmx"), "w",
              encoding="utf-8", newline="") as handle:
        handle.write(FIXTURE)
    with open(os.path.join(workspace, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [{"name": "fixture", "identifier": "fixture",
                             "file": "data/maps/fixture.tmx"}]}, handle)
    with open(os.path.join(workspace, "data", "project", "tables",
                           "actors.json"), "w", encoding="utf-8") as handle:
        json.dump(ACTORS_TABLE, handle)

    session = Session.open(workspace, genre_id="topdown_rpg")
    document = session.project.map("fixture")

    def scope_for(object_id: int) -> Scope:
        return Scope.of(("map", "fixture"), ("layer", "entity"),
                        ("object", str(object_id)))

    HERO, CHEST = scope_for(1), scope_for(2)

    def obj(object_id: int):
        return document.object_layer("entity").find(object_id)

    def props(object_id: int) -> dict:
        return obj(object_id).properties.as_dict()

    harness = Harness(session)

    # ------------------------------------------------------------------
    print("1. the screen shows THIS object -- identity, placement, both "
          "halves of what it is")
    # ------------------------------------------------------------------
    screen = ObjectEditor(session, HERO, harness)
    screen.show()
    settle()

    left = rows(screen.object_view)
    expect("it offers the identity and the placement of the real object",
           [left["name"].text(), left["x"].value(), left["y"].value(),
            left["width"].value()],
           ["hero", 16.0, 16.0, 16.0])
    expect("...and the object's own custom property with it",
           "hp" in left, True)
    expect("the title names the object, its layer and its map",
           screen.windowTitle(), "hero — entity — map:fixture")

    # THE BEHAVIOR CHECKLIST IS EMBEDDED, not re-stated. Asserted by finding
    # a registered token's tickbox in the second view, with the fixture's own
    # two ticked and a third not -- which is the checklist reading the object
    # rather than a list of names drawn on a form.
    right = rows(screen.behavior_view)
    expect("the behavior checklist is on the same screen, ticked from the "
           "object", [row(screen.behavior_view, t).isChecked()
                      for t in ("player_input", "topdown_move",
                                "animation_drive")],
           [True, True, False])
    expect("...and its rows are real tickboxes, not labels",
           isinstance(row(screen.behavior_view, "topdown_move"), QCheckBox),
           True)
    expect("the behavior half is aimed at the same object as the left half",
           str(screen.behavior_view.inspection.scope), str(HERO))

    # The actor row: lifted OUT of the generic property list and rendered as
    # the rows that exist. Both halves -- it is present as a choice, and it
    # is absent from the untyped Properties list it would otherwise sit in.
    actor = left.get("actor row")
    expect("the actors row is offered as the rows that exist",
           (isinstance(actor, QComboBox), actor.currentText(),
            sorted(actor.itemText(i) for i in range(actor.count()))),
           (True, "hero", ["", "hero", "slime"]))
    expect("...and NOT also as an untyped text box in Properties",
           ACTOR in left, False)
    expect("...with the Properties note saying where it went",
           any(ACTOR_MOVED.strip() in text for text in
               headings(screen.object_view)), True)
    expect("the behavior vocabulary is not in the property list either",
           BEHAVIORS in left, False)
    expect("nothing modal opened to show any of it", modals(), [])

    # ------------------------------------------------------------------
    print()
    print("2. an edit is a command, the verb accepts it, and ONE undo "
          "reverses it")
    # ------------------------------------------------------------------
    screen.command_requested.connect(harness.run)
    harness.applied.clear()
    name_field = rows(screen.object_view)["name"]
    name_field.setText("champion")
    name_field.editingFinished.emit()          # what Enter does
    settle()

    expect("one edit emitted exactly one command", len(harness.applied), 1)
    expect("...and it was the verb that writes a tmx attribute",
           (harness.applied[0].verb, harness.applied[0].args),
           ("map.object.set", {"key": "name", "value": "champion"}))
    expect("the verb accepted it", harness.rejected, [])
    expect("the document has the new name", obj(1).name, "champion")

    # Ctrl+Z has to work in THIS window: Qt shortcuts are per-window, and a
    # promise that only works in the other one is worse than no promise. The
    # screen owns no stream -- it forwards to the window that does.
    def action(text: str):
        found = [a for a in screen.actions() if a.text() == text]
        return found[0] if len(found) == 1 else None

    expect("the screen carries its own Undo, Redo and Save",
           [action(t) is not None for t in ("&Undo", "&Redo", "&Save")],
           [True, True, True])
    action("&Undo").trigger()
    expect("...and Undo forwards to the stream that owns the edit",
           (harness.undone, obj(1).name), (1, "hero"))
    # The real window refreshes every open view after a command; this harness
    # is deliberately smaller, so the form is put back in step by hand.
    screen.refresh()
    # THE OTHER HALF: a parent that cannot do what is forwarded to it must be
    # a no-op, not a crash -- this harness has no `save`, and a window whose
    # Ctrl+S took the editor down would be a poor trade for a shortcut.
    action("&Save").trigger()
    expect("a forward with nobody to receive it does nothing at all",
           (obj(1).name, len(harness.applied)), ("hero", 1))
    expect("still nothing modal", modals(), [])

    # ------------------------------------------------------------------
    print()
    print("3. the field the author is still typing in is not lost")
    # ------------------------------------------------------------------
    # THE HAZARD, REPRODUCED: `setText` is what typing does to a QLineEdit --
    # it changes the widget and emits nothing the view listens to. The value
    # is in the widget and nowhere else.
    harness.applied.clear()
    name_field = rows(screen.object_view)["name"]
    name_field.setFocus()
    expect("the window knows which field the caret is in",
           screen.focusWidget() is name_field, True)
    name_field.setText("in flight")
    expect("typing alone reaches NOTHING -- this is the hazard",
           (obj(1).name, len(harness.applied)), ("hero", 0))

    # WHICH OF THESE ASSERTIONS DISCRIMINATES, measured rather than assumed.
    # A plain `close()` is NOT the sharp case: on this Qt, hiding a window
    # clears the focus inside it and `QLineEdit` emits `editingFinished` for
    # any focus-out that is not a popup -- a deliberate probe, sending a
    # FocusOut with `ActiveWindowFocusReason` by hand, committed the value on
    # its own. So the close below is asserted because it is the outcome the
    # author asked for, and the two cases where Qt hands out no focus-out at
    # all are what prove the commit is load-bearing: RE-AIMING the window
    # (section 4) and QUITTING the editor (section 6), both of which destroy
    # the field rather than defocusing it. Stubbing `commit_in_flight` to
    # return False turns exactly those two red and leaves this one green.
    screen.close()
    settle()
    expect("closing puts it in the DOCUMENT, not merely on a signal",
           obj(1).name, "in flight")
    expect("...as exactly one command, so one Ctrl+Z reaches it",
           len(harness.applied), 1)
    session.undo()
    expect("...which it does", obj(1).name, "hero")

    # THE OTHER HALF. With nothing in flight there is nothing to commit and
    # nothing may be emitted -- a close that always fired a command would
    # write the same value back on every visit and fill the history with it.
    harness.applied.clear()
    expect("a close with no field in flight commits nothing",
           (screen.commit_in_flight(), len(harness.applied)), (False, 0))

    # And the same for a spin box, which holds typed digits as TEXT until
    # something interprets them -- a different mechanism, the same hazard.
    screen.show()
    settle()
    harness.applied.clear()
    x_field = rows(screen.object_view)["x"]
    x_field.setFocus()
    x_field.lineEdit().setText("48")
    expect("a typed coordinate reaches nothing either",
           (obj(1).x, len(harness.applied)), (16.0, 0))
    screen.close()
    settle()
    expect("closing interprets it and moves the object",
           (obj(1).x, len(harness.applied)), (48.0, 1))
    session.undo()
    expect("one undo puts the position back", obj(1).x, 16.0)

    # ------------------------------------------------------------------
    print()
    print("4. re-aiming is the SAME window, and it does not drop the edit "
          "either")
    # ------------------------------------------------------------------
    screen.show()
    settle()
    harness.applied.clear()
    before = id(screen)
    name_field = rows(screen.object_view)["name"]
    name_field.setFocus()
    name_field.setText("ghost")
    screen.set_scope(CHEST)
    settle()
    expect("re-aiming commits what was in flight on the object being left",
           obj(1).name, "ghost")
    session.undo()

    expect("it is the same window object", id(screen), before)
    expect("it now shows the OTHER object's values",
           [rows(screen.object_view)["name"].text(),
            rows(screen.object_view)["x"].value()], ["chest", 48.0])
    expect("...and none of the first object's",
           ("hp" in rows(screen.object_view),
            rows(screen.object_view)["name"].text() == "hero"),
           (False, False))
    expect("the behavior half followed it",
           [row(screen.behavior_view, t).isChecked()
            for t in ("player_input", "topdown_move")], [False, False])
    expect("an object with no actors row still offers the table's rows",
           sorted(rows(screen.object_view)["actor row"].itemText(i)
                  for i in range(
                      rows(screen.object_view)["actor row"].count())),
           ["", "hero", "slime"])

    # Naming a row writes the property; blanking it REMOVES the property
    # rather than writing an empty one, which is a spawn-time exception
    # naming the property instead of the row.
    harness.applied.clear()
    actor = rows(screen.object_view)["actor row"]
    actor.setCurrentText("slime")
    actor.lineEdit().editingFinished.emit()
    settle()
    expect("choosing a row writes it", props(2).get(ACTOR), "slime")
    actor = rows(screen.object_view)["actor row"]
    actor.setCurrentText("")
    actor.lineEdit().editingFinished.emit()
    settle()
    expect("blanking it REMOVES the property, not blanks it",
           ACTOR in props(2), False)
    session.undo()
    session.undo()
    # THE DUPLICATE GUARD, named. `QComboBox` connects its own line edit's
    # `editingFinished` to a handler that emits `activated` when the text
    # names an item, and `InspectionView` listens to both -- so one commit
    # ran one emitter twice and this pair landed as FOUR commands, with one
    # Ctrl+Z undoing only half of one edit. Measured, before the guard:
    # ['...set slime', '...set slime', '...remove'].
    expect("choosing a row and blanking it is TWO commands, not four",
           [command.verb for command in harness.applied],
           ["map.object.property.set", "map.object.property.remove"])
    expect("two undos leave the object as it was", props(2), {})
    expect("nothing modal through any of it", modals(), [])

    screen.close()
    screen.deleteLater()
    settle()

    # ------------------------------------------------------------------
    print()
    print("5. the preference: ON unless it is turned off, and it reaches the "
          "canvas")
    # ------------------------------------------------------------------
    expect("there is a snap preference at all", "snap_objects" in BY_KEY, True)
    expect("it is a boolean and it defaults ON",
           (BY_KEY["snap_objects"].type, BY_KEY["snap_objects"].default),
           ("bool", True))
    expect("an empty store answers ON",
           EditorSettings(FakeStore()).get("snap_objects"), True)
    # THE OTHER HALF, through the string backend that is how a boolean
    # preference silently stops working.
    expect("a store holding false answers OFF -- as a bool, not a string",
           EditorSettings(FakeStore(snap_objects=False)).get("snap_objects"),
           False)

    window = EditorWindow(session)
    window.settings = EditorSettings(FakeStore())
    window.show()
    settle()
    expect("the window opened the fixture map", window.map_name, "fixture")
    expect("the canvas came up snapping", window.canvas.snap_objects, True)
    expect("the menu tick agrees with it", window.snap_action.isChecked(),
           True)

    window.snap_action.trigger()                # the author's one gesture
    settle()
    expect("the menu entry turns it OFF on the mounted canvas",
           window.canvas.snap_objects, False)
    expect("...and stores it, so the next canvas comes up the same way",
           window.settings.get("snap_objects"), False)
    fresh = window._EditorWindow__new_canvas("fixture")
    expect("...which it does", fresh.snap_objects, False)
    fresh.deleteLater()

    window.snap_action.trigger()
    settle()
    expect("and back ON again, both places",
           (window.canvas.snap_objects,
            window.settings.get("snap_objects")), (True, True))

    # The settings dialog's half of the same preference: it stores the value
    # itself and reports it, so this branch must APPLY without storing again
    # -- and must put the menu tick in step, or two controls disagree about
    # one answer.
    window.settings.set("snap_objects", False)
    window._EditorWindow__on_setting_changed("snap_objects", False)
    expect("the settings dialog's report reaches the canvas too",
           window.canvas.snap_objects, False)
    expect("...and drags the menu tick with it",
           window.snap_action.isChecked(), False)
    window.snap_action.trigger()
    expect("the tick is still live afterwards, not stuck by the blocking",
           (window.canvas.snap_objects, window.snap_action.isChecked()),
           (True, True))
    expect("no dialog anywhere on the preference path", modals(), [])

    # ------------------------------------------------------------------
    print()
    print("6. the screen is REACHABLE: the canvas asks, the window opens it")
    # ------------------------------------------------------------------
    landed = ("exists on MapCanvas" if CANVAS_HAS_CONTRACT else
              "has NOT landed on MapCanvas yet, so a canvas carrying the "
              "contract was substituted for this section")
    print(f"       note: MapCanvas.{CONTRACT} {landed}")
    expect("the window has a public door onto the screen",
           callable(getattr(window, "edit_object", None)), True)
    expect("nothing is open before anything asks", window.object_editor, None)

    def ask_for(scope) -> bool:
        """What a double-click does. Returns whether the CONTRACT carried it.

        Falls through to the method when it did not, so one broken wire costs
        the one assertion that is about the wire instead of abandoning the
        eight below it, which are about the window.
        """
        window.canvas.edit_object_requested.emit(scope)
        settle()
        held = window.object_editor
        if held is not None and held.scope == scope and held.isVisible():
            return True
        window.edit_object(scope)
        settle()
        return False

    def owned() -> list:
        return [w for w in QApplication.topLevelWidgets()
                if isinstance(w, ObjectEditor) and w.parent() is window]

    expect("the canvas's own request opens the screen on that object",
           ask_for(HERO), True)
    expect("...on the object it named, and on screen",
           (str(window.object_editor.scope),
            window.object_editor.isVisible()), (str(HERO), True))
    expect("exactly one of them exists", len(owned()), 1)

    held = window.object_editor
    ask_for(CHEST)
    expect("a second object RE-AIMS it rather than stacking another",
           (window.object_editor is held, str(window.object_editor.scope)),
           (True, str(CHEST)))
    expect("...still exactly one", len(owned()), 1)

    # THE COUNTER IS PROVED ABLE TO SAY TWO. Without this, "exactly one"
    # could be a constant and the assertion above would pass over a window
    # that opened one per double-click.
    spare = ObjectEditor(session, HERO, window)
    expect("the counter can see a second window when there is one",
           len(owned()), 2)
    spare.close()
    spare.deleteLater()
    settle()
    expect("...and back to one when it goes", len(owned()), 1)

    # The refusal half: a scope that is not an object opens nothing.
    window.object_editor.close()
    settle()
    window.edit_object(Scope.of(("map", "fixture"), ("layer", "entity")))
    settle()
    expect("a scope that is not an object opens nothing",
           window.object_editor.isVisible(), False)
    expect("...and says so where it can be read afterwards",
           ("edit_object" in window.problems.notice_keys(),
            any("not an object" in violation.message
                for _key, violation, _detail in window.problems.notices)),
           (True, True))
    expect("no modal on any of those paths", modals(), [])

    # An edit made in the screen goes through the WINDOW's single mutation
    # point, which is the property that gives it undo, the History panel and
    # a reported rejection.
    ask_for(HERO)
    field = rows(window.object_editor.object_view)["name"]
    field.setText("through the window")
    field.editingFinished.emit()
    settle()
    expect("an edit made in the screen lands through the editor's own run",
           obj(1).name, "through the window")
    expect("...and the main window's undo reaches it",
           (window.undo(), obj(1).name), (None, "hero"))
    expect("no modal for a routine edit", modals(), [])

    # Quitting the editor must not lose an in-flight field either: the screen
    # is a child window and is destroyed without a close event of its own.
    field = rows(window.object_editor.object_view)["name"]
    field.setFocus()
    field.setText("typed at quit")
    expect("...and it has not reached the document yet", obj(1).name, "hero")
    window.confirm = lambda *a, **k: False      # "close and lose the files"
    window.close()
    settle()
    expect("quitting the editor commits it before it asks about saving",
           obj(1).name, "typed at quit")
    session.undo()

    # ------------------------------------------------------------------
    print()
    print("7. the structural properties every window in editor/ui owes")
    # ------------------------------------------------------------------
    with open(os.path.join(REPO, "editor", "ui", "object_editor.py"),
              encoding="utf-8") as handle:
        source = handle.read()
    expect("the screen opens no QMessageBox of its own",
           re.findall(r"QMessageBox\.(\w+)\(", source), [])
    expect("...and blocks on no dialog either -- show(), never exec()",
           re.findall(r"(\w+)\.exec_?\(\)", source), [])
    expect("it is shown, and by this window",
           "self.object_editor.show()" in
           open(os.path.join(REPO, "editor", "ui", "main_window.py"),
                encoding="utf-8").read(), True)
    expect("nothing modal opened in this entire file", modals(), [])
    no_modals()

    # ------------------------------------------------------------------
    print()
    print("8. ONE gesture is ONE command -- all four ways an editable combo "
          "is committed")
    # ------------------------------------------------------------------
    # THE GESTURES ARE REAL EVENTS HERE. Every section above emits
    # `editingFinished` by hand, deliberately, because there the subject is
    # what the WINDOW does with a commit that has already happened. It is
    # useless for this one: a hand-emitted signal can only ever produce the
    # one signal whoever wrote the check thought of, and the fault is a
    # SECOND signal nobody thought of. `QTest` posts the key and mouse events
    # Qt itself would deliver, so every signal under test is emitted by Qt
    # for its own reasons.
    #
    # Measured on this Qt, per gesture, as (activated, editingFinished):
    #     drop-down pick with the mouse     (1, 1)  <- the editingFinished
    #                                       fires when the popup takes the
    #                                       focus, BEFORE the pick, carrying
    #                                       the OLD text
    #     pick with the keyboard            (1, 0)
    #     type a value and press Enter      (2, 2)
    #     type a NEW value and click away   (0, 1)
    # So a "fix" that keeps one signal breaks a gesture: dropping `activated`
    # loses the two picks, and dropping `editingFinished` loses the typed
    # value the author never pressed Enter on -- silently, which is worse
    # than the duplicate it would have cured. All four are asserted, and each
    # is asserted to REACH THE DOCUMENT, because a fix that emits one command
    # and drops the edit passes a counting assertion on its own.
    ACTOR_CHOICES = ("hero", "slime", "goblin")

    class Bench:
        """One `InspectionView`, wired the way a dock wires one.

        A dock's whole contract is two lines -- run the command, then
        re-render from the document -- and both are here because the
        re-render is half of the fault: retiring a body clears the focus
        inside it, so a widget that has already spoken speaks again from
        inside the emit it caused.
        """

        def __init__(self):
            self.commands: list = []
            self.holder = QWidget()
            box = QVBoxLayout(self.holder)
            self.view = InspectionView(show_sources=False)
            self.view.command_requested.connect(self.__on_command)
            # Somewhere to click away TO. A focus-out is a gesture like any
            # other and needs a real destination to be one.
            self.elsewhere = QLineEdit()
            box.addWidget(self.view)
            box.addWidget(self.elsewhere)
            self.render()
            self.holder.show()
            application.processEvents()
            self.holder.activateWindow()
            application.processEvents()

        def __on_command(self, command) -> None:
            self.commands.append(command)
            session.run(command)
            # NO `settle()` in here. This runs with the committing widget's
            # own signal on the stack, and settle() flushes DeferredDelete --
            # which would free that widget under Qt's feet. Law 12, from the
            # other side of the fence.
            self.render()

        def render(self) -> None:
            self.view.show_inspection(Inspection(
                HERO, "hero", sections=[Section("Identity", [
                    Field(ACTOR, "actor row", "choice",
                          props(1).get(ACTOR, ""), choices=ACTOR_CHOICES,
                          emit=lambda v: Command(
                              "map.object.property.set", HERO,
                              {"key": ACTOR, "value": str(v)})),
                    Field("name", "name", "str", obj(1).name,
                          emit=lambda v: Command(
                              "map.object.set", HERO,
                              {"key": "name", "value": str(v)})),
                ])]))

        def combo(self) -> QComboBox:
            return rows(self.view)["actor row"]

        def line(self) -> QLineEdit:
            return rows(self.view)["name"]

        def aim(self, widget) -> None:
            widget.setFocus()
            application.processEvents()

        def click_away(self) -> None:
            QTest.mouseClick(self.elsewhere, Qt.LeftButton, Qt.NoModifier,
                             self.elsewhere.rect().center())
            settle()

        def start(self) -> None:
            self.commands.clear()

        def close(self) -> None:
            self.holder.close()
            self.holder.deleteLater()
            settle()

    session.run(Command("map.object.property.set", HERO,
                        {"key": ACTOR, "value": "hero"}))
    bench = Bench()
    expect("the row renders as an editable combo on the document's value",
           (isinstance(bench.combo(), QComboBox), bench.combo().isEditable(),
            bench.combo().currentText()), (True, True, "hero"))

    def undo_and_redraw() -> None:
        session.undo()
        bench.render()
        settle()

    # GESTURE 1 -- the mouse, in the drop-down.
    bench.start()
    combo = bench.combo()
    bench.aim(combo)
    combo.showPopup()
    application.processEvents()
    popup = combo.view()
    target = popup.visualRect(combo.model().index(combo.findText("goblin"), 0))
    QTest.mouseClick(popup.viewport(), Qt.LeftButton, Qt.NoModifier,
                     target.center())
    settle()
    expect("picking from the drop-down with the MOUSE is one command",
           len(bench.commands), 1)
    expect("...and the pick is in the document", props(1).get(ACTOR),
           "goblin")
    undo_and_redraw()

    # GESTURE 2 -- the keyboard, on the closed combo. Qt emits `activated`
    # and no `editingFinished` at all for this one.
    bench.start()
    combo = bench.combo()
    bench.aim(combo)
    QTest.keyClick(combo, Qt.Key_Down)
    settle()
    expect("picking with the KEYBOARD is one command", len(bench.commands), 1)
    expect("...and that pick is in the document too", props(1).get(ACTOR),
           "slime")
    undo_and_redraw()

    # GESTURE 3 -- typed, then Enter. The noisiest of the four: Qt emits two
    # `activated` and two `editingFinished` from this single key press.
    bench.start()
    combo = bench.combo()
    bench.aim(combo)
    combo.lineEdit().selectAll()
    QTest.keyClicks(combo.lineEdit(), "wraith")
    QTest.keyClick(combo.lineEdit(), Qt.Key_Return)
    settle()
    expect("typing a value and pressing ENTER is one command",
           len(bench.commands), 1)
    expect("...and the typed value is in the document", props(1).get(ACTOR),
           "wraith")
    undo_and_redraw()

    # GESTURE 4 -- typed, then clicked away. The one a de-duplication that
    # drops `editingFinished` loses in silence.
    bench.start()
    combo = bench.combo()
    bench.aim(combo)
    combo.lineEdit().selectAll()
    QTest.keyClicks(combo.lineEdit(), "phantom")
    bench.click_away()
    expect("typing a value and CLICKING AWAY is one command",
           len(bench.commands), 1)
    expect("...and the value nobody pressed Enter on is in the document",
           props(1).get(ACTOR), "phantom")
    undo_and_redraw()

    # THE OTHER HALF of "a widget will not say the same thing twice": the
    # guard is per RENDER, not a permanent mute. The same row, set to the
    # same value again after the document has moved back, must commit again
    # -- a guard that silenced it would eat every second edit and look
    # exactly like the fault it was written to cure.
    bench.start()
    bench.aim(bench.combo())
    QTest.keyClick(bench.combo(), Qt.Key_Down)
    settle()
    undo_and_redraw()
    bench.aim(bench.combo())
    QTest.keyClick(bench.combo(), Qt.Key_Down)
    settle()
    expect("the SAME value again, after a re-render, commits again",
           (len(bench.commands), props(1).get(ACTOR)), (2, "slime"))
    undo_and_redraw()
    expect("the row is back where it started", props(1).get(ACTOR), "hero")

    # THE CONTROL. A plain text row commits through the same path and has
    # only ever had one signal, so it must count ONE -- and the counter is
    # proved able to say two by making a second real edit.
    bench.start()
    line = bench.line()
    bench.aim(line)
    line.selectAll()
    QTest.keyClicks(line, "champion")
    bench.click_away()
    expect("CONTROL: one gesture on a plain text row is one command",
           (len(bench.commands), obj(1).name), (1, "champion"))
    line = bench.line()
    bench.aim(line)
    line.selectAll()
    QTest.keyClicks(line, "paladin")
    bench.click_away()
    expect("...and the counter can see a SECOND command when there is one",
           (len(bench.commands), obj(1).name), (2, "paladin"))
    session.undo()
    session.undo()
    bench.render()
    settle()
    expect("two undos put the name back", obj(1).name, "hero")
    expect("nothing modal through any gesture", modals(), [])
    bench.close()

    # ------------------------------------------------------------------
    print()
    print("9. the same gesture through the REAL Inspector dock: one commit, "
          "ONE Ctrl+Z")
    # ------------------------------------------------------------------
    # The layer above, which is where this was actually costing the author.
    # The isolated bench proves the widget; this proves the dock the widget
    # is mounted in, with the editor's own undo doing the reversing.
    dock_window = EditorWindow(session)
    dock_window.settings = EditorSettings(FakeStore())
    dock_window.show()
    settle()
    dock_window.selection.select(HERO)
    settle()

    form = rows(dock_window.inspector.view)
    klass = form["class"]
    expect("the Inspector renders the class as an editable combo",
           (isinstance(klass, QComboBox), klass.isEditable()), (True, True))
    was_class = obj(1).type

    before = len(session.stream.done)
    klass.setFocus()
    application.processEvents()
    klass.lineEdit().selectAll()
    QTest.keyClicks(klass.lineEdit(), "Chest")
    QTest.keyClick(klass.lineEdit(), Qt.Key_Return)
    settle()
    pushed = session.stream.done[before:]
    expect("one commit in the dock is ONE undo step",
           [transaction.commands[0].verb for transaction in pushed],
           ["map.object.set"])
    expect("...and it reached the document", obj(1).type, "Chest")
    # THE KEYSTROKE ITSELF, not the method behind it: `undo_action` is what
    # Ctrl+Z is bound to, and a disabled action would trigger nothing.
    expect("the window's Undo really is Ctrl+Z, and it is live",
           (dock_window.undo_action.shortcut() ==
            QKeySequence(QKeySequence.Undo), dock_window.undo_action.isEnabled()),
           (True, True))
    dock_window.undo_action.trigger()
    settle()
    expect("ONE Ctrl+Z restores the previous value", obj(1).type, was_class)

    # The same, for the text row in the same dock -- where the second command
    # came from the rebuild re-parenting the widget that had just spoken.
    before = len(session.stream.done)
    field = rows(dock_window.inspector.view)["name"]
    field.setFocus()
    application.processEvents()
    field.selectAll()
    QTest.keyClicks(field, "warden")
    QTest.keyClick(field, Qt.Key_Return)
    settle()
    expect("a text row in the dock is ONE undo step as well",
           (len(session.stream.done) - before, obj(1).name), (1, "warden"))
    dock_window.undo_action.trigger()
    settle()
    expect("...and one Ctrl+Z reaches it", obj(1).name, "hero")

    # THE COUNTER, PROVED ABLE TO SAY TWO in this frame too: two real edits
    # must push two transactions, or "exactly one" above is a constant.
    before = len(session.stream.done)
    for typed in ("first", "second"):
        field = rows(dock_window.inspector.view)["name"]
        field.setFocus()
        application.processEvents()
        field.selectAll()
        QTest.keyClicks(field, typed)
        QTest.keyClick(field, Qt.Key_Return)
        settle()
    expect("two edits in the dock are two undo steps",
           (len(session.stream.done) - before, obj(1).name), (2, "second"))
    dock_window.undo_action.trigger()
    dock_window.undo_action.trigger()
    settle()
    expect("...and two Ctrl+Z put both back", obj(1).name, "hero")
    expect("no modal anywhere in the dock either", modals(), [])
    dock_window.close()
    dock_window.deleteLater()
    settle()

finally:
    shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print(f"FAILED: {failures}")
    sys.exit(1)
print("entity editing screen OK")
