"""Verify the map-layer bake: empty layers are dropped, composites are exact.

Four claims, each of which the renderer would otherwise be free to break
without any visible symptom until someone looked at a profiler or a diff of
two screenshots:

    an empty tile layer produces no MapLayer   (and says so out loud)
    the composite preserves entity interleaving
    a rebake reproduces the same frame, byte for byte
    a layer that says it does not draw is skipped in SILENCE, and one that
        does draw and has no depth still warns

    .venv/Scripts/python.exe tools/check_maplayers.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import hashlib
import os
import sys
import tempfile
import warnings

import pygame

pygame.init()
pygame.display.set_mode((1024, 768))

import pytmx

import main as main_module
from scripts.core import blitpool, layer_profile
from scripts.core.depth import MAP_DEPTH
from scripts.core.renderer import (LayerRenderer, MapComposite, MapLayer,
                                   composite_is_exact, drawable_tile_count,
                                   opaque_mask, partial_alpha_mask)
from scripts.game.game_camera import GameCamera
from scripts.game.game_map import GameMap

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<56} got={got} want={want}")
    if not ok:
        failures.append(label)


# ENTITY_DEPTHS is derived from the booted renderer, just below.

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    game = main_module.MainGame(autostart=False)
    boot_warnings = [str(w.message) for w in caught]

game.begin(max_frames=1)
renderer = game.renderer

# DERIVED FROM THE BOOTED RENDERER, never typed. This read `(40, 41)` while
# `main.py` built six bodies by hand at those depths; those are deleted and
# the map's own object layer produces the bodies now, so a typed pair would
# be pinning decoys that no longer exist. `SpawnedEntity.depth` is the LAYER
# depth each body was bound into -- the code's answer, not the map's -- so
# repainting or replacing the shipped map cannot make the rows below red.
ENTITY_DEPTHS = tuple(sorted({s.depth for s in renderer.spawned_entities}))
expect("the map's object layer produced at least one body",
       len(ENTITY_DEPTHS) >= 1, True)


def tile_layers():
    """Every tile-ish layer currently in the render list, as (depth, layer)."""
    found = []
    for depth in sorted(renderer.layers):
        for layer in renderer.layers[depth]:
            if isinstance(layer, (MapLayer, MapComposite)):
                found.append((depth, layer))
    return found


def source_names():
    """Names of every rasterized tile layer, composited or not."""
    names = []
    for _depth, layer in tile_layers():
        if isinstance(layer, MapComposite):
            names.extend(str(s.layer_name) for s in layer.sources)
        else:
            names.append(str(layer.layer_name))
    return names


def frame_hash():
    game.tick()
    game.frame += 1
    return hashlib.sha256(
        pygame.image.tostring(pygame.display.get_surface(), "RGB")
    ).hexdigest()[:16]


def frame_blits():
    """(depth, sender class name) for every token queued by one frame."""
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
        game.tick()
        game.frame += 1
    finally:
        blitpool.BlitPool.get_blit_pool_pygame = original
    return captured


# ---------------------------------------------------------------- empty layers
print("an empty tile layer produces no MapLayer")
tmx = game.assets.maps.load_assets(main_module.MAP_NAME)
declared = {layer.name: layer for layer in tmx.layers
            if isinstance(layer, pytmx.TiledTileLayer)}
empty = [name for name, layer in declared.items()
         if drawable_tile_count(layer, tmx) == 0]
# Two reasons a declared layer is absent from the render list, and both are
# discovered from the file rather than named. Which layers are empty is
# CONTENT, and the author paints in this map -- naming "Above1" here failed
# the moment tiles were painted into it, while the code it guards was working
# perfectly. Which layers declare pyoneer_renders=false is content too: he
# gets a companion the moment he paints collision anywhere.
undrawn = [name for name, layer in declared.items()
           if not layer_profile.read(layer).renders]
occupancy = {name: drawable_tile_count(layer, tmx)
             for name, layer in declared.items()}
print(f"  ..   {'tiles per declared layer':<54} {occupancy}")
print(f"  ..   {'layers declaring they do not draw':<54} {sorted(undrawn)}")
expect("at least one layer has tiles",
       any(count > 0 for count in occupancy.values()), True)
expect("empty is exactly the set with a zero count",
       sorted(empty), sorted(n for n, c in occupancy.items() if c == 0))
expect("Floor is not mistaken for empty", occupancy["Floor"] > 0, True)

for name in empty:
    expect(f"{name} rasterized nowhere", name in source_names(), False)
    depth = None
    for layer in tmx.layers:
        if getattr(layer, "name", None) == name:
            from scripts.core.depth import resolve_layer_depth
            depth = resolve_layer_depth(name)
    expect(f"{name}'s depth {depth} holds no layer", depth in renderer.layers, False)
    expect(f"{name} was reported, not silently dropped",
           any(name in message and "no drawable tiles" in message
               for message in boot_warnings), True)

for name in undrawn:
    expect(f"{name} says it does not draw, and does not", name in source_names(), False)
    # Narrowly the renderer's own advice, not every mention of the name:
    # `collision_layers` legitimately names a companion when the layer that
    # declares it cannot carry masks. Absolute silence is asserted over the
    # fixture below, where every layer in the map is this check's own.
    expect(f"{name} was not advised to get a depth",
           [m for m in boot_warnings
            if name in m and "has no depth mapping" in m], [])

expect("every drawable declared layer survived",
       sorted(source_names()),
       sorted(n for n in declared if n not in empty and n not in undrawn))

# ------------------------------------------------------------- interleaving
print()
print("the composite preserves entity interleaving")
composites = [l for _d, l in tile_layers() if isinstance(l, MapComposite)]
# Deliberately NOT "exactly two composites". How many runs the renderer can
# merge is a property of the MAP CONTENT, not of the code: painting tiles
# that put partial alpha over partial alpha makes a merge provably lossy,
# and composite_is_exact then correctly refuses it. That happened for real
# the first time the author painted into PlayerDepth and Foreground, and it
# failed this check even though the engine had behaved perfectly.
#
# The invariants are that compositing HAPPENS, that it SAVES work, and that
# it never spans the entity layers. All three hold for any content.
sources = sum(len(c.sources) if isinstance(c, MapComposite) else 1
              for _d, c in tile_layers())
expect("compositing is happening at all", len(composites) >= 1, True)
expect("and it costs fewer blits than there are source layers",
       len(tile_layers()) < sources, True)

for composite in composites:
    low, high = composite.depth_band
    expect(f"composite {composite.depth_band} does not span the entities",
           any(low <= d <= high for d in ENTITY_DEPTHS), False)
    expect(f"composite {composite.depth_band} is queued at its lowest depth",
           composite.layer_depth, low)

blits = frame_blits()
tile_depths = [d for d, sender in blits
               if sender in ("MapLayer", "MapComposite")]
entity_depths = [d for d, sender in blits if sender == "GamePlayer"]
expect("the bodies still draw, at the depths they were bound into",
       sorted(set(entity_depths)), list(ENTITY_DEPTHS))
expect("no tile layer draws between the entity layers",
       [d for d in tile_depths if min(ENTITY_DEPTHS) <= d <= max(ENTITY_DEPTHS)], [])
expect("tiles below the entities are drawn first",
       min(tile_depths) < min(entity_depths), True)
expect("tiles above the entities are drawn last",
       max(tile_depths) > max(entity_depths), True)
# The pool flushes in sorted depth order, so ordering in the list mirrors it.
order = [sender for _d, sender in blits]
tile_positions = [i for i, sender in enumerate(order)
                  if sender in ("MapLayer", "MapComposite")]
entity_positions = [i for i, sender in enumerate(order) if sender == "GamePlayer"]
expect("some tiles are queued before every entity",
       min(tile_positions) < min(entity_positions), True)
expect("some tiles are queued after every entity",
       max(tile_positions) > max(entity_positions), True)
expect("no tile token is queued between the two entity layers",
       [i for i in tile_positions
        if min(entity_positions) < i < max(entity_positions)], [])

# The opaque claim is measured, not assumed: an opaque composite drops its
# alpha channel, and a .convert()ed surface has no SRCALPHA flag.
for composite in composites:
    image = composite.require_image()
    flagged = bool(image.get_flags() & pygame.SRCALPHA)
    expect(f"composite {composite.depth_band} opaque flag matches its surface",
           composite.opaque, not flagged)
    if composite.opaque:
        w, h = image.get_size()
        expect(f"composite {composite.depth_band} really covers every pixel",
               opaque_mask(image).count(), w * h)

# The claim that matters, checked over the WHOLE map rather than the one
# viewport the smoke run happens to sit at: drawing the composite must land
# the same pixels as drawing its sources one at a time. Two backgrounds,
# because the double-alpha error this guards against is background-dependent
# and vanishes on some of them.
print()
print("the flattened surface equals the sequential draw, over the whole map")
for composite in composites:
    ordered = sorted(composite.sources, key=lambda s: s.layer_depth)
    size = composite.require_image().get_size()
    for background in ((0, 0, 0), (128, 96, 64)):
        sequential = pygame.Surface(size)
        sequential.fill(background)
        for source in ordered:
            sequential.blit(source.require_image(), (0, 0))
        flattened = pygame.Surface(size)
        flattened.fill(background)
        flattened.blit(composite.require_image(), (0, 0))
        expect(f"composite {composite.depth_band} on {background}",
               hashlib.sha256(pygame.image.tostring(flattened, "RGB")).hexdigest()[:16],
               hashlib.sha256(pygame.image.tostring(sequential, "RGB")).hexdigest()[:16])

# ------------------------------------------------------------------- rebake
print()
print("a rebake reproduces the same frame")
before = frame_hash()
expect("two untouched frames agree", frame_hash(), before)
grouped_before = len(tile_layers())

renderer.invalidate()                     # full regroup + re-rasterize
expect("invalidate() marks the grouping stale", renderer._map_regroup, True)
after_regroup = frame_hash()
expect("regroup rebake is byte-identical", after_regroup, before)
expect("the flag is cleared once serviced", renderer._map_regroup, False)
expect("regroup did not composite a composite",
       len(tile_layers()), grouped_before)

renderer.invalidate((1, 30))              # band path: pixels only
expect("band invalidate leaves the grouping alone", renderer._map_regroup, False)
expect("band invalidate is recorded", (1, 30) in renderer._map_invalid, True)
expect("band rebake is byte-identical", frame_hash(), before)

renderer.invalidate(60)                   # int is accepted as a 1-wide band
expect("int invalidate is normalised to a band",
       (60, 60) in renderer._map_invalid, True)
expect("single-depth rebake is byte-identical", frame_hash(), before)

# Rebaking a composite directly must also be idempotent.
for composite in composites:
    composite.rebake()
expect("direct MapComposite.rebake is byte-identical", frame_hash(), before)

# ------------------------------------------------- the exactness rule itself
print()
print("composite_is_exact encodes pygame's actual blend behaviour")


def surf(color, alpha, size=(4, 4)):
    s = pygame.Surface(size, pygame.SRCALPHA)
    s.fill((*color, alpha))
    return s


def half(color, alpha):
    """Partial alpha on the left half only, so overlap can be controlled."""
    s = pygame.Surface((4, 4), pygame.SRCALPHA)
    s.fill((0, 0, 0, 0))
    s.fill((*color, alpha), pygame.Rect(0, 0, 2, 4))
    return s


def right(color, alpha):
    s = pygame.Surface((4, 4), pygame.SRCALPHA)
    s.fill((0, 0, 0, 0))
    s.fill((*color, alpha), pygame.Rect(2, 0, 2, 4))
    return s


expect("a single layer is trivially exact", composite_is_exact([surf((1, 2, 3), 128)]), True)
expect("binary alpha merges", composite_is_exact([surf((9, 9, 9), 255),
                                                  surf((7, 7, 7), 0)]), True)
expect("partial alpha onto an untouched buffer merges",
       composite_is_exact([surf((9, 9, 9), 128), surf((7, 7, 7), 0)]), True)
expect("partial alpha backed by an opaque layer merges",
       composite_is_exact([surf((9, 9, 9), 255), surf((7, 7, 7), 128)]), True)
expect("disjoint partial alpha merges",
       composite_is_exact([half((9, 9, 9), 128), right((7, 7, 7), 200)]), True)
expect("partial alpha ONTO partial alpha does not merge",
       composite_is_exact([surf((9, 9, 9), 128), surf((7, 7, 7), 200)]), False)
expect("partial-on-partial covered by a later opaque layer merges",
       composite_is_exact([surf((9, 9, 9), 128), surf((7, 7, 7), 200),
                           surf((5, 5, 5), 255)]), True)
expect("partial alpha mask counts partials only",
       partial_alpha_mask(surf((9, 9, 9), 128)).count(), 16)
expect("partial alpha mask ignores opaque", partial_alpha_mask(surf((9, 9, 9), 255)).count(), 0)

# And the reason the rule has to exist at all. If a future pygame fixes the
# blitter these two assertions fail loudly, rather than leaving a needlessly
# conservative rule in place forever with nothing pointing at it.
def flatten_differs(layers, background):
    direct = pygame.Surface((1, 1))
    direct.fill(background)
    buffer = pygame.Surface((1, 1), pygame.SRCALPHA)
    buffer.fill((0, 0, 0, 0))
    for color, alpha in layers:
        one = surf(color, alpha, (1, 1))
        direct.blit(one, (0, 0))
        buffer.blit(one, (0, 0))
    screen = pygame.Surface((1, 1))
    screen.fill(background)
    screen.blit(buffer, (0, 0))
    return direct.get_at((0, 0))[:3] != screen.get_at((0, 0))[:3]


expect("one partial layer flattens exactly (pygame copies onto alpha 0)",
       flatten_differs([((90, 90, 90), 64)], (0, 0, 0)), False)
expect("partial onto partial still loses pixels",
       flatten_differs([((0, 0, 0), 1), ((90, 90, 90), 32)], (0, 0, 0)), True)

print()
print("invalidate() re-rasterizes sources, so a content edit reaches the screen")
# The live-edit spine: MapDocument writes tiles, load_assets(reload=True)
# reparses, then the renderer has to actually re-rasterize. Skipping the rebake
# on the invalidate() path -- to avoid a boot-time double-rasterization -- would
# leave the BROADEST call doing less than a band call, and a tile edit would
# render stale pixels with no error. Asserted directly rather than through a
# real file edit, which is slow and touches the map.
import main as main_module

game = main_module.MainGame(autostart=False)
game.begin(max_frames=1)
renderer = game.renderer

rebakes = {"n": 0}
sources = [s for layers in renderer.map_sources.values() for s in layers]
for source in sources:
    original = source.rebake

    def counting(_o=original):
        rebakes["n"] += 1
        return _o()

    source.rebake = counting

expect("there are sources to rebake", len(sources) > 0, True)

rebakes["n"] = 0
renderer.invalidate()
renderer.rebake_map()
expect("invalidate() rebakes every source", rebakes["n"], len(sources))

rebakes["n"] = 0
renderer.invalidate((min(renderer.map_sources), max(renderer.map_sources)))
renderer.rebake_map()
expect("invalidate(band) rebakes every source in the band", rebakes["n"], len(sources))

rebakes["n"] = 0
renderer.invalidate(sources_dirty=False)
renderer.rebake_map()
expect("sources_dirty=False regroups WITHOUT rebaking", rebakes["n"], 0)

# ------------------------------------------------------- renders=false is data
print()
print("a layer that declares it does not draw is skipped in silence -- and one "
      "that does draw is still warned about")
# The bug this pins: a passability companion declares pyoneer_renders=false,
# the renderer ignored the declaration entirely, and the layer stayed off
# screen only because its name happened to be absent from MAP_DEPTH -- so the
# author was ADVISED to add it, and following that advice would have painted
# the mask vocabulary over his map.
#
# Both halves, because silencing both is a regression wearing a fix: the
# no-depth warning is the guard that caught 39 authored tiles going missing
# to a misspelling, and it must still fire for a layer that really is art.
#
# A fixture, never data/maps/starter.tmx: that map is repainted, and
# what it declares is his business (law 4).
FIXTURE_ROW = "1,1,1,1"
FIXTURE_CSV = ",\n".join([FIXTURE_ROW] * 4)
FIXTURE_HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="4" height="4" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="9" nextobjectid="1">
 <tileset firstgid="1" name="probe" tilewidth="16" tileheight="16" \
tilecount="4" columns="2">
  <image source="probe.png" width="32" height="32"/>
 </tileset>
"""
NO_DRAW = '   <property name="pyoneer_renders" type="bool" value="false"/>\n'

