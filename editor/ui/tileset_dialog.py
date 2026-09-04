"""Import a tileset by SELECTING A REGION of any image.

WHY A REGION AND NOT A GRID DESCRIPTION
---------------------------------------
Tiled describes a sheet with `margin` and `spacing`, and this editor cannot
honour that description: measured, the editor's atlas and the engine agree
about which pixels a gid names only at margin 0, spacing 0, and a full-width
column count. At `margin=8` every probed tile disagreed; at `spacing=1` five
of six did. Two readers disagreeing about what a gid looks like raises
nowhere -- it just paints the wrong art.

So the region is not recorded in the tmx at all. The user drags a rectangle,
this module CROPS those pixels into a PNG, and the tileset is declared as a
plain 0/0 grid over that file -- the one geometry all three readers already
agree on. Offset, resize and truncate are therefore editor-side operations
on a selection, and the file records only their result.

Writing a PNG from a view is not a new kind of act here: `write_mask_sheet`
in `editor/ui/canvas.py` already materialises a sheet as part of a command
path, for the same reason -- pytmx opens every `<image source>` it parses,
so the file has to exist at the declared size before the map will load.

WHY A PREVIEW EARNS ITS CODE
----------------------------
Tile size is two numbers that are each individually plausible and jointly
wrong, and the file they land in gives no feedback at all. A 16px sheet cut
at 15 produces perfectly legal TMX: correct schema, correct tilecount, and
every tile carrying a one-pixel seam of its neighbour. Nothing raises, in
Tiled or in the engine. Drawing the proposed cut over the actual pixels is
the only cheap way to see that BEFORE a map is authored against it -- and
once tiles are painted, changing the grid means renumbering every gid, which
`MapDocument.add_tileset` refuses to do on principle.

THE NUMBERS ARE NOT COMPUTED HERE
---------------------------------
`tileset_geometry` is the function `MapDocument.add_tileset` itself uses to
write `columns` and `tilecount`, so this module imports it rather than
dividing width by tile width -- and calls it with the CROP's size, which is
the sheet the file will actually name.

WHY QImage AND NOT image_size()
-------------------------------
`scripts.loaders.map_document.image_size` reads PNG headers by hand, and
deliberately: `scripts/` may never import `editor/`, so the engine side
cannot reach for Qt to learn two integers. The editor has no such
constraint, and someone importing art will hand it a .bmp or a .jpg sooner
or later. So this side asks Qt and passes the measured width and height into
the command explicitly -- which is also what keeps the engine from ever
having to open the image at all.

THIS VIEW APPLIES NOTHING, AND IT DOES NOT BLOCK
------------------------------------------------
It emits a `TilesetImport` and stops. Every change to a map goes through a
Command, and a view that wrote to the document directly would be the one
edit in the editor with no inverse, no history entry and nothing for a human
to review. It is shown with `show()` and stays open across an import, so
adding four regions off one sheet is four drags -- which is what turns a
form into a tool, and is why it must not be modal.

NO BLOCKING CALL OF ITS OWN, AND BROWSE IS STILL A SEAM
------------------------------------------------------
Browse opens the platform file picker, and there is no way to pick a file
without one -- but the picker is `ask.choose_file` now, so this module owns
no modal at all and the named exemption `tools/check_editor_ui.py` carried
for it on 2026-09-04 is gone. `_choose_image_file` stays as a one-line
adapter, because the SEAM is the half that matters here: it is held as an
INSTANCE attribute -- `self.choose_file`, the same shape as
`MapCanvas.popup_menu` and `ask.confirm` -- so a check drives the button,
substitutes the opener and asserts what Browse did with the answer, instead
of sitting on a modal until the suite's 600s timeout (law 13).
#TAG:file_picker_is_a_seam
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from scripts.loaders.map_document import tileset_geometry

from editor.ui.ask import choose_file

# Offered as a filter, not enforced. An unreadable file is caught by QImage
# handing back a null image, which is a real test; a file extension is not.
IMAGE_FILTER = ("Tileset images (*.png *.bmp *.jpg *.jpeg *.gif *.tga *.webp)"
                ";;All files (*)")

#: Where a cropped selection lands, relative to the .tmx. A directory beside
#: the map rather than beside the source art: the source may be read-only,
#: may be outside the project, and may be on another drive -- and a path
#: relative to the map is the only one Tiled and the engine both resolve.
CROP_DIR = "tilesets"


def safe_stem(name: str) -> str:
    """A filename for a tileset called `name`.

    A tileset name is free text and a filename is not. Anything that is not
    a letter, a digit, a dash or an underscore becomes an underscore, so a
    tileset called `Cave walls (2)` cannot write a path with a bracket in it
    that only some platforms accept.
    """
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_")


def write_region(image: QImage, rect: QRect, path: str) -> bool:
    """Put a cropped sheet on disk. Returns True when it wrote one.

    NEVER OVERWRITES DIFFERENT PIXELS. A file already at `path` is reused
    when it holds exactly this crop and RAISES otherwise, because the two
    failure modes either way are silent: overwriting would destroy art
    another map is declared against, and reusing blindly would declare a
    tileset over pixels nobody chose.

    Reused rather than refused when the bytes match, so add-undo-add of the
    same region is not a dead end.

    Raises OSError when it cannot write, because `QImage.save` returns False
    and raises nothing: an unchecked call reports success and leaves a
    tileset declared over an image that is not there.
    """
    crop = image.copy(rect)
    if os.path.exists(path):
        existing = QImage(path)
        if not existing.isNull() and existing.convertToFormat(
                crop.format()) == crop:
            return False
        raise OSError(
            f"{path} already holds different pixels; rename this tileset or "
            f"delete that file")
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not crop.save(path, "PNG"):
        raise OSError(f"could not write the cropped sheet to {path}")
    return True


@dataclass(frozen=True)
class TilesetImport:
    """What the user asked for, as plain data.

    Frozen and Qt-free on purpose. This is what crosses from the view layer
    into a Command, and anything carrying a widget across that line would
    make the command stream un-replayable.

    There is no `margin` or `spacing`. The editor writes neither, ever: see
    this module's own header for the measurement that decided it.
    """

    name: str
    image: str                  # relative to the .tmx, forward slashes
    tile_width: int
    tile_height: int
    image_width: int            # of the sheet AS DECLARED -- the crop, if any
    image_height: int
    columns: int
    rows: int
    tile_count: int
    region_x: int = 0           # what was selected, in the SOURCE image
    region_y: int = 0
    cropped: bool = False       # whether `image` names a file this view wrote

    def command_args(self) -> dict[str, Any]:
        """Arguments for `map.tileset.add`.

        A dict rather than a Command: constructing one and running it
        through the session is the caller's job, and this module
        deliberately cannot do it. `columns` and `tile_count` are handed
        over explicitly so the file records exactly the grid the user was
        shown, even though the document would derive the same pair itself --
        and `tile_count` is the truncation, which no formula could derive.
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


