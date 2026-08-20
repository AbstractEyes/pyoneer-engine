"""Assert the collision stack is actually WIRED to the canvas.

`check_collision.py` and `check_collision_view.py` prove the model and the
pixmap in isolation. This file covers the seam neither can see: that a real
`MapCanvas` mounts the overlay, that the mode changes where a drag lands,
and that a collision stroke is one transaction with an exact inverse.

What it proves:

  1. CLICKING A COLLISION TILE PAINTS A MASK, and everything a first stroke
     needs -- the mask sheet on disk, the `collision` tileset declared, the
     gids in range -- is arranged inside that one transaction, with no
     dialog on any path.
  2. NO MODAL CAN REACH THE PAINT PATH, proved three ways rather than
     trusted: every `QMessageBox` entry point raises for the whole run
     (law 13), `MapCanvas` carries no `confirm` seam, and
     `editor/ui/canvas.py`'s import graph is walked with `ast` to assert
     `QMessageBox` is not imported at all.
  3. THE MASK LANDS WHERE THE AUTHOR CLICKED, on a `pyoneer_subcell="4"`
     map and on a 1x one. Driven and asserted in scene PIXELS: the painted
     sub-cell must CONTAIN the clicked pixel, because an assertion phrased
     in cells is phrased in the unit under test.
  4. THE OVERLAY'S CELLS ARE THE COMPANION'S CELLS, a 1x layer read into a
     4x field lands over its own map tile, and a stroke whose paint unit
     and companion disagree is refused rather than written elsewhere.
  5. THE COMPANION THE EDITOR CREATES FOR ITSELF takes the author's chosen
     resolution -- driven at 1x, 4x and 16x from a map with no companion at
     all, since `map.layer.set` cannot write `pyoneer_subcell` and no verb
     re-scales one afterwards.
  6. A TILE CARRIES ITS OWN MASK, from one pick in the palette.
     `MapCanvas.set_stamp` is the seam: in collision mode a tile pick is
     not a brush, it is the TARGET the current mask is written onto. Both
     halves of the mode gate, both halves of the readout (the resolved view
     moves, the single-layer view does not and says why), and the refusals
     -- an empty cell, a gid no tileset owns.

Against its OWN fixture map, never `data/maps/test.tmx` (law 4). The
fixture declares exactly what the feature needs: a `collision` tileset to
store masks in, an art layer with no companion (so the create-on-first-
stroke path runs), and one that already declares its companion (so the
layer stack has two members to resolve).

The window wiring -- toolbar buttons, the mask palette dock, the C
shortcut -- belongs to `main_window.py` and is deliberately NOT exercised
here. This drives the canvas through a minimal harness supplying the one
thing it asks of its window, `run(commands)`, so a failure here is a
failure in the canvas rather than in the toolbar.

Skips cleanly when PySide6 is not installed.
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

from editor.core.collision import (                                     # noqa: E402
    SUBCELL,
    NO_DATA,
    Blitmask,
    companion_subcell,
    field_subcell,
    gid_to_opinion,
)
from editor.core.layers import (                                        # noqa: E402
    BLOCK_ALL,
    BLOCK_UP,
    PASS_ALL,
    STAR,
    read_profile,
)
from editor.core.commands import Command                                # noqa: E402
from editor.core.paint import EditMode, Stamp, Tool                     # noqa: E402
from editor.core.scope import Scope                                     # noqa: E402
from editor.core.session import Session                                 # noqa: E402
from editor.ui import canvas as canvas_module                           # noqa: E402
from scripts.core.errors import PyoneerError                            # noqa: E402
from editor.ui.canvas import (                                          # noqa: E402
    COLLISION_IMAGE,
    COLLISION_TILESET,
    MapCanvas,
    PaintUnit,
    write_mask_sheet,
)
from editor.ui.collision_view import (                                   # noqa: E402
    LEVEL_COMPANION,
    LEVEL_NAMES,
    LEVEL_NONE,
    LEVEL_TILESET,
    MASK_DOMAIN,
    CollisionOverlay,
)
from scripts.core.collision_runtime import field_from_map                # noqa: E402

failures: list[str] = []


# --------------------------------------------------------------------------
# No modal may reach anything below
# --------------------------------------------------------------------------
# Armed for the WHOLE run, not around one block: a stub that RAISES turns a
# dialog into a red line naming the caller instead of a hang (law 13), and
# it covers entry points nobody thought to leave a seam for.

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

    Three shapes from one template, all three states a real map reaches.
    SEVENTEEN is a map somebody already painted collision on. NONE is what
    every map starts as, and is what the provisioning path exists for.
    FEWER THAN SEVENTEEN declares the tileset but cannot hold every mask,
    so a stroke would encode gids the declared sheet does not own.

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
# A SECOND map rather than a parameter on the first, so everything above
# stays about a 1x map. Small enough that every cell can be named: 4x4 tiles
# at 16px, so 64x64 scene pixels, and a `pyoneer_subcell="4"` companion
# divides that into 16x16 cells of 4px each.

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
# The BAKED-IN fixture: masks that live on the tile
# --------------------------------------------------------------------------
# A THIRD map, so everything above stays about maps whose only collision is
# painted. This one gives the ART tileset a `.blitmask` -- level ONE -- so
# stamping a tile is the whole of authoring a wall, and then paints over two
# of those tiles to prove the levels compose in the readout the way they
# compose in the field.
#
# It is a real workspace with a real sidecar on disk, because
# `tileset_defaults` resolves the reference relative to the .tmx and a
# fixture built from bytes cannot reach that path at all -- the engine says
# so in as many words and raises rather than guessing.

BAKED_W, BAKED_H = 6, 5
#: Local ids of the ART tileset, and therefore gids, since its firstgid is 1.
PLAIN_GID = 1                     # a tile the mask says nothing about
WALL_GID = 2                      # a tile whose own mask is BLOCK_ALL
LEDGE_GID = 3                     # a tile whose own mask is BLOCK_UP only
#: One row of the 16-column sheet is masked and the rest is not, which is a
#: perfectly ordinary thing to author -- `TilesetDefaults` answers NO_DATA
#: past the end of a mask SHORTER than its sheet, and only a mask TALLER
#: than the sheet raises.
BAKED_MASK_ROW = ["." for _ in range(16)]
BAKED_MASK_ROW[WALL_GID - 1] = "f"                            # BLOCK_ALL
BAKED_MASK_ROW[LEDGE_GID - 1] = "8"                           # BLOCK_UP

#: Where each level is exercised. Named rather than inlined because every
#: assertion below is about one of these five cells.
TILE_WALL = (1, 1)          # blocked by the TILE alone; nothing painted here
PAINTED_OPEN = (2, 1)       # a wall tile with PASS_ALL painted over it
STARRED = (3, 1)            # a wall tile with a STAR painted over it
TILE_LEDGE = (4, 1)         # a one-direction tile default
ROOF_WALL = (1, 3)          # a wall tile on a layer that has NO companion


def blitmask_text(name: str = "Art") -> str:
    """The sidecar, written the way `Blitmask.render` writes one.

    Spelled out rather than produced by `Blitmask.render`: this file is the
    FORMAT the engine reads, and a fixture generated by the same code that
    parses it would agree with itself whatever either one said.
    """
    head = ["blitmask 1", "size 16 1"]
    if name:
        head.append("name " + name)
    return "\n".join(head + ["".join(BAKED_MASK_ROW)]) + "\n"


_BAKED_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" compressionlevel="-1" width="{w}" height="{h}" \
tilewidth="16" tileheight="16" infinite="0" nextlayerid="5" nextobjectid="1">
 <tileset firstgid="1" name="Art" tilewidth="16" tileheight="16" \
tilecount="256" columns="16">
{declares}\
  <image source="art.png" width="256" height="256"/>
 </tileset>
{collision}\
 <layer id="1" name="Floor" width="{w}" height="{h}">
  <properties>
   <property name="pyoneer_passability" value="FloorCollision"/>
  </properties>
  <data encoding="csv">
{floor}
</data>
 </layer>
 <layer id="2" name="FloorCollision" width="{w}" height="{h}">
  <properties>
   <property name="pyoneer_renders" type="bool" value="false"/>
  </properties>
  <data encoding="csv">
{companion}
</data>
 </layer>
 <layer id="3" name="Roof" width="{w}" height="{h}">
  <data encoding="csv">
{roof}
</data>
 </layer>
</map>
"""

