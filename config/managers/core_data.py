from __future__ import annotations

from abc import ABC, abstractmethod


class CoreAsset(ABC):

    @abstractmethod
    def load_assets(self, name: str): ...

    @abstractmethod
    def unload_assets(self, name: str): ...

    @abstractmethod
    def reload(self, config: dict[str, any] | tuple[str, any]): ...

    @abstractmethod
    def prepare(self, config: dict[str, any]) -> CoreAsset: ...