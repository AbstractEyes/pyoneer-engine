"""The collision companion is gone from the panel and still in the field.

The author's complaint was that a collision tilemap is visible at all. A
companion layer was already invisible as PIXELS -- it declares
`pyoneer_renders` false and both the engine and the canvas skip it -- but it
was still a ROW: checkable, selectable, warned about for the wrong reason,
and paintable with art the runtime then reads as no-data. This file covers
the change that removes the row and the two things that change removes with
it.

What it proves, and the half each assertion would be missing without:

  1. THE COMPANION HAS NO ROW, and a layer merely NAMED `...Collision`
     still does. The fold is `companion_pairs`, not the name suffix, and a
     `pyoneer_passability` naming a layer the map does not have folds
     NOTHING -- both driven, because a fold keyed on the suffix passes the
     first assertion and fails the other two silently.
  2. AND ITS MASKS STILL REACH THE ENGINE. Hiding a layer whose data
     stopped being read would pass every visibility assertion above and
     disarm every wall in the map, so the field is baked before and after
     the editor opens the map and compared with `CollisionField.__eq__` --
     and the comparison is proved SENSITIVE by baking a third map whose
     companion cells are zeroed and asserting it differs. The .tmx bytes are
     compared too: opening a map runs no command.
  3. THE BADGE CARRIES THE ENGINE'S OWN REFUSAL. A parallaxed layer's masks
     reach no field -- `collision_layers` drops it -- and folding its
     companion away without carrying that forward would hide a real fault
     the author could at least see a row for. Both halves: the parallaxed
     layer warns, the static one does not.
  4. THE NO-OPINION CHIP EXISTS, IS DRAWN APART FROM `OPEN`, AND CLEARS.
     `PASS_ALL` and NO_DATA are the two values in this vocabulary that draw
     no glyph at all and mean opposite things -- open ENDS the resolve,
     no-opinion falls through to the tile -- so the pixels are compared, not
     just the model. Then both are clicked onto the same cell and the two
     gids must DIFFER.
  5. A MASK REACHES A TILE FROM ONE SHIFT+CLICK ON THE MAP, IN TILES MODE,
     and the map DISPLAY changes because of it. The overlay's own pixels are
     read, not the list behind them: three assertions about a mask list
     stayed green through a pass that cut the wire drawing it.
  6. AND DELETING AN ART LAYER TAKES ITS COMPANION, IN ONE TRANSACTION.
     The fold is what makes this necessary: a companion has no row, so the
     minus button cannot reach it, and an art layer removed on its own left
     a stranded companion that then UNFOLDS -- the visible collision
     tilemap this whole file exists to abolish, produced by the one
     operation an author performs on a painted layer. Three halves, because
     two of them are the ones a pass would forget: ONE Ctrl+Z brings both
     back byte-for-byte (two transactions would restore half a pair), a
     companion SHARED with a second art layer is left alone (taking it from
     a living layer is worse than a stray), and afterwards NO formerly
     folded companion is a row.

Against its OWN fixture (law 4), never `data/maps/starter.tmx`: the fixture is
shaped like the author's canvas -- two art layers, two companions, one of
them parallaxed and therefore dead -- so the migration question is answered
on a map with the same problem and none of his content.

Skips cleanly when PySide6 is not installed.
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
from PySide6.QtGui import QColor, QImage, QMouseEvent                   # noqa: E402
from PySide6.QtWidgets import (                                         # noqa: E402
    QApplication,
    QMainWindow,
    QMessageBox,
)

from editor.core.collision import (                                     # noqa: E402
    NO_DATA,
    collision_first_gid,
    companion_pairs,
    gid_to_opinion,
)
from editor.core.layers import BLOCK_ALL, PASS_ALL, STAR               # noqa: E402
from editor.core.paint import EditMode, Tool                            # noqa: E402
from editor.core.scope import Scope                                     # noqa: E402
from editor.core.session import Session                                 # noqa: E402
from editor.ui.canvas import MapCanvas                                  # noqa: E402
from editor.ui.collision_view import (                                  # noqa: E402
    BRUSH_DOMAIN,
    MASK_DOMAIN,
    MaskPalette,
)
from editor.ui.hierarchy import _MASK_MARK, HierarchyDock              # noqa: E402
from scripts.core.collision_runtime import (                            # noqa: E402
    collision_layers,
    field_from_map,
    world_coordinate_fault,
)
from scripts.loaders.map_document import MapDocument                    # noqa: E402

failures: list[str] = []


# --------------------------------------------------------------------------
# No modal may reach anything below
# --------------------------------------------------------------------------
# Law 13, armed for the whole run: a dialog on any path here would hang the
# suite for 600s rather than fail it, and the panel under test is one the
# author opens on every map.

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
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={got} want={want}")
    if not ok:
        failures.append(label)


# --------------------------------------------------------------------------
# The fixture -- shaped like the author's canvas, holding none of it
# --------------------------------------------------------------------------

WIDTH, HEIGHT = 6, 4
FIRST_GID = 257                       # where the collision tileset starts
WALL = 41                             # an art gid, painted on Floor
PARALLAX_X = 1.4

#: Where Floor's companion holds masks, and what each one says.
FLOOR_MASKS = {(1, 1): BLOCK_ALL, (2, 1): BLOCK_ALL, (4, 2): STAR}
#: Paralax's, which the engine throws away -- see `world_coordinate_fault`.
PARALAX_MASKS = {(0, 0): BLOCK_ALL, (5, 3): BLOCK_ALL}
#: Floor cells holding a tile, so a shift+click has something to mask.
FLOOR_ART = {(0, 3): WALL, (3, 0): WALL}

EMPTY_CELL = (5, 0)                   # no tile on Floor, on purpose


def csv(cells: dict) -> str:
    return ",\n".join(",".join(str(cells.get((x, y), 0)) for x in range(WIDTH))
                      for y in range(HEIGHT))


_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" compressionlevel="-1" width="{w}" height="{h}" \
tilewidth="16" tileheight="16" infinite="0" nextlayerid="6" nextobjectid="1">
 <tileset firstgid="1" name="Art" tilewidth="16" tileheight="16" \
tilecount="256" columns="16">
  <image source="art.png" width="256" height="256"/>
 </tileset>
 <tileset firstgid="{first}" name="collision" tilewidth="16" tileheight="16" \
tilecount="17" columns="17">
  <image source="collision.png" width="272" height="16"/>
 </tileset>
 <layer id="1" name="Paralax" width="{w}" height="{h}">
  <properties>
   <property name="pyoneer_parallax_x" type="float" value="{parallax}"/>
   <property name="pyoneer_passability" value="{paralax_declares}"/>
  </properties>
  <data encoding="csv">
{empty}
</data>
 </layer>
 <layer id="2" name="ParalaxCollision" width="{w}" height="{h}">
  <properties>
   <property name="pyoneer_renders" type="bool" value="false"/>
  </properties>
  <data encoding="csv">
{paralax_masks}
</data>
 </layer>
 <layer id="3" name="Floor" width="{w}" height="{h}">
  <properties>
   <property name="pyoneer_passability" value="{declares}"/>
  </properties>
  <data encoding="csv">
{floor_art}
</data>
 </layer>
 <layer id="4" name="FloorCollision" width="{w}" height="{h}">
  <properties>
   <property name="pyoneer_renders" type="bool" value="false"/>
  </properties>
  <data encoding="csv">
{floor_masks}
</data>
 </layer>
 <layer id="5" name="GhostCollision" width="{w}" height="{h}">
  <data encoding="csv">
{empty}
</data>
 </layer>
</map>
"""


