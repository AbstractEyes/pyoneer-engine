"""Story demo: an opening cutscene, advanced by the player, then handed back.

`demo_story.tmx` places two `GamePlayer` objects that differ by two tokens:

    hero     player_input,topdown_move,animation_drive,interact_action,action_relay
    keeper   topdown_move,animation_drive

`interact_action` fires on the rising edge of the `action` verb;
`action_relay` hands the firing to `entity.action_sink`, which `SceneManager`
has already assigned as the scene's `ActionRouter`; `demos/narrative.py`
routes that token to `SceneFlow.on_action`. The chain is calls, not events,
so any number of handlers may read one firing and none can silence another.

The keeper carries no action tokens, so pressing the verb beside it does
nothing: what advances a conversation is a body's behavior list, not its
position.

The hero's object also carries `pyoneer_param_payload="keeper"`, and the
route is registered for that payload. A route is keyed by (token, payload),
so one body with one action verb can open a different conversation in a
different room without a second token or an `if` in the handler.

While the cutscene holds, the hero cannot WALK and can still PRESS CONTINUE:
`steerable` and `enabled_inputs` are separate axes, and `SceneFlow`'s default
hold clears only the first. (`begin_text_capture` makes every verb read False
and would lock a dialogue out of its own advance button.)

    .venv/Scripts/python.exe -m demos.story

    action (E)   advance the conversation; after it ends, nothing
    w a s d      walk -- refused while the cutscene holds, restored after
    escape       quit
"""
from __future__ import annotations

import sys

from demos.narrative import StoryGame
from demos.runtime import run


class StoryDemo(StoryGame):
    MAP_NAME = "demo_story"

    ADVANCE_PAYLOAD = "keeper"

    SCRIPT = (
        ("title", "The lamp room. Nobody has been here in years.", 900.0),
        ("greet", "KEEPER: You are early. Press action to go on.", 0.0),
        ("close", "KEEPER: Then the room is yours. Walk where you like.", 0.0),
    )


if __name__ == "__main__":
    sys.exit(run(StoryDemo))
