from __future__ import annotations

from typing import Optional

import pygame

from scripts.core.event_types import GameEventType

# takes the concept of the pygame event queue and simplifies it to a single game-wide queue for reusable access
# the entire subset here is static, and is not meant to be instantiated

QUEUE: list[pygame.event.Event] = []
PYO_QUEUE: list[PyoneerEvent] = []
FRAME_DELTA: float = 0.0

__PROBLEM_EVENTS: list[int] = [
    pygame.MOUSEBUTTONDOWN,
    pygame.MOUSEBUTTONUP,
] # these events are problematic on macOS, and duplicates should be ignored


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
                self.data[key].core_update(value)
            elif isinstance(value, list):
                self.data[key].extend(value)
            else:
                self.data[key] = data[key]

    def __translate(self) -> GameEventType:
        """Naturally these are pygame events, so we need to convert them to the appropriate pyoneer event type."""
        typ = self.type
        if typ is GameEventType.PYGAME:
            if self.event is not None:
                for event_type in GameEventType:
                    if event_type.value[1] == self.event.type:
                        self.type = event_type
                        break
        return self.type

    def __str__(self):
        return f"PyoneerEvent: {self.type}, {self.event}, {self.data}, {self.handled}"


def update(delta: float = pygame.time.Clock().tick(60) / 1000):
    global QUEUE
    global PYO_QUEUE
    global FRAME_DELTA
    FRAME_DELTA = delta
    #pygame.event.pump()
    QUEUE = pygame.event.get(pump=True)
    pump_pyo()
    #PYO_QUEUE = get_pyo()


def queue():
    """Queues another event to the next frame's pyo queue."""
    global QUEUE
    global PYO_QUEUE
    for event in QUEUE:
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



