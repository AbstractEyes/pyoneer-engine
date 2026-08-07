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
    """One instance per concrete subclass, constructed exactly once.

    `__new__` returning a cached instance is NOT sufficient on its own:
    Python still calls `__init__` on whatever `__new__` returns, so every
    subsequent `CoreAssetManager()` re-ran the constructor and rebound every
    sub-manager to a brand-new object -- silently discarding the parsed tmx
    cache and orphaning every reference already handed out.

    Subclasses cooperate by returning early when `self.is_initialized` is
    True, which `initialized()` sets. `_instances` is keyed per class so
    sibling subclasses cannot collide.
    """

    _instances: dict[type, "Singleton"] = {}

    def __new__(cls, *args, **kwargs):
        instance = Singleton._instances.get(cls)
        if instance is None:
            instance = super().__new__(cls)
            instance.is_initialized = False
            Singleton._instances[cls] = instance
        return instance

    def initialized(self):
        """Call at the end of __init__ to seal the instance."""
        self.is_initialized = True

    @classmethod
    def reset_singleton(cls):
        """Drop the cached instance. For tests and headless tooling only.

        Without this, global state makes test order significant -- the
        second test in a process inherits the first one's loaded assets.
        """
        Singleton._instances.pop(cls, None)


class CoreAssetManager(Singleton):
    """Root accessor for every loaded asset domain.

    Constructed once per process. Later `CoreAssetManager()` calls return the
    same object without re-reading anything from disk, so it is safe to write
    `Config = CoreAssetManager()` at module scope.

    Attributes are the domain accessors:
        .config      config/*.json
        .entity      entity definitions
        .animations  animation categories
        .maps        tmx maps (parsed lazily, cached)
        .inputs      the input action manager
    """

    def __init__(self):
        if self.is_initialized:
            # Already built. Re-running would replace every sub-manager and
            # drop the parsed tmx cache; call reload() if that is the intent.
            return
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
        self.initialized()

    def reload(self):
        """Explicitly rebuild every sub-manager from disk.

        The only supported way to re-read configuration. Nothing calls this
        implicitly -- that was the defect.
        """
        self.is_initialized = False
        self.__init__()
        return self

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
