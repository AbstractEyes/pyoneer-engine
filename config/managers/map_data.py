"""Maps named in config/maps.json, parsed and handed to the renderer.

TWO FORMATS, ONE LOOKUP
-----------------------
`config/maps.json` names a file. Until now that file had to be a `.tmx` and
`load_assets` had to be pytmx. `scripts/loaders/blitmap.py` ships a native
format, a converter and a check, and nothing read it at runtime -- so this
module is where the second format gets a door, and it is deliberately the
ONLY door: one `load_assets(name)` that dispatches on the extension, so a
caller never has to know which format a map is stored in.

The pytmx path is untouched. `.blitmap` is ADDITIVE until something proves
it can replace tmx, and the thing that would prove it is the shipped map
converted and loaded side by side producing the same layers, gids, objects,
properties and tilesets -- which is what `tools/check_blitmap_engine.py`
measures, field by field, against a copy.

WHY THE RUNTIME VIEW LIVES HERE AND NOT IN scripts/loaders/
-----------------------------------------------------------
`scripts/loaders/__init__.py` states the rule the package is built on:
nothing in there imports pygame. That is what lets a tool exercise the
formats with no display and no game loop, and `check_blitmap.py` asserts it.
Turning a gid into a `pygame.Surface` needs pygame, so the surface half of
the load lives on this side of that line -- where `pytmx.load_pygame`
already is -- and the pure half (following tileset links, resolving a gid to
a cell) stays in `blitmap.py` where it can still be read without a screen.
"""
from __future__ import annotations

import os
import re

import pygame
import pytmx
import pytmx.util_pygame

from config.managers.core_data import CoreAsset
from scripts.core.art import resolve_art
from scripts.core.errors import (PyoneerAssetMissingError, PyoneerConfigError,
                                 warn_content)
from scripts.core.log import trace_assets
from scripts.loaders.blitmap import (BLITMAP_SUFFIX, LinkedTileset, LoadedMap,
                                     MapObjectRecord, TileAddress,
                                     layer_object_records, load_map)
# The format's own model classes, aliased so a reader can tell a MODEL
# TileLayer -- gids and nothing else -- from the VIEW of one defined below.
from scripts.loaders.blitmap import ImageLayer as ImageLayerModel
from scripts.loaders.blitmap import LayerGroup as LayerGroupModel
from scripts.loaders.blitmap import ObjectLayer as ObjectLayerModel
from scripts.loaders.blitmap import TileLayer as TileLayerModel
from scripts.loaders.map_document import MapDocument

# Resolved from this file's location, not the working directory -- the same
# rule ConfigManager already uses for config/. config/maps.json stores
# "data/maps/starter.tmx" relative to the repo root, so starting the engine (or
# a tool, or a test) from anywhere else made pytmx.load_pygame raise
# FileNotFoundError on a path the user never wrote down.
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

TMX_SUFFIX = ".tmx"


def tileset_image_loader(filename: str, colorkey=None, **kwargs):
    """pytmx's image hook, with the shipped pack behind the declared path.

    pytmx joins a `<image source>` onto the map's directory and opens the
    result itself, so this is the ONLY seam where a tmx tileset image can
    be redirected. `resolve_art` hands back the same string whenever a file
    is already there, which is why a machine holding real art loads exactly
    the bytes it loaded before; `scripts/core/art.py` states the rule.

    `pytmx.load_pygame` cannot be used to install this: it ASSIGNS
    `kwargs["image_loader"]` over anything a caller passed, so the map is
    built through `TiledMap` directly. Everything else about the parse is
    pytmx's own, including the smart convert/convert_alpha choice this
    delegates to.
    """
    return pytmx.util_pygame.pygame_image_loader(
        resolve_art(filename), colorkey, **kwargs)

# What `file` may end in, and which reader claims it. A table rather than an
# if/else chain so the error for an unknown extension can list what IS
# supported -- the same reason PyoneerAssetMissingError carries `available`.
KNOWN_SUFFIXES: tuple[str, ...] = (TMX_SUFFIX, BLITMAP_SUFFIX)


def resolve_map_path(relative: str) -> str:
    """Turn a config/maps.json 'file' value into an absolute path."""
    if os.path.isabs(relative):
        return os.path.normpath(relative)
    return os.path.normpath(os.path.join(REPO_ROOT, relative))


