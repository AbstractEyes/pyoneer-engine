"""Story demo: an opening cutscene, advanced by the player, then handed back.

WHAT THIS PROVES
----------------
That `SceneFlow` is mounted -- that a beat of narrative can take the player's
steering, drive a real `GameWindow` through the engine's own frame, advance on
the player's own action verb, and give the steering back EXACTLY.

`demo_story.tmx` places two `GamePlayer` objects that differ by two tokens:

    hero     player_input,topdown_move,animation_drive,interact_action,action_relay
    keeper   topdown_move,animation_drive

`interact_action` fires on the rising edge of the `action` verb;
`action_relay` hands the firing to `entity.action_sink`, which `SceneManager`
has already assigned as the scene's `ActionRouter`; the game routes that token
to `SceneFlow.on_action`. Nothing here dispatches an event and nothing here
was added to the event system -- the whole chain is calls, which is why N
handlers may read one firing and none of them can silence the others.

The keeper is the negative control: same class, same depth, same room, no
action tokens. Pressing the verb next to it does nothing, because what makes a
body able to advance a conversation is its behavior list and not its position.

The hero's object also carries `pyoneer_param_payload="keeper"`, and the route
is registered for that payload rather than for any payload. A route is keyed
by (token, payload), so this is how ONE body with ONE action verb opens a
different conversation in a different room -- no second token, no second verb,
no `if` in the handler. A firing with a different payload reaches this flow's
route not at all, which is the half worth measuring.

THE HALF THAT IS EASY TO GET WRONG, AND IS THE POINT
-----------------------------------------------------
While the cutscene runs the hero cannot WALK and can still PRESS CONTINUE.
Those are two different axes -- `steerable` and `enabled_inputs` -- and the
obvious wrong move is `begin_text_capture`, which makes every verb read False
and locks a dialogue out of its own advance button. `SceneFlow`'s default hold
clears `steerable` and leaves `enabled_inputs`, and `tools/check_prototype.py`
presses movement and the action verb on the SAME frames to measure both.

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
