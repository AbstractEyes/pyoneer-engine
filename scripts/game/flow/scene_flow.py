"""A step sequencer for narrative: what step we are on, and who may act.

WHAT THIS IS AND WHAT IT REFUSES TO BE
---------------------------------------
`SceneFlow` is an ordered list of steps, a cursor, a clock, and a record of
the agency it took away so it can give exactly that back. It is roughly a
hundred lines of state machine and it contains NO WIDGETS. That is the whole
design: `scripts/core/ui/` is 3,605 lines of window, panel, grid, scroll,
text, anchor and button machinery which `main.py` drives every frame at 124
live components -- it is mounted, not dormant, and a narrative layer that
grew its own dialogue container would be the sixth thing in this repository to
be finished, correct and unattached.

So a step DRIVES a window it was handed. It calls `open()` on entry and
`close()` on exit and knows nothing else about it. `GameWindow` has both,
they are exact inverses (`visible`/`active` up, `visible`/`active`/focus
down), and they are what a window flow needs. Anything with that pair works
here -- a panel wrapper, a fade, a test double -- because the flow duck-types
it rather than importing `GameWindow`. Importing it would drag
`CoreAssetManager`'s theme load into every module that touches a flow, for a
type annotation.

WHAT "WHO HAS INPUT FOCUS, IS THE WORLD SIMULATING" ACTUALLY IS HERE
---------------------------------------------------------------------
It is `BodyState`'s agency triple, and it was already the primitive form of
this before the flow existed. The flow owns the WRITE and, more importantly,
owns the RESTORE. Three facts, all measured on this engine, that decide what
this class is allowed to claim:

  * `steerable = False` does NOT pause the world. A side-on body with it
    cleared still fell 13.772px in ten frames, because the gate is on the
    PRODUCER: `player_input` publishes an empty intent while gravity,
    terminal velocity and the vertical resolve all keep running. That is
    deliberate and documented at `input.py`. A cutscene that needs the body
    frozen mid-air must say so separately.
  * `enabled_inputs` is read by `player_input` WITH `steerable` and by every
    action behavior WITHOUT it. "A body frozen for a cutscene may not walk
    and must still be able to press continue" is not a convention, it is
    asserted in both directions by `tools/check_action.py`. So the default
    hold clears `steerable` and LEAVES `enabled_inputs` -- clearing both is
    how a visual novel locks itself out of its own advance button.
  * `simulated = False` stops a `GamePlayer` completely, animation clock
    included (measured: five frames left `current_time` at 0.000). It is read
    by `GamePlayer.core_frame_update` and by nothing else -- a bare
    `GameEntity` driven by the scene does not consult it. It is therefore
    per-entity and is NOT a world pause; there is no scene-level pause in this
    engine and this class must not be sold as one. It is offered because a
    real cutscene wants the player's own idle animation to stop, and it is
    documented at exactly the reach it has.

Each of the three is an explicit keyword with `None` meaning "leave it
alone", rather than a policy enum. A named policy would be one more
vocabulary to learn and would hide which axis moved; three optional booleans
say it in the call.

THE RESTORE IS EXACT, WHICH IS THE HALF THAT GETS FORGOTTEN
------------------------------------------------------------
`end()` puts back the value each body HAD, never `True`. The failure this
prevents is quiet and permanent: five of the six demo players are inert
precisely because their `can_move` is False, and a flow that ended by
enabling everything it touched would silently animate the scenery. A body
handed to a flow that was already unsteerable is still unsteerable
afterwards, and `tools/check_flow.py` asserts that specific case.

HOW A FIRING REACHES IT
-----------------------
`SceneFlow.on_action(entity, fired)` is shaped as an `ActionRouter` handler,
so the whole wire is one line:

    manager.actions.route(ADVANCE_ACTION, flow.on_action)

`ADVANCE_ACTION` is `interact_action`, which is the runtime half of the `use`
trigger kind (`ADVANCE_TRIGGER_KIND`) -- the editor's word, spelled here and
asserted equal to `editor.core.map_events.USE` by the check, because
`scripts/` may not import `editor/` and an agreement that is not measured is
a coincidence.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
  * **Branching.** A step has a successor and not a set of them. Choices need
    a `ListBoxComponent` that reports a selection and a `Button` that reports
    a click, and today NO widget in this engine reports a click to anything --
    `Button`'s only listener consumes the press, and the sole click route in
    the repo is `GameWindow`'s `if widget is self.close_button`. Shipping
    branch steps before that exists would be authoring against a hole.
  * **Text reveal and word wrap.** `TextComponent.text` repaints on assignment
    and `TextBox.update_carat` is already the clock pattern, so a reveal is
    expressible -- but `prepare_text` is ONE `font.render` of ONE string and
    responds to overflow by SHRINKING the font (measured: a 100-char line in a
    360x80 box asked for 18pt and rendered at 11pt). Wrapping is a real
    missing part in `text.py` and does not belong in a sequencer.
  * **`begin_text_capture`.** The obvious wrong move, written down here so it
    is not made: `InputActionManager.begin_text_capture` makes `pressed`,
    `released` AND `held` return False for EVERY verb. It is all-or-nothing,
    so a dialogue that reached for it could not advance itself. The correct
    gate is one level down and is already asserted in both directions --
    clear `steerable`, leave `enabled_inputs`, which is what this does.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from scripts.core.errors import PyoneerConfigError
from scripts.game.behavior.movement import MS_PER_DELTA
from scripts.game.behavior.state import BodyState, state_of

ADVANCE_ACTION: str = "interact_action"
"""The action token a flow advances on by default.

