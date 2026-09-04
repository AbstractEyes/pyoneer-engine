"""Side-on demo: the same class as the top-down one, one token different.

Genre lives in map data. `demo_sidestep.tmx` places the same
`<object type="GamePlayer">` on the same kind of object layer at the same
depth as `demo_topdown.tmx`; the only thing that makes it a platformer is the
word `platformer_move` where the other map says `topdown_move`:

    demo_topdown    player_input,topdown_move,animation_drive
    demo_sidestep   player_input,platformer_move,animation_drive
                    pyoneer_param_jump_verb        = jump
                    pyoneer_param_initial_sequence = idle_right
                    pyoneer_param_gravity          = 900

The second object carries `platformer_move,animation_drive` and NOT
`player_input`, so nothing steers it and it only falls. Both bodies come to
rest on the same floor row: `player_input` decides whether a body is STEERED,
not whether it is SIMULATED.

The floor holds because `LayerRenderer` bakes the map's passability once at
bind (`field_from_map`) and hands the field to every entity it binds. The
demo does not assign a field of its own; if a body falls through the floor,
the map lost its mask or that wire is gone, and `tools/check_demos.py` says
so.

    .venv/Scripts/python.exe -m demos.sidestep

    a d          run             (config/inputs.json, verbs left/right)
    space        jump            (verb `jump`, polled on the rising edge)
    escape       quit
"""
from __future__ import annotations

import sys

from demos.runtime import DemoGame, run


class SidestepDemo(DemoGame):
    MAP_NAME = "demo_sidestep"

    COLLISION_OFFSET = (22.0, 63.0)
    """The anchor this demo EXPECTS, typed out. It is not applied here.

    Feet, not head. `GameEntity.collision_offset` defaults to (0, 0), which
    is the sprite's TOP-LEFT, because `EntityLayer` blits with
    `get_rect(topleft=position)`; for the shipped 44x64 `~Garet` frame that
    anchor is the top of the character's head, so a body gated at (0, 0)
    walks 63 pixels down into the floor and stops with its head on the floor
    line and its whole sprite below it.

    This demo no longer assigns it. `main.py`'s `feet_anchor` DERIVES the
    same pair from the animation category -- half the frame wide, one pixel
    above the bottom edge -- and `spawn_arguments()` hands it to every object
    the map spawns, which is the route the shipped game uses too.

    The literal survives as the thing that derivation is checked AGAINST:
    `tools/check_demos.py` asserts the live body's anchor equals this pair,
    and comparing a derived number to a second derivation of itself is the
    assertion that cannot fail. So this is a hand-typed expected value, and
    it goes red if the anchor ever stops meaning feet.
    """


if __name__ == "__main__":
    sys.exit(run(SidestepDemo))
