"""Cost + ordering facts for the event repair plan.

    .venv/Scripts/python.exe tools/probe_event_cost.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import json
import timeit


def main() -> int:
    import pygame

    pygame.init()
    pygame.display.set_mode((1, 1))

    from scripts.core.component import GameComponent
    from scripts.core.event_types import GameEventType
    from scripts.core.event_manager import PyoneerEvent

    out = {}

    # 1. GameEventType.__translate linear scan cost
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (0, 0), "button": 1})
    out["translate_us_per_event"] = round(
        timeit.timeit(
            lambda: PyoneerEvent(GameEventType.PYGAME, ev, {}, False), number=20000
        )
        / 20000
        * 1e6,
        3,
    )
    out["enum_members"] = len(list(GameEventType))
    # position of MOUSE_DOWN in the scan
    out["mouse_down_scan_index"] = [
        i for i, m in enumerate(GameEventType) if m is GameEventType.MOUSE_DOWN
    ][0]

    import main as main_module

    game = main_module.MainGame(autostart=False)
    game.begin(max_frames=2)

    window = None
    for depth, layers in getattr(game.renderer, "layers", {}).items():
        for layer in layers:
            for comp in getattr(layer, "components", []):
                if type(comp).__name__ == "GameWindow":
                    window = comp

    # 2. sibling dispatch order vs. z-order (depth) inside each container
    def order_report(comp, path="root"):
        rows = []
        names = list(comp.components.keys())
        depths = [comp.components[n].depth for n in names]
        if depths != sorted(depths):
            rows.append(
                {
                    "container": f"{path}:{type(comp).__name__}",
                    "dispatch_order": [
                        f"{n}({comp.components[n].depth})" for n in names
                    ],
                    "z_order": [
                        f"{n}({comp.components[n].depth})"
                        for n in sorted(names, key=lambda k: comp.components[k].depth)
                    ],
                }
            )
        for n, c in comp.components.items():
            rows.extend(order_report(c, f"{path}/{n}"))
        return rows

    out["containers_where_dispatch_order_ne_z_order"] = order_report(window)

    # 3. total tree size + dispatches per frame
    def count(c):
        return 1 + sum(count(x) for x in c.components.values())

    out["window_subtree_size"] = count(window)

    # 4. mutation during dispatch -> RuntimeError?
    from scripts.core.ui.widget.shape import ShapeComponent
    from pygame import Rect

    # The mutation must land while the PARENT is mid-iteration over its own
    # components dict, so hang it off a child that the parent is fanning out to.
    victim = window
    child = window.components["body"]

    def mutator(event=None):
        victim.bind_component(
            "probe_injected",
            ShapeComponent(parent=victim, depth=9, bounds=Rect(0, 0, 1, 1)),
            commands=[],
        )

    child.bind_sync_listener(GameEventType.UPDATE, mutator)
    try:
        game.tick()
        out["mutate_during_dispatch"] = "no error"
    except RuntimeError as exc:
        out["mutate_during_dispatch"] = f"RuntimeError: {exc}"
    finally:
        child.unbind_event_listener(GameEventType.UPDATE, mutator)

    # 5. does unbind during dispatch blow up too?
    def unbinder(event=None):
        if "probe_injected" in victim.components:
            victim.unbind_component("probe_injected")

    child.bind_sync_listener(GameEventType.UPDATE, unbinder)
    try:
        game.tick()
        out["unbind_during_dispatch"] = "no error"
    except RuntimeError as exc:
        out["unbind_during_dispatch"] = f"RuntimeError: {exc}"

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
