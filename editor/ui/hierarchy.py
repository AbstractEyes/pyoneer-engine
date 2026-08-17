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
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from scripts.core.depth import MAP_DEPTH, OBJECT_DEPTH

from editor.core.commands import Command
from editor.core.inspect import Field
from editor.core.project import layer_tree
from editor.core.scope import Scope
from editor.ui.docks import ScopedDock

_KIND_MARK = {"tile": "▦", "object": "◈", "image": "▣", "group": "▾"}

_TOP_LEVEL = "(top level)"


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

        buttons = QHBoxLayout()
        self.add_tile = QPushButton("+ tile layer")
        self.add_tile.clicked.connect(lambda: self.__on_add("tile"))
        self.add_object = QPushButton("+ object layer")
        self.add_object.clicked.connect(lambda: self.__on_add("object"))
        self.remove_layer = QPushButton("−")
        self.remove_layer.clicked.connect(self.__on_remove)
        for button in (self.add_tile, self.add_object, self.remove_layer):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return holder

    # -- adding and removing layers ----------------------------------------

    def __known_names(self, kind: str, taken: set[str]) -> list[str]:
        """Layer names that will draw, minus the ones already used.

        Two sources, because two things decide whether a layer renders: the
        genre pack declares what this KIND of game expects, and the engine
        keeps its own name-to-depth table for everything else. A name in
        neither is not refused -- authoring a layer the engine has never
        heard of is a legitimate thing to do first -- but it is not
        suggested either, and the row it produces is already coloured with
        the reason.
        """
        declared = [layer.name for layer in self.session.project.genre.layers
                    if layer.kind == kind]
        engine = list(MAP_DEPTH if kind == "tile" else OBJECT_DEPTH)
        seen: list[str] = []
        for name in declared + engine:
            if name not in taken and name not in seen:
                seen.append(name)
        return seen

    def __on_add(self, kind: str) -> None:
        window = self.window()
        map_name = self._scope.get("map")
        if map_name is None:
            # The buttons are disabled without a map, so this is unreachable
            # by clicking. It stays because a shortcut or a script can still
            # arrive here, and a call that does nothing must still say so.
            self.notify("open a map before adding a layer to it")
            return

        groups: list[str] = []
        taken: set[str] = set()
        try:
            document = self.session.project.map(map_name)
            groups = [node.name for node in layer_tree(document)
                      if not node.selectable]
            taken = set(document.layer_names())
        except Exception:                                       # noqa: BLE001
            pass

        rows = [Field("name", "Name", "str", "",
                      doc="Names the genre and the engine already know are "
                          "listed. A name neither of them knows is allowed "
                          "and will not draw until it is declared — the "
                          "hierarchy marks such a layer in yellow.",
                      choices=tuple(self.__known_names(kind, taken)))]
        if groups:
            # One dialog, not two. It used to ask for the name, then ask for
            # the group in a second modal -- and cancelling the second threw
            # away the name that had just been typed into the first.
            rows.append(Field("group", "Inside", "choice", _TOP_LEVEL,
                              doc="A Tiled group is organisation only; it "
                                  "does not change what draws or when.",
                              choices=tuple([_TOP_LEVEL] + groups)))

        answer = self.ask(self, f"New {kind} layer", rows,
                          ok_label=f"Add the {kind} layer")
        if answer is None:
            return
        name = answer["name"].strip()
        if not name:
            self.notify("a layer needs a name — nothing was added")
            return
        group = answer.get("group", _TOP_LEVEL)
        window.run(Command("map.layer.add", Scope.of(("map", map_name)),
                           {"name": name, "kind": kind,
                            "group": "" if group == _TOP_LEVEL else group}))

    def __on_remove(self) -> None:
        layer = self._scope.get("layer")
        if layer is None or self._scope.kind == "object":
            return
        # No confirmation. It used to ask "Remove 'Roof' and everything on
        # it?" and then reassure, in the same box, that "undo restores the
        # layer byte-for-byte" -- a dialog whose body is the argument that
        # the dialog is unnecessary. The reassurance was the only useful
        # half, so it moved to where it is read AFTER the click.
        if self.window().run(Command(
                "map.layer.remove",
                Scope.of(("map", self._scope.require("map")),
                         ("layer", layer)))):
            self.notify(f"removed {layer!r} and everything on it — "
                        f"Ctrl+Z restores it byte-for-byte", seconds=10)

    def __sync_buttons(self) -> None:
        """Enable only what can actually happen, and say why when it cannot.

        Reported from a real run: both add buttons were enabled, carried no
        tooltip, and silently returned when the panel's scope had no map --
        a dead click of exactly the shape the Database's three row buttons
        were fixed for. `editor/ui/database.py` is the model.
        """
        map_name = self._scope.get("map")
        for button, kind in ((self.add_tile, "a tile"),
                             (self.add_object, "an object")):
            button.setEnabled(map_name is not None)
            button.setToolTip(f"add {kind} layer to map:{map_name}"
                              if map_name is not None else "open a map first")

        removable = (self._scope.get("layer") is not None
                     and self._scope.kind != "object")
        self.remove_layer.setEnabled(removable)
        self.remove_layer.setToolTip(
            f"remove the {self._scope.get('layer')!r} layer" if removable
            else "select a layer to remove it")

    # -- building ----------------------------------------------------------

    def refresh(self) -> None:
        map_name = self._scope.get("map")
        # Sync BEFORE the early return, or a scope with no map leaves both
        # add buttons in the state they were constructed in -- enabled, and
        # about to do nothing.
        self.__sync_buttons()
        if map_name is None:
            self.tree.blockSignals(True)
            self.tree.clear()
            self.tree.addTopLevelItem(QTreeWidgetItem(["no map is open"]))
            self.tree.blockSignals(False)
            self.count.setText("")
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
        self.__sync_buttons()

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
        self.__sync_buttons()

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

