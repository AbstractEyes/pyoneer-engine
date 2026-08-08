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
    """A panel that knows what part of the project it is showing."""

    scope_changed = Signal(object)

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
# Layers
# --------------------------------------------------------------------------

class LayersDock(ScopedDock):
    """The map's layers. Selecting one aims the canvas and the prompt."""

    layer_selected = Signal(str)

    def build_content(self) -> QWidget:
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self.__on_selection)
        self.list.itemChanged.connect(self.__on_visibility)
        return self.list

    def refresh(self) -> None:
        map_name = self._scope.get("map")
        if map_name is None:
            return
        wanted = self._scope.get("layer")
        self.list.blockSignals(True)
        self.list.clear()
        try:
            document = self.session.project.map(map_name)
        except Exception as exc:                                # noqa: BLE001
            self.list.addItem(f"(map unreadable: {exc})")
            self.list.blockSignals(False)
            return
        tile_layers = set(document.tile_layer_names())
        object_layers = set(document.object_layer_names())
        pack = self.session.project.genre
        for name in document.layer_names():
            # layer_names() also returns <group> elements, which are neither
            # tile nor object layers. Listing one as selectable produced a
            # scope (map:test/layer:Graphic) that no verb can act on, so
            # groups are shown as structure and nothing more.
            if name not in tile_layers and name not in object_layers:
                group = QListWidgetItem(f"▾ {name}")
                group.setFlags(Qt.NoItemFlags)
                group.setForeground(Qt.gray)
                group.setToolTip("a Tiled group; it holds layers but is not "
                                 "one itself")
                self.list.addItem(group)
                continue
            kind = "tile" if name in tile_layers else "object"
            declared = pack.layer(name)
            depth = f"  d{declared.depth}" if declared else "  d?"
            item = QListWidgetItem(f"    {name}   [{kind}]{depth}")
            item.setData(Qt.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            if declared is None:
                item.setToolTip(
                    f"{name!r} is not declared by genre "
                    f"{pack.id!r}, and scripts/core/depth.py may not map it "
                    f"to a depth — in which case it will not render.")
                item.setForeground(Qt.darkYellow)
            else:
                item.setToolTip(declared.doc)
            self.list.addItem(item)
            if name == wanted:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def __on_selection(self, current, _previous) -> None:
        if current is None:
            return
        name = current.data(Qt.UserRole)
        if not name:
            return
        map_name = self._scope.require("map")
        self.set_scope(Scope.of(("map", map_name), ("layer", name)))
        self.layer_selected.emit(name)

    def __on_visibility(self, item) -> None:
        name = item.data(Qt.UserRole)
        if name:
            self.window().set_layer_visible(name, item.checkState() == Qt.Checked)


# --------------------------------------------------------------------------
# Objects
# --------------------------------------------------------------------------

class ObjectsDock(ScopedDock):
    """Everything placed on the selected object layer."""

    object_selected = Signal(int)

    def build_content(self) -> QWidget:
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["id", "class", "name", "x", "y"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.currentItemChanged.connect(self.__on_selection)
        header = self.tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        return self.tree

    def refresh(self) -> None:
        self.tree.clear()
        map_name = self._scope.get("map")
        layer_name = self._scope.get("layer")
        if not map_name or not layer_name:
            return
        try:
            document = self.session.project.map(map_name)
            if layer_name not in document.object_layer_names():
                placeholder = QTreeWidgetItem(
                    ["", f"({layer_name} is a tile layer)", "", "", ""])
                self.tree.addTopLevelItem(placeholder)
                return
            layer = document.object_layer(layer_name)
        except Exception as exc:                                # noqa: BLE001
            self.tree.addTopLevelItem(QTreeWidgetItem(["", str(exc), "", "", ""]))
            return
        for obj in layer.objects():
            item = QTreeWidgetItem([str(obj.id), obj.type or "-", obj.name or "-",
                                    f"{obj.x:g}", f"{obj.y:g}"])
            item.setData(0, Qt.UserRole, obj.id)
            properties = obj.properties.as_dict()
            if properties:
                item.setToolTip(1, "\n".join(
                    f"{k} = {v!r}" for k, v in sorted(properties.items())))
            self.tree.addTopLevelItem(item)

    def __on_selection(self, current, _previous) -> None:
        if current is None:
            return
        object_id = current.data(0, Qt.UserRole)
        if object_id is None:
            return
        self.set_scope(Scope.of(("map", self._scope.require("map")),
                                ("layer", self._scope.require("layer")),
                                ("object", str(object_id))))
        self.object_selected.emit(int(object_id))


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
