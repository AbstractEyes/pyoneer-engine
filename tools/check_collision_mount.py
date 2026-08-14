"""Assert the collision stack is actually WIRED to the canvas.

`check_collision.py` and `check_collision_view.py` already prove the model
and the pixmap are correct. They proved that while nothing in the editor
imported either one -- 2,794 lines of verified code with zero production
importers. This file covers the seam those two cannot see: that a real
`MapCanvas` mounts the overlay, that the mode changes where a drag lands,
and that a collision stroke is one transaction with an exact inverse.

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

import importlib.util
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
from PySide6.QtGui import QMouseEvent                                   # noqa: E402
from PySide6.QtWidgets import (                                         # noqa: E402
    QApplication,
    QGraphicsPixmapItem,
    QMainWindow,
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
from editor.ui.canvas import COLLISION_TILESET, MapCanvas               # noqa: E402
from editor.ui.collision_view import CollisionOverlay                   # noqa: E402

failures: list[str] = []


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


FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" compressionlevel="-1" width="{w}" height="{h}" \
tilewidth="16" tileheight="16" infinite="0" nextlayerid="4" nextobjectid="1">
 <tileset firstgid="1" name="Art" tilewidth="16" tileheight="16" \
tilecount="256" columns="16">
  <image source="art.png" width="256" height="256"/>
 </tileset>
 <tileset firstgid="{first}" name="collision" tilewidth="16" tileheight="16" \
tilecount="17" columns="17">
  <image source="collision.png" width="272" height="16"/>
 </tileset>
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
""".format(w=WIDTH, h=HEIGHT, first=COLLISION_FIRST_GID,
           empty=_csv({}),
           roof=_csv({CONFLICT_CELL: COLLISION_FIRST_GID + BLOCK_UP}))


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


workspace = tempfile.mkdtemp(prefix="pyoneer_collision_mount_")
application = QApplication.instance() or QApplication([])

try:
    os.makedirs(os.path.join(workspace, "config"))
    os.makedirs(os.path.join(workspace, "data", "maps"))
    fixture_path = os.path.join(workspace, "data", "maps", "fixture.tmx")
    with open(fixture_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(FIXTURE)
    with open(os.path.join(workspace, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [{"name": "fixture", "identifier": "fixture",
                             "file": "data/maps/fixture.tmx"}]}, handle)

    session = Session.open(workspace, genre_id="topdown_rpg")
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

    # ----------------------------------------------------------------
    print()
    print("a map with no collision tileset refuses instead of inventing one")
    # ----------------------------------------------------------------
    messages.clear()
    canvas.status.connect(messages.append)
    canvas.set_mode(EditMode.COLLISION)
    real_tilesets = type(document).tilesets
    type(document).tilesets = lambda self: []
    try:
        before = len(session.history())
        drag(application, canvas, [(0, 0), (2, 0)])
        expect("nothing was written", len(session.history()) - before, 0)
        expect("and it names what is missing",
               any(COLLISION_TILESET in m for m in messages), True)
    finally:
        type(document).tilesets = real_tilesets
    canvas.status.disconnect(messages.append)

    window.close()

finally:
    CollisionOverlay.bake = _real_bake
    CollisionOverlay.bake_resolved = _real_resolved
    CollisionOverlay.set_cell = _real_set_cell
    shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
