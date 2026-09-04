from __future__ import annotations

from typing import Optional

import pygame

from scripts.core.event_types import GameEventType, PYGAME_EVENT_TYPES

# takes the concept of the pygame event queue and simplifies it to a single game-wide queue for reusable access
# the entire subset here is static, and is not meant to be instantiated

QUEUE: list[pygame.event.Event] = []
PYO_QUEUE: list[PyoneerEvent] = []
FRAME_DELTA: float = 0.0

__PROBLEM_EVENTS: list[int] = [
    pygame.MOUSEBUTTONDOWN,
    pygame.MOUSEBUTTONUP,
] # these events are problematic on macOS, and duplicates should be ignored

DEVICE_EVENTS: frozenset[int] = frozenset({
    pygame.AUDIODEVICEADDED,
    pygame.AUDIODEVICEREMOVED,
    pygame.JOYDEVICEADDED,
    pygame.JOYDEVICEREMOVED,
    pygame.CONTROLLERDEVICEADDED,
    pygame.CONTROLLERDEVICEREMOVED,
    pygame.CONTROLLERDEVICEREMAPPED,
})
"""Hardware hotplug notices: they stay in `QUEUE` and never enter `PYO_QUEUE`.

MEASURED, and this is why the number exists. SDL enumerates the machine's
hardware at `pygame.init()`, so the very first `pygame.event.get()` of a run
returns one of these per audio output device and one per joystick -- on this
machine `{'AudioDeviceAdded': 6, 'WindowShown': 1}`, on the author's
`{'JoyDeviceAdded': 1, 'AudioDeviceAdded': 6, 'WindowShown': 1}`. Nothing in
`GameEventType` names them, so `__translate` left every one of them
`GameEventType.PYGAME`, `SceneManager.inputs` handed each to
`GameScene.core_input_receive`, and every bound object dispatched it under the
constant `INPUTS`: **19 listener invocations per device, consumed by nobody.**
That is how `dispatch_during_boot` came to read `559 + 19 * (audio devices +
joysticks + 1)` -- a number that moved between machines with no code change,
which made law 11's "name a smoke drift field by field" impossible for the
one field that actually drifted.

WHY A FILTER AND NOT NEW MEMBERS. Translating these to real `GameEventType`
members would not have saved a single dispatch: `GameComponent.core_input_receive`
sends everything under `GameEventType.INPUTS` whatever the event's own type
is, so the fan-out costs the same for a translated event as for a generic
one. A member would also be a member with no listener, and `GameEventType.USE`
is the standing proof of what that costs. So the events are kept OUT of the
pyo queue, not renamed inside it.

NOT DROPPED. They stay in `QUEUE`, so `get(pygame.AUDIODEVICEADDED)` still
finds them and a subsystem that genuinely wants to know a device appeared --
audio being the obvious one -- polls for it the same way `main.py` already
polls for `pygame.QUIT`. The day such a consumer exists and wants the fan-out
instead, it brings its own member AND its own listener in one change, and
takes the type out of this set.
"""  # #TAG:device_events_not_fanned_out


def fans_out(event: pygame.event.Event) -> bool:
    """Whether this pygame event becomes a `PyoneerEvent` for the scene tree.

    The single statement of the rule, so `pump_pyo` and `queue` cannot
    disagree about it. Everything fans out except `DEVICE_EVENTS`.
    """
    return event.type not in DEVICE_EVENTS


