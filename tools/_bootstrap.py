"""Put the repository root on sys.path.

`python main.py` works because Python puts the *script's* directory on
sys.path[0]. Anything outside the repo root -- tools, tests, a REPL -- does
not get that, so every tool in this directory imports this module first.

This is the one sanctioned replacement for PyCharm's 14 injected source
roots. There is exactly one path entry (the repo root) and exactly one
dotted name per module, which is what keeps `isinstance` working across
the engine.
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Headless by default; a tool that wants a real window overrides this before
# importing pygame.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
