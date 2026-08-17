"""The editor window.

Holds the session and the selection, and is the only place that calls
`session.run`. Panels reach it with `self.window().run(command)`, so there
is exactly one place where a change enters the project, one place that
catches a rejection, and one place that refreshes the views.

It is also the only place that launches anything -- the game, an IDE -- and
both are detached subprocesses. Nothing the editor spawns can block its
event loop or take it down with it.

HOW THIS WINDOW SPEAKS
----------------------
Three channels, and which one a message goes down is decided by whether
there is a decision in it:

    self.notify(...)    something happened. Status bar, and gone.
    self.report(...)    something happened that must be SEEN even if the
                        author was looking elsewhere. Status bar plus a
                        Problems row that stays until its situation ends.
    self.ask / .confirm a real decision, and only ever the author's to make.

A rejected command used to be a modal titled "Rejected" whose body was verb
names, scope syntax, an args dict and an exception class -- a box to dismiss
in order to learn that nothing had changed. It is the second channel now.
The two dialogs left in this file are the two that carry a choice: which
genre pack, and whether to apply an AI's command list to the project.
`QMessageBox.critical` survives in three places, all of them an unexpected
exception at a point where the alternative is losing work.
"""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QFileSystemWatcher, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSpinBox,
    QToolBar,
)

from editor.core import ide
from editor.core.commands import Command
from editor.core.errors import PyoneerEditorError
from editor.core.genre import RuleViolation
from editor.core.inspect import Field
from editor.core.layers import describe_mask
from editor.core.paint import EditMode, Tool
from editor.core.request import REQUESTS_DIR, RESPONSE_FILE, read_response
from editor.core.scope import Scope
from editor.ui.actions_panel import ActionsDock
from editor.ui.ask import ask_form, confirm
from editor.ui.behavior_panel import BehaviorDock
from editor.ui.canvas import MapCanvas, TilePalette
from editor.ui.collision_view import MaskPalette, build_mode_actions
from editor.ui.database import DatabaseWindow
from editor.ui.docks import HistoryDock, ManifestDock, ProblemsDock
from editor.ui.hierarchy import HierarchyDock
from editor.ui.icons import tool_icon
from editor.ui.inspector import InspectorDock
from editor.ui.selection import Selection
from editor.ui.settings_dialog import SettingsDialog
from editor.ui.tileset_dialog import TilesetImportDialog
from editor.ui import theme as theme_module
from editor.ui.theme import Theme
from editor.core.settings import EditorSettings

_OBJECT_CLASSES = (
    "GamePlayer", "GameEntity", "GameFloorEntity",
    "GameBackgroundEntity", "GameForegroundEntity", "GameUIEntity",
)

_TOOL_SHORTCUTS = {
    Tool.BRUSH: "B",
    Tool.FILLED_RECT: "R",
    Tool.RECTANGLE: "Shift+R",
    Tool.FILL: "G",
    Tool.ERASER: "E",
    Tool.PICKER: "I",
}


