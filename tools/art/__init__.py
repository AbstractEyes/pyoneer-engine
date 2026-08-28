"""Generated art: the sheets that ship with the engine, as code.

Every pixel this repository ships is produced by a function in here. Nothing
is copied, traced, downsampled or recoloured from anything; the generator is
the asset, and the `.png` is its output. `tools/check_art_sprites.py` and
`tools/check_art_tilesets.py` prove it by making `pygame.image.load` raise
for the duration of a build.

    .venv/Scripts/python.exe -m tools.art             write the whole pack
    .venv/Scripts/python.exe -m tools.art --list      say what it would write
    .venv/Scripts/python.exe -m tools.art --force     redraw it after an edit
    .venv/Scripts/python.exe -m tools.art --out DIR   write it somewhere else
    .venv/Scripts/python.exe -m tools.art.sprites     one module's sheets only

A SHEET KEY IS AN ENGINE PATH; THE PACK LANDS SOMEWHERE ELSE  #TAG:art_write_once
------------------------------------------------------------------------
A `SHEETS` key is the path the ENGINE looks for -- the string in
`config/animations.json` or in a `.tmx` `<image source>` -- so it is spelled
under `data/graphics/`, and `tools/check_art_sprites.py` asserts the config
and the pack agree on it. But `data/graphics/` is the author's own directory,
gitignored whole because the sheets in it are licensed art that may not be
redistributed. So `render_cli` sends every key through
`scripts.core.art.shipped_relative` and writes the TWIN, under `data/art/`,
which is the tracked root `resolve_art` falls back to. The consequence worth
knowing: this package cannot write into `data/graphics/` at all, whatever
`--force` says, so running it can never change what a machine with real art
renders.

Within `data/art/` the write is still create-only-if-absent -- `write_sheets`
skips a path that already has bytes and reports the skip, and `--force` is
the explicit way past it. `editor.ui.canvas`'s `write_mask_sheet` and
`demos.mapgen.ensure_art` hold the same contract, so it is the tree's one
spelling of "provision, never clobber".

A BUILDER TAKES NOTHING AND READS NOTHING
-----------------------------------------
`Builder` is a zero-argument callable returning a `pygame.Surface`. It must
not open a file: the point of this package is that the pixels come from
arithmetic, not from a copy of somebody's licensed sheet, and
`tools/check_art_sprites.py` proves it by making `pygame.image.load` raise
for the duration of a build. It must also be DETERMINISTIC -- called twice it
returns the same bytes -- because a pack that differs per run cannot be
compared, cached, or blamed.
"""
from __future__ import annotations

import argparse
import os
from typing import Callable, Mapping

import pygame

from scripts.core.art import SHIPPED_ROOT, shipped_relative

Builder = Callable[[], pygame.Surface]
"""Zero-argument, file-free, deterministic. See the module docstring."""

# Three levels up from tools/art/__init__.py: art -> tools -> the repo.
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def write_sheets(sheets: Mapping[str, Builder], root: str,
                 force: bool = False) -> tuple[list[str], list[str]]:
    """Write every sheet under `root`. Returns (written, skipped) paths.

    Keys are repo-relative and spelled with forward slashes, because they are
    the paths `config/animations.json` and a `.tmx` `<image source>` name;
    `os.path.join` on the split parts is what makes them open on Windows.

    Raises OSError from pygame if a write fails, rather than reporting a
    success it did not have.
    """
    written: list[str] = []
    skipped: list[str] = []
    for relative, builder in sheets.items():
        path = os.path.join(root, *relative.split("/"))
        if os.path.exists(path) and not force:
            skipped.append(relative)
            continue
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        pygame.image.save(builder(), path)
        written.append(relative)
    return written, skipped


def render_cli(sheets: Mapping[str, Builder], description: str,
               argv: list[str] | None = None) -> int:
    """The `--out/--force/--list` front end every module in this package uses.

    One implementation, so `-m tools.art` and `-m tools.art.sprites` cannot
    come to disagree about what `--force` means.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--out", default=REPO_ROOT, metavar="DIR",
                        help="write under DIR instead of the repository root")
    parser.add_argument("--force", action="store_true",
                        help="overwrite files that are already there "
                             "(default: leave them alone)")
    parser.add_argument("--list", action="store_true",
                        help="print each sheet's path and size, write nothing")
    args = parser.parse_args(argv)

    # Engine path in, shipped path out. See `#TAG:art_write_once`: the keys
    # name where the ENGINE looks, and the pack is written to the tracked
    # twin of each one, which is the only root this package may write to.
    shipped = {shipped_relative(relative): builder
               for relative, builder in sheets.items()}

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    pygame.init()

    if args.list:
        for relative, builder in shipped.items():
            surface = builder()
            print(f"  {relative}  {surface.get_width()}x{surface.get_height()}")
        return 0

    written, skipped = write_sheets(shipped, args.out, force=args.force)
    for relative in written:
        print(f"  write  {relative}")
    for relative in skipped:
        print(f"  skip   {relative}  (exists; --force to overwrite)")
    print()
    print(f"{len(written)} written, {len(skipped)} left alone, "
          f"under {SHIPPED_ROOT}/")
    return 0
