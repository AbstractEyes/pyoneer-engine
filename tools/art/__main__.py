"""Write the whole generated art pack in one command.

    .venv/Scripts/python.exe -m tools.art
    .venv/Scripts/python.exe -m tools.art --list
    .venv/Scripts/python.exe -m tools.art --out DIR --force

Every module that draws sheets is listed here, and its `SHEETS` is merged
into one map of path -> builder. Two modules claiming the same path RAISE:
whichever ran last would otherwise win silently, and the loser's sheet would
be missing from a clone with no error anywhere to say why.

The pack is written under `data/art/`, never under `data/graphics/` --
`#TAG:art_write_once` says why the keys below are spelled the other way. The
write is create-only-if-absent, so on a checkout that already carries the
tracked pack this command writes nothing and says so; `--force` redraws it,
which is what to run after editing a generator.
"""
from __future__ import annotations

from tools.art import Builder, render_cli
from tools.art import collision, parallax, sprites, terrain, tiles

MODULES = (terrain, tiles, sprites, collision, parallax)

SHEETS: dict[str, Builder] = {}
for _module in MODULES:
    for _path, _builder in _module.SHEETS.items():
        if _path in SHEETS:
            raise RuntimeError(
                f"two modules both write {_path!r}; one of them would be "
                f"silently discarded, so pick one owner for that slot")
        SHEETS[_path] = _builder


if __name__ == "__main__":
    raise SystemExit(render_cli(SHEETS, "the whole generated art pack"))
