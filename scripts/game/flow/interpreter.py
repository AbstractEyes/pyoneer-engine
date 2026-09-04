"""Run one event script: a step machine, a node stack, and two hard caps.

`ScriptRun` is what a loaded `Script` becomes while it is running. It is
CALLED, never dispatched to: it fits `SceneManager`'s existing duck-typed
`flow` slot on `update(delta)`, after the scene fan-out has returned.

    manager.flow = ScriptRun(script, variables=store, bodies=[player],
                             host=dialogue, scripts=every_script)
    manager.flow.begin(trigger="use", payload="keeper")

**ZERO changes to `SceneManager`. ZERO to `GameScene`. ZERO new
`GameEventType` members. ZERO contact with the event bus.** That is not a
promise, it is the shape: `GameScene.core_input_receive` hands ONE shared
`PyoneerEvent` to every bound object including the whole UI tree, and
consumption is not type-gated, so one `handle()` reached from here would
silence every sibling for the rest of the frame. `tools/check_ops.py` asserts
it from this module's PARSE TREE, with a planted decoy proving the scan can
find a `handle(` -- because a scan whose name list was wrong would look
exactly like a clean pass.

A NODE EITHER COMPLETES OR YIELDS
---------------------------------
The cursor is a STACK of (node list, index). Entering an arm pushes; running
off the end pops; a `while` re-tests its condition when its body runs out;
`stop` clears the stack. A node that completes advances the frame it came
from -- the frame OBJECT, not "the top of the stack", so a `call` that pushed
a new frame underneath the answer cannot make the caller re-run its own call
for ever.

THE TWO CAPS, AND WHY NEITHER IS A BUDGET
-----------------------------------------
  * `MAX_STEPS_PER_FRAME = 512`, and exceeding it **RAISES**, naming the
    script and the node. It does NOT silently budget the run and carry on
    next frame. RPG Maker's answer to a runaway loop is exactly that silent
    cap, and a silent cap is a hang you cannot diagnose -- the same failure
    law 13 already paid forty silent minutes for, one layer down.
  * `MAX_CALL_DEPTH = 16` script frames on the stack, root included, raising
    with the WHOLE chain. `call` may cycle; it is caught, not prevented,
    because a silent stop is a script that looks like it worked.

DELTA IS CONVERTED EXACTLY ONCE
-------------------------------
`event.data["delta"]` is milliseconds divided by 60. `update` multiplies by
`MS_PER_DELTA` once, at the top, into `node_elapsed_ms`; no op converts
anything. Two conversions is the ~16.7x error that still looks like it works.

WHAT IT TAKES, AND WHAT IT GIVES BACK
-------------------------------------
Agency goes through the shared `AgencyHold` in `scene_flow.py` -- the same
object a `SceneFlow` borrows through, so `hold` and `release` cannot drift
from a cutscene's borrow and restore. `release` puts back THE RECORDED VALUE,
never `True`: a body that was already unsteerable is still unsteerable
afterwards. A run that ends -- off the end, or through `stop` -- gives back
anything still outstanding, because a script that stranded a player
permanently unable to walk is the worst failure this file can have and the
author's `release` is one editing accident away from being deleted.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
  * **A queue.** `SceneManager.flow` is one slot on purpose: a narrative flow
    is modal, and two runs would each restore agency the other changed. The
    thing that owns "which run is next" is a caller's, and it is not written
    yet -- an unreachable class shipped early is this repository's signature
    defect, not a head start.
  * **A trigger.** Route A already exists end to end: an action behavior
    records a firing, `action_relay` calls `entity.action_sink`, and the
    `ActionRouter` picks the handler. `on_action` below is shaped as one of
    those handlers, so wiring a script to a keypress is one `route()` call.
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence, Tuple

from scripts.core.errors import (PyoneerAssetMissingError, PyoneerConfigError,
                                 PyoneerError)
from scripts.game.behavior.movement import MS_PER_DELTA
from scripts.game.flow.scene_flow import AgencyHold

MAX_STEPS_PER_FRAME: int = 512
"""How many nodes one frame may complete before the run is declared runaway.

Chosen well above any authored beat -- a page of forty nodes with three
nested arms completes in under a hundred -- and well below anything a human
would call a freeze. Exceeding it RAISES.
"""

MAX_CALL_DEPTH: int = 16
"""Script frames allowed on the stack at once, the root run included.

`call` may cycle (`a` calls `b` calls `a`), which the load graph cannot
prevent because the target is resolved at run time. Sixteen is deep enough
that no legitimate structure reaches it and shallow enough that the chain in
the error message is readable.
"""

SAY_OPEN: str = "say_open"
SAY_CLOSE: str = "say_close"
"""The two methods a SAY HOST provides, duck-typed and named here once.

    say_open(who, text)   called on the frame a `say` node is entered
    say_close()           called on the frame it completes

