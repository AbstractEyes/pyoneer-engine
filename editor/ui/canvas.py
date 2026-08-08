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
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
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

from editor.core import autotile
from editor.core.commands import Command
from editor.core.paint import (
    Bounds,
    Stamp,
    Stroke,
    Tool,
    edits_to_triples,
)
from editor.core.scope import Scope
from editor.ui.tileset import TilesetAtlas, gid_colour, render_layer

_OBJECT_PEN = QColor(255, 90, 90)
_OBJECT_SELECTED = QColor(120, 200, 255)
_GRID_PEN = QColor(255, 255, 255, 28)
_GHOST_Z = 2000


class MapCanvas(QGraphicsView):
    """A depth-ordered, paintable view of one map."""

    status = Signal(str)
    picked_gid = Signal(int)
    selected = Signal(object)          # a Scope

    def __init__(self, session, map_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.map_name = map_name
        self.active_layer: str | None = None
        self.tool = Tool.BRUSH
        self.stamp = Stamp.single(1)
        self.object_class = "GameEntity"
        self.hidden_layers: set[str] = set()
        self.selected_scope: Scope | None = None

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

    # -- building ----------------------------------------------------------

    def rebuild(self) -> None:
        scene = self.scene()
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

        pack = self.session.project.genre

        def depth_of(name: str) -> int:
            declared = pack.layer(name)
            return declared.depth if declared else 500

        for name in sorted(document.tile_layer_names(), key=depth_of):
            if name in self.hidden_layers:
                continue
            item = QGraphicsPixmapItem(
                render_layer(document.tile_layer(name), self.atlas))
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

    def __draw_grid(self, scene, document, width: int, height: int) -> None:
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
        self.rebuild()

    def set_selection(self, scope: Scope) -> None:
        self.selected_scope = scope
        self.rebuild()

    # -- ghost preview -----------------------------------------------------

    def __clear_ghost(self) -> None:
        if self.__ghost is not None:
            self.scene().removeItem(self.__ghost)
            self.__ghost = None

    def __draw_ghost(self) -> None:
        self.__clear_ghost()
        if self.__stroke is None or self.atlas is None:
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
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

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
            self.__pick(column, row)
            event.accept()
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
            self.status.emit(f"cell ({column}, {row})   "
                             f"{len(self.__stroke.edits())} tiles")
            event.accept()
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
