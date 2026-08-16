"""Triggers on the selected object -- and, on screen, the fact that none run.

`editor/core/map_events.py` has been complete and tested since it was
written and had ZERO importers: 843 lines and a 497-line check verifying a
vocabulary nothing in the application could reach. This panel is the
surface. It shows the declaration on the selected object, edits every field
of it through `map.object.action.*`, and deletes it -- all of it as commands,
so it inherits undo, rollback, the history panel and the generated
`COMMANDS.md` without asking for any of them.

THE BANNER IS THE POINT
-----------------------
The engine cannot execute one of these. Not "not completely" -- there is no
collision detection at all, entities derive `PyoneerGameObject` rather than
`GameComponent` and so are not on the event bus, no `MAP_TRIGGER_*` event
type exists, and the renderer skips `<objectgroup>` entirely. A map authored
here plays exactly as it did before.

`PLAN_EDITOR.md` argued from that to "do not build the panel yet", and the
argument was right about one thing: a feature that LOOKS complete and does
nothing is the failure this project exists to avoid. But the fix for looking
complete is saying so, and the cost of not building it was 843 lines nobody
could reach. So the panel exists and it carries `NOT_WIRED` above every
field, in the widget tree rather than in a docstring or a tooltip -- because
the author reading a docstring is not the author who is about to spend an
afternoon wondering why the door does nothing.

WHY THE DESCRIPTION IS DATA
---------------------------
`describe_actions` returns an `Inspection`, the same structure
`editor/core/inspect.py` returns and the same one `fields.InspectionView`
renders. That buys typed editors, per-field remove buttons and
command emission for free, and -- more to the point -- it means a check can
assert "editing the trigger kind produces `map.object.action.set`" without
opening a window. The first run of the equivalent check on the Inspector
found two fields wired to the wrong verb.

It belongs in `editor/core/inspect.py` beside the other describers, and is
here because this pass owned this path. The move is mechanical: nothing in
`describe_actions` touches Qt.
"""
from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from editor.core import layers, map_events
from editor.core.commands import Command
from editor.core.inspect import Field, Inspection, Section
from editor.core.scope import Scope
from editor.ui.docks import ScopedDock
from editor.ui.fields import InspectionView

#: Shown above every field, always, declared or not. Every clause is a fact
#: about the repository as it stands rather than a caveat about polish, and
#: `tools/check_actions_panel.py` asserts this string is in a visible label
#: -- moving it into a docstring or a tooltip fails the check.
NOT_WIRED = (
    "Nothing here runs yet. The engine has no collision detection, entities "
    "are not on the event bus, there is no MAP_TRIGGER_* event type, and the "
    "renderer skips object layers entirely — so a map authored with these "
    "triggers plays exactly as it did before."
)

#: The rest of it, on hover. Kept off the face of the panel because the
#: sentence above is the one that has to be read every time.
NOT_WIRED_DETAIL = (
    "What IS real: Tiled reads and edits these properties in its own dialog, "
    "every edit here is a command with an exact inverse, and the file is "
    "under the byte-exactness contract. editor/core/map_events.py documents "
    "the seam a runtime would read them through — load, index, per-frame "
    "cell compare, filter, dispatch — so the executing half can be built "
    "against this without renegotiating anything."
)

_BANNER_STYLE = ("background: rgba(255, 206, 74, 38); "
                 "border-left: 3px solid rgb(255, 206, 74); "
                 "padding: 7px 9px; font-size: 11px;")

_NO_OBJECT = ("Select an object on an object layer. A trigger is a region, "
              "and a region is an object — there is nowhere else to hang one.")


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def object_at(session, scope: Scope):
    """`(object_layer, object)` for an object scope, or `(None, None)`.

    Never raises. A selection goes stale constantly -- an object removed by
    an undo, a layer renamed under it -- and every caller here wants the same
    answer for all of those.
    """
    if scope.kind != "object":
        return None, None
    try:
        document = session.project.map(scope.require("map"))
        layer = document.object_layer(scope.require("layer"))
        return layer, layer.find(int(scope.require("object")))
    except Exception:                                           # noqa: BLE001
        return None, None


def declared_keys(obj: Any) -> tuple[str, ...]:
    """Which map-event fields this object actually authors, in FIELDS order.

    Order matters for the removal batch: it is what makes deleting a trigger
    produce the same command list every time, and therefore the same history
    entry and the same diff.
    """
    if obj is None:
        return ()
    raw = obj.properties.as_dict()
    return tuple(capability.key for capability in map_events.FIELDS
                 if capability.property_name in raw)


