"""The editor window.

Holds the session and is the only place that calls `session.run`. Panels
reach it with `self.window().run(command)`, so there is exactly one place
where a change enters the project, one place that catches a rejection, and
one place that refreshes the views afterwards.
"""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QLabel,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QSpinBox,
    QToolBar,
)

from editor.core.commands import Command
from editor.core.errors import PyoneerEditorError
from editor.core.request import REQUESTS_DIR, RESPONSE_FILE, read_response
from editor.core.scope import Scope
from editor.ui.canvas import MapCanvas, TilePalette
from editor.ui.docks import (
    HistoryDock,
    LayersDock,
    ManifestDock,
    ObjectsDock,
    ProblemsDock,
)
from editor.ui.tables import TablesDock

_OBJECT_CLASSES = (
    "GamePlayer", "GameEntity", "GameFloorEntity",
    "GameBackgroundEntity", "GameForegroundEntity", "GameUIEntity",
)


class EditorWindow(QMainWindow):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.map_name = (session.project.map_names() or ["<none>"])[0]
        self.setWindowTitle(self.__title())
        self.resize(1500, 950)

        self.canvas = MapCanvas(session, self.map_name, self)
        self.canvas.status.connect(self.__on_status)
        self.setCentralWidget(self.canvas)

        map_scope = Scope.of(("map", self.map_name))
        self.layers = LayersDock("Layers", session, map_scope, self)
        self.objects = ObjectsDock("Objects", session, map_scope, self)
        self.tables = TablesDock("Tables", session, Scope.of(("table", "actors")), self)
        self.problems = ProblemsDock("Problems", session, Scope.of("project"), self)
        self.manifest = ManifestDock("Manifest", session, Scope.of("project"), self)
        self.history = HistoryDock("History", session, Scope.of("project"), self)

        self.addDockWidget(Qt.LeftDockWidgetArea, self.layers)
        self.addDockWidget(Qt.RightDockWidgetArea, self.objects)
        self.addDockWidget(Qt.RightDockWidgetArea, self.tables)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.problems)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.manifest)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.history)
        self.tabifyDockWidget(self.problems, self.history)
        self.problems.raise_()

        self.palette_dock = self.__build_palette()
        self.layers.layer_selected.connect(self.__on_layer)
        self.manifest.ship_requested.connect(self.ship)

        self.__build_actions()
        self.__build_toolbar()
        self.statusBar().showMessage("Alt+click paints. Alt+right-click erases.")

        self.__watcher = QFileSystemWatcher(self)
        self.__watcher.directoryChanged.connect(self.__on_requests_changed)
        self.__watch_requests()

        self.refresh_all()

    # -- construction ------------------------------------------------------

    def __build_palette(self):
        from PySide6.QtWidgets import QDockWidget

        dock = QDockWidget("Tiles", self)
        dock.setObjectName("Tiles")
        self.palette = TilePalette(dock)
        self.palette.gid_picked.connect(self.__on_gid)
        dock.setWidget(self.palette)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        return dock

    def __build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self.__act(file_menu, "&Save", QKeySequence.Save, self.save)
        file_menu.addSeparator()
        self.__act(file_menu, "&Play the game", "F5", self.play)
        file_menu.addSeparator()
        self.__act(file_menu, "&Quit", QKeySequence.Quit, self.close)

        edit_menu = self.menuBar().addMenu("&Edit")
        self.undo_action = self.__act(edit_menu, "&Undo", QKeySequence.Undo, self.undo)
        self.redo_action = self.__act(edit_menu, "&Redo", QKeySequence.Redo, self.redo)

        ai_menu = self.menuBar().addMenu("&AI")
        self.__act(ai_menu, "&Ship staged notes as a request…", "Ctrl+Return", self.ship)
        self.__act(ai_menu, "&Apply a response…", "Ctrl+Shift+Return",
                   self.apply_response_dialog)
        ai_menu.addSeparator()
        self.__act(ai_menu, "Copy the &art brief", None, self.copy_art_brief)

        project_menu = self.menuBar().addMenu("&Project")
        self.__act(project_menu, "Switch &genre…", None, self.switch_genre)

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
        self.addToolBar(bar)

        bar.addWidget(QLabel("  gid "))
        self.gid_spin = QSpinBox()
        self.gid_spin.setRange(0, 999999)
        self.gid_spin.setValue(1)
        self.gid_spin.valueChanged.connect(self.__on_gid)
        bar.addWidget(self.gid_spin)

        bar.addSeparator()
        bar.addWidget(QLabel("  object class "))
        self.class_combo = QComboBox()
        self.class_combo.addItems(_OBJECT_CLASSES)
        self.class_combo.setEditable(True)
        self.class_combo.currentTextChanged.connect(self.__on_class)
        bar.addWidget(self.class_combo)

        bar.addSeparator()
        self.genre_label = QLabel(f"  genre: {self.session.project.genre.id}  ")
        bar.addWidget(self.genre_label)

    def __title(self) -> str:
        star = "*" if self.session.dirty else ""
        return (f"Pyoneer Editor{star} — {self.session.project.genre.title} — "
                f"{self.session.project.root}")

    # -- the single mutation point -----------------------------------------

    def run(self, commands, *, label: str | None = None,
            source: str = "editor") -> bool:
        """Apply commands. Returns True on success; reports and returns
        False on a rejection. Never lets an editor error escape into Qt."""
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
        self.canvas.rebuild()
        if self.canvas.atlas is not None:
            self.palette.set_atlas(self.canvas.atlas)
        for dock in (self.layers, self.objects, self.tables,
                     self.problems, self.manifest, self.history):
            dock.refresh()
        self.undo_action.setEnabled(self.session.stream.can_undo)
        self.redo_action.setEnabled(self.session.stream.can_redo)
        self.genre_label.setText(f"  genre: {self.session.project.genre.id}  ")
        self.setWindowTitle(self.__title())

    def refresh_manifest(self) -> None:
        self.manifest.refresh()
        for dock in (self.layers, self.objects, self.tables,
                     self.problems, self.manifest, self.history):
            dock.strip.refresh()

    def set_layer_visible(self, name: str, visible: bool) -> None:
        self.canvas.set_layer_visible(name, visible)

    # -- slots -------------------------------------------------------------

    def __on_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 3000)

    def __on_layer(self, name: str) -> None:
        self.canvas.active_layer = name
        self.objects.set_scope(Scope.of(("map", self.map_name), ("layer", name)))
        self.objects.refresh()

    def __on_gid(self, gid: int) -> None:
        self.canvas.brush_gid = int(gid)
        if self.gid_spin.value() != gid:
            self.gid_spin.blockSignals(True)
            self.gid_spin.setValue(int(gid))
            self.gid_spin.blockSignals(False)

    def __on_class(self, name: str) -> None:
        self.canvas.object_class = name

    # -- commands ----------------------------------------------------------

    def undo(self) -> None:
        if self.session.undo() is not None:
            self.refresh_all()

    def redo(self) -> None:
        if self.session.redo() is not None:
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
        subprocess.Popen([sys.executable, main], cwd=self.session.project.root)
        self.statusBar().showMessage("launched main.py", 4000)

    def switch_genre(self) -> None:
        from editor.core import genre as genre_module

        options = genre_module.available()
        current = self.session.project.genre.id
        index = options.index(current) if current in options else 0
        chosen, ok = QInputDialog.getItem(self, "Genre",
                                          "Genre pack for this project:",
                                          options, index, False)
        if ok and chosen != current:
            self.run(Command("project.genre.set", Scope.of("project"),
                             {"genre": chosen}))

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
            f"Wrote {relative}\n\n"
            f"Hand it to Claude Code:\n\n"
            f"    Read {relative}/BRIEF.md and do the work\n\n"
            f"The editor is watching for {RESPONSE_FILE} and will offer to "
            f"apply it.")

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
        for path in [base] + [os.path.join(base, d) for d in os.listdir(base)
                              if os.path.isdir(os.path.join(base, d))]:
            if path not in existing:
                self.__watcher.addPath(path)

    def __on_requests_changed(self, directory: str) -> None:
        self.__watch_requests()
        candidate = os.path.join(directory, RESPONSE_FILE)
        if not os.path.isfile(candidate):
            return
        if candidate in getattr(self, "_seen_responses", set()):
            return
        self._seen_responses = getattr(self, "_seen_responses", set())
        self._seen_responses.add(candidate)
        # Give the writer a moment to finish; a half-written jsonl is the
        # obvious race here and a 400ms wait is cheaper than a parse error.
        QTimer.singleShot(400, lambda: self.__offer(candidate))

    def __offer(self, path: str) -> None:
        name = os.path.basename(os.path.dirname(path))
        answer = QMessageBox.question(
            self, "Response arrived",
            f"{name} has a response. Review and apply it?")
        if answer == QMessageBox.Yes:
            self.apply_response(path)
