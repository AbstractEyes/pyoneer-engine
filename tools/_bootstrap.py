"""Put the repository root on sys.path.

`python main.py` works because Python puts the *script's* directory on
sys.path[0]. Anything outside the repo root -- tools, tests, a REPL -- does
not get that, so every tool in this directory imports this module first.

Exactly one path entry (the repo root) and exactly one dotted name per
module, which is what keeps `isinstance` working across the engine.
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

# Directories that sit INSIDE the repo and are not part of this working tree.
# Any check that walks the tree counting definitions must skip every one of
# them, and they live here rather than in each walker so that one edit moves
# every walker at once.  #TAG:not_this_tree
#
# `.claude/worktrees/` is the expensive one and the reason this exists: a
# background task runs in a git worktree checked out THERE, so the whole
# repository appears a second time underneath itself. A walk that counts
# `def foo` across the tree then reports two of everything and blames the
# author -- measured, as `check_demo_map` reporting `driven_record` defined
# twice while one definition was a worktree's copy of the file holding the
# other. A worktree is another checkout, never a duplicate.
NOT_THIS_TREE = frozenset({
    ".git", ".venv", "__pycache__", "node_modules", ".idea", ".vs", ".claude",
})