def relative_image_path(image_path: str, map_dir: str) -> str:
    """The path to write into the .tmx: relative to the MAP, forward slashes.

    Two traps in one function. Tiled resolves `<image source=...>` against
    the .tmx and never against the working directory, so a path relative to
    anything else loads on the machine that wrote it and nowhere else. And
    `os.path.relpath` returns backslashes on Windows, which in a tmx is a
    path that only opens on Windows -- the shipped map spells its sheets
    `../graphics/tilesets/...` and has to keep doing so.

    Falls back to the absolute path when the two sit on different drives,
    where no relative path exists at all.
    """
    if not image_path:
        return ""
    try:
        relative = os.path.relpath(os.path.abspath(image_path),
                                   os.path.abspath(map_dir))
    except ValueError:
        # Different drive letters on Windows. An absolute path is wrong for
        # sharing the project and right for opening the map today, and the
        # alternative is a path that resolves to nothing anywhere.
        return image_path.replace(os.sep, "/")
    return relative.replace(os.sep, "/")


_HANDLE = 7
"""Half-width, in widget pixels, of a resize grip. Also the slack a press
gets when deciding whether it landed ON an edge or INSIDE the band."""


class GridPreview(QWidget):
    """The sheet, with the selected region drawn as a snapped rubber band.

    Scaled to fit rather than shown 1:1, because a 512x512 sheet inside a
    dock is most of a laptop screen. One rectangle per tile INSIDE the band
    rather than a lattice over the whole image, because the pixels outside
    the band belong to no tile -- and a lattice would draw straight through
    them and hide exactly the mistake worth seeing.

    The grid is anchored at the band's own origin, not at the image's. That
    is what makes an offset meaningful: a sheet with a three-pixel border is
    cut correctly by moving the band three pixels, and the cut the preview
    draws is the cut the crop takes.
    """

    region_changed = Signal(int, int, int, int)    # x, y, columns, rows

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.image: QImage | None = None
        self.tile_width = 16
        self.tile_height = 16
        self.region_x = 0
        self.region_y = 0
        self.columns = 0
        self.rows = 0
        self.setMinimumSize(280, 180)
        self.setMouseTracking(True)
        self.__drag: tuple[int, int, tuple[int, int, int, int], QPointF] | None
        self.__drag = None

    def describe(self, image: QImage | None, tile_width: int, tile_height: int,
                 region_x: int, region_y: int, columns: int, rows: int) -> None:
        self.image = image
        self.tile_width = max(1, tile_width)
        self.tile_height = max(1, tile_height)
        self.region_x = region_x
        self.region_y = region_y
        self.columns = columns
        self.rows = rows
        self.update()

    # -- mapping -----------------------------------------------------------

    def fit(self) -> tuple[float, float, float]:
        """Where the image is drawn: left, top, and the scale it is drawn at.

        Public because every mouse handler needs the same three numbers the
        painter used, and a second derivation of them would put the rubber
        band somewhere the pixels are not.
        """
        if self.image is None or self.image.isNull():
            return 0.0, 0.0, 1.0
        area = self.rect().adjusted(6, 6, -6, -6)
        scale = min(area.width() / self.image.width(),
                    area.height() / self.image.height())
        # Magnified only by whole numbers. A 64x64 sheet shown at 1:1 in a
        # 500px view is unpickable, and a fractional enlargement of pixel
        # art is a preview of tiles the map will not draw.
        scale = float(int(scale)) if scale > 1 else scale
        width = self.image.width() * scale
        height = self.image.height() * scale
        return (area.x() + (area.width() - width) / 2,
                area.y() + (area.height() - height) / 2, scale)

    def band_rect(self) -> QRectF:
        """The band in WIDGET coordinates."""
        left, top, scale = self.fit()
        return QRectF(left + self.region_x * scale, top + self.region_y * scale,
                      self.columns * self.tile_width * scale,
                      self.rows * self.tile_height * scale)

    def __image_point(self, position) -> QPointF:
        left, top, scale = self.fit()
        return QPointF((position.x() - left) / scale, (position.y() - top) / scale)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:                        # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        if self.image is None or self.image.isNull():
            painter.setPen(self.palette().mid().color())
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "choose an image, then drag out the tiles you want")
            painter.end()
            return

        left, top, scale = self.fit()
        width = self.image.width() * scale
        height = self.image.height() * scale
        painter.drawImage(QRectF(left, top, width, height), self.image)

        # The image's own edge, so unclaimed pixels down the right or bottom
        # read as a gap between the last tile and the border.
        painter.setPen(QPen(QColor(255, 255, 255, 90), 0))
        painter.drawRect(QRectF(left, top, width, height))

        band = self.band_rect()
        if self.columns <= 0 or self.rows <= 0:
            painter.end()
            return

        # Everything outside the selection is dimmed rather than hidden: an
        # author moving the band needs to see what is next to it.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 96))
        for outside in (QRectF(left, top, width, band.top() - top),
                        QRectF(left, band.bottom(), width,
                               top + height - band.bottom()),
                        QRectF(left, band.top(), band.left() - left,
                               band.height()),
                        QRectF(band.right(), band.top(),
                               left + width - band.right(), band.height())):
            if outside.width() > 0 and outside.height() > 0:
                painter.fillRect(outside, painter.brush())

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 190, 255, 170), 0))
        for row in range(self.rows):
            for column in range(self.columns):
                painter.drawRect(QRectF(
                    band.left() + column * self.tile_width * scale,
                    band.top() + row * self.tile_height * scale,
                    self.tile_width * scale, self.tile_height * scale))

        painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
        painter.drawRect(band)
        painter.setBrush(QColor(255, 255, 255, 220))
        for point in self.__grips(band):
            painter.drawRect(QRectF(point.x() - 3, point.y() - 3, 6, 6))
        painter.end()

    @staticmethod
    def __grips(band: QRectF) -> list[QPointF]:
        xs = (band.left(), band.center().x(), band.right())
        ys = (band.top(), band.center().y(), band.bottom())
        return [QPointF(x, y) for y in ys for x in xs
                if not (x == band.center().x() and y == band.center().y())]

    # -- dragging ----------------------------------------------------------

    def zone(self, position) -> tuple[int, int] | None:
        """Which part of the band a widget point is on.

        `(dx, dy)` in -1/0/1 names the edge being grabbed, `(0, 0)` is the
        body, and None is outside -- where a press starts a new selection
        rather than adjusting this one. One nine-way test rather than eight
        handle rectangles and a body rectangle, which are the same thing
        written out longhand.
        """
        if self.columns <= 0 or self.rows <= 0:
            return None
        band = self.band_rect()
        grown = band.adjusted(-_HANDLE, -_HANDLE, _HANDLE, _HANDLE)
        if not grown.contains(QPointF(position.x(), position.y())):
            return None
        dx = (-1 if position.x() < band.left() + _HANDLE
              else 1 if position.x() > band.right() - _HANDLE else 0)
        dy = (-1 if position.y() < band.top() + _HANDLE
              else 1 if position.y() > band.bottom() - _HANDLE else 0)
        return dx, dy

    def mousePressEvent(self, event) -> None:                   # noqa: N802
        if event.button() != Qt.LeftButton or self.image is None:
            return
        zone = self.zone(event.position())
        if zone is None:
            # A fresh selection. The anchor snaps to the IMAGE's grid,
            # because there is no band yet to derive an origin from; the
            # offset fields move it off that grid afterwards.
            point = self.__image_point(event.position())
            column = self.__clamp(int(point.x()) // self.tile_width, 0,
                                  max(0, self.image.width() // self.tile_width - 1))
            row = self.__clamp(int(point.y()) // self.tile_height, 0,
                               max(0, self.image.height() // self.tile_height - 1))
            self.region_x = column * self.tile_width
            self.region_y = row * self.tile_height
            self.columns = self.rows = 1
            zone = (1, 1)
        self.__drag = (zone[0], zone[1],
                       (self.region_x, self.region_y, self.columns, self.rows),
                       self.__image_point(event.position()))
        self.__emit()

    def mouseMoveEvent(self, event) -> None:                    # noqa: N802
        if self.__drag is None:
            zone = self.zone(event.position())
            self.setCursor(Qt.CrossCursor if zone is None
                           else Qt.SizeAllCursor if zone == (0, 0)
                           else Qt.SizeFDiagCursor)
            return
        dx, dy, start, origin = self.__drag
        point = self.__image_point(event.position())
        x, y, columns, rows = start
        if (dx, dy) == (0, 0):
            x = self.__clamp(int(round(x + point.x() - origin.x())), 0,
                             self.image.width() - columns * self.tile_width)
            y = self.__clamp(int(round(y + point.y() - origin.y())), 0,
                             self.image.height() - rows * self.tile_height)
        else:
            x, columns = self.__resize(dx, x, columns, point.x(),
                                       self.tile_width, self.image.width())
            y, rows = self.__resize(dy, y, rows, point.y(),
                                    self.tile_height, self.image.height())
        self.region_x, self.region_y = x, y
        self.columns, self.rows = columns, rows
        self.__emit()

    def mouseReleaseEvent(self, event) -> None:                 # noqa: N802
        if event.button() == Qt.LeftButton:
            self.__drag = None

    @staticmethod
    def __resize(edge: int, start: int, count: int, position: float,
                 size: int, limit: int) -> tuple[int, int]:
        """One axis of a handle drag, in whole tiles off the band's own grid.

        Snapping to the BAND's grid rather than the image's is what keeps a
        pixel offset through a resize: a band three pixels in stays three
        pixels in however its right edge moves.
        """
        if edge == 0:
            return start, count
        if edge > 0:
            wanted = int(round((position - start) / size))
            room = (limit - start) // size
            return start, max(1, min(wanted, room))
        steps = int(round((position - start) / size))
        steps = max(-(start // size), min(steps, count - 1))
        return start + steps * size, count - steps

    @staticmethod
    def __clamp(value: int, low: int, high: int) -> int:
        return max(low, min(value, max(low, high)))

    def __emit(self) -> None:
        self.update()
        self.region_changed.emit(self.region_x, self.region_y,
                                 self.columns, self.rows)


def _choose_image_file(parent: QWidget | None, start: str) -> str:
    """Ask the platform for one image path, or "" if the author cancelled.

    THE TITLE AND THE FILTER ARE THIS MODULE'S, THE WINDOW IS `ask.py`'S.
    That split is the whole reason this two-line adapter still exists: the
    dialog seam owns "how a file is picked" for the whole editor, and only
    this file knows that the thing being picked is a tileset sheet.

    Held as `self.choose_file` by the dialog, never called through this
    name, so replacing the attribute replaces the picker for one widget --
    the seam `ask.confirm` and `MapCanvas.popup_menu` already are. Its own
    signature is `(parent, start)` rather than `ask.choose_file`'s four
    arguments, because a check substituting it should not have to restate a
    title and a filter it has no opinion about.
    """
    return choose_file(parent, "Choose a tileset image", start, IMAGE_FILTER)


class TilesetImportDialog(QDialog):
    """Select tiles out of an image and add them as a named tileset.

    Non-modal, and it stays open after an import: `map_dir` is the directory
    of the .tmx the tileset is going into, and it is required rather than
    optional -- without it there is no way to write a portable
    `<image source>`, and a view that guessed would produce a map that opens
    only on the machine that made it.
    """

    imported = Signal(object)          # a TilesetImport, on every Add

    def __init__(self, map_dir: str, *,
                 tile_width: int = 16, tile_height: int = 16,
                 existing_names: Iterable[str] = (),
                 next_gid: int = 1,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.map_dir = map_dir
        self.existing_names = {str(name) for name in existing_names}
        self.next_gid = max(1, next_gid)
        #: THE FILE PICKER, as a replaceable attribute. See
        #: `_choose_image_file`: a check drives Browse by substituting this,
        #: because the shipping call blocks and a check must not (law 13).
        self.choose_file: Callable[[QWidget | None, str], str] = \
            _choose_image_file
        self.setWindowTitle("Add tiles")
        self.setMinimumWidth(520)
        # A real window rather than a sheet stapled to the editor, so the map
        # stays visible and reachable while a region is being chosen. Same
        # shape as the Database window, for the same reason.
        self.setWindowFlag(Qt.Window, True)

        # Measured from the chosen image; 0 until one of them is readable.
        self.image: QImage | None = None
        self.image_path = ""
        self.image_width = 0
        self.image_height = 0
        #: Why the last Add could not be written, or "". Shown in the summary
        #: rather than in a box: a refusal on a routine path is a message.
        self.refusal = ""
        # The name auto-fills from the file stem, but only while the user has
        # not typed one. Overwriting a typed name on every browse is the kind
        # of helpfulness that loses work.
        self.__name_is_mine = True
        # Likewise the count: it follows columns x rows until the author
        # lowers it, which is the only way to say "truncate".
        self.__count_is_mine = True
        self.__updating = False

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Drag out the tiles you want. Move the selection to offset it, "
            "drag a handle to resize it, and lower the tile count to cut a "
            "ragged end off. A selection that is not the whole sheet is "
            "written out as its own image.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: palette(mid);")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.path_field = QLineEdit()
        self.path_field.setPlaceholderText("path to the tileset image")
        self.browse_button = QPushButton("Browse...")
        picker = QHBoxLayout()
        picker.setContentsMargins(0, 0, 0, 0)
        picker.addWidget(self.path_field, 1)
        picker.addWidget(self.browse_button)
        holder = QWidget()
        holder.setLayout(picker)
        form.addRow("Image", holder)

        self.name_field = QLineEdit()
        self.name_field.setPlaceholderText("tileset name, unique in this map")
        form.addRow("Name", self.name_field)

        self.tile_width_spin = self.__spin(1, 4096, tile_width, " px")
        self.tile_height_spin = self.__spin(1, 4096, tile_height, " px")
        form.addRow("Tile size", self.__pair(self.tile_width_spin,
                                             self.tile_height_spin))

        self.x_spin = self.__spin(0, 1 << 16, 0, " px")
        self.y_spin = self.__spin(0, 1 << 16, 0, " px")
        form.addRow("Offset", self.__pair(self.x_spin, self.y_spin))

        self.columns_spin = self.__spin(1, 1024, 1, "")
        self.rows_spin = self.__spin(1, 1024, 1, "")
        form.addRow("Columns x rows", self.__pair(self.columns_spin,
                                                  self.rows_spin))

        self.count_spin = self.__spin(1, 1 << 20, 1, " tiles")
        self.count_spin.setToolTip(
            "lower this to drop a ragged end; the last row is then short")
        form.addRow("Tiles", self.count_spin)
        layout.addLayout(form)

        self.preview = GridPreview()
        layout.addWidget(self.preview, 1)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add tiles")
        self.add_button.setDefault(True)
        self.close_button = QPushButton("Close")
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.add_button)
        layout.addLayout(buttons)

        # Every connection AFTER every widget exists. `refresh` reads the
        # preview, the summary and the buttons, so a signal that fired
        # mid-construction would reach a handler whose widgets were not
        # built yet.
        self.path_field.textChanged.connect(self.__on_path_changed)
        self.name_field.textEdited.connect(self.__on_name_edited)
        self.name_field.textChanged.connect(lambda _t: self.refresh())
        self.browse_button.clicked.connect(self.__browse)
        for spin in (self.tile_width_spin, self.tile_height_spin,
                     self.x_spin, self.y_spin,
                     self.columns_spin, self.rows_spin):
            spin.valueChanged.connect(self.__on_field_changed)
        self.count_spin.valueChanged.connect(self.__on_count_edited)
        self.preview.region_changed.connect(self.__on_region_dragged)
        self.add_button.clicked.connect(self.commit)
        self.close_button.clicked.connect(self.close)

        self.refresh()

    # -- building ----------------------------------------------------------

    @staticmethod
    def __spin(low: int, high: int, value: int, suffix: str) -> QSpinBox:
        box = QSpinBox()
        box.setRange(low, high)
        box.setValue(value)
        box.setSuffix(suffix)
        return box

    @staticmethod
    def __pair(first: QWidget, second: QWidget) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(first, 1)
        row.addWidget(second, 1)
        holder = QWidget()
        holder.setLayout(row)
        return holder

    # -- input -------------------------------------------------------------

    def __browse(self) -> None:
        """Browse: ask through the seam, and do nothing on a cancel.

        A cancelled picker returns "", and clearing the path field on it
        would throw away a sheet the author had already loaded because they
        opened the picker and changed their mind.
        """
        chosen = self.choose_file(self, self.map_dir)
        if chosen:
            self.set_image_path(chosen)

    def set_image_path(self, path: str) -> None:
        """Point at a sheet.

        Separate from the file dialog so the same path can be driven by a
        check, a drag-and-drop, or a recent-files entry without any of them
        having to reimplement the reload.
        """
        self.path_field.setText(path)

    def select_region(self, x: int, y: int, columns: int, rows: int) -> None:
        """Set the selection outright, the way a drag would.

        The one entry point a check needs, and the one a future
        drag-and-drop would use: everything the mouse does ends here.
        """
        self.__updating = True
        self.x_spin.setValue(x)
        self.y_spin.setValue(y)
        self.columns_spin.setValue(columns)
        self.rows_spin.setValue(rows)
        self.__updating = False
        self.refresh()

    def __on_path_changed(self, text: str) -> None:
        self.image_path = text
        if self.__name_is_mine:
            self.name_field.setText(os.path.splitext(os.path.basename(text))[0])
        self.__load_image()
        self.__select_whole_sheet()

    def __on_name_edited(self, _text: str) -> None:
        # textEdited, not textChanged: this must fire for a human typing and
        # NOT for the auto-fill above, or the first browse would permanently
        # disable the auto-fill it had just performed.
        self.__name_is_mine = False

    def __on_field_changed(self, _value: int) -> None:
        if not self.__updating:
            self.refresh()

    def __on_count_edited(self, _value: int) -> None:
        if self.__updating:
            return
        self.__count_is_mine = False
        self.refresh()

    def __on_region_dragged(self, x: int, y: int, columns: int, rows: int) -> None:
        self.select_region(x, y, columns, rows)

    def __load_image(self) -> None:
        self.image = None
        self.image_width = 0
        self.image_height = 0
        if not self.image_path or not os.path.isfile(self.image_path):
            return
        loaded = QImage(self.image_path)
        if loaded.isNull():
            return
        self.image = loaded
        self.image_width = loaded.width()
        self.image_height = loaded.height()

    def __select_whole_sheet(self) -> None:
        """The default selection: everything, cut at the current tile size.

        Deliberately the same tileset a straight "import this sheet" would
        have produced, so the region machinery costs the common case
        nothing -- and a whole-sheet selection writes no crop at all.
        """
        columns, rows, _count = tileset_geometry(
            self.image_width, self.image_height,
            self.tile_width_spin.value(), self.tile_height_spin.value(), 0, 0)
        self.__count_is_mine = True
        self.select_region(0, 0, max(1, columns), max(1, rows))

    # -- geometry ----------------------------------------------------------

    @property
    def region_columns(self) -> int:
        """Columns that fit between the offset and the right edge."""
        return max(0, (self.image_width - self.x_spin.value())
                   // self.tile_width_spin.value())

    @property
    def region_rows(self) -> int:
        return max(0, (self.image_height - self.y_spin.value())
                   // self.tile_height_spin.value())

    def refresh(self) -> None:
        """Recompute the selection and everything that shows it.

        Public, and the only place the numbers are derived, so a headless
        check can set the fields, call this, and read the same values the
        user would see -- without a window ever being shown.
        """
        self.__updating = True
        try:
            columns = min(self.columns_spin.value(), max(1, self.region_columns))
            rows = min(self.rows_spin.value(), max(1, self.region_rows))
            self.columns_spin.setValue(columns)
            self.rows_spin.setValue(rows)
            full = columns * rows
            self.count_spin.setMaximum(max(1, full))
            if self.__count_is_mine or self.count_spin.value() > full:
                self.count_spin.setValue(max(1, full))
        finally:
            self.__updating = False

        self.preview.describe(self.image, self.tile_width_spin.value(),
                              self.tile_height_spin.value(),
                              self.x_spin.value(), self.y_spin.value(),
                              columns, rows)
        self.summary.setText(self.summary_text())
        self.add_button.setEnabled(self.problem() is None)

    @property
    def columns(self) -> int:
        return self.columns_spin.value()

    @property
    def rows(self) -> int:
        return self.rows_spin.value()

    @property
    def tile_count(self) -> int:
        return self.count_spin.value()

    @property
    def whole_sheet(self) -> bool:
        """Does the selection claim the entire image, untruncated?

        The one case that needs no crop: the source file already IS the
        sheet, so declaring it directly costs nothing and duplicates
        nothing.
        """
        return (self.x_spin.value() == 0 and self.y_spin.value() == 0
                and self.columns * self.tile_width_spin.value() == self.image_width
                and self.rows * self.tile_height_spin.value() == self.image_height
                and self.tile_count == self.columns * self.rows)

    def crop_path(self) -> str:
        """Where a cropped selection would be written, absolutely."""
        return os.path.join(self.map_dir, CROP_DIR,
                            f"{safe_stem(self.name_field.text())}.png")

    def problem(self) -> str | None:
        """Why this cannot be imported yet, or None when it can.

        Every one of these would be refused by `MapDocument.add_tileset`
        anyway. Answering here as well is not a second copy of the rule --
        it is the difference between a greyed-out button and a rolled-back
        transaction with a traceback in it.
        """
        if not self.image_path:
            return "Choose a tileset image."
        if not os.path.isfile(self.image_path):
            return f"{self.image_path} does not exist."
        if self.image is None:
            return (f"Qt cannot decode {os.path.basename(self.image_path)}; "
                    f"convert it to PNG.")
        name = self.name_field.text().strip()
        if not name:
            return "The tileset needs a name."
        if name in self.existing_names:
            return f"This map already has a tileset named {name!r}."
        if not safe_stem(name):
            return (f"{name!r} has no letters or digits in it, so there is no "
                    f"filename to write a cropped sheet to.")
        if self.region_columns < 1 or self.region_rows < 1:
            return (f"A {self.tile_width_spin.value()}x"
                    f"{self.tile_height_spin.value()} tile does not fit "
                    f"between the offset and the edge of a "
                    f"{self.image_width}x{self.image_height} image.")
        if self.refusal:
            return self.refusal
        return None

    def summary_text(self) -> str:
        """One line naming the cut, the gids, and the leftover pixels."""
        blocked = self.problem()
        if blocked is not None:
            return blocked
        used_width = self.x_spin.value() + self.columns * self.tile_width_spin.value()
        used_height = self.y_spin.value() + self.rows * self.tile_height_spin.value()
        last = self.next_gid + self.tile_count - 1
        text = (f"x={self.x_spin.value()} y={self.y_spin.value()}  ·  "
                f"{self.columns} x {self.rows} = {self.tile_count} tiles  ·  "
                f"gids {self.next_gid}–{last}")
        dropped = self.columns * self.rows - self.tile_count
        if dropped:
            text += f"  ({dropped} dropped off the end)"
        # Named rather than hidden. Leftover pixels are the symptom of a tile
        # size that is off by one, and they are invisible in the tilecount,
        # which stays a believable number either way -- 64px at 15 is still
        # "4 columns".
        #
        # ONLY A PARTIAL TILE'S WORTH, though: a selection that deliberately
        # stops short leaves whole tiles over, and reporting those as
        # "claimed by no tile" every time would train the author to ignore
        # the one message that catches a 16px sheet cut at 15.
        spare = []
        right = self.image_width - used_width
        below = self.image_height - used_height
        if 0 < right < self.tile_width_spin.value():
            spare.append(f"{right} px to the right")
        if 0 < below < self.tile_height_spin.value():
            spare.append(f"{below} px below")
        if spare:
            text += "  (" + " and ".join(spare) + " claimed by no tile)"
        return text

    # -- the answer --------------------------------------------------------

    def value(self) -> TilesetImport | None:
        """What the user asked for, or None while it is not importable.

        Not called `result()`: QDialog already owns that name, and there it
        means accepted-or-rejected. The image path is the SOURCE while the
        whole sheet is selected and the crop's path otherwise -- so what
        this returns is always what the file will name.
        """
        if self.problem() is not None:
            return None
        cropped = not self.whole_sheet
        image = (self.crop_path() if cropped else self.image_path)
        tile_width = self.tile_width_spin.value()
        tile_height = self.tile_height_spin.value()
        return TilesetImport(
            name=self.name_field.text().strip(),
            image=relative_image_path(image, self.map_dir),
            tile_width=tile_width,
            tile_height=tile_height,
            image_width=(self.columns * tile_width if cropped
                         else self.image_width),
            image_height=(self.rows * tile_height if cropped
                          else self.image_height),
            columns=self.columns,
            rows=self.rows,
            tile_count=self.tile_count,
            region_x=self.x_spin.value(),
            region_y=self.y_spin.value(),
            cropped=cropped,
        )

    def region_rect(self) -> QRect:
        """The selected pixels of the SOURCE image."""
        return QRect(self.x_spin.value(), self.y_spin.value(),
                     self.columns * self.tile_width_spin.value(),
                     self.rows * self.tile_height_spin.value())

    def commit(self) -> TilesetImport | None:
        """Materialise the selection and emit it. Does not close.

        The crop happens HERE and not in the command, because a Command
        carries plain data and re-running one on replay must not depend on
        an image the author has since moved. By the time `imported` fires,
        the file the tileset names is on disk at the size the tmx will
        declare -- which is what pytmx requires to open the map at all.
        """
        request = self.value()
        if request is None:
            return None
        if request.cropped and self.image is not None:
            try:
                write_region(self.image, self.region_rect(), self.crop_path())
            except OSError as exc:
                self.refusal = str(exc)
                self.refresh()
                return None
        self.refusal = ""
        self.imported.emit(request)
        return request

    def set_name(self, name: str) -> None:
        """Name it the way a human does: this sticks, and auto-fill stops."""
        self.__name_is_mine = False
        self.name_field.setText(name)

    def known_names(self, names: Iterable[str], *,
                    next_gid: int | None = None) -> None:
        """What the map holds NOW, and where its gids start.

        Pushed in by the window after every command rather than
        accumulated here, so the duplicate-name refusal and the gid readout
        follow an UNDO as well as an add. A view that only learned about
        its own imports would go on refusing a name the author had just
        taken back.

        The name is re-derived only while the author has never typed one --
        otherwise their word stands and the button greys with the reason.
        """
        self.existing_names = {str(name) for name in names}
        if next_gid is not None:
            self.next_gid = max(1, int(next_gid))
        if self.__name_is_mine:
            self.name_field.setText(self.__free_name())
        self.refresh()

    def __free_name(self) -> str:
        """The file's own stem, numbered up until the map has no such name."""
        stem = os.path.splitext(os.path.basename(self.image_path))[0]
        candidate, index = stem, 2
        while candidate and candidate in self.existing_names:
            candidate, index = f"{stem}-{index}", index + 1
        return candidate

    @staticmethod
    def open_for(map_dir: str, *, on_import: Callable[[TilesetImport], None],
                 tile_width: int = 16, tile_height: int = 16,
                 existing_names: Iterable[str] = (),
                 next_gid: int = 1,
                 parent: QWidget | None = None) -> "TilesetImportDialog":
        """Show the view NON-MODALLY and hand every Add to `on_import`.

        The whole interaction in one call, so the menu action stays three
        lines. It returns the view rather than an answer, because there is
        no single answer any more: the author adds a region, keeps the
        window, and adds another.
        """
        view = TilesetImportDialog(map_dir, tile_width=tile_width,
                                   tile_height=tile_height,
                                   existing_names=existing_names,
                                   next_gid=next_gid, parent=parent)
        # Freed on close rather than kept as a hidden child of the editor:
        # this is opened and closed repeatedly, and a parented QDialog that
        # is merely hidden accumulates one per open for the session.
        view.setAttribute(Qt.WA_DeleteOnClose, True)
        view.imported.connect(on_import)
        view.show()
        view.raise_()
        view.activateWindow()
        return view
