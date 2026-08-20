"""Measure the engine's .blitmap load path against the pytmx one it joins.

`config/managers/map_data.py` resolves either extension out of
config/maps.json, so `scripts/loaders/blitmap.py` and `tileset_file.py` are on
the running engine's path rather than beside it. Four claims:

    the LOOKUP dispatches on the extension, refuses one it does not know,
        and keeps the tmx path bit for bit what it was
    the two readers AGREE -- the shipped map converted to .blitmap and
        loaded natively produces the same layers, gids, offsets, custom
        properties, layer profiles, objects, tilesets and TILE PIXELS as
        pytmx produces from the .tmx
    the renderer's own tile path CONSUMES the native view: MapLayer.rebake
        against a .blitmap layer produces the same surface, byte for byte,
        as against the pytmx layer
    the seam that is left is exactly one isinstance test, and it is
        measured here rather than asserted away

WHAT IS NOT PINNED
------------------
The fidelity run reads a COPY of data/maps/test.tmx and compares
derived-against-derived: every number on the tmx side is recovered from
pytmx (undoing its gid renumbering with `tiledgidmap` and `imagemap`), every
number on the native side from the converted file, and the two are compared
to each other. Nothing asserts what the map CONTAINS: the author repaints that
file constantly, and a check that froze its contents would go red for a
repaint (law 4).

The claims that need a specific SHAPE to have any teeth -- flipped gids,
every property type, a hidden layer, an object with a gid, a nested group --
run against a fixture map built in this file, because the shipped map is
allowed to stop containing any of them tomorrow.

    .venv/Scripts/python.exe tools/check_blitmap_engine.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import hashlib
import os
import shutil
import sys
import tempfile
import warnings
from dataclasses import replace

import pygame

pygame.init()
pygame.display.set_mode((320, 240))

import pytmx

from config.managers.map_data import (TILE_LAYER_TYPES, AssetMapManager,
                                      BlitmapObjectGroup, BlitmapRuntime,
                                      BlitmapTileLayer, MapData, map_format,
                                      resolve_map_path)
from scripts.core import layer_profile
from scripts.core import renderer as renderer_module
from scripts.core.errors import (PyoneerAssetMissingError, PyoneerConfigError,
                                 PyoneerContentWarning)
from scripts.core.renderer import (LayerRenderer, MapComposite, MapLayer,
                                   drawable_tile_count)
from scripts.core.spawn import SPAWN_REGISTRY, resolve_depth, spawn
from scripts.game.game_camera import GameCamera
from scripts.game.game_map import GameMap
from scripts.loaders import map_loader
from scripts.loaders.map_loader import SpawnedEntity
from scripts.loaders.blitmap import (GID_FLIP_DIAGONAL, GID_FLIP_HORIZONTAL,
                                     GID_FLIP_VERTICAL, Blitmap, LinkedTileset,
                                     LoadedMap, PyoneerBlitFormatError,
                                     bare_gid, convert_file, gid_flips,
                                     load_map, write_conversion)
from scripts.loaders.map_document import MapDocument
from scripts.loaders.map_loader import object_top_left

ROOT = _bootstrap.REPO_ROOT
REAL_MAP = os.path.join(ROOT, "data", "maps", "test.tmx")

failures: list[str] = []


def brief(value) -> str:
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<54} got={brief(got)} want={brief(want)}")
    if not ok:
        failures.append(label)


def expect_same(label, got, want):
    """`expect` for a long sequence: report the FIRST disagreement.

    A 10,000-cell gid grid printed in full is a wall nobody reads, and
    `expect(label, got == want, True)` is worse -- it says a layer differs
    and refuses to say where. This says which index, and what each side
    holds there, which is the only form of the answer that is actionable.
    """
    if len(got) == len(want) and list(got) == list(want):
        print(f"  ok   {label:<54} {len(got)} values agree")
        return
    if len(got) != len(want):
        print(f"  FAIL {label:<54} length {len(got)} want {len(want)}")
        failures.append(label)
        return
    for index, (left, right) in enumerate(zip(got, want)):
        if left != right:
            print(f"  FAIL {label:<54} first differs at {index}: "
                  f"got={brief(left)} want={brief(right)}")
            failures.append(label)
            return


def returns(action):
    """Run `action` and hand `expect` its value, or the exception it raised.

    `expect(label, thing_that_might_raise(), want)` evaluates inside the
    caller's argument list, so a reader that refuses input it is supposed to
    accept takes the whole file down: no FAIL line, no failure list, and
    every assertion below it never runs. Here the raise IS the got.
    """
    try:
        return action()
    except Exception as error:                                # noqa: BLE001
        return " ".join(f"{type(error).__name__}: {error}".split())


def expect_raises(label, exception, action, *, contains: str = ""):
    """Assert `action` raises, and that the message names the problem."""
    try:
        action()
    except exception as error:
        text = str(error)
        ok = contains in text
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<54} "
              f"raised={type(error).__name__} says={brief(text)}")
        if not ok:
            failures.append(label)
        return
    except Exception as error:                                # noqa: BLE001
        print(f"  FAIL {label:<54} raised {type(error).__name__}, "
              f"wanted {exception.__name__}")
        failures.append(label)
        return
    print(f"  FAIL {label:<54} did not raise")
    failures.append(label)


# ---------------------------------------------------------------------------
# Recovering FILE gids from pytmx
#
# pytmx renumbers: `layer.data` holds internal ids handed out in first-seen
# order, and the tables that invert it are split in two -- `tiledgidmap`
# gives the tile's identity with the flip bits already stripped, and the
# flip bits themselves survive only as the key of `imagemap`. Recombining
# them is the only way to ask pytmx what the FILE said, and it is the exact
# work the native format exists so that nobody has to do.
# ---------------------------------------------------------------------------

def file_gid_table(tmx: pytmx.TiledMap) -> dict[int, int]:
    """{pytmx internal gid -> the gid as written in the .tmx, flags and all}."""
    table: dict[int, int] = {0: 0}
    for (tiled_gid, flags), value in tmx.imagemap.items():
        # imagemap seeds itself with imagemap[(0, 0)] = 0 -- a bare int
        # where every other value is a (gid, flags) pair.
        if not isinstance(value, tuple):
            continue
        internal = value[0]
        raw = int(tiled_gid)
        if flags:
            if flags.flipped_horizontally:
                raw |= GID_FLIP_HORIZONTAL
            if flags.flipped_vertically:
                raw |= GID_FLIP_VERTICAL
            if flags.flipped_diagonally:
                raw |= GID_FLIP_DIAGONAL
        table[internal] = raw
    return table


def tmx_file_gids(layer, table: dict[int, int]) -> list[int]:
    return [table.get(gid, gid) for _x, _y, gid in layer]


def native_gids(layer: BlitmapTileLayer) -> list[int]:
    return [gid for _x, _y, gid in layer]


def tmx_tile_layers(tmx: pytmx.TiledMap) -> list:
    return [layer for layer in tmx.layers
            if isinstance(layer, pytmx.TiledTileLayer)]


def tmx_object_groups(tmx: pytmx.TiledMap) -> list:
    """Real object layers only.

    pytmx finds them with `findall(".//objectgroup")` from the map root, so
    it also picks up the per-tile collision shapes inside an embedded
    tileset and hands each back as a layer whose name is None. That is
    pytmx's documented bug (see scripts/loaders/map_loader.py), not a
    property of any particular map, so filtering on it is not pinning
    content.
    """
    return [layer for layer in tmx.layers
            if isinstance(layer, pytmx.TiledObjectGroup) and layer.name is not None]


def native_object_groups(runtime: BlitmapRuntime) -> list[BlitmapObjectGroup]:
    return [layer for layer in runtime.layers
            if isinstance(layer, BlitmapObjectGroup)]


def pixels(surface) -> bytes | None:
    return None if surface is None else pygame.image.tostring(surface, "RGBA")


def tile_shape(surface):
    """A tile's pixels AND whether it kept an alpha channel.

    The pixels alone are not enough. pytmx picks `.convert()` for a tile
    with no transparent pixel and `.convert_alpha()` otherwise, and an
    opaque tile has identical RGBA bytes either way -- so a comparison of
    bytes would call the two paths equal while one of them blits per-pixel
    and the other copies, and while `composite_is_exact` sees a different
    surface. The flag is the half that catches that.
    """
    if surface is None:
        return None
    return (pygame.image.tostring(surface, "RGBA"),
            bool(surface.get_flags() & pygame.SRCALPHA))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_TMX = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.10.2" orientation="orthogonal" \
renderorder="right-down" width="4" height="3" tilewidth="8" tileheight="8" \
infinite="0" nextlayerid="6" nextobjectid="4">
 <properties>
  <property name="pyoneer_note" value="map level"/>
  <property name="pyoneer_stage" type="int" value="7"/>
  <property name="pyoneer_gravity" type="float" value="0.5"/>
  <property name="pyoneer_night" type="bool" value="true"/>
 </properties>
 <tileset firstgid="1" name="fixture" tilewidth="8" tileheight="8" \
tilecount="4" columns="2">
  <image source="fixture.png" width="16" height="16"/>
 </tileset>
 <group id="5" name="Wrapper">
  <layer id="1" name="Floor" width="4" height="3" offsetx="3" offsety="-2">
   <properties>
    <property name="pyoneer_depth" type="int" value="20"/>
    <property name="pyoneer_parallax_x" type="float" value="0.5"/>
    <property name="pyoneer_motion" value="dynamic"/>
    <property name="pyoneer_occludes" type="bool" value="true"/>
   </properties>
   <data encoding="csv">
1,2,3,4,
0,2147483651,1073741826,536870915,
4,3,2,1
</data>
  </layer>
  <layer id="2" name="Hidden" width="4" height="3" visible="0" opacity="0.5">
   <data encoding="csv">
0,0,0,0,
0,1,0,0,
0,0,0,0
</data>
  </layer>
 </group>
 <objectgroup id="3" name="entity">
  <properties>
   <property name="pyoneer_note" value="group level"/>
  </properties>
  <object id="1" name="Hero" type="GamePlayer" x="16" y="24" width="8" height="8">
   <properties>
    <property name="pyoneer_depth" type="int" value="41"/>
    <property name="tint" type="color" value="#ff00ff00"/>
    <property name="scale" type="float" value="1.5"/>
    <property name="awake" type="bool" value="true"/>
   </properties>
  </object>
  <object id="2" name="Marker" x="4.5" y="7.25" width="3" height="2" rotation="15" visible="0"/>
  <object id="3" type="Chest" gid="2" x="8" y="32" width="8" height="16"/>
 </objectgroup>
</map>
"""


