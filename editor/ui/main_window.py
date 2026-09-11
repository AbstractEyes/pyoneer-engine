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

A rejected command goes down the second channel: nothing changed, so there
is no decision to interrupt for. The three dialogs in this file are the
three that carry a choice -- which genre pack, whether to apply an AI's
command list, and whether unsaved work survives the window closing -- and
`QMessageBox.critical` survives in three places, all of them an unexpected
exception where the alternative is losing work.

The third of those is `closeEvent`, and it is the only one the author does
not open on purpose: nothing else in this window writes at command time, so
until it existed, closing threw away every edit since the last save without
a word. Read its docstring before touching `save`, `play` or `&Quit` --
all three lean on the same one-line contract, that `save` returns None and
only None when it has already shown its own stop.
"""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QFileSystemWatcher, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSpinBox,
    QToolBar,
)

from editor.core import ide
from editor.core.collision import describe_opinion
from editor.core.commands import Command
from editor.core.errors import (
    PyoneerEditorError,
    PyoneerScopeRefusedError,
)
from editor.core.genre import RuleViolation
from editor.core.inspect import Field
from editor.core.layers import describe_mask
from editor.core.paint import EditMode, Tool
from editor.core.request import REQUESTS_DIR, RESPONSE_FILE, read_response
from editor.core.scope import Scope
from editor.ui.actions_panel import ActionsDock
from editor.ui.ask import ask_form, choose_file, confirm
from editor.ui.behavior_panel import BehaviorDock
from editor.ui.canvas import MapCanvas, TilePalette, TilesetFacts
from editor.ui.collision_view import MaskPalette, build_mode_actions
from editor.ui.database import DatabaseWindow
from editor.ui.docks import HistoryDock, ManifestDock, ProblemsDock
from editor.ui.hierarchy import HierarchyDock
from editor.ui.icons import tool_icon
from editor.ui.inspector import InspectorDock
from editor.ui.object_editor import ObjectEditor
from editor.ui.script_editor import ScriptEditor
from editor.ui.selection import Selection
from editor.ui.settings_dialog import SettingsDialog
from editor.ui.tileset_dialog import TilesetImportDialog
from editor.ui import theme as theme_module
from editor.ui.theme import Theme
from editor.core.settings import APPLICATION, ORGANISATION, EditorSettings

_OBJECT_CLASSES = (
    "GamePlayer", "GameEntity", "GameFloorEntity",
    "GameBackgroundEntity", "GameForegroundEntity", "GameUIEntity",
)

#: The Tiles dock's tab label, in each mode. It changes because what a click
#: in that palette DOES changes: in collision mode the brush is a mask and a
#: tile pick is the target that mask is written onto. `objectName` -- which is
#: what Qt saves and restores dock state by -- is deliberately NOT this, so
#: the label can move without moving the layout the author arranged.
TILES_TITLE = "Tiles"
TILES_AS_MASK_TARGET = "Tiles → mask"

#: Where the arranged dock layout is kept. Deliberately NOT an
#: `EditorSettings` entry: those are typed str/bool/int preferences the
#: settings dialog offers a control for, and this is an opaque Qt blob that
#: nobody reads, edits or validates. It is keyed by every dock's
#: `objectName`, which is why each one sets a name and why those names are
#: not the visible titles.
LAYOUT_KEY = "window/state"


def layout_store():
    """The store the arranged layout is written to and read back from.

    A SEAM, held on the window like `ask` and `confirm`, and for the same
    reason: a check drives a real `EditorWindow` and closes it, so a
    `QSettings` built inline inside the save would write the developer's own
    preferences on every run -- and a restore reading them back would make
    the suite's answer depend on how that developer last dragged a panel.
    """
    return QSettings(ORGANISATION, APPLICATION)


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
        #: The entity editing screen while it exists. ONE of them, re-aimed
        #: at whichever object is being edited -- see `edit_object`. Held for
        #: the same reason the tile importer is: it is a non-modal top-level
        #: window, and without a reference Python collects it the moment the
        #: function that opened it returns, which looks exactly like the
        #: window flashing and vanishing.
        self.object_editor: ObjectEditor | None = None
        #: The event screen while it exists. ONE of them, re-aimed at
        #: whichever script is being written -- and held for the same
        #: reason as the entity screen above it. A script is a SHARED
        #: document, so it is reachable both from an object that runs it
        #: and from the menu, which is why this is not owned by
        #: `object_editor`.
        self.script_editor: ScriptEditor | None = None
        #: The tile importer while it is open. Non-modal, so the window has
        #: to hold it: without a reference Python collects it the moment
        #: `add_tileset` returns and it vanishes as it appears.
        self.tileset_import = None
        # The dialog seams, same as every panel's. See editor/ui/ask.py.
        self.ask = ask_form
        self.confirm = confirm
        #: The platform file picker, as a replaceable attribute for the same
        #: reason as the two above (law 13). It was inline here as
        #: a bare `getOpenFileName` and the source census could not see
        #: it -- so a check driving Apply-a-response would have sat on a
        #: modal until the 600s timeout, and nothing said so.
        self.choose_file = choose_file
        # The layout seam, same shape and the same reason. See `layout_store`.
        self.layout_store = layout_store
        #: The last response file that arrived on disk and has not been
        #: applied. Surfaced in the status bar, never as a modal.
        self.pending_response: str | None = None
        #: The colour the current theme paints behind the map. Held rather
        #: than asked for, because a canvas built AFTER `apply_theme` ran --
        #: every canvas but the first, once `&Maps` can swap one in -- has
        #: no other way to come up in the theme the window is already in.
        self.canvas_background = None
        self.setWindowTitle(self.__title())
        self.resize(1600, 1000)

        map_scope = Scope.of(("map", self.map_name))
        self.selection = self.__new_selection(map_scope)

        self.canvas = self.__new_canvas(self.map_name)
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
        # newcomer on top and the Inspector is what a selection usually wants.
        # The collision palette was tabbed on this same argument and is NOT
        # any more -- see `__build_mask_palette` for why the two cases part.
        self.addDockWidget(Qt.RightDockWidgetArea, self.behaviors)
        self.tabifyDockWidget(self.inspector, self.behaviors)
        # Actions answers "what is this selected thing", so it tabs with the
        # Inspector, like Behaviors.
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

        self.docks = (self.hierarchy, self.inspector, self.behaviors,
                      self.actions, self.problems, self.manifest, self.history)

        self.__build_actions()
        self.__build_toolbar()
        self.statusBar().showMessage(
            "left drag paints · right drag erases · middle or space pans · "
            "wheel zooms the map, ctrl+wheel the palette · alt+click picks "
            "the tile under the cursor · drag in the palette picks a stamp")

        self.__watcher = QFileSystemWatcher(self)
        self.__watcher.directoryChanged.connect(self.__on_requests_changed)
        self.__seen_responses: set[str] = set()
        self.__watch_requests()

        # The three view preferences are applied by `__new_canvas`, which
        # is where every canvas this window mounts is wired; only the theme
        # is left, because it repaints the whole application and not just
        # the map.
        self.apply_theme(Theme.parse(self.settings.get("theme")))
        self.refresh_all()
        self.__select_first_paintable_layer()
        # LAST, because `restoreState` matches saved entries against the
        # docks and toolbars that exist NOW: anything built after it would
        # come up in its default place and quietly ignore the arrangement.
        if not self.__restore_layout():
            # DEFAULT proportions, and only when nothing was stored: an
            # arrangement the author dragged outranks them, and a resize
            # after a restore would silently undo half of what came back.
            # After `__restore_layout`, not inside `__build_mask_palette`,
            # because a resize asked for before the toolbar and the theme
            # land is measurably discarded -- the left column comes back
            # split evenly, which is the collision swatches taking as much
            # height as every tileset in the project.
            self.resizeDocks([self.hierarchy, self.palette_dock, self.mask_dock],
                             [300, 520, 220], Qt.Vertical)

    # -- construction ------------------------------------------------------

    def __new_selection(self, scope: Scope) -> Selection:
        """The cursor into the project, rooted at one map.

        A FRESH ONE PER MAP, which is what makes `Alt+Left` safe: the
        history is a list of scopes, and a history spanning two maps hands
        `__on_selection` a layer that is not on the map the canvas is
        showing. Rooting a new cursor at the new map is the same thing
        `__init__` does on the first one, so a switched window is in the
        state a freshly opened window would be in.

        The menu entries for `Back` and `Select the parent` go through
        `self.selection` at CLICK time and not through a bound method
        captured at build time, for exactly this reason.
        """
        selection = Selection(scope, self)
        selection.changed.connect(self.__on_selection)
        return selection

    def __new_canvas(self, name: str) -> MapCanvas:
        """A canvas on one map, wired to this window and to nothing else.

        ONE PLACE, because there are two callers: `__init__` builds a canvas
        and `__switch_map` builds another every time the author picks a
        different map. A second spelling of "wired up" is a wire that goes
        missing on whichever of the two paths is looked at less -- the five
        signals, the four view preferences and the theme's background all
        have to be here or a switched-to canvas is subtly less connected
        than the first one and nothing says so.

        The preferences are read from `self.settings` rather than copied off
        the outgoing canvas: they are the author's stored answers, and
        `__on_setting_changed` writes them to whichever canvas is mounted,
        so the store stays the one source and the widget never becomes one.
        """
        canvas = MapCanvas(self.session, name, self)
        canvas.status.connect(self.__on_status)
        canvas.picked_gid.connect(self.__on_picked)
        canvas.picked_mask.connect(self.__on_picked_mask)
        canvas.selected.connect(self.selection.select)
        # The entity editing screen's door. The canvas decides WHEN an object
        # wants editing -- creating one, double-clicking one -- and hands over
        # the scope; this window owns the window that opens. Spelled exactly
        # `edit_object_requested(Scope)` on both sides: a signal renamed on
        # one side only is a wire that looks connected and is not.
        canvas.edit_object_requested.connect(self.edit_object)
        canvas.show_grid = self.settings.get("show_grid")
        canvas.grid_step = self.settings.get("grid_step")
        canvas.collision_subcell = self.settings.get("collision_subcell")
        canvas.snap_objects = self.settings.get("snap_objects")
        canvas.set_background(self.canvas_background)
        return canvas

    def __build_palette(self) -> QDockWidget:
        dock = QDockWidget(TILES_TITLE, self)
        dock.setObjectName("Tiles")
        self.palette = TilePalette(dock)
        self.palette.stamp_picked.connect(self.__on_stamp)
        # The palette's own door onto the importer, beside the tilesets it
        # will be added to. The menu entry stays -- one action, two places a
        # hand already is.
        self.palette.add_tiles_requested.connect(self.add_tileset)
        # And the door onto the three verbs that address a whole tileset,
        # off the right-click on its header. The palette decides and argues;
        # this window is still the only thing that runs a command.
        self.palette.tileset_requested.connect(self.tileset_command)
        # The half of that decision the palette cannot see. A seam rather
        # than a push, because two of these answers walk every cell of every
        # tile layer and a menu opens far less often than a command lands.
        self.palette.tileset_facts = self.tileset_facts
        dock.setWidget(self.palette)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        return dock

    def __build_mask_palette(self) -> QDockWidget:
        """The collision brush, BESIDE the tile palette and never behind it.

        SPLIT, NOT TABBED.  #TAG:mask_palette_is_never_tabbed
        That is the whole point of this method's shape. It was tabified onto
        `palette_dock` once, on the argument that both answer "what am I
        painting with" and only one can be the answer at a time. That
        argument is sound and the result was not: a tab is a control that
        hides its own contents, so the seventeen masks were one click away
        and zero pixels wide, and the standing complaint was that collision
        should be visible on the screen as a palette selector rather than
        filed behind the tiles. Two `addDockWidget` calls into
        the same area with NO `tabifyDockWidget` between them leaves Qt
        splitting the strip, so both vocabularies are on screen at once and
        neither needs a mode change or a `raise_()` to be seen.

        The proportions of that split are set at the END of `__init__` and
        not here: a `resizeDocks` asked for at this point is measurably
        discarded, and an evenly divided column gives five rows of swatches
        as much height as every tileset in the project.

        The palette emits a MASK; turning it into a gid needs the companion
        layer's firstgid, which is the canvas's business, so `set_mask` takes
        it raw.

        ONE MASK, TWO TARGETS, and this widget knows about neither: a mask
        picked here is written into a map CELL by a canvas stroke, or onto a
        TILE by a pick in the palette next door (`MapCanvas.set_stamp`).
        """
        dock = QDockWidget("Collision", self)
        dock.setObjectName("Collision")
        self.mask_palette = MaskPalette(dock)
        self.mask_palette.mask_picked.connect(self.canvas.set_mask)
        dock.setWidget(self.mask_palette)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        return dock

    # -- the arranged layout -----------------------------------------------

    def __restore_layout(self) -> bool:
        """Put the docks back where the author last dragged them.

        Answers whether it did, because the caller sizes the left column by
        hand when it did not.

        NOTHING STORED IS NOT A FAILURE. A first launch, or a fresh machine,
        has no blob and keeps the layout `__init__` just built -- which is
        the one this window is designed around, with the tile palette and
        the collision palette both on screen and neither behind the other.

        A blob that will NOT restore is a failure, and it is the silent
        kind: the author arranged a window, it came back wrong, and nothing
        said why. `restoreState` answers False for a state written by a
        different Qt or naming docks that no longer exist, so that answer
        goes down the `report` channel and stays in Problems until the next
        arrangement replaces it. The blob is left on disk rather than
        deleted: arranging the window again overwrites it anyway, and
        throwing it away here would destroy the only copy of a layout a
        newer Qt might still read.
        """
        blob = self.layout_store().value(LAYOUT_KEY)
        if not blob:
            return False
        if self.restoreState(blob):
            return True
        self.report(
            "the stored panel layout could not be restored - the panels "
            "are in their default places",
            key="layout", severity="soft",
            fix="arrange the panels once and close the editor; that "
                "replaces the stored layout")
        return False

    def __save_layout(self) -> None:
        """Remember the arrangement, on the way out and nowhere else.

        `closeEvent` is the only caller, because closing is the only moment
        the layout is final. Writing on every drag would hit the store dozens
        of times a minute AND would record arrangements the hand was still in
        the middle of making.
        """
        self.layout_store().setValue(LAYOUT_KEY, self.saveState())

    def __build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self.__act(file_menu, "&Save", QKeySequence.Save, self.save)
        self.maps_menu = file_menu.addMenu("&Maps")
        self.map_group = QActionGroup(self)
        self.map_group.setExclusive(True)
        self.map_actions: dict[str, QAction] = {}
        self.__build_map_actions()
        file_menu.addSeparator()
        self.__act(file_menu, "&Play the game", "F5", self.play)
        self.__act(file_menu, "Open the &project in my IDE", None,
                   lambda: self.reveal("main.py"))
        file_menu.addSeparator()
        self.__act(file_menu, "Se&ttings…", "Ctrl+,", self.open_settings)
        file_menu.addSeparator()
        # `self.close` and not a quit of its own: `QWidget.close` posts the
        # QCloseEvent that `closeEvent` answers, so the menu entry, the
        # window's own close button and the window manager are ONE path and
        # cannot disagree about whether unsaved work is offered a save. A
        # `QApplication.quit()` here would be the way to make them disagree
        # -- it tears the loop down without ever asking a window anything.
        self.__act(file_menu, "&Quit", QKeySequence.Quit, self.close)

        edit_menu = self.menuBar().addMenu("&Edit")
        self.undo_action = self.__act(edit_menu, "&Undo", QKeySequence.Undo, self.undo)
        self.redo_action = self.__act(edit_menu, "&Redo", QKeySequence.Redo, self.redo)
        edit_menu.addSeparator()
        # Through `self.selection` at CLICK time, never a bound method
        # captured here: `__switch_map` roots a fresh cursor at the new map,
        # and a menu holding the old object would navigate a selection
        # nothing else is listening to.
        self.__act(edit_menu, "Select the &parent", "Alt+Up",
                   lambda: self.selection.select_parent())
        self.__act(edit_menu, "&Back", "Alt+Left",
                   lambda: self.selection.back())

        view_menu = self.menuBar().addMenu("&View")
        # Driven off `self.docks` rather than a second hand-written list:
        # the previous copy went stale silently, and a dock missing from
        # here is a panel the author cannot get back once it is closed.
        for dock in self.docks + (self.palette_dock, self.mask_dock):
            view_menu.addAction(dock.toggleViewAction())
        view_menu.addSeparator()
        # ONE GESTURE, on the menu the author already opens to show a panel.
        # A preference that exists only inside the settings dialog is the
        # shape this tree keeps shipping and then filing as unreachable, and
        # snapping is decided per object -- a tile-shaped body wants it, a
        # trigger region does not -- so it is asked for far too often to live
        # three clicks away. The dialog still offers it: this and the dialog
        # write the SAME stored preference, through `set_snap_objects`.
        self.snap_action = QAction("&Snap objects to the grid", self)
        self.snap_action.setCheckable(True)
        self.snap_action.setShortcut("Ctrl+G")
        self.snap_action.setToolTip(
            "place and drag objects on cell boundaries")
        # Checked BEFORE it is connected. `setChecked` emits `toggled`, and a
        # handler reached during construction would write the stored
        # preference -- editing the machine's real QSettings -- to say what it
        # already says.
        self.snap_action.setChecked(bool(self.settings.get("snap_objects")))
        self.snap_action.toggled.connect(self.set_snap_objects)
        view_menu.addAction(self.snap_action)
        view_menu.addSeparator()
        self.__act(view_menu, "Zoom &in", QKeySequence.ZoomIn,
                   lambda: self.canvas.scale(1.25, 1.25))
        self.__act(view_menu, "Zoom &out", QKeySequence.ZoomOut,
                   lambda: self.canvas.scale(0.8, 0.8))
        self.__act(view_menu, "&Reset zoom", "Ctrl+0", self.__reset_zoom)

        data_menu = self.menuBar().addMenu("&Database")
        self.__act(data_menu, "&Open the database…", "Ctrl+D", self.open_database)
        # THE EVENT SCREEN HAS TWO DOORS, and this is the one that does not
        # go through an object. A script is a shared document -- a keeper, a
        # chest and a sign can all run the same one -- so "open the script I
        # am writing" must not require first finding something that runs it.
        # The other door is the Script row in the entity screen, which is
        # where the author looked for it.
        self.__act(data_menu, "&Event scripts…", "Ctrl+E", self.open_script)

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

    def __build_map_actions(self) -> None:
        """One checkable entry per DECLARED map, with the open one ticked.

        THE PICKER IS THE WHOLE FEATURE.  #TAG:the_window_was_the_last_single_map_layer
        Every layer under this window has been multi-map since it was
        written -- `Project.map` opens and caches any declared name,
        `Session.known_scopes` walks all of them "for pickers and
        validation" -- while this window pinned itself to `map_names()[0]`.
        A project could declare ten maps and the editor would open the
        alphabetically first one and offer no way at all to reach the other
        nine. No verb and no file-format work is needed to fix that, only a
        control, which is why this builds a picker and not a `map.create`.

        Rebuilt from `map_names()` rather than built once, because a menu
        that has gone stale is a menu lying about which maps exist;
        `__sync_actions` rebuilds only when the list itself moved, so the
        common case costs one comparison of a list of strings.

        The actions are parented to the MENU and not to the window, which is
        what lets `clear()` delete them: parented to the window they would
        be removed from the menu, kept alive by Qt, and would accumulate one
        dead action per rebuild.
        """
        for action in self.map_actions.values():
            self.map_group.removeAction(action)
        self.maps_menu.clear()
        self.map_actions = {}
        for name in self.session.project.map_names():
            action = QAction(name, self.maps_menu)
            action.setCheckable(True)
            action.setChecked(name == self.map_name)
            action.setStatusTip(f"edit map:{name}")
            action.triggered.connect(
                lambda _checked=False, n=name: self.__switch_map(n))
            self.map_group.addAction(action)
            self.maps_menu.addAction(action)
            self.map_actions[name] = action

    def __switch_map(self, name: str) -> None:
        """Point this window at another declared map.

        IT ASKS NOTHING, AND THAT IS A MEASUREMENT.  #TAG:switching_maps_discards_nothing
        `Project.map` opens a document once and caches it for the life of
        the project, `save` writes EVERY dirty document rather than the one
        on screen, and nothing on this path closes a document. So an unsaved
        edit on the map being left stays exactly where it was: in memory,
        still dirty, still undoable, still written by the next Ctrl+S. A
        prompt here would be protecting nothing, and `closeEvent` already
        carries this editor's ruling on that shape -- a question that cannot
        possibly save any work is what teaches a hand to dismiss questions,
        and then the one that matters is dismissed too. `closeEvent` stays
        the only place work can be lost and the only place that asks.

        THE MAP IS OPENED BEFORE ANYTHING IS TORN DOWN. A name that will not
        open is reported and changes nothing at all, rather than leaving the
        window half-switched with no canvas -- law 7 on the one path where
        the plausible default is "carry on and see what happens".

        The canvas swap is law 12 in its QMainWindow spelling: the central
        widget is TAKEN first, re-parented to this window, hidden, and
        deleted LATER. `setCentralWidget` alone frees the outgoing canvas
        synchronously, and this is reached from a QAction's own `triggered`
        while that signal is still on the stack.

        The toolbar does not change, so the canvas under it must not either:
        a mode button reading COLLISION over a canvas that came up in TILES
        is a control lying about what the next click does.
        """
        if name == self.map_name:
            return
        try:
            self.session.project.map(name)
        except Exception as exc:                                # noqa: BLE001
            self.report(f"cannot open map:{name}: {exc}", key="switch_map",
                        detail=f"{type(exc).__name__}: {exc}",
                        fix=f"map:{self.map_name} is still the map on screen")
            self.__sync_actions()       # put the tick back on the open map
            return
        self.clear("switch_map")

        closed_importer = self.tileset_import is not None
        if closed_importer:
            # It is aimed at the map it was opened on: `import_tileset`
            # reads `self.map_name` when the author presses Add, and the
            # names and the next gid it argues about came from that map's
            # document. Left open across a switch it would declare a region
            # into a map nobody chose, which is the silent-retarget shape.
            self.tileset_import.close()
        if self.object_editor is not None and self.object_editor.isVisible():
            # Same argument, and the same shape: it is aimed at an object on
            # the map being left. Its scope names that map, so its edits
            # would still land correctly -- and it would be a window editing
            # something the author can no longer see, which is worse than a
            # window that went away. Closing it commits the field in flight.
            self.object_editor.close()

        previous = self.canvas
        carried = (previous.tool, previous.mode, previous.stamp,
                   previous.mask, previous.all_layers)
        self.hierarchy.visibility_changed.disconnect(previous.set_layer_visible)
        self.mask_palette.mask_picked.disconnect(previous.set_mask)
        previous.detach()

        old = self.takeCentralWidget()      # #TAG:qt_takecentralwidget_sequence
        old.setParent(self)
        old.hide()
        old.deleteLater()

        self.map_name = name
        map_scope = Scope.of(("map", name))
        stale, self.selection = self.selection, self.__new_selection(map_scope)
        stale.changed.disconnect(self.__on_selection)
        stale.deleteLater()

        self.canvas = self.__new_canvas(name)
        self.setCentralWidget(self.canvas)
        self.hierarchy.visibility_changed.connect(self.canvas.set_layer_visible)
        self.mask_palette.mask_picked.connect(self.canvas.set_mask)

        tool, mode, stamp, mask, all_layers = carried
        self.canvas.tool = tool
        self.canvas.stamp = stamp
        self.canvas.mask = mask
        self.canvas.brush_size = int(self.size_spin.value())
        self.canvas.object_class = self.class_combo.currentText()
        self.canvas.set_mode(mode)
        self.canvas.set_all_layers(all_layers)

        self.selection.select(map_scope)
        self.__select_first_paintable_layer()
        self.refresh_all()
        self.notify(
            f"editing map:{name}" + (
                " - the tile importer closed with the map it was opened on"
                if closed_importer else ""), seconds=8)

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
        # A lambda and not `self.canvas.set_all_layers`: a bound method
        # captured here is bound to the canvas that exists NOW, and `&Maps`
        # replaces that canvas. The toggle would keep resolving the stack of
        # a map that is no longer on screen, with the button still lighting.
        self.modes = build_mode_actions(
            self, self.__on_mode, lambda on: self.canvas.set_all_layers(on))
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
        """Which project, which genre, and — since `&Maps` — which map.

        The map is in the title because it is now a choice. While the window
        could only ever open `map_names()[0]` there was nothing to say; with
        a picker, "which map am I editing" is a question the author can get
        wrong, and the title bar is the one surface that answers it without
        being asked.
        """
        star = "*" if self.session.dirty else ""
        return (f"Pyoneer Editor{star} — map:{self.map_name} — "
                f"{self.session.project.genre.title} — "
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

        A rejection comes down this channel, not a dialog: a verb refusing an
        edit that would corrupt gids is the system working, and a normal
        outcome must not stop the hand and take the keyboard.
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
            # BEFORE the atlas: `set_masks` does not repaint, and `set_atlas`
            # rebuilds unconditionally on the next line, so this order is
            # what draws the sheet once with its badges on.
            #
            # AFTER `set_selection`, which rebuilds the canvas and so re-reads
            # level one -- asking first would hand the palette the masks from
            # before the command that just landed, which on a bake is the one
            # command whose whole effect is the answer.
            #
            # It costs at most ONE `.blitmask` read per command, through the
            # canvas's memo, and nothing at all on a map that declares none.
            self.palette.set_masks(self.canvas.tile_masks())
            self.palette.set_atlas(self.canvas.atlas)
        if self.tileset_import is not None:
            self.__safely(self.__refresh_tileset_import, "Add tiles")
        # Only while it is on screen. It is kept alive between opens, and a
        # hidden window rebuilding two forms on every paint stroke is work
        # nobody can see. `edit_object` refreshes it on the way back up.
        if self.object_editor is not None and self.object_editor.isVisible():
            self.__safely(self.object_editor.refresh, "Object")
        # Same rule, same reason: an undo can take a script, a page or a
        # command back from under the event screen, and a screen that only
        # rebuilt when it was touched would go on offering a node that is
        # no longer in the document.
        if self.script_editor is not None and self.script_editor.isVisible():
            self.__safely(self.script_editor.refresh, "Events")
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

        A control that is present and refusing is worse than one greyed with
        a reason: the click has already been spent by the time the refusal
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

        names = self.session.project.map_names()
        maps = bool(names)
        self.add_tileset_action.setEnabled(maps)
        self.add_tileset_action.setToolTip(
            f"declare a sheet on map:{self.map_name}" if maps
            else "this project has no maps")

        # The picker, re-derived rather than remembered. The tick follows
        # `self.map_name` and NOT the last click: an exclusive QActionGroup
        # ticks whatever was clicked, and a switch that was REFUSED leaves
        # those two disagreeing — a menu claiming a map the window never
        # opened. Rebuilt only when the declared list itself moved, so this
        # costs one comparison of a list of strings on the refresh path.
        if list(self.map_actions) != names:
            self.__build_map_actions()
        for name, action in self.map_actions.items():
            action.setChecked(name == self.map_name)
        self.maps_menu.setEnabled(maps)
        self.maps_menu.setToolTip(
            "choose which declared map this window edits" if maps
            else "config/maps.json declares no maps")

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

        A rectangle, a filled rectangle and a flood fill read the stamp as a
        repeating pattern keyed on map coordinates, so a uniform 3x3 produces
        bit-identical edits to a 1x1 (`Tool.uses_size`). A live spinner for
        those three would be a control the author turns and watches do
        nothing.
        """
        tool = self.canvas.tool
        live = tool.uses_size
        self.size_spin.setEnabled(live)
        size = self.canvas.brush_size
        # The unit, spelled out: a size is in CELLS, and how big a cell is
        # depends on what is being painted.
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
        """A tile picked in the palette. In collision mode it is a TARGET.

        `set_stamp` rather than assigning `canvas.stamp`, because what a tile
        pick MEANS is the canvas's business: in tiles mode it is the brush,
        and in collision mode the brush is already a mask, so the tile is
        what that mask gets written onto. The readout follows the same split.
        """
        self.canvas.set_stamp(stamp)
        if self.canvas.mode is EditMode.COLLISION:
            target = (f"gid {stamp.primary}" if stamp.is_single
                      else f"{stamp.width}×{stamp.height} tiles")
            # `describe_opinion`, because the mask brush can now hold the
            # no-opinion chip: `describe_mask` reads -1 as every bit set and
            # would label the value that CLEARS a mask "blocks down, left,
            # right, up".
            self.stamp_label.setText(
                f"  {describe_opinion(self.canvas.mask)} → {target}  ")
            return
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
        # THE TAB SAYS WHAT A CLICK IN IT DOES. In collision mode a tile pick
        # writes that tile's own mask instead of setting a brush the mode
        # cannot paint with, and a control whose meaning changed while its
        # label did not is the shape this editor keeps paying for. The tab is
        # the one place the label is visible the whole time, so it carries it
        # -- and the status line below teaches the gesture once, on the
        # switch, rather than interrupting to explain it later.
        self.palette_dock.setWindowTitle(
            TILES_AS_MASK_TARGET if mode is EditMode.COLLISION else TILES_TITLE)
        if mode is EditMode.COLLISION:
            self.statusBar().showMessage(
                f"{mode.tip} · picking a tile in the Tiles palette gives "
                f"that TILE the current mask, everywhere it is stamped", 8000)

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
        transaction = self.session.undo()
        if transaction is not None:
            self.selection.reselect()
            self.refresh_all()
            # AFTER the refresh, and measured: a rebuild of the canvas emits
            # its own status line, so an announcement made first is written
            # over by the time the author looks at the bar.
            self.__announce_elsewhere(transaction, "undid")

    def redo(self) -> None:
        transaction = self.session.redo()
        if transaction is not None:
            self.selection.reselect()
            self.refresh_all()
            self.__announce_elsewhere(transaction, "redid")

    def __announce_elsewhere(self, transaction, what: str) -> None:
        """Say so when an undo landed on a map that is not on screen.

        THE STACK IS THE PROJECT'S, NOT THE MAP'S.  #TAG:undo_carries_the_scope_not_the_window
        Every inverse carries the scope of the command it takes back, so a
        transaction on map:a is undone on map:a whichever map this window
        happens to be showing. Clearing the stack when `&Maps` switches —
        the obvious alternative — would destroy the only route back for
        work the author has not saved, and applying it to the map on screen
        instead would be the worst outcome available here.

        What it is NOT, once a picker exists, is VISIBLE. Before one, a
        window saw every map there was and the question could not arise. Now
        Ctrl+Z can unwind a map nobody is looking at, and every symptom of
        that reads as "undo did nothing" — so the hand presses it again.

        The status bar and not a Problems row: an undo is a moment, not a
        standing situation, and a row would have to be retired by the next
        unrelated command.
        """
        maps = {command.scope.get("map") for command in transaction.commands}
        elsewhere = sorted(m for m in maps if m and m != self.map_name)
        if elsewhere:
            self.notify(f"{what} {transaction.label} on "
                        + ", ".join(f"map:{m}" for m in elsewhere)
                        + " — not the map on screen", seconds=8)

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

    def closeEvent(self, event) -> None:
        """The only door out of the editor, and the one place work is lost.

        Almost nothing in this window writes at command time -- two verbs
        out of thirty-six touch a `.blitmask` and every other edit lives in
        an open `MapDocument` until something calls `save`. So closing used
        to throw away every tile paint, every layer, every object edit and
        every passability cell since the last save, in silence:
        `window.close()` returned True, opened nothing, left the session
        dirty and left the .tmx byte-identical on disk.

        A CLEAN close asks NOTHING. A prompt that cannot possibly be
        protecting anything is the shape that teaches a hand to dismiss the
        prompt, and the one time it mattered it would be dismissed too.

        A DIRTY close is the canonical decision undo cannot reach (see
        `editor/ui/ask.py`), so it goes through `self.confirm` -- the seam a
        check can replace -- and never through a `QMessageBox` of its own.
        That seam is a yes/no, so the wording says outright which of the two
        outcomes each answer is rather than leaning on a cancel button that
        does not exist.

        The window stays OPEN for exactly ONE reason: the author asked to
        save and the SAVE FAILED. `save` returns None there and has already
        shown its own stop, so closing anyway would eat the work and the
        warning together. A refusal is not a failure -- "no, lose it" is an
        answer, and it closes.

        THE LISTING AND THE FLAG ARE ONE SENTENCE. The question asked here
        is raised by `session.dirty` and answered by three listings, so the
        two have to be the same fact or the prompt lies. They were not, for
        one pass: `dirty` learned about event scripts and the listing did
        not. `Project.dirty` is composed from the same three listings now --
        see `Project.dirty_scripts` -- which is why this reads three methods
        instead of asking each document kind its own question here.

        It is also where the ARRANGEMENT is remembered. `__save_layout` runs
        on each of the two paths that really close and on neither of the two
        that do not, so a window held open by a failed save does not record
        the layout of a session the author has not finished with.
        """
        # BEFORE `dirty` is read, because that is exactly what an uncommitted
        # field would change. The object editor is a child window, so quitting
        # destroys it without ever sending it a close event of its own, and
        # the value the author was typing into it would go with it -- and
        # would not even count towards the question asked below.
        if self.object_editor is not None:
            self.object_editor.commit_in_flight()
        if not self.session.dirty:
            self.__save_layout()
            event.accept()
            return
        project = self.session.project
        # ALL THREE KINDS, and the third was missing while `session.dirty`
        # already knew about it: a session dirty ONLY because of an event
        # script prompted correctly and then said "0 documents have changes
        # that are not on disk:" over an empty list. Nothing was lost -- Yes
        # saved the script too -- but the sentence was, which is the worse
        # half of the pair to get wrong, because it is the one the author
        # reads before deciding. `Project.dirty` is now exactly
        # `bool(dirty_maps() + dirty_tables() + dirty_scripts())`, so this
        # list is empty only when the branch above has already returned.
        unsaved = (project.dirty_maps() + project.dirty_tables()
                   + project.dirty_scripts())
        listing = "\n".join(f"  {name}" for name in unsaved)
        many = len(unsaved) != 1
        if self.confirm(
                self, "Unsaved changes",
                f"{len(unsaved)} document{'s' if many else ''} "
                f"{'have' if many else 'has'} changes that are not on "
                f"disk:\n\n{listing}\n\n"
                f"Yes: save them, then close.\n"
                f"No: close and LOSE them."):
            if self.save() is None:
                event.ignore()          # the save failed and said so
                return
        self.__save_layout()
        event.accept()

    def play(self) -> None:
        """Save, then launch the game as a subprocess. Not the runtime.

        Saves without asking. The game reads files from disk and the editor
        knows whether the session is dirty, so there is no decision to make;
        nothing is lost, because a save writes what undo can still take back
        byte-for-byte, and the status line says it happened.
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

    def edit_object(self, scope: Scope) -> None:
        """Open the entity editing screen on one object, or re-aim it.

        The far end of `MapCanvas.edit_object_requested`, which fires when an
        object is created or double-clicked. It also stands on its own as a
        method: an object is a thing a script, a menu or a future keyboard
        shortcut can ask to edit, and none of those should have to synthesise
        a mouse event to do it.

        ONE WINDOW, RE-AIMED. A window per object would pile up look-alike
        windows over one map, each holding a scope an undo can invalidate
        under it -- and re-aiming goes through `set_scope`, which commits the
        field the author was typing in before it throws the form away.

        `Qt.WA_DeleteOnClose` is deliberately NOT set, which is the opposite
        of the tile importer's answer to the same question. That one is
        opened, used and dismissed; this is closed and reopened constantly
        while an author works down a row of entities, and rebuilding the
        whole form for each is work with nothing to show for it.
        """
        if scope.kind != "object":
            self.report(f"{scope} is not an object", key="edit_object",
                        scope=scope,
                        fix="double-click an object on an object layer")
            return
        self.clear("edit_object")
        if self.object_editor is None:
            self.object_editor = ObjectEditor(self.session, scope, self)
            self.object_editor.command_requested.connect(self.run)
            # The entity screen names a script; this window opens it. The
            # screen does not open a window of its own, for the same reason
            # the canvas does not: one owner per top-level window, and that
            # owner is here.
            self.object_editor.script_requested.connect(self.open_script)
        else:
            self.object_editor.set_scope(scope)
        self.object_editor.show()
        self.object_editor.raise_()
        self.object_editor.activateWindow()

    def open_script(self, script_id: str = "") -> None:
        """Open the event screen, on a script or on the list of them.

        ONE WINDOW, RE-AIMED, exactly as `edit_object` is and for the same
        reason: a window per script is a pile of look-alike windows over
        one library, each holding an id that an undo can invalidate under
        it.

        `script_id` of `""` is not a missing argument -- it is the menu
        entry, which opens the screen with nothing picked, where the empty
        state says what a script IS and offers to make one. That is the
        screen an author who has never written one meets first, and it is
        the one worth getting right.
        """
        wanted = str(script_id or "")
        if self.script_editor is None:
            self.script_editor = ScriptEditor(self.session, wanted, self)
            self.script_editor.command_requested.connect(self.run)
        elif wanted:
            self.script_editor.set_script(wanted)
        else:
            self.script_editor.refresh()
        self.script_editor.show()
        self.script_editor.raise_()
        self.script_editor.activateWindow()

    def add_tileset(self) -> None:
        """Open the tile importer on the current map, without blocking it.

        NON-MODAL, and reopened rather than duplicated. Selecting a region
        is something an author does several times off one sheet, and each
        one wants a look at the map it is going into -- a dialog that owned
        the whole window would make "add four regions" four round trips
        through a menu.
        """
        try:
            document = self.session.project.map(self.map_name)
        except Exception as exc:                                # noqa: BLE001
            self.report(f"cannot read map:{self.map_name}: {exc}",
                        key="add_tileset")
            return
        if self.tileset_import is not None:
            self.tileset_import.raise_()
            self.tileset_import.activateWindow()
            return
        view = TilesetImportDialog.open_for(
            os.path.dirname(document.path),
            on_import=self.import_tileset,
            tile_width=document.tile_width, tile_height=document.tile_height,
            existing_names=document.tileset_names(),
            next_gid=document.next_tileset_firstgid(), parent=self)
        self.tileset_import = view
        # BOTH signals. `finished` fires the moment it closes, which is what
        # makes reopening deterministic; `destroyed` is the backstop for a
        # window torn down some other way. A stale pointer here would make
        # the next Add raise a window Qt has already deleted.
        view.finished.connect(self.__forget_tileset_import)
        view.destroyed.connect(self.__forget_tileset_import)

    def __forget_tileset_import(self, *_args) -> None:
        self.tileset_import = None

    def __refresh_tileset_import(self) -> None:
        """Tell the open importer what the map holds after this command.

        Undo is why this is pushed rather than remembered: taking an import
        back frees its name and its gid range again, and a view holding its
        own tally would refuse the author the name they had just released.
        """
        document = self.session.project.map(self.map_name)
        self.tileset_import.known_names(
            document.tileset_names(),
            next_gid=document.next_tileset_firstgid())

    def import_tileset(self, request) -> None:
        """One Add from the importer, as a command.

        The crop -- when there is one -- is already on disk by the time this
        runs; see `TilesetImportDialog.commit`. All that is left is the
        declaration, which is undoable, and telling the view the name is
        taken so its next region is offered a fresh one.
        """
        if not self.run(Command("map.tileset.add",
                                Scope.of(("map", self.map_name)),
                                request.command_args())):
            return
        cut = " (cropped)" if request.cropped else ""
        self.notify(f"declared {request.name!r} — {request.tile_count} "
                    f"tiles are now in the palette{cut}", seconds=8)

    def tileset_facts(self, name: str) -> TilesetFacts:
        """What the map knows about one tileset, for the palette's header menu.

        Asked when that menu opens and never on the refresh path: `placed`
        walks every cell of every tile layer plus every `<object gid=>`, and
        paying for that after each stroke would be a scan nobody asked for.

        Raises rather than answering with a zero. The palette catches it and
        greys the entries that needed the number -- "no headroom, nothing
        placed" is the shape of wrong answer that deletes painted cells.
        """
        document = self.session.project.map(self.map_name)
        ref = document.tileset(name)
        headroom = document.tileset_headroom(name)
        # Derived from the document's OWN number rather than re-walking the
        # ranges: `tileset_headroom` stops at the lowest firstgid above this
        # one, so that firstgid is exactly where the room runs out.
        ceiling = ref.last_gid + headroom + 1
        above = [other for other in document.tilesets()
                 if other.first_gid == ceiling]
        blocked_by = (f"{above[0].name or above[0].source or 'the tileset'} "
                      f"at gid {ceiling}") if above else ""

        per_layer: dict[str, int] = {}
        for layer_name, _x, _y, _gid in document.tiles_using_tileset(name):
            per_layer[layer_name] = per_layer.get(layer_name, 0) + 1
        for layer_name, _oid, _gid in document.objects_using_tileset(name):
            per_layer[layer_name] = per_layer.get(layer_name, 0) + 1

        # The shapes `MapDocument.grow_tileset` refuses outright, each
        # asked as an attribute rather than by trying it: they are properties
        # of the DECLARATION, they never change while the menu is open, and
        # the alternative is offering a control whose only outcome is that
        # refusal. The verb still owns the real one, with the better
        # sentence, for anything that reaches it.
        if ref.is_external:
            refusal = "its sheet and count live in a .tsx"
        elif ref.margin or ref.spacing:
            refusal = (f"margin={ref.margin} spacing={ref.spacing}; the three "
                       "readers only agree on a 0/0 grid")
        elif not ref.image_source:
            refusal = "it is a collection of images, not a grid"
        elif ref.columns <= 0:
            refusal = "it declares no columns, so there is no stride to grow by"
        else:
            refusal = ""

        return TilesetFacts(
            headroom=headroom,
            placed=sum(per_layer.values()),
            where=", ".join(f"{layer} x{count}"
                            for layer, count in sorted(per_layer.items())),
            blocked_by=blocked_by,
            growth_refusal=refusal)

    def tileset_command(self, name: str, verb: str, args: dict) -> None:
        """One whole-tileset edit from the palette's header menu.

        The same door `import_tileset` uses, and deliberately the same one:
        a refusal lands in Problems where it can be read, the edit lands in
        the history list as a verb, and undo takes it back.
        """
        if not self.run(Command(verb, Scope.of(("map", self.map_name)), args)):
            return
        told = {
            "map.tileset.rename": f"renamed {name!r} to {args.get('to')!r}",
            "map.tileset.grow": f"{name!r} now owns "
                                f"{args.get('tile_count')} tiles",
            "map.tileset.remove": f"removed {name!r} — one undo puts it back "
                                  f"with every <tile> child",
        }
        self.notify(told.get(verb, f"{verb} on {name!r}"), seconds=8)

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
        elif key == "collision_subcell":
            # The opposite of `grid_step` above, and deliberately: this one
            # DOES change which cell a click lands in, because the layer the
            # click is about to create is the layer being sized. It reaches
            # `paint_unit` and moves the grid, the ghost and the bounds
            # together or it moves none of them. Existing companions are
            # untouched -- they declare their own resolution and this is only
            # consulted for one that does not exist yet.
            self.canvas.collision_subcell = int(value)
            self.canvas.rebuild()
        elif key == "snap_objects":
            # The settings dialog's half of the same preference. It does NOT
            # go through `set_snap_objects`: the dialog has already stored the
            # value, and storing it again from here would be the second writer
            # this branch exists to avoid. The menu tick is put in step
            # without re-entering, because `setChecked` emits `toggled`.
            self.__apply_snap(bool(value))
            self.snap_action.blockSignals(True)
            self.snap_action.setChecked(bool(value))
            self.snap_action.blockSignals(False)
        # `ide` is read in `reveal`, and `confirm_response` in
        # `apply_response` and `__offer` -- both at the moment they matter,
        # so nothing has to happen here for them. (`confirm_response` was
        # read NOWHERE for as long as it existed: a preference the author
        # could tick that changed nothing at all.)
        #
        # `snap_objects` is the one preference with a control OUTSIDE this
        # dialog, which is why its branch echoes the tick as well as applying
        # the value: two controls that can disagree about one stored answer
        # are worse than one control in the wrong place.

    def set_snap_objects(self, on: bool) -> None:
        """Store the snap preference and apply it. The View menu's handler.

        THE ONLY WRITER. `__on_setting_changed` applies without storing,
        because the settings dialog has already stored what it is reporting;
        a second write there and a call to this from there would be two
        writers of one key, which is how the value a control shows and the
        value a canvas uses part company.
        """
        self.settings.set("snap_objects", bool(on))
        self.__apply_snap(bool(on))
        self.notify(f"objects {'snap to' if on else 'ignore'} the grid")

    def __apply_snap(self, on: bool) -> None:
        """Push it onto the mounted canvas.

        Written onto the canvas rather than read back off `self.settings` by
        the canvas, for the same reason as the other three view preferences:
        the store is the one source of the answer and the widget never
        becomes a second one. `__new_canvas` applies it to every canvas this
        window mounts, so switching maps carries it.
        """
        self.canvas.snap_objects = on
        self.canvas.rebuild()

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
        # HELD, not just applied: `__new_canvas` builds a canvas long after
        # this ran, and a canvas mounted by `&Maps` has no other way to come
        # up in the theme the rest of the window is already wearing.
        self.canvas_background = theme_module.CANVAS_BACKGROUND.get(concrete)
        self.canvas.set_background(self.canvas_background)
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
            # itself, so this is only reachable by calling it directly.
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
        # A report, not a dialog: the row stays until the response lands.
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
        path = self.choose_file(self, "Apply a response", start,
                                "JSON Lines (*.jsonl);;All files (*)")
        if path:
            self.apply_response(path)

    def apply_response(self, path: str) -> None:
        """Apply a responder's command list, after that bundle's own gate.

        THIS IS A SECOND DOOR, not a caller of `Session.apply_response` --
        measured, and it is why the scope gate lives inside `read_response`
        rather than in the session. A gate in `Session.apply_response`
        would have covered the tool path and left this one, the one the
        author actually clicks, wide open.

        TWO REFUSALS, SPELLED APART. A malformed file and a well-formed
        file that reached outside its bundle's declared scope are different
        facts, and the second used to be reported as "is not a readable
        response" -- wrong in the way that costs a reader an hour: the file
        IS readable, every line of it parsed, and what happened is that the
        bundle promised one address and the answer touched another.
        `BundleContract.enforce` has already written the whole explanation,
        the ways forward included, so it is passed through rather than
        summarised. #TAG:a_refusal_is_not_a_parse_error
        """
        try:
            commands = read_response(path)
        except PyoneerScopeRefusedError as exc:                 # noqa: BLE001
            # NOTHING WAS APPLIED. The contract refuses the batch
            # before its first command runs, so there is no partial
            # edit here and nothing for the author to undo.
            self.report(f"{os.path.basename(path)} was refused: "
                        f"{getattr(exc, 'message', str(exc))}",
                        key="response",
                        detail=f"{type(exc).__name__}: {exc}\n{path}")
            return
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

        A filesystem watcher fires this, with no gesture from the author, so
        it must never open a dialog: one would land on top of an in-progress
        stroke and take the mouse button with it. It announces itself
        instead. `confirm_response` unticked means the author already said
        "apply as soon as it arrives", which is the one case where arriving
        is enough to act on.
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
