"""Turn a map's `<tileset>` declarations into per-gid pixmaps.

Reads the tmx XML directly rather than going through pytmx, because the
editor is pygame-free and pytmx's pygame loader is not.

Degrades on purpose. This repository ships without art, so a tileset image
will often be missing. Rather than refusing to draw a map, a missing image
produces a deterministic colour swatch per gid -- enough to see structure,
edit layers, and place objects, and visibly not real art.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap


@dataclass
class TilesetEntry:
    first_gid: int
    name: str
    tile_width: int
    tile_height: int
    tile_count: int
    columns: int
    source: str
    image: QImage | None


class TilesetAtlas:
    """gid -> pixmap, for one map."""

    def __init__(self, document, *, tile_width: int, tile_height: int):
        self.tile_width = tile_width
        self.tile_height = tile_height
        self.entries: list[TilesetEntry] = []
        self.missing: list[str] = []
        self.__cache: dict[int, QPixmap] = {}
        self.__load(document)

    # -- loading -----------------------------------------------------------

    def __load(self, document) -> None:
        base = os.path.dirname(os.path.abspath(document.path or ""))
        for element in document.root.findall("tileset"):
            image_element = element.find("image")
            source = image_element.get("source", "") if image_element is not None else ""
            resolved = os.path.normpath(os.path.join(base, source)) if source else ""
            image = None
            if resolved and os.path.isfile(resolved):
                loaded = QImage(resolved)
                image = loaded if not loaded.isNull() else None
            if source and image is None:
                self.missing.append(source)
            self.entries.append(TilesetEntry(
                first_gid=int(element.get("firstgid", "1")),
                name=element.get("name", ""),
                tile_width=int(element.get("tilewidth", self.tile_width)),
                tile_height=int(element.get("tileheight", self.tile_height)),
                tile_count=int(element.get("tilecount", "0")),
                columns=int(element.get("columns", "1")) or 1,
                source=source,
                image=image,
            ))
        self.entries.sort(key=lambda e: e.first_gid)

    # -- reading -----------------------------------------------------------

    @property
    def has_art(self) -> bool:
        return any(entry.image is not None for entry in self.entries)

    @property
    def max_gid(self) -> int:
        if not self.entries:
            return 0
        last = self.entries[-1]
        return last.first_gid + max(0, last.tile_count) - 1

    def entry_for(self, gid: int) -> TilesetEntry | None:
        found = None
        for entry in self.entries:
            if entry.first_gid <= gid:
                found = entry
            else:
                break
        if found is None:
            return None
        if found.tile_count and gid >= found.first_gid + found.tile_count:
            return None
        return found

    def pixmap(self, gid: int) -> QPixmap | None:
        """The tile image for `gid`, or a swatch when the art is missing."""
        if gid <= 0:
            return None
        if gid in self.__cache:
            return self.__cache[gid]
        entry = self.entry_for(gid)
        made = (self.__from_image(entry, gid) if entry and entry.image is not None
                else self.__swatch(gid))
        self.__cache[gid] = made
        return made

    def __from_image(self, entry: TilesetEntry, gid: int) -> QPixmap:
        index = gid - entry.first_gid
        column = index % entry.columns
        row = index // entry.columns
        rect = QRect(column * entry.tile_width, row * entry.tile_height,
                     entry.tile_width, entry.tile_height)
        return QPixmap.fromImage(entry.image.copy(rect))

    def __swatch(self, gid: int) -> QPixmap:
        """A stable, readable stand-in: same gid always gets the same colour."""
        pixmap = QPixmap(self.tile_width, self.tile_height)
        pixmap.fill(gid_colour(gid))
        painter = QPainter(pixmap)
        painter.setPen(QColor(0, 0, 0, 60))
        painter.drawRect(0, 0, self.tile_width - 1, self.tile_height - 1)
        painter.end()
        return pixmap


def gid_colour(gid: int) -> QColor:
    """Deterministic colour for a gid. Golden-ratio hue so neighbours differ."""
    hue = int((gid * 137.508) % 360)
    saturation = 90 + (gid * 37) % 60
    value = 130 + (gid * 61) % 90
    return QColor.fromHsv(hue, saturation, value)


def render_layer(layer, atlas: TilesetAtlas) -> QPixmap:
    """Composite one tile layer into a single pixmap."""
    width = layer.width * atlas.tile_width
    height = layer.height * atlas.tile_height
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    gids = layer.gids()
    painter = QPainter(pixmap)
    for index, gid in enumerate(gids):
        if not gid:
            continue
        tile = atlas.pixmap(gid)
        if tile is None:
            continue
        column = index % layer.width
        row = index // layer.width
        painter.drawPixmap(column * atlas.tile_width, row * atlas.tile_height, tile)
    painter.end()
    return pixmap
