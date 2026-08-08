"""The panels.

Every one of them is a `ScopedDock`: some content, a prompt strip beneath
it, and a scope that both of them agree on. Changing the selection in a
panel re-aims its prompt strip, so a note typed after clicking the `Floor`
layer is a note about `map:test/layer:Floor` without anyone saying so.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from editor.core.scope import Scope
from editor.ui.prompt import PromptStrip


class ScopedDock(QDockWidget):
    """A panel that knows what part of the project it is showing.

    `follows_selection` decides whether this panel re-aims when something is
    selected elsewhere. Inspectors do; Tables, Problems and Manifest do not,
    because a note typed into Problems is about the project and should not
    be dragged onto whatever tile was last clicked.
    """

    scope_changed = Signal(object)
    follows_selection = False

    def __init__(self, title: str, session, scope: Scope, parent=None):
        super().__init__(title, parent)
        self.session = session
        self.base_title = title
        self._scope = scope
        self.setObjectName(title.replace(" ", "_"))

        self.content = self.build_content()
        self.strip = PromptStrip(session, scope)
        self.strip.staged.connect(lambda _n: self.window().refresh_manifest())

        holder = QWidget(self)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.content, 1)
        layout.addWidget(self.strip)
        self.setWidget(holder)
        self.__retitle()

    # -- subclasses implement these ----------------------------------------

    def build_content(self) -> QWidget:                        # pragma: no cover
        raise NotImplementedError

    def refresh(self) -> None:
        """Re-read the session. Called after every transaction."""

    def on_selection_changed(self, scope: Scope) -> None:
        """React to a selection made elsewhere. Only called when
        `follows_selection` is True. The default is to follow and re-read."""
        self.set_scope(scope)
        self.refresh()

    # -- scope -------------------------------------------------------------

    @property
    def scope(self) -> Scope:
        return self._scope

    def set_scope(self, scope: Scope) -> None:
        if scope == self._scope:
            return
        self._scope = scope
        self.strip.set_scope(scope)
        self.__retitle()
        self.scope_changed.emit(scope)

    def __retitle(self) -> None:
        self.setWindowTitle(f"{self.base_title}  —  {self._scope}")


# --------------------------------------------------------------------------
# Problems
# --------------------------------------------------------------------------

class ProblemsDock(ScopedDock):
    """Soft rule violations. Nothing here blocks anything."""

    def build_content(self) -> QWidget:
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self.__on_activate)
        return self.list

    def refresh(self) -> None:
        self.list.clear()
        try:
            problems = self.session.problems()
        except Exception as exc:                                # noqa: BLE001
            self.list.addItem(f"(validation failed: {exc})")
            return
        if not problems:
            item = QListWidgetItem("No rule violations.")
            item.setForeground(Qt.darkGreen)
            self.list.addItem(item)
            return
        for violation in problems:
            text = f"{violation.scope}  —  {violation.message}"
            if violation.fix:
                text += f"   ({violation.fix})"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, str(violation.scope))
            item.setForeground(Qt.red if violation.severity == "hard"
                               else Qt.darkYellow)
            self.list.addItem(item)

    def __on_activate(self, item) -> None:
        raw = item.data(Qt.UserRole)
        if raw:
            self.set_scope(Scope.parse(raw))


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------

class HistoryDock(ScopedDock):
    """Every command that has run, human or AI. This is the review surface."""

    def build_content(self) -> QWidget:
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setPlaceholderText(
            "Nothing has changed yet. Every command — yours or an AI's — "
            "is logged here in the order it ran.")
        return self.view

    def refresh(self) -> None:
        lines: list[str] = []
        for index, transaction in enumerate(self.session.history(), 1):
            lines.append(f"{index:>3}. {transaction}")
            lines.extend(transaction.summary_lines())
        self.view.setPlainText("\n".join(lines))
        self.view.verticalScrollBar().setValue(
            self.view.verticalScrollBar().maximum())


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------

class ManifestDock(ScopedDock):
    """The staged notes, and the button that turns them into a request."""

    ship_requested = Signal()

    def build_content(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(4, 4, 4, 4)

        self.summary = QLabel("Nothing staged.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.itemDoubleClicked.connect(self.__on_remove)
        self.list.setToolTip("Double-click a note to remove it.")
        layout.addWidget(self.list, 1)

        self.ship = QPushButton("Ship as a request…")
        self.ship.clicked.connect(self.ship_requested.emit)
        self.ship.setEnabled(False)
        layout.addWidget(self.ship)
        return holder

    def refresh(self) -> None:
        manifest = self.session.manifest
        self.list.clear()
        for scope, notes in manifest.grouped():
            header = QListWidgetItem(str(scope))
            header.setFlags(Qt.NoItemFlags)
            header.setForeground(Qt.gray)
            self.list.addItem(header)
            for note in notes:
                prefix = {"change": "  • ", "question": "  ? ",
                          "constraint": "  ! "}[note.kind]
                item = QListWidgetItem(prefix + note.text)
                item.setData(Qt.UserRole, manifest.notes.index(note))
                self.list.addItem(item)
        count = len(manifest.notes)
        scopes = len(manifest.scopes())
        self.summary.setText(
            "Nothing staged. Type under any panel to leave a note."
            if not count else
            f"{count} note{'' if count == 1 else 's'} across {scopes} "
            f"scope{'' if scopes == 1 else 's'}. Review, then ship.")
        self.ship.setEnabled(bool(count))

    def __on_remove(self, item) -> None:
        index = item.data(Qt.UserRole)
        if index is None:
            return
        self.session.manifest.remove(int(index))
        self.window().refresh_manifest()
