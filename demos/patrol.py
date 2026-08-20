"""Patrol demo: two bodies, one movement behavior, two different drivers.

`demo_patrol.tmx` places two `GamePlayer` objects whose behavior lists differ
only in what sits at order 10:

    patroller   patrol_input,topdown_move,animation_drive
    hero        player_input,topdown_move,animation_drive

`topdown_move` is the same registered behavior in both. It reads a
`MoveIntent` and does not know whether a keyboard or a clock wrote it.

`patrol_input` is registered in `demos/behaviors.py`, outside `scripts/`, so
the import below is load-bearing: a behavior token is resolved while the map
is being bound, and a registration that happened later raises "unknown
behavior token 'patrol_input'" during boot.

    .venv/Scripts/python.exe -m demos.patrol

    w a s d      walk the hero; the patroller walks its own square regardless
    escape       quit
"""
from __future__ import annotations

import sys

import demos.behaviors  # noqa: F401  registers `patrol_input` before bind
from demos.runtime import DemoGame, run


class PatrolDemo(DemoGame):
    MAP_NAME = "demo_patrol"


if __name__ == "__main__":
    sys.exit(run(PatrolDemo))
