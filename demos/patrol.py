"""Patrol demo: two bodies, one movement behavior, two different drivers.

WHAT THIS PROVES
----------------
That the intent seam is real. `demo_patrol.tmx` places two `GamePlayer`
objects whose behavior lists differ only in what sits at order 10:

    patroller   patrol_input,topdown_move,animation_drive
    hero        player_input,topdown_move,animation_drive

`topdown_move` is the same registered behavior in both, unmodified and
unsubclassed. It reads a `MoveIntent` and does not know whether a keyboard
or a clock wrote it. `scripts/game/behavior/input.py` states this is
possible; before this demo nothing exercised it, which made it a claim about
the design rather than a fact about the code.

It proves a second thing on the way. `patrol_input` is declared and
registered in `demos/behaviors.py` -- OUTSIDE `scripts/` -- so a game adds a
behavior through `scripts.game.behavior.register` without editing the
engine's table. `demos.behaviors` is imported below rather than in
`runtime.py`, and the import is load-bearing: the token is resolved while the
map is being BOUND, so a registration that happened later would raise
"unknown behavior token 'patrol_input'" during boot.

It is also the only demo a check can drive with no key injection at all,
which is what makes it the cheapest instrument in the suite for watching a
player actually walk -- the blind spot `tools/smoke.py` has by construction,
since smoke presses nothing.

    .venv/Scripts/python.exe -m demos.patrol

    w a s d      walk the hero; the patroller walks its own square regardless
    escape       quit
"""
from __future__ import annotations

import sys

import demos.behaviors  # noqa: F401  registers `patrol_input` -- see above
from demos.runtime import DemoGame, run


class PatrolDemo(DemoGame):
    MAP_NAME = "demo_patrol"


if __name__ == "__main__":
    sys.exit(run(PatrolDemo))
