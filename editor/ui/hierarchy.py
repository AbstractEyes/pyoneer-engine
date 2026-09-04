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

A ROW IS A CONTROL, NOT A LABEL
-------------------------------
Double-clicking an object row centres the canvas on it. Right-clicking one
opens Select, Focus, Edit, Cut, Copy, Paste and Delete. Right-clicking an
object LAYER row opens the same menu with Paste live and the object entries
greyed -- without that, the only surface a cut object could be pasted back
onto would be the row that was just cut away, and a clipboard you cannot
empty is a clipboard that does not work.

An entry that cannot act is DISABLED and carries the reason in its own
label, the way `TilePalette.tileset_menu` does one panel over: a control
that is present and refusing has already spent the click by the time the
refusal arrives. Over any other row -- a tile layer, a group, the map --
the menu does not open at all, because a menu whose every entry is greyed
tells the author they missed without telling them what they missed.

The clipboard holds AUTHORED DATA AND NEVER AN ID; see `ObjectClipping`
for why an id must not make the trip. A paste is ONE `map.object.add`, so
it is one undo step, and it lands a tile away from the last one it made
rather than exactly on its source -- a duplicate nobody can see is
indistinguishable from nothing having happened.

AN OPEN MENU IS ABOUT AN OBJECT, NEVER ABOUT AN ID   #TAG:the_menu_holds_the_object_not_the_id
--------------------------------------------------
`popup` RETURNS WITH THE MENU STILL ON SCREEN and the event loop still
running, which is the whole reason it is used instead of the blocking call
law 13 is named after -- and it means the document can change while the
menu is up. `EditorWindow` watches `editor/requests/` and applies an AI
response from inside that same loop, so this is not a thought experiment:
measured, the menu stayed up, the response recycled an id onto a DIFFERENT
object, and Delete removed that one.

Ids ARE recycled. `MapDocument._release_object_id` rolls `nextobjectid`
back so that add-then-remove is byte-exact, so `find(id)` after a recycle
answers a DIFFERENT OBJECT rather than answering nothing -- and every
greying test in this panel asks "does it resolve", which a recycled id
passes.

SO THE ELEMENT IS THE IDENTITY, exactly as `SelectedObject` already
decided it for the canvas, and this panel imports that record rather than
inventing a second opinion about what an id means. `identify` takes the
card when the menu is BUILT -- while the author can still see the row it
was built for -- and every entry that acts on the object re-validates
through `stale_refusal` when it is TRIGGERED.

RE-VALIDATED AT TRIGGER, NOT CLOSED ON CHANGE, and the choice is
deliberate. Closing the menu would need a document-changed wire this dock
does not have, would free a QMenu while its own signal may be on the stack
(the neighbour of law 12), and would still leave every other route in --
a shortcut, a script, a relayed request -- resolving by id alone. The
guard belongs at the moment of the action, where there is exactly one of
them per verb.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from scripts.core.depth import MAP_DEPTH, OBJECT_DEPTH
from scripts.core.errors import PyoneerError
from scripts.game.behavior.base import BEHAVIORS
from scripts.game.behavior.registry import validate_list

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
# The menu seam, imported rather than respelled. `_exec_menu` pops with
# `popup` and never with the blocking call law 13 is about, and it is held
# as an instance attribute so a check can read the menu a real right-click
# built. Its own docstring says why there is one function and not one per
# panel: a second spelling is a second menu nothing is watching, which is
# how the modal that hung this suite for 40+ minutes got in.
# ...and `SelectedObject` with them, for the same reason: the canvas
# already paid for the measurement that an id is not an identity -- its
# docstring is where those five gestures are written down -- and two
# records deciding what an id means is how this defect existed in the
# first place. (Cited by name and not as a tag: a `#TAG:` in source is a
# PLACEMENT, and placing the canvas's twice is a duplicate.)
from editor.ui.canvas import SelectedObject, _exec_menu, _hold_menu
from editor.ui.docks import ScopedDock

_KIND_MARK = {"tile": "▦", "object": "◈", "image": "▣", "group": "▾"}

#: The mask badge, drawn from the same Geometric Shapes block as the kind
#: marks above so it cannot be the one glyph a font lacks.
_MASK_MARK = "▨"

_TOP_LEVEL = "(top level)"


