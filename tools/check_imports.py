"""Regression guard for the Segment 0 import decoupling.

Fails if any engine module is reachable under two distinct module names.
That duplication makes `component.GameComponent is not
scripts.core.component.GameComponent`, so every `isinstance` check in
LayerRenderer.bind silently rejects perfectly valid widgets -- and the
error message names the type, not the real cause, which makes it
near-undebuggable. Keep this in CI.

    .venv/Scripts/python.exe tools/check_imports.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import collections
import os
import sys

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

import scripts.core.component as component_module
from pygame import Rect

from scripts.core.component import GameComponent
from scripts.core.renderer import LayerRenderer
from scripts.core.ui.widget.containers.window import GameWindow
from scripts.core.ui.widget.draw import DrawComponent

failures: list[str] = []

# 1. One file must map to exactly one module name.
#    Scoped to files inside the repo: the stdlib legitimately aliases some of
#    its own modules (os.path IS ntpath, importlib._bootstrap is frozen), and
#    those are not ours to police.
ROOT = os.path.normcase(_bootstrap.REPO_ROOT) + os.sep
by_file: dict[str, list[str]] = collections.defaultdict(list)
for name, mod in list(sys.modules.items()):
    path = getattr(mod, "__file__", None)
    if not path:
        continue
    path = os.path.normcase(os.path.abspath(path))
    if not path.startswith(ROOT) or ".venv" in path:
        continue
    by_file[path].append(name)

duplicates = {f: n for f, n in by_file.items() if len(n) > 1}
print(f"engine modules loaded  : {len(by_file)}")
print(f"loaded under 2+ names  : {len(duplicates)}")
for path, names in duplicates.items():
    msg = f"{os.path.basename(path)} imported as {names}"
    print(f"   FAIL {msg}")
    failures.append(msg)

# 2. Class identity must hold.
if component_module.GameComponent is not GameComponent:
    failures.append("GameComponent has two distinct class objects")
if not issubclass(GameWindow, GameComponent):
    failures.append("GameWindow is not a GameComponent subclass")
print(f"GameComponent identity : {component_module.GameComponent is GameComponent}")

# 3. The call that failed before decoupling: bind a dotted-path subclass.
class _DottedWidget(DrawComponent):
    pass

renderer = LayerRenderer(pygame.display.get_surface())
try:
    renderer.bind("UI_LAYER_1", _DottedWidget(bounds=Rect(0, 0, 10, 10)))
    print("LayerRenderer.bind()    : OK")
except Exception as exc:  # noqa: BLE001 - reporting tool
    print(f"LayerRenderer.bind()    : FAIL -> {exc}")
    failures.append(f"LayerRenderer.bind rejected a dotted-path subclass: {exc}")

# 4. No bare source-root imports may reappear.
BARE = ("component", "event_types", "event_manager", "game_camera",
        "draw", "async_", "keyboard", "image", "behavior", "simple_component")
leaked = [n for n in sys.modules if n in BARE]
if leaked:
    failures.append(f"bare module names resolved: {leaked}")
print(f"bare names in sys.modules: {leaked or 'none'}")

print()
if failures:
    print("FAILED")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("PASS")