def fixture(*, declares: str = "FloorCollision",
            floor_masks: dict | None = None,
            paralax_declares: str = "ParalaxCollision") -> str:
    """The map, with three knobs and no others.

    `declares` repoints Floor's `pyoneer_passability`. Naming a layer the
    map does not have is the DANGLING case -- an author renames a companion
    in Tiled and the property stays behind -- and it is the one that
    separates a fold derived from `companion_pairs` from one that pattern-
    matches the `Collision` suffix.

    `floor_masks` empties the companion, which is what makes "the field is
    unchanged" an assertion rather than a tautology.

    `paralax_declares` points a SECOND art layer at a companion, which is
    the only way to build the map where removing one art layer must not
    take the companion with it. It is legal content: nothing in the format
    says a companion belongs to one layer.
    """
    return _TEMPLATE.format(
        w=WIDTH, h=HEIGHT, first=FIRST_GID, parallax=PARALLAX_X,
        declares=declares, paralax_declares=paralax_declares,
        empty=csv({}), floor_art=csv(FLOOR_ART),
        paralax_masks=csv({cell: FIRST_GID + mask
                           for cell, mask in PARALAX_MASKS.items()}),
        floor_masks=csv({cell: FIRST_GID + mask for cell, mask in
                         (FLOOR_MASKS if floor_masks is None
                          else floor_masks).items()}))


