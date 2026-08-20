"""A step sequencer for narrative: what step we are on, and who may act.

`SceneFlow` is an ordered list of steps, a cursor, a clock, and a record of
the agency it took away so it can give exactly that back. It contains NO
WIDGETS: a step DRIVES a window it was handed, calling `open()` on entry and
`close()` on exit and knowing nothing else about it. The window is duck-typed
rather than annotated as `GameWindow`, because importing that would drag
`CoreAssetManager`'s theme load into every module that touches a flow.

THE AGENCY IT BORROWS
---------------------
`BodyState`'s three agency axes, each an explicit keyword whose `None` means
"leave this axis alone":

  * `steerable = False` stops the body walking and does NOT pause the world.
    The gate is on the PRODUCER, so `player_input` publishes an empty intent
    while gravity and the vertical resolve keep running -- a side-on body
    still falls 13.772px in ten frames. A cutscene that needs a body frozen
    mid-air must say so separately.
  * `enabled_inputs` is read by `player_input` WITH `steerable` and by every
    action behavior WITHOUT it, which `tools/check_action.py` asserts in both
    directions. So the default hold clears `steerable` and LEAVES
    `enabled_inputs`: clearing both is how a visual novel locks itself out of
    its own advance button.
  * `simulated = False` stops a `GamePlayer` completely, animation clock
    included. Only `GamePlayer.core_frame_update` reads it, so it is
    per-entity and is NOT a world pause -- there is no scene-level pause in
    this engine. It is offered because a cutscene may want the player's idle
    animation to stop.

THE RESTORE IS EXACT
--------------------
`end()` puts back the value each body HAD, never `True`. A body handed to a
flow that was already unsteerable is still unsteerable afterwards, so a flow
cannot silently animate the scenery it borrowed.

HOW A FIRING REACHES IT
-----------------------
`SceneFlow.on_action(entity, fired)` is shaped as an `ActionRouter` handler,
so the whole wire is one line:

    manager.actions.route(ADVANCE_ACTION, flow.on_action)

`ADVANCE_ACTION` is `interact_action`, the runtime half of the `use` trigger
kind (`ADVANCE_TRIGGER_KIND`).

WHAT IS NOT HERE
----------------
  * **Branching.** A step has one successor. Choices need a widget that
    reports a click, and no widget in this engine reports one to anything.
  * **Text reveal and word wrap.** `prepare_text` is ONE `font.render` of ONE
    string and answers overflow by SHRINKING the font. Wrapping is a missing
    part of `text.py` and does not belong in a sequencer.
  * **`begin_text_capture`.** It makes `pressed`, `released` AND `held` return
    False for EVERY verb, so a dialogue reaching for it could not advance
    itself. The correct gate is one level down: clear `steerable`, leave
    `enabled_inputs`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from scripts.core.errors import PyoneerConfigError
from scripts.game.behavior.movement import MS_PER_DELTA
from scripts.game.behavior.state import BodyState, state_of

ADVANCE_ACTION: str = "interact_action"
"""The action token a flow advances on by default.

The runtime half of the editor's `use` trigger kind.
"""

ADVANCE_TRIGGER_KIND: str = "use"
"""The AUTHORING word `ADVANCE_ACTION` serves: `editor/core/map_events.USE`.

