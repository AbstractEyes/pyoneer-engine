"""Probe: how many times is CoreAssetManager.__init__ actually run at boot,
and who calls it?

    .venv/Scripts/python.exe tools/probe_singleton_boot.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import traceback

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

import scripts.core.input as _input_mod
for _i in range(16):
    _input_mod.CONTROLLER.setdefault(f"button_{_i}", _i)

import config.managers.core_asset_manager as cam

_calls: list[str] = []
_original_init = cam.CoreAssetManager.__init__


def _counting_init(self, *a, **k):
    stack = traceback.extract_stack()[:-1]
    caller = stack[-1]
    _calls.append(f"{caller.filename.split('Pyoneer')[-1]}:{caller.lineno}  {caller.line}")
    return _original_init(self, *a, **k)


cam.CoreAssetManager.__init__ = _counting_init

print("=== booting the engine ===")
import main as main_module

game = main_module.MainGame(autostart=False)
game.begin(max_frames=3)

print("\n=== CoreAssetManager.__init__ ran", len(_calls), "times during boot ===")
for i, c in enumerate(_calls, 1):
    print(f"  {i}. {c}")

print("\n=== consequence ===")
print("  game.input is game.assets.inputs :", game.input is game.assets.inputs)
print("  tmx cached after boot            :",
      game.assets.maps.maps['test'].data is not None)

print("\n=== simulate one more stray construction (any module doing "
      "`Config = CoreAssetManager()`) ===")
before = game.assets.maps.maps['test'].data
cam.CoreAssetManager()
after = game.assets.maps.maps['test'].data
print("  tmx before                       :", id(before) if before else None)
print("  tmx after                        :", id(after) if after else None)
print("  live game.assets.maps is stale   :", game.assets.maps is not
      cam.CoreAssetManager().maps)
print("  game.input now orphaned          :", game.input is not game.assets.inputs)
