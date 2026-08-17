"""Prototype games built out of the engine's own composition system.

WHAT A DEMO IS HERE, AND WHAT IT IS NOT
---------------------------------------
A demo is a `.tmx` file plus a subclass of `MainGame` that says which map to
load. It is NOT a copy of `main.py` with different numbers in it. The whole
claim these three exist to make is that a side-on game and a top-down game
are the SAME classes carrying different `pyoneer_behaviors` lists, and a
demo that re-implemented the boot would be evidence against its own point.

    demos/runtime.py     the boot path, extracted ONCE. Every demo is a
                         subclass of `DemoGame` with two class attributes.
    demos/mapgen.py      writes each demo's .tmx and its tileset art into
                         demos/maps/ the first time it is needed, and never
                         again -- so the file is a real map an author can
                         open in Tiled and repaint.
    demos/behaviors.py   `patrol_input`, registered from OUTSIDE the engine.
                         Proof that `scripts.game.behavior.register` is a
                         real extension point and a game does not have to
                         edit `scripts/` to add a behavior.
    demos/topdown.py     what the three demos differ by, which is
    demos/sidestep.py    about ten lines each.
    demos/patrol.py

WHY main.py IS NOT ONE OF THEM
-------------------------------
`main.py` builds its six entities in Python and is the baseline
`tools/smoke.py` measures drift against. Changing it would move the frame,
so it is left exactly as it is; `demos/topdown.py` is the same game authored
into a map instead, which is what makes "the composition model is faithful"
a claim you can measure by comparing them rather than a claim you look at.

RUNNING ONE

    .venv/Scripts/python.exe -m demos.topdown
    .venv/Scripts/python.exe -m demos.sidestep
    .venv/Scripts/python.exe -m demos.patrol
    .venv/Scripts/python.exe -m demos.topdown --frames 120    # headless-ish

See docs/DEMOS.md for what each one proves and what to copy to start a new
one. `tools/check_demos.py` boots all three headless and drives them with
injected input, so none of them can rot unnoticed.

THE ONE RULE THIS PACKAGE IS UNDER
-----------------------------------
`demos/` may import `scripts/` and `main`. Nothing in `scripts/` may import
`demos/`, for exactly the reason nothing in `scripts/` may import `editor/`:
the engine cannot depend on a game built on top of it.
"""
