"""Measure the native .blitmap / .tileset formats and the tmx converter.

Four claims, and only the first is about syntax:

    the format is CANONICAL -- parse(render(m)) is m, render(parse(t)) is t
    the converter is LOSSLESS -- every layer, gid, object, property and
        tileset in a .tmx comes out the other side, and what does NOT is
        named in `Conversion.dropped` rather than lost quietly
    the reader REFUSES what it cannot read exactly, and says which line
    interning DECIDES before it copies, and the decision is a pure value

The fidelity run is against a COPY of data/maps/test.tmx, and every
assertion in it is derived-versus-derived: the tmx is read by a second,
independent reader here (a regex over the csv, ElementTree over the
attributes) and the two censuses are compared. Nothing pins what the map
CONTAINS, because the author paints in that file constantly and four red
suites have come from checks that froze its contents.

Pure Python. No Qt, no pygame, no pytmx -- which is most of the point of the
format, so it is also asserted.

    .venv/Scripts/python.exe tools/check_blitmap.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import os
import re
import shutil
import sys
import tempfile
import time
import warnings
import xml.etree.ElementTree as ElementTree

from scripts.core import collision_runtime, layer_profile
from scripts.core.errors import PyoneerContentWarning
from scripts.loaders import blitmap
from scripts.loaders.blitmap import (
    Blitmap,
    Conversion,
    ImageLayer,
    LayerGroup,
    ObjectLayer,
    Property,
    PyoneerBlitFormatError,
    Shape,
    TileLayer,
    TilesetLink,
    declared_collision,
    from_tmx,
    tileset_reference,
    write_conversion,
)
from scripts.loaders.map_document import MapDocument
from scripts.loaders.tileset_file import (
    COPY,
    KEEP,
    MISSING,
    OCCUPIED,
    TilesetFile,
    apply_intern,
    interned,
    plan_intern,
    resolve_image,
)

ROOT = _bootstrap.REPO_ROOT
REAL_MAP = os.path.join(ROOT, "data", "maps", "test.tmx")
REAL_IMAGE = os.path.join(ROOT, "data", "graphics", "tilesets", "System", "TileA2.png")

failures: list[str] = []


def brief(value) -> str:
    text = repr(value)
    return text if len(text) <= 66 else text[:63] + "..."


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<56} got={brief(got)} want={brief(want)}")
    if not ok:
        failures.append(label)


def expect_returns(label, action, want):
    """`expect`, for a value a REFUSAL can stop from existing at all.

    `expect(label, TilesetFile.parse(text).collision, want)` evaluates the
    parse inside the caller's own argument list, so a reader that refuses
    input it is supposed to accept takes the whole file down with a raw
    traceback: no FAIL line, no failure list, and every assertion below it
    never runs. The exit code stays honest, which is why this was not a CI
    hole -- but "which claim broke" was left to whoever reads a stack, and
    one refusal hid the rest of the run.

    Here the raise IS the got, printed in the same column as every other
    result, and the file carries on to the assertions that follow.
    """
    try:
        got = action()
    except Exception as error:                                # noqa: BLE001
        # Flattened, because a PyoneerBlitFormatError carries its `via`
        # context on continuation lines and a multi-line got breaks the
        # column alignment that makes this output scannable.
        got = " ".join(f"{type(error).__name__}: {error}".split())
    expect(label, got, want)


def expect_raises(label, exception, action, *, contains: str = ""):
    """Assert `action` raises, and that the message names the problem.

    The `contains` half matters as much as the raise: a reader that refuses
    a 600-line map without saying which line is a reader nobody will use.
    """
    try:
        action()
    except exception as error:
        text = str(error)
        ok = contains in text
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<56} "
              f"raised={type(error).__name__} says={brief(text)}")
        if not ok:
            failures.append(label)
        return
    except Exception as error:                                # noqa: BLE001
        print(f"  FAIL {label:<56} raised {type(error).__name__}, "
              f"wanted {exception.__name__}")
        failures.append(label)
        return
    print(f"  FAIL {label:<56} did not raise")
    failures.append(label)


# ---------------------------------------------------------------------------
# A fixture map, built here rather than borrowed from data/maps.
#
# Every feature the format claims to carry appears exactly once: each
# property type including the ones that collapse to str, a name with a
# space, a value with padding, a multi-line body value, a flipped gid, every
# object shape, a per-tile property, an animation that must be REPORTED as
# dropped, a group, an image layer, and a spaced/margined tileset.
# ---------------------------------------------------------------------------

FIXTURE_TMX = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.10.2" orientation="orthogonal" renderorder="right-down" compressionlevel="-1" width="3" height="2" tilewidth="16" tileheight="16" infinite="0" nextlayerid="9" nextobjectid="7">
 <properties>
  <property name="theme" value="forest glade"/>
  <property name="difficulty" type="int" value="3"/>
  <property name="gravity" type="float" value="9.8"/>
  <property name="dark" type="bool" value="true"/>
  <property name="tint" type="color" value="#ff0088ff"/>
  <property name="readme" type="file" value="../docs/readme.md"/>
  <property name="two words" value="a  b"/>
  <property name="padded" value=" x "/>
  <property name="blurb">line one
line two</property>
 </properties>
 <editorsettings>
  <export target="out.tmx" format="tmx"/>
 </editorsettings>
 <tileset firstgid="1" name="Fixture" tilewidth="16" tileheight="16" spacing="1" margin="2" tilecount="4" columns="2">
  <image source="../art/fixture.png" width="35" height="35"/>
  <tile id="0" type="wall">
   <properties>
    <property name="solid" type="bool" value="true"/>
   </properties>
  </tile>
  <tile id="1">
   <animation>
    <frame tileid="1" duration="100"/>
   </animation>
  </tile>
 </tileset>
 <group id="7" name="Graphic">
  <layer id="1" name="Floor" width="3" height="2" opacity="0.5" offsetx="8">
   <properties>
    <property name="pyoneer_motion" value="dynamic"/>
    <property name="pyoneer_parallax_x" type="float" value="1.4"/>
    <property name="pyoneer_depth" type="int" value="12"/>
   </properties>
   <data encoding="csv">
1,2,3,
2147483649,0,4
</data>
  </layer>
  <imagelayer id="8" name="Sky" offsetx="4">
   <image source="../art/sky.png"/>
  </imagelayer>
 </group>
 <objectgroup id="2" name="entity">
  <object id="1" name="Hero" type="spawn" x="16" y="32" width="16" height="16">
   <properties>
    <property name="hp" type="int" value="20"/>
   </properties>
  </object>
  <object id="2" gid="3" x="48" y="64"/>
  <object id="3" x="0" y="0" rotation="45" visible="0">
   <polygon points="0,0 16,0 16,16"/>
  </object>
  <object id="4" x="1" y="2">
   <ellipse/>
  </object>
  <object id="5" x="3" y="4">
   <point/>
  </object>
  <object id="6" x="5" y="6" width="80" height="20">
   <text fontfamily="Arial" pixelsize="12" wrap="1">hello world</text>
  </object>
 </objectgroup>
</map>
"""


