"""Render an `Inspection` as an editable form.

Shared by the Inspector dock and the Database window, which need the same
thing in different frames: a list of typed fields where editing one emits a
Command. Two renderers would drift, and the drift would be silent -- a
field editable in one place and not the other looks like a bug in the
document rather than in the UI.

The view emits `command_requested`; it never applies anything itself. That
keeps the "one mutation point" rule intact all the way down to the widget
that a spin box lives in.

Forms rebuild wholesale rather than diffing. A dozen fields is
microseconds, and it removes the whole class of bug where a stale widget
keeps editing an object that an undo has already deleted.
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from editor.core.commands import Command
from editor.core.inspect import Field, Inspection
from editor.ui.ask import ask_form

PROPERTY_TYPES = ("str", "int", "float", "bool")
BLANK: dict[str, Any] = {"str": "", "int": 0, "float": 0.0, "bool": False}


class InspectionView(QScrollArea):
    """A scrollable, editable rendering of one Inspection."""

    command_requested = Signal(object)      # Command
    reveal_requested = Signal(str)          # a repo-relative path

    def __init__(self, parent: QWidget | None = None, *,
                 show_header: bool = True, show_sources: bool = True):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.show_header = show_header
        self.show_sources = show_sources
        self.inspection: Inspection | None = None
        self.ask = ask_form          # the dialog seam; see editor/ui/ask.py

        self.__body = QWidget()
        self.__layout = QVBoxLayout(self.__body)
        self.__layout.setContentsMargins(8, 8, 8, 8)
        self.__layout.setSpacing(6)
        self.setWidget(self.__body)

    # -- rendering ---------------------------------------------------------

    def show_inspection(self, inspection: Inspection) -> None:
        """Rebuild the form.

        The whole body is REPLACED rather than emptied, because clearing a
        layout with `widget.setParent(None)` does not detach a widget -- it
        promotes it to a **top-level window**. That makes one orphaned window
        per row on every refresh (about twenty flashing on each Ctrl+Z), and
        they accumulate: `deleteLater()` only runs when the event loop
        unwinds to the level that queued it. Measured, 59 top-level widgets
        at rest became 85 after a single undo and stayed there.

        `QScrollArea.setWidget()` deletes the widget it replaces without ever
        detaching the children, so nothing is momentarily parentless and
        nothing leaks.
        """
        self.inspection = inspection
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.__body, self.__layout = body, layout

        if self.show_header:
            self.__header(inspection)
        if inspection.error:
            self.__note(inspection.error, size=12)
        for section in inspection.sections:
            self.__section(section, inspection)
        if self.show_sources:
            self.__sources(inspection)
        layout.addStretch(1)

        # Retire the old body WITHOUT deleting it synchronously.
        #
        # `setWidget()` alone would delete it immediately, and this method is
        # reached from a field's own signal -- toggling the `renders`
        # checkbox emits a command, which refreshes, which would free the
        # checkbox while its `toggled` signal is still on the stack. Qt then
        # returns into freed memory: measured as a hard
        # STATUS_HEAP_CORRUPTION (0xC0000374) crash of the whole editor.
        #
        # deleteLater() defers the free until the event loop unwinds, which
        # is exactly when it is safe. Re-parenting to `self` first keeps it
        # from becoming a top-level window in the meantime.
        old = self.takeWidget()  # #TAG:qt_takewidget_sequence
        if old is not None:
            old.setParent(self)
            old.hide()
            old.deleteLater()
        self.setWidget(body)

    def __header(self, inspection: Inspection) -> None:
        heading = QLabel(inspection.heading)
        heading.setStyleSheet("font-size: 15px; font-weight: 600;")
        heading.setWordWrap(True)
        self.__layout.addWidget(heading)
        if inspection.subheading:
            self.__note(inspection.subheading, size=12)
        scope = QLabel(str(inspection.scope))
        scope.setStyleSheet("color: palette(mid); font-size: 11px;")
        scope.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.__layout.addWidget(scope)

    def __note(self, text: str, *, size: int = 11) -> None:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: palette(mid); font-size: {size}px;")
        self.__layout.addWidget(label)

    def __section(self, section, inspection: Inspection) -> None:
        title = QLabel(section.title.upper())
        title.setStyleSheet("color: palette(mid); font-size: 10px; "
                            "font-weight: 700; padding-top: 8px;")
        self.__layout.addWidget(title)

        if section.note:
            self.__note(section.note)

        if not section.fields:
            self.__note("none")
        else:
            holder = QWidget()
            form = QFormLayout(holder)
            form.setContentsMargins(0, 2, 0, 2)
            form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            for entry in section.fields:
                form.addRow(self.__label_for(entry), self.__editor_for(entry))
            self.__layout.addWidget(holder)

        if section.title == "Properties" and inspection.scope.kind == "object":
            add = QPushButton("+ property")
            add.clicked.connect(self.__on_add_property)
            self.__layout.addWidget(add, alignment=Qt.AlignLeft)

    def __label_for(self, entry: Field) -> QLabel:
        label = QLabel(entry.label)
        tip = entry.doc
        if entry.blocked_reason:
            tip = (f"{tip}\n\nRead-only: {entry.blocked_reason}" if tip
                   else f"Read-only: {entry.blocked_reason}")
            label.setStyleSheet("color: palette(mid);")
        if tip:
            label.setToolTip(tip)
        return label

    # -- editors -----------------------------------------------------------

    def __editor_for(self, entry: Field) -> QWidget:
        if not entry.editable:
            value = QLabel(str(entry.value))
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            if entry.blocked_reason:
                value.setStyleSheet("color: palette(mid); font-style: italic;")
                value.setToolTip(entry.blocked_reason)
            return value

        widget = self.__build_editor(entry)
        if entry.doc:
            widget.setToolTip(entry.doc)
        return self.__with_remove(entry, widget) if entry.removable else widget

    def __build_editor(self, entry: Field) -> QWidget:
        if entry.kind == "bool":
            box = QCheckBox()
            box.setChecked(bool(entry.value))
            box.toggled.connect(lambda v, f=entry: self.__commit(f, bool(v)))
            return box

        if entry.kind == "choice":
            combo = QComboBox()
            combo.setEditable(True)
            options = [str(o) for o in entry.choices]
            if str(entry.value) not in options:
                options.insert(0, str(entry.value))
            combo.addItems(options)
            combo.setCurrentText(str(entry.value))
            # BOTH signals, because neither is the commit on its own -- the
            # measured table is in `__says_once`, which is what makes both
            # of them safe to connect.  #TAG:one_gesture_one_command
            says = self.__says_once(entry)
            combo.activated.connect(lambda _i, c=combo: says(c.currentText()))
            combo.lineEdit().editingFinished.connect(
                lambda c=combo: says(c.currentText()))
            return combo

        if entry.kind == "int":
            spin = QSpinBox()
            spin.setRange(-2_147_483_647, 2_147_483_647)
            spin.setValue(int(entry.value or 0))
            # Without this every keystroke fires a command, so typing "120"
            # emits 1, then 12, then 120 -- three transactions and two wrong.
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda v, f=entry: self.__commit(f, int(v)))
            return spin

        if entry.kind == "float":
            spin = QDoubleSpinBox()
            spin.setRange(-1e9, 1e9)
            spin.setDecimals(3)
            spin.setValue(float(entry.value or 0.0))
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda v, f=entry: self.__commit(f, float(v)))
            return spin

        line = QLineEdit(str(entry.value if entry.value is not None else ""))
        # Same gate as the combo, for the second half of the same fault: a
        # commit rebuilds the form, and retiring the old body clears the focus
        # inside it, so the widget that just spoke emits `editingFinished`
        # again from inside the emit it caused. Measured in the real Inspector
        # dock: renaming an object pushed TWO `map.object.set` transactions.
        says = self.__says_once(entry)
        line.editingFinished.connect(lambda w=line: says(w.text()))
        return line

    def __says_once(self, entry: Field) -> Callable[[str], None]:
        """A commit for a text-bearing editor that never says the same
        thing twice.

        AN EDITABLE `QComboBox` HAS NO SINGLE COMMIT SIGNAL. Measured on this
        Qt, per gesture, as (activated, editingFinished) emissions:

            pick from the drop-down with the mouse      (1, 1)
            pick with the keyboard (Down)               (1, 0)
            type a value and press Enter                (2, 2)
            type a NEW value and click away             (0, 1)
            type an EXISTING value and click away       (1, 1)

        So connecting one of them is not an option. Dropping `activated`
        loses the drop-down pick outright: the `editingFinished` in that row
        fires when the popup takes the focus, BEFORE the pick, and carries
        the OLD text -- nothing at all is emitted afterwards. Dropping
        `editingFinished` loses a typed value that names nothing in the list
        the moment the author clicks away instead of pressing Enter, which
        is the silent-data-loss shape: no command, no error, and the form
        redraws from the document as though they had never typed.

        Connecting both is what shipped, and one gesture then emitted up to
        FOUR identical commands -- `QComboBox` re-emits `activated` from the
        very `editingFinished` this view also listens to. Every command
        after the first is an EMPTY transaction, because the document
        already holds the value, so one Ctrl+Z appeared to do nothing and
        the author learned not to trust undo.

        The de-duplication therefore lives HERE, on the widget that speaks:
        `said` is what this widget has already committed, and a repeat of it
        is not a second edit. It must not move downstream -- a verb that
        tolerates a no-op, or a stream that drops empty transactions, would
        hide this for every future caller too, and an empty transaction
        reaching the stream at all is the fault.
        """
        said = str(entry.value if entry.value is not None else "")

        def commit(text: str) -> None:
            nonlocal said
            if text == said:
                return
            # BEFORE the emit, never after. Emitting rebuilds the form
            # synchronously, and that rebuild is what makes this same widget
            # speak again -- back into this closure, from inside this call.
            said = text
            self.__commit(entry, text)

        return commit

    def __with_remove(self, entry: Field, widget: QWidget) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        row.addWidget(widget, 1)
        button = QToolButton()
        button.setText("×")
        button.setToolTip(f"remove the {entry.key!r} property")
        button.clicked.connect(lambda _c=False, f=entry: self.__remove(f))
        row.addWidget(button)
        return holder

    # -- emitting ----------------------------------------------------------

    def __commit(self, entry: Field, value: Any) -> None:
        if value == entry.value or entry.emit is None:
            return
        command = entry.emit(value)
        if command is not None:
            self.command_requested.emit(command)

    def __remove(self, entry: Field) -> None:
        if entry.remove is None:
            return
        command = entry.remove(None)
        if command is not None:
            self.command_requested.emit(command)

    def __on_add_property(self) -> None:
        """Name and type in ONE dialog.

        It was two `QInputDialog`s in a row, and cancelling the second threw
        away the name typed into the first -- the author had made one
        decision and the editor made them hold half of it across a modal
        boundary. Adding a property is one act.
        """
        if self.inspection is None:
            return
        answer = self.ask(
            self, "New property",
            [Field("key", "Name", "str", "",
                   doc="The property key as it is written into the .tmx. "
                       "Stable once anything reads it."),
             Field("kind", "Holds", "choice", PROPERTY_TYPES[0],
                   doc="What kind of value it starts with. The value itself "
                       "is edited in the form afterwards.",
                   choices=PROPERTY_TYPES)],
            ok_label="Add the property")
        if answer is None or not answer["key"]:
            return
        self.command_requested.emit(Command(
            "map.object.property.set", self.inspection.scope,
            {"key": answer["key"], "value": BLANK[answer["kind"]]}))

    # -- code links --------------------------------------------------------

    def __sources(self, inspection: Inspection) -> None:
        if not inspection.sources:
            return
        title = QLabel("CODE")
        title.setStyleSheet("color: palette(mid); font-size: 10px; "
                            "font-weight: 700; padding-top: 10px;")
        self.__layout.addWidget(title)
        self.__note("Files that own this. Opening one is read-only and cannot "
                    "affect the editor or the running game.")
        for path in inspection.sources:
            button = QPushButton(path)
            button.setStyleSheet("text-align: left; padding: 2px 6px;")
            button.setFlat(True)
            button.clicked.connect(
                lambda _c=False, p=path: self.reveal_requested.emit(p))
            self.__layout.addWidget(button)
