"""Generate the minimum placeholder art needed to boot the engine.

This repository ships without art (see docs/ASSETS.md). Three files are
enough to get `python main.py` running and all 12 checks passing:

    .venv/Scripts/python.exe tools/make_placeholder_art.py

Nothing here is pretty. It exists so a fresh clone can run in one command
instead of hunting for what is missing.

The sizes are not arbitrary:
  - the two tilesets must match the width/height declared in the <tileset>
    elements of data/maps/test.tmx, or pytmx computes the wrong tile grid
  - the character sheet must cover every frame rectangle declared in
    config/animations.json. Those are 44x64 frames, order left-to-right, so
    GameAnimation.frame_rect reads x + index*44. Across 8 sequences the
    furthest extents are x=132+44 and y=192+64 -> 176x256. GameAnimation
    .slice_frames raises naming the sequence and frame if a rect falls
    outside, so a sheet that is too small fails loudly rather than producing
    empty sprites.

Pass --force to overwrite files that already exist; by default real art is
left alone.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import argparse
import os

import pygame

# path -> (width, height, fill colour)
SHEETS: dict[str, tuple[int, int, tuple[int, int, int]]] = {
    "data/graphics/tilesets/System/TileA2.png": (512, 384, (58, 104, 72)),
    "data/graphics/tilesets/System/TileC.png": (512, 512, (104, 78, 52)),
    "data/graphics/tilesets/Characters/~Garet.png": (176, 256, (198, 62, 62)),
}

CHECKER = 16
"""Checker square size, so a placeholder is obviously a placeholder."""


def build(path: str, width: int, height: int, colour: tuple[int, int, int]) -> pygame.Surface:
    """A two-tone checkerboard: readable as tiles, unmistakably not real art."""
    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    surface.fill(colour)
    lighter = tuple(min(255, channel + 28) for channel in colour)
    for y in range(0, height, CHECKER):
        for x in range(0, width, CHECKER):
            if (x // CHECKER + y // CHECKER) % 2:
                surface.fill(lighter, pygame.Rect(x, y, CHECKER, CHECKER))
    return surface


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing files (default: skip them)")
    args = parser.parse_args()

    pygame.init()
    root = _bootstrap.REPO_ROOT
    written, skipped = 0, 0
    for relative, (width, height, colour) in SHEETS.items():
        path = os.path.join(root, relative)
        if os.path.exists(path) and not args.force:
            print(f"  skip   {relative}  (exists; --force to overwrite)")
            skipped += 1
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        pygame.image.save(build(path, width, height, colour), path)
        print(f"  write  {relative}  {width}x{height}")
        written += 1

    print()
    print(f"{written} written, {skipped} left alone")
    if written:
        print("Now: .venv/Scripts/python.exe main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
