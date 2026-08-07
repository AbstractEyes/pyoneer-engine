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

    # Resolved from this file's location, not the working directory. The old
    # bare 'config' path meant the engine could only start from the repo root,
    # so any tool or test run from elsewhere failed to find its own config.
    CONFIG_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    def __load_configurations(self):
        # get each config option from the config folder
        for filename in sorted(os.listdir(self.CONFIG_DIR)):
            if filename.endswith('.json'):  # load the json configuration
                ready_filename = filename.replace('.json', '')
                path = os.path.join(self.CONFIG_DIR, filename)
                with open(path, "r", encoding="utf-8") as handle:
                    self.data[ready_filename] = json.load(handle)
        return self

    def load_assets(self, name: str):
        pass

    def unload_assets(self, name: str):
        pass