The runtime half of the editor's `use` trigger kind. `interact_action`'s own
registered summary already reads "The explicit interaction a `use` map trigger
is waiting for", so this is a collection of an agreement that exists rather
than a new claim.
"""

ADVANCE_TRIGGER_KIND: str = "use"
"""The AUTHORING word `ADVANCE_ACTION` serves: `editor/core/map_events.USE`.

Spelled, not imported: `scripts/` may never import `editor/`, and
`map_events.py` pulls `editor.core.layers`. `tools/check_flow.py` imports both
sides -- a check under `tools/` may -- and asserts this string equals
`map_events.USE`, so the agreement is measured on every run instead of being
a coincidence two files happen to share. When `map_events.py` moves to
`scripts/core/trigger_profile.py` this becomes an import and the check becomes
an identity test.
"""


@dataclass(frozen=True)
class FlowStep:
    """One beat of a flow: a name, a thing to show, and how it ends.

    Frozen, for the reason `ActionFired` and `MapEvent` are: the steps are the
    script, and a step that could be edited by the machinery running it is a
    script that changes while it is being read.

    `window` holds a live widget on a frozen record, which is not a
    contradiction -- the reference is fixed, the widget it points at is not.
    """

    name: str
    """What this step is, for a trace, a check or a save file. Free-form."""

    window: Any = None
    """Anything with `open()` and `close()`. Opened on entry, closed on exit.

    Duck-typed on purpose -- see the module docstring. None is a real step:
    a beat that only holds input away, or only waits, needs no widget.
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

    Same word, same meaning and same "deliberately not interpreted" contract
    as `pyoneer_payload` on a map trigger and `pyoneer_param_payload` on an
    action. A flow does not resolve it; a game that built the flow from a
    payload already knows what it meant.
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

    Not a `PyoneerGameObject` and not a `GameComponent`. It is called --
    `SceneManager.post_update` ticks the one it holds, after the scene fan-out
    has returned -- for the same reason a behavior is called: it never touches
    the event bus, so it cannot consume an event and silence a sibling, and
    landing it needs no event-system change at all.
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
        "do not touch this axis". The defaults are the measured-correct
        cutscene hold: `steerable=False` so the body stops walking,
        `enabled_inputs` untouched so it can still press continue, `simulated`
        untouched so a side-on body keeps falling rather than freezing in
        mid-air with no explanation.
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

        Deliberately NOT `not running`: "has not started" and "has finished"
        are different answers and a caller deciding whether to start one needs
        to tell them apart.
        """
        return self._done

    @property
    def elapsed_ms(self) -> float:
        """Milliseconds spent on the current step. Reset on every entry."""
        return self._elapsed_ms

    @property
    def held_bodies(self) -> Tuple[Any, ...]:
        """The bodies whose agency this flow is currently holding.

        Empty when it is not running, and empty for bodies that carry no
        `BodyState` -- a flow silently ignores those rather than raising,
        because a `GameEntity` used as scenery legitimately has no record and
        refusing it would make "which of my objects have movement behaviors"
        a question the caller has to answer before it can start a cutscene.

        Carried on the borrow record rather than derived by zipping
        `self.bodies`: a skipped body would shift that zip by one and report
        the WRONG entity as held, which is the kind of off-by-one that reads
        as correct in every test with no scenery in it.
        """
        return tuple(body for body, _, _ in self._borrowed)

    # -- the run -----------------------------------------------------------

    def begin(self) -> bool:
        """Take the agency, enter step 0. False if it was already running.

        Re-beginning a finished flow is legal and rewinds it -- a shopkeeper's
        dialogue is played more than once. What is refused is beginning one
        that is already running, because that would take a second snapshot of
        agency the flow itself has already modified, and `end()` would then
        restore the held values rather than the real ones.
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

        Returns True if a next step was entered, False if the flow ended --
        so `while flow.advance(): ...` terminates, and a caller can tell
        "moved on" from "finished" without reading two properties.
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
        here through `MS_PER_DELTA`. Taking the engine's unit rather than
        milliseconds is what lets `SceneManager.post_update` pass its own
        `delta` straight through with no arithmetic at the call site -- and a
        conversion at a call site is the ~16.7x error that still looks like it
        works.
        """
        if not self._running:
            return
        step = self.steps[self._index]
        self._elapsed_ms += delta * MS_PER_DELTA
        if step.hold_ms > 0 and self._elapsed_ms >= step.hold_ms:
            self.advance()

    def end(self) -> bool:
        """Stop here, close the open window, give the agency back exactly.

        False if it was not running. Called by `advance()` off the end, and
        callable by a game that wants a cutscene skipped -- the two paths are
        the same code, so a skipped flow cannot leave a body in a state a
        completed one would not.
        """
        if not self._running:
            return False
        self._leave()
        self._finish()
        return True

    # -- the router handler ------------------------------------------------

    def on_action(self, entity: Any, fired: Any) -> None:
        """Advance on a firing. Shaped as an `ActionRouter` handler.

        Takes `(entity, fired)` and reads neither, because WHICH action
        advanced the flow is the router's decision -- that is what routing is
        -- and re-testing the token here would be a second copy of the routing
        rule that could disagree with the first. A flow that must only advance
        for one payload is routed with that payload.
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
        actually touches -- an axis left `None` is neither saved nor written,
        so a flow cannot restore a value it never had a reason to look at.
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
