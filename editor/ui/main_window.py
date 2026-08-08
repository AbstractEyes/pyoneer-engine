"""The editor window.

Holds the session and the selection, and is the only place that calls
`session.run`. Panels reach it with `self.window().run(command)`, so there
is exactly one place where a change enters the project, one place that
catches a rejection, and one place that refreshes the views.

It is also the only place that launches anything -- the game, an IDE -- and
both are detached subprocesses. Nothing the editor spawns can block its
event loop or take it down with it.
"""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QFileSystemWatcher, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolBar,
)

from editor.core import ide
from editor.core.commands import Command
from editor.core.errors import PyoneerEditorError
from editor.core.paint import Tool
from editor.core.request import REQUESTS_DIR, RESPONSE_FILE, read_response
from editor.core.scope import Scope
from editor.ui.canvas import MapCanvas, TilePalette
from editor.ui.database import DatabaseWindow
from editor.ui.docks import HistoryDock, ManifestDock, ProblemsDock
from editor.ui.hierarchy import HierarchyDock
from editor.ui.icons import tool_icon
from editor.ui.inspector import InspectorDock
from editor.ui.selection import Selection

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
        self.map_name = (session.project.map_names() or ["<none>"])[0]
        self.database: DatabaseWindow | None = None
        self.setWindowTitle(self.__title())
        self.resize(1600, 1000)

        map_scope = Scope.of(("map", self.map_name))
        self.selection = Selection(map_scope, self)

        self.canvas = MapCanvas(session, self.map_name, self)
        self.canvas.status.connect(self.__on_status)
        self.canvas.picked_gid.connect(self.__on_picked)
        self.canvas.selected.connect(self.selection.select)
        self.setCentralWidget(self.canvas)

        self.hierarchy = HierarchyDock("Hierarchy", session, map_scope, self)
        self.inspector = InspectorDock("Inspector", session, map_scope, self)
        self.problems = ProblemsDock("Problems", session, Scope.of("project"), self)
        self.manifest = ManifestDock("Manifest", session, Scope.of("project"), self)
        self.history = HistoryDock("History", session, Scope.of("project"), self)

        self.addDockWidget(Qt.LeftDockWidgetArea, self.hierarchy)
        self.addDockWidget(Qt.RightDockWidgetArea, self.inspector)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.problems)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.manifest)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.history)
        self.tabifyDockWidget(self.problems, self.history)
        self.problems.raise_()
        self.resizeDocks([self.inspector], [420], Qt.Horizontal)

        self.palette_dock = self.__build_palette()
        self.hierarchy.visibility_changed.connect(self.canvas.set_layer_visible)
        self.manifest.ship_requested.connect(self.ship)
        self.selection.changed.connect(self.__on_selection)

        self.docks = (self.hierarchy, self.inspector, self.problems,
                      self.manifest, self.history)

        self.__build_actions()
        self.__build_toolbar()
        self.statusBar().showMessage(
            "left drag paints · right drag erases · middle or space pans · "
            "ctrl+wheel zooms · alt+click picks")

        self.__watcher = QFileSystemWatcher(self)
        self.__watcher.directoryChanged.connect(self.__on_requests_changed)
        self.__seen_responses: set[str] = set()
        self.__watch_requests()

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

    def __build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self.__act(file_menu, "&Save", QKeySequence.Save, self.save)
        file_menu.addSeparator()
        self.__act(file_menu, "&Play the game", "F5", self.play)
        self.__act(file_menu, "Open the &project in my IDE", None,
                   lambda: self.reveal("main.py"))
        file_menu.addSeparator()
        self.__act(file_menu, "&Quit", QKeySequence.Quit, self.close)

        edit_menu = self.menuBar().addMenu("&Edit")
        self.undo_action = self.__act(edit_menu, "&Undo", QKeySequence.Undo, self.undo)
        self.redo_action = self.__act(edit_menu, "&Redo", QKeySequence.Redo, self.redo)

        view_menu = self.menuBar().addMenu("&View")
        for dock in (self.hierarchy, self.inspector, self.problems,
                     self.manifest, self.history, self.palette_dock):
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
        self.__act(ai_menu, "&Ship staged notes as a request…", "Ctrl+Return", self.ship)
        self.__act(ai_menu, "&Apply a response…", "Ctrl+Shift+Return",
                   self.apply_response_dialog)
        ai_menu.addSeparator()
        self.__act(ai_menu, "Copy the &art brief", None, self.copy_art_brief)

        project_menu = self.menuBar().addMenu("&Project")
        self.__act(project_menu, "Switch &genre…", None, self.switch_genre)
        self.ide_menu = project_menu.addMenu("Preferred &IDE")
        self.__build_ide_menu()

    def __build_ide_menu(self) -> None:
        self.ide_menu.clear()
        found = ide.detect()
        if not found:
            action = self.ide_menu.addAction("none detected")
            action.setEnabled(False)
            return
        group = QActionGroup(self)
        group.setExclusive(True)
        configured = self.session.project.meta.get("ide")
        for entry in found:
            action = self.ide_menu.addAction(f"{entry.name}  ({entry.how})")
            action.setCheckable(True)
            action.setChecked(entry.id == configured
                              or (configured is None and entry is found[0]))
            action.triggered.connect(
                lambda _c=False, i=entry.id: self.__set_ide(i))
            group.addAction(action)

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
        self.stamp_label = QLabel("  brush: gid 1  ")
        bar.addWidget(self.stamp_label)

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

    # -- the single mutation point -----------------------------------------

    def run(self, commands, *, label: str | None = None,
            source: str = "editor") -> bool:
        """Apply commands. Returns True on success; reports and returns False
        on a rejection. Never lets an editor error escape into Qt."""
        try:
            transaction = self.session.run(commands, label=label, source=source)
        except PyoneerEditorError as exc:
            QMessageBox.warning(self, "Rejected", str(exc))
            self.statusBar().showMessage("rejected — nothing changed", 6000)
            return False
        except Exception as exc:                                # noqa: BLE001
            QMessageBox.critical(self, type(exc).__name__, str(exc))
            return False
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
        self.setWindowTitle(self.__title())

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
        self.statusBar().showMessage(tool.label, 2000)

    def __on_stamp(self, stamp) -> None:
        self.canvas.stamp = stamp
        self.stamp_label.setText(
            f"  brush: gid {stamp.primary}  " if stamp.is_single
            else f"  brush: {stamp.width}×{stamp.height} stamp  ")

    def __on_picked(self, gid: int) -> None:
        self.palette.select_gid(gid)
        self.stamp_label.setText(f"  brush: gid {gid}  ")

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

    def save(self) -> None:
        try:
            written = self.session.save()
        except Exception as exc:                                # noqa: BLE001
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.statusBar().showMessage(
            f"wrote {len(written)} file{'' if len(written) == 1 else 's'}", 5000)
        self.setWindowTitle(self.__title())

    def play(self) -> None:
        """Launch the game as a subprocess. The editor is not the runtime."""
        if self.session.dirty:
            answer = QMessageBox.question(
                self, "Unsaved changes",
                "The game reads files from disk. Save before playing?")
            if answer == QMessageBox.Yes:
                self.save()
        main = os.path.join(self.session.project.root, "main.py")
        if not os.path.isfile(main):
            QMessageBox.warning(self, "No entry point", f"{main} does not exist.")
            return
        try:
            subprocess.Popen([sys.executable, main],
                             cwd=self.session.project.root)
        except OSError as exc:
            QMessageBox.warning(self, "Could not launch", str(exc))
            return
        self.statusBar().showMessage("launched main.py", 4000)

    def open_database(self) -> None:
        if self.database is None:
            self.database = DatabaseWindow(self.session, self)
            self.database.command_requested.connect(self.run)
            self.database.reveal_requested.connect(self.reveal)
        self.database.refresh()
        self.database.show()
        self.database.raise_()
        self.database.activateWindow()

    def switch_genre(self) -> None:
        from editor.core import genre as genre_module

        options = genre_module.available()
        current = self.session.project.genre.id
        index = options.index(current) if current in options else 0
        chosen, ok = QInputDialog.getItem(self, "Genre",
                                          "Genre pack for this project:",
                                          options, index, False)
        if ok and chosen != current:
            if self.run(Command("project.genre.set", Scope.of("project"),
                                {"genre": chosen})) and self.database is not None:
                self.database.rebuild()

    def copy_art_brief(self) -> None:
        from PySide6.QtWidgets import QApplication

        brief = self.session.project.genre.art_brief
        if not brief:
            QMessageBox.information(
                self, "No art brief",
                f"Genre {self.session.project.genre.id!r} ships no ART.md.")
            return
        QApplication.clipboard().setText(brief)
        self.statusBar().showMessage(
            "art brief copied — paste it into an image model", 6000)

    # -- code ---------------------------------------------------------------

    def __set_ide(self, ide_id: str) -> None:
        self.session.project.meta["ide"] = ide_id
        self.statusBar().showMessage(f"IDE set to {ide_id}", 4000)

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
                             configured=self.session.project.meta.get("ide"))
        self.statusBar().showMessage(result.message, 8000)
        if not result.ok and not ide.detect():
            QMessageBox.information(
                self, "No IDE found",
                "Could not find PyCharm, VS Code, IntelliJ, Sublime or "
                "Notepad++ on this machine.\n\n" + result.message)

    # -- the AI loop -------------------------------------------------------

    def ship(self) -> None:
        if self.session.manifest.empty:
            QMessageBox.information(
                self, "Nothing staged",
                "Type a note under any panel first. The panel's scope is "
                "attached automatically, so the request knows where it lands.")
            return
        title, ok = QInputDialog.getText(
            self, "Ship request", "Title for this request:",
            text=self.session.manifest.suggested_title())
        if not ok:
            return
        try:
            bundle = self.session.ship(title=title)
        except Exception as exc:                                # noqa: BLE001
            QMessageBox.critical(self, "Could not write the request", str(exc))
            return
        self.refresh_manifest()
        self.__watch_requests()
        relative = os.path.relpath(bundle.directory, self.session.project.root)
        QMessageBox.information(
            self, "Request written",
            f"Wrote {relative}\n\nHand it to Claude Code:\n\n"
            f"    Read {relative}/BRIEF.md and do the work\n\n"
            f"The editor is watching for {RESPONSE_FILE}.")

    def apply_response_dialog(self) -> None:
        start = os.path.join(self.session.project.root, REQUESTS_DIR)
        path, _ = QFileDialog.getOpenFileName(
            self, "Apply a response", start, "JSON Lines (*.jsonl);;All files (*)")
        if path:
            self.apply_response(path)

    def apply_response(self, path: str) -> None:
        try:
            commands = read_response(path)
        except Exception as exc:                                # noqa: BLE001
            QMessageBox.warning(self, "Unreadable response", str(exc))
            return
        identifier = os.path.basename(os.path.dirname(os.path.abspath(path)))
        preview = "\n".join(f"  {c}" for c in commands[:20])
        if len(commands) > 20:
            preview += f"\n  … and {len(commands) - 20} more"
        answer = QMessageBox.question(
            self, "Apply response",
            f"{identifier} contains {len(commands)} command"
            f"{'' if len(commands) == 1 else 's'}:\n\n{preview}\n\n"
            f"Apply as one undoable transaction?")
        if answer != QMessageBox.Yes:
            return
        self.run(commands, label=f"response {identifier}",
                 source=f"response:{identifier}")

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
        name = os.path.basename(os.path.dirname(path))
        answer = QMessageBox.question(
            self, "Response arrived",
            f"{name} has a response. Review and apply it?")
        if answer == QMessageBox.Yes:
            self.apply_response(path)