Duck-typed rather than annotated as `GameWindow`, for the reason
`scene_flow.py` gives: importing that would drag `CoreAssetManager`'s theme
load onto the import path of every module that touches a flow. Absent, or
present without these two, RAISES naming the method -- a `say` that showed
nothing would be a line of dialogue the player never sees and no complaint.
"""


class _Frame:
    """One node list and a cursor into it.

    `kind` decides what running off the end means:

        body     an ordinary list (a page body, a `then`, an `else`): pop
        loop     a `while` body: re-test the condition, and either restart
                 this frame or pop it
        script   a `call`ed script's body: pop, and it is what
                 `MAX_CALL_DEPTH` counts
    """

    __slots__ = ("nodes", "index", "kind", "label", "node")

    def __init__(self, nodes: Sequence[Any], kind: str, label: str,
                 node: Any = None):
        self.nodes: Tuple[Any, ...] = tuple(nodes)
        self.index: int = 0
        self.kind: str = kind
        self.label: str = label
        self.node: Any = node

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return "<%s %s %d/%d>" % (self.kind, self.label, self.index,
                                  len(self.nodes))


class ScriptRun:
    """One running event script. Ticked by whoever holds it, once per frame."""

    def __init__(self,
                 script: Any,
                 *,
                 variables: Any,
                 bodies: Sequence[Any] = (),
                 host: Any = None,
                 scripts: Any = None,
                 name: str = ""):
        """`script` is a loaded `Script`; `variables` is its `VarStore`.

        `bodies` are the entities `hold` may take agency from -- the same
        argument a `SceneFlow` takes, and skipping a body with no `BodyState`
        is the hold's job rather than the caller's.

        `host` provides `say_open` / `say_close`. `scripts` is how `call`
        finds another script: a mapping of id -> Script, or a callable taking
        an id. `None` for either is a WIRING state, and the op that needs it
        raises saying which wire is missing rather than doing nothing.
        """
        if variables is None:
            raise PyoneerConfigError(
                "ScriptRun(%r) was given no variable store. Every variable a "
                "script touches is declared by its scene, and the store is "
                "what makes reading one TOTAL at run time -- which is the "
                "whole reason no read can raise mid-cutscene."
                % (getattr(script, "id", script),))
        self.script = script
        self.variables = variables
        self.host = host
        self.name: str = name or getattr(script, "id", "script")
        self._scripts = scripts
        self._hold = AgencyHold(bodies)
        self._stack: List[_Frame] = []
        self._page: Any = None
        self._running: bool = False
        self._done: bool = False
        self._fresh: bool = True
        self._advance: bool = False
        self._node_elapsed_ms: float = 0.0
        self._steps: int = 0

    # -- inspection --------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def done(self) -> bool:
        """True once the run has finished. False before it begins.

        NOT `not running`: "has not started" and "has finished" are different
        answers, and a caller deciding whether to start one needs both.
        """
        return self._done

    @property
    def page(self) -> Any:
        """The page this run picked, or None before `begin`."""
        return self._page

    @property
    def first_step(self) -> bool:
        """Whether this is the frame the current node was ENTERED on.

        What lets a yielding op do its once-only work -- open a window,
        consume a stale advance -- without a flag of its own.
        """
        return self._fresh

    @property
    def node_elapsed_ms(self) -> float:
        """Milliseconds spent on the current node. Reset on every entry."""
        return self._node_elapsed_ms

    @property
    def steps_last_frame(self) -> int:
        """How many nodes the last `update` completed. For a trace and a check."""
        return self._steps

    @property
    def current(self) -> Any:
        """The node about to run, or None when the run is not running."""
        if not self._running or not self._stack:
            return None
        frame = self._stack[-1]
        if frame.index >= len(frame.nodes):
            return None
        return frame.nodes[frame.index]

    @property
    def call_chain(self) -> Tuple[str, ...]:
        """The scripts on the stack, outermost first. What a depth raise names."""
        return tuple(frame.label for frame in self._stack
                     if frame.kind == "script")

    @property
    def held_bodies(self) -> Tuple[Any, ...]:
        """The bodies whose agency this run is currently holding."""
        return self._hold.held_bodies

    @property
    def holding(self) -> bool:
        return self._hold.holding

    @property
    def blame(self) -> str:
        """Where the run is, as one string. Every op's message opens with it."""
        node = self.current
        return "%s%s%s" % (
            self.name,
            " page '%s'" % self._page.id if self._page is not None else "",
            " node '%s'" % node.id if node is not None else "")

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return "<ScriptRun %s %s>" % (
            self.name, self.blame if self._running
            else ("done" if self._done else "idle"))

    # -- the run -----------------------------------------------------------

    def begin(self, trigger: Optional[str] = None,
              payload: Optional[str] = None) -> bool:
        """Pick a page and start on it. False if there was nothing to run.

        Zero passing pages is NOT an error and returns False: a keeper with
        nothing to say today is a real idiom, and raising would make every
        conditional NPC a crash waiting for the wrong game state. Beginning a
        run that is already running is refused for the same reason
        `SceneFlow.begin` refuses it -- the second run would take agency this
        one has already changed, and the restore would put back the held
        values instead of the real ones.
        """
        if self._running:
            return False
        page = self.script.first_passing(self.variables, trigger, payload)
        if page is None:
            return False
        self._page = page
        self._stack = [_Frame(page.body, "script", self.script.id)]
        self._running = True
        self._done = False
        self._fresh = True
        self._advance = False
        self._node_elapsed_ms = 0.0
        return True

    def update(self, delta: float) -> None:
        """Step until the run yields, ends, or is declared runaway.

        `delta` is the ENGINE's delta -- milliseconds divided by 60, exactly
        what `event.data["delta"]` carries and what `SceneManager.post_update`
        passes straight through. It is converted HERE and nowhere else.
        """
        if not self._running:
            return
        self._node_elapsed_ms += delta * MS_PER_DELTA
        self._steps = 0
        while self._running:
            if self._steps >= MAX_STEPS_PER_FRAME:
                raise PyoneerConfigError(
                    "%s completed %d nodes in one frame without yielding, "
                    "which is the runaway cap (MAX_STEPS_PER_FRAME=%d). The "
                    "innermost node list is %r. A `while` whose condition "
                    "nothing in its body changes does this. The run is "
                    "stopped rather than budgeted: a silent cap is a hang "
                    "you cannot diagnose."
                    % (self.blame, self._steps, MAX_STEPS_PER_FRAME,
                       self._stack[-1].label if self._stack else "<empty>"))
            if not self._stack:
                self._finish()
                return
            frame = self._stack[-1]
            if frame.index >= len(frame.nodes):
                self._steps += 1
                self._leave(frame)
                continue
            node = frame.nodes[frame.index]
            try:
                if not self._step(frame, node):
                    return
            except PyoneerError as error:
                raise error.push_frame(script=self.script.id,
                                       page=getattr(self._page, "id", None),
                                       node=getattr(node, "id", None))
            self._steps += 1

    def advance(self) -> None:
        """Ask the current yielding node to move on. The 'continue' press."""
        self._advance = True

    def take_advance(self) -> bool:
        """Consume a pending advance. True if there was one."""
        pending, self._advance = self._advance, False
        return pending

    def on_action(self, entity: Any, fired: Any) -> None:
        """Advance on a firing. Shaped as an `ActionRouter` handler.

        Takes `(entity, fired)` and reads neither, exactly as
        `SceneFlow.on_action` does: which action advances a script is the
        router's decision, and re-testing the token here would be a second
        copy of the routing rule.
        """
        self.advance()

    def stop(self) -> None:
        """End the run here, releasing anything still held."""
        self._stack = []
        self._finish()

    # -- what the ops call -------------------------------------------------

    def hold(self, *, steerable: Optional[bool] = None,
             enabled_inputs: Optional[bool] = None,
             simulated: Optional[bool] = None) -> Tuple[Any, ...]:
        """Take agency. `None` on an axis means "leave this one alone"."""
        return self._hold.take(steerable=steerable,
                               enabled_inputs=enabled_inputs,
                               simulated=simulated)

    def release(self) -> Tuple[Any, ...]:
        """Give back exactly what `hold` recorded. Never `True`."""
        return self._hold.give_back()

    def host_say(self, who: str, text: str) -> None:
        self._host_call(SAY_OPEN)(who, text)

    def host_end_say(self) -> None:
        self._host_call(SAY_CLOSE)()

    def call_script(self, script_id: str) -> bool:
        """Push another script's first passing page. False if none passes.

        The called script's page filters are NOT applied: `call` is the
        author saying "run this here", so a page's `trigger` -- which answers
        "what may start this from the world" -- has no say. Its `when` still
        does, and zero passing pages is a no-op for the same reason it is in
        `begin`.
        """
        script = self._resolve_script(script_id)
        depth = len(self.call_chain) + 1
        if depth > MAX_CALL_DEPTH:
            raise PyoneerConfigError(
                "%s: `call` would make the chain %d scripts deep, past "
                "MAX_CALL_DEPTH=%d. The chain is: %s -> %s. `call` may cycle "
                "and that is caught rather than prevented, because a silent "
                "stop is a script that looks like it worked."
                % (self.blame, depth, MAX_CALL_DEPTH,
                   " -> ".join(self.call_chain), script_id))
        page = script.first_passing(self.variables)
        if page is None:
            return False
        self._stack.append(_Frame(page.body, "script", script.id))
        self._fresh = True
        self._node_elapsed_ms = 0.0
        return True

    # -- internals ---------------------------------------------------------

    def _step(self, frame: _Frame, node: Any) -> bool:
        """Run one node. False means "yield: this frame is over".

        `frame` is the frame the node came FROM and is advanced by identity,
        so a node that pushed another frame (a `call`, an `if` arm) still
        moves its own cursor on rather than running itself again.
        """
        spec = getattr(node, "spec", None)
        if spec is None:
            self._enter_control(frame, node)
            return True
        complete = spec.run(self, node.args)
        if not self._running:
            return True                      # `stop` cleared the stack
        if not complete:
            if not spec.yields:
                raise PyoneerConfigError(
                    "%s: op %r declares yields=False and its run returned "
                    "False, which would stall the script with no beat to "
                    "explain it. Either it completes in the frame it is "
                    "entered, or its spec says it yields."
                    % (self.blame, spec.name))
            self._fresh = False
            return False
        frame.index += 1
        self._fresh = True
        self._node_elapsed_ms = 0.0
        return True

    def _enter_control(self, frame: _Frame, node: Any) -> None:
        """Evaluate an `if` or a `while` and push the arm it selects.

        The parent's cursor moves FIRST, so the pushed arm pops back to the
        node after this one, and a `while` frame carries the node it came
        from so that running off its body re-tests the condition.
        """
        frame.index += 1
        self._fresh = True
        self._node_elapsed_ms = 0.0
        if node.kind == "while":
            if _passes(node.when, self.variables):
                self._stack.append(_Frame(node.body, "loop", node.id, node))
            return
        if _passes(node.when, self.variables):
            self._stack.append(_Frame(node.body, "body", node.id))
            return
        for arm in node.arms:
            if _passes(arm.when, self.variables):
                self._stack.append(_Frame(arm.body, "body", node.id))
                return
        if node.otherwise:
            self._stack.append(_Frame(node.otherwise, "body", node.id))

    def _leave(self, frame: _Frame) -> None:
        """A frame ran off its end. A loop may restart; everything else pops."""
        if frame.kind == "loop" and _passes(frame.node.when, self.variables):
            frame.index = 0
            self._fresh = True
            self._node_elapsed_ms = 0.0
            return
        self._stack.pop()
        self._fresh = True
        self._node_elapsed_ms = 0.0
        if not self._stack:
            self._finish()

    def _finish(self) -> None:
        self.release()
        self._running = False
        self._done = True
        self._stack = []
        self._fresh = True
        self._advance = False
        self._node_elapsed_ms = 0.0

    def _host_call(self, method: str) -> Callable[..., Any]:
        if self.host is None:
            raise PyoneerConfigError(
                "%s: `say` needs a host and this run was given none. A host "
                "is anything with %s(who, text) and %s() -- duck-typed, so a "
                "`GameWindow` with two lines around it qualifies."
                % (self.blame, SAY_OPEN, SAY_CLOSE))
        found = getattr(self.host, method, None)
        if not callable(found):
            raise PyoneerConfigError(
                "%s: the host (%s) has no callable %s. A say host provides "
                "%s(who, text) and %s()."
                % (self.blame, type(self.host).__name__, method, SAY_OPEN,
                   SAY_CLOSE))
        return found

    def _resolve_script(self, script_id: Any) -> Any:
        if not isinstance(script_id, str) or not script_id:
            raise PyoneerConfigError(
                "%s: `call` names %r; it names a script by its id"
                % (self.blame, script_id))
        if self._scripts is None:
            raise PyoneerConfigError(
                "%s: `call` names the script %r and this run was given no "
                "way to find one. Hand `ScriptRun(scripts=...)` a mapping of "
                "id -> Script (`scripts.loaders.script_file.load_scripts()`) "
                "or a callable that returns one."
                % (self.blame, script_id))
        if callable(self._scripts):
            return self._scripts(script_id)
        if script_id not in self._scripts:
            raise PyoneerAssetMissingError(
                "event script", script_id, available=sorted(self._scripts),
                asked_by=self.blame)
        return self._scripts[script_id]


def _passes(conditions: Sequence[Any], store: Any) -> bool:
    """Every condition holds. An empty list passes -- that is the fallback.

    Spelled here rather than imported from `scripts/loaders/script_file.py`,
    which is three lines of `all(...)` and one import direction this module
    deliberately does not have: the loader imports the op registry, and an
    interpreter that imported the loader back would put a cycle one careless
    `__init__` edit away.
    """
    return all(condition.test(store) for condition in conditions)


__all__ = ["MAX_CALL_DEPTH", "MAX_STEPS_PER_FRAME", "SAY_CLOSE", "SAY_OPEN",
           "ScriptRun"]
