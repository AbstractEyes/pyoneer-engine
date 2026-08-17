"""The game-side narrative kit: a dialogue box, a step adapter, and the wiring.

WHAT THIS IS FOR
----------------
`scripts/game/flow/scene_flow.py` ships a sequencer with NO widgets, and says
so in its first paragraph: a step drives a window it was HANDED, calls
`open()` on entry and `close()` on exit, and knows nothing else about it.
Everything on the other side of that pair is the game's, and this module is
one game's answer. It is the fourth demo's half of the contract, kept out of
`scripts/` for the reason `demos/behaviors.py` is: proving an extension point
is only proof when the extension lives outside the thing it extends.

THE ONE REAL FINDING, WRITTEN WHERE IT WAS FOUND
------------------------------------------------
A `FlowStep` carries `name`, `window`, `hold_ms` and `payload`. It carries no
TEXT. So "a dialogue box that shows a different line on each beat" is not
expressible by handing the same `GameWindow` to every step -- that reopens one
box saying one thing three times, which looks like a flow that is not
advancing.

The duck type is what saves it, and `StoryLine` below is the whole fix: an
object with `open()`/`close()` that sets the line and then opens the shared
box. Six lines, and it is the difference between "SceneFlow cannot do
dialogue" and "SceneFlow does dialogue". The flow's own docstring anticipates
it -- "a panel wrapper, a fade, a test double" -- but nothing in the tree had
written one, and the shape a reader reaches for first is the one that fails.

WHAT IS STILL MISSING AND IS NOT PAPERED OVER HERE
---------------------------------------------------
  * **No word wrap.** `TextComponent.prepare_text` is ONE `font.render` of ONE
    string and answers overflow by SHRINKING the font. So a line here is
    short, and a real script needs wrapping in `scripts/core/ui/text.py` --
    not in a sequencer and not in this file.
  * **No branching.** `FlowStep` has a successor, not a set of them. A choice
    needs a widget that reports a click and nothing in this engine reports one
    yet, so this demo is a linear scene and says so.
  * **No trigger.** The flow begins at boot because the map's `use` triggers
    have no runtime reader: `editor/core/map_events.py` authors them and
    `scripts/` has no consumer. Standing next to the keeper is therefore
    scenery, not a condition. That gap is the reason the keeper is in the map:
    it is the negative control for a wire that does not exist yet.
"""
from __future__ import annotations

from typing import Any, Sequence

from pygame import Rect

from scripts.core.ui.anchor import Anchor
from scripts.core.ui.widget.text import TextComponent
from scripts.core.ui.widget.containers.window import GameWindow
from scripts.game.flow.router import ANY_PAYLOAD
from scripts.game.flow.scene_flow import ADVANCE_ACTION, FlowStep, SceneFlow

from demos.runtime import DemoGame

BOX_BOUNDS = Rect(120, 400, 560, 120)
"""Where the dialogue box sits. Bottom-ish and wide, like every dialogue box."""