def removal_commands(scope: Scope, keys: Iterable[str]) -> list[Command]:
    """One `map.object.action.unset` per declared field.

    A list rather than a `map.object.action.clear` verb. A clear would need
    an inverse that puts every property back AT ITS ORIGINAL POSITION, and
    `MapProperties` can delete a `<property>` and append one but cannot
    insert at an index -- so the verb would advertise an exactness it could
    not deliver. N unsets each carry their own exact per-field inverse, and
    the window applies the list as one transaction, so the author still gets
    one undo step.
    """
    return [Command("map.object.action.unset", scope, {"key": key})
            for key in keys]


# --------------------------------------------------------------------------
# Describing
# --------------------------------------------------------------------------

def describe_actions(session, scope: Scope) -> Inspection:
    """What this panel shows for one scope. Never raises."""
    layer, obj = object_at(session, scope)
    if obj is None:
        return Inspection(
            scope, "Actions",
            error=(_NO_OBJECT if scope.kind != "object" else
                   f"object {scope.get('object')} is no longer on "
                   f"{scope.get('layer')!r} — it may have been undone"))
    try:
        return _describe(session, scope, layer, obj)
    except Exception as exc:                                    # noqa: BLE001
        return Inspection(scope, "Actions",
                          error=f"{type(exc).__name__}: {exc}")


def _describe(session, scope: Scope, layer: Any, obj: Any) -> Inspection:
    document = session.project.map(scope.require("map"))
    layer_name = scope.require("layer")
    anchor = map_events.read_anchor(layer)
    event = map_events.read(obj, layer=anchor, source_layer=layer_name)
    raw = obj.properties.as_dict()

    declaration = Section(
        "Trigger",
        note=(event.describe() if event.declared else
              "This object declares nothing, so it is an ordinary object. "
              "Set a trigger kind, or tick `blocks` for a wall that never "
              "fires — the two are independent."))
    for capability in map_events.FIELDS:
        name = capability.property_name
        declared = name in raw
        # `coerce`, not the raw value: a hand-edited file can hold anything,
        # and the form must show what the READER will make of it rather than
        # what the bytes say. That is also `read_profile`'s contract for
        # layer capabilities, and the two panels should not disagree.
        current = capability.coerce(raw[name]) if declared else capability.default
        declaration.fields.append(Field(
            capability.key,
            capability.label + ("" if declared else "   (default)"),
            "choice" if capability.choices else capability.type,
            current,
            doc=capability.doc,
            choices=capability.choices,
            emit=(lambda k: lambda v: Command(
                "map.object.action.set", scope, {"key": k, "value": v}))(
                    capability.key),
            removable=declared,
            remove=(lambda k: lambda _v: Command(
                "map.object.action.unset", scope, {"key": k}))(capability.key)))

    return Inspection(scope, obj.name or f"object {obj.id}",
                      event.describe() if event.declared else "no declaration",
                      [declaration,
                       _region_section(document, obj, event),
                       _anchor_section(scope, layer_name, anchor)])


def _region_section(document, obj: Any, event: map_events.MapEvent) -> Section:
    """Where this trigger is, read-only, with the traps named.

    Read-only because moving and resizing an object is `map.object.move` and
    `map.object.set`, which the Inspector already offers; a second set of
    x/y/width/height editors here would be two panels racing to write the
    same four attributes.
    """
    region = event.region
    cells = region.cells(document.tile_width, document.tile_height)
    facts = Section("Region", [
        Field("rect", "rectangle", "str",
              f"{region.x:g}, {region.y:g}   {region.width:g} × "
              f"{region.height:g} px"),
        Field("cells", "cells covered", "str",
              f"{len(cells)} from ({cells[0][0]}, {cells[0][1]})"
              if cells else "none"),
    ])

    notes = ["Move or resize it in the Inspector, or by dragging in Tiled."]
    if region.is_point:
        notes.append("Zero-sized, so this is an authored CELL rather than a "
                     "region — it covers the one cell its origin falls in.")
    if obj.gid:
        notes.append("This is a tile object, which tmx anchors BOTTOM-left; "
                     "the rectangle above is the corrected one, and it is not "
                     "the y you see in the Inspector.")
    rotation = float(obj.element.attrib.get("rotation", "0") or 0)
    if rotation:
        notes.append(f"Rotated {rotation:g}°. The cells come from the "
                     f"UNROTATED rectangle, so the region drawn and the "
                     f"region that would fire are different.")
    facts.note = "  ".join(notes)
    return facts