workspaces: list[str] = []


def open_workspace(text: str):
    """A throwaway project holding one map, and a session over it."""
    workspace = tempfile.mkdtemp(prefix="pyoneer_collision_fold_")
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


# --------------------------------------------------------------------------
# The harness
# --------------------------------------------------------------------------

class Harness(QMainWindow):
    """The three things the panels ask of their window.

    Not `EditorWindow`: a failure here has to be a failure in the hierarchy
    or the canvas rather than in the toolbar that mounts them.
    """

    def __init__(self, session, map_name: str):
        super().__init__()
        self.session = session
        self.map_name = map_name
        self.rejected: list[str] = []
        self.notices: list[str] = []
        self.canvas = MapCanvas(session, map_name, self)
        self.canvas.status.connect(self.notices.append)
        self.setCentralWidget(self.canvas)
        self.hierarchy = HierarchyDock("Hierarchy", session,
                                       Scope.of(("map", map_name)), self)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.hierarchy)
        self.resize(900, 700)

    def notify(self, message, *, seconds: float = 6.0) -> None:
        self.notices.append(message)

    def refresh_manifest(self) -> None:
        pass

    def run(self, commands, *, label=None, source="editor") -> bool:
        try:
            self.session.run(commands, label=label, source=source)
        except Exception as exc:                                # noqa: BLE001
            self.rejected.append(str(exc))
            return False
        self.canvas.rebuild()
        self.hierarchy.refresh()
        return True


def rows(hierarchy) -> list[tuple[str, str, str, bool]]:
    """(label, address, tooltip, warned) for every row in the tree."""
    tree = hierarchy.tree
    out = []
    stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        out.append((item.text(0), item.data(0, Qt.UserRole) or "",
                    item.toolTip(0),
                    item.foreground(0).color() == QColor(Qt.darkYellow)))
        stack.extend(item.child(i) for i in range(item.childCount()))
    return out


#: What `row_named` answers for a layer with no row. A tuple rather than
#: None so a mutation that folds too much fails an ASSERTION instead of
#: crashing the run and hiding every assertion after it.
NO_ROW = ("", "", "", False)


def row_named(hierarchy, name: str):
    """The one row whose ADDRESS is that layer, or NO_ROW when it has none."""
    wanted = f"map:fixture/layer:{name}"
    found = [row for row in rows(hierarchy) if row[1] == wanted]
    return found[0] if found else NO_ROW


def select_layer(hierarchy, name: str) -> None:
    """Put the panel where clicking that layer's row puts it.

    `set_scope` on its own is not it: the minus button's enable lives in
    `refresh`, which is what the window calls after any selection, so
    asserting on a button that was never synced would be asserting on the
    state it was constructed in.
    """
    hierarchy.set_scope(Scope.parse(f"map:fixture/layer:{name}"))
    hierarchy.refresh()
    application.processEvents()


#: What `mask_count` answers for a companion the map no longer holds. A
#: number rather than the raise `tile_layer` would give, for `NO_ROW`'s
#: reason: a mutation that removes too much has to fail an ASSERTION, not
#: crash the run and hide every assertion after it.
NO_LAYER = -1


def mask_count(document, companion: str) -> int:
    """Cells of `companion` the engine would read as an opinion."""
    if companion not in document.tile_layer_names():
        return NO_LAYER
    first_gid = collision_first_gid(document)
    return sum(1 for gid in document.tile_layer(companion).gids()
               if gid and gid_to_opinion(gid, first_gid) != NO_DATA)


def image_bytes(image: QImage) -> bytes:
    return image.convertToFormat(QImage.Format_ARGB32).bits().tobytes()


def click(canvas, cell, *, modifiers=Qt.NoModifier, button=Qt.LeftButton):
    """Press and release on one MAP cell, with whatever modifiers."""
    x = cell[0] * canvas.tile_width + canvas.tile_width / 2
    y = cell[1] * canvas.tile_height + canvas.tile_height / 2
    point = QPointF(canvas.mapFromScene(x, y))
    for kind, handler in ((QEvent.Type.MouseButtonPress,
                           canvas.mousePressEvent),
                          (QEvent.Type.MouseButtonRelease,
                           canvas.mouseReleaseEvent)):
        handler(QMouseEvent(kind, point, button, button, modifiers))
    application.processEvents()


def last_verbs(session) -> list[str]:
    history = session.history()
    return [c.verb for c in history[-1].commands] if history else []


def last_args(session, verb: str) -> dict:
    for command in session.history()[-1].commands:
        if command.verb == verb:
            return command.args
    return {}


application = QApplication.instance() or QApplication([])

try:
    # ----------------------------------------------------------------
    print("the companion has no row, and a layer merely NAMED one does")
    # ----------------------------------------------------------------
    workspace, path, session = open_workspace(fixture())
    document = session.project.map("fixture")
    ORIGINAL = document.to_bytes()
    BEFORE = field_from_map(MapDocument.load(path))

    pairs = companion_pairs(document)
    expect("the fixture is shaped like the author's canvas",
           pairs, [("Floor", "FloorCollision"),
                   ("Paralax", "ParalaxCollision")])

    window = Harness(session, "fixture")
    window.show()
    application.processEvents()
    hierarchy = window.hierarchy
    hierarchy.refresh()
    application.processEvents()

    addresses = [address for _t, address, _d, _w in rows(hierarchy)
                 if "/layer:" in address]
    expect("neither companion is a row at all",
           [name for _art, name in pairs
            if row_named(hierarchy, name) != NO_ROW], [])
    companions = {name for _art, name in pairs}
    expect("...so nothing in this panel can make one the active layer",
           [a for a in addresses
            if a.rsplit("layer:", 1)[-1] in companions], [])
    # THE HALF A SUFFIX MATCH WOULD PASS. `GhostCollision` is a real,
    # paintable tile layer that nobody declares: folding it would hide
    # authored content for good.
    expect("a layer only NAMED like a companion keeps its row",
           row_named(hierarchy, "GhostCollision") != NO_ROW, True)
    expect("and the count is exactly the layers minus the companions",
           len(addresses),
           len(document.tile_layer_names()) - len(pairs))

    # ----------------------------------------------------------------
    print()
    print("the layer that owns the masks wears them")
    # ----------------------------------------------------------------
    floor = row_named(hierarchy, "Floor")
    expect("Floor's row ends in a badge naming how many masks it has",
           floor[0].split()[-1].endswith(
               str(mask_count(document, "FloorCollision"))), True)
    expect("...which is the number the fixture painted",
           mask_count(document, "FloorCollision"), len(FLOOR_MASKS))
    expect("and the tooltip names the layer that is no longer a row",
           "FloorCollision" in floor[2], True)
    expect("while a layer with no companion wears no badge",
           row_named(hierarchy, "GhostCollision")[0].strip().endswith("d?"),
           True)

    # ----------------------------------------------------------------
    print()
    print("A DANGLING DECLARATION FOLDS NOTHING -- the other half")
    # ----------------------------------------------------------------
    # `companion_pairs` warns and SKIPS a `pyoneer_passability` naming a
    # layer the map does not have, which is what an author is left with
    # after renaming a companion in Tiled. A fold that matched the name
    # would hide `FloorCollision` here too, and would hide the one state
    # the author can actually repair.
    _w2, _p2, dangling = open_workspace(fixture(declares="RenamedInTiled"))
    stray = Harness(dangling, "fixture")
    stray.show()
    stray.hierarchy.refresh()
    application.processEvents()
    expect("the orphaned companion is a row again",
           row_named(stray.hierarchy, "FloorCollision") != NO_ROW, True)
    expect("...and Floor wears no badge, because it has no masks",
           row_named(stray.hierarchy, "Floor")[0].strip().endswith("d10"),
           True)
    expect("which is the engine's own reading of that map",
           [name for _art, name
            in companion_pairs(dangling.project.map("fixture"))],
           ["ParalaxCollision"])
    stray.close()

    # ----------------------------------------------------------------
    print()
    print("AND THE MASKS STILL REACH THE ENGINE")
    # ----------------------------------------------------------------
    # The half that would be forgotten. Every assertion above passes just as
    # well when the data has been deleted.
    AFTER = field_from_map(MapDocument.load(path))
    blocking = sum(n for mask, n in AFTER.counts().items()
                   if mask and mask != STAR)
    expect("the baked field is untouched by opening the map",
           BEFORE == AFTER, True)
    expect("...and it is a field with walls in it, not an empty one",
           blocking > 0, True)
    expect("opening a map wrote no command",
           session.history(), [])
    expect("...and changed no byte of the .tmx",
           session.project.map("fixture").to_bytes() == ORIGINAL, True)

    # THE SENSITIVITY HALF: prove `BEFORE == AFTER` could have failed.
    _w3, path3, zeroed = open_workspace(fixture(floor_masks={}))
    expect("a map whose companion was emptied bakes a DIFFERENT field",
           field_from_map(MapDocument.load(path3)) == AFTER, False)

    # ----------------------------------------------------------------
    print()
    print("the badge carries the engine's own refusal, or does not")
    # ----------------------------------------------------------------
    expect("the engine drops the parallaxed layer from the stack",
           [layer.name for layer in collision_layers(document)], ["Floor"])
    fault = world_coordinate_fault(document, "Paralax")
    paralax = row_named(hierarchy, "Paralax")
    expect("...and the parallaxed row says so in the engine's own words",
           fault is not None and fault in paralax[2], True)
    expect("...and is marked, though the genre declares it",
           (paralax[3], session.project.genre.layer("Paralax") is not None),
           (True, True))
    expect("while the layer whose masks DO reach the field is not marked",
           (floor[3], "reach no field" in floor[2]), (False, False))
    expect("no dialog opened on any of that", modals, [])

    # ----------------------------------------------------------------
    print()
    print("the no-opinion chip: a brush value, not an eighteenth mask")
    # ----------------------------------------------------------------
    # MASK_DOMAIN doubles as the physical layout of Collision.png, so it
    # cannot grow: `write_mask_sheet` sizes the sheet from its length and
    # `CollisionTilesetOffer.holds` refuses a map declaring fewer tiles.
    expect("MASK_DOMAIN is still exactly the seventeen storable masks",
           (len(MASK_DOMAIN), MASK_DOMAIN[0], MASK_DOMAIN[-1],
            NO_DATA in MASK_DOMAIN), (17, 0, STAR, False))
    expect("and the BRUSH is those plus no-opinion, in that order",
           BRUSH_DOMAIN, MASK_DOMAIN + (NO_DATA,))

    palette = MaskPalette(window)
    palette.resize(palette.surface.minimumSize())
    palette.surface.resize(palette.surface.minimumSize())
    application.processEvents()
    step = palette.surface.width() // MaskPalette.COLUMNS
    index = BRUSH_DOMAIN.index(NO_DATA)
    chip = ((index % MaskPalette.COLUMNS) * step + step // 2,
            (index // MaskPalette.COLUMNS) * step + step // 2)
    open_index = BRUSH_DOMAIN.index(PASS_ALL)
    open_at = ((open_index % MaskPalette.COLUMNS) * step + step // 2,
               (open_index // MaskPalette.COLUMNS) * step + step // 2)

    expect("the chip is where the widget's own hit test says it is",
           palette.mask_at(chip[0] // step, chip[1] // step), NO_DATA)
    picked: list[int] = []
    palette.mask_picked.connect(picked.append)
    palette.select_mask(NO_DATA)
    expect("selecting it emits it and the caption says what it is",
           (picked, palette.mask, palette.caption.text()),
           ([NO_DATA], NO_DATA, "no opinion"))
    palette.select_mask(999)
    expect("...while a value in neither domain is still refused",
           palette.mask, NO_DATA)

    # THE PIXELS, not the model. `PASS_ALL` and NO_DATA both draw no glyph,
    # and they mean opposite things -- open ENDS the resolve at this level,
    # no-opinion falls through to the tile's own mask. If they render the
    # same, the palette is lying about the one distinction level one exists
    # to make.
    palette.select_mask(BLOCK_ALL)      # so neither chip wears the selection
    application.processEvents()
    sheet = palette.surface.grab().toImage()

    def swatch(at) -> bytes:
        return image_bytes(sheet.copy(at[0] - step // 2 + 3,
                                      at[1] - step // 2 + 3,
                                      palette.cell, palette.cell))

    expect("open and no-opinion are DRAWN differently",
           swatch(open_at) == swatch(chip), False)
    star_index = BRUSH_DOMAIN.index(STAR)
    star_at = ((star_index % MaskPalette.COLUMNS) * step + step // 2,
               (star_index // MaskPalette.COLUMNS) * step + step // 2)
    expect("...and both differently from a swatch that draws a glyph",
           (swatch(open_at) == swatch(star_at),
            swatch(chip) == swatch(star_at)), (False, False))

    # ----------------------------------------------------------------
    print()
    print("one click clears a CELL; a different click asserts it is open")
    # ----------------------------------------------------------------
    canvas = window.canvas
    palette.mask_picked.connect(canvas.set_mask)
    canvas.set_active_layer("Floor")
    canvas.set_mode(EditMode.COLLISION)
    canvas.tool = Tool.BRUSH
    application.processEvents()

    target = (0, 2)                       # nothing painted there yet
    palette.select_mask(BLOCK_ALL)
    click(canvas, target)
    companion = session.project.map("fixture").tile_layer("FloorCollision")
    expect("a mask lands where it was clicked",
           companion.get_tile(*target), FIRST_GID + BLOCK_ALL)
    blocked_pixels = image_bytes(canvas.overlay.cell_image(*target))

    # THE CHIP. Driven through the SURFACE, so the wire under test is
    # pixel -> mask -> canvas -> verb and not a direct call.
    palette.surface.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(*chip),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    application.processEvents()
    expect("clicking the chip aims the canvas at no-opinion", canvas.mask,
           NO_DATA)
    click(canvas, target)
    companion = session.project.map("fixture").tile_layer("FloorCollision")
    cleared = last_args(session, "map.tile.set_many").get("tiles")
    expect("the stroke is one map.tile.set_many, writing the empty cell",
           (last_verbs(session), cleared), (["map.tile.set_many"],
                                            [[target[0], target[1], 0]]))
    expect("...and the companion really is empty there",
           companion.get_tile(*target), 0)
    expect("...and the READOUT changed, not only the list behind it",
           image_bytes(canvas.overlay.cell_image(*target)) == blocked_pixels,
           False)

    # THE OTHER HALF. `open` and `no opinion` are the pair that can be
    # silently conflated, so the two clicks must produce DIFFERENT gids.
    palette.surface.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(*open_at),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    application.processEvents()
    click(canvas, target)
    companion = session.project.map("fixture").tile_layer("FloorCollision")
    expect("clicking OPEN on the same cell writes a different gid",
           (canvas.mask, companion.get_tile(*target)),
           (PASS_ALL, FIRST_GID + PASS_ALL))

    # ----------------------------------------------------------------
    print()
    print("shift+click masks the TILE under the cursor, in TILES mode")
    # ----------------------------------------------------------------
    canvas.set_mode(EditMode.TILES)
    palette.select_mask(BLOCK_ALL)
    application.processEvents()
    art_cell = (0, 3)
    expect("the fixture put a tile there to mask", FLOOR_ART[art_cell], WALL)
    before_pixels = image_bytes(canvas.overlay.cell_image(*art_cell))
    expect("...and nothing has given that tile a mask yet",
           canvas.tile_masks().get(WALL), None)

    click(canvas, art_cell, modifiers=Qt.ShiftModifier)
    expect("shift+click reached the tileset verb, with no mode switch",
           (last_verbs(session), canvas.mode), (["map.tileset.mask.set"],
                                                EditMode.TILES))
    expect("...writing that tile's local id, not its gid",
           last_args(session, "map.tileset.mask.set").get("tile"), WALL - 1)
    expect("...so the tile carries the mask everywhere it is stamped",
           canvas.tile_masks().get(WALL), BLOCK_ALL)
    expect("AND THE MAP DISPLAY SHOWS IT, without All layers or a mode",
           image_bytes(canvas.overlay.cell_image(*art_cell)) == before_pixels,
           False)
    other = image_bytes(canvas.overlay.cell_image(3, 0))
    expect("...on every cell holding that tile, which is what level one is",
           other == image_bytes(canvas.overlay.cell_image(*art_cell)), True)

    # THE CHIP ON A TILE -- the one thing no UI could produce before, and
    # the reason a tile mask could be set and never cleared except by undo.
    palette.surface.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(*chip),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    application.processEvents()
    click(canvas, art_cell, modifiers=Qt.ShiftModifier)
    expect("the chip clears a TILE's mask through the same verb",
           (last_verbs(session),
            last_args(session, "map.tileset.mask.set").get("mask")),
           (["map.tileset.mask.set"], NO_DATA))
    expect("...so the tile carries none",
           canvas.tile_masks().get(WALL), None)
    expect("...and the display went back to what it drew before",
           image_bytes(canvas.overlay.cell_image(*art_cell)) == before_pixels,
           True)

    # THE REFUSAL, which must be a sentence and not a silent no-op.
    history = len(session.history())
    window.notices.clear()
    click(canvas, EMPTY_CELL, modifiers=Qt.ShiftModifier)
    expect("shift+clicking an empty cell writes nothing",
           len(session.history()), history)
    expect("...and says why",
           any("no tile here" in line for line in window.notices), True)
    expect("still no dialog anywhere", modals, [])

    window.close()

    # ----------------------------------------------------------------
    print()
    print("REMOVING AN ART LAYER TAKES ITS COMPANION, IN ONE TRANSACTION")
    # ----------------------------------------------------------------
    # A fresh workspace: everything above wrote commands into `session`, and
    # "one Ctrl+Z empties the history" is only an assertion on a map nothing
    # has edited yet.
    _w4, _p4, cut = open_workspace(fixture())
    cut_window = Harness(cut, "fixture")
    cut_window.show()
    cut_window.hierarchy.refresh()
    application.processEvents()
    cut_tree = cut_window.hierarchy
    CUT_ORIGINAL = cut.project.map("fixture").to_bytes()
    CUT_NAMES = list(cut.project.map("fixture").tile_layer_names())
    CUT_PAIRS = companion_pairs(cut.project.map("fixture"))

    expect("before the click FloorCollision is folded, so it has no row",
           row_named(cut_tree, "FloorCollision"), NO_ROW)

    select_layer(cut_tree, "Floor")
    cut_window.notices.clear()
    expect("the minus button is enabled for an art layer",
           cut_tree.remove_layer.isEnabled(), True)
    # THROUGH THE BUTTON, not through the handler: `QAbstractButton.click`
    # returns immediately on a disabled button, so this drives the enable
    # and the wire in one call and cannot pass on a control nobody can press.
    cut_tree.remove_layer.click()
    application.processEvents()

    cut_document = cut.project.map("fixture")
    expect("the art layer and its companion both left",
           ("Floor" in cut_document.tile_layer_names(),
            "FloorCollision" in cut_document.tile_layer_names()),
           (False, False))
    expect("...in ONE transaction of exactly two removes",
           (len(cut.history()),
            [command.verb for command in cut.history()[-1].commands]),
           (1, ["map.layer.remove", "map.layer.remove"]))
    expect("...naming the selected layer and then its companion",
           [command.scope.require("layer")
            for command in cut.history()[-1].commands],
           ["Floor", "FloorCollision"])
    expect("...and the click SAID the companion went too",
           any("FloorCollision" in line for line in cut_window.notices), True)

    # THE NEGATIVE THAT MOTIVATES THE ITEM. A companion the fold used to
    # hide is stranded by removing its art layer alone: `companion_pairs`
    # stops pairing it, so it unfolds into the tree as a `pyoneer_renders`
    # false row -- the separate collision tilemap the author said must not
    # exist, arrived at by deleting a layer.
    expect("NO formerly folded companion is a visible row afterwards",
           [name for _art, name in CUT_PAIRS
            if row_named(cut_tree, name) != NO_ROW], [])
    # THE OTHER HALF OF THE FOLD: the untouched pair is still a pair, so
    # this did not pass by emptying the tree.
    expect("...because the OTHER pair is untouched and still folded",
           ("Paralax" in cut_document.tile_layer_names(),
            "ParalaxCollision" in cut_document.tile_layer_names(),
            row_named(cut_tree, "ParalaxCollision")), (True, True, NO_ROW))
    expect("and a layer nobody paired is still there to remove by hand",
           row_named(cut_tree, "GhostCollision") != NO_ROW, True)

    # ONE Ctrl+Z. Two `run` calls would leave a second transaction on the
    # stack and hand the author half a deleted pair, so `can_undo` after one
    # undo is the assertion that this was a single transaction.
    cut.undo()
    cut_window.canvas.rebuild()
    cut_tree.refresh()
    application.processEvents()
    restored = cut.project.map("fixture")
    expect("ONE undo brings both back, and empties the stack",
           (restored.tile_layer_names(), cut.stream.can_undo),
           (CUT_NAMES, False))
    expect("...byte-for-byte, whitespace included",
           restored.to_bytes() == CUT_ORIGINAL, True)
    expect("...and the companion folds away again",
           row_named(cut_tree, "FloorCollision"), NO_ROW)
    # Compared as a BOOLEAN, not printed: this console is cp1252 and the
    # badge glyph is U+25A8, so putting it in a `got=` would crash the run
    # inside `expect` and take every assertion after it down with it.
    expect("...with Floor wearing every one of its masks again",
           (row_named(cut_tree, "Floor")[0].endswith(
               f"{_MASK_MARK}{len(FLOOR_MASKS)}"),
            mask_count(restored, "FloorCollision")),
           (True, len(FLOOR_MASKS)))
    cut_window.close()

    # ----------------------------------------------------------------
    print()
    print("A SHARED COMPANION IS LEFT ALONE -- the half that must not fire")
    # ----------------------------------------------------------------
    # Two art layers, one companion. Taking it away from a layer that is
    # still standing is a worse outcome than leaving a stray, because the
    # stray is visible and the disarmed layer is not.
    _w5, _p5, shared = open_workspace(fixture(paralax_declares="FloorCollision"))
    shared_window = Harness(shared, "fixture")
    shared_window.show()
    shared_window.hierarchy.refresh()
    application.processEvents()
    shared_tree = shared_window.hierarchy
    expect("the fixture really does share one companion between two layers",
           companion_pairs(shared.project.map("fixture")),
           [("Floor", "FloorCollision"), ("Paralax", "FloorCollision")])

    select_layer(shared_tree, "Floor")
    shared_window.notices.clear()
    shared_tree.remove_layer.click()
    application.processEvents()

    left = shared.project.map("fixture")
    expect("the shared companion stayed, and only Floor was removed",
           ("Floor" in left.tile_layer_names(),
            "FloorCollision" in left.tile_layer_names(),
            [command.scope.require("layer")
             for command in shared.history()[-1].commands]),
           (False, True, ["Floor"]))
    expect("...with its masks still in the file, every one of them",
           mask_count(left, "FloorCollision"), len(FLOOR_MASKS))
    expect("...still folded, because Paralax still points at it",
           (row_named(shared_tree, "FloorCollision"),
            "FloorCollision" in row_named(shared_tree, "Paralax")[2]),
           (NO_ROW, True))
    expect("...and the click did not claim to have removed it",
           any("FloorCollision" in line for line in shared_window.notices),
           False)
    expect("no dialog opened on either removal", modals, [])
    shared_window.close()

finally:
    for directory in workspaces:
        shutil.rmtree(directory, ignore_errors=True)

print()
if failures:
    print(f"FAILED: {failures}")
    sys.exit(1)
print("PASS")