def map_format(path: str) -> str:
    """Which reader a map file wants, from its extension alone.

    Extension, not sniffing the first line. A `.blitmap` announces itself in
    its magic line and a `.tmx` does not announce anything, so content
    sniffing would be asymmetric -- and the config file is where the author
    already said what this is. An unknown suffix RAISES rather than falling
    back to pytmx: a fallback would report the failure three frames inside a
    third-party XML parser, naming a syntax error rather than the real
    mistake, which is that nothing here reads that format.
    """
    suffix = os.path.splitext(path)[1].lower()
    if suffix not in KNOWN_SUFFIXES:
        raise PyoneerConfigError(
            "map file %r has extension %r, which no loader claims; this "
            "engine reads %s" % (path, suffix or "(none)",
                                 ", ".join(KNOWN_SUFFIXES)),
            source="config/maps.json",
        )
    return suffix


# ---------------------------------------------------------------------------
# The .blitmap runtime view
#
# The renderer's tile path reads a very small surface of pytmx.TiledMap:
# `.layers`, `.width/.height/.tilewidth/.tileheight`, `get_tile_image_by_gid`,
# and per layer `.name`, `.properties`, `.offsetx/.offsety` plus iteration
# yielding (x, y, gid). These classes present exactly that, from a .blitmap.
#
# They are NOT pytmx subclasses and cannot be: pytmx's layer constructors
# take an ElementTree node and parse it. So `isinstance(layer, TiledTileLayer)`
# -- which is how renderer.py and game_map.py decide what is a tile layer --
# is False for these, and that one test is the whole remaining seam. See
# `tools/check_blitmap_engine.py`, which measures it rather than asserting it
# away.
# ---------------------------------------------------------------------------

def _attribute_int(attributes: dict[str, str], key: str, fallback: int) -> int:
    """A tmx attribute that rode across as an `attr` line, as pytmx types it.

    pytmx's `types` table casts `offsetx`/`offsety` to int and `opacity` to
    float, and the renderer adds the offsets straight to a blit destination.
    Matching that table matters more than it looks: a layer offset arriving
    as the string '8' would concatenate rather than add, and a float where
    pytmx had an int is a subpixel difference in the frame hash.
    """
    raw = attributes.get(key)
    if raw is None:
        return fallback
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        warn_content("blitmap layer attr %s=%r is not a number; using %d"
                     % (key, raw, fallback))
        return fallback


def _attribute_float(attributes: dict[str, str], key: str, fallback: float) -> float:
    raw = attributes.get(key)
    if raw is None:
        return fallback
    try:
        return float(raw)
    except (TypeError, ValueError):
        warn_content("blitmap layer attr %s=%r is not a number; using %s"
                     % (key, raw, fallback))
        return fallback


def _attribute_flag(attributes: dict[str, str], key: str, fallback: bool) -> bool:
    raw = attributes.get(key)
    if raw is None:
        return fallback
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


class BlitmapLayerView:
    """What every .blitmap layer presents, whatever kind it is.

    `visible`, `opacity`, `offsetx` and `offsety` are tmx attributes the
    format does not model, so they arrive as `attr` lines and are read back
    here. That is the `attr` pressure valve working as designed -- the
    format did not have to grow four fields to stay faithful -- but it does
    mean this class is where their meaning is restored.
    """

    def __init__(self, source):
        self.source = source
        self.id = source.id
        self.name = source.name
        attributes = dict(source.attributes)
        self.attributes = attributes
        self.visible = _attribute_flag(attributes, "visible", True)
        self.opacity = _attribute_float(attributes, "opacity", 1.0)
        self.offsetx = _attribute_int(attributes, "offsetx", 0)
        self.offsety = _attribute_int(attributes, "offsety", 0)
        # Typed, not raw text. `layer_profile.read` tolerates strings but
        # `spawn.resolve_depth` refuses them, so a single spelling of
        # "properties" has to be the typed one or the two disagree about the
        # same file.
        self.properties = {prop.name: prop.value for prop in source.properties}

    def __repr__(self) -> str:
        return "<%s %r>" % (type(self).__name__, self.name)


