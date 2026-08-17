"""Measure the .tmx write path against the shipped 133,940-byte map.

The claim this file exists to test is narrow and load-bearing: a
programmatic edit to a map must produce a MINIMAL DIFF, so a human can keep
editing the same file in Tiled and still read `git diff`. "It produces valid
XML" is not the claim -- ElementTree already does that, and reflows the
whole document doing it.

So everything here compares BYTES, against data/maps/test.tmx as it actually
ships (CRLF, tab indentation for the first elements and spaces for the rest,
`</data>` at column 0, self-closing tags with no space before the slash).

    .venv/Scripts/python.exe tools/check_tmx_roundtrip.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import os
import shutil
import sys
import tempfile
import warnings

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

import pytmx

from config.managers.map_data import AssetMapManager, MapData, resolve_map_path
from scripts.core.collision_runtime import SUBCELL, companion_subcell
from scripts.core.errors import PyoneerConfigError
from scripts.loaders.map_document import (
    MapDocument,
    format_property,
    parse_property,
    subcell_property,
)

MAP_PATH = os.path.join(_bootstrap.REPO_ROOT, "data", "maps", "test.tmx")

failures: list[str] = []


def brief(value) -> str:
    """A repr that will not dump 133KB of csv into the check output."""
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>" if len(value) > 60 else repr(value)
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<54} got={brief(got)} want={brief(want)}")
    if not ok:
        failures.append(label)
        if isinstance(got, bytes) and isinstance(want, bytes) and len(want) > 60:
            span = diff_span(want, got)
            if span is not None:
                low, high = span
                print(f"        first diff at byte {low}")
                print(f"        want ...{want[max(0, low - 40):high + 40]!r}...")
                print(f"        got  ...{got[max(0, low - 40):low + 40]!r}...")


def raises(label, exc_type, fn):
    try:
        fn()
    except exc_type as exc:
        print(f"  ok   {label:<54} {type(exc).__name__}")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<54} raised {type(exc).__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<54} did not raise")
    failures.append(label)


def raises_naming(label, exc_type, fn, *needles):
    """It raises, AND the message carries every one of `needles`.

    A refusal that does not name the numbers is a refusal the author has to
    go and measure. `raises` above proves only that something went wrong,
    which is the half of this invariant that was already covered.
    """
    try:
        fn()
    except exc_type as exc:
        missing = [n for n in needles if n not in str(exc)]
        if missing:
            print(f"  FAIL {label:<54} message omits {missing}")
            print(f"        {str(exc).splitlines()[0]}")
            failures.append(label)
            return
        print(f"  ok   {label:<54} {type(exc).__name__}, names {list(needles)}")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<54} raised {type(exc).__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<54} did not raise")
    failures.append(label)


def diff_span(left: bytes, right: bytes) -> tuple[int, int] | None:
    """(first, last_exclusive) differing byte offsets in `left`, or None."""
    if left == right:
        return None
    limit = min(len(left), len(right))
    low = 0
    while low < limit and left[low] == right[low]:
        low += 1
    high_left, high_right = len(left), len(right)
    while high_left > low and high_right > low and left[high_left - 1] == right[high_right - 1]:
        high_left -= 1
        high_right -= 1
    return low, high_left


with open(MAP_PATH, "rb") as handle:
    ORIGINAL = handle.read()

# --------------------------------------------------------------------------
print("the shipped file is the awkward case, on purpose")
# --------------------------------------------------------------------------
# NOT a pinned byte count. The map is a live fixture the author paints in,
# so its size changes whenever they use the editor -- and a stale constant
# here fails loudly while every assertion that actually matters (to_bytes()
# reproduces the file, save() writes the same bytes, revert restores them)
# still passes. Those compare against the REAL bytes, which is the property
# under test; the size was only ever a description of it.
print(f"  ..   {'size on disk':<54} {len(ORIGINAL)} bytes")
expect("big enough to exercise the awkward paths", len(ORIGINAL) > 50_000, True)
expect("CRLF throughout", ORIGINAL.count(b"\r\n"), ORIGINAL.count(b"\n"))
expect("tab-indented early elements", b"\r\n\t<tileset " in ORIGINAL, True)
expect("space-indented later elements", b"\r\n  <layer " in ORIGINAL, True)
expect("</data> sits at column 0", b"\r\n</data>\r\n" in ORIGINAL, True)
expect("self-closing tags have no space", b'format="tmx"/>' in ORIGINAL, True)
expect("double-quoted xml declaration",
       ORIGINAL.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\r\n'), True)

# --------------------------------------------------------------------------
print()
print("load + save with no edits is byte identical")
# --------------------------------------------------------------------------
document = MapDocument.load(MAP_PATH)
expect("to_bytes() reproduces the file exactly", document.to_bytes(), ORIGINAL)
expect("nothing changed", document.changed, False)

scratch = tempfile.mkdtemp(prefix="pyoneer_tmx_")
try:
    copy_path = os.path.join(scratch, "roundtrip.tmx")
    document.save(copy_path)
    with open(copy_path, "rb") as handle:
        written = handle.read()
    expect("save() writes the same bytes", written, ORIGINAL)
    expect("no CRLF doubling on Windows", written.count(b"\r\r"), 0)

    # --------------------------------------------------------------------
    print()
    print("the document reads what Tiled wrote")
    # --------------------------------------------------------------------
    expect("map size", (document.width, document.height), (100, 100))
    expect("tile size", (document.tile_width, document.tile_height), (16, 16))
    expect("layer_names() in document order", document.layer_names(),
           ["Graphic", "Paralax", "Floor", "GroundClutter", "PlayerDepth",
            "Above1", "Foreground", "Entity", "entity"])
    expect("tile layers only", document.tile_layer_names(),
           ["Paralax", "Floor", "GroundClutter", "PlayerDepth", "Above1", "Foreground"])
    expect("object layers only", document.object_layer_names(), ["entity"])

    floor = document.tile_layer("Floor")
    expect("a tile layer holds width*height gids", len(floor), 100 * 100)
    expect("rows() is row-major", len(floor.rows()), 100)
    expect("get_tile agrees with the flat list", floor.get_tile(3, 4),
           floor.gids()[4 * 100 + 3])
    raises("an unknown tile layer names the ones that exist", KeyError,
           lambda: document.tile_layer("NoSuchLayer"))
    raises("an out-of-bounds tile raises", Exception,
           lambda: floor.get_tile(100, 0))

    # --------------------------------------------------------------------
    print()
    print("set_tile rewrites exactly one csv token")
    # --------------------------------------------------------------------
    before = floor.get_tile(3, 4)
    expect("the probe tile is not already the test value", before == 777, False)
    expect("set_tile reports the change", floor.set_tile(3, 4, 777), True)
    edited = document.to_bytes()
    span = diff_span(ORIGINAL, edited)
    expect("something changed", span is not None, True)
    low, high = span
    expect("the changed run is just the old gid", ORIGINAL[low:high], str(before).encode())
    expect("it was replaced by just the new gid", edited[low:high + 1], b"777")
    expect("length grew by exactly the extra digit",
           len(edited) - len(ORIGINAL), len(b"777") - len(str(before).encode()))
    expect("the byte before is a separator", ORIGINAL[low - 1:low] in (b",", b"\n"), True)
    expect("the byte after is a separator", ORIGINAL[high:high + 1] in (b",", b"\r"), True)

    # Nothing else in the whole document moved: every other gid, on every
    # other layer, is untouched.
    reference = MapDocument.load(MAP_PATH)
    drifted = []
    for name in document.tile_layer_names():
        mine = document.tile_layer(name).gids()
        theirs = reference.tile_layer(name).gids()
        if name == "Floor":
            theirs[4 * 100 + 3] = 777
        if mine != theirs:
            drifted.append(name)
    expect("no other gid on any layer moved", drifted, [])
    expect("changed is True while edited", document.changed, True)

    expect("writing the value it already holds is a no-op",
           floor.set_tile(3, 4, 777), False)
    floor.set_tile(3, 4, before)
    expect("reverting restores the original bytes", document.to_bytes(), ORIGINAL)
    expect("changed is False again", document.changed, False)

    # --------------------------------------------------------------------
    print()
    print("fill covers a rect and clips to the layer")
    # --------------------------------------------------------------------
    filled = document.tile_layer("Above1")
    baseline = filled.gids()
    changed = filled.fill((10, 10, 4, 3), 999)
    expect("fill reports how many tiles moved", changed,
           sum(1 for row in range(10, 13) for col in range(10, 14)
               if baseline[row * 100 + col] != 999))
    expect("every tile in the rect is set",
           {filled.get_tile(col, row) for row in range(10, 13) for col in range(10, 14)},
           {999})
    expect("the tile just outside is untouched", filled.get_tile(14, 10), baseline[10 * 100 + 14])
    expect("an over-large rect clips instead of raising",
           filled.fill((98, 98, 50, 50), 999) <= 4, True)
    for index, gid in enumerate(baseline):
        filled.set_tile(index % 100, index // 100, gid)
    expect("undoing the fill restores the original bytes", document.to_bytes(), ORIGINAL)

    # --------------------------------------------------------------------
    print()
    print("add_object then remove_object returns the original bytes")
    # --------------------------------------------------------------------
    entity = document.object_layer("entity")
    expect("the shipped object group is empty", entity.objects(), [])
    expect("and self-closing", b'<objectgroup id="9" name="entity"/>' in ORIGINAL, True)
    expect("nextobjectid before", document.root.get("nextobjectid"), "1")

    spawned = entity.add_object(name="spawn", type="player", x=64, y=32,
                                width=16, height=16,
                                properties={"depth": 50, "solid": True})
    expect("the new object took the declared id", spawned.id, 1)
    expect("nextobjectid advanced", document.root.get("nextobjectid"), "2")
    expect("it is in the layer", [o.id for o in entity.objects()], [1])
    expect("its properties are typed on the way back out",
           spawned.properties.as_dict(), {"depth": 50, "solid": True})

    with_object = document.to_bytes()
    expect("the object serializes in Tiled's attribute order",
           b'<object id="1" name="spawn" type="player" x="64" y="32" width="16" height="16">'
           in with_object, True)
    expect("its properties serialize with types",
           b'<property name="depth" type="int" value="50"/>' in with_object, True)
    expect("the group is no longer self-closing",
           b'<objectgroup id="9" name="entity">' in with_object, True)
    expect("the added lines use CRLF, like the rest of the file",
           b'\r\n   <object id="1"' in with_object, True)
    expect("no lone LF was introduced",
           with_object.count(b"\r\n"), with_object.count(b"\n"))

    expect("remove_object finds it", entity.remove_object(spawned.id), True)
    expect("nextobjectid rolled back", document.root.get("nextobjectid"), "1")
    expect("the round trip is byte identical again", document.to_bytes(), ORIGINAL)
    expect("removing it twice is False, not an exception",
           entity.remove_object(spawned.id), False)

    # --------------------------------------------------------------------
    print()
    print("a 4x sub-cell companion is CREATABLE, and undoes byte-exactly")
    # --------------------------------------------------------------------
    # The dimensions are the point. Before add_layer took them, every layer
    # the editor could create was the map's size, so the format the engine
    # reads -- a companion `subcell` times finer -- could not be written by
    # any editor action at all.
    #
    # Nothing here pins what the map CONTAINS. It reads width, height and
    # tile size off whatever the file is and asserts the arithmetic against
    # those, so repainting test.tmx cannot make this red.
    map_width, map_height = document.width, document.height

    def added(*args, **kwargs):
        """add_layer with the has-no-depth warning silenced. Every probe name
        below is deliberately absent from MAP_DEPTH, that warning is the
        subject of its own assertion elsewhere, and printing it three times
        here would bury the lines that are being measured."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return document.add_layer(*args, **kwargs)

    fine = added("SubcellProbe", "tile", subcell=4)
    expect("the layer is subcell x the map on both axes",
           (fine.width, fine.height), (map_width * 4, map_height * 4))
    expect("its csv holds one gid per cell, not one per map tile",
           len(fine), map_width * 4 * map_height * 4)
    expect("and every one of them is empty", set(fine.gids()), {0})
    expect("the declaration went on the layer, in one command with the size",
           fine.properties.get(SUBCELL), 4)
    expect("written as the file-format string, not a second spelling",
           (SUBCELL, subcell_property()), ("pyoneer_subcell", "pyoneer_subcell"))

    with_fine = document.to_bytes()
    expect("the element declares the same size its csv holds",
           b'name="SubcellProbe" width="%d" height="%d"'
           % (map_width * 4, map_height * 4) in with_fine, True)
    expect("the property serializes as a typed int Tiled will show",
           b'<property name="pyoneer_subcell" type="int" value="4"/>'
           in with_fine, True)
    expect("no lone LF was introduced by a 160,000-cell payload",
           with_fine.count(b"\r\n"), with_fine.count(b"\n"))

    # The ENGINE's own reader, on the document the WRITER just produced.
    # This is the half that a check asserting only "width == 400" cannot
    # reach: the two sides agreeing is the whole feature.
    expect("the engine reads the factor back off it",
           companion_subcell(document, "SubcellProbe"), 4)

    expect("remove_layer takes it out", document.remove_layer("SubcellProbe"), True)
    expect("and a 4x layer round trips to the original bytes",
           document.to_bytes(), ORIGINAL)

    print()
    print("...and every way of asking for one that cannot load is refused")
    # BOTH HALVES. The three above prove it lets a good one through; these
    # prove it stops the bad ones, and that the document is untouched after
    # each refusal -- a half-written companion is a map that raises at load,
    # with nothing for the author to undo.
    raises_naming(
        "explicit dimensions that contradict the factor", PyoneerConfigError,
        lambda: added("Bad", "tile", subcell=4,
                                   width=map_width * 2, height=map_height * 2),
        "pyoneer_subcell=4", f"{map_width * 2}x{map_height * 2}",
        f"{map_width * 4}x{map_height * 4}")
    expect("the refused layer left no trace",
           ("Bad" in document.layer_names(), document.to_bytes() == ORIGINAL),
           (False, True))
    raises_naming(
        "a factor the tile size does not divide", PyoneerConfigError,
        lambda: added("Bad", "tile", subcell=3),
        "pyoneer_subcell=3", f"{document.tile_width}x{document.tile_height}px")
    expect("that one rolled the layer back out too",
           ("Bad" in document.layer_names(), document.to_bytes() == ORIGINAL),
           (False, True))
    raises_naming("a factor below 1", PyoneerConfigError,
                  lambda: added("Bad", "tile", subcell=0),
                  "pyoneer_subcell=0")
    raises_naming("a zero-width layer", PyoneerConfigError,
                  lambda: added("Bad", "tile", width=0),
                  "0x%d" % map_height)
    raises_naming("dimensions on an object layer", PyoneerConfigError,
                  lambda: added("Bad", "object", width=8),
                  "pyoneer_subcell", "object layer")
    expect("the document is still byte-identical after all five refusals",
           document.to_bytes(), ORIGINAL)

    print()
    print("explicit dimensions, with no factor declared at all")
    plain = added("PlainProbe", "tile", width=7, height=3)
    expect("a layer may be any size the caller names",
           (plain.width, plain.height, len(plain)), (7, 3, 21))
    expect("and declares nothing it was not asked to",
           plain.properties.as_dict(), {})
    document.remove_layer("PlainProbe")
    expect("it also comes back byte-identically", document.to_bytes(), ORIGINAL)

    default = added("DefaultProbe", "tile")
    expect("omitting them is still exactly the map's size",
           (default.width, default.height), (map_width, map_height))
    document.remove_layer("DefaultProbe")
    expect("unchanged behaviour for every caller that predates this",
           document.to_bytes(), ORIGINAL)

    # --------------------------------------------------------------------
    print()
    print("a shrunken companion is caught at LOAD, not walked through")
    # --------------------------------------------------------------------
    # A synthetic map, not test.tmx: this is about a shape the author's tmx
    # does not have and must never silently acquire. A finite map's layer
    # width/height are spec'd to equal the map's, so Tiled MAY rewrite a 4x
    # companion back to map size on the next save. Nobody has been able to
    # run Tiled to find out. So the case is detected rather than resolved.
    def tiny_map(layer_width: int, layer_height: int,
                 declare: str | None) -> bytes:
        """A 4x4 map at 16px whose one layer is `layer_width` x
        `layer_height` and declares `declare`, or nothing.

        Hand-built rather than produced by `add_layer`, on purpose: this
        section is about a file the ENGINE meets, and generating it with the
        writer under test would only prove the writer agrees with itself.
        """
        rows = ",\n".join(
            ",".join("0" for _ in range(layer_width))
            + ("," if y < layer_height - 1 else "")
            for y in range(layer_height))
        declaration = (
            b'  <properties>\n'
            b'   <property name="pyoneer_subcell" type="int" value="%s"/>\n'
            b'  </properties>\n' % declare.encode()) if declare else b""
        return (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<map version="1.10" width="4" height="4" tilewidth="16"'
            b' tileheight="16" infinite="0" nextlayerid="3" nextobjectid="1">\n'
            b' <layer id="1" name="FloorCollision" width="%d" height="%d">\n'
            b'%s'
            b'  <data encoding="csv">\n%s\n</data>\n'
            b' </layer>\n'
            b'</map>\n' % (layer_width, layer_height, declaration,
                           rows.encode()))

    shrunken = MapDocument.from_bytes(tiny_map(4, 4, "4"))
    raises_naming(
        "a 4x companion resized to the map's size raises", PyoneerConfigError,
        lambda: companion_subcell(shrunken, "FloorCollision"),
        "pyoneer_subcell=4", "4x4", "16x16", "240", "TILED")

    # The other half, and the reason this warns instead of raising for every
    # small companion: part of a map authored at 4x is a real shape, already
    # supported, and reads NO_DATA past its edge.
    partial = MapDocument.from_bytes(tiny_map(8, 8, "4"))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        expect("a companion smaller than 4x the map is still legal",
               companion_subcell(partial, "FloorCollision"), 4)
    expect("but it says how many sub-cells have no mask",
           [w for w in caught if "192 of 256" in str(w.message)] != [], True)

    exact = MapDocument.from_bytes(tiny_map(16, 16, "4"))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        expect("a correctly sized 4x companion loads",
               companion_subcell(exact, "FloorCollision"), 4)
    expect("and says nothing at all about it", list(caught), [])

    undeclared = MapDocument.from_bytes(tiny_map(4, 4, None))
    expect("a map-sized companion declaring nothing is still 1x, silently",
           companion_subcell(undeclared, "FloorCollision"), 1)

    # --------------------------------------------------------------------
    print()
    print("a saved file still parses in pytmx")
    # --------------------------------------------------------------------
    spawn_path = os.path.join(scratch, "spawned.tmx")
    # pytmx resolves <image source="../graphics/..."> relative to the .tmx,
    # so the copy has to live where the original did.
    live_path = os.path.join(os.path.dirname(MAP_PATH), "_check_roundtrip.tmx")
    document.tile_layer("Floor").set_tile(7, 3, 66)
    document.object_layer("entity").add_object(
        name="spawn", type="player", x=64, y=32, width=16, height=16,
        properties={"depth": 50, "solid": True, "scale": 1.5, "label": "hut"})
    document.save(live_path)
    try:
        reparsed = pytmx.TiledMap(live_path)
        expect("pytmx accepts the written file", reparsed.width, 100)
        # pytmx re-numbers gids internally, so the comparison has to go
        # through map_gid rather than assuming 66 stays 66. layer.data is
        # indexed [y][x]; the probe is asymmetric so a transposed read
        # would fail rather than pass by luck.
        floor_data = reparsed.get_layer_by_name("Floor").data
        expect("pytmx sees the edited tile", floor_data[3][7], reparsed.map_gid(66)[0][0])
        objects = list(reparsed.get_layer_by_name("entity"))
        expect("pytmx sees the added object", len(objects), 1)
        expect("pytmx reads its name", objects[0].name, "spawn")
        expect("pytmx reads its position", (objects[0].x, objects[0].y), (64.0, 32.0))

        # The type attributes MapDocument writes are the ones pytmx reads,
        # so the two sides agree without either importing the other. That
        # agreement is the whole point of emitting type= at all: drop it and
        # `depth` comes back as the string '50' on the spawn path.
        written_properties = objects[0].properties
        expect("pytmx and MapDocument agree on the property values",
               {k: written_properties[k] for k in ("depth", "solid", "scale", "label")},
               {"depth": 50, "solid": True, "scale": 1.5, "label": "hut"})
        expect("MapDocument reads back what it wrote",
               MapDocument.load(live_path).object_layer("entity")
               .objects()[0].properties.as_dict(),
               {"depth": 50, "solid": True, "scale": 1.5, "label": "hut"})
        expect("an untyped property really would be a string",
               parse_property(None, "50"), "50")
    finally:
        os.remove(live_path)
        document.save(spawn_path)

    # --------------------------------------------------------------------
    print()
    print("property type inference, both directions")
    # --------------------------------------------------------------------
    expect("int", parse_property("int", "50"), 50)
    expect("float", parse_property("float", "1.5"), 1.5)
    expect("bool true", parse_property("bool", "true"), True)
    expect("bool false", parse_property("bool", "false"), False)
    expect("object reference is an int", parse_property("object", "7"), 7)
    expect("colour stays a string", parse_property("color", "#ff00ff00"), "#ff00ff00")
    expect("file stays a string", parse_property("file", "../a.png"), "../a.png")
    expect("no type means string", parse_property(None, "50"), "50")
    expect("bool is checked before int", format_property(True), ("bool", "true"))
    expect("int writes type=int", format_property(50), ("int", "50"))
    expect("float writes type=float", format_property(1.5), ("float", "1.5"))
    expect("str writes no type at all", format_property("50"), (None, "50"))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        expect("an unparseable typed value falls back to the string",
               parse_property("int", "fifty"), "fifty")
        expect("and warns rather than dying", len(caught), 1)

    # --------------------------------------------------------------------
    print()
    print("properties on a synthetic document, including the odd forms")
    # --------------------------------------------------------------------
    synthetic = (
        b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
        b'<map version="1.2" width="1" height="1" nextobjectid="1">\r\n'
        b' <properties>\r\n'
        b'  <property name="depth" type="int" value="50"/>\r\n'
        b'  <property name="solid" type="bool" value="true"/>\r\n'
        b'  <property name="gravity" type="float" value="9.8"/>\r\n'
        b'  <property name="title" value="Test &amp; Map"/>\r\n'
        b'  <property name="notes">line one\r\nline two</property>\r\n'
        b' </properties>\r\n'
        b'</map>\r\n'
    )
    document2 = MapDocument.from_bytes(synthetic)
    expect("synthetic round trip is byte identical", document2.to_bytes(), synthetic)
    props = document2.properties
    expect("int property", props["depth"], 50)
    expect("bool property", props["solid"], True)
    expect("float property", props["gravity"], 9.8)
    expect("entity-escaped string", props["title"], "Test & Map")
    expect("body-text property", props["notes"], "line one\nline two")
    expect("membership", "depth" in props, True)
    expect("missing key membership", "nope" in props, False)
    expect("get() default", props.get("nope", 7), 7)
    raises("a missing property raises a KeyError", KeyError, lambda: props["nope"])
    expect("as_dict has every key", sorted(props.keys()),
           ["depth", "gravity", "notes", "solid", "title"])

    props["depth"] = 51
    expect("writing keeps the type attribute",
           b'<property name="depth" type="int" value="51"/>' in document2.to_bytes(), True)
    props["depth"] = 50
    props["notes"] = "line one\nline two"
    expect("a body-text property rewritten as an attribute still reads back",
           MapDocument.from_bytes(document2.to_bytes()).properties["notes"],
           "line one\nline two")
    expect("the newline survives as a character reference",
           b"&#10;" in document2.to_bytes(), True)

    document3 = MapDocument.from_bytes(synthetic)
    document3.properties["spawned"] = 3
    document3.properties["flag"] = False
    body = document3.to_bytes()
    expect("new properties are indented like their siblings",
           b'\r\n  <property name="spawned" type="int" value="3"/>' in body, True)
    expect("bool writes true/false, not True/False",
           b'<property name="flag" type="bool" value="false"/>' in body, True)
    del document3.properties["spawned"]
    del document3.properties["flag"]
    expect("deleting them restores the original bytes", document3.to_bytes(), synthetic)

    # --------------------------------------------------------------------
    print()
    print("unsupported layer encodings raise instead of mangling the file")
    # --------------------------------------------------------------------
    base64_map = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<map version="1.2" width="1" height="1">\n'
        b' <layer id="1" name="B64" width="1" height="1">\n'
        b'  <data encoding="base64" compression="zlib">eJxjYGBgAAAABAAB</data>\n'
        b' </layer>\n'
        b'</map>\n'
    )
    document4 = MapDocument.from_bytes(base64_map)
    expect("a base64 map still round trips untouched", document4.to_bytes(), base64_map)
    raises("but reading its tiles refuses", Exception,
           lambda: document4.tile_layer("B64"))

    lf_map = synthetic.replace(b"\r\n", b"\n")
    expect("an LF file stays LF", MapDocument.from_bytes(lf_map).to_bytes(), lf_map)

    # --------------------------------------------------------------------
    print()
    print("map paths resolve from the repo, not the working directory")
    # --------------------------------------------------------------------
    expect("resolve_map_path returns an absolute path",
           os.path.isabs(resolve_map_path("data/maps/test.tmx")), True)
    expect("and it points at the shipped map",
           os.path.normcase(resolve_map_path("data/maps/test.tmx")),
           os.path.normcase(MAP_PATH))
    expect("an already-absolute path is left alone",
           os.path.normcase(resolve_map_path(MAP_PATH)), os.path.normcase(MAP_PATH))

    entry = MapData({"file": "data/maps/test.tmx", "name": "test", "identifier": "test"})
    expect("MapData keeps the authored string", entry.source, "data/maps/test.tmx")
    expect("MapData resolves the file", os.path.isfile(entry.file), True)

    # The actual regression: this used to raise FileNotFoundError purely
    # because of where the process happened to be standing.
    previous_cwd = os.getcwd()
    os.chdir(scratch)
    try:
        manager = AssetMapManager().prepare(
            {"data": [{"file": "data/maps/test.tmx", "name": "test", "identifier": "test"}]}
        )
        parsed = manager.load_assets("test")
        expect("a map loads from an unrelated working directory",
               (parsed.width, parsed.height), (100, 100))
        opened = manager.document("test")
        expect("and document() opens the same file byte-faithfully",
               opened.to_bytes(), ORIGINAL)
    finally:
        os.chdir(previous_cwd)
finally:
    shutil.rmtree(scratch, ignore_errors=True)

# The shipped map must not have been touched by any of the above.
with open(MAP_PATH, "rb") as handle:
    expect("data/maps/test.tmx is untouched on disk", handle.read(), ORIGINAL)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