# Two names the code ranks and two it does not. Read off MAP_DEPTH rather
# than assumed, so adding "ProbeMask" to the table makes this say so instead
# of passing on a premise that stopped being true.
RANKED_ART, RANKED_MASK = "Floor", "Above1"
UNRANKED_ART, UNRANKED_MASK = "ProbeArt", "ProbeMask"
expect("the two ranked probe names really are ranked",
       [name in MAP_DEPTH for name in (RANKED_ART, RANKED_MASK)], [True, True])
expect("and the two unranked ones really are not",
       [name in MAP_DEPTH for name in (UNRANKED_ART, UNRANKED_MASK)],
       [False, False])


def fixture_layer(layer_id: int, name: str, declares: str = "") -> str:
    return (f' <layer id="{layer_id}" name="{name}" width="4" height="4">\n'
            + (f"  <properties>\n{declares}  </properties>\n" if declares else "")
            + f'  <data encoding="csv">\n{FIXTURE_CSV}\n</data>\n </layer>\n')


probe_workspace = tempfile.mkdtemp(prefix="pyoneer_maplayers_")
probe_sheet = pygame.Surface((32, 32))
for index, color in enumerate(((180, 40, 40), (40, 180, 40),
                               (40, 40, 180), (180, 180, 40))):
    probe_sheet.fill(color, pygame.Rect((index % 2) * 16, (index // 2) * 16, 16, 16))
pygame.image.save(probe_sheet, os.path.join(probe_workspace, "probe.png"))
probe_path = os.path.join(probe_workspace, "probe.tmx")
with open(probe_path, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(FIXTURE_HEAD
                 + fixture_layer(1, RANKED_ART)
                 + fixture_layer(2, UNRANKED_ART)
                 + fixture_layer(3, UNRANKED_MASK, NO_DRAW)
                 + fixture_layer(4, RANKED_MASK, NO_DRAW)
                 + ' <objectgroup id="5" name="entity"/>\n</map>\n')

probe_renderer = LayerRenderer(pygame.display.get_surface())
probe_renderer.bind_camera(GameCamera(pygame.Vector2(64, 64),
                                      pygame.Rect(0, 0, 64, 64), scale=1))
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    probe_renderer.bind("MAP", GameMap(pytmx.load_pygame(probe_path)))
    probe_warnings = [str(w.message) for w in caught]

probe_drawn = []
for depth in sorted(probe_renderer.layers):
    for layer in probe_renderer.layers[depth]:
        if isinstance(layer, MapComposite):
            probe_drawn.extend(str(source.layer_name) for source in layer.sources)
        elif isinstance(layer, MapLayer):
            probe_drawn.append(str(layer.layer_name))

print(f"  ..   {'drawn':<54} {sorted(probe_drawn)}")
expect("a ranked layer with tiles is drawn, so the skip is not blanket",
       RANKED_ART in probe_drawn, True)
expect("a layer declaring renders=false is NOT drawn -- even though its name "
       "has a depth", RANKED_MASK in probe_drawn, False)
expect("nor is one whose name has no depth", UNRANKED_MASK in probe_drawn, False)
expect("and neither of them was mentioned at all",
       [message for message in probe_warnings
        if RANKED_MASK in message or UNRANKED_MASK in message], [])
expect("the layer that DOES draw and has no depth is still reported",
       len([m for m in probe_warnings if UNRANKED_ART in m]), 1)
expect("it says what happens, not merely that something is odd",
       all(part in probe_warnings[0]
           for part in ("has no depth mapping", "will NOT be drawn",
                        "MAP_DEPTH")), True)
expect("and it offers the declaration instead of only the depth table",
       "pyoneer_renders=false" in probe_warnings[0], True)
expect("that warning is the ONLY thing the bind said",
       len(probe_warnings), 1)
expect("the unranked art layer is not drawn either",
       UNRANKED_ART in probe_drawn, False)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
