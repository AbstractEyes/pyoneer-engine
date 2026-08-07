"""Run every engine check, plus the smoke drift comparison.

    .venv/Scripts/python.exe tools/check_all.py
    .venv/Scripts/python.exe tools/check_all.py -v      # show each check's output

Exit code is non-zero if anything fails, so this is the one command CI needs.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import os
import subprocess
import sys

CHECKS = [
    ("imports", "one dotted name per module; LayerRenderer.bind accepts subclasses"),
    ("errors", "exception hierarchy, naming schema, single image slot"),
    ("log", "trace channels off by default, opt-in, lazy formatting"),
    ("events", "consumption, active-gating, depth setter"),
    ("input", "edge detection, multi-binding, load-time validation"),
    ("animation", "sequence switching, pause/resume, pre-sliced frames"),
    ("singletons", "one CoreAssetManager, tmx cached until reload is asked for"),
    ("window", "drag, close, focus, visibility matrix"),
    ("window_close", "visibility cascade, F1 toggle, typing suppresses movement"),
]

ROOT = _bootstrap.REPO_ROOT
PYTHON = sys.executable
verbose = "-v" in sys.argv

results = []
for name, blurb in CHECKS:
    path = os.path.join(ROOT, "tools", f"check_{name}.py")
    proc = subprocess.run([PYTHON, path], capture_output=True, text=True, cwd=ROOT)
    ok = proc.returncode == 0
    results.append((name, ok, blurb))
    print(f"  {'PASS' if ok else 'FAIL'}  check_{name:<14} {blurb}")
    if verbose or not ok:
        for line in (proc.stdout + proc.stderr).splitlines():
            if verbose or "FAIL" in line or "Error" in line:
                print(f"          {line}")

# Smoke drift is a separate concern: a change to the rendered frame is not
# automatically wrong, it just has to be intentional and re-baselined.
smoke = subprocess.run(
    [PYTHON, os.path.join(ROOT, "tools", "smoke.py"),
     "--frames", "60", "--baseline", os.path.join(ROOT, "tools", "baseline.json")],
    capture_output=True, text=True, cwd=ROOT,
)
drift_ok = smoke.returncode == 0
print(f"  {'PASS' if drift_ok else 'DRIFT'}  smoke          frame hash, component census, blit tokens")
if not drift_ok:
    for line in smoke.stdout.splitlines():
        if "DRIFT" in line or "baseline:" in line or "current" in line:
            print(f"          {line.strip()}")
    print("          -> if intended: tools/smoke.py --frames 60 --write-baseline")

failed = [n for n, ok, _ in results if not ok]
print()
if failed or not drift_ok:
    print(f"FAILED: {failed or []}{'  + smoke drift' if not drift_ok else ''}")
    sys.exit(1)
print(f"ALL {len(results)} CHECKS PASS, NO DRIFT")
