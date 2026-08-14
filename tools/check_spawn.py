"""Verify the object-layer -> entity spawn path.

Six claims, every one of which the code is otherwise free to break with no
visible symptom until an author notices an entity is missing or standing one
sprite too low:

    the registry holds only classes that can actually be constructed
    an unknown type raises and lists the registry -- it never falls back
    a depth property arrives as an int, and a wrongly-typed one raises
    depth resolves property > OBJECT_CONVERTER > layer name > default
    a gid object's bottom-left origin becomes a top-left position
    the position survives construction, which discards the transform kwarg

THE FIXTURE IS THIS FILE'S OWN
------------------------------
Everything is spawned from a .tmx written into a temp directory by
`write_fixture` below. `data/maps/test.tmx` is painted in constantly and is
never read here: a check that pins map CONTENT goes red the next time the
author paints, while the code it guards is working perfectly. That has cost
this repo four red suites.

The fixture needs no art. Its tileset points at a PNG that does not exist,
which both pytmx and MapDocument parse happily as long as no tile image is
resolved -- and no tile image is, because spawning reads object attributes
and not pixels.

    .venv/Scripts/python.exe tools/check_spawn.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import os
import shutil
import sys
import tempfile
import warnings

import pygame

pygame.init()

import pytmx

from scripts.core.depth import DEPTH, MAP_DEPTH, OBJECT_CONVERTER, OBJECT_DEPTH
from scripts.core.errors import PyoneerConfigError, PyoneerError
from scripts.core import spawn as spawn_module
from scripts.core.spawn import (DEFAULT_OBJECT_DEPTH, SPAWN_REGISTRY,
                                register, register_all, resolve_depth,
                                resolve_factory, spawn)
from scripts.game.entity import game_entity as game_entity_module
from scripts.game.entity import game_player as game_player_module
from scripts.game.entity.game_entity import GameAnimatedEntity, GameEntity
from scripts.game.entity.game_player import GamePlayer
from scripts.game.entity.game_transform import Transform
from scripts.loaders.map_document import MapDocument
from scripts.loaders.map_loader import (SpawnedEntity, as_document,
                                        object_group_elements,
                                        object_top_left, spawn_counts,
                                        spawn_objects)

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception, call, *fragments):
    """The call must raise `exception`, and its message must name each fragment.

    The fragments are the teeth. An assertion that only checks the exception
    TYPE passes for any raise anywhere inside the call, including one from a
    typo three frames down.
    """
    try:
        call()
    except exception as exc:
        text = str(exc)
        missing = [f for f in fragments if f not in text]
        ok = not missing
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} "
              f"raised {type(exc).__name__}: {text.splitlines()[0][:70]}")
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
# Test entities. Concrete on purpose, and with no art dependency: GamePlayer
# needs a spritesheet the repository deliberately does not ship, so driving
# the spawn path through it would make this check unrunnable on a clone.
# ---------------------------------------------------------------------------

class ProbeEntity(GameEntity):
    """A GameEntity that is actually constructible.

    GameEntity leaves core_lifecycle_build and core_input_receive abstract;
    filling those two in is the entire difference between the base class and
    something a registry may hold.
    """

    def core_lifecycle_build(self, event=None):
        pass

    def core_input_receive(self, events=None):
        pass


class GameUIEntity(ProbeEntity):
    """Named for an OBJECT_CONVERTER key that has no class in the tree.

    OBJECT_CONVERTER promises "GameUIEntity" -> 100 and nothing anywhere
    defines the class, so this is the only way to exercise the depth
    lookup's fall back to the CONSTRUCTED class's name. Registering it under
    a different tmx type ("Hero") is what makes the two lookups separable.
    """


SCRATCH_REGISTRY: dict[str, object] = {}
register_all([
    ("Probe", ProbeEntity),
    # Deliberately an OBJECT_CONVERTER key (-> 20), so a depth that comes
    # from the class table is distinguishable from the default 50.
    ("GameFloorEntity", ProbeEntity),
    ("Hero", GameUIEntity),
], SCRATCH_REGISTRY)


# ---------------------------------------------------------------------------
# The fixture
# ---------------------------------------------------------------------------

FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="8" height="8" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="7" nextobjectid="20">
 <tileset firstgid="1" name="probe" tilewidth="16" tileheight="16" tilecount="4" columns="2">
  <image source="no-such-art.png" width="32" height="32"/>
  <tile id="0">
   <objectgroup draworder="index" id="6">
    <object id="99" type="Probe" x="0" y="0" width="16" height="16"/>
   </objectgroup>
  </tile>
 </tileset>
 <layer id="1" name="Floor" width="8" height="8">
  <data encoding="csv">
0,0,0,0,0,0,0,0,
0,0,0,0,0,0,0,0,
0,0,0,0,0,0,0,0,
0,0,0,0,0,0,0,0,
0,0,0,0,0,0,0,0,
0,0,0,0,0,0,0,0,
0,0,0,0,0,0,0,0,
0,0,0,0,0,0,0,0
</data>
 </layer>
 <objectgroup id="2" name="entity">
  <object id="1" name="rect" type="Probe" x="64" y="128" width="16" height="32"/>
  <object id="2" name="tile" type="Probe" gid="1" x="32" y="96" width="16" height="32"/>
  <object id="3" name="classattr" class="Probe" x="8" y="8" width="16" height="16"/>
  <object id="4" name="turned" type="Probe" x="0" y="0" width="16" height="16" rotation="45"/>
 </objectgroup>
 <objectgroup id="3" name="ENTITY_3">
  <object id="5" name="declared" type="GameFloorEntity" x="0" y="0" width="16" height="16">
   <properties>
    <property name="pyoneer_depth" type="int" value="77"/>
   </properties>
  </object>
  <object id="6" name="plainprop" type="Probe" x="0" y="0" width="16" height="16">
   <properties>
    <property name="depth" type="int" value="33"/>
   </properties>
  </object>
  <object id="7" name="byclass" type="GameFloorEntity" x="0" y="0" width="16" height="16"/>
  <object id="8" name="byalias" type="Hero" x="0" y="0" width="16" height="16"/>
  <object id="9" name="bylayer" type="Probe" x="0" y="0" width="16" height="16"/>
 </objectgroup>
 <objectgroup id="4" name="props">
  <object id="10" name="region" x="0" y="0" width="64" height="64"/>
  <object id="11" name="marker" x="16" y="16"/>
 </objectgroup>
</map>
"""

