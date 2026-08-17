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

# Adding a row here is half the change. `docs/CHECKS.md` is GENERATED from this
# list, so regenerate it in the same commit or `check_docs` goes red:
#     .venv/Scripts/python.exe tools/check_docs.py --write
CHECKS = [
    ("imports", "one dotted name per module; LayerRenderer.bind accepts subclasses"),
    ("errors", "exception hierarchy, naming schema, single image slot"),
    ("log", "trace channels off by default, opt-in, lazy formatting"),
    ("viewclip", "exact-pixel clipping, containment, off-screen culling"),
    ("maplayers", "empty layers dropped, composites exact, rebake reproducible"),
    ("grid", "grid layout, binding, sizing, scrolling inside a Panel"),
    ("anchor", "children reflow when their parent resizes"),
    ("scroll", "no-overflow scrollbars are hidden, inactive, and safe to drag"),
    ("textbox", "placeholder semantics, text placement, font auto-fit"),
    ("events", "consumption, active-gating, depth setter"),
    ("transform2d", "the extracted transform, and GameComponent unchanged"),
    ("input", "edge detection, multi-binding, load-time validation"),
    ("animation", "sequence switching, pause/resume, pre-sliced frames"),
    ("singletons", "one CoreAssetManager, tmx cached until reload is asked for"),
    ("tmx_roundtrip", "byte-identical tmx save, minimal-diff tile and object edits"),
    ("tileset", "byte-exact tileset add/remove, gid-range and extent guards"),
    ("tileset_verbs", "tileset add/remove/restore verbs with exact undo"),
    ("blitmap", "the native .blitmap/.tileset format and the tmx converter"),
    ("blitmap_engine", "the engine loads a .blitmap equivalently to its tmx"),
    ("spawn", "object layer -> entity registry, depth resolution, y-origin"),
    ("spawn_runtime", "map objects become bound entities at the right depths"),
    ("behavior", "behavior contract, registry, declared order, ordered drive"),
    ("state", "the shared body-state axes, and the two bodies translated onto them"),
    ("movement", "top-down and platformer bodies, the intent, the animator"),
    ("behavior_docs", "BEHAVIORS.md is generated, and every column is backed"),
    ("action", "discrete verbs, cooldowns, the per-entity record, no bus"),
    ("lifecycle", "a body declares itself gone, and is really unbound, undrawn "
                  "and forgotten"),
    ("flow", "action routing, the step sequencer, and the agency it gives back"),
    ("window", "drag, close, focus, visibility matrix"),
    ("window_close", "visibility cascade, F1 toggle, typing suppresses movement"),
    ("window_events", "os window events translate, route, and still fan out"),
    ("editor", "scopes, command stream, exact undo, genre rules, requests"),
    ("paint", "strokes, stamps, flood fill, one drag is one transaction"),
    ("autotile", "corner masks, terrain recovery, diagonal policy"),
    ("collision", "three-level resolution, .blitmask round trip, mask encoding"),
    ("collision_view", "collision overlay builds, glyphs distinguish direction "
                       "bits, a read past a companion's edge abstains"),
    ("map_events", "trigger vocabulary, collision filters, tmx round trip"),
    ("collision_mount", "the overlay, the mode, one stroke one transaction, "
                        "a 4x map whose mask lands under the cursor, and the "
                        "resolution a created companion is given"),
    ("collision_runtime", "the engine reads a mask and gates movement"),
    ("collision_field", "map load bakes passability and every body is handed it"),
    ("actions_panel", "trigger authoring, action verbs, exact inverses"),
    ("behavior_ui", "behavior checklist from the registry, refusals at "
                    "authoring time, exact undo"),
    ("editor_ui", "panels build, canvas edits are commands, responses apply"),
    ("demos", "three prototype games boot headless and answer injected input"),
    ("prototype", "the design form resolves against the registries, and its "
                  "worked example boots"),
    ("docs", "the doc spine: navigation, #TAG anchors, the generated code map, "
             "fact drift"),
]

ROOT = _bootstrap.REPO_ROOT
PYTHON = sys.executable
verbose = "-v" in sys.argv

results = []
skipped = []
for name, blurb in CHECKS:
    path = os.path.join(ROOT, "tools", f"check_{name}.py")
    # timeout is not belt-and-braces: a check that blocks on a modal dialog
    # makes this script never return, and a suite that hangs is strictly
    # worse than one that fails -- it looks like a slow machine. Measured:
    # check_collision_mount blocked on QMessageBox.question for 40+ minutes
    # with zero output and no way to tell it from a long run.
    try:
        proc = subprocess.run([PYTHON, path], capture_output=True, text=True,
                              cwd=ROOT, timeout=600)
    except subprocess.TimeoutExpired:
        results.append((name, False, blurb))
        print(f"  HANG  check_{name:<14} exceeded 600s -- probably blocked on "
              f"a dialog or waiting on input")
        continue
    ok = proc.returncode == 0
    # A check may opt out when an OPTIONAL dependency is absent -- the editor
    # needs PySide6 and the engine does not. Report that as SKIP, never as
    # PASS: a check that did not run has proved nothing.
    if ok and proc.stdout.lstrip().startswith("SKIP"):
        skipped.append(name)
        reason = proc.stdout.strip().splitlines()[0][4:].strip()
        print(f"  SKIP  check_{name:<14} {reason}")
        continue
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
# Distinguish "the frame changed" from "the harness could not run". Both used
# to print DRIFT and invite a re-baseline -- so a crash that never rendered a
# frame looked like an intentional visual change, and the suggested fix was to
# bless it.
smoke_ran = "frame_hash" in smoke.stdout
drift_ok = smoke.returncode == 0
if not smoke_ran:
    print("  ERROR smoke          harness could not run - no frame was rendered")
    for line in (smoke.stdout + smoke.stderr).splitlines()[-6:]:
        if line.strip():
            print(f"          {line.rstrip()}")
    print("          (no baseline change will fix this; the engine failed to boot)")
elif drift_ok:
    print("  PASS  smoke          frame hash, component census, blit tokens")
else:
    print("  DRIFT smoke          frame hash, component census, blit tokens")
    for line in smoke.stdout.splitlines():
        if "DRIFT" in line or "baseline:" in line or "current" in line:
            print(f"          {line.strip()}")
    print("          -> if intended: tools/smoke.py --frames 60 --write-baseline")

failed = [n for n, ok, _ in results if not ok]
print()
if failed or not drift_ok or not smoke_ran:
    print(f"FAILED: {failed or []}{'  + smoke drift' if not drift_ok else ''}")
    sys.exit(1)
tail = f", {len(skipped)} SKIPPED ({', '.join(skipped)})" if skipped else ""
print(f"ALL {len(results)} CHECKS PASS, NO DRIFT{tail}")
