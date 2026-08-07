from __future__ import annotations

from config.managers.core_data import CoreAsset


class Depth:
    def __init__(self, config: tuple[str, int]):
        self.name = config[0]
        self.depth = config[1]


class DepthAssetManager(CoreAsset):
    def __init__(self):
        self.__depths: dict[str, Depth] = {}

    def get(self, key: str) -> int:
        if key not in self.__depths:
            raise Exception("Depth not found: ", key)
        return self.__depths[key].depth

    def prepare(self, config: dict[str, any]) -> DepthAssetManager:
        return self.load_depths(config)

    def load_depths(self, config: dict[str, any]) -> DepthAssetManager:
        for name, data in config.items():
            self.__depths[name] = Depth(data)
        return self

    def load_assets(self, name: str):
        pass

    def unload_assets(self, name: str):
        pass

    def reload(self, config: dict[str, any] | tuple[str, any]):
        pass