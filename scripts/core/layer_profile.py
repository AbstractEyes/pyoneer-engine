"""What a map layer declares about itself, read at load time.

WHY THIS IS IN THE ENGINE
-------------------------
The editor writes these as tmx custom properties and the engine reads them,
so the names have to be shared. The dependency only runs one way -- the
editor may import `scripts/`, never the reverse -- so the vocabulary lives
here and `editor/core/layers.py` imports it. Two hand-kept copies of a
string like `pyoneer_parallax_x` would drift, and the failure would be
silent: a property written under one name and read under another simply
does nothing, which is exactly the bug this module exists to end.

THE PREFIX IS LOAD-BEARING
--------------------------
pytmx RAISES and makes the whole map unloadable if a custom property  #TAG:pyoneer_prefix_pytmx
shadows one of its own attribute names (`opacity`, `visible`, `offsetx`,
`name`, `data`, ...). `opacity` is both a natural capability name and one of
those, so everything is prefixed.
"""
from __future__ import annotations

from dataclasses import dataclass

PREFIX = "pyoneer_"

DEPTH = PREFIX + "depth"
MOTION = PREFIX + "motion"
PARALLAX_X = PREFIX + "parallax_x"
PARALLAX_Y = PREFIX + "parallax_y"
OPACITY = PREFIX + "opacity"
OCCLUDES = PREFIX + "occludes"
PASSABILITY = PREFIX + "passability"
RENDERS = PREFIX + "renders"

# Every property this module understands. `tools/check_editor.py` asserts
# the editor's authoring vocabulary declares exactly these, so a capability
# added on one side and forgotten on the other fails a check instead of
# quietly doing nothing.
KNOWN: tuple[str, ...] = (DEPTH, MOTION, PARALLAX_X, PARALLAX_Y, OPACITY,
                          OCCLUDES, PASSABILITY, RENDERS)

STATIC = "static"
DYNAMIC = "dynamic"


@dataclass(frozen=True)
class LayerProfile:
    """A layer's declared behaviour, with defaults already applied."""

    depth: int = -1                       # -1 means "use the layer's name"
    motion: str = STATIC
    parallax: tuple[float, float] = (1.0, 1.0)
    opacity: float = 1.0
    occludes: bool = False
    passability: str = ""
    renders: bool = True

    @property
    def static(self) -> bool:
        """May this layer be flattened into the map plane with its neighbours?

        Declared motion is only one way to lose it. Anything that has to be
        modulated at blit time cannot be baked, because a per-layer alpha or
        a shifted source rect is exactly the partial-on-partial case
        `composite_is_exact` refuses to merge.
        """
        return (self.motion == STATIC
                and self.parallax == (1.0, 1.0)
                and self.opacity >= 1.0)

    @property
    def parallaxed(self) -> bool:
        return self.parallax != (1.0, 1.0)


DEFAULT = LayerProfile()


def _number(properties: dict, key: str, fallback: float) -> float:
    value = properties.get(key, fallback)
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return fallback


def _flag(properties: dict, key: str, fallback: bool) -> bool:
    value = properties.get(key, fallback)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def read(layer) -> LayerProfile:
    """Read a pytmx layer's declared profile. Never raises.

    A layer with nothing declared returns DEFAULT, and a layer with a
    nonsense value behaves like an undeclared one rather than taking the
    renderer down -- a hand-edited tmx should not be able to do that.
    """
    properties = getattr(layer, "properties", None) or {}
    if not isinstance(properties, dict):
        return DEFAULT
    return read_properties(properties)


def read_properties(properties: dict) -> LayerProfile:
    """The same reading, from a plain mapping rather than from a layer.

    Split out because a pytmx layer is not the only thing that carries these
    properties: `MapDocument`'s tile layers carry them too, typed by the same
    rules, and `scripts/core/collision_runtime.py` has to ask a DOCUMENT
    layer whether it sits at world coordinates. Two readings of `parallax`
    would be two answers on the day one of them was fixed.
    """
    depth = properties.get(DEPTH, -1)
    try:
        depth = int(depth)
    except (TypeError, ValueError):
        depth = -1

    motion = str(properties.get(MOTION, STATIC)).strip().lower()
    if motion not in (STATIC, DYNAMIC):
        motion = STATIC

    return LayerProfile(
        depth=depth,
        motion=motion,
        parallax=(_number(properties, PARALLAX_X, 1.0),
                  _number(properties, PARALLAX_Y, 1.0)),
        opacity=max(0.0, min(1.0, _number(properties, OPACITY, 1.0))),
        occludes=_flag(properties, OCCLUDES, False),
        passability=str(properties.get(PASSABILITY, "") or ""),
        renders=_flag(properties, RENDERS, True),
    )


def parallax_view(view, parallax: tuple[float, float],
                  full_width: int, full_height: int):
    """Where a parallaxed layer should sample from, clamped to its surface.

    A factor below 1 makes the layer travel LESS than the camera, so a
    distant background drifts a little and settles rather than sliding away.
    Clamping is not optional: `destination` is a hard (0, 0) and `draw_area`
    is a source rect, so an unclamped rect near the map edge just draws
    fewer pixels and leaves whatever was underneath on the rest of the
    screen.
    """
    import pygame

    factor_x, factor_y = parallax
    x = int(round(view.x * factor_x))
    y = int(round(view.y * factor_y))
    x = max(0, min(x, max(0, full_width - view.width)))
    y = max(0, min(y, max(0, full_height - view.height)))
    return pygame.Rect(x, y, view.width, view.height)
