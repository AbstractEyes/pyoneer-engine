"""Archaeology probe: dump raw XML structure of a .tmx and what pytmx makes of it."""
import _bootstrap  # noqa: F401
import sys
import xml.etree.ElementTree as ET

PATH = sys.argv[1] if len(sys.argv) > 1 else "data/maps/test.tmx"

print("=" * 70)
print("RAW XML TREE (data/property payloads elided)")
print("=" * 70)
tree = ET.parse(PATH)
root = tree.getroot()


def walk(el, indent=0):
    attrs = " ".join(f'{k}="{v}"' for k, v in el.attrib.items())
    txtlen = len((el.text or "").strip())
    note = f"  [text {txtlen} chars]" if txtlen else ""
    print("  " * indent + f"<{el.tag} {attrs}>{note}")
    if el.tag == "data":
        return
    for c in el:
        walk(c, indent + 1)


walk(root)

print()
print("=" * 70)
print("PYTMX VIEW")
print("=" * 70)
import pytmx  # noqa: E402

tm = pytmx.TiledMap(PATH)
print(f"pytmx version: {pytmx.__version__ if hasattr(pytmx, '__version__') else '?'}")
print(f"map {tm.width}x{tm.height} tile {tm.tilewidth}x{tm.tileheight}")
print(f"map properties: {tm.properties}")
print(f"tm.layers ({len(tm.layers)}):")
for ly in tm.layers:
    print(f"  - {ly.name!r:16} {type(ly).__name__:22} id={getattr(ly, 'id', None)} "
          f"visible={getattr(ly, 'visible', None)} props={getattr(ly, 'properties', {})}")
    if isinstance(ly, pytmx.TiledObjectGroup):
        print(f"      OBJECT GROUP with {len(ly)} objects:")
        for ob in ly:
            print(f"        obj id={ob.id} name={ob.name!r} type={getattr(ob, 'type', None)!r} "
                  f"gid={getattr(ob, 'gid', None)} at=({ob.x},{ob.y}) size=({ob.width}x{ob.height})")
            print(f"           props={ob.properties}")

print()
print("tm.objectgroups:", list(getattr(tm, "objectgroups", [])))
print("tm.visible_layers:", [l.name for l in tm.visible_layers])
try:
    print("tm.visible_tile_layers idx:", list(tm.visible_tile_layers))
except Exception as e:
    print("visible_tile_layers err", e)
print("tm.layernames keys:", list(tm.layernames.keys()))
print()
print("GROUP NESTING: does pytmx flatten <group>?")
for ly in tm.layers:
    print("   ", ly.name, "parent=", getattr(ly, "parent", None).__class__.__name__)
