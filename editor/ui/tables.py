"""The data-table panel -- actors, weapons, equipment, levels.

The panel the brief describes directly: "if the game calls for a list of
characters, we'll want a GUI component capable of handling a list of
actors, their stats, and so on."

It is generated, not hand-written per genre. The genre pack declares the
tables and their columns; this panel renders whatever it finds. Adding
`stat_modifier` to equipment is `table.column.add`, not an editor change.

Editing a cell emits a command. That is the whole reason undo works here
and the AI's edits and yours are indistinguishable in the history.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from editor.core.commands import Command
from editor.core.scope import Scope
from editor.ui.docks import ScopedDock

_PARSERS = {
    "int": int,
    "float": float,
    "str": str,
    "bool": lambda text: str(text).strip().lower() in ("1", "true", "yes", "on"),
}


class TablesDock(ScopedDock):
    """One table at a time, chosen from a combo."""

    def build_content(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(4, 4, 4, 4)

        top = QHBoxLayout()
        self.picker = QComboBox()
        self.picker.currentTextChanged.connect(self.__on_pick)
        top.addWidget(self.picker, 1)

        self.create = QPushButton("Create")
        self.create.setToolTip("Create this table from the genre's declared shape.")
        self.create.clicked.connect(self.__on_create)
        top.addWidget(self.create)

        self.add_row = QPushButton("+ Row")
        self.add_row.clicked.connect(self.__on_add_row)
        top.addWidget(self.add_row)

        self.add_column = QPushButton("+ Column")
        self.add_column.clicked.connect(self.__on_add_column)
        top.addWidget(self.add_column)
        layout.addLayout(top)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.note)

        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self.__on_edit)
        self.table.currentCellChanged.connect(self.__on_cell)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)
        return holder

    # -- state -------------------------------------------------------------

    @property
    def current(self) -> str:
        return self.picker.currentText()

    def refresh(self) -> None:
        project = self.session.project
        declared = [t.name for t in project.genre.tables]
        names = sorted(set(declared) | set(project.table_names()))

        self.picker.blockSignals(True)
        wanted = self._scope.get("table") or self.current
        self.picker.clear()
        self.picker.addItems(names)
        if wanted in names:
            self.picker.setCurrentText(wanted)
        self.picker.blockSignals(False)

        name = self.current
        if not name:
            self.__show_empty("This genre declares no tables.")
            return
        if not project.has_table(name):
            declared_table = project.genre.table(name)
            self.create.setEnabled(True)
            self.add_row.setEnabled(False)
            self.add_column.setEnabled(False)
            self.__show_empty(
                f"The genre declares `{name}` but the project has not created "
                f"it yet." + (f"  {declared_table.doc}" if declared_table else ""))
            return

        self.create.setEnabled(False)
        self.add_row.setEnabled(True)
        self.add_column.setEnabled(True)
        table = project.table(name)
        self.note.setText(table.doc)

        self.table.blockSignals(True)
        self.table.clear()
        self.table.setColumnCount(len(table.columns))
        self.table.setRowCount(len(table.rows))
        self.table.setHorizontalHeaderLabels([c.name for c in table.columns])
        for column_index, column in enumerate(table.columns):
            header = self.table.horizontalHeaderItem(column_index)
            if header is not None:
                header.setToolTip(f"{column.type} — {column.doc}")
        self.table.setVerticalHeaderLabels(table.row_ids())
        for row_index, row_id in enumerate(table.row_ids()):
            row = table.rows[row_id]
            for column_index, column in enumerate(table.columns):
                item = QTableWidgetItem(str(row.get(column.name, "")))
                item.setData(Qt.UserRole, (row_id, column.name))
                self.table.setItem(row_index, column_index, item)
        self.table.blockSignals(False)

    def __show_empty(self, message: str) -> None:
        self.note.setText(message)
        self.table.blockSignals(True)
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.table.blockSignals(False)

    # -- interaction -------------------------------------------------------

    def __on_pick(self, name: str) -> None:
        if name:
            self.set_scope(Scope.of(("table", name)))
            self.refresh()

    def __on_cell(self, row: int, _column: int, *_rest) -> None:
        table_name = self.current
        if not table_name or row < 0:
            return
        header = self.table.verticalHeaderItem(row)
        if header is not None:
            self.set_scope(Scope.of(("table", table_name),
                                    ("row", header.text())))

    def __on_edit(self, item) -> None:
        payload = item.data(Qt.UserRole)
        if payload is None:
            return
        row_id, column_name = payload
        table = self.session.project.table(self.current)
        column = table.field(column_name)
        if column is None:
            return
        try:
            value = _PARSERS[column.type](item.text())
        except ValueError:
            self.__complain(f"{item.text()!r} is not a valid {column.type} "
                            f"for column {column_name!r}.")
            self.refresh()
            return
        try:
            self.window().run(Command(
                "table.row.set",
                Scope.of(("table", self.current), ("row", row_id)),
                {"column": column_name, "value": value}))
        except Exception as exc:                                # noqa: BLE001
            self.__complain(str(exc))
            self.refresh()

    def __on_create(self) -> None:
        self.window().run(Command("table.create",
                                  Scope.of(("table", self.current)), {}))

    def __on_add_row(self) -> None:
        row_id, ok = QInputDialog.getText(
            self, "New row",
            "Row id (snake_case, stable — it is referenced by name):")
        if not ok or not row_id.strip():
            return
        try:
            self.window().run(Command(
                "table.row.add", Scope.of(("table", self.current)),
                {"id": row_id.strip()}))
        except Exception as exc:                                # noqa: BLE001
            self.__complain(str(exc))

    def __on_add_column(self) -> None:
        name, ok = QInputDialog.getText(self, "New column", "Column name:")
        if not ok or not name.strip():
            return
        kind, ok = QInputDialog.getItem(
            self, "New column", f"Type of {name.strip()!r}:",
            ["int", "float", "str", "bool"], 0, False)
        if not ok:
            return
        doc, _ = QInputDialog.getText(
            self, "New column", "What does it mean? (goes into the AI's docs)")
        try:
            self.window().run(Command(
                "table.column.add", Scope.of(("table", self.current)),
                {"name": name.strip(), "type": kind, "doc": doc}))
        except Exception as exc:                                # noqa: BLE001
            self.__complain(str(exc))

    def __complain(self, message: str) -> None:
        QMessageBox.warning(self, "Rejected", message)
