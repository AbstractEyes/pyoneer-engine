"""Import a tileset: pick a sheet, cut it into a grid, see the grid first.

WHY A PREVIEW EARNS ITS CODE
----------------------------
Tile size, margin and spacing are four numbers that are each individually
plausible and jointly wrong, and the file they land in gives no feedback at
all. A 16px sheet cut at 15 produces perfectly legal TMX: correct schema,
correct tilecount, and every tile carrying a one-pixel seam of its
neighbour. Nothing raises, in Tiled or in the engine. Drawing the proposed
grid over the actual pixels is the only cheap way to see that BEFORE a map
is authored against it -- and once tiles are painted, changing the grid
means renumbering every gid, which `MapDocument.add_tileset` refuses to do
on principle.

THE NUMBERS ARE NOT COMPUTED HERE
---------------------------------
`tileset_geometry` is the function `MapDocument.add_tileset` itself uses to
write `columns` and `tilecount`, so this dialog imports it rather than
dividing width by tile width. The naive division is only correct at margin
0 and spacing 0, and a second implementation of the corrected form would
drift from the first the moment either changed. What the preview shows and
what the file records come from one function by construction.

WHY QImage AND NOT image_size()
-------------------------------
`scripts.loaders.map_document.image_size` reads PNG headers by hand, and
deliberately: `scripts/` may never import `editor/`, so the engine side
cannot reach for Qt to learn two integers. The editor has no such
constraint, and someone importing art will hand it a .bmp or a .jpg sooner
or later. So this side asks Qt and passes the measured width and height
into the command explicitly -- which is also what keeps the engine from
ever having to open the image at all.

THIS DIALOG APPLIES NOTHING
---------------------------
It returns a `TilesetImport` and stops. Every change to a map goes through
a Command, and a dialog that wrote to the document directly would be the
one edit in the editor with no inverse, no history entry and nothing for a
human to review.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
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

# Offered as a filter, not enforced. An unreadable file is caught by QImage
# handing back a null image, which is a real test; a file extension is not.
IMAGE_FILTER = ("Tileset images (*.png *.bmp *.jpg *.jpeg *.gif *.tga *.webp)"
                ";;All files (*)")


@dataclass(frozen=True)
class TilesetImport:
    """What the user asked for, as plain data.

    Frozen and Qt-free on purpose. This is what crosses from the view layer
    into a Command, and anything carrying a widget across that line would
    make the command stream un-replayable.
    """

    name: str
    image: str                  # relative to the .tmx, forward slashes
    tile_width: int
    tile_height: int
    margin: int
    spacing: int
    image_width: int
    image_height: int
    columns: int
    rows: int
    tile_count: int

    def command_args(self) -> dict[str, Any]:
        """Arguments for `map.tileset.add`.

        A dict rather than a Command: constructing one and running it
        through the session is the caller's job, and this module
        deliberately cannot do it. `columns` and `tile_count` are handed
        over explicitly so the file records exactly the grid the user was
        shown, even though the document would derive the same pair itself.
        """
        return {
            "name": self.name,
            "image": self.image,
            "tile_width": self.tile_width,
            "tile_height": self.tile_height,
            "margin": self.margin,
            "spacing": self.spacing,
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


class GridPreview(QWidget):
    """The sheet with the proposed cut drawn over it.

    Scaled to fit rather than shown 1:1, because a 512x512 sheet inside a
    modal dialog is most of a laptop screen. One rectangle per tile rather
    than a continuous lattice, because with spacing > 0 the gaps between
    tiles are pixels that belong to no tile -- and a lattice would draw
    straight through them and hide exactly the mistake worth seeing.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.image: QImage | None = None
        self.tile_width = 16
        self.tile_height = 16
        self.margin = 0
        self.spacing = 0
        self.columns = 0
        self.rows = 0
        self.setMinimumSize(280, 200)

    def describe(self, image: QImage | None, tile_width: int, tile_height: int,
                 margin: int, spacing: int, columns: int, rows: int) -> None:
        self.image = image
        self.tile_width = tile_width
        self.tile_height = tile_height
        self.margin = margin
        self.spacing = spacing
        self.columns = columns
        self.rows = rows
        self.update()

    def paintEvent(self, event) -> None:                        # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        if self.image is None or self.image.isNull():
            painter.setPen(self.palette().mid().color())
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "choose an image to see the grid")
            painter.end()
            return

        area = self.rect().adjusted(6, 6, -6, -6)
        scale = min(area.width() / self.image.width(),
                    area.height() / self.image.height(), 1.0)
        width = self.image.width() * scale
        height = self.image.height() * scale
        left = area.x() + (area.width() - width) / 2
        top = area.y() + (area.height() - height) / 2
        painter.drawImage(QRectF(left, top, width, height), self.image)

        # The image's own edge, so unclaimed pixels down the right or bottom
        # read as a gap between the last tile and the border.
        painter.setPen(QPen(QColor(255, 255, 255, 90), 0))
        painter.drawRect(QRectF(left, top, width, height))

        painter.setPen(QPen(QColor(0, 190, 255, 170), 0))
        step_x = self.tile_width + self.spacing
        step_y = self.tile_height + self.spacing
        for row in range(self.rows):
            for column in range(self.columns):
                painter.drawRect(QRectF(
                    left + (self.margin + column * step_x) * scale,
                    top + (self.margin + row * step_y) * scale,
                    self.tile_width * scale, self.tile_height * scale))
        painter.end()


