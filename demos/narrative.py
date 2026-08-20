"""The game-side narrative kit: a dialogue box, a step adapter, and the wiring.

`scripts/game/flow/scene_flow.py` sequences steps and ships no widgets: a
step drives a window it was handed, calling `open()` on entry and `close()`
on exit. This module is one game's answer to the other side of that pair, and
lives here rather than in `scripts/` because it is game content.

A `FlowStep` carries `name`, `window`, `hold_ms` and `payload` -- no TEXT.
Handing the same `GameWindow` to every step therefore reopens one box saying
one thing on every beat. `StoryLine` below is the fix: anything with
`open()`/`close()` is a step's window, so each step gets a small object that
sets the shared box's line and then opens it.

Limits a script written against this will hit:

  * **No word wrap.** `TextComponent.prepare_text` is one `font.render` of one
    string and answers overflow by SHRINKING the font, so lines here are
    short. Wrapping belongs in `scripts/core/ui/text.py`.
  * **No branching.** `FlowStep` has one successor, and no widget in this
    engine reports a click yet, so a flow is a linear scene.
  * **No trigger.** A flow begins when the game calls `begin()` -- at boot,
    here. The map's `use` triggers are authored by
    `editor/core/map_events.py` and have no runtime reader, so proximity to
    an object cannot start one.
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

    Derives `GameWindow` rather than wrapping one so that `open()` and
    `close()` stay the inherited pair -- `visible`/`active` up, and
    `visible`/`active`/focus down. A wrapper that reimplements them is how a
    closed dialogue box goes on swallowing clicks where it used to be.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("header_text", "")
        kwargs.setdefault("resizable", False)
        super().__init__(*args, **kwargs)
        self.line_text: TextComponent | None = None
        self._line: str = ""

    def build_content(self):
        """Build the line of text. Called by `GameWindow` once the chrome exists.

        Content belongs here rather than in `__init__`: `world_bounds` is not
        final until the component has a parent and has been prepared, so a
        child sized in the constructor is sized against the wrong rectangle.
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
        # Buffered until the chrome exists: `build_content` runs at
        # `core_lifecycle_prepare`, and a flow may begin before that.
        if self.line_text is not None:
            self.line_text.text = self._line


class StoryLine:
    """One beat's window: set the shared box's line, THEN open the box.

    `SceneFlow` calls `open()` and `close()` and asks nothing else, so a
    step's window need not be a widget -- one of these per step is what makes
    a shared box say something different on each beat.

    `close()` closes the box rather than clearing the line, so consecutive
    steps sharing a box do not flicker an empty frame between them.
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

    A function rather than a `SceneFlow` subclass: this only builds records.

    The agency keywords are left at their defaults -- `steerable=False`,
    `enabled_inputs` and `simulated` untouched. That is the cutscene hold a
    dialogue wants: the body stops walking and can still press continue.
    Clearing `enabled_inputs` as well locks the flow out of its own advance
    button.
    """
    steps = tuple(FlowStep(name=step_name, window=StoryLine(box, line),
                           hold_ms=hold)
                  for step_name, line, hold in script)
    return SceneFlow(steps, bodies, name=name)


class StoryGame(DemoGame):
    """A `DemoGame` that also mounts a scene flow over a dialogue box.

    Everything a narrative demo needs that a `.tmx` cannot say, and nothing
    else: a concrete story demo is a `MAP_NAME` and a `SCRIPT`.
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

        Calls `super()` first, and must: that is what resolves the driven
        entity out of the composition and sets `self.player`, the body whose
        agency the flow borrows.
        """
        bindable = super().load_test_objects()
        if not self.SCRIPT:
            return bindable

        self.story_box = StoryBox(bounds=Rect(BOX_BOUNDS))
        self.scene.bind("UI_LAYER_1", self.story_box)

        bodies = [record.entity for record in self.spawned]
        self.story_flow = build_flow(self.SCRIPT, self.story_box, bodies,
                                     name=self.FLOW_NAME)
        # The scene's router is already every bound entity's `action_sink`, so
        # this one line is the whole wire from "the player pressed the action
        # verb" to "the conversation moved on".
        self.scene.actions.route(ADVANCE_ACTION, self.story_flow.on_action,
                                 self.ADVANCE_PAYLOAD)
        # One slot on the manager, not a list. `post_update` ticks it after
        # the scene fan-out returns, which is what advances a timed step.
        self.scene.flow = self.story_flow
        self.story_flow.begin()
        return bindable


__all__ = ["BOX_BOUNDS", "StoryBox", "StoryGame", "StoryLine", "build_flow"]
