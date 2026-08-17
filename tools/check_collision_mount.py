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

from editor.core.collision import NO_DATA, gid_to_opinion               # noqa: E402
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
