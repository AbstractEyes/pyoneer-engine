"""Put the repository root on sys.path for the editor process.

The editor is a separate application from the engine and runs in its own
process, but it imports a small, deliberate slice of engine code -- notably
`scripts.loaders.map_document`. Same rule as `tools/_bootstrap.py`: exactly
one path entry, exactly one dotted name per module.

The dependency direction is one-way and enforced by `tools/check_editor.py`:

    editor/  ---->  scripts/        allowed
    scripts/ ---->  editor/         never

The engine must run with `python main.py` on a clone where `editor/` has
been deleted.
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