@dataclass(frozen=True)
class ObjectClipping:
    """One object's authored data, with its id deliberately left behind.

    AN ID DOES NOT MAKE THE TRIP. An id is per-map and per-document, and
    this document RECYCLES them -- `MapDocument._release_object_id` rolls
    `nextobjectid` back so that add-then-remove is byte-exact, which means
    the id you copied is very likely handed to a DIFFERENT object before
    you paste. A clipping that carried one would paste onto a stranger,
    and the canvas already learned this lesson the expensive way: its
    selection names an object and not an id for the same reason.

    `properties` is EVERY custom property, not only the `pyoneer_` ones.
    The behavior list and its parameters are the point of the exercise,
    but an object also carries whatever the author invented -- `locked`,
    `loot` -- and a copy that quietly dropped those is a duplicate that
    looks right and plays differently (law 7). They are held as a sorted
    tuple of pairs so a clipping cannot be edited after the fact by
    whoever is holding it.

    `map_name` rides along so a paste can tell same-map from cross-map. It
    is never written into anything: it exists for `paste_refusal`, where a
    gid is the one field whose meaning does not survive the trip.
    """

    map_name: str
    layer: str
    type: str
    name: str
    x: float
    y: float
    width: float
    height: float
    gid: int
    properties: tuple[tuple[str, Any], ...]
    label: str

    def property_dict(self) -> dict[str, Any]:
        """A fresh mutable copy, for handing to `map.object.add`."""
        return dict(self.properties)


