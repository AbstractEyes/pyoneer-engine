"""Seeing collision: the overlay, the glyphs, and the mode that swaps to them.

Collision in this editor is already expressed as ordinary tile gids in a
companion layer -- `editor/core/layers.py` does `mask_to_gid` /
`gid_to_mask` and the passability bits are RPG Maker's. So collision
authoring needs no new paint model and no new command; it needs a way to
SEE the masks, because a companion layer painted with art-less swatches is
seventeen indistinguishable coloured squares.

WHY ONE PIXMAP AND NOT N ITEMS
------------------------------
The obvious shape -- a `QGraphicsRectItem` per blocked cell -- was measured
and is the wrong one: 38-47 ms to build a 100x100 field, +2.9 ms on every
viewport paint forever, and 12.8 ms for `scene.clear()` to tear back down
on a canvas that clears on every single command. A `paint()` that re-issues
vector calls per exposed cell is worse still, +47 ms/frame.

This item owns ONE scene-sized `QPixmap` and blits `option.exposedRect` out
of it: 6.0 ms to bake, +0.9 ms marginal on a viewport paint, 10.4 us to
change one cell. The pixmap reference is handed to nobody -- that is the
whole trick. A plain `QGraphicsPixmapItem` ties on paint but shares its
pixmap implicitly, so every incremental edit pays a 10.24 MB detach
(6.5 ms) instead of writing four kilobytes in place. `cell_image()` exists
so callers can look without being handed the buffer.

WHY THE COLOURS ARE NOT THEMED
------------------------------
`icons.py` inks from `QPalette` because a toolbar glyph has to read against
the application chrome, which the user chooses. This overlay reads against
the MAP, which the user paints -- including saturated red rock. Instrumentation
that changes colour with the theme would be unlearnable, so the wash, the
bars and the star ring are fixed and were verified at a real 16px over five
backgrounds. The only palette-ish knob is the keyline, kept as a cache-keyed
parameter for anyone who needs it, exactly the way `icons.py` keys on ink.

WHY THE ALL-LAYERS VIEW RESOLVES INSTEAD OF STACKING
----------------------------------------------------
Drawing every collision layer's glyphs on top of each other was tried and
hides the thing you opened it for: an upper layer is mostly stars and empty
cells, and both of those are "abstain, ask below", so the stack paints
abstentions over the ground layer's real answers. `bake_resolved()` renders
the ONE mask the player will actually feel, plus two cheap channels the
stack cannot express -- a corner tick saying which layer decided, and a
centre square saying a layer below disagreed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QGraphicsItem, QLabel, QVBoxLayout, QWidget

# `editor/core/collision.py` owns the RULES: what a gid means, what counts as
# abstention, which layer decides and whether one below it disagrees. Nothing
# here re-implements any of that. A view that carried its own copy of the
# resolve would disagree with the runtime the first time either one changed,
# and it would disagree silently, in the one place whose entire job is to
# show you what the runtime thinks.
from editor.core.collision import (
    NO_DATA,
    CollisionLayer,
    companion_reader,
    describe_opinion,
    gid_to_opinion,
    resolve,
)
from editor.core.layers import (
    BLOCK_ALL,
    BLOCK_DOWN,
    BLOCK_LEFT,
    BLOCK_RIGHT,
    BLOCK_UP,
    PASS_ALL,
    STAR,
    describe_mask,
)
# `EditMode` was defined here and is now `editor/core/paint.py`'s, imported
# back so that `from editor.ui.collision_view import EditMode` keeps working.
# It moved because it gates the whole feature and describes what a drag means:
# leaving it in a Qt module meant the canvas could not read it without
# importing this view, and nothing did. `Tool` is re-exported for the same
# reason -- everything a mode constrains lives in one import.
from editor.core.paint import EditMode, Tool

#: The masks a companion layer can currently hold. `mask_to_gid` raises
#: outside 0..STAR, so there are seventeen, not thirty-two. The glyphs are
#: drawn so that widening this to 0x1F (STAR *combined* with directions)
#: needs no redesign: the ring owns the centre and the bars own the edges,
#: and they never overlap.
MASK_DOMAIN: tuple[int, ...] = tuple(range(STAR + 1))

_DIRECTION_BITS = (BLOCK_UP, BLOCK_DOWN, BLOCK_LEFT, BLOCK_RIGHT)


# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------

#: A translucent wash over any cell with a direction bit. This is the LOD
#: channel: zoomed out to fit a map, the bars merge into noise but the wash
#: still says "there is data here".
WASH = QColor(228, 40, 48, 52)
#: The blocked-edge bar. Opaque, because a translucent bar over dark art and
#: the same bar over bright art are two different colours.
BAR = QColor(255, 74, 74)
#: One device pixel on the bar's INWARD edge only. The outward edge sits on
#: the cell boundary, where the neighbour's bar or the grid already draws a
#: line; keylining both turns a solid wall into a corduroy smear.
KEYLINE = QColor(40, 0, 6, 190)
#: Star gets a different hue AND a round silhouette, so "abstain" can never
#: be misread as a direction.
STAR_INK = QColor(255, 206, 74)
STAR_OUTLINE = QColor(52, 32, 0, 200)
#: Resolve-only channels. Violet is nowhere else in this vocabulary.
CONFLICT = QColor(186, 96, 255)
#: Cycled by deciding-layer index, for the provenance tick.
PROVENANCE = (
    QColor(96, 224, 255), QColor(126, 226, 128), QColor(255, 226, 96),
    QColor(255, 158, 84), QColor(238, 118, 210), QColor(140, 156, 255),
)


# --------------------------------------------------------------------------
# Edit mode
# --------------------------------------------------------------------------

#: Free in `main_window._TOOL_SHORTCUTS`, checked before choosing it.
MODE_SHORTCUT = "C"


# --------------------------------------------------------------------------
# Glyphs
# --------------------------------------------------------------------------

_GLYPH_CACHE: dict[tuple[int, int, int], dict[int, QPixmap]] = {}
_ICON_CACHE: dict[tuple[str, int], QIcon] = {}


def glyph_pixmaps(tile_width: int, tile_height: int,
                  keyline: QColor | None = None) -> Mapping[int, QPixmap]:
    """Every mask in `MASK_DOMAIN`, drawn once and cached.

    Cached on (tile_width, tile_height, keyline) the way `icons.py` caches on
    (name, size, ink): the whole set costs 0.59 ms to bake, which is nothing
    once but is 10,000 times nothing if a bake draws each cell from scratch.

    The returned mapping is SHARED. Do not draw into these pixmaps.
    """
    ink = keyline if keyline is not None else KEYLINE
    key = (int(tile_width), int(tile_height), ink.rgba())
    cached = _GLYPH_CACHE.get(key)
    if cached is None:
        cached = {mask: _build_glyph(mask, int(tile_width), int(tile_height), ink)
                  for mask in MASK_DOMAIN}
        _GLYPH_CACHE[key] = cached
    return cached


def clear_cache() -> None:
    """Drop cached glyphs and icons, e.g. after a palette change."""
    _GLYPH_CACHE.clear()
    _ICON_CACHE.clear()


def _build_glyph(mask: int, tile_width: int, tile_height: int,
                 keyline: QColor) -> QPixmap:
    """One cell's instrumentation, cell-relative so it scales with zoom.

    Geometry is in sixteenths of a tile, because 16px is where this was
    designed and verified; `ux`/`uy` are kept separate so a non-square tile
    stretches the bars along their own edge instead of skewing them.
    """
    width = max(1, tile_width)
    height = max(1, tile_height)
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    if mask == PASS_ALL or mask == NO_DATA:
        # Open cells are more than half of a map. Absence is the cheapest
        # possible signal, and drawing nothing is also the fastest bake.
        return pixmap

    ux = width / 16.0
    uy = height / 16.0
    unit = min(ux, uy)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    if mask & BLOCK_ALL:
        painter.fillRect(QRectF(0, 0, width, height), WASH)

    thin = QPen(keyline)
    thin.setWidthF(max(1.0, unit))
    for bit in _DIRECTION_BITS:
        if not mask & bit:
            continue
        bar, inward = _bar_geometry(bit, width, height, ux, uy)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(BAR))
        painter.drawRect(bar)
        painter.setPen(thin)
        painter.drawLine(inward[0], inward[1])

    if mask & STAR:
        _draw_star(painter, width, height, unit)

    painter.end()
    return pixmap


def _bar_geometry(bit: int, width: float, height: float,
                  ux: float, uy: float) -> tuple[QRectF, tuple[QPointF, QPointF]]:
    """A blocked edge's bar, and the segment to keyline on its inward side.

    4u thick, 10u long, inset 3u from both corners. The corner gaps do two
    jobs: they let you count cells across a solid wall run, and they stop
    four bars collapsing into an undifferentiated ring on a fully blocked
    cell, which is the most common mask there is.
    """
    inset_x, inset_y = 3 * ux, 3 * uy
    thick_x, thick_y = 4 * ux, 4 * uy
    if bit == BLOCK_UP:
        rect = QRectF(inset_x, 0, width - 2 * inset_x, thick_y)
        edge = (QPointF(inset_x, thick_y), QPointF(width - inset_x, thick_y))
    elif bit == BLOCK_DOWN:
        rect = QRectF(inset_x, height - thick_y, width - 2 * inset_x, thick_y)
        edge = (QPointF(inset_x, height - thick_y),
                QPointF(width - inset_x, height - thick_y))
    elif bit == BLOCK_LEFT:
        rect = QRectF(0, inset_y, thick_x, height - 2 * inset_y)
        edge = (QPointF(thick_x, inset_y), QPointF(thick_x, height - inset_y))
    else:                                                     # BLOCK_RIGHT
        rect = QRectF(width - thick_x, inset_y, thick_x, height - 2 * inset_y)
        edge = (QPointF(width - thick_x, inset_y),
                QPointF(width - thick_x, height - inset_y))
    return rect, edge


def _draw_star(painter: QPainter, width: float, height: float,
               unit: float) -> None:
    """A centred amber annulus: outer d 8u, inner d 3.2u.

    Drawn as a stroked circle rather than two filled ellipses so the ring
    keeps its weight at any tile size, and outlined on both rims so it still
    reads over amber-ish art.
    """
    centre = QPointF(width / 2.0, height / 2.0)
    outer, inner = 8.0 * unit, 3.2 * unit
    painter.setBrush(Qt.NoBrush)
    ring = QPen(STAR_INK)
    ring.setWidthF((outer - inner) / 2.0)
    painter.setPen(ring)
    radius = (outer + inner) / 4.0
    painter.drawEllipse(centre, radius, radius)
    rim = QPen(STAR_OUTLINE)
    rim.setWidthF(max(1.0, unit))
    painter.setPen(rim)
    painter.drawEllipse(centre, outer / 2.0, outer / 2.0)
    painter.drawEllipse(centre, inner / 2.0, inner / 2.0)


def mode_icon(mode: EditMode, size: int = 22) -> QIcon:
    """Toolbar icon for a mode, cached like `icons.tool_icon`."""
    key = (mode.value, size)
    if key not in _ICON_CACHE:
        _ICON_CACHE[key] = _build_mode_icon(mode, size)
    return _ICON_CACHE[key]


def all_layers_icon(size: int = 22) -> QIcon:
    key = ("all_layers", size)
    if key not in _ICON_CACHE:
        _ICON_CACHE[key] = _build_all_layers_icon(size)
    return _ICON_CACHE[key]


def _build_mode_icon(mode: EditMode, size: int) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    u = size / 22.0
    if mode is EditMode.TILES:
        # Four tiles, one lighter, so it reads as "the map itself".
        for row in range(2):
            for column in range(2):
                shade = 168 if (row + column) % 2 else 118
                painter.fillRect(QRectF(3 * u + column * 8 * u,
                                        3 * u + row * 8 * u, 7.4 * u, 7.4 * u),
                                 QColor(shade, shade + 20, shade + 46))
    else:
        # One cell wearing the overlay's own vocabulary, so the toolbar
        # button and the thing it turns on are visibly the same idea.
        painter.fillRect(QRectF(3 * u, 3 * u, 16 * u, 16 * u), QColor(60, 62, 70))
        painter.fillRect(QRectF(3 * u, 3 * u, 16 * u, 16 * u), WASH)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(BAR))
        painter.drawRect(QRectF(6 * u, 3 * u, 10 * u, 4 * u))
        painter.drawRect(QRectF(3 * u, 6 * u, 4 * u, 10 * u))
    painter.end()
    return QIcon(pixmap)


def _build_all_layers_icon(size: int) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    u = size / 22.0
    for index in range(3):
        offset = (2 - index) * 3.4 * u
        painter.setPen(QPen(QColor(28, 30, 34, 200), 1.2 * u))
        painter.setBrush(QBrush(PROVENANCE[index]))
        painter.drawRect(QRectF(4 * u + offset, 4 * u + offset,
                                10 * u, 10 * u))
    painter.end()
    return QIcon(pixmap)


# --------------------------------------------------------------------------
# The overlay
# --------------------------------------------------------------------------

class CollisionOverlay(QGraphicsItem):
    """A scene-sized collision readout as one owned pixmap.

    Positioned at the scene origin and never moved: the pixmap maps 1:1 to
    item coordinates, which is what lets `paint()` use the exposed rect as
    both source and target and skip everything off-screen.

    LIFECYCLE. The canvas clears its scene on every command, so this item is
    built ONCE, held on the canvas across rebuilds, and re-added rather than
    re-baked. A bake is 6 ms; a brush stroke that re-baked would pay that on
    top of the 26.9 ms of layer rendering `rebuild()` already costs.

    OPACITY. Do not put this behind the per-layer fade `rebuild()` applies to
    layers above the active one. It is instrumentation, not content: the
    moment you are working under a foreground layer is exactly the moment you
    need to read it. Its alpha is baked into the glyphs.
    """

    #: Above the grid (1000) and below the stroke ghost (2000). The ghost has
    #: to win, because during a stroke the question is "what am I about to
    #: write", not "what is already there".
    Z = 1600

    def __init__(self, width: int, height: int,
                 tile_width: int, tile_height: int,
                 keyline: QColor | None = None):
        super().__init__()
        self.width = int(width)
        self.height = int(height)
        self.tile_width = int(tile_width)
        self.tile_height = int(tile_height)
        self.show_provenance = True
        self.show_conflicts = True

        self.__glyphs: Mapping[int, QPixmap] = glyph_pixmaps(
            self.tile_width, self.tile_height, keyline)
        self.__masks: list[int] = [NO_DATA] * (self.width * self.height)
        self.__owners: list[int] | None = None
        self.__conflicts: list[bool] | None = None

        self.__pixmap = QPixmap(max(1, self.width * self.tile_width),
                                max(1, self.height * self.tile_height))
        self.__pixmap.fill(Qt.transparent)

        self.setZValue(self.Z)
        # Without this flag `option.exposedRect` is the whole bounding rect
        # and the blit is 10.24 MB per paint instead of a viewport's worth.
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption,
                     True)
        # The canvas does its own hit testing against the document; an
        # instrumentation item must never swallow a click.
        self.setAcceptedMouseButtons(Qt.NoButton)

    # -- QGraphicsItem -----------------------------------------------------

    def boundingRect(self) -> QRectF:                         # noqa: N802
        return QRectF(0, 0, self.width * self.tile_width,
                      self.height * self.tile_height)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        exposed = option.exposedRect.intersected(self.boundingRect())
        if exposed.isEmpty():
            return
        # Nearest-neighbour: at 8x zoom a smoothed 1px keyline becomes a
        # grey smudge and the bars stop having edges.
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.drawPixmap(exposed, self.__pixmap, exposed)

    # -- baking ------------------------------------------------------------

    def bake(self, masks: Sequence[int]) -> None:
        """Render ONE layer's masks, row-major, length width*height.

        Short input is padded with NO_DATA rather than refused: a layer can
        legitimately be smaller than the map, and half a readout is more
        useful than an exception mid-rebuild.
        """
        self.__masks = self.__fit(masks)
        self.__owners = None
        self.__conflicts = None
        self.__render_all()

    def bake_resolved(self, layers: Sequence[CollisionLayer], *,
                      undecided: int = NO_DATA) -> None:
        """Render every collision layer at once, resolved to one answer.

        `layers[0]` is the TOP-MOST, which is `collision.resolve`'s contract
        and the opposite of a tmx layer list -- a caller reading a map
        reverses it. Each cell goes through `collision.resolve`, so the
        overlay shows exactly what the runtime will compute, and the result
        carries two channels a stacked rendering cannot express: which layer
        decided (a corner tick, coloured by index) and whether a layer below
        it disagreed (a hollow violet square in the centre, which the edge
        bars never touch).

        `undecided` is NO_DATA here where `collision.resolve` defaults it to
        PASS_ALL. The runtime is right to say "unauthored means walkable";
        an overlay that drew every unauthored cell as an assertion would ink
        the whole map and say nothing.
        """
        self.__masks, self.__owners, self.__conflicts = resolve_field(
            layers, self.width, self.height, undecided=undecided)
        self.__render_all()

    def set_cell(self, x: int, y: int, mask: int, *,
                 owner: int = -1, conflicted: bool = False) -> None:
        """Change one cell in place, without re-baking the field.

        This is the reason the pixmap is private. Writing four kilobytes into
        an owned buffer is 10.4 us; the same write against a pixmap whose
        reference escaped costs a 10.24 MB implicit-share detach first.
        """
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        index = y * self.width + x
        self.__masks[index] = mask
        if self.__owners is not None:
            self.__owners[index] = owner
        if self.__conflicts is not None:
            self.__conflicts[index] = conflicted

        left, top = x * self.tile_width, y * self.tile_height
        painter = QPainter(self.__pixmap)
        # Source, not SourceOver: the old glyph has to GO. Blending a new
        # glyph over the old one is how an edited cell ends up showing both.
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(left, top, self.tile_width, self.tile_height,
                         Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        self.__paint_cell(painter, x, y, mask, owner, conflicted)
        painter.end()
        self.update(QRectF(left, top, self.tile_width, self.tile_height))

    def set_glyphs(self, glyphs: Mapping[int, QPixmap]) -> None:
        """Swap the glyph set and re-render what is already baked."""
        self.__glyphs = dict(glyphs)
        self.__render_all()

    # -- reading -----------------------------------------------------------

    def mask_at(self, x: int, y: int) -> int:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return NO_DATA
        return self.__masks[y * self.width + x]

    def owner_at(self, x: int, y: int) -> int:
        """Which layer decided this cell, or -1 (also -1 outside a resolve)."""
        if self.__owners is None or not (0 <= x < self.width
                                         and 0 <= y < self.height):
            return -1
        return self.__owners[y * self.width + x]

    def conflicted_at(self, x: int, y: int) -> bool:
        if self.__conflicts is None or not (0 <= x < self.width
                                            and 0 <= y < self.height):
            return False
        return self.__conflicts[y * self.width + x]

    def cell_image(self, x: int, y: int) -> QImage:
        """A COPY of one cell's rendered pixels, for tooltips and checks.

        A copy on purpose. Handing out the pixmap is what the whole design
        avoids, and `QPixmap.copy` leaves the original unshared.
        """
        return self.__pixmap.copy(x * self.tile_width, y * self.tile_height,
                                  self.tile_width, self.tile_height).toImage()

    def describe(self, x: int, y: int) -> str:
        """A status-bar line for the cell under the cursor."""
        text = describe_opinion(self.mask_at(x, y))
        owner = self.owner_at(x, y)
        if owner >= 0:
            text += f"  (layer {owner})"
        if self.conflicted_at(x, y):
            text += "  — a layer below disagrees"
        return text

    # -- internals ---------------------------------------------------------

    def __fit(self, masks: Sequence[int]) -> list[int]:
        cells = self.width * self.height
        out = list(masks[:cells])
        if len(out) < cells:
            out.extend([NO_DATA] * (cells - len(out)))
        return out

    def __render_all(self) -> None:
        self.__pixmap.fill(Qt.transparent)
        painter = QPainter(self.__pixmap)
        owners, conflicts = self.__owners, self.__conflicts
        width = self.width
        for index, mask in enumerate(self.__masks):
            owner = owners[index] if owners is not None else -1
            conflicted = conflicts[index] if conflicts is not None else False
            if mask == NO_DATA or (mask == PASS_ALL and owner < 0
                                   and not conflicted):
                continue                      # nothing to say about this cell
            self.__paint_cell(painter, index % width, index // width,
                              mask, owner, conflicted)
        painter.end()
        self.update()

    def __paint_cell(self, painter: QPainter, x: int, y: int, mask: int,
                     owner: int, conflicted: bool) -> None:
        left, top = x * self.tile_width, y * self.tile_height
        glyph = self.__glyphs.get(mask)
        if glyph is not None:
            painter.drawPixmap(left, top, glyph)
        ux = self.tile_width / 16.0
        uy = self.tile_height / 16.0
        if owner >= 0 and self.show_provenance:
            # Top-left corner, 2x2u. The bars start 3u in, so this never
            # collides with one; at fit-zoom it vanishes, which is the
            # correct level of detail for "which layer decided".
            painter.fillRect(QRectF(left, top, 2 * ux, 2 * uy),
                             PROVENANCE[owner % len(PROVENANCE)])
        if conflicted and self.show_conflicts:
            pen = QPen(CONFLICT)
            pen.setWidthF(max(1.0, min(ux, uy)))
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(left + 5.5 * ux, top + 5.5 * uy,
                                    5 * ux, 5 * uy))


# --------------------------------------------------------------------------
# Reading a layer
# --------------------------------------------------------------------------

def masks_from_layer(layer, first_gid: int) -> list[int]:
    """A companion tile layer's gids as opinions, row-major, ready for `bake`.

    Takes anything with `width`, `height` and `get_tile(x, y)` -- the
    document's TileLayer, or a fixture built in a check. Note this reads
    FILE gids: pytmx renumbers, and `tmx.tiledgidmap` is internal->file, so
    an engine-side reader has to invert it first. The editor's MapDocument
    never renumbers, so there is nothing to invert here.
    """
    width, height = int(layer.width), int(layer.height)
    read = layer.get_tile
    return [gid_to_opinion(read(x, y), first_gid)
            for y in range(height) for x in range(width)]


def layer_from_companion(layer, first_gid: int, name: str = "") -> CollisionLayer:
    """A document tile layer as a stack member, without copying its cells.

    A `CollisionLayer` is three lazy readers, so this costs one closure --
    which matters, because the all-layers view holds one of these per
    collision layer and rebuilds them whenever the document changes.
    """
    return CollisionLayer(name=name or getattr(layer, "name", ""),
                          companion=companion_reader(layer.get_tile, first_gid))


def layer_from_masks(masks: Sequence[int], width: int,
                     name: str = "") -> CollisionLayer:
    """A flat mask list as a stack member, for previews and fixtures.

    Out-of-range reads answer NO_DATA rather than raising: a collision layer
    may legitimately be smaller than the map, and `resolve` treats "nothing
    here" as abstention, which is exactly the right answer past the edge.
    """
    def read(x: int, y: int) -> int:
        index = y * width + x
        if x < 0 or x >= width or not 0 <= index < len(masks):
            return NO_DATA
        return masks[index]

    return CollisionLayer(name=name, companion=read)


def resolve_field(layers: Sequence[CollisionLayer], width: int, height: int,
                  *, undecided: int = NO_DATA
                  ) -> tuple[list[int], list[int], list[bool]]:
    """The whole resolved field as plain data, for anything without a pixmap.

    `layers[0]` is the TOP-MOST. Split out from `bake_resolved` so a check,
    an exporter or a tooltip can ask "what will the player feel here"
    without building a QGraphicsItem.
    """
    masks: list[int] = []
    owners: list[int] = []
    conflicts: list[bool] = []
    for y in range(height):
        for x in range(width):
            resolution = resolve(layers, x, y, undecided=undecided)
            masks.append(resolution.mask)
            owners.append(resolution.layer)
            conflicts.append(resolution.conflicted)
    return masks, owners, conflicts


# --------------------------------------------------------------------------
# The mode switch
# --------------------------------------------------------------------------

@dataclass
class ModeActions:
    """The toolbar controls for the mode, built as one unit.

    Built here rather than in `main_window.__build_toolbar` so that adding
    collision mode to the window is three lines instead of thirty, and so the
    enable/disable coupling -- "All layers" only means anything in collision
    mode -- lives next to the thing it constrains rather than being
    re-derived by every caller.
    """

    group: QActionGroup
    actions: dict[EditMode, QAction]
    all_layers: QAction
    toggle: QAction
    _mode: EditMode = EditMode.TILES
    _on_change: Callable[[EditMode], None] | None = None

    @property
    def mode(self) -> EditMode:
        return self._mode

    def set_mode(self, mode: EditMode) -> None:
        """Idempotent: re-selecting the live mode does not re-notify, which
        matters because the notification rebuilds the canvas."""
        if mode is self._mode and self.actions[mode].isChecked():
            return
        self._mode = mode
        for candidate, action in self.actions.items():
            action.setChecked(candidate is mode)
        self.all_layers.setEnabled(mode is EditMode.COLLISION)
        if self._on_change is not None:
            self._on_change(mode)

    @property
    def all_layers_on(self) -> bool:
        return self.all_layers.isChecked() and self._mode is EditMode.COLLISION


def build_mode_actions(parent: QWidget,
                       on_change: Callable[[EditMode], None] | None = None,
                       on_all_layers: Callable[[bool], None] | None = None,
                       *, size: int = 22) -> ModeActions:
    """An exclusive Tiles/Collision pair, plus the All-layers toggle.

    The mode gets ONE shortcut that flips it, not one per member: two
    mutually exclusive states do not need two keys, and `C` is the only
    letter `_TOOL_SHORTCUTS` leaves free. Add `toggle` to the WINDOW rather
    than the toolbar -- it is a keyboard accelerator, not a button.
    """
    group = QActionGroup(parent)
    group.setExclusive(True)
    actions: dict[EditMode, QAction] = {}
    for mode in EditMode:
        action = QAction(mode_icon(mode, size), mode.label, parent)
        action.setCheckable(True)
        action.setChecked(mode is EditMode.TILES)
        action.setToolTip(f"{mode.label}  ({MODE_SHORTCUT} toggles)\n{mode.tip}")
        action.setStatusTip(mode.tip)
        group.addAction(action)
        actions[mode] = action

    all_layers = QAction(all_layers_icon(size), "All layers", parent)
    all_layers.setCheckable(True)
    all_layers.setEnabled(False)
    all_layers.setToolTip(
        "Resolve every collision layer into the one answer the player will "
        "feel, with a corner tick for the deciding layer and a violet square "
        "where a layer below disagrees.")

    toggle = QAction("Toggle collision mode", parent)
    toggle.setShortcut(MODE_SHORTCUT)

    switch = ModeActions(group=group, actions=actions, all_layers=all_layers,
                         toggle=toggle, _on_change=on_change)

    for mode, action in actions.items():
        action.triggered.connect(
            lambda checked=False, m=mode: switch.set_mode(m))
    toggle.triggered.connect(lambda: switch.set_mode(switch.mode.other))
    if on_all_layers is not None:
        all_layers.toggled.connect(on_all_layers)
    return switch


# --------------------------------------------------------------------------
# The mask palette
# --------------------------------------------------------------------------

class MaskPalette(QWidget):
    """Seventeen swatches: what `TilePalette` becomes in collision mode.

    Laid out four wide so the column index is the low two bits (down, left)
    and the row index is the high two (right, up) -- picking "blocks left and
    right" is then a position, not a hunt. Star sits alone on the last row,
    which is honest: it is not a direction.

    Emits a MASK, not a gid. Turning it into a gid needs the companion
    layer's firstgid, which the canvas knows and this widget should not.
    """

    mask_picked = Signal(int)

    COLUMNS = 4

    def __init__(self, parent: QWidget | None = None, *, cell: int = 34):
        super().__init__(parent)
        self.cell = cell
        self.__mask = BLOCK_ALL
        self.__glyphs = glyph_pixmaps(cell, cell)

        self.surface = _MaskSurface(self)
        self.caption = QLabel(describe_mask(self.__mask))
        self.caption.setStyleSheet("color: palette(mid); font-size: 11px;")
        self.caption.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        layout.addWidget(self.surface, 1)
        layout.addWidget(self.caption)

    @property
    def mask(self) -> int:
        return self.__mask

    @property
    def glyphs(self) -> Mapping[int, QPixmap]:
        return self.__glyphs

    @property
    def rows(self) -> int:
        return (len(MASK_DOMAIN) + self.COLUMNS - 1) // self.COLUMNS

    def mask_at(self, column: int, row: int) -> int | None:
        index = row * self.COLUMNS + column
        if not (0 <= column < self.COLUMNS and 0 <= index < len(MASK_DOMAIN)):
            return None
        return MASK_DOMAIN[index]

    def select_mask(self, mask: int, *, notify: bool = True) -> None:
        if mask not in MASK_DOMAIN:
            return
        self.__mask = mask
        self.caption.setText(describe_mask(mask))
        self.surface.update()
        if notify:
            self.mask_picked.emit(mask)


class _MaskSurface(QWidget):
    """The drawn grid. Split out so the palette owns the caption."""

    def __init__(self, palette: MaskPalette):
        super().__init__()
        self.palette = palette
        size = palette.cell + 6
        self.setMinimumSize(MaskPalette.COLUMNS * size, palette.rows * size)

    def __step(self) -> int:
        return self.palette.cell + 6

    def paintEvent(self, _event) -> None:                     # noqa: N802
        painter = QPainter(self)
        step, cell = self.__step(), self.palette.cell
        for index, mask in enumerate(MASK_DOMAIN):
            x = (index % MaskPalette.COLUMNS) * step + 3
            y = (index // MaskPalette.COLUMNS) * step + 3
            # A neutral plate under every swatch, so "open" is a visible
            # choice rather than a hole in the widget.
            painter.fillRect(x, y, cell, cell, QColor(46, 48, 54))
            glyph = self.palette.glyphs.get(mask)
            if glyph is not None:
                painter.drawPixmap(x, y, glyph)
            if mask == self.palette.mask:
                painter.setPen(QPen(QColor(120, 200, 255), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(x - 1, y - 1, cell + 2, cell + 2)
        painter.end()

    def mousePressEvent(self, event) -> None:                 # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        step = self.__step()
        mask = self.palette.mask_at(int(event.position().x()) // step,
                                    int(event.position().y()) // step)
        if mask is not None:
            self.palette.select_mask(mask)