def fixture_conversion() -> Conversion:
    document = MapDocument.from_bytes(FIXTURE_TMX.encode("utf-8"),
                                      path=os.path.join(ROOT, "fixture.tmx"))
    return from_tmx(document)


# ---------------------------------------------------------------------------
print("the format is canonical: one spelling per model")

fixture = fixture_conversion()
fixture_text = fixture.blitmap.render()

expect_returns("parse(render(map)) is the same model",
               lambda: Blitmap.parse(fixture_text) == fixture.blitmap, True)
expect_returns("render(parse(text)) is the same bytes",
               lambda: Blitmap.parse(fixture_text).render() == fixture_text, True)
expect("the file ends in a newline", fixture_text.endswith("\n"), True)
expect("the first line names the format and a version",
       fixture_text.splitlines()[0], "blitmap 1")

tileset = fixture.tileset("Fixture")
tileset_text = tileset.render()
expect_returns("parse(render(tileset)) is the same model",
               lambda: TilesetFile.parse(tileset_text) == tileset, True)
expect_returns("render(parse(tileset text)) is the same bytes",
               lambda: TilesetFile.parse(tileset_text).render() == tileset_text, True)
expect("a .tileset names itself too", tileset_text.splitlines()[0], "tileset 1")

# The negative control. Every assertion above compares a value-comparing
# frozen type against another one, and a round trip that lost a field would
# still be "equal" if the field never made it into either side. This proves
# the comparison can distinguish two models that differ by ONE cell.
floor = fixture.blitmap.layer("Floor")
mutant_gids = list(floor.gids)
mutant_gids[0] += 1
mutant = TileLayer(floor.id, floor.name, floor.width, floor.height,
                   tuple(mutant_gids), floor.attributes, floor.properties)
expect("one changed gid is a different model", mutant == floor, False)
expect("one changed gid is different bytes",
       mutant.render() == floor.render(), False)
expect("one changed gid moves exactly one line",
       sum(1 for a, b in zip(mutant.render(), floor.render()) if a != b), 1)

# Whitespace is the thing formats lose. These values survive only because
# escape_text guards the ENDS of a value and escape_word guards a name.
padded = Property("two words", "string", " a  b ")
expect_returns("a padded, spaced property survives a round trip",
               lambda: Blitmap.parse(
                   Blitmap(1, 1, 16, 16, properties=(padded,)).render()
               ).properties[0], padded)
newline = Property("blurb", "string", "line one\nline two")
expect_returns("a multi-line property value survives",
               lambda: Blitmap.parse(
                   Blitmap(1, 1, 16, 16, properties=(newline,)).render()
               ).properties[0], newline)

