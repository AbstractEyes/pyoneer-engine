"""The hierarchy -- one tree for the whole map, Unity/Godot style.

Replaces the separate Layers and Objects panels. Keeping them apart meant
the thing you clicked and the thing you were editing lived in different
boxes, and a group element could be selected as though it were a layer.

    map:test
      ▾ Graphic                    (group -- structure, not selectable)
          Paralax      tile   d1
          Floor        tile   d10        ← selecting a layer aims the brush
          ...
      ▾ Entity
          entity       object d50
            player_start   GamePlayer    ← selecting an object fills the
            chest_01       GameEntity       inspector and the prompt

Layer visibility is a checkbox on the layer row. It is a VIEW toggle only --
it hides the layer in the canvas and changes nothing in the file, because a
tmx `visible` attribute is authored content and toggling it while looking
around would be a silent edit.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from editor.core.project import layer_tree
from editor.core.scope import Scope
from editor.ui.docks import ScopedDock

_KIND_MARK = {"tile": "▦", "object": "◈", "image": "▣", "group": "▾"}


class HierarchyDock(ScopedDock):
    """Everything in the map, in the order it was authored."""

    follows_selection = True

    visibility_changed = Signal(str, bool)

    def build_content(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(4, 4, 4, 2)
        layout.setSpacing(3)

        top = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("filter by name or class…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda _t: self.refresh())
        top.addWidget(self.filter, 1)
        self.count = QLabel("")
        self.count.setStyleSheet("color: palette(mid);")
        top.addWidget(self.count)
        layout.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setUniformRowHeights(True)
        self.tree.currentItemChanged.connect(self.__on_current)
        self.tree.itemChanged.connect(self.__on_check)
        layout.addWidget(self.tree, 1)
        return holder

    # -- building ----------------------------------------------------------

    def refresh(self) -> None:
        map_name = self._scope.get("map")
        if map_name is None:
            return
        needle = self.filter.text().strip().lower()

        self.tree.blockSignals(True)
        self.tree.clear()
        try:
            document = self.session.project.map(map_name)
        except Exception as exc:                                # noqa: BLE001
            self.tree.addTopLevelItem(QTreeWidgetItem([f"map unreadable: {exc}"]))
            self.tree.blockSignals(False)
            return

        root = QTreeWidgetItem([f"map:{map_name}"])
        root.setData(0, Qt.UserRole, f"map:{map_name}")
        root.setForeground(0, Qt.gray)
        self.tree.addTopLevelItem(root)

        pack = self.session.project.genre
        objects_shown = 0
        for node in layer_tree(document):
            objects_shown += self.__add_node(root, node, document, pack,
                                             map_name, needle)
        # A map has a handful of layers, so expanding everything is simpler
        # and more useful than remembering collapse state. Revisit if a map
        # ever carries enough objects for that to be noise.
        self.tree.expandAll()
        self.__reselect()
        self.tree.blockSignals(False)

        total = sum(len(document.object_layer(n).objects())
                    for n in document.object_layer_names())
        self.count.setText(f"{objects_shown}/{total}" if needle
                           else f"{total} object{'' if total == 1 else 's'}")

    def __add_node(self, parent, node, document, pack, map_name,
                   needle: str) -> int:
        if not node.selectable:
            item = QTreeWidgetItem([f"{_KIND_MARK['group']} {node.name}"])
            item.setForeground(0, Qt.gray)
            item.setToolTip(0, "a Tiled group: it holds layers but is not one, "
                               "so no command can act on it")
            parent.addChild(item)
            shown = 0
            for child in node.children:
                shown += self.__add_node(item, child, document, pack,
                                         map_name, needle)
            item.setExpanded(True)
            return shown

        declared = pack.layer(node.name)
        depth = f"d{declared.depth}" if declared else "d?"
        item = QTreeWidgetItem(
            [f"{_KIND_MARK.get(node.kind, '?')} {node.name}    {node.kind}  {depth}"])
        item.setData(0, Qt.UserRole, f"map:{map_name}/layer:{node.name}")
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Unchecked if node.name in self.__hidden()
                           else Qt.Checked)
        if declared is None:
            item.setForeground(0, Qt.darkYellow)
            item.setToolTip(0,
                            f"{node.name!r} is not declared by genre {pack.id!r}. "
                            f"If scripts/core/depth.py does not map it either, "
                            f"it will not render at all.")
        else:
            item.setToolTip(0, declared.doc)
        parent.addChild(item)

        shown = 0
        if node.kind == "object" and node.name in document.object_layer_names():
            for obj in document.object_layer(node.name).objects():
                label = obj.name or f"#{obj.id}"
                haystack = f"{obj.name} {obj.type}".lower()
                if needle and needle not in haystack:
                    continue
                child = QTreeWidgetItem([f"     {label}      {obj.type or '-'}"])
                child.setData(0, Qt.UserRole,
                              f"map:{map_name}/layer:{node.name}/object:{obj.id}")
                properties = obj.properties.as_dict()
                child.setToolTip(0, "\n".join(
                    [f"id {obj.id}   ({obj.x:g}, {obj.y:g})"]
                    + [f"{k} = {v!r}" for k, v in sorted(properties.items())]))
                if declared and declared.object_types and obj.type \
                        and obj.type not in declared.object_types:
                    child.setForeground(0, Qt.darkYellow)
                item.addChild(child)
                shown += 1
            item.setExpanded(True)
        return shown

    # -- selection ---------------------------------------------------------

    def __on_current(self, current, _previous) -> None:
        if current is None:
            return
        raw = current.data(0, Qt.UserRole)
        if not raw:
            return
        scope = Scope.parse(raw)
        self.set_scope(scope)
        window = self.window()
        if hasattr(window, "selection"):
            window.selection.select(scope)

    def on_selection_changed(self, scope: Scope) -> None:
        """Follow a selection made elsewhere -- canvas, problems, anywhere.

        Re-scoping is not just cosmetic: the panel's own prompt strip hangs
        off `_scope`, so without this a note typed in the hierarchy after
        clicking a tile on the canvas landed on the map rather than on the
        layer you were looking at.
        """
        if scope.get("map") != self._scope.get("map"):
            return
        self.set_scope(scope)
        self.tree.blockSignals(True)
        self.__reselect(str(scope))
        self.tree.blockSignals(False)

    def __reselect(self, wanted: str | None = None) -> None:
        target = wanted or str(self._scope)
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item.data(0, Qt.UserRole) == target:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return
            iterator += 1

    # -- visibility --------------------------------------------------------

    def __hidden(self) -> set[str]:
        window = self.window()
        canvas = getattr(window, "canvas", None)
        return getattr(canvas, "hidden_layers", set()) if canvas else set()

    def __on_check(self, item, _column) -> None:
        raw = item.data(0, Qt.UserRole)
        if not raw or "/layer:" not in raw:
            return
        name = Scope.parse(raw).require("layer")
        self.visibility_changed.emit(name, item.checkState(0) == Qt.Checked)

