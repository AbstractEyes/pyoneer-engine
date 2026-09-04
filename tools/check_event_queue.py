"""Verify the OS event queue: what translates, what fans out, what is reported.

Three things, and they are three because the change they guard was three
things:

  1. TRANSLATION.  `PyoneerEvent.__translate` used to linear-scan every
     `GameEventType` member for every pygame event that arrived. It is a dict
     now. The table is built BOTH ways here -- the old scan, and the shipped
     `PYGAME_EVENT_TYPES` -- and compared as whole mappings, so a rewrite
     cannot silently drop a member or re-point one. The other half is
     asserted too: a pygame code no member names resolves to nothing under
     both algorithms and leaves the event as `GameEventType.PYGAME`.

  2. THE FAN-OUT.  SDL enumerates hardware at init, so the first
     `pygame.event.get()` of a run returns one `AUDIODEVICEADDED` per audio
     output device and one `JOYDEVICEADDED` per joystick. No member names
     them, nothing consumes them, and every one of them used to cost a full
     `INPUTS` fan-out over every bound object. They are kept out of
     `PYO_QUEUE` now. Counted here, not read: listeners are bound to a real
     component tree and the invocations are counted with a device event and
     without one. And the other half twice over -- a NON-device event still
     costs the full fan-out, and the device event is still sitting in `QUEUE`
     for anyone who polls for it, because filtered is not dropped.

  3. THE REPORT.  `tools/smoke.py` summed its boot dispatch counter into one
     integer. That integer read `559 + 19 * (audio devices + joysticks + 1)`,
     so it moved between machines with no code change and law 11's "name a
     smoke drift field by field or do not bless it" had nothing to name.
     `dispatch_during_boot` is a per-type mapping now. Asserted three ways
     against each other: the breakdown sums to the total, the total is what
     an INDEPENDENT count of every listener invocation during boot says, and
     every key is a real event-type name. That equality is the proof the
     REPORT changed and the BEHAVIOUR did not.

Nothing here pins an absolute dispatch count or anything about the map on
disk: every engine-scale number is a comparison between two runs in this
process, so replacing `data/maps/starter.tmx` cannot make this check lie.

    .venv/Scripts/python.exe tools/check_event_queue.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import collections
import os
import sys

import pygame

pygame.init()
pygame.display.set_mode((256, 256))

from pygame import Rect                                          # noqa: E402

import scripts.core.event_manager as EventManager                # noqa: E402
from scripts.core.component import GameComponent                 # noqa: E402
from scripts.core.event_manager import DEVICE_EVENTS, PyoneerEvent  # noqa: E402
from scripts.core.event_types import GameEventType, PYGAME_EVENT_TYPES  # noqa: E402

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_empty(label, got):
    ok = not got
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} {'[]' if ok else got}")
    if not ok:
        failures.append(label)


# ===========================================================================
print("\n1. the translation table, built both ways and compared")
# ===========================================================================

def legacy_translate(code: int):
    """The EXACT loop `PyoneerEvent.__translate` ran before the dict landed.

    Kept verbatim, including the `break`-on-first-match that makes definition
    order the tie-break, so the comparison below is against the real previous
    algorithm and not against a tidier retelling of it.
    """
    for event_type in GameEventType:
        if event_type.value[1] == code:
            return event_type
    return None


declared = [member for member in GameEventType if member.value[1] is not None]
scanned = {member.value[1]: legacy_translate(member.value[1])
           for member in declared}

expect("the scan finds a member for every declared pygame code",
       sorted(name for code, name in
              ((c, m.name) for c, m in scanned.items()) if name is None), [])
expect("the dict and the scan map the same set of pygame codes",
       sorted(PYGAME_EVENT_TYPES) == sorted(scanned), True)
expect_empty("no code resolves to a different member under the dict",
             [f"{code}: dict={PYGAME_EVENT_TYPES.get(code)} scan={member}"
              for code, member in sorted(scanned.items())
              if PYGAME_EVENT_TYPES.get(code) is not member])
expect("the two mappings are equal as mappings",
       set(PYGAME_EVENT_TYPES.items()) == set(scanned.items()), True)
# A floor, not a pin: a member added later must not shrink this, and a
# rewrite that returned an empty dict would pass every equality above if the
# scan were broken in the same direction.
expect("the table is worth having", len(PYGAME_EVENT_TYPES) >= 14, True)

# The other half of the invariant: a code NO member names must resolve to
# nothing under both algorithms. Without this, a table that mapped every
# integer to MOUSE_MOTION would satisfy everything above.
UNNAMED = [
    (pygame.USEREVENT, "USEREVENT"),
    (pygame.AUDIODEVICEADDED, "AUDIODEVICEADDED"),
    (pygame.JOYDEVICEADDED, "JOYDEVICEADDED"),
    (pygame.WINDOWSHOWN, "WINDOWSHOWN"),
    (pygame.TEXTINPUT, "TEXTINPUT"),
]
expect_empty("a code no member names resolves nowhere, both ways",
             [f"{name}: dict={PYGAME_EVENT_TYPES.get(code)} "
              f"scan={legacy_translate(code)}"
              for code, name in UNNAMED
              if code in PYGAME_EVENT_TYPES or legacy_translate(code) is not None])

# And the live constructor agrees with the table it is supposed to be using.
expect_empty("a built event carries the member the table names",
             [f"{code}: built={PyoneerEvent(GameEventType.PYGAME, pygame.event.Event(code, {})).type} "
              f"want={member}"
              for code, member in sorted(scanned.items())
              if PyoneerEvent(GameEventType.PYGAME,
                              pygame.event.Event(code, {})).type is not member])
expect_empty("a built event for an unnamed code stays PYGAME",
             [name for code, name in UNNAMED
              if PyoneerEvent(GameEventType.PYGAME,
                              pygame.event.Event(code, {})).type
              is not GameEventType.PYGAME])


# ===========================================================================
print("\n2. the fan-out: a device event costs nothing, everything else costs")
# ===========================================================================

class Probe(GameComponent):
    """Minimal concrete component that records every INPUTS it is handed."""

    def __init__(self, tag, log, **kw):
        super().__init__(**kw)
        self.tag = tag
        self.log = log
        self.bind_sync_listener(GameEventType.INPUTS, self.__on_input)

    def __on_input(self, event, *args, **kwargs):
        self.log.append(self.tag)

    def core_input_receive(self, event=None):
        return super().core_input_receive(event)


log: list[str] = []
root = Probe("root", log, bounds=Rect(0, 0, 100, 100))
child = Probe("child", log, parent=root, bounds=Rect(0, 0, 50, 50))
grand = Probe("grand", log, parent=child, bounds=Rect(0, 0, 20, 20))
root.bind_component("child", child)
child.bind_component("grand", grand)
TREE_WIDTH = 3


def drive(code: int, **attrs) -> tuple[int, int]:
    """Run one pygame event down the REAL path and count what it cost.

    `EventManager.pump_pyo` then `GameScene.core_input_receive`'s loop, which
    is exactly what `SceneManager.inputs` does minus the routes. Returns
    (pyo events produced, listener invocations).
    """
    log.clear()
    EventManager.QUEUE = [pygame.event.Event(code, attrs)]
    EventManager.PYO_QUEUE.clear()
    EventManager.pump_pyo()
    produced = len(EventManager.PYO_QUEUE)
    for pyo_event in list(EventManager.PYO_QUEUE):
        root.core_input_receive(pyo_event)
    return produced, len(log)


# WITHOUT a device event: a translated one and an untranslated one both pay
# the full fan-out. The untranslated case matters -- it proves the filter is
# about DEVICE-ness and not about whether a member happened to name the code.
expect("a translated event still fans out", drive(pygame.MOUSEMOTION, pos=(0, 0),
                                                  rel=(0, 0), buttons=(0, 0, 0)),
       (1, TREE_WIDTH))
expect("an untranslated non-device event still fans out",
       drive(pygame.USEREVENT), (1, TREE_WIDTH))

# WITH a device event: every member of the set, no pyo event, no invocation.
expect_empty("no device event reaches the fan-out",
             [f"{pygame.event.event_name(code)} -> {drive(code, which=0)}"
              for code in sorted(DEVICE_EVENTS)
              if drive(code, which=0) != (0, 0)])

# Filtered is NOT dropped: it is still in the raw queue for a subsystem that
# polls for it, the way main.py already polls for pygame.QUIT.
EventManager.QUEUE = [pygame.event.Event(pygame.AUDIODEVICEADDED,
                                         {"which": 0, "iscapture": 0})]
EventManager.pump_pyo()
expect("a filtered device event is still in the raw QUEUE",
       EventManager.get(pygame.AUDIODEVICEADDED) is not None, True)
expect("and it produced no pyo event", len(EventManager.PYO_QUEUE), 0)

# The rule is stated once and both queue builders obey it.
EventManager.QUEUE = [
    pygame.event.Event(pygame.AUDIODEVICEADDED, {"which": 0, "iscapture": 0}),
    pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_a, "mod": 0,
                                        "unicode": "a", "scancode": 4}),
]
EventManager.PYO_QUEUE.clear()
EventManager.queue()
expect("EventManager.queue() filters identically", len(EventManager.PYO_QUEUE), 1)
expect("and keeps the non-device event",
       EventManager.PYO_QUEUE[0].type if EventManager.PYO_QUEUE else None,
       GameEventType.KEY_DOWN)
EventManager.QUEUE = []
EventManager.PYO_QUEUE.clear()

# The set itself: narrow on purpose. Both halves -- the hotplug family is in,
# and nothing anyone plays the game with is.
expect_empty("every hardware hotplug code is in the set",
             [name for name, code in (
                 ("AUDIODEVICEADDED", pygame.AUDIODEVICEADDED),
                 ("AUDIODEVICEREMOVED", pygame.AUDIODEVICEREMOVED),
                 ("JOYDEVICEADDED", pygame.JOYDEVICEADDED),
                 ("JOYDEVICEREMOVED", pygame.JOYDEVICEREMOVED),
                 ("CONTROLLERDEVICEADDED", pygame.CONTROLLERDEVICEADDED),
                 ("CONTROLLERDEVICEREMOVED", pygame.CONTROLLERDEVICEREMOVED),
                 ("CONTROLLERDEVICEREMAPPED", pygame.CONTROLLERDEVICEREMAPPED),
             ) if code not in DEVICE_EVENTS])
expect_empty("no event anyone plays with is in the set",
             [name for name, code in (
                 ("MOUSEMOTION", pygame.MOUSEMOTION),
                 ("MOUSEBUTTONDOWN", pygame.MOUSEBUTTONDOWN),
                 ("KEYDOWN", pygame.KEYDOWN),
                 ("KEYUP", pygame.KEYUP),
                 ("JOYBUTTONDOWN", pygame.JOYBUTTONDOWN),
                 ("JOYAXISMOTION", pygame.JOYAXISMOTION),
                 ("QUIT", pygame.QUIT),
                 ("WINDOWRESIZED", pygame.WINDOWRESIZED),
             ) if code in DEVICE_EVENTS])

# No member may name a filtered code: a member is a promise that the event
# reaches a listener, and this set is the promise that it does not.
expect_empty("no GameEventType member names a filtered code",
             [f"{PYGAME_EVENT_TYPES[code].name} names "
              f"{pygame.event.event_name(code)}"
              for code in sorted(DEVICE_EVENTS) if code in PYGAME_EVENT_TYPES])


# ===========================================================================
print("\n3. the boot report: a breakdown, and it still adds up")
# ===========================================================================
# An INDEPENDENT count of every listener invocation, installed BENEATH the
# one smoke.py installs, so smoke's counter and this one see the same calls
# by different code. At frames=1 the whole run IS the boot -- smoke's frame
# loop is `range(frames - 1)` -- so this counter and smoke's boot counter
# must agree key for key.
sys.path.insert(0, os.path.join(_bootstrap.REPO_ROOT, "tools"))
import smoke                                                     # noqa: E402

independent: collections.Counter = collections.Counter()
real_invoke = GameComponent._GameComponent__invoke_listener


def _counting(self, typ, callback, event, *args, **kwargs):
    independent[getattr(typ, "name", str(typ))] += 1
    return real_invoke(self, typ, callback, event, *args, **kwargs)


GameComponent._GameComponent__invoke_listener = _counting


def boot(inject: list[pygame.event.Event] | None = None) -> tuple[dict, dict]:
    """One headless boot. Returns (smoke report, this check's own count)."""
    pygame.event.clear()
    for event in inject or ():
        pygame.event.post(event)
    independent.clear()
    report = smoke.run(1)
    return report, dict(sorted(independent.items()))


def breakdown_of(report: dict) -> dict:
    """The boot breakdown, or {} if the field is not a mapping at all.

    A scalar there is the exact regression this check exists to catch, and a
    scalar makes every assertion below raise instead of fail. A raised check
    is a red check, but it reports one traceback where this reports every
    assertion that noticed.
    """
    raw = report["dispatch_during_boot"]
    return raw if isinstance(raw, dict) else {}


first, first_mine = boot()

expect("dispatch_during_boot is a mapping",
       isinstance(first["dispatch_during_boot"], dict), True)
expect("it is not empty", bool(breakdown_of(first)), True)
expect_empty("every key it names is a real GameEventType member",
             [key for key in breakdown_of(first)
              if key not in GameEventType.__members__])
expect_empty("every count it names is a positive integer",
             [f"{k}={v!r}" for k, v in breakdown_of(first).items()
              if not isinstance(v, int) or v <= 0])

# THE EQUALITY THAT PROVES THE REPORT CHANGED AND THE BEHAVIOUR DID NOT.
# The old field was `sum(boot_dispatch.values())`. The breakdown must still
# sum to it, and an independent count of the same run must agree with both.
expect("the breakdown sums to the total it is reported beside",
       sum(breakdown_of(first).values()),
       first["dispatch_total_during_boot"])
expect("an independent count of the same boot agrees, key for key",
       first_mine, breakdown_of(first))
expect("and agrees on the total",
       sum(first_mine.values()), first["dispatch_total_during_boot"])

# The engine-scale with/without. `first` is not comparable to anything -- it
# is the process's first boot and pays SDL's hardware enumeration, which is
# exactly the machine-dependent cost being removed. `base` is the second
# boot, `devices` and `others` are third and fourth, and those three ARE
# comparable to each other.
base, _ = boot()
devices, _ = boot([
    pygame.event.Event(pygame.AUDIODEVICEADDED, {"which": i, "iscapture": 0})
    for i in range(6)
] + [
    pygame.event.Event(pygame.JOYDEVICEADDED, {"device_index": i})
    for i in range(6)
])
others, _ = boot([pygame.event.Event(pygame.USEREVENT, {}) for _ in range(2)])

GameComponent._GameComponent__invoke_listener = real_invoke

expect("12 injected device events change no count at all",
       breakdown_of(devices), breakdown_of(base))
expect("and change no total",
       devices["dispatch_total_during_boot"],
       base["dispatch_total_during_boot"])

# The other half: an ordinary event still costs a full fan-out, and the whole
# of the difference is INPUTS. Written as a delta rather than an absolute so
# that a different map, a different UI tree or another machine cannot move it.
base_inputs = breakdown_of(base).get("INPUTS", 0)
extra_inputs = breakdown_of(others).get("INPUTS", 0) - base_inputs
extra_total = (others["dispatch_total_during_boot"]
               - base["dispatch_total_during_boot"])
expect("2 injected non-device events DO cost a fan-out", extra_inputs > 0, True)
expect("and the fan-out is the whole of the difference",
       extra_total, extra_inputs)

# Boot is boot: the frame the engine draws is untouched by any of this.
expect_empty("no injected event changed the frame",
             [f"{label}={report['frame_hash']}"
              for label, report in (("base", base), ("devices", devices),
                                    ("others", others))
              if report["frame_hash"] != first["frame_hash"]])


print()
if failures:
    print(f"FAILED: {failures}")
    sys.exit(1)
print("event queue OK")
