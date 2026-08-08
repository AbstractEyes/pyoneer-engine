"""Verify the map-layer bake: empty layers are dropped, composites are exact.

Three claims, each of which the renderer would otherwise be free to break
without any visible symptom until someone looked at a profiler or a diff of
two screenshots:

    an empty tile layer produces no MapLayer   (and says so out loud)
    the composite preserves entity interleaving
    a rebake reproduces the same frame, byte for byte

    .venv/Scripts/python.exe tools/check_maplayers.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import hashlib
import sys
import warnings

import pygame

pygame.init()
pygame.display.set_mode((1024, 768))

import pytmx

import main as main_module
from scripts.core import blitpool
from scripts.core.renderer import (MapComposite, MapLayer, composite_is_exact,
                                   drawable_tile_count, opaque_mask,
                                   partial_alpha_mask)

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<56} got={got} want={want}")
    if not ok:
        failures.append(label)


ENTITY_DEPTHS = (40, 41)

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    game = main_module.MainGame(autostart=False)
    boot_warnings = [str(w.message) for w in caught]

game.begin(max_frames=1)
renderer = game.renderer


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
tmx = game.assets.maps.load_assets("test")
declared = {layer.name: layer for layer in tmx.layers
            if isinstance(layer, pytmx.TiledTileLayer)}
empty = [name for name, layer in declared.items()
         if drawable_tile_count(layer, tmx) == 0]
expect("test.tmx still declares an empty tile layer", empty, ["Above1"])
expect("Floor is not mistaken for empty",
       drawable_tile_count(declared["Floor"], tmx), 10000)

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

expect("every non-empty declared layer survived",
       sorted(source_names()),
       sorted(n for n in declared if n not in empty))

# ------------------------------------------------------------- interleaving
print()
print("the composite preserves entity interleaving")
composites = [l for _d, l in tile_layers() if isinstance(l, MapComposite)]
expect("both bands composited", len(composites), 2)
expect("six declared tile layers now cost two blits", len(tile_layers()), 2)

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
expect("entities still draw at 40/41", sorted(set(entity_depths)), [40, 41])
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

renderer.invalidate()                     # full regroup + re-rasterize
expect("invalidate() marks the grouping stale", renderer._map_regroup, True)
after_regroup = frame_hash()
expect("regroup rebake is byte-identical", after_regroup, before)
expect("the flag is cleared once serviced", renderer._map_regroup, False)
expect("regroup did not composite a composite", len(tile_layers()), 2)

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
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
