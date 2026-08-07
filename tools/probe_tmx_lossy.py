"""Archaeology probe 3: prove pytmx cannot be used as the basis of a .tmx writer.

Two questions:
  1. Does pytmx preserve the <group> nesting? (needed to rewrite the file)
  2. Does pytmx preserve object/property fidelity + element order?
"""
import _bootstrap  # noqa: F401
import pytmx
from pytmx.pytmx import TiledGroupLayer

tm = pytmx.TiledMap("data/maps/test.tmx")

print("--- Q1: group nesting ---")
for ly in tm.layers:
    if isinstance(ly, TiledGroupLayer):
        print(f"  group {ly.name!r} id={ly.id}")
        print(f"     attrs: {[a for a in vars(ly) if not a.startswith('_')]}")
        print(f"     has .layers? {hasattr(ly, 'layers')}  "
              f"children recorded = {getattr(ly, 'layers', 'N/A')}")
print("  => tm.layers is FLAT; every layer's .parent is:",
      {type(getattr(l, 'parent', None)).__name__ for l in tm.layers})
print("  => the Graphic/Entity <group> membership is NOT recoverable from pytmx.")

print()
print("--- Q2: synthetic round-trip fidelity check ---")
SYN = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.10.2" orientation="orthogonal" renderorder="right-down" width="4" height="4" tilewidth="16" tileheight="16" infinite="0" nextlayerid="3" nextobjectid="4">
 <tileset firstgid="1" name="T" tilewidth="16" tileheight="16" tilecount="4" columns="2">
  <image source="t.png" width="32" height="32"/>
 </tileset>
 <objectgroup id="2" name="spawns" tintcolor="#ff8800" opacity="0.75" offsetx="8" offsety="-4">
  <properties>
   <property name="group_note" value="unused-by-code"/>
  </properties>
  <object id="1" name="hero_start" type="GamePlayer" x="32" y="48" width="16" height="24">
   <properties>
    <property name="entity" value="player"/>
    <property name="depth" type="int" value="50"/>
    <property name="facing" value="down"/>
    <property name="patrol" type="bool" value="true"/>
   </properties>
  </object>
  <object id="2" name="poly" x="0" y="0">
   <polygon points="0,0 16,0 16,16"/>
  </object>
  <object id="3" name="tileobj" gid="3" x="64" y="64" width="16" height="16"/>
 </objectgroup>
</map>
"""
tm2 = pytmx.TiledMap()
tm2.parse_xml(__import__("xml.etree.ElementTree", fromlist=["ElementTree"]).fromstring(SYN))
og = tm2.get_layer_by_name("spawns")
print("  objectgroup attrs pytmx kept:",
      {k: v for k, v in vars(og).items() if not k.startswith("_") and k != "parent"})
for ob in og:
    print(f"  obj id={ob.id} name={ob.name!r} type={ob.type!r} gid={ob.gid} "
          f"x={ob.x} y={ob.y} w={ob.width} h={ob.height}")
    print(f"     properties={ob.properties}")
    print(f"     points={getattr(ob, 'points', None)}  closed={getattr(ob, 'closed', None)}")
print()
print("  property VALUE TYPES pytmx produced:",
      {k: type(v).__name__ for k, v in og[0].properties.items()})
print("  NOTE: pytmx has no writer. Confirmed exports:",
      [n for n in dir(pytmx) if any(s in n.lower() for s in ('sav', 'writ', 'dump', 'serial'))])
