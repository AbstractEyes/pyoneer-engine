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
    companion_name as engine_companion_name,
    depth_for_layer_name,
)
from scripts.loaders.map_document import tileset_geometry

from editor.core import autotile
from editor.core.collision import (
    NO_DATA,
    CollisionLayer,
    gid_to_opinion,
    opinion_to_gid,
    resolve,
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
)
from editor.core.scope import Scope
from editor.ui.collision_view import (
    MASK_DOMAIN,
    CollisionOverlay,
    glyph_pixmaps,
    layer_from_companion,
    masks_from_layer,
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

    def cell_at(self, scene_x: float, scene_y: float) -> tuple[int, int]:
        # Floor division, not int(): int(-0.5) is 0, which puts the cell one
        # to the right of where the cursor actually is on the left edge.
        return (int(scene_x // self.tile_width), int(scene_y // self.tile_height))

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

    def collision_stack(self) -> list[CollisionLayer]:
        """Every layer that declares a companion, TOPMOST FIRST.

        Topmost first is `collision.resolve`'s contract and the reverse of a
        tmx layer list, so the sort is by draw depth and then reversed. The
        members are lazy readers over the live document, which is why this is
        cheap enough to rebuild whenever the stack is consulted rather than
        cached and invalidated.
        """
        first_gid = self.collision_first_gid
        if first_gid is None:
            return []
        document = self.document
        names = document.tile_layer_names()
        stack: list[CollisionLayer] = []
        for name in sorted(names, key=self.__depth_of):
            companion = self.companion_name(name)
            if companion and companion in names and companion != name:
                stack.append(layer_from_companion(
                    document.tile_layer(companion), first_gid, name=name))
        stack.reverse()
        return stack

    # -- building ----------------------------------------------------------

    def __depth_of(self, name: str) -> int:
        """How high a layer draws, and therefore where it sits in the
        collision stack.

        The genre pack first, because that is the editor's authored contract
        with the author, then the ENGINE's table for anything it does not
        declare. The fallback used to be a bare 500, which meant a layer the
        renderer ranks (`ENTITY_1`, `FOREGROUND_2`, `UI_LAYER_1` -- all in
        `scripts/core/depth.MAP_DEPTH`, none in any genre pack) sorted here at
        500 and there at 20, 90 or 100. `resolve` walks TOPMOST FIRST, so that
        is a different DECIDING layer for the same cell in the overlay than in
        the game. See UNRANKED_DEPTH in `scripts/core/collision_runtime.py`;
        `tools/check_collision_runtime.py` asserts the two tables agree
        wherever both rank a name.
        """
        declared = self.session.project.genre.layer(name)
        if declared is not None:
            return declared.depth
        return depth_for_layer_name(name)

    def rebuild(self) -> None:
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
        self.__mount_overlay(document)

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
        if not self.show_grid:
            return
        pen = QPen(_GRID_PEN)
        pen.setCosmetic(True)
        for column in range(document.width + 1):
            x = column * document.tile_width
            scene.addLine(x, 0, x, height, pen).setZValue(1000)
        for row in range(document.height + 1):
            y = row * document.tile_height
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
        """Resolve the whole stack instead of showing one layer's opinion."""
        if bool(on) == self.all_layers:
            return
        self.all_layers = bool(on)
        self.__collision_stale = True
        if self.mode is EditMode.COLLISION:
            self.__bake_overlay()

    def set_mask(self, mask: int) -> None:
        """The mask a collision stroke writes -- what `stamp` is to tiles."""
        self.mask = int(mask)

    def __detach_overlay(self) -> None:
        if self.__overlay is not None and self.__overlay.scene() is not None:
            self.__overlay.scene().removeItem(self.__overlay)

    def __mount_overlay(self, document) -> None:
        """Put the readout back into the freshly cleared scene.

        Built once per map GEOMETRY and re-added, never rebuilt: the item
        owns a scene-sized pixmap, and both making one and filling it are
        expensive enough that doing either on every command -- and a command
        is every click -- would be felt.
        """
        geometry = (document.width, document.height,
                    document.tile_width, document.tile_height)
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
        if action == "apply" and self.__own_commit:
            return          # our cells are written by __sync_overlay instead
        self.__collision_stale = True

    def __bake_overlay(self) -> None:
        """The whole field, from the document. The expensive path."""
        overlay = self.__overlay
        if overlay is None:
            return
        self.__collision_stale = False
        first_gid = self.collision_first_gid
        if first_gid is None:
            overlay.bake([])                  # pads with NO_DATA: draws nothing
            return
        if self.all_layers:
            overlay.bake_resolved(self.collision_stack())
            return
        companion = self.companion_layer()
        overlay.bake(masks_from_layer(companion, first_gid)
                     if companion is not None else [])

    def __sync_overlay(self, cells) -> None:
        """Repaint only the cells a stroke just changed.

        This is the reason the item is held rather than re-made: a cell is
        10.4 us and a full bake is 6 ms, on top of the layer rendering a
        rebuild already pays. The resolved view re-resolves the same cells
        rather than falling back to a bake, because changing one cell of one
        layer can only change that cell's answer.
        """
        overlay = self.__overlay
        if overlay is None or self.collision_first_gid is None:
            return
        if self.all_layers:
            stack = self.collision_stack()
            for x, y in cells:
                answer = resolve(stack, x, y, undecided=NO_DATA)
                overlay.set_cell(x, y, answer.mask, owner=answer.layer,
                                 conflicted=answer.conflicted)
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
        glyphs = glyph_pixmaps(self.tile_width, self.tile_height)
        group = QGraphicsItemGroup()
        group.setZValue(_GHOST_Z)
        group.setOpacity(0.75)
        for x, y, gid in self.__stroke.preview():
            px, py = x * self.tile_width, y * self.tile_height
            plate = QGraphicsRectItem(px, py, self.tile_width, self.tile_height)
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
            self.__stroke = Stroke(
                Tool.ERASER if self.__erasing else self.tool,
                self.stamp, Bounds(layer.width, layer.height), layer.get_tile)
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
            # What the overlay is already showing, said in words -- including
            # which layer decided and whether one below it disagrees, neither
            # of which survives being reduced to a colour.
            self.status.emit(f"cell ({column}, {row})   "
                             f"{self.__overlay.describe(column, row)}")
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
        # says. The layer itself is created by the commit, at the map's size,
        # which is why the bounds come from the map and not from the reader.
        read = companion.get_tile if companion is not None else _EMPTY_READER
        bounds = (Bounds(companion.width, companion.height) if companion
                  is not None else Bounds(document.width, document.height))
        self.__stroke = Stroke(
            Tool.ERASER if erase else self.tool,
            Stamp.single(opinion_to_gid(self.mask, first_gid)), bounds, read)
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
                                    {"name": name, "kind": "tile"}))
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
        self.__terrain = _TerrainStroke(layer, terrain, erase=erase)
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
                 erase: bool = False):
        self.layer = layer
        self.terrain = terrain
        self.erase = erase
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
        edits, self.field = autotile.paint(
            self.read, self.bounds, self.terrain,
            autotile.corners_for_cell_brush(column, row),
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
        self.caption.setText(
            f"gid {stamp.primary}" if stamp.is_single
            else f"{stamp.width}×{stamp.height} stamp from gid {stamp.primary}")
        self.stamp_picked.emit(stamp)

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
                self.caption.setText(f"gid {gid}")
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
        for index in range(entry.tile_count):
            gid = entry.first_gid + index
            x = (index % self.palette.columns) * cell
            y = (index // self.palette.columns) * cell
            tile = self.palette.atlas.pixmap(gid)
            if tile is not None:
                painter.drawPixmap(x, y, tile)
            else:
                painter.fillRect(x, y, cell, cell, gid_colour(gid))
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
