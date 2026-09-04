"""One entity, on one screen: what it is, where it is, and what it does.

Opened when an object is created or double-clicked, and aimed at exactly one
`map:*/layer:*/object:*` scope. It is the human-interactive face of the three
things that decide what a tmx object BECOMES at spawn -- its identity and
placement, its `pyoneer_behaviors` list with the parameters that list reads,
and the actors row it names -- which until now were three separate docks a
selection had to be steered through one tab at a time.

NOTHING HERE IS NEW MACHINERY
-----------------------------
Every part of this window already existed and is EMBEDDED rather than
rebuilt, because a second renderer drifts from the first in silence:

    identity / placement / properties   `editor.core.inspect.describe`
    the behavior checklist and params   `editor.core.behavior_view`
    the widgets for both                `editor.ui.fields.InspectionView`
    the verbs every edit becomes        map.object.set, map.object.move,
                                        map.object.property.set / .remove

So this module contributes a FRAME and two compositions: it lifts
`pyoneer_actor` out of the generic Properties list into a row that offers the
actual rows of the actors table, and it commits the field the author is still
typing in before the window goes away. That is all.

WHY THERE IS NO SAVE BUTTON, AND WHY CLOSING IS STILL SAFE
----------------------------------------------------------
The author asked that closing this window save the entity. Taken literally
that would mean a Save button and a window that holds edits until it is
pressed -- and this editor cannot honour that shape without lying, because
every change here is already a `Command` applied through the session's single
stream the moment it is made. It is in the document, in the History panel and
under Ctrl+Z before the window is closed. A Save button would either do
nothing at all, or would have to mean "write the .tmx to disk", which is
Ctrl+S and is not this window's decision to make on the author's behalf.

Held in substance, then, rather than in form: NOTHING MAY BE LOST ON GOING
AWAY. There is exactly one way it could be, and it is the reason
`commit_in_flight` exists. `InspectionView` commits a text field on
`editingFinished` -- focus leaving it, or Enter -- so a value that has been
TYPED and not yet left is held in a widget and nowhere else.

Which of the three ways this window goes away actually needs that was
measured, not assumed. A plain `close()` does not: hiding a window clears
the focus inside it, and Qt emits `editingFinished` for any focus-out that
is not a popup, so the value commits itself. The other two hand out no
focus-out at all, because they DESTROY the field rather than defocusing it:

    re-aiming at another object   `set_scope` throws the whole form away
    quitting the editor           this is a child window, so the main
                                  window's close destroys it without ever
                                  sending it a close event of its own

Both were confirmed by stubbing `commit_in_flight` to return False and
watching exactly those two assertions in
`tools/check_object_editor.py` go red while the plain close stayed green.
So this is called on all three paths -- one of them redundantly, and
deliberately: which one is redundant depends on a Qt version and a window
manager, and the cost of calling it when it was not needed is nothing.

The alternative answer -- make the whole window one transaction, so one
Ctrl+Z takes the entire session of edits back -- is defensible, and it is
rejected on purpose: this window would then be the only place in the editor
where an edit is not durable until something else happens, and undo would
mean a different amount here than in the Inspector, the Behaviors dock and
the Database, which all edit these same objects through these same verbs.

WHAT IT DOES, THIRD: WHICH SCRIPT IT RUNS
-----------------------------------------
The author looked here for scripting and did not find it -- *"I still don't
see any entity actions, scripting, or event-flow control in the entity
editing screen"* -- so the door is here, at the bottom, where the two other
"what does it DO" halves already are.

The row is thin on purpose. It offers the scripts that exist, opens the
event screen on the one chosen, and creates a new one; everything a script
SAYS is authored in `editor/ui/script_editor.py`, because a second surface
for the same document would be a second set of rules for what a page may
hold. `pyoneer_script` is lifted out of the generic Properties list for the
same reason `pyoneer_actor` is: that list renders every property as an
untyped text box, and a script id typed into one is a spawn-time exception
naming this object.

IT IS NOT MODAL, AND IT MUST NEVER BECOME MODAL
-----------------------------------------------
`show()`, never a blocking call. The map has to stay visible and clickable
while an entity is being authored -- moving it, looking at what it stands
next to -- and a modal would also hang the headless checks (law 13), which
is why `tools/check_editor_ui.py` enrols every `editor/ui/*.py` by
`os.listdir` and fails on any blocking call it finds here.

There is exactly ONE dialog, and it is held as `self.ask` so a check can
replace it: naming a new script. That is genuinely the author's decision
and cannot be made for them -- a script id is the file stem, the scope and
what another script's `call` addresses it by, and there is no rename verb
because the id IS the address. Every other gesture here opens nothing.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from editor.core import event_script
from editor.core.behavior_view import (
    describe_behaviors,
    object_at,
    strip_vocabulary,
)
from editor.core.commands import Command
from editor.core.inspect import Field, Inspection, Section, describe
from editor.core.scope import Scope
from editor.ui.ask import ask_form
from editor.ui.behavior_panel import IS_WIRED
from editor.ui.fields import InspectionView
from editor.ui.script_editor import SCRIPT, one_line

from scripts.game.behavior.base import ACTOR
from scripts.loaders.table_file import ACTORS

#: The sentence that replaces the Save button the author expected to find.
#: It says what happened rather than what to press, because by the time it
#: is read the change is already in the command stream.
SAVES_AS_YOU_GO = (
    "Every change here is applied as you make it, as one undoable command — "
    "so there is nothing to save and closing this window keeps all of it. "
    "Ctrl+Z takes back one field; Ctrl+S writes the .tmx to disk."
)

#: The Properties section note gains this when `pyoneer_actor` is lifted out
#: of it, for the same reason `strip_vocabulary` explains itself there: a
#: property that vanishes from the list it used to be in looks like a bug.
ACTOR_MOVED = (
    f"   {ACTOR} is edited above, where the rows of the {ACTORS} table are "
    f"offered by name."
)

#: Same idiom, same sentence shape, for the script row at the bottom.
SCRIPT_MOVED = (
    f"   {SCRIPT} is edited in the Script row below, which offers the "
    f"scripts that exist and opens the event screen on one."
)

#: The empty state, and the one the author meets first. It says what a
#: script IS before it says what to press, because the word carries no
#: meaning yet for someone who has never opened one.
NO_SCRIPT_ON_OBJECT = (
    "This object runs no script. A script is what makes it answer — a line "
    "of dialogue when the action button is pressed, a gate that opens once "
    "you have paid, a chest that only gives its contents once. Press New… "
    "to write one, or pick a script another object already uses."
)

#: What the row says once it has one. `%s` is the script id.
RUNS_SCRIPT = (
    "Pressed with the action button, this object runs the first page of "
    "%r whose conditions pass. Edit… opens it."
)


_FOOTER_STYLE = ("color: palette(mid); font-size: 11px; padding: 4px 2px;")

_BANNER_STYLE = ("background: rgba(120, 180, 255, 30); "
                 "border-left: 3px solid rgb(120, 180, 255); "
                 "padding: 7px 9px; font-size: 11px;")

_PROBLEM_STYLE = ("background: rgba(255, 120, 120, 40); "
                  "border-left: 3px solid rgb(255, 120, 120); "
                  "padding: 6px 9px; font-size: 11px;")


class ObjectEditor(QMainWindow):
    """The entity editing screen, aimed at one object scope at a time."""

    command_requested = Signal(object)      # a Command, for the window to run
    script_requested = Signal(str)          # a script id, for the event screen

    def __init__(self, session, scope: Scope, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._scope = scope
        # The one dialog this window may open, held so a check can replace
        # it: naming a NEW script. See the module docstring -- a script id
        # is the file stem, the scope and what another script's `call`
        # addresses it by, so it cannot be minted for the author.
        self.ask = ask_form
        #: True while `refresh` is replacing the forms. See `__on_command`:
        #: a command that arrives during a rebuild came from a widget being
        #: torn down, never from the author.
        self.__rebuilding = False
        #: The command last sent, until the next refresh from anywhere else
        #: forgets it. The other half of the same defence -- see
        #: `__on_command`.
        self.__last: tuple | None = None
        # A real top-level window rather than a panel stapled to the editor,
        # exactly as the Database and the tile importer are: the map stays
        # visible and reachable while an entity is being authored.
        self.setWindowFlag(Qt.Window, True)
        self.resize(940, 660)

        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)

        split = QSplitter(Qt.Horizontal)

        # LEFT: what the object IS and where it is -- the Inspector's own
        # description, with the behavior vocabulary taken out (it is authored
        # on the right, and two doors onto one property where only one
        # validates is the same thing as no validation).
        self.object_view = InspectionView(show_header=True, show_sources=False)
        self.object_view.command_requested.connect(self.__on_command)
        split.addWidget(self.object_view)

        # RIGHT: what it DOES. The behavior checklist verbatim, banner and
        # refusal label included, because those two are the panel's argument
        # and not its decoration.
        right = QWidget()
        stack = QVBoxLayout(right)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        self.banner = QLabel(IS_WIRED)
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(_BANNER_STYLE)
        stack.addWidget(self.banner)
        self.behavior_view = InspectionView(show_header=False,
                                            show_sources=False)
        self.behavior_view.command_requested.connect(self.__on_command)
        stack.addWidget(self.behavior_view, 1)
        # An emitter that refuses to build a command returns None, which the
        # view treats as a silent no-op -- right for "nothing changed", wrong
        # for "your value was rejected". Its text is set and it is never
        # rebuilt, so neither Qt trap applies to it.
        self.problem = QLabel("")
        self.problem.setWordWrap(True)
        self.problem.setStyleSheet(_PROBLEM_STYLE)
        self.problem.hide()
        stack.addWidget(self.problem)
        split.addWidget(right)

        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        column.addWidget(split, 1)
        self.splitter = split

        # WHAT IT DOES, THIRD: WHICH SCRIPT IT RUNS. A row rather than a
        # form field, because two of the three controls are gestures and an
        # `InspectionView` renders values -- and because the note under it
        # is the empty state the author meets first.
        column.addWidget(self.__build_script_row())

        self.footer = QLabel(SAVES_AS_YOU_GO)
        self.footer.setWordWrap(True)
        self.footer.setStyleSheet(_FOOTER_STYLE)
        column.addWidget(self.footer)
        self.setCentralWidget(holder)

        # Ctrl+Z has to work HERE too, for the same reason the Database
        # duplicates it: Qt shortcuts are per-window, and a promise that only
        # works in the OTHER window is worse than no promise. The stream is
        # still the parent's -- these forward, they do not undo.
        for text, sequence, name in (("&Undo", QKeySequence.Undo, "undo"),
                                     ("&Redo", QKeySequence.Redo, "redo"),
                                     ("&Save", QKeySequence.Save, "save")):
            action = QAction(text, self)
            action.setShortcut(sequence)
            action.triggered.connect(
                lambda _checked=False, n=name: self.__forward(n))
            self.addAction(action)

        self.refresh()

    # -- aiming ------------------------------------------------------------

    @property
    def scope(self) -> Scope:
        """The object this window is currently editing."""
        return self._scope

    def set_scope(self, scope: Scope) -> None:
        """Aim this window at another object.

        ONE WINDOW, RE-AIMED, never a second one: a window per object is a
        pile of look-alike windows over the same map, each holding a scope
        that an undo can invalidate under it.

        The in-flight field is committed FIRST. Re-aiming discards the form
        exactly as closing does, so it is the same hazard: a value typed into
        the old object and not yet left would otherwise be thrown away by a
        double-click on the next one.
        """
        if scope == self._scope:
            self.refresh()
            return
        self.commit_in_flight()
        self._scope = scope
        self.refresh()

    # -- rendering ---------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild both halves from the document.

        Both describers are contractually incapable of raising -- a selection
        goes stale constantly, and the answer is a message in the form rather
        than a traceback through the event loop.
        """
        # Cleared BEFORE describing, never after: describing installs the
        # emitters that call `report`, and one firing during this refresh
        # must not have its message wiped.
        self.report("")
        # Forgotten here, and RE-REMEMBERED by `__on_command` after its own
        # refresh returns. So the memory covers exactly the window between a
        # command and the next time this form is rebuilt by anything else --
        # an undo, a re-aim, a sibling panel's edit -- which is the only span
        # in which an identical command cannot be a second real edit.
        self.__last = None
        # Flagged across BOTH halves, and released in a `finally`: a
        # describer that raised while the flag was up would leave this window
        # permanently unable to accept an edit, which is a worse failure than
        # the one the flag prevents.
        self.__rebuilding = True
        retiring = [(view, view.widget())
                    for view in (self.object_view, self.behavior_view)]
        try:
            self.object_view.show_inspection(self.__describe_object())
            self.behavior_view.show_inspection(
                describe_behaviors(self.session, self._scope,
                                   on_error=self.report))
            for view, body in retiring:
                if body is not None and body is not view.widget():
                    self.__silence(body)
            # Inside the flag as well: refilling the combo is exactly the
            # shape that emits a signal nobody asked for, and its own
            # `blockSignals` is belt to this braces.
            self.refresh_script()
        finally:
            self.__rebuilding = False
        self.setWindowTitle(self.__title())

    @staticmethod
    def __silence(body: QWidget) -> None:
        """A form that has been replaced does not speak again.

        `InspectionView` retires the body it replaces by re-parenting it,
        hiding it and calling `deleteLater` -- which does not run until an
        event loop unwinds. So for the rest of the gesture, and often longer,
        the old form is alive, still connected, and still able to emit
        `editingFinished` the moment Qt takes the focus off it. That lands
        the command it has already sent a SECOND time, against a `Field`
        describing the value from before, and one Ctrl+Z then undoes only
        half of one edit.

        `__on_command` drops the copy that arrives DURING the rebuild; this
        stops the one that arrives after it, which is the same defect on a
        longer fuse -- measured, an actors row chosen from the combo landed
        twice with only the first guard in place.

        The body is identified by having BEEN this view's widget rather than
        by walking the scroll area's children, which are Qt's own viewport
        and scrollbar containers as well; blocking one of those would break
        scrolling. `blockSignals` is per-object and not recursive, so every
        descendant is silenced too.  #TAG:a_retired_form_does_not_speak
        """
        body.blockSignals(True)
        for inner in body.findChildren(QWidget):
            inner.blockSignals(True)

    def report(self, message: str) -> None:
        """Show why an edit produced no command, or clear it."""
        self.problem.setText(message)
        self.problem.setVisible(bool(message))

    def __title(self) -> str:
        _layer, obj = object_at(self.session, self._scope)
        if obj is None:
            return f"Object — {self._scope}"
        name = obj.name or f"object {obj.id}"
        return f"{name} — {self._scope.get('layer')} — " \
               f"map:{self._scope.get('map')}"

    def __describe_object(self) -> Inspection:
        inspection = self.__strip_script(
            strip_vocabulary(describe(self.session, self._scope)))
        row = self.__actor_field()
        if row is None:
            return inspection
        for section in inspection.sections:
            if section.title == "Properties":
                # ONE DOOR. The generic list renders `pyoneer_actor` as an
                # untyped text box, and a row id typed into it is a spawn-time
                # exception naming this object; the row below offers the ids
                # that exist.
                kept = [f for f in section.fields if f.key != ACTOR]
                if len(kept) != len(section.fields):
                    section.fields = kept
                    section.note += ACTOR_MOVED
        inspection.sections.insert(1, self.__actor_section(row))
        return inspection

    def __strip_script(self, inspection: Inspection) -> Inspection:
        """Take `pyoneer_script` out of the generic Properties list.

        Same argument as `ACTOR_MOVED`, one property along: that list
        renders every property as an untyped text box, and a script id
        typed into one is a spawn-time exception naming this object. The
        row at the bottom offers the scripts that exist and opens them.
        """
        for section in inspection.sections:
            if section.title != "Properties":
                continue
            kept = [f for f in section.fields if f.key != SCRIPT]
            if len(kept) != len(section.fields):
                section.fields = kept
                section.note += SCRIPT_MOVED
        return inspection

    # -- the actors row ----------------------------------------------------

    def __actor_rows(self) -> tuple[str, ...]:
        """Every row id the actors table holds, or none when it holds none.

        `has_table` rather than a caught exception: a project with no actors
        table is an ordinary state -- most maps have one before they have any
        actors -- and swallowing the other failures would hide them.
        """
        project = self.session.project
        if not project.has_table(ACTORS):
            return ()
        return tuple(sorted(project.table(ACTORS).rows))

    def __actor_field(self) -> Field | None:
        """The `pyoneer_actor` row, offered as the ids that exist.

        None when there is nothing to say: no actors table AND no row named
        by this object. Editable free text as well as a list, because a row
        may be authored in the Database after this object names it -- the
        engine raises at load either way and the note says so first.
        """
        _layer, obj = object_at(self.session, self._scope)
        if obj is None:
            return None
        current = str(obj.properties.as_dict().get(ACTOR, "") or "").strip()
        rows = self.__actor_rows()
        if not rows and not current:
            return None
        choices = [""] + list(rows)
        if current and current not in choices:
            choices.append(current)
        scope = self._scope

        def emit(value: Any) -> Command | None:
            wanted = str(value).strip()
            if wanted == current:
                return None
            if not wanted:
                # Blank means "names no actor", which is the ABSENCE of the
                # property and not an empty one: `table_file.row_id` raises
                # on a present-and-empty value, naming the property rather
                # than the row -- the confusing half of the same message.
                return (Command("map.object.property.remove", scope,
                                {"key": ACTOR}) if current else None)
            return Command("map.object.property.set", scope,
                           {"key": ACTOR, "value": wanted})

        return Field(
            ACTOR, "actor row", "choice", current, choices=tuple(choices),
            doc=f"the id of a row in the {ACTORS} table. The engine reads it "
                f"at spawn, and a behavior parameter declared "
                f"source={ACTORS!r} answers from that row before its own "
                f"default. Blank removes the property.",
            emit=emit)

    def __actor_section(self, row: Field) -> Section:
        current = str(row.value)
        rows = self.__actor_rows()
        if not rows:
            note = (f"this project has no {ACTORS} table yet — the Database "
                    f"window creates one, and until it does a row named here "
                    f"raises at map load.")
        elif current and current not in rows:
            note = (f"{current!r} is not a row in the {ACTORS} table "
                    f"({len(rows)} rows). The engine raises at map load "
                    f"naming this object.")
        else:
            note = (f"which row of the {ACTORS} table this entity's "
                    f"parameters read from")
        return Section("Actor", [row], note=note)

    # -- which script it runs ----------------------------------------------

    def __build_script_row(self) -> QWidget:
        """The door to the event screen, on the screen the author looked at.

        Three controls and a sentence. The combo offers the scripts that
        EXIST -- a script id typed free-hand is a spawn-time exception
        naming this object, which is the same argument that lifted
        `pyoneer_actor` out of the generic Properties list.
        """
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(4)
        row.addWidget(QLabel("Script"))
        self.script_box = QComboBox()
        self.script_box.setMinimumWidth(220)
        # `activated` and NOT `currentIndexChanged`: Qt emits the latter
        # when the list is refilled, so a rebuild would write the value it
        # had just read back into the document as a fresh command.
        self.script_box.activated.connect(
            lambda _index: self.choose_script(self.script_box.currentText()))
        row.addWidget(self.script_box)
        self.script_new = QPushButton("New…")
        self.script_new.setToolTip(
            "Write a new event script and give it to this object. You "
            "choose its name: that name is the file, the address, and what "
            "another script's `call` names.")
        self.script_new.clicked.connect(self.new_script)
        row.addWidget(self.script_new)
        self.script_edit = QPushButton("Edit…")
        self.script_edit.setToolTip("Open the event screen on this script.")
        self.script_edit.clicked.connect(self.open_script)
        row.addWidget(self.script_edit)
        row.addStretch(1)

        self.script_note = QLabel(NO_SCRIPT_ON_OBJECT)
        self.script_note.setWordWrap(True)
        self.script_note.setStyleSheet(_FOOTER_STYLE)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(holder)
        column.addWidget(self.script_note)
        wrapper = QWidget()
        wrapper.setLayout(column)
        return wrapper

    def script_names(self) -> tuple[str, ...]:
        """Every script in this project, or none when the library refuses.

        A library that will not load is REPORTED rather than swallowed: one
        script with a stray comma stops the whole directory being read, and
        an author whose combo silently emptied would go looking for the
        wrong bug.
        """
        try:
            library = event_script.scripts_of(self.session.project)
            return tuple(library.names())
        except Exception as exc:                                # noqa: BLE001
            self.report(one_line(exc))
            return ()

    def current_script(self) -> str:
        """The `pyoneer_script` this object names, or ""."""
        _layer, obj = object_at(self.session, self._scope)
        if obj is None:
            return ""
        return str(obj.properties.as_dict().get(SCRIPT, "") or "").strip()

    def refresh_script(self) -> None:
        """Refill the row from the document. Never emits a command."""
        current = self.current_script()
        names = self.script_names()
        choices = [""] + [n for n in names]
        if current and current not in choices:
            # Authored, and gone -- an undo took the script back, or it was
            # deleted. Kept in the list so the row shows what the object
            # actually says, with the note explaining it.
            choices.append(current)
        self.script_box.blockSignals(True)
        self.script_box.clear()
        self.script_box.addItems(choices)
        self.script_box.setCurrentText(current)
        self.script_box.blockSignals(False)
        self.script_edit.setEnabled(bool(current))
        if not current:
            self.script_note.setText(NO_SCRIPT_ON_OBJECT)
        elif current not in names:
            self.script_note.setText(
                "%r is not a script in this project (%d exist). The engine "
                "raises at map load naming this object; pick one that "
                "exists, or press New… to write it."
                % (current, len(names)))
        else:
            self.script_note.setText(RUNS_SCRIPT % current)

    def choose_script(self, wanted: str) -> None:
        """Give this object a script, or take it away. One command."""
        wanted = str(wanted).strip()
        current = self.current_script()
        if wanted == current:
            return
        if not wanted:
            # Blank means "runs no script", which is the ABSENCE of the
            # property rather than an empty one -- the same distinction the
            # actor row makes, and for the same reason: a present-and-empty
            # value is a load-time error blaming the property.
            if current:
                self.__on_command(Command("map.object.property.remove",
                                          self._scope, {"key": SCRIPT}))
            return
        self.__on_command(Command("map.object.property.set", self._scope,
                                  {"key": SCRIPT, "value": wanted}))

    def new_script(self) -> None:
        """Ask for an id, create the script, and give it to this object.

        ONE transaction: `script.create` and the property that names it go
        out as a list, so one Ctrl+Z takes back the whole gesture rather
        than leaving an object pointing at a script that no longer exists.
        """
        try:
            library = event_script.scripts_of(self.session.project)
        except Exception as exc:                                # noqa: BLE001
            self.report(one_line(exc))
            return
        answer = self.ask(
            self, "New event script",
            [Field("id", "id", "str", "",
                   doc="letters, digits, '_' and '-'. It becomes the file "
                       "name and the address, and it never changes."),
             Field("title", "title", "str", "",
                   doc="a human label; optional")],
            ok_label="Create",
            note="A script is shared: several objects can name the same "
                 "one, and each keeps its own `local.` state.")
        if not answer:
            return
        wanted = str(answer.get("id", "")).strip()
        if not wanted:
            self.report("a script needs an id — it is the file name and the "
                        "address this object will name")
            return
        if library.has(wanted):
            self.report("there is already a script called %r; pick it from "
                        "the list instead" % wanted)
            return
        self.__on_command([
            Command("script.create", Scope.of(("script", wanted)),
                    {"title": str(answer.get("title", "")).strip()}),
            Command("map.object.property.set", self._scope,
                    {"key": SCRIPT, "value": wanted}),
        ])
        self.script_requested.emit(wanted)

    def open_script(self) -> None:
        """Open the event screen on this object's script."""
        current = self.current_script()
        if not current:
            self.report("this object runs no script yet — press New… to "
                        "write one, or pick one from the list")
            return
        self.script_requested.emit(current)

    # -- the one thing that could be lost ----------------------------------

    def commit_in_flight(self) -> bool:
        """Push the field the author is still inside into the document.

        Returns True when a field was asked to finish. THE ONE WAY WORK CAN
        BE LOST HERE: `InspectionView` commits a text field on
        `editingFinished`, which Qt emits when focus leaves it or Enter is
        pressed. A form that is DESTROYED rather than defocused -- re-aimed
        at another object, or taken down with the editor -- emits neither, so
        a value typed and not yet left dies in the widget. The module
        docstring names which paths those are and how it was measured.

        The field's own signal is emitted rather than its focus being taken
        away, deliberately. `clearFocus()` delivers a focus-out only to a
        widget that really holds the application's focus, which needs this
        window to be ACTIVE -- so a commit built on it would work while a
        developer watches and not when a window manager takes the focus away
        first. `editingFinished` is the signal the view already listens to,
        so this goes through the same emitter, the same refusal and the same
        verb as pressing Enter would.

        Committing rebuilds the form, and the widget that just spoke is
        retired by that rebuild -- where `__silence` stops it saying the same
        thing again. Nothing more is needed here: a commit that produced no
        command rebuilds nothing, and a widget still in the live form has
        said its piece exactly once.
        """
        focus = self.focusWidget()
        # `focusWidget()` is this window's own last-focused child rather than
        # the application's, so it answers correctly for a window that is not
        # the active one. Invisible means a previous rebuild already retired
        # it, and it is not what the author is typing in.
        if focus is None or not focus.isVisible():
            return False
        if isinstance(focus, QAbstractSpinBox):
            # A spin box with keyboard tracking off holds the typed digits as
            # TEXT until something interprets them; `interpretText` is what
            # its own focus-out would call.
            focus.interpretText()
        elif isinstance(focus, QLineEdit):
            # An editable QComboBox's focus widget is its internal QLineEdit,
            # so this covers the combo rows too -- which is the shape the
            # actor row and the object's class are rendered in.
            focus.editingFinished.emit()
        else:
            return False
        return True

    def closeEvent(self, event) -> None:                        # noqa: N802
        """Closing saves, by having nothing left to save.

        Every edit is already in the command stream; the one exception is the
        field being typed into right now.  #TAG:closing_commits_the_field_in_flight
        """
        self.commit_in_flight()
        super().closeEvent(event)

    # -- emitting ----------------------------------------------------------

    def __on_command(self, command: Any) -> None:
        """One edit, on its way to the window's single mutation point.

        THE SECOND COMMAND IS DROPPED, and both ways it arrives were
        measured here rather than reasoned about. One field can produce two
        identical commands, because a `Field`'s captured value is a snapshot
        and a widget that has already spoken can speak again before it is
        freed:

          * DURING the rebuild that the first command triggers. Retiring a
            form re-parents it, which makes Qt clear the focus inside it and
            emit `editingFinished` from the widget that just committed.
            Caught by the flag: a command arriving while a form is being
            replaced is never the author's, whose gestures reach a form that
            is on screen.
          * IMMEDIATELY AFTER IT, from a second slot on the SAME emission.
            `QComboBox` connects its own line edit's `editingFinished` to a
            handler that emits `activated` when the typed text names an item
            -- and `InspectionView` listens to both, so committing one combo
            row runs its emitter twice with one stale snapshot. Measured: an
            actors row chosen by name landed as two `map.object.property.set`
            commands, and one Ctrl+Z undid only the second. Blocking signals
            cannot reach that one; an emission already under way delivers to
            every slot it started with.

        The second guard is therefore about the COMMAND rather than about the
        widget: between a command and the next rebuild from any other source,
        the document already holds what a repeat of it asks for, so an
        identical repeat is a duplicate by construction and never a second
        real edit.
        """
        if self.__rebuilding:
            return
        # A list is one gesture that needs more than one verb -- creating a
        # script AND naming it on this object. It travels as a list so the
        # window runs it as ONE transaction and one Ctrl+Z takes the whole
        # gesture back; the duplicate guard has to read it the same way.
        commands = command if isinstance(command, list) else [command]
        signature = tuple((c.verb, str(c.scope), repr(c.args))
                          for c in commands)
        if signature == self.__last:
            return
        # The window applies it -- there is one mutation point and this is not
        # it. Refreshed afterwards either way: on success the document has
        # moved, and on a rejection the form must be rebuilt from the document
        # rather than left showing the value that was refused.
        self.command_requested.emit(command)
        self.refresh()
        # AFTER the refresh, which clears it. The copy this guards against
        # arrives once this call has returned.
        self.__last = signature

    def __forward(self, name: str) -> None:
        call = getattr(self.parent(), name, None)
        if callable(call):
            call()
