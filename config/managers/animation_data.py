from __future__ import annotations

import pygame
from pygame import Surface

from config.managers.core_data import CoreAsset


class DataAnimationFrame:
    def __init__(self, width, height, x, y, duration, index):
        self.width = width
        self.height = height
        self.x = x
        self.y = y
        self.duration = duration
        self.index = index


class DataAnimation:
    def __init__(self, name, data_in):
        self.name = name
        self.data = data_in
        self.frame_count = 0
        self.frames = []
        self.loop = self.data['loop']
        for frame in self.data['frames']:
            self.add_frame(self.data['width'], self.data['height'],
                           self.data['x'], self.data['y'],
                           frame['duration'], frame['index'])
        self.frames.sort(key=lambda x: x.index)
        self.frame_count = len(self.frames)

    def add_frame(self, width, height, x, y, duration, index):
        self.frames.append(DataAnimationFrame(width, height, x, y, duration, index))


class DataAnimationCategory:
    def __init__(self, config):
        self.name = config['name']
        self.description = config['description']
        self.id = config['id']
        self.seq_data = config['sequences']
        self.order = config['order']
        self.type = config['type']
        self.file = config['file']
        self.sequences: dict[str, DataAnimation] = {}
        self._prepare_sequences()

    def _prepare_sequences(self):
        for animation_name, animation_data in self.seq_data.items():
            self.sequences[animation_name] = DataAnimation(animation_name, animation_data)


class AssetAnimationManager(CoreAsset):


    def __init__(self):
        self.animations: dict[str, DataAnimationCategory] = {}
        self.cache: dict[str, Surface] = {}

    def get(self, name: str) -> DataAnimationCategory | None:
        return self.animations[name] if name in self.animations.keys() else None

    def __load_animations(self, config: dict[str, any]) -> AssetAnimationManager:
        for animation_type, animation_config in config.items():
            self.animations[animation_type] = DataAnimationCategory(animation_config)
        return self

    def load_assets(self, category_name: str) -> DataAnimationCategory | None:
        if category_name not in self.cache.keys():
            # load the animation images
            animation = self.get(category_name)
            if animation is not None:
                if animation.file:
                    self.cache[category_name] = pygame.image.load(animation.file)
                else:
                    print(f"No file found for animation {category_name}")
                    return None
            else:
                print(f"No animation found for {category_name}")
                return None

        return self.get(category_name)

    def unload_assets(self, category_name: str):
        if category_name in self.cache.keys():
            del self.cache[category_name]
            return True
        return False

    def reload(self, config: dict[str, any] | tuple[str, any]):
        pass

    def prepare(self, config: dict[str, any]) -> AssetAnimationManager:
        return self.__load_animations(config)