class HierarchyDock(ScopedDock):
    """Everything in the map, in the order it was authored."""

    follows_selection = True

    visibility_changed = Signal(str, bool)

    #: Why the companion fold is off, or "" when it is on. Read by `refresh`
    #: on the very first build, before `__collision` has ever run.
    __collision_refusal = ""

    #: What Copy and Cut last took. Held on the CLASS, not the instance, so
    #: one cut can be pasted after the window has switched maps -- the dock
    #: survives that, but a clipboard hidden behind a per-instance attribute
    #: would still be the wrong shape the day a second window exists.
    _clipboard: "ObjectClipping | None" = None

    #: How many times the current clipping has been pasted. Reset by every
    #: Copy and Cut, and the whole reason two pastes never land on top of
    #: each other. See `paste_position`.
    _paste_step: int = 0

    def build_content(self) -> QWidget:
        # The menu seam, replaceable per instance exactly like `self.ask`:
        # a check replaces it to READ the menu a real right-click built,
        # and the unreplaced path pops rather than blocking (law 13).
        self.popup_menu = _exec_menu
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
        self.tree.itemDoubleClicked.connect(self.__on_double)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.__on_context_menu)
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

    def __orphaned_companion(self, layer: str) -> list[str]:
        """The companion `layer` takes with it -- at most one, often none.

        A COMPANION LEAVES WITH THE LAYER IT BELONGS TO. #TAG:companion_leaves_with_its_layer
        Removing the art layer alone stranded it, and a stranded companion
        is no longer folded: it UNFOLDS into the tree as a
        `pyoneer_renders` false row holding masks for a layer that is gone
        -- the visible collision tilemap this panel exists to abolish,
        produced by the one operation an author performs on a painted
        layer. The minus button cannot reach it either, because a folded
        companion has no row to select.

        Two refusals, both deliberate:

          * A companion a SECOND art layer still points at is LEFT ALONE.
            Two layers sharing one companion is legal, and taking it away
            from a living layer is a worse outcome than leaving a stray.
          * The pairing is `companion_pairs` and nothing else -- not the
            `Collision` name suffix, and not `pyoneer_passability` being
            present. `companion_name` is declared-wins-over-CONVENTION, so
            an undeclared `Floor` pairs with `FloorCollision`, and a test
            for the property would miss every layer the author has.
        """
        try:
            document = self.session.project.map(self._scope.require("map"))
            pairs = companion_pairs(document)
        except Exception as exc:                                # noqa: BLE001
            # The same answer `refresh` gives when the declarations cannot
            # be read: nothing is folded, so the companion still HAS a row
            # and the author can remove it themselves. Taking a layer away
            # on a question nobody could answer is the one removal undo
            # cannot explain.
            self.notify(f"this map's collision declarations could not be "
                        f"read, so only {layer!r} was considered for "
                        f"removal: {exc}", seconds=10)
            return []
        shared = {companion for art, companion in pairs if art != layer}
        return [companion for art, companion in pairs
                if art == layer and companion not in shared]

    def __on_remove(self) -> None:
        layer = self._scope.get("layer")
        if layer is None or self._scope.kind == "object":
            return
        map_scope = Scope.of(("map", self._scope.require("map")))
        going = [layer] + self.__orphaned_companion(layer)
        # ONE transaction, so ONE Ctrl+Z takes both back. Two `run` calls
        # would leave the author pressing undo once and looking at half a
        # deleted pair -- an art layer restored with no masks, or masks with
        # no layer.
        commands = [Command("map.layer.remove", map_scope.child("layer", name))
                    for name in going]
        # No confirmation: undo restores the layer byte-for-byte, and that
        # reassurance is reported after the click rather than asked before it.
        if self.window().run(commands, label=f"remove {', '.join(going)}"):
            with_companion = ("" if len(going) == 1 else
                              f" and its mask companion {going[1]!r}")
            self.notify(f"removed {layer!r}{with_companion} and everything "
                        f"on it — one Ctrl+Z restores "
                        f"{'it' if len(going) == 1 else 'both'} "
                        f"byte-for-byte", seconds=10)

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

    # -- the row menu ------------------------------------------------------

    def row_scope(self, point) -> Scope | None:
        """The scope of the row under a VIEWPORT point, or None.

        THE HIT TEST IS THE SILENT HALF. `itemAt` answers None past the end
        of the list and for a point that is over no row at all, which is
        what stops a menu from acting on whatever happened to be selected
        instead of on what the author pointed at -- the same failure
        `TilePalette.header_at` exists to prevent one panel over, where a
        clamping hit test would have offered to rename the wrong sheet.
        """
        item = self.tree.itemAt(point)
        if item is None:
            return None
        raw = item.data(0, Qt.UserRole)
        if not raw:
            return None
        return Scope.parse(raw)

    def __on_context_menu(self, point) -> None:
        """`customContextMenuRequested` delivers a point in the TREE's own
        coordinates and every hit test below wants the VIEWPORT's; the two
        differ by the frame. One conversion, in one place, so no caller has
        to remember which of the two it is holding."""
        self.open_object_menu(self.tree.viewport().mapFrom(self.tree, point))

    def open_object_menu(self, point) -> None:
        """Right-click, in viewport coordinates.

        Opens on an object row, and on an object LAYER row so that a
        clipping has somewhere to land. Over anything else it opens NOTHING
        and says what the button means instead -- `MapCanvas` answers the
        same question the same way over bare ground.
        """
        scope = self.row_scope(point)
        if scope is None or not (scope.kind == "object"
                                 or self.is_object_layer(scope)):
            self.notify("right-click an object for Select, Focus, Edit, Cut, "
                        "Copy and Delete — or an object layer to paste onto")
            return
        menu = self.object_menu(scope)
        # Parented to the tree, so it was never a top-level orphan (law
        # 12) -- and freed when it closes rather than now, because `popup`
        # returns with it still on screen. See `_hold_menu`.
        _hold_menu(menu)
        self.popup_menu(menu, self.tree.viewport().mapToGlobal(point))

    def object_menu(self, scope: Scope) -> QMenu:
        """The row menu, built and not yet shown.

        Built apart from being shown for `TilePalette.tileset_menu`'s two
        reasons: a check can trigger an entry without touching a modal (law
        13), and every entry's ENABLEMENT is a fact about the map that has
        to be read BEFORE the menu appears rather than after the click.
        """
        menu = QMenu(self.tree)
        menu.setToolTipsVisible(True)
        on_object = self.object_refusal(scope)
        # WHICH OBJECT THIS MENU IS ABOUT, taken now, while the row the
        # author pointed at is still the row on screen. Every entry below
        # that acts on the object carries it and re-validates against it
        # when it is triggered, because `popup` returns with the menu still
        # up and the document free to change underneath it. None on a layer
        # row, which is what leaves Paste live there.
        card = self.identify(scope)

        self.__entry(menu, "Select", "",
                     "make this the editor's selection — the inspector, the "
                     "prompt strip and the canvas all follow it",
                     lambda: self.select_scope(scope, card))
        self.__entry(menu, "Focus", self.focus_refusal(scope),
                     "centre the canvas on it and select it",
                     lambda: self.focus_object(scope, card))
        self.__entry(menu, "Edit…", on_object,
                     "open the entity editing screen on it",
                     lambda: self.edit_object(scope, card))
        self.__entry(menu, "Cut", on_object,
                     "copy it and take it off the map, in ONE undo step",
                     lambda: self.cut_object(scope, card))
        self.__entry(menu, "Copy", on_object,
                     "take its type, its size and every custom property — "
                     "never its id, which this document recycles",
                     lambda: self.copy_object(scope, card))
        # NO CARD, and that is the contrast that proves the rest is not a
        # dead menu: a paste acts on the LAYER this row is on, which a
        # recycled id cannot change. `paste_object` re-reads `paste_refusal`
        # when it runs, so a layer that went away is still refused.
        self.__entry(menu, "Paste", self.paste_refusal(scope),
                     "add a copy, a tile away from the last one",
                     lambda: self.paste_object(scope))
        self.__entry(menu, "Delete", on_object,
                     "remove it. One Ctrl+Z puts it back with every property "
                     "it carried",
                     lambda: self.delete_object(scope, card))
        return menu

    def __entry(self, menu: QMenu, text: str, refusal: str, tip: str, act):
        """One menu row. A refusal greys it AND goes in its own label.

        The house rule, and the reason it is a helper rather than seven
        copies of an if: a control that is present and refusing has already
        spent the click by the time the refusal arrives, so the reason has
        to be readable on the way TO the click.
        """
        entry = menu.addAction(text)
        entry.triggered.connect(lambda _checked=False: act())
        if refusal:
            entry.setEnabled(False)
            entry.setText(f"{text}  ·  {refusal}")
            entry.setToolTip(refusal)
        else:
            entry.setToolTip(tip)
        return entry

    # -- what a row can and cannot do --------------------------------------

    def __object(self, scope: Scope):
        """The `MapObject` a scope names, or None. Never raises.

        Asked while a menu is being BUILT, where a raise would take the
        gesture with it -- and a row can outlive its object by one refresh,
        which is exactly the case the menu has to be able to grey out.
        """
        if scope.kind != "object":
            return None
        try:
            document = self.session.project.map(scope.require("map"))
            layer = scope.require("layer")
            if layer not in document.object_layer_names():
                return None
            return document.object_layer(layer).find(int(scope.name))
        except Exception:                                       # noqa: BLE001
            return None

    def identify(self, scope: Scope) -> SelectedObject | None:
        """WHICH object this scope names right now, as a card. Never raises.

        The canvas's record, not a second one: `SelectedObject`'s own
        docstring carries the five gestures that measured it. The card
        holds the live `<object>` element, and the element is what survives
        a move, a rename and a property write, while `add_object` and
        `restore_object` both build a new one.

        None for every scope `__object` answers None for, and for a layer
        row: a row that names no object has no identity to be wrong about.
        """
        found = self.__object(scope)
        if found is None:
            return None
        return SelectedObject(layer=scope.require("layer"),
                              object_id=found.id, element=found.element,
                              x=found.x, y=found.y,
                              type=found.type, name=found.name)

    def stale_refusal(self, scope: Scope, card) -> str:
        """Why the object a card was taken from cannot be acted on, or "".

        THE HALF `object_refusal` CANNOT SEE. That one asks whether the id
        resolves, and a RECYCLED id resolves -- to somebody else. This asks
        the only question that separates the two: is the element the one
        the card was taken from.

        BOTH NAMES GO IN THE SENTENCE, the object the author asked for and
        the object the id answers with now, because "that is not it any
        more" without saying what it is now is a refusal the author cannot
        act on.

        A card that still names its object is REFRESHED here rather than
        merely passed, so a legitimate edit under an open menu -- a move, a
        rename from the inspector, an undo of either -- follows the object
        instead of dropping the gesture. `MapCanvas` revalidates its own
        selection this way, for this reason.

        "" for a null card, which is what a layer row and every direct call
        hand in: an address is all the caller gave, so an address is all
        this can check.
        """
        if card is None:
            return ""
        found = self.__object(scope)
        if found is None:
            return f"{card.describe()} is gone"
        if not card.still(found):
            return (f"object {card.object_id} is not {card.describe()} any "
                    f"more — that id now names {self.object_label(found)}")
        card.refresh(found)
        return ""

    @staticmethod
    def object_label(found) -> str:
        """How one object says which one it is, in a message.

        Its authored name when it has one, because that is the string the
        author typed and the only one they will recognise; the id when it
        has none, whole rather than invented into something friendlier.
        """
        return f"{found.name or '#%d' % found.id} ({found.type or 'no type'})"

    def object_refusal(self, scope: Scope) -> str:
        """Why Edit, Cut, Copy and Delete cannot act on this row, or ""."""
        if scope.kind == "layer":
            return f"the {scope.name!r} layer is not an object"
        if scope.kind != "object":
            return f"{scope} is not an object"
        if self.__object(scope) is None:
            return f"{scope} no longer resolves to an object on this map"
        return ""

    def __canvas_focus(self):
        """`MapCanvas.focus_object`, or None while the canvas has none."""
        return getattr(getattr(self.window(), "canvas", None),
                       "focus_object", None)

    def focus_refusal(self, scope: Scope) -> str:
        """Why Focus cannot act, or "".

        Names the MISSING METHOD when that is the answer. The canvas owns
        centring and this panel calls it; a Focus entry that was live and
        then quietly did nothing would be the reachability failure this
        repository keeps repeating, dressed as a working control.
        """
        blocked = self.object_refusal(scope)
        if blocked:
            return blocked
        if not callable(self.__canvas_focus()):
            return ("this canvas has no focus_object(scope) yet, so nothing "
                    "here can centre the view on an object")
        return ""

    def paste_layer(self, scope: Scope) -> str | None:
        """The object layer a paste on this row would land on, or None."""
        if scope.kind not in ("layer", "object"):
            return None
        name = scope.get("layer")
        map_name = scope.get("map")
        if name is None or map_name is None:
            return None
        try:
            document = self.session.project.map(map_name)
        except Exception:                                       # noqa: BLE001
            return None
        return name if name in document.object_layer_names() else None

    def is_object_layer(self, scope: Scope) -> bool:
        return scope.kind == "layer" and self.paste_layer(scope) is not None

    def paste_refusal(self, scope: Scope) -> str:
        """Why Paste cannot act on this row, or "".

        TWO REFUSALS THAT ARE NOT ABOUT THE ROW, and both are about a
        clipping meaning something different where it is going:

          * A GID IS A NUMBER IN ONE MAP'S TILESETS. Cross-map paste is
            otherwise free -- an object's authored data is its own -- but a
            `gid` names a tile through the target map's `firstgid`s, so the
            same number in another map draws different art or none at all,
            raising nowhere. That is refused rather than pasted; a gidless
            object crosses maps freely.
          * A BEHAVIOR TOKEN THE REGISTRY DOES NOT KNOW. `resolve` raises
            on one by design (law 8), so a paste that stripped it would
            produce an object that looks authored and does nothing. The
            token is named here, in the entry's own label, and the
            authority is `validate_list` rather than a membership test --
            it also catches the duplicate and the declared conflict, which
            a membership test would paste straight through.

        AND ONE THAT IS ABOUT THE ROW: A HIDDEN LAYER. This is the same
        hole `MapCanvas.__place_object` closed, arrived at by the other
        door -- a paste onto an unticked layer creates an object that is
        not drawn, cannot be clicked, cannot be dragged and cannot be
        right-clicked, because `__draw_objects` and `objects_under` both
        skip a hidden layer. Creation is the one direction that cannot be
        walked back by hand, so it is refused here rather than pasted and
        the layer is NOT switched back on instead: visibility is view
        state, it never enters the command stream, and unhiding as a side
        effect would leave Ctrl+Z able to take the object back and unable
        to put the tick back. The words are the canvas's words on purpose.
        #TAG:a_paste_is_a_creation_too
        """
        clip = self._clipboard
        if clip is None:
            return "nothing has been copied yet"
        map_name = scope.get("map")
        if map_name is None:
            return "this row is not on a map"
        layer = self.paste_layer(scope)
        if layer is None:
            return "an object goes on an object layer, and this row is not one"
        if layer in self.__hidden():
            return (f"a paste puts an object on a layer, and {layer!r} is "
                    f"hidden — switch the layer back on in Layers first")
        if clip.map_name != map_name and clip.gid:
            return (f"{clip.label} draws tile gid {clip.gid}, which is a "
                    f"number in map:{clip.map_name}'s tilesets and not in "
                    f"map:{map_name}'s")
        try:
            validate_list(clip.property_dict().get(BEHAVIORS),
                          where=f"the copied {clip.label}")
        except PyoneerError as exc:                             # noqa: BLE001
            token = getattr(exc, "name", "")
            return (f"its {BEHAVIORS} names {token!r}, which no behavior is "
                    f"registered under" if token
                    else getattr(exc, "message", str(exc)))
        return ""

    # -- what a row can do -------------------------------------------------

    def edit_object(self, scope: Scope, card=None) -> bool:
        """Open the entity editing screen. The window owns that door.

        `EditorWindow.edit_object` is already the far end of the canvas's
        double-click, so this calls it rather than growing a second route
        to the same window -- two openers is two places for the one-window
        rule to be forgotten.

        `card` is the identity the menu was built on; see `stale_refusal`.
        """
        refusal = self.stale_refusal(scope, card) or self.object_refusal(scope)
        if refusal:
            self.notify(f"there is nothing to edit here: {refusal}")
            return False
        opener = getattr(self.window(), "edit_object", None)
        if not callable(opener):
            self.notify("this window has no entity editor to open")
            return False
        opener(scope)
        return True

    def focus_object(self, scope: Scope, card=None) -> bool:
        """Centre the canvas on the object this row names.

        SPELLED OUT, not reached through `__canvas_focus`, and that is not
        style. The counter-move this repository writes down for its own
        signature defect is "grep for a caller from the layer ABOVE the
        thing you just built" -- and measured here, the getter form left
        `grep -rn "canvas.focus_object" editor/ui/` returning the canvas's
        own docstring and NOTHING ELSE, which reads exactly like a
        capability with no caller. `focus_refusal` has already proved the
        attribute is there and callable, so the direct spelling is the
        same call and one a grep can find.
        """
        refusal = self.stale_refusal(scope, card) or self.focus_refusal(scope)
        if refusal:
            self.notify(f"the canvas did not move: {refusal}", seconds=10)
            return False
        if not self.window().canvas.focus_object(scope):
            self.notify(f"the canvas could not centre on {scope}: it resolves "
                        f"to nothing there", seconds=10)
            return False
        return True

    def copy_object(self, scope: Scope, card=None) -> bool:
        """Snapshot the object onto the clipboard. Changes nothing.

        A snapshot and not a command: nothing about the map moves, so there
        is nothing to undo and nothing to put in the history.

        IT STILL TAKES THE CARD. A copy writes nothing to the map, which
        makes it look like the one entry that could not do harm -- but the
        clipping it takes is what the next Paste AUTHORS, so a copy off a
        recycled id lays a stranger's properties down on the next click.
        """
        refusal = self.stale_refusal(scope, card) or self.object_refusal(scope)
        if refusal:
            self.notify(f"nothing was copied: {refusal}")
            return False
        found = self.__object(scope)
        clip = ObjectClipping(
            map_name=scope.require("map"), layer=scope.require("layer"),
            type=found.type, name=found.name,
            x=found.x, y=found.y,
            width=found.width, height=found.height, gid=found.gid,
            properties=tuple(sorted(found.properties.as_dict().items())),
            label=self.object_label(found))
        HierarchyDock._clipboard = clip
        HierarchyDock._paste_step = 0
        count = len(clip.properties)
        self.notify(f"copied {clip.label} and its {count} "
                    f"propert{'y' if count == 1 else 'ies'} — Paste puts a "
                    f"new one on any object layer", seconds=8)
        return True

    def cut_object(self, scope: Scope, card=None) -> bool:
        """Copy it and take it off the map, as ONE transaction.

        ONE `run` call, so ONE Ctrl+Z puts it back -- the same reason
        `__on_remove` batches a layer with its companion rather than
        running two commands and leaving the author looking at half a pair.

        THE SNAPSHOT IS TAKEN FIRST and survives a refused removal. A
        clipboard that emptied itself when the map said no would lose the
        thing the author was carrying, on the one path where they can least
        afford it.
        """
        # ASKED HERE FIRST, in cut's own words, and then again inside the
        # copy: a cut that could only refuse as "nothing was copied" would
        # name the wrong half of a gesture the author spelled as one verb.
        refusal = self.stale_refusal(scope, card)
        if refusal:
            self.notify(f"nothing was cut: {refusal}", seconds=10)
            return False
        if not self.copy_object(scope, card):
            return False
        clip = self._clipboard
        layer_scope = scope.parent()
        if not self.window().run([Command("map.object.remove", scope)],
                                 label=f"cut {clip.label}"):
            return False
        # Onto the layer it came off, never the scope that just stopped
        # resolving: a selection pointing at a removed object is a stale
        # address every panel downstream has to re-derive nothing from.
        self.select_scope(layer_scope)
        self.notify(f"cut {clip.label} — it is on the clipboard, and one "
                    f"Ctrl+Z puts it back on {layer_scope} with every "
                    f"property it carried", seconds=10)
        return True

    def delete_object(self, scope: Scope, card=None) -> bool:
        """Remove the object. `map.object.remove` restores its whole XML.

        `card` is the identity the menu was built on. Without it this took
        an ADDRESS and removed whatever answered it, which after a recycle
        is a DIFFERENT OBJECT -- measured, and the reason `stale_refusal`
        exists.
        """
        refusal = self.stale_refusal(scope, card) or self.object_refusal(scope)
        if refusal:
            self.notify(f"nothing was deleted: {refusal}")
            return False
        label = self.object_label(self.__object(scope))
        layer_scope = scope.parent()
        # No confirmation: the inverse restores the whole `<object>`
        # element, shape children and all, and that reassurance is reported
        # after the click rather than asked before it.
        if not self.window().run([Command("map.object.remove", scope)],
                                 label=f"remove {label}"):
            return False
        self.select_scope(layer_scope)
        self.notify(f"removed {label} — one Ctrl+Z puts it back with every "
                    f"property it carried", seconds=10)
        return True

    @staticmethod
    def paste_position(clip: ObjectClipping, document,
                       step: int) -> tuple[float, float]:
        """Where the `step`-th paste of `clip` lands, in world pixels.

        ONE TILE DOWN AND RIGHT PER PASTE, never on the source. A duplicate
        at the source's own coordinates draws underneath it, so the click
        that made it is indistinguishable from a click that did nothing --
        and the second paste has to clear the first for the same reason,
        which is what `step` counts.

        WRAPPED, NOT CLAMPED, and both alternatives fail the same test.
        Cascading off the bottom-right corner puts a paste outside the map,
        which is legal tmx that draws nowhere -- invisible again, by a
        different route. Clamping to the edge stacks every later paste on
        one clamped pixel -- invisible again, by the first route. Wrapping
        keeps every paste inside the map AND keeps consecutive ones apart.
        """
        across = max(1, document.width) * document.tile_width
        down = max(1, document.height) * document.tile_height
        return ((clip.x + step * document.tile_width) % across,
                (clip.y + step * document.tile_height) % down)

    def paste_object(self, scope: Scope) -> bool:
        """Add a copy of the clipping to the object layer this row is on.

        ONE `map.object.add`, which is what makes a paste ONE undo step.
        The alternative -- add, then set N properties -- cannot be built:
        every command in a batch is constructed before the first one runs,
        and the new object's id is not handed out until the add has.

        THE PACK'S STARTING LIST IS REPORTED, NOT FOUGHT. `map.object.add`
        materialises a genre pack's `object_classes` list onto a new object
        when the caller supplies no `pyoneer_behaviors`, so a clipping that
        carried none is born with the pack's. That precedence is the add
        verb's and this does not argue with it -- an author's own list, an
        explicitly empty one included, still wins outright -- but it IS a
        difference between the source and the copy, so the report below
        names the properties that appeared rather than letting them arrive
        in silence.
        """
        refusal = self.paste_refusal(scope)
        if refusal:
            self.notify(f"nothing was pasted: {refusal}", seconds=10)
            return False
        clip = self._clipboard
        map_name = scope.require("map")
        layer = self.paste_layer(scope)
        document = self.session.project.map(map_name)
        step = self._paste_step + 1
        x, y = self.paste_position(clip, document, step)
        layer_scope = Scope.of(("map", map_name), ("layer", layer))
        before = {obj.id for obj in document.object_layer(layer).objects()}
        if not self.window().run(
                [Command("map.object.add", layer_scope,
                         {"type": clip.type, "name": clip.name,
                          "x": x, "y": y,
                          "width": clip.width, "height": clip.height,
                          "gid": clip.gid,
                          "properties": clip.property_dict()})],
                label=f"paste {clip.label}"):
            return False
        HierarchyDock._paste_step = step

        document = self.session.project.map(map_name)
        fresh = [obj for obj in document.object_layer(layer).objects()
                 if obj.id not in before]
        if not fresh:
            # Not reachable by clicking -- `run` answered True, so the add
            # applied -- and reported rather than assumed all the same,
            # because the alternative is a paste that claims to have worked
            # and re-selects the row the author was already on.
            self.notify(f"the paste ran and no new object appeared on "
                        f"{layer_scope}")
            return False
        made = fresh[-1]
        self.select_scope(layer_scope.child("object", str(made.id)))
        born = sorted(set(made.properties.as_dict()) - set(clip.property_dict()))
        extra = (f", and the {self.session.project.genre.id!r} pack's starting "
                 f"list for {clip.type!r} was written onto it as "
                 f"{', '.join(born)}" if born else "")
        self.notify(f"pasted {clip.label} as #{made.id} at ({x:g}, {y:g}) on "
                    f"{layer!r}{extra} — one Ctrl+Z takes it away", seconds=10)
        return True

    # -- selection ---------------------------------------------------------

    def select_scope(self, scope: Scope, card=None) -> bool:
        """Select a row without clicking it -- what a menu entry needs.

        REFUSES A STALE CARD like every other entry, and it writes nothing,
        which is exactly why the temptation is to let it through. It must
        not be let through: the selection is what the inspector, the prompt
        strip and the canvas all follow, so a Select off a recycled id
        points every one of them at an object the author never pointed at,
        and the next edit they make there is authored in earnest.

        Moves the tree's own cursor as well as the editor's selection, so
        the row the author acted on is the row that ends up highlighted.
        The move is made with signals blocked and then announced by hand,
        rather than letting `currentItemChanged` do it: a scope the tree
        has no row for (a layer whose object was just cut) would otherwise
        announce nothing at all.
        """
        refusal = self.stale_refusal(scope, card)
        if refusal:
            self.notify(f"nothing was selected: {refusal}", seconds=10)
            return False
        self.tree.blockSignals(True)
        self.__reselect(str(scope))
        self.tree.blockSignals(False)
        self.__announce(scope)
        return True

    def __announce(self, scope: Scope) -> None:
        """Tell the panel and the editor that this is what is selected.

        ONE spelling, because a click and a menu entry must mean the same
        thing: the panel's own prompt strip hangs off `_scope`, and every
        inspector hangs off `window.selection`.
        """
        self.set_scope(scope)
        window = self.window()
        if hasattr(window, "selection"):
            window.selection.select(scope)

    def __on_current(self, current, _previous) -> None:
        if current is None:
            return
        raw = current.data(0, Qt.UserRole)
        if not raw:
            return
        self.__announce(Scope.parse(raw))

    def __on_double(self, item, _column) -> None:
        """Double-click. AN OBJECT ROW MOVES THE CANVAS ONTO IT.

        Selection is the single click's job and already happened by the
        time this runs -- Qt presses before it double-clicks -- so this
        adds the one thing a click cannot: finding the thing on a map
        bigger than the viewport. A row that is not an object says what
        the gesture is for rather than doing nothing.
        """
        raw = item.data(0, Qt.UserRole)
        if not raw:
            return
        scope = Scope.parse(raw)
        if scope.kind != "object":
            self.notify("double-click an object to centre the canvas on it")
            return
        self.focus_object(scope)

    def on_selection_changed(self, scope: Scope) -> None:
        """Follow a selection made elsewhere -- canvas, problems, anywhere.

        Re-scoping is not just cosmetic: the panel's own prompt strip hangs
        off `_scope`, so without this a note typed in the hierarchy after
        clicking a tile on the canvas landed on the map rather than on the
        layer you were looking at.

        A SCOPE ON ANOTHER MAP IS TWO DIFFERENT EVENTS, and the guard here
        used to answer both by ignoring them. Since the window grew a map
        picker, `__switch_map` selects the new map's scope, and a tree that
        refused it went on listing the map that is no longer on screen --
        every row an address the canvas will not act on, and every menu on
        those rows aimed at the wrong document. So a scope naming the map
        THIS WINDOW IS NOW SHOWING is adopted and the tree is rebuilt for
        it. Anything else is still refused: the validator walks every map,
        so double-clicking a problem on a map nobody is looking at must not
        drag the tree off the one that is.
        """
        wanted = scope.get("map")
        if wanted != self._scope.get("map"):
            if wanted is None or wanted != getattr(self.window(), "map_name",
                                                   None):
                return
            self.set_scope(scope)
            self.refresh()
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

