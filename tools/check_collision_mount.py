"""Assert the collision stack is actually WIRED to the canvas.

`check_collision.py` and `check_collision_view.py` already prove the model
and the pixmap are correct. They proved that while nothing in the editor
imported either one -- 2,794 lines of verified code with zero production
importers. This file covers the seam those two cannot see: that a real
`MapCanvas` mounts the overlay, that the mode changes where a drag lands,
and that a collision stroke is one transaction with an exact inverse.

CLICKING A COLLISION TILE PAINTS A MASK. That is the whole requirement, and
the second half of this file is about the three ways it used not to be:

  * a 191-word modal dialog on the first press, which also consumed the
    stroke that raised it ("paint again"), also fired on right-click erase,
    also fired before the cheaper "select a tile layer" refusal, and whose
    Yes button left behind a map that raises FileNotFoundError at load;
  * the sufficiency guard, which protected only the ADD path -- so a map
    already declaring a five-tile `collision` tileset painted gids past the
    end of its own sheet, silently. That is the law-5 shape: an invariant
    proved in the permissive direction only;
  * `QImage.save` returning False and raising nothing, which would have
    turned an unwritable target into a declaration pointing at no file.

NO MODAL CAN REACH THE PAINT PATH, and this file proves it three ways
rather than trusting it: every `QMessageBox` entry point raises for the
whole run (so a dialog is a red check, not a 40-minute hang -- law 13, and
this exact file is where that cost was paid), `MapCanvas` is asserted to
carry no `confirm` seam, and `editor/ui/canvas.py`'s import graph is walked
with `ast` to assert `QMessageBox` is not imported at all.

AND IT LANDS WHERE THE AUTHOR CLICKED. The engine learned to read a
companion four times finer than the map -- `pyoneer_subcell="4"`, sixteen
masks per tile -- and every check that existed still passed while the editor
addressed whole tiles over such a map. Measured at the commit before this
one, on the 4x fixture below: a click at scene pixel (26, 26) wrote sub-cell
(1, 1), which is pixels 4..7, so the mask landed 20px up and 20px left of
the cursor and 1,188px away on a 100x100 map. Nothing was red, because no
check had ever opened a 4x map in a MapCanvas.

So the last third of this file does exactly that, and asserts the thing the
author can see rather than the thing the code returns: the painted sub-cell
must CONTAIN the clicked pixel. Then the 1x case in the same shape, because
a resolution change breaks the map that did not change far more often than
the one that did; then that the overlay's cells are the COMPANION's cells;
then that a 1x layer read into a 4x field lands over its own map tile rather
than four times too close to the origin; and finally the guard, which
refuses a stroke whose paint unit and companion disagree instead of writing
a mask it cannot place.

Against its OWN fixture map, never `data/maps/test.tmx`. The author paints
in that file constantly, and four red suites have come from a check that
pinned its contents. The fixture here declares exactly what the feature
needs and nothing else: a `collision` tileset to store masks in, an art
layer with no companion (so the create-on-first-stroke path runs), and one
that already declares its companion (so the layer stack has two members to
resolve).

The window wiring -- toolbar buttons, the mask palette dock, the C
shortcut -- belongs to `main_window.py` and is deliberately NOT exercised
here. This drives the canvas through a minimal harness that supplies the
one thing it asks of its window, `run(commands)`, so a failure here is a
failure in the canvas rather than in whatever the toolbar happens to look
like today.

Skips cleanly when PySide6 is not installed; the engine does not depend on
it and a bare clone should not fail here.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import ast
import importlib.util
import inspect
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
from PySide6.QtGui import QImage, QMouseEvent                           # noqa: E402
from PySide6.QtWidgets import (                                         # noqa: E402
    QApplication,
    QGraphicsPixmapItem,
    QMainWindow,
    QMessageBox,
)

from editor.core.collision import SUBCELL, NO_DATA, gid_to_opinion      # noqa: E402
from editor.core.layers import (                                        # noqa: E402
    BLOCK_ALL,
    BLOCK_UP,
    PASS_ALL,
    read_profile,
)
from editor.core.paint import EditMode, Stamp, Tool                     # noqa: E402
from editor.core.scope import Scope                                     # noqa: E402
from editor.core.session import Session                                 # noqa: E402
from editor.ui import canvas as canvas_module                           # noqa: E402
from editor.ui.canvas import (                                          # noqa: E402
    COLLISION_IMAGE,
    COLLISION_TILESET,
    MapCanvas,
    PaintUnit,
    write_mask_sheet,
)
from editor.ui.collision_view import MASK_DOMAIN, CollisionOverlay      # noqa: E402

failures: list[str] = []


# --------------------------------------------------------------------------
# No modal may reach anything below
# --------------------------------------------------------------------------
# Armed for the WHOLE run, not around one block. Law 13's cost was measured
# in this very file: `QMessageBox.question` blocked check_all.py for 40+
# minutes with zero output, indistinguishable from a slow machine, which is
# why there is now a 600s timeout and a HANG verdict. A stub that RAISES
# turns that hang into a red line naming the caller, and -- unlike the
# `confirm`-seam stub this replaces -- it covers dialogs nobody thought to
# leave a seam for.

modals: list[str] = []


def _no_modal(*_args, **_kwargs):
    modals.append("a modal was raised")
    raise AssertionError(
        "a QMessageBox was raised on a routine editor path (law 13)")


for _entry in ("question", "warning", "critical", "information", "about",
               "aboutQt", "exec", "exec_", "open", "show"):
    if hasattr(QMessageBox, _entry):
        setattr(QMessageBox, _entry, staticmethod(_no_modal))


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<56} got={got} want={want}")
    if not ok:
        failures.append(label)


# --------------------------------------------------------------------------
# The fixture
# --------------------------------------------------------------------------

WIDTH, HEIGHT = 8, 6
COLLISION_FIRST_GID = 257

#: Where the two collision layers disagree, so the resolved view has a
#: conflict to report and a decider to name.
CONFLICT_CELL = (1, 1)


def _csv(cells: dict[tuple[int, int], int]) -> str:
    rows = []
    for y in range(HEIGHT):
        rows.append(",".join(str(cells.get((x, y), 0)) for x in range(WIDTH)))
    return ",\n".join(rows)


_COLLISION_TILESET = """ <tileset firstgid="{first}" name="collision" \
tilewidth="16" tileheight="16" tilecount="{count}" columns="{count}">
  <image source="{image}" width="{width}" height="16"/>
 </tileset>
"""

_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" compressionlevel="-1" width="{w}" height="{h}" \
tilewidth="16" tileheight="16" infinite="0" nextlayerid="4" nextobjectid="1">
 <tileset firstgid="1" name="Art" tilewidth="16" tileheight="16" \
tilecount="256" columns="16">
  <image source="art.png" width="256" height="256"/>
 </tileset>
{collision}\
 <layer id="1" name="Floor" width="{w}" height="{h}">
  <data encoding="csv">
{empty}
</data>
 </layer>
 <layer id="2" name="Roof" width="{w}" height="{h}">
  <properties>
   <property name="pyoneer_passability" value="RoofCollision"/>
  </properties>
  <data encoding="csv">
{empty}
</data>
 </layer>
 <layer id="3" name="RoofCollision" width="{w}" height="{h}">
  <properties>
   <property name="pyoneer_renders" type="bool" value="false"/>
  </properties>
  <data encoding="csv">
{roof}
</data>
 </layer>
</map>
"""


def fixture(collision_tiles: int | None = len(MASK_DOMAIN)) -> str:
    """The map, declaring a `collision` tileset of N tiles -- or none.

    Three shapes from one template, because all three are states a real map
    reaches. SEVENTEEN is a map somebody already painted collision on.
    NONE is what every map starts as, and is the state the provisioning
    path exists for. FEWER THAN SEVENTEEN is the state nothing guarded: the
    map declares the tileset, the canvas finds a firstgid, and masks are
    written as gids the declared sheet does not own -- silently, because
    `CollisionTilesetOffer.sufficient` was consulted only on the way IN.

    The conflict cell is authored only when the tileset can actually hold
    the mask it stores, so the smaller fixtures do not smuggle in the very
    out-of-range gid they exist to catch.
    """
    declares = collision_tiles is not None
    collision = _COLLISION_TILESET.format(
        first=COLLISION_FIRST_GID, count=collision_tiles,
        image="collision.png" if collision_tiles == len(MASK_DOMAIN)
        else "small_collision.png",
        width=16 * (collision_tiles or 0)) if declares else ""
    holds_conflict = declares and collision_tiles > BLOCK_UP
    return _TEMPLATE.format(
        w=WIDTH, h=HEIGHT, collision=collision, empty=_csv({}),
        roof=_csv({CONFLICT_CELL: COLLISION_FIRST_GID + BLOCK_UP}
                  if holds_conflict else {}))


