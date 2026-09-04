"""Verify the shipped art pack: it is there, it is reproducible, it loads.

    .venv/Scripts/python.exe tools/check_art.py

WHAT THIS COVERS THAT THE TWO GENERATOR CHECKS DO NOT
-----------------------------------------------------
`check_art_tilesets` and `check_art_sprites` read a surface a builder just
returned: they prove the DRAWING is right. Nothing there opens the file a
clone actually gets, and nothing there knows the file exists. This covers
the other half -- the mechanism between a builder and a running engine:

  1. every sheet the pack declares is ON DISK under `data/art/`, at the size
     its builder produces, and big enough for every frame rectangle
     `config/animations.json` declares;
  2. the tracked bytes ARE the generator's output -- built twice into two
     scratch trees they agree with each other and with what is committed, so
     a generator edited without redrawing the pack fails here rather than
     shipping art nothing in the repository can reproduce;
  3. the engine loads them: `pygame.image.load` on every sheet, a real
     `GameAnimationHandler` built on the shipped character sheet, and a tmx
     fixture parsed end to end through `tileset_image_loader`;
  4. `resolve_art` orders the two roots BOTH WAYS -- the declared path wins
     when it holds a file, the shipped twin answers when it does not, and
     when NEITHER holds one the argument comes back untouched so the
     caller's own error names what the author wrote;
  5. `git check-ignore` agrees with the licence rule in both directions:
     `data/graphics/` is ignored, and every shipped file is not.

WHY (4) AND (5) ARE THE LOAD-BEARING ONES
-----------------------------------------
The first half of (4) is the whole no-drift guarantee. `tools/smoke.py`
hashes a rendered frame against `tools/baseline.json`, and the author's
machine holds licensed art at the declared paths; if `resolve_art` ever
preferred the shipped twin over a file that is really there, every frame he
renders would change and the pack would have broken the instrument that was
supposed to catch it. So the identity is asserted with a real file at a real
path under the real root, not against an injected fixture tree.

(5) is the licence rule as something a machine says rather than something a
person remembers. A negation added to `.gitignore`, or `data/art/` swept up
by a later rule, both fail here immediately -- one would stage the author's
RTP sheets, the other would ship a repository with no art in it at all.

NO MAP CONTENT IS PINNED
------------------------
`data/maps/starter.tmx` is never opened. The tmx this check parses is nine
lines it writes into a scratch directory itself.

Runs on a bare clone: it needs `data/art/`, which is tracked, and it does
not need `data/graphics/` to exist.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede the engine and tools.art imports)

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pygame

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
pygame.init()
# A display, on the dummy driver. pytmx's own tile slicer calls .convert()
# on every tile it cuts, which raises without one -- so a check that parses a
# tmx needs a surface even though it never shows anything.
pygame.display.set_mode((1, 1))

from config.managers.animation_data import DataAnimationCategory
from config.managers.map_data import (AssetMapManager, MapData,
                                      tileset_image_loader)
from scripts.core.art import (GRAPHICS_ROOT, REPO_ROOT, SHIPPED_ROOT,
                              resolve_art, shipped_path, shipped_relative)
from scripts.core.errors import PyoneerAssetMissingError
from scripts.game.entity.game_animation import GameAnimationHandler
from tools.art import render_cli
from tools.art.__main__ import SHEETS

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception_type, fn, contains=None):
    try:
        fn()
    except exception_type as exc:
        if contains is not None and contains not in str(exc):
            print(f"  FAIL {label:<62} raised {type(exc).__name__} without "
                  f"{contains!r}: {exc}")
            failures.append(label)
            return
        print(f"  ok   {label:<62} raised {type(exc).__name__}")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<62} raised {type(exc).__name__}, wanted "
              f"{exception_type.__name__}")
        failures.append(label)
        return
    print(f"  FAIL {label:<62} did not raise")
    failures.append(label)


def digest(path: str) -> str:
    """sha256 prefix of a file, or a readable stand-in when it is not there.

    A stand-in rather than an exception: a sheet missing from the checkout is
    already reported by section 1, and dying here would hide the four
    sections after it.
    """
    if not os.path.isfile(path):
        return "<absent>"
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()[:16]


def ignored(relative: str) -> bool:
    """What `git check-ignore` says about one path. Exit 0 means ignored."""
    proc = subprocess.run(["git", "check-ignore", "-q", relative],
                          cwd=REPO_ROOT, capture_output=True)
    if proc.returncode not in (0, 1):
        raise RuntimeError("git check-ignore failed on %r: %s"
                           % (relative, proc.stderr.decode("utf-8", "replace")))
    return proc.returncode == 0


PROBE = "__check_art__"
"""A directory name nothing else in the tree uses, under BOTH roots.