class BlitmapTileLayer(BlitmapLayerView):
    """A grid of gids, presented the way pytmx presents one.

    The gids are the FILE's gids. pytmx renumbers -- `layer.data` holds
    internal ids and `tiledgidmap` is required to get back to what the file
    says -- and every consumer that wanted a real gid had to remember to
    invert it. Here there is nothing to invert, which is most of the point
    of the format.
    """

    def __init__(self, source):
        super().__init__(source)
        self.width = source.width
        self.height = source.height
        self.data = [list(row) for row in source.rows()]

    def __iter__(self):
        """(x, y, gid) per cell, row major. `TiledTileLayer.iter_data`'s shape."""
        for y, row in enumerate(self.data):
            for x, gid in enumerate(row):
                yield x, y, gid

    def __len__(self) -> int:
        return self.width * self.height


class BlitmapObjectGroup(BlitmapLayerView):
    """An object layer: placements, already flattened for the spawn path.

    Each entry is a `MapObjectRecord`, which is shaped like
    `map_document.MapObject` on purpose -- see that dataclass for why the
    y-origin rule is not written down twice.
    """

    def __init__(self, source):
        super().__init__(source)
        self.objects: list[MapObjectRecord] = layer_object_records(source)

    def __iter__(self):
        return iter(self.objects)

    def __len__(self) -> int:
        return len(self.objects)


class BlitmapImageLayer(BlitmapLayerView):
    """A single placed image. Carried, and drawn by nothing yet.

    Present because the format carries one and the renderer's own image
    layer path does not exist either -- dropping it here would make the
    runtime view lossier than the format, which is the wrong direction for
    the thing that is supposed to prove the format is enough.
    """

    def __init__(self, source):
        super().__init__(source)
        self.source_path = source.source


class BlitmapGroupLayer(BlitmapLayerView):
    """A `<group>`. Carries no cells; kept so `.layers` lists what the map has."""


_MISSING = object()
"""Sentinel for the tile cache below, so a cached None is not a cache miss."""


