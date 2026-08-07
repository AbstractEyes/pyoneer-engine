"""Archaeology probe 2: which authored tmx layers actually reach the renderer?

Works around the transient input.py binding-validation failure (another worker
is mid-edit there) so the map/render seam can be measured today.
"""
import _bootstrap  # noqa: F401

import scripts.core.input as inp
_orig_validate = inp.InputActionManager.validate_bindings
inp.InputActionManager.validate_bindings = lambda self: None  # transient shim

import pygame  # noqa: E402
import pytmx  # noqa: E402

pygame.init()
pygame.display.set_mode((640, 480))

from scripts.core.depth import MAP_DEPTH, OBJECT_DEPTH, OBJECT_CONVERTER, DEPTH  # noqa: E402
from scripts.core.renderer import LayerRenderer  # noqa: E402
from scripts.game.game_map import GameMap  # noqa: E402

tm = pytmx.load_pygame("data/maps/test.tmx")

authored = [l.name for l in tm.layers]
print("authored tmx layers :", authored)
print("MAP_DEPTH keys      :", list(MAP_DEPTH))
print()
print("--- per-authored-layer verdict ---")
for l in tm.layers:
    kind = type(l).__name__
    in_depth = l.name in MAP_DEPTH
    renders = in_depth and isinstance(l, pytmx.TiledTileLayer)
    print(f"  {l.name:16} {kind:20} in MAP_DEPTH={str(in_depth):5} -> RENDERS={renders}")
print()
print("--- MAP_DEPTH keys with no authored layer ---")
for k in MAP_DEPTH:
    if k not in tm.layernames:
        print(f"  {k:16} depth={MAP_DEPTH[k]}  (renderer prints 'Layer not found in map')")
print()

print("--- actually binding a GameMap through LayerRenderer ---")
screen = pygame.display.get_surface()
r = LayerRenderer(screen)
r.bind("MAP", GameMap(tm))
print("renderer.layers depths ->", sorted(r.layers))
for d in sorted(r.layers):
    for ly in r.layers[d]:
        print(f"    depth {d:4} {type(ly).__name__:20} name={ly.layer_name!r} type={ly.layer_type}")
print()
print("DEPTH merged table:", DEPTH)
print()
print("--- tmx tile GID usage per layer (are the dead layers even populated?) ---")
for l in tm.layers:
    if isinstance(l, pytmx.TiledTileLayer):
        nz = sum(1 for _x, _y, gid in l if gid)
        print(f"  {l.name:16} nonzero gids = {nz}")
