"""The Database window -- actors, items, equipment, weapons, levels.

A second, non-modal window rather than a dock, in the RPG Maker shape: a
list of things on the left, every field of the selected thing on the right,
and enough room to see all of them at once. A side panel shows six columns
of twenty and none of the meaning.

Non-modal on purpose. You edit a monster's hp while looking at where it
stands on the map; a modal dialog would make that two trips.

WHAT IT IS NOT
--------------
Not a spreadsheet. The grid view still exists for bulk work, but the
default is the detail form, because the question "what is a Town Guard"
is answered by one screen of labelled fields, not by scrolling a row.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from editor.core.commands import Command
from editor.core.inspect import Field, describe
from editor.core.scope import Scope
from editor.ui.ask import ask_form
from editor.ui.fields import InspectionView
from editor.ui.prompt import PromptStrip


class TablePage(QWidget):
    """One table: its rows on the left, the selected row's fields on the right."""

    command_requested = Signal(object)
    reveal_requested = Signal(str)
    scope_changed = Signal(object)
    status_requested = Signal(str)

    def __init__(self, session, table_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.table_name = table_name
        self.current_row: str | None = None
        self.ask = ask_form          # the dialog seam; see editor/ui/ask.py

        self.list = QListWidget()
        self.list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list.currentItemChanged.connect(self.__on_select)

        # Enabled state, not an early return: on a fresh project there is no
        # table and no selection, and a button that cannot act must look like
        # it cannot act rather than swallowing the click.
        buttons = QHBoxLayout()
        self.add_button = QPushButton("+")
        self.add_button.clicked.connect(self.__on_add)
        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.clicked.connect(self.__on_duplicate)
        self.remove_button = QPushButton("−")
        self.remove_button.clicked.connect(self.__on_remove)
        for button in (self.add_button, self.duplicate_button,
                       self.remove_button):
            buttons.addWidget(button)
        buttons.addStretch(1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.addWidget(self.list, 1)
        left_layout.addLayout(buttons)

        self.view = InspectionView(show_sources=False)
        self.view.command_requested.connect(self.command_requested.emit)
        self.view.reveal_requested.connect(self.reveal_requested.emit)

        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet("color: palette(mid); padding: 24px;")

        self.create = QPushButton("Create this table")
        self.create.setMinimumHeight(34)
        self.create.clicked.connect(self.__on_create)

        right = QWidget()
        self.right_layout = QVBoxLayout(right)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.addWidget(self.empty)
        self.right_layout.addWidget(self.create)
        self.right_layout.addWidget(self.view, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 620])

        self.strip = PromptStrip(session, Scope.of(("table", table_name)))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.strip)

    # -- state -------------------------------------------------------------

    @property
    def exists(self) -> bool:
        return self.session.project.has_table(self.table_name)

    def __sync_buttons(self) -> None:
        """Enable only what can actually happen, and say why when it cannot."""
        exists = self.exists
        selected = exists and self.current_row is not None

        self.add_button.setEnabled(exists)
        self.add_button.setToolTip(
            "add a row" if exists else
            f"create the {self.table_name} table first")

        for button, verb in ((self.duplicate_button, "copy"),
                             (self.remove_button, "delete")):
            button.setEnabled(selected)
            button.setToolTip(
                f"{verb} the selected row" if selected else
                (f"select a row to {verb} it" if exists
                 else f"create the {self.table_name} table first"))

    def refresh(self) -> None:
        if not self.exists:
            declared = self.session.project.genre.table(self.table_name)
            self.empty.setText(
                f"The {self.session.project.genre.title} genre declares a "
                f"{self.table_name!r} table"
                + (f" — {declared.doc}" if declared and declared.doc else "")
                + "\n\nThe project has not created it yet.")
            self.empty.show()
            self.create.show()
            self.view.hide()
            self.list.clear()
            self.current_row = None
            self.__sync_buttons()
            return

        self.empty.hide()
        self.create.hide()
        self.view.show()

        table = self.session.project.table(self.table_name)
        label_column = next((c.name for c in table.columns
                             if c.name in ("display_name", "name", "title")), None)

        self.list.blockSignals(True)
        self.list.clear()
        for row_id, row in table:
            label = row.get(label_column) if label_column else None
            item = QListWidgetItem(f"{label}   ({row_id})" if label else row_id)
            item.setData(Qt.UserRole, row_id)
            self.list.addItem(item)
            if row_id == self.current_row:
                self.list.setCurrentItem(item)
        if self.current_row not in table.rows:
            self.current_row = None
        if self.current_row is None and self.list.count():
            self.list.setCurrentRow(0)
            self.current_row = self.list.item(0).data(Qt.UserRole)
        self.list.blockSignals(False)

        self.__sync_buttons()
        self.__show_current()

    def __show_current(self) -> None:
        if self.current_row is None:
            self.view.show_inspection(
                describe(self.session, Scope.of(("table", self.table_name))))
            return
        scope = Scope.of(("table", self.table_name), ("row", self.current_row))
        self.view.show_inspection(describe(self.session, scope))
        self.strip.set_scope(scope)
        self.scope_changed.emit(scope)

    # -- actions -----------------------------------------------------------

    def __on_select(self, current, _previous) -> None:
        if current is None:
            return
        self.current_row = current.data(Qt.UserRole)
        self.__sync_buttons()
        self.__show_current()

    def __on_create(self) -> None:
        self.command_requested.emit(
            Command("table.create", Scope.of(("table", self.table_name)), {}))

    #: A row id is a file-format string -- stable once referenced, never
    #: renamed. Nothing can infer it, so asking for it is a real decision.
    _ID_DOC = ("snake_case, stable, referenced by name from maps and other "
               "tables. Renaming it later silently disarms every reference.")

    def __on_add(self) -> None:
        if not self.exists:
            return
        answer = self.ask(self, f"New {self.table_name} row",
                          [Field("id", "Row id", "str", "", doc=self._ID_DOC)],
                          ok_label="Add the row")
        if answer is None or not answer["id"]:
            return
        self.current_row = answer["id"]
        self.command_requested.emit(Command(
            "table.row.add", Scope.of(("table", self.table_name)),
            {"id": answer["id"]}))

    def __on_duplicate(self) -> None:
        if not self.exists or self.current_row is None:
            return
        source = dict(self.session.project.table(self.table_name)
                      .require_row(self.current_row))
        answer = self.ask(
            self, f"Duplicate {self.current_row!r}",
            [Field("id", "Id for the copy", "str", f"{self.current_row}_copy",
                   doc=self._ID_DOC)],
            ok_label="Duplicate it")
        if answer is None or not answer["id"]:
            return
        self.current_row = answer["id"]
        self.command_requested.emit(Command(
            "table.row.add", Scope.of(("table", self.table_name)),
            {"id": answer["id"], "values": source}))

    def __on_remove(self) -> None:
        if not self.exists or self.current_row is None:
            return
        # No confirmation: the button is disabled unless a row is selected,
        # so the click is deliberate, and undo reaches this exactly -- which
        # by this editor's definition means it is not destructive. The
        # status line says so, where it informs rather than interrupts.
        doomed = self.current_row
        self.current_row = None
        self.command_requested.emit(Command(
            "table.row.remove",
            Scope.of(("table", self.table_name), ("row", doomed))))
        self.status_requested.emit(
            f"deleted {doomed!r} from {self.table_name} — Ctrl+Z brings it back")


