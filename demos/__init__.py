"""Prototype games built out of the engine's own composition system.

A demo is a `.tmx` file plus a subclass of `MainGame` naming the map to load.
A side-on game and a top-down game are the same classes carrying different
`pyoneer_behaviors` lists, so a demo adds no entity code of its own.

    demos/runtime.py     the boot path, extracted once. Every demo is a
                         subclass of `DemoGame` with two class attributes.
    demos/mapgen.py      writes each demo's .tmx and its tileset art into
                         demos/maps/ the first time it is needed, and never
                         again -- so the file is a real map an author can
                         open in Tiled and repaint.
    demos/behaviors.py   `patrol_input`, registered from outside the engine
                         through `scripts.game.behavior.register`.
    demos/narrative.py   a dialogue box and the `SceneFlow` wiring the story
                         demo mounts over its map.
    demos/topdown.py     what the demos differ by, which is about ten lines
    demos/sidestep.py    each.
    demos/patrol.py
    demos/story.py

RUNNING ONE

    .venv/Scripts/python.exe -m demos.topdown
    .venv/Scripts/python.exe -m demos.sidestep
    .venv/Scripts/python.exe -m demos.patrol
    .venv/Scripts/python.exe -m demos.topdown --frames 120    # headless-ish

See docs/DEMOS.md for what each one shows and what to copy to start a new
one. `tools/check_demos.py` boots them headless and drives them with
injected input.

THE ONE RULE THIS PACKAGE IS UNDER
-----------------------------------
`demos/` may import `scripts/` and `main`. Nothing in `scripts/` may import
`demos/`, for the reason nothing in `scripts/` may import `editor/`: the
engine cannot depend on a game built on top of it.
"""