# Round trip through the disk, on the real file-writing path.
scratch = tempfile.mkdtemp(prefix="blitmap_check_")
try:
    written = write_conversion(fixture, os.path.join(scratch, "fixture.blitmap"))
    with open(written[0], "rb") as handle:
        on_disk = handle.read()
    expect("save writes exactly what render produced",
           on_disk, fixture_text.encode("utf-8"))
    expect("no platform newline translation on the way out",
           b"\r\n" in on_disk, False)
    expect_returns("load(save(map)) is the same model",
                   lambda: Blitmap.load(written[0]) == fixture.blitmap, True)
    expect("the tileset landed where the map's link points",
           os.path.relpath(written[1], scratch).replace("\\", "/"),
           fixture.blitmap.tilesets[0].source)
    expect_returns("load(save(tileset)) is the same model",
                   lambda: TilesetFile.load(written[1]) == tileset, True)
finally:
    shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
print("\nthe converter carries every kind of thing a tmx holds")

blit = fixture.blitmap
expect("map geometry", (blit.width, blit.height, blit.tile_width, blit.tile_height),
       (3, 2, 16, 16))
expect("unmodelled map attributes ride along as attr",
       dict(blit.attributes).get("nextlayerid"), "9")
expect("...in document order, first one first",
       blit.attributes[0], ("version", "1.10"))

map_properties = [(p.name, p.type, p.text) for p in blit.properties]
expect("every property type survives with its type intact", map_properties, [
    ("theme", "string", "forest glade"),
    ("difficulty", "int", "3"),
    ("gravity", "float", "9.8"),
    ("dark", "bool", "true"),
    ("tint", "color", "#ff0088ff"),
    ("readme", "file", "../docs/readme.md"),
    ("two words", "string", "a  b"),
    ("padded", "string", " x "),
    ("blurb", "string", "line one\nline two"),
])
# The reason the raw text is stored rather than a Python value: three of
# Tiled's types cast to str, so a round trip through values would rewrite
# type="color" as a plain string and the colour picker would be gone.
expect("a color keeps its type, not just its text",
       [p.type for p in blit.properties if p.name == "tint"], ["color"])
expect("properties still cast on demand",
       [p.value for p in blit.properties
        if p.name in ("difficulty", "gravity", "dark")], [3, 9.8, True])

expect("group nesting is preserved, not flattened",
       blit.layer_names(), ["Graphic", "Floor", "Sky", "entity"])
expect("a group is a group", isinstance(blit.layers[0], LayerGroup), True)
expect("its children hang off it",
       [type(layer).__name__ for layer in blit.layers[0].layers],
       ["TileLayer", "ImageLayer"])

expect("gids come through as FILE gids, flip flags and all",
       floor.gids, (1, 2, 3, 2147483649, 0, 4))
expect("the grid keeps its shape", floor.rows(), [(1, 2, 3), (2147483649, 0, 4)])
expect("a flipped gid still resolves to its tileset",
       blit.tileset_for_gid(2147483649).name, "Fixture")
expect("gid 0 belongs to nobody", blit.tileset_for_gid(0), None)

expect("the pyoneer_ capability vocabulary survives verbatim",
       [(p.name, p.value) for p in floor.properties],
       [(layer_profile.MOTION, "dynamic"),
        (layer_profile.PARALLAX_X, 1.4),
        (layer_profile.DEPTH, 12)])
expect("layer attributes the format does not model ride along",
       floor.attributes, (("opacity", "0.5"), ("offsetx", "8")))

sky = blit.layer("Sky")
expect("an image layer survives", (isinstance(sky, ImageLayer), sky.source),
       (True, "../art/sky.png"))

entity = blit.layer("entity")
expect("every object survives", [o.id for o in entity.objects], [1, 2, 3, 4, 5, 6])
hero = entity.find(1)
expect("object placement and class",
       (hero.name, hero.type, hero.x, hero.y, hero.width, hero.height),
       ("Hero", "spawn", 16.0, 32.0, 16.0, 16.0))
expect("typed object properties",
       [(p.name, p.value) for p in hero.properties], [("hp", 20)])
expect("a tile object keeps its gid", entity.find(2).gid, 3)
expect("rotation and visibility",
       (entity.find(3).rotation, entity.find(3).visible), (45.0, False))
expect("a polygon keeps its points", entity.find(3).shape,
       Shape("polygon", ((0.0, 0.0), (16.0, 0.0), (16.0, 16.0))))
# getattr rather than attribute access: a converter that dropped shapes
# should produce a readable FAIL line, not an AttributeError from the check.
expect("an ellipse is an ellipse",
       getattr(entity.find(4).shape, "kind", None), "ellipse")
expect("a point is a point",
       getattr(entity.find(5).shape, "kind", None), "point")
expect("a text object keeps its body and its font",
       (getattr(entity.find(6).shape, "text", None),
        dict(getattr(entity.find(6).shape, "attributes", ()))),
       ("hello world", {"fontfamily": "Arial", "pixelsize": "12", "wrap": "1"}))

