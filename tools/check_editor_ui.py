"""Drive the editor's Qt window offscreen and assert it holds together.

Not a screenshot test. It builds the real window against a throwaway copy
of the real map, drives the real signal paths, and asserts what would
actually break:

  * every panel builds and refreshes without raising
  * a canvas DRAG is one transaction, not one per cell -- the property that
    makes undo usable
  * the terrain tool re-tiles cells the cursor never touched
  * selecting anything re-aims the hierarchy, the inspector and the prompt
  * a click on the TILE palette means a brush in tiles mode and a baked
    collision mask in collision mode -- the one surface that reaches
    `map.tileset.mask.set`, which shipped reachable from nothing -- and the
    palette draws which tiles are already masked, including the one whose
    glyph is deliberately blank
  * a rejected edit reaches the user as a message, not a traceback
  * a response comes back through the same door a click does
  * THE SELECTION NAMES AN OBJECT, NOT AN ID. Ids are recycled -- the
    document rolls `nextobjectid` back so that add-then-remove is
    byte-exact -- so a selection re-resolved by id lands on a DIFFERENT
    object, and Delete removed one the author had never clicked. Both
    halves: a recycled id selects and deletes NOTHING, and a selection
    that is still the same object still deletes, still survives a move
    and still survives painting a tile
  * Delete refuses on a HIDDEN layer, where nothing is drawn selected and
    nothing can be clicked -- and still deletes when the layer comes back
  * the REAL right-click opener is driven, unstubbed, and asserted to
    return with its menu still on screen: `QMenu.exec` does not return
    until the menu closes, and a check that only ever drove the stubbed
    seam could not see that (law 13)

AND FOUR PROPERTIES ABOUT DIALOGS
---------------------------------
A box with an OK button, opened on a routine path to say that nothing
happened, is the shape this section is against. Each property is asserted in
BOTH directions, because the dominant failure in this tree is proving one
half of an invariant:

  * a routine outcome opens NO dialog -- and every dialog is recorded
    rather than silenced, so "nothing opened" is a measurement. A modal on
    a routine path is also how this suite once hung for 40+ minutes with
    zero output (law 13), so this is the check protecting itself.
  * the ONE confirmation that survives is the one undo cannot reach, and
    it is asserted to still be asked AND to be obeyed when refused.
  * a control that cannot act is disabled WITH a reason -- asserted live
    and greyed, since only asserting the greyed half is how the same bug
    survived in the Database the first time.
  * nothing silently does nothing: a refusal that the author cannot see is
    the defect, so the refusals are read back off the status bar and out of
    the Problems dock.

Skips cleanly when PySide6 is not installed.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import dataclasses
import importlib.util
import ast
import inspect
import textwrap
import json
import os
import shutil
import sys
import tempfile

if importlib.util.find_spec("PySide6") is None:
    print("SKIP  PySide6 is not installed "
          "(pip install -r editor/requirements.txt)")
    sys.exit(0)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt                          # noqa: E402
from PySide6.QtGui import QAction, QKeyEvent, QMouseEvent                # noqa: E402
from PySide6.QtWidgets import (                                         # noqa: E402
    QApplication,
    QGraphicsLineItem,
    QMessageBox,
    QWidget,
)

from editor.core import genre as genre_module                          # noqa: E402
from editor.core.autotile import TerrainSet                             # noqa: E402
from editor.core.collision import NO_DATA, companion_pairs              # noqa: E402
from editor.core.commands import Command                                # noqa: E402
from editor.core.layers import BLOCK_ALL, PASS_ALL                      # noqa: E402
from editor.core.paint import EditMode, Stamp, Tool, grid_lines         # noqa: E402
from editor.core.scope import Scope                                     # noqa: E402
from editor.core.session import Session                                 # noqa: E402
from scripts.game.behavior.base import BEHAVIORS                        # noqa: E402
from editor.ui import ask as ask_module                                 # noqa: E402
from editor.ui.actions_panel import NOT_WIRED                           # noqa: E402
from editor.ui.collision_view import (                                  # noqa: E402
    BRUSH_DOMAIN,
    MASK_DOMAIN,
    MaskPalette,
)
import editor.ui.canvas as canvas_module                              # noqa: E402
import editor.ui.main_window as main_window_module                      # noqa: E402
from editor.ui.main_window import (                                      # noqa: E402
    LAYOUT_KEY,
    TILES_AS_MASK_TARGET,
    TILES_TITLE,
    EditorWindow,
)

REPO = _bootstrap.REPO_ROOT
failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<56} got={got} want={want}")
    if not ok:
        failures.append(label)


# RECORD every modal, do not merely silence it. Silencing proves nothing in
# either direction -- a box that opens is invisible to the suite, and so is a
# box that stops opening. These four lists are the instrument for "this path
# asked nothing", which is the stronger of the two claims.
warned: list[str] = []
asked: list[str] = []
informed: list[str] = []

#: Qt wrappers this file must not let go of. See `menu_entry`, which is
#: where the one measured reason is written down.
held: list = []


def _body(args) -> str:
    return str(args[2]) if len(args) > 2 else ""


def _record(bucket, answer=None):
    def stub(*a, **k):
        bucket.append(_body(a))
        return answer
    return staticmethod(stub)


QMessageBox.warning = _record(warned)
QMessageBox.critical = _record(warned)
QMessageBox.information = _record(informed)
QMessageBox.question = _record(asked, QMessageBox.Yes)


def modals() -> list[str]:
    """Every dialog opened since the last clear, of any kind."""
    return warned + asked + informed


def no_modals() -> None:
    for bucket in (warned, asked, informed):
        bucket.clear()


class FakeLayout:
    """Stands in for the QSettings the window keeps its dock layout in.

    Two reasons, and they pull in opposite directions, which is why the seam
    exists at all. A real store would be WRITTEN on every window this file
    closes, editing the developer's own editor. And it would be READ on
    every window this file opens, so "are the two palettes side by side"
    would answer with however that developer last dragged a panel -- a check
    whose verdict depends on the machine is not a check.

    Deliberately keeps the blob as the QByteArray `saveState` returns, the
    way QSettings does: stringifying it is how a layout round-trips into
    something `restoreState` politely refuses.
    """

    def __init__(self):
        self.data = {}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value


#: Every `EditorWindow` in this file, including the ones built inside a
#: section, goes to a throwaway store. Installed at module scope because the
#: restore happens inside `__init__` and there is no later seam onto it.
LAYOUTS = FakeLayout()
main_window_module.layout_store = lambda: LAYOUTS


class FakeStore:
    """Stands in for QSettings, and returns everything as TEXT the way the
    ini backend does -- which is exactly how a boolean preference silently
    stops working if nothing coerces it.

    Also used to keep this check away from the REAL preferences: the window
    reads `confirm_response` now, and a check that wrote the developer's
    actual QSettings to exercise it would be editing the machine it runs on.
    """

    def __init__(self):
        self.data = {}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = str(value)

    def remove(self, key):
        self.data.pop(key, None)


workspace = tempfile.mkdtemp(prefix="pyoneer_editor_ui_")
application = QApplication.instance() or QApplication([])

# --------------------------------------------------------------------------
print("Selection navigation semantics, with no window and no map")
# --------------------------------------------------------------------------
# Deliberately synthesised scopes. Asserting against map:test/layer:Floor
# would assert what the author has painted, and would route through
# __on_selection -> canvas.set_active_layer() for a layer that may not exist.
from editor.ui.selection import Selection                                # noqa: E402

moves: list[str] = []
navigator = Selection(Scope.parse("map:m/layer:l/object:1"))
navigator.changed.connect(lambda scope: moves.append(str(scope)))

expect("select_parent climbs one segment",
       (navigator.select_parent(), str(navigator.scope)), (True, "map:m/layer:l"))
expect("select_parent stops at the root",
       [navigator.select_parent(), navigator.select_parent(),
        navigator.select_parent()], [True, False, False])
expect("back returns to the previous scope",
       (navigator.back(), str(navigator.scope)), (True, "map:m/layer:l"))
expect("back walks the whole history then stops",
       [navigator.back(), navigator.back()], [True, False])
# Two successful select_parent calls and two successful back calls. The four
# refusals above must emit nothing -- a panel that rebuilds on a refused
# navigation is the bug this counts.
expect("changed fired once per real move, never on a refusal",
       len(moves), 4)


def mouse_px(window, kind, px, button=Qt.LeftButton, buttons=None,
             modifiers=Qt.NoModifier):
    """One mouse event at an exact SCENE PIXEL.

    `mouse` below aims at cell centres, which is right for painting and
    useless for dragging an object: a whole number of cells of travel
    lands on a tile boundary whether the canvas snapped it or not, so a
    cell-addressed drag cannot tell snapped from freeflow apart (law 5).
    Pixels are the only coordinate that can.
    """
    canvas = window.canvas
    point = QPointF(canvas.mapFromScene(px[0], px[1]))
    down = buttons if buttons is not None else button
    event = QMouseEvent(kind, point, button, down, modifiers)
    {QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
     QEvent.Type.MouseMove: canvas.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent,
     QEvent.Type.MouseButtonDblClick: canvas.mouseDoubleClickEvent}[kind](event)


def mouse(window, kind, cell, button=Qt.LeftButton, buttons=None):
    """Drive the canvas the way a real mouse would, in CELL coordinates."""
    canvas = window.canvas
    mouse_px(window, kind,
             (cell[0] * canvas.tile_width + canvas.tile_width / 2,
              cell[1] * canvas.tile_height + canvas.tile_height / 2),
             button, buttons)


def drag(window, cells, button=Qt.LeftButton):
    mouse(window, QEvent.Type.MouseButtonPress, cells[0], button)
    for cell in cells[1:]:
        mouse(window, QEvent.Type.MouseMove, cell, Qt.NoButton, button)
    mouse(window, QEvent.Type.MouseButtonRelease, cells[-1], button)
    application.processEvents()


def drag_px(window, start, end, *, modifiers=Qt.NoModifier):
    """Press, travel, release -- in scene pixels, with live modifiers.

    The press carries NO modifiers even when the drag does, and that is
    not a convenience: alt+press is the tile picker, so ALT can only ever
    be taken up once the button is already down. Driving it any other way
    would be driving a gesture a hand cannot make.
    """
    mouse_px(window, QEvent.Type.MouseButtonPress, start, Qt.LeftButton)
    mouse_px(window, QEvent.Type.MouseMove, end, Qt.NoButton, Qt.LeftButton,
             modifiers)
    mouse_px(window, QEvent.Type.MouseButtonRelease, end, Qt.LeftButton, None,
             modifiers)
    application.processEvents()


def double_click_px(window, px):
    """The FOUR events Qt really sends for a double-click.

    Press, release, DoubleClick, release. Driving only the third would
    prove the handler works and miss the whole risk, which is that the
    first press has already run the single-click path -- on bare ground it
    has already PLACED an object, and a handler that placed another would
    litter one duplicate per double-click.
    """
    mouse_px(window, QEvent.Type.MouseButtonPress, px)
    mouse_px(window, QEvent.Type.MouseButtonRelease, px)
    mouse_px(window, QEvent.Type.MouseButtonDblClick, px)
    mouse_px(window, QEvent.Type.MouseButtonRelease, px)
    application.processEvents()


def place_object(window, cell):
    """THE GESTURE THAT PLACES AN OBJECT, now that a single click does not.

    A whole double-click, driven as Qt really delivers one -- press,
    release, DoubleClick, release -- because that is the only way to put an
    object on a map by hand any more, and a check that placed by writing
    `map.object.add` would keep passing after the gesture stopped working.

    The object editor the gesture opens is CLOSED again. It is not what the
    sections below are measuring, and `refresh_all` rebuilds a visible one
    on every command that follows -- so leaving it up would put an unrelated
    form on the path of every assertion after the first placement.
    """
    canvas = window.canvas
    double_click_px(window,
                    (cell[0] * canvas.tile_width + canvas.tile_width / 2,
                     cell[1] * canvas.tile_height + canvas.tile_height / 2))
    if window.object_editor is not None:
        window.object_editor.close()
    application.processEvents()


def select_layer(window, name):
    window.selection.select(
        Scope.of(("map", window.map_name), ("layer", name)))
    application.processEvents()

# --------------------------------------------------------------------------
# The tile-mask fixture, and the two palette clicks
# --------------------------------------------------------------------------
# Its own map, because baking a tile mask WRITES: a `.blitmask` beside the
# .tmx and a `pyoneer_collision` property on the `<tileset>`. Doing that to a
# copy of `data/maps/test.tmx` would pin the author's tileset names and their
# geometry into this file (law 4).
#
# Two columns and four tiles, so a tile id, a grid position and a gid are all
# small enough to name: gid 2 is column 1 of row 0.

MASKED_GID = 2
MASKED_TMX = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" compressionlevel="-1" width="4" height="3" \
tilewidth="16" tileheight="16" infinite="0" nextlayerid="2" nextobjectid="1">
 <tileset firstgid="1" name="Art" tilewidth="16" tileheight="16" \
tilecount="4" columns="2">
  <image source="art.png" width="32" height="32"/>
 </tileset>
 <layer id="1" name="Floor" width="4" height="3">
  <data encoding="csv">
2,0,0,1,
0,0,2,0,
1,0,0,0
</data>
 </layer>
</map>
"""


def pick_tile(window, tileset, column, row):
    """Press and release on one cell of the TILE palette, as a mouse does.

    Addressed by TILESET NAME, because the palette stacks every sheet the
    map declares into one surface: a bare row and column would name a
    different tile the moment another tileset is declared above it.
    """
    surface = window.palette.surface
    point = window.palette.tile_point(tileset, column, row)
    for kind, handler in ((QEvent.Type.MouseButtonPress,
                           surface.mousePressEvent),
                          (QEvent.Type.MouseButtonRelease,
                           surface.mouseReleaseEvent)):
        handler(QMouseEvent(kind, point, Qt.LeftButton, Qt.LeftButton,
                            Qt.NoModifier))
    application.processEvents()


def pick_mask(window, mask):
    """Press on one swatch of the MASK palette, addressed by its value."""
    surface = window.mask_palette.surface
    step = window.mask_palette.cell + 6
    # BRUSH_DOMAIN, not MASK_DOMAIN: the palette lays out the seventeen
    # storable masks AND the no-opinion chip, and the chip is the swatch a
    # check most needs to be able to press.
    index = BRUSH_DOMAIN.index(mask)
    column, row = index % MaskPalette.COLUMNS, index // MaskPalette.COLUMNS
    point = QPointF(column * step + step / 2, row * step + step / 2)
    surface.mousePressEvent(
        QMouseEvent(QEvent.Type.MouseButtonPress, point, Qt.LeftButton,
                    Qt.LeftButton, Qt.NoModifier))
    application.processEvents()


def sheet_cells(palette, tileset):
    """Each tile's own patch of one DRAWN sheet, keyed by grid position.

    The composited pixmap rather than a widget grab, and that is the whole
    reason this helper exists: the selection rectangle is painted OVER the
    sheet and moves on every pick, so a grab would report "the palette
    changed" for the click itself and never for the badge -- an assertion
    that cannot fail, which is not an assertion.
    """
    image = palette.surface._PaletteSurface__pixmap.toImage()
    section = palette.section(tileset)
    return {(column, row): image.copy(
                section.rect(column, row).toRect())
            for row in range(section.rows)
            for column in range(section.columns)}