class StoryBox(GameWindow):
    """A `GameWindow` with one line of text in it. That is the entire widget.

    Derives `GameWindow` rather than composing one, because `open()` and
    `close()` are the pair `SceneFlow` drives and they are already exact
    inverses here -- `visible`/`active` up, `visible`/`active`/focus down.
    Reimplementing that pair on a wrapper is how a closed dialogue box goes on
    swallowing clicks in the rectangle it used to occupy.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("header_text", "")
        kwargs.setdefault("resizable", False)
        super().__init__(*args, **kwargs)
        self.line_text: TextComponent | None = None
        self._line: str = ""

    def build_content(self):
        """Called by `GameWindow` once the chrome exists.

        The text component is built here and not in `__init__` for the reason
        every other window content is: `world_bounds` is not final until the
        component has a parent and has been prepared, so a child sized in the
        constructor is sized against the wrong rectangle.
        """
        self.line_text = TextComponent(
            parent=self, depth=2,
            bounds=Rect(10, self.header_height + 8,
                        self.local_bounds.width - 20,
                        self.local_bounds.height - self.header_height - 16),
            text=self._line,
            center=False,
            auto_fit=True)
        self.line_text.anchor = Anchor.ALL
        self.bind_component("line_text", self.line_text)

    @property
    def line(self) -> str:
        """The sentence currently shown. Assigning repaints it."""
        return self._line

    @line.setter
    def line(self, value: str) -> None:
        self._line = str(value)
        # Buffered when the chrome has not been built yet -- `build_content`
        # runs at `core_lifecycle_prepare`, and a flow may legally begin before
        # that. Writing straight through would raise on None and make "the
        # cutscene starts at boot" an ordering rule the caller has to know.
        if self.line_text is not None:
            self.line_text.text = self._line


class StoryLine:
    """One beat's window: set the shared box's line, THEN open the box.

    This is the adapter the module docstring is about. `SceneFlow` calls
    `open()` and `close()` and asks nothing else, so a step's "window" does not
    have to be a widget -- it has to be a pair of verbs. Handing every step the
    same `StoryBox` would open one box saying one thing on every beat; handing
    each step one of these changes what the box says on the way in.

    `close()` closes the shared box rather than clearing the line, so two
    consecutive steps sharing a box do not flicker an empty frame between them,
    and so a replayed flow shows the first line again rather than the last.
    """

    __slots__ = ("box", "text")

    def __init__(self, box: Any, text: str):
        self.box = box
        self.text = text

    def open(self) -> None:
        self.box.line = self.text
        self.box.open()

    def close(self) -> None:
        self.box.close()

    def __repr__(self) -> str:              # pragma: no cover - diagnostic only
        return "<StoryLine %r>" % (self.text[:32],)


def build_flow(script: Sequence[tuple[str, str, float]], box: Any,
               bodies: Sequence[Any], *, name: str = "opening") -> SceneFlow:
    """Turn `(step name, line, hold_ms)` rows into a running-ready `SceneFlow`.

    A separate function and not a `SceneFlow` subclass: the sequencer is
    finished, and a subclass would be a second place for the step vocabulary
    to be spelled. This only builds records.

    The agency keywords are left at their defaults deliberately --
    `steerable=False`, `enabled_inputs` untouched, `simulated` untouched. That
    is the measured-correct cutscene hold: the body stops walking and can
    still press continue. Clearing `enabled_inputs` too is how a visual novel
    locks itself out of its own advance button, and it is one keyword away.
    """
    steps = tuple(FlowStep(name=step_name, window=StoryLine(box, line),
                           hold_ms=hold)
                  for step_name, line, hold in script)
    return SceneFlow(steps, bodies, name=name)


class StoryGame(DemoGame):
    """A `DemoGame` that also mounts a scene flow over a dialogue box.

    Everything a narrative demo needs that a `.tmx` cannot say, and nothing
    else. `DemoGame` stays untouched: `tools/check_demos.py` asserts by name
    that it overrides exactly `load_map`, `load_test_objects` and `entity_of`,
    and a narrative hook added there would be a hook the three older demos
    carry and never use.

    A concrete story demo below this is a `MAP_NAME` and a `SCRIPT`.
    """

    SCRIPT: tuple[tuple[str, str, float], ...] = ()
    """`(step name, the line shown, hold_ms)` per beat, in order.

    `hold_ms > 0` is a beat that advances itself after that many milliseconds;
    `0` is a beat that waits for the player. Milliseconds, matching
    `cooldown_ms` and `lifetime_ms` -- `SceneFlow.update` converts from the
    engine's delta, which is milliseconds/60 and NOT seconds.
    """

    FLOW_NAME: str = "opening"
    """What a trace, a check and a save file call this flow."""

    ADVANCE_PAYLOAD: str = ANY_PAYLOAD
    """Which firing of `interact_action` advances this flow.

    `ANY_PAYLOAD` -- the empty string -- takes every firing of the token, which
    is what a game with one conversation wants. Set it to the same string the
    map puts in `pyoneer_param_payload` and this flow answers only THAT
    interaction, which is how one body's one action verb opens a different
    conversation in a different room with no second token and no second verb.
    """

    def load_test_objects(self):
        """Let `DemoGame` place the camera, then mount the box and the flow.

        Calls `super()` first, and needs to: that is what resolves the driven
        entity out of the composition and sets `self.player`, which is the body
        whose agency the flow borrows. Deriving it a second time here would be
        the second implementation of "which object is the player", and the
        answer would silently diverge the day `player_input` is renamed.
        """
        bindable = super().load_test_objects()
        if not self.SCRIPT:
            return bindable

        self.story_box = StoryBox(bounds=Rect(BOX_BOUNDS))
        self.scene.bind("UI_LAYER_1", self.story_box)

        bodies = [record.entity for record in self.spawned]
        self.story_flow = build_flow(self.SCRIPT, self.story_box, bodies,
                                     name=self.FLOW_NAME)
        # The router is the scene's, already assigned to every bound entity as
        # its `action_sink` -- so this one line is the whole wire from "the
        # player pressed the action verb" to "the conversation moved on".
        # `SceneFlow.on_action` takes (entity, fired) and reads neither,
        # because WHICH action advances a flow is the router's decision.
        self.scene.actions.route(ADVANCE_ACTION, self.story_flow.on_action,
                                 self.ADVANCE_PAYLOAD)
        # One slot on the manager, not a list: `post_update` ticks this after
        # the scene fan-out returns, which is what makes a timed step advance.
        self.scene.flow = self.story_flow
        self.story_flow.begin()
        return bindable


__all__ = ["BOX_BOUNDS", "StoryBox", "StoryGame", "StoryLine", "build_flow"]