_DECLARES = ('  <properties>\n'
             '   <property name="pyoneer_collision" value="{reference}"/>\n'
             '  </properties>\n')


def baked_csv(cells: dict) -> str:
    rows = []
    for y in range(BAKED_H):
        rows.append(",".join(str(cells.get((x, y), 0))
                             for x in range(BAKED_W)))
    return ",\n".join(rows)


def baked_fixture(*, reference: str | None = "art.blitmask",
                  with_collision_tileset: bool = True) -> str:
    """The map. `reference` None declares no masks at all, which is every
    map in this repository and has to keep costing nothing.

    `with_collision_tileset` False removes the `collision` tileset, which is
    the shape a map takes when the author has painted NOTHING and the tiles
    carry everything: there is no firstgid, no mask can be encoded, and level
    one is the only level there is.
    """
    collision = _COLLISION_TILESET.format(
        first=COLLISION_FIRST_GID, count=len(MASK_DOMAIN),
        image="collision.png",
        width=16 * len(MASK_DOMAIN)) if with_collision_tileset else ""
    declares = "" if reference is None else _DECLARES.format(reference=reference)
    floor = {TILE_WALL: WALL_GID, PAINTED_OPEN: WALL_GID,
             STARRED: WALL_GID, TILE_LEDGE: LEDGE_GID,
             (0, 0): PLAIN_GID, (5, 4): PLAIN_GID}
    companion = {}
    if with_collision_tileset:
        companion = {PAINTED_OPEN: COLLISION_FIRST_GID + PASS_ALL,
                     STARRED: COLLISION_FIRST_GID + STAR}
    return _BAKED_TEMPLATE.format(
        w=BAKED_W, h=BAKED_H, declares=declares, collision=collision,
        floor=baked_csv(floor), companion=baked_csv(companion),
        roof=baked_csv({ROOF_WALL: WALL_GID}))


