"""Write the whole generated audio pack in one command.

    .venv/Scripts/python.exe -m tools.audio
    .venv/Scripts/python.exe -m tools.audio --list
    .venv/Scripts/python.exe -m tools.audio --out DIR --force

Every module that synthesises sounds is listed here, and its `SOUNDS` is
merged into one map of path -> builder. Two modules claiming the same path
RAISE: whichever ran last would otherwise win silently, and the loser's sound
would be missing with no error anywhere to say why. Same rule, same reason,
as `tools/art/__main__.py`.

The pack is written under `data/audio/`, never under `data/sound/` --
`#TAG:audio_write_once` says why the keys below are spelled the other way.
The write is create-only-if-absent; `--force` redraws it, which is what to
run after editing a generator.
"""
from __future__ import annotations

from tools.audio import Builder, render_cli
from tools.audio import tones

MODULES = (tones,)

SOUNDS: dict[str, Builder] = {}
for _module in MODULES:
    for _path, _builder in _module.SOUNDS.items():
        if _path in SOUNDS:
            raise RuntimeError(
                f"two modules both write {_path!r}; one of them would be "
                f"silently discarded, so pick one owner for that slot")
        SOUNDS[_path] = _builder


if __name__ == "__main__":
    raise SystemExit(render_cli(SOUNDS, "the whole generated audio pack"))
