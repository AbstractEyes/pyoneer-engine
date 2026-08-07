"""Verify CoreAssetManager is constructed once and never silently rebuilt.

Regression guard: Singleton.__new__ returned the cached instance, but Python
still calls __init__ on it, so every `CoreAssetManager()` -- including the
module-scope `Config = CoreAssetManager()` in component.py and window.py --
rebuilt every sub-manager and dropped the parsed tmx cache.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import os
import sys
import time

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

from config.managers.core_asset_manager import CoreAssetManager

failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<46} got={got} want={want}")
    if not ok:
        failures.append(label)


print("identity and sub-manager stability")
a = CoreAssetManager()
sub = (a.config, a.entity, a.animations, a.maps, a.inputs)
b = CoreAssetManager()
expect("same instance", a is b, True)
expect("config manager preserved", b.config is sub[0], True)
expect("entity manager preserved", b.entity is sub[1], True)
expect("animation manager preserved", b.animations is sub[2], True)
expect("map manager preserved", b.maps is sub[3], True)
expect("input manager preserved", b.inputs is sub[4], True)

print()
print("tmx cache survives re-construction")
tmx = a.maps.load_assets("test")
expect("map parsed", tmx is not None, True)
expect("map reports loaded", a.maps.is_loaded("test"), True)
c = CoreAssetManager()
expect("cache preserved across CoreAssetManager()", c.maps.is_loaded("test"), True)
expect("same tmx object returned", c.maps.load_assets("test") is tmx, True)

print()
print("re-parse only happens when asked")
t0 = time.perf_counter()
for _ in range(50):
    CoreAssetManager().maps.load_assets("test")
cached_ms = (time.perf_counter() - t0) * 1000
expect("50 cached loads are cheap (<50ms)", cached_ms < 50, True)
print(f"       50 cached load_assets calls took {cached_ms:.2f} ms")

forced = a.maps.load_assets("test", reload=True)
expect("reload=True returns a NEW parse", forced is not tmx, True)

print()
print("unknown map fails loudly instead of KeyError-ing on a dict")
try:
    a.maps.load_assets("no_such_map")
    expect("raises KeyError", False, True)
except KeyError as exc:
    print(f"  ok   raised: {exc}")

print()
print("config loads independently of the working directory")
cwd = os.getcwd()
try:
    os.chdir(os.path.dirname(_bootstrap.REPO_ROOT))
    CoreAssetManager.reset_singleton()
    fresh = CoreAssetManager()
    expect("config loaded from another cwd", "game" in fresh.config.data, True)
finally:
    os.chdir(cwd)
    CoreAssetManager.reset_singleton()

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
