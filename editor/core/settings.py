"""Editor preferences.

Small on purpose. These are the things that are about the PERSON using the
editor rather than about the project -- which theme, which IDE, whether to
confirm before applying an AI response. Anything that describes the game
belongs in the project or the genre pack, not here, and the fastest way to
make a settings dialog useless is to let those two mix.

Stored through `QSettings`, so the location is whatever the platform expects
(the registry on Windows, a plist on macOS, an ini on Linux) and there is no
path for this module to invent or get wrong.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ORGANISATION = "Pyoneer"
APPLICATION = "PyoneerEditor"


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    type: str                      # str | bool | int
    default: Any
    doc: str
    choices: tuple[tuple[str, str], ...] = ()   # (value, label)


SETTINGS: tuple[Setting, ...] = (
    Setting("theme", "Theme", "str", "system",
            "Dark switches to Qt's Fusion style, because the native Windows "
            "style ignores a custom palette and would leave half the window "
            "light.",
            choices=(("system", "Follow the system"),
                     ("light", "Light"),
                     ("dark", "Dark"))),
    Setting("ide", "Preferred IDE", "str", "",
            "Which editor 'open in my IDE' uses. Empty means the best one "
            "found -- detection reads JetBrains Toolbox and known install "
            "locations before falling back to PATH."),
    Setting("show_grid", "Show the tile grid", "bool", True,
            "Draws cell boundaries over the map."),
    Setting("grid_step", "Grid line every", "int", 1,
            "How far apart the grid lines are, counted in the cells a "
            "click actually addresses. A line is only ever drawn ON a real "
            "boundary, so the grid can be COARSER than the paint cell but "
            "never finer -- a finer grid would show cells no click can "
            "reach, which is worse than no grid at all.",
            choices=(("1", "Every cell"),
                     ("2", "Every 2 cells"),
                     ("4", "Every 4 cells"),
                     ("8", "Every 8 cells"))),
    Setting("snap_objects", "Snap objects to the grid", "bool", True,
            "Whether placing or dragging an object on an object layer lands "
            "it on a cell boundary. ON by default because a tile-sized body "
            "half a pixel off its cell is invisible on screen and wrong "
            "everywhere it matters -- the spawn's cell, the collision cell "
            "it stands in, and the .tmx diff, which grows a line per object "
            "for a drag nobody meant. Turn it off for the objects that are "
            "not tile-shaped: a trigger region, a spawn point, a light. It "
            "is read by `EditorWindow.__new_canvas` and written onto "
            "`MapCanvas.snap_objects`, the same way the grid preferences "
            "are, so it follows the map the window switches to."),
    Setting("collision_subcell", "New collision layers are", "int", 1,
            "How finely a passability layer CREATED by the next collision "
            "stroke divides one map tile, per axis. It is the resolution the "
            "brush addresses too, so a mask still lands under the cursor. "
            "It changes nothing about a companion that already exists -- "
            "there is no verb to re-scale one -- so decide before the first "
            "stroke. The default is 1 because finer is not free: measured on "
            "a 100x100 map, 4x is 8.6x the file bytes and +271ms per "
            "companion at load.",
            choices=(("1", "1 x 1 per tile — one mask per tile"),
                     ("2", "2 x 2 per tile"),
                     ("4", "4 x 4 per tile — sixteen masks per tile"),
                     ("8", "8 x 8 per tile"),
                     ("16", "16 x 16 per tile — one mask per pixel "
                            "on a 16px tile"))),
    Setting("confirm_response", "Confirm before applying an AI response",
            "bool", True,
            "Untick to apply a response as soon as it arrives. It is still "
            "one undoable transaction either way."),
)

BY_KEY = {setting.key: setting for setting in SETTINGS}


class EditorSettings:
    """Typed access to the stored preferences."""

    def __init__(self, backend=None):
        if backend is None:
            from PySide6.QtCore import QSettings
            backend = QSettings(ORGANISATION, APPLICATION)
        self._backend = backend

    def get(self, key: str) -> Any:
        setting = BY_KEY.get(key)
        if setting is None:
            raise KeyError(f"unknown setting {key!r}; "
                           f"known: {sorted(BY_KEY)}")
        raw = self._backend.value(setting.key, setting.default)
        return self.__coerce(setting, raw)

    def set(self, key: str, value: Any) -> None:
        setting = BY_KEY.get(key)
        if setting is None:
            raise KeyError(f"unknown setting {key!r}")
        self._backend.setValue(setting.key, self.__coerce(setting, value))

    def reset(self) -> None:
        for setting in SETTINGS:
            self._backend.remove(setting.key)

    def as_dict(self) -> dict[str, Any]:
        return {setting.key: self.get(setting.key) for setting in SETTINGS}

    @staticmethod
    def __coerce(setting: Setting, raw: Any) -> Any:
        # QSettings round-trips through strings on some backends, so "false"
        # comes back truthy unless it is handled. That is the classic way a
        # boolean preference silently stops working.
        if setting.type == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "yes", "on")
        if setting.type == "int":
            try:
                number = int(raw)
            except (TypeError, ValueError):
                return setting.default
            # An int setting is validated against `choices` here, not only on
            # the str branch below: a stored 0 would otherwise come straight
            # back, and 0 is a ZeroDivisionError in the code that divides a
            # pixel by a cell size.
            if setting.choices and str(number) not in [c for c, _l in setting.choices]:
                return setting.default
            return number
        value = "" if raw is None else str(raw)
        if setting.choices and value not in [c for c, _l in setting.choices]:
            return setting.default
        return value