The fixtures for the fallback have to sit under the real `data/graphics/`
and `data/art/`, because those roots are baked into module constants and the
point of the exercise is that THOSE constants are right. Both roots tolerate
it: `data/graphics/` is gitignored whole, and this directory is removed in a
`finally` -- along with `data/graphics/` itself if this check is what created
it, so a bare clone is still bare afterwards.
"""

GRAPHICS_DIR = os.path.join(REPO_ROOT, *GRAPHICS_ROOT.split("/"))
SHIPPED_DIR = os.path.join(REPO_ROOT, *SHIPPED_ROOT.split("/"))


def swatch(width: int, height: int, colour) -> pygame.Surface:
    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    surface.fill(colour)
    return surface


# ---------------------------------------------------------------------------
print("1. every declared sheet ships, at the size its builder draws")
# ---------------------------------------------------------------------------
expect("the pack declares some sheets", len(SHEETS) > 0, True)

for relative, builder in sorted(SHEETS.items()):
    shipped = shipped_relative(relative)
    expect(f"{shipped} is under {SHIPPED_ROOT}/",
           shipped.startswith(SHIPPED_ROOT + "/"), True)
    expect("...and not under the licensed root",
           shipped.startswith(GRAPHICS_ROOT + "/"), False)
    path = shipped_path(relative)
    on_disk = os.path.isfile(path)
    expect(f"{shipped} is on disk", on_disk, True)
    if not on_disk:
        continue
    expect("...at the size its builder draws",
           pygame.image.load(path).get_size(), builder().get_size())

# The character sheet has a SECOND declared size: the frame rectangles in
# config/animations.json. A sheet one row short slices empty sprites, and
# GameAnimation.slice_frames raises for it -- but only once something builds
# the handler, which on a fresh clone is the first frame of the game.
with open(os.path.join(REPO_ROOT, "config", "animations.json"),
          encoding="utf-8") as handle:
    ANIMATIONS = json.load(handle)

for category, config in sorted(ANIMATIONS.items()):
    if config["file"] not in SHEETS:
        continue
    sheet = pygame.image.load(shipped_path(config["file"]))
    right = max(seq["x"] + seq["width"] * (max(f["index"] for f in seq["frames"]) + 1)
                for seq in config["sequences"].values())
    bottom = max(seq["y"] + seq["height"] for seq in config["sequences"].values())
    expect(f"{category}: every declared frame is inside the shipped sheet",
           (right <= sheet.get_width(), bottom <= sheet.get_height()),
           (True, True))


# ---------------------------------------------------------------------------
print()
print("2. the tracked bytes are the generator's output, twice over")
# ---------------------------------------------------------------------------
# Two independent builds, then both against what is committed. Comparing only
# the two scratch trees would prove the generator is deterministic and say
# nothing about whether the pack in the repository is still its output --
# which is the failure that actually happens: a generator edited, the suite
# green, and a clone getting art no longer reproducible from this tree.
first = tempfile.mkdtemp(prefix="pyoneer_art_a_")
second = tempfile.mkdtemp(prefix="pyoneer_art_b_")
try:
    for scratch in (first, second):
        expect("the pack writes into a bare tree",
               render_cli(SHEETS, "check fixture", ["--out", scratch]), 0)

    # The property that protects tools/smoke.py: the CLI physically cannot
    # reach the author's art, because every path it writes has already been
    # re-rooted off the licensed tree. Asserted BEFORE the digests below, so
    # a CLI writing to the wrong root says that rather than dying on a file
    # the digests cannot find.
    roots = set()
    for base, _dirs, names in os.walk(first):
        for name in names:
            relative = os.path.relpath(os.path.join(base, name), first)
            roots.add("/".join(relative.replace(os.sep, "/").split("/")[:2]))
    expect("the CLI writes only under the shipped root", sorted(roots),
           [SHIPPED_ROOT])

    for relative in sorted(SHEETS):
        parts = shipped_relative(relative).split("/")
        built = os.path.join(first, *parts)
        if not os.path.isfile(built):
            continue
        expect(f"{parts[-1]} is byte-identical across two builds",
               digest(built), digest(os.path.join(second, *parts)))
        expect("...and the tracked file is that same build",
               digest(os.path.join(REPO_ROOT, *parts)), digest(built))
finally:
    shutil.rmtree(first, ignore_errors=True)
    shutil.rmtree(second, ignore_errors=True)


# ---------------------------------------------------------------------------
print()
print("3. resolve_art orders the two roots, in both directions")
# ---------------------------------------------------------------------------
graphics_was_absent = not os.path.isdir(GRAPHICS_DIR)
graphics_probe_dir = os.path.join(GRAPHICS_DIR, PROBE)
shipped_probe_dir = os.path.join(SHIPPED_DIR, PROBE)
declared = "%s/%s/probe.png" % (GRAPHICS_ROOT, PROBE)
absent = "%s/%s/nowhere.png" % (GRAPHICS_ROOT, PROBE)
try:
    os.makedirs(graphics_probe_dir, exist_ok=True)
    os.makedirs(shipped_probe_dir, exist_ok=True)
    graphics_probe = os.path.join(graphics_probe_dir, "probe.png")
    shipped_probe = os.path.join(shipped_probe_dir, "probe.png")
    pygame.image.save(swatch(32, 32, (10, 20, 30, 255)), graphics_probe)
    pygame.image.save(swatch(32, 32, (200, 100, 50, 255)), shipped_probe)

    # THE NO-DRIFT HALF. The argument comes back unchanged, character for
    # character, so the loader downstream is handed exactly what it was
    # handed before this module existed.
    expect("a declared path that holds a file comes back UNCHANGED",
           resolve_art(declared), declared)
    absolute = os.path.join(REPO_ROOT, *declared.split("/"))
    expect("...and so does the absolute spelling of it",
           resolve_art(absolute), absolute)

    # THE FALLBACK HALF, with the very same shipped twin already in place:
    # remove the declared file and the answer moves.
    os.remove(graphics_probe)
    expect("with nothing at the declared path, the shipped twin answers",
           resolve_art(declared), shipped_probe)
    expect("...and it is really the shipped bytes",
           tuple(pygame.image.load(resolve_art(declared)).get_at((0, 0))[:3]),
           (200, 100, 50))

    # THE THIRD CASE, the one a fallback usually forgets: neither root has it.
    expect("with neither root holding it, the argument comes back untouched",
           resolve_art(absent), absent)

    # A path outside the licensed root is not the pack's business, including
    # one on another drive -- a scratch directory routinely is, and answering
    # that with os.path.relpath raises ValueError instead of returning.
    foreign = os.path.join(tempfile.gettempdir(), "pyoneer_no_such_art.png")
    expect("a path outside the graphics root is returned untouched",
           resolve_art(foreign), foreign)
    expect("a map file is not art either",
           resolve_art("data/maps/nothing.tmx"), "data/maps/nothing.tmx")

    # -----------------------------------------------------------------------
    print()
    print("4. the engine's own readers go through it")
    # -----------------------------------------------------------------------
    # pytmx joins <image source> onto the map's directory and opens the result
    # itself, so this fixture proves the ONE seam that can redirect it. The
    # tmx is written here; no map under data/ is read.
    work = tempfile.mkdtemp(prefix="pyoneer_art_tmx_")
    try:
        def write_map(name: str, image: str) -> str:
            path = os.path.join(work, name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<map version="1.10" orientation="orthogonal" '
                    'renderorder="right-down" width="2" height="2" '
                    'tilewidth="16" tileheight="16" infinite="0" '
                    'nextlayerid="2" nextobjectid="1">\n'
                    ' <tileset firstgid="1" name="probe" tilewidth="16" '
                    'tileheight="16" tilecount="4" columns="2">\n'
                    '  <image source="%s" width="32" height="32"/>\n'
                    ' </tileset>\n'
                    ' <layer id="1" name="Ground" width="2" height="2">\n'
                    '  <data encoding="csv">1,2,3,4</data>\n'
                    ' </layer>\n'
                    '</map>\n' % image.replace("\\", "/"))
            return path

        def load(path: str):
            manager = AssetMapManager()
            manager.maps["probe"] = MapData(
                {"file": path, "name": "probe", "identifier": "probe"})
            return manager.load_assets("probe")

        def load_or_none(path: str):
            """Report a refusal as a failed assertion, not as a traceback.

            An engine that stopped consulting the pack raises here, and the
            check has four more sections to run.
            """
            try:
                return load(path)
            except Exception as exc:  # noqa: BLE001 - reporting tool
                print(f"       (the load raised {type(exc).__name__}: {exc})")
                return None

        # The tmx names a path under the licensed root that is NOT there; only
        # the shipped twin is. A clone renders from exactly this arrangement.
        tmx = load_or_none(write_map("shipped.tmx", absolute))
        expect("a tmx whose art is only in the pack loads",
               tmx is not None and tmx.get_tile_image_by_gid(1) is not None,
               True)
        if tmx is not None:
            expect("...through the loader this engine installs",
                   tmx.image_loader, tileset_image_loader)
            expect("...and the pixels are the shipped twin's",
                   tuple(tmx.get_tile_image_by_gid(1).get_at((0, 0))[:3]),
                   (200, 100, 50))

        # And the other half: art in NEITHER root still raises, naming the
        # path the author wrote rather than a rewritten guess.
        missing = os.path.join(REPO_ROOT, *absent.split("/"))
        expect_raises("a tmx whose art is in neither root still raises",
                      PyoneerAssetMissingError,
                      lambda: load(write_map("missing.tmx", missing)),
                      contains="nowhere.png")
    finally:
        shutil.rmtree(work, ignore_errors=True)
finally:
    shutil.rmtree(graphics_probe_dir, ignore_errors=True)
    shutil.rmtree(shipped_probe_dir, ignore_errors=True)
    if graphics_was_absent and os.path.isdir(GRAPHICS_DIR) \
            and not os.listdir(GRAPHICS_DIR):
        try:
            os.rmdir(GRAPHICS_DIR)
        except OSError:
            # Best effort, and deliberately not a failure. A file-syncing
            # client holds a directory it has just seen appear, so this loses
            # a coin toss on the author's tree and would otherwise report a
            # red check for a courtesy: what is left behind is an EMPTY
            # gitignored directory that changes nothing about what loads.
            pass

# The spritesheet reader is the other engine door, and it is the strict one:
# GameAnimationHandler loads the sheet eagerly and starts `idle_down` in its
# own constructor, so this fails if the shipped sheet is absent, is the wrong
# size, or lacks the sequence every body opens with.
for category, config in sorted(ANIMATIONS.items()):
    if config["file"] not in SHEETS:
        continue
    handler = GameAnimationHandler(DataAnimationCategory(config))
    expect(f"{category}: a handler builds on the shipped sheet and plays",
           handler.image() is not None, True)

expect_raises("a sheet key outside the graphics root has no twin, and says so",
              ValueError, lambda: shipped_relative("config/animations.json"))


# ---------------------------------------------------------------------------
print()
print("5. git agrees with the licence rule, in both directions")
# ---------------------------------------------------------------------------
# The author's own art may never be tracked; the generated pack must be. Both
# halves, because either one alone is satisfied by the wrong .gitignore.
expect("the licensed root is ignored",
       ignored("%s/tilesets/System/TileA2.png" % GRAPHICS_ROOT), True)
expect("...and so is anything under it",
       ignored("%s/anything/at/all.png" % GRAPHICS_ROOT), True)
expect("the shipped pack is NOT ignored",
       sorted(ignored(shipped_relative(r)) for r in SHEETS),
       [False] * len(SHEETS))

tracked = subprocess.run(["git", "ls-files", GRAPHICS_ROOT],
                         cwd=REPO_ROOT, capture_output=True, text=True)
expect("no file under the licensed root is tracked, at all",
       tracked.stdout.strip(), "")

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
