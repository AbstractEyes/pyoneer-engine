from __future__ import annotations

import os
import json

from config.managers.core_data import CoreAsset


class ConfigManager(CoreAsset):

    def reload(self, config: dict[str, any] | tuple[str, any]):
        pass

    def __init__(self):
        self.data: dict[str, dict] = dict()

    def get(self, type_in: str, key: str|None = None):
        return self.data[type_in] if key is None else self.data[type_in][key]

    def prepare(self, config: dict[str, any] | None = None) -> ConfigManager:
        self.__load_configurations()
        return self

    def __load_configurations(self):
        # get each config option from the config folder
        for filename in os.listdir('config'):
            if filename.endswith('.json'):  # load the json configuration
                ready_filename = filename.replace('.json', '')
                self.data[ready_filename] = json.load(open('config/' + filename, "r"))
        return self

    def load_assets(self, name: str):
        pass

    def unload_assets(self, name: str):
        pass
