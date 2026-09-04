"""Triggers on the selected object -- and, on screen, the fact that none run.

`editor/core/map_events.py` owns the trigger vocabulary; this panel is its
surface. It shows the declaration on the selected object, edits every field
of it through `map.object.action.*`, and deletes it -- all as commands, so it
inherits undo, rollback, the history panel and the generated `COMMANDS.md`.

THE BANNER IS THE POINT
-----------------------
The engine cannot execute one of these: no `MAP_TRIGGER_*` event type
exists, nothing under `scripts/` reads `pyoneer_trigger`, and an entity is
CALLED rather than dispatched to, so there is no bus seat to deliver one
to. A map authored here plays exactly as it did before. A feature that LOOKS
complete and does nothing is the failure this project exists to avoid, so
the panel carries `NOT_WIRED` above every field, in the widget tree rather
than in a docstring or a tooltip -- whoever reads a docstring is not whoever
is about to wonder why the door does nothing.

A BANNER THAT OVERSTATES IS ALSO A FALSE BANNER
-----------------------------------------------
This one used to say the engine has no collision detection and that the
renderer skips object layers entirely. Both shipped:
`scripts/core/renderer.py` bakes `field_from_map` into `collision_field` and
calls `spawn_objects`, so the objects on an object layer DO become entities
and a body IS gated by the baked field. An overstated gap costs what an
understated one costs -- it sends a reader to build something that is
already there -- so the clauses were narrowed rather than the banner
deleted, and `tools/check_actions_panel.py` now pins their ABSENCE as well
as the presence of what is really missing.

WHY THE DESCRIPTION IS DATA
---------------------------
`describe_actions` returns an `Inspection`, the structure
`editor/core/inspect.py` returns and `fields.InspectionView` renders. That
buys typed editors, per-field remove buttons and command emission, and lets
a check assert "editing the trigger kind produces `map.object.action.set`"
without opening a window.

It belongs in `editor/core/inspect.py` beside the other describers; nothing
in `describe_actions` touches Qt, so the move is mechanical.
"""
from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from editor.core import layers, map_events
from editor.core.behavior_view import object_at
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
    "Nothing here runs yet. There is no MAP_TRIGGER_* event type, nothing "
    "under scripts/ reads pyoneer_trigger, and entities are not on the event "
    "bus — so a map authored with these triggers plays exactly as it did "
    "before."
)

#: The rest of it, on hover. Kept off the face of the panel because the
#: sentence above is the one that has to be read every time — and because
#: the second paragraph here is the correction of a banner that was WIDER
#: than the gap, which is the mistake this file was repaired for.
NOT_WIRED_DETAIL = (
    "What IS real: Tiled reads and edits these properties in its own dialog, "
    "every edit here is a command with an exact inverse, and the file is "
    "under the byte-exactness contract. editor/core/map_events.py documents "
    "the seam a runtime would read them through — load, index, per-frame "
    "cell compare, filter, dispatch — so the executing half can be built "
    "against this without renegotiating anything.\n\n"
    "Also real, and this banner used to deny both: the engine DOES detect "
    "collision and the renderer DOES read object layers. "
    "scripts/core/renderer.py bakes field_from_map into collision_field and "
    "calls spawn_objects, so a placed object becomes an entity and a body is "
    "gated by the baked field. What is missing is narrower than it looks — "
    "the reading of pyoneer_trigger and the firing, not the pipeline under "
    "them."
)

_BANNER_STYLE = ("background: rgba(255, 206, 74, 38); "
                 "border-left: 3px solid rgb(255, 206, 74); "
                 "padding: 7px 9px; font-size: 11px;")

_NO_OBJECT = ("Select an object on an object layer. A trigger is a region, "
              "and a region is an object — there is nowhere else to hang one.")


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

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
        # A disabled control must say what would enable it. These two were
        # greyed with their enabled-state tooltip still on them, which reads
        # as a description of something that is refusing to happen.
        for button, key, enabled_tip in (
                (self.add_trigger, "trigger",
                 "Declare this region as firing when an entity enters it. "
                 "Change the kind, and who may fire it, above."),
                (self.add_blocks, "blocks",
                 "Declare this region solid. Independent of the trigger "
                 "kind: a wall is solid and never fires, a tripwire fires "
                 "and is not solid, a locked door is both.")):
            live = obj is not None and key not in keys
            button.setEnabled(live)
            button.setToolTip(
                enabled_tip if live else
                (f"this object already declares {key!r} — edit it above"
                 if obj is not None else
                 "select an object on an object layer first"))

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
        """Act, and put the reassurance where it can be read afterwards.

        The confirmation this replaces asked "Remove trigger, blocks from
        this object?" and then answered itself: "One undo brings the whole
        declaration back." A dialog whose body argues that the dialog is
        unnecessary is a dialog that is unnecessary -- and the button is
        already disabled unless there is something to remove, so the click
        cannot be an accident of aim.
        """
        _layer, obj = object_at(self.session, self._scope)
        keys = declared_keys(obj)
        if not keys:
            return
        if self.window().run(removal_commands(self._scope, keys),
                             label="Remove the trigger declaration"):
            self.notify(
                f"removed {', '.join(keys)} — it is an ordinary object again, "
                f"and Ctrl+Z brings the whole declaration back", seconds=10)
        self.refresh()