BAD_DEPTH = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" orientation="orthogonal" renderorder="right-down" width="4" \
height="4" tilewidth="16" tileheight="16" infinite="0" nextlayerid="3" nextobjectid="4">
 <objectgroup id="2" name="entity">
  <object id="12" name="stringly" type="Probe" x="0" y="0" width="16" height="16">
   <properties>
    <property name="depth" value="50"/>
   </properties>
  </object>
 </objectgroup>
</map>
"""

UNKNOWN_TYPE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" orientation="orthogonal" renderorder="right-down" width="4" \
height="4" tilewidth="16" tileheight="16" infinite="0" nextlayerid="3" nextobjectid="4">
 <objectgroup id="2" name="entity">
  <object id="13" name="spook" type="Ghost" x="0" y="0" width="16" height="16"/>
 </objectgroup>
</map>
"""

SIZELESS_TILE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" orientation="orthogonal" renderorder="right-down" width="4" \
height="4" tilewidth="16" tileheight="16" infinite="0" nextlayerid="3" nextobjectid="4">
 <objectgroup id="2" name="entity">
  <object id="14" name="nosize" type="Probe" gid="1" x="48" y="80"/>
 </objectgroup>
</map>
"""

workspace = tempfile.mkdtemp(prefix="pyoneer_spawn_")


def write_fixture(name: str, text: str) -> str:
    path = os.path.join(workspace, name)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def spawn_all(path: str, **kwargs):
    """Run a spawn pass, returning (spawned, warning messages)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = spawn_objects(path, SCRATCH_REGISTRY, **kwargs)
    return result, [str(w.message) for w in caught]


def quietly(call, *args, **kwargs):
    """Run a pass whose warnings are already asserted elsewhere.

    The fixture deliberately contains a rotated object, so every pass over
    it warns. Letting those reach stderr interleaves them with the ok/FAIL
    lines at whatever point the stream happens to flush, which reads as a
    failure in whichever section they land next to.
    """
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        return call(*args, **kwargs)


