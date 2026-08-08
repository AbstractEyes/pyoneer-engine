"""Light and dark palettes for the editor.

WHY A PALETTE AND NOT A STYLESHEET
----------------------------------
Everything in this editor that draws its own pixels -- the tool icons, the
inspector's muted labels, the canvas surround -- reads `QPalette`. A
stylesheet would restyle the widgets and leave all of that stranded, so the
theme is a palette and the drawing code asks the palette. Change it in one
place and the icons re-ink themselves.

THE FUSION DETAIL
-----------------
On Windows the native style renders through the OS theme and largely
IGNORES a custom palette, so setting a dark palette under it produces a
half-dark window with white text on white buttons. `QStyle("Fusion")` is the
cross-platform style that actually honours the palette, so a dark theme has
to switch to it. Light mode goes back to the native style, because a native
light window is better than an imitation of one.
"""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

_NATIVE_STYLE: str | None = None


class Theme(Enum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"

    @property
    def label(self) -> str:
        return {Theme.SYSTEM: "Follow the system",
                Theme.LIGHT: "Light",
                Theme.DARK: "Dark"}[self]

    @classmethod
    def parse(cls, text: str) -> "Theme":
        for member in cls:
            if member.value == str(text).lower():
                return member
        return cls.SYSTEM


# Canvas surround, per theme. Deliberately dark-ish in both: a tile editor
# wants the map to be the brightest thing on screen, which is why Tiled and
# Aseprite both keep a dark surround in light mode.
CANVAS_BACKGROUND = {
    Theme.LIGHT: QColor(96, 98, 104),
    Theme.DARK: QColor(28, 28, 32),
}


def dark_palette() -> QPalette:
    palette = QPalette()
    base = QColor(30, 31, 34)
    surface = QColor(43, 45, 49)
    text = QColor(226, 227, 232)
    accent = QColor(70, 145, 230)

    palette.setColor(QPalette.Window, surface)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, base)
    palette.setColor(QPalette.AlternateBase, QColor(37, 39, 43))
    palette.setColor(QPalette.ToolTipBase, surface)
    palette.setColor(QPalette.ToolTipText, text)
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.Button, surface)
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.BrightText, QColor(255, 110, 110))
    palette.setColor(QPalette.Link, accent)
    palette.setColor(QPalette.Highlight, accent)
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.PlaceholderText, QColor(140, 143, 150))
    # `Mid` is what the inspector's secondary labels use, so it has to stay
    # legible rather than fading into the surface.
    palette.setColor(QPalette.Mid, QColor(148, 151, 158))
    palette.setColor(QPalette.Dark, QColor(22, 23, 26))

    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(120, 122, 128))
    return palette


def light_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(240, 240, 240))
    palette.setColor(QPalette.WindowText, QColor(28, 30, 34))
    palette.setColor(QPalette.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.AlternateBase, QColor(246, 246, 248))
    palette.setColor(QPalette.Text, QColor(28, 30, 34))
    palette.setColor(QPalette.Button, QColor(240, 240, 240))
    palette.setColor(QPalette.ButtonText, QColor(28, 30, 34))
    palette.setColor(QPalette.Highlight, QColor(60, 130, 220))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.PlaceholderText, QColor(140, 143, 150))
    palette.setColor(QPalette.Mid, QColor(120, 123, 130))
    return palette


def resolve(theme: Theme) -> Theme:
    """SYSTEM into a concrete choice, using Qt's own scheme hint."""
    if theme is not Theme.SYSTEM:
        return theme
    try:
        from PySide6.QtGui import QGuiApplication
        hint = QGuiApplication.styleHints()
        # colorScheme() is Qt 6.5+. Anything older falls back to light,
        # which is the safe guess: a light theme on a dark desktop is
        # merely bright, while dark-on-light is unreadable.
        scheme = hint.colorScheme() if hasattr(hint, "colorScheme") else None
        if scheme is not None and int(scheme) == int(Qt.ColorScheme.Dark):
            return Theme.DARK
    except Exception:                                           # noqa: BLE001
        pass
    return Theme.LIGHT


def apply(application, theme: Theme) -> Theme:
    """Apply a theme. Returns the concrete theme that was applied."""
    global _NATIVE_STYLE
    if _NATIVE_STYLE is None:
        _NATIVE_STYLE = application.style().objectName()

    concrete = resolve(theme)
    if concrete is Theme.DARK:
        application.setStyle("Fusion")
        application.setPalette(dark_palette())
    else:
        application.setStyle(_NATIVE_STYLE or "Fusion")
        application.setPalette(light_palette())

    # Icons ink themselves from the palette and are cached, so the cache has
    # to go or the toolbar keeps yesterday's colour.
    from editor.ui import icons
    icons.clear_cache()
    return concrete
