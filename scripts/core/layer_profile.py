"""What a map layer declares about itself, read at load time.

The editor writes these as tmx custom properties and the engine reads them,
so the names are shared: the vocabulary lives here and `editor/core/layers.py`
imports it, because two hand-kept copies of a string like
`pyoneer_parallax_x` would drift and a property written under one name and
read under another silently does nothing.

THE PREFIX IS LOAD-BEARING.
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

# Every name a tmx custom PROPERTY may never take, on any element.        #TAG:pytmx_reserved_names
#
# THE OTHER HALF OF THE PREFIX RULE ABOVE, and the reason it lives beside
# it: pytmx casts every XML ATTRIBUTE of an element onto the element as a
# Python attribute FIRST, and only then checks each custom property with a
# bare `hasattr`. So a `<property name="visible">` on a layer, a
# `<property name="rotation">` on an object and a `<property name="append">`
# on an object group all raise `ValueError: Reserved names and duplicate
# names are not allowed` and the WHOLE MAP stops loading -- not that layer,
# not that object.
#
# `rotation` and `append` are in that list for two different reasons, and
# both are why this is not the short obvious set somebody types from memory.
# `rotation` is an attribute pytmx gives every object a DEFAULT for, so it is
# reserved on an object that does not carry it in its `attrib` at all;
# `append` is there because `TiledTileLayer` and `TiledObjectGroup` subclass
# `list`. A guard reading only the element's own attributes misses both.
#
# THE UNION across every element kind, deliberately, rather than one set per
# kind: law 1 says an authored property is prefixed, so an unprefixed name is
# already outside the sanctioned vocabulary and the strictest answer is the
# useful one -- the refusal tells the author to prefix it, which is the thing
# that was going to be true anyway.
#
# MEASURED, NOT REMEMBERED. `tools/check_tmx_roundtrip.py` loads a fixture
# carrying one of every element kind and derives this set from pytmx itself,
# name for name, so a pytmx upgrade that adds an attribute turns the suite
# red instead of turning somebody's map unloadable.
RESERVED = frozenset({
    'add_layer', 'add_tileset', 'allow_duplicate_names', 'append',
    'apply_transformations', 'as_points', 'background_color', 'clear',
    'closed', 'color', 'columns', 'copy', 'count',
    'custom_property_filename', 'custom_types', 'data', 'draworder',
    'extend', 'filename', 'firstgid', 'from_xml_string',
    'get_layer_by_name', 'get_object_by_id', 'get_object_by_name',
    'get_tile_colliders', 'get_tile_gid', 'get_tile_image',
    'get_tile_image_by_gid', 'get_tile_locations_by_gid',
    'get_tile_properties', 'get_tile_properties_by_gid',
    'get_tile_properties_by_layer', 'get_tileset_from_gid', 'gid',
    'gidmap', 'height', 'hexsidelength', 'id', 'image', 'image_loader',
    'imagemap', 'images', 'index', 'infinite', 'insert', 'invert_y',
    'iter_data', 'layernames', 'layers', 'load_all_tiles', 'map_gid',
    'map_gid2', 'margin', 'maxgid', 'name', 'nextlayerid', 'nextobjectid',
    'objectgroups', 'objects', 'objects_by_id', 'objects_by_name',
    'offset', 'offsetx', 'offsety', 'opacity', 'optional_gids',
    'orientation', 'parent', 'parse_json', 'parse_xml', 'pop',
    'properties', 'register_gid', 'register_gid_check_flags',
    'reload_images', 'remove', 'renderorder', 'reverse', 'rotation',
    'set_tile_properties', 'sort', 'source', 'spacing', 'staggeraxis',
    'staggerindex', 'template', 'tile_properties', 'tilecount',
    'tiledgidmap', 'tiledversion', 'tileheight', 'tiles', 'tilesets',
    'tilewidth', 'trans', 'type', 'version', 'visible', 'visible_layers',
    'visible_object_groups', 'visible_tile_layers', 'width', 'x', 'y',
})


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
