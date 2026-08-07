from __future__ import annotations

import pytmx

from config.managers.core_data import CoreAsset


class MapData:


    def __init__(self, config: dict[str, str]):
        self.file = config['file']
        self.name = config['name']
        self.identifier = config['identifier']
        self.data: pytmx.TiledMap | None = None


class AssetMapManager(CoreAsset):
    def __init__(self):
        self.maps: dict[str, MapData] = {}

    def __find_map(self, name: str) -> MapData:
        return self.maps[name]

    def load_assets(self, name: str) -> pytmx.TiledMap | None:
        map_data = self.__find_map(name)
        if map_data is None:
            print(f"Map {name} not found as loaded.")
            return None
        if map_data.data is not None:
            return map_data.data
        else:
            map_data.data = pytmx.load_pygame(map_data.file)
            return map_data.data

    def unload_assets(self, name: str) -> bool:
        map_data = self.__find_map(name)
        if map_data is not None:
            del map_data.data
            map_data.data = None
            return True # map asset found and unloaded
        return False # map asset not found

    def __load_maps(self, config: dict[str, any]) -> AssetMapManager:
        for map_ in config['data']:
            map_name = map_['name']
            self.maps[map_name] = MapData(map_)
        return self

    def reload(self, config: dict[str, any] | tuple[str, any]):
        pass

    def prepare(self, config: dict[str, any]) -> AssetMapManager:
        return self.__load_maps(config)