from __future__ import annotations

from enum import Enum

from config.managers.animation_data import AssetAnimationManager
from config.managers.config_data import ConfigManager
from config.managers.map_data import AssetMapManager
from config.managers.entity_data import DataEntity, EntityAssetManager
from scripts.core.input import InputActionManager


class AssetTypes(str, Enum):
    ANIMATIONS = "animations"
    CONFIG = "config"
    ENTITY = "entity"
    MAPS = "maps"
    #UI = "ui"

class Singleton:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Singleton, cls).__new__(cls)
        return cls._instance


class CoreAssetManager(Singleton):
    def __init__(self):
        self.name = "CoreAssetManager"
        # Contains the loaded configuration data
        self.config: ConfigManager = ConfigManager().prepare()
        self.entity: EntityAssetManager = EntityAssetManager().prepare(self.config.get('entity'))
        # Contains the global game animation data
        self.animations: AssetAnimationManager = AssetAnimationManager().prepare(self.config.get('animations'))
        # Contains the global game map data
        self.maps: AssetMapManager = AssetMapManager().prepare(self.config.get('maps'))
        # Contains the player's input action manager
        self.inputs: InputActionManager = InputActionManager().prepare(self.config.get('inputs'))
        #self.ui: dict[str, dict] = UIManager(self.config.get('ui'))

    def load_assets(self, typ: AssetTypes, name: str):
        match typ:
            case AssetTypes.ANIMATIONS:
                self.animations.load_assets(name)
            case AssetTypes.CONFIG:
                self.config.load_assets(name)
            case AssetTypes.ENTITY:
                self.entity.load_assets(name)
            case AssetTypes.MAPS:
                self.maps.load_assets(name)
            # case AssetTypes.UI:
            #    return self.ui.load_assets(name)

    def unload_assets(self, typ: AssetTypes, name: str):
        match typ:
            case AssetTypes.ANIMATIONS:
                self.animations.unload_assets(name)
            case AssetTypes.CONFIG:
                self.config.unload_assets(name)
            case AssetTypes.ENTITY:
                self.entity.unload_assets(name)
            case AssetTypes.MAPS:
                self.maps.unload_assets(name)
            # case AssetTypes.UI:
            #    return self.ui.unload_assets(name)
