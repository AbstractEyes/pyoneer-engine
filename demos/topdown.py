"""Top-down demo: six identical objects, one of which is the player.

Every entity comes from `<object type="GamePlayer">` on `demo_topdown.tmx`;
no Python here builds one. Five of the six carry

    pyoneer_behaviors="topdown_move,animation_drive"

and the sixth carries

    pyoneer_behaviors="player_input,topdown_move,animation_drive"

That one extra token is the whole difference between scenery and a player.
Every object is handed the same live `InputActionManager` by
`spawn_arguments`; only `player_input` reads one, so the other five stand
still.

    .venv/Scripts/python.exe -m demos.topdown

    w a s d      walk            (config/inputs.json, verbs up/down/left/right)
    left ctrl    sprint
    escape       quit
"""
from __future__ import annotations

import sys

from demos.runtime import DemoGame, run


class TopDownDemo(DemoGame):
    MAP_NAME = "demo_topdown"
    # No COLLISION_OFFSET: this map declares no companion collision layer, so
    # `field_from_map` returns None and every body on it is ungated.


if __name__ == "__main__":
    sys.exit(run(TopDownDemo))