class EditorWindow(QMainWindow):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.settings = EditorSettings()
        self.map_name = (session.project.map_names() or ["<none>"])[0]
        self.database: DatabaseWindow | None = None
        # The dialog seams, same as every panel's. See editor/ui/ask.py.
        self.ask = ask_form
        self.confirm = confirm
        #: The last response file that arrived on disk and has not been
        #: applied. It used to interrupt with a modal the moment it landed.
        self.pending_response: str | None = None
        self.setWindowTitle(self.__title())
        self.resize(1600, 1000)

        map_scope = Scope.of(("map", self.map_name))
        self.selection = Selection(map_scope, self)

        self.canvas = MapCanvas(session, self.map_name, self)
        self.canvas.status.connect(self.__on_status)
        self.canvas.picked_gid.connect(self.__on_picked)
        self.canvas.picked_mask.connect(self.__on_picked_mask)
        self.canvas.selected.connect(self.selection.select)
        self.setCentralWidget(self.canvas)

        self.hierarchy = HierarchyDock("Hierarchy", session, map_scope, self)
        self.inspector = InspectorDock("Inspector", session, map_scope, self)
        self.behaviors = BehaviorDock("Behaviors", session, map_scope, self)
        self.actions = ActionsDock("Actions", session, map_scope, self)
        self.problems = ProblemsDock("Problems", session, Scope.of("project"), self)
        self.manifest = ManifestDock("Manifest", session, Scope.of("project"), self)
        self.history = HistoryDock("History", session, Scope.of("project"), self)

        self.addDockWidget(Qt.LeftDockWidgetArea, self.hierarchy)
        self.addDockWidget(Qt.RightDockWidgetArea, self.inspector)
        # Tabbed onto the Inspector rather than stacked beside it: both answer
        # "what is this selected thing", only one of them at a time, and two
        # right-hand columns would spend half the width saying nothing. The
        # Inspector is raised again because tabifyDockWidget leaves the
        # newcomer on top and the Inspector is what a selection usually wants
        # -- the same argument, and the same fix, as the collision palette.
        self.addDockWidget(Qt.RightDockWidgetArea, self.behaviors)
        self.tabifyDockWidget(self.inspector, self.behaviors)
        # Actions was written, checked by the suite, and mounted NOWHERE: 353
        # lines and a passing check for a surface no click could reach, which
        # is the exact failure its own docstring is about. It answers "what is
        # this selected thing", so it tabs with the Inspector like Behaviors.
        self.addDockWidget(Qt.RightDockWidgetArea, self.actions)
        self.tabifyDockWidget(self.inspector, self.actions)
        self.inspector.raise_()
        self.addDockWidget(Qt.BottomDockWidgetArea, self.problems)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.manifest)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.history)
        self.tabifyDockWidget(self.problems, self.history)
        self.problems.raise_()
        self.resizeDocks([self.inspector], [420], Qt.Horizontal)

        self.palette_dock = self.__build_palette()
        self.mask_dock = self.__build_mask_palette()
        self.hierarchy.visibility_changed.connect(self.canvas.set_layer_visible)
        self.manifest.ship_requested.connect(self.ship)
        self.selection.changed.connect(self.__on_selection)

        self.docks = (self.hierarchy, self.inspector, self.behaviors,
                      self.actions, self.problems, self.manifest, self.history)

        self.__build_actions()
        self.__build_toolbar()
        self.statusBar().showMessage(
            "left drag paints · right drag erases · middle or space pans · "
            "ctrl+wheel zooms · alt+click picks")

        self.__watcher = QFileSystemWatcher(self)
        self.__watcher.directoryChanged.connect(self.__on_requests_changed)
        self.__seen_responses: set[str] = set()
        self.__watch_requests()

        self.canvas.show_grid = self.settings.get("show_grid")
        self.canvas.grid_step = self.settings.get("grid_step")
        self.apply_theme(Theme.parse(self.settings.get("theme")))
        self.refresh_all()
        self.__select_first_paintable_layer()

    # -- construction ------------------------------------------------------

    def __build_palette(self) -> QDockWidget:
        dock = QDockWidget("Tiles", self)
        dock.setObjectName("Tiles")
        self.palette = TilePalette(dock)
        self.palette.stamp_picked.connect(self.__on_stamp)
        dock.setWidget(self.palette)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        return dock

    def __build_mask_palette(self) -> QDockWidget:
        """The collision brush: what the tile palette becomes in that mode.

        Tabified onto `palette_dock` rather than given its own strip. It
        answers the SAME question -- what am I painting with -- and only one
        of the two can be the answer at a time, so two side-by-side palettes
        would be two-thirds of the left column spent saying nothing.
        `palette_dock` is raised again afterwards because tabifyDockWidget
        leaves the newcomer on top, and the editor opens in tile mode.

        The palette emits a MASK; turning it into a gid needs the companion
        layer's firstgid, which is the canvas's business, so `set_mask` takes
        it raw.
        """
        dock = QDockWidget("Collision", self)
        dock.setObjectName("Collision")
        self.mask_palette = MaskPalette(dock)
        self.mask_palette.mask_picked.connect(self.canvas.set_mask)
        dock.setWidget(self.mask_palette)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.tabifyDockWidget(self.palette_dock, dock)
        self.palette_dock.raise_()
        return dock

    def __build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self.__act(file_menu, "&Save", QKeySequence.Save, self.save)
        file_menu.addSeparator()
        self.__act(file_menu, "&Play the game", "F5", self.play)
        self.__act(file_menu, "Open the &project in my IDE", None,
                   lambda: self.reveal("main.py"))
        file_menu.addSeparator()
        self.__act(file_menu, "Se&ttings…", "Ctrl+,", self.open_settings)
        file_menu.addSeparator()
        self.__act(file_menu, "&Quit", QKeySequence.Quit, self.close)

        edit_menu = self.menuBar().addMenu("&Edit")
        self.undo_action = self.__act(edit_menu, "&Undo", QKeySequence.Undo, self.undo)
        self.redo_action = self.__act(edit_menu, "&Redo", QKeySequence.Redo, self.redo)
        edit_menu.addSeparator()
        self.__act(edit_menu, "Select the &parent", "Alt+Up",
                   self.selection.select_parent)
        self.__act(edit_menu, "&Back", "Alt+Left", self.selection.back)

        view_menu = self.menuBar().addMenu("&View")
        # Driven off `self.docks` rather than a second hand-written list:
        # the previous copy went stale silently, and a dock missing from
        # here is a panel the author cannot get back once it is closed.
        for dock in self.docks + (self.palette_dock, self.mask_dock):
            view_menu.addAction(dock.toggleViewAction())
        view_menu.addSeparator()
        self.__act(view_menu, "Zoom &in", QKeySequence.ZoomIn,
                   lambda: self.canvas.scale(1.25, 1.25))
        self.__act(view_menu, "Zoom &out", QKeySequence.ZoomOut,
                   lambda: self.canvas.scale(0.8, 0.8))
        self.__act(view_menu, "&Reset zoom", "Ctrl+0", self.__reset_zoom)

        data_menu = self.menuBar().addMenu("&Database")
        self.__act(data_menu, "&Open the database…", "Ctrl+D", self.open_database)

        ai_menu = self.menuBar().addMenu("&AI")
        # Held, not fired and forgotten: all three refused with a modal when
        # they could not act, while the Manifest dock's own Ship button
        # already disabled itself in the same state. Two doors onto one
        # action, one greyed and one arguing.
        self.ship_action = self.__act(
            ai_menu, "&Ship staged notes as a request…", "Ctrl+Return", self.ship)
        # Not held: browsing for a response is always possible, so there is
        # no state to grey it for, and an attribute nothing reads is the
        # `confirm_response` disease one layer up.
        self.__act(ai_menu, "&Apply a response…", "Ctrl+Shift+Return",
                   self.apply_response_dialog)
        ai_menu.addSeparator()
        self.art_action = self.__act(ai_menu, "Copy the &art brief", None,
                                     self.copy_art_brief)

        project_menu = self.menuBar().addMenu("&Project")
        self.add_tileset_action = self.__act(
            project_menu, "Add a &tileset…", None, self.add_tileset)
        self.__act(project_menu, "Switch &genre…", None, self.switch_genre)
        self.__sync_actions()

    def __act(self, menu, text, shortcut, slot) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def __build_toolbar(self) -> None:
        bar = QToolBar("Tools", self)
        bar.setObjectName("Tools")
        bar.setMovable(False)
        self.addToolBar(bar)

        bar.setIconSize(QSize(22, 22))
        bar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        group = QActionGroup(self)
        group.setExclusive(True)
        self.tool_actions: dict[Tool, QAction] = {}
        for tool in Tool:
            action = QAction(tool_icon(tool.value), tool.label, self)
            action.setCheckable(True)
            action.setChecked(tool is Tool.BRUSH)
            shortcut = _TOOL_SHORTCUTS.get(tool)
            tip = tool.label
            if shortcut:
                action.setShortcut(shortcut)
                tip = f"{tool.label}  ({shortcut})"
            action.setToolTip(tip)
            action.setStatusTip(tip)
            action.triggered.connect(lambda _c=False, t=tool: self.__set_tool(t))
            group.addAction(action)
            bar.addAction(action)
            self.tool_actions[tool] = action

        bar.addSeparator()
        # The mode sits beside the tools rather than in a menu because it
        # changes what every one of them writes. `toggle` goes on the WINDOW,
        # not the bar: it is the keyboard accelerator for the pair, not a
        # third button.
        self.modes = build_mode_actions(self, self.__on_mode,
                                        self.canvas.set_all_layers)
        for action in self.modes.actions.values():
            bar.addAction(action)
        bar.addAction(self.modes.all_layers)
        self.addAction(self.modes.toggle)

        bar.addSeparator()
        self.stamp_label = QLabel("  brush: gid 1  ")
        bar.addWidget(self.stamp_label)

        # THE FOOTPRINT, not the grid and not the tile size. It counts the
        # cells a click addresses, so the same number means 3 tiles here and
        # 3 sub-cells the day collision is authored finer -- one integer,
        # one control, the unit derived rather than stored, so the two can
        # never disagree because there is only one of them. The label under
        # it spells the unit out in pixels.
        bar.addSeparator()
        bar.addWidget(QLabel("  size "))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(1, 9)
        self.size_spin.setValue(self.canvas.brush_size)
        self.size_spin.valueChanged.connect(self.__on_brush_size)
        bar.addWidget(self.size_spin)
        self.size_label = QLabel("")
        self.size_label.setStyleSheet("color: palette(mid);")
        bar.addWidget(self.size_label)
        self.__sync_size_control()

        bar.addSeparator()
        bar.addWidget(QLabel("  place "))
        self.class_combo = QComboBox()
        self.class_combo.addItems(_OBJECT_CLASSES)
        self.class_combo.setEditable(True)
        self.class_combo.setToolTip(
            "Class used when you click an empty spot on an object layer.")
        self.class_combo.currentTextChanged.connect(self.__on_class)
        bar.addWidget(self.class_combo)

        bar.addSeparator()
        self.layer_label = QLabel("  no layer selected  ")
        self.layer_label.setStyleSheet("color: palette(mid);")
        bar.addWidget(self.layer_label)

    def __title(self) -> str:
        star = "*" if self.session.dirty else ""
        return (f"Pyoneer Editor{star} — {self.session.project.genre.title} — "
                f"{self.session.project.root}")

    def __select_first_paintable_layer(self) -> None:
        try:
            names = self.session.project.map(self.map_name).tile_layer_names()
        except Exception:                                       # noqa: BLE001
            return
        if names:
            self.selection.select(
                Scope.of(("map", self.map_name), ("layer", names[0])))

    # -- saying things -----------------------------------------------------

    def notify(self, message: str, *, seconds: float = 6.0) -> None:
        """Something happened. Read it or don't."""
        self.statusBar().showMessage(message, int(seconds * 1000))

    def report(self, message: str, *, key: str, scope: Scope | None = None,
               detail: str = "", severity: str = "hard", fix: str = "",
               seconds: float = 12.0) -> None:
        """Something happened that must be SEEN, even later.

        Status bar for the moment, Problems row for afterwards. `key` makes
        the row idempotent -- one rejection replaces the previous rejection
        rather than stacking -- and is what `clear` names when the situation
        it described is over.

        This is what the "Rejected" modal became. A rejection is a normal
        outcome (a verb refusing an edit that would corrupt gids is the
        system working), and a normal outcome that stops the hand and takes
        the keyboard is the defect the author reported on a paint click.
        """
        self.notify(message, seconds=seconds)
        self.problems.post(
            RuleViolation(severity, scope or Scope.of("project"), message, fix),
            key=key, detail=detail)

    def clear(self, key: str) -> None:
        """Retire a reported situation."""
        self.problems.clear_notices(key)

    # -- the single mutation point -----------------------------------------

    def run(self, commands, *, label: str | None = None,
            source: str = "editor") -> bool:
        """Apply commands. Returns True on success; reports and returns False
        on a rejection. Never lets an editor error escape into Qt."""
        try:
            transaction = self.session.run(commands, label=label, source=source)
        except PyoneerEditorError as exc:
            # `exc.message` is the human clause; `str(exc)` appends the
            # context trail -- verb, scope, args, exception class -- which is
            # debugging vocabulary the author did not ask for. It goes in the
            # row's tooltip, where it is available and not in the way.
            self.report(getattr(exc, "message", None) or str(exc),
                        key="rejection", detail=str(exc),
                        fix="nothing changed")
            return False
        except Exception as exc:                                # noqa: BLE001
            # Kept modal. A rejection is a designed outcome; this is not one,
            # and it means the mutation point itself is in a state nothing
            # here can reason about.
            QMessageBox.critical(self, type(exc).__name__, str(exc))
            return False
        self.clear("rejection")
        self.statusBar().showMessage(str(transaction), 4000)
        self.refresh_all()
        return True

    # -- refreshing --------------------------------------------------------

    def refresh_all(self) -> None:
        self.canvas.set_selection(self.selection.scope)
        if self.canvas.atlas is not None:
            self.palette.set_atlas(self.canvas.atlas)
        for dock in self.docks:
            self.__safely(dock.refresh, dock.base_title)
        if self.database is not None:
            self.__safely(self.database.refresh, "Database")
        self.undo_action.setEnabled(self.session.stream.can_undo)
        self.redo_action.setEnabled(self.session.stream.can_redo)
        self.__sync_actions()
        self.setWindowTitle(self.__title())

    def __sync_actions(self) -> None:
        """A menu entry that cannot act is greyed and says why.

        Every one of these used to be permanently enabled and to answer with
        a modal: "Nothing staged", "No art brief", "No response". A control
        that is present and refusing is worse than one that is greyed with a
        reason -- the click has already been spent by the time the refusal
        arrives.
        """
        staged = not self.session.manifest.empty
        self.ship_action.setEnabled(staged)
        self.ship_action.setToolTip(
            "hand the staged notes to an AI as a request" if staged
            else "type a note under any panel first")

        brief = bool(self.session.project.genre.art_brief)
        self.art_action.setEnabled(brief)
        self.art_action.setToolTip(
            "copy the genre's art brief for an image model" if brief
            else f"genre {self.session.project.genre.id!r} ships no ART.md")

        maps = bool(self.session.project.map_names())
        self.add_tileset_action.setEnabled(maps)
        self.add_tileset_action.setToolTip(
            f"declare a sheet on map:{self.map_name}" if maps
            else "this project has no maps")

    def __safely(self, call, what: str) -> None:
        """One panel failing must not take the window down.

        A panel reads a document that a command just changed, and a stale
        assumption in one of them is a bug in that panel -- not a reason for
        the editor to die holding unsaved work.
        """
        try:
            call()
        except Exception as exc:                                # noqa: BLE001
            self.statusBar().showMessage(
                f"{what} panel failed to refresh: {type(exc).__name__}: {exc}",
                12000)

    def refresh_manifest(self) -> None:
        self.manifest.refresh()
        for dock in self.docks:
            dock.strip.refresh()
        self.__sync_actions()

    # -- selection ---------------------------------------------------------

    def __on_selection(self, scope: Scope) -> None:
        for dock in self.docks:
            if dock.follows_selection:
                self.__safely(lambda d=dock: d.on_selection_changed(scope),
                              dock.base_title)
        layer = scope.get("layer")
        if layer != self.canvas.active_layer:
            self.canvas.set_active_layer(layer)
        else:
            self.canvas.set_selection(scope)
        self.layer_label.setText(f"  layer: {layer}  " if layer
                                 else "  no layer selected  ")

    # -- tools -------------------------------------------------------------

    def __set_tool(self, tool: Tool) -> None:
        self.canvas.tool = tool
        self.__sync_size_control()
        self.statusBar().showMessage(tool.label, 2000)

    def __on_brush_size(self, size: int) -> None:
        self.canvas.brush_size = int(size)
        self.__sync_size_control()

    def __sync_size_control(self) -> None:
        """Lit for the tools a footprint reaches, greyed WITH A REASON for
        the rest.

        Measured, and this is the whole justification for `Tool.uses_size`:
        a rectangle, a filled rectangle and a flood fill read the stamp as
        a repeating pattern keyed on map coordinates, so a uniform 3x3
        produces bit-identical edits to a 1x1. Leaving the spinner live for
        those three would be a control the author turns and watches do
        nothing -- the exact shape the last pass spent itself removing.
        """
        tool = self.canvas.tool
        live = tool.uses_size
        self.size_spin.setEnabled(live)
        size = self.canvas.brush_size
        # The unit, spelled out. A size is in CELLS, and how big a cell is
        # depends on what is being painted -- which is the confusion this
        # whole control exists to end.
        try:
            unit = f"{self.canvas.paint_width}px"
        except Exception:                                       # noqa: BLE001
            unit = "cells"                  # no readable map; say nothing false
        self.size_label.setText(f" × {unit}  " if live else "  n/a  ")
        self.size_spin.setToolTip(
            f"Brush footprint: {size} × {size} cells of {unit}."
            if live else
            f"{tool.label} has no footprint — it reads the brush as a "
            f"repeating pattern over the area it covers, so a size larger "
            f"than 1 would change nothing.")

    def __on_stamp(self, stamp) -> None:
        self.canvas.stamp = stamp
        self.stamp_label.setText(
            f"  brush: gid {stamp.primary}  " if stamp.is_single
            else f"  brush: {stamp.width}×{stamp.height} stamp  ")

    def __on_picked(self, gid: int) -> None:
        self.palette.select_gid(gid)
        self.stamp_label.setText(f"  brush: gid {gid}  ")

    def __on_mode(self, mode: EditMode) -> None:
        """Point the canvas at the other layer, and the toolbar with it.

        The tools do not change -- B is still brush -- but a tool the mode
        cannot express is disabled rather than left clickable and silent, and
        the palette that answers "painting with what" is brought forward.
        """
        self.canvas.set_mode(mode)
        for tool, action in self.tool_actions.items():
            action.setEnabled(mode.allows(tool))
        if not mode.allows(self.canvas.tool):
            # A disabled action that is still the checked one is a toolbar
            # nobody can get out of, so fall back rather than just greying it.
            self.tool_actions[Tool.BRUSH].setChecked(True)
            self.__set_tool(Tool.BRUSH)
        # The size is in cells of the ACTIVE mode's paint unit, so its
        # readout has to be re-derived even when the tool did not change.
        self.__sync_size_control()
        dock = self.mask_dock if mode is EditMode.COLLISION else self.palette_dock
        dock.raise_()

    def __on_picked_mask(self, mask: int) -> None:
        """The canvas picked a mask off the map (alt-click, or the picker)."""
        # notify=False: this mask CAME from the canvas, and echoing it back
        # would be a round trip that ends where it started.
        self.mask_palette.select_mask(mask, notify=False)
        self.stamp_label.setText(f"  {describe_mask(mask)}  ")

    def __on_class(self, name: str) -> None:
        self.canvas.object_class = name

    def __on_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 3000)

    def __reset_zoom(self) -> None:
        self.canvas.resetTransform()

    # -- commands ----------------------------------------------------------

    def undo(self) -> None:
        if self.session.undo() is not None:
            self.selection.reselect()
            self.refresh_all()

    def redo(self) -> None:
        if self.session.redo() is not None:
            self.selection.reselect()
            self.refresh_all()

    def save(self) -> int | None:
        """Write every dirty document. Returns how many, or None on failure.

        The one modal that stays a modal on a routine action: a failed save
        is the only outcome here where carrying on quietly loses work.
        """
        try:
            written = self.session.save()
        except Exception as exc:                                # noqa: BLE001
            QMessageBox.critical(self, "Save failed", str(exc))
            return None
        self.notify(f"wrote {len(written)} "
                    f"file{'' if len(written) == 1 else 's'}", seconds=5)
        self.setWindowTitle(self.__title())
        return len(written)

    def play(self) -> None:
        """Save, then launch the game as a subprocess. Not the runtime.

        It used to ask "The game reads files from disk. Save before
        playing?" on the most repeated action in the loop -- an unanchored
        question, no default button, and the same answer every single time.
        The editor knows the game reads from disk and knows the session is
        dirty, so it saves: if the editor can do the thing, it does the
        thing. Nothing is lost by it, because a save writes what undo can
        still take back byte-for-byte, and the status line says it happened.
        """
        saved = 0
        if self.session.dirty:
            saved = self.save()
            if saved is None:
                return                  # the save failed and said so
        main = os.path.join(self.session.project.root, "main.py")
        if not os.path.isfile(main):
            self.report(f"there is no main.py in {self.session.project.root} — "
                        f"nothing to play", key="play",
                        fix="the game's entry point is main.py at the project root")
            return
        try:
            subprocess.Popen([sys.executable, main],
                             cwd=self.session.project.root)
        except OSError as exc:
            self.report(f"could not launch main.py: {exc}", key="play",
                        detail=f"{type(exc).__name__}: {exc}")
            return
        self.clear("play")
        self.notify(f"saved {saved} file{'' if saved == 1 else 's'} and "
                    f"launched main.py" if saved else "launched main.py")

    def open_database(self) -> None:
        if self.database is None:
            self.database = DatabaseWindow(self.session, self)
            self.database.command_requested.connect(self.run)
            self.database.reveal_requested.connect(self.reveal)
        self.database.refresh()
        self.database.show()
        self.database.raise_()
        self.database.activateWindow()

    def add_tileset(self) -> None:
        """Declare a sheet on the open map.

        `TilesetImportDialog` was finished, had a complete `ask()` whose own
        docstring says "so the menu action stays two lines", and no menu
        action existed -- so no tileset could be added from the GUI at all.
        That absence is why the collision path grew its own 191-word modal
        tileset importer: it was the only door onto `map.tileset.add`.
        """
        try:
            document = self.session.project.map(self.map_name)
        except Exception as exc:                                # noqa: BLE001
            self.report(f"cannot read map:{self.map_name}: {exc}",
                        key="add_tileset")
            return
        request = TilesetImportDialog.ask(
            os.path.dirname(document.path),
            tile_width=document.tile_width, tile_height=document.tile_height,
            existing_names=document.tileset_names(), parent=self)
        if request is None:
            return
        if self.run(Command("map.tileset.add", Scope.of(("map", self.map_name)),
                            request.command_args())):
            self.notify(f"declared {request.name!r} — {request.tile_count} "
                        f"tiles are now in the palette", seconds=8)

    def switch_genre(self) -> None:
        from editor.core import genre as genre_module

        options = genre_module.available()
        current = self.session.project.genre.id
        answer = self.ask(
            self, "Genre",
            [Field("genre", "Genre pack", "choice", current,
                   doc="Reshapes the Database window and what the Problems "
                       "panel considers a violation. It changes no map data.",
                   choices=tuple(options))],
            ok_label="Switch")
        if answer is None or answer["genre"] == current:
            return
        if self.run(Command("project.genre.set", Scope.of("project"),
                            {"genre": answer["genre"]})) \
                and self.database is not None:
            self.database.rebuild()

    def copy_art_brief(self) -> None:
        from PySide6.QtWidgets import QApplication

        brief = self.session.project.genre.art_brief
        if not brief:
            # Unreachable by clicking -- the action is greyed with this
            # reason on it -- and still said rather than swallowed.
            self.notify(f"genre {self.session.project.genre.id!r} ships no "
                        f"ART.md, so there is no brief to copy")
            return
        QApplication.clipboard().setText(brief)
        self.notify("art brief copied — paste it into an image model")

    # -- code ---------------------------------------------------------------

    # -- settings ----------------------------------------------------------

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self.settings, self,
            ide_choices=[(found.id, f"{found.name}  ({found.how})")
                         for found in ide.detect()])
        dialog.changed.connect(self.__on_setting_changed)
        dialog.exec()

    def __on_setting_changed(self, key: str, value) -> None:
        if key == "theme":
            self.apply_theme(Theme.parse(value))
        elif key == "show_grid":
            self.canvas.show_grid = bool(value)
            self.canvas.rebuild()
        elif key == "grid_step":
            # Grid only. `cell_at` is deliberately NOT consulted here and
            # must not be: the spacing decides which boundaries are DRAWN,
            # never which cell a click lands in, and the moment those two
            # can disagree the grid starts lying about the map.
            self.canvas.grid_step = int(value)
            self.canvas.rebuild()
        # `ide` is read in `reveal`, and `confirm_response` in
        # `apply_response` and `__offer` -- both at the moment they matter,
        # so nothing has to happen here for them. (`confirm_response` was
        # read NOWHERE for as long as it existed: a preference the author
        # could tick that changed nothing at all.)

    def apply_theme(self, theme: Theme) -> None:
        """Repaint the whole application, icons included."""
        application = QApplication.instance()
        if application is None:
            return
        concrete = theme_module.apply(application, theme)
        # Icons ink themselves from the palette and are cached, so they have
        # to be re-fetched or the toolbar keeps the old contrast.
        for tool, action in self.tool_actions.items():
            action.setIcon(tool_icon(tool.value))
        self.canvas.set_background(
            theme_module.CANVAS_BACKGROUND.get(concrete))
        self.statusBar().showMessage(f"{concrete.label} theme", 3000)

    def reveal(self, path: str, line: int | None = None,
               symbol: str | None = None) -> None:
        """Open a source file in the developer's IDE.

        Read-only by construction: it launches a detached process and
        reports failure in the status bar. Nothing here can affect the
        project, the running game, or the editor.
        """
        absolute = path if os.path.isabs(path) \
            else os.path.join(self.session.project.root, path)
        if symbol and line is None:
            line = ide.find_symbol_line(absolute, symbol)
        result = ide.open_at(absolute, line,
                             configured=self.settings.get("ide") or None)
        if not result.ok and not ide.detect():
            # Was a modal AND the status line below it -- the same fact
            # twice, once with a button on it.
            self.report("no IDE found: PyCharm, VS Code, IntelliJ, Sublime "
                        "and Notepad++ are all absent from this machine",
                        key="ide", severity="soft", detail=result.message,
                        fix="File ▸ Settings names one explicitly")
            return
        self.clear("ide")
        self.notify(result.message, seconds=8)

    # -- the AI loop -------------------------------------------------------

    def ship(self) -> None:
        if self.session.manifest.empty:
            # The menu entry is greyed and the dock's Ship button disables
            # itself, so this is only reachable by calling it. It used to be
            # a modal on an always-enabled action, next to a button that was
            # already doing the right thing.
            self.notify("nothing is staged — type a note under any panel "
                        "first, and its scope comes with it")
            return
        answer = self.ask(
            self, "Ship request",
            [Field("title", "Title", "str",
                   self.session.manifest.suggested_title(),
                   doc="What this request is about. It names the folder and "
                       "heads the brief.")],
            ok_label="Write the request")
        if answer is None:
            return
        try:
            bundle = self.session.ship(title=answer["title"])
        except Exception as exc:                                # noqa: BLE001
            QMessageBox.critical(self, "Could not write the request", str(exc))
            return
        self.refresh_manifest()
        self.__watch_requests()
        relative = os.path.relpath(bundle.directory, self.session.project.root)
        # A four-line modal to be told a file was written is a report with an
        # OK button. The row stays until the response lands, which is longer
        # than any dialog would have.
        self.report(f"wrote {relative} — hand it over with: Read "
                    f"{relative}/BRIEF.md and do the work",
                    key=f"request:{bundle.identifier}", severity="soft",
                    fix=f"watching for {RESPONSE_FILE}", seconds=15)

    def apply_response_dialog(self) -> None:
        # Starts where the waiting response is, when one is waiting: the
        # arrival is announced rather than demanded, so the menu entry has
        # to be able to find it again.
        start = self.pending_response or os.path.join(
            self.session.project.root, REQUESTS_DIR)
        path, _ = QFileDialog.getOpenFileName(
            self, "Apply a response", start, "JSON Lines (*.jsonl);;All files (*)")
        if path:
            self.apply_response(path)

    def apply_response(self, path: str) -> None:
        try:
            commands = read_response(path)
        except Exception as exc:                                # noqa: BLE001
            self.report(f"{os.path.basename(path)} is not a readable "
                        f"response: {exc}", key="response",
                        detail=f"{type(exc).__name__}: {exc}\n{path}")
            return
        identifier = os.path.basename(os.path.dirname(os.path.abspath(path)))
        preview = "\n".join(f"  {c}" for c in commands[:20])
        if len(commands) > 20:
            preview += f"\n  … and {len(commands) - 20} more"
        # A real decision: this is someone else's command list about to be
        # applied to the author's project, and the preview is what makes it
        # a decision rather than a formality. `confirm_response` is the
        # preference that turns it off -- it was declared, rendered in the
        # settings dialog, promised "apply as soon as it arrives", and read
        # by nothing at all until here.
        if self.settings.get("confirm_response") and not self.confirm(
                self, "Apply response",
                f"{identifier} contains {len(commands)} command"
                f"{'' if len(commands) == 1 else 's'}:\n\n{preview}\n\n"
                f"Apply as one undoable transaction?"):
            return
        if self.run(commands, label=f"response {identifier}",
                    source=f"response:{identifier}"):
            self.clear(f"response:{os.path.abspath(path)}")
            self.clear(f"request:{identifier}")
            if self.pending_response \
                    and os.path.abspath(self.pending_response) == \
                    os.path.abspath(path):
                self.pending_response = None

    def __watch_requests(self) -> None:
        base = os.path.join(self.session.project.root, REQUESTS_DIR)
        if not os.path.isdir(base):
            return
        existing = set(self.__watcher.directories())
        wanted = [base] + [os.path.join(base, d) for d in os.listdir(base)
                           if os.path.isdir(os.path.join(base, d))]
        for path in wanted:
            if path not in existing:
                self.__watcher.addPath(path)

    def __on_requests_changed(self, directory: str) -> None:
        self.__watch_requests()
        candidate = os.path.join(directory, RESPONSE_FILE)
        if not os.path.isfile(candidate) or candidate in self.__seen_responses:
            return
        self.__seen_responses.add(candidate)
        # Give the writer a moment; a half-written jsonl is the obvious race
        # and 400 ms is cheaper than a parse error.
        QTimer.singleShot(400, lambda: self.__offer(candidate))

    def __offer(self, path: str) -> None:
        """A file appeared on disk. That is news, not a question.

        This was the only modal in the tree that could open with NO gesture
        from the author at all -- a filesystem watcher fired it, so it could
        land on top of an in-progress stroke and take the mouse button with
        it. Nothing about focus, drag state or consent was consulted.

        So it announces itself instead. `confirm_response` unticked means
        the author already said "apply as soon as it arrives", and that is
        the one case where arriving is enough to act on.
        """
        name = os.path.basename(os.path.dirname(path))
        self.pending_response = path
        if not self.settings.get("confirm_response"):
            self.apply_response(path)
            return
        self.report(f"{name} has a response waiting — AI ▸ Apply a response… "
                    f"(Ctrl+Shift+Return) reviews it",
                    key=f"response:{os.path.abspath(path)}", severity="soft",
                    detail=path, seconds=15)