def open_baked(*, reference: str | None = "art.blitmask",
               with_collision_tileset: bool = True,
               sidecar: str | None = "art.blitmask",
               mask_name: str = "Art"):
    """A workspace holding the map AND its sidecar, side by side.

    `sidecar` None writes no file, which is how the "declared and not there"
    refusal is reached -- the one `tileset_defaults` raises for, and the one
    an author hits by renaming a `.blitmask` in a file browser.
    """
    workspace, path, session = open_workspace(
        baked_fixture(reference=reference,
                      with_collision_tileset=with_collision_tileset))
    if sidecar is not None:
        with open(os.path.join(os.path.dirname(path), sidecar), "w",
                  encoding="utf-8", newline="") as handle:
            handle.write(blitmask_text(mask_name))
    return workspace, path, session


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
    asserting where a cell IS: clicking 'cell (6, 6)' and finding a mask in
    cell (6, 6) passes whatever `paint_width` says, because both halves went
    through the same number. A pixel is the only coordinate the canvas does
    not get to choose.
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

    NOT `lines[-1]`: a refused press starts no stroke, so the mouse moves
    after it fall through to the collision-mode cell readout and that ends up
    last. What is under test is that the editor SAID why, in the channel the
    author is looking at, rather than doing nothing.
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
                     mask: int = BLOCK_ALL, subcell: int = 1):
    window = Harness(session, "fixture")
    window.show()
    application.processEvents()
    # BEFORE the first rebuild, because this is what `paint_unit` answers for
    # a companion that does not exist yet -- so it sizes the grid, the ghost
    # and the stroke's bounds, not just the layer the commit creates. 1 is
    # the canvas's own default and every block above it depends on that.
    window.canvas.collision_subcell = subcell
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
    # Nothing may be provisioned for a gesture that is going to be refused
    # anyway, so the cheap refusals have to run BEFORE the tileset gate.
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
    # Undo must not delete a sheet the author may have painted since, which
    # create-only-if-absent answers. This is the half of that invariant a
    # permissive check skips.
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
    # `sufficient` has to guard the ALREADY-DECLARED path too, not just the
    # ADD path: a map declaring a five-tile `collision` tileset would encode
    # BLOCK_ALL as firstgid+15 against a range stopping at firstgid+4, and
    # say nothing.
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
    # The end-to-end claim: a declared <tileset> whose PNG is not on disk
    # raises FileNotFoundError inside pytmx's image loader, so an editor
    # that declares without provisioning drives the project into a state the
    # engine cannot open. Both halves, because only the second says the file
    # is load-bearing: WITH the provisioned sheet the map loads, WITHOUT it
    # the same map raises.
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
    # Driven in scene PIXELS and asserted in pixels throughout: the failure
    # this section covers is the canvas and the file disagreeing about what a
    # cell IS, and an assertion phrased in cells is phrased in the very unit
    # under test.
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
    # The wrong answer, named. Cell (1, 1) is where a canvas addressing whole
    # tiles puts this, and it owns pixels 4..7 -- 20px up and 20px left of
    # the cursor.
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
    # those, so a stack member has to read through the engine's
    # `document_gid_reader` or All layers dies mid-rebuild on a map shape the
    # runtime supports on purpose.
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

    # The DATA layer selected, not the art layer. A companion is a selectable
    # row in the Layers panel, so an author reaches it with one click, and the
    # block above only proves a tile-mode cell is a tile for the ART layer.
    # A FRESH fixture, because the blocks above have painted this one and an
    # absolute assertion would measure their residue rather than this stroke.
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
    # `collision_stack` builds one `CollisionLayer` per companion and
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
    # -- which is why the guard reads the declaration a SECOND time straight
    # off the document instead of asking the funnel whether it agrees with
    # itself. Reached here by breaking the funnel the way a future change
    # would: reporting whole tiles on a map storing quarter-tiles.
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

    # ----------------------------------------------------------------
    print()
    print("...AND THE READOUT SAYS SO TOO, rather than drawing a quiet 1x")
    # ----------------------------------------------------------------
    # The other half. `stack_subcell` degrades to 1 on a map `field_subcell`
    # refuses -- correctly, because an editor that cannot draw a broken map
    # cannot fix one -- so without this the All layers view would draw a
    # plausible 1x readout over a map that RAISES at load and say nothing,
    # leaving the author to find out only by attempting a stroke.
    expect("the resolved view still degrades rather than raising",
           canvas.stack_subcell(), 1)
    expect("...and it does not raise on the mouse-move path either",
           canvas.overlay_cell_at(26.0, 26.0), (1, 1))
    expect("BUT THE REASON IS CARRIED, not swallowed",
           canvas.stack_refusal() is not None, True)
    expect("...naming the property and the value, as the stroke path does",
           (SUBCELL in (canvas.stack_refusal() or ""),
            "banana" in (canvas.stack_refusal() or "")), (True, True))
    said.clear()
    canvas.set_all_layers(True)
    application.processEvents()
    expect("switching All layers ON says it, in the status bar",
           (among("cannot be trusted", said), among("banana", said)),
           (True, True))
    said.clear()
    mouse(canvas, QEvent.Type.MouseMove, (1, 1), Qt.NoButton, Qt.NoButton)
    expect("...and the cell readout keeps saying it, so nothing stomps it",
           (among("cannot be trusted", said), among("banana", said)),
           (True, True))
    expect("...instead of describing a cell it cannot answer for",
           any("passable" in line or "blocks" in line for line in said), False)
    expect("...still with no dialog anywhere", modals, [])
    window.close()

    # The permissive half. A map whose declarations DO read has nothing to
    # say, and a readout that cried on every map would be a readout the
    # author stops reading -- which is the same defect as silence, later.
    _ws, _sound_path, sound = open_workspace(fine_fixture())
    window = collision_canvas(sound)
    canvas = window.canvas
    said = []
    canvas.status.connect(said.append)
    expect("a map that reads has no refusal to carry",
           (canvas.stack_refusal(), canvas.stack_subcell()), (None, FINE_SUB))
    canvas.set_all_layers(True)
    application.processEvents()
    mouse(canvas, QEvent.Type.MouseMove, (1, 1), Qt.NoButton, Qt.NoButton)
    expect("...and All layers describes the cell instead of complaining",
           among("cannot be trusted", said), False)
    window.close()

    # ==================================================================
    print()
    print("THE COMPANION THE EDITOR CREATES FOR ITSELF, at the resolution "
          "the author asked for")
    # ==================================================================
    # THE COMPANION THE EDITOR CREATES FOR ITSELF. Every 4x assertion above
    # starts from `fine_fixture()`, whose companion is hand-written with
    # `pyoneer_subcell="4"` already on it. This section drives the path a real
    # author takes FIRST: a map with no companion at all, one stroke, and
    # whatever resolution the editor decides to create. It is the only chance
    # to get that resolution right -- `map.layer.set` deliberately cannot
    # write `pyoneer_subcell` and no verb re-scales a companion.
    #
    # Driven in scene PIXELS, because the created layer's cells and the
    # clicked cell go through one funnel and an assertion phrased in cells
    # would be satisfied by that funnel agreeing with itself.
    FRESH_CLICK = (26.0, 26.0)
    for wanted in (1, FINE_SUB, 16):
        print(f"  -- the author asks for {wanted} sub-cells per tile")
        _ws, _fresh_path, fresh = open_workspace(FIXTURE)
        FRESH_ORIGINAL = fresh.project.map("fixture").to_bytes()
        window = collision_canvas(fresh, subcell=wanted)
        canvas = window.canvas
        document = fresh.project.map("fixture")
        expect(f"{wanted}: the map really has no companion to read from",
               "FloorCollision" in document.tile_layer_names(), False)
        expect(f"{wanted}: so the CLICK is addressed at the resolution about "
               f"to be created",
               (canvas.paint_subcell, canvas.paint_width),
               (wanted, TILE // wanted))

        before = len(fresh.history())
        click_px(application, canvas, *FRESH_CLICK)
        expect(f"{wanted}: one click, one transaction",
               len(fresh.history()) - before, 1)
        added = [c for c in fresh.history()[-1].commands
                 if c.verb == "map.layer.add"]
        expect(f"{wanted}: the stroke created the companion",
               [c.args.get("name") for c in added], ["FloorCollision"])
        # OMITTED at 1, not passed as 1. The verb accepts 1 and writes
        # `pyoneer_subcell="1"` for it, and no companion this editor has ever
        # created carries that property: a default that rewrites what
        # existing maps get is not a default.
        expect(f"{wanted}: and asked for the factor, or for nothing at 1x",
               added[0].args.get("subcell"), None if wanted == 1 else wanted)

        document = fresh.project.map("fixture")
        made = document.tile_layer("FloorCollision")
        expect(f"{wanted}: it is {wanted}x the map on each axis",
               (made.width, made.height),
               (WIDTH * wanted, HEIGHT * wanted))
        expect(f"{wanted}: and declares the factor, or nothing at all at 1x",
               made.properties.get(SUBCELL), None if wanted == 1 else wanted)
        # The ENGINE's own reader, not the editor's: a companion the editor
        # can write and the engine refuses is the unloadable map this whole
        # file exists to stop producing.
        expect(f"{wanted}: THE ENGINE READS IT AT THE SAME RESOLUTION",
               (companion_subcell(document, "FloorCollision"),
                field_subcell(document)), (wanted, wanted))

        marks = painted_cells(made)
        expect(f"{wanted}: exactly one cell took the mask", len(marks), 1)
        expect(f"{wanted}: AND THAT CELL CONTAINS THE CLICKED PIXEL",
               bool(marks) and covers(marks[0], TILE // wanted, FRESH_CLICK),
               True)
        window.undo()
        application.processEvents()
        expect(f"{wanted}: and one undo is byte-identical",
               fresh.project.map("fixture").to_bytes() == FRESH_ORIGINAL, True)
        window.close()

    # ------------------------------------------------------------------
    print()
    print("...and it moves the COLLISION grid only, never the tile grid")
    # ------------------------------------------------------------------
    # The other half of the same preference, and the half a permissive check
    # skips: proved to subdivide, never proved to leave art alone. A
    # companion's resolution is none of an art stroke's business -- that is
    # `mode.subdivides`' whole job -- and a preference that quartered the
    # grid the author paints floor on would make the editor unusable for
    # everything except collision.
    _ws, _art_path, art_map = open_workspace(FIXTURE)
    window = collision_canvas(art_map, subcell=FINE_SUB)
    canvas = window.canvas
    expect("in collision mode the preference subdivides",
           (canvas.paint_subcell, canvas.paint_width), (FINE_SUB, FINE_CELL))
    canvas.set_mode(EditMode.TILES)
    application.processEvents()
    expect("...and in tile mode a cell is a whole tile, as it always was",
           (canvas.paint_subcell, canvas.paint_width), (1, TILE))
    canvas.stamp = Stamp.single(9)
    before = len(art_map.history())
    click_px(application, canvas, *FRESH_CLICK)
    expect("so an art stroke writes the TILE under the cursor",
           painted_cells(art_map.project.map("fixture").tile_layer("Floor")),
           [(1, 1)])
    expect("...as its own transaction, creating no companion",
           (len(art_map.history()) - before,
            "FloorCollision" in art_map.project.map(
                "fixture").tile_layer_names()), (1, False))
    window.close()

    # ------------------------------------------------------------------
    print()
    print("...and it does NOT re-scale a companion that already exists")
    # ------------------------------------------------------------------
    # The preference decides what is CREATED and nothing else. A companion
    # carries its own declaration, there is no verb to re-scale one, and a
    # canvas that let a global preference override the file would move every
    # mask on an existing map by changing a dropdown.
    _ws, _keep_path, keep = open_workspace(fine_fixture())
    window = collision_canvas(keep, subcell=1)          # asks for 1x...
    canvas = window.canvas
    expect("a 4x companion is still read at 4x, whatever the preference says",
           (canvas.paint_subcell, canvas.paint_width), (FINE_SUB, FINE_CELL))
    before = len(keep.history())
    click_px(application, canvas, *FRESH_CLICK)
    expect("...and the stroke lands in the file's own sub-cell",
           painted_cells(keep.project.map("fixture").tile_layer(
               "FloorCollision")), [(6, 6)])
    expect("...adding no layer, because there is nothing to add",
           [c.verb for c in keep.history()[-1].commands],
           ["map.tile.set_many"])
    expect("...as one transaction", len(keep.history()) - before, 1)
    window.close()

    _ws, _plain_path, plain1x = open_workspace(fine_fixture(declare=None,
                                                            side=FINE_TILES))
    window = collision_canvas(plain1x, subcell=FINE_SUB)  # ...and 4x
    canvas = window.canvas
    expect("a 1x companion stays 1x too -- an absent property is a "
           "declaration",
           (canvas.paint_subcell, canvas.paint_width), (1, TILE))
    click_px(application, canvas, *FRESH_CLICK)
    expect("...so the mask lands in the whole tile, as it always did",
           painted_cells(plain1x.project.map("fixture").tile_layer(
               "FloorCollision")), [(1, 1)])
    expect("...and no map.layer.add went with it",
           [c.verb for c in plain1x.history()[-1].commands],
           ["map.tile.set_many"])
    window.close()

    # ------------------------------------------------------------------
    print()
    print("...and a factor THIS MAP cannot hold is refused, not rounded")
    # ------------------------------------------------------------------
    # Law 7 on the create path. The canvas cannot ask `companion_subcell`
    # whether a factor is legal -- that reader needs a layer, and there is no
    # layer yet -- so it spells the same rule and refuses. A mirror rots, so
    # BOTH sides are asserted on the same map: the editor refuses at press,
    # and `map.layer.add` carrying that very factor raises at apply.
    ODD_TILE = 24                       # 16 does not divide it; 24 % 16 = 8
    _ws, _odd_path, odd = open_workspace(FIXTURE.replace(
        'tilewidth="16" tileheight="16" infinite',
        f'tilewidth="{ODD_TILE}" tileheight="{ODD_TILE}" infinite'))
    ODD_ORIGINAL = odd.project.map("fixture").to_bytes()
    window = collision_canvas(odd, subcell=16)
    canvas = window.canvas
    said = []
    canvas.status.connect(said.append)
    expect("the map's tiles really are indivisible by the asked factor",
           (odd.project.map("fixture").tile_width % 16 != 0), True)
    expect("the canvas draws at the only resolution it can trust",
           (canvas.paint_subcell, canvas.paint_width), (1, ODD_TILE))
    expect("...and refuses to write rather than rounding to a cell that "
           "cannot exist", canvas.collision_stroke_refusal() is not None, True)
    before = len(odd.history())
    drag(application, canvas, [(1, 1), (2, 1)])
    expect("the stroke runs no command", len(odd.history()) - before, 0)
    expect("...leaves the document byte-identical",
           odd.project.map("fixture").to_bytes() == ODD_ORIGINAL, True)
    expect("...names the factor and the tile size it will not divide",
           (among("16", said), among(f"{ODD_TILE}x{ODD_TILE}px", said)),
           (True, True))
    expect("...and says it without a dialog", modals, [])
    # THE MIRROR, AUDITED. If `companion_subcell` ever stops refusing this,
    # the refusal above becomes the editor inventing a rule of its own and
    # this line is what goes red.
    engine_refused = "accepted"
    try:
        odd.run(Command("map.layer.add", Scope.of(("map", "fixture")),
                        {"name": "Probe", "kind": "tile", "subcell": 16}))
    except PyoneerError as exc:                                 # noqa: BLE001
        engine_refused = SUBCELL in str(exc)
    expect("...and the ENGINE refuses the same factor on the same map",
           engine_refused, True)
    expect("...leaving the document byte-identical after that too",
           odd.project.map("fixture").to_bytes() == ODD_ORIGINAL, True)
    window.close()

    # ==================================================================
    print()
    print("BAKED-IN MASKS: the overlay shows what the GAME walks")
    # ==================================================================
    # The engine stacks a tileset's own `.blitmask` under every companion, so
    # `collision_stack` has to as well. A builder using `companion=` alone
    # reads ONE level while the player obeys three: a wall nobody painted
    # stops him, the readout draws nothing there, and the only way to find
    # out is to walk into it.
    _ws, baked_path, baked = open_baked()
    BAKED_ORIGINAL = baked.project.map("fixture").to_bytes()
    window = collision_canvas(baked, layer="Floor")
    canvas = window.canvas
    said = []
    canvas.status.connect(said.append)

    stack = canvas.collision_stack()
    expect("the stack is the ENGINE's, topmost first",
           [layer.name for layer in stack], ["Roof", "Floor"])
    expect("...and every member now carries level ONE",
           [layer.defaults is not None for layer in stack], [True, True])
    # The membership half, and the one a check about levels alone would miss:
    # `Roof` declares no companion at all. A builder that only walks companions
    # leaves it out of the stack, so a wall stamped on it is invisible here and
    # solid in the game.
    expect("...INCLUDING A LAYER THAT DECLARES NO COMPANION",
           (canvas.companion_name("Roof") in
            baked.project.map("fixture").tile_layer_names(),
            "Roof" in [layer.name for layer in stack]),
           (False, True))
    expect("...while the companion layer itself is never a stack member",
           "FloorCollision" in [layer.name for layer in stack], False)

    canvas.set_all_layers(True)
    application.processEvents()
    overlay = canvas.overlay
    expect("A CELL BLOCKED ONLY BY ITS TILE IS IN THE OVERLAY",
           (overlay.mask_at(*TILE_WALL), overlay.level_at(*TILE_WALL)),
           (BLOCK_ALL, LEVEL_TILESET))
    expect("...and a one-direction tile default keeps its one direction",
           (overlay.mask_at(*TILE_LEDGE), overlay.level_at(*TILE_LEDGE)),
           (BLOCK_UP, LEVEL_TILESET))
    expect("A PAINTED CELL OVERRIDES THE DEFAULT, and the overlay shows the "
           "OVERRIDE rather than the default",
           (overlay.mask_at(*PAINTED_OPEN), overlay.level_at(*PAINTED_OPEN)),
           (PASS_ALL, LEVEL_COMPANION))
    # Not the union, and not the default: the whole point of level two is
    # "not THIS one" -- a door left open in a wall of the same tile.
    expect("...which is a real reversal, not a coincidence: the same tile "
           "one cell along is still solid",
           (overlay.mask_at(*TILE_WALL), overlay.mask_at(*PAINTED_OPEN)),
           (BLOCK_ALL, PASS_ALL))
    expect("a STAR painted over a default suppresses it and asks below, "
           "where nothing answers",
           (overlay.mask_at(*STARRED), overlay.owner_at(*STARRED)),
           (NO_DATA, -1))
    expect("and the companion-less layer's wall is credited to IT",
           (overlay.mask_at(*ROOF_WALL), overlay.owner_at(*ROOF_WALL),
            overlay.level_at(*ROOF_WALL)),
           (BLOCK_ALL, 0, LEVEL_TILESET))
    expect("the author can read WHICH LEVEL blocked a cell without opening "
           "a file",
           (LEVEL_NAMES[LEVEL_TILESET] in overlay.describe(*TILE_WALL),
            LEVEL_NAMES[LEVEL_COMPANION] in overlay.describe(*PAINTED_OPEN)),
           (True, True))
    expect("...and the two readouts are not the same sentence",
           overlay.describe(*TILE_WALL) == overlay.describe(*PAINTED_OPEN),
           False)

    # ...AND IT REACHES HIM. `describe` returning the right string proves
    # nothing about whether anybody ever sees it; the cell readout under the
    # cursor is the channel, and it is the one thing nothing else stomps.
    said.clear()
    mouse(canvas, QEvent.Type.MouseMove, TILE_WALL, Qt.NoButton, Qt.NoButton)
    expect("moving over a tile-default cell SAYS so in the status bar",
           among(LEVEL_NAMES[LEVEL_TILESET], said), True)
    said.clear()
    mouse(canvas, QEvent.Type.MouseMove, PAINTED_OPEN, Qt.NoButton,
          Qt.NoButton)
    expect("...and moving over a painted one says the other thing",
           (among(LEVEL_NAMES[LEVEL_COMPANION], said),
            among(LEVEL_NAMES[LEVEL_TILESET], said)), (True, False))

    # THE MEMO, PRICED. `stack_refusal` is consulted on every mouse move and
    # level one lives in a FILE, so a naive read would open and parse a
    # `.blitmask` per pixel of travel. It is cached against the same key the
    # overlay's own staleness uses -- and a cache is only safe while it is
    # invalidated, which is what the "put the file back" assertions at the
    # bottom of this file pin from the other side.
    loads = []
    _real_load = Blitmask.load

    def _counted_load(path):
        loads.append(path)
        return _real_load(path)

    Blitmask.load = staticmethod(_counted_load)
    try:
        for _cell in ((0, 0), (1, 1), (2, 1), (3, 1), (4, 1), (5, 4),
                      (1, 3), (0, 4)):
            mouse(canvas, QEvent.Type.MouseMove, _cell, Qt.NoButton,
                  Qt.NoButton)
        expect("eight mouse moves open the sidecar zero times", loads, [])
        canvas.rebuild()
        application.processEvents()
        expect("...and a rebuild re-reads it exactly once, which is what "
               "lets a file fixed on disk be noticed at all", len(loads), 1)
    finally:
        Blitmask.load = _real_load

    # ----------------------------------------------------------------
    print()
    print("...AND IT AGREES WITH field_from_map CELL FOR CELL")
    # ----------------------------------------------------------------
    # THE WHOLE-MAP AGREEMENT. Everything above says the overlay shows the
    # right thing on cells somebody chose; this says it
    # shows the same thing as the engine EVERYWHERE, including the cells
    # nobody thought about. The two now build their stack with one function
    # over one document, so agreement is structural -- and this is what goes
    # red the day somebody gives either side a second builder.
    #
    # The one honest translation: `field_from_map` bakes `undecided` into
    # every cell nobody decided, because a field has to answer for every
    # cell, and the overlay draws NO_DATA there instead, because inking the
    # whole map as an assertion says nothing. So a decided cell must MATCH
    # and an undecided one must be exactly the field's own `undecided`.
    # Both halves, or the mapping could hide a real disagreement.

    def disagreements(canvas, document, *, undecided=PASS_ALL):
        """Every cell where the READOUT and the baked FIELD differ."""
        field = field_from_map(document, undecided=undecided)
        overlay = canvas.overlay
        out = []
        for y in range(field.height):
            for x in range(field.width):
                drawn = overlay.mask_at(x, y)
                walked = field.mask_at(x, y)
                wanted = undecided if drawn == NO_DATA else drawn
                if wanted != walked:
                    out.append((x, y, drawn, walked))
        return out, field

    document = baked.project.map("fixture")
    differ, field = disagreements(canvas, document)
    expect("THE OVERLAY AND THE FIELD AGREE ON EVERY CELL", differ, [])
    expect("...over a field the fixture actually exercises, not an empty one",
           (field.width, field.height,
            sum(1 for y in range(field.height) for x in range(field.width)
                if field.mask_at(x, y)) >= 3),
           (BAKED_W, BAKED_H, True))
    # Vacuity guard. A readout that said NO_DATA everywhere would satisfy
    # "decided cells match" trivially, and an all-open field would satisfy
    # the other half. Neither is this map.
    drawn_masks = {overlay.mask_at(x, y)
                   for y in range(BAKED_H) for x in range(BAKED_W)}
    expect("...and the readout really is drawing more than one answer",
           (len(drawn_masks) >= 3, NO_DATA in drawn_masks), (True, True))
    expect("...with BOTH levels represented, which is what makes the "
           "agreement about the stack rather than about one level",
           sorted({overlay.level_at(x, y)
                   for y in range(BAKED_H) for x in range(BAKED_W)}),
           [LEVEL_NONE, LEVEL_TILESET, LEVEL_COMPANION])

    # ----------------------------------------------------------------
    print()
    print("...and it keeps agreeing after a stroke, not only after a bake")
    # ----------------------------------------------------------------
    # `__sync_overlay` repaints the cells a stroke touched instead of
    # re-baking, which is the whole reason the overlay is held across
    # rebuilds. A per-cell path that resolved differently from the bake would
    # show up only as a readout that drifts as you paint.
    bakes.clear()
    canvas.set_mask(BLOCK_UP)
    before = len(baked.history())
    drag(application, canvas, [TILE_WALL])
    expect("the stroke is one transaction", len(baked.history()) - before, 1)
    expect("...and repainted the cell rather than re-baking the field",
           bakes, [])
    expect("...the readout now shows the paint, credited to the paint",
           (canvas.overlay.mask_at(*TILE_WALL),
            canvas.overlay.level_at(*TILE_WALL)),
           (BLOCK_UP, LEVEL_COMPANION))
    differ, _field = disagreements(canvas, baked.project.map("fixture"))
    expect("...AND THE TWO STILL AGREE, cell for cell", differ, [])
    window.undo()
    application.processEvents()
    expect("undo puts the tile's own mask back, exactly",
           (canvas.overlay.mask_at(*TILE_WALL),
            canvas.overlay.level_at(*TILE_WALL)),
           (BLOCK_ALL, LEVEL_TILESET))
    expect("...leaving the document byte-identical",
           baked.project.map("fixture").to_bytes() == BAKED_ORIGINAL, True)
    expect("...with no dialog anywhere in any of it", modals, [])
    window.close()

    # ----------------------------------------------------------------
    print()
    print("A MAP WITH NO .blitmask DRAWS EXACTLY AS IT DID BEFORE")
    # ----------------------------------------------------------------
    # The optional case, which is every map in this repository. A tileset
    # that declares nothing contributes nothing: no level one, no extra
    # members, and the same readout the companion-only builder drew. Missing
    # is not an error -- only DECLARED AND UNREADABLE is.
    _ws, _plain_path, plain = open_baked(reference=None, sidecar=None)
    window = collision_canvas(plain, layer="Floor")
    canvas = window.canvas
    stack = canvas.collision_stack()
    expect("no declaration means no level one at all",
           [layer.defaults for layer in stack], [None])
    expect("...and the stack is the companion-carrying layers and no others",
           [layer.name for layer in stack], ["Floor"])
    expect("...so a layer with no companion is out again, as it always was",
           "Roof" in [layer.name for layer in stack], False)
    canvas.set_all_layers(True)
    application.processEvents()
    expect("the tile that WOULD have been a wall is not one here",
           canvas.overlay.mask_at(*TILE_WALL), NO_DATA)
    expect("...while the painted cells are exactly as painted",
           (canvas.overlay.mask_at(*PAINTED_OPEN),
            canvas.overlay.mask_at(*STARRED)),
           (PASS_ALL, NO_DATA))
    expect("...and the readout has no level to credit",
           canvas.overlay.level_at(*PAINTED_OPEN), LEVEL_COMPANION)
    differ, _f = disagreements(canvas, plain.project.map("fixture"))
    expect("AND THE UNDECLARED MAP AGREES WITH THE ENGINE TOO", differ, [])
    expect("...which is the engine agreeing that it declares nothing",
           field_from_map(plain.project.map("fixture")) is not None, True)
    expect("...still with no dialog", modals, [])
    window.close()

    # ----------------------------------------------------------------
    print()
    print("A MAP WITH NO collision TILESET, whose tiles carry everything")
    # ----------------------------------------------------------------
    # NO `collision` TILESET AT ALL, which is not a reason to draw nothing.
    # A missing firstgid rules out level TWO -- no gid can encode a mask --
    # and says nothing about level one, which lives in a file beside the .tmx
    # and needs no gid. This is the map shape where the author paints NOTHING
    # and the tiles carry everything.
    _ws, _only_path, only = open_baked(with_collision_tileset=False)
    window = collision_canvas(only, layer="Floor")
    canvas = window.canvas
    expect("this map really has no collision tileset",
           canvas.collision_first_gid, None)
    # The companion LAYER is still in the file -- the fixture writes one --
    # and it is inert, which is the point: with no firstgid there is no gid
    # that means a mask, so `collision_layers` gives its member no level two
    # at all. Level one is the only level this map has.
    expect("...so its one stack member carries level ONE and nothing else",
           [(layer.name, layer.defaults is not None,
             layer.companion is not None)
            for layer in canvas.collision_stack()],
           [("Roof", True, False), ("Floor", True, False)])
    canvas.set_all_layers(True)
    application.processEvents()
    expect("THE TILE WALLS ARE STILL DRAWN",
           (canvas.overlay.mask_at(*TILE_WALL),
            canvas.overlay.mask_at(*TILE_LEDGE),
            canvas.overlay.mask_at(*ROOF_WALL)),
           (BLOCK_ALL, BLOCK_UP, BLOCK_ALL))
    expect("...every one of them credited to the tileset",
           {canvas.overlay.level_at(*cell)
            for cell in (TILE_WALL, TILE_LEDGE, ROOF_WALL)},
           {LEVEL_TILESET})
    differ, _f = disagreements(canvas, only.project.map("fixture"))
    expect("AND IT AGREES WITH THE ENGINE, which never had this gate",
           differ, [])
    window.close()

    # ----------------------------------------------------------------
    print()
    print("A DECLARED .blitmask THAT IS NOT THERE is said out loud")
    # ----------------------------------------------------------------
    # Law 7 with its exception stated: MISSING is not an error, DECLARED AND
    # UNREADABLE is. The engine raises on this map at load, so there is no
    # field and no player to agree with -- and a resolved view that drew a
    # plausible picture beside a warning would be the editor implying the map
    # is fine. It goes dark and says why, on the path the author is looking
    # at, without a dialog and without taking the editor with it.
    _ws, gone_path, gone = open_baked(reference="not_here.blitmask",
                                      sidecar=None)
    GONE_ORIGINAL = gone.project.map("fixture").to_bytes()
    window = collision_canvas(gone, layer="Floor")
    canvas = window.canvas
    said = []
    canvas.status.connect(said.append)
    expect("the canvas still opened the map", canvas.overlay is not None, True)
    expect("THE REASON IS CARRIED, naming the file that is not there",
           ("not_here.blitmask" in (canvas.stack_refusal() or ""),
            canvas.stack_refusal() is not None),
           (True, True))
    canvas.set_all_layers(True)
    application.processEvents()
    expect("...and the resolved view is EMPTY rather than plausible",
           {canvas.overlay.mask_at(x, y)
            for y in range(BAKED_H) for x in range(BAKED_W)}, {NO_DATA})
    expect("switching All layers on says it in the status bar",
           (among("cannot be trusted", said),
            among("not_here.blitmask", said)), (True, True))
    said.clear()
    mouse(canvas, QEvent.Type.MouseMove, TILE_WALL, Qt.NoButton, Qt.NoButton)
    expect("...and the cell readout keeps saying it",
           (among("cannot be trusted", said),
            among("not_here.blitmask", said)), (True, True))
    expect("...rather than describing a cell it cannot answer for",
           any("blocks" in line or "blocked" in line for line in said), False)
    expect("...with no dialog and no raise", modals, [])
    expect("...and the document untouched",
           gone.project.map("fixture").to_bytes() == GONE_ORIGINAL, True)
    # THE MIRROR, AUDITED. The editor refuses because the ENGINE refuses. If
    # `tileset_defaults` ever starts tolerating a missing sidecar, the
    # refusal above becomes the editor inventing a rule of its own, and this
    # is the line that goes red.
    engine_refused = "accepted"
    try:
        field_from_map(gone.project.map("fixture"))
    except PyoneerError as exc:                                 # noqa: BLE001
        engine_refused = "not_here.blitmask" in str(exc)
    expect("...and the ENGINE refuses the same map for the same reason",
           engine_refused, True)
    # The permissive half, on the same map made whole: a readout that cried
    # over every map is a readout the author stops reading.
    with open(os.path.join(os.path.dirname(gone_path), "not_here.blitmask"),
              "w", encoding="utf-8", newline="") as _handle:
        _handle.write(blitmask_text())
    canvas.rebuild()
    application.processEvents()
    expect("put the file back and the refusal goes with it",
           canvas.stack_refusal(), None)
    expect("...and the walls come back",
           canvas.overlay.mask_at(*TILE_WALL), BLOCK_ALL)
    window.close()

    # ----------------------------------------------------------------
    print()
    print("ONE PICK IN THE TILE PALETTE BAKES THAT TILE'S OWN MASK")
    # ----------------------------------------------------------------
    # THE CLICK THAT REACHES `map.tileset.mask.set`. The gesture is the
    # two-step the author already knows for CELLS, with the tileset palette
    # standing in for the map: pick the mask, then pick what it applies to.
    # `MapCanvas.set_stamp` is the whole seam, and it is what
    # `EditorWindow.__on_stamp` calls for a real click on the palette --
    # driven through the real window in `check_editor_ui.py`.
    #
    # AND THE HALF A COMMAND-LEVEL CHECK CANNOT SEE. A mask set writes the
    # SIDECAR and the tileset's declaration, so a check that stops at "the
    # command was emitted" passes over an editor in which the author sets a
    # mask and watches the readout not move. Every assertion below that
    # names the overlay is there for that: the click has to reach the
    # instrument, not just the file.
    _ws, bake_path, baking = open_baked(reference=None, sidecar=None)
    BAKE_ORIGINAL = baking.project.map("fixture").to_bytes()
    sidecar = os.path.join(os.path.dirname(bake_path), "Art.blitmask")
    window = collision_canvas(baking, layer="Floor", mask=BLOCK_ALL)
    canvas = window.canvas
    canvas.set_all_layers(True)
    application.processEvents()
    said: list[str] = []
    canvas.status.connect(said.append)

    expect("this map bakes nothing to begin with", canvas.tile_masks(), {})
    expect("...and has no sidecar on disk", os.path.isfile(sidecar), False)
    expect("...so the readout says nothing about the wall tile",
           canvas.overlay.mask_at(*TILE_WALL), NO_DATA)
    expect("...and the stack is the companion-carrying layer alone",
           [layer.name for layer in canvas.collision_stack()], ["Floor"])
    before = len(baking.history())

    # THE CLICK.
    canvas.set_stamp(Stamp.single(WALL_GID))
    application.processEvents()

    expect("ONE transaction for the whole gesture",
           len(baking.history()) - before, 1)
    # Hoisted, and compared as a WHOLE LIST rather than indexed: `[0]` on an
    # empty history raises IndexError, and a check that turns a red line into
    # a traceback hides every assertion after it.
    baked_commands = last_commands(baking)
    expect("...and it is the mask verb, once",
           [c.verb for c in baked_commands], ["map.tileset.mask.set"])
    expect("...addressing the ART tileset by name, by LOCAL tile id",
           [{key: c.args.get(key) for key in ("name", "tile", "mask")}
            for c in baked_commands],
           [{"name": "Art", "tile": WALL_GID - 1, "mask": BLOCK_ALL}])
    expect("THE MASK REACHED THE TILESET",
           canvas.tile_masks(), {WALL_GID: BLOCK_ALL})
    expect("...the sidecar was provisioned, nothing asked",
           os.path.isfile(sidecar), True)
    expect("...and the tmx declares it now",
           b"pyoneer_collision" in baking.project.map("fixture").to_bytes(),
           True)

    # AND THE OVERLAY MOVED. This is the half that a check asserting the
    # command was emitted cannot see, and the half the author meets first.
    expect("AND THE OVERLAY REDREW, at the cell holding that tile",
           (canvas.overlay.mask_at(*TILE_WALL),
            canvas.overlay.level_at(*TILE_WALL)),
           (BLOCK_ALL, LEVEL_TILESET))
    expect("...EVERYWHERE it is stamped, including a layer with no companion",
           canvas.overlay.mask_at(*ROOF_WALL), BLOCK_ALL)
    expect("...which is the stack gaining every tile layer, as the engine's "
           "does the moment a tileset carries masks",
           sorted(layer.name for layer in canvas.collision_stack()),
           ["Floor", "Roof"])
    expect("...while a cell PAINTED open over that tile still wins",
           (canvas.overlay.mask_at(*PAINTED_OPEN),
            canvas.overlay.level_at(*PAINTED_OPEN)),
           (PASS_ALL, LEVEL_COMPANION))
    # A STAR painted over the same tile SUPPRESSES what the tile says and
    # asks the layer below, where nothing answers -- the established
    # semantics, asserted here because a baked tile is exactly the thing the
    # star exists to be able to say "not here" about, and because it is the
    # one cell where "the tileset now blocks this tile" must NOT propagate.
    expect("...and a STAR painted over it still suppresses it",
           (canvas.overlay.mask_at(*STARRED),
            canvas.overlay.level_at(*STARRED)),
           (NO_DATA, LEVEL_NONE))
    expect("...and a tile nobody masked is untouched",
           canvas.overlay.mask_at(*TILE_LEDGE), NO_DATA)
    differ, _field = disagreements(canvas, baking.project.map("fixture"))
    expect("...AND THE READOUT AGREES WITH THE ENGINE, cell for cell",
           differ, [])
    expect("...with no dialog anywhere on the path", modals, [])
    expect("the author was told what changed, and how far it reaches",
           (among("blocked", said), among("everywhere", said)), (True, True))

    # UNDO. Both halves come back: the cell in the sidecar and the
    # declaration on the tileset, which is why `map.tileset.mask.restore`
    # exists as a separate verb at all.
    window.undo()
    application.processEvents()
    expect("UNDO TAKES THE MASK BACK OUT", canvas.tile_masks(), {})
    expect("...and the readout with it",
           (canvas.overlay.mask_at(*TILE_WALL),
            canvas.overlay.mask_at(*ROOF_WALL)), (NO_DATA, NO_DATA))
    expect("...and the tmx byte for byte, declaration included",
           baking.project.map("fixture").to_bytes() == BAKE_ORIGINAL, True)
    expect("...leaving the file it wrote on disk, which reads as no masks",
           os.path.isfile(sidecar), True)
    window.redo()
    application.processEvents()
    expect("...and redo puts both back",
           (canvas.tile_masks(), canvas.overlay.mask_at(*TILE_WALL)),
           ({WALL_GID: BLOCK_ALL}, BLOCK_ALL))

    # THE OTHER HALF OF THE MODE GATE. The same pick in TILES mode is a
    # BRUSH and must write nothing -- an editor that baked a mask every time
    # the author chose a tile to paint with would be unusable, and proving
    # only the permissive direction is the dominant failure shape here.
    canvas.set_mode(EditMode.TILES)
    application.processEvents()
    quiet = len(baking.history())
    canvas.set_stamp(Stamp.single(LEDGE_GID))
    application.processEvents()
    expect("a tile picked in TILES mode writes nothing at all",
           len(baking.history()), quiet)
    expect("...it is the brush, exactly as it always was",
           canvas.stamp.primary, LEDGE_GID)
    expect("...and the tileset still says only what collision mode said",
           canvas.tile_masks(), {WALL_GID: BLOCK_ALL})
    canvas.set_mode(EditMode.COLLISION)
    canvas.set_all_layers(True)
    application.processEvents()
    expect("...and the stamp survived the mode switch, so the next pick "
           "does not have to be made twice", canvas.stamp.primary, LEDGE_GID)

    # NOTHING SILENTLY DOES NOTHING. An empty cell is not a tile; the
    # refusal is one line in the channel the author is looking at, and no
    # command at all rather than a `map.tileset.mask.set` for gid 0.
    said.clear()
    quiet = len(baking.history())
    canvas.set_stamp(Stamp.single(0))
    application.processEvents()
    expect("an empty cell cannot carry a mask, so nothing is written",
           len(baking.history()), quiet)
    expect("...and it says so rather than failing quietly",
           among("pick a tile", said), True)
    expect("...with no dialog", modals, [])

    # A RECTANGLE DRAGGED OUT OF THE PALETTE IS STILL ONE CTRL+Z, and the
    # two tiles it covers had DIFFERENT previous masks -- which is the only
    # shape in which "the inverse carries what it found" can be told apart
    # from "the inverse re-derives a plausible value".
    said.clear()
    before = len(baking.history())
    canvas.set_mask(BLOCK_UP)
    canvas.set_stamp(Stamp.from_rows([[WALL_GID, LEDGE_GID]]))
    application.processEvents()
    expect("a two-tile pick is TWO commands in ONE transaction",
           (len(baking.history()) - before,
            [c.verb for c in last_commands(baking)]),
           (1, ["map.tileset.mask.set", "map.tileset.mask.set"]))
    expect("...and both tiles took the mask",
           (canvas.tile_masks().get(WALL_GID),
            canvas.tile_masks().get(LEDGE_GID)), (BLOCK_UP, BLOCK_UP))
    expect("...the readout following both",
           (canvas.overlay.mask_at(*TILE_WALL),
            canvas.overlay.mask_at(*TILE_LEDGE)), (BLOCK_UP, BLOCK_UP))
    window.undo()
    application.processEvents()
    expect("...and ONE undo puts each back to ITS OWN previous answer",
           (canvas.tile_masks().get(WALL_GID),
            canvas.tile_masks().get(LEDGE_GID)), (BLOCK_ALL, None))

    # THE SINGLE-LAYER READOUT DOES NOT MOVE, AND SAYS SO. A tile's mask is
    # level ONE and this view draws one companion's own gids -- level two.
    # Drawing it here would be the instrument reporting an answer the layer
    # it claims to be showing does not hold; staying silent about it would
    # be the exact "I set a mask and nothing happened" this section exists
    # to close. So: unchanged, and one line saying where to look.
    canvas.set_all_layers(False)
    application.processEvents()
    said.clear()
    canvas.set_mask(BLOCK_ALL)
    canvas.set_stamp(Stamp.single(PLAIN_GID))
    application.processEvents()
    expect("the mask still landed on the tile",
           canvas.tile_masks().get(PLAIN_GID), BLOCK_ALL)
    expect("...but the single-layer view is unmoved, because level one is "
           "not what it draws", canvas.overlay.mask_at(0, 0), NO_DATA)
    expect("...and it says where to look instead of looking broken",
           among("All layers", said), True)
    canvas.set_all_layers(True)
    application.processEvents()
    expect("...and turning it on shows what was there all along",
           canvas.overlay.mask_at(0, 0), BLOCK_ALL)
    window.close()

    # ----------------------------------------------------------------
    print()
    print("a tileset the mask cannot be stored against is REFUSED, in words")
    # ----------------------------------------------------------------
    # Law 7 from the palette's end. The canvas refuses what it can answer
    # for -- a gid belonging to no tileset -- and leaves the rest to the
    # verb, which states it better; either way the gesture ends with a
    # sentence and an unchanged document, never with a mask stored somewhere
    # the engine will not look.
    _ws, _path, plainest = open_baked(reference=None, sidecar=None,
                                      with_collision_tileset=False)
    window = collision_canvas(plainest, layer="Floor", mask=BLOCK_ALL)
    canvas = window.canvas
    said = []
    canvas.status.connect(said.append)
    UNTOUCHED = plainest.project.map("fixture").to_bytes()
    quiet = len(plainest.history())
    canvas.set_stamp(Stamp.single(9999))
    application.processEvents()
    expect("a gid no tileset owns writes nothing",
           len(plainest.history()), quiet)
    expect("...and names the gid it could not place",
           among("9999", said), True)
    expect("...leaving the document exactly as it was found",
           plainest.project.map("fixture").to_bytes() == UNTOUCHED, True)
    expect("...with no dialog", modals, [])
    # The permissive half on the same canvas: a gid that IS owned still
    # goes through, so the refusal above is a guard rather than a wall.
    canvas.set_stamp(Stamp.single(WALL_GID))
    application.processEvents()
    expect("...while a real tile on the same map is still baked",
           canvas.tile_masks().get(WALL_GID), BLOCK_ALL)
    expect("...on a map with no collision tileset at all, which needs none",
           canvas.collision_first_gid, None)
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