FIXTURE = fixture()


# --------------------------------------------------------------------------
# The sub-cell fixture
# --------------------------------------------------------------------------
# A SECOND map, deliberately, and not a parameter on the first: everything
# above is about a 1x map and has to keep being about a 1x map. This one is
# small enough that every cell can be named -- 4x4 tiles at 16px, so 64x64
# scene pixels, and a `pyoneer_subcell="4"` companion divides that into
# 16x16 cells of 4px each.

FINE_TILES = 4                        # map tiles per axis
FINE_SUB = 4                          # sub-cells per tile per axis
FINE_SIDE = FINE_TILES * FINE_SUB     # 16 companion cells per axis
TILE = 16                             # pixels per map tile
FINE_CELL = TILE // FINE_SUB          # 4 pixels per sub-cell


def grid_csv(cells: dict[tuple[int, int], int], side: int) -> str:
    """A csv payload for a `side` x `side` layer, one text row per map row."""
    return ",\n".join(",".join(str(cells.get((x, y), 0)) for x in range(side))
                      for y in range(side))


_FINE_ART = """ <layer id="{id}" name="{name}" width="4" height="4">
  <properties>
   <property name="pyoneer_passability" value="{companion}"/>
  </properties>
  <data encoding="csv">
{empty}
</data>
 </layer>
"""

_FINE_DATA = """ <layer id="{id}" name="{name}" width="{w}" height="{h}">
  <properties>
   <property name="pyoneer_renders" type="bool" value="false"/>
{subcell}  </properties>
  <data encoding="csv">
{cells}
</data>
 </layer>
"""

_FINE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" compressionlevel="-1" width="4" height="4" \
tilewidth="16" tileheight="16" infinite="0" nextlayerid="5" nextobjectid="1">
 <tileset firstgid="1" name="Art" tilewidth="16" tileheight="16" \
tilecount="256" columns="16">
  <image source="art.png" width="256" height="256"/>
 </tileset>
 <tileset firstgid="{first}" name="collision" tilewidth="16" tileheight="16" \
