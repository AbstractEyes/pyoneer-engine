"""Instrument the live event path. Read-only: patches nothing in scripts/.

    .venv/Scripts/python.exe tools/probe_events.py --frames 30
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import argparse
import collections
import json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=30)
    args = ap.parse_args()

    # The engine's module-level CoreAssetManager() touches pygame.key at import
    # time, so the video system must exist before the first engine import.
    import pygame

    pygame.init()
    pygame.display.set_mode((1, 1))

    from scripts.core.component import GameComponent
    from scripts.core.event_types import GameEventType
    from scripts.core.event_manager import PyoneerEvent

    stats = {
        "calls": collections.Counter(),        # send_event_advanced calls by etype name
        "dropped_none_event": collections.Counter(),
        "dropped_no_type": collections.Counter(),
        "dispatched": collections.Counter(),
        "callback_fired": collections.Counter(),
        "core_override_called": collections.Counter(),
        "handled_set": collections.Counter(),
        "handled_ignored_children": collections.Counter(),
    }

    orig_sea = GameComponent.send_event_advanced

    def spy_sea(self, event_type=None, event=None, *a, **kw):
        name = getattr(event_type, "name", type(event_type).__name__)
        stats["calls"][name] += 1
        if isinstance(event_type, GameEventType) and not isinstance(
            event, (dict, PyoneerEvent)
        ):
            stats["dropped_none_event"][name] += 1
        elif not isinstance(event_type, (GameEventType, PyoneerEvent)):
            stats["dropped_no_type"][name] += 1
        else:
            stats["dispatched"][name] += 1
        return orig_sea(self, event_type, event, *a, **kw)

    GameComponent.send_event_advanced = spy_sea

    # count child fan-out that happens while event.handled is already True
    orig_setc = GameComponent.send_event_to_children_advanced

    def spy_children(self, event_type=None, event=None, *a, **kw):
        if isinstance(event, PyoneerEvent) and event.handled and self.components:
            stats["handled_ignored_children"][
                getattr(event_type, "name", "?")
            ] += 1
        return orig_setc(self, event_type, event, *a, **kw)

    GameComponent.send_event_to_children_advanced = spy_children

    # wrap every subclass core_* override to see if it is ever entered
    import importlib
    import pkgutil
    import scripts

    for m in pkgutil.walk_packages(scripts.__path__, "scripts."):
        if ".tests" in m.name or ".icebox" in m.name:
            continue
        try:
            importlib.import_module(m.name)
        except Exception:
            pass

    def wrap_overrides(cls):
        for attr, fn in list(vars(cls).items()):
            if not attr.startswith("core_") or not callable(fn):
                continue
            key = f"{cls.__name__}.{attr}"
            stats["core_override_called"].setdefault(key, 0)

            def make(fn=fn, key=key):
                def wrapper(self, *a, **kw):
                    stats["core_override_called"][key] += 1
                    return fn(self, *a, **kw)

                return wrapper

            setattr(cls, attr, make())

    def all_subclasses(c):
        for s in c.__subclasses__():
            yield s
            yield from all_subclasses(s)

    for cls in set(all_subclasses(GameComponent)):
        wrap_overrides(cls)

    import main as main_module

    game = main_module.MainGame(autostart=False)
    game.begin(max_frames=args.frames)

    out = {
        k: (dict(v) if isinstance(v, collections.Counter) else v)
        for k, v in stats.items()
    }
    out["core_override_called_ZERO"] = sorted(
        k for k, v in stats["core_override_called"].items() if v == 0
    )
    out["core_override_called_NONZERO"] = {
        k: v for k, v in sorted(stats["core_override_called"].items()) if v
    }
    del out["core_override_called"]
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