expect("one tileset became one .tileset file",
       [t.name for t in fixture.tilesets], ["Fixture"])
expect("the map links it by firstgid and path",
       fixture.blitmap.tilesets[0],
       TilesetLink(1, "Fixture", "tilesets/Fixture.tileset"))
expect("tileset geometry, margin and spacing included",
       (tileset.image, tileset.image_width, tileset.image_height,
        tileset.tile_width, tileset.tile_height, tileset.margin,
        tileset.spacing, tileset.tile_count, tileset.columns),
       ("../art/fixture.png", 35, 35, 16, 16, 2, 1, 4, 2))
expect("what the image can actually hold is derived separately",
       tileset.measured, (2, 2, 4))
expect("per-tile class and properties survive",
       (tileset.tile(0).type, [(p.name, p.value) for p in tileset.tile(0).properties]),
       ("wall", [("solid", True)]))
expect("the tileset points at a .blitmask only when told to",
       tileset.collision, "")

with_mask = from_tmx(
    MapDocument.from_bytes(FIXTURE_TMX.encode("utf-8"),
                           path=os.path.join(ROOT, "fixture.tmx")),
    collision_for=lambda name: name + ".blitmask")
masked = with_mask.tileset("Fixture")
expect("a supplied .blitmask reference is carried, not parsed",
       masked.collision, "Fixture.blitmask")
# The line above only reads back what from_tmx() handed the constructor, so
# it is true by dataclass construction and survives a render that never
# writes `collision` AND a parse that never reads it. The .blitmask
# reference is the whole engine/editor collision seam; assert the ROUND TRIP.
#
# expect_returns rather than expect, because the two mutations this covers
# fail in two different ways: a render that drops the line comes back as ""
# and a parse that no longer knows the keyword RAISES, and only one of those
# is a comparison. See expect_returns for what the raw raise used to cost.
expect_returns("a .blitmask reference survives render/parse",
               lambda: TilesetFile.parse(masked.render()).collision,
               "Fixture.blitmask")
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    TilesetFile(name="A", tile_width=8, tile_height=8, collision="A.png")
expect("a collision reference that is not a .blitmask says so out loud",
       [w.category.__name__ for w in caught
        if issubclass(w.category, PyoneerContentWarning)],
       ["PyoneerContentWarning"])

# ---------------------------------------------------------------------------
# A tmx that DECLARES its own masks, which is what `map.tileset.mask.set`
# leaves behind the first time an author paints a tile.
#
# Its own fixture rather than a property bolted onto FIXTURE_TMX, because
# FIXTURE_TMX is the "declares nothing" control for every assertion below and
# the two halves of this invariant have to be two different documents. A
# second `<tileset>` declaring nothing sits beside the first, so "carried"
# and "absent" are measured in ONE conversion and a converter that stamped
# every tileset with the same reference could not pass both.
#
# The `license` property is a DECOY and is load-bearing. Measured: with the
# collision property alone, a converter reading the FIRST property rather
# than the NAMED one passed every assertion here -- the check could not tell
# "reads pyoneer_collision" from "reads whatever is first". Its value ends in
# .blitmask on purpose, so "grab anything that looks like a mask" dies too.
MASKED_TMX = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" orientation="orthogonal" width="1" height="1" tilewidth="16" tileheight="16">
 <tileset firstgid="1" name="Painted" tilewidth="16" tileheight="16" tilecount="4" columns="2">
  <properties>
   <property name="license" value="decoy.blitmask"/>
   <property name="%s" value="../art/Painted.blitmask"/>
  </properties>
  <image source="../art/painted.png" width="32" height="32"/>
 </tileset>
 <tileset firstgid="5" name="Plain" tilewidth="16" tileheight="16" tilecount="4" columns="2">
  <image source="../art/plain.png" width="32" height="32"/>
 </tileset>
 <layer id="1" name="A" width="1" height="1"><data encoding="csv">1</data></layer>
