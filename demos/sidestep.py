"""Side-on demo: the same class as the top-down one, one token different.

WHAT THIS PROVES
----------------
That genre lives in map data. `demo_sidestep.tmx` places the same
`<object type="GamePlayer">` on the same kind of object layer at the same
depth as `demo_topdown.tmx`, and the only thing that makes it a platformer
is the word `platformer_move` where the other map says `topdown_move`:

    demo_topdown    player_input,topdown_move,animation_drive
    demo_sidestep   player_input,platformer_move,animation_drive
                    pyoneer_param_jump_verb        = jump
                    pyoneer_param_initial_sequence = idle_right
                    pyoneer_param_gravity          = 900

There is no `GamePlatformerPlayer`, and adding one would undo the point.

The second object carries `platformer_move,animation_drive` and NOT
`player_input`, so nothing steers it and it only falls. Both bodies come to
rest on the same floor row at the same y -- which is the sharper half of the
claim: `player_input` is about being STEERED, not about being SIMULATED.

WHAT THIS DEMO STANDS ON
`platformer_move` only lands because something gated it. `LayerRenderer`
bakes the map's passability once at bind (`field_from_map`) and hands the
field to every entity it binds -- a sweep at the end of `__bind_map` for
map-placed objects, and `__bind_entity` for hand-built ones. Note it is NOT
`__prepare_entity_layers`, which says in its own docstring that it does not
gate what it binds.

`demos/` deliberately does not assign the field privately: a demo that gated
only its own entities would work while every other map-driven game stayed
ungated, and would hide a gap rather than report it. So if this demo ever
falls through the floor again, the wire is gone or the map lost its mask --
and `tools/check_demos.py` fails loudly in those words rather than papering
over it.

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
    """Feet, not head. The single per-entity value a .tmx cannot say.

    `GameEntity.collision_offset` defaults to (0, 0), which is the sprite's
    TOP-LEFT, because `EntityLayer` blits with `get_rect(topleft=position)`.
    For the shipped 44x64 `~Garet` frame that anchor is the top of the
    character's head, so a body gated at (0, 0) stops with its head on the
    floor and its whole sprite below it. Half the width and one pixel above
    the bottom edge is feet.

    Left in Python because there is no `pyoneer_collision_offset` property
    and no behavior parameter for it -- see docs/DEMOS.md, "What a demo still
    has to say in Python". This is the shortest item on that list and the one
    most worth closing.
    """


if __name__ == "__main__":
    sys.exit(run(SidestepDemo))
