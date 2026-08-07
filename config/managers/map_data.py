from __future__ import annotations

import pytmx

from config.managers.core_data import CoreAsset
from scripts.core.errors import PyoneerAssetMissingError


class MapData:


    def __init__(self, config: dict[str, str]):
        self.file = config['file']
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
            map_data.data = pytmx.load_pygame(map_data.file)
        return map_data.data

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
                map_data.data = pytmx.load_pygame(map_data.file)
        return self

    def prepare(self, config: dict[str, any]) -> AssetMapManager:
        return self.__load_maps(config)