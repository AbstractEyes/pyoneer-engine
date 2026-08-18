"""The map canvas and the tile palette.

MOUSE CONVENTIONS
-----------------
Taken from Tiled and Aseprite, because a tile editor that invents its own
are the ones nobody keeps using:

    left drag        paint with the current tool
    right drag       erase (a temporary eraser, whatever the tool)
    middle drag      pan
    space + drag     pan
    ctrl + wheel     zoom under the cursor
    alt + click      pick the tile under the cursor into the brush

The first version required `alt+click` to paint at all and panned with a
plain drag, which is backwards: panning is the occasional act and painting
is the constant one.

ONE STROKE, ONE TRANSACTION
---------------------------
Press-drag-release accumulates in an `editor.core.paint.Stroke` and commits
a single `map.tile.set_many` on release. Before this, dragging across forty
cells produced forty transactions, so undo walked back one tile at a time
and the tmx csv payload was re-rendered forty times.

While the stroke is live the canvas draws a translucent GHOST of what it
would do. Nothing is committed until the button comes up, so dragging out a
rectangle and changing your mind costs nothing.

TWO MODES, ONE SET OF TOOLS
---------------------------
`EditMode.COLLISION` changes what a stroke WRITES, never what the tools ARE:
brush still brushes, R is still a rectangle, right-drag still erases. The
only differences are the layer that receives the write -- the active layer's
companion passability layer -- and the value, a mask instead of a tile.

That is why there is no second stroke machinery. A mask is stored as
`first_gid + mask` in an ordinary tile layer, so `paint.Stroke` over the
companion is already correct, down to the eraser: it writes gid 0, and gid 0
in a companion layer is `NO_DATA`, "nobody said anything here" -- which is
exactly what erasing collision should mean, and is NOT the same claim as
"open". Committing is the same `map.tile.set_many`, so a collision stroke
inherits one-transaction undo and an exact inverse for free.

The mode reaches the PALETTE by the same rule, and that is the one place it
did not used to. A tile picked in collision mode set a brush the mode cannot
paint with -- a live control that did nothing -- so it now writes that tile's
own mask instead, everywhere the tile is ever stamped. Same two-step as a
cell: pick the mask, then pick what it applies to. See `set_stamp` and
`bake_tile_mask`.

The companion layer is created by the FIRST stroke that needs it, inside the
same transaction as the tiles. Three commands land together or none do, and
one undo takes the layer, its declaration and its tiles back out in reverse.

The mask TILESET is created the same way, by the same stroke. It used to be
the one thing that was not: a 191-word modal dialog explained gid arithmetic
mid-gesture, refused to write the PNG it named, consumed the stroke that
asked, and left behind a map that raised `FileNotFoundError` on load. The
whole of that reasoning, and what replaced it, is at
`CollisionTilesetOffer` and `write_mask_sheet`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsItemGroup,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from scripts.core.errors import PyoneerError
from scripts.core.collision_runtime import (  # noqa: F401  (re-exported)
    COLLISION_TILESET,
    COMPANION_SUFFIX,
    collision_first_gid as engine_collision_first_gid,
    collision_layers,
    companion_name as engine_companion_name,
    depth_for_layer_name,
    tileset_defaults,
)
from scripts.game.behavior.base import BEHAVIORS
from scripts.loaders.map_document import tileset_geometry

from editor.core import autotile
from editor.core.collision import (
    NO_DATA,
    SUBCELL,
    CollisionLayer,
    companion_subcell,
    field_subcell,
    gid_to_opinion,
    opinion_to_gid,
)
from editor.core.commands import Command
from editor.core.layers import BLOCK_ALL, describe_mask, read_profile
from editor.core.paint import (
    Bounds,
    EditMode,
    Stamp,
    Stroke,
    Tool,
    edits_to_triples,
    footprint,
    grid_lines,
)
from editor.core.scope import Scope
from editor.ui.collision_view import (
    LEVEL_NONE,
    MASK_DOMAIN,
    CollisionOverlay,
    glyph_pixmaps,
    masks_from_layer,
    resolve_cell,
)
from editor.ui.tileset import TilesetAtlas, gid_colour, render_layer

_OBJECT_PEN = QColor(255, 90, 90)
_OBJECT_SELECTED = QColor(120, 200, 255)
_GRID_PEN = QColor(255, 255, 255, 28)
_GHOST_Z = 2000
#: Under a mask ghost, so that painting "open" or clearing -- both of which
#: draw no glyph at all -- still shows you where the brush is.
_MASK_GHOST_FILL = QColor(120, 200, 255, 60)
_MASK_GHOST_PEN = QColor(120, 200, 255, 140)
#: The tile palette's marker for "this tile carries its own mask".
#:
#: A GLYPH ALONE CANNOT CARRY IT, and that is the whole reason this colour
#: exists rather than just drawing the overlay's glyph. `PASS_ALL`'s glyph is
#: deliberately EMPTY -- an open cell is more than half of a map and absence
#: is the cheapest possible signal -- so a tile baked OPEN would look exactly
#: like a tile nobody has ever touched. "Open" and "nobody said anything" are
#: the one distinction level one exists to make, and a palette that cannot
#: show it is a palette the author cannot use to find their own work.
_BAKED_PEN = QColor(255, 206, 74)

# COLLISION_TILESET and COMPANION_SUFFIX are imported from
# `scripts/core/collision_runtime.py` above and re-exported here, because
# `from editor.ui.canvas import COLLISION_TILESET` is what the checks and the
# rest of the UI already write. They used to be spelled a second time in this
# file. A map is PAINTED against that tileset name here and READ back by it in
# the engine; two copies means a map painted against one spelling and read
# against the other, which is collision the player cannot feel -- no error, no
# warning, just walls that are not there.
#
# A map without the tileset is GIVEN one by the stroke that needs it -- see
# `CollisionTilesetOffer` -- appended above every gid range the map already
# uses, so it changes the meaning of no gid that already exists.

#: Where the offer proposes the mask sheet. Written into the tmx and therefore
#: RELATIVE TO THE .tmx, which is what Tiled and the engine both resolve an
#: `<image source>` against, and spelled with forward slashes for the same
#: reason `tileset_dialog.relative_image_path` does: a backslash here is a
#: path that only opens on Windows. It sits beside the sheets the shipped map
#: already names.
COLLISION_IMAGE = "../graphics/tilesets/System/Collision.png"


def write_mask_sheet(path: str, tile_width: int, tile_height: int) -> bool:
    """Put the mask sheet on disk. CREATE-ONLY-IF-ABSENT, never overwrite.

    Returns True when it wrote one and False when a file was already there.
    That asymmetry is the whole reason this is safe to run inside an
    undoable gesture: calling it again is a no-op, so undo/redo/undo can
    cycle for as long as the author likes without ever touching a sheet
    they have since replaced with their own. Undo removes the `<tileset>`
    DECLARATION -- the document edit, which the command stream owns and
    inverts exactly -- and leaves the file. An unreferenced PNG on disk is
    harmless; a map that raises `FileNotFoundError` at load is not.

    Raises OSError when it cannot write. `QImage.save` returns False and
    raises NOTHING -- measured, over a read-only target -- so an unchecked
    call reports success and lets the caller declare a tileset whose image
    is not there, which is the exact failure this function exists to
    remove. Law 7: raise, never fall back to a plausible default.

    Tile N of the sheet IS mask N, because a mask is stored as
    `first_gid + mask`, so the glyphs are laid out in `MASK_DOMAIN` order --
    the same order the Collision palette shows. NOTHING READS THESE PIXELS:
    the editor draws its own glyphs from `glyph_pixmaps` and the engine
    reads numbers. They are drawn anyway so the sheet is legible to a human
    who opens it in Tiled, which is why `demos/mapgen.py` hand-draws the
    same seventeen. That one is pygame and cannot be called from here --
    the editor is deliberately pygame-free -- and
    `tools/make_placeholder_art.py` is a script with a hardcoded three-entry
    table and no importable API, so this is a third caller of Qt's painter
    rather than a second implementation of anything.
    """
    if os.path.exists(path):
        return False
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    image = QImage(tile_width * len(MASK_DOMAIN), tile_height,
                   QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    glyphs = glyph_pixmaps(tile_width, tile_height)
    try:
        for index, mask in enumerate(MASK_DOMAIN):
            glyph = glyphs.get(mask)
            if glyph is not None:
                painter.drawPixmap(index * tile_width, 0, glyph)
    finally:
        # An open QPainter holds the QImage's buffer; save() while it is
        # live writes a half-flushed file on some platforms and warns on
        # all of them.
        painter.end()
    if not image.save(path, "PNG"):
        raise OSError(f"could not write the collision mask sheet to {path}")
    return True


@dataclass(frozen=True)
class CollisionTilesetOffer:
    """What declaring a `collision` tileset on one map would write.

    Plain data, Qt-free once built, and derived without a window, so the
    decision is checkable headlessly. `TilesetImport` is the same shape for
    the same reason.

    WHY THE PIXELS ARE PROVISIONED RATHER THAN ASKED FOR. The sheet exists
    for one reason: pytmx opens every `<image source>` it parses, and
    `pygame.image.load` raises FileNotFoundError, which stops the whole map
    loading -- measured, on a tmx declaring an absent image. Nothing reads
    what is ON it. The editor renders masks from
    `collision_view.glyph_pixmaps`, a companion layer declares
    `pyoneer_renders=false` so `rebuild()` skips it, and the engine reads
    numbers. So the file has to EXIST at the declared size and its contents
    are irrelevant.

    This class used to carry a `prompt()` -- 191 words, 16 lines, on a
    left-click -- whose argument was that a written PNG has no inverse and
    so the author must go and create the file by hand. That argument does
    not survive measurement, and both halves were measured:

      * the tmx bytes `map.tileset.add` produces are BIT-IDENTICAL whether
        or not the PNG is on disk, and add/undo/redo/undo/redo/undo is
        byte-exact at every step. Provisioning cannot reach the document,
        the inverse, or the byte-exactness contract, so there is no
        coupling to protect;
      * the outcome it chose instead was a project that will not boot.

    `write_mask_sheet` is create-only-if-absent, which is idempotent, so
    the undo cycle it was afraid of is safe without ever deleting anything.
    """

    name: str
    image: str                  # as written into the .tmx
    absolute: str               # where that resolves on this machine
    tile_width: int
    tile_height: int
    image_width: int
    image_height: int
    columns: int
    rows: int
    tile_count: int
    exists: bool                # on disk AND readable; see the reader below

    @property
    def sufficient(self) -> bool:
        """Can this grid hold every mask?

        A mask is stored as `first_gid + mask`, so tile N of this sheet IS
        mask N. A sheet with fewer than seventeen tiles leaves the high masks
        -- including STAR, "defer to the layer below" -- pointing past its
        end, where pytmx resolves them to whatever tileset comes next.
        """
        return self.tile_count >= len(MASK_DOMAIN)

    def command_args(self) -> dict[str, Any]:
        """Arguments for `map.tileset.add`.

        `image_width` and `image_height` are handed over EXPLICITLY, not left
        to be measured. `MapDocument.add_tileset` reads the PNG header when
        they are absent and raises when the file is not there -- and the
        whole point of this offer is that the file is usually not there yet.
        Passing them is what lets a map declare the tileset today and the
        author drop the sheet in afterwards.
        """
        return {
            "name": self.name,
            "image": self.image,
            "tile_width": self.tile_width,
            "tile_height": self.tile_height,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "columns": self.columns,
            "tile_count": self.tile_count,
        }

    def grid(self) -> str:
        """One line naming the cut, the way the import dialog does."""
        return (f"{self.image_width}x{self.image_height} -> {self.columns} "
                f"columns x {self.rows} rows = {self.tile_count} tiles")


def _EMPTY_READER(_x: int, _y: int) -> int:                       # noqa: N802
    """Every cell empty -- what a companion layer that does not exist yet
    holds. A `Stroke` needs a reader to drop no-op edits against, and the
    honest answer for a layer about to be created is gid 0 everywhere."""
    return 0


@dataclass(frozen=True)
class PaintUnit:
    """What ONE addressable cell is, right now, and where the number came
    from.

    Resolved in one place -- `MapCanvas.paint_unit` -- so that the displayed
    grid, the cell a click snaps to, the ghost, the bounds a stroke clips to
    and the mask that gets written cannot be reading five different numbers.
    Before this it was five reads of `document.tile_width`, and on a map whose
    companion declares `pyoneer_subcell="4"` all five were wrong the same way:
    the canvas addressed whole tiles and the file stored quarter-tiles, so a
    click wrote a mask up to 1,188px from the cursor on a 100x100 map and 20px
    from it on the 4x4 fixture below.

    `refusal` is the one thing this cannot resolve: a companion whose
    declaration cannot be read at all. It is carried rather than raised
    because this is consulted on every mouse move and every grid line, and an
    exception on that path takes the editor down over a property an author
    can fix in Tiled. The stroke is refused instead -- see
    `MapCanvas.collision_stroke_refusal`, which is where law 7 is actually
    paid: nothing is written, and the reason is said out loud.
    """

    #: How many addressable cells one map TILE divides into, per axis.
    subcell: int
    #: Pixels per addressable cell. `tile size // subcell`, both axes.
    width: int
    height: int
    #: The companion the number was read off. None in tile mode, where a
    #: companion's resolution is none of a tile stroke's business.
    layer: str | None = None
    #: Why the declaration could not be read, if it could not be.
    refusal: str | None = None


class MapCanvas(QGraphicsView):
    """A depth-ordered, paintable view of one map."""

    status = Signal(str)
    picked_gid = Signal(int)
    picked_mask = Signal(int)          # alt/picker in collision mode
    selected = Signal(object)          # a Scope

    def __init__(self, session, map_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.map_name = map_name
        self.active_layer: str | None = None
        self.tool = Tool.BRUSH
        self.stamp = Stamp.single(1)
        self.mode = EditMode.TILES
        self.mask = BLOCK_ALL          # the collision brush; see set_mask
        self.all_layers = False
        self.object_class = "GameEntity"
        self.hidden_layers: set[str] = set()
        self.selected_scope: Scope | None = None
        self.show_grid = True
        #: How many paint cells apart the grid lines are drawn. A view
        #: preference, so it comes from `editor.core.settings` -- the one
        #: store -- and it can only ever SKIP boundaries, never invent
        #: them. See `paint.grid_lines`.
        self.grid_step = 1
        #: How many sub-cells per map tile a companion layer CREATED by the
        #: next collision stroke is given. An authoring preference, so it
        #: comes from `editor.core.settings` -- the same one store
        #: `grid_step` comes from -- and it reaches `paint_unit`, so the
        #: cell a click addresses before the companion exists is the cell
        #: the companion is about to hold.
        #:
        #: 1 by DEFAULT, and that number is not timidity: measured on a
        #: 100x100 map, a 4x companion is 8.6x the file bytes and +271ms per
        #: companion at load. The author opts in, and an existing companion
        #: keeps whatever it declares -- there is no verb to re-scale one.
        self.collision_subcell = 1
        #: The brush footprint, in paint cells, for the tools that have
        #: one. Transient like `tool` and `stamp` and deliberately not
        #: persisted: it is a moment-to-moment choice, not a view
        #: preference, and every editor the author has used forgets it.
        self.brush_size = 1
        #: The tileset this stroke will declare in front of its tiles, or
        #: None. Set at press by `provision_collision_tileset`, consumed by
        #: `__commit_collision`, and cleared either way -- so a gesture that
        #: never commits cannot leave a declaration queued for the next one.
        self.__pending_tileset: CollisionTilesetOffer | None = None
        #: Did this session's provisioning actually write the PNG? Carried
        #: so the commit can disclose it ONCE, in the same status line as
        #: the stroke, rather than as a second message about plumbing.
        self.__wrote_sheet = False

        # This canvas holds NO `confirm` seam and this module imports no
        # QMessageBox. Both facts are asserted structurally by
        # `tools/check_collision_mount.py`, because a modal on the paint
        # path is not only bad UX -- law 13 -- it is a measured way to wedge
        # the check suite for 40 minutes with no output.

        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(28, 28, 32)))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.atlas: TilesetAtlas | None = None
        self.__stroke: Stroke | None = None
        self.__terrain: _TerrainStroke | None = None
        self.__erasing = False
        self.__ghost: QGraphicsItemGroup | None = None
        self.__panning = False
        self.__pan_from = None
        self.__space = False
        self.__overlay: CollisionOverlay | None = None
        self.__overlay_geometry: tuple[int, int, int, int] | None = None
        self.__collision_stale = True
        self.__own_commit = False
        #: Level one, memoised: `(defaults, refusal)` or None for "not read
        #: yet". The only part of the collision stack that is cached, because
        #: it is the only part that lives in a file -- see
        #: `__tileset_defaults` for the key and why the rest is not cached.
        self.__level_one: tuple[tuple, str | None] | None = None
        #: Why the last stack BUILD came back empty, or None. Recorded rather
        #: than recomputed: reproducing it on the mouse-move path would mean
        #: snapshotting every layer's gids to find out.
        self.__stack_build_refusal: str | None = None

        # The overlay is kept current cell by cell as strokes commit, so it
        # has to be told when the document moved some OTHER way -- an undo, a
        # redo, an applied response, a command from a panel. The stream
        # announces every one of those and this is the only way to hear about
        # them; without it the readout would quietly disagree with the map
        # after the first Ctrl+Z, which is the worst failure an instrument
        # can have.
        self.session.stream.subscribe(self.__on_transaction)
        self.rebuild()

    # -- document ----------------------------------------------------------

    @property
    def document(self):
        return self.session.project.map(self.map_name)

    @property
    def tile_width(self) -> int:
        return self.document.tile_width

    @property
    def tile_height(self) -> int:
        return self.document.tile_height

    # -- the paint unit ----------------------------------------------------
    #
    # THE ONE NUMBER THAT USED TO DO THREE JOBS. `document.tile_width`
    # decided how big the displayed grid was, what a click snapped to, and
    # how much a single press painted, and it reached all three through
    # separate reads -- so nothing coupled them and nothing could move one
    # without the others.
    #
    # Everything that means "an addressable CELL" reads `paint_width` /
    # `paint_height`, and everything that means "the size of a tile's ART"
    # -- the atlas, the tile ghost, the terrain ghost, an object's default
    # box -- still reads `tile_width` / `tile_height`.
    #
    # THE SEAM IS NOW LOAD-BEARING. The split shipped as a rename with no
    # behaviour in it, against the day a companion layer would divide a tile.
    # That day is here: a companion declaring `pyoneer_subcell="4"` stores
    # four masks per tile per axis, and until this funnel subdivided, the
    # canvas still reported 16 on such a map -- the click snapped to a whole
    # tile, the mask went into the sub-cell of the same index, and the wall
    # landed a long way from the cursor. Measured on the 4x4 fixture in
    # `tools/check_collision_mount.py`: a click at scene pixel (26, 26)
    # wrote sub-cell (1, 1), which is pixels 4..7 -- 20px up and 20px left of
    # where the author clicked, and 1,188px on a 100x100 map.

    def paint_unit(self) -> PaintUnit:
        """One addressable cell, resolved from the MODE and the companion.

        WHICH mode subdivides is the mode's own business -- `EditMode
        .subdivides` -- and is asked here rather than tested against
        `EditMode.COLLISION`, so the enum that declares what a drag means
        also declares whether the thing being dragged can be smaller than a
        tile. In tile mode a cell is a tile: nothing about a passability
        layer's resolution should move the grid the author paints art on.

        HOW FINELY is the map's business, and cannot live on the enum: it is
        `pyoneer_subcell` on the companion this stroke would write into, a
        FILE FORMAT string read through the engine's own `companion_subcell`
        rather than re-spelled here, so the cell the editor addresses is the
        cell the runtime bakes.

        A companion that does not exist yet resolves to the resolution this
        canvas would CREATE it at -- `collision_subcell`, the author's own
        preference -- and not to 1. The two have to be the same number or
        the first stroke on a fresh map is the 1,200px bug with the roles
        swapped: the click addresses a whole tile and the layer created to
        hold it stores sixteen masks per tile, so the mask lands in the
        top-left sixteenth of the tile the author clicked.

        THE MODE IS NOT THE WHOLE ANSWER, and assuming it was cost 1,200px.
        `mode.subdivides` says WHICH LAYER a stroke goes to, and the sentence
        above -- "in tile mode a cell is a tile" -- quietly assumed the active
        layer is an ART layer. A companion is a selectable row in the Layers
        panel, so an author can click it and paint on it in TILE mode. Then
        the assumption is false: measured, a click at px(1599,1599) on a
        100x100 map wrote companion cell (99,99), which owns x396..399 --
        1,200 pixels away -- and only 6% of the companion (10,000 of 160,000
        cells) was addressable at all. The collision tileset lives in the same
        palette, so this wrote REAL masks: a wall baked at sub-cell (1,1) for
        a click on (6,6). That is the original defect verbatim, on a surface
        none of the five named gaps covered.

        So the resolution comes from the LAYER BEING PAINTED, whichever that
        is. In collision mode that is the companion this stroke would write
        into; in tile mode it is the active layer itself. A layer with no
        declaration answers 1, so an art layer is unaffected and this stays
        one read.
        """
        document = self.document
        tile_w, tile_h = document.tile_width, document.tile_height
        name = (self.companion_name() if self.mode.subdivides
                else self.active_layer)
        subcell, refusal = self.__declared_subcell(name)
        return PaintUnit(subcell, tile_w // subcell, tile_h // subcell,
                         layer=name, refusal=refusal)

    def __declared_subcell(self, name: str | None) -> tuple[int, str | None]:
        """(resolution, why it could not be read) for one companion layer.

        The ONE read of `pyoneer_subcell` on this class. `paint_unit` and
        `overlay_subcell` both come through here, so the cell a click lands
        in and the cell the readout draws are the same cell by construction
        rather than by two functions agreeing.

        An absent property means 1 -- that is the file format's documented
        default, decided at `SUBCELL` in `scripts/core/collision_runtime.py`,
        not a guess made here.

        A layer that does not exist yet is two different questions wearing
        one shape. If it is the COMPANION this canvas would create, the
        answer is `__pending_subcell`: `map.layer.add` now takes a
        resolution, so the layer is about to be whatever the author asked
        for and the click has to address that same cell. Anything else --
        no active layer, an object layer, a name this map does not have --
        is 1, which is what a tile-mode stroke on an art layer has always
        wanted.

        The error is RETURNED rather than raised because this is consulted on
        every mouse move and every grid line; see `PaintUnit.refusal`.
        """
        document = self.document
        if name is None or name not in document.tile_layer_names():
            if name is not None and name == self.companion_name():
                return self.__pending_subcell()
            return 1, None
        try:
            return companion_subcell(document, name), None
        except PyoneerError as exc:
            return 1, str(exc)

    def __pending_subcell(self) -> tuple[int, str | None]:
        """(resolution, why not) for the companion the next stroke CREATES.

        `collision_subcell` is a PREFERENCE and the map is a FACT, and the
        two are reconciled here -- once, into the same `(value, refusal)`
        pair `__declared_subcell` hands back for a companion that already
        exists. So `paint_unit` cannot tell the created case from the
        pre-made one, which is exactly the distinction that let the 4x
        assertions all start from a hand-written 4x fixture and never once
        drive the path an author actually takes first.

        THE REFUSAL IS `companion_subcell`'S OWN RULE, spelled here because
        that reader needs a LAYER and this runs before one exists. A mirror
        rots, so it is not left to be trusted: `tools/check_collision_mount
        .py` asserts both sides on the same map -- that this refuses, and
        that `map.layer.add` carrying the same factor raises there too. Law 7
        decides the shape rather than a fallback: a factor the map cannot
        hold draws at 1x and REFUSES to write, the same as an unreadable
        declaration one branch up.
        """
        document = self.document
        wanted = int(self.collision_subcell)
        if wanted < 1:
            return 1, (f"the collision resolution is set to {wanted} "
                       f"sub-cells per tile; it is 1 or more (1 means one "
                       f"mask per map tile)")
        if document.tile_width % wanted or document.tile_height % wanted:
            return 1, (f"the collision resolution is set to {wanted} "
                       f"sub-cells per tile, but this map's tiles are "
                       f"{document.tile_width}x{document.tile_height}px and "
                       f"{wanted} does not divide them evenly; a sub-cell "
                       f"has to land on whole pixels")
        return wanted, None

    @property
    def paint_subcell(self) -> int:
        """How many addressable cells one map tile divides into, per axis."""
        return self.paint_unit().subcell

    @property
    def paint_width(self) -> int:
        """Pixels per addressable cell, horizontally."""
        return self.paint_unit().width

    @property
    def paint_height(self) -> int:
        """Pixels per addressable cell, vertically."""
        return self.paint_unit().height

    def cell_at(self, scene_x: float, scene_y: float) -> tuple[int, int]:
        # Floor division, not int(): int(-0.5) is 0, which puts the cell one
        # to the right of where the cursor actually is on the left edge.
        unit = self.paint_unit()
        return (int(scene_x // unit.width), int(scene_y // unit.height))

    def __footprint(self, stamp: Stamp | None = None):
        """The stamp this press should place, and where it sits.

        The gate is `self.tool.uses_size` -- the SELECTED tool, not the
        effective one. A right-drag substitutes the eraser, which does take
        a footprint, but the toolbar's size control is greyed or lit for
        what is selected: making the two disagree would give the author a
        greyed control that quietly changed the size of a right-drag.
        """
        size = self.brush_size if self.tool.uses_size else 1
        return footprint(self.stamp if stamp is None else stamp, size)

    def __active_tile_layer(self):
        if self.active_layer is None:
            return None
        document = self.document
        if self.active_layer not in document.tile_layer_names():
            return None
        return document.tile_layer(self.active_layer)

    # -- collision addressing ----------------------------------------------

    @property
    def collision_first_gid(self) -> int | None:
        """The firstgid masks are stored relative to, or None if this map has
        no collision tileset. Everything collision-shaped checks this first,
        because without it a mask cannot be encoded OR decoded.

        The engine's own function, called rather than mirrored: this canvas
        WRITES the gids that function READS, and the two answering from
        separate copies of "the tileset called collision, case-insensitively"
        is a difference the author would only meet as a wall that is not
        there.
        """
        return engine_collision_first_gid(self.document)

    def collision_tileset_offer(self) -> CollisionTilesetOffer:
        """What declaring the mask tileset on THIS map would write.

        The geometry comes from `tileset_geometry`, which is the function
        `MapDocument.add_tileset` itself uses to write `columns` and
        `tilecount` -- so what the offer describes and what the file records
        come from one function rather than from two divisions that agree
        until margins exist.

        A sheet already on disk is MEASURED rather than assumed, because the
        author may have supplied one of their own shape. One that is present
        but undecodable counts as absent: the canonical size is the better
        guess, and a file Qt cannot read is a file the author has to replace
        anyway.
        """
        document = self.document
        directory = os.path.dirname(document.path or "")
        absolute = (os.path.normpath(os.path.join(directory, COLLISION_IMAGE))
                    if directory else COLLISION_IMAGE)
        tile_width, tile_height = document.tile_width, document.tile_height

        image = QImage(absolute) if os.path.isfile(absolute) else QImage()
        exists = not image.isNull()
        width = image.width() if exists else tile_width * len(MASK_DOMAIN)
        height = image.height() if exists else tile_height

        columns, rows, count = tileset_geometry(
            width, height, tile_width, tile_height, 0, 0)
        return CollisionTilesetOffer(
            name=COLLISION_TILESET, image=COLLISION_IMAGE, absolute=absolute,
            tile_width=tile_width, tile_height=tile_height,
            image_width=width, image_height=height,
            columns=columns, rows=rows, tile_count=count, exists=exists)

    def collision_tileset_ref(self):
        """The `<tileset>` masks are stored in, as a ref, or None.

        Found BY THE FIRSTGID the engine answered with rather than by
        re-spelling "the tileset called collision, case-insensitively".
        That predicate lives in `scripts/core/collision_runtime.py` and
        nowhere else; a second spelling here is how the canvas and the
        engine come to disagree about which tileset a mask means, which the
        author only ever meets as a wall that is not there.
        """
        first_gid = self.collision_first_gid
        if first_gid is None:
            return None
        for ref in self.document.tilesets():
            if ref.first_gid == first_gid:
                return ref
        return None

    def provision_collision_tileset(self) -> CollisionTilesetOffer | None:
        """Get the mask sheet onto disk, and say what to declare for it.

        Returns the offer for `__commit_collision` to prepend, or None
        having emitted ONE status line saying why the stroke was refused.
        No dialog, no question, nothing to dismiss: every outcome here is
        either "carry on painting" or "refuse the gesture, say why in one
        line, change nothing".

        This does not touch the document. The DECLARATION is a document
        change and stays in the command stream with an exact inverse, in
        the same transaction as the tiles it exists for -- provisioning an
        asset is not a document change, and the companion LAYER, created
        silently by the first stroke that needs it, is the precedent
        sitting in the very next method.

        Two of the three refusals below are about a sheet the AUTHOR
        supplied; never overwrite one to make it fit.
        """
        offer = self.collision_tileset_offer()
        if not offer.sufficient:
            # Only reachable for a sheet already on disk: an absent one is
            # sized from MASK_DOMAIN and is sufficient by construction.
            self.status.emit(
                f"the collision sheet at {offer.absolute} is too small — "
                f"{offer.grid()}, and a mask sheet needs {len(MASK_DOMAIN)}. "
                f"Delete it and paint again to have one made")
            return None
        try:
            wrote = write_mask_sheet(offer.absolute, offer.tile_width,
                                     offer.tile_height)
        except OSError as exc:
            # The absolute path FIRST and always, because the cause varies
            # -- `makedirs` raises with the directory in the message and a
            # refused `QImage.save` carries no path at all -- and the one
            # thing the author needs is where the editor was trying to
            # write.
            self.status.emit(
                f"could not write the collision sheet at {offer.absolute} "
                f"({exc}) — nothing was changed")
            return None
        self.__wrote_sheet = wrote
        return offer

    def companion_name(self, layer_name: str | None = None) -> str | None:
        """Which layer holds `layer_name`'s masks.

        The layer's own `pyoneer_passability` declaration if it has one --
        the author may point two art layers at one companion, and that is a
        legitimate thing to author -- otherwise the name this canvas would
        create. Returning the would-be name rather than None is what lets one
        stroke both create the companion and paint into it.

        Only the "which layer is this about" part is this canvas's: the
        answer itself comes from the engine's `companion_name`, so the layer
        this stroke paints into is by construction the layer the game reads
        the masks out of. None means the question does not apply -- no active
        layer, or a name this map does not have -- which is not something the
        engine's version has to answer.
        """
        name = layer_name if layer_name is not None else self.active_layer
        if name is None or name not in self.document.tile_layer_names():
            return None
        return engine_companion_name(self.document, name)

    def companion_layer(self, layer_name: str | None = None):
        """The companion as a TileLayer, or None when it does not exist yet."""
        document = self.document
        name = self.companion_name(layer_name)
        if not name or name not in document.tile_layer_names():
            return None
        return document.tile_layer(name)

    def collision_stroke_refusal(self) -> str | None:
        """Why a collision stroke cannot be PLACED right now, or None.

        THE GUARD. A mask is only meaningful at the resolution its companion
        declares, and the cell a click resolved to came from `paint_unit`.
        If those two numbers disagree, every cell of the stroke is written at
        the right index into the wrong grid -- which does not look like a
        bug, it looks like collision that is slightly off, and the author
        finds it by walking into a wall that is not there.

        So this reads the declaration a SECOND time, straight off the
        document, and compares. Two independent reads is normally the shape
        this file spends its docstrings arguing against; here it is the whole
        point. `paint_unit` is the funnel, and a guard that consulted the
        funnel would be asserting `x == x`. Close gap 2 correctly and this is
        unreachable -- which is the right outcome, and is why it is a status
        line rather than an exception: the next person to touch `paint_width`
        gets a refusal naming both numbers instead of a misplaced wall.

        Law 7, stated in the negative: never write a mask you cannot place.
        Law 13 decides the shape -- a STATUS LINE, never a dialog, because
        this sits on the paint path and `editor/ui/ask.py` is the only seam
        in this editor that is allowed to be modal.
        """
        unit = self.paint_unit()
        if unit.refusal is not None:
            return (f"{unit.refusal} — refusing the stroke rather than "
                    f"writing a mask at a resolution nobody agrees on")
        name = self.companion_name()
        document = self.document
        if name is None or name not in document.tile_layer_names():
            # There is nothing to disagree with yet: the companion this
            # stroke CREATES is created at `paint_unit`'s own resolution --
            # `__commit_collision` passes that very number to
            # `map.layer.add` -- so the two cannot diverge here by
            # construction. A resolution the map cannot hold at all is
            # already refused above, through `unit.refusal`.
            return None
        declared = companion_subcell(document, name)      # cannot raise: see above
        if declared == unit.subcell:
            return None
        # The worst cell on THIS map, so the number is about the map in front
        # of the author rather than about a hypothetical one. Cell i is
        # written at i x the companion's cell size and was clicked at i x the
        # paint unit, so the two diverge by i x the difference; the largest i
        # that both addresses and lands is bounded by whichever grid runs out
        # first. Both cells are square by construction -- `companion_subcell`
        # refuses a subcell the tile size does not divide -- so one axis tells
        # the whole story. Measured: 1,188px on a 100x100 map at 16px.
        cell_px = document.tile_width // declared
        last = min(document.width * unit.subcell,
                   document.width * declared) - 1
        drift = last * abs(unit.width - cell_px)
        return (f"refusing this collision stroke: a click here addresses a "
                f"{unit.width}x{unit.height}px cell ({unit.subcell} per tile) "
                f"but {name!r} declares {SUBCELL}={declared}, which is "
                f"{cell_px}x{document.tile_height // declared}px — a mask "
                f"would land up to {drift}px from the cursor")

    def collision_stack(self, subcell: int | None = None) -> list[CollisionLayer]:
        """The map's collision stack, TOPMOST FIRST -- THE ENGINE'S OWN.

        `collision_layers`, called and not mirrored. This method used to
        build its members here: one `CollisionLayer` per companion, ordered
        by this canvas's own depth table, with `companion=` and nothing else.
        Every word of that was true of the engine too until a tileset learned
        to carry its own masks, and then it was three separate lies at once.
        Measured at the commit that landed level one: an author painted a
        mask, saw ONE level, and the player walked THREE -- so a wall the
        author never painted stopped him, the overlay drew nothing there, and
        the only way to find out was to walk into it.

        The three that diverged, and none of them announces itself:

          * LEVEL ONE was absent. The engine stacks `tileset_defaults` under
            every companion; this drew the companion alone.
          * MEMBERSHIP was different. With defaults in play the engine puts
            every non-companion tile layer at world coordinates into the
            stack, because the whole value of a mask on the TILE is that
            stamping the tile is the only authoring step -- a layer nobody
            thought to give a companion is exactly the layer that would
            otherwise be missed. This canvas required a companion.
          * ORDER was different. `layer_rank` ranks by the engine's own
            `layer_depth`; this ranked by `__depth_of`, which asks the GENRE
            PACK first. The engine never reads a genre pack. `Resolution.layer`
            is an INDEX, so one layer ranked differently renumbers every
            answer the readout gives about who decided.

        So membership, order, resolution and the levels themselves are the
        engine's answer now, and this method's whole remaining job is to say
        WHERE the answer is read from -- see `__collision_stack`, which holds
        the two things a canvas has that a bake does not: level one memoised,
        and a raise turned into a sentence instead of a dead editor.

        `subcell` is the resolution the STACK is read at, defaulting to the
        finest any of its members declares -- `field_subcell`, the same
        function `field_from_map` calls, so a stack resolved here and a field
        baked there index the same cells. `collision_layers` scales every
        member into it, which is what keeps a 1x companion on a mixed map
        drawn over its own map tile rather than four times too close to the
        origin -- measured on the engine side at 84px.

        Rebuilt whenever it is consulted rather than cached: a member costs
        one flat snapshot of its layer's gids (`document_gid_reader`), 0.78 ms
        for a whole stack over a 400x400 companion, against the 6.9 ms rebuild
        every command already pays. A cache keyed on nothing reliable is how a
        readout comes to disagree with the map, which is the worst failure an
        instrument has. Level one is the one exception and it is keyed on
        something real -- see `__tileset_defaults`.
        """
        return self.__collision_stack(subcell)[0]

    def __collision_stack(self, subcell: int | None = None
                          ) -> tuple[list[CollisionLayer], str | None]:
        """(the stack, why it is empty) -- the raising call, made safe.

        `collision_layers` RAISES on a map it cannot read, which is right for
        the engine: law 7, and a map that raises at load is a map with no
        collision rather than a map with some. A canvas cannot raise here.
        This method sits under `rebuild`, under a mouse move and under a
        stroke's own commit, and an exception on any of the three is the
        editor going down over a map the author opened it to repair.

        SO THE REFUSAL IS CARRIED, NEVER SWALLOWED, and the resolved view
        goes DARK rather than degrading. That is the change of mind this pass
        makes and it is worth stating plainly: the previous shape read a bad
        companion at 1x and drew a plausible readout beside a warning, on the
        argument that an editor which cannot draw a broken map cannot fix
        one. But the map is still drawn, the single-layer collision view
        still works, and the brush still paints -- it is only the ALL-LAYERS
        view that goes dark, and that view's entire claim is "this is what
        the player will feel". On a map the engine refuses there is no player
        and no field, so every cell it could draw would be an invention.
        Nothing plus a sentence beats a plausible picture plus a sentence.
        """
        if subcell is None:
            subcell = self.stack_subcell()
        defaults, refusal = self.__tileset_defaults()
        if refusal is not None:
            return [], refusal
        try:
            return collision_layers(self.document, subcell=subcell,
                                    defaults=defaults), None
        except PyoneerError as exc:
            self.__stack_build_refusal = (
                f"the resolved view is empty because this map's collision "
                f"stack cannot be built: {exc}")
            return [], self.__stack_build_refusal

    def __tileset_defaults(self):
        """(level one for this map, why it could not be read).

        MEMOISED, unlike everything else the stack is made of, because this
        is the one level that lives in a FILE. `stack_refusal` is consulted on
        every mouse move; opening and parsing a `.blitmask` per pixel of
        travel is not a cost worth paying for an answer that can only change
        when the document does.

        The key is the same one the overlay's own staleness uses: cleared by
        `rebuild` and by every transaction, which between them cover every
        way a `<tileset>`'s `pyoneer_collision` can appear, change or go. A
        sidecar edited on disk behind the editor's back is stale until the
        next command, exactly as `TilesetAtlas`'s art is.

        MISSING IS NOT AN ERROR AND UNREADABLE IS. A tileset that declares no
        masks contributes none and says nothing -- that is every map in this
        repository, and it must stay free. A tileset that declares a
        `.blitmask` which is absent, mis-shaped or names another sheet makes
        `tileset_defaults` raise, and the engine raises on the same map at
        load; the refusal is what carries that fact to the author instead of
        letting the overlay imply the map is fine.
        """
        if self.__level_one is None:
            try:
                self.__level_one = (tuple(tileset_defaults(self.document)), None)
            except PyoneerError as exc:
                self.__level_one = ((), f"this map's tileset masks could not "
                                        f"be read: {exc}")
        return self.__level_one

    def stack_subcell(self) -> int:
        """The finest resolution any companion on this map declares.

        `field_subcell`, the engine's own function, so the overlay's
        all-layers view is drawn at exactly the resolution `field_from_map`
        bakes at. Named differently from the function it calls because the
        canvas has two resolutions and they are not the same question: this
        one is about the whole STACK, `paint_unit` is about the one companion
        a stroke writes into.

        It raises on a stack whose declarations do not nest; that raise is
        caught for `paint_unit`'s reason -- this is consulted from `rebuild`,
        and a map the editor cannot draw is a map the author cannot fix. It
        is CAUGHT, not swallowed: `stack_refusal` is the other half and the
        readout says it out loud.
        """
        return self.__field_subcell()[0]

    def stack_refusal(self) -> str | None:
        """Why the resolved view cannot be trusted on this map, or None.

        THE HALF THAT WAS MISSING. `stack_subcell` degrades to 1 on a map
        the ENGINE refuses to load, which is right -- an editor that cannot
        draw a broken map is an editor that cannot fix one -- and for as
        long as that was the whole story the all-layers view drew a
        plausible 1x readout over a map that raises at load and said
        nothing at all. The author found out from the STROKE path, if a
        stroke happened to be refused, in a message about the stroke.

        A readout that is wrong and quiet is the worst state an instrument
        has, so the reason is carried out to where the author is looking:
        the cell readout under the cursor, and the moment All layers is
        switched on. Reported, never raised -- this sits on the same mouse
        move `paint_unit` does.

        THREE WAYS TO BE UNREADABLE, in the order they are cheap to know:
        a `pyoneer_subcell` the map cannot honour, a `.blitmask` a tileset
        declares and this map cannot open, and anything else that made
        `collision_layers` refuse the stack. The first two are answered from
        state that is already computed or memoised, which is what lets this
        be called on every mouse move; the third is recorded by the build
        that hit it, because reproducing it here would mean snapshotting
        every layer's gids to find out.
        """
        return (self.__field_subcell()[1] or self.__tileset_defaults()[1]
                or self.__stack_build_refusal)

    def __field_subcell(self) -> tuple[int, str | None]:
        """(the stack's resolution, why it could not be read).

        The ONE read of `field_subcell` on this class, in the same
        `(value, refusal)` shape `__declared_subcell` uses for one companion,
        so `stack_subcell` and `stack_refusal` are two halves of one answer
        rather than two functions that have to agree about when to raise.
        """
        try:
            return field_subcell(self.document), None
        except PyoneerError as exc:
            return 1, f"the readout is drawn at 1x cells: {exc}"

    def overlay_subcell(self) -> int:
        """The resolution the READOUT is drawn at.

        Not always `paint_unit`'s, and deliberately: the all-layers view
        resolves every collision layer into the one answer the player will
        feel, and that answer only exists at the finest resolution in the
        stack. An author painting a 1x layer on a map that also carries a 4x
        one paints whole tiles and READS quarter-tiles, which is exactly what
        the game will do with the same two layers.

        Otherwise it is the active companion's own resolution -- read through
        `__declared_subcell`, the same call `paint_unit` makes, because
        `paint_unit` answers 1 in TILE mode and re-sizing a scene-sized pixmap
        on a mode switch would be paying a bake for a change in what is being
        painted rather than in what is being shown.
        """
        if self.all_layers:
            return self.stack_subcell()
        return self.__declared_subcell(self.companion_name())[0]

    # -- building ----------------------------------------------------------

    def __depth_of(self, name: str) -> int:
        """How high a layer DRAWS in this scene.

        The genre pack first, because that is the editor's authored contract
        with the author, then the ENGINE's table for anything it does not
        declare. The fallback used to be a bare 500, which meant a layer the
        renderer ranks (`ENTITY_1`, `FOREGROUND_2`, `UI_LAYER_1` -- all in
        `scripts/core/depth.MAP_DEPTH`, none in any genre pack) sorted here at
        500 and there at 20, 90 or 100.

        DRAWING ONLY. It used to order the collision stack as well, and that
        was a second table deciding which layer wins a cell: the engine ranks
        collision through `layer_rank` -> `layer_depth` -> `MAP_DEPTH` and has
        never read a genre pack. `collision_stack` delegates to
        `collision_layers` now, so the two cannot differ by construction.
        `tools/check_collision_runtime.py` still asserts the two tables agree
        wherever both rank a name, which is what keeps the PIXELS and the
        walls in the same order as well.
        """
        declared = self.session.project.genre.layer(name)
        if declared is not None:
            return declared.depth
        return depth_for_layer_name(name)

    def rebuild(self) -> None:
        # Level one is re-read from here down, for `TilesetAtlas`'s reason
        # and on the same beat: a rebuild is what follows every document
        # change this canvas is told about, and a `<tileset>` declaration is
        # a document change. See `__tileset_defaults`.
        self.__refresh_level_one()
        scene = self.scene()
        # scene.clear() DELETES what it holds, C++ side and all, and the
        # overlay is meant to outlive a rebuild. removeItem hands ownership
        # back to us; clearing while it is attached would leave a live Python
        # wrapper around freed memory, which is a crash and not an exception.
        self.__detach_overlay()
        scene.clear()
        self.__ghost = None

        try:
            document = self.document
        except Exception as exc:                                # noqa: BLE001
            scene.addText(f"map unreadable: {exc}")
            return

        self.atlas = TilesetAtlas(document,
                                  tile_width=document.tile_width,
                                  tile_height=document.tile_height)
        width = document.width * document.tile_width
        height = document.height * document.tile_height
        scene.setSceneRect(0, 0, width, height)

        depth_of = self.__depth_of
        for name in sorted(document.tile_layer_names(), key=depth_of):
            layer = document.tile_layer(name)
            # A data layer -- passability, region ids, spawn weights -- says
            # so with pyoneer_renders=false, and the engine already skips it.
            # Drawing its gids as art puts confetti over the map and hides
            # the thing the author is actually editing.
            if name in self.hidden_layers or not read_profile(layer).renders:
                continue
            item = QGraphicsPixmapItem(render_layer(layer, self.atlas))
            item.setZValue(depth_of(name))
            item.setTransformationMode(Qt.FastTransformation)
            # The layer being painted stays fully opaque; everything above it
            # fades, so you can see what you are doing without hiding context.
            if self.active_layer and depth_of(name) > depth_of(self.active_layer):
                item.setOpacity(0.35)
            scene.addItem(item)

        for name in document.object_layer_names():
            if name in self.hidden_layers:
                continue
            self.__draw_objects(scene, document.object_layer(name),
                                depth_of(name) + 0.5, name)

        self.__draw_grid(scene, document, width, height)
        self.__mount_overlay()

        if self.atlas.missing:
            self.status.emit(
                f"no tileset art for {', '.join(self.atlas.missing)} — "
                f"drawing colour swatches (docs/ASSETS.md)")

    def __draw_objects(self, scene, layer, z: float, layer_name: str) -> None:
        selected_id = None
        if self.selected_scope is not None and self.selected_scope.kind == "object" \
                and self.selected_scope.get("layer") == layer_name:
            selected_id = int(self.selected_scope.require("object"))
        for obj in layer.objects():
            width = obj.width or self.tile_width
            height = obj.height or self.tile_height
            is_selected = obj.id == selected_id
            colour = _OBJECT_SELECTED if is_selected else _OBJECT_PEN
            rect = QGraphicsRectItem(QRectF(obj.x, obj.y, width, height))
            rect.setPen(QPen(colour, 2.5 if is_selected else 1.5))
            rect.setBrush(QBrush(QColor(colour.red(), colour.green(),
                                        colour.blue(), 60 if is_selected else 30)))
            rect.setZValue(z + (0.1 if is_selected else 0))
            scene.addItem(rect)
            label = QGraphicsSimpleTextItem(obj.name or obj.type or str(obj.id))
            label.setBrush(QBrush(QColor(240, 240, 240)))
            # Scale the label back so zoom does not turn it into a billboard.
            label.setFlag(QGraphicsSimpleTextItem.ItemIgnoresTransformations)
            label.setPos(obj.x, obj.y - 14)
            label.setZValue(z + 0.2)
            scene.addItem(label)

    def set_background(self, colour) -> None:
        if colour is not None:
            self.setBackgroundBrush(QBrush(colour))

    def __draw_grid(self, scene, document, width: int, height: int) -> None:
        """Cell boundaries, every `grid_step` of them.

        Drawn in PAINT cells rather than in tiles, and only on boundaries
        that exist -- `grid_lines` returns a subset of the real ones, so a
        coarser grid hides lines and can never invent them. That is the
        difference between a grid setting and a lie: at any step, every
        line the author sees is somewhere a click can actually land.

        Which is why the unit is read ONCE, into a local, rather than per
        line: `paint_unit` reaches the document, and a 100x100 map at 4x is
        401 lines per axis. Same number for every line of one grid is also
        the only way the promise above can hold.
        """
        if not self.show_grid:
            return
        pen = QPen(_GRID_PEN)
        pen.setCosmetic(True)
        # Not clamped here. `EditorSettings` validates the stored value
        # against its own choices and falls back if it is nonsense -- a
        # corrupt preference must not stop the editor booting -- so a bad
        # step arriving at the canvas means a CALLER set it, and
        # `grid_lines` raising is the right way to find that out.
        step = self.grid_step
        unit = self.paint_unit()
        columns = width // unit.width
        rows = height // unit.height
        for column in grid_lines(columns, step):
            x = column * unit.width
            scene.addLine(x, 0, x, height, pen).setZValue(1000)
        for row in grid_lines(rows, step):
            y = row * unit.height
            scene.addLine(0, y, width, y, pen).setZValue(1000)

    def set_layer_visible(self, name: str, visible: bool) -> None:
        if visible:
            self.hidden_layers.discard(name)
        else:
            self.hidden_layers.add(name)
        self.rebuild()

    def set_active_layer(self, name: str | None) -> None:
        self.active_layer = name
        # A different layer means a different companion, so the readout is
        # about to be about something else.
        self.__collision_stale = True
        self.rebuild()

    def set_selection(self, scope: Scope) -> None:
        self.selected_scope = scope
        self.rebuild()

    # -- the collision overlay ---------------------------------------------

    @property
    def overlay(self) -> CollisionOverlay | None:
        """The collision readout, once a rebuild has had a document to size
        it against. Exposed so a panel can read `mask_at`/`describe` rather
        than re-deriving what is already rendered."""
        return self.__overlay

    def set_mode(self, mode: EditMode) -> None:
        """Switch what a stroke acts on. Same tools, same keys, other layer."""
        if mode is self.mode:
            return
        self.mode = mode
        # A mode change mid-drag would commit a stroke into the layer the
        # other mode addresses. Dropping it is the honest outcome -- and the
        # queued declaration goes with it, or the NEXT stroke would carry a
        # `map.tileset.add` nobody asked for.
        self.__stroke = None
        self.__pending_tileset = None
        self.__wrote_sheet = False
        self.__terrain = None
        self.__clear_ghost()
        self.__collision_stale = True
        self.rebuild()
        self.status.emit(mode.tip)

    def set_all_layers(self, on: bool) -> None:
        """Resolve the whole stack instead of showing one layer's opinion.

        A re-bake is normally enough -- the same cells, a different answer in
        each. It is not enough when the two views are drawn at different
        RESOLUTIONS: a 1x active layer on a map that also carries a 4x one
        resolves at 4x, which is a different number of cells and a different
        pixmap, so the item has to be rebuilt rather than repainted. Asked as
        a geometry comparison rather than as "is this map mixed", because
        that is the question `__mount_overlay` will ask anyway.
        """
        if bool(on) == self.all_layers:
            return
        self.all_layers = bool(on)
        self.__collision_stale = True
        # The gesture that ASKS for the resolved view is the one place a
        # single status line cannot be stomped by something else's -- nothing
        # else emits on this path. `set_mode` does (its tip, right after the
        # rebuild), which is why the readout below repeats it on every move
        # rather than this being the only telling.
        if self.all_layers:
            refusal = self.stack_refusal()
            if refusal is not None:
                self.status.emit(f"All layers cannot be trusted here: "
                                 f"{refusal}")
        if self.overlay_geometry() != self.__overlay_geometry:
            self.rebuild()
            return
        if self.mode is EditMode.COLLISION:
            self.__bake_overlay()

    def set_mask(self, mask: int) -> None:
        """The mask a collision stroke writes -- what `stamp` is to tiles."""
        self.mask = int(mask)

    # -- a mask on the TILE, not on the cell -------------------------------
    #
    # THE MODE ALREADY MEANT THIS, ONE SURFACE FURTHER OUT. `EditMode
    # .COLLISION` has always meant "a click writes a mask instead of a tile"
    # -- that is the sentence at the top of this module -- and until this
    # section it was true of the CANVAS and false of the palette. In
    # collision mode a tile pick set `stamp`, a brush that mode cannot paint
    # with, so the Tiles palette was a live control that did nothing at all.
    # It now does the only thing a tile can mean beside a mask: give that
    # TILE this mask, once, for everywhere it is ever stamped.
    #
    # So the two-step is the one the author already learned for cells -- pick
    # the mask in the palette, then pick what it applies to -- with the
    # tileset palette standing in for the map. No second mask vocabulary, no
    # second widget, and nothing new to learn except which of the two tabs
    # the second click lands in.
    #
    # WHERE THE ANSWER SHOWS UP, AND WHERE IT DOES NOT.       #TAG:tile_mask_is_level_one
    # A tile's mask is LEVEL ONE. The single-layer readout draws one
    # companion's own gids -- level two -- so it cannot show a tile mask and
    # must not pretend to; the resolved All-layers view is where level one
    # lives, and `__on_transaction` marks the overlay stale for this
    # transaction like any other, so the next rebuild re-bakes it. Measured
    # on the fixture in `tools/check_collision_mount.py`: one palette pick,
    # and every cell holding that tile changes in the readout, on layers
    # that have no companion at all. The single-layer case is not silently
    # wrong -- it says in one line where to look.

    def set_stamp(self, stamp: Stamp) -> None:
        """A tile picked in the palette. What it MEANS is the mode's answer.

        In TILES mode it is the brush, exactly as it has always been. In
        COLLISION mode the brush is a MASK, so the tile is the TARGET and the
        pick writes that mask onto the tile itself.

        The stamp is remembered EITHER WAY, and that is not incidental: a
        mode switch must not lose the author's tile, and the palette's own
        highlight does not move back.
        """
        self.stamp = stamp
        if self.mode is EditMode.COLLISION:
            self.bake_tile_mask(stamp)

    def bake_tile_mask(self, stamp: Stamp | None = None) -> bool:
        """Give every tile in `stamp` the collision brush's mask, for good.

        ONE TRANSACTION, one `map.tileset.mask.set` per distinct tile, each
        carrying the exact `map.tileset.mask.restore` the verb hands back --
        so a rectangle dragged out of the palette is still one Ctrl+Z, and it
        puts back both the cells and the `pyoneer_collision` declaration a
        first bake had to add.

        REFUSALS ARE SAID, NEVER GUESSED AROUND (law 7). An empty pick, an
        atlas that has not loaded, a gid belonging to no tileset this map
        declares: each ends the gesture with one status line and no command
        at all, so nothing is half-written. The verb's OWN refusals -- an
        external tileset whose extent lives in a .tsx, a tileset with no name
        to derive a sidecar from -- are left to the verb, which states them
        far better than a second guess here could and reaches the author
        through `run`'s rejection report. Nothing on this path opens a
        dialog; a palette click is as routine as a paint stroke.

        A TILESET THAT CARRIES NO MASKS STAYS FREE. This writes the sidecar
        the first time and declares it in the same transaction, exactly as
        the first collision stroke provisions `Collision.png` -- and a map
        nobody has ever baked a tile on declares nothing, opens nothing and
        costs nothing, which is every map in this repository.
        """
        if self.atlas is None:
            self.status.emit("no tilesets are loaded yet, so there is no "
                             "tile to give a mask to")
            return False
        stamp = self.stamp if stamp is None else stamp
        mask = self.mask
        # Distinct, and in the order the palette laid them out: a 2x2 pick of
        # one repeated tile is ONE mask edit, not four commands writing the
        # same cell whose inverses would then undo each other in sequence.
        gids: list[int] = []
        for gid in stamp.gids:
            # -1 is `Stamp`'s "leave this cell alone" hole and 0 is the empty
            # cell. Neither is a tile, so neither can carry a mask.
            if gid > 0 and gid not in gids:
                gids.append(gid)
        if not gids:
            self.status.emit("pick a tile in the Tiles palette to give it "
                             "this mask")
            return False

        map_scope = Scope.of(("map", self.map_name))
        commands: list[Command] = []
        for gid in gids:
            entry = self.atlas.entry_for(gid)
            if entry is None:
                self.status.emit(
                    f"gid {gid} belongs to no tileset this map declares, so "
                    f"there is nowhere to store its mask — nothing changed")
                return False
            commands.append(Command("map.tileset.mask.set", map_scope, {
                # A name when there is one, the firstgid when there is not:
                # an external `<tileset source=...>` carries no name in this
                # file, and `_tileset_key` takes either.
                "name": entry.name,
                "first_gid": 0 if entry.name else entry.first_gid,
                "tile": gid - entry.first_gid,
                "mask": mask,
            }))

        what = f"tile {gids[0]}" if len(gids) == 1 else f"{len(gids)} tiles"
        if not self.window().run(commands,
                                 label=f"{what} {describe_mask(mask)}"):
            return False
        # AFTER run(), which writes its own line to the same status bar. The
        # author is left looking at what the click did, not at the verb that
        # did it -- `__commit_collision` makes the same argument.
        note = ""
        if self.mode is EditMode.COLLISION and not self.all_layers:
            note = (" — turn All layers on to see it: this view draws one "
                    "companion's own cells, and a tile's mask is not one")
        self.status.emit(
            f"{what}: {describe_mask(mask)}, everywhere "
            f"{'it is' if len(gids) == 1 else 'they are'} stamped{note}")
        return True

    def tile_masks(self) -> dict[int, int]:
        """gid -> the mask its TILESET carries, for every tile that has one.

        Level one, read through the SAME memo the resolved overlay resolves
        against -- `__tileset_defaults` -- so the badge the palette draws and
        the glyph the overlay draws cannot come to disagree. Two reads of one
        `.blitmask` is how the palette would come to say a tile is baked over
        a map on which it is not.

        MISSING IS NOT AN ERROR. A tileset that declares no masks contributes
        none, which is every map in this repository and must stay free; a
        declaration that cannot be honoured answers an empty mapping here and
        leaves the shouting to `stack_refusal`, which is already saying it in
        the status bar and on every mouse move.
        """
        found: dict[int, int] = {}
        defaults, _refusal = self.__tileset_defaults()
        for tileset in defaults:
            for local, opinion in enumerate(tileset.opinions):
                if opinion != NO_DATA:
                    found[tileset.first_gid + local] = opinion
        return found

    def __detach_overlay(self) -> None:
        if self.__overlay is not None and self.__overlay.scene() is not None:
            self.__overlay.scene().removeItem(self.__overlay)

    def overlay_geometry(self) -> tuple[int, int, int, int]:
        """The readout's size, in cells and in pixels per cell.

        FROM THE COMPANION, NOT FROM THE MAP. The overlay draws what is in
        the file, so its cells have to BE the file's cells: a companion
        declaring `pyoneer_subcell="4"` holds sixteen masks per map tile, and
        an overlay sized from the map drew one 16px glyph where the file has
        sixteen 4px ones -- a readout that disagreed with the layer it was
        reading, in the instrument whose only job is to agree with it.

        Taking the companion's OWN width and height, rather than
        `map * subcell`, closes a second one for free: a companion smaller
        than the map is legal (`file_gid_reader` answers 0 past its edge on
        purpose), and `bake` fits a flat row-major list by index, so a
        narrower layer baked into a map-wide overlay skewed by one row per
        row. Now the two grids are the same grid.

        The all-layers view is the exception and sizes from the MAP, because
        a resolved field is not any one layer -- it is every layer, at the
        finest resolution any of them declares, which is what the engine
        bakes and therefore what the player will feel.
        """
        document = self.document
        subcell = self.overlay_subcell()
        cell_w = max(1, document.tile_width // subcell)
        cell_h = max(1, document.tile_height // subcell)
        if not self.all_layers:
            companion = self.companion_layer()
            if companion is not None:
                return companion.width, companion.height, cell_w, cell_h
        return (document.width * subcell, document.height * subcell,
                cell_w, cell_h)

    def overlay_cell_at(self, scene_x: float, scene_y: float) -> tuple[int, int]:
        """Which READOUT cell a scene point is in.

        `cell_at`'s sibling, and separate from it because the two grids are
        allowed to differ: painting a 1x layer under the all-layers view is
        a 16px brush over a 4px readout, and the status line has to name the
        cell the cursor is actually over rather than the top-left corner of
        the cell the brush would fill.
        """
        _width, _height, cell_w, cell_h = self.overlay_geometry()
        return int(scene_x // cell_w), int(scene_y // cell_h)

    def __mount_overlay(self) -> None:
        """Put the readout back into the freshly cleared scene.

        Built once per map GEOMETRY and re-added, never rebuilt: the item
        owns a scene-sized pixmap, and both making one and filling it are
        expensive enough that doing either on every command -- and a command
        is every click -- would be felt.
        """
        geometry = self.overlay_geometry()
        if self.__overlay is None or self.__overlay_geometry != geometry:
            self.__overlay = CollisionOverlay(*geometry)
            self.__overlay_geometry = geometry
            self.__collision_stale = True
        self.scene().addItem(self.__overlay)
        self.__overlay.setVisible(self.mode is EditMode.COLLISION)
        if self.mode is EditMode.COLLISION and self.__collision_stale:
            self.__bake_overlay()

    def __on_transaction(self, _transaction, action: str) -> None:
        """Anything that changed the project other than our own stroke."""
        # BEFORE the early return, and deliberately. Our own stroke can carry
        # a `map.tileset.add` in the same transaction as its cells, so "this
        # commit was ours" is a reason not to re-bake the whole overlay and
        # is not a reason to keep reading a tileset table from before it.
        self.__forget_level_one()
        if action == "apply" and self.__own_commit:
            return          # our cells are written by __sync_overlay instead
        self.__collision_stale = True

    def __forget_level_one(self) -> None:
        """Drop the memoised tileset defaults and the last build's refusal.

        Both are answers about a document that has just changed underneath
        them. Kept as one call because forgetting one without the other is a
        readout reporting last document's reason for this document's stack.
        """
        self.__level_one = None
        self.__stack_build_refusal = None

    def __refresh_level_one(self) -> None:
        """Re-read level one, and mark the READOUT stale if it moved.

        A `.blitmask` is the one input to this overlay that can change with
        no command behind it: the refusal names a file, the author goes and
        writes that file, and comes back. Nothing in the stream announces
        that, so a rebuild re-reads the sidecar and compares.

        MARKED STALE ONLY WHEN THE ANSWER REALLY CHANGED. Marking it on every
        rebuild would pay a full bake per command and undo the entire reason
        the overlay item is held across rebuilds -- 6 ms on top of the 26.9 ms
        of layer rendering, on every click. And when a TRANSACTION cleared the
        memo a moment ago there is nothing to compare against, which is
        exactly right: `__on_transaction` has already decided whether that
        change needs a bake, and it knows something this does not -- whether
        the change was our own stroke, whose cells are written one at a time.
        """
        previous = self.__level_one
        self.__forget_level_one()
        if previous is not None and self.__tileset_defaults() != previous:
            self.__collision_stale = True

    def __bake_overlay(self) -> None:
        """The whole field, from the document. The expensive path.

        THE RESOLVED VIEW IS ASKED FIRST, AND IS NOT GATED ON A COLLISION
        TILESET. It used to be: no `collision` tileset meant no firstgid,
        which meant no gid could encode a mask, which meant an empty bake.
        That reasoning is exactly right about level TWO and false about level
        one -- a tileset default is stored in a `.blitmask` beside the .tmx
        and needs no firstgid at all, so the one map shape where the author
        painted nothing and the tiles carry everything drew a blank overlay
        over a map the player cannot cross. `field_from_map` has never had
        that gate; it looks up level one "in the same breath" for this reason.

        The single-layer view keeps the gate, and keeps it correctly: it shows
        one companion's own gids, and without a firstgid there is no companion
        and nothing to decode.
        """
        overlay = self.__overlay
        if overlay is None:
            return
        self.__collision_stale = False
        if self.all_layers:
            # At the overlay's OWN resolution, and every member scaled into
            # it -- see `collision_stack`. The overlay was sized from the
            # same number, so cell (x, y) here and cell (x, y) there are the
            # same square of the map.
            overlay.bake_resolved(self.collision_stack(self.overlay_subcell()))
            return
        first_gid = self.collision_first_gid
        if first_gid is None:
            overlay.bake([])                  # pads with NO_DATA: draws nothing
            return
        companion = self.companion_layer()
        overlay.bake(masks_from_layer(companion, first_gid)
                     if companion is not None else [])

    def __overlay_scale(self) -> int:
        """How many overlay cells one PAINT cell covers, per axis.

        1 whenever the readout and the brush are at the same resolution,
        which is every single-layer view and every unmixed map. It is not 1
        for an author painting a 1x layer while the all-layers view resolves
        the map at 4x: one click changes sixteen cells of that readout, and
        writing only the first of them leaves fifteen showing the answer from
        before the stroke.
        """
        return max(1, self.overlay_subcell() // max(1, self.paint_subcell))

    def __sync_overlay(self, cells) -> None:
        """Repaint only the cells a stroke just changed.

        This is the reason the item is held rather than re-made: a cell is
        10.4 us and a full bake is 6 ms, on top of the layer rendering a
        rebuild already pays. The resolved view re-resolves the same cells
        rather than falling back to a bake, because changing one cell of one
        layer can only change that cell's answer.

        `cells` are PAINT cells -- what the stroke wrote -- and the overlay is
        indexed in overlay cells, so each one expands by `__overlay_scale`.
        """
        overlay = self.__overlay
        if overlay is None or self.collision_first_gid is None:
            return
        scale = self.__overlay_scale()
        if self.all_layers:
            stack = self.collision_stack(self.overlay_subcell())
            for x, y in cells:
                for offset_y in range(scale):
                    for offset_x in range(scale):
                        cx, cy = x * scale + offset_x, y * scale + offset_y
                        # `resolve_cell`, which is what a full bake calls per
                        # cell too. Spelling the four channels here a second
                        # time is how a stroke comes to draw one thing and the
                        # next bake another, in the same cells of the same
                        # document -- and the level channel is exactly the
                        # kind of addition that would have been made in one
                        # of the two places.
                        mask, owner, conflicted, level = resolve_cell(
                            stack, cx, cy, undecided=NO_DATA)
                        overlay.set_cell(cx, cy, mask, owner=owner,
                                         conflicted=conflicted, level=level)
            return
        companion = self.companion_layer()
        if companion is None:
            return
        first_gid = self.collision_first_gid
        for x, y in cells:
            overlay.set_cell(
                x, y, gid_to_opinion(companion.get_tile(x, y), first_gid))

    # -- ghost preview -----------------------------------------------------

    def __clear_ghost(self) -> None:
        if self.__ghost is not None:
            self.scene().removeItem(self.__ghost)
            self.__ghost = None

    def __draw_ghost(self) -> None:
        self.__clear_ghost()
        if self.__stroke is None:
            return
        if self.mode is EditMode.COLLISION:
            self.__draw_mask_ghost()
            return
        if self.atlas is None:
            return
        group = QGraphicsItemGroup()
        group.setZValue(_GHOST_Z)
        group.setOpacity(0.55)
        for x, y, gid in self.__stroke.preview():
            px, py = x * self.tile_width, y * self.tile_height
            if gid <= 0:
                marker = QGraphicsRectItem(px, py, self.tile_width, self.tile_height)
                marker.setPen(QPen(QColor(255, 120, 120), 0))
                marker.setBrush(QBrush(QColor(255, 60, 60, 90)))
                group.addToGroup(marker)
                continue
            tile = self.atlas.pixmap(gid)
            if tile is not None:
                item = QGraphicsPixmapItem(tile)
                item.setPos(px, py)
                item.setTransformationMode(Qt.FastTransformation)
                group.addToGroup(item)
        self.scene().addItem(group)
        self.__ghost = group

    def __draw_mask_ghost(self) -> None:
        """The pending stroke in the overlay's own vocabulary.

        A tile ghost cannot say this: what is being placed is a mask, and its
        art is the glyph rather than anything in a tileset. The plate under
        each glyph is what makes "open" and "clear" aimable -- both of those
        draw no glyph at all, and a brush you cannot see is a brush you
        cannot place.
        """
        first_gid = self.collision_first_gid
        if first_gid is None:
            return
        # A mask ghost is drawn in PAINT cells, not in tiles: what is being
        # placed is an opinion about one addressable cell, and its art is
        # the glyph rather than anything in a tileset.
        glyphs = glyph_pixmaps(self.paint_width, self.paint_height)
        group = QGraphicsItemGroup()
        group.setZValue(_GHOST_Z)
        group.setOpacity(0.75)
        for x, y, gid in self.__stroke.preview():
            px, py = x * self.paint_width, y * self.paint_height
            plate = QGraphicsRectItem(px, py, self.paint_width, self.paint_height)
            plate.setPen(QPen(_MASK_GHOST_PEN, 0))
            plate.setBrush(QBrush(_MASK_GHOST_FILL))
            group.addToGroup(plate)
            glyph = glyphs.get(gid_to_opinion(gid, first_gid))
            if glyph is not None:
                item = QGraphicsPixmapItem(glyph)
                item.setPos(px, py)
                item.setTransformationMode(Qt.FastTransformation)
                group.addToGroup(item)
        self.scene().addItem(group)
        self.__ghost = group

    # -- input -------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space:
            self.__space = True
            self.setCursor(Qt.OpenHandCursor)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key_Space:
            self.__space = False
            self.unsetCursor()
        super().keyReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        """Plain wheel zooms.

        Tiled scrolls on a plain wheel and zooms on ctrl+wheel. In a tile
        editor you zoom constantly and scroll almost never -- panning is
        middle-drag -- so the modifier is on the wrong action. Shift+wheel
        still scrolls for anyone who wants it.
        """
        if event.modifiers() & Qt.ShiftModifier:
            super().wheelEvent(event)
            return
        steps = event.angleDelta().y()
        if not steps:
            super().wheelEvent(event)
            return
        factor = 1.15 if steps > 0 else 1 / 1.15
        # Keep zoom inside a range where the scene is still addressable; at
        # 0.02x a 1600px map is 32px and every click lands on the same tile.
        current = self.transform().m11()
        target = current * factor
        if not (0.05 <= target <= 20.0):
            event.accept()
            return
        self.scale(factor, factor)
        self.status.emit(f"zoom {target * 100:.0f}%")
        event.accept()

    def mousePressEvent(self, event) -> None:
        point = self.mapToScene(event.position().toPoint())
        column, row = self.cell_at(point.x(), point.y())

        if event.button() == Qt.MiddleButton or self.__space:
            self.__panning = True
            self.__pan_from = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if event.modifiers() & Qt.AltModifier and event.button() == Qt.LeftButton:
            if self.mode is EditMode.COLLISION:
                self.__pick_mask(column, row)
            else:
                self.__pick(column, row)
            event.accept()
            return

        if self.mode is EditMode.COLLISION:
            if event.button() in (Qt.LeftButton, Qt.RightButton):
                self.__begin_collision(
                    column, row, erase=event.button() == Qt.RightButton)
                event.accept()
                return
            super().mousePressEvent(event)
            return

        layer = self.__active_tile_layer()
        if layer is not None and event.button() in (Qt.LeftButton, Qt.RightButton):
            if self.tool is Tool.PICKER:
                self.__pick(column, row)
                event.accept()
                return
            if self.tool is Tool.AUTOTILE:
                self.__begin_terrain(layer, column, row,
                                     erase=event.button() == Qt.RightButton)
                event.accept()
                return
            self.__erasing = event.button() == Qt.RightButton
            stamp, anchor = self.__footprint()
            self.__stroke = Stroke(
                Tool.ERASER if self.__erasing else self.tool,
                stamp, Bounds(layer.width, layer.height), layer.get_tile,
                anchor=anchor)
            self.__stroke.begin(column, row)
            self.__draw_ghost()
            event.accept()
            return

        if event.button() == Qt.LeftButton:
            self.__click_object(point, column, row)
            event.accept()
            return
        if event.button() == Qt.RightButton:
            self.__delete_object_under(point)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        position = event.position().toPoint()
        point = self.mapToScene(position)
        column, row = self.cell_at(point.x(), point.y())

        if self.__panning and self.__pan_from is not None:
            delta = position - self.__pan_from
            self.__pan_from = position
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y())
            event.accept()
            return

        if self.__terrain is not None:
            self.__terrain.extend(column, row)
            self.__draw_terrain_ghost()
            self.status.emit(f"cell ({column}, {row})   "
                             f"{len(self.__terrain.pending)} tiles")
            event.accept()
            return

        if self.__stroke is not None:
            self.__stroke.extend(column, row)
            self.__draw_ghost()
            unit = "cells" if self.mode is EditMode.COLLISION else "tiles"
            self.status.emit(f"cell ({column}, {row})   "
                             f"{len(self.__stroke.edits())} {unit}")
            event.accept()
            return

        if self.mode is EditMode.COLLISION and self.__overlay is not None:
            # A RESOLVED VIEW THE MAP CANNOT SUPPORT DESCRIBES NOTHING. When
            # `field_subcell` refuses this map the overlay is drawn at 1x --
            # deliberately, so a broken map stays editable -- and describing
            # a cell of it would be the readout stating the answer the player
            # will feel, from a map that raises before the player gets one.
            # Said here, on every move, because this line is the only status
            # nothing else overwrites.
            refusal = self.stack_refusal() if self.all_layers else None
            if refusal is not None:
                self.status.emit(f"cell ({column}, {row})   All layers cannot "
                                 f"be trusted here: {refusal}")
                super().mouseMoveEvent(event)
                return
            # What the overlay is already showing, said in words -- including
            # which layer decided and whether one below it disagrees, neither
            # of which survives being reduced to a colour. Read at the
            # OVERLAY's cell, which is the brush's cell on every unmixed map
            # and finer than it under the all-layers view.
            self.status.emit(
                f"cell ({column}, {row})   "
                f"{self.__overlay.describe(*self.overlay_cell_at(point.x(), point.y()))}")
            super().mouseMoveEvent(event)
            return

        self.status.emit(f"cell ({column}, {row})   "
                         f"px ({point.x():.0f}, {point.y():.0f})")
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.__panning:
            self.__panning = False
            self.__pan_from = None
            self.setCursor(Qt.OpenHandCursor if self.__space else Qt.ArrowCursor)
            self.unsetCursor()
            event.accept()
            return

        if self.__terrain is not None:
            self.__commit_terrain()
            event.accept()
            return

        if self.__stroke is not None:
            if self.mode is EditMode.COLLISION:
                self.__commit_collision()
            else:
                self.__commit_stroke()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def __commit_stroke(self) -> None:
        stroke, self.__stroke = self.__stroke, None
        self.__clear_ghost()
        if stroke is None:
            return
        edits = stroke.edits()
        if not edits:
            self.status.emit("nothing changed")
            return
        scope = Scope.of(("map", self.map_name), ("layer", self.active_layer))
        verb = "map.tile.set_many"
        self.window().run(
            Command(verb, scope, {"tiles": edits_to_triples(edits)}),
            label=f"{stroke.tool.label} ({len(edits)} tiles)")

    # -- collision ---------------------------------------------------------

    def __begin_collision(self, column: int, row: int, *, erase: bool) -> None:
        """Start a stroke against the active layer's companion.

        The same `Stroke` the tile tools use, over the same kind of layer,
        writing the same kind of value -- `first_gid + mask` is a gid. What
        changes is only where it reads and what it stamps.

        THE ORDER OF THE GATES IS THE POINT. The LOCAL refusals -- no
        layer, wrong tool, nothing to pick -- run first, because nothing
        should be provisioned for a gesture that was going to be refused
        anyway. Before this they ran last, so clicking with no layer
        selected raised the tileset dialog, and the "select a tile layer"
        message five lines below it was unreachable until the tileset
        existed.

        Then the mask tileset. When the map has none the sheet is written
        if it is absent and the DECLARATION is queued for the commit, so
        the gesture that asked is the gesture that paints; when the map has
        one, it is checked that it can actually hold every mask, which is
        the half of that invariant that did not exist -- `sufficient`
        guarded only the add path, so a map already declaring a five-tile
        `collision` tileset painted gids past the end of its own sheet with
        no warning from anywhere.
        """
        if self.__active_tile_layer() is None:
            self.status.emit("select a tile layer to give collision to")
            return
        # THE GUARD, above the picker on purpose: a resolution the canvas and
        # the file disagree about makes a PICK read the wrong cell just as
        # surely as it makes a stroke write one, and neither is worth
        # provisioning a tileset for. Cheap and local like the refusal above
        # it -- it reads the document and writes nothing.
        misplaced = self.collision_stroke_refusal()
        if misplaced is not None:
            self.status.emit(misplaced)
            return
        if self.tool is Tool.PICKER:
            self.__pick_mask(column, row)
            return
        if not self.mode.allows(self.tool):
            self.status.emit(f"{self.tool.label} has no meaning in collision "
                             f"mode — there is no mask sheet to index")
            return

        self.__pending_tileset = None
        self.__wrote_sheet = False
        first_gid = self.collision_first_gid
        if first_gid is None:
            if erase:
                # Erasing writes gid 0, which needs no tileset, and there
                # is nothing here to erase. Declaring a gid range to
                # service a right-drag over an empty map would be the old
                # modal's mistake with the question taken out.
                self.status.emit("no collision on this map yet — "
                                 "nothing to erase")
                return
            try:
                # A pure query -- measured: the document is byte-identical
                # afterwards -- and it is the SAME function `add_tileset`
                # will use at release, so the gid this stroke stamps is by
                # construction the gid the tileset ends up claiming. It
                # raises when a tileset's extent lives in a .tsx this
                # document cannot see, which makes a collision-free
                # firstgid unknowable; refusing at press is the answer
                # `map.tileset.add` would give at release, arrived at
                # before the author drags forty cells.
                first_gid = self.document.next_tileset_firstgid()
            except PyoneerError as exc:
                self.status.emit(str(exc))
                return
            offer = self.provision_collision_tileset()
            if offer is None:
                return                      # it said why; changed nothing
            self.__pending_tileset = offer
        else:
            declared = self.collision_tileset_ref()
            if declared is not None and declared.tile_count < len(MASK_DOMAIN):
                self.status.emit(
                    f"this map's {declared.name!r} tileset declares "
                    f"{declared.tile_count} tiles (gids {declared.first_gid}–"
                    f"{declared.last_gid}) — too few to hold "
                    f"{len(MASK_DOMAIN)} masks, so a mask would be written as "
                    f"a gid it does not own. Re-add it at "
                    f"{len(MASK_DOMAIN)} tiles before painting collision")
                return

        companion = self.companion_layer()
        document = self.document
        # Before the companion exists there is nothing to read, and every
        # cell of it is empty -- which is exactly what a reader that answers 0
        # says.
        #
        # THE BOUNDS ARE THE LAYER'S, NOT THE MAP'S. When the companion is
        # there, they are literally its own width and height, which is how a
        # companion finer than the map -- or smaller than it, which was
        # always legal -- gets clipped to what actually exists. When it is
        # not, the commit creates it at the map's size in PAINT cells, so
        # that is what the stroke may write into; spelled through the paint
        # unit rather than as `document.width` against the day
        # `map.layer.add` would learn to create a finer one. That day is
        # here -- the commit passes this same number as `subcell` -- so this
        # line is now load-bearing rather than anticipatory.
        subcell = self.paint_subcell
        read = companion.get_tile if companion is not None else _EMPTY_READER
        bounds = (Bounds(companion.width, companion.height)
                  if companion is not None
                  else Bounds(document.width * subcell,
                              document.height * subcell))
        stamp, anchor = self.__footprint(
            Stamp.single(opinion_to_gid(self.mask, first_gid)))
        self.__stroke = Stroke(
            Tool.ERASER if erase else self.tool,
            stamp, bounds, read, anchor=anchor)
        self.__stroke.begin(column, row)
        self.__draw_ghost()

    def __commit_collision(self) -> None:
        """One stroke, one transaction -- tileset and companion layer included.

        Up to four commands land in front of the tiles: declare the mask
        TILESET if this map had none, then create the companion LAYER, tell
        the art layer which layer holds its masks, and mark the companion as
        data rather than art. They land together or not at all, and one undo
        takes all five back out in reverse, each from its own recorded
        inverse.

        `map.tileset.add`'s inverse is `map.tileset.remove(force=False)`,
        and that guard is correct here rather than in spite of being here:
        the tiles pointing into the new range are zeroed EARLIER in the same
        unwind, which is the one situation `force` documents. So undo takes
        the declaration back out and leaves the PNG, which is exactly what
        the deleted dialog's own worry asked for.

        The undo entry reads as the stroke -- "Brush collision (3 cells)" --
        not as the plumbing. The tileset and the layer are implementation of
        that stroke, not separate acts the author performed, and
        `Transaction.summary_lines()` already exposes all five commands to
        anyone who wants them. A provisioning step that costs its own
        history entry is the modal's problem in a quieter voice.
        """
        stroke, self.__stroke = self.__stroke, None
        # Consumed, not merely read. `__begin_collision` also clears these at
        # the top of every press, so measured, either one alone is enough --
        # removing BOTH makes the next stroke on the next layer carry a
        # `map.tileset.add` it never asked for, which is what the check
        # asserts. This half stays because leaving a spent offer on the
        # instance is a loaded gun for whoever adds the next early return.
        pending, self.__pending_tileset = self.__pending_tileset, None
        wrote, self.__wrote_sheet = self.__wrote_sheet, False
        self.__clear_ghost()
        if stroke is None:
            return
        edits = stroke.edits()
        if not edits:
            self.status.emit("nothing changed")
            return

        name = self.companion_name()
        if name is None:
            return
        map_scope = Scope.of(("map", self.map_name))
        companion_scope = map_scope.child("layer", name)
        commands: list[Command] = []
        if pending is not None:
            commands.append(Command("map.tileset.add", map_scope,
                                    pending.command_args()))
        if self.companion_layer() is None:
            commands.append(Command("map.layer.add", map_scope,
                                    self.__companion_add_args(name)))
            commands.append(Command(
                "map.layer.set", map_scope.child("layer", self.active_layer),
                {"key": "passability", "value": name}))
            commands.append(Command("map.layer.set", companion_scope,
                                    {"key": "renders", "value": False}))
        commands.append(Command("map.tile.set_many", companion_scope,
                                {"tiles": edits_to_triples(edits)}))

        # The window refreshes -- and so rebuilds this canvas -- inside run(),
        # so the flag has to be up for the whole call: it is how the stream
        # listener tells our own write apart from everybody else's.
        self.__own_commit = True
        try:
            applied = self.window().run(
                commands, label=f"{stroke.tool.label} collision "
                                f"({len(edits)} cells)")
        finally:
            self.__own_commit = False
        if not applied:
            return
        self.__sync_overlay([(x, y) for x, y, _gid in edits])
        if pending is not None:
            # ONE line, after run() has written its own to the same status
            # bar, so this is what the author is left looking at. The whole
            # disclosure the 191-word dialog was carrying, said as something
            # that happened rather than as a threat about what will not.
            written = (f" — wrote {pending.absolute}" if wrote else "")
            self.status.emit(
                f"{stroke.tool.label} collision ({len(edits)} cells): added "
                f"the {pending.name!r} tileset, {pending.tile_count} masks"
                f"{written}")

    def __companion_add_args(self, name: str) -> dict:
        """The `map.layer.add` that creates a companion for this stroke.

        THE RESOLUTION COMES FROM THE FUNNEL, not from `collision_subcell`
        directly. `paint_unit` is what decided which cell the click landed
        in; passing anything else here would create a layer whose cells are
        not the cells this stroke just addressed, which is the 1,200px bug
        rebuilt from the other end. Reading the preference twice would be
        two places for one number to be wrong.

        `subcell` is OMITTED at 1 rather than passed as 1. The verb accepts
        1 and writes `pyoneer_subcell="1"` for it, which is the format's
        documented default said out loud -- and no companion this editor has
        ever created carries that property. A default that rewrites what
        existing maps get is not a default, so the 1x file stays the file it
        has always been and the author opts in to anything else.

        Until this argument existed, every companion the editor made for
        itself was 1x: `map.layer.add subcell=N` was reachable only through
        the AI response path, there is no verb to re-scale a companion
        afterwards, and `map.layer.set` deliberately refuses to write
        `pyoneer_subcell` -- so "paint collision, then decide you want 4x"
        was a dead end that raises at load.
        """
        args: dict = {"name": name, "kind": "tile"}
        subcell = self.paint_subcell
        if subcell > 1:
            args["subcell"] = subcell
        return args

    def __pick_mask(self, column: int, row: int) -> None:
        """Alt+click, or the picker tool, in collision mode."""
        first_gid = self.collision_first_gid
        companion = self.companion_layer()
        if first_gid is None or companion is None or not (
                0 <= column < companion.width and 0 <= row < companion.height):
            self.status.emit("no mask here to pick")
            return
        mask = gid_to_opinion(companion.get_tile(column, row), first_gid)
        if mask == NO_DATA:
            self.status.emit("no mask here to pick")
            return
        self.mask = mask
        self.picked_mask.emit(mask)
        self.status.emit(f"picked {describe_mask(mask)}")

    # -- terrain -----------------------------------------------------------

    def __terrain_for_brush(self):
        """The autotile group the currently-picked tile belongs to.

        Choosing a terrain is therefore "click any tile of it in the
        palette", rather than picking one of 32 origin gids out of a list.
        """
        if self.atlas is None:
            return None
        gid = self.stamp.primary
        entry = self.atlas.entry_for(gid)
        if entry is None or gid <= 0:
            return None
        try:
            origin = autotile.origin_for_gid(gid, entry.first_gid, entry.columns)
        except ValueError:
            return None
        return autotile.TerrainSet(origin=origin, columns=entry.columns,
                                   name=entry.name)

    def __begin_terrain(self, layer, column: int, row: int, *,
                        erase: bool) -> None:
        terrain = self.__terrain_for_brush()
        if terrain is None:
            self.status.emit("pick a tile from an autotile sheet first")
            return
        self.__terrain = _TerrainStroke(
            layer, terrain, erase=erase,
            size=self.brush_size if self.tool.uses_size else 1)
        self.__terrain.extend(column, row)
        self.__draw_terrain_ghost()

    def __draw_terrain_ghost(self) -> None:
        self.__clear_ghost()
        if self.__terrain is None or self.atlas is None:
            return
        group = QGraphicsItemGroup()
        group.setZValue(_GHOST_Z)
        group.setOpacity(0.6)
        for (x, y), gid in self.__terrain.pending.items():
            tile = self.atlas.pixmap(gid)
            if tile is None:
                continue
            item = QGraphicsPixmapItem(tile)
            item.setPos(x * self.tile_width, y * self.tile_height)
            item.setTransformationMode(Qt.FastTransformation)
            group.addToGroup(item)
        self.scene().addItem(group)
        self.__ghost = group

    def __commit_terrain(self) -> None:
        stroke, self.__terrain = self.__terrain, None
        self.__clear_ghost()
        if stroke is None:
            return
        edits = stroke.edits()
        if not edits:
            self.status.emit("nothing changed")
            return
        scope = Scope.of(("map", self.map_name), ("layer", self.active_layer))
        self.window().run(
            Command("map.tile.set_many", scope,
                    {"tiles": edits_to_triples(edits)}),
            label=f"Terrain ({len(edits)} tiles)")

    # -- picking and objects -----------------------------------------------

    def __pick(self, column: int, row: int) -> None:
        layer = self.__active_tile_layer()
        if layer is None or not (0 <= column < layer.width
                                 and 0 <= row < layer.height):
            # Its counterpart `__pick_mask` has said this since it was
            # written; this half returned in silence, so an alt+click off
            # the map or with no layer selected looked like a dead editor.
            self.status.emit("no tile here to pick")
            return
        gid = layer.get_tile(column, row)
        self.stamp = Stamp.single(gid)
        self.picked_gid.emit(gid)
        self.status.emit(f"picked gid {gid}")

    def __object_under(self, point):
        document = self.document
        for name in reversed(document.object_layer_names()):
            if name in self.hidden_layers:
                continue
            for obj in reversed(document.object_layer(name).objects()):
                width = obj.width or self.tile_width
                height = obj.height or self.tile_height
                if (obj.x <= point.x() < obj.x + width
                        and obj.y <= point.y() < obj.y + height):
                    return name, obj
        return None, None

    def __click_object(self, point, column: int, row: int) -> None:
        layer_name, obj = self.__object_under(point)
        if obj is not None:
            self.selected.emit(Scope.of(("map", self.map_name),
                                        ("layer", layer_name),
                                        ("object", str(obj.id))))
            return
        document = self.document
        if self.active_layer in document.object_layer_names():
            scope = Scope.of(("map", self.map_name), ("layer", self.active_layer))
            self.window().run(Command("map.object.add", scope, {
                "type": self.object_class,
                "x": float(column * self.tile_width),
                "y": float(row * self.tile_height),
            }))
            # A genre default materialised onto the new object is otherwise
            # INVISIBLE: the property is on the object and the author is
            # looking at a rectangle. Say the list out loud once, here, or
            # filling in a pack is again a surface where nothing happens.
            placed = self.document.object_layer(self.active_layer).objects()
            tokens = (placed[-1].properties.as_dict().get(BEHAVIORS, "")
                      if placed else "")
            self.status.emit(f"placed {self.object_class}"
                             + (f" with {tokens}" if tokens else ""))
            return
        self.status.emit("select a layer to paint on, or an object to select")

    def __delete_object_under(self, point) -> None:
        layer_name, obj = self.__object_under(point)
        if obj is None:
            self.status.emit("no object under the cursor")
            return
        self.window().run(Command(
            "map.object.remove",
            Scope.of(("map", self.map_name), ("layer", layer_name),
                     ("object", str(obj.id)))))


class _TerrainStroke:
    """One press-drag-release of the terrain tool.

    Kept separate from `paint.Stroke` because the models genuinely differ:
    a stamp tool writes the cells the cursor covered, and terrain writes a
    corner lattice and then re-tiles every cell those corners touch --
    including cells the cursor never went near, which is how the seam
    against existing terrain updates.

    The corner field is recovered once, on press, and then carried through
    the drag. Rebuilding it per mouse move would rescan the whole layer.
    """

    def __init__(self, layer, terrain: autotile.TerrainSet, *,
                 erase: bool = False, size: int = 1):
        if size < 1:
            raise ValueError(f"a terrain footprint must be at least 1 cell, "
                             f"got {size}")
        self.layer = layer
        self.terrain = terrain
        self.erase = erase
        #: A footprint in CELLS, the same number the brush uses. Terrain
        #: has no stamp -- `Tool.uses_stamp` is False for it -- but it does
        #: have a size, which is why `Tool.uses_size` had to be its own
        #: property rather than the negation of that one.
        self.size = size
        self.bounds = autotile.Bounds(layer.width, layer.height)
        self.pending: dict[tuple[int, int], int] = {}
        self.__last: tuple[int, int] | None = None
        self.field = autotile.corner_field(self.read, self.bounds, terrain)

    def read(self, x: int, y: int) -> int:
        """Uncommitted edits win, so a drag builds on its own work."""
        if (x, y) in self.pending:
            return self.pending[(x, y)]
        return self.layer.get_tile(x, y)

    def extend(self, column: int, row: int) -> None:
        if (column, row) == self.__last:
            return
        self.__last = (column, row)
        # A size-N terrain brush is the UNION of the per-cell corner sets
        # over an NxN block, centred the same way a tile brush is. At size
        # 1 that is one call to `corners_for_cell_brush` with the cell the
        # cursor is on -- byte for byte the previous behaviour, which is
        # why the default is safe.
        half = (self.size - 1) // 2
        corners: set[autotile.Corner] = set()
        for down in range(self.size):
            for across in range(self.size):
                corners.update(autotile.corners_for_cell_brush(
                    column - half + across, row - half + down))
        edits, self.field = autotile.paint(
            self.read, self.bounds, self.terrain, corners,
            erase=self.erase, field=self.field)
        for x, y, gid in edits:
            self.pending[(x, y)] = gid

    def edits(self) -> list[tuple[int, int, int]]:
        return [(x, y, gid) for (x, y), gid in sorted(self.pending.items())
                if self.layer.get_tile(x, y) != gid]


# --------------------------------------------------------------------------
# The tile palette
# --------------------------------------------------------------------------

class TilePalette(QWidget):
    """Pick a tile, or drag out a rectangle to pick a multi-tile stamp.

    One tileset at a time, laid out with that tileset's OWN column count.
    The first version flattened every gid into a fixed 32-wide grid, which
    happened to match this map's tilesets and would have silently produced
    nonsense stamps for any tileset with different geometry.
    """

    stamp_picked = Signal(object)      # a Stamp

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.atlas: TilesetAtlas | None = None
        self.entry = None
        self.cell = 16
        #: gid -> the mask its TILESET bakes in, from `MapCanvas.tile_masks`.
        #: Drawn over the sheet so an author can SEE which tiles are already
        #: baked. Without it the feature is invisible until you walk into a
        #: wall: level one is stored in a file beside the .tmx, nothing in
        #: the map names it per tile, and the only other readout is the
        #: All-layers overlay, which answers about map cells rather than
        #: about the tile you are holding.
        self.masks: dict[int, int] = {}
        self.__anchor: tuple[int, int] | None = None
        self.__current: tuple[int, int] | None = None

        self.chooser = QComboBox()
        self.chooser.currentIndexChanged.connect(self.__on_choose)

        self.surface = _PaletteSurface(self)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.surface)
        self.scroll.setWidgetResizable(False)

        self.caption = QLabel("")
        self.caption.setStyleSheet("color: palette(mid); font-size: 11px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        layout.addWidget(self.chooser)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.caption)

    # -- data --------------------------------------------------------------

    def set_atlas(self, atlas: TilesetAtlas) -> None:
        remembered = self.chooser.currentIndex()
        self.atlas = atlas
        self.chooser.blockSignals(True)
        self.chooser.clear()
        for entry in atlas.entries:
            missing = "" if entry.image is not None else "   (no art)"
            self.chooser.addItem(f"{entry.name}   {entry.tile_count} tiles{missing}")
        self.chooser.setCurrentIndex(max(0, min(remembered,
                                                self.chooser.count() - 1)))
        self.chooser.blockSignals(False)
        self.__on_choose(self.chooser.currentIndex())

    def set_masks(self, masks: dict[int, int]) -> None:
        """Which gids their own tileset already masks. See `masks`.

        DOES NOT REBUILD, and that is the whole point of where it sits. Its
        one caller is `EditorWindow.refresh_all`, which calls `set_atlas` on
        the very NEXT line -- and `set_atlas` rebuilds the sheet
        unconditionally, through `__on_choose`. So this method setting the
        masks and leaving the repaint to its neighbour is what actually makes
        the ordering comment there true: the sheet is drawn ONCE, with its
        badges already on.

        An earlier version rebuilt here behind a `masks == self.masks` memo,
        justified as saving a repaint on every click of a drag. Measured, it
        saved nothing: one unrelated tile edit rebuilt the sheet once, five
        rebuilt it five times, because the unconditional rebuild on the next
        line was paying regardless. Both halves of that memo were also
        unasserted -- deleting the rebuild and deleting the comparison each
        left the suite green. A guard that cannot be observed is not a guard.

        If a second caller ever uses this alone, it must rebuild itself; that
        is cheaper than a memo nobody can see working.
        """
        self.masks = dict(masks)

    def __on_choose(self, index: int) -> None:
        if self.atlas is None or not (0 <= index < len(self.atlas.entries)):
            return
        self.entry = self.atlas.entries[index]
        self.cell = max(self.entry.tile_width, 8)
        self.__anchor = self.__current = None
        self.surface.rebuild()

    @property
    def columns(self) -> int:
        return self.entry.columns if self.entry else 1

    @property
    def rows(self) -> int:
        if not self.entry:
            return 0
        return max(1, (self.entry.tile_count + self.columns - 1) // self.columns)

    def gid_at(self, column: int, row: int) -> int | None:
        if self.entry is None:
            return None
        index = row * self.columns + column
        if not (0 <= column < self.columns and 0 <= index < self.entry.tile_count):
            return None
        return self.entry.first_gid + index

    # -- selection ---------------------------------------------------------

    def begin(self, column: int, row: int) -> None:
        self.__anchor = self.__current = (column, row)
        self.surface.update()

    def extend(self, column: int, row: int) -> None:
        if self.__anchor is None:
            return
        self.__current = (column, row)
        self.surface.update()

    def commit(self) -> None:
        if self.__anchor is None or self.__current is None:
            return
        left, right = sorted((self.__anchor[0], self.__current[0]))
        top, bottom = sorted((self.__anchor[1], self.__current[1]))
        rows: list[list[int]] = []
        for row in range(top, bottom + 1):
            line: list[int] = []
            for column in range(left, right + 1):
                gid = self.gid_at(column, row)
                # -1 means "leave this cell alone" -- a ragged selection at
                # the end of a tileset stays a rectangle with holes rather
                # than silently shrinking.
                line.append(gid if gid is not None else -1)
            rows.append(line)
        if not rows or not rows[0]:
            return
        stamp = Stamp.from_rows(rows)
        self.stamp_picked.emit(stamp)
        # CAPTIONED AFTER THE EMIT, deliberately. In collision mode that
        # signal is what writes the mask, and `refresh_all` hands this widget
        # the new mapping on its way back -- so captioning first would show
        # the author the mask their own click had just replaced.
        self.caption.setText(self.describe(stamp))

    def describe(self, stamp: Stamp) -> str:
        """The caption for a pick: what it is, and what it already carries."""
        head = (f"gid {stamp.primary}" if stamp.is_single
                else f"{stamp.width}×{stamp.height} stamp from gid "
                     f"{stamp.primary}")
        mask = self.masks.get(stamp.primary)
        return head if mask is None else f"{head}  ·  {describe_mask(mask)}"

    def selection_rect(self) -> tuple[int, int, int, int] | None:
        if self.__anchor is None or self.__current is None:
            return None
        left, right = sorted((self.__anchor[0], self.__current[0]))
        top, bottom = sorted((self.__anchor[1], self.__current[1]))
        return left, top, right - left + 1, bottom - top + 1

    def select_gid(self, gid: int) -> None:
        """Move the highlight to a gid chosen elsewhere (the canvas picker)."""
        if self.atlas is None:
            return
        for index, entry in enumerate(self.atlas.entries):
            if entry.first_gid <= gid < entry.first_gid + max(1, entry.tile_count):
                if self.chooser.currentIndex() != index:
                    self.chooser.setCurrentIndex(index)
                offset = gid - entry.first_gid
                self.__anchor = self.__current = (offset % entry.columns,
                                                  offset // entry.columns)
                self.caption.setText(self.describe(Stamp.single(gid)))
                self.surface.update()
                return


class _PaletteSurface(QWidget):
    """The drawn grid. Split out so the palette can own scrolling."""

    def __init__(self, palette: TilePalette):
        super().__init__()
        self.palette = palette
        self.__pixmap: QPixmap | None = None
        self.setMouseTracking(True)

    def rebuild(self) -> None:
        entry = self.palette.entry
        if entry is None:
            self.__pixmap = None
            self.resize(1, 1)
            self.update()
            return
        cell = self.palette.cell
        pixmap = QPixmap(self.palette.columns * cell, self.palette.rows * cell)
        pixmap.fill(QColor(20, 20, 24))
        painter = QPainter(pixmap)
        masks = self.palette.masks
        # The overlay's OWN glyphs, at this palette's cell size. A second
        # drawing of "blocks left and right" is a second thing to keep in
        # step with the mask palette and the readout, and the author would
        # meet the drift as two pictures of one mask.
        glyphs = glyph_pixmaps(cell, cell) if masks else {}
        for index in range(entry.tile_count):
            gid = entry.first_gid + index
            x = (index % self.palette.columns) * cell
            y = (index // self.palette.columns) * cell
            tile = self.palette.atlas.pixmap(gid)
            if tile is not None:
                painter.drawPixmap(x, y, tile)
            else:
                painter.fillRect(x, y, cell, cell, gid_colour(gid))
            mask = masks.get(gid)
            if mask is None:
                continue
            glyph = glyphs.get(mask)
            if glyph is not None:
                painter.drawPixmap(x, y, glyph)
            # And the frame, whatever the glyph drew -- see `_BAKED_PEN`.
            painter.setPen(QPen(_BAKED_PEN, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(x, y, cell - 1, cell - 1)
        painter.end()
        self.__pixmap = pixmap
        self.resize(pixmap.size())
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        if self.__pixmap is not None:
            painter.drawPixmap(0, 0, self.__pixmap)
        rect = self.palette.selection_rect()
        if rect is not None:
            cell = self.palette.cell
            x, y, width, height = rect
            painter.setPen(QPen(QColor(120, 200, 255), 2))
            painter.setBrush(QBrush(QColor(120, 200, 255, 50)))
            painter.drawRect(x * cell, y * cell, width * cell, height * cell)
        painter.end()

    def __cell(self, position) -> tuple[int, int]:
        cell = self.palette.cell
        return int(position.x()) // cell, int(position.y()) // cell

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        self.palette.begin(*self.__cell(event.position()))

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self.palette.extend(*self.__cell(event.position()))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.palette.commit()