class PyoneerEvent:
    """The Pyoneer event class."""
    def __init__(self,
                 event_type: GameEventType,
                 py_event: pygame.event.Event | list[pygame.event.Event] | None = None,
                 data: Optional[dict] = None,
                 handled: bool = False,
                 trickle: bool = False,
                 sender: any = None):
        self.type: GameEventType = event_type
        """The type of event, from the GameEventType enum."""
        self.event: pygame.event.Event | list[pygame.event.Event] | None = py_event
        """The pygame event that this Pyoneer event is based on, can pool matching events in sequence."""
        self.data: dict[str, any] = data
        """The specific set data associated with the event, if any."""
        self.handled: bool = handled
        """Whether the event has been handled and consumed. Consumption removes the event from execution."""
        self.sender = sender
        """The manual sender of the event, if any."""
        self.trickle: bool = trickle
        """Whether the event should trickle down to other objects in the hierarchy."""
        self.type = self.__translate()

    def handle(self):
        """Marks the event as handled."""
        self.handled = True

    def append_event(self, event: pygame.event.Event):
        """Appends a pygame event to the event list."""
        if self.event is not list:
            self.event = [self.event]
        self.event.append(event)

    def update_data(self, data: dict):
        """Appends data to the event data."""
        for key, value in data.items():
            if isinstance(value, dict):
                self.data[key].core_frame_update(value)
            elif isinstance(value, list):
                self.data[key].extend(value)
            else:
                self.data[key] = data[key]

    def __translate(self) -> GameEventType:
        """Naturally these are pygame events, so we need to convert them to the appropriate pyoneer event type.

        One dict lookup where this used to be a linear scan over every member
        of `GameEventType` for every pygame event that arrived. Same answer:
        `PYGAME_EVENT_TYPES` is built from the same members in the same order
        and keeps the first that claims a pygame type, which is what the old
        loop's `break` did. An unnamed type still leaves `self.type` as
        `GameEventType.PYGAME`.
        """
        typ = self.type
        if typ is GameEventType.PYGAME:
            if self.event is not None:
                translated = PYGAME_EVENT_TYPES.get(self.event.type)
                if translated is not None:
                    self.type = translated
        return self.type

    def __str__(self):
        return f"PyoneerEvent: {self.type}, {self.event}, {self.data}, {self.handled}"


def update(delta: float = pygame.time.Clock().tick(60) / 1000):
    global QUEUE
    global PYO_QUEUE
    global FRAME_DELTA
    FRAME_DELTA = delta
    QUEUE = pygame.event.get(pump=True)
    pump_pyo()


def queue():
    """Queues another event to the next frame's pyo queue."""
    global QUEUE
    global PYO_QUEUE
    for event in QUEUE:
        if not fans_out(event):
            continue
        pyo_event = PyoneerEvent(GameEventType.PYGAME, event, {}, False)
        PYO_QUEUE.append(pyo_event)


def get(event: pygame.event.EventType | int | None = None, consume: bool = False) -> list[pygame.event.Event] | pygame.event.Event | None:
    global QUEUE
    if event is None:
        cop = list(QUEUE)
        if consume:
            QUEUE.clear()
        if len (QUEUE) == 1:
            return cop[0]
        return cop
    elif event is not None:
        for ev in QUEUE:
            if event == ev.type:
                # consuming will remove it from the queue
                QUEUE.remove(ev) if consume else None
                return ev
    return None # return none if no event is found


def pump_pyo():
    global PYO_QUEUE
    global QUEUE
    PYO_QUEUE.clear()
    for event in QUEUE:
        # A hardware hotplug notice never becomes a PyoneerEvent -- see
        # DEVICE_EVENTS. It is still in QUEUE for anyone who polls for it.
        if not fans_out(event):
            continue

        # make a Pyoneer event from the pygame event
        last_event = PYO_QUEUE[-1] if len(PYO_QUEUE) > 0 else None
        if last_event is not None and last_event == GameEventType.PYGAME:
            # if the last pyo_queue event type matches this type, append the PyoneerEvent
            if __PROBLEM_EVENTS.__contains__(event.type):
                # check for problem events
                continue
            last_event.append_event(event)
        else:
            pyo_event = PyoneerEvent(GameEventType.PYGAME, event, {}, False)
            PYO_QUEUE.append(pyo_event)
    pass


def get_pyo(event: pygame.event.Event | int | None = None, consume: bool = False) -> list[PyoneerEvent] | PyoneerEvent:
    # construct the queue of Pyoneer events to replace the pygame event queue
    global PYO_QUEUE
    if event is None:
        if consume:
            cop = PYO_QUEUE.copy()
            PYO_QUEUE.clear()
        else:
            cop = PYO_QUEUE
        return cop
    elif event is int and event is not pygame.event.Event:
        output = []
        for pyo_event in PYO_QUEUE:
            if pyo_event.event == event:
                # consuming will remove it from the queue
                PYO_QUEUE.remove(pyo_event) if consume else None
                output.append(pyo_event)
        if len (output) == 1:
            return output[0]
        return output
    elif event is pygame.event.Event:
        for pyo_event in PYO_QUEUE:
            if pyo_event.event == event:
                # consuming will remove it from the queue
                PYO_QUEUE.remove(pyo_event) if consume else None
                return pyo_event
    return []  # return none if no event is found



