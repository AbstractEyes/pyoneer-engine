"""Inject synthetic mouse/keyboard events and trace who sees them, in order.

Answers: is the current top-down dispatch order correct for UI hit-testing,
does mark_event_handled actually consume, and does an invisible-but-active
component still receive input?

    .venv/Scripts/python.exe tools/probe_input_order.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import json


def main() -> int:
    import pygame

    pygame.init()
    pygame.display.set_mode((1, 1))

    from scripts.core.component import GameComponent
    from scripts.core.event_types import GameEventType
    from scripts.core.event_manager import PyoneerEvent

    trace: list = []
    depth_of_receipt: list = []

    orig_sea = GameComponent.send_event_advanced

    def spy(self, event_type=None, event=None, *a, **kw):
        etype = event_type if isinstance(event_type, GameEventType) else getattr(
            event_type, "type", None
        )
        if etype in (
            GameEventType.INPUTS,
            GameEventType.MOUSE_DOWN,
            GameEventType.MOUSE_UP,
            GameEventType.MOUSE_MOTION,
        ):
            d = 0
            p = self.parent
            while p is not None:
                d += 1
                p = p.parent
            trace.append(
                {
                    "cls": type(self).__name__,
                    "tree_depth": d,
                    "sort_depth": self.depth,
                    "etype": etype.name,
                    "handled_on_entry": bool(
                        isinstance(event, PyoneerEvent) and event.handled
                    ),
                    "active": self.active,
                    "visible": self.visible,
                }
            )
        return orig_sea(self, event_type, event, *a, **kw)

    GameComponent.send_event_advanced = spy

    import main as main_module

    game = main_module.MainGame(autostart=False)
    game.begin(max_frames=2)

    trace.clear()

    # --- experiment 1: a click straight through the window stack -------------
    pygame.event.post(
        pygame.event.Event(
            pygame.MOUSEMOTION, {"pos": (300, 300), "rel": (1, 1), "buttons": (0, 0, 0)}
        )
    )
    pygame.event.post(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (300, 300), "button": 1})
    )
    game.tick()
    click_trace = list(trace)
    trace.clear()

    pygame.event.post(
        pygame.event.Event(pygame.MOUSEBUTTONUP, {"pos": (300, 300), "button": 1})
    )
    game.tick()
    up_trace = list(trace)
    trace.clear()

    # --- experiment 2: hide the window, keep it active -----------------------
    window = None
    for depth, layers in getattr(game.renderer, "layers", {}).items():
        for layer in layers:
            for comp in getattr(layer, "components", []):
                if type(comp).__name__ == "GameWindow":
                    window = comp
    window.visible = False
    window.active = True
    pygame.event.post(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (300, 300), "button": 1})
    )
    game.tick()
    invisible_trace = list(trace)

    def summarize(t):
        return {
            "receipts": len(t),
            "order_first_12": [
                f"{r['cls']}(tree={r['tree_depth']},sort={r['sort_depth']})" for r in t[:12]
            ],
            "any_handled_on_entry": sum(1 for r in t if r["handled_on_entry"]),
            "inactive_receipts": sum(1 for r in t if not r["active"]),
            "invisible_receipts": sum(1 for r in t if not r["visible"]),
        }

    print(
        json.dumps(
            {
                "mousedown_frame": summarize(click_trace),
                "mouseup_frame": summarize(up_trace),
                "invisible_active_window_frame": summarize(invisible_trace),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