class BlitmapRuntime:
    """A loaded .blitmap, presented the way the renderer reads a tmx map.

    WHY A VIEW AND NOT A CONVERSION TO pytmx
    ----------------------------------------
    Building a `pytmx.TiledMap` from a .blitmap would mean re-entering the
    gid renumbering, the attribute-shadowing raise and the phantom
    collision layers -- the three costs the format exists to avoid -- and it
    would make the native path strictly slower than the one it replaces. So
    the map keeps its own gids and answers the questions the renderer asks.

    IMAGES ARE LOADED EAGERLY, LIKE pytmx
    -------------------------------------
    `pytmx.load_pygame` opens every tileset image during the parse, so a
    fresh clone -- which ships the map and not the art -- fails at
    `load_assets` with a message about art. Slicing lazily instead would
    move that failure to the first frame that happens to reach a tile,
    which is a crash in the render loop reporting a missing file. Same
    failure, much worse place.
    """

    def __init__(self, loaded: LoadedMap):
        self.loaded = loaded
        self.blitmap = loaded.blitmap
        # `filename` because that is what pytmx calls it and what
        # `map_loader.as_document` looks for. It names a .blitmap, which
        # that function cannot open -- see NOT DONE in the check.
        self.filename = loaded.path
        self.width = self.blitmap.width
        self.height = self.blitmap.height
        self.tilewidth = self.blitmap.tile_width
        self.tileheight = self.blitmap.tile_height
        attributes = dict(self.blitmap.attributes)
        self.attributes = attributes
        self.orientation = attributes.get("orientation", "orthogonal")
        self.renderorder = attributes.get("renderorder", "right-down")
        self.properties = {prop.name: prop.value
                           for prop in self.blitmap.properties}
        self.tilesets: tuple[LinkedTileset, ...] = loaded.tilesets

        self.layers: list[BlitmapLayerView] = []
        self._build_layers(self.blitmap.layers, self.layers)

        self._sheets: dict[str, pygame.Surface] = {}
        self._tiles: dict[int, pygame.Surface | None] = {}
        self._complained: set[int] = set()
        self._load_sheets()

    # -- layers ------------------------------------------------------------
    @staticmethod
    def _view(source) -> BlitmapLayerView:
        if isinstance(source, TileLayerModel):
            return BlitmapTileLayer(source)
        if isinstance(source, ObjectLayerModel):
            return BlitmapObjectGroup(source)
        if isinstance(source, ImageLayerModel):
            return BlitmapImageLayer(source)
        return BlitmapGroupLayer(source)

    def _build_layers(self, sources, into: list) -> None:
        """Flatten the group tree into document order.

        Flattened because every consumer in the engine iterates `.layers`
        and filters by type; nested groups would make each of them recurse.
        Document order rather than pytmx's order -- which puts every group
        first, then every tile layer, then image layers, then object groups
        -- because document order is the order the author sees in Tiled and
        is the order the tile layers come out in either way.
        """
        for source in sources:
            into.append(self._view(source))
            if isinstance(source, LayerGroupModel):
                self._build_layers(source.layers, into)

    @property
    def visible_layers(self):
        """pytmx's accessor, same name and same meaning. `GameMap` reads it."""
        return (layer for layer in self.layers if layer.visible)

    @property
    def objectgroups(self):
        return (layer for layer in self.layers
                if isinstance(layer, BlitmapObjectGroup))

    @property
    def objects(self) -> list[MapObjectRecord]:
        return self.object_records()

    def object_records(self, layers=None) -> list[MapObjectRecord]:
        """Every placed object, in the shape the spawn path already reads.

        Duck-typed on purpose, and named for `blitmap.object_records`.
        `map_loader.spawn_objects` re-reads a .tmx FROM DISK through
        MapDocument because pytmx drops property types -- a native map has
        neither the file to re-read nor the problem that made it necessary,
        since these records already carry typed values. A caller can test
        for this METHOD rather than for this class, which is what keeps
        `scripts/loaders/` from having to import `config/` to spawn from a
        .blitmap. See the integration note in tools/check_blitmap_engine.py.

        `layers` restricts the pass to named object groups, the same
        argument `spawn_objects` takes.
        """
        wanted = None if layers is None else set(layers)
        found: list[MapObjectRecord] = []
        for group in self.objectgroups:
            if wanted is None or group.name in wanted:
                found.extend(group.objects)
        return found

    def layer_names(self) -> list[str]:
        return [layer.name for layer in self.layers]

    # -- images ------------------------------------------------------------
    def _load_sheets(self) -> None:
        for linked in self.tilesets:
            path = resolve_art(linked.image_path())
            if not path:
                warn_content(
                    "tileset %r in %s declares no image, so every gid in its "
                    "range draws nothing"
                    % (linked.name, os.path.basename(self.filename)))
                continue
            if not os.path.isfile(path):
                raise PyoneerAssetMissingError(
                    "tileset image", path.replace("\\", "/"),
                    available=(),
                    map=os.path.basename(self.filename),
                    tileset=linked.name,
                    declared_in=linked.path,
                    hint="the repository ships without art; see docs/ASSETS.md",
                )
            self._sheets[linked.name] = pygame.image.load(path)
        trace_assets("blitmap %s loaded %d tileset image(s)",
                     os.path.basename(self.filename), len(self._sheets))

    def get_tile_image_by_gid(self, gid: int):
        """The surface for one gid, or None when nothing can draw it.

        None rather than pytmx's 0-for-empty, because every caller in this
        engine tests `isinstance(tile, pygame.Surface)` and both answers
        fail that test identically -- while None is the one that reads as
        "no tile" to a human.
        """
        if not gid:
            return None
        hit = self._tiles.get(gid, _MISSING)
        if hit is not _MISSING:
            return hit
        surface = self._slice(gid)
        self._tiles[gid] = surface
        return surface

    def _slice(self, gid: int):
        address = self.loaded.address(gid)
        if address is None:
            self._complain(gid, "no tileset in this map owns it")
            return None
        sheet = self._sheets.get(address.tileset.name)
        if sheet is None:
            return None
        tileset = address.tileset.tileset
        left = tileset.margin + address.column * (tileset.tile_width + tileset.spacing)
        top = tileset.margin + address.row * (tileset.tile_height + tileset.spacing)
        rect = pygame.Rect(left, top, tileset.tile_width, tileset.tile_height)
        if not sheet.get_rect().contains(rect):
            # The declared count says this tile exists and the image is too
            # small to hold it: the sheet was recropped under a map that
            # still points into it. Naming the tile is the only way the
            # author finds out which one.
            self._complain(gid, "tile %d of %r is outside its %dx%d image"
                                % (address.local_id, address.tileset.name,
                                   sheet.get_width(), sheet.get_height()))
            return None
        return _convert_tile(sheet.subsurface(rect), address)

    def _complain(self, gid: int, why: str) -> None:
        """Warn once per distinct gid, not once per cell.

        A bad gid on a 100x100 map is 10,000 identical warnings, which is
        indistinguishable from a hang.
        """
        if gid in self._complained:
            return
        self._complained.add(gid)
        warn_content("map %s uses gid %d and %s; those cells draw nothing"
                     % (os.path.basename(self.filename), gid, why))

    def __repr__(self) -> str:
        return "<BlitmapRuntime %r %dx%d, %d layers>" % (
            os.path.basename(self.filename), self.width, self.height,
            len(self.layers))


