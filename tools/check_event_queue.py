"""Verify the OS event queue: what translates, what fans out, what is reported.

Four things, and they are four because the changes they guard were four
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

  4. THE QUEUE SHAPE.  `pump_pyo` used to open a coalescing branch on
     `last_event == GameEventType.PYGAME`, comparing a `PyoneerEvent`
     INSTANCE to an enum member, which is constant False. That branch, its
     `append_event` pooling and its `__PROBLEM_EVENTS` macOS duplicate guard
     were deleted as a claim about this engine that was never true. Both
     halves are here. The behaviour that REMAINS is proved unchanged by
     running the deleted function verbatim beside the shipped one over a
     corpus and comparing event for event -- with the old branch instrumented,
     so the agreement is shown to come from the branch never firing and not
     from a corpus that never offered it one. And the invariant that REPLACES
     it -- a `PyoneerEvent.event` is one pygame event, never a container -- is
     asserted against the attribute names the real consumers in `scripts/`
     actually read, discovered from their AST rather than recited here.

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


# ===========================================================================
print("\n4. the queue shape: one in, one out, and the branch that never ran")
# ===========================================================================
import ast                                                       # noqa: E402


def expect_raises(label, exc, thunk):
    try:
        got = thunk()
    except exc as err:
        print(f"  ok   {label:<58} {type(err).__name__}: {err}")
        return
    except Exception as err:  # noqa: BLE001 -- the wrong exception is a failure
        print(f"  FAIL {label:<58} raised {type(err).__name__}: {err}")
        failures.append(label)
        return
    print(f"  FAIL {label:<58} returned {got!r}")
    failures.append(label)


EventManager.QUEUE = []
EventManager.PYO_QUEUE.clear()

# --- the deleted code, verbatim ------------------------------------------
# Reproduced exactly as it stood, including the `__contains__` call, so the
# comparison below is against the real previous function and not a tidier
# retelling of it. `branch_entries` counts every time the coalescing branch
# was entered; it is the number that decides whether the deletion was
# behaviour-preserving or a behaviour change wearing a bug fix's clothes.
LEGACY_PROBLEM_EVENTS: list[int] = [
    pygame.MOUSEBUTTONDOWN,
    pygame.MOUSEBUTTONUP,
]
branch_entries = 0


def legacy_append_event(pyo_event, event):
    if pyo_event.event is not list:
        pyo_event.event = [pyo_event.event]
    pyo_event.event.append(event)


def legacy_pump(queue: list) -> list:
    global branch_entries
    out: list = []
    for event in queue:
        if not EventManager.fans_out(event):
            continue
        last_event = out[-1] if len(out) > 0 else None
        if last_event is not None and last_event == GameEventType.PYGAME:
            branch_entries += 1
            if LEGACY_PROBLEM_EVENTS.__contains__(event.type):
                continue
            legacy_append_event(last_event, event)
        else:
            out.append(PyoneerEvent(GameEventType.PYGAME, event, {}, False))
    return out


def ev(code, **attrs):
    return pygame.event.Event(code, attrs)


MOTION = dict(pos=(1, 2), rel=(0, 0), buttons=(0, 0, 0))
CLICK = dict(pos=(1, 2), button=1, touch=False)
KEY = dict(key=pygame.K_a, mod=0, unicode="a", scancode=4)

# Every queue shape the branch could possibly have wanted: adjacent
# duplicates of a translated code, of an untranslated code, of the two codes
# __PROBLEM_EVENTS named, a flood, and a mixture with a filtered device event
# sitting between two duplicates.
CORPUS: dict[str, list] = {
    "empty": [],
    "one motion": [ev(pygame.MOUSEMOTION, **MOTION)],
    "2 adjacent MOUSEBUTTONDOWN": [ev(pygame.MOUSEBUTTONDOWN, **CLICK)] * 2,
    "2 adjacent MOUSEBUTTONUP": [ev(pygame.MOUSEBUTTONUP, **CLICK)] * 2,
    "8 adjacent MOUSEMOTION": [ev(pygame.MOUSEMOTION, **MOTION)] * 8,
    "2 adjacent USEREVENT (untranslated)": [ev(pygame.USEREVENT)] * 2,
    "3 unrelated untranslated": [ev(pygame.USEREVENT),
                                 ev(pygame.WINDOWSHOWN),
                                 ev(pygame.TEXTINPUT, text="x")],
    "50 adjacent KEYDOWN": [ev(pygame.KEYDOWN, **KEY)] * 50,
    "500 motion flood": [ev(pygame.MOUSEMOTION, **MOTION)] * 500,
    "alternating down/up": [ev(pygame.MOUSEBUTTONDOWN, **CLICK),
                            ev(pygame.MOUSEBUTTONUP, **CLICK)] * 4,
    "device event between duplicates": [
        ev(pygame.MOUSEMOTION, **MOTION),
        ev(pygame.AUDIODEVICEADDED, which=0, iscapture=0),
        ev(pygame.MOUSEMOTION, **MOTION),
    ],
}
OPPORTUNITIES = sum(max(len([e for e in q if EventManager.fans_out(e)]) - 1, 0)
                    for q in CORPUS.values())


def shipped_pump(queue: list) -> list:
    EventManager.QUEUE = list(queue)
    EventManager.PYO_QUEUE.clear()
    EventManager.pump_pyo()
    return list(EventManager.PYO_QUEUE)


def queued_pump(queue: list) -> list:
    EventManager.QUEUE = list(queue)
    EventManager.PYO_QUEUE.clear()
    EventManager.queue()
    return list(EventManager.PYO_QUEUE)


def shape(events: list) -> list:
    """What a consumer can actually see: the member, and WHICH pygame event."""
    return [(pyo.type.name, id(pyo.event), type(pyo.event).__name__)
            for pyo in events]


# THE EQUALITY THAT MAKES THE DELETION SAFE: for every input that reaches it,
# the function that remains produces what the deleted one did -- same count,
# same member, same pygame event object, same order.
expect_empty("the deletion changed nothing the old code would have produced",
             [f"{label}: shipped={shape(shipped_pump(q))} "
              f"legacy={shape(legacy_pump(q))}"
              for label, q in CORPUS.items()
              if shape(shipped_pump(q)) != shape(legacy_pump(q))])

# ...and the agreement is not an artefact of a corpus that never gave the old
# branch a chance. It was offered one on every event after the first.
expect("the corpus offered the deleted branch many chances",
       OPPORTUNITIES > 500, True)
expect("and it entered on none of them", branch_entries, 0)

# WHY it entered on none: the condition compared an instance to an enum
# member, and `PyoneerEvent` declares no `__eq__`, so it was constant False.
expect("PyoneerEvent declares no __eq__",
       "__eq__" in PyoneerEvent.__dict__, False)
sample = PyoneerEvent(GameEventType.PYGAME, ev(pygame.MOUSEMOTION, **MOTION))
expect_empty("no GameEventType member equals a PyoneerEvent instance",
             [member.name for member in GameEventType if sample == member])
# The other half, so "always False" is not this harness being broken: the
# comparison the branch MEANT to make does distinguish members.
expect("but comparing the event's TYPE does distinguish",
       [member.name for member in GameEventType if sample.type == member],
       ["MOUSE_MOTION"])
# And the one-line repair docs/NEXT.md item 16 proposes is not one: an
# instance's `.type` is the TRANSLATED member, so `== PYGAME` is true only
# for an event no member names -- never for the mouse duplicates the branch
# was aimed at. Both halves, in one pair.
expect("the proposed repair is false for the events it was aimed at",
       PyoneerEvent(GameEventType.PYGAME,
                    ev(pygame.MOUSEBUTTONDOWN, **CLICK)).type
       == GameEventType.PYGAME, False)
expect("and true for unrelated events it would have folded together",
       PyoneerEvent(GameEventType.PYGAME, ev(pygame.WINDOWSHOWN)).type
       == GameEventType.PYGAME, True)

# --- the invariant that replaces the branch -------------------------------
# A PyoneerEvent carries ONE pygame event. Never a container. This is the
# assertion that goes red the day pooling is re-added.
expect_empty("a pumped event never holds a container",
             [f"{label}[{i}]={type(pyo.event).__name__}"
              for label, q in CORPUS.items()
              for i, pyo in enumerate(shipped_pump(q))
              if not isinstance(pyo.event, pygame.event.Event)])
expect_empty("and EventManager.queue() agrees",
             [f"{label}[{i}]={type(pyo.event).__name__}"
              for label, q in CORPUS.items()
              for i, pyo in enumerate(queued_pump(q))
              if not isinstance(pyo.event, pygame.event.Event)])
expect_empty("one pyo event per fanned-out pygame event",
             [f"{label}: {len(shipped_pump(q))} != "
              f"{len([e for e in q if EventManager.fans_out(e)])}"
              for label, q in CORPUS.items()
              if len(shipped_pump(q))
              != len([e for e in q if EventManager.fans_out(e)])])
expect_empty("in order, and the SAME object, not a copy",
             [label for label, q in CORPUS.items()
              if [id(pyo.event) for pyo in shipped_pump(q)]
              != [id(e) for e in q if EventManager.fans_out(e)]])

EventManager.QUEUE = []
EventManager.PYO_QUEUE.clear()

# The container shape is not merely unused -- the PYGAME constructor refuses
# it, because __translate reads self.event.type. Both halves: one event in,
# the translated member out.
expect_raises("a list handed to the PYGAME constructor raises",
              AttributeError,
              lambda: PyoneerEvent(GameEventType.PYGAME,
                                   [ev(pygame.MOUSEMOTION, **MOTION)] * 2))
expect("one event handed to it translates",
       PyoneerEvent(GameEventType.PYGAME,
                    ev(pygame.MOUSEMOTION, **MOTION)).type,
       GameEventType.MOUSE_MOTION)

# --- WHY pooling was impossible, measured off the real consumers ----------
# Every `<something>.event.<attr>` in scripts/, found by walking the AST
# rather than recited here, so this cannot go stale when a consumer moves.
read_attrs: set[str] = set()
sites = 0
for folder, _dirs, files in os.walk(os.path.join(_bootstrap.REPO_ROOT,
                                                 "scripts")):
    for filename in files:
        if not filename.endswith(".py"):
            continue
        path = os.path.join(folder, filename)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), path)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr == "event"
                    and isinstance(node.value.value, ast.Name)
                    and "event" in node.value.value.id.lower()
                    and node.attr != "type"):
                read_attrs.add(node.attr)
                sites += 1

expect("scripts/ really does read a single event's attributes",
       sites >= 20, True)
expect("and the attribute names were found, not assumed",
       bool(read_attrs), True)
# A single event answers every one of them; a pooled list answers none. That
# is the whole reason the branch could not be finished as it was written.
single = ev(pygame.MOUSEBUTTONDOWN, **{name: 0 for name in sorted(read_attrs)})
expect_empty("a single event answers every attribute they read",
             [name for name in sorted(read_attrs) if not hasattr(single, name)])
expect_empty("a pooled list answers none of them",
             [name for name in sorted(read_attrs)
              if hasattr([single, single], name)])


print()
if failures:
    print(f"FAILED: {failures}")
    sys.exit(1)
print("event queue OK")
