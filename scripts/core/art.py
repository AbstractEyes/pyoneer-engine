"""Where the engine looks for a picture, and in what order.

TWO ROOTS, ONE TREE                                       #TAG:art_two_roots
------------------------------------------------------------------------
`data/graphics/` is the author's own art. It is gitignored in its entirety,
with no exception and no negation, because the sheets in it match the RPG
Maker VX Ace RTP by filename and by exact pixel size and that licence does
not permit redistribution -- see `docs/ASSETS.md`. Nothing in this repository
may ever track a file under it.

`data/art/` is the pack this repository ships. Every pixel in it is produced
by `tools/art/`, it is TRACKED, and it mirrors the same relative subtree:
`data/graphics/tilesets/System/TileA2.png` has its shipped twin at
`data/art/tilesets/System/TileA2.png`. One prefix swap, spelled once, in
`shipped_relative` below.

`resolve_art` puts them in order: whatever is at the declared path wins, and
the shipped twin answers only when nothing is there. So a machine that HAS
the art loads exactly the bytes it always loaded -- the same path string
reaches `pygame.image.load`, so a frame hash cannot move -- and a fresh
clone, which has `data/art/` from the checkout and no `data/graphics/` at
all, boots with no command to run first.

TWO ROOTS RATHER THAN A `.gitignore` NEGATION            #TAG:art_no_negation
------------------------------------------------------------------------
A negation would have to spell `!data/graphics/tilesets/System/TileA2.png`,
which is the exact path the licensed sheet occupies on the author's machine:
`git add` would then stage HIS file. The licence rule survives only while it
stays the flat one a person can hold -- no image file under `data/graphics/`,
ever, for any reason -- so the shipped pack lives somewhere else entirely and
`.gitignore` keeps one unqualified line.

WHAT THIS IS NOT
----------------
Not a search path. There are exactly two roots and the second holds exactly
what `tools/art/` writes. A path that is under neither is returned untouched,
so the caller's own `PyoneerAssetMissingError` still names what was authored
rather than a rewritten guess.
"""
from __future__ import annotations

import os

# scripts/core/art.py -> core -> scripts -> the repo.
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GRAPHICS_ROOT = "data/graphics"
"""The author's art. Gitignored whole; see this module's docstring."""

SHIPPED_ROOT = "data/art"
"""The generated pack. Tracked, and written only by `tools/art/`."""

_GRAPHICS_PARTS = tuple(GRAPHICS_ROOT.split("/"))
_SHIPPED_PARTS = tuple(SHIPPED_ROOT.split("/"))

# Compared with `str.startswith` rather than with `os.path.relpath`, which
# RAISES ValueError for a path on another drive letter -- and a check's
# tempdir routinely is one. Comparison is normcased so a Windows path that
# spells the drive or a directory in the other case still matches; normcase
# preserves length, so the prefix can be cut off the original string.
_GRAPHICS_PREFIX = os.path.normcase(
    os.path.join(REPO_ROOT, *_GRAPHICS_PARTS) + os.sep)


def _parts(path: str) -> tuple[str, ...]:
    """Split a repo-relative path on either separator.

    Callers spell these with forward slashes because they are `.tmx`
    `<image source>` and `config/animations.json` values, but the same
    strings arrive from `os.path` on Windows with backslashes in them.
    """
    return tuple(part for part in path.replace("\\", "/").split("/") if part)


def shipped_relative(relative: str) -> str:
    """`data/graphics/X` -> `data/art/X`, still repo-relative.

    RAISES for a path that is not under `data/graphics/`. The generator's
    sheet keys ARE engine paths -- `config/animations.json` and a `<tileset>`
    read the same strings -- so a key outside that subtree is a sheet the
    engine would never look for, and answering with a plausible destination
    would ship it somewhere nothing loads.
    """
    parts = _parts(relative)
    if parts[:len(_GRAPHICS_PARTS)] != _GRAPHICS_PARTS:
        raise ValueError(
            "%r is not under %s/, so it has no shipped twin; the pack mirrors "
            "that subtree and nothing else" % (relative, GRAPHICS_ROOT))
    return "/".join(_SHIPPED_PARTS + parts[len(_GRAPHICS_PARTS):])


def shipped_path(relative: str) -> str:
    """Where `shipped_relative(relative)` lands in THIS checkout, absolutely."""
    return os.path.join(REPO_ROOT, *_parts(shipped_relative(relative)))


def _under_repo(path: str) -> str:
    """`path` as an absolute path, resolving a relative one against the repo.

    Against the repo root rather than the working directory: the strings in
    `config/animations.json` are repo-relative, and resolving them against
    wherever a tool happened to be started is how the same config names a
    file that exists and a file that does not.
    """
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(REPO_ROOT, path))


def resolve_art(path: str) -> str:
    """The declared path if anything is there, else its shipped twin.

    Returns the ARGUMENT UNCHANGED when a file is already at it. That is the
    whole no-drift guarantee: on a machine holding real art this function is
    an `os.path.isfile` and an identity, the loader is handed the same string
    it was handed before, and nothing about the frame can move.

    Returns the argument unchanged when neither exists, too, so the caller
    raises naming what the author wrote.
    """
    if os.path.isfile(path):
        return path
    absolute = _under_repo(path)
    if os.path.isfile(absolute):
        return absolute
    if not os.path.normcase(absolute).startswith(_GRAPHICS_PREFIX):
        return path
    rest = _parts(absolute[len(_GRAPHICS_PREFIX):])
    shipped = os.path.join(REPO_ROOT, *(_SHIPPED_PARTS + rest))
    if os.path.isfile(shipped):
        return shipped
    return path