TILE_LAYER_TYPES: tuple[type, ...] = (pytmx.TiledTileLayer, BlitmapTileLayer)
"""What counts as a tile layer, whichever format the map was stored in.

`renderer.py` and `game_map.py` both ask this question with a bare
`isinstance(layer, pytmx.TiledTileLayer)`, and that one test is the whole
reason a .blitmap cannot reach the renderer today. One tuple rather than two
hand-written isinstance lists, because a second spelling is the one that
gets missed -- and this module is the only place that can hold it:
`scripts/loaders/` may not import pygame, so the native view cannot live
there, and neither reader may import the other.

It has NO production consumer until those two lines change. That is
deliberate and it is written down rather than assumed -- see NOT DONE in
`tools/check_blitmap_engine.py`, which measures the seam and proves what
closing it produces.
"""


def _convert_tile(tile: pygame.Surface, address: TileAddress) -> pygame.Surface:
    """Apply the gid's flips and pick the cheaper surface format.

    Mirrors what `pytmx.util_pygame` does, and is written out here rather
    than imported from it for one reason: the point of this path is that a
    .blitmap loads without pytmx, and importing pytmx's converter to finish
    the job would leave that claim false in a way nobody would notice. The
    duplication is paid for by `tools/check_blitmap_engine.py`, which
    compares the two paths' surfaces byte for byte on the shipped map -- so
    if these ever drift apart, a check says so instead of a screenshot.

    The format choice is pytmx's measured rule: a tile with no transparent
    pixel is cheaper as a plain surface, because .convert() is a copy where
    .convert_alpha() is a per-pixel blend, and the pixels are identical.
    """
    horizontal, vertical, diagonal = address.flips
    if diagonal:
        tile = pygame.transform.flip(pygame.transform.rotate(tile, 270), True, False)
    if horizontal or vertical:
        tile = pygame.transform.flip(tile, horizontal, vertical)
    size = tile.get_size()
    if pygame.mask.from_surface(tile, 254).count() == size[0] * size[1]:
        return tile.convert()
    return tile.convert_alpha()


# ---------------------------------------------------------------------------
# The manager
# ---------------------------------------------------------------------------

class MapData:

    def __init__(self, config: dict[str, str]):
        # `source` keeps the value as authored so an error message can name
        # the string that is actually in the json file, not just where it
        # ended up resolving to.
        self.source = config['file']
        self.file = resolve_map_path(self.source)
        self.name = config['name']
        self.identifier = config['identifier']
        # Refused at PREPARE time, not at first load. A typo in an extension
        # is a config mistake, and a config mistake that waits until the
        # scene asks for the map reports itself as a rendering failure.
        self.format = map_format(self.file)
        self.data: pytmx.TiledMap | BlitmapRuntime | None = None

    @property
    def native(self) -> bool:
        """True when this map is stored in the engine's own format."""
        return self.format == BLITMAP_SUFFIX


