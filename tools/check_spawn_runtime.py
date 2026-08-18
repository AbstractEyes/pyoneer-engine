"""Verify that a tmx object becomes a live entity in a running renderer.

`scripts/core/spawn.py` and `scripts/loaders/map_loader.py` are checked by
`tools/check_spawn.py`, which stops one step short of the engine: it proves an
object CAN be constructed at the right depth, never that anything constructs
it. This check covers the last hop, and the four claims it makes are each a
thing the renderer would otherwise be free to break with no visible symptom
until an author noticed an entity missing, or drawn behind a wall:

    binding a map spawns its objects and binds them into EntityLayers
    an entity depth that splits a run of tile layers really does split it,
        because the spawn happens BEFORE the first bake and not after
    a bulk spawn at N depths costs one regroup and zero re-rasterizations
    a spawned entity is bound into the SCENE too, so it actually updates

WHAT "ONE REGROUP" IS MEASURED AS, AND WHY IT IS NOT A REGROUP COUNT
--------------------------------------------------------------------
invalidate() sets a flag; the work happens once, later, in render(). So
calling it per entity would NOT produce N regroups, and counting regroups
alone would be an assertion that cannot fail. What per-entity invalidation
actually costs is the `sources_dirty` keyword: the default is True, so the
first entity to land inside the tile span flips the pending regroup into one
that re-rasterizes every tile layer the bind pass has just finished
rasterizing. The number with teeth is therefore the REBAKE count, and this
check asserts it is zero -- then makes the counter move on purpose, so a zero
that came from a broken instrument is not mistaken for a passing claim.

THE FIXTURE IS THIS FILE'S OWN, ART INCLUDED
--------------------------------------------
`data/maps/test.tmx` is repainted constantly and is never read here; a check
that pins map content goes red the next time the author paints. The tileset
PNG is generated into the same temp directory, because unlike check_spawn.py
this one needs tiles that really rasterize: the whole point is what entity
depths do to a run of tile layers.

    .venv/Scripts/python.exe tools/check_spawn_runtime.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import ast
import json
import os
import shutil
import sys
import tempfile
import warnings

import pygame

pygame.init()
SCREEN = pygame.display.set_mode((128, 128))

import pytmx

from scripts.core import blitpool
from scripts.core.depth import MAP_DEPTH
from scripts.core.errors import (PyoneerAssetMissingError,
                                 PyoneerConfigError)
from scripts.core.renderer import (EntityLayer, LayerRenderer, MapComposite,
                                   MapLayer)
from scripts.core.scene.game_scene import GameScene
from scripts.core.scene.scene_manager import SceneManager
from scripts.core.spawn import DEFAULT_OBJECT_DEPTH, SPAWN_REGISTRY, register
from scripts.game.behavior import BEHAVIOR_REGISTRY
from scripts.game.entity.game_entity import GameEntity
from scripts.game.entity.game_transform import Transform
from scripts.game.game_camera import GameCamera
from scripts.game.game_map import GameMap
from scripts.loaders.table_file import load_tables

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception, call, *fragments):
    """The call must raise `exception`, and its message must name each fragment.

    The fragments are the teeth: asserting only the exception TYPE passes for
    any raise anywhere inside the call, including a typo three frames down.
    """
    try:
        call()
    except exception as exc:
        text = str(exc)
        missing = [f for f in fragments if f not in text]
        ok = not missing
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} "
              f"raised {type(exc).__name__}: {text.splitlines()[0][:60]}")
        if not ok:
            failures.append(f"{label} (message lacks {missing})")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<58} raised {type(exc).__name__} not "
              f"{exception.__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<58} did not raise")
    failures.append(label)


# ---------------------------------------------------------------------------
# The probe entity
# ---------------------------------------------------------------------------

class ProbeEntity(GameEntity):
    """A GameEntity that is constructible, drawable, and counts its updates.

    Three gaps in the base class, all of them deliberate there and all of them
    in the way here. GameEntity leaves core_lifecycle_build and
    core_input_receive abstract, so it cannot be instantiated at all. It has no
    `image` of its own -- only GameAnimatedEntity computes one -- so an 8x8
    block is set instead of None, because the render path SKIPS an entity with
    no image and a skipped entity is indistinguishable from an unbound one.
    And core_frame_update is a no-op, so it is counted: that count is the only
    externally visible difference between an entity the scene drives and an
    entity that merely draws.

    GamePlayer is the real registry entry and is not used, because it needs a
    spritesheet the repository deliberately does not ship.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.updates = 0
        block = pygame.Surface((8, 8))
        block.fill((0, 200, 0))
        self._image = block

    def core_lifecycle_build(self, event=None):
        pass

    def core_input_receive(self, events=None):
        pass

    def core_frame_update(self, event=None):
        self.updates += 1


