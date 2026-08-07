"""How many live components would an `active`-gate switch off today?

    .venv/Scripts/python.exe tools/probe_active_census.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import collections
import json


def main() -> int:
    import pygame

    pygame.init()
    pygame.display.set_mode((1, 1))

    import main as main_module

    game = main_module.MainGame(autostart=False)
    game.begin(max_frames=2)

    active_t = collections.Counter()
    active_f = collections.Counter()
    listener_owners = collections.Counter()

    def walk(c):
        (active_t if c.active else active_f)[type(c).__name__] += 1
        if getattr(c, "callbacks", None):
            listener_owners[type(c).__name__] += 1
        for x in c.components.values():
            walk(x)

    for depth, layers in getattr(game.renderer, "layers", {}).items():
        for layer in layers:
            for comp in getattr(layer, "components", []):
                walk(comp)

    print(
        json.dumps(
            {
                "active_true": dict(sorted(active_t.items())),
                "active_true_total": sum(active_t.values()),
                "active_false": dict(sorted(active_f.items())),
                "active_false_total": sum(active_f.values()),
                "classes_with_sync_callbacks": dict(sorted(listener_owners.items())),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