def write_fixture_png(path: str) -> None:
    """A 16x16 sheet of four visibly different 8x8 tiles.

    Asymmetric on both axes ON PURPOSE: a flipped tile has to be
    distinguishable from an unflipped one, and a checkerboard or a solid
    colour would make the flip assertions pass no matter what the code did.
    Tile 2 keeps one fully opaque corner and one transparent one so the
    opaque-versus-alpha surface choice is exercised in both directions.
    """
    sheet = pygame.Surface((16, 16), pygame.SRCALPHA)
    sheet.fill((0, 0, 0, 0))
    colours = [(200, 30, 30, 255), (30, 200, 30, 255),
               (30, 30, 200, 255), (200, 200, 30, 255)]
    for index, colour in enumerate(colours):
        left, top = (index % 2) * 8, (index // 2) * 8
        sheet.fill(colour, pygame.Rect(left, top, 8, 8))
        # One corner pixel darkened and one cleared: the darkened pixel makes
        # a flip detectable, the cleared one makes the tile non-opaque.
        sheet.set_at((left, top), (0, 0, 0, 255))
        if index == 1:
            sheet.set_at((left + 7, top + 7), (0, 0, 0, 0))
    pygame.image.save(sheet, path)


def stage_fixture(root: str) -> str:
    """Write the hand-built map and its sheet. Returns the .tmx path."""
    os.makedirs(root, exist_ok=True)
    write_fixture_png(os.path.join(root, "fixture.png"))
    path = os.path.join(root, "fixture.tmx")
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(FIXTURE_TMX)
    return path


def stage_real_copy(root: str) -> str:
    """A COPY of the shipped map, plus exactly the art the map names.

    The art is copied to the SAME relative location it sits at now, derived
    from each `<image source>` rather than hard-coded, so the copy resolves
    its tilesets the way the original does and the fixture does not go stale
    the day a tileset moves.
    """
    maps = os.path.join(root, "maps")
    os.makedirs(maps, exist_ok=True)
    copy = os.path.join(maps, "test.tmx")
    shutil.copy2(REAL_MAP, copy)
    document = MapDocument.load(REAL_MAP)
    for element in document.root.findall("tileset"):
        image = element.find("image")
        source = "" if image is None else image.get("source", "")
        if not source:
            continue
        origin = os.path.normpath(
            os.path.join(os.path.dirname(REAL_MAP), source))
        destination = os.path.normpath(os.path.join(maps, source))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        if os.path.isfile(origin):
            shutil.copy2(origin, destination)
    return copy


def convert_beside(tmx_path: str) -> str:
    """Convert a .tmx and write the .tileset files BESIDE the map.

    `tileset_dir=""` rather than the default "tilesets" because a tileset's
    `image` line is carried across verbatim: written one directory down, a
    reference like `../graphics/...` resolves one directory too high. That
    is the trap `plan_intern`/`interned` exist to close, and it is measured
    below rather than being worked around silently here.
    """
    conversion = convert_file(tmx_path, tileset_dir="")
    target = os.path.splitext(tmx_path)[0] + ".blitmap"
    write_conversion(conversion, target)
    return target


def manager_for(entries: list[tuple[str, str]]) -> AssetMapManager:
    return AssetMapManager().prepare({"data": [
        {"name": name, "identifier": name, "file": path}
        for name, path in entries]})


# ---------------------------------------------------------------------------
print("the lookup dispatches on the extension")
# ---------------------------------------------------------------------------

expect("a .tmx names the pytmx reader", map_format("a/b/test.tmx"), ".tmx")
expect("a .blitmap names the native reader", map_format("t.blitmap"), ".blitmap")
expect("the suffix test is case insensitive",
       returns(lambda: map_format("T.BlitMap")), ".blitmap")
expect_raises("an unknown suffix is refused, not guessed at", PyoneerConfigError,
              lambda: map_format("data/maps/test.json"), contains=".json")
expect_raises("...and it says which formats do load", PyoneerConfigError,
              lambda: map_format("data/maps/test.json"), contains=".blitmap")
expect_raises("a file with no extension is refused too", PyoneerConfigError,
              lambda: map_format("data/maps/test"), contains="(none)")
expect_raises("a bad extension fails when the CONFIG is read", PyoneerConfigError,
              lambda: MapData({"file": "data/maps/test.json",
                               "name": "x", "identifier": "x"}),
              contains="config/maps.json")

print()
print("...and the path it dispatches on is resolved against the REPO, not the cwd")
# config/maps.json stores a repo-relative string. Every check, tool and editor
# in this tree runs from a different working directory, and a relative answer
# here does not fail here -- it fails later, inside pytmx, as a
# FileNotFoundError naming a path nobody wrote down. `ROOT` comes from
# _bootstrap, so this is two independent derivations of the same directory
# rather than the module agreeing with itself.
#
# A name that is deliberately NOT on disk: the claim is about the arithmetic,
# and reading the shipped map here would pin content instead of code.
expect("a repo-relative file becomes the repo's own absolute path",
       os.path.normcase(resolve_map_path("data/maps/nowhere.tmx")),
       os.path.normcase(os.path.join(ROOT, "data", "maps", "nowhere.tmx")))
expect("...and the answer is absolute whatever the cwd is",
       os.path.isabs(resolve_map_path("data/maps/nowhere.tmx")), True)
expect("an already-absolute path is kept, and normalised",
       os.path.normcase(resolve_map_path(
           os.path.join(ROOT, "data", "..", "data", "maps", "nowhere.tmx"))),
       os.path.normcase(os.path.join(ROOT, "data", "maps", "nowhere.tmx")))
expect("and the separators are the platform's, so a config may use either",
       resolve_map_path("data/maps/nowhere.tmx"),
       resolve_map_path(os.path.join("data", "maps", "nowhere.tmx")))

work = tempfile.mkdtemp(prefix="blitmap_engine_")
try:
    real_tmx = stage_real_copy(work)
    real_blitmap = convert_beside(real_tmx)
    fixture_tmx = stage_fixture(os.path.join(work, "fixture"))
    fixture_blitmap = convert_beside(fixture_tmx)

    assets = manager_for([("tmx", real_tmx), ("native", real_blitmap)])
    tmx_map = assets.load_assets("tmx")
    native_map = assets.load_assets("native")

    print()
    print("...and returns the reader the extension named")
    expect("the .tmx entry is still a pytmx map",
           type(tmx_map).__name__, "TiledMap")
    expect("the .blitmap entry is the native view",
           type(native_map).__name__, "BlitmapRuntime")
    expect("the .tmx entry does not claim to be native",
           assets.maps["tmx"].native, False)
    expect("the .blitmap entry does", assets.maps["native"].native, True)

    print()
    print("caching and reload behave the same for both")
    expect("a second load returns the cached tmx",
           assets.load_assets("tmx") is tmx_map, True)
    expect("a second load returns the cached blitmap",
           assets.load_assets("native") is native_map, True)
    expect("both report loaded",
           (assets.is_loaded("tmx"), assets.is_loaded("native")), (True, True))
    expect("reload=True re-parses the native map",
           assets.load_assets("native", reload=True) is native_map, False)
    native_map = assets.load_assets("native")
    expect("unload clears it", (assets.unload_assets("native"),
                                assets.is_loaded("native")), (True, False))
    native_map = assets.load_assets("native")
    # reload() is the batch form -- "re-parse everything that is loaded" --
    # and it is a SECOND place the extension has to be honoured. It used to
    # call pytmx.load_pygame directly, which would have fed a .blitmap to an
    # XML parser the moment anything asked for a live reload.
    assets.reload()
    expect("manager reload() re-parses through the same dispatcher",
           [type(assets.load_assets(name)).__name__ for name in ("tmx", "native")],
           ["TiledMap", "BlitmapRuntime"])
    expect("...and it really did re-parse rather than keep the old object",
           assets.load_assets("native") is native_map, False)
    tmx_map = assets.load_assets("tmx")
    native_map = assets.load_assets("native")
    expect_raises("an unknown map still fails by name", PyoneerAssetMissingError,
                  lambda: assets.load_assets("nope"), contains="nope")
    expect_raises("document() refuses a .blitmap and says why",
                  PyoneerConfigError, lambda: assets.document("native"),
                  contains="MapDocument reads .tmx only")
    expect("document() still opens a .tmx",
           type(assets.document("tmx")).__name__, "MapDocument")

    # -----------------------------------------------------------------------
    print()
    print("the two readers agree about the shipped map (a copy of it)")
    # -----------------------------------------------------------------------
    expect("map size", (native_map.width, native_map.height),
           (tmx_map.width, tmx_map.height))
    expect("tile size", (native_map.tilewidth, native_map.tileheight),
           (tmx_map.tilewidth, tmx_map.tileheight))
    expect("orientation", native_map.orientation, tmx_map.orientation)
    # Kept, but it proves nothing on its own: the shipped map declares no
    # map-level <properties> today, so this is {} == {} and a native reader
    # that dropped them all would satisfy it. The claim with teeth is taken
    # against the fixture below, which declares four of them on purpose.
    expect("map-level custom properties (vacuous when the map declares none)",
           native_map.properties, dict(tmx_map.properties))

    tmx_layers = tmx_tile_layers(tmx_map)
    native_layers = [layer for layer in native_map.layers
                     if isinstance(layer, BlitmapTileLayer)]
    expect_same("tile layer names, in order",
                [layer.name for layer in native_layers],
                [layer.name for layer in tmx_layers])

    gid_table = file_gid_table(tmx_map)
    for tmx_layer, native_layer in zip(tmx_layers, native_layers):
        where = tmx_layer.name
        expect(f"{where}: size",
               (native_layer.width, native_layer.height),
               (tmx_layer.width, tmx_layer.height))
        expect(f"{where}: offsets",
               (native_layer.offsetx, native_layer.offsety),
               (tmx_layer.offsetx, tmx_layer.offsety))
        expect(f"{where}: visible/opacity",
               (native_layer.visible, native_layer.opacity),
               (tmx_layer.visible, tmx_layer.opacity))
        expect(f"{where}: custom properties",
               native_layer.properties, dict(tmx_layer.properties))
        expect(f"{where}: layer profile the renderer acts on",
               layer_profile.read(native_layer), layer_profile.read(tmx_layer))
        expect_same(f"{where}: every gid, as the FILE writes it",
                    native_gids(native_layer),
                    tmx_file_gids(tmx_layer, gid_table))
        expect(f"{where}: drawable tile count",
               drawable_tile_count(native_layer, native_map),
               drawable_tile_count(tmx_layer, tmx_map))

    print()
    print("...about its objects")
    tmx_groups = tmx_object_groups(tmx_map)
    native_groups = native_object_groups(native_map)
    expect_same("object layer names, in order",
                [group.name for group in native_groups],
                [group.name for group in tmx_groups])
    for tmx_group, native_group in zip(tmx_groups, native_groups):
        where = tmx_group.name
        expect(f"{where}: object count",
               len(native_group.objects), len(tmx_group))
        expect(f"{where}: layer custom properties",
               native_group.properties, dict(tmx_group.properties))
        for native_object, tmx_object in zip(native_group.objects, tmx_group):
            tag = f"{where}#{tmx_object.id}"
            expect(f"{tag}: id/name/type",
                   (native_object.id, native_object.name, native_object.type),
                   (tmx_object.id, tmx_object.name or "", tmx_object.type or ""))
            expect(f"{tag}: size/gid/rotation",
                   (native_object.width, native_object.height,
                    native_object.gid, native_object.rotation),
                   (tmx_object.width, tmx_object.height,
                    tmx_object.gid, tmx_object.rotation))
            # pytmx has ALREADY lifted a gid object by its height (it does
            # `o.y -= o.height` at parse time), so the honest comparison is
            # against what the spawn path computes from the native record --
            # the position that actually reaches EntityLayer either way.
            expect(f"{tag}: top-left the spawn path would use",
                   object_top_left(native_object, native_map.tileheight),
                   (tmx_object.x, tmx_object.y))
            expect(f"{tag}: custom properties",
                   native_object.properties, dict(tmx_object.properties))

    print()
    print("...about its tilesets")
    expect_same("tileset names, in firstgid order",
                [linked.name for linked in native_map.tilesets],
                [tileset.name for tileset in tmx_map.tilesets])
    for linked, tileset in zip(native_map.tilesets, tmx_map.tilesets):
        where = linked.name
        expect(f"{where}: firstgid", linked.first_gid, tileset.firstgid)
        expect(f"{where}: tile size",
               (linked.tileset.tile_width, linked.tileset.tile_height),
               (tileset.tilewidth, tileset.tileheight))
        expect(f"{where}: count and columns",
               (linked.tileset.tile_count, linked.tileset.columns),
               (tileset.tilecount, tileset.columns))
        expect(f"{where}: margin and spacing",
               (linked.tileset.margin, linked.tileset.spacing),
               (tileset.margin, tileset.spacing))
        # pytmx keeps an embedded tileset's `<image source>` verbatim and
        # joins it against the .tmx's own directory at load time
        # (`TiledMap.reload_images`). The native side resolves against the
        # .TILESET's directory. Two different bases, and the claim is that
        # they land on the same file.
        expect(f"{where}: the image both readers resolve to",
               os.path.normcase(linked.image_path()),
               os.path.normcase(os.path.normpath(os.path.join(
                   os.path.dirname(tmx_map.filename), tileset.source))))

    print()
    print("...and about the PIXELS every used gid resolves to")
    seen: dict[int, int] = {}
    for tmx_layer in tmx_layers:
        for _x, _y, internal in tmx_layer:
            if internal and internal not in seen:
                seen[internal] = gid_table.get(internal, internal)
    mismatched = [file_gid for internal, file_gid in sorted(seen.items())
                  if tile_shape(native_map.get_tile_image_by_gid(file_gid))
                  != tile_shape(tmx_map.get_tile_image_by_gid(internal))]
    expect(f"every one of {len(seen)} distinct gids gives the same surface",
           mismatched[:4], [])
    expect("gid 0 draws nothing", native_map.get_tile_image_by_gid(0), None)
    a_gid = next(iter(sorted(seen.values())))
    expect("a tile is sliced once and cached, not re-cut per cell",
           native_map.get_tile_image_by_gid(a_gid)
           is native_map.get_tile_image_by_gid(a_gid), True)

    # -----------------------------------------------------------------------
    print()
    print("the fixture map: flips, every property type, a hidden layer")
    # -----------------------------------------------------------------------
    fixtures = manager_for([("ftmx", fixture_tmx), ("fnative", fixture_blitmap)])
    fixture_pytmx = fixtures.load_assets("ftmx")
    fixture_native = fixtures.load_assets("fnative")
    fixture_table = file_gid_table(fixture_pytmx)

    # Map-level custom properties, on a map that HAS some. The fixture
    # declares one of every type the format supports, so a reader that
    # dropped the block, or one that read them as strings, both fail here --
    # and the assertion cannot go quiet the way the shipped map's can.
    expect("the fixture really declares map-level properties",
           sorted(fixture_native.properties),
           ["pyoneer_gravity", "pyoneer_night", "pyoneer_note", "pyoneer_stage"])
    expect("every one of them survives to the same value pytmx reads",
           fixture_native.properties, dict(fixture_pytmx.properties))
    # 1 == True and 7.0 == 7 in Python, so the value comparison above would
    # pass for a reader that handed back the wrong types.
    expect("...and to the same TYPE, which a value comparison cannot see",
           [type(fixture_native.properties.get(key)).__name__
            for key in ("pyoneer_note", "pyoneer_stage", "pyoneer_gravity",
                        "pyoneer_night")],
           ["str", "int", "float", "bool"])

    expect("the group is carried, not flattened away",
           [layer.name for layer in fixture_native.layers],
           ["Wrapper", "Floor", "Hidden", "entity"])
    # By name, not by index. A structural break -- a group not descended
    # into, a layer dropped -- should register as the one FAIL above and
    # then let the rest of the file run, rather than taking every assertion
    # after it down with an IndexError.
    floor_tmx = fixture_pytmx.get_layer_by_name("Floor")
    by_name = {layer.name: layer for layer in fixture_native.layers}
    floor_native = by_name.get("Floor", fixture_native.layers[0])
    expect("the floor really does carry flipped gids",
           sorted({gid for gid in native_gids(floor_native)
                   if gid != bare_gid(gid)}),
           [536870915, 1073741826, 2147483651])
    expect_same("flipped gids survive the conversion exactly",
                native_gids(floor_native),
                tmx_file_gids(floor_tmx, fixture_table))
    expect("...and the flip bits decode the way pytmx reads them",
           [gid_flips(gid) for gid in (2147483651, 1073741826, 536870915)],
           [(True, False, False), (False, True, False), (False, False, True)])
    expect("a hidden layer stays hidden",
           [(layer.name, layer.visible, layer.opacity)
            for layer in fixture_native.layers
            if isinstance(layer, BlitmapTileLayer)],
           [("Floor", True, 1.0), ("Hidden", False, 0.5)])
    # The TYPE is asserted alongside the value because 3.0 == 3 in Python:
    # a reader that handed the renderer floats where pytmx hands it ints
    # would pass a value-only comparison while moving every blit
    # destination onto a different arithmetic path.
    expect("negative and positive layer offsets survive as ints",
           (floor_native.offsetx, floor_native.offsety,
            type(floor_native.offsetx).__name__), (3, -2, "int"))
    expect("every property type round-trips to the same value pytmx reads",
           floor_native.properties, dict(floor_tmx.properties))
    expect("...including the bool the profile reads as a flag",
           layer_profile.read(floor_native), layer_profile.read(floor_tmx))
    expect("the declared depth is an int, not the string '20'",
           floor_native.properties[layer_profile.DEPTH], 20)

    expect("objects come out in document order",
           [obj.id for obj in fixture_native.objects], [1, 2, 3])
    by_id = {obj.id: obj for obj in fixture_native.objects}
    hero = by_id.get(1, fixture_native.objects[0])
    expect("an object's typed properties are typed",
           [type(hero.properties.get(key)).__name__
            for key in ("pyoneer_depth", "tint", "scale", "awake")],
           ["int", "str", "float", "bool"])
    # Its declared height (16) is deliberately NOT the map's tile height (8):
    # `object_top_left` falls back to the tile height when an object has no
    # height of its own, so a fixture where the two agree cannot tell a
    # working lift from a lost one.
    expect("a tile object is lifted to top-left by its OWN height",
           object_top_left(by_id.get(3, hero), fixture_native.tileheight),
           (8.0, 16.0))
    expect("a plain object is not lifted",
           object_top_left(by_id.get(2, hero), fixture_native.tileheight),
           (4.5, 7.25))
    expect("a hidden object stays hidden",
           [obj.visible for obj in fixture_native.objects], [True, False, True])

    fixture_mismatched = []
    for _x, _y, internal in floor_tmx:
        if not internal:
            continue
        file_gid = fixture_table[internal]
        if tile_shape(fixture_native.get_tile_image_by_gid(file_gid)) != tile_shape(
                fixture_pytmx.get_tile_image_by_gid(internal)):
            fixture_mismatched.append(file_gid)
    expect("flipped tiles come out of both readers pixel-identical",
           sorted(set(fixture_mismatched)), [])

    # Tile 1 of the fixture sheet is fully opaque and tile 2 has one cleared
    # pixel, so the two branches of pytmx's format rule are both exercised
    # and a reader that always picked one would fail exactly one of these.
    internal_of = {file_gid: internal for internal, file_gid in fixture_table.items()}
    def alpha_flags(file_gid):
        return (tile_shape(fixture_native.get_tile_image_by_gid(file_gid))[1],
                tile_shape(fixture_pytmx.get_tile_image_by_gid(
                    internal_of[file_gid]))[1])
    expect("an opaque tile keeps the cheaper non-alpha surface, like pytmx",
           alpha_flags(1), (False, False))
    expect("...and one with a transparent pixel keeps its alpha channel",
           alpha_flags(2), (True, True))

    # -----------------------------------------------------------------------
    print()
    print("the renderer's own tile path consumes the native view")
    # -----------------------------------------------------------------------
    def baked(layer, source_map):
        surface = pygame.Surface(
            (source_map.width * source_map.tilewidth,
             source_map.height * source_map.tileheight), pygame.SRCALPHA)
        rendered = MapLayer(layer.name, 20, surface)
        rendered.set_layer(layer, source_map)
        return rendered.rebake()

    from_native = baked(floor_native, fixture_native)
    from_tmx = baked(floor_tmx, fixture_pytmx)
    expect("MapLayer.set_layer reads the native map's tile size",
           (from_native.tile_width, from_native.tile_height),
           (from_tmx.tile_width, from_tmx.tile_height))
    expect("MapLayer reads the same profile off it",
           from_native.profile, from_tmx.profile)
    expect("...so the layer is excluded from the bake for the same reason",
           (from_native.static, from_native.profile.parallaxed),
           (from_tmx.static, from_tmx.profile.parallaxed))
    expect("MapLayer.rebake produces the same surface, byte for byte",
           pixels(from_native.require_image()),
           pixels(from_tmx.require_image()))

    print()
    print("the object records the spawn path needs")
    # Not "spawn_objects works on a .blitmap" -- it does not, and pinning
    # that would make this check go red the day the integration lands. What
    # is asserted is the CAPABILITY the integration needs: records that the
    # existing depth and y-origin rules already understand, with no second
    # spelling of either.
    entity_record = by_id.get(1, hero)
    expect("a record resolves a depth through the engine's own rule",
           resolve_depth(entity_record.type, properties=entity_record.properties,
                         layer_name=entity_record.layer_name,
                         class_name="GamePlayer"), 41)
    expect("...and an untyped one is visible as untyped, not as a default",
           [bool(record.type) for record in fixture_native.object_records()],
           [True, False, True])
    expect("object_records filters by layer name like spawn_objects does",
           (len(fixture_native.object_records(["entity"])),
            len(fixture_native.object_records(["nothing"]))), (3, 0))

    print()
    print("the seam that is left, measured rather than assumed")
    expect("a native tile layer is NOT a pytmx.TiledTileLayer",
           isinstance(floor_native, pytmx.TiledTileLayer), False)
    expect("...which is the test LayerRenderer filters on",
           "TiledTileLayer" in open(
               os.path.join(ROOT, "scripts", "core", "renderer.py"),
               encoding="utf-8").read(), True)
    expect("TILE_LAYER_TYPES is the one tuple that widens it",
           [isinstance(floor_native, TILE_LAYER_TYPES),
            isinstance(floor_tmx, TILE_LAYER_TYPES),
            isinstance(fixture_native.layers[0], TILE_LAYER_TYPES)],
           [True, True, False])
    expect("the native view answers every OTHER attribute that path reads",
           [hasattr(fixture_native, name) for name in
            ("width", "height", "tilewidth", "tileheight", "layers",
             "visible_layers", "get_tile_image_by_gid", "filename")],
           [True] * 8)
    expect("...and every one it reads off a layer",
           [hasattr(floor_native, name) for name in
            ("name", "width", "height", "offsetx", "offsety", "properties",
             "visible", "__iter__")],
           [True] * 8)
    expect("GameMap's visible_layers accessor exists and filters",
           [layer.name for layer in fixture_native.visible_layers],
           ["Wrapper", "Floor", "entity"])

    # -----------------------------------------------------------------------
    print()
    print("the proposed integration, applied in process and measured")
    #
    # renderer.py and game_map.py look `pytmx.TiledTileLayer` up as a MODULE
    # ATTRIBUTE at call time, so widening that attribute here is exactly
    # equivalent to the isinstance edit proposed for those two files -- and
    # it writes to no file this check does not own. The spawn branch is
    # wrapped the same way.
    #
    # Both patches are SUPERSETS of the real edit, so this section reads the
    # same before and after the integration lands: it is measuring that the
    # code being handed over works, not pinning the fact that it has not
    # been applied.
    #
    # `spawn_native_objects` below IS the proposed body for
    # scripts/loaders/map_loader.py. It lives here until it lands there, and
    # it is exercised here so it cannot be pasted in untested.
    # -----------------------------------------------------------------------
    def spawn_native_objects(runtime, registry=None, *, defaults=None,
                             layers=None) -> list[SpawnedEntity]:
        table = SPAWN_REGISTRY if registry is None else registry
        argument_sets = defaults or {}
        tile_height = runtime.tileheight
        spawned: list[SpawnedEntity] = []
        for record in runtime.object_records(layers):
            if not record.type:
                continue
            where = "blitmap object id=%d on layer %r" % (record.id,
                                                          record.layer_name)
            entity = spawn(record.type, table,
                           **argument_sets.get(record.type, {}))
            entity.moveto(object_top_left(record, tile_height))
            spawned.append(SpawnedEntity(
                entity=entity,
                depth=resolve_depth(record.type, properties=record.properties,
                                    layer_name=record.layer_name,
                                    class_name=type(entity).__name__,
                                    where=where),
                layer_name=record.layer_name, object_id=record.id,
                type_name=record.type))
        return spawned

    real_spawn_objects = map_loader.spawn_objects

    def dispatching_spawn_objects(source, registry=None, *, defaults=None,
                                  layers=None, tables=None):
        # `tables` is accepted and forwarded rather than dropped: the renderer
        # passes it on every bind, and a stand-in that swallowed it would make
        # this check the one place in the tree where an object's
        # `pyoneer_actor` silently resolved to nothing.
        records = getattr(source, "object_records", None)
        if callable(records):
            return spawn_native_objects(source, registry, defaults=defaults,
                                        layers=layers)
        return real_spawn_objects(source, registry, defaults=defaults,
                                  layers=layers, tables=tables)

    def census_and_frame(source_map):
        """Bind a map, then render one frame. Returns (layer census, hash)."""
        surface = pygame.Surface((640, 480))
        renderer = LayerRenderer(surface)
        renderer.bind("MAP", GameMap(source_map))
        renderer.bind_camera(GameCamera(
            pygame.Vector2(640, 480),
            pygame.Rect(0, 0,
                        source_map.width * source_map.tilewidth,
                        source_map.height * source_map.tileheight), scale=1))
        renderer.render()
        names = []
        for depth in sorted(renderer.layers):
            for layer in renderer.layers[depth]:
                if isinstance(layer, MapComposite):
                    names.append((depth, "+".join(str(source.layer_name)
                                                  for source in layer.sources)))
                elif isinstance(layer, MapLayer):
                    names.append((depth, str(layer.layer_name)))
        return names, hashlib.sha256(
            pygame.image.tostring(surface, "RGB")).hexdigest()[:16]

    real_tile_layer_type = pytmx.TiledTileLayer
    pytmx.TiledTileLayer = (real_tile_layer_type, BlitmapTileLayer)
    map_loader.spawn_objects = dispatching_spawn_objects
    renderer_module.spawn_objects = dispatching_spawn_objects
    try:
        tmx_census, tmx_frame = census_and_frame(tmx_map)
        native_census, native_frame = census_and_frame(native_map)
    finally:
        pytmx.TiledTileLayer = real_tile_layer_type
        map_loader.spawn_objects = real_spawn_objects
        renderer_module.spawn_objects = real_spawn_objects

    expect("LayerRenderer builds the same layers from either format",
           native_census, tmx_census)
    expect("...and it built some, so the comparison is not two empty lists",
           len(native_census) > 0, True)
    expect("and one rendered frame is identical, byte for byte",
           native_frame, tmx_frame)

    # -----------------------------------------------------------------------
    print()
    print("what the loader refuses, and what it only warns about")
    # -----------------------------------------------------------------------
    broken = os.path.join(work, "broken")
    os.makedirs(broken, exist_ok=True)
    intact = Blitmap.load(fixture_blitmap)

    unlinked = os.path.join(broken, "unlinked.blitmap")
    Blitmap(intact.width, intact.height, intact.tile_width, intact.tile_height,
            tuple(type(link)(link.first_gid, link.name) for link in intact.tilesets),
            intact.layers, intact.attributes, intact.properties).save(unlinked)
    expect_raises("a tileset link with no source is refused by name",
                  PyoneerBlitFormatError, lambda: load_map(unlinked),
                  contains="fixture")

    dangling = os.path.join(broken, "dangling.blitmap")
    Blitmap(intact.width, intact.height, intact.tile_width, intact.tile_height,
            tuple(type(link)(link.first_gid, link.name, "gone.tileset")
                  for link in intact.tilesets),
            intact.layers, intact.attributes, intact.properties).save(dangling)
    expect_raises("a link pointing at nothing names the path it tried",
                  PyoneerConfigError, lambda: load_map(dangling),
                  contains="gone.tileset")

    artless = os.path.join(work, "artless")
    os.makedirs(artless, exist_ok=True)
    shutil.copy2(fixture_blitmap, os.path.join(artless, "fixture.blitmap"))
    shutil.copy2(os.path.join(os.path.dirname(fixture_blitmap), "fixture.tileset"),
                 os.path.join(artless, "fixture.tileset"))
    expect_raises("a map whose art is absent points at docs/ASSETS.md",
                  PyoneerAssetMissingError,
                  lambda: BlitmapRuntime(load_map(
                      os.path.join(artless, "fixture.blitmap"))),
                  contains="ships without art")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        outside = fixture_native.get_tile_image_by_gid(9999)
        again = fixture_native.get_tile_image_by_gid(9999)
        complaints = [str(w.message) for w in caught
                      if issubclass(w.category, PyoneerContentWarning)]
    expect("a gid past every tileset draws nothing", (outside, again), (None, None))
    expect("...and says so exactly once, not once per cell", len(complaints), 1)
    expect("...naming the gid", "9999" in (complaints[0] if complaints else ""), True)

    # A tileset that DECLARES fewer tiles than its image can hold is the
    # recropped-sheet case, and it is the one the slicer's rect-bounds guard
    # cannot see: the rectangle for the extra tile is perfectly valid. The
    # declared count is the only thing that knows, which is why `address`
    # checks it rather than leaving the question to the image.
    full = load_map(fixture_blitmap)
    shrunk = LoadedMap(
        full.blitmap,
        (LinkedTileset(full.tilesets[0].link,
                       replace(full.tilesets[0].tileset, tile_count=2),
                       full.tilesets[0].path),),
        full.path)
    expect("a gid past the DECLARED count resolves to nothing",
           shrunk.address(3), None)
    expect("...even though the image is big enough to hold that tile",
           full.address(3).local_id, 2)
    expect("...and the tiles it does declare still resolve",
           [shrunk.address(gid).local_id for gid in (1, 2)], [0, 1])

    print()
    print("the converter carries an image reference VERBATIM")
    nested = convert_file(real_tmx, tileset_dir="tilesets")
    written = write_conversion(nested, os.path.join(work, "nested", "test.blitmap"))
    nested_map = load_map(written[0])
    resolves = [os.path.isfile(linked.image_path())
                for linked in nested_map.tilesets]
    # Not a bug being tolerated: it is the reason `plan_intern`/`interned`
    # exist, and the reason this check converts beside the map instead.
    # Asserting it keeps the constraint visible to whoever wires the
    # converter into the editor's save path.
    expect("a .tileset written one directory down loses its relative image",
           any(resolves), False)
    expect("...while beside the map every image resolves",
           [os.path.isfile(linked.image_path())
            for linked in load_map(real_blitmap).tilesets],
           [True] * len(load_map(real_blitmap).tilesets))

finally:
    shutil.rmtree(work, ignore_errors=True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("ALL BLITMAP ENGINE CHECKS PASS")