Spelled, not imported, because `scripts/` may never import `editor/`.
`tools/check_flow.py` may import both sides, and asserts this string equals
`map_events.USE` on every run.
"""


@dataclass(frozen=True)
class FlowStep:
    """One beat of a flow: a name, a thing to show, and how it ends.

    Frozen, because the steps are the script and a step the machinery could
    edit is a script that changes while it is read. `window` still holds a
    live widget: the reference is fixed, the widget it points at is not.
    """

    name: str
    """What this step is, for a trace, a check or a save file. Free-form."""

    window: Any = None
    """Anything with `open()` and `close()`. Opened on entry, closed on exit.

    None is a real step: a beat that only holds input away, or only waits,
    needs no widget.
    """

    hold_ms: float = 0.0
    """How long this step lasts. 0 means "until something advances it".

    Milliseconds, matching `cooldown_ms` and `lifetime_ms` in the behavior
    vocabulary and `pyoneer_cooldown_ms` in the trigger vocabulary. NOT delta
    units: `event.data["delta"]` is milliseconds/60, and `SceneFlow.update`
    converts through `MS_PER_DELTA` so no caller has to know that.
    """

    payload: str = ""
    """The authored key this step corresponds to, if any. Opaque.

    Carries the same "not interpreted" contract as `pyoneer_payload` on a map
    trigger and `pyoneer_param_payload` on an action: a flow never resolves it.
    """

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise PyoneerConfigError(
                "a flow step needs a non-empty name; it is what a trace, a "
                "check and a save file identify the step by, and an unnamed "
                "step in a five-step flow is reported as its index, which "
                "changes the moment anyone inserts a beat")
        if isinstance(self.hold_ms, bool) or not isinstance(self.hold_ms, (int, float)):
            raise PyoneerConfigError(
                "flow step %r declares hold_ms=%r (%s); it is a number of "
                "milliseconds" % (self.name, self.hold_ms,
                                  type(self.hold_ms).__name__))
        if self.hold_ms < 0:
            raise PyoneerConfigError(
                "flow step %r declares hold_ms=%r. A negative hold reads as "
                "'already elapsed' and would be skipped on the frame it is "
                "entered, which is indistinguishable from the step not being "
                "in the list. Use 0 to wait for an advance."
                % (self.name, self.hold_ms))


class SceneFlow:
    """An ordered run of steps, and the agency it borrows while it runs.

    Not a `PyoneerGameObject` and not a `GameComponent`: it is CALLED, by
    `SceneManager.post_update`, after the scene fan-out has returned. It never
    touches the event bus, so it cannot consume an event and silence a
    sibling.
    """

    def __init__(self,
                 steps: Sequence[FlowStep],
                 bodies: Iterable[Any] = (),
                 *,
                 name: str = "flow",
                 steerable: Optional[bool] = False,
                 enabled_inputs: Optional[bool] = None,
                 simulated: Optional[bool] = None):
        """`bodies` are the entities whose agency this flow borrows.

        The three axis keywords are what it does to them, and `None` means
        "do not touch this axis". The defaults are the cutscene hold:
        `steerable=False` so the body stops walking, `enabled_inputs`
        untouched so it can still press continue, `simulated` untouched so a
        side-on body keeps falling rather than freezing in mid-air.
        """
        self.steps: Tuple[FlowStep, ...] = tuple(steps)
        if not self.steps:
            raise PyoneerConfigError(
                "SceneFlow(%r) was given no steps. An empty flow would report "
                "`done` before it began and would still take and give back "
                "every body's agency, which is a visible freeze with no beat "
                "to explain it." % (name,))
        for step in self.steps:
            if not isinstance(step, FlowStep):
                raise PyoneerConfigError(
                    "SceneFlow(%r) was given %r as a step, which is not a "
                    "FlowStep. The record is what every consumer reads, and a "
                    "stand-in shaped like it would diverge silently."
                    % (name, step))
        self.name = name
        self.bodies: Tuple[Any, ...] = tuple(bodies)
        self._axes: Tuple[Tuple[str, Optional[bool]], ...] = (
            ("steerable", steerable),
            ("enabled_inputs", enabled_inputs),
            ("simulated", simulated),
        )
        self._index: int = -1
        self._running: bool = False
        self._done: bool = False
        self._elapsed_ms: float = 0.0
        self._borrowed: List[Tuple[Any, BodyState,
                                   Tuple[Tuple[str, bool], ...]]] = []

    # -- inspection --------------------------------------------------------

    @property
    def index(self) -> int:
        """Which step is current. -1 before `begin()` and after `end()`."""
        return self._index

    @property
    def current(self) -> Optional[FlowStep]:
        """The step being held, or None when the flow is not running."""
        if not self._running:
            return None
        return self.steps[self._index]

    @property
    def running(self) -> bool:
        return self._running

    @property
    def done(self) -> bool:
        """True once the flow has run off the end. False before it begins.

        NOT `not running`: "has not started" and "has finished" are different
        answers, and a caller deciding whether to start one needs both.
        """
        return self._done

    @property
    def elapsed_ms(self) -> float:
        """Milliseconds spent on the current step. Reset on every entry."""
        return self._elapsed_ms

    @property
    def held_bodies(self) -> Tuple[Any, ...]:
        """The bodies whose agency this flow is currently holding.

        Empty when it is not running, and it omits bodies carrying no
        `BodyState` -- scenery is skipped rather than refused.

        Read off the borrow record rather than by zipping `self.bodies`, since
        a skipped body would shift that zip by one and name the WRONG entity.
        """
        return tuple(body for body, _, _ in self._borrowed)

    # -- the run -----------------------------------------------------------

    def begin(self) -> bool:
        """Take the agency, enter step 0. False if it was already running.

        Re-beginning a FINISHED flow is legal and rewinds it. Beginning one
        that is already RUNNING is refused: the second snapshot would capture
        agency this flow had already modified, so `end()` would restore the
        held values instead of the real ones.
        """
        if self._running:
            return False
        self._borrow()
        self._done = False
        self._index = 0
        self._running = True
        self._enter()
        return True

    def advance(self) -> bool:
        """Leave the current step for the next one.

        Returns True if a next step was entered, False if the flow ended, so
        `while flow.advance(): ...` terminates.
        """
        if not self._running:
            return False
        self._leave()
        if self._index + 1 >= len(self.steps):
            self._finish()
            return False
        self._index += 1
        self._enter()
        return True

    def update(self, delta: float) -> None:
        """Advance the clock by one frame. `delta` is the ENGINE's delta.

        Milliseconds/60, exactly what `event.data["delta"]` carries, converted
        here through `MS_PER_DELTA` so `SceneManager.post_update` can pass its
        own `delta` straight through. A conversion at the call site instead is
        the ~16.7x error that still looks like it works.
        """
        if not self._running:
            return
        step = self.steps[self._index]
        self._elapsed_ms += delta * MS_PER_DELTA
        if step.hold_ms > 0 and self._elapsed_ms >= step.hold_ms:
            self.advance()

    def end(self) -> bool:
        """Stop here, close the open window, give the agency back exactly.

        False if it was not running. Called by `advance()` off the end, and by
        a game skipping a cutscene -- one path, so a skipped flow cannot leave
        a body in a state a completed one would not.
        """
        if not self._running:
            return False
        self._leave()
        self._finish()
        return True

    # -- the router handler ------------------------------------------------

    def on_action(self, entity: Any, fired: Any) -> None:
        """Advance on a firing. Shaped as an `ActionRouter` handler.

        Takes `(entity, fired)` and reads neither: which action advances the
        flow is the router's decision, and re-testing the token here would be
        a second copy of the routing rule. A flow that must advance only for
        one payload is routed with that payload.
        """
        self.advance()

    # -- internals ---------------------------------------------------------

    def _enter(self) -> None:
        self._elapsed_ms = 0.0
        window = self.steps[self._index].window
        if window is not None:
            window.open()

    def _leave(self) -> None:
        window = self.steps[self._index].window
        if window is not None:
            window.close()

    def _finish(self) -> None:
        self._restore()
        self._running = False
        self._done = True
        self._index = -1
        self._elapsed_ms = 0.0

    def _borrow(self) -> None:
        """Record each body's current agency, then apply this flow's.

        Records BEFORE writing, per body, and stores only the axes this flow
        touches: an axis left `None` is neither saved nor written.
        """
        self._borrowed = []
        for body in self.bodies:
            state = state_of(body)
            if state is None:
                continue
            saved: List[Tuple[str, bool]] = []
            for axis, wanted in self._axes:
                if wanted is None:
                    continue
                saved.append((axis, bool(getattr(state, axis))))
                setattr(state, axis, bool(wanted))
            self._borrowed.append((body, state, tuple(saved)))

    def _restore(self) -> None:
        """Put back what was taken, value by value. Never `True`."""
        for _body, state, saved in self._borrowed:
            for axis, value in saved:
                setattr(state, axis, value)
        self._borrowed = []

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        where = ("%d/%d %s" % (self._index + 1, len(self.steps),
                               self.steps[self._index].name)
                 if self._running else ("done" if self._done else "idle"))
        return "<SceneFlow %s %s>" % (self.name, where)


__all__ = ["ADVANCE_ACTION", "ADVANCE_TRIGGER_KIND", "FlowStep", "SceneFlow"]