class TilesetImportDialog(QDialog):
    """Collect one embedded tileset's declaration. Applies nothing.

    `map_dir` is the directory of the .tmx the tileset is going into, and
    it is required rather than optional: without it there is no way to
    write a portable `<image source>`, and a dialog that guessed would
    produce a map that opens only on the machine that made it.
    """

    def __init__(self, map_dir: str, *,
                 tile_width: int = 16, tile_height: int = 16,
                 existing_names: Iterable[str] = (),
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.map_dir = map_dir
        self.existing_names = {str(name) for name in existing_names}
        self.setWindowTitle("Import tileset")
        self.setMinimumWidth(520)

        # Measured from the chosen image; 0 until one of them is readable.
        self.image: QImage | None = None
        self.image_path = ""
        self.image_width = 0
        self.image_height = 0
        self.columns = 0
        self.rows = 0
        self.tile_count = 0
        # The name auto-fills from the file stem, but only while the user has
        # not typed one. Overwriting a typed name on every browse is the kind
        # of helpfulness that loses work.
        self.__name_is_mine = True

        layout = QVBoxLayout(self)
        intro = QLabel(
            "The sheet is cut into a grid and appended above every gid this "
            "map already uses. Tile size, margin and spacing cannot be "
            "changed afterwards without renumbering every painted tile, so "
            "check the preview.")
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

        self.tile_width_spin = self.__spin(1, 4096, tile_width)
        self.tile_height_spin = self.__spin(1, 4096, tile_height)
        self.margin_spin = self.__spin(0, 512, 0)
        self.spacing_spin = self.__spin(0, 512, 0)
        form.addRow("Tile width", self.tile_width_spin)
        form.addRow("Tile height", self.tile_height_spin)
        form.addRow("Margin", self.margin_spin)
        form.addRow("Spacing", self.spacing_spin)
        layout.addLayout(form)

        self.preview = GridPreview()
        layout.addWidget(self.preview, 1)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Add tileset")
        layout.addWidget(self.buttons)

        # Every connection AFTER every widget exists. `refresh` reads the
        # preview, the summary and the button box, so a signal that fired
        # mid-construction would reach a handler whose widgets were not
        # built yet.
        self.path_field.textChanged.connect(self.__on_path_changed)
        self.name_field.textEdited.connect(self.__on_name_edited)
        self.name_field.textChanged.connect(lambda _t: self.refresh())
        self.browse_button.clicked.connect(self.__browse)
        for spin in (self.tile_width_spin, self.tile_height_spin,
                     self.margin_spin, self.spacing_spin):
            spin.valueChanged.connect(lambda _v: self.refresh())
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        self.refresh()

    # -- building ----------------------------------------------------------

    @staticmethod
    def __spin(low: int, high: int, value: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(low, high)
        box.setValue(value)
        box.setSuffix(" px")
        return box

    # -- input -------------------------------------------------------------

    def __browse(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(
            self, "Choose a tileset image", self.map_dir, IMAGE_FILTER)
        if chosen:
            self.set_image_path(chosen)

    def set_image_path(self, path: str) -> None:
        """Point at a sheet.

        Separate from the file dialog so the same path can be driven by a
        test, a drag-and-drop, or a recent-files entry without any of them
        having to reimplement the reload.
        """
        self.path_field.setText(path)

    def __on_path_changed(self, text: str) -> None:
        self.image_path = text
        if self.__name_is_mine:
            self.name_field.setText(os.path.splitext(os.path.basename(text))[0])
        self.__load_image()
        self.refresh()

    def __on_name_edited(self, _text: str) -> None:
        # textEdited, not textChanged: this must fire for a human typing and
        # NOT for the auto-fill above, or the first browse would permanently
        # disable the auto-fill it had just performed.
        self.__name_is_mine = False

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

    # -- geometry ----------------------------------------------------------

    def refresh(self) -> None:
        """Recompute the grid and everything that shows it.

        Public, and the only place the numbers are derived, so a headless
        check can set the fields, call this, and read the same values the
        user would see -- without a window ever being shown.
        """
        tile_width = self.tile_width_spin.value()
        tile_height = self.tile_height_spin.value()
        margin = self.margin_spin.value()
        spacing = self.spacing_spin.value()

        self.columns, self.rows, self.tile_count = tileset_geometry(
            self.image_width, self.image_height,
            tile_width, tile_height, margin, spacing)

        self.preview.describe(self.image, tile_width, tile_height,
                              margin, spacing, self.columns, self.rows)
        self.summary.setText(self.summary_text())
        accept = self.buttons.button(QDialogButtonBox.Ok)
        if accept is not None:
            accept.setEnabled(self.problem() is None)

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
        if self.tile_count <= 0:
            return (f"A {self.image_width}x{self.image_height} image cannot "
                    f"fit a single {self.tile_width_spin.value()}x"
                    f"{self.tile_height_spin.value()} tile at margin "
                    f"{self.margin_spin.value()}, spacing "
                    f"{self.spacing_spin.value()}.")
        return None

    def summary_text(self) -> str:
        """One line naming the grid, and the leftover when there is one."""
        blocked = self.problem()
        if blocked is not None:
            return blocked
        margin = self.margin_spin.value()
        spacing = self.spacing_spin.value()
        used_width = (margin + self.columns * self.tile_width_spin.value()
                      + max(0, self.columns - 1) * spacing)
        used_height = (margin + self.rows * self.tile_height_spin.value()
                       + max(0, self.rows - 1) * spacing)
        text = (f"{self.image_width}x{self.image_height} -> "
                f"{self.columns} columns x {self.rows} rows = "
                f"{self.tile_count} tiles")
        # Named rather than hidden. Leftover pixels are the symptom of a tile
        # size that is off by one, and they are invisible in the tilecount,
        # which stays a believable number either way -- 64px at 15 is still
        # "4 columns".
        spare = []
        if self.image_width - used_width:
            spare.append(f"{self.image_width - used_width} px to the right")
        if self.image_height - used_height:
            spare.append(f"{self.image_height - used_height} px below")
        if spare:
            text += "  (" + " and ".join(spare) + " claimed by no tile)"
        return text

    # -- the answer --------------------------------------------------------

    def value(self) -> TilesetImport | None:
        """What the user asked for, or None while it is not importable.

        Not called `result()`: QDialog already owns that name, and there it
        means accepted-or-rejected.
        """
        if self.problem() is not None:
            return None
        return TilesetImport(
            name=self.name_field.text().strip(),
            image=relative_image_path(self.image_path, self.map_dir),
            tile_width=self.tile_width_spin.value(),
            tile_height=self.tile_height_spin.value(),
            margin=self.margin_spin.value(),
            spacing=self.spacing_spin.value(),
            image_width=self.image_width,
            image_height=self.image_height,
            columns=self.columns,
            rows=self.rows,
            tile_count=self.tile_count,
        )

    @staticmethod
    def ask(map_dir: str, *, tile_width: int = 16, tile_height: int = 16,
            existing_names: Iterable[str] = (),
            parent: QWidget | None = None) -> TilesetImport | None:
        """Show the dialog and return the request, or None if cancelled.

        The whole interaction in one call, so the menu action stays two
        lines: ask, then hand the answer to the command stream.
        """
        dialog = TilesetImportDialog(map_dir, tile_width=tile_width,
                                     tile_height=tile_height,
                                     existing_names=existing_names,
                                     parent=parent)
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.value()