class AssetMapManager(CoreAsset):
    def __init__(self):
        self.maps: dict[str, MapData] = {}

    def __find_map(self, name: str) -> MapData | None:
        # .get, not [name]: the old lookup raised KeyError on an unknown map,
        # so the `if map_data is None` branch below was unreachable and the
        # intended "not found" message never printed.
        return self.maps.get(name)

    def __require_map(self, name: str) -> MapData:
        map_data = self.__find_map(name)
        if map_data is None:
            raise PyoneerAssetMissingError("map", name, available=self.maps.keys(),
                                          source="config/maps.json")
        return map_data

    def load_assets(self, name: str,
                    reload: bool = False) -> pytmx.TiledMap | BlitmapRuntime | None:
        """Return the parsed map, parsing it at most once.

        Parsing the shipped map builds thousands of tile data entries plus
        tileset surfaces, so it must not happen implicitly more than once. Pass reload=True to
        force a re-parse after the file changes on disk -- which is what the
        map editor will need.

        Which reader runs is decided by the extension in config/maps.json:
        a `.tmx` goes through pytmx exactly as it always has, a `.blitmap`
        through the engine's own loader. The caller gets an object with the
        same read surface either way and does not choose.
        """
        map_data = self.__require_map(name)
        if map_data.data is None or reload:
            self.__require_file(map_data)
            map_data.data = self.__parse(map_data)
        return map_data.data

    @staticmethod
    def __parse(map_data: MapData) -> pytmx.TiledMap | BlitmapRuntime:
        """Read one map file with whichever loader its extension names."""
        if map_data.native:
            return BlitmapRuntime(load_map(map_data.file))
        try:
            return pytmx.TiledMap(map_data.file,
                                  image_loader=tileset_image_loader)
        except FileNotFoundError as exc:
            # pytmx resolves <tileset source=...> relative to the .tmx and
            # raises a bare FileNotFoundError from three frames inside a
            # third-party package, on a mixed-separator path with an
            # unresolved '..' segment. On a fresh clone -- which ships the
            # map but not the art -- that is the FIRST thing a newcomer
            # sees, and it reads as "the checkout is broken" rather than
            # "this repo ships without art on purpose".
            raise PyoneerAssetMissingError(
                "tileset image", AssetMapManager.__missing_tileset_name(exc),
                available=(),
                map=map_data.name,
                tmx=map_data.file,
                hint="the repository ships without art; see docs/ASSETS.md",
            ) from exc

    @staticmethod
    def __missing_tileset_name(exc: BaseException) -> str:
        """Pull just the path out of pytmx's mangled FileNotFoundError.

        pygame raises this with `filename` unset and the path embedded in the
        message as "No such file or directory: '<path>'.", on a mixed-separator
        string with an unresolved '..' segment. Recover the quoted path and
        normalize it so the reported name matches what is on disk.
        """
        raw = getattr(exc, "filename", None)
        if not raw:
            match = re.search(r"['\"]([^'\"]+)['\"]", str(exc))
            raw = match.group(1) if match else str(exc)
        return os.path.normpath(str(raw)).replace("\\", "/")

    @staticmethod
    def __require_file(map_data: MapData) -> None:
        """Fail with both paths, not just the one pytmx happens to hold.

        A bare FileNotFoundError on an absolute path leaves the reader
        guessing whether config/maps.json is wrong or the file moved.
        """
        if not os.path.isfile(map_data.file):
            raise PyoneerConfigError(
                f"map {map_data.name!r} points at {map_data.source!r}, which "
                f"resolves to {map_data.file} and does not exist",
                source="config/maps.json",
            )

    def document(self, name: str) -> MapDocument:
        """Open a map for EDITING, as a byte-faithful XML document.

        Deliberately separate from load_assets(): that returns pytmx's
        read-only render view, which has no memory of the file's formatting
        and so cannot be written back without reflowing it. Editing goes
        through MapDocument, then load_assets(name, reload=True) picks the
        change up.

        Only .tmx. A .blitmap needs no byte-faithful writer -- the format is
        canonical, so its own `render()` IS the writer -- but the editor's
        whole command stream is built on `MapDocument`, and handing it
        something else would be a silent half-support. It raises here
        instead, naming the format.
        """
        map_data = self.__require_map(name)
        if map_data.native:
            raise PyoneerConfigError(
                f"map {map_data.name!r} is stored as {map_data.source!r}; "
                f"MapDocument reads .tmx only. The editor's command stream "
                f"has no .blitmap write path yet",
                source="config/maps.json",
            )
        self.__require_file(map_data)
        return MapDocument.load(map_data.file)

    def is_loaded(self, name: str) -> bool:
        map_data = self.__find_map(name)
        return map_data is not None and map_data.data is not None

    def unload_assets(self, name: str) -> bool:
        map_data = self.__find_map(name)
        if map_data is not None:
            map_data.data = None
            return True # map asset found and unloaded
        return False # map asset not found

    def __load_maps(self, config: dict[str, any]) -> AssetMapManager:
        for map_ in config['data']:
            map_name = map_['name']
            self.maps[map_name] = MapData(map_)
        return self

    def reload(self, config: dict[str, any] | tuple[str, any] | None = None) -> AssetMapManager:
        """Re-parse every map that is currently loaded, in place."""
        for name, map_data in self.maps.items():
            if map_data.data is not None:
                self.__require_file(map_data)
                map_data.data = self.__parse(map_data)
        return self

    def prepare(self, config: dict[str, any]) -> AssetMapManager:
        return self.__load_maps(config)