def _anchor_section(scope: Scope, layer_name: str, anchor: str) -> Section:
    """`pyoneer_trigger_layer`, which lives on the objectgroup, not the object.

    Editable exactly when `map.layer.set` will accept it, ASKED rather than
    assumed. `trigger_layer` is not in `editor/core/layers.py`'s capability
    table today, and that table is what the verb's `choices` are built from,
    so there is no command that writes it -- the field is shown greyed with
    that reason rather than hidden, because hiding it would make the panel
    look complete and behave otherwise. Adding the capability is a one-entry
    change over there, and this field turns editable on its own when it
    lands; there is nothing to remember to come back and switch on.
    """
    known = "trigger_layer" in layers.BY_KEY
    layer_scope = Scope.of(("map", scope.require("map")), ("layer", layer_name))
    return Section("Anchor", [
        Field("trigger_layer", "anchored to", "str",
              anchor if known else (anchor or "(the whole map)"),
              doc="Which tile layer these regions belong to. Empty means the "
                  "whole map, which is the right default: a trigger that does "
                  "not care about elevation should not have to name a layer.",
              emit=(lambda v: Command("map.layer.set", layer_scope,
                                      {"key": "trigger_layer", "value": str(v)}))
                   if known else None,
              removable=known and bool(anchor),
              remove=(lambda _v: Command("map.layer.unset", layer_scope,
                                         {"key": "trigger_layer"}))
                     if known else None,
              blocked_reason="" if known else (
                  f"pyoneer_trigger_layer belongs to the {layer_name!r} "
                  f"OBJECT LAYER, not to this object, and it is not one of "
                  f"the capabilities editor/core/layers.py declares — so "
                  f"map.layer.set will not write it. Tiled will."))],
        note="It is a property of the object layer, so changing it re-aims "
             "every region on that layer at once.")


# --------------------------------------------------------------------------
# The panel
# --------------------------------------------------------------------------

class ActionsDock(ScopedDock):
    """The trigger declaration on the selected object, editable."""

    follows_selection = True

    def build_content(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.banner = QLabel(NOT_WIRED)
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(_BANNER_STYLE)
        self.banner.setToolTip(NOT_WIRED_DETAIL)
        layout.addWidget(self.banner)

        self.view = InspectionView(show_header=True, show_sources=False)
        self.view.command_requested.connect(self.__on_command)
        layout.addWidget(self.view, 1)

        row = QHBoxLayout()
        row.setContentsMargins(6, 4, 6, 6)
        self.add_trigger = QPushButton("Fires on enter")
        self.add_trigger.setToolTip(
            "Declare this region as firing when an entity enters it. Change "
            "the kind, and who may fire it, above.")
        self.add_trigger.clicked.connect(self.__on_add_trigger)
        row.addWidget(self.add_trigger)

        self.add_blocks = QPushButton("Solid")
        self.add_blocks.setToolTip(
            "Declare this region solid. Independent of the trigger kind: a "
            "wall is solid and never fires, a tripwire fires and is not "
            "solid, a locked door is both.")
        self.add_blocks.clicked.connect(self.__on_add_blocks)
        row.addWidget(self.add_blocks)

        row.addStretch(1)
        self.remove = QPushButton("Remove declaration")
        self.remove.clicked.connect(self.__on_remove)
        row.addWidget(self.remove)
        layout.addLayout(row)
        return holder

    # -- refreshing --------------------------------------------------------

    def refresh(self) -> None:
        self.view.show_inspection(describe_actions(self.session, self._scope))
        _layer, obj = object_at(self.session, self._scope)
        keys = declared_keys(obj)
        self.add_trigger.setEnabled(obj is not None and "trigger" not in keys)
        self.add_blocks.setEnabled(obj is not None and "blocks" not in keys)
        self.remove.setEnabled(bool(keys))
        self.remove.setToolTip(
            f"remove {len(keys)} declared field"
            f"{'' if len(keys) == 1 else 's'} as one undoable step"
            if keys else "this object declares nothing")

    # -- emitting ----------------------------------------------------------

    def __on_command(self, command) -> None:
        # run() reports a rejection and returns False; either way the form is
        # rebuilt from the document rather than left showing what was typed.
        self.window().run(command)
        self.refresh()

    def __on_add_trigger(self) -> None:
        self.__on_command(Command("map.object.action.set", self._scope,
                                  {"key": "trigger", "value": map_events.ENTER}))

    def __on_add_blocks(self) -> None:
        self.__on_command(Command("map.object.action.set", self._scope,
                                  {"key": "blocks", "value": True}))

    def __on_remove(self) -> None:
        _layer, obj = object_at(self.session, self._scope)
        keys = declared_keys(obj)
        if not keys:
            return
        answer = QMessageBox.question(
            self, "Remove declaration",
            f"Remove {', '.join(keys)} from this object?\n\n"
            f"It stays an ordinary object; nothing else about it changes. "
            f"One undo brings the whole declaration back.")
        if answer != QMessageBox.Yes:
            return
        self.window().run(removal_commands(self._scope, keys),
                          label="Remove the trigger declaration")
        self.refresh()