</map>
""" % collision_runtime.DEFAULTS_PROPERTY


def masked_conversion(**kwargs) -> Conversion:
    return from_tmx(MapDocument.from_bytes(
        MASKED_TMX.encode("utf-8"),
        path=os.path.join(ROOT, "masked.tmx")), **kwargs)


# The property name is spelled ONCE, in the runtime, and read here from the
# same constant the converter imports. A file-format string retyped in the
# converter would pass a check that retyped it too, and law 8's whole cost is
# that a renamed token looks exactly like the feature working.
expect("the converter reads the runtime's own property name, not a copy",
       blitmap.DEFAULTS_PROPERTY is collision_runtime.DEFAULTS_PROPERTY, True)
expect("and that name is the one an author's .tmx actually spells",
       collision_runtime.DEFAULTS_PROPERTY in MASKED_TMX, True)

declared = masked_conversion()
expect("a tileset's OWN pyoneer_collision reaches the .tileset",
       declared.tileset("Painted").collision, "../art/Painted.blitmask")
# The other half. Without it the assertion above passes for a converter that
# writes a reference onto every tileset it sees.
expect("...and a tileset that declares none still has none",
       declared.tileset("Plain").collision, "")
expect("a map with no masks at all converts with nothing dropped",
       list(declared.dropped), [])

# Both spellings of one fact, and they agree. `collision` is the modelled
# declaration this format's readers consult; the property rides along in the
# passthrough bag like every other tmx property. Populating one and leaving
# the other stale is the divergence this pins.
painted = declared.tileset("Painted")
expect("the modelled line and the carried property say the same thing",
       ([p.value for p in painted.properties
         if p.name == collision_runtime.DEFAULTS_PROPERTY], painted.collision),
       (["../art/Painted.blitmask"], "../art/Painted.blitmask"))

# Round trip, for the reason the injected case round trips: a value handed
# to a constructor is true by construction until it survives render/parse.
expect_returns("a declared reference survives render/parse",
               lambda: TilesetFile.parse(painted.render()).collision,
               "../art/Painted.blitmask")

# The injection is an OVERRIDE, and the two directions are separate claims.
overridden = masked_conversion(collision_for=lambda name: "beside/art.blitmask")
expect("a caller with an answer beats the declaration",
       overridden.tileset("Painted").collision, "beside/art.blitmask")
deferred = masked_conversion(collision_for=lambda name: "")
expect("a caller with nothing to say cannot unpaint the declaration",
       deferred.tileset("Painted").collision, "../art/Painted.blitmask")
expect("...and still adds nothing to a tileset that declared nothing",
       deferred.tileset("Plain").collision, "")

# A tileset declaring an EMPTY pyoneer_collision is a tileset declaring
# nothing -- `map.tileset.mask.restore` removes the property, but a hand
# edit that blanks the value must not become a reference to a file named "".
blank = from_tmx(MapDocument.from_bytes(
    MASKED_TMX.replace("../art/Painted.blitmask", "  ").encode("utf-8"),
    path=os.path.join(ROOT, "masked.tmx")))
expect("a blank declaration is not a reference to a file named ''",
       blank.tileset("Painted").collision, "")

# `declared_collision` reads an element directly, so it is asserted directly
# too: the converter path above cannot distinguish "read the wrong element"
# from "read no element" once both answer "".
masked_root = MapDocument.from_bytes(
    MASKED_TMX.encode("utf-8"),
    path=os.path.join(ROOT, "masked.tmx")).root
tileset_elements = masked_root.findall("tileset")
expect("declared_collision reads the element it is handed",
       [declared_collision(element) for element in tileset_elements],
       ["../art/Painted.blitmask", ""])

# What did NOT survive is a value, not a log line. `<editorsettings>` is
# Tiled's export target -- editor state, not map data -- and a per-tile
# <animation> is real authored data this format does not model yet.
expect("everything dropped is named",
       list(fixture.dropped),
       ["editorsettings", "tileset/Fixture/tile[1]/animation"])
expect("and the conversion says it was incomplete", fixture.complete, False)
expect("a map with nothing to drop says so",
       from_tmx(MapDocument.from_bytes(
           b'<?xml version="1.0" encoding="UTF-8"?>\n'
           b'<map version="1.10" width="1" height="1" tilewidth="8" '
           b'tileheight="8"><layer id="1" name="A" width="1" height="1">'
           b'<data encoding="csv">0</data></layer></map>')).complete, True)


# ---------------------------------------------------------------------------
print("\nfidelity against a copy of the real map")

# A COPY. The author paints in data/maps/test.tmx and nothing here may write
# to it, so the bytes are read once and handed to a document that has never
# heard of the original path.
with open(REAL_MAP, "rb") as handle:
    real_bytes = handle.read()
real_scratch = tempfile.mkdtemp(prefix="blitmap_real_")
real_copy = os.path.join(real_scratch, "test.tmx")
with open(real_copy, "wb") as handle:
    handle.write(real_bytes)

_CSV_TOKEN = re.compile(r"\d+")


def xml_properties(element) -> tuple:
    """Read `<properties>` with a reader that is not the converter's.

    Deliberately a second transcription rather than an import: a census
    built by calling the code under test proves only that the code equals
    itself.
    """
    container = element.find("properties")
    if container is None:
        return ()
    return tuple(
        (entry.get("name", ""), entry.get("type") or "string",
         entry.get("value") if "value" in entry.attrib else (entry.text or ""))
        for entry in container.findall("property"))


def xml_census(element, path=()):
    """(kind, path, id, facts) for every layer in a tmx subtree."""
    rows = []
    for child in element:
        tag = child.tag
        if not isinstance(tag, str):
            continue
        name = child.get("name", "")
        here = path + (name,)
        identifier = int(child.get("id", "0"))
        if tag == "layer":
            data = child.find("data")
            gids = tuple(int(m.group())
                         for m in _CSV_TOKEN.finditer(data.text or ""))
            rows.append(("tiles", here, identifier,
                         (int(child.get("width", "0")), int(child.get("height", "0"))),
                         gids, xml_properties(child)))
        elif tag == "objectgroup":
            objects = tuple(
                (int(o.get("id", "0")), o.get("name", ""),
                 o.get("type") or o.get("class") or "",
                 float(o.get("x", "0")), float(o.get("y", "0")),
                 int(o.get("gid", "0")), xml_properties(o))
                for o in child.findall("object"))
            rows.append(("objects", here, identifier, objects,
                         xml_properties(child)))
        elif tag == "imagelayer":
            image = child.find("image")
            rows.append(("image", here, identifier,
                         "" if image is None else image.get("source", ""),
                         xml_properties(child)))
        elif tag == "group":
            rows.append(("group", here, identifier, xml_properties(child)))
            rows.extend(xml_census(child, here))
    return rows


def model_census(layers, path=()):
    rows = []
    for layer in layers:
        here = path + (layer.name,)
        properties = tuple((p.name, p.type, p.text) for p in layer.properties)
        if isinstance(layer, TileLayer):
            rows.append(("tiles", here, layer.id, (layer.width, layer.height),
                         layer.gids, properties))
        elif isinstance(layer, ObjectLayer):
            objects = tuple((o.id, o.name, o.type, o.x, o.y, o.gid,
                             tuple((p.name, p.type, p.text) for p in o.properties))
                            for o in layer.objects)
            rows.append(("objects", here, layer.id, objects, properties))
        elif isinstance(layer, ImageLayer):
            rows.append(("image", here, layer.id, layer.source, properties))
        else:
            rows.append(("group", here, layer.id, properties))
            rows.extend(model_census(layer.layers, here))
    return rows


real_document = MapDocument.load(real_copy)
real_root = ElementTree.fromstring(real_bytes)

started = time.perf_counter()
real = from_tmx(real_document)
convert_seconds = time.perf_counter() - started

real_text = real.blitmap.render()
# Guarded rather than bare: this is the one parse in the file whose input the
# AUTHOR controls, so a cell the reader will not take back is a plausible
# failure and it must print as a FAIL rather than end the run on line 533.
reparsed = None
refusal = ""
started = time.perf_counter()
try:
    reparsed = Blitmap.parse(real_text)
except PyoneerBlitFormatError as error:
    refusal = " ".join(str(error).split())
parse_seconds = time.perf_counter() - started

print(f"  ..   {'the real map, for scale':<56} "
      f"{len(real_bytes)} tmx bytes -> {len(real_text.encode('utf-8'))} blitmap bytes")
print(f"  ..   {'convert / parse cost':<56} "
      f"{convert_seconds * 1000:.0f} ms / {parse_seconds * 1000:.0f} ms")

expect("the real map's own rendered text reads back", refusal, "")

want_census = xml_census(real_root)
expect("every layer, gid, object and property survives",
       model_census(real.blitmap.layers), want_census)
expect_returns("and survives the trip through the text too",
               lambda: model_census(reparsed.layers), want_census)
expect("the census is not empty", len(want_census) > 0, True)
# The census is compared derived-to-derived, so it holds no matter what the
# author paints. This is the only place the map's own numbers are used, and
# they are used as an INVARIANT (a layer has as many cells as it declares),
# never as a frozen value.
expect("every tile layer holds exactly the cells it declares",
       [row[1] for row in model_census(real.blitmap.layers)
        if row[0] == "tiles" and len(row[4]) != row[3][0] * row[3][1]], [])

expect("tilesets: firstgid, name and link",
       [(link.first_gid, link.name, link.source)
        for link in real.blitmap.tilesets],
       [(int(e.get("firstgid", "0")), e.get("name", ""),
         tileset_reference(e.get("name", "")))
        for e in real_root.findall("tileset")])
expect("one .tileset file per tileset",
       [t.name for t in real.tilesets],
       [e.get("name", "") for e in real_root.findall("tileset")])
expect("each carries its image and its geometry",
       [(t.image, t.image_width, t.image_height, t.tile_width, t.tile_height,
         t.tile_count, t.columns) for t in real.tilesets],
       [(e.find("image").get("source", ""),
         int(e.find("image").get("width", "0")),
         int(e.find("image").get("height", "0")),
         int(e.get("tilewidth", "0")), int(e.get("tileheight", "0")),
         int(e.get("tilecount", "0")), int(e.get("columns", "0")))
        for e in real_root.findall("tileset")])
expect("map size and tile size match the source",
       (real.blitmap.width, real.blitmap.height,
        real.blitmap.tile_width, real.blitmap.tile_height),
       (int(real_root.get("width", "0")), int(real_root.get("height", "0")),
        int(real_root.get("tilewidth", "0")), int(real_root.get("tileheight", "0"))))
expect("every map attribute the format does not model is carried",
       dict(real.blitmap.attributes),
       {k: v for k, v in real_root.attrib.items()
        if k not in ("width", "height", "tilewidth", "tileheight")})
expect("nothing named in the map was dropped",
       [name for name in real.dropped
        if name.split("/")[0] in set(real_document.layer_names())
        | set(real_document.tileset_names())], [])

with open(REAL_MAP, "rb") as handle:
    expect("the reader never touched the author's file", handle.read(), real_bytes)
shutil.rmtree(real_scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
print("\nthe reader refuses what it cannot read exactly")

# One space, not two, and the message is asserted rather than just the
# raise. A lexer that stripped spaces alongside tabs would read this file
# perfectly happily -- and a two-space version would still raise, but for
# the unrelated reason that two spaces read as two levels. An assertion that
# passes whether or not the feature exists is not an assertion.
expect_raises("a space indent is refused, naming the rule",
              PyoneerBlitFormatError,
              lambda: Blitmap.parse("blitmap 1\nsize 1 1\ntilesize 8 8\n"
                                    "tileset 1 A\n source a.tileset\n"),
              contains="tabs only")
expect_raises("...and the message names the line", PyoneerBlitFormatError,
              lambda: Blitmap.parse("blitmap 1\nsize 1 1\ntilesize 8 8\n"
                                    "tileset 1 A\n source a.tileset\n"),
              contains="line 5")
expect_raises("a future version is refused", PyoneerBlitFormatError,
              lambda: Blitmap.parse("blitmap 2\nsize 1 1\ntilesize 8 8\n"),
              contains="version 2")
expect_raises("a foreign magic word is refused", PyoneerBlitFormatError,
              lambda: Blitmap.parse("blitmask 1\nsize 1 1\n"),
              contains="expected 'blitmap'")
expect_raises("an unknown keyword is refused", PyoneerBlitFormatError,
              lambda: Blitmap.parse("blitmap 1\nsize 1 1\ntilesize 8 8\nwibble x\n"),
              contains="wibble")
expect_raises("a duplicated header key is refused", PyoneerBlitFormatError,
              lambda: Blitmap.parse("blitmap 1\nsize 1 1\nsize 2 2\ntilesize 8 8\n"),
              contains="twice")
expect_raises("a missing size line is refused", PyoneerBlitFormatError,
              lambda: Blitmap.parse("blitmap 1\ntilesize 8 8\n"),
              contains="no size line")
expect_raises("an unknown escape is refused", PyoneerBlitFormatError,
              lambda: Blitmap.parse("blitmap 1\nsize 1 1\ntilesize 8 8\n"
                                    "prop string a b\\qc\n"),
              contains="\\q")
expect_raises("a grid that is not the declared size is refused",
              PyoneerBlitFormatError,
              lambda: Blitmap.parse("blitmap 1\nsize 2 1\ntilesize 8 8\n"
                                    "tiles 1 A\n\tsize 2 1\n\tdata\n\t\t1,2,3\n"),
              contains="carries 3")
expect_raises("a negative gid is refused, not silently absolute-valued",
              PyoneerBlitFormatError,
              lambda: TileLayer(1, "A", 2, 1, (1, -5)),
              contains="unsigned")
expect_raises("an over-indented line is refused rather than skipped",
              PyoneerBlitFormatError,
              lambda: Blitmap.parse("blitmap 1\nsize 1 1\ntilesize 8 8\n"
                                    "\tattr a b\n"),
              contains="unexpected indent")
expect_raises("two tilesets cannot share a firstgid", PyoneerBlitFormatError,
              lambda: Blitmap(1, 1, 8, 8,
                              tilesets=(TilesetLink(1, "A"), TilesetLink(1, "B"))),
              contains="firstgid")
expect_raises("an object cannot have two shapes", PyoneerBlitFormatError,
              lambda: Blitmap.parse("blitmap 1\nsize 1 1\ntilesize 8 8\n"
                                    "objects 1 e\n\tobject 1\n\t\tat 0 0\n"
                                    "\t\tpoint\n\t\tellipse\n"),
              contains="two shapes")
expect_raises("an external .tsx is refused rather than guessed at",
              PyoneerBlitFormatError,
              lambda: from_tmx(MapDocument.from_bytes(
                  b'<map version="1.10" width="1" height="1" tilewidth="8" '
                  b'tileheight="8"><tileset firstgid="1" source="other.tsx"/>'
                  b'</map>')),
              contains="EXTERNAL")

# A comment is for humans and has nowhere in the model to live, so it is
# dropped on read. Stated as a check because "round-trips byte-exactly"
# would otherwise be read as covering it.
commented = "blitmap 1\n# a note\nsize 1 1\n\ntilesize 8 8\n"
expect_returns("comments and blank lines read fine and do not come back",
               lambda: Blitmap.parse(commented).render(),
               "blitmap 1\nsize 1 1\ntilesize 8 8\n")


# ---------------------------------------------------------------------------
print("\ninterning decides before it copies")

FAKE = TilesetFile(name="Art", image="../../shared/art/tiles.png",
                   tile_width=16, tile_height=16, image_width=32,
                   image_height=32, tile_count=4, columns=2)
HERE = os.path.join(ROOT, "data", "maps", "tilesets", "Art.tileset")
MANAGED = os.path.join(ROOT, "data", "graphics", "managed")


def plan(*, exists=lambda path: True, same=lambda a, b: False, name=None,
         tileset=FAKE):
    return plan_intern(tileset, tileset_path=HERE, managed_root=MANAGED,
                       exists=exists, same_content=same, name=name)


expect("an image resolves relative to its .tileset, not to the cwd",
       resolve_image(FAKE, HERE),
       os.path.normpath(os.path.join(ROOT, "data", "shared", "art", "tiles.png")))

fresh = plan(exists=lambda path: "shared" in path)
expect("a new image is copied", fresh.action, COPY)
expect("...to the managed directory under its own name",
       os.path.basename(fresh.destination), "tiles.png")
expect("...and the rewritten reference points there from the .tileset",
       fresh.reference, "../../graphics/managed/tiles.png")

expect("a missing image is not copied and not invented",
       plan(exists=lambda path: False).action, MISSING)
expect("an occupied name refuses rather than overwriting art",
       plan(exists=lambda path: True, same=lambda a, b: False).action, OCCUPIED)
expect("an identical file already interned is idempotent, not a collision",
       plan(exists=lambda path: True, same=lambda a, b: True).action, KEEP)
already = TilesetFile(name="Art", image="../../graphics/managed/tiles.png",
                      tile_width=16, tile_height=16)
expect("an image already inside the managed directory is kept in place",
       plan(tileset=already).action, KEEP)
expect("...and needs no copy", plan(tileset=already).copies, False)
expect("a name override sends two same-named images to two files",
       os.path.basename(plan(exists=lambda p: "shared" in p,
                             name="Art_tiles.png").destination),
       "Art_tiles.png")

expect("only a safe plan may rewrite a reference",
       interned(FAKE, fresh).image, fresh.reference)
expect("...and everything else about the tileset is untouched",
       interned(FAKE, fresh).tile_count, FAKE.tile_count)
expect_raises("an occupied plan will not rewrite the reference",
              PyoneerBlitFormatError,
              lambda: interned(FAKE, plan(same=lambda a, b: False)),
              contains="DIFFERENT file")
expect_raises("nor will a missing one", PyoneerBlitFormatError,
              lambda: interned(FAKE, plan(exists=lambda path: False)),
              contains="does not exist")

expect("planning wrote nothing to the managed directory",
       os.path.exists(MANAGED), False)

# One pass over real bytes, in a scratch directory, to prove the plan and the
# copy agree about a file that actually exists.
intern_scratch = tempfile.mkdtemp(prefix="blitmap_intern_")
try:
    # An absolute reference on purpose: the scratch directory can live on a
    # different drive than the repo, which is exactly the case where a
    # relative path cannot be formed at all.
    real_tileset = TilesetFile(name="TileA2", image=REAL_IMAGE,
                               tile_width=16, tile_height=16)
    tileset_path = os.path.join(intern_scratch, "TileA2.tileset")
    managed = os.path.join(intern_scratch, "managed")
    first = plan_intern(real_tileset, tileset_path=tileset_path,
                        managed_root=managed)
    expect("a real image plans as a copy", first.action, COPY)
    expect("the copy happens", apply_intern(first), True)
    expect("...and lands where the plan said",
           os.path.isfile(first.destination), True)
    with open(first.destination, "rb") as copied, open(REAL_IMAGE, "rb") as origin:
        expect("...byte for byte", copied.read(), origin.read())
    second = plan_intern(real_tileset, tileset_path=tileset_path,
                         managed_root=managed)
    expect("interning twice is idempotent", second.action, KEEP)
    expect("...and copies nothing the second time", apply_intern(second), False)
    rewritten = interned(real_tileset, second)
    expect("the tileset now points inside the managed directory",
           rewritten.image, "managed/TileA2.png")
    expect("and that reference resolves to the interned file",
           resolve_image(rewritten, tileset_path), first.destination)
finally:
    shutil.rmtree(intern_scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
print("\nthe format modules stay pure and stay below the engine")

for module in ("scripts/loaders/blitmap.py", "scripts/loaders/tileset_file.py"):
    with open(os.path.join(ROOT, module), "r", encoding="utf-8") as handle:
        body = handle.read()
    banned = [name for name in ("import editor", "from editor", "import pygame",
                                "import pytmx", "PySide6")
              if name in body]
    expect(f"{os.path.basename(module)} imports nothing it must not", banned, [])

expect("neither module pulled a display library in",
       sorted(n for n in ("pygame", "pytmx", "PySide6") if n in sys.modules), [])


# ---------------------------------------------------------------------------
print()
if failures:
    print(f"FAILED ({len(failures)}): {failures}")
    sys.exit(1)
print("ALL BLITMAP CHECKS PASS")