class DatabaseWindow(QMainWindow):
    """Every data table the genre knows about, one tab each."""

    command_requested = Signal(object)
    reveal_requested = Signal(str)

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.setWindowTitle(f"Database — {session.project.genre.title}")
        self.setWindowFlag(Qt.Window, True)
        self.resize(1000, 700)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.pages: dict[str, TablePage] = {}
        self.setCentralWidget(self.tabs)

        # Ctrl+Z has to work HERE too. Deleting a row now says "Ctrl+Z brings
        # it back" in this window's status bar, and a promise that only works
        # in the OTHER window would be worse than the dialog it replaced. Qt
        # shortcuts are per-window, so the actions are duplicated and
        # forwarded to the single command stream that owns them.
        for text, sequence, name in (("&Undo", QKeySequence.Undo, "undo"),
                                     ("&Redo", QKeySequence.Redo, "redo")):
            action = QAction(text, self)
            action.setShortcut(sequence)
            action.triggered.connect(
                lambda _checked=False, n=name: self.__forward(n))
            self.addAction(action)

        self.rebuild()

    def __forward(self, name: str) -> None:
        call = getattr(self.parent(), name, None)
        if callable(call):
            call()

    def __on_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)

    def rebuild(self) -> None:
        """Tabs come from the GENRE, so switching genre reshapes the window."""
        remembered = self.tabs.tabText(self.tabs.currentIndex()) \
            if self.tabs.count() else ""
        # QTabWidget.clear() removes the pages but does NOT delete them, so
        # each one becomes a parentless top-level window -- the same defect
        # that made Ctrl+Z flash twenty little windows. Delete them here.
        while self.tabs.count():
            page = self.tabs.widget(0)
            self.tabs.removeTab(0)
            page.setParent(self)      # keep it owned until it is destroyed
            page.hide()
            page.deleteLater()
        self.pages.clear()

        project = self.session.project
        names = sorted({t.name for t in project.genre.tables}
                       | set(project.table_names()))
        for name in names:
            declared = project.genre.table(name)
            page = TablePage(self.session, name)
            page.command_requested.connect(self.command_requested.emit)
            page.reveal_requested.connect(self.reveal_requested.emit)
            page.status_requested.connect(self.__on_status)
            title = declared.title if declared else name.title()
            self.tabs.addTab(page, title)
            self.pages[name] = page
            if title == remembered:
                self.tabs.setCurrentWidget(page)
        if not names:
            placeholder = QLabel(
                f"The {project.genre.title} genre declares no data tables.")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color: palette(mid); padding: 40px;")
            self.tabs.addTab(placeholder, "—")
        self.refresh()

    def refresh(self) -> None:
        self.setWindowTitle(f"Database — {self.session.project.genre.title}")
        for page in self.pages.values():
            page.refresh()
