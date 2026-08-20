"""Tool icons, drawn in code.

No image files: the repository ships without art on purpose, and a toolbar
that needs a PNG to be legible would be the one place that quietly stops
working on a fresh clone. These are drawn with QPainter at request time and
cached, so they cost nothing after the first paint.

TWO RULES
---------
**Ink comes from the palette, never from a constant.** A hardcoded
near-white ink is invisible on a light theme. `_ink()` reads
`QPalette.ButtonText` and pushes it to full contrast, so glyphs are dark on
a light theme and light on a dark one, and the cache is keyed on the result
so a theme change re-renders rather than serving the old colour.

**Each tool gets its own hue.** A row of seven identical grey silhouettes is
a memory test, so the bucket is blue, the eraser is pink, the picker is
teal and terrain is green -- the conventions every paint program uses.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

_CACHE: dict[tuple[str, int, int], QIcon] = {}

# Per-tool accents. Saturated enough to read at 22px against either theme.
BRUSH_WOOD = QColor(176, 118, 64)
BRUSH_TIP = QColor(74, 144, 226)
SHAPE = QColor(60, 130, 220)
BUCKET = QColor(40, 110, 200)
BUCKET_DROP = QColor(90, 190, 255)
ERASER = QColor(232, 106, 138)
PICKER = QColor(28, 178, 176)
TERRAIN = QColor(92, 176, 84)
TERRAIN_DIM = QColor(92, 176, 84, 90)


def _ink() -> QColor:
    """The outline colour: whatever this theme uses for button text, at
    full contrast. Falls back to near-black if there is no application yet
    (importing this module must not require a QApplication)."""
    application = QApplication.instance()
    if application is None:
        return QColor(32, 34, 38)
    colour = application.palette().color(QPalette.Active, QPalette.ButtonText)
    # Push toward the end of the range it is already on, so a mid-grey theme
    # still yields a glyph that reads rather than a smudge.
    if colour.lightness() > 127:
        return QColor(240, 241, 245)
    return QColor(28, 30, 34)


def tool_icon(name: str, size: int = 22) -> QIcon:
    """A cached icon by tool name. Unknown names get a neutral square."""
    ink = _ink()
    key = (name, size, ink.rgba())
    if key not in _CACHE:
        _CACHE[key] = _build(name, size, ink)
    return _CACHE[key]


def clear_cache() -> None:
    """Drop cached icons, e.g. after a palette change."""
    _CACHE.clear()


def _build(name: str, size: int, ink: QColor) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    _DRAWERS.get(name, _draw_unknown)(painter, size, ink)
    painter.end()
    return QIcon(pixmap)


def _pen(width: float, colour: QColor) -> QPen:
    pen = QPen(colour)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


# --------------------------------------------------------------------------
# The glyphs
# --------------------------------------------------------------------------

def _draw_brush(painter: QPainter, size: int, ink: QColor) -> None:
    u = size / 22.0
    painter.setPen(_pen(2.6 * u, BRUSH_WOOD))
    painter.drawLine(QPointF(16 * u, 4 * u), QPointF(9.5 * u, 10.5 * u))
    painter.setPen(_pen(1.5 * u, ink))
    painter.setBrush(QBrush(BRUSH_TIP))
    tip = QPainterPath()
    tip.moveTo(9.5 * u, 9 * u)
    tip.lineTo(13 * u, 12.5 * u)
    tip.lineTo(8 * u, 18 * u)
    tip.lineTo(4.5 * u, 14.5 * u)
    tip.closeSubpath()
    painter.drawPath(tip)


def _draw_rectangle(painter: QPainter, size: int, ink: QColor) -> None:
    u = size / 22.0
    painter.setPen(_pen(2.4 * u, SHAPE))
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(QRectF(4 * u, 5.5 * u, 14 * u, 11 * u))


def _draw_filled_rect(painter: QPainter, size: int, ink: QColor) -> None:
    u = size / 22.0
    painter.setPen(_pen(2.0 * u, SHAPE))
    painter.setBrush(QBrush(QColor(SHAPE.red(), SHAPE.green(), SHAPE.blue(), 150)))
    painter.drawRect(QRectF(4 * u, 5.5 * u, 14 * u, 11 * u))


def _draw_fill(painter: QPainter, size: int, ink: QColor) -> None:
    """A tipped bucket pouring, with a handle -- the flood-fill glyph.

    The first version was a rotated square with a small drop, which at 22px
    was indistinguishable from the rectangle tool sitting two icons away. A
    bucket needs the TAPER and the HANDLE to read as a bucket; the taper is
    what the eye actually uses.
    """
    u = size / 22.0
    painter.save()
    painter.translate(10.5 * u, 10.5 * u)
    painter.rotate(-38)
    painter.translate(-10.5 * u, -10.5 * u)

    # Handle first, so the body's outline crosses over its ends.
    painter.setPen(_pen(1.5 * u, ink))
    painter.setBrush(Qt.NoBrush)
    painter.drawArc(QRectF(5.5 * u, 1.5 * u, 10 * u, 8 * u), 0, 180 * 16)

    # Tapered body: wide mouth, narrow base.
    painter.setPen(_pen(1.5 * u, ink))
    painter.setBrush(QBrush(BUCKET))
    body = QPainterPath()
    body.moveTo(4.5 * u, 6 * u)
    body.lineTo(16.5 * u, 6 * u)
    body.lineTo(14 * u, 17.5 * u)
    body.lineTo(7 * u, 17.5 * u)
    body.closeSubpath()
    painter.drawPath(body)

    # The paint surface at the mouth, so it reads as full.
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(BUCKET_DROP))
    painter.drawEllipse(QRectF(5.2 * u, 4.2 * u, 10.6 * u, 3.4 * u))
    painter.restore()

    # A drop leaving the lip, upright in screen space.
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(BUCKET_DROP))
    drop = QPainterPath()
    drop.moveTo(17.5 * u, 12 * u)
    drop.cubicTo(20.6 * u, 15.8 * u, 20.6 * u, 19.4 * u, 17.5 * u, 19.4 * u)
    drop.cubicTo(14.4 * u, 19.4 * u, 14.4 * u, 15.8 * u, 17.5 * u, 12 * u)
    painter.drawPath(drop)


def _draw_eraser(painter: QPainter, size: int, ink: QColor) -> None:
    u = size / 22.0
    painter.setPen(_pen(1.6 * u, ink))
    painter.setBrush(QBrush(ERASER))
    body = QPainterPath()
    body.moveTo(3.5 * u, 14 * u)
    body.lineTo(11.5 * u, 5.5 * u)
    body.lineTo(18.5 * u, 12 * u)
    body.lineTo(10.5 * u, 18.5 * u)
    body.closeSubpath()
    painter.drawPath(body)
    painter.setPen(_pen(1.5 * u, ink))
    painter.drawLine(QPointF(7.6 * u, 10 * u), QPointF(14.6 * u, 16.4 * u))


def _draw_picker(painter: QPainter, size: int, ink: QColor) -> None:
    """An eyedropper."""
    u = size / 22.0
    painter.setPen(_pen(2.4 * u, PICKER))
    painter.drawLine(QPointF(15.5 * u, 5.5 * u), QPointF(9 * u, 12 * u))
    painter.setPen(_pen(1.4 * u, ink))
    painter.setBrush(QBrush(PICKER))
    painter.drawEllipse(QPointF(16.8 * u, 4.4 * u), 2.9 * u, 2.9 * u)
    painter.setBrush(QBrush(QColor(PICKER.red(), PICKER.green(),
                                   PICKER.blue(), 120)))
    tip = QPainterPath()
    tip.moveTo(9 * u, 11 * u)
    tip.lineTo(5 * u, 15.5 * u)
    tip.lineTo(7.5 * u, 18 * u)
    tip.lineTo(11.8 * u, 13.8 * u)
    tip.closeSubpath()
    painter.drawPath(tip)


def _draw_autotile(painter: QPainter, size: int, ink: QColor) -> None:
    """Four quadrants with one corner missing -- the corner-set idea itself."""
    u = size / 22.0
    cell = 6.2 * u
    origin = 4 * u
    painter.setPen(_pen(1.2 * u, ink))
    for row in range(2):
        for column in range(2):
            filled = not (row == 0 and column == 1)
            painter.setBrush(QBrush(TERRAIN if filled else TERRAIN_DIM))
            painter.drawRect(QRectF(origin + column * cell, origin + row * cell,
                                    cell - 1.0 * u, cell - 1.0 * u))
    painter.setPen(_pen(1.8 * u, BUCKET_DROP))
    painter.setBrush(Qt.NoBrush)
    painter.drawArc(QRectF(origin + cell - 2.4 * u, origin - 1.4 * u,
                           7.6 * u, 7.6 * u), 180 * 16, 90 * 16)


def _draw_unknown(painter: QPainter, size: int, ink: QColor) -> None:
    u = size / 22.0
    painter.setPen(_pen(1.8 * u, ink))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(QRectF(5 * u, 5 * u, 12 * u, 12 * u),
                            2 * u, 2 * u)


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
