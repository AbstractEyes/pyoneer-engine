"""Top-down demo: six identical objects, one of which is the player.

WHAT THIS PROVES
----------------
That the map is enough. Every entity here comes from `<object
type="GamePlayer">` on `demo_topdown.tmx`; there is no Python that builds an
entity, no subclass, and no flag. Five of the six carry

    pyoneer_behaviors="topdown_move,animation_drive"

and the sixth carries

    pyoneer_behaviors="player_input,topdown_move,animation_drive"

That one extra token is the entire difference between scenery and a player.
The five decoys are handed the same live `InputActionManager` as the hero --
`spawn_arguments` gives every GamePlayer the same constructor arguments --
and they stand still anyway, because holding a manager does nothing and only
`player_input` reads one.

WHY IT IS WORTH HAVING WHEN main.py ALREADY DOES THIS
-------------------------------------------------------
`main.py` builds the same six entities in Python, and it is the baseline
`tools/smoke.py` measures drift against, so it is not going to change. This
is the same game with the Python deleted, which makes "the composition model
is faithful" a claim you can measure -- same behaviors, same depths,
comparable positions -- instead of a claim you look at.

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
    # No COLLISION_OFFSET: this map declares no companion layer, so
    # `field_from_map` returns None and every body on it is ungated. Moving
    # the anchor would change nothing and would imply a gate that is not here.


if __name__ == "__main__":
    sys.exit(run(TopDownDemo))