tilecount="17" columns="17">
  <image source="collision.png" width="272" height="16"/>
 </tileset>
{layers}</map>
"""


def fine_fixture(*, declare: str | None = "4", side: int = FINE_SIDE,
                 roof: dict[tuple[int, int], int] | None = None) -> str:
    """A 4x4 map at 16px whose Floor companion is `declare` times finer.

    `declare=None` omits the property, which is the shape of every map
    written before `pyoneer_subcell` existed and is the migration case the
    1x half of this section drives.

    `side` is the companion's own size in cells, so it can be made SMALLER
    than `4 x` the map -- which is legal, is what a partly-authored map looks
    like, and is the only way to tell a bound taken from the layer apart from
    one taken from `map x subcell`.

    `roof` adds a second art layer with a 1x companion holding the masks it
    names, keyed by MAP cell. That is a mixed stack, and it is the only shape
    in which dropping `collision_stack`'s scale is visible: read unscaled, a
    1x wall on map cell (2, 0) answers at sub-cell (2, 0), which is a
    different square of the map entirely.
    """
    prop = ""
    if declare is not None:
        prop = ('   <property name="%s" type="int" value="%s"/>\n'
                % (SUBCELL, declare))
    layers = _FINE_ART.format(id=1, name="Floor", companion="FloorCollision",
                              empty=grid_csv({}, FINE_TILES))
    layers += _FINE_DATA.format(id=2, name="FloorCollision", w=side, h=side,
                                subcell=prop, cells=grid_csv({}, side))
    if roof is not None:
        layers += _FINE_ART.format(id=3, name="Roof",
                                   companion="RoofCollision",
                                   empty=grid_csv({}, FINE_TILES))
        layers += _FINE_DATA.format(
            id=4, name="RoofCollision", w=FINE_TILES, h=FINE_TILES,
            subcell="",
            cells=grid_csv({cell: COLLISION_FIRST_GID + mask
                            for cell, mask in roof.items()}, FINE_TILES))
    return _FINE_TEMPLATE.format(first=COLLISION_FIRST_GID, layers=layers)


# --------------------------------------------------------------------------
# Counting instrumentation
# --------------------------------------------------------------------------
# Patched for the whole run rather than around one block: "the overlay is
# updated per stroke rather than re-baked" is a claim about which of these
# runs and how often, and it cannot be measured after the fact.

bakes: list[str] = []
touched: list[tuple[int, int]] = []

_real_bake = CollisionOverlay.bake
_real_resolved = CollisionOverlay.bake_resolved
_real_set_cell = CollisionOverlay.set_cell


def _counted_bake(self, masks):
    bakes.append("bake")
    return _real_bake(self, masks)


def _counted_resolved(self, layers, **kwargs):
    bakes.append("resolved")
    return _real_resolved(self, layers, **kwargs)


def _counted_set_cell(self, x, y, mask, **kwargs):
    touched.append((x, y))
    return _real_set_cell(self, x, y, mask, **kwargs)


CollisionOverlay.bake = _counted_bake
CollisionOverlay.bake_resolved = _counted_resolved
CollisionOverlay.set_cell = _counted_set_cell


# --------------------------------------------------------------------------
# The harness
# --------------------------------------------------------------------------

class Harness(QMainWindow):
    """The one thing `MapCanvas` asks of its window: `run(commands)`.

    It refreshes the way `EditorWindow.refresh_all` does -- rebuild the
    canvas after every applied command -- because that rebuild is precisely
    what the overlay has to survive.
    """

    def __init__(self, session, map_name: str):
        super().__init__()
        self.session = session
        self.rejected: list[str] = []
        self.canvas = MapCanvas(session, map_name, self)
        self.setCentralWidget(self.canvas)
        self.resize(900, 700)

    def run(self, commands, *, label=None, source="editor") -> bool:
        try:
            self.session.run(commands, label=label, source=source)
        except Exception as exc:                                # noqa: BLE001
            self.rejected.append(str(exc))
            return False
        self.canvas.rebuild()
        return True

    def undo(self) -> None:
        self.session.undo()
        self.canvas.rebuild()

    def redo(self) -> None:
        self.session.redo()
        self.canvas.rebuild()


def mouse(canvas, kind, cell, button=Qt.LeftButton, buttons=None):
    """Drive the canvas the way a real mouse would, in CELL coordinates."""
    scene_x = cell[0] * canvas.tile_width + canvas.tile_width / 2
    scene_y = cell[1] * canvas.tile_height + canvas.tile_height / 2
    point = QPointF(canvas.mapFromScene(scene_x, scene_y))
    held = buttons if buttons is not None else button
    event = QMouseEvent(kind, point, button, held, Qt.NoModifier)
    {QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
     QEvent.Type.MouseMove: canvas.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent}[kind](event)


def click_px(application, canvas, px: float, py: float,
             button=Qt.LeftButton) -> None:
    """Press and release at one SCENE PIXEL, which is what a mouse gives you.

    The `mouse`/`drag` pair above speaks in cells, which is the right unit
    for asserting that a drag covers three of them and the wrong one for
    asserting where a cell IS: a check that clicks 'cell (6, 6)' and finds a
    mask in cell (6, 6) passes whatever `paint_width` says, because both
    halves went through the same broken number. A pixel is the only
    coordinate the canvas does not get to choose.
    """
    point = QPointF(canvas.mapFromScene(px, py))
    for kind, handler in ((QEvent.Type.MouseButtonPress,
                           canvas.mousePressEvent),
                          (QEvent.Type.MouseButtonRelease,
                           canvas.mouseReleaseEvent)):
        handler(QMouseEvent(kind, point, button, button, Qt.NoModifier))
    application.processEvents()


def painted_cells(layer) -> list[tuple[int, int]]:
    """Every cell of a layer holding a gid, in reading order."""
    return [(x, y) for y in range(layer.height) for x in range(layer.width)
            if layer.get_tile(x, y)]


def covers(cell: tuple[int, int], size: int,
           point: tuple[float, float]) -> bool:
    """Does `cell`, at `size` pixels per side, contain that scene pixel?

    The assertion that cannot be satisfied by agreeing with yourself: it
    turns a cell INDEX back into the pixels it owns and asks whether the
    author's click is among them.
    """
    left, top = cell[0] * size, cell[1] * size
    return (left <= point[0] < left + size
            and top <= point[1] < top + size)


def drag(application, canvas, cells, button=Qt.LeftButton):
    mouse(canvas, QEvent.Type.MouseButtonPress, cells[0], button)
    for cell in cells[1:]:
        mouse(canvas, QEvent.Type.MouseMove, cell, Qt.NoButton, button)
    mouse(canvas, QEvent.Type.MouseButtonRelease, cells[-1], button)
    application.processEvents()


def last_commands(session):
    return session.history()[-1].commands if session.history() else []


workspaces: list[str] = []


def open_workspace(text: str):
    """A throwaway project holding one map, and a session over it.

    Each of the states below is a different MAP, so each gets its own
    directory -- including its own `data/graphics/`, which is where the
    provisioned sheet lands. Sharing one would make "the sheet was written
    by this stroke" and "the sheet was already there" the same assertion.
    """
    workspace = tempfile.mkdtemp(prefix="pyoneer_collision_mount_")
    workspaces.append(workspace)
    os.makedirs(os.path.join(workspace, "config"))
    os.makedirs(os.path.join(workspace, "data", "maps"))
    path = os.path.join(workspace, "data", "maps", "fixture.tmx")
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    with open(os.path.join(workspace, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [{"name": "fixture", "identifier": "fixture",
                             "file": "data/maps/fixture.tmx"}]}, handle)
    return workspace, path, Session.open(workspace, genre_id="topdown_rpg")


def sheet_path(fixture_path: str) -> str:
    """Where the offer's relative image resolves for this map -- the same
    join `collision_tileset_offer` does, so a change to COLLISION_IMAGE
    moves the check with it instead of leaving it asserting an old path."""
    return os.path.normpath(
        os.path.join(os.path.dirname(fixture_path), COLLISION_IMAGE))


def among(needle: str, lines: list[str]) -> bool:
    """Was this said at all, anywhere in the gesture?

    NOT `lines[-1]`. A refused press starts no stroke, so the mouse moves
    that follow it fall through to the collision-mode cell readout and that
    is what ends up last -- which is true of every refusal on this path and
    always has been. What is under test is that the editor SAID why, in the
    channel the author is looking at, rather than doing nothing.
    """
    return any(needle in line for line in lines)


def refuses_to_write(path: str) -> bool:
    """Does `write_mask_sheet` RAISE rather than report success?

    Law 7, and the half a permissive check skips. The failure mode this
    guards is not an exception escaping -- it is an exception NEVER
    happening: `QImage.save` returns False and raises nothing, so an
    unchecked call leaves the caller declaring a tileset whose image is not
    on disk.
    """
    try:
        write_mask_sheet(path, 16, 16)
    except OSError:
        return True
    return False


def collision_canvas(session, *, layer: str | None = "Floor",
                     mask: int = BLOCK_ALL):
    window = Harness(session, "fixture")
    window.show()
    application.processEvents()
    window.canvas.set_active_layer(layer)
    window.canvas.set_mode(EditMode.COLLISION)
    window.canvas.tool = Tool.BRUSH
    window.canvas.set_mask(mask)
    application.processEvents()
    return window


application = QApplication.instance() or QApplication([])

try:
    workspace, fixture_path, session = open_workspace(FIXTURE)
    document = session.project.map("fixture")
    ORIGINAL = document.to_bytes()

    window = Harness(session, "fixture")
    window.show()
    application.processEvents()
    canvas = window.canvas
    canvas.set_active_layer("Floor")
    application.processEvents()

    MASK_GID = COLLISION_FIRST_GID + BLOCK_ALL

    # ----------------------------------------------------------------
    print("the overlay is mounted, sized to the map")
    # ----------------------------------------------------------------
    overlay = canvas.overlay
    expect("the canvas built one", overlay is not None, True)
    expect("sized to the map, in cells and in pixels",
           (overlay.width, overlay.height,
            overlay.tile_width, overlay.tile_height), (WIDTH, HEIGHT, 16, 16))
    expect("and it is in the scene", overlay.scene() is canvas.scene(), True)
    expect("above the grid, below the stroke ghost",
           1000 < overlay.zValue() < 2000, True)
    expect("hidden until collision mode", overlay.isVisible(), False)
    expect("the fixture's collision tileset was found",
           canvas.collision_first_gid, COLLISION_FIRST_GID)

    # ----------------------------------------------------------------
    print()
    print("it survives the scene clear that happens on every command")
    # ----------------------------------------------------------------
    # scene.clear() DELETES its items C++-side. If the canvas does not
    # detach the overlay first, the Python wrapper outlives the object it
    # wraps and the next touch is a RuntimeError -- or, in a build without
    # the guard, a crash.
    canvas.rebuild()
    application.processEvents()
    expect("the same item, not a new one", canvas.overlay is overlay, True)
    alive = True
    try:
        overlay.mask_at(0, 0)
        in_scene = overlay.scene() is canvas.scene()
    except RuntimeError:
        alive, in_scene = False, False
    expect("still alive after the clear", alive, True)
    expect("and re-added to the fresh scene", in_scene, True)

    # ----------------------------------------------------------------
    print()
    print("a layer that declares renders=false is not drawn as art")
    # ----------------------------------------------------------------
    # The fixture has three tile layers and one of them is data. Drawing a
    # companion layer's mask gids through the tile atlas puts confetti over
    # the map -- and the collision layer this canvas creates would do it
    # from the first stroke.
    drawn = [i for i in canvas.scene().items()
             if isinstance(i, QGraphicsPixmapItem)]
    expect("two art layers drawn, the data layer skipped", len(drawn), 2)

    # ----------------------------------------------------------------
    print()
    print("switching modes changes what a stroke emits")
    # ----------------------------------------------------------------
    canvas.stamp = Stamp.single(9)
    canvas.tool = Tool.BRUSH
    drag(application, canvas, [(1, 3), (3, 3)])
    tiles_command = last_commands(session)[-1]
    expect("in tiles mode it writes the layer you selected",
           (str(tiles_command.scope), tiles_command.verb),
           ("map:fixture/layer:Floor", "map.tile.set_many"))
    expect("with the palette's gid",
           {gid for _x, _y, gid in tiles_command.args["tiles"]}, {9})
    window.undo()
    expect("undone", session.project.map("fixture").to_bytes() == ORIGINAL, True)

    canvas.set_mode(EditMode.COLLISION)
    application.processEvents()
    expect("the overlay shows itself in collision mode",
           canvas.overlay.isVisible(), True)
    canvas.set_mask(BLOCK_ALL)
    bakes.clear()
    touched.clear()
    before = len(session.history())
    drag(application, canvas, [(1, 3), (3, 3)])
    transaction = session.history()[-1]
    collision_command = transaction.commands[-1]
    expect("the same drag now writes the companion layer",
           (str(collision_command.scope), collision_command.verb),
           ("map:fixture/layer:FloorCollision", "map.tile.set_many"))
    expect("and writes a MASK gid, not a tile",
           {gid for _x, _y, gid in collision_command.args["tiles"]}, {MASK_GID})
    expect("the art layer itself was not touched",
           set(session.project.map("fixture").tile_layer("Floor").gids()), {0})
    expect("three cells, as dragged", len(collision_command.args["tiles"]), 3)

    # ----------------------------------------------------------------
    print()
    print("one stroke is ONE transaction, companion layer included")
    # ----------------------------------------------------------------
    expect("a single transaction entered the history",
           len(session.history()) - before, 1)
    expect("carrying the layer, its declaration, its kind and the tiles",
           [c.verb for c in transaction.commands],
           ["map.layer.add", "map.layer.set", "map.layer.set",
            "map.tile.set_many"])
    floor = session.project.map("fixture").tile_layer("Floor")
    expect("the art layer now points at its companion",
           read_profile(floor).passability, "FloorCollision")
    companion = session.project.map("fixture").tile_layer("FloorCollision")
    expect("which is declared data, not art", read_profile(companion).renders,
           False)
    expect("and holds the mask", companion.get_tile(2, 3), MASK_GID)

    # ----------------------------------------------------------------
    print()
    print("the overlay was updated per stroke, not re-baked")
    # ----------------------------------------------------------------
    expect("the three painted cells were written directly",
           sorted(touched), [(1, 3), (2, 3), (3, 3)])
    expect("no full bake, despite the rebuild the command triggered",
           bakes, [])
    expect("and the readout agrees with the document",
           canvas.overlay.mask_at(2, 3), BLOCK_ALL)

    # ----------------------------------------------------------------
    print()
    print("one undo takes the whole stroke back, layer and all")
    # ----------------------------------------------------------------
    bakes.clear()
    window.undo()
    application.processEvents()
    document = session.project.map("fixture")
    expect("the companion layer is gone",
           "FloorCollision" in document.tile_layer_names(), False)
    expect("the declaration with it",
           read_profile(document.tile_layer("Floor")).passability, "")
    expect("byte-identical", document.to_bytes() == ORIGINAL, True)
    # An undo is a change this canvas did not make, so the incremental path
    # cannot know about it. Without the stream subscription the overlay
    # would happily keep showing masks the map no longer holds.
    expect("the readout re-baked rather than believing itself",
           len(bakes), 1)
    expect("and shows nothing again", canvas.overlay.mask_at(2, 3), NO_DATA)

    # ----------------------------------------------------------------
    print()
    print("erasing collision means 'nobody said', not 'open'")
    # ----------------------------------------------------------------
    # gid 0 in a companion layer is NO_DATA, and NO_DATA is what lets a
    # layer below be asked. PASS_ALL is an assertion -- a hole punched
    # through a wall -- and an eraser that wrote it would silently unblock
    # everything underneath.
    drag(application, canvas, [(5, 4)])
    expect("painted first", canvas.overlay.mask_at(5, 4), BLOCK_ALL)
    drag(application, canvas, [(5, 4)], button=Qt.RightButton)
    erased = session.project.map("fixture").tile_layer("FloorCollision")
    expect("the cell is empty again", erased.get_tile(5, 4), 0)
    expect("which reads as no opinion",
           gid_to_opinion(erased.get_tile(5, 4), COLLISION_FIRST_GID), NO_DATA)
    expect("and is NOT 'open'",
           gid_to_opinion(erased.get_tile(5, 4), COLLISION_FIRST_GID)
           == PASS_ALL, False)
    expect("the overlay agrees", canvas.overlay.mask_at(5, 4), NO_DATA)

    # ----------------------------------------------------------------
    print()
    print("terrain has no meaning here, and says so instead of writing")
    # ----------------------------------------------------------------
    messages: list[str] = []
    canvas.status.connect(messages.append)
    canvas.tool = Tool.AUTOTILE
    before = len(session.history())
    drag(application, canvas, [(6, 1), (7, 1)])
    expect("nothing was written", len(session.history()) - before, 0)
    expect("the user was told why",
           any("collision mode" in m for m in messages), True)
    expect("which is what the mode itself declares",
           EditMode.COLLISION.allows(Tool.AUTOTILE), False)
    canvas.tool = Tool.BRUSH
    canvas.status.disconnect(messages.append)

    # ----------------------------------------------------------------
    print()
    print("all layers resolves the stack instead of stacking it")
    # ----------------------------------------------------------------
    x, y = CONFLICT_CELL
    drag(application, canvas, [CONFLICT_CELL])
    expect("the active layer's own opinion is what one layer shows",
           canvas.overlay.mask_at(x, y), BLOCK_ALL)
    expect("with nobody named as the decider", canvas.overlay.owner_at(x, y), -1)

    # Stated rather than assumed: everything below depends on which layer is
    # on top, and `resolve` takes the stack TOPMOST FIRST -- the reverse of a
    # tmx layer list. If a future genre pack or depth change flips this, the
    # failure should name the cause.
    expect("the stack is built topmost first",
           [layer.name for layer in canvas.collision_stack()],
           ["Roof", "Floor"])

    bakes.clear()
    canvas.set_all_layers(True)
    application.processEvents()
    expect("turning it on resolves the whole stack", bakes, ["resolved"])
    expect("the topmost layer with an opinion wins",
           canvas.overlay.mask_at(x, y), BLOCK_UP)
    expect("it is named", canvas.overlay.owner_at(x, y), 0)
    expect("and the layer below is flagged as disagreeing",
           canvas.overlay.conflicted_at(x, y), True)
    expect("a cell nobody authored stays silent",
           canvas.overlay.mask_at(6, 5), NO_DATA)

    # A stroke while resolved must re-resolve the cells it touched, not
    # write the raw mask over the top of an answer that came from elsewhere.
    touched.clear()
    bakes.clear()
    canvas.set_mask(PASS_ALL)
    drag(application, canvas, [(x, y)])
    expect("painting under the resolved view re-resolves the cell",
           (sorted(touched), bakes), ([(x, y)], []))
    expect("so the upper layer still wins", canvas.overlay.mask_at(x, y),
           BLOCK_UP)
    # PASS_ALL is an assertion -- "open, deliberately" -- so painting it
    # under a blocked cell is still two layers saying different things. Only
    # NO_DATA and STAR abstain, and neither is what the brush just wrote.
    expect("and 'open' underneath is still a disagreement, not agreement",
           canvas.overlay.conflicted_at(x, y), True)

    canvas.set_all_layers(False)
    canvas.set_mode(EditMode.TILES)
    application.processEvents()
    expect("leaving collision mode hides the readout",
           canvas.overlay.isVisible(), False)

    window.close()

    # ==================================================================
    print()
    print("THE SEAM IS GONE: no consent step exists to answer")
    # ==================================================================
    # Structural, not behavioural, and deliberately so. "No modal fired on
    # the paths I happened to drive" is a claim about coverage; "there is
    # no QMessageBox in this module and no seam on this class" is a claim
    # about the module. The second one stops the dialog growing back in a
    # branch nobody thought to drag through.
    expect("no modal was raised by anything above", modals, [])
    expect("MapCanvas carries no `confirm` attribute",
           hasattr(canvas, "confirm"), False)
    expect("...and none is set on the class either",
           hasattr(MapCanvas, "confirm"), False)
    expect("canvas.py exposes no QMessageBox in its namespace",
           hasattr(canvas_module, "QMessageBox"), False)

    imported: list[str] = []
    for node in ast.walk(ast.parse(inspect.getsource(canvas_module))):
        if isinstance(node, ast.ImportFrom):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
    expect("...and does not import one, by AST rather than by grep",
           [name for name in imported if "MessageBox" in name], [])
    expect("the writer that replaced it is importable and public",
           callable(write_mask_sheet), True)

    # ==================================================================
    print()
    print("A MAP WITH NO COLLISION TILESET: the cheap refusals come first")
    # ==================================================================
    # Nothing may be provisioned for a gesture that was going to be refused
    # anyway. Before this pass the tileset gate ran FIRST, so clicking with
    # no layer selected produced a 191-word dialog, and the "select a tile
    # layer" message five lines below it was unreachable until the tileset
    # existed.
    _ws, bare_path, bare = open_workspace(fixture(None))
    BARE_ORIGINAL = bare.project.map("fixture").to_bytes()
    SHEET = sheet_path(bare_path)
    window = collision_canvas(bare, layer=None)
    canvas = window.canvas
    said: list[str] = []
    canvas.status.connect(said.append)

    expect("this map declares no collision tileset",
           canvas.collision_first_gid, None)
    expect("and the sheet it would declare is not on disk",
           os.path.exists(SHEET), False)

    def refusal(label, *, tool=Tool.BRUSH, layer=None, button=Qt.LeftButton,
                cells=((1, 3), (3, 3))):
        """Drive one gesture that must be refused, and report what it cost."""
        canvas.tool = tool
        canvas.set_active_layer(layer)
        said.clear()
        before = len(bare.history())
        drag(application, canvas, list(cells), button=button)
        expect(f"{label}: no command",
               len(bare.history()) - before, 0)
        expect(f"{label}: no sheet written", os.path.exists(SHEET), False)
        expect(f"{label}: the document is untouched",
               bare.project.map("fixture").to_bytes() == BARE_ORIGINAL, True)
        return said

    told = refusal("no layer selected", layer=None)
    expect("...and it says which one to select",
           any("select a tile layer" in m for m in told), True)

    told = refusal("terrain in collision mode", tool=Tool.AUTOTILE,
                   layer="Floor")
    expect("...and it says why terrain cannot mean anything here",
           any("collision mode" in m for m in told), True)

    told = refusal("picker with nothing to pick", tool=Tool.PICKER,
                   layer="Floor")
    expect("...and it says there is no mask there",
           any("no mask here to pick" in m for m in told), True)

    told = refusal("right-drag erase on a map with no collision",
                   layer="Floor", button=Qt.RightButton)
    expect("...and it says there is nothing to erase",
           any("nothing to erase" in m for m in told), True)

    # ==================================================================
    print()
    print("...and then the stroke PAINTS, in one transaction, tileset first")
    # ==================================================================
    canvas.tool = Tool.BRUSH
    canvas.set_active_layer("Floor")
    said.clear()
    before = len(bare.history())
    drag(application, canvas, [(1, 3), (2, 3), (3, 3)])
    expect("one transaction, not two and not none",
           len(bare.history()) - before, 1)
    transaction = bare.history()[-1]
    expect("the tileset is declared IN FRONT OF the tiles it is for",
           [c.verb for c in transaction.commands],
           ["map.tileset.add", "map.layer.add", "map.layer.set",
            "map.layer.set", "map.tile.set_many"])
    # Inverse i belongs to command i, and undo walks them in REVERSE -- so
    # the tileset's remove runs LAST, after `map.tile.set_many`'s inverse has
    # already zeroed every gid pointing into the range. That is the one
    # situation `force=False` is safe in, and it stays False here on purpose:
    # a forced remove outside that ordering silently repaints orphaned tiles.
    expect("...and its inverse is the GUARDED remove, unwound last",
           (transaction.inverses[0].verb,
            transaction.inverses[0].args["force"]),
           ("map.tileset.remove", False))
    expect("the undo entry reads as the stroke, not as the plumbing",
           transaction.label, "Brush collision (3 cells)")
    painted = bare.project.map("fixture")
    expect("the map now has a gid range for masks",
           canvas.collision_first_gid, 257)
    expect("THE GESTURE THAT ASKED IS THE GESTURE THAT PAINTED",
           painted.tile_layer("FloorCollision").get_tile(2, 3),
           257 + BLOCK_ALL)
    expect("all three cells of it, not 'paint again'",
           len(transaction.commands[-1].args["tiles"]), 3)
    expect("no modal was raised getting there", modals, [])

    # ==================================================================
    print()
    print("the sheet is on disk, and the author is told in one line")
    # ==================================================================
    expect("the PNG the declaration points at exists",
           os.path.isfile(SHEET), True)
    written = QImage(SHEET)
    expect("...at the size the tileset declares, one row of seventeen",
           (written.width(), written.height()),
           (16 * len(MASK_DOMAIN), 16))
    expect("the last thing said names the tileset and the file",
           bool(said) and COLLISION_TILESET in said[-1]
           and SHEET in said[-1], True)
    expect("...and says it in words, not in gid arithmetic",
           any(term in said[-1] for term in ("firstgid", "gid ", "pytmx")),
           False)

    # ==================================================================
    print()
    print("EVERY layer is paintable after that, with no ceremony at all")
    # ==================================================================
    # The author's actual complaint, restated: clicking a collision tile
    # paints a mask. Roof already declares its companion, so there is
    # nothing left for this stroke to arrange -- and in particular it must
    # not carry the previous stroke's `map.tileset.add` along with it.
    AFTER = bare.project.map("fixture").to_bytes()
    canvas.set_active_layer("Roof")
    before = len(bare.history())
    drag(application, canvas, [(4, 4)])
    expect("a second layer paints", len(bare.history()) - before, 1)
    expect("...as ONE command, because everything it needs already exists",
           [c.verb for c in bare.history()[-1].commands], ["map.tile.set_many"])
    expect("...into the companion IT declares, not the first layer's",
           str(bare.history()[-1].commands[0].scope),
           "map:fixture/layer:RoofCollision")
    expect("...and no second sheet was written for it",
           QImage(SHEET).height(), 16)
    window.undo()
    canvas.set_active_layer("Floor")
    application.processEvents()
    expect("...and taking it back out is byte-exact",
           bare.project.map("fixture").to_bytes() == AFTER, True)

    # ==================================================================
    print()
    print("undo is exact, and leaves the file it did not write")
    # ==================================================================
    for turn in range(2):
        window.undo()
        application.processEvents()
        expect(f"undo {turn + 1}: byte-identical to before the stroke",
               bare.project.map("fixture").to_bytes() == BARE_ORIGINAL, True)
        expect(f"undo {turn + 1}: the declaration is gone",
               canvas.collision_first_gid, None)
        expect(f"undo {turn + 1}: the PNG is still there",
               os.path.isfile(SHEET), True)
        window.redo()
        application.processEvents()
        expect(f"redo {turn + 1}: byte-identical to after the stroke",
               bare.project.map("fixture").to_bytes() == AFTER, True)
        expect(f"redo {turn + 1}: and it did not rewrite the file",
               os.path.isfile(SHEET), True)
    window.undo()
    application.processEvents()

    # ==================================================================
    print()
    print("an author's own sheet is measured, never overwritten")
    # ==================================================================
    # The deleted dialog's stated fear -- "undo must not delete a file you
    # may have since painted" -- is answered by create-only-if-absent, and
    # this is the half of that invariant that a permissive check skips.
    sentinel = QImage(16 * len(MASK_DOMAIN), 32, QImage.Format_ARGB32)
    sentinel.fill(Qt.magenta)
    expect("a two-row sheet of the author's own is put in place",
           sentinel.save(SHEET, "PNG"), True)
    offer = canvas.collision_tileset_offer()
    expect("the offer measures it rather than assuming the canonical size",
           (offer.exists, offer.image_height, offer.tile_count),
           (True, 32, 2 * len(MASK_DOMAIN)))
    before = len(bare.history())
    drag(application, canvas, [(0, 0)])
    expect("the stroke still lands", len(bare.history()) - before, 1)
    surviving = QImage(SHEET)
    expect("AND THE AUTHOR'S FILE IS UNTOUCHED",
           (surviving.height(), surviving.pixelColor(0, 0).name()),
           (32, "#ff00ff"))
    expect("...and the tileset declared matches what is actually on disk",
           [c.args["image_height"] for c in bare.history()[-1].commands
            if c.verb == "map.tileset.add"], [32])
    window.undo()
    application.processEvents()
    os.remove(SHEET)
    window.close()

    # ==================================================================
    print()
    print("AN UNWRITABLE TARGET REFUSES, and runs no command")
    # ==================================================================
    # Two arms, because there are two ways to fail and only one of them
    # raises on its own. `QImage.save` returns False and raises NOTHING --
    # measured over a read-only target -- so an unchecked call reports
    # success and declares a tileset pointing at no file, which is the
    # unbootable map the whole change exists to stop producing.
    _ws, blocked_path, blocked = open_workspace(fixture(None))
    BLOCKED_ORIGINAL = blocked.project.map("fixture").to_bytes()
    BLOCKED_SHEET = sheet_path(blocked_path)
    os.makedirs(os.path.dirname(os.path.dirname(BLOCKED_SHEET)),
                exist_ok=True)
    # A FILE where the directory has to go: os.makedirs(exist_ok=True) still
    # raises FileExistsError, because the path exists and is not a directory.
    with open(os.path.dirname(BLOCKED_SHEET), "w", encoding="utf-8") as handle:
        handle.write("not a directory")
    window = collision_canvas(blocked)
    canvas = window.canvas
    said = []
    canvas.status.connect(said.append)
    before = len(blocked.history())
    drag(application, canvas, [(1, 1), (2, 1)])
    expect("the makedirs failure runs no command",
           len(blocked.history()) - before, 0)
    expect("...leaves the document byte-identical",
           blocked.project.map("fixture").to_bytes() == BLOCKED_ORIGINAL, True)
    expect("...names the path it could not write",
           among(BLOCKED_SHEET, said), True)
    expect("...and says so as a status line, not a dialog",
           (among("could not write", said), modals), (True, []))

    # The second arm. The directory is unblocked, so `makedirs` succeeds and
    # the ONLY thing left to fail is the save -- which fails the way Qt
    # actually fails, by returning False and raising nothing. Patched on the
    # module rather than on the C++ type, because `write_mask_sheet` reads
    # `QImage` out of its own module globals.
    os.remove(os.path.dirname(BLOCKED_SHEET))

    class _SilentlyFailingImage(QImage):
        def save(self, *_args, **_kwargs) -> bool:
            return False

    canvas_module.QImage = _SilentlyFailingImage
    try:
        expect("a save() that returns False RAISES rather than reporting "
               "success", refuses_to_write(BLOCKED_SHEET), True)
        expect("...and left no file behind to be believed",
               os.path.exists(BLOCKED_SHEET), False)
        said.clear()
        before = len(blocked.history())
        drag(application, canvas, [(1, 1), (2, 1)])
        expect("the stroke above it runs no command either",
               len(blocked.history()) - before, 0)
        expect("...leaving the document byte-identical",
               blocked.project.map("fixture").to_bytes() == BLOCKED_ORIGINAL,
               True)
        expect("...and no tileset declared for an image that is not there",
               blocked.project.map("fixture").tileset_names(), ["Art"])
        expect("...and saying so where the author will see it",
               among("could not write", said), True)
    finally:
        canvas_module.QImage = QImage
    window.close()

    # ==================================================================
    print()
    print("A DECLARED TILESET TOO SMALL FOR THE MASKS REFUSES THE STROKE")
    # ==================================================================
    # The bug this pass found, and the half of the invariant that did not
    # exist. `sufficient` guarded only the ADD path, so a map that already
    # declared a five-tile `collision` tileset painted masks as gids past
    # the end of its own sheet -- BLOCK_ALL is firstgid+15 against a range
    # that stops at firstgid+4 -- with no status line from anywhere.
    _ws, small_path, small = open_workspace(fixture(5))
    SMALL_ORIGINAL = small.project.map("fixture").to_bytes()
    window = collision_canvas(small)
    canvas = window.canvas
    said = []
    canvas.status.connect(said.append)
    expect("the map DOES resolve a firstgid, which is why nothing caught it",
           canvas.collision_first_gid, COLLISION_FIRST_GID)
    declared = canvas.collision_tileset_ref()
    expect("and the tileset it resolves to holds five tiles",
           (declared.name, declared.tile_count, declared.last_gid),
           ("collision", 5, COLLISION_FIRST_GID + 4))
    expect("...while the mask the brush holds needs one past its end",
           COLLISION_FIRST_GID + BLOCK_ALL > declared.last_gid, True)

    before = len(small.history())
    drag(application, canvas, [(1, 1), (3, 1)])
    expect("the stroke is refused", len(small.history()) - before, 0)
    expect("...the document is byte-identical",
           small.project.map("fixture").to_bytes() == SMALL_ORIGINAL, True)
    expect("...no companion layer was created for it",
           "FloorCollision" in small.project.map("fixture").tile_layer_names(),
           False)
    expect("...the refusal names what is declared and what will not fit",
           (among(f"{declared.tile_count} tiles", said),
            among(f"{len(MASK_DOMAIN)} masks", said)), (True, True))
    expect("...and the gid range, so the author can find it in Tiled",
           among(f"{declared.first_gid}", said), True)
    expect("...and it is a status line, not a dialog", modals, [])
    expect("...and the tileset was NOT auto-repaired behind the author",
           canvas.collision_tileset_ref().tile_count, 5)
    window.close()

    # ==================================================================
    print()
    print("THE SAVED MAP STILL BOOTS -- the assertion the old design failed")
    # ==================================================================
    # This is the one that matters. The deleted dialog's Yes button wrote a
    # <tileset> pointing at a PNG it refused to create, and `pygame.image
    # .load` raises FileNotFoundError inside pytmx's image loader, so the
    # editor drove the project into a state the engine cannot open --
    # through its own command stream, to protect an inverse. Both halves
    # here: WITH the provisioned sheet the map loads, and WITHOUT it the
    # same map raises. The second half is what says the file is load-bearing
    # rather than decorative.
    if (importlib.util.find_spec("pygame") is None
            or importlib.util.find_spec("pytmx") is None):
        print("  ....  skipped: pygame/pytmx not installed")
    else:
        import pygame                                          # noqa: E402
        from pytmx.util_pygame import load_pygame              # noqa: E402

        _ws, boot_path, boot = open_workspace(fixture(None))
        BOOT_SHEET = sheet_path(boot_path)
        art = QImage(256, 256, QImage.Format_ARGB32)
        art.fill(Qt.transparent)
        art.save(os.path.join(os.path.dirname(boot_path), "art.png"), "PNG")
        window = collision_canvas(boot)
        drag(application, window.canvas, [(2, 2), (3, 2)])
        expect("the stroke landed", len(boot.history()), 1)
        with open(boot_path, "wb") as handle:
            handle.write(boot.project.map("fixture").to_bytes())

        pygame.init()
        pygame.display.set_mode((32, 32))

        def loads(path: str) -> str:
            try:
                load_pygame(path)
            except Exception as exc:                            # noqa: BLE001
                return type(exc).__name__
            return "loaded"

        expect("pytmx opens the map the editor just wrote",
               loads(boot_path), "loaded")
        os.remove(BOOT_SHEET)
        expect("...and would NOT have, without the sheet it provisioned",
               loads(boot_path), "FileNotFoundError")
        window.close()

    # ==================================================================
    print()
    print("A 4x MAP IN A REAL CANVAS: the mask lands UNDER THE CURSOR")
    # ==================================================================
    # The check whose absence let a whole pass ship green. Everything here
    # is driven in scene PIXELS and asserted in pixels, because the failure
    # was that the canvas and the file disagreed about what a cell is -- and
    # any assertion phrased in cells is phrased in the very unit under test.
    _ws, fine_path, fine = open_workspace(fine_fixture())
    FINE_ORIGINAL = fine.project.map("fixture").to_bytes()
    window = collision_canvas(fine)
    canvas = window.canvas
    said = []
    canvas.status.connect(said.append)

    expect("the map is 4 tiles of 16px, so 64 scene pixels across",
           (fine.project.map("fixture").width,
            fine.project.map("fixture").tile_width), (FINE_TILES, TILE))
    expect("its companion declares four sub-cells per tile",
           canvas.paint_subcell, FINE_SUB)
    expect("so ONE addressable cell is a quarter-tile, not a tile",
           (canvas.paint_width, canvas.paint_height), (FINE_CELL, FINE_CELL))

    # A pixel chosen to be unambiguous: 26 is inside sub-cell 6 (24..27) and
    # inside map tile 1 (16..31), so a canvas addressing tiles and a canvas
    # addressing sub-cells give visibly different answers for it.
    CLICK = (26.0, 26.0)
    expect("the cell under that pixel is the sub-cell, not the tile",
           canvas.cell_at(*CLICK), (6, 6))

    before = len(fine.history())
    click_px(application, canvas, *CLICK)
    companion = fine.project.map("fixture").tile_layer("FloorCollision")
    marks = painted_cells(companion)
    expect("one click, one transaction", len(fine.history()) - before, 1)
    expect("...writing exactly one cell of the companion", len(marks), 1)
    expect("THE MASK LANDED IN THE SUB-CELL UNDER THE CURSOR",
           bool(marks) and covers(marks[0], FINE_CELL, CLICK), True)
    expect("...which is that sub-cell and no other", marks, [(6, 6)])
    expect("...and it is the mask the brush held",
           companion.get_tile(6, 6), COLLISION_FIRST_GID + BLOCK_ALL)
    # The bug, named as a number rather than as a memory. Cell (1, 1) is
    # where a canvas addressing whole tiles would have put this, and it owns
    # pixels 4..7 -- so the wall would have been 20px up and 20px left.
    expect("...NOT the whole-tile cell, which owns pixels 4..7",
           covers((1, 1), FINE_CELL, CLICK), False)
    expect("...and that cell is empty, so nothing was written twice",
           companion.get_tile(1, 1), 0)

    # ----------------------------------------------------------------
    print()
    print("the overlay's cells are the COMPANION's cells")
    # ----------------------------------------------------------------
    overlay = canvas.overlay
    expect("sized from the companion: 16x16 cells of 4px",
           (overlay.width, overlay.height,
            overlay.tile_width, overlay.tile_height),
           (FINE_SIDE, FINE_SIDE, FINE_CELL, FINE_CELL))
    expect("...which still covers exactly the map's pixels",
           (overlay.boundingRect().width(), overlay.boundingRect().height()),
           (float(FINE_TILES * TILE), float(FINE_TILES * TILE)))
    expect("and the readout agrees with the file, cell for cell",
           (overlay.mask_at(6, 6), overlay.mask_at(1, 1)),
           (BLOCK_ALL, NO_DATA))

    # ----------------------------------------------------------------
    print()
    print("the far corner is reachable: bounds come from the LAYER")
    # ----------------------------------------------------------------
    # Sub-cell (15, 15) owns pixels 60..63. A stroke bounded by the MAP's
    # 4x4 would clip every cell past 3 and write nothing at all here.
    FAR = (62.0, 62.0)
    click_px(application, canvas, *FAR)
    companion = fine.project.map("fixture").tile_layer("FloorCollision")
    expect("the last sub-cell of the map takes a mask",
           companion.get_tile(FINE_SIDE - 1, FINE_SIDE - 1),
           COLLISION_FIRST_GID + BLOCK_ALL)
    expect("...and it is the cell that owns the clicked pixel",
           covers((FINE_SIDE - 1, FINE_SIDE - 1), FINE_CELL, FAR), True)
    window.close()

    # The other half of that bound, and the only shape that separates "the
    # layer's own size" from "map x subcell": a companion authored over just
    # the top-left quarter of the map. Cells past its edge are not merely
    # unpainted, they do not exist, and `file_gid_reader` answering 0 past
    # them is what makes that legal.
    _ws, small_fine_path, small_fine = open_workspace(fine_fixture(side=8))
    SMALL_FINE_ORIGINAL = small_fine.project.map("fixture").to_bytes()
    window = collision_canvas(small_fine)
    canvas = window.canvas
    expect("a companion may cover part of the map and still be read",
           (canvas.paint_subcell,
            small_fine.project.map("fixture").tile_layer(
                "FloorCollision").width), (FINE_SUB, 8))
    click_px(application, canvas, 30.0, 30.0)          # sub-cell (7, 7)
    inside = small_fine.project.map("fixture").tile_layer("FloorCollision")
    expect("a cell inside it is painted", inside.get_tile(7, 7),
           COLLISION_FIRST_GID + BLOCK_ALL)
    before = len(small_fine.history())
    click_px(application, canvas, 42.0, 42.0)          # sub-cell (10, 10)
    expect("a cell past its edge writes nothing at all",
           len(small_fine.history()) - before, 0)
    expect("...and leaves the map exactly as the first stroke left it",
           painted_cells(small_fine.project.map("fixture").tile_layer(
               "FloorCollision")), [(7, 7)])
    expect("...which is not the same as being outside the MAP: it is not",
           covers((10, 10), FINE_CELL, (42.0, 42.0)), True)

    # And the resolved view over that same partial map. The field is as big
    # as the FINEST layer, so every cell past this companion's edge is a read
    # it cannot answer -- 192 of the 256. `MapDocument.get_tile` raises on
    # those, so before `layer_from_companion` went through the engine's
    # `document_gid_reader` this turned All layers into a PyoneerConfigError
    # mid-rebuild, on a map shape the runtime supports on purpose.
    bakes.clear()
    resolved = "built"
    try:
        canvas.set_all_layers(True)
        application.processEvents()
    except Exception as exc:                                    # noqa: BLE001
        resolved = type(exc).__name__
    expect("All layers over a partly-authored companion still builds",
           resolved, "built")
    expect("...covering the whole map, at the finest declared resolution",
           (canvas.overlay.width, canvas.overlay.height,
            canvas.overlay.tile_width),
           (FINE_SIDE, FINE_SIDE, FINE_CELL))
    expect("...showing the wall that is authored",
           canvas.overlay.mask_at(7, 7), BLOCK_ALL)
    expect("...and abstaining past the companion's edge, not erroring",
           (canvas.overlay.mask_at(8, 8), canvas.overlay.mask_at(15, 15)),
           (NO_DATA, NO_DATA))
    window.close()

    # ==================================================================
    print()
    print("THE 1x CASE, IN THE SAME SHAPE -- the migration guarantee")
    # ==================================================================
    # The half that breaks. A map with no `pyoneer_subcell` anywhere is
    # every map this editor has ever written, and it has to keep addressing
    # whole tiles: the property's absence MEANS 1, which is the file
    # format's documented default and not a fallback anybody guessed at.
    _ws, plain_path, plain = open_workspace(fine_fixture(declare=None,
                                                         side=FINE_TILES))
    window = collision_canvas(plain)
    canvas = window.canvas
    expect("an absent property still means one mask per tile",
           canvas.paint_subcell, 1)
    expect("so a cell is a whole tile again",
           (canvas.paint_width, canvas.paint_height), (TILE, TILE))
    expect("and the same pixel resolves to the tile that owns it",
           canvas.cell_at(*CLICK), (1, 1))
    click_px(application, canvas, *CLICK)
    plain_companion = plain.project.map("fixture").tile_layer("FloorCollision")
    plain_marks = painted_cells(plain_companion)
    expect("THE MASK LANDED IN THE TILE UNDER THE CURSOR",
           bool(plain_marks) and covers(plain_marks[0], TILE, CLICK), True)
    expect("...which is one cell, and that cell", plain_marks, [(1, 1)])
    expect("the overlay is the map's own grid, as it always was",
           (canvas.overlay.width, canvas.overlay.height,
            canvas.overlay.tile_width, canvas.overlay.tile_height),
           (FINE_TILES, FINE_TILES, TILE, TILE))
    # A 1x map must not acquire a finer grid from the mode either: switching
    # to tiles and back is the gesture an author makes constantly.
    canvas.set_mode(EditMode.TILES)
    application.processEvents()
    expect("tile mode addresses tiles on a 1x map",
           (canvas.paint_width, canvas.paint_height), (TILE, TILE))
    window.close()

    # And the same for TILE mode on the 4x map: a companion's resolution is
    # none of an art stroke's business, and a grid that quartered itself
    # when the author went back to painting floor would be unusable.
    window = collision_canvas(fine, layer="Floor")
    canvas = window.canvas
    canvas.set_mode(EditMode.TILES)
    application.processEvents()
    expect("tile mode on a 4x map STILL addresses tiles",
           (canvas.paint_subcell, canvas.paint_width), (1, TILE))
    canvas.stamp = Stamp.single(9)
    before = len(fine.history())
    click_px(application, canvas, *CLICK)
    art = fine.project.map("fixture").tile_layer("Floor")
    expect("...so an art stroke writes the tile under the cursor",
           painted_cells(art), [(1, 1)])
    expect("...as its own transaction", len(fine.history()) - before, 1)
    window.undo()
    application.processEvents()
    window.close()

    # THE HALF THAT WAS MISSING, and it is the whole reason the 1,200px bug
    # survived a pass that was chartered to kill exactly it. The block above
    # selects the ART layer and proves a tile-mode cell is a tile. Nobody
    # selected the DATA layer -- and a companion is a selectable row in the
    # Layers panel, so an author reaches it with one click. Proved for the art
    # layer, never proved for the data layer: the repo's dominant shape.
    # A FRESH fixture, because the blocks above have painted this one and an
    # absolute assertion would be measuring their residue rather than this
    # stroke -- which is how a placement bug hides inside a passing check.
    _ws2, _fine2_path, fine2 = open_workspace(fine_fixture())
    window = collision_canvas(fine2, layer="FloorCollision")
    canvas = window.canvas
    canvas.set_mode(EditMode.TILES)
    application.processEvents()
    expect("tile mode ON THE COMPANION addresses SUB-cells, because the "
           "resolution is the layer's and not the mode's",
           (canvas.paint_subcell, canvas.paint_width), (FINE_SUB, FINE_CELL))
    canvas.stamp = Stamp.single(COLLISION_FIRST_GID + BLOCK_ALL)
    companion = fine2.project.map("fixture").tile_layer("FloorCollision")
    was = set(painted_cells(companion))
    before = len(fine2.history())
    click_px(application, canvas, *CLICK)
    companion = fine2.project.map("fixture").tile_layer("FloorCollision")
    # CLICK is (26, 26); at 4px sub-cells that is (6, 6). Before the fix this
    # wrote (1, 1) -- 20px away on a 4x4 map, and 1,200px away on a 100x100.
    expect("...so the mask lands under the cursor here too",
           sorted(set(painted_cells(companion)) - was),
           [(int(CLICK[0]) // FINE_CELL, int(CLICK[1]) // FINE_CELL)])
    expect("...in one transaction", len(fine2.history()) - before, 1)
    window.undo()
    application.processEvents()
    window.close()

    # ==================================================================
    print()
    print("A MIXED STACK: a 1x layer read at 4x stays where it was painted")
    # ==================================================================
    # Gap 4. `collision_stack` builds one `CollisionLayer` per companion and
    # the resolved view reads them all at the FINEST resolution in the map.
    # Without a scale, a 1x companion asked for sub-cell (8, 0) answers with
    # its own cell (8, 0) -- which does not exist -- and its wall on map cell
    # (2, 0) surfaces at sub-cell (2, 0) instead, a different square of the
    # map. Not a lost layer: a MOVED one, which still looks like collision.
    ROOF_CELL = (2, 0)
    _ws, mixed_path, mixed = open_workspace(
        fine_fixture(roof={ROOF_CELL: BLOCK_UP}))
    window = collision_canvas(mixed, layer="Floor")
    canvas = window.canvas
    expect("the stack has both layers, topmost first",
           [layer.name for layer in canvas.collision_stack()],
           ["Roof", "Floor"])
    expect("and the map's finest declared resolution is the 4x one",
           canvas.stack_subcell(), FINE_SUB)
    click_px(application, canvas, *CLICK)               # Floor sub-cell (6, 6)

    canvas.set_all_layers(True)
    application.processEvents()
    overlay = canvas.overlay
    expect("the resolved view is drawn at the field's resolution",
           (overlay.width, overlay.height, overlay.tile_width),
           (FINE_SIDE, FINE_SIDE, FINE_CELL))
    # Map cell (2, 0) owns sub-cells x 8..11, y 0..3 -- all sixteen of them.
    expect("THE 1x WALL COVERS ITS WHOLE MAP TILE",
           [overlay.mask_at(x, y) for x, y in
            ((8, 0), (11, 0), (8, 3), (11, 3))],
           [BLOCK_UP] * 4)
    expect("...and stops at that tile's edge",
           (overlay.mask_at(7, 0), overlay.mask_at(12, 0)),
           (NO_DATA, NO_DATA))
    expect("...and is NOT at sub-cell (2, 0), where an unscaled read puts it",
           overlay.mask_at(*ROOF_CELL), NO_DATA)
    expect("the 4x layer keeps its own sub-cell under the same resolve",
           overlay.mask_at(6, 6), BLOCK_ALL)

    # Painting the 1x layer while the 4x view is up: one click changes one
    # cell of the FILE and sixteen cells of the READOUT, and writing only
    # the first of them leaves fifteen showing the answer from before.
    canvas.set_active_layer("Roof")
    application.processEvents()
    expect("the brush follows the layer being painted, not the readout",
           (canvas.paint_subcell, canvas.paint_width), (1, TILE))
    touched.clear()
    bakes.clear()
    click_px(application, canvas, *CLICK)               # map cell (1, 1)
    expect("one map cell of the 1x companion took the mask",
           mixed.project.map("fixture").tile_layer(
               "RoofCollision").get_tile(1, 1),
           COLLISION_FIRST_GID + BLOCK_ALL)
    expect("...and all sixteen readout cells it covers were repainted",
           len(touched), FINE_SUB * FINE_SUB)
    expect("...incrementally, without re-resolving the whole field",
           bakes, [])
    expect("...so the readout shows the wall across the whole tile",
           [canvas.overlay.mask_at(x, y) for x, y in
            ((4, 4), (7, 7))], [BLOCK_ALL, BLOCK_ALL])
    window.close()

    # ==================================================================
    print()
    print("THE GUARD: a stroke it cannot place is refused, not misplaced")
    # ==================================================================
    # Unreachable while `paint_unit` is the only thing that resolves a cell
    # -- which is the point of closing gap 2, and is why the guard reads the
    # declaration a SECOND time straight off the document instead of asking
    # the funnel whether it agrees with itself. Reached here by breaking the
    # funnel the way the next change will break it: reporting whole tiles on
    # a map whose companion stores quarter-tiles.
    window = collision_canvas(fine, layer="Floor")
    canvas = window.canvas
    said = []
    canvas.status.connect(said.append)
    expect("correctly wired, there is nothing to refuse",
           canvas.collision_stroke_refusal(), None)

    _real_paint_unit = MapCanvas.paint_unit
    MapCanvas.paint_unit = lambda self: PaintUnit(1, TILE, TILE,
                                                  layer="FloorCollision")
    try:
        BEFORE_GUARD = fine.project.map("fixture").to_bytes()
        expect("a broken paint unit is caught rather than believed",
               canvas.collision_stroke_refusal() is not None, True)
        said.clear()
        before = len(fine.history())
        drag(application, canvas, [(1, 1), (2, 2)])
        expect("the stroke writes nothing", len(fine.history()) - before, 0)
        expect("...and the document is byte-identical",
               fine.project.map("fixture").to_bytes() == BEFORE_GUARD, True)
        expect("...the refusal names the unit the click resolved to",
               among(f"{TILE}x{TILE}px cell (1 per tile)", said), True)
        expect("...and the resolution the file actually declares",
               among(f"{SUBCELL}={FINE_SUB}", said), True)
        expect("...and how far the mask would have gone",
               among("from the cursor", said), True)
        expect("...as a status line, with no dialog anywhere near it",
               modals, [])
        # An unreadable declaration is the other way in, and it must not
        # take the editor down on a mouse move: the unit degrades to 1x for
        # DRAWING and the stroke is refused for WRITING.
        expect("...and the picker is refused on the same terms, not silently "
               "reading the wrong cell",
               canvas.collision_stroke_refusal() is not None, True)
    finally:
        MapCanvas.paint_unit = _real_paint_unit
    # The permissive half, and it has to be a cell nothing has painted yet:
    # a stroke that changes no gid commits nothing, so re-clicking (6, 6)
    # would answer "refused" and "already correct" with the same zero.
    # Pixel 10 owns sub-cell 2 (8..11).
    UNPAINTED = (10.0, 10.0)
    expect("with the funnel restored the refusal is gone",
           canvas.collision_stroke_refusal(), None)
    expect("...and a fresh cell really is fresh",
           fine.project.map("fixture").tile_layer(
               "FloorCollision").get_tile(2, 2), 0)
    before = len(fine.history())
    click_px(application, canvas, *UNPAINTED)
    expect("...AND THE SAME GESTURE PAINTS", len(fine.history()) - before, 1)
    expect("...into the sub-cell under the cursor, as before",
           (fine.project.map("fixture").tile_layer(
               "FloorCollision").get_tile(2, 2),
            covers((2, 2), FINE_CELL, UNPAINTED)),
           (COLLISION_FIRST_GID + BLOCK_ALL, True))
    window.close()

    # ==================================================================
    print()
    print("a companion nobody can read refuses the stroke and says why")
    # ==================================================================
    # Law 7 from the other end. `companion_subcell` raises on a declaration
    # that is not a positive integer; the canvas may not turn that into a
    # plausible 1 and paint, and it may not raise on every mouse move
    # either. It draws at 1x and refuses to WRITE, naming the property.
    _ws, bad_path, bad = open_workspace(fine_fixture(declare="banana"))
    BAD_ORIGINAL = bad.project.map("fixture").to_bytes()
    window = collision_canvas(bad)
    canvas = window.canvas
    said = []
    canvas.status.connect(said.append)
    expect("the canvas still draws, at the only resolution it can trust",
           canvas.paint_width, TILE)
    expect("...and a mouse move over it does not raise",
           canvas.cell_at(*CLICK), (1, 1))
    before = len(bad.history())
    drag(application, canvas, [(1, 1), (2, 2)])
    expect("but the stroke is refused", len(bad.history()) - before, 0)
    expect("...the document untouched",
           bad.project.map("fixture").to_bytes() == BAD_ORIGINAL, True)
    expect("...and the message names the property and the value",
           (among(SUBCELL, said), among("banana", said)), (True, True))
    expect("...still with no dialog", modals, [])
    window.close()

finally:
    CollisionOverlay.bake = _real_bake
    CollisionOverlay.bake_resolved = _real_resolved
    CollisionOverlay.set_cell = _real_set_cell
    for _directory in workspaces:
        shutil.rmtree(_directory, ignore_errors=True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