try:
    fixture = write_fixture("fixture.tmx", FIXTURE)

    # ------------------------------------------------------- the registry
    print("the registry is seeded only with classes that can be constructed")
    expect("SPAWN_REGISTRY holds exactly the concrete entity",
           sorted(SPAWN_REGISTRY), ["GamePlayer"])
    expect("and it is GamePlayer itself, not a wrapper",
           SPAWN_REGISTRY["GamePlayer"] is GamePlayer, True)
    for name, factory in SPAWN_REGISTRY.items():
        expect(f"{name} has no unimplemented abstract methods",
               sorted(getattr(factory, "__abstractmethods__", ())), [])

    # The two claims spawn.py's docstring makes about why the other five
    # OBJECT_CONVERTER names are absent. If either stops being true, this
    # fails and names the line to change.
    expect("GameEntity is abstract, so it cannot be registered",
           sorted(GameEntity.__abstractmethods__),
           ["core_input_receive", "core_lifecycle_build"])
    expect_raises("constructing GameEntity raises rather than half-working",
                  TypeError, lambda: GameEntity(), "abstract")
    expect("GameAnimatedEntity is abstract too",
           bool(GameAnimatedEntity.__abstractmethods__), True)

    ghosts = ["GameFloorEntity", "GameBackgroundEntity",
              "GameForegroundEntity", "GameUIEntity"]
    for ghost in ghosts:
        expect(f"OBJECT_CONVERTER still promises {ghost}",
               ghost in OBJECT_CONVERTER, True)
        found = (hasattr(game_entity_module, ghost)
                 or hasattr(game_player_module, ghost))
        expect(f"...and no class {ghost} exists to register", found, False)
        expect(f"...so it is not in SPAWN_REGISTRY", ghost in SPAWN_REGISTRY, False)

    # ------------------------------------------------- unknown type raises
    print()
    print("an unknown type raises, lists the registry, and never falls back")
    expect_raises("resolve_factory names the type and the options",
                  PyoneerError,
                  lambda: resolve_factory("Ghost", SCRATCH_REGISTRY),
                  "Ghost", "Probe", "Hero")
    expect_raises("spawn() refuses an unknown type",
                  PyoneerError,
                  lambda: spawn("Ghost", SCRATCH_REGISTRY), "Ghost")
    unknown_map = write_fixture("unknown.tmx", UNKNOWN_TYPE)
    expect_raises("a whole pass refuses rather than skipping the object",
                  PyoneerError,
                  lambda: spawn_objects(unknown_map, SCRATCH_REGISTRY), "Ghost")
    # An empty registry must still raise, not degrade into "nothing to do".
    expect_raises("an empty registry raises too",
                  PyoneerError, lambda: resolve_factory("Probe", {}), "Probe")

    # ------------------------------------------------------ property types
    print()
    print("a depth property arrives typed, and an untyped one raises")
    document = MapDocument.load(fixture)
    declared = document.object_layer("ENTITY_3").find(5).properties["pyoneer_depth"]
    expect("MapDocument types pyoneer_depth as an int", declared, 77)
    expect("...an int, not the string '50' pytmx would hand back",
           isinstance(declared, int) and not isinstance(declared, bool), True)
    bad = write_fixture("bad_depth.tmx", BAD_DEPTH)
    expect_raises("an untyped depth raises instead of being coerced",
                  PyoneerConfigError,
                  lambda: spawn_objects(bad, SCRATCH_REGISTRY),
                  "id=12", "depth", "int")
    expect_raises("a bool depth raises rather than resolving to 1",
                  PyoneerConfigError,
                  lambda: resolve_depth("Probe", {"depth": True}, where="obj"),
                  "bool")
    expect_raises("a float depth raises rather than becoming a dict key",
                  PyoneerConfigError,
                  lambda: resolve_depth("Probe", {"depth": 50.0}, where="obj"),
                  "float")

    # -------------------------------------------------- depth precedence
    print()
    print("depth resolves property > OBJECT_CONVERTER > layer name > default")
    # Each rung is only meaningful because the value below it is different,
    # so assert the ladder's rungs are actually distinct first. If someone
    # renumbers depth.py so two of these collide, the tests below would pass
    # while proving nothing.
    expect("the class rung differs from the default",
           OBJECT_CONVERTER["GameFloorEntity"] != DEFAULT_OBJECT_DEPTH, True)
    expect("the layer rung differs from both",
           MAP_DEPTH["ENTITY_3"] not in (OBJECT_CONVERTER["GameFloorEntity"],
                                         DEFAULT_OBJECT_DEPTH), True)
    expect("the default is the entity depth, not zero",
           DEFAULT_OBJECT_DEPTH, OBJECT_DEPTH["ENTITY"])

    expect("a declared property beats everything",
           resolve_depth("GameFloorEntity", {"pyoneer_depth": 77},
                         layer_name="ENTITY_3", class_name="GameUIEntity"), 77)
    expect("the unprefixed spelling is accepted too",
           resolve_depth("GameFloorEntity", {"depth": 33},
                         layer_name="ENTITY_3"), 33)
    expect("the prefixed spelling wins when both are present",
           resolve_depth("Probe", {"pyoneer_depth": 77, "depth": 33}), 77)
    expect("with no property, the type's OBJECT_CONVERTER entry wins",
           resolve_depth("GameFloorEntity", {}, layer_name="ENTITY_3"),
           OBJECT_CONVERTER["GameFloorEntity"])
    expect("an alias falls back to the CONSTRUCTED class name",
           resolve_depth("Hero", {}, layer_name="ENTITY_3",
                         class_name="GameUIEntity"),
           OBJECT_CONVERTER["GameUIEntity"])
    expect("with neither, the object layer's own name resolves through DEPTH",
           resolve_depth("Probe", {}, layer_name="ENTITY_3"),
           DEPTH["ENTITY_3"])
    expect("an unmapped layer name falls through to the default",
           resolve_depth("Probe", {}, layer_name="entity"), DEFAULT_OBJECT_DEPTH)
    expect("and so does no layer at all",
           resolve_depth("Probe", {}), DEFAULT_OBJECT_DEPTH)

    # ------------------------------------------------------- the y origin
    print()
    print("a gid object's bottom-left origin becomes a top-left position")
    entity_layer = document.object_layer("entity")
    rectangle = entity_layer.find(1)
    tile_object = entity_layer.find(2)
    expect("the fixture's two objects sit at the same declared y",
           (rectangle.y, tile_object.y), (128.0, 96.0))
    expect("a rectangle's y is already the top edge",
           object_top_left(rectangle, 16), (64.0, 128.0))
    expect("a tile object is lifted by its own height",
           object_top_left(tile_object, 16), (32.0, 96.0 - 32.0))
    expect("the lift is the object height, not the map's tile height",
           object_top_left(tile_object, 16)[1] != 96.0 - 16.0, True)

    sizeless = MapDocument.load(write_fixture("sizeless.tmx", SIZELESS_TILE))
    nosize = sizeless.object_layer("entity").find(14)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fallback = object_top_left(nosize, 16)
    expect("a gid object with no height falls back to the tile height",
           fallback, (48.0, 80.0 - 16.0))
    expect("...and says so rather than guessing quietly",
           any("no height" in str(w.message) for w in caught), True)

    # ---------------------------------------------------- the whole pass
    print()
    print("the pass constructs, positions and depths every typed object")
    spawned, messages = spawn_all(fixture)
    by_id = {item.object_id: item for item in spawned}
    expect("every typed object spawned, and only those",
           sorted(by_id), [1, 2, 3, 4, 5, 6, 7, 8, 9])
    expect("results are SpawnedEntity records",
           all(isinstance(item, SpawnedEntity) for item in spawned), True)
    expect("spawn_counts groups by tmx type",
           spawn_counts(spawned), {"Probe": 6, "GameFloorEntity": 2, "Hero": 1})

    # The transform kwarg is accepted and discarded by GameEntity, so the
    # ONLY thing that can put an entity anywhere is the moveto() call after
    # construction. Assert the discard first, so a future fix to
    # game_entity.py shows up here as a deliberate change rather than as a
    # mystery.
    marker = Transform(position=(999, 999))
    expect("GameEntity still discards its transform kwarg",
           tuple(ProbeEntity(transform=marker).transform.position), (0.0, 0.0))
    expect("so the loader's moveto is what places a rectangle object",
           tuple(by_id[1].entity.transform.position), (64.0, 128.0))
    expect("...and a tile object lands at its lifted top-left",
           tuple(by_id[2].entity.transform.position), (32.0, 64.0))

    expect("Tiled 1.9's class= attribute types an object too",
           by_id[3].type_name, "Probe")
    expect("entities are constructed instances of the registered class",
           type(by_id[8].entity).__name__, "GameUIEntity")

    expect("id=5 takes its declared depth", by_id[5].depth, 77)
    expect("id=6 takes its unprefixed declared depth", by_id[6].depth, 33)
    expect("id=7 takes the OBJECT_CONVERTER depth for its type",
           by_id[7].depth, OBJECT_CONVERTER["GameFloorEntity"])
    expect("id=8 takes the depth of the class it actually built",
           by_id[8].depth, OBJECT_CONVERTER["GameUIEntity"])
    expect("id=9 takes its object layer's depth", by_id[9].depth, DEPTH["ENTITY_3"])
    expect("id=1 on an unmapped layer takes the default",
           by_id[1].depth, DEFAULT_OBJECT_DEPTH)
    expect("the layer name is carried for error reporting",
           by_id[9].layer_name, "ENTITY_3")

    # Nothing is bound, and nothing writes entity.depth: EntityLayer queues
    # at entity.depth + layer_depth, so setting both would double it.
    expect("entity.depth is left alone, because it is a within-layer offset",
           sorted({item.entity.depth for item in spawned}), [0])

    expect("an untyped object is skipped and reported once per layer",
           [m for m in messages if "no Type" in m and "'props'" in m
            and "[10, 11]" in m],
           [f"object layer 'props' has 2 object(s) with no Type and spawned "
            f"nothing for them: ids [10, 11]. That is normal for region "
            f"markers and is a typo if it was meant to be an entity."])
    expect("a rotation the render path cannot draw is reported",
           any("rotation=45" in m and "id=4" in m for m in messages), True)

    # ------------------------------------------------ layers and phantoms
    print()
    print("only real object layers are walked, and the filter narrows them")
    expect("the tileset's per-tile collision group is not an object layer",
           [e.get("name") for e in object_group_elements(document)],
           ["entity", "ENTITY_3", "props"])
    expect("...even though the document's name list includes it",
           "" in document.object_layer_names(), True)
    expect("...and pytmx hands back a phantom layer for it",
           sum(1 for layer in pytmx.TiledMap(fixture).layers
               if isinstance(layer, pytmx.TiledObjectGroup)
               and layer.name is None), 1)
    expect("nothing spawned from inside the tileset",
           99 in by_id, False)

    only_entity, _ = spawn_all(fixture, layers=["entity"])
    expect("layers= restricts the pass",
           sorted(item.object_id for item in only_entity), [1, 2, 3, 4])
    empty, _ = spawn_all(fixture, layers=["nothing-called-this"])
    expect("an unmatched filter spawns nothing", empty, [])

    # ------------------------------------------------------ input coercion
    print()
    print("a MapDocument, a path and a parsed pytmx map all work")
    from_document = quietly(spawn_objects, document, SCRATCH_REGISTRY,
                            layers=["ENTITY_3"])
    from_pytmx = quietly(spawn_objects, pytmx.TiledMap(fixture),
                         SCRATCH_REGISTRY, layers=["ENTITY_3"])
    from_path = quietly(spawn_objects, fixture, SCRATCH_REGISTRY,
                        layers=["ENTITY_3"])
    def signature(items):
        """Everything about a pass EXCEPT object identity.

        Comparing the SpawnedEntity records directly would compare the
        entity objects, and two passes build two different instances, so
        that assertion would fail for a reason that is not a bug.
        """
        return [(i.object_id, i.depth, i.type_name,
                 tuple(i.entity.transform.position)) for i in items]

    expect("a path and a MapDocument agree",
           signature(from_path), signature(from_document))
    expect("a parsed pytmx map agrees, because it is re-read as a document",
           signature(from_pytmx), signature(from_document))
    expect("as_document returns the document it was handed, unwrapped",
           as_document(document) is document, True)
    expect_raises("a map with no filename says so rather than spawning nothing",
                  PyoneerError, lambda: as_document(object()), "filename")

    # ----------------------------------------------- constructor arguments
    print()
    print("per-type constructor arguments reach the class")
    seen: list[dict] = []

    def recording_factory(**kwargs):
        seen.append(kwargs)
        return ProbeEntity()

    scratch = dict(SCRATCH_REGISTRY)
    register("Probe", recording_factory, scratch)
    quietly(spawn_objects, fixture, scratch, layers=["entity"],
            defaults={"Probe": {"movement_config": {"move_speed": 20}}})
    expect("defaults are passed as keyword arguments",
           seen, [{"movement_config": {"move_speed": 20}}] * 4)
    expect("registering into a scratch dict left the module registry alone",
           sorted(spawn_module.SPAWN_REGISTRY), ["GamePlayer"])

finally:
    shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
