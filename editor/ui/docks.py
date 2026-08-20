"""The panels.

Every one of them is a `ScopedDock`: some content, a prompt strip beneath
it, and a scope that both of them agree on. Changing the selection in a
panel re-aims its prompt strip, so a note typed after clicking the `Floor`
layer is a note about `map:test/layer:Floor` without anyone saying so.

Every one of them also carries `self.ask` and `self.confirm`, the two
dialog seams from `editor/ui/ask.py`. A panel never calls `QMessageBox`
directly: a check has to be able to assert, per panel, that the routine
path opened nothing at all, and a hard static call cannot be watched
without patching the class for the whole process.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QHBoxLayout,
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

from editor.core.genre import RuleViolation
from editor.core.scope import Scope
from editor.ui.ask import ask_form, confirm
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
        # The dialog seams. Replaceable per instance so a check can drive a
        # panel without a window ever opening, and so "this path asked
        # nothing" is an assertion rather than a hope. See editor/ui/ask.py.
        self.ask = ask_form
        self.confirm = confirm
        self.last_notice = ""

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

    # -- saying things -----------------------------------------------------

    def notify(self, message: str, *, seconds: float = 6.0) -> None:
        """Say something to the author, wherever this panel is mounted.

        Forwards to the window's status bar when there is one, and always
        remembers the last message: panels are driven by check harnesses
        that are deliberately not `EditorWindow`, and "the click reported
        something" has to stay assertable there. A panel that reached for
        `self.window().notify` directly would raise inside those harnesses
        and would make reporting the risky option.
        """
        self.last_notice = message
        report = getattr(self.window(), "notify", None)
        if callable(report):
            report(message, seconds=seconds)

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
    """Soft rule violations, and anything else the author needs to have SEEN.

    Two sources, one list. The genre's validator answers "is this project
    coherent", which is re-derived on every refresh and owns no state. The
    notices answer "something happened while you were not looking" -- a
    rejected command, a response file arriving on disk -- and they are the
    reason this dock exists as a surface rather than a report.

    None of them is a dialog. A rejection is a NORMAL outcome here
    (`map.tileset.remove` refusing while gids still point into its range is
    a designed refusal with a long, useful message), and a dialog for a
    normal outcome is a decision with no choice in it -- as well as a modal
    on the ordinary edit path, where it can hang a headless check.

    A notice is a `RuleViolation` -- the same record the validator emits, so
    the row renders, colours and double-click-to-scope identically and there
    is no second shape of problem. `key` makes posting idempotent: the same
    key replaces its predecessor rather than stacking ten copies of one
    rejection, and it is what the window clears when the situation is over.
    """

    def build_content(self) -> QWidget:
        self.notices: list[tuple[str, RuleViolation, str]] = []
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self.__on_activate)
        return self.list

    # -- notices -----------------------------------------------------------

    def post(self, violation: RuleViolation, *, key: str,
             detail: str = "") -> None:
        """Show something that happened. `detail` goes in the tooltip.

        The tooltip is where the debugging vocabulary lives -- verb names,
        scope syntax, the args dict, the exception class. Useful, and not
        what the author asked for when they clicked something.
        """
        self.notices = [n for n in self.notices if n[0] != key]
        self.notices.append((key, violation, detail))
        del self.notices[:-8]
        self.refresh()

    def clear_notices(self, key: str | None = None) -> None:
        """Retire a notice whose situation is over. No key clears them all."""
        before = len(self.notices)
        self.notices = ([] if key is None
                        else [n for n in self.notices if n[0] != key])
        if len(self.notices) != before:
            self.refresh()

    def notice_keys(self) -> list[str]:
        return [key for key, _violation, _detail in self.notices]

    # -- rendering ---------------------------------------------------------

    def refresh(self) -> None:
        self.list.clear()
        try:
            problems = list(self.session.problems())
        except Exception as exc:                                # noqa: BLE001
            problems = [RuleViolation("hard", self._scope,
                                      f"validation failed: {exc}")]
        rows = [(violation, detail) for _key, violation, detail in self.notices]
        rows += [(violation, "") for violation in problems]
        if not rows:
            item = QListWidgetItem("No rule violations.")
            item.setForeground(Qt.darkGreen)
            self.list.addItem(item)
            return
        for violation, detail in rows:
            text = f"{violation.scope}  —  {violation.message}"
            if violation.fix:
                text += f"   ({violation.fix})"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, str(violation.scope))
            item.setForeground(Qt.red if violation.severity == "hard"
                               else Qt.darkYellow)
            if detail:
                item.setToolTip(detail)
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
        self.list.currentItemChanged.connect(lambda *_a: self.__sync_buttons())
        layout.addWidget(self.list, 1)

        # A destructive action needs a visible control, not just the
        # double-click above.
        row = QHBoxLayout()
        self.unstage = QPushButton("Unstage")
        self.unstage.clicked.connect(self.__on_unstage)
        self.unstage.setEnabled(False)
        row.addWidget(self.unstage)

        self.unstage_all = QPushButton("Unstage all")
        self.unstage_all.clicked.connect(self.__on_unstage_all)
        self.unstage_all.setEnabled(False)
        row.addWidget(self.unstage_all)
        row.addStretch(1)
        layout.addLayout(row)

        self.ship = QPushButton("Ship as a request…")
        self.ship.clicked.connect(self.ship_requested.emit)
        self.ship.setEnabled(False)
        layout.addWidget(self.ship)
        return holder

    def __selected_index(self) -> int | None:
        item = self.list.currentItem()
        if item is None:
            return None
        index = item.data(Qt.UserRole)
        return None if index is None else int(index)

    def __sync_buttons(self) -> None:
        staged = len(self.session.manifest.notes)
        self.unstage.setEnabled(self.__selected_index() is not None)
        self.unstage.setToolTip(
            "remove the selected note" if self.__selected_index() is not None
            else "select a note to unstage it")
        self.unstage_all.setEnabled(bool(staged))
        self.ship.setEnabled(bool(staged))

    def __on_unstage(self) -> None:
        index = self.__selected_index()
        if index is None:
            return
        self.session.manifest.remove(index)
        self.window().refresh_manifest()

    def __on_unstage_all(self) -> None:
        count = len(self.session.manifest.notes)
        if not count:
            return
        # The only confirmation in the editor, because it is the only click
        # undo cannot reach: a staged note never entered the command stream,
        # so there is no inverse to fall back on.
        if not self.confirm(
                self, "Unstage all",
                f"Discard {count} staged note{'' if count == 1 else 's'}?\n\n"
                f"Notes are not undoable -- they have not been applied to "
                f"anything yet."):
            return
        self.session.manifest.clear()
        self.window().refresh_manifest()

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
        self.__sync_buttons()

    def __on_remove(self, item) -> None:
        index = item.data(Qt.UserRole)
        if index is None:
            return
        self.session.manifest.remove(int(index))
        self.window().refresh_manifest()
