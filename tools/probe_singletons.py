"""Probe: prove the singleton / global-state defects by execution.

    .venv/Scripts/python.exe tools/probe_singletons.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import os
import sys

import pygame

# ORDERING HAZARD, LIVE: `Config = CoreAssetManager()` runs at component.py:16
# during *import*. Today that import-time call reaches pygame.key.get_pressed(),
# which needs an initialised video system. So the module graph cannot even be
# imported unless the importer happens to have called pygame.init()/set_mode()
# first. main.py gets away with it only because MainGame.__init__ calls
# pygame.init() before the first `from scripts.core...` line executes... which
# it does NOT -- see run at the bottom. This probe therefore has to init pygame
# manually BEFORE touching the engine, which is exactly the bug.
pygame.init()
pygame.display.set_mode((64, 64))

# --- TRANSIENT SHIM -------------------------------------------------------
# As of this run another worker's in-flight input.py adds validate_bindings(),
# which hard-fails boot because config/inputs.json binds gamepad:button_0/1/9
# and CONTROLLER has no such names. Not my file to fix; widen the table so the
# probe can reach the singleton behaviour it is actually measuring.
import scripts.core.input as _input_mod
for _i in range(16):
    _input_mod.CONTROLLER.setdefault(f"button_{_i}", _i)
# --------------------------------------------------------------------------

from config.managers.core_asset_manager import CoreAssetManager, Singleton


def line(t):
    print("\n" + "=" * 8 + " " + t + " " + "=" * 8)


line("1. identity: is CoreAssetManager() actually one object?")
a = CoreAssetManager()
b = CoreAssetManager()
print("  a is b                       :", a is b)
print("  Singleton._instance          :", Singleton.__dict__.get("_instance"))
print("  CoreAssetManager._instance   :", type(CoreAssetManager.__dict__.get("_instance")).__name__)

line("2. do the SUB-managers survive re-construction?")
cfg1, ent1, ani1, map1, inp1 = a.config, a.entity, a.animations, a.maps, a.inputs
c = CoreAssetManager()
print("  CoreAssetManager() is same   :", c is a)
print("  .config    identity kept     :", c.config is cfg1)
print("  .entity    identity kept     :", c.entity is ent1)
print("  .animations identity kept    :", c.animations is ani1)
print("  .maps      identity kept     :", c.maps is map1)
print("  .inputs    identity kept     :", c.inputs is inp1)
print("  sub-managers are Singletons? :",
      [issubclass(t, Singleton) for t in
       (type(cfg1), type(ent1), type(ani1), type(map1), type(inp1))])

line("3. TMX cache: does re-construction wipe a loaded map?")
pygame.init()
pygame.display.set_mode((64, 64))
m = CoreAssetManager()
tmx1 = m.maps.load_assets("test")
print("  loaded tmx                   :", type(tmx1).__name__, id(tmx1))
print("  cached on MapData?           :", m.maps.maps['test'].data is tmx1)
m2 = CoreAssetManager()          # <-- ordinary attribute access pattern in the engine
tmx_after = m2.maps.maps['test'].data
print("  after CoreAssetManager()     :", tmx_after)
print("  CACHE WIPED                  :", tmx_after is None)
tmx2 = m2.maps.load_assets("test")
print("  reload gives new object      :", tmx2 is not tmx1, id(tmx2))

line("4. cost of an accidental re-construct")
import time
t0 = time.perf_counter()
CoreAssetManager()
print(f"  one CoreAssetManager() call  : {(time.perf_counter()-t0)*1000:.2f} ms (rebuilds every sub-manager)")

line("5. InputActionManager rebind state destroyed by re-construct")
m3 = CoreAssetManager()
m3.inputs.actions["__probe_marker__"] = "sentinel"
m4 = CoreAssetManager()
print("  marker survives              :", "__probe_marker__" in m4.inputs.actions)

line("6. ConfigManager is CWD-dependent (os.listdir('config'))")
print("  cwd                          :", os.getcwd())
os.chdir(os.path.dirname(_bootstrap.REPO_ROOT))
try:
    CoreAssetManager()
    print("  construct from parent cwd    : OK (unexpected)")
except Exception as e:
    print("  construct from parent cwd    :", type(e).__name__, e)
finally:
    os.chdir(_bootstrap.REPO_ROOT)

line("7. module globals: identity across re-import")
from scripts.core import blitpool, event_manager
import importlib
import __init__ as pyoneer_root

print("  blitpool.ORGANIZED_BLITS id  :", id(blitpool.ORGANIZED_BLITS))
blitpool.ORGANIZED_BLITS[999] = {0: []}
importlib.reload(blitpool)
print("  after reload, id             :", id(blitpool.ORGANIZED_BLITS),
      "-> survives:", 999 in blitpool.ORGANIZED_BLITS)
print("  BlitPool.blit_to_layer binds :",
      "module-global by name (rebinding on reload breaks aliases held elsewhere)")

line("8. event_manager QUEUE rebinding")
q_before = event_manager.QUEUE
alias = event_manager.QUEUE
event_manager.update(0.016)
print("  QUEUE object identity kept   :", event_manager.QUEUE is q_before)
print("  -> stale alias held by caller:", alias is event_manager.QUEUE)
print("  (event_manager.update line 86 REBINDS QUEUE, it does not mutate it)")

line("9. root registry")
print("  __init__.__object_registry__ :", len(pyoneer_root.__object_registry__), "entries after full boot")

line("10. two MainGame() in one process -- test-order dependence")
import main as main_module
g1 = main_module.MainGame(autostart=False)
n1 = len(pyoneer_root.__object_registry__)
blits1 = dict(blitpool.ORGANIZED_BLITS)
g2 = main_module.MainGame(autostart=False)
n2 = len(pyoneer_root.__object_registry__)
print("  registry after 1 game        :", n1)
print("  registry after 2 games       :", n2, "(leaked:", n2 - n1, ")")
print("  g1.assets is g2.assets       :", g1.assets is g2.assets)
print("  g1.assets.maps is g2.assets.maps:", g1.assets.maps is g2.assets.maps)
print("  g1.input is g2.input         :", g1.input is g2.input)
print("  ORGANIZED_BLITS depths       :", sorted(blitpool.ORGANIZED_BLITS))
g1.tick()
print("  g1.tick() after g2 built     : ran; blits now", sum(
    len(v) for d in blitpool.ORGANIZED_BLITS.values() for v in d.values()))
