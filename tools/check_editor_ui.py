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
import re
import shutil
import sys
import tempfile

if importlib.util.find_spec("PySide6") is None:
    print("SKIP  PySide6 is not installed "
          "(pip install -r editor/requirements.txt)")
    sys.exit(0)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt                          # noqa: E402
from PySide6.QtGui import QAction, QMouseEvent                          # noqa: E402
from PySide6.QtWidgets import (                                         # noqa: E402
    QApplication,
    QGraphicsLineItem,
    QMessageBox,
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
from editor.ui.main_window import (                                      # noqa: E402
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


def mouse(window, kind, cell, button=Qt.LeftButton, buttons=None):
    """Drive the canvas the way a real mouse would, in CELL coordinates."""
    canvas = window.canvas
    scene_x = cell[0] * canvas.tile_width + canvas.tile_width / 2
    scene_y = cell[1] * canvas.tile_height + canvas.tile_height / 2
    point = QPointF(canvas.mapFromScene(scene_x, scene_y))
    held = buttons if buttons is not None else button
    event = QMouseEvent(kind, point, button, held, Qt.NoModifier)
    {QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
     QEvent.Type.MouseMove: canvas.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent}[kind](event)


def drag(window, cells, button=Qt.LeftButton):
    mouse(window, QEvent.Type.MouseButtonPress, cells[0], button)
    for cell in cells[1:]:
        mouse(window, QEvent.Type.MouseMove, cell, Qt.NoButton, button)
    mouse(window, QEvent.Type.MouseButtonRelease, cells[-1], button)
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
    expect("every real layer is addressable, and only those",
           sum(1 for a in addressable if "/layer:" in a),
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
    select_layer(window, "entity")
    window.canvas.object_class = "GamePlayer"
    mouse(window, QEvent.Type.MouseButtonPress, (4, 6))
    application.processEvents()
    objects = session.project.map("test").object_layer("entity").objects()
    expect("an object was placed", len(objects), 1)
    expect("with the chosen class", objects[0].type, "GamePlayer")

    # A CLICK, not a Command written by the check: the whole point of putting
    # materialisation in the verb rather than in the panel is that the author's
    # real path gets it. And the property is invisible on a rectangle, so the
    # status line is asserted too -- an authoring surface where something
    # happens and nothing says so is the defect this suite is named after.
    STARTS_AS = genre_module.load("topdown_rpg").object_class(
        "entity", "GamePlayer").behaviors_text
    expect("clicking an entity layer materialises the pack's behavior list",
           objects[0].properties.as_dict().get(BEHAVIORS), STARTS_AS)
    expect("and the status bar says so, since a property is invisible",
           STARTS_AS in window.statusBar().currentMessage(), True)

    # The other half, through the same click path: a class the pack does not
    # name is placed with nothing, and the status line does not invent a list.
    window.canvas.object_class = "GameEntity"
    mouse(window, QEvent.Type.MouseButtonPress, (6, 6))
    application.processEvents()
    plain = session.project.map("test").object_layer("entity").objects()[-1]
    expect("a class the pack does not name is placed with nothing",
           plain.properties.as_dict(), {})
    expect("and the status line does not claim a list it did not write",
           window.statusBar().currentMessage(), "placed GameEntity")
    window.undo()
    application.processEvents()
    objects = session.project.map("test").object_layer("entity").objects()
    expect("undoing it leaves the first object alone", len(objects), 1)
    window.canvas.object_class = "GamePlayer"

    window.selection.select(Scope.of(("map", "test"), ("layer", "entity"),
                                     ("object", str(objects[0].id))))
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
           str(window.actions.scope), "map:test/layer:entity/object:1")

    inspection = window.inspector.view.inspection
    fields = {f.key: f for section in inspection.sections for f in section.fields}
    expect("the inspector describes it", inspection.heading, "object 1")
    expect("it offers position as a number", fields["x"].kind, "float")
    expect("class as a constrained choice", fields["type"].kind, "choice")
    expect("rotation is editable now", fields["rotation"].editable, True)
    expect("and visible is a checkbox", fields["visible"].kind, "bool")

    window.run(fields["x"].emit(128.0))
    expect("editing through the inspector moved it",
           session.project.map("test").object_layer("entity")
           .find(objects[0].id).x, 128.0)
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
               .find(objects[0].id).properties.as_dict().get("pyoneer_probe")),
           "0")
    window.inspector.view.ask = ask_module.ask_form
    window.undo()

    mouse(window, QEvent.Type.MouseButtonPress, (4, 6), Qt.RightButton)
    application.processEvents()
    expect("right-click deleted it",
           len(session.project.map("test").object_layer("entity").objects()), 0)
    window.undo()
    window.undo()
    expect("and everything unwound byte-identically",
           session.project.map("test").to_bytes() == ORIGINAL, True)

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
            window.ask is ask_module.ask_form], [True] * 5)

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
    def modal_calls(relative: str) -> list[str]:
        # BOTH ways to block, not just the obvious one. Watching only
        # `QMessageBox.x(...)` is blind to `dialog.exec()`, so a panel could
        # grow a fully blocking QDialog and the guard that exists to stop
        # exactly this pattern returning would not see it.
        with open(os.path.join(REPO, relative), encoding="utf-8") as handle:
            text = handle.read()
        return (re.findall(r"QMessageBox\.(\w+)\(", text)
                + [f"exec:{name}" for name in re.findall(r"(\w+)\.exec_?\(\)", text)])

    # A module may open a modal ONLY if it exposes a seam a check can
    # replace -- that is the whole property, and it is why the exclusion
    # below is a single name rather than a convenience. `ask.py` is the one
    # DIALOG module: opening one is its job, and it is asserted replaceable
    # just below, so excluding it is earned rather than assumed.
    # `main_window.py` keeps the genuine stops. `canvas.py` belongs to the
    # collision path, where `check_collision_mount.py` asserts the same
    # property from the far side.
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
        and name not in DIALOG_MODULES + ("main_window.py", "canvas.py"))
    expect("no panel opens one of its own",
           {name: modal_calls(f"editor/ui/{name}") for name in panels
            if modal_calls(f"editor/ui/{name}")}, {})
    expect("ask.py owns the only question in the tree",
           modal_calls("editor/ui/ask.py"), ["question", "exec:dialog"])
    # THE EARNED HALF of the exclusion. A dialog module is exempt from the
    # census because a check can substitute its opener; that is a claim, so
    # it is asserted rather than trusted, or "it is a dialog module" becomes
    # a way to smuggle an unreplaceable modal back in. Named explicitly,
    # because the two seams have different SHAPES -- ask.py exposes
    # module-level functions that panels call, tileset_dialog.py a
    # classmethod -- and a generic "has something callable" probe would pass
    # for any module and prove nothing.
    SEAMS = {"ask.py": ("editor.ui.ask", None, ("ask_form", "confirm")),
             "tileset_dialog.py": ("editor.ui.tileset_dialog",
                                   "TilesetImportDialog", ("ask",))}
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
    # settings dialog, which is a decision and opens on an explicit menu pick.
    expect("and the window keeps exactly its three genuine stops",
           modal_calls("editor/ui/main_window.py"),
           ["critical"] * 3 + ["exec:dialog"])

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
    expect("defaults come back typed",
           [type(store.get(s.key)).__name__ for s in SETTINGS],
           ["str", "str", "bool", "int", "int", "bool"])
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
    masked.close()

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

    window.close()

finally:
    shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
