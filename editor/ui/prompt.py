"""The prompt strip -- a comment box at the bottom of every panel.

The idea this editor is organised around: you review the project the way
you review a pull request, by leaving comments *where the thing is*. The
panel knows its scope, so the note is addressed for you. When the notes
add up to a coherent request, you ship them as one manifest.

The strip is deliberately small. It is not a chat window. A note is one
sentence about one thing; the aggregation happens in the Manifest panel.
"""
from __future__ import annotations

from typing import Callable

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

    def __init__(self, session, scope: Scope, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.__scope = scope

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
        self.button.clicked.connect(self.stage)

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


def wrap_with_prompt(session, scope: Scope, content: QWidget,
                     on_staged: Callable[[object], None] | None = None
                     ) -> tuple[QWidget, PromptStrip]:
    """Stack `content` above a prompt strip. Returns (container, strip)."""
    from PySide6.QtWidgets import QVBoxLayout

    container = QWidget()
    strip = PromptStrip(session, scope, container)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(content, 1)
    layout.addWidget(strip)
    if on_staged is not None:
        strip.staged.connect(on_staged)
    return container, strip
