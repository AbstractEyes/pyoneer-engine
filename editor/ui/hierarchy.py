"""The hierarchy -- one tree for the whole map, Unity/Godot style.

One tree rather than separate Layers and Objects panels, so the thing you
click and the thing you edit are in the same box and a group element cannot
be selected as though it were a layer.

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

A COMPANION IS NOT A LAYER YOU LOOK AT               #TAG:companion_folded_into_its_layer
-------------------------------------
A collision companion holds masks, not art: it declares `pyoneer_renders`
false, the engine skips it and so does the canvas, so its row offered a
visibility checkbox that changed nothing, a genre warning that was false
for it, and -- worst -- a selectable target that accepted art strokes the
runtime then read as no-data. It is folded away, and the art layer it
belongs to carries a badge instead: how many masks it has, and the reason
they do not reach the field when there is one.

The fold set comes from `companion_pairs`, which reads
`pyoneer_passability` and ranks the pairs; it is never taken from the
`Collision` name suffix. A layer somebody called `RoofCollision` and never
declared is an ordinary paintable layer and stays on screen, and a
declaration naming a layer the map does not have folds nothing -- so the
dangling case an author can actually fix stays visible.
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

from editor.core.collision import (
    NO_DATA,
    collision_first_gid,
    companion_pairs,
    gid_to_opinion,
    world_coordinate_fault,
)
from editor.core.commands import Command
from editor.core.inspect import Field
from editor.core.project import layer_tree
from editor.core.scope import Scope
from editor.ui.docks import ScopedDock

_KIND_MARK = {"tile": "▦", "object": "◈", "image": "▣", "group": "▾"}

#: The mask badge, drawn from the same Geometric Shapes block as the kind
#: marks above so it cannot be the one glyph a font lacks.
_MASK_MARK = "▨"

_TOP_LEVEL = "(top level)"


class HierarchyDock(ScopedDock):
    """Everything in the map, in the order it was authored."""

    follows_selection = True

    visibility_changed = Signal(str, bool)

    #: Why the companion fold is off, or "" when it is on. Read by `refresh`
    #: on the very first build, before `__collision` has ever run.
    __collision_refusal = ""

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
            # One dialog, not two: a second modal for the group would throw
            # away the typed name if it were cancelled.
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
        # No confirmation: undo restores the layer byte-for-byte, and that
        # reassurance is reported after the click rather than asked before it.
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

    # -- collision companions ----------------------------------------------

    def __collision(self, document):
        """Which layers to fold away, and what badge their art layer wears.

        Returns `(folded, badges)`, or `(None, {})` when the map's collision
        declarations cannot be read at all -- `companion_subcell` and the
        rest raise on contradictory content, and a panel that swallowed that
        would hide layers for a reason it never said.

        A badge is `(masks, companion, fault)`. `masks` counts CELLS THAT
        DECODE, not cells that are non-empty: a companion gid outside the
        collision tileset's range reads as NO_DATA in the engine, so
        counting it would report walls the field does not have. With no
        collision tileset in the map nothing decodes and the count is zero,
        which is the same answer `gid_to_opinion` gives.

        The `if gid` in front of the decode is not decoration: a companion is
        empty almost everywhere, and it turns 10,000 function calls per
        refresh into a truth test plus one call per painted cell.
        """
        self.__collision_refusal = ""
        try:
            pairs = companion_pairs(document)
            first_gid = collision_first_gid(document)
            badges: dict[str, tuple[int, str, str | None]] = {}
            for art, companion in pairs:
                gids = document.tile_layer(companion).gids()
                count = 0
                if first_gid is not None:
                    for gid in gids:
                        if gid and gid_to_opinion(gid, first_gid) != NO_DATA:
                            count += 1
                badges[art] = (count, companion,
                               world_coordinate_fault(document, art))
        except Exception as exc:                                # noqa: BLE001
            self.__collision_refusal = (
                f"this map's collision declarations could not be read, so no "
                f"companion layer is folded away: {exc}")
            return None, {}
        return {companion for _art, companion in pairs}, badges

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

        folded, badges = self.__collision(document)
        if folded is None:
            # NOTHING IS HIDDEN ON A QUESTION NOBODY COULD ANSWER. A map whose
            # collision declarations cannot be read is exactly the map whose
            # companion the author has to go and look at, so the fold is off
            # and the reason is on the map row rather than on a layer that is
            # no longer there to carry it.
            folded, badges = set(), {}
            root.setForeground(0, Qt.darkYellow)
            root.setToolTip(0, self.__collision_refusal)

        pack = self.session.project.genre
        objects_shown = 0
        for node in layer_tree(document):
            objects_shown += self.__add_node(root, node, document, pack,
                                             map_name, needle, folded, badges)
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
                   needle: str, folded: set[str],
                   badges: dict[str, tuple[int, str, str | None]]) -> int:
        if not node.selectable:
            item = QTreeWidgetItem([f"{_KIND_MARK['group']} {node.name}"])
            item.setForeground(0, Qt.gray)
            item.setToolTip(0, "a Tiled group: it holds layers but is not one, "
                               "so no command can act on it")
            parent.addChild(item)
            shown = 0
            for child in node.children:
                shown += self.__add_node(item, child, document, pack,
                                         map_name, needle, folded, badges)
            item.setExpanded(True)
            return shown

        if node.kind == "tile" and node.name in folded:
            # Its art layer draws the badge. A companion inside a group is
            # folded the same way, which is why this sits here and not in a
            # filter over the top-level list.
            return 0

        declared = pack.layer(node.name)
        depth = f"d{declared.depth}" if declared else "d?"
        badge = badges.get(node.name)
        label = (f"{_KIND_MARK.get(node.kind, '?')} {node.name}    "
                 f"{node.kind}  {depth}")
        if badge is not None:
            label += f"   {_MASK_MARK}{badge[0]}"
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.UserRole, f"map:{map_name}/layer:{node.name}")
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Unchecked if node.name in self.__hidden()
                           else Qt.Checked)
        notes: list[str] = []
        warn = declared is None
        if declared is None:
            notes.append(f"{node.name!r} is not declared by genre {pack.id!r}. "
                         f"If scripts/core/depth.py does not map it either, "
                         f"it will not render at all.")
        elif declared.doc:
            notes.append(declared.doc)
        if badge is not None:
            count, companion, fault = badge
            notes.append(f"{count} mask{'' if count == 1 else 's'} painted "
                         f"for this layer, in {companion!r} — a data layer, "
                         f"which is why it is not a row of its own. The "
                         f"layer inspector's `passability` property names it.")
            if fault is not None:
                # `world_coordinate_fault`'s own words, forwarded rather than
                # paraphrased: it names the properties in the spelling the
                # author has to go and edit, and it is the reason
                # `collision_layers` leaves this layer out of the stack.
                warn = True
                notes.append(f"BUT {node.name!r} is {fault}, so its cells are "
                             f"not the map's cells and nothing on it blocks "
                             f"movement: those {count} masks reach no field.")
        if warn:
            item.setForeground(0, Qt.darkYellow)
        item.setToolTip(0, '\n\n'.join(notes))
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