# ---------------------------------------------------------------------------
# The fixture
#
# Tile layers at 10 / 30 / 60, so the tile span is 10..60 and an entity at 20
# or 50 lands INSIDE it while one at 70 or 77 does not. Every rung of the
# depth ladder appears once: two objects on an unmapped object group (the
# default 50), one with a prefixed property (77), one with the plain spelling
# (20), and two on a group whose name IS in MAP_DEPTH (70).
# ---------------------------------------------------------------------------

TILE_LAYERS = ("Floor", "GroundClutter", "Foreground")
ROW = "1,1,1,1,1,1,1,1"
CSV = ",\n".join([ROW] * 8)

HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="8" height="8" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="9" nextobjectid="20">
 <tileset firstgid="1" name="probe" tilewidth="16" tileheight="16" tilecount="4" columns="2">
  <image source="probe.png" width="32" height="32"/>
 </tileset>
"""

TILES = "".join(
    f""" <layer id="{index + 1}" name="{name}" width="8" height="8">
  <data encoding="csv">
{CSV}
</data>
 </layer>
"""
    for index, name in enumerate(TILE_LAYERS)
)

OBJECTS = """ <objectgroup id="4" name="entity">
  <object id="1" name="a" type="Probe" x="16" y="32" width="16" height="16"/>
  <object id="2" name="b" type="Probe" x="32" y="48" width="16" height="16"/>
  <object id="3" name="high" type="Probe" x="0" y="0" width="16" height="16">
   <properties>
    <property name="pyoneer_depth" type="int" value="77"/>
   </properties>
  </object>
  <object id="4" name="low" type="Probe" x="48" y="64" width="16" height="16">
   <properties>
    <property name="depth" type="int" value="20"/>
   </properties>
  </object>
  <object id="5" name="region" x="0" y="0" width="16" height="16"/>
 </objectgroup>
 <objectgroup id="5" name="ENTITY_3">
  <object id="6" name="named" type="Probe" x="8" y="8" width="16" height="16"/>
  <object id="7" name="configured" type="Configured" x="24" y="8" width="16" height="16"/>
 </objectgroup>
"""

# The same map with nothing on its object layer -- the shape data/maps/test.tmx
# ships in. It is what makes "spawning changes nothing when there is nothing to
# spawn" a measured claim rather than an observation about today's map file.
EMPTY_OBJECTS = """ <objectgroup id="4" name="entity"/>
"""

# One object whose depth property carries no type="int". Tiled writes that for
# any property the author did not type, and pytmx hands it back as the string
# '20'. It must raise, naming the object, rather than resolving to something
# plausible.
UNTYPED_OBJECTS = """ <objectgroup id="4" name="entity">
  <object id="8" name="stringly" type="Probe" x="0" y="0" width="16" height="16">
   <properties>
    <property name="depth" value="20"/>
   </properties>
  </object>
 </objectgroup>
"""

# Three objects that differ ONLY in what they say about an actors row, so the
# ladder is measured on one map, one bind and one table. id=10 names a row;
# id=11 names the same row and overrides ONE of its columns per object; id=12
# names none. `pyoneer_actor` is written untyped, which is what Tiled emits
# for a property the author did not type, so it arrives as the string it is.
ACTOR_OBJECTS = """ <objectgroup id="4" name="entity">
  <object id="10" name="from_row" type="Probe" x="0" y="16" width="16" height="16">
   <properties>
    <property name="pyoneer_behaviors" value="platformer_move"/>
    <property name="pyoneer_actor" value="hero"/>
   </properties>
  </object>
  <object id="11" name="overridden" type="Probe" x="16" y="16" width="16" height="16">
   <properties>
    <property name="pyoneer_behaviors" value="platformer_move"/>
    <property name="pyoneer_actor" value="hero"/>
    <property name="pyoneer_param_move_speed" type="float" value="11.0"/>
   </properties>
  </object>
  <object id="12" name="no_row" type="Probe" x="32" y="16" width="16" height="16">
   <properties>
    <property name="pyoneer_behaviors" value="platformer_move"/>
   </properties>
  </object>
 </objectgroup>
