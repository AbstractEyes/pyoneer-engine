"""Tool icons, drawn in code.

No image files: the repository ships without art on purpose, and a toolbar
that needs a PNG to be legible would be the one place that quietly stops
working on a fresh clone. These are drawn with QPainter at request time and
cached, so they cost nothing after the first paint and scale to whatever
size the toolbar asks for.

They are deliberately plain — a recognisable silhouette in one colour, no
gradients or shadows — because a 20px toolbar glyph that tries to be a
picture just becomes noise.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

_CACHE: dict[tuple[str, int, int], QIcon] = {}

_INK = QColor(228, 228, 232)
_ACCENT = QColor(120, 200, 255)


def tool_icon(name: str, size: int = 22) -> QIcon:
    """A cached icon by tool name. Unknown names get a neutral square."""
    key = (name, size, _INK.rgba())
    if key not in _CACHE:
        _CACHE[key] = _build(name, size)
    return _CACHE[key]


def _build(name: str, size: int) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    drawer = _DRAWERS.get(name, _draw_unknown)
    drawer(painter, size)
    painter.end()
    return QIcon(pixmap)


def _pen(width: float = 1.6, colour: QColor | None = None) -> QPen:
    pen = QPen(colour or _INK)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


# --------------------------------------------------------------------------
# The glyphs
# --------------------------------------------------------------------------

def _draw_brush(painter: QPainter, size: int) -> None:
    unit = size / 22.0
    painter.setPen(_pen(1.7 * unit))
    # handle
    painter.drawLine(QPointF(15 * unit, 4 * unit), QPointF(8.5 * unit, 10.5 * unit))
    # ferrule
    painter.setBrush(QBrush(_INK))
    path = QPainterPath()
    path.moveTo(8.5 * unit, 10.5 * unit)
    path.lineTo(11.5 * unit, 13.5 * unit)
    path.lineTo(7.5 * unit, 17.5 * unit)
    path.lineTo(4.5 * unit, 14.5 * unit)
    path.closeSubpath()
    painter.drawPath(path)


def _draw_rectangle(painter: QPainter, size: int) -> None:
    unit = size / 22.0
    painter.setPen(_pen(1.8 * unit))
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(QRectF(4 * unit, 5 * unit, 14 * unit, 12 * unit))


def _draw_filled_rect(painter: QPainter, size: int) -> None:
    unit = size / 22.0
    painter.setPen(_pen(1.8 * unit))
    painter.setBrush(QBrush(QColor(_INK.red(), _INK.green(), _INK.blue(), 110)))
    painter.drawRect(QRectF(4 * unit, 5 * unit, 14 * unit, 12 * unit))


def _draw_fill(painter: QPainter, size: int) -> None:
    """A tipped bucket with a drop -- the universal flood-fill glyph."""
    unit = size / 22.0
    painter.setPen(_pen(1.6 * unit))
    painter.setBrush(QBrush(QColor(_INK.red(), _INK.green(), _INK.blue(), 90)))
    bucket = QPainterPath()
    bucket.moveTo(4 * unit, 11 * unit)
    bucket.lineTo(11 * unit, 4.5 * unit)
    bucket.lineTo(17 * unit, 10.5 * unit)
    bucket.lineTo(10 * unit, 17 * unit)
    bucket.closeSubpath()
    painter.drawPath(bucket)
    painter.setBrush(QBrush(_ACCENT))
    painter.setPen(Qt.NoPen)
    drop = QPainterPath()
    drop.moveTo(18.5 * unit, 12 * unit)
    drop.cubicTo(20.5 * unit, 15 * unit, 20.5 * unit, 17.5 * unit,
                 18.5 * unit, 17.5 * unit)
    drop.cubicTo(16.5 * unit, 17.5 * unit, 16.5 * unit, 15 * unit,
                 18.5 * unit, 12 * unit)
    painter.drawPath(drop)


def _draw_eraser(painter: QPainter, size: int) -> None:
    unit = size / 22.0
    painter.setPen(_pen(1.6 * unit))
    painter.setBrush(QBrush(QColor(_INK.red(), _INK.green(), _INK.blue(), 70)))
    body = QPainterPath()
    body.moveTo(4 * unit, 14 * unit)
    body.lineTo(12 * unit, 6 * unit)
    body.lineTo(18 * unit, 12 * unit)
    body.lineTo(10 * unit, 18 * unit)
    body.closeSubpath()
    painter.drawPath(body)
    painter.setPen(_pen(1.4 * unit))
    painter.drawLine(QPointF(8 * unit, 10 * unit), QPointF(14 * unit, 16 * unit))


def _draw_picker(painter: QPainter, size: int) -> None:
    """An eyedropper."""
    unit = size / 22.0
    painter.setPen(_pen(1.7 * unit))
    painter.drawLine(QPointF(16 * unit, 5 * unit), QPointF(9 * unit, 12 * unit))
    painter.setBrush(QBrush(_INK))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(16.5 * unit, 4.5 * unit), 2.6 * unit, 2.6 * unit)
    painter.setPen(_pen(1.6 * unit, _ACCENT))
    painter.setBrush(Qt.NoBrush)
    tip = QPainterPath()
    tip.moveTo(9 * unit, 12 * unit)
    tip.lineTo(5.5 * unit, 16 * unit)
    tip.lineTo(8 * unit, 18 * unit)
    tip.lineTo(11.5 * unit, 14.5 * unit)
    tip.closeSubpath()
    painter.drawPath(tip)


def _draw_autotile(painter: QPainter, size: int) -> None:
    """Four quadrants with one corner cut -- the corner-set idea itself."""
    unit = size / 22.0
    painter.setPen(Qt.NoPen)
    solid = QColor(_INK.red(), _INK.green(), _INK.blue(), 200)
    faint = QColor(_INK.red(), _INK.green(), _INK.blue(), 70)
    cell = 6 * unit
    origin = 4 * unit
    for row in range(2):
        for column in range(2):
            filled = not (row == 0 and column == 1)
            painter.setBrush(QBrush(solid if filled else faint))
            painter.drawRect(QRectF(origin + column * cell, origin + row * cell,
                                    cell - 1.2 * unit, cell - 1.2 * unit))
    painter.setPen(_pen(1.5 * unit, _ACCENT))
    painter.setBrush(Qt.NoBrush)
    painter.drawArc(QRectF(origin + cell - 2 * unit, origin - 1 * unit,
                           7 * unit, 7 * unit), 180 * 16, 90 * 16)


def _draw_unknown(painter: QPainter, size: int) -> None:
    unit = size / 22.0
    painter.setPen(_pen(1.5 * unit))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(QRectF(5 * unit, 5 * unit, 12 * unit, 12 * unit),
                            2 * unit, 2 * unit)


_DRAWERS = {
    "brush": _draw_brush,
    "rectangle": _draw_rectangle,
    "filled_rect": _draw_filled_rect,
    "fill": _draw_fill,
    "eraser": _draw_eraser,
    "picker": _draw_picker,
    "autotile": _draw_autotile,
}


def available() -> list[str]:
    return sorted(_DRAWERS)
