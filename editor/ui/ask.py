"""The two dialogs the panels are allowed to open, and the rule for both.

A dialog costs the author their gesture. It stops the hand, takes the
keyboard, and refuses to say anything until it is dismissed -- so it may
only ever carry a decision that is genuinely the author's to make.

    A dialog with no choice in it is a REPORT, and a report belongs in the
    status bar or the Problems dock, where it can be read after the fact
    and cannot interrupt a stroke.

That sentence is the whole policy. The failure it names was reported by the
author on a paint click: a 191-word modal explaining gid arithmetic, with
Yes/No buttons, for a file the editor could have written itself. Every
"Rejected", "Nothing staged", "No IDE found" and "Response arrived" box in
this tree was the same shape at lower volume -- an OK button asking to be
told that nothing happened.

So there are exactly two primitives here:

  * `ask_form` -- ONE dialog for one decision, however many fields it takes.
    Two `QInputDialog`s in a row is not two decisions, it is one decision
    the author has to hold in their head across a modal boundary, and
    cancelling the second one throws away what they typed into the first.
  * `confirm` -- a yes/no, for an action UNDO CANNOT REACH. Undo here is
    exact and byte-for-byte, so "destructive" does not mean "deletes
    something": removing a layer is destructive and recoverable, and asking
    about it is theatre. Discarding staged notes is not recoverable,
    because notes never entered the command stream. That is the line.

WHY THESE ARE FUNCTIONS AND NOT `QMessageBox` CALLS AT THE CALL SITE
--------------------------------------------------------------------
Law 13: a check must never block on a modal. `check_collision_mount` once
sat on `QMessageBox.question` for 40+ minutes with no output, which is
indistinguishable from a slow machine, and `check_all.py` grew a 600s
timeout and a HANG verdict because of it. Every panel holds these two as
INSTANCE ATTRIBUTES (`self.ask`, `self.confirm`), so a check replaces the
seam on the one widget it is driving and asserts, per panel, both that the
legitimate question is still asked and that the routine path asks nothing at
all. A hard, inline `QMessageBox` call is unreachable from a check except
by patching the class globally, which proves nothing about which path
opened it.
"""
from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from editor.core.inspect import Field


class QuickForm(QDialog):
    """One decision, every field of it on screen at once.

    Rows are `editor.core.inspect.Field`s -- the same typed row the
    Inspector renders -- so the vocabulary for "a labelled value with a
    type, a doc string and maybe a closed set of choices" is declared once
    for the whole editor.

    Two kinds are honoured, because two are all a decision needs:

        kind="choice"                a closed set; the combo is not editable
        kind="str"                   free text; a combo WITH suggestions if
                                     the field carries `choices`, otherwise
                                     a plain line edit

    OK is disabled while any text row is blank rather than accepting the
    click and returning nothing. A button that cannot act must look like it
    cannot act -- the same rule the Database's three row buttons were fixed
    under.
    """

    def __init__(self, title: str, rows: Iterable[Field],
                 parent: QWidget | None = None, *, ok_label: str = "OK",
                 note: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.rows = list(rows)
        self.editors: dict[str, QWidget] = {}

        layout = QVBoxLayout(self)
        if note:
            label = QLabel(note)
            label.setWordWrap(True)
            label.setStyleSheet("color: palette(mid);")
            layout.addWidget(label)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for entry in self.rows:
            widget = self.__editor_for(entry)
            if entry.doc:
                widget.setToolTip(entry.doc)
            self.editors[entry.key] = widget
            form.addRow(entry.label, widget)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText(ok_label)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.__sync()

    def __editor_for(self, entry: Field) -> QWidget:
        if entry.kind == "choice":
            combo = QComboBox()
            combo.addItems([str(choice) for choice in entry.choices])
            combo.setCurrentText(str(entry.value))
            return combo
        if entry.choices:
            combo = QComboBox()
            combo.setEditable(True)
            combo.addItems([str(choice) for choice in entry.choices])
            combo.setCurrentText(str(entry.value or ""))
            combo.editTextChanged.connect(lambda _t: self.__sync())
            return combo
        line = QLineEdit(str(entry.value or ""))
        line.textChanged.connect(lambda _t: self.__sync())
        return line

    def __sync(self) -> None:
        """OK is live only when every free-text row has something in it."""
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(
            all(str(v).strip() for k, v in self.value().items()
                if self.__is_text(k)))

    def __is_text(self, key: str) -> bool:
        widget = self.editors[key]
        return isinstance(widget, QLineEdit) or (
            isinstance(widget, QComboBox) and widget.isEditable())

    def value(self) -> dict[str, Any]:
        """What is typed in right now, keyed by field key."""
        answer: dict[str, Any] = {}
        for entry in self.rows:
            widget = self.editors[entry.key]
            raw = (widget.currentText() if isinstance(widget, QComboBox)
                   else widget.text())
            answer[entry.key] = raw.strip()
        return answer


def ask_form(parent: QWidget | None, title: str, rows: Iterable[Field], *,
             ok_label: str = "OK", note: str = "") -> dict[str, Any] | None:
    """Show one form and return its values, or None if it was cancelled.

    The whole interaction in one call, so a panel's handler stays readable
    and so a check can replace `self.ask` with a function that returns a
    dict and never opens a window.
    """
    dialog = QuickForm(title, rows, parent, ok_label=ok_label, note=note)
    try:
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.value()
    finally:
        # Parented, so it is not a top-level orphan -- but it would outlive
        # the call until the next garbage collection, and this tree counts
        # widgets to catch exactly that class of leak.
        dialog.deleteLater()


def confirm(parent: QWidget | None, title: str, question: str) -> bool:
    """A yes/no for something undo cannot take back. See the module docstring
    before adding a caller: there is currently ONE in the whole editor."""
    return QMessageBox.question(parent, title, question) == QMessageBox.Yes
