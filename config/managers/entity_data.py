from __future__ import annotations

from config.managers.core_data import CoreAsset


class DataEntitySpriteInfo:
    def __init__(self, config: dict[str, str]):
        self.config = config
        self.body = config['body']


class DataEntityMovement:
    def __init__(self, config: dict[str, str]):
        self.config = config
        self.move_speed = config['move_speed']
        self.sprint_mult = config['sprint_mult']


class DataEntity:
    def __init__(self, config: dict[str | int | float]):
        self.config: dict[str | int | float] = config
        self.movement: DataEntityMovement = DataEntityMovement(config['movement'])
        self.sprite_info: DataEntitySpriteInfo = DataEntitySpriteInfo(config['animations'])


class EntityAssetManager(CoreAsset):

    def reload(self, config: dict[str, any] | tuple[str, any], unload_first: bool = False):
        pass

    def __init__(self):
        self.entities: dict[str, DataEntity] = {}

    def get(self, key: str) -> DataEntity:
        return self.entities[key]

    def prepare(self, config: dict[str, any]) -> EntityAssetManager:
        for name, data in config.items():
            self.entities[name] = DataEntity(data)
        return self

    def load_assets(self, name: str):
        pass

    def unload_assets(self, name: str):
        pass