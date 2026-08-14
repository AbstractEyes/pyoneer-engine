"""Verify that OS window events translate, route, and still fan out.

smoke.py can never cover this. Under SDL_VIDEODRIVER=dummy the driver never
generates a WINDOWRESIZED or a WINDOWFOCUSLOST on its own, so the routes fire
zero times across a 60-frame run and a regression here is invisible to drift.
Everything below posts the events by hand.

Three separate things are asserted, and the middle one is the point:

  1. translation      a pygame code resolves to exactly one GameEventType
  2. addition         a route runs IN ADDITION to the component fan-out
  3. the trap         a route that consumes cuts the component tree out

(3) is written as a PASSING check on purpose. It encodes the failure mode
rather than the fix, so the next person who adds `event.handle()` to a route
finds out here instead of wondering why the UI went deaf.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import collections
import sys

import pygame

from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType

failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<52} got={got} want={want}")
    if not ok:
        failures.append(label)


def code_of(member: GameEventType):
    """The pygame code a member claims, or None if it claims none."""
    value = member.value
    if isinstance(value, (tuple, list)) and len(value) > 1:
        return value[1]
    return None


# --------------------------------------------------------------------------
print("translation is exhaustive and unambiguous")
# PyoneerEvent.__translate linear-scans the enum for value[1] == event.type.
# Assert the resolution of each code the engine actually cares about. A code
# no member claims must stay PYGAME -- that is the honest answer, not a bug.
for code, name, want in [
    (pygame.WINDOWRESIZED, "WINDOWRESIZED", GameEventType.WINDOW_RESIZE),
    (pygame.WINDOWFOCUSLOST, "WINDOWFOCUSLOST", GameEventType.WINDOW_FOCUS_LOST),
    (pygame.WINDOWFOCUSGAINED, "WINDOWFOCUSGAINED", GameEventType.WINDOW_FOCUS_GAINED),
    (pygame.QUIT, "QUIT", GameEventType.QUIT),
    (pygame.MOUSEMOTION, "MOUSEMOTION", GameEventType.MOUSE_MOTION),
    # USER_EVENT was deleted from the enum, so USEREVENT resolves to nothing
    # and correctly stays as the untranslated wrapper type.
    (pygame.USEREVENT, "USEREVENT", GameEventType.PYGAME),
]:
    built = PyoneerEvent(GameEventType.PYGAME, pygame.event.Event(code, {}))
    expect(f"{name} translates", built.type, want)

# The guard that catches an accidental Enum alias when someone adds
# WINDOWSIZECHANGED next to WINDOWRESIZED with the same code.
claimed = collections.Counter(
    code_of(m) for m in GameEventType if code_of(m) is not None)
expect("no two members claim the same pygame code",
       sorted(c for c, n in claimed.items() if n > 1), [])
expect("the enum has zero aliases",
       len(list(GameEventType)), len(GameEventType.__members__))

# --------------------------------------------------------------------------
print()
print("booting the engine to drive real frames")
import main as main_module                                    # noqa: E402

game = main_module.MainGame(autostart=False)
game.begin(max_frames=1)
mouse = game.window.components["mouse"]
expect("a MouseComponentAsync is reachable on the demo window",
       type(mouse).__name__, "MouseComponentAsync")
expect("the scene manager exposes an event.type route table",
       isinstance(game.scene.routes, dict), True)
expect("WINDOW_RESIZE is routed", GameEventType.WINDOW_RESIZE in game.scene.routes, True)

# --------------------------------------------------------------------------
print()
print("a route runs IN ADDITION to the component fan-out")
route_hits = []
component_hits = []
game.scene.routes[GameEventType.WINDOW_FOCUS_LOST] = route_hits.append
mouse.bind_async_listener(GameEventType.WINDOW_FOCUS_LOST, component_hits.append)

pygame.event.post(pygame.event.Event(pygame.WINDOWFOCUSLOST, {}))
game.tick()
expect("the route saw the focus loss", len(route_hits), 1)
expect("the component ALSO saw the focus loss", len(component_hits), 1)

motion_hits = []
mouse.bind_async_listener(GameEventType.MOUSE_MOTION, motion_hits.append)
pygame.event.post(pygame.event.Event(
    pygame.MOUSEMOTION, {"pos": (5, 5), "rel": (1, 1), "buttons": (0, 0, 0)}))
game.tick()
expect("an unrouted event reaches its component unchanged", len(motion_hits), 1)

# --------------------------------------------------------------------------
print()
print("the trap: a route that consumes cuts the component tree out")
motion_hits.clear()
game.scene.routes[GameEventType.MOUSE_MOTION] = lambda event: event.handle()
pygame.event.post(pygame.event.Event(
    pygame.MOUSEMOTION, {"pos": (6, 6), "rel": (1, 1), "buttons": (0, 0, 0)}))
game.tick()
expect("a consuming route silences the component tree", len(motion_hits), 0)
del game.scene.routes[GameEventType.MOUSE_MOTION]

motion_hits.clear()
pygame.event.post(pygame.event.Event(
    pygame.MOUSEMOTION, {"pos": (7, 7), "rel": (1, 1), "buttons": (0, 0, 0)}))
game.tick()
expect("removing the consuming route restores delivery", len(motion_hits), 1)

# --------------------------------------------------------------------------
print()
print("resize actually reconfigures the engine")
# Wrap the engine's own route rather than replacing it, so the resize is
# PROVED to have been delivered. Without this the section could report ok on
# a run where no WINDOWRESIZED ever reached the route -- which is what the
# previous "20 further frames run clean" line did: it caught an exception and
# nothing else, so it printed ok whether or not the resize happened.
resize_seen = []
engine_route = game.scene.routes[GameEventType.WINDOW_RESIZE]


def spy_on_resize(event):
    resize_seen.append(event)
    engine_route(event)


game.scene.routes[GameEventType.WINDOW_RESIZE] = spy_on_resize

# A DECOY, and it is the only thing that makes the identity assertion below
# mean anything. On pygame 2.6 `set_mode` MUTATES the existing display
# Surface in place and hands back the SAME object, so
# `renderer.image() is pygame.display.get_surface()` is True before the
# resize, after a resize that re-pointed nothing, and after a resize that
# re-pointed correctly -- three different worlds, one answer. Pointing the
# renderer somewhere else first makes "it was re-pointed" a claim that can
# actually come out false.
DECOY = pygame.Surface((17, 13))
game.renderer.image(DECOY)
expect("the renderer starts on a decoy, not the display surface",
       game.renderer.image() is DECOY, True)

pygame.event.post(pygame.event.Event(pygame.WINDOWRESIZED, {"x": 1280, "y": 800}))
game.tick()
expect("the engine's resize route ran, exactly once", len(resize_seen), 1)
expect("and it carried the new size",
       [(e.event.x, e.event.y) for e in resize_seen], [(1280, 800)])
expect("the display surface resized", game.screen.get_size(), (1280, 800))
# The renderer keeping a stale surface is the failure that produces a black
# frame with no exception, so assert identity rather than size -- against the
# decoy bound above, so a route that never re-points is caught.
expect("the renderer re-took the live display surface",
       game.renderer.image() is pygame.display.get_surface(), True)
expect("and is no longer pointing at the decoy",
       game.renderer.image() is DECOY, False)
expect("the camera view area followed", tuple(game.scene.camera.view_area.size),
       (1280, 800))

# The new geometry then has to SURVIVE the frame loop. Every line below is a
# distinct failure that only shows up after the resize frame: a per-frame
# path re-taking the surface at the old size, GameCamera.update clamping
# view_area back on its next tick, or a route that re-emits its own event.
frames = 0
try:
    for _ in range(20):
        game.tick()
        frames += 1
except Exception as exc:                                       # noqa: BLE001
    print(f"  FAIL frames after resize raised: {exc}")
    failures.append("post-resize frames")
expect("20 further frames ran after the resize", frames, 20)
expect("the display is still at the new size", game.screen.get_size(), (1280, 800))
expect("the renderer still holds the live surface",
       game.renderer.image() is pygame.display.get_surface(), True)
expect("and still not the decoy", game.renderer.image() is DECOY, False)
expect("the camera view area is still the new size",
       tuple(game.scene.camera.view_area.size), (1280, 800))
expect("and no further resize was routed", len(resize_seen), 1)
game.scene.routes[GameEventType.WINDOW_RESIZE] = engine_route

expect("the window carries the RESIZABLE flag",
       bool(pygame.display.get_surface().get_flags() & pygame.RESIZABLE), True)

# --------------------------------------------------------------------------
print()
print("focus loss clears the flags that latch a drag")
# The whole reason WINDOW_FOCUS_LOST is worth routing: a window that loses
# focus mid-drag never sees the MOUSEBUTTONUP.
mouse.dragging = True
mouse.mouse_down = True
mouse.mouse_down_inside = True
mouse.mouse_inside = True
pygame.event.post(pygame.event.Event(pygame.WINDOWFOCUSLOST, {}))
game.tick()
expect("dragging cleared", mouse.dragging, False)
expect("mouse_down cleared", mouse.mouse_down, False)
expect("mouse_down_inside cleared", mouse.mouse_down_inside, False)
expect("mouse_inside cleared", mouse.mouse_inside, False)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