try:
    os.makedirs(os.path.join(workspace, "config"))
    os.makedirs(os.path.join(workspace, "data", "maps"))
    shutil.copy2(os.path.join(REPO, "data", "maps", "test.tmx"),
                 os.path.join(workspace, "data", "maps", "test.tmx"))
    with open(os.path.join(workspace, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [{"name": "test", "identifier": "test",
                             "file": "data/maps/test.tmx"}]}, handle)
    with open(os.path.join(workspace, "data", "maps", "test.tmx"), "rb") as handle:
        ORIGINAL = handle.read()

    session = Session.open(workspace, genre_id="topdown_rpg")

    # ----------------------------------------------------------------
    print("the window and every panel build")
    # ----------------------------------------------------------------
    window = EditorWindow(session)
    # Before anything reads a preference: `confirm_response` is live now, and
    # a check that toggled the real QSettings would be editing the machine.
    from editor.core.settings import EditorSettings as _Settings   # noqa: E402
    window.settings = _Settings(FakeStore())
    window.show()
    application.processEvents()
    expect("it opened the map", window.map_name, "test")
    expect("the canvas composited something",
           len(window.canvas.scene().items()) > 0, True)
    # Derived from the map, not counted by hand: the author adds a tileset the
    # moment he paints collision, and a literal here goes red for that while
    # saying nothing about the palette.
    expect("the tile palette found every tileset the map declares",
           len(window.canvas.atlas.entries),
           len(window.session.project.map(window.map_name).tileset_names()))
    expect("it picked a paintable layer to start on",
           window.canvas.active_layer, "Paralax")

    # ----------------------------------------------------------------
    print()
    print("the collision swatches are BESIDE the tiles, never behind them")
    # ----------------------------------------------------------------
    # The complaint this section pins: collision should be visible on screen
    # as a palette selector, and it was tabified onto the Tiles dock, so it
    # was one click away and zero pixels wide. A tab is a control that hides
    # its own contents.
    #
    # TWO INSTRUMENTS, and each is proved to answer BOTH ways in this same
    # section, because a measurement that only ever returns the wanted answer
    # is the vacuous half this suite keeps paying for.

    def tabbed_with(dock):
        """Which docks share a tab bar with this one, by objectName."""
        return sorted(other.objectName()
                      for other in window.tabifiedDockWidgets(dock))

    def painted(widget):
        """Does this widget occupy pixels RIGHT NOW.

        Not `isVisible()`: a dock sitting behind a tab answers True to that,
        which is exactly the state being ruled out here. `visibleRegion` is
        the area Qt would repaint, and it is empty for the loser of a tab.
        """
        return not widget.visibleRegion().isEmpty()

    expect("the mask palette exists at all", window.mask_dock.objectName(),
           "Collision")
    expect("BOTH palettes are painted at once, with no mode change",
           (painted(window.palette), painted(window.mask_palette)),
           (True, True))
    expect("...and that is measured in tiles mode, so nothing raised it",
           window.canvas.mode, EditMode.TILES)
    expect("neither palette shares a tab bar with anything",
           (tabbed_with(window.palette_dock), tabbed_with(window.mask_dock)),
           ([], []))

    # THE OTHER HALF OF BOTH INSTRUMENTS, on the docks that ARE tabbed on
    # purpose. Without these two lines "not tabbed" and "painted" could both
    # be constants and the section above would pass on a window that stacked
    # every panel into one tab.
    expect("the instrument SEES a tab bar where one is intended",
           tabbed_with(window.inspector), ["Actions", "Behaviors"])
    expect("...and SEES that the loser of that tab paints nothing",
           (painted(window.inspector), painted(window.behaviors)),
           (True, False))

    # The precondition for remembering any of it: Qt keys saved dock state by
    # `objectName`, and an unnamed dock is dropped from the blob in silence.
    expect("every dock is named, which is what a layout is stored by",
           [d.objectName() for d in window.docks
            + (window.palette_dock, window.mask_dock) if not d.objectName()],
           [])

    # ----------------------------------------------------------------
    print()
    print("an arranged layout survives the next launch")
    # ----------------------------------------------------------------
    # Part two of the same complaint: splitting the docks is only an opinion
    # about where they START. The author drags them where he wants them, and
    # until now the next launch threw that away.
    #
    # Driven with a store of its own so the assertions below cannot be
    # answered by a blob some earlier section left behind.
    arranged = FakeLayout()
    main_window_module.layout_store = lambda: arranged
    try:
        first = EditorWindow(session)
        first.settings = _Settings(FakeStore())
        first.show()
        application.processEvents()
        expect("a window with nothing stored splits the two palettes",
               sorted(o.objectName()
                      for o in first.tabifiedDockWidgets(first.palette_dock)),
               [])
        expect("...and stores nothing before it closes",
               list(arranged.data), [])

        # THE AUTHOR ARRANGES IT: he tabs the two palettes himself. That is
        # his to do -- the split is a default, not a rule -- and it is the
        # arrangement most obviously destroyed by a forgetful window.
        first.tabifyDockWidget(first.palette_dock, first.mask_dock)
        first.mask_dock.raise_()
        application.processEvents()
        first.confirm = lambda *a, **k: False
        first.close()
        application.processEvents()
        expect("closing writes the arrangement down", list(arranged.data),
               [LAYOUT_KEY])

        second = EditorWindow(session)
        second.settings = _Settings(FakeStore())
        second.show()
        application.processEvents()
        expect("THE NEXT LAUNCH BRINGS IT BACK",
               sorted(o.objectName()
                      for o in second.tabifiedDockWidgets(second.palette_dock)),
               ["Collision"])
        expect("...and says nothing about it, because nothing went wrong",
               second.problems.notice_keys(), [])
        second.confirm = lambda *a, **k: False
        second.close()
        second.deleteLater()
        first.deleteLater()
        application.processEvents()

        # AND THE FAILING HALF. A blob Qt will not read is the one case where
        # falling back silently would be indistinguishable from the feature
        # never having been written -- the author arranges a window, it comes
        # back wrong, and nothing says why.
        arranged.data[LAYOUT_KEY] = b"this is not a Qt window state"
        broken = EditorWindow(session)
        broken.settings = _Settings(FakeStore())
        broken.show()
        application.processEvents()
        expect("a layout that will not restore falls back to the default",
               sorted(o.objectName()
                      for o in broken.tabifiedDockWidgets(broken.palette_dock)),
               [])
        expect("...and SAYS SO, rather than looking like a fresh machine",
               broken.problems.notice_keys(), ["layout"])
        expect("...in the status bar too",
               "layout could not be restored" in
               broken.statusBar().currentMessage(), True)
        expect("...and it opened no dialog to say it", modals(), [])
        broken.confirm = lambda *a, **k: False
        broken.close()
        broken.deleteLater()
        application.processEvents()
    finally:
        main_window_module.layout_store = lambda: LAYOUTS
    no_modals()

    # ----------------------------------------------------------------
    print()
    print("navigation is reachable from the menu, not just from the API")
    # ----------------------------------------------------------------
    actions = window.findChildren(QAction)
    shortcuts = [a.shortcut().toString() for a in actions if not a.shortcut().isEmpty()]
    expect("exactly one action carries Alt+Up", shortcuts.count("Alt+Up"), 1)
    expect("exactly one action carries Alt+Left", shortcuts.count("Alt+Left"), 1)
    # A shortcut bound twice is ambiguous and Qt silently fires neither.
    expect("no shortcut is bound twice",
           sorted({s for s in shortcuts if shortcuts.count(s) > 1}), [])

    up = next(a for a in actions if a.shortcut().toString() == "Alt+Up")
    left = next(a for a in actions if a.shortcut().toString() == "Alt+Left")

    # Scopes the CHECK creates, so this asserts the wiring and says nothing
    # about which layers the author has painted.
    window.selection.select(Scope.parse("map:m/layer:l/object:1"))
    up.trigger()
    application.processEvents()
    expect("triggering Alt+Up climbed to the parent",
           str(window.selection.scope), "map:m/layer:l")
    left.trigger()
    application.processEvents()
    expect("triggering Alt+Left went back",
           str(window.selection.scope), "map:m/layer:l/object:1")

    # ----------------------------------------------------------------
    print()
    print("the hierarchy shows the authored tree, groups included")
    # ----------------------------------------------------------------
    tree = window.hierarchy.tree
    labels, addressable = [], []
    stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        labels.append(item.text(0))
        raw = item.data(0, Qt.UserRole)
        if raw:
            addressable.append(raw)
        stack.extend(item.child(i) for i in range(item.childCount()))
    expect("both Tiled groups are shown as structure",
           sum(1 for text in labels if text.startswith("▾")), 2)
    expect("but neither is addressable",
           any("layer:Graphic" in a or "layer:Entity" in a
               for a in addressable), False)
    # Tile layers AND object layers are addressable; the two Tiled groups
    # above them are structure and are not.
    _doc = window.session.project.map(window.map_name)
    # Minus the collision companions. They hold masks rather than art, and
    # the hierarchy folds each one into a badge on the layer that declares
    # it -- #TAG:companion_folded_into_its_layer. DERIVED from
    # `companion_pairs`, the same function the fold is derived from, so this
    # still says nothing about which layers the author has painted.
    _companions = {companion for _art, companion in companion_pairs(_doc)}
    # `/object:` rows are addressable as well and are NOT layers, so they
    # are excluded by scope shape rather than by counting on the fixture
    # holding no objects -- which is a claim about the map (law 4), and one
    # that stopped being true the day someone authored one into it.
    expect("every real layer is addressable, and only those",
           sum(1 for a in addressable
               if "/layer:" in a and "/object:" not in a),
           len(_doc.tile_layer_names()) + len(_doc.object_layer_names())
           - len(_companions))
    expect("and a companion has no row at all, not merely no address",
           sorted(c for c in _companions
                  if any(c in text for text in labels)), [])

    # ----------------------------------------------------------------
    print()
    print("one selection re-aims every panel that inspects")
    # ----------------------------------------------------------------
    select_layer(window, "Floor")
    expect("the canvas knows what it is painting",
           window.canvas.active_layer, "Floor")
    expect("the hierarchy followed",
           str(window.hierarchy.scope), "map:test/layer:Floor")
    expect("the inspector followed",
           str(window.inspector.scope), "map:test/layer:Floor")
    expect("and its prompt strip did too",
           str(window.inspector.strip.scope()), "map:test/layer:Floor")
    expect("Problems did NOT follow -- it is about the project",
           str(window.problems.scope), "project")

    # ----------------------------------------------------------------
    print()
    print("a canvas DRAG is one transaction, not one per cell")
    # ----------------------------------------------------------------
    layer = session.project.map("test").tile_layer("Floor")
    before = [layer.get_tile(x, 5) for x in range(3, 9)]
    window.canvas.stamp = Stamp.single(77)
    window.canvas.tool = Tool.BRUSH
    drag(window, [(3, 5), (5, 5), (8, 5)])
    expect("every cell along the drag was painted",
           [session.project.map("test").tile_layer("Floor").get_tile(x, 5)
            for x in range(3, 9)], [77] * 6)
    expect("as a SINGLE transaction", len(session.history()), 1)
    expect("which one undo takes back", True, True)
    window.undo()
    expect("the row is restored",
           [session.project.map("test").tile_layer("Floor").get_tile(x, 5)
            for x in range(3, 9)], before)
    expect("byte-identical", session.project.map("test").to_bytes() == ORIGINAL,
           True)

    print()
    print("a fast drag leaves no gaps")
    drag(window, [(20, 20), (26, 26)])
    painted = [(x, y) for x in range(20, 27) for y in range(20, 27)
               if session.project.map("test").tile_layer("Floor").get_tile(x, y) == 77]
    expect("the diagonal is contiguous, not two dots", len(painted), 7)
    window.undo()

    print()
    print("right-drag erases, and also as one step")
    drag(window, [(30, 30), (33, 30)], button=Qt.RightButton)
    expect("the cells were cleared",
           {session.project.map("test").tile_layer("Floor").get_tile(x, 30)
            for x in range(30, 34)}, {0})
    expect("one transaction", len(session.history()), 1)
    window.undo()
    expect("byte-identical again",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("the BRUSH has a footprint of its own, and it is still one undo")
    # ----------------------------------------------------------------
    # On a layer this check creates, so nothing here asserts what the author
    # has painted -- only what a press does.
    window.run(Command("map.layer.add", Scope.of(("map", "test")),
                       {"name": "SizeProbe", "kind": "tile"}))
    select_layer(window, "SizeProbe")
    window.canvas.tool = Tool.BRUSH
    window.canvas.stamp = Stamp.single(77)

    def probe():
        return session.project.map("test").tile_layer("SizeProbe")

    def painted(gid=77):
        layer = probe()
        return {(x, y) for y in range(layer.height) for x in range(layer.width)
                if layer.get_tile(x, y) == gid}

    window.canvas.brush_size = 1
    before_stroke = len(session.history())
    drag(window, [(20, 20)])
    expect("size 1 paints exactly the cell clicked", painted(), {(20, 20)})
    expect("as one transaction", len(session.history()) - before_stroke, 1)
    window.undo()

    window.canvas.brush_size = 3
    before_stroke = len(session.history())
    drag(window, [(20, 20)])
    expect("size 3 paints exactly 9 cells", len(painted()), 9)
    expect("centred on the cell clicked, not hung off its corner",
           painted(), {(x, y) for x in (19, 20, 21) for y in (19, 20, 21)})
    expect("and a 3x3 press is STILL one transaction",
           len(session.history()) - before_stroke, 1)
    window.undo()
    expect("which one undo takes back completely", painted(), set())

    # A DRAG at size 3, which is the property easiest to break: the stroke
    # accumulates a wide trail and must still commit once.
    before_stroke = len(session.history())
    drag(window, [(30, 30), (33, 30), (36, 30)])
    expect("a size-3 drag sweeps a 3-wide trail", len(painted()), 3 * 9)
    expect("and commits as a single transaction",
           len(session.history()) - before_stroke, 1)
    expect("with every cell written once, not once per mouse move",
           len(session.history()[-1].commands[-1].args["tiles"]), 27)
    window.undo()
    window.canvas.brush_size = 1

    print()
    print("the size control is lit or greyed for a measured reason")
    # Both halves: live for the tools a footprint reaches, greyed for the
    # three that read a stamp as a repeating pattern and would ignore it.
    for tool, want in ((Tool.BRUSH, True), (Tool.ERASER, True),
                       (Tool.AUTOTILE, True), (Tool.FILLED_RECT, False),
                       (Tool.RECTANGLE, False), (Tool.FILL, False),
                       (Tool.PICKER, False)):
        window.tool_actions[tool].trigger()
        application.processEvents()
        expect(f"{tool.value}: spinner enabled == {want}",
               window.size_spin.isEnabled(), want)
    window.tool_actions[Tool.FILLED_RECT].trigger()
    expect("a greyed control says WHY, rather than sitting there dead",
           "no footprint" in window.size_spin.toolTip(), True)
    window.tool_actions[Tool.BRUSH].trigger()
    expect("and a live one names the unit in pixels",
           f"{window.canvas.paint_width}px" in window.size_spin.toolTip(), True)

    # A greyed control must also be INERT, not merely un-clickable: set the
    # size behind its back and prove the filled rectangle ignores it.
    window.tool_actions[Tool.FILLED_RECT].trigger()
    window.canvas.brush_size = 3
    drag(window, [(50, 50), (52, 51)])
    expect("a filled rectangle ignores the footprint entirely",
           painted(), {(x, y) for x in (50, 51, 52) for y in (50, 51)})

    # The half that is NOT visible through a filled rectangle, because a
    # uniform footprint tiles to itself there and hides the difference. A
    # right-drag substitutes the eraser, which DOES take a footprint -- so
    # the gate has to read the SELECTED tool, or a greyed spinner would
    # silently resize a right-drag the author cannot see the size of.
    drag(window, [(51, 50)], button=Qt.RightButton)
    expect("a right-drag under a greyed size erases one cell, not nine",
           painted(), {(50, 50), (52, 50), (50, 51), (51, 51), (52, 51)})
    window.undo()
    window.undo()
    window.canvas.brush_size = 1
    window.tool_actions[Tool.BRUSH].trigger()

    print()
    print("the GRID setting changes what is drawn and NOTHING about a click")
    document = session.project.map("test")

    def grid_line_count():
        window.canvas.rebuild()
        application.processEvents()
        return len([item for item in window.canvas.scene().items()
                    if isinstance(item, QGraphicsLineItem)])

    window.canvas.show_grid = True
    window.canvas.grid_step = 1
    fine = grid_line_count()
    expect("step 1 draws every boundary of the map",
           fine, (document.width + 1) + (document.height + 1))
    window.canvas.grid_step = 4
    coarse = grid_line_count()
    expect("step 4 draws strictly fewer lines", coarse < fine, True)
    expect("and exactly the boundaries paint.grid_lines names",
           coarse, len(grid_lines(document.width, 4))
           + len(grid_lines(document.height, 4)))

    # THE HALF THAT MATTERS. A grid that changes what a click addresses is
    # the failure this whole design is arranged to prevent, so it is proved
    # twice: by the coordinate function, and by actually painting.
    samples = [(0.0, 0.0), (17.0, 33.0), (99.5, 1.5), (640.0, 640.0)]
    window.canvas.grid_step = 1
    at_step_1 = [window.canvas.cell_at(x, y) for x, y in samples]
    window.canvas.grid_step = 4
    expect("cell_at is untouched by the grid spacing",
           [window.canvas.cell_at(x, y) for x, y in samples], at_step_1)
    drag(window, [(40, 40)])
    expect("and a click still paints the one cell it always did",
           painted(), {(40, 40)})
    window.undo()
    window.canvas.grid_step = 1
    grid_line_count()

    window.undo()          # the probe layer
    expect("the probe layer undoes byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("the terrain tool re-tiles cells the cursor never touched")
    # ----------------------------------------------------------------
    # Paint on a layer this check CREATES, so the fixture is guaranteed
    # empty. A shipped layer is repainted by the author, and Floor cannot be
    # used at all: it is filled with gid 65, a real quadrant of the grass
    # autotile block, so the terrain recogniser reads most of it as
    # already-grass and a small stroke changes almost nothing.
    window.run(Command("map.layer.add", Scope.of(("map", "test")),
                       {"name": "TerrainProbe", "kind": "tile"}))
    select_layer(window, "TerrainProbe")
    window.canvas.tool = Tool.AUTOTILE
    window.canvas.stamp = Stamp.single(98)      # a TileA2 grass fill quadrant
    terrain = window.canvas._MapCanvas__terrain_for_brush()
    expect("the brush resolved to a terrain", isinstance(terrain, TerrainSet), True)
    expect("and to the right autotile block", terrain.origin, 1)
    expect("the layer starts empty",
           set(session.project.map("test").tile_layer("TerrainProbe").gids()),
           {0})

    before_stroke = len(session.history())
    drag(window, [(40, 40), (42, 40)])
    expect("the stroke is ONE transaction on top of the layer creation",
           len(session.history()) - before_stroke, 1)
    touched = session.history()[-1].commands[0].args["tiles"]
    xs = [x for x, _y, _g in touched]
    ys = [y for _x, y, _g in touched]
    # Corners of cells 40..42 span a 4x2 lattice, which tiles a 4x3 cell
    # block -- wider and taller than the three cells dragged over.
    expect("it wrote outside the dragged cells", min(ys) < 40 or max(ys) > 40,
           True)
    expect("and used more than one gid",
           len({g for _x, _y, g in touched}) > 1, True)
    window.undo()          # the stroke

    # AUTOTILE takes a SIZE even though it takes no STAMP, which is the
    # whole reason `uses_size` had to be its own property instead of the
    # negation of `uses_stamp`. Both halves, on the check's own empty
    # layer: a bigger footprint re-tiles strictly more, and a size of 1
    # still re-tiles exactly the block it always did.
    def terrain_cells(size):
        window.canvas.brush_size = size
        drag(window, [(50, 50)])
        touched = {(x, y) for x, y, _g
                   in session.history()[-1].commands[0].args["tiles"]}
        window.undo()
        return touched

    small, large = terrain_cells(1), terrain_cells(3)
    window.canvas.brush_size = 1
    expect("a size-1 terrain brush re-tiles the cells its 4 corners touch",
           len(small), 9)
    expect("size 3 sets a 4x4 corner lattice and re-tiles 25",
           len(large), 25)
    expect("and the small footprint sits inside the large one",
           small <= large, True)

    window.undo()          # the probe layer
    expect("terrain and the probe layer both undo byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)
    window.canvas.tool = Tool.BRUSH

    # ----------------------------------------------------------------
    print()
    print("objects: place, inspect, edit, delete, undo")
    # ----------------------------------------------------------------
    # Where the undo stack stood before any of this ran. Everything below
    # unwinds back to exactly here, and the byte comparison at the end is
    # what proves it -- counting undos by hand stops being a measurement
    # the moment a section grows one more command.
    OBJECT_BASE = len(session.stream.done)
    select_layer(window, "entity")
    # WHAT THE FIXTURE ALREADY HOLDS, counted rather than assumed. Every
    # count below is a DELTA against this. "One click leaves one object"
    # is a claim about the map as much as about the click (law 4), and it
    # was false the day an object was authored into `test.tmx`.
    BORN_WITH = len(session.project.map("test").object_layer("entity").objects())
    window.canvas.object_class = "GamePlayer"
    place_object(window, (4, 6))
    objects = session.project.map("test").object_layer("entity").objects()
    expect("an object was placed", len(objects), BORN_WITH + 1)
    expect("with the chosen class", objects[-1].type, "GamePlayer")

    # A GESTURE, not a Command written by the check: the whole point of putting
    # materialisation in the verb rather than in the panel is that the author's
    # real path gets it. And the property is invisible on a rectangle, so the
    # status line is asserted too -- an authoring surface where something
    # happens and nothing says so is the defect this suite is named after.
    STARTS_AS = genre_module.load("topdown_rpg").object_class(
        "entity", "GamePlayer").behaviors_text
    expect("clicking an entity layer materialises the pack's behavior list",
           objects[-1].properties.as_dict().get(BEHAVIORS), STARTS_AS)
    expect("and the status bar says so, since a property is invisible",
           STARTS_AS in window.statusBar().currentMessage(), True)

    # The other half, through the same click path: a class the pack does not
    # name is placed with nothing, and the status line does not invent a list.
    window.canvas.object_class = "GameEntity"
    place_object(window, (6, 6))
    plain = session.project.map("test").object_layer("entity").objects()[-1]
    expect("a class the pack does not name is placed with nothing",
           plain.properties.as_dict(), {})
    expect("and the status line does not claim a list it did not write",
           window.statusBar().currentMessage(), "placed GameEntity")
    window.undo()
    application.processEvents()
    objects = session.project.map("test").object_layer("entity").objects()
    expect("undoing it leaves the first object alone", len(objects),
           BORN_WITH + 1)
    window.canvas.object_class = "GamePlayer"

    # THE OBJECT UNDER TEST, by the id the document gave it. Written down
    # once: every assertion from here to the end of the section names it,
    # and "object 1" only ever meant "the fixture happened to be empty".
    TARGET = objects[-1].id
    TARGET_SCOPE = f"map:test/layer:entity/object:{TARGET}"
    window.selection.select(Scope.of(("map", "test"), ("layer", "entity"),
                                     ("object", str(TARGET))))
    application.processEvents()

    # The Actions panel has to be IN `window.docks`, or no click can open it
    # -- a panel with its own passing check and no door is a surface the
    # author cannot reach.
    from PySide6.QtWidgets import QLabel                          # noqa: E402
    expect("the Actions panel is mounted", window.actions in window.docks, True)
    expect("in the window, not floating free",
           window.actions.parent() is window, True)
    view_menu = next(a.menu() for a in window.menuBar().actions()
                     if a.text() == "&View")
    expect("and reachable from the View menu",
           any(a.text().startswith("Actions") for a in view_menu.actions()),
           True)
    expect("its banner is on screen, not in a docstring",
           NOT_WIRED in [label.text()
                         for label in window.actions.findChildren(QLabel)], True)
    expect("and it followed the selection like the Inspector",
           str(window.actions.scope), TARGET_SCOPE)

    inspection = window.inspector.view.inspection
    fields = {f.key: f for section in inspection.sections for f in section.fields}
    expect("the inspector describes it", inspection.heading,
           f"object {TARGET}")
    expect("it offers position as a number", fields["x"].kind, "float")
    expect("class as a constrained choice", fields["type"].kind, "choice")
    expect("rotation is editable now", fields["rotation"].editable, True)
    expect("and visible is a checkbox", fields["visible"].kind, "bool")

    window.run(fields["x"].emit(128.0))
    expect("editing through the inspector moved it",
           session.project.map("test").object_layer("entity")
           .find(TARGET).x, 128.0)
    window.undo()

    # Adding a property is ONE form. Two QInputDialogs in a row -- name, then
    # type -- throws away the name when the second is cancelled.
    property_forms: list = []
    window.inspector.view.ask = lambda _p, title, rows, **k: (
        property_forms.append([f.key for f in rows])
        or {"key": "pyoneer_probe", "kind": "int"})
    no_modals()
    window.inspector.view._InspectionView__on_add_property()
    application.processEvents()
    expect("one form carries name and type together",
           property_forms, [["key", "kind"]])
    expect("and it asked nothing else", modals(), [])
    expect("the property landed, typed",
           str(session.project.map("test").object_layer("entity")
               .find(TARGET).properties.as_dict().get("pyoneer_probe")),
           "0")
    window.inspector.view.ask = ask_module.ask_form
    window.undo()

    # ----------------------------------------------------------------
    print()
    print("an object is MOVED, PICKED and DELETED by hand -- and a "
          "right-click no longer destroys one")
    # ----------------------------------------------------------------
    # THE DEFECT THIS SECTION REPLACES. Right-click used to route straight
    # into `__delete_object_under`: one press, on the same button that
    # erases tiles, and the entity was gone with no menu and no question.
    # The assertion that stood here read "right-click deleted it" and was
    # green for the whole life of that behaviour, which is the measure of
    # how little a passing assertion says about whether the gesture is the
    # right one.
    #
    # THE MENU SEAM. `QMenu.exec` blocks (law 13) -- measured on the way to
    # writing this: the first run of the changed canvas against the OLD
    # right-click assertion hung this file for the full 600s timeout with
    # zero output, which is exactly the failure law 13 was written for. So
    # `popup_menu` is replaced here the way `TilePalette.popup_menu` is in
    # `check_palette.py`, and a real right-click is driven through the real
    # hit test into a real QMenu that is READ instead of shown.
    entity_scope = Scope.of(("map", "test"), ("layer", "entity"))

    def entity_objects():
        return session.project.map("test").object_layer("entity").objects()

    def entity_object(object_id):
        return session.project.map("test").object_layer("entity").find(object_id)

    opened: list = []
    window.canvas.popup_menu = lambda menu, at: opened.append(menu)

    def right_click_px(px):
        """A real right-click, and every menu it opened.

        NO processEvents, and the reason changed with the fix: the handler
        no longer frees the menu on the way out -- `_hold_menu` frees it
        when it CLOSES, because `popup` hands it back still open -- but a
        menu built through the stub below never shows and so never hides,
        and spinning the loop here would still fire the watchdog armed by
        the section that drives the REAL opener.
        """
        opened.clear()
        mouse_px(window, QEvent.Type.MouseButtonPress, px, Qt.RightButton)
        return list(opened)

    def labels(menu):
        return [action.text() for action in menu.actions()]

    edits: list = []
    window.canvas.edit_object_requested.connect(
        lambda scope: edits.append(str(scope)))

    one = entity_object(TARGET)
    ONE_ID = TARGET
    HOME = (one.x, one.y)
    TILE = window.canvas.tile_width
    inside = (HOME[0] + 4, HOME[1] + 4)
    expect("the object under test is on a tile boundary to begin with",
           (HOME[0] % TILE, HOME[1] % TILE), (0.0, 0.0))

    # -- RIGHT-CLICK: a menu, and the object survives it ---------------
    # The count is taken BEFORE the click, or "nothing was written" is
    # `x == x` and asserts nothing at all (law 5).
    no_modals()
    before = len(entity_objects())
    depth = len(session.stream.done)
    menus = right_click_px(inside)
    expect("right-clicking an object opens a menu with the two things "
           "there are to do",
           [labels(m) for m in menus], [["Edit…", "Delete"]])
    expect("...AND THE OBJECT IS STILL THERE, which is the whole point",
           (len(entity_objects()), entity_object(ONE_ID) is not None),
           (before, True))
    # The other half of "no object was removed": the undo stack did not
    # move either. A removal that was immediately undone would satisfy the
    # count above and not this.
    expect("...having written no command and opened no dialog",
           (len(session.stream.done), modals()), (depth, []))

    # -- RIGHT-CLICK OVER NOTHING: no menu, but a line saying so -------
    empty_px = (HOME[0] + TILE * 5, HOME[1])
    expect("right-clicking bare ground opens NOTHING",
           right_click_px(empty_px), [])
    expect("...and says what the button would have meant there",
           "double-click bare ground" in window.statusBar().currentMessage(),
           True)
    # The builder REFUSES rather than handing back an empty menu, so the
    # decision cannot be made twice and answered differently (law 7).
    refused = None
    try:
        window.canvas.object_menu([])
    except Exception as exc:                                    # noqa: BLE001
        refused = type(exc).__name__
    expect("...and the menu builder refuses an empty pick outright",
           refused, "PyoneerError")

    # -- RIGHT-CLICK ON A TILE LAYER STILL ERASES ----------------------
    # The branch that was wrong was the OBJECT one. Painting is a different
    # branch and the author did not ask for it to change, so this is the
    # half that proves the edit stayed inside its own case.
    select_layer(window, "Floor")
    floor = session.project.map("test").tile_layer("Floor")
    window.canvas.tool = Tool.BRUSH
    # A gid the cell does not already hold, so the paint is guaranteed to
    # produce an edit and the two undos below are guaranteed to be this
    # section's own. A stroke that changes nothing commits nothing.
    ERASE_CELL = (2, 2)
    window.canvas.stamp = Stamp.single(
        77 if floor.get_tile(*ERASE_CELL) != 77 else 98)
    painted_gid = window.canvas.stamp.gids[0]
    drag(window, [ERASE_CELL])                   # something to erase
    expect("a left-click on a tile layer paints",
           floor.get_tile(*ERASE_CELL), painted_gid)
    depth = len(session.stream.done)
    opened.clear()
    drag(window, [ERASE_CELL], Qt.RightButton)
    expect("...and a right-click there still ERASES, menu-free",
           (floor.get_tile(*ERASE_CELL), opened, len(session.stream.done)),
           (0, [], depth + 1))
    window.undo()                                # the erase
    window.undo()                                # the paint
    select_layer(window, "entity")
    window.selection.select(entity_scope.child("object", str(ONE_ID)))
    application.processEvents()

    # -- DRAG: snapped by default --------------------------------------
    # A whole tile plus five pixels, so snapped and freeflow land on
    # DIFFERENT numbers. A whole number of tiles would land on a boundary
    # either way and prove nothing about snapping (law 5).
    OFF = TILE + 5
    depth = len(session.stream.done)
    drag_px(window, inside, (inside[0] + OFF, inside[1]))
    moved = entity_object(ONE_ID)
    expect("dragging an object moves it, snapped to the tile grid",
           (moved.x, moved.x % TILE, moved.y), (HOME[0] + TILE, 0.0, HOME[1]))
    expect("...as ONE transaction, so one Ctrl+Z takes the whole drag back",
           len(session.stream.done), depth + 1)
    window.undo()
    application.processEvents()
    expect("...and it does", (entity_object(ONE_ID).x, entity_object(ONE_ID).y),
           HOME)

    # -- DRAG: freeflow, and ALT inverts the toggle live ---------------
    depth = len(session.stream.done)
    drag_px(window, inside, (inside[0] + OFF, inside[1]),
            modifiers=Qt.AltModifier)
    freed = entity_object(ONE_ID)
    expect("ALT during the drag goes freeflow: it lands OFF the grid",
           (freed.x, freed.x % TILE), (HOME[0] + OFF, float(OFF % TILE)))
    expect("...still one transaction", len(session.stream.done), depth + 1)
    window.undo()
    application.processEvents()

    # The toggle is a plain attribute, so the same gesture with it off has
    # to land where ALT just did -- and ALT then has to snap. Both halves,
    # because a canvas that ignored `snap_objects` and always snapped
    # would pass every assertion above.
    window.canvas.snap_objects = False
    drag_px(window, inside, (inside[0] + OFF, inside[1]))
    expect("with snapping switched off a plain drag is freeflow",
           entity_object(ONE_ID).x, HOME[0] + OFF)
    window.undo()
    drag_px(window, inside, (inside[0] + OFF, inside[1]),
            modifiers=Qt.AltModifier)
    expect("...and ALT inverts THAT too, back onto the grid",
           (entity_object(ONE_ID).x, entity_object(ONE_ID).x % TILE),
           (HOME[0] + TILE, 0.0))
    window.undo()
    application.processEvents()
    window.canvas.snap_objects = True

    # -- DRAG: nowhere. NO COMMAND. ------------------------------------
    # An undo step that changes nothing is worse than no undo step: the
    # first Ctrl+Z after it appears to do nothing at all.
    depth = len(session.stream.done)
    drag_px(window, inside, inside)
    expect("a drag that ends where it started writes NO command",
           (len(session.stream.done), entity_object(ONE_ID).x), (depth, HOME[0]))
    # And the same for travel too small to leave the cell -- the snap puts
    # it back on the boundary it came from, so there is nothing to record.
    drag_px(window, inside, (inside[0] + 3, inside[1] + 3))
    expect("...nor does travel the snap swallows",
           (len(session.stream.done), entity_object(ONE_ID).x), (depth, HOME[0]))

    # -- STACKING: the menu becomes a picker ---------------------------
    # A SECOND object at the same pixel. Placed through the verb rather
    # than by clicking, because a click on an occupied cell now grabs what
    # is there -- which is the behaviour two assertions up.
    window.run(Command("map.object.add", entity_scope,
                       {"type": "GameEntity", "name": "Twin",
                        "x": HOME[0], "y": HOME[1]}))
    application.processEvents()
    stacked = entity_objects()
    expect("two objects now sit on the same cell",
           len(stacked), BORN_WITH + 2)
    TWIN_ID = stacked[-1].id
    hits = window.canvas.objects_under(QPointF(*inside))
    expect("both are under the cursor, topmost first -- the one added last "
           "is the one drawn on top",
           [obj.id for _layer, obj in hits], [TWIN_ID, ONE_ID])

    menus = right_click_px(inside)
    expect("right-clicking a stack opens a PICKER, one entry per object",
           [len(labels(m)) for m in menus], [2])
    expect("...each labelled so it can be told from the other: the tmx "
           "name when it has one, the id and the type when it does not",
           labels(menus[0]),
           [f"Twin  ·  GameEntity {TWIN_ID}  ·  entity",
            f"GamePlayer {ONE_ID}  ·  entity"])

    # A PICK SELECTS. It does not delete, and it does not edit.
    picker = window.canvas.object_menu(window.canvas.objects_under(QPointF(*inside)))
    held.append(picker)
    held.append(picker.actions())
    depth = len(session.stream.done)
    edits.clear()
    picker.actions()[1].trigger()               # the one UNDERNEATH
    application.processEvents()
    expect("picking the buried one SELECTS it",
           str(window.selection.scope), f"map:test/layer:entity/object:{ONE_ID}")
    expect("...and changes nothing and opens nothing",
           (len(session.stream.done), len(entity_objects()), edits, modals()),
           (depth, BORN_WITH + 2, [], []))

    # THE OTHER HALF: one object is not a picker. Same code, same click,
    # a different menu -- which is the only way to know the count decides
    # it rather than the shape being a constant.
    window.run(Command("map.object.remove", entity_scope.child("object",
                                                               str(TWIN_ID))))
    application.processEvents()
    menus = right_click_px(inside)
    expect("one object under the cursor produces no picker at all",
           [labels(m) for m in menus], [["Edit…", "Delete"]])

    # -- THE REAL OPENER, DRIVEN. NOT A STUB. --------------------------
    # Everything above replaces `popup_menu`, which is right for reading a
    # menu and proves NOTHING about the call the author's own right-click
    # makes. That call used to be `QMenu.exec`, which does not return until
    # the menu closes -- the 40-minute shape law 13 is named after, and a
    # check that only ever drove the stub could not see it.
    #
    # THE WATCHDOG IS WHAT MAKES THIS SAFE TO ASSERT. A zero-timer is armed
    # first: under `exec` it fires inside that nested loop, closes the menu
    # and lets the call return, so a regression comes back RED in
    # milliseconds instead of hanging this file for the full 600s. Under
    # `popup` nothing spins the loop before the assertion, so the timer
    # cannot have fired and a VISIBLE menu is proof the call did not block.
    from PySide6.QtCore import QTimer                            # noqa: E402
    from PySide6.QtWidgets import QMenu                          # noqa: E402

    def close_any_popup():
        popup = QApplication.activePopupWidget()
        if popup is not None:
            popup.close()

    real_menus: list = []

    def watched_open(menu, at):
        """Record the menu, then hand it to the REAL opener."""
        real_menus.append(menu)
        canvas_module._exec_menu(menu, at)

    window.canvas.popup_menu = watched_open
    menus_before = len(window.canvas.findChildren(QMenu))
    depth = len(session.stream.done)
    QTimer.singleShot(0, close_any_popup)
    mouse_px(window, QEvent.Type.MouseButtonPress, inside, Qt.RightButton)
    expect("the REAL right-click opened exactly one menu",
           [labels(m) for m in real_menus], [["Edit…", "Delete"]])
    live = real_menus[0]
    expect("...and RETURNED with it still on screen, so nothing blocked",
           (live.isVisible(), QApplication.activePopupWidget() is live),
           (True, True))
    expect("...having deleted nothing and asked nothing",
           (len(entity_objects()), len(session.stream.done), modals()),
           (BORN_WITH + 1, depth, []))
    # THE OTHER HALF OF THE MENU'S LIFETIME. It must not be freed while it
    # is up -- that is what a `deleteLater()` under a non-blocking `popup`
    # would do -- and it must not survive being dismissed either, or every
    # right-click leaves a QMenu on the canvas for the rest of the session.
    expect("a menu that is still open is still alive",
           len(window.canvas.findChildren(QMenu)), menus_before + 1)
    # AND IT STILL ACTS. An entry wired with `triggered` does not care
    # whether its menu was `exec`'d or popped, but that is a claim, and
    # `Edit…` is the one entry that proves it without writing anything.
    # NO processEvents around it: `triggered` is a direct connection and
    # arrives synchronously, and spinning the loop here would let the
    # watchdog close the menu the next two assertions are about.
    edits.clear()
    live.actions()[0].trigger()
    expect("...and an entry on the LIVE menu still does what it says",
           edits, [f"map:test/layer:entity/object:{ONE_ID}"])
    live.close()
    application.processEvents()
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    expect("...and closing it frees it, on the same beat Qt hides it",
           len(window.canvas.findChildren(QMenu)), menus_before)
    window.canvas.popup_menu = lambda menu, at: opened.append(menu)

    # -- THE MENU'S OWN Edit AND Delete --------------------------------
    # Built here rather than triggered out of the popped one: a popped
    # menu is freed when it closes, so an entry triggered after it has
    # been dismissed is an entry on a freed QMenu. Same split
    # `check_palette.py` makes for the same reason. The REAL opener is
    # driven in its own section below, where the menu is still open.
    single = window.canvas.object_menu(window.canvas.objects_under(QPointF(*inside)))
    held.append(single)
    held.append(single.actions())
    edits.clear()
    single.actions()[0].trigger()               # Edit…
    application.processEvents()
    expect("Edit… asks the window to open the object, by scope",
           edits, [f"map:test/layer:entity/object:{ONE_ID}"])
    expect("...and selects it on the way, so the canvas draws what opened",
           str(window.selection.scope), f"map:test/layer:entity/object:{ONE_ID}")

    depth = len(session.stream.done)
    single.actions()[1].trigger()               # Delete
    application.processEvents()
    expect("Delete on the menu removes it, through map.object.remove",
           (entity_object(ONE_ID), len(session.stream.done)), (None, depth + 1))
    expect("...and the selection climbs to the layer rather than pointing "
           "at an object that is gone",
           str(window.selection.scope), "map:test/layer:entity")
    window.undo()
    application.processEvents()
    window.selection.select(entity_scope.child("object", str(ONE_ID)))
    application.processEvents()

    # -- THE DELETE KEY ------------------------------------------------
    def press_key(key):
        window.canvas.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, key, Qt.NoModifier))
        application.processEvents()

    depth = len(session.stream.done)
    press_key(Qt.Key_Delete)
    expect("Delete removes the SELECTED object",
           (entity_object(ONE_ID), len(session.stream.done)), (None, depth + 1))
    window.undo()
    application.processEvents()

    # BOTH HALVES OF THE GUARD, and this is the half that matters: a key
    # that deletes whatever the selection happens to name is a key that
    # deletes something the author cannot see selected.
    window.selection.select(entity_scope)
    application.processEvents()
    depth = len(session.stream.done)
    press_key(Qt.Key_Delete)
    expect("Delete with nothing selected removes NOTHING",
           (len(entity_objects()), len(session.stream.done)),
           (BORN_WITH + 1, depth))
    expect("...and says so rather than looking like a dead key",
           "nothing is selected" in window.statusBar().currentMessage(), True)

    # A stale selection is the other way to delete the wrong thing: the
    # scope survives the object it names. It has to resolve to nothing.
    window.selection.select(entity_scope.child("object", "9999"))
    application.processEvents()
    press_key(Qt.Key_Delete)
    expect("...and a selection whose object is gone removes nothing either",
           (len(entity_objects()), len(session.stream.done)),
           (BORN_WITH + 1, depth))

    # And with a TILE layer active, where no object outline is drawn at all.
    window.selection.select(entity_scope.child("object", str(ONE_ID)))
    application.processEvents()
    window.canvas.active_layer = "Floor"
    press_key(Qt.Key_Delete)
    expect("Delete while a TILE layer is active removes nothing",
           (len(entity_objects()), len(session.stream.done)),
           (BORN_WITH + 1, depth))
    expect("...naming the layer that is in the way",
           "'Floor' is a tile layer" in window.statusBar().currentMessage(),
           True)
    window.canvas.active_layer = "entity"

    # -- DELETE ON A HIDDEN LAYER --------------------------------------
    # The fourth guard, and the one its own docstring described while not
    # existing. A hidden layer draws no outline (`__draw_objects` skips it)
    # and cannot be right-clicked (`objects_under` skips it), so this key
    # was the last path that could still remove an object the author
    # cannot see. Driven through the REAL Layers-panel signal, not by
    # writing to `hidden_layers`: the wire is part of the claim.
    window.selection.select(entity_scope.child("object", str(ONE_ID)))
    application.processEvents()
    window.hierarchy.visibility_changed.emit("entity", False)
    application.processEvents()
    expect("a hidden layer's object cannot be right-clicked either",
           window.canvas.objects_under(QPointF(*inside)), [])
    depth = len(session.stream.done)
    press_key(Qt.Key_Delete)
    expect("Delete on a HIDDEN layer removes NOTHING",
           (len(entity_objects()), len(session.stream.done)),
           (BORN_WITH + 1, depth))
    expect("...and says which layer is hidden, the way the other three do",
           ("'entity' is hidden" in window.statusBar().currentMessage(),
            modals()), (True, []))
    # THE OTHER HALF, through the same switch: turn the layer back on and
    # the very same key on the very same selection deletes. Without this
    # the guard above would pass on a Delete key that never worked.
    window.hierarchy.visibility_changed.emit("entity", True)
    application.processEvents()
    press_key(Qt.Key_Delete)
    expect("...and the same key on the same object deletes once it is "
           "visible again",
           (entity_object(ONE_ID), len(session.stream.done)),
           (None, depth + 1))
    window.undo()
    application.processEvents()

    # -- PLACING ON A HIDDEN LAYER, THE MIRROR OF THAT GUARD -----------
    # THE SAME BUG, ON THE PATH THAT GREW LATER. Delete learned about a
    # hidden layer; creation moved onto the double-click and did not, and
    # creation is the direction that cannot be walked back by hand:
    # `__draw_objects` skips a hidden layer and `objects_under` skips it,
    # so the object that lands is not drawn, cannot be clicked, cannot be
    # dragged, cannot be right-clicked -- and the double-click therefore
    # finds NOTHING under the cursor and places AGAIN. Measured before the
    # fix: three double-clicks in one cell of a layer unticked in the
    # Layers panel left objects 1, 2 and 3 stacked invisibly, and the
    # refusal above then declined to remove any of them.
    #
    # Driven through the REAL Layers-panel signal, exactly as the Delete
    # guard above is, and on a cell PROVED bare rather than assumed to be
    # (law 4) -- the fixture's own objects sit wherever the author put them.
    def bare_cell(column: int, row: int) -> tuple[int, int]:
        canvas = window.canvas
        while canvas.objects_under(
                QPointF(column * canvas.tile_width + canvas.tile_width / 2,
                        row * canvas.tile_height + canvas.tile_height / 2)):
            column += 2
        return column, row

    def double_click_cell(cell):
        canvas = window.canvas
        double_click_px(window,
                        (cell[0] * canvas.tile_width + canvas.tile_width / 2,
                         cell[1] * canvas.tile_height + canvas.tile_height / 2))

    def editor_up() -> bool:
        return (window.object_editor is not None
                and window.object_editor.isVisible())

    BARE = bare_cell(12, 12)
    window.canvas.object_class = "GamePlayer"
    if window.object_editor is not None:
        window.object_editor.close()
    application.processEvents()
    window.hierarchy.visibility_changed.emit("entity", False)
    application.processEvents()
    no_modals()
    depth = len(session.stream.done)
    before = len(entity_objects())
    for _attempt in range(3):
        double_click_cell(BARE)
    expect("THREE double-clicks on a HIDDEN layer place NOTHING",
           (len(entity_objects()), len(session.stream.done)), (before, depth))
    expect("...saying which layer is hidden, in the shape Delete uses",
           ("'entity' is hidden" in window.statusBar().currentMessage(),
            modals()), (True, []))
    expect("...and opening no editor over a placement that did not happen",
           editor_up(), False)

    # The single click of that same gesture must not ADVERTISE the refused
    # one. `objects_under` skips the layer, so this branch sees bare ground
    # and used to answer "Double-click to place a GamePlayer" -- an editor
    # recommending a gesture it has just decided to decline.
    mouse(window, QEvent.Type.MouseButtonPress, BARE)
    mouse(window, QEvent.Type.MouseButtonRelease, BARE)
    application.processEvents()
    expect("a single click there says hidden, and does not invite the "
           "gesture that is refused",
           ("'entity' is hidden" in window.statusBar().currentMessage(),
            "Double-click to place" in window.statusBar().currentMessage()),
           (True, False))

    # THE OTHER HALF, through the same switch. Without it the refusal above
    # would pass on a double-click that never placed anything anywhere --
    # and it is the assertion that proves the cell really was bare.
    window.hierarchy.visibility_changed.emit("entity", True)
    application.processEvents()
    double_click_cell(BARE)
    expect("...and the SAME double-click on the SAME cell places exactly "
           "one once the layer is visible",
           (len(entity_objects()), len(session.stream.done)),
           (before + 1, depth + 1))
    expect("...opening the editor it refused to open while hidden",
           editor_up(), True)
    window.object_editor.close()
    window.undo()
    application.processEvents()
    window.selection.select(entity_scope.child("object", str(ONE_ID)))
    application.processEvents()
    expect("and the hidden-layer detour left the layer exactly as it found it",
           (len(entity_objects()), len(session.stream.done),
            sorted(window.canvas.hidden_layers)), (before, depth, []))

    # -- A RECYCLED ID IS NOT THE OBJECT THAT WAS SELECTED -------------
    # THE WORST DEFECT THIS FILE HAS COVERED: Delete removing an object
    # the author had never clicked, silently.
    #
    # `MapDocument._release_object_id` ROLLS `nextobjectid` back when the
    # id being removed is the one just handed out -- deliberately, because
    # that is what makes add-then-remove byte-exact. So ids are REUSED,
    # and a selection re-resolved by id lands on a different object. Five
    # real gestures, and every one of them is a gesture: place, place,
    # select, Ctrl+Z, place.
    from PySide6.QtWidgets import QGraphicsRectItem                # noqa: E402

    def drawn_selected():
        """WHICH objects the canvas is DRAWING the selected outline around.

        Read off the SCENE, not off the state the drawing is derived from.
        The defect was that the canvas painted a selection around an object
        the author never clicked, so the assertion has to look at the
        picture -- asking the canvas which id it thinks is selected would
        be asking the accused.
        """
        corners = {(round(item.rect().x()), round(item.rect().y()))
                   for item in window.canvas.scene().items()
                   if isinstance(item, QGraphicsRectItem)
                   and item.parentItem() is None
                   and item.pen().color() == canvas_module._OBJECT_SELECTED}
        return sorted(obj.id for obj in entity_objects()
                      if (round(obj.x), round(obj.y)) in corners)

    STALE_BASE = len(session.stream.done)
    STANDING = [obj.id for obj in entity_objects()]
    window.canvas.object_class = "GamePlayer"

    def add_at(cell):
        """Put an object on the map WITHOUT selecting it.

        THE PLACING GESTURE IS A DOUBLE-CLICK NOW, and a double-click
        selects what it placed and opens its editor -- which is right, and
        which would make this section untestable: the premise is a
        selection left pointing at an id that has since been handed to a
        DIFFERENT object, and a gesture that selects what it just made can
        never leave one. So these three arrive by command, the way a
        script or a sibling panel places one, and every assertion below is
        still driven by a real click or a real key.
        """
        window.run(Command("map.object.add", entity_scope,
                           {"type": "GamePlayer",
                            "x": float(cell[0] * TILE),
                            "y": float(cell[1] * window.canvas.tile_height)}))
        application.processEvents()

    add_at((12, 12))                                               # A
    add_at((14, 12))                                               # B
    A_ID, B_ID = [obj.id for obj in entity_objects()[-2:]]
    B_AT = (entity_object(B_ID).x, entity_object(B_ID).y)
    window.selection.select(entity_scope.child("object", str(B_ID)))
    application.processEvents()
    expect("the author selects B, and B is what is drawn selected",
           drawn_selected(), [B_ID])

    window.undo()                                   # B is gone
    application.processEvents()
    expect("one Ctrl+Z takes B away and nothing is drawn selected",
           (entity_object(B_ID), drawn_selected()), (None, []))

    add_at((17, 12))                                               # C
    C_ID = entity_objects()[-1].id
    C_AT = (entity_object(C_ID).x, entity_object(C_ID).y)
    expect("THE ID IS HANDED OUT AGAIN: C is a different object in a "
           "different place, carrying B's id",
           (C_ID, C_AT == B_AT), (B_ID, False))
    # THE ASSERTION THE WHOLE SECTION EXISTS FOR.
    expect("...and the canvas draws NOTHING as selected, because the "
           "author never clicked C",
           drawn_selected(), [])
    depth = len(session.stream.done)
    press_key(Qt.Key_Delete)
    expect("...and Delete removes NOTHING",
           ([obj.id for obj in entity_objects()], len(session.stream.done)),
           (STANDING + [A_ID, C_ID], depth))
    expect("...saying nothing is selected, rather than deleting in silence",
           ("nothing is selected" in window.statusBar().currentMessage(),
            modals()), (True, []))
    # And the window is not left pointing at the dead id either: a
    # `Selection` that still named it would swallow the author's next
    # click on C, since `select` de-duplicates.
    expect("...and the selection climbed off the dead id",
           str(window.selection.scope), "map:test/layer:entity")

    # THE POSITIVE HALF, and it is not optional: a fix that forgets more
    # than it must is a fix that gets reverted. C is selected by CLICKING
    # it -- the same gesture, the same id -- and now Delete does remove it.
    # A WHOLE CLICK -- press AND release. A press on an object opens a
    # drag, and the drag lives until a release commits it: measured here,
    # a press with no release left one open, the tile drag three
    # assertions later released into it instead of into its own stroke,
    # and the orphaned stroke then committed `map.tile.set_many` against
    # an OBJECT layer on the next release anywhere. Nothing a hand can do
    # gets there, because a hand always lets go.
    mouse(window, QEvent.Type.MouseButtonPress, (17, 12))
    mouse(window, QEvent.Type.MouseButtonRelease, (17, 12))
    application.processEvents()
    expect("clicking C selects C, id and all", drawn_selected(), [C_ID])
    press_key(Qt.Key_Delete)
    expect("...and Delete removes THAT, so the guard is not a dead key",
           ([obj.id for obj in entity_objects()], len(session.stream.done)),
           (STANDING + [A_ID], depth + 1))
    window.undo()                                   # C is back
    application.processEvents()

    # THE SAME DEFECT IN ONE STEP, and this is the half that a rule of
    # "it was missing at some rebuild" cannot catch. A script, or a panel
    # that is not this canvas, edits through the SESSION -- so the remove
    # and the add land between two rebuilds, the freed id is handed
    # straight back, and there is no moment at which the canvas could have
    # seen the id resolve to nothing. Only the card can tell the two
    # objects apart here. Driven with `session.run`, deliberately, because
    # `window.run` refreshes and would rebuild in between.
    window.selection.select(entity_scope.child("object", str(C_ID)))
    application.processEvents()
    expect("C is selected to begin with", drawn_selected(), [C_ID])
    session.run(Command("map.object.remove",
                        entity_scope.child("object", str(C_ID))))
    session.run(Command("map.object.add", entity_scope,
                        {"type": "GamePlayer", "name": "Impostor",
                         "x": 320.0, "y": 320.0}))
    impostor = entity_objects()[-1]
    expect("an impostor is handed the selected object's id, with no "
           "rebuild in between",
           (impostor.id, impostor.name), (C_ID, "Impostor"))
    depth = len(session.stream.done)
    window.canvas.rebuild()
    application.processEvents()
    expect("...and the canvas drops the selection instead of adopting it",
           drawn_selected(), [])
    expect("...naming the object the id used to mean",
           (f"object {C_ID} is not" in window.statusBar().currentMessage(),
            modals()), (True, []))
    press_key(Qt.Key_Delete)
    expect("...so Delete removes nothing, impostor included",
           ([obj.id for obj in entity_objects()], len(session.stream.done)),
           (STANDING + [A_ID, C_ID], depth))
    session.undo()
    session.undo()
    window.canvas.rebuild()
    application.processEvents()

    # AND THE TWO WAYS A SELECTION MUST SURVIVE. Only the object ceasing
    # to be that object may cost the author their selection; a fix that
    # cleared on every edit would pass everything above and be useless.
    window.selection.select(entity_scope.child("object", str(A_ID)))
    application.processEvents()
    window.run(Command("map.object.move",
                       entity_scope.child("object", str(A_ID)),
                       {"x": float(entity_object(A_ID).x + TILE),
                        "y": float(entity_object(A_ID).y)}))
    application.processEvents()
    expect("MOVING the selected object keeps it selected -- it is still "
           "the same object",
           drawn_selected(), [A_ID])
    window.undo()
    application.processEvents()

    window.canvas.active_layer = "Floor"
    window.canvas.stamp = Stamp.single(77)
    window.canvas.tool = Tool.BRUSH
    drag(window, [(31, 31)])
    expect("...and PAINTING A TILE does not cost the author their object",
           drawn_selected(), [A_ID])
    window.undo()
    window.canvas.active_layer = "entity"
    application.processEvents()

    while len(session.stream.done) > STALE_BASE:
        window.undo()
    application.processEvents()
    window.selection.select(entity_scope.child("object", str(ONE_ID)))
    application.processEvents()

    # -- A SINGLE CLICK NEVER CREATES ----------------------------------
    # THE AUTHOR'S REPORT: "left click is currently adding an entity to
    # the map when it needs to be double click". Double-click-to-place was
    # added and single-click-to-place was never taken out, so bare ground
    # took an object on every click that meant "look here" -- on a map
    # being navigated, one per click, and the author need never notice.
    #
    # It is also what Qt's event order demands. A double-click arrives as
    # press, release, DoubleClick, release, so the single-click path runs
    # FIRST on the way to every double-click: anything irreversible here
    # happens once per double-click too.
    expect("the object under test is selected before the click",
           drawn_selected(), [ONE_ID])
    edits.clear()
    count = len(entity_objects())
    depth = len(session.stream.done)
    no_modals()
    mouse_px(window, QEvent.Type.MouseButtonPress, empty_px)
    mouse_px(window, QEvent.Type.MouseButtonRelease, empty_px)
    application.processEvents()
    expect("A SINGLE CLICK ON BARE GROUND CREATES NOTHING",
           (len(entity_objects()), len(session.stream.done)), (count, depth))
    expect("...it CLEARS the selection instead -- the deliberate way back "
           "to nothing-selected, which Delete and the inspector both read",
           (drawn_selected(), str(window.selection.scope)),
           ([], "map:test/layer:entity"))
    expect("...saying what a double-click would have done there",
           (f"Double-click to place a {window.canvas.object_class}"
            in window.statusBar().currentMessage(), modals()), (True, []))
    expect("...and opening no editor for an object it did not make",
           edits, [])

    # THE OTHER HALF, and it is the half that stops the fix from being
    # "make left click do nothing": the same button on an OBJECT still
    # selects it, and still writes nothing.
    mouse_px(window, QEvent.Type.MouseButtonPress, inside)
    mouse_px(window, QEvent.Type.MouseButtonRelease, inside)
    application.processEvents()
    expect("a single click ON an object still selects it, and still writes "
           "nothing",
           (drawn_selected(), len(entity_objects()), len(session.stream.done)),
           ([ONE_ID], count, depth))

    # -- DOUBLE-CLICK --------------------------------------------------
    # Over an EXISTING object: nothing is created. Getting this backwards
    # litters one duplicate per double-click on a crowded map, silently.
    edits.clear()
    count = len(entity_objects())
    depth = len(session.stream.done)
    double_click_px(window, inside)
    expect("double-clicking an object creates NOTHING and asks to edit it, "
           "once",
           (len(entity_objects()), len(session.stream.done), edits),
           (count, depth, [f"map:test/layer:entity/object:{ONE_ID}"]))

    # Over BARE GROUND: exactly one object, and one request for it.
    edits.clear()
    depth = len(session.stream.done)
    double_click_px(window, empty_px)
    application.processEvents()
    made = entity_objects()
    expect("double-clicking bare ground places EXACTLY ONE object",
           (len(made), len(session.stream.done)), (count + 1, depth + 1))
    expect("...and asks to edit the one it just made, once",
           edits, [f"map:test/layer:entity/object:{made[-1].id}"])
    expect("...snapped to the cell, the way a single click already places",
           (made[-1].x % TILE, made[-1].y % TILE), (0.0, 0.0))
    expect("...with no dialog anywhere in any of this", modals(), [])

    # -- focus_object: THE HIERARCHY'S DOOR ----------------------------
    # `self.window().canvas.focus_object(scope)` is what a tree row calls.
    # It is asserted here, in the canvas's own file, because the canvas
    # owns both halves of the contract: it CENTRES, and it selects through
    # THE SAME PATH A CLICK USES -- two ways of setting a selection is how
    # the canvas comes to draw one object highlighted while the inspector
    # fills in a form for another.
    def visible():
        """What the viewport is showing, in scene coordinates."""
        return window.canvas.mapToScene(
            window.canvas.viewport().rect()).boundingRect()

    def shows(point):
        return visible().contains(QPointF(*point))

    target = entity_object(ONE_ID)
    centre = (target.x + (target.width or TILE) / 2,
              target.y + (target.height or window.canvas.tile_height) / 2)
    # Zoomed in and scrolled away, deliberately: on a map that fits in the
    # viewport whole, "the object is on screen" is true before the call and
    # is not an assertion at all (law 5).
    window.canvas.resetTransform()
    window.canvas.scale(8, 8)
    window.canvas.centerOn(window.canvas.scene().sceneRect().bottomRight())
    window.selection.select(entity_scope)
    application.processEvents()
    expect("the object is off screen and unselected before the call -- or "
           "nothing below could fail",
           (shows(centre), drawn_selected()), (False, []))

    answered = window.canvas.focus_object(
        entity_scope.child("object", str(ONE_ID)))
    application.processEvents()
    expect("focus_object brings the object into view and answers True",
           (answered, shows(centre)), (True, True))
    expect("...and selects it through the same path a click uses, so the "
           "card and the window agree",
           (drawn_selected(), str(window.selection.scope)),
           ([ONE_ID], f"map:test/layer:entity/object:{ONE_ID}"))

    # A STALE ROW, made the way an author makes one: place an object, then
    # Ctrl+Z. The hierarchy can still be holding that address for a frame,
    # and a row that lost its race is not a contract violation -- so this
    # answers False and does not raise.
    standing = len(entity_objects())
    place_object(window, (2, 9))
    ghost = entity_objects()[-1].id
    expect("the row is made by really placing an object -- the cell has to "
           "have been bare, or `ghost` names somebody else",
           len(entity_objects()), standing + 1)
    window.undo()
    application.processEvents()
    expect("...and one Ctrl+Z is what makes the row stale",
           (entity_object(ghost), len(entity_objects())), (None, standing))
    window.selection.select(entity_scope.child("object", str(ONE_ID)))
    application.processEvents()
    def standing_still():
        """Everything the refusal must leave exactly as it found it.

        Measured with NO spin of the event loop inside the measurement:
        `focus_object` is synchronous -- its emit reaches the window and
        comes back through `set_selection` before it returns -- so a
        `processEvents` between the two readings would only let unrelated
        queued work land in the middle of the comparison.

        AND WITHOUT `drawn_selected`, which cannot be asked twice.
        Measured, three reads apart with nothing in between: the first
        `scene().items()` returns 213 items including both object
        rectangles, and the second returns 211 with NO `QGraphicsRectItem`
        at all -- enumerating the scene from Python is what frees them.
        Every other use in this file gets away with it by asking once per
        rebuild. So the canvas is asked for its own answer here, through
        `selected_object`, which re-resolves the card against the document
        and never touches the scene; the PICTURE is asserted on the
        success path above, where the read is the first after a rebuild.
        """
        layer_name, obj = window.canvas.selected_object()
        return (str(window.selection.scope), layer_name,
                None if obj is None else obj.id,
                len(session.stream.done), visible())

    was = standing_still()
    raised = None
    try:
        stale = window.canvas.focus_object(
            entity_scope.child("object", str(ghost)))
    except Exception as exc:                                    # noqa: BLE001
        stale, raised = None, f"{type(exc).__name__}: {exc}"
    now = standing_still()
    expect("focus_object answers False for an id the layer no longer has, "
           "and does not raise", (stale, raised), (False, None))
    expect("...having moved nothing: no scroll, no selection, no command",
           now, was)
    expect("...and a scope that is not an object at all is the same answer, "
           "with the view still where it was",
           (window.canvas.focus_object(entity_scope), standing_still()),
           (False, was))
    window.canvas.resetTransform()
    application.processEvents()

    # ----------------------------------------------------------------
    while len(session.stream.done) > OBJECT_BASE:
        window.undo()
    application.processEvents()
    expect("and everything unwound byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)
    window.canvas.popup_menu = canvas_module._exec_menu

    # ----------------------------------------------------------------
    print()
    print("a rejected edit is reported where it can be read, and asks nothing")
    # ----------------------------------------------------------------
    # A rejection is a designed outcome here, so it is a REPORT: the Problems
    # dock and the status line, and no box to dismiss in order to learn that
    # nothing changed.
    def problem_rows():
        widget = window.problems.list
        return [widget.item(i).text() for i in range(widget.count())]

    no_modals()
    ok = window.run(Command("map.tile.set", Scope.parse("map:test/layer:Floor"),
                            {"x": 99999, "y": 0, "gid": 1}))
    expect("run() reported failure instead of throwing", ok, False)
    expect("and opened no dialog of any kind", modals(), [])
    message = window.statusBar().currentMessage()
    expect("the status bar carries the human clause", bool(message), True)
    expect("without the verb/scope/args trail on its face",
           "via verb=" in message, False)
    expect("Problems has the row", window.problems.notice_keys(), ["rejection"])
    expect("worded the same as the status line",
           any(message in row for row in problem_rows()), True)
    detail = window.problems.notices[0][2]
    expect("and the debugging trail is on the row, in the tooltip",
           "via verb=" in detail, True)
    expect("nothing entered the history", len(session.history()), 0)
    expect("and the file is untouched",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # The other half: a rejection that has been superseded must stop being
    # reported, or the dock becomes a graveyard nobody reads.
    window.run(Command("map.tile.set", Scope.parse("map:test/layer:Floor"),
                       {"x": 1, "y": 1, "gid": 70}))
    expect("a successful edit retires the rejection",
           window.problems.notice_keys(), [])
    window.undo()
    expect("and that edit undoes byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("the hierarchy's add buttons are live or greyed, never silent")
    # ----------------------------------------------------------------
    # '+ tile layer' and '+ object layer' must not be enabled while the
    # panel's scope has no map, or the click returns silently. Both
    # directions are asserted, because only asserting the greyed half is how
    # the same bug survived in the Database.
    hierarchy = window.hierarchy
    select_layer(window, "Floor")
    expect("live on a map, both of them",
           (hierarchy.add_tile.isEnabled(), hierarchy.add_object.isEnabled()),
           (True, True))
    expect("and each says what it will do",
           ("add a tile layer to map:test" in hierarchy.add_tile.toolTip(),
            "add an object layer" in hierarchy.add_object.toolTip()),
           (True, True))

    hierarchy.set_scope(Scope.of("project"))
    hierarchy.refresh()
    application.processEvents()
    expect("greyed when the scope carries no map",
           (hierarchy.add_tile.isEnabled(), hierarchy.add_object.isEnabled()),
           (False, False))
    expect("and both say what would enable them",
           [b.toolTip() for b in (hierarchy.add_tile, hierarchy.add_object)],
           ["open a map first", "open a map first"])
    hierarchy.set_scope(Scope.of(("map", "test")))
    hierarchy.refresh()
    application.processEvents()

    # ----------------------------------------------------------------
    print()
    print("adding a layer is ONE dialog, and it speaks the author's language")
    # ----------------------------------------------------------------
    # ONE form, in the author's language: two dialogs in a row -- name, then
    # group -- discard the name when the second is cancelled, and a prompt
    # naming a repo-relative Python path says nothing to someone who asked to
    # name a layer.
    forms: list = []

    def fake_ask(_parent, title, rows, **_kwargs):
        forms.append((title, list(rows)))
        return {"name": "Roof", "group": "(top level)"}

    hierarchy.ask = fake_ask
    no_modals()
    hierarchy.add_tile.click()
    application.processEvents()
    expect("one form, not two", len(forms), 1)
    expect("carrying both halves of the decision at once",
           [field.key for field in forms[0][1]], ["name", "group"])
    expect("no source file is quoted at the author",
           [f.key for f in forms[0][1] if ".py" in (f.doc + f.label)], [])
    expect("it suggests names the engine already draws",
           "UI_LAYER_1" in forms[0][1][0].choices, True)
    expect("but never one the map already has",
           [n for n in forms[0][1][0].choices
            if n in ("Floor", "Paralax", "Foreground")], [])
    expect("and no modal was involved", modals(), [])
    expect("the layer landed",
           "Roof" in session.project.map("test").layer_names(), True)
    window.undo()
    expect("and undoes byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)
    hierarchy.ask = ask_module.ask_form

    # ----------------------------------------------------------------
    print()
    print("removing a layer acts, and says how to take it back")
    # ----------------------------------------------------------------
    # Undo restores a removed layer byte-for-byte, so by this editor's own
    # definition removing one is not destructive and asks nothing. It says
    # how to take it back instead.
    window.run(Command("map.layer.add", Scope.of(("map", "test")),
                       {"name": "Doomed", "kind": "tile"}))
    select_layer(window, "Doomed")
    expect("the remove button is live with a layer selected",
           hierarchy.remove_layer.isEnabled(), True)
    no_modals()
    hierarchy.remove_layer.click()
    application.processEvents()
    expect("the layer is gone",
           "Doomed" in session.project.map("test").layer_names(), False)
    expect("nobody was asked", modals(), [])
    expect("and the status bar carries the affordance instead",
           "Ctrl+Z" in hierarchy.last_notice, True)
    window.undo()
    window.undo()
    expect("both steps unwind byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("the ONE confirmation that survives is the one undo cannot reach")
    # ----------------------------------------------------------------
    # Staged notes have never entered the command stream, so there is no
    # inverse to fall back on. Every other confirmation in the editor was
    # about something undo restores exactly, and said so in its own body.
    expect("the seam is the real dialog, not a stub left in the tree",
           [window.manifest.confirm is ask_module.confirm,
            window.hierarchy.confirm is ask_module.confirm,
            window.hierarchy.ask is ask_module.ask_form,
            window.inspector.view.ask is ask_module.ask_form,
            window.ask is ask_module.ask_form,
            # The window's own confirm, which `closeEvent` is the heaviest
            # caller of: a stub left on this seam in the shipped tree is a
            # close that answers its own question and loses the session.
            window.confirm is ask_module.confirm], [True] * 6)

    window.hierarchy.strip.field.setText("a note that has gone nowhere yet")
    window.hierarchy.strip.stage()
    application.processEvents()
    staged_before = len(session.manifest.notes)
    window.manifest.confirm = lambda *a, **k: False
    window.manifest._ManifestDock__on_unstage_all()
    expect("refusing it keeps every note",
           len(session.manifest.notes), staged_before)
    window.manifest.confirm = lambda *a, **k: True
    window.manifest._ManifestDock__on_unstage_all()
    expect("accepting it discards them", len(session.manifest.notes), 0)
    window.manifest.confirm = ask_module.confirm

    # ----------------------------------------------------------------
    print()
    print("no panel opens a modal of its own any more")
    # ----------------------------------------------------------------
    # The standing structural proof, and the thing that stops it growing
    # back: a check can only watch a seam it can replace, and every hard
    # `QMessageBox.x(...)` in a panel is a dialog no check can see.
    #
    # IT IS AN AST WALK NOW, AND THAT IS THE FIX. The predicate used to be
    # two regexes over source text, and a regex over source text is
    # beatable by anyone typing normally -- not by anyone hiding. Measured
    # against the ways a hand actually blocks a window, IT MISSED 14 OF 18,
    # with no false positives to show for the narrowness:
    #
    #     QMessageBox(self).exec()   QInputDialog.getText(...)
    #     QDialog(self).exec()       QFileDialog.getOpenFileName(...)
    #     self.__box().exec()        QColorDialog.getColor(...)
    #     dialog.open()              QFontDialog.getFont(...)
    #     box.exec ()                dialog.setModal(True); show()
    #     QMessageBox . warning()    getattr(dialog, 'exec')()
    #
    # A ")" before `.exec` was enough, so it could not see the constructor
    # form of the very class it was named after. AND ONE WAS LIVE: the tile
    # importer's Browse button has called `QFileDialog.getOpenFileName`
    # since it stopped being modal, in the panel de-exempted below on the
    # words "has to prove it blocks nothing at all", and the census
    # reported `[]` for it. Proof it was blind, before it was widened:
    # planting `QInputDialog.getText` and `QMessageBox(self).exec()` into
    # `editor/ui/prompt.py` -- a censused panel -- left this file at PASS,
    # exit 0.
    #
    # Nothing text-shaped could fix that: `getattr(dialog, 'exec')()`
    # spells `exec` in a string literal. So this reads CALLS, the way the
    # `refresh_all` order scan at the end of this file already does.

    #: Classes whose *static* helpers block. Any call on one of these names
    #: counts: they exist to open a window and wait, and maintaining a
    #: per-class method list is how `getSaveFileName` gets forgotten.
    BLOCKING_CLASSES = ("QMessageBox", "QInputDialog", "QFileDialog",
                        "QColorDialog", "QFontDialog")
    EXEC_NAMES = ("exec", "exec_")
    #: What a receiver has to be CALLED for `.open()` to count as a dialog
    #: being opened. Narrow on purpose: `editor/ui/script_editor.py` holds
    #: an inline `ArgumentForm` in a layout and calls `self.form.open(...)`
    #: four times, which is a panel method and not a modal -- a rule that
    #: flagged every `.open()` would report four dialogs that do not exist,
    #: and a census that cries wolf gets exempted and then sees nothing.
    DIALOG_WORDS = ("dialog", "dlg", "box", "msgbox", "messagebox", "popup",
                    "prompt", "picker", "chooser", "wizard")

    def _is_dialog_receiver(node) -> bool:
        """Does this expression name something a `.open()` would make modal."""
        if isinstance(node, ast.Call):
            return _is_dialog_receiver(node.func)
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        else:
            return False
        if name.startswith("Q") and (name.endswith("Dialog")
                                     or name in BLOCKING_CLASSES):
            return True
        lowered = name.lower().strip("_")
        return lowered in DIALOG_WORDS or lowered.split("_")[-1] in DIALOG_WORDS

    def modal_calls_in(text: str) -> list[str]:
        """Every call in this source that blocks or takes the window, sorted.

        FOUR SHAPES, because there are four ways to stop the author:

          * `.exec()` / `.exec_()` on ANY receiver expression -- a name, a
            constructor, a method call, or a `getattr` that spells the
            attribute in a string.
          * a static helper on one of `BLOCKING_CLASSES`.
          * `.open()` on something whose name says it is a dialog. Not
            blocking, window-MODAL: it takes the keyboard and returns, which
            is the same theft with a nicer stack trace.
          * `setModal(True)` / `setWindowModality(...)`, which is how a
            plain `show()` becomes one.

        Each is reported as `kind:receiver` or `Class.helper`, so a failure
        names the call rather than only its count. Sorted, so the expected
        sets below do not pin the order lines happen to sit in.

        COMMENTS AND PROSE CANNOT TRIP IT, structurally rather than by
        exclusion: the parser drops comments, and a docstring describing
        `dialog.exec()` is a string constant with no Call in it.
        """
        found: list[tuple[tuple[int, int], str]] = []

        def add(node, label: str) -> None:
            found.append(((node.lineno, node.col_offset), label))

        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (isinstance(func, ast.Call) and isinstance(func.func, ast.Name)
                    and func.func.id == "getattr" and len(func.args) >= 2
                    and isinstance(func.args[1], ast.Constant)
                    and func.args[1].value in EXEC_NAMES):
                add(node, f"exec:{ast.unparse(func.args[0])}")
                continue
            if not isinstance(func, ast.Attribute):
                continue
            attr, receiver = func.attr, ast.unparse(func.value)
            if attr in EXEC_NAMES:
                add(node, f"exec:{receiver}")
            elif receiver in BLOCKING_CLASSES:
                add(node, f"{receiver}.{attr}")
            elif attr == "open" and _is_dialog_receiver(func.value):
                add(node, f"open:{receiver}")
            elif attr == "setModal":
                # `setModal(False)` un-modals a window. Anything else --
                # True, or a variable this cannot read -- counts.
                if not (node.args and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value is False):
                    add(node, f"setModal:{receiver}")
            elif attr == "setWindowModality":
                if not (node.args
                        and ast.unparse(node.args[0]).endswith("NonModal")):
                    add(node, f"setWindowModality:{receiver}")
        return sorted(label for _where, label in found)

    def modal_calls(relative: str) -> list[str]:
        with open(os.path.join(REPO, relative), encoding="utf-8") as handle:
            return modal_calls_in(handle.read())

    # THE PLANTED DECOYS. Asserting the census comes back EMPTY over the
    # tree proves nothing about the predicate -- an instrument that always
    # answers "no" answers "no" for a panel full of modals too, which is
    # exactly how the planted call got through. So it is fed EIGHTEEN
    # spellings, in scratch strings owned by this file: the fourteen the
    # old regex missed and the four it caught, each with the label it must
    # come back under, so a widening that stops naming the receiver is a
    # failure too.
    BLOCKING = (
        ("QMessageBox(self).exec()", "exec:QMessageBox(self)"),
        ("QDialog(self).exec()", "exec:QDialog(self)"),
        ("self.__box().exec()", "exec:self.__box()"),
        ("dialog.open()", "open:dialog"),
        ("dialog.setModal(True)\ndialog.show()", "setModal:dialog"),
        ("QMessageBox . warning(self, 't', 'b')", "QMessageBox.warning"),
        ("box.exec ()", "exec:box"),
        ("getattr(dialog, 'exec')()", "exec:dialog"),
        ("QInputDialog.getText(self, 't', 'label')", "QInputDialog.getText"),
        ("QFileDialog.getOpenFileName(self, 'Open')",
         "QFileDialog.getOpenFileName"),
        ("QColorDialog.getColor(parent=self)", "QColorDialog.getColor"),
        ("QFontDialog.getFont(parent=self)", "QFontDialog.getFont"),
        ("d.setWindowModality(Qt.ApplicationModal)\nd.show()",
         "setWindowModality:d"),
        ("QInputDialog.getInt(self, 't', 'l')", "QInputDialog.getInt"),
        ("QFileDialog.getSaveFileName(self, 'Save')",
         "QFileDialog.getSaveFileName"),
        ("QMessageBox.warning(self, 'x', 'y')", "QMessageBox.warning"),
        ("dialog.exec()", "exec:dialog"),
        ("menu.exec(at)", "exec:menu"),
    )
    expect("the census sees every one of the eighteen ways to block",
           [source for source, _label in BLOCKING if not modal_calls_in(source)],
           [])
    expect("...and names each one by its receiver, not merely by its count",
           [modal_calls_in(source) for source, _label in BLOCKING],
           [[label] for _source, label in BLOCKING])

    # THE FALSE-POSITIVE HALF, and it matters as much: a census that cries
    # wolf gets exempted, and an exempted census sees nothing. Every line
    # here is something the tree really contains -- prose about the rule in
    # `editor/ui/object_editor.py`, `self.form.open(...)` four times in
    # `editor/ui/script_editor.py`, and a plain builtin `open`.
    CLEAN = ("# this check fails on any `.exec()` it finds here\n",
             "'''prose about dialog.exec() and QInputDialog.getText'''\n",
             "self.form.open('t', rows, ok_label='Insert')\n",
             "handle = open(path, encoding='utf-8')\n",
             "dialog.setModal(False)\n",
             "view.setWindowModality(Qt.NonModal)\n")
    expect("...and fires on none of the six ways it must not",
           {line: modal_calls_in(line) for line in CLEAN
            if modal_calls_in(line)}, {})

    # A module may open a modal ONLY if it exposes a seam a check can
    # replace -- that is the whole property, and it is why the exclusion
    # below is a single name rather than a convenience. `ask.py` is the one
    # DIALOG module: opening one is its job, and it is asserted replaceable
    # just below, so excluding it is earned rather than assumed.
    # `main_window.py` keeps the genuine stops.
    #
    # `canvas.py` is NOT exempt any more either. It was excused to
    # `check_collision_mount.py`, which stubs `QMessageBox` and has never
    # looked at `exec` at all -- and while it was excused the canvas grew
    # `menu.exec(at)` on the right-click path, which is a blocking call in
    # the file the census was told not to read. It reads it now.
    #
    # `tileset_dialog.py` is NOT exempt any more, and that is the point: the
    # tile importer used to be exempt on the strength of a replaceable
    # `ask()` that called `exec()`. It is a non-modal window now, so it goes
    # into the census below with every other panel and has to prove it
    # blocks nothing at all.
    DIALOG_MODULES = ("ask.py", )
    panels = sorted(
        name for name in os.listdir(os.path.join(REPO, "editor", "ui"))
        if name.endswith(".py")
        and name not in DIALOG_MODULES + ("main_window.py", ))
    expect("the canvas is one of the panels the census reads",
           "canvas.py" in panels, True)

    # NO EXEMPTION AT ALL, AND THAT IS NEW. This carried exactly one on
    # 2026-09-04 -- `tileset_dialog.py: QFileDialog.getOpenFileName`, Browse
    # on the tile importer -- written down by file and by call because there
    # is no way to pick a file without the platform picker. The exemption
    # named the thing that would retire it, `ask.choose_file(parent, title,
    # start, filters) -> str`, and that primitive now exists: both pickers
    # in the tree (Browse, and Apply a response in the window) call it, and
    # the census is empty for every panel with nothing written down.
    census = {name: modal_calls(f"editor/ui/{name}") for name in panels}
    expect("no panel opens a dialog of its own -- and there is no longer an "
           "exemption for any of them",
           {name: got for name, got in census.items() if got}, {})
    # WHERE THE PICKER WENT, asserted rather than assumed. "No panel opens
    # one" is satisfied just as well by a Browse button that stopped
    # working, so the call has to be found at its new address.
    expect("ask.py owns every question in the tree, the file picker included",
           modal_calls("editor/ui/ask.py"),
           ["QFileDialog.getOpenFileName", "QMessageBox.question",
            "exec:dialog"])
    # THE EARNED HALF of the exclusion. A dialog module is exempt from the
    # census because a check can substitute its opener; that is a claim, so
    # it is asserted rather than trusted, or "it is a dialog module" becomes
    # a way to smuggle an unreplaceable modal back in. Named explicitly,
    # because the two seams have different SHAPES -- ask.py exposes
    # module-level functions that panels call, tileset_dialog.py an instance
    # attribute on the widget -- and a generic "has something callable"
    # probe would pass for any module and prove nothing.
    SEAMS = {"ask.py": ("editor.ui.ask", None,
                        ("ask_form", "choose_file", "confirm"))}
    for name in DIALOG_MODULES:
        dotted, owner, attrs = SEAMS[name]
        module = importlib.import_module(dotted)
        holder = getattr(module, owner) if owner else module
        expect(f"{name} exposes the replaceable opener that exempts it from "
               f"the census", [a for a in attrs
                               if callable(getattr(holder, a, None))],
               list(attrs))
    # The other half. Three unexpected-exception stops remain deliberately:
    # a rejection is designed, but these are not, and the alternative is
    # carrying on with work at risk. The window's own `exec:dialog` is the
    # settings dialog, which is a decision and opens on an explicit menu
    # pick -- and so is the `getOpenFileName` behind Apply a response, which
    # the widened census can see for the first time.
    expect("and the window keeps exactly its four genuine stops",
           modal_calls("editor/ui/main_window.py"),
           ["QMessageBox.critical"] * 3 + ["exec:dialog"])
    # THE PICKER LEFT THE WINDOW TOO, and it is asserted by the SEAM rather
    # than by the count above: a window that simply deleted Apply-a-response
    # would satisfy the count. `EditorWindow.choose_file` is an instance
    # attribute for the same reason `self.ask` and `self.confirm` are --
    # the widened census found this call for the first time on 2026-09-04,
    # after it had been unseeable for as long as the menu entry existed.
    seam = getattr(window, "choose_file", None)
    expect("...and its own file picker is a replaceable seam now, not an "
           "inline modal", (callable(seam), seam is ask_module.choose_file),
           (True, True))

    # ----------------------------------------------------------------
    print()
    print("Browse on the tile importer is a seam, not a wall")
    # ----------------------------------------------------------------
    # THE ACHIEVABLE HALF of the exemption above, driven rather than
    # asserted about. The button is CLICKED, so this measures the wire
    # from `browse_button` to `set_image_path` and not a function that
    # nothing calls -- and it returns, which is the whole point: under the
    # unreplaced `QFileDialog.getOpenFileName` this line would sit there
    # until the 600s timeout, exit code HANG, indistinguishable from a slow
    # machine (law 13).
    from editor.ui.tileset_dialog import TilesetImportDialog     # noqa: E402

    importer = TilesetImportDialog(os.path.join(workspace, "data", "maps"),
                                   parent=window)
    expect("the picker is a replaceable attribute on the widget",
           callable(getattr(importer, "choose_file", None)), True)

    asked_for: list = []
    importer.choose_file = lambda parent, start: (
        asked_for.append(start) or "C:/art/sheet.png")
    no_modals()
    importer.browse_button.click()
    application.processEvents()
    expect("clicking Browse asks the seam, starting beside the map",
           (asked_for, importer.image_path),
           ([os.path.join(workspace, "data", "maps")], "C:/art/sheet.png"))
    expect("...and it opened no dialog this check could not see", modals(), [])

    # THE CANCEL HALF. An empty answer is a cancel, and a cancel that wiped
    # the path field would throw away a sheet the author had already loaded
    # for the sin of opening the picker and changing their mind.
    importer.choose_file = lambda parent, start: ""
    importer.browse_button.click()
    application.processEvents()
    expect("cancelling Browse leaves the sheet that was already chosen",
           importer.image_path, "C:/art/sheet.png")
    importer.close()
    importer.deleteLater()
    application.processEvents()

    # ----------------------------------------------------------------
    print()
    print("the form dialog itself: one decision, and OK means something")
    # ----------------------------------------------------------------
    # Built and inspected rather than exec()'d -- a check must never block
    # on a modal (law 13), and everything above stubs the seam, so this is
    # the only place the real widget is measured.
    from editor.core.inspect import Field                          # noqa: E402

    form = ask_module.QuickForm(
        "New property", [Field("key", "Name", "str", ""),
                         Field("kind", "Holds", "choice", "int",
                               choices=("str", "int", "float", "bool"))],
        window)
    ok_button = form.buttons.button(
        type(form.buttons).StandardButton.Ok)
    expect("OK is dead while a required text row is blank",
           ok_button.isEnabled(), False)
    form.editors["key"].setText("hp")
    expect("and comes alive as soon as it is not",
           ok_button.isEnabled(), True)
    expect("the closed choice is not typeable",
           form.editors["kind"].isEditable(), False)
    expect("and both halves of the decision come back together",
           form.value(), {"key": "hp", "kind": "int"})
    form.deleteLater()

    # ----------------------------------------------------------------
    print()
    print("the database is a real window, generated from the genre")
    # ----------------------------------------------------------------
    window.open_database()
    application.processEvents()
    expect("it has a tab per declared table",
           sorted(window.database.pages), ["actors", "equipment", "items"])
    page = window.database.pages["actors"]
    expect("an uncreated table says so", page.exists, False)

    # A button that cannot act must LOOK like it cannot act. All three row
    # buttons early-return when the table does not exist -- which on a fresh
    # project is always -- so enabled, they are dead clicks with no feedback.
    expect("+ is disabled before the table exists",
           page.add_button.isEnabled(), False)
    expect("and its tooltip says why",
           "create the actors table first" in page.add_button.toolTip(), True)
    expect("Duplicate is disabled too", page.duplicate_button.isEnabled(), False)
    expect("and remove", page.remove_button.isEnabled(), False)

    page._TablePage__on_create()
    application.processEvents()
    expect("creating it worked", session.project.has_table("actors"), True)
    expect("+ is live once the table exists", page.add_button.isEnabled(), True)
    expect("but Duplicate still needs a selected row",
           page.duplicate_button.isEnabled(), False)
    expect("and says so",
           "select a row" in page.duplicate_button.toolTip(), True)

    window.run(Command("table.row.add", Scope.of(("table", "actors")),
                       {"id": "hero", "values": {"display_name": "Hero"}}))
    window.database.refresh()
    application.processEvents()
    expect("the row appears in the list", page.list.count(), 1)
    expect("and the detail form is showing it",
           page.view.inspection.heading, "hero")
    expect("Duplicate and remove came alive with a selection",
           (page.duplicate_button.isEnabled(), page.remove_button.isEnabled()),
           (True, True))

    row_fields = {f.key: f for section in page.view.inspection.sections
                  for f in section.fields}
    expect("every genre column is a field", len(row_fields), 8)
    window.run(row_fields["hp"].emit(42))
    expect("editing a field changed the row",
           session.project.table("actors").rows["hero"]["hp"], 42)
    window.undo()
    expect("and it undoes",
           session.project.table("actors").rows["hero"]["hp"], 10)

    # A row id is a file-format string -- nothing can infer it and getting it
    # wrong is expensive -- so ASKING is legitimate here. Asking through the
    # seam is what makes it drivable.
    page.ask = lambda *a, **k: {"id": "villain"}
    no_modals()
    page.add_button.click()
    application.processEvents()
    expect("the new row landed",
           "villain" in session.project.table("actors").rows, True)
    expect("and no message box was involved", modals(), [])
    window.undo()

    # Deleting a row asks nothing: it is undoable, and the button is disabled
    # unless a row is selected, so the click cannot be a slip.
    statuses: list[str] = []
    page.status_requested.connect(statuses.append)
    window.database.refresh()
    application.processEvents()
    no_modals()
    page.remove_button.click()
    application.processEvents()
    expect("the row is gone", "hero" in session.project.table("actors").rows,
           False)
    expect("nobody was asked about the row", modals(), [])
    expect("and the status names the way back",
           bool(statuses) and "Ctrl+Z" in statuses[0], True)

    # ...and Ctrl+Z has to WORK in this window, or that line is a lie. Qt
    # shortcuts are per-window and the undo action lives on the editor.
    database_undo = next(
        (a for a in window.database.findChildren(QAction)
         if a.shortcut().toString() == "Ctrl+Z"), None)
    expect("the Database window carries its own Ctrl+Z",
           database_undo is not None, True)
    database_undo.trigger()
    application.processEvents()
    expect("and it reaches the one command stream",
           "hero" in session.project.table("actors").rows, True)

    # ----------------------------------------------------------------
    print()
    print("prompt strips carry their own panel's scope")
    # ----------------------------------------------------------------
    select_layer(window, "Floor")
    window.hierarchy.strip.field.setText("this layer needs a market square")
    window.hierarchy.strip.stage()
    window.problems.strip.field.setText("what should happen on a bad map?")
    window.problems.strip.kind.setCurrentText("question")
    window.problems.strip.stage()
    application.processEvents()
    expect("two notes staged", len(session.manifest.notes), 2)
    expect("each on its own panel's scope",
           sorted(str(n.scope) for n in session.manifest.notes),
           ["map:test/layer:Floor", "project"])
    expect("and their kinds survived",
           sorted(n.kind for n in session.manifest.notes),
           ["change", "question"])

    # ----------------------------------------------------------------
    print()
    print("shipping and applying a response use the same door")
    # ----------------------------------------------------------------
    # Two doors onto one action, so they must agree: the menu entry greys
    # itself in the state the Manifest dock's own Ship button does, rather
    # than staying enabled and answering with a "Nothing staged" box.
    session.manifest.clear()
    window.refresh_manifest()
    expect("Ship is greyed with nothing staged",
           window.ship_action.isEnabled(), False)
    expect("and says what to do first",
           "type a note" in window.ship_action.toolTip(), True)
    no_modals()
    window.ship()                       # only reachable by calling it
    expect("calling it anyway reports rather than popping a box", modals(), [])
    expect("where the author is looking",
           "nothing is staged" in window.statusBar().currentMessage(), True)

    window.problems.strip.field.setText("a note to ship")
    window.problems.strip.stage()
    window.refresh_manifest()
    expect("staging one brings Ship back", window.ship_action.isEnabled(), True)

    bundles: list = []
    real_ship = session.ship
    session.ship = lambda **k: (bundles.append(real_ship(**k)), bundles[-1])[1]
    window.ask = lambda *a, **k: {"title": "ui smoke"}
    no_modals()
    window.ship()
    session.ship, window.ask = real_ship, ask_module.ask_form
    bundle = bundles[-1]
    expect("shipping asked for a title and opened nothing else", modals(), [])
    expect("the bundle exists", os.path.isdir(bundle.directory), True)
    expect("and the four-line 'Request written' box is a Problems row now",
           any("BRIEF.md" in row for row in problem_rows()), True)

    with open(bundle.response_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({
            "verb": "table.row.set", "scope": "table:actors/row:hero",
            "args": {"column": "hp", "value": 55}}) + "\n")

    # A file APPEARING is news, not a question. This was the only modal in
    # the tree that could open with no gesture from the author at all: a
    # QFileSystemWatcher fired it, so it could land on top of an
    # in-progress stroke and take the mouse button with it.
    no_modals()
    window._EditorWindow__offer(bundle.response_path)
    application.processEvents()
    expect("an arriving response interrupts nothing", modals(), [])
    expect("it is announced in the Problems dock",
           any("has a response waiting" in row for row in problem_rows()), True)
    expect("and remembered, so the menu can find it again",
           window.pending_response, bundle.response_path)
    expect("nothing was applied behind the author's back",
           session.project.table("actors").rows["hero"]["hp"], 10)

    # Applying it IS a decision -- someone else's command list, against the
    # author's project -- so this one still asks, through the seam.
    questions: list[str] = []
    window.confirm = lambda _p, title, _body: questions.append(title) or True
    window.apply_response(bundle.response_path)
    application.processEvents()
    expect("it asked before applying", questions, ["Apply response"])
    expect("the response applied",
           session.project.table("actors").rows["hero"]["hp"], 55)
    expect("recorded as coming from a response",
           session.history()[-1].source, f"response:{bundle.identifier}")
    expect("and the waiting notice retired itself",
           [row for row in problem_rows() if "has a response waiting" in row],
           [])
    expect("as did the pending path", window.pending_response, None)
    window.undo()

    # `confirm_response` is declared in settings.py and rendered in the
    # settings dialog, so it has to be READ here. Both halves, since a
    # preference that changes nothing is the same disease one layer down.
    window.settings.set("confirm_response", False)
    questions.clear()
    no_modals()
    with open(bundle.response_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({
            "verb": "table.row.set", "scope": "table:actors/row:hero",
            "args": {"column": "hp", "value": 77}}) + "\n")
    window._EditorWindow__offer(bundle.response_path)
    application.processEvents()
    expect("unticked, an arriving response applies itself",
           session.project.table("actors").rows["hero"]["hp"], 77)
    expect("and asks nobody anything", questions + modals(), [])
    window.settings.set("confirm_response", True)
    window.confirm = ask_module.confirm
    window.undo()

    # A REFUSAL IS NOT A PARSE ERROR, and the window used to call it one.
    # `read_response` gates a SCOPED bundle -- the verbs it shipped, at the
    # addresses it declared -- and every refusal arrived here as "<file> is
    # not a readable response", which is wrong about the one thing a reader
    # needs: the file parsed perfectly, and what happened is that the answer
    # reached somewhere the bundle never promised.
    #
    # This is also the door that matters. `EditorWindow.apply_response` does
    # NOT call `Session.apply_response`: it does its own `read_response` and
    # its own `run`, so it is the path the author clicks and the reason the
    # gate lives one call further down.
    # NOT `asked`: this file already owns a module-level `asked`
    # bucket, and shadowing it turns `no_modals()` into a crash.
    scoped_dir = session.ask("map:test/layer:Floor",
                             "widen this floor")
    outside = os.path.join(scoped_dir, "response.jsonl")
    with open(outside, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({
            "verb": "table.row.set", "scope": "table:actors/row:hero",
            "args": {"column": "hp", "value": 99}}) + "\n")
    before = session.project.table("actors").rows["hero"]["hp"]
    depth = len(session.history())
    no_modals()
    window.apply_response(outside)
    application.processEvents()
    refusal = [row for row in problem_rows() if "was refused" in row]
    expect("a response reaching outside its bundle's scope is REFUSED, and "
           "the window says refused rather than unreadable",
           (len(refusal) == 1,
            any("not a readable response" in row for row in problem_rows())),
           (True, False))
    expect("...naming the address it reached for and the address it was cut "
           "for", ("table:actors/row:hero" in refusal[0],
                   "map:test/layer:Floor" in refusal[0]), (True, True))
    expect("...and NOTHING was applied, and nothing was asked",
           (session.project.table("actors").rows["hero"]["hp"],
            len(session.history()), modals()), (before, depth, []))

    # THE OTHER HALF, and it is what stops the arm above from swallowing
    # every fault into one word: a file that really is unreadable still says
    # so, in the sentence that was always right for it.
    with open(outside, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("this is not json at all\n")
    window.apply_response(outside)
    application.processEvents()
    expect("...while a file that genuinely will not parse is still reported "
           "as unreadable, not as a scope refusal",
           (any("not a readable response" in row for row in problem_rows()),
            len(session.history())), (True, depth))
    window.clear("response")

    # ----------------------------------------------------------------
    print()
    print("revealing code never raises, even with no IDE")
    # ----------------------------------------------------------------
    from editor.core import ide

    real_detect, real_open = ide.detect, ide.open_at
    try:
        ide.detect = lambda **k: []
        ide.open_at = lambda *a, **k: ide.LaunchResult(False, "no IDE (test)")
        window.reveal("main.py")
        window.reveal("scripts/core/component.py", symbol="GameComponent")
        print("  ok   reveal() with no IDE installed did not raise")
    except Exception as exc:                                    # noqa: BLE001
        print(f"  FAIL reveal() raised {type(exc).__name__}: {exc}")
        failures.append("reveal")
    finally:
        ide.detect, ide.open_at = real_detect, real_open

    expect("a symbol's line is found without importing it",
           ide.find_symbol_line(
               os.path.join(REPO, "scripts", "core", "component.py"),
               "GameComponent") is not None, True)

    # ----------------------------------------------------------------
    print()
    print("refreshing never orphans a widget into a top-level window")
    # ----------------------------------------------------------------
    # `widget.setParent(None)` does not detach a widget in Qt, it PROMOTES it
    # to a top-level window, and `deleteLater()` only runs once the event loop
    # unwinds -- so clearing a layout that way both flashes orphan windows and
    # accumulates them (law 12). Counting top-levels is the cheapest way to
    # make that impossible to reintroduce, in any panel.
    def top_levels():
        return len([w for w in QApplication.topLevelWidgets()
                    if w is not window and w.parent() is None])

    window.selection.select(Scope.of(("map", "test"), ("layer", "Floor")))
    application.processEvents()
    at_rest = top_levels()
    window.run(Command("map.tile.set", Scope.parse("map:test/layer:Floor"),
                       {"x": 1, "y": 1, "gid": 70}))
    application.processEvents()
    after_edit = top_levels()
    window.undo()
    application.processEvents()
    after_undo = top_levels()
    window.redo()
    application.processEvents()
    # All three have to be the same number, and printing all three is what
    # makes a regression readable rather than a bare False.
    print(f"       top-level widgets: at rest {at_rest}, after an edit "
          f"{after_edit}, after an undo {after_undo}")
    expect("an edit orphans nothing", after_edit, at_rest)
    expect("and neither does an undo", after_undo, at_rest)
    settled = top_levels()

    peak = settled
    import editor.ui.fields as fields_module
    original_show = fields_module.InspectionView.show_inspection

    def watched(self, inspection):
        # `global`, not `nonlocal`: this file is a script, so `peak` lives at
        # module scope and there is no enclosing function to bind to.
        global peak
        original_show(self, inspection)
        peak = max(peak, top_levels())

    fields_module.InspectionView.show_inspection = watched
    try:
        for _ in range(12):
            window.undo()
            application.processEvents()
            window.redo()
            application.processEvents()
    finally:
        fields_module.InspectionView.show_inspection = original_show

    expect("no orphan appears mid-rebuild", peak <= settled, True)
    expect("and none accumulate over 12 undo/redo cycles",
           top_levels() <= settled, True)
    window.undo()

    # ----------------------------------------------------------------
    print()
    print("a field never outlives its own signal (heap-corruption guard)")
    # ----------------------------------------------------------------
    # `setWidget()` DELETES the old body synchronously, so toggling a
    # checkbox emits a command, which refreshes, which frees that very
    # checkbox while its `toggled` signal is still on the stack -- Qt then
    # returns into freed memory (0xC0000374, STATUS_HEAP_CORRUPTION; law 12).
    # Deferring the free with deleteLater() is the fix. Asserted together with
    # the orphan-window guard above, since the naive cure for either one is
    # the cause of the other.
    from PySide6.QtWidgets import QCheckBox                       # noqa: E402

    window.selection.select(Scope.of(("map", "test"), ("layer", "Floor")))
    application.processEvents()
    boxes = window.inspector.view.findChildren(QCheckBox)
    expect("the layer inspector offers boolean capabilities",
           len(boxes) > 0, True)

    box = boxes[-1]
    destroyed_synchronously = []
    box.destroyed.connect(lambda *_a: destroyed_synchronously.append(1))
    box.setChecked(not box.isChecked())
    still_alive = True
    try:
        box.isChecked()
    except RuntimeError:
        still_alive = False
    expect("the widget survives emitting its own command", still_alive, True)
    expect("its destruction was deferred, not synchronous",
           destroyed_synchronously, [])
    application.processEvents()
    expect("the command still landed",
           "pyoneer_" in "".join(session.project.map("test")
                                 .tile_layer("Floor").properties.keys()), True)
    window.undo()
    application.processEvents()
    expect("and undoing it leaves the map byte-identical",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("settings are typed, validated, and survive a round trip")
    # ----------------------------------------------------------------
    from editor.core.settings import SETTINGS, EditorSettings      # noqa: E402

    store = EditorSettings(FakeStore())
    # DERIVED from each setting's own declared type, not a list written
    # out here. A hardcoded row per setting says nothing about coercion
    # and everything about how recently someone added a preference: this
    # assertion went red for a bool that was added correctly. What it is
    # actually for is that the STORE hands back the type the declaration
    # promises, through a backend that returns everything as text.
    expect("defaults come back typed",
           [type(store.get(s.key)).__name__ for s in SETTINGS],
           [s.type for s in SETTINGS])
    store.set("show_grid", False)
    expect("a bool survives a text backend", store.get("show_grid"), False)
    store.set("show_grid", True)
    expect("and back again", store.get("show_grid"), True)
    store.set("theme", "dark")
    expect("a choice round-trips", store.get("theme"), "dark")
    store.set("theme", "banana")
    expect("a value outside the choices falls back to the default",
           store.get("theme"), "system")
    # An INT setting is validated against its choices too, not just a str
    # one: any number coming straight back includes 0, which is a
    # ZeroDivisionError in the code that turns a pixel into a cell. Both
    # halves, because a fallback that cannot fire is not a fallback.
    store.set("grid_step", 4)
    expect("an int choice round-trips as an int", store.get("grid_step"), 4)
    store._backend.setValue("grid_step", 0)
    expect("a stored 0 is refused and falls back to the default",
           store.get("grid_step"), 1)
    store._backend.setValue("grid_step", 7)
    expect("so is a number that is simply not one of the choices",
           store.get("grid_step"), 1)
    store._backend.setValue("grid_step", "banana")
    expect("and so is something that is not a number at all",
           store.get("grid_step"), 1)
    # The same validation, on the setting that decides what a NEW passability
    # layer costs. A stored 3 is not a rounding question: it is a factor no
    # 16px tile divides, and 0 is the ZeroDivisionError above wearing another
    # key. Both halves again, and the fallback matters more here than for the
    # grid -- this one reaches `paint_unit`, so a nonsense value would move
    # every cell a click addresses rather than only the lines drawn over it.
    store.set("collision_subcell", 4)
    expect("the collision resolution round-trips as an int",
           store.get("collision_subcell"), 4)
    store._backend.setValue("collision_subcell", 3)
    expect("a factor outside the choices falls back to one mask per tile",
           store.get("collision_subcell"), 1)
    store._backend.setValue("collision_subcell", 0)
    expect("...and so does a stored 0", store.get("collision_subcell"), 1)
    store.reset()
    expect("reset restores every default", store.as_dict()["show_grid"], True)
    expect("including the grid spacing", store.as_dict()["grid_step"], 1)
    expect("and the collision resolution, which is 1 because finer is not "
           "free", store.as_dict()["collision_subcell"], 1)

    try:
        store.get("nonexistent")
        expect("an unknown setting is refused", False, True)
    except KeyError:
        print("  ok   an unknown setting raises rather than returning None")

    # The dialog is generated from SETTINGS, so an int setting has to survive
    # the trip through a combo box's item data as an INT: authored as a
    # string, `findData` against an int misses and the combo shows its first
    # entry however the preference is actually set.
    from editor.ui.settings_dialog import SettingsDialog            # noqa: E402
    from PySide6.QtWidgets import QComboBox                         # noqa: E402

    def shown(key):
        dialog = SettingsDialog(store, window)
        try:
            return dialog.findChild(QComboBox, f"setting:{key}").currentData()
        finally:
            dialog.deleteLater()

    store.set("grid_step", 4)
    expect("the dialog shows the stored int, not the first entry",
           shown("grid_step"), 4)
    store.set("grid_step", 1)
    expect("and follows it back down", shown("grid_step"), 1)
    expect("a str setting still round-trips through the same field",
           (store.set("theme", "dark"), shown("theme"))[1], "dark")
    store.reset()

    # And it has to REACH the canvas, through the one preference store and
    # no other route. Driven through the slot `open_settings` connects the
    # dialog's `changed` signal to, because that is the only path a real
    # change takes.
    apply_setting = window._EditorWindow__on_setting_changed
    window.canvas.grid_step = 1
    before_click = window.canvas.cell_at(17.0, 33.0)
    apply_setting("grid_step", 4)
    expect("changing the preference reaches the canvas",
           window.canvas.grid_step, 4)
    expect("and STILL changes nothing about what a click addresses",
           window.canvas.cell_at(17.0, 33.0), before_click)
    apply_setting("grid_step", 1)
    expect("and back down again", window.canvas.grid_step, 1)

    # And the sub-cell control, which is the OPPOSITE of the line above and
    # deliberately so: it is the resolution a companion CREATED by the next
    # collision stroke is given, so it has to reach `paint_unit` and move
    # what a click addresses. It is also the only human route to
    # `map.layer.add subcell=N`, and no verb re-scales a companion afterwards.
    expect("the dialog offers the collision resolution as a real field",
           shown("collision_subcell"), 1)
    window.canvas.collision_subcell = 1
    apply_setting("collision_subcell", 4)
    expect("changing the preference reaches the canvas",
           window.canvas.collision_subcell, 4)
    apply_setting("collision_subcell", 1)
    expect("and back down again", window.canvas.collision_subcell, 1)

    # AND IT HAS TO BE READ AT BOOT, which is a separate wire from the one
    # above: a preference the dialog can change and the next launch forgets
    # is a preference that works exactly once. Driven by constructing a
    # SECOND window against a store that
    # already holds the value, because `EditorSettings()` is built inside
    # `__init__` and there is no other seam onto that moment.
    import editor.ui.main_window as main_window_module               # noqa: E402

    boot_store = EditorSettings(FakeStore())
    boot_store.set("collision_subcell", 4)
    boot_store.set("grid_step", 8)
    _real_settings = main_window_module.EditorSettings
    main_window_module.EditorSettings = lambda: boot_store
    try:
        booted = EditorWindow(session)
    finally:
        main_window_module.EditorSettings = _real_settings
    expect("a freshly opened window reads the stored collision resolution",
           booted.canvas.collision_subcell, 4)
    expect("...and the stored grid spacing beside it, which nothing covered "
           "either", booted.canvas.grid_step, 8)
    # Closing a dirty window now OFFERS TO SAVE (`EditorWindow.closeEvent`),
    # so a teardown that did not answer would write this fixture out from
    # under every assertion after it -- including the byte-identical
    # comparisons against ORIGINAL. "No" is the answer a teardown wants: it
    # closes and writes nothing, which is what `close()` did before the
    # feature existed. The same three words appear at every teardown close
    # in this file for the same reason.
    booted.confirm = lambda *a, **k: False
    booted.close()
    booted.deleteLater()
    application.processEvents()

    # ----------------------------------------------------------------
    print()
    print("switching theme repaints the window AND re-inks the icons")
    # ----------------------------------------------------------------
    from PySide6.QtGui import QPalette                             # noqa: E402
    from editor.ui import icons as icons_module                    # noqa: E402
    from editor.ui.theme import Theme                              # noqa: E402

    def ink_of(icon):
        """Sample the drawn glyph so a theme change is measured, not assumed."""
        image = icon.pixmap(22, 22).toImage()
        total, count = 0, 0
        for y in range(image.height()):
            for x in range(image.width()):
                pixel = image.pixelColor(x, y)
                if pixel.alpha() > 200:
                    total += pixel.lightness()
                    count += 1
        return total / count if count else -1

    window.apply_theme(Theme.LIGHT)
    application.processEvents()
    light_window = application.palette().color(QPalette.Window).lightness()
    light_ink = ink_of(icons_module.tool_icon("brush"))

    window.apply_theme(Theme.DARK)
    application.processEvents()
    dark_window = application.palette().color(QPalette.Window).lightness()
    dark_ink = ink_of(icons_module.tool_icon("brush"))

    expect("the window palette actually darkened", dark_window < light_window,
           True)
    # Ink must move the OPPOSITE way to the background, or a hardcoded
    # near-white glyph vanishes on a light theme.
    expect("and the icon ink moved the other way", dark_ink > light_ink, True)
    expect("dark mode uses a style that honours the palette",
           application.style().objectName(), "fusion")

    window.apply_theme(Theme.LIGHT)
    application.processEvents()
    expect("every tool still has a non-null icon",
           [t.value for t in Tool
            if icons_module.tool_icon(t.value).isNull()], [])

    # ----------------------------------------------------------------
    print()
    print("a menu entry that cannot act is greyed with a reason")
    # ----------------------------------------------------------------
    # "Copy the art brief" greys itself for a genre that ships no ART.md
    # rather than answering with a modal. Both directions, because a control
    # asserted only in its disabled state is how the Database's buttons
    # shipped broken.
    pack = session.project.genre
    expect("live for a genre that ships one",
           window.art_action.isEnabled(), True)
    session.project.genre = dataclasses.replace(pack, art_brief="")
    window.refresh_all()
    expect("greyed for a genre that does not",
           window.art_action.isEnabled(), False)
    expect("and it names the genre rather than shrugging",
           "ships no ART.md" in window.art_action.toolTip(), True)
    no_modals()
    window.copy_art_brief()
    expect("calling it anyway says so without a box", modals(), [])
    session.project.genre = pack
    window.refresh_all()

    # ----------------------------------------------------------------
    print()
    print("a tileset can be added from the GUI at all")
    # ----------------------------------------------------------------
    # The importer needs a door, or `map.tileset.add` has no way into the
    # editor at all and every path that needs a tileset grows its own
    # importer. There are two doors now -- the menu and the palette's own
    # button -- and both are asserted to reach the same one window.
    expect("the action exists and is live with a map open",
           window.add_tileset_action.isEnabled(), True)
    no_modals()
    window.add_tileset_action.trigger()
    application.processEvents()
    view = window.tileset_import
    expect("triggering it opened the importer", view is not None, True)
    # THE PROPERTY RULE 11 IS ABOUT, asserted rather than described: a
    # blocking dialog would never have returned from `trigger()` above, so
    # reaching this line at all is half of it, and the window being visible
    # while the editor is still usable is the other half.
    expect("...as a NON-MODAL window, with the editor still live",
           (view.isVisible(), view.isModal(), window.isEnabled()),
           (True, False, True))
    expect("...and it asked nothing on the way", modals(), [])

    # The palette's button is the same door, not a second one.
    window.palette.add_button.click()
    application.processEvents()
    expect("the palette's own button reaches the same window",
           window.tileset_import is view, True)

    # A REAL IMPORT, driven the way a human drives it: point at a sheet,
    # take the whole thing, press Add.
    view.set_image_path(os.path.join(REPO, "data", "art", "tilesets",
                                     "System", "TileC.png"))
    view.set_name("probe")
    view.refresh()
    expect("a readable sheet makes Add live",
           (view.problem(), view.add_button.isEnabled()), (None, True))
    view.add_button.click()
    application.processEvents()
    expect("pressing Add declared the tileset",
           "probe" in session.project.map("test").tileset_names(), True)
    expect("through the command stream, as one transaction",
           [c.verb for c in session.history()[-1].commands],
           ["map.tileset.add"])
    expect("and asked nothing", modals(), [])
    expect("the view STAYS OPEN for the next region",
           view.isVisible(), True)
    expect("...knowing the name it just used is taken, with the reason",
           view.problem(), "This map already has a tileset named 'probe'.")
    window.undo()
    expect("one undo takes it back byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)
    # The other side of that, and the reason the view is TOLD rather than
    # left to tally: undo frees the name again, and a view keeping its own
    # count would go on refusing one the author had just taken back.
    expect("...and undo frees the name again",
           (view.problem(), view.add_button.isEnabled()), (None, True))

    # The other half: a view that emits nothing runs nothing at all.
    before_cancel = len(session.history())
    view.close()
    application.processEvents()
    expect("closing it changes nothing",
           len(session.history()), before_cancel)
    expect("...and the window forgets it, so the door opens again",
           window.tileset_import, None)

    # ----------------------------------------------------------------
    print()
    print("F5 saves and plays; it does not ask the same question every time")
    # ----------------------------------------------------------------
    # "The game reads files from disk. Save before playing?" -- no default
    # button, no remember, on the most repeated action in the loop, and the
    # answer is the same every time. The editor knows the game reads from
    # disk and knows the session is dirty, so it saves.
    launched: list = []
    real_popen = main_window_module.subprocess.Popen
    main_window_module.subprocess.Popen = \
        lambda *a, **k: launched.append(a) or None
    entry = os.path.join(workspace, "main.py")
    with open(entry, "w", encoding="utf-8") as handle:
        handle.write("")
    try:
        window.run(Command("map.tile.set", Scope.parse("map:test/layer:Floor"),
                           {"x": 2, "y": 2, "gid": 70}))
        expect("the session is dirty before playing", session.dirty, True)
        no_modals()
        window.play()
        expect("F5 asked nothing", modals(), [])
        expect("it saved first", session.dirty, False)
        expect("and launched the game", len(launched), 1)
        expect("saying both in one line",
               "saved" in window.statusBar().currentMessage()
               and "launched" in window.statusBar().currentMessage(), True)

        # The other half: no entry point is a REPORT, not a warning box.
        os.remove(entry)
        launched.clear()
        no_modals()
        window.play()
        expect("a missing main.py launches nothing", launched, [])
        expect("and still opens no dialog", modals(), [])
        expect("it lands in Problems where it can be read later",
               any("nothing to play" in row for row in problem_rows()), True)
    finally:
        main_window_module.subprocess.Popen = real_popen
    window.undo()
    expect("and the edit F5 saved still undoes byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)

    # ----------------------------------------------------------------
    print()
    print("a tile picked in the palette carries its own collision mask")
    # ----------------------------------------------------------------
    # THE CLICK, THROUGH THE REAL WINDOW, onto `map.tileset.mask.set`.
    # `check_collision_mount.py` drives the canvas seam; what only this file
    # can see is the half between a real mouse press on a real `TilePalette`
    # and that seam: the signal, the mode-dependent meaning, and the palette
    # being told the answer afterwards.
    #
    # AGAINST ITS OWN FIXTURE, never `data/maps/test.tmx` (law 4). Baking a
    # mask writes a `.blitmask` beside the map and adds `pyoneer_collision`
    # to a `<tileset>`, so doing it on the author's canvas would pin both the
    # tileset's name and its geometry.
    masked_root = os.path.join(workspace, "tilemask")
    os.makedirs(os.path.join(masked_root, "config"))
    os.makedirs(os.path.join(masked_root, "data", "maps"))
    with open(os.path.join(masked_root, "data", "maps", "masked.tmx"), "w",
              encoding="utf-8", newline="") as handle:
        handle.write(MASKED_TMX)
    with open(os.path.join(masked_root, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [{"name": "masked", "identifier": "masked",
                             "file": "data/maps/masked.tmx"}]}, handle)
    masked_session = Session.open(masked_root, genre_id="topdown_rpg")
    MASKED_ORIGINAL = masked_session.project.map("masked").to_bytes()

    masked = EditorWindow(masked_session)
    masked.settings = _Settings(FakeStore())
    masked.show()
    application.processEvents()
    palette = masked.palette
    no_modals()

    expect("the fixture's one tileset is in the palette",
           (len(masked.canvas.atlas.entries),
            [s.name for s in palette.sections]), (1, ["Art"]))
    expect("...and nothing is baked yet, so the palette badges nothing",
           palette.masks, {})
    # Compared as a BOOLEAN rather than printed: the collision title carries
    # an arrow, and a check that cannot print its own failure on a cp1252
    # console is a check that turns a red line into a traceback.
    expect("the Tiles tab says Tiles while a tile pick means a brush",
           masked.palette_dock.windowTitle() == TILES_TITLE, True)

    # A REAL PRESS ON THE PALETTE, in tiles mode: a brush, and no command.
    quiet = len(masked_session.history())
    pick_tile(masked, "Art", 1, 0)
    expect("a palette click in TILES mode sets the brush",
           masked.canvas.stamp.primary, MASKED_GID)
    expect("...and writes nothing", len(masked_session.history()), quiet)
    expect("...and the toolbar calls it a brush",
           "brush: gid" in masked.stamp_label.text(), True)

    # THE MODE SWITCH, through the toolbar action a click would trigger.
    masked.modes.actions[EditMode.COLLISION].trigger()
    application.processEvents()
    expect("collision mode reaches the canvas",
           masked.canvas.mode, EditMode.COLLISION)
    expect("...and the Tiles tab now says what a click in it DOES",
           masked.palette_dock.windowTitle() == TILES_AS_MASK_TARGET, True)
    expect("...and the gesture is taught once, in the status bar",
           "Tiles palette" in masked.statusBar().currentMessage(), True)

    # A REAL PRESS ON THE MASK PALETTE. Same seventeen swatches, same
    # values: there is no second mask-picking control anywhere in this
    # window, which is the whole reason a tile mask needed no new vocabulary.
    pick_mask(masked, BLOCK_ALL)
    expect("the mask palette still sets the brush mask",
           masked.canvas.mask, BLOCK_ALL)
    expect("...and picking a mask on its own writes nothing",
           len(masked_session.history()), quiet)

    before_sheet = sheet_cells(palette, "Art")
    pick_tile(masked, "Art", 1, 0)

    # Every command since the baseline, not `history()[-1]`: a wire that
    # went dead leaves the history EMPTY, and indexing it then raises a
    # traceback where the suite should be printing a red line naming this.
    expect("A PALETTE CLICK IN COLLISION MODE REACHES THE VERB",
           [c.verb for t in masked_session.history()[quiet:]
            for c in t.commands],
           ["map.tileset.mask.set"])
    expect("...as ONE transaction", len(masked_session.history()) - quiet, 1)
    expect("...and the mask reached the tileset",
           masked.canvas.tile_masks(), {MASKED_GID: BLOCK_ALL})
    expect("...the palette was handed the answer, not left to guess",
           palette.masks, {MASKED_GID: BLOCK_ALL})
    # A palette that knows and does not draw is the same as not knowing.
    changed = [key for key, image in sheet_cells(palette, "Art").items()
               if image != before_sheet[key]]
    expect("...AND THE SHEET REDREW, at that tile and at no other",
           changed, [(1, 0)])

    # THE ORDER IS THE MECHANISM, so it is pinned. `set_masks` deliberately
    # does not repaint -- `set_atlas` rebuilds unconditionally on the next
    # line of `refresh_all` -- which means the sheet above was drawn ONCE,
    # already carrying its badge. Swap the two calls and it is drawn without
    # one, then not drawn again, and the badge simply never appears.
    _order = inspect.getsource(type(window).refresh_all)
    expect("refresh_all hands the palette its masks BEFORE its atlas",
           _order.index("set_masks") < _order.index("set_atlas"), True)
    # Parsed, not grepped: the docstring above explains the rebuild it does
    # NOT do, so a text search over the source matches its own explanation.
    # The CODE is what is being asserted, so the docstring is stripped first.
    _fn = ast.parse(textwrap.dedent(
        inspect.getsource(type(palette).set_masks))).body[0]
    if (_fn.body and isinstance(_fn.body[0], ast.Expr)
            and isinstance(_fn.body[0].value, ast.Constant)):
        _fn.body = _fn.body[1:]
    expect("...and set_masks leaves the one repaint to set_atlas",
           [n.attr for n in ast.walk(ast.Module(body=_fn.body, type_ignores=[]))
            if isinstance(n, ast.Attribute) and n.attr == "rebuild"], [])
    expect("...with the caption naming what the tile now carries",
           "blocked" in palette.caption.text(), True)
    expect("...and the toolbar reading as a target, not as a brush",
           ("blocked" in masked.stamp_label.text(),
            "brush" in masked.stamp_label.text()), (True, False))
    expect("...and no dialog anywhere on that path", modals(), [])

    # THE CHIP THROUGH THE WHOLE WINDOW. -1 has every direction bit set, so
    # a toolbar that formatted it with `describe_mask` would label the one
    # value that CLEARS a mask as the one that blocks everything.
    pick_mask(masked, NO_DATA)
    pick_tile(masked, "Art", 1, 0)
    expect("the no-opinion chip clears a tile's mask from the window",
           masked.canvas.tile_masks(), {})
    expect("...and the toolbar says so instead of 'blocks' anything",
           ("no opinion" in masked.stamp_label.text(),
            "blocks" in masked.stamp_label.text()), (True, False))
    masked.undo()
    application.processEvents()

    masked.undo()
    application.processEvents()
    expect("UNDO takes the mask, the badge and the declaration back",
           (masked.canvas.tile_masks(), palette.masks), ({}, {}))
    expect("...the sheet with them",
           sheet_cells(palette, "Art") == before_sheet, True)
    expect("...and the tmx byte for byte",
           masked_session.project.map("masked").to_bytes() == MASKED_ORIGINAL,
           True)

    # THE OTHER HALF OF THE BADGE. `PASS_ALL`'s glyph is deliberately EMPTY
    # -- an open cell is more than half of a map -- so a tile baked OPEN
    # would look exactly like a tile nobody has touched if the badge were
    # the glyph alone. "Open" and "nothing said" are the one distinction
    # level one exists to make.
    pick_mask(masked, PASS_ALL)
    pick_tile(masked, "Art", 1, 0)
    expect("a tile baked OPEN is stored as open, not as nothing",
           masked.canvas.tile_masks(), {MASKED_GID: PASS_ALL})
    changed = [key for key, image in sheet_cells(palette, "Art").items()
               if image != before_sheet[key]]
    expect("...and the palette SHOWS it, though its glyph draws nothing",
           changed, [(1, 0)])
    expect("...still with no dialog", modals(), [])
    masked.undo()
    application.processEvents()
    expect("...and it undoes like any other edit",
           (masked.canvas.tile_masks(),
            masked_session.project.map("masked").to_bytes() == MASKED_ORIGINAL),
           ({}, True))
    masked.confirm = lambda *a, **k: False      # teardown: close, write nothing
    masked.close()

    # ----------------------------------------------------------------
    print()
    print("closing the window cannot throw the session away in silence")
    # ----------------------------------------------------------------
    # THE MEASUREMENT THIS SECTION EXISTS FOR: two verbs out of thirty-six
    # write at command time, so every tile paint, layer, object edit and
    # passability cell lives in an open MapDocument until something calls
    # save. Before `EditorWindow.closeEvent`, `window.close()` returned True,
    # opened nothing, left the session dirty and left the .tmx byte-identical
    # on disk -- the whole edit gone, with no way for the author to notice.
    #
    # ITS OWN PROJECT, because these assertions SAVE. Writing the shared
    # fixture out would break every byte-identical comparison against
    # ORIGINAL that runs after it, and a check that writes something it did
    # not create is the shape law 4 is about.
    #
    # All four outcomes, and the fourth is the one nobody writes: a
    # closeEvent that swallows a FAILED save is worse than no closeEvent at
    # all, because it reports the work safe on the way to discarding it.
    closing_root = os.path.join(workspace, "closing")
    os.makedirs(os.path.join(closing_root, "config"))
    os.makedirs(os.path.join(closing_root, "data", "maps"))
    closing_tmx = os.path.join(closing_root, "data", "maps", "closing.tmx")
    with open(closing_tmx, "w", encoding="utf-8", newline="") as handle:
        handle.write(MASKED_TMX)
    with open(os.path.join(closing_root, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [{"name": "closing", "identifier": "closing",
                             "file": "data/maps/closing.tmx"}]}, handle)
    closing_session = Session.open(closing_root, genre_id="topdown_rpg")
    CLOSING_ORIGINAL = closing_session.project.map("closing").to_bytes()

    closing = EditorWindow(closing_session)
    closing.settings = _Settings(FakeStore())
    closing.show()
    application.processEvents()
    no_modals()

    FLOOR = Scope.parse("map:closing/layer:Floor")

    def on_disk() -> bytes:
        with open(closing_tmx, "rb") as handle:
            return handle.read()

    at_ask: list[bytes] = []

    def answering(reply):
        """Stand in for the confirm seam AND record the disk as it was asked.

        The body is deliberately not compared -- it names the dirty
        documents, and pinning that text here would make a wording change
        look like a lost session. WHEN it opened is the load-bearing part:
        the disk must still hold the old bytes at the moment the question is
        put, or the window saved before it asked and the answer was theatre.
        """
        def stub(*_a, **_k):
            at_ask.append(on_disk())
            return reply
        return stub

    def paint(x, y, gid):
        applied = closing.run(Command("map.tile.set", FLOOR,
                                      {"x": x, "y": y, "gid": gid}))
        if not applied:
            failures.append("closing fixture would not take an edit")
        return applied

    # ONE: nothing to lose, so nothing is asked. A prompt on a close that
    # cannot protect anything is what teaches a hand to dismiss the prompt,
    # and then the one that matters is dismissed too.
    closing.confirm = answering(True)
    expect("the fixture starts clean", closing_session.dirty, False)
    # `len(at_ask)` and never `at_ask` itself: the recorder holds whole .tmx
    # files, and a failure that prints one is a failure nobody reads.
    expect("a CLEAN window closes with no question at all",
           (closing.close(), len(at_ask), closing.isVisible()),
           (True, 0, False))
    expect("...and no dialog of any kind", modals(), [])

    # TWO: dirty, answered yes. The bytes must reach disk BEFORE it closes.
    closing.show()
    application.processEvents()
    paint(1, 1, 3)
    expect("one edit makes it dirty and leaves the disk alone",
           (closing_session.dirty, on_disk() == CLOSING_ORIGINAL), (True, True))
    edited = closing_session.project.map("closing").to_bytes()
    expect("...and the edit really is a change to the bytes",
           edited == CLOSING_ORIGINAL, False)
    at_ask.clear()
    closing.confirm = answering(True)
    accepted = closing.close()
    expect("a DIRTY window asks exactly once before closing", len(at_ask), 1)
    expect("...and had saved nothing yet when it asked",
           at_ask[0] == CLOSING_ORIGINAL, True)
    expect("...saying yes writes the edit, then closes",
           (accepted, on_disk() == edited, closing.isVisible(),
            closing_session.dirty), (True, True, False, False))
    expect("...through save(), not a dialog of its own", modals(), [])

    # THE OTHER HALF OF ONE, and not a repeat of it: clean is RECOMPUTED at
    # every close, not a state the window was born in. A closeEvent that
    # asked once and then remembered would pass ONE and fail here.
    closing.show()
    application.processEvents()
    at_ask.clear()
    closing.confirm = answering(True)
    expect("a window made clean BY that save asks nothing on the next close",
           (closing.close(), len(at_ask)), (True, 0))

    # THREE: dirty, answered no. It closes, and writes NOTHING.
    closing.show()
    application.processEvents()
    paint(2, 1, 4)
    saved_bytes = on_disk()
    expect("a second edit is dirty again", closing_session.dirty, True)
    at_ask.clear()
    closing.confirm = answering(False)
    refused = closing.close()
    expect("saying no CLOSES -- a refusal is an answer, not a failure",
           (refused, closing.isVisible(), len(at_ask)), (True, False, 1))
    expect("...and nothing at all reached disk",
           (on_disk() == saved_bytes, closing_session.dirty), (True, True))
    expect("...still with no dialog beyond the question", modals(), [])

    # FOUR: the menu entry is the SAME door. `&Quit` is bound to
    # `self.close`, which posts the QCloseEvent `closeEvent` answers -- so
    # the menu, the title-bar button and the window manager cannot disagree.
    # A `QApplication.quit()` here would look identical from the outside
    # until the day it silently took the session with it, which is why this
    # is asserted through the real QAction rather than by reading the source.
    def menu_entry(window, menu_text, entry_text):
        """One menu entry, by the text a hand reads off the screen.

        EVERY WRAPPER IT MAKES IS KEPT, and that is not tidiness. Measured
        here: `QAction.menu()` hands out a SECOND shiboken wrapper for a
        QMenu, and releasing that duplicate invalidates the Python wrappers
        of the menu's CHILDREN. A window holding a submenu of its own --
        `EditorWindow.maps_menu` does -- then answers "Internal C++ object
        (QMenu) already deleted" the next time it touches it, from inside
        `refresh_all`, for a menu Qt has not deleted at all. The walk looks
        read-only and is not, so the temporaries live as long as this file.
        """
        held.append(window.menuBar().actions())
        for top in held[-1]:
            if top.text() != menu_text:
                continue
            menu = top.menu()
            if menu is None:
                continue
            held.append(menu)
            held.append(menu.actions())
            for entry in held[-1]:
                if entry.text() == entry_text:
                    return entry
        return None

    quit_entry = menu_entry(closing, "&File", "&Quit")
    expect("File carries a Quit entry to drive", quit_entry is not None, True)
    closing.show()
    application.processEvents()
    at_ask.clear()
    closing.confirm = answering(False)
    quit_entry.trigger()
    application.processEvents()
    expect("File > Quit goes THROUGH closeEvent, not around it",
           (len(at_ask), closing.isVisible()), (1, False))
    expect("...and honours the same answer", on_disk() == saved_bytes, True)

    # FIVE: THE HALF NOBODY WRITES. The author asked to save, the save
    # failed, `save` already showed its own stop and returned None -- so
    # closing anyway would eat the work AND the warning. This is the one
    # outcome where the window must refuse to close.
    closing.show()
    application.processEvents()

    def explode_save():
        raise OSError("the disk said no")

    closing_session.save = explode_save
    no_modals()
    at_ask.clear()
    closing.confirm = answering(True)
    vetoed = closing.close()
    expect("a save that FAILS leaves the window OPEN",
           (vetoed, closing.isVisible()), (False, True))
    expect("...having asked, and having tried", len(at_ask), 1)
    expect("...with the failure on screen rather than swallowed",
           [line for line in warned if "the disk said no" in line],
           ["the disk said no"])
    expect("...and the work still unsaved rather than reported saved",
           (closing_session.dirty, on_disk() == saved_bytes), (True, True))
    del closing_session.save
    no_modals()

    closing.confirm = lambda *a, **k: False     # teardown: close, write nothing
    closing.close()
    closing.deleteLater()
    application.processEvents()

    # ----------------------------------------------------------------
    print()
    print("the window can reach every declared map, not just the first one")
    # ----------------------------------------------------------------
    # THE MEASUREMENT THIS SECTION EXISTS FOR: every layer under the window
    # has been multi-map since it was written -- `Project.map` opens and
    # caches any declared name, `Session.known_scopes` walks all of them
    # "for pickers and validation" -- while the window itself did
    # `map_names()[0]` and offered no control at all. A project could
    # declare ten maps and the editor would open the alphabetically first
    # one for ever.
    #
    # A TWO-MAP FIXTURE, because one map proves nothing here: with a single
    # declaration "the picker opened the right map" and "the picker is a
    # constant" are the same measurement (law 5). Its own project, too --
    # these assertions paint, and the shared fixture is compared against
    # ORIGINAL by sections that run after this one.
    picker_root = os.path.join(workspace, "picker")
    os.makedirs(os.path.join(picker_root, "config"))
    os.makedirs(os.path.join(picker_root, "data", "maps"))
    for map_name in ("alpha", "beta"):
        with open(os.path.join(picker_root, "data", "maps", f"{map_name}.tmx"),
                  "w", encoding="utf-8", newline="") as handle:
            handle.write(MASKED_TMX)
    with open(os.path.join(picker_root, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        # DECLARED OUT OF ORDER on purpose: `map_names()` sorts, and a
        # picker that offered them in declaration order would put a
        # different map under the same click on the author's next project.
        json.dump({"data": [{"name": n, "identifier": n,
                             "file": f"data/maps/{n}.tmx"}
                            for n in ("beta", "alpha")]}, handle)
    picker_session = Session.open(picker_root, genre_id="topdown_rpg")

    picker = EditorWindow(picker_session)
    picker.settings = _Settings(FakeStore())
    picker.show()
    application.processEvents()
    no_modals()

    def ticked(window):
        return [name for name, action in window.map_actions.items()
                if action.isChecked()]

    expect("two declared maps give two entries, in name order",
           list(picker.map_actions), ["alpha", "beta"])
    expect("...every one of them checkable",
           [a.isCheckable() for a in picker.map_actions.values()], [True, True])
    expect("...with EXACTLY ONE ticked, and it is the map on screen",
           (ticked(picker), picker.map_name), (["alpha"], "alpha"))
    expect("...and the title bar says which map, since it is now a choice",
           "map:alpha" in picker.windowTitle(), True)

    # REACHABILITY. The point of this pass is a control, so every assertion
    # below is driven through the QAction a hand actually clicks -- a dict
    # of actions the author cannot find is the shape this repository has
    # now shipped four times.
    maps_entry = menu_entry(picker, "&File", "&Maps")
    expect("File carries a Maps submenu",
           maps_entry is not None and maps_entry.menu() is not None, True)
    submenu = {a.text(): a for a in maps_entry.menu().actions()}
    expect("...listing both declared maps", sorted(submenu), ["alpha", "beta"])

    # ONE CANVAS PER STREAM. `MapCanvas.__init__` hands the command stream a
    # bound method, which a Qt delete does not take back -- so a window that
    # swaps canvases would keep every one it ever built. Proved in BOTH
    # directions on a spare canvas before it is used to judge the switch,
    # because "the count did not grow" is worthless if the count never moves.
    from editor.ui.canvas import MapCanvas as _MapCanvas                # noqa: E402
    subscribed = lambda: len(picker_session.stream.listeners)
    base_listeners = subscribed()
    spare = _MapCanvas(picker_session, "beta")
    expect("building a canvas subscribes it to the command stream",
           subscribed(), base_listeners + 1)
    expect("...a fresh canvas comes up in TILES mode", spare.mode, EditMode.TILES)
    spare.detach()
    expect("...detach takes exactly that subscription back",
           subscribed(), base_listeners)
    spare.detach()
    expect("...and says nothing the second time, so a caller need not count",
           subscribed(), base_listeners)
    spare.deleteLater()
    application.processEvents()

    # THE STATE A SWITCH MUST CARRY. The toolbar does not change, so a
    # canvas that came up in TILES under a mode button reading COLLISION is
    # a control lying about what the next click does.
    picker.modes.actions[EditMode.COLLISION].trigger()
    application.processEvents()
    expect("the window is in collision mode before the switch",
           picker.canvas.mode, EditMode.COLLISION)

    # AND AN UNSAVED EDIT, on the map being LEFT. Nothing on this path
    # closes a document -- `Project.map` caches for the life of the project
    # and `save` writes every dirty one -- so the whole claim is that the
    # edit is still there afterwards, and that the window did not stop to
    # ask about work it was never going to lose.
    picker.run(Command("map.tile.set", Scope.parse("map:alpha/layer:Floor"),
                       {"x": 0, "y": 0, "gid": 3}))
    edited_alpha = picker_session.project.map("alpha").to_bytes()
    expect("the edit made the session dirty on alpha",
           (picker_session.dirty, picker_session.project.dirty_maps()),
           (True, ["alpha"]))

    asked_on_switch = []
    picker.confirm = lambda *a, **k: asked_on_switch.append(a) or True
    outgoing = picker.canvas
    listeners_before = subscribed()
    no_modals()

    submenu["beta"].trigger()

    # BEFORE processEvents, deliberately: `deleteLater` is what frees the
    # outgoing canvas, and after the event loop runs there is no Python
    # object left to ask where it was parented.
    expect("LAW 12: the outgoing canvas is re-parented to the window",
           outgoing.parent() is picker, True)
    expect("...so it is NOT promoted to a top-level window",
           (outgoing.isWindow(), outgoing in application.topLevelWidgets()),
           (False, False))
    expect("...and it is hidden rather than left painting over the new one",
           outgoing.isVisible(), False)
    # THE OTHER HALF OF BOTH INSTRUMENTS, on a widget orphaned on purpose.
    # Without it `isWindow()` and the top-level roster could each be a
    # constant and the two lines above would pass on the very bug they are
    # written against -- ~20 orphan windows per undo, which is what law 12
    # cost when it was paid the first time.
    orphan = QWidget(picker)
    was_child = (orphan.isWindow(), orphan in application.topLevelWidgets())
    orphan.setParent(None)
    expect("...and both instruments SEE the parentless state they rule out",
           (was_child, orphan.isWindow(),
            orphan in application.topLevelWidgets()),
           ((False, False), True, True))
    orphan.deleteLater()

    application.processEvents()

    expect("the click switched the map", picker.map_name, "beta")
    expect("...onto a NEW canvas, over the other map's own document",
           (picker.canvas is not outgoing, picker.canvas.map_name,
            picker.canvas.document is picker_session.project.map("beta")),
           (True, "beta", True))
    expect("...mounted as the central widget, not merely built",
           picker.centralWidget() is picker.canvas, True)
    expect("...carrying the mode the toolbar still shows",
           picker.canvas.mode, EditMode.COLLISION)
    expect("...with exactly one entry ticked, and it is the new map",
           ticked(picker), ["beta"])
    expect("...and the title bar following it",
           ("map:beta" in picker.windowTitle(),
            "map:alpha" in picker.windowTitle()), (True, False))
    expect("...and the swapped-out canvas no longer on the stream",
           subscribed(), listeners_before)

    # NOTHING IS LOST, WHICH IS WHY NOTHING IS ASKED. A prompt that cannot
    # possibly protect any work is the shape `closeEvent` rules against in
    # its own docstring, and the honest way to assert it is to prove the
    # work survived rather than to prove a box appeared.
    expect("switching with UNSAVED work asks the author nothing",
           (len(asked_on_switch), modals()), (0, []))
    expect("...because the edit is still there, byte for byte, still dirty",
           (picker_session.dirty, picker_session.project.dirty_maps(),
            picker_session.project.map("alpha").to_bytes() == edited_alpha),
           (True, ["alpha"], True))

    # THE ALL-LAYERS TOGGLE REACHES THE CANVAS THAT IS ON SCREEN NOW. It was
    # wired to a bound method of the canvas that existed when the toolbar
    # was built, which after a switch is a deleted map's canvas -- the
    # button lights and nothing resolves.
    picker.modes.all_layers.setChecked(True)
    application.processEvents()
    expect("the All-layers toggle reaches the canvas the switch mounted",
           picker.canvas.all_layers, True)
    picker.modes.all_layers.setChecked(False)
    application.processEvents()
    expect("...in both directions", picker.canvas.all_layers, False)

    # NAVIGATION FOLLOWS THE NEW CURSOR. `&Back` and `Select the parent`
    # held bound methods of the Selection object built in `__init__`; a
    # switch roots a fresh one, and a menu still driving the old object
    # navigates a selection nothing is listening to.
    select_layer(picker, "Floor")
    expect("a layer on the NEW map can be selected",
           str(picker.selection.scope), "map:beta/layer:Floor")
    menu_entry(picker, "&Edit", "&Back").trigger()
    application.processEvents()
    expect("...and File-menu Back walks the cursor the switch created",
           str(picker.selection.scope), "map:beta")

    # UNDO CROSSES MAPS, AND SAYS SO. The stack is the project's and every
    # inverse carries its own scope, so Ctrl+Z here takes back the edit on
    # alpha -- correctly, invisibly, and indistinguishably from "undo did
    # nothing" unless the window says where it landed.
    picker.undo()
    application.processEvents()
    expect("undo took the off-screen edit back",
           picker_session.project.dirty_maps(), [])
    expect("...and SAID it landed on a map that is not on screen",
           ("map:alpha" in picker.statusBar().currentMessage(),
            "not the map on screen" in picker.statusBar().currentMessage()),
           (True, True))

    # THE OTHER HALF: an undo on the map the author is looking at must NOT
    # announce anything, or the notice is noise on every Ctrl+Z.
    picker.run(Command("map.tile.set", Scope.parse("map:beta/layer:Floor"),
                       {"x": 1, "y": 1, "gid": 4}))
    picker.undo()
    application.processEvents()
    expect("an undo on the map ON SCREEN says nothing about maps",
           "not the map on screen" in picker.statusBar().currentMessage(), False)

    # THE SAME SEAM DOES FIRE WHERE WORK REALLY CAN BE LOST. Without this
    # line "switching asked nothing" is satisfied by a confirm seam that was
    # never reachable at all.
    asked_on_switch.clear()
    picker.confirm = lambda *a, **k: asked_on_switch.append(a) or False
    picker.run(Command("map.tile.set", Scope.parse("map:beta/layer:Floor"),
                       {"x": 2, "y": 1, "gid": 4}))
    picker.close()
    application.processEvents()
    expect("...while a DIRTY close still asks, through that very seam",
           len(asked_on_switch), 1)
    picker.deleteLater()
    application.processEvents()
    no_modals()

    # ----------------------------------------------------------------
    print()
    print("a map that will not open changes nothing at all")
    # ----------------------------------------------------------------
    # LAW 7 on the one path where the plausible default is "carry on and
    # see": the window must open the document BEFORE it tears the old
    # canvas down, or a bad declaration leaves it with no central widget and
    # a menu ticking a map it never opened.
    broken_root = os.path.join(workspace, "broken_map")
    os.makedirs(os.path.join(broken_root, "config"))
    os.makedirs(os.path.join(broken_root, "data", "maps"))
    with open(os.path.join(broken_root, "data", "maps", "real.tmx"), "w",
              encoding="utf-8", newline="") as handle:
        handle.write(MASKED_TMX)
    with open(os.path.join(broken_root, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        # `zmissing` sorts last, so the window still OPENS on `real`; the
        # declaration points at a file nobody wrote.
        json.dump({"data": [{"name": "real", "identifier": "real",
                             "file": "data/maps/real.tmx"},
                            {"name": "zmissing", "identifier": "zmissing",
                             "file": "data/maps/zmissing.tmx"}]}, handle)
    broken_session = Session.open(broken_root, genre_id="topdown_rpg")
    breaker = EditorWindow(broken_session)
    breaker.settings = _Settings(FakeStore())
    breaker.show()
    application.processEvents()
    no_modals()

    expect("it opened the map that exists", breaker.map_name, "real")
    held = breaker.canvas
    breaker.map_actions["zmissing"].trigger()
    application.processEvents()
    expect("a map that will not open leaves the window exactly as it was",
           (breaker.map_name, breaker.canvas is held,
            breaker.centralWidget() is held), ("real", True, True))
    expect("...and puts the tick back on the map that IS open",
           ticked(breaker), ["real"])
    expect("...having said so where it can be read afterwards",
           breaker.problems.notice_keys(), ["switch_map"])
    expect("...and in the status bar", "zmissing" in
           breaker.statusBar().currentMessage(), True)
    expect("...without a dialog", modals(), [])

    # AND THE OTHER HALF, on the same window: the map that CAN open still
    # switches, and the refusal retires rather than staying on the panel.
    breaker.map_actions["real"].trigger()
    expect("clicking the open map again is not a switch",
           (breaker.canvas is held, ticked(breaker)), (True, ["real"]))
    breaker.confirm = lambda *a, **k: False
    breaker.close()
    breaker.deleteLater()
    application.processEvents()
    no_modals()

    # ----------------------------------------------------------------
    print()
    print("one broken panel does not take the window down")
    # ----------------------------------------------------------------
    def explode():
        raise RuntimeError("panel is unhappy")

    original = window.problems.refresh
    window.problems.refresh = explode
    try:
        window.refresh_all()
        print("  ok   refresh_all survived a panel that raised")
    except Exception as exc:                                    # noqa: BLE001
        print(f"  FAIL refresh_all propagated {type(exc).__name__}")
        failures.append("panel isolation")
    finally:
        window.problems.refresh = original

    window.confirm = lambda *a, **k: False      # teardown: close, write nothing
    window.close()

finally:
    shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
