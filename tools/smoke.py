"""Headless smoke harness: boot the engine, run N frames, report what happened.

This is the instrument the rest of the improvement plan is verified against.
Every structural change should leave `frame_hash` and `component_census`
identical unless it is *supposed* to change them -- and when it is, the diff
tells you exactly what moved.

    .venv/Scripts/python.exe tools/smoke.py --frames 120 --out run.json
    .venv/Scripts/python.exe tools/smoke.py --frames 120 --baseline tools/baseline.json
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import argparse
import collections
import hashlib
import json
import statistics
import sys

import pygame


def _census(root, seen=None) -> collections.Counter:
    """Count every component in a widget subtree, by class name."""
    if seen is None:
        seen = set()
    counts = collections.Counter()
    if id(root) in seen:
        return counts
    seen.add(id(root))
    counts[type(root).__name__] += 1
    for child in getattr(root, "components", {}).values():
        counts.update(_census(child, seen))
    return counts


def run(frames: int) -> dict:
    import main as main_module
    from scripts.core import blitpool

    game = main_module.MainGame(autostart=False)

    # Instrument the blit pool: capture the depth/priority histogram of the
    # last frame before it is flushed and cleared.
    captured: dict = {}
    original_flush = blitpool.BlitPool.get_blit_pool_pygame

    @staticmethod
    def _spy(clear: bool = True):
        pool = blitpool.ORGANIZED_BLITS
        captured["depths"] = {
            int(d): sum(len(t) for t in pool[d].values()) for d in sorted(pool)
        }
        captured["tokens"] = sum(captured["depths"].values())
        return original_flush(clear)

    blitpool.BlitPool.get_blit_pool_pygame = _spy

    timings: list[float] = []
    game.begin(max_frames=1)  # first frame separately: it pays one-time costs
    for _ in range(max(0, frames - 1)):
        t0 = pygame.time.get_ticks()
        game.tick()
        timings.append(pygame.time.get_ticks() - t0)
        game.frame += 1

    blitpool.BlitPool.get_blit_pool_pygame = original_flush

    surface = pygame.display.get_surface()
    frame_hash = hashlib.sha256(
        pygame.image.tostring(surface, "RGB")
    ).hexdigest()[:16]

    # The UI tree bound by main.py -- this is the "expected UI components" set.
    ui_roots = []
    for depth, layers in getattr(game.renderer, "layers", {}).items():
        for layer in layers:
            for comp in getattr(layer, "components", []):
                ui_roots.append((depth, comp))

    ui_census = collections.Counter()
    for _, comp in ui_roots:
        ui_census.update(_census(comp))

    return {
        "frames": frames,
        "frame_hash": frame_hash,
        "frame_ms_median": round(statistics.median(timings), 3) if timings else None,
        "screen_size": list(surface.get_size()),
        "ui_roots": [f"{type(c).__name__}@{d}" for d, c in ui_roots],
        "ui_component_total": sum(ui_census.values()),
        "ui_component_census": dict(sorted(ui_census.items())),
        "blit_tokens": captured.get("tokens"),
        "blit_depths": captured.get("depths"),
        "renderer_layer_depths": sorted(
            int(d) for d in getattr(game.renderer, "layers", {})
        ),
        "entity_layer_counts": {
            int(d): len(getattr(layer, "entities", []))
            for d, layers in getattr(game.renderer, "layers", {}).items()
            for layer in layers
            if hasattr(layer, "entities")
        },
    }


def compare(baseline: dict, current: dict) -> list[str]:
    # Round-trip both sides: JSON stringifies int dict keys, so a freshly
    # computed {40: 5} would otherwise always "differ" from a loaded {"40": 5}.
    baseline = json.loads(json.dumps(baseline))
    current = json.loads(json.dumps(current))
    drift = []
    for key in sorted(set(baseline) | set(current)):
        if key in ("frame_ms_median", "frames"):
            continue  # timing is machine-dependent
        old, new = baseline.get(key), current.get(key)
        if old != new:
            drift.append(f"{key}:\n    baseline: {old}\n    current : {new}")
    return drift


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--out")
    ap.add_argument("--baseline")
    ap.add_argument("--write-baseline", action="store_true")
    args = ap.parse_args()

    result = run(args.frames)
    text = json.dumps(result, indent=2)
    print(text)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"\nwrote {args.out}")

    if args.write_baseline:
        with open("tools/baseline.json", "w", encoding="utf-8") as fh:
            fh.write(text)
        print("\nwrote tools/baseline.json")

    if args.baseline:
        with open(args.baseline, encoding="utf-8") as fh:
            base = json.load(fh)
        drift = compare(base, result)
        print()
        if drift:
            print(f"DRIFT vs {args.baseline} ({len(drift)} field(s)):")
            for d in drift:
                print(f"  {d}")
            return 1
        print(f"NO DRIFT vs {args.baseline}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
