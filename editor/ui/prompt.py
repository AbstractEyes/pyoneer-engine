"""The prompt strip -- a comment box at the bottom of every panel.

The idea this editor is organised around: you review the project the way
you review a pull request, by leaving comments *where the thing is*. The
panel knows its scope, so the note is addressed for you. When the notes
add up to a coherent request, you ship them as one manifest.

The strip is deliberately small. It is not a chat window. A note is one
sentence about one thing; the aggregation happens in the Manifest panel.

TWO BUTTONS, TWO GRAINS
-----------------------
**Stage** contributes to the one global manifest and ships later, which is
what a change crossing five panels needs. **Ask** ships THIS note, about
THIS panel's scope, right now -- and the bundle it writes carries only the
verbs that address that scope. Measured: ~2,300 tokens instead of ~9,300,
because a request about one tile layer does not need the 29 verbs that
cannot touch a tile layer, and it does not need the genre pack either.

That is the gesture the author described as how they intend to work --
"communicating through the engine to the AI for curative changes" -- so it
is a button on the surface they are already standing on, not a workflow.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from editor.core.request import NOTE_KINDS
from editor.core.scope import Scope

_PLACEHOLDER = "note for the AI about {scope}…"


class PromptStrip(QWidget):
    """One line of input, bound to whatever scope its panel is showing."""

    staged = Signal(object)          # emits the Note
    asked = Signal(str)              # emits the bundle directory

    def __init__(self, session, scope: Scope, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.__scope = scope
        #: The last thing this strip said, always, whether or not it reached
        #: a status bar. Panels are driven by check harnesses that are not
        #: `EditorWindow`, and "the gesture reported something" has to stay
        #: assertable there -- the same reason `ScopedDock.notify` keeps one.
        self.last_notice = ""
        self.last_bundle_path = ""

        self.field = QLineEdit(self)
        self.field.setClearButtonEnabled(True)
        self.field.returnPressed.connect(self.stage)

        self.kind = QComboBox(self)
        self.kind.addItems(list(NOTE_KINDS))
        self.kind.setToolTip(
            "change: do this.\n"
            "question: answer this before doing anything.\n"
            "constraint: a rule that applies to the whole request.")
        self.kind.setFixedWidth(96)

        self.button = QPushButton("Stage", self)
        self.button.setDefault(False)
        self.button.setAutoDefault(False)
        self.button.setToolTip(
            "Add this note to the manifest. Ship the whole manifest later, "
            "when the request is done being written.")
        self.button.clicked.connect(self.stage)

        # `ask` is a METHOD on this widget, while `self.ask` on a ScopedDock
        # is the dialog seam (`editor/ui/ask.py`). Different objects, and the
        # strip opens no dialog at all -- a refusal here is a status line.
        self.ask_button = QPushButton("Ask", self)
        self.ask_button.setDefault(False)
        self.ask_button.setAutoDefault(False)
        self.ask_button.setToolTip(
            "Send this one note now, as its own request, scoped to what this "
            "panel is showing. Smaller and cheaper than the whole manifest: "
            "the bundle carries only the verbs that can act on this scope.")
        self.ask_button.clicked.connect(self.ask)

        self.badge = QLabel("", self)
        self.badge.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.badge.setMinimumWidth(58)
        self.badge.setStyleSheet("color: palette(mid);")

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 4)
        row.setSpacing(4)
        row.addWidget(self.field, 1)
        row.addWidget(self.kind)
        row.addWidget(self.button)
        row.addWidget(self.ask_button)
        row.addWidget(self.badge)

        self.set_scope(scope)

    # -- scope -------------------------------------------------------------

    def scope(self) -> Scope:
        return self.__scope

    def set_scope(self, scope: Scope) -> None:
        self.__scope = scope
        self.field.setPlaceholderText(_PLACEHOLDER.format(scope=scope))
        self.field.setToolTip(f"This note will be addressed to {scope}")
        self.refresh()

    # -- staging -----------------------------------------------------------

    def stage(self) -> None:
        text = self.field.text().strip()
        if not text:
            return
        note = self.session.stage(self.__scope, text, self.kind.currentText())
        self.field.clear()
        self.refresh()
        self.staged.emit(note)

    # -- asking ------------------------------------------------------------

    def ask(self) -> str | None:
        """Ship THIS note as its own scoped bundle, now. Returns its path.

        Nothing here opens a dialog (law 13). A refusal -- an empty box, a
        scope no verb accepts, a disk that will not take the write -- is a
        status line the author can read after the fact, and their sentence
        is LEFT IN THE FIELD so a refusal costs them the press and not the
        typing.
        """
        text = self.field.text().strip()
        if not text:
            self.notify("say what you want changed first — the scope comes "
                        "from the panel you are standing on")
            return None
        try:
            path = self.session.ask(self.__scope, text,
                                    self.kind.currentText())
        except Exception as exc:                                # noqa: BLE001
            # Broad on purpose: this is a Qt slot, and an exception thrown
            # out of one is swallowed by the event loop -- the author would
            # see the press do nothing at all, which is the failure shape
            # this repository pays for most.
            self.notify(str(exc).splitlines()[0], seconds=14.0)
            return None
        self.field.clear()
        self.last_bundle_path = path
        self.notify(f"wrote {self.__shown(path)} — hand it over with: Read "
                    f"{self.__shown(path)}/BRIEF.md and do the work",
                    seconds=15.0)
        self.asked.emit(path)
        return path

    def __shown(self, path: str) -> str:
        """The bundle path as the author would type it, when that is
        possible. `relpath` raises across drives on Windows, and a status
        line is not worth a traceback."""
        try:
            return os.path.relpath(path, self.session.project.root)
        except (ValueError, AttributeError):
            return path

    # -- saying things -----------------------------------------------------

    def notify(self, message: str, *, seconds: float = 8.0) -> None:
        """Report to the window's status bar, and always remember it.

        `self.window()` is THIS widget when the strip has no parent -- which
        is exactly how a check drives it -- so the identity guard is not
        defensive typing: without it the forward finds this same method and
        recurses until the stack ends.
        """
        self.last_notice = message
        window = self.window()
        report = getattr(window, "notify", None)
        if window is not self and callable(report):
            report(message, seconds=seconds)

    def refresh(self) -> None:
        mine = sum(1 for n in self.session.manifest.notes
                   if n.scope == self.__scope)
        total = len(self.session.manifest.notes)
        if not total:
            self.badge.setText("")
        elif mine:
            self.badge.setText(f"{mine} here / {total}")
        else:
            self.badge.setText(f"0 / {total}")