"""

# Names a row the table does not carry. The failure this exists to make loud:
# left to fall back, every parameter would sit at its default and the map
# would be indistinguishable from one where the Database works.
GHOST_ACTOR_OBJECTS = """ <objectgroup id="4" name="entity">
  <object id="13" name="ghost_row" type="Probe" x="0" y="16" width="16" height="16">
   <properties>
    <property name="pyoneer_behaviors" value="platformer_move"/>
    <property name="pyoneer_actor" value="nobody"/>
   </properties>
  </object>
 </objectgroup>
"""

# Behaviors and no row reference: the shape every .tmx in this repository
# ships in. Bound by a renderer that was never handed tables, it must behave
# exactly as it did before the reader existed.
NO_ACTOR_OBJECTS = """ <objectgroup id="4" name="entity">
  <object id="14" name="plain" type="Probe" x="0" y="16" width="16" height="16">
   <properties>
    <property name="pyoneer_behaviors" value="platformer_move"/>
   </properties>
  </object>
 </objectgroup>
"""

FIXTURE = HEAD + TILES + OBJECTS + "</map>\n"
EMPTY_FIXTURE = HEAD + TILES + EMPTY_OBJECTS + "</map>\n"
UNTYPED_FIXTURE = HEAD + TILES + UNTYPED_OBJECTS + "</map>\n"

workspace = tempfile.mkdtemp(prefix="pyoneer_spawn_runtime_")


def write_fixture(name: str, text: str) -> str:
    path = os.path.join(workspace, name)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def write_art() -> None:
    """A 2x2 grid of opaque 16px tiles. Opaque so a merge is provably exact."""
    sheet = pygame.Surface((32, 32))
    for index, color in enumerate(((180, 40, 40), (40, 180, 40),
                                   (40, 40, 180), (180, 180, 40))):
        sheet.fill(color, pygame.Rect((index % 2) * 16, (index // 2) * 16, 16, 16))
    pygame.image.save(sheet, os.path.join(workspace, "probe.png"))


def build_renderer(path: str) -> tuple[LayerRenderer, list[str]]:
    """Bind a fixture map into a fresh renderer. Returns it and its warnings."""
    renderer = LayerRenderer(SCREEN)
    renderer.bind_camera(GameCamera(pygame.Vector2(128, 128),
                                    pygame.Rect(0, 0, 128, 128), scale=1))
    renderer.spawn_defaults = {"Configured": {"movement_config": {"move_speed": 20}}}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        renderer.bind("MAP", GameMap(pytmx.load_pygame(path)))
        return renderer, [str(w.message) for w in caught]


class _MissingEntity:
    """Stands in for an object that did not spawn at all.

    Every value on it is deliberately impossible to match, so a break in the
    spawn pass reports as the twenty false claims it really is rather than
    hiding nineteen of them behind the first KeyError.
    """
    transform = Transform(position=(-1, -1))
    move_speed = -1
    updates = -1


class _MissingRecord:
    object_id = None
    depth = None
    layer_name = None
    entity = _MissingEntity()


def entity_layers(renderer: LayerRenderer) -> dict[int, list[EntityLayer]]:
    return {depth: [layer for layer in layers if isinstance(layer, EntityLayer)]
            for depth, layers in renderer.layers.items()
            if any(isinstance(layer, EntityLayer) for layer in layers)}


def composites(renderer: LayerRenderer) -> list[MapComposite]:
    return [layer for layers in renderer.layers.values() for layer in layers
            if isinstance(layer, MapComposite)]


def frame_blits(renderer: LayerRenderer) -> list[tuple[int, str]]:
    """(depth, sender class name) for every token one render() queues."""
    captured: list[tuple[int, str]] = []
    original = blitpool.BlitPool.get_blit_pool_pygame

    @staticmethod
    def spy(clear: bool = True):
        for depth in sorted(blitpool.ORGANIZED_BLITS):
            for priority in sorted(blitpool.ORGANIZED_BLITS[depth]):
                for token in blitpool.ORGANIZED_BLITS[depth][priority]:
                    captured.append((depth, type(token.sender).__name__))
        return original(clear)

    blitpool.BlitPool.get_blit_pool_pygame = spy
    try:
        renderer.render()
    finally:
        blitpool.BlitPool.get_blit_pool_pygame = original
    return captured


def instrument(renderer: LayerRenderer) -> dict[str, int]:
    """Count source rebakes and regroups from here on.

    Wired AFTER the bind, so the rasterization __prepare_map_layers does
    through core_lifecycle_prepare is not counted -- what is under test is
    whether anything rasterizes those layers a SECOND time.
    """
    counts = {"rebakes": 0, "regroups": 0}
    for layers in renderer.map_sources.values():
        for source in layers:
            original = source.rebake

            def counting(_original=original):
                counts["rebakes"] += 1
                return _original()

            source.rebake = counting

    original_regroup = renderer._LayerRenderer__regroup_map_layers

    def counting_regroup(_original=original_regroup):
        counts["regroups"] += 1
        return _original()

    renderer._LayerRenderer__regroup_map_layers = counting_regroup
    return counts


try:
    write_art()
    fixture = write_fixture("fixture.tmx", FIXTURE)
    register("Probe", ProbeEntity)
    register("Configured", ProbeEntity)

    # --------------------------------------------------- the map layers exist
    print("the fixture rasterizes real tile layers, so entity depths can split them")
    renderer, boot_warnings = build_renderer(fixture)
    expect("every declared tile layer rasterized",
           sorted(renderer.map_sources), sorted(MAP_DEPTH[n] for n in TILE_LAYERS))
    expect("the tile span is what the entity depths are measured against",
           (min(renderer.map_sources), max(renderer.map_sources)), (10, 60))

    # ------------------------------------------------------- objects -> entities
    print()
    print("binding the map spawns its objects and binds them into EntityLayers")
    spawned = renderer.spawned_entities
    by_id = {record.object_id: record for record in spawned}

    def object_(object_id):
        return by_id.get(object_id, _MissingRecord)

    def held(found, depth):
        return found[depth][0].entities if found.get(depth) else []

    expect("every typed object spawned, and only those",
           sorted(by_id), [1, 2, 3, 4, 6, 7])
    expect("the untyped object was skipped and said so",
           any("no Type" in message and "[5]" in message
               for message in boot_warnings), True)
    expect("nothing was constructed for it",
           5 in by_id, False)

    layers = entity_layers(renderer)
    expect("an EntityLayer exists at every resolved depth",
           sorted(layers), [20, 50, 70, 77])
    expect("and exactly one per depth, never two",
           sorted(len(found) for found in layers.values()), [1, 1, 1, 1])

    # Identity, not count: a layer holding SOME ProbeEntity at depth 50 would
    # pass a count assertion even if the binder had constructed its own.
    for record in spawned:
        expect(f"object id={record.object_id} is bound at depth {record.depth}",
               any(entity is record.entity
                   for entity in held(layers, record.depth)), True)
    expect("the two objects that resolved to the same depth share one layer",
           len(held(layers, 50)), 2)
    expect("and so do the two on the named object group",
           len(held(layers, 70)), 2)
    expect("the layer is named for the tmx object group it came from",
           layers[70][0].layer_name if layers.get(70) else None, "ENTITY_3")

    # ------------------------------------------------------------ depth ladder
    print()
    print("depth comes through MapDocument, so it is an int and not the string '20'")
    expect("a prefixed property lands at its own depth", object_(3).depth, 77)
    expect("the plain spelling lands at its own depth", object_(4).depth, 20)
    expect("an object group named in MAP_DEPTH lands at that depth",
           object_(6).depth, MAP_DEPTH["ENTITY_3"])
    expect("an unmapped object group falls through to the default",
           object_(1).depth, DEFAULT_OBJECT_DEPTH)
    # The renderer keys self.layers by depth, so a string depth does not raise
    # -- it makes a second, unreachable bucket named '20' that sorts as a str
    # and blows up in sorted() next to the ints. Assert the keys, not the value.
    expect("every layer bucket is keyed by an int",
           sorted({type(depth).__name__ for depth in renderer.layers}), ["int"])

    untyped = write_fixture("untyped.tmx", UNTYPED_FIXTURE)
    expect_raises("an untyped depth property refuses to boot, naming the object",
                  PyoneerConfigError, lambda: build_renderer(untyped),
                  "id=8", "depth", "int")

    # --------------------------------------------------------------- position
    print()
    print("the position survives construction, which discards the transform kwarg")
    expect("GameEntity still throws its transform argument away",
           tuple(ProbeEntity(transform=Transform(position=(999, 999))).transform.position),
           (0.0, 0.0))
    expect("so moveto() is what places an object",
           tuple(object_(1).entity.transform.position), (16.0, 32.0))
    expect("...for every object, not just the first",
           tuple(object_(4).entity.transform.position), (48.0, 64.0))

    # ------------------------------------------------- constructor arguments
    print()
    print("spawn_defaults reaches the constructor, because the tmx cannot carry it")
    expect("the configured type took the movement block it was given",
           object_(7).entity.move_speed, 20)
    expect("...and a type with no defaults took the class fallback",
           object_(6).entity.move_speed, 16)

    # --------------------------------------------- one regroup, zero rebakes
    print()
    print("a bulk spawn at four depths costs one regroup and no re-rasterization")
    expect("the pending regroup does not want the sources rebaked",
           renderer._map_regroup_rebakes, False)
    counts = instrument(renderer)
    blits = frame_blits(renderer)
    expect("the first render regrouped exactly once", counts["regroups"], 1)
    expect("and re-rasterized nothing, because the bind pass just baked",
           counts["rebakes"], 0)
    expect("the flag is cleared once serviced", renderer._map_regroup, False)

    # Prove the instrument can move, so the zero above is a measurement and not
    # a broken counter. This is the cost a per-entity invalidate() would have
    # bought, once per bind, at boot.
    renderer.invalidate()
    renderer.render()
    expect("...and the counters do move when a regroup really is dirty",
           (counts["regroups"], counts["rebakes"]),
           (2, len(TILE_LAYERS)))

    # ------------------------------------------------------- draw order
    print()
    print("the entities interleave with the tiles, so nothing hides behind a wall")
    expect("no composite spans the entity depths", composites(renderer), [])
    tile_depths = [depth for depth, sender in blits
                   if sender in ("MapLayer", "MapComposite")]
    entity_depths = [depth for depth, sender in blits if sender == "ProbeEntity"]
    expect("every tile layer drew on its own", sorted(tile_depths), [10, 30, 60])
    expect("every spawned entity drew, at its resolved depth",
           sorted(entity_depths), [20, 50, 50, 70, 70, 77])
    expect("the deepest entity is drawn between two tile layers",
           min(tile_depths) < min(entity_depths) < max(tile_depths), True)
    order = [sender for _depth, sender in blits]
    expect("tiles are queued both before and after the entities",
           (order.index("MapLayer") < order.index("ProbeEntity"),
            len(order) - 1 - order[::-1].index("MapLayer")
            > order.index("ProbeEntity")), (True, True))

    # ----------------------------------------- why it must precede the render
    print()
    print("and that is only true because the spawn precedes the first bake")
    late = LayerRenderer(SCREEN)
    late.bind_camera(GameCamera(pygame.Vector2(128, 128),
                                pygame.Rect(0, 0, 128, 128), scale=1))
    late.bind("MAP", GameMap(pytmx.load_pygame(write_fixture(
        "empty.tmx", EMPTY_FIXTURE))))
    expect("with nothing on the object layer, nothing spawns",
           late.spawned_entities, [])
    expect("and no EntityLayer is created", entity_layers(late), {})
    late.render()
    baked = composites(late)
    expect("the three tile layers merge into one composite", len(baked), 1)
    expect("whose band covers the depths the real fixture spawned into",
           [depth for depth in (20, 50) if baked[0].covers((depth, depth))],
           [20, 50])
    late.bind(20, ProbeEntity())
    expect("an entity bound AFTER that bake is inside an already-baked composite",
           baked[0].covers((20, 20)), True)
    expect("...and only a further regroup can separate them",
           late._map_regroup, True)

    # The span test is a STRICT inequality, and the difference is a regroup
    # nobody needs. A layer at either end of the tile depths, or past them, has
    # no run to cut in half: it draws after everything already below it either
    # way. Order matters here -- the last bind leaves the flag set on purpose.
    late.render()
    late.bind(max(late.map_sources), ProbeEntity())
    expect("an entity AT the top of the tile span asks for no regroup",
           late._map_regroup, False)
    late.bind(100, ProbeEntity())
    expect("nor does one above every tile layer", late._map_regroup, False)
    late.bind(30, ProbeEntity())
    expect("one strictly inside the span does", late._map_regroup, True)

    # -------------------------------------------------- the empty map is inert
    print()
    print("an empty object layer changes nothing, which is why smoke cannot drift")
    inert, _messages = build_renderer(os.path.join(workspace, "empty.tmx"))
    inert_counts = instrument(inert)
    inert.render()
    expect("no entity layer anywhere", entity_layers(inert), {})
    expect("one regroup, as before any of this existed",
           inert_counts["regroups"], 1)
    expect("and still no re-rasterization", inert_counts["rebakes"], 0)
    expect("only tile depths hold layers", sorted(inert.layers), [10])

    # --------------------------------------------------- the scene gets them
    print()
    print("a spawned entity is bound into the scene too, so it actually updates")

    class _HostStub:
        """Stands in for MainGame. SceneManager touches .screen only on resize."""
        screen = None

    manager = SceneManager(_HostStub())
    manager.add_scene("fixture", GameScene("fixture"))
    manager.set_scene("fixture")
    scene_renderer = LayerRenderer(SCREEN)
    scene_renderer.spawn_defaults = {"Configured": {"movement_config": {"move_speed": 20}}}
    manager.bind("renderer", scene_renderer)
    manager.bind("camera", GameCamera(pygame.Vector2(128, 128),
                                      pygame.Rect(0, 0, 128, 128), scale=1))
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        manager.bind("MAP", GameMap(pytmx.load_pygame(fixture)))

    scene_spawned = scene_renderer.spawned_entities
    expect("the scene bind spawned the same six entities", len(scene_spawned), 6)
    expect("none of them has been updated yet",
           sorted({record.entity.updates for record in scene_spawned}), [0])

    # AT WHAT DEPTH the scene binds them. GameScene fans updates out over
    # every bucket regardless of its key, so the update counts below cannot
    # see this: binding all six at 0 -- or at any single number -- passes
    # every one of them. The key is the only observable, and it is the thing
    # `unbind`, and anything that ever iterates the scene by depth, reads.
    scene_buckets = manager.current_scene._GameScene__game_objects
    expect("the scene holds a bucket per resolved depth, and no others",
           sorted(key for key in scene_buckets if isinstance(key, int)),
           sorted({record.depth for record in scene_spawned}))
    expect("...which is the same ladder the renderer resolved",
           sorted(key for key in scene_buckets if isinstance(key, int)),
           [20, 50, 70, 77])
    for record in scene_spawned:
        expect(f"scene id={record.object_id} sits at depth {record.depth}",
               any(held is record.entity
                   for held in scene_buckets.get(record.depth, ())), True)
    manager.update(0.5)
    expect("one scene update reaches every spawned entity exactly once",
           sorted(record.entity.updates for record in scene_spawned), [1] * 6)
    manager.update(0.5)
    expect("...and again on the next frame, without doubling",
           sorted(record.entity.updates for record in scene_spawned), [2] * 6)
    expect("binding into the scene did not bind them into the renderer twice",
           sorted(len(found[0].entities)
                  for found in entity_layers(scene_renderer).values()),
           [1, 1, 2, 2])

    # ----------------------------------------- spawn_defaults BEFORE the bind
    print()
    print("spawn_defaults is read DURING the bind, so it has to be set first")
    # There is no error if it is not. The entity is constructed with the class
    # fallback and the game boots on, until something that needed the argument
    # dereferences it -- for GamePlayer that is an animation category of None,
    # which dies in scripts/game/entity/game_animation.py as a bare
    # AttributeError three files from the mistake, naming neither the object
    # nor spawn_defaults. So the ordering is asserted twice: that it MATTERS,
    # and that the one caller which has to get it right does.
    afterwards = LayerRenderer(SCREEN)
    afterwards.bind_camera(GameCamera(pygame.Vector2(128, 128),
                                      pygame.Rect(0, 0, 128, 128), scale=1))
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        afterwards.bind("MAP", GameMap(pytmx.load_pygame(fixture)))
    afterwards.spawn_defaults = {"Configured": {"movement_config":
                                                {"move_speed": 20}}}
    configured = [record for record in afterwards.spawned_entities
                  if record.type_name == "Configured"]
    expect("the object that wanted defaults did spawn either way",
           len(configured), 1)
    expect("...but set after the bind, the defaults reached nothing",
           configured[0].entity.move_speed if configured else None, 16)
    expect("...where set before the bind they reach it", object_(7).entity.move_speed, 20)

    # main.py is the only caller that has to order these two statements, and
    # nothing else in the tree would notice if it stopped. Read as SOURCE:
    # booting MainGame needs a display, a config, art and the shipped map,
    # while the claim is purely about statement order, which the AST answers
    # exactly and without a fixture.
    with open(os.path.join(_bootstrap.REPO_ROOT, "main.py"),
              encoding="utf-8") as handle:
        main_tree = ast.parse(handle.read())
    scene_setup = [node for node in ast.walk(main_tree)
                   if isinstance(node, ast.FunctionDef)
                   and node.name == "prepare_test_scene"]
    expect("main.py still builds the scene in prepare_test_scene",
           len(scene_setup), 1)
    body = scene_setup[0] if scene_setup else ast.parse("pass")
    def assigned_at(attribute: str) -> list[int]:
        return [node.lineno for node in ast.walk(body)
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Attribute)
                        and target.attr == attribute
                        for target in node.targets)]

    defaults_at = assigned_at("spawn_defaults")
    tables_at = assigned_at("tables")
    map_bind_at = [node.lineno for node in ast.walk(body)
                   if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "bind" and node.args
                   and isinstance(node.args[0], ast.Constant)
                   and node.args[0].value == "MAP"]
    expect("it assigns spawn_defaults once and binds the map once",
           (len(defaults_at), len(map_bind_at)), (1, 1))
    expect("and the assignment comes FIRST",
           bool(defaults_at) and bool(map_bind_at)
           and max(defaults_at) < min(map_bind_at), True)
    # `tables` has the same ordering rule and a LOUDER failure than
    # spawn_defaults: an object's `pyoneer_actor` is resolved during the bind,
    # so tables assigned afterwards means a raise at boot rather than a wrong
    # number later. Asserted the same way and for the same reason -- main.py is
    # the only caller that has to order these statements.
    expect("main.py hands the renderer its data tables exactly once",
           len(tables_at), 1)
    expect("...and before the map bind, which is when a pyoneer_actor is read",
           bool(tables_at) and bool(map_bind_at)
           and max(tables_at) < min(map_bind_at), True)

    # ------------------------------------ the actors table reaches a live body
    print()
    print("an authored pyoneer_actor reaches the behavior a bound map built")
    # The last hop of the parameter ladder, measured where it is actually
    # taken: not `resolve_params` with a dict handed to it (tools/
    # check_behavior.py section 8 does that), but a .tmx object, a .json table
    # and a LayerRenderer.bind, ending at the attribute on the behavior
    # instance the renderer constructed. Ten parameters declare
    # `source="actors"` and until `scripts/loaders/table_file.py` landed the
    # answer to every one of them was its declared default.
    #
    # THREE OBJECTS ON ONE MAP, so the difference between them cannot be the
    # map, the bind, the table or the order. Only what each <object> says.
    table_root = os.path.join(workspace, "project_tables")
    os.makedirs(table_root, exist_ok=True)
    with open(os.path.join(table_root, "actors.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"table": "actors",
                   "columns": [{"name": "move_speed", "type": "float"},
                               {"name": "gravity", "type": "float"}],
                   "rows": {"hero": {"move_speed": 240.0, "gravity": 111.0}}},
                  handle)
    project_tables = load_tables(table_root)

    actor_map = write_fixture("actors.tmx", HEAD + TILES + ACTOR_OBJECTS
                              + "</map>\n")
    actor_renderer = LayerRenderer(SCREEN)
    actor_renderer.bind_camera(GameCamera(pygame.Vector2(128, 128),
                                          pygame.Rect(0, 0, 128, 128), scale=1))
    actor_renderer.tables = project_tables
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        actor_renderer.bind("MAP", GameMap(pytmx.load_pygame(actor_map)))

    def moved(object_id: int):
        """The `platformer_move` instance on the entity that object spawned."""
        for record in actor_renderer.spawned_entities:
            if record.object_id == object_id:
                found = record.entity.behaviors.get("platformer_move")
                return _MissingEntity() if found is None else found
        return _MissingEntity()

    declared = BEHAVIOR_REGISTRY["platformer_move"]
    default_speed = declared.param("move_speed").default
    default_gravity = declared.param("gravity").default
    expect("the three numbers under test are three DIFFERENT numbers, so no "
           "reading order passes by accident",
           len({default_speed, 240.0, 11.0}), 3)
    expect("all three objects spawned off the one bind",
           sorted(record.object_id for record in actor_renderer.spawned_entities),
           [10, 11, 12])

    expect("an object naming a row is built with that row's column",
           moved(10).move_speed, 240.0)
    expect("...and with the row's other column too, so it is the ROW that "
           "arrived and not one lucky key", moved(10).gravity, 111.0)
    expect("its own pyoneer_param_ beats the row it names",
           moved(11).move_speed, 11.0)
    expect("...per KEY, so the same object still takes the row's gravity",
           moved(11).gravity, 111.0)
    expect("an object on the SAME map naming no row gets the declared default",
           moved(12).move_speed, default_speed)
    expect("...for every actors parameter it declares, not just the one",
           moved(12).gravity, default_gravity)

    # -------------------------------- and the refusals, from inside the bind
    print()
    print("a row reference that cannot resolve stops the bind, naming the object")
    # Each of these is the failure that would otherwise be INVISIBLE: the body
    # spawns, every number quietly sits at its default, and the map looks like
    # a map where the Database does nothing -- which is exactly what it was
    # before this landed.
    unwired = LayerRenderer(SCREEN)
    unwired.bind_camera(GameCamera(pygame.Vector2(128, 128),
                                   pygame.Rect(0, 0, 128, 128), scale=1))
    expect_raises("a map that names a row bound by a renderer with no tables",
                  PyoneerConfigError,
                  lambda: unwired.bind("MAP", GameMap(pytmx.load_pygame(actor_map))),
                  "id=10", "LayerRenderer.tables")

    ghost_map = write_fixture("ghost_actor.tmx",
                              HEAD + TILES + GHOST_ACTOR_OBJECTS + "</map>\n")
    ghosted = LayerRenderer(SCREEN)
    ghosted.bind_camera(GameCamera(pygame.Vector2(128, 128),
                                   pygame.Rect(0, 0, 128, 128), scale=1))
    ghosted.tables = project_tables
    expect_raises("a pyoneer_actor naming a row the table has not got",
                  PyoneerAssetMissingError,
                  lambda: ghosted.bind("MAP", GameMap(pytmx.load_pygame(ghost_map))),
                  "'nobody'", "id=13", "hero")

    # The half that keeps every shipped map working: behaviors, parameters and
    # NO pyoneer_actor, bound by a renderer that was never given tables. This
    # is the shape of every .tmx in the repository, and it must not raise, must
    # not warn about tables, and must resolve to the declared defaults.
    plain_map = write_fixture("no_actor.tmx",
                              HEAD + TILES + NO_ACTOR_OBJECTS + "</map>\n")
    plain = LayerRenderer(SCREEN)
    plain.bind_camera(GameCamera(pygame.Vector2(128, 128),
                                 pygame.Rect(0, 0, 128, 128), scale=1))
    with warnings.catch_warnings(record=True) as plain_warnings:
        warnings.simplefilter("always")
        plain.bind("MAP", GameMap(pytmx.load_pygame(plain_map)))
    plain_move = [record.entity.behaviors.get("platformer_move")
                  for record in plain.spawned_entities
                  if record.entity.behaviors.get("platformer_move")]
    expect("with no tables and no pyoneer_actor, the map still binds",
           len(plain_move), 1)
    expect("...to the declared default, exactly as before any of this existed",
           plain_move[0].move_speed if plain_move else None, default_speed)
    expect("...and the tables were never mentioned in a warning",
           [message for message in
            (str(w.message) for w in plain_warnings) if "table" in message], [])

    # ------------------------------- SceneManager.spawn reads the SAME slot
    print()
    print("a runtime spawn reads the row out of the renderer's one slot")
    # Two routes into a frame, one table set. A second slot on SceneManager
    # would be a second thing to forget, and the symptom would be a projectile
    # built in Python resolving move_speed to 120 while the object Tiled placed
    # beside it resolved 240 -- the same map, the same behavior, two answers.
    runtime = SceneManager(_HostStub())
    runtime.add_scene("runtime", GameScene("runtime"))
    runtime.set_scene("runtime")
    runtime_renderer = LayerRenderer(SCREEN)
    runtime_renderer.tables = project_tables
    runtime.bind("renderer", runtime_renderer)
    runtime.bind("camera", GameCamera(pygame.Vector2(128, 128),
                                      pygame.Rect(0, 0, 128, 128), scale=1))
    thrown = runtime.spawn("Probe", (8.0, 8.0), depth=50,
                           properties={"pyoneer_behaviors": "platformer_move",
                                       "pyoneer_actor": "hero"})
    expect("a Python-built body reads the actors row the map objects read",
           thrown.behaviors.get("platformer_move").move_speed, 240.0)
    expect_raises("...and a runtime row reference that cannot resolve raises, "
                  "naming the spawn", PyoneerAssetMissingError,
                  lambda: runtime.spawn("Probe", (0.0, 0.0), depth=50,
                                        properties={"pyoneer_actor": "nobody"}),
                  "'nobody'", "SceneManager.spawn")
    bare = runtime.spawn("Probe", (0.0, 0.0), depth=50,
                         properties={"pyoneer_behaviors": "platformer_move"})
    expect("a runtime spawn naming no row still gets the declared default",
           bare.behaviors.get("platformer_move").move_speed, default_speed)


finally:
    SPAWN_REGISTRY.pop("Probe", None)
    SPAWN_REGISTRY.pop("Configured", None)
    shutil.rmtree(workspace, ignore_errors=True)

print()
expect("the module registry was left as it was found",
       sorted(SPAWN_REGISTRY), ["GamePlayer"])

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
