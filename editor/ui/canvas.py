"""The map canvas and the tile palette.

Clicking a tile emits `map.tile.set`. Placing an object emits
`map.object.add`. There is no direct-mutation path — which is why undo
works on canvas edits and why the history reads the same whether you
painted a tile or an AI did.

Rendering degrades honestly: with no tileset art on disk, every gid gets a
deterministic colour swatch. Structure stays editable; nobody mistakes it
for finished art.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QLabel,
    QScrollArea,
    QWidget,
)

from editor.core.commands import Command
from editor.core.scope import Scope
from editor.ui.tileset import TilesetAtlas, gid_colour, render_layer

_OBJECT_PEN = QColor(255, 90, 90)
_GRID_PEN = QColor(255, 255, 255, 28)


class MapCanvas(QGraphicsView):
    """A depth-ordered view of one map."""

    tile_clicked = Signal(int, int)
    status = Signal(str)

    def __init__(self, session, map_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.map_name = map_name
        self.active_layer: str | None = None
        self.brush_gid = 1
        self.object_class = "GameEntity"
        self.hidden_layers: set[str] = set()

        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(28, 28, 32)))
        self.setMouseTracking(True)

        self.atlas: TilesetAtlas | None = None
        self.__items: dict[str, QGraphicsPixmapItem] = {}
        self.rebuild()

    # -- geometry ----------------------------------------------------------

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
        return int(scene_x // self.tile_width), int(scene_y // self.tile_height)

    # -- building ----------------------------------------------------------

    def rebuild(self) -> None:
        """Re-composite every layer. Called on open and after a transaction."""
        scene = self.scene()
        scene.clear()
        self.__items.clear()

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
        tile_names = document.tile_layer_names()

        def depth_of(name: str) -> int:
            declared = pack.layer(name)
            return declared.depth if declared else 500

        for name in sorted(tile_names, key=depth_of):
            if name in self.hidden_layers:
                continue
            layer = document.tile_layer(name)
            item = QGraphicsPixmapItem(render_layer(layer, self.atlas))
            item.setZValue(depth_of(name))
            item.setTransformationMode(Qt.FastTransformation)
            scene.addItem(item)
            self.__items[name] = item

        for name in document.object_layer_names():
            if name in self.hidden_layers:
                continue
            self.__draw_objects(scene, document.object_layer(name),
                                depth_of(name) + 0.5)

        self.__draw_grid(scene, document, width, height)

        if self.atlas.missing:
            self.status.emit(
                f"no tileset art for {', '.join(self.atlas.missing)} — "
                f"drawing colour swatches (see docs/ASSETS.md)")

    def __draw_objects(self, scene, layer, z: float) -> None:
        for obj in layer.objects():
            width = obj.width or self.tile_width
            height = obj.height or self.tile_height
            rect = QGraphicsRectItem(QRectF(obj.x, obj.y, width, height))
            rect.setPen(QPen(_OBJECT_PEN, 1.5))
            rect.setBrush(QBrush(QColor(255, 90, 90, 40)))
            rect.setZValue(z)
            rect.setData(0, obj.id)
            scene.addItem(rect)
            label = QGraphicsSimpleTextItem(obj.type or obj.name or str(obj.id))
            label.setBrush(QBrush(QColor(255, 220, 220)))
            label.setPos(obj.x + 1, obj.y - 12)
            label.setZValue(z)
            scene.addItem(label)

    def __draw_grid(self, scene, document, width: int, height: int) -> None:
        pen = QPen(_GRID_PEN)
        pen.setCosmetic(True)
        for column in range(0, document.width + 1):
            x = column * document.tile_width
            scene.addLine(x, 0, x, height, pen).setZValue(1000)
        for row in range(0, document.height + 1):
            y = row * document.tile_height
            scene.addLine(0, y, width, y, pen).setZValue(1000)

    def set_layer_visible(self, name: str, visible: bool) -> None:
        if visible:
            self.hidden_layers.discard(name)
        else:
            self.hidden_layers.add(name)
        self.rebuild()

    # -- interaction -------------------------------------------------------

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    def mouseMoveEvent(self, event) -> None:
        point = self.mapToScene(event.pos())
        column, row = self.cell_at(point.x(), point.y())
        self.status.emit(f"cell ({column}, {row})   px ({point.x():.0f}, "
                         f"{point.y():.0f})")
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() not in (Qt.LeftButton, Qt.RightButton):
            super().mousePressEvent(event)
            return
        if not (event.modifiers() & Qt.AltModifier):
            super().mousePressEvent(event)
            return

        point = self.mapToScene(event.pos())
        column, row = self.cell_at(point.x(), point.y())
        self.__edit_at(column, row, point.x(), point.y(),
                       erase=event.button() == Qt.RightButton)
        event.accept()

    def __edit_at(self, column: int, row: int, px: float, py: float,
                  *, erase: bool) -> None:
        if self.active_layer is None:
            self.status.emit("select a layer first")
            return
        document = self.document
        scope = Scope.of(("map", self.map_name), ("layer", self.active_layer))

        if self.active_layer in document.tile_layer_names():
            gid = 0 if erase else self.brush_gid
            self.window().run(Command("map.tile.set", scope,
                                      {"x": column, "y": row, "gid": gid}))
            return

        if self.active_layer in document.object_layer_names():
            if erase:
                layer = document.object_layer(self.active_layer)
                for obj in layer.objects():
                    width = obj.width or self.tile_width
                    height = obj.height or self.tile_height
                    if (obj.x <= px < obj.x + width
                            and obj.y <= py < obj.y + height):
                        self.window().run(Command(
                            "map.object.remove",
                            scope.child("object", str(obj.id))))
                        return
                self.status.emit("no object under the cursor")
                return
            self.window().run(Command("map.object.add", scope, {
                "type": self.object_class,
                "x": float(column * self.tile_width),
                "y": float(row * self.tile_height),
            }))


class TilePalette(QScrollArea):
    """Pick a gid by clicking it."""

    gid_picked = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setWidget(self.label)
        self.setWidgetResizable(False)
        self.atlas: TilesetAtlas | None = None
        self.columns = 32
        self.cell = 16
        self.selected = 1

    def set_atlas(self, atlas: TilesetAtlas) -> None:
        self.atlas = atlas
        self.cell = max(atlas.tile_width, 8)
        self.columns = 32
        self.__render()

    def __render(self) -> None:
        if self.atlas is None or self.atlas.max_gid <= 0:
            self.label.setText("no tilesets in this map")
            return
        count = self.atlas.max_gid
        rows = (count + self.columns - 1) // self.columns
        pixmap = QPixmap(self.columns * self.cell, rows * self.cell)
        pixmap.fill(QColor(20, 20, 24))
        painter = QPainter(pixmap)
        for index in range(count):
            gid = index + 1
            tile = self.atlas.pixmap(gid)
            x = (index % self.columns) * self.cell
            y = (index // self.columns) * self.cell
            if tile is not None:
                painter.drawPixmap(x, y, tile)
            else:
                painter.fillRect(x, y, self.cell, self.cell, gid_colour(gid))
        painter.end()
        self.label.setPixmap(pixmap)
        self.label.resize(pixmap.size())

    def mousePressEvent(self, event) -> None:
        if self.atlas is None:
            return
        point = self.label.mapFrom(self, event.pos())
        column = point.x() // self.cell
        row = point.y() // self.cell
        if column < 0 or column >= self.columns:
            return
        gid = row * self.columns + column + 1
        if 1 <= gid <= self.atlas.max_gid:
            self.selected = gid
            self.gid_picked.emit(gid)
