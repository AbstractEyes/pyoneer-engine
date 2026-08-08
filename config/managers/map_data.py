from __future__ import annotations

import os

import pytmx

from config.managers.core_data import CoreAsset
from scripts.core.errors import PyoneerAssetMissingError, PyoneerConfigError
from scripts.loaders.map_document import MapDocument

# Resolved from this file's location, not the working directory -- the same
# rule ConfigManager already uses for config/. config/maps.json stores
# "data/maps/test.tmx" relative to the repo root, so starting the engine (or
# a tool, or a test) from anywhere else made pytmx.load_pygame raise
# FileNotFoundError on a path the user never wrote down.
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def resolve_map_path(relative: str) -> str:
    """Turn a config/maps.json 'file' value into an absolute path."""
    if os.path.isabs(relative):
        return os.path.normpath(relative)
    return os.path.normpath(os.path.join(REPO_ROOT, relative))


class MapData:


    def __init__(self, config: dict[str, str]):
        # `source` keeps the value as authored so an error message can name
        # the string that is actually in the json file, not just where it
        # ended up resolving to.
        self.source = config['file']
        self.file = resolve_map_path(self.source)
        self.name = config['name']
        self.identifier = config['identifier']
        self.data: pytmx.TiledMap | None = None


class AssetMapManager(CoreAsset):
    def __init__(self):
        self.maps: dict[str, MapData] = {}

    def __find_map(self, name: str) -> MapData | None:
        # .get, not [name]: the old lookup raised KeyError on an unknown map,
        # so the `if map_data is None` branch below was unreachable and the
        # intended "not found" message never printed.
        return self.maps.get(name)

    def load_assets(self, name: str, reload: bool = False) -> pytmx.TiledMap | None:
        """Return the parsed map, parsing it at most once.

        Parsing test.tmx builds 100x100 tile data plus tileset surfaces, so
        it must not happen implicitly more than once. Pass reload=True to
        force a re-parse after the file changes on disk -- which is what the
        map editor will need.
        """
        map_data = self.__find_map(name)
        if map_data is None:
            raise PyoneerAssetMissingError("map", name, available=self.maps.keys(),
                                          source="config/maps.json")
        if map_data.data is None or reload:
            self.__require_file(map_data)
            map_data.data = pytmx.load_pygame(map_data.file)
        return map_data.data

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
        """
        map_data = self.__find_map(name)
        if map_data is None:
            raise PyoneerAssetMissingError("map", name, available=self.maps.keys(),
                                          source="config/maps.json")
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
                map_data.data = pytmx.load_pygame(map_data.file)
        return self

    def prepare(self, config: dict[str, any]) -> AssetMapManager:
        return self.__load_maps(config)