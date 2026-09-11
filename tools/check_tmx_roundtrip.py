"""Measure the .tmx write path against a deliberately AWKWARD file.

The claim this file exists to test is narrow and load-bearing: a
programmatic edit to a map must produce a MINIMAL DIFF, so a human can keep
editing the same file in Tiled and still read `git diff`. "It produces valid
XML" is not the claim -- ElementTree already does that, and reflows the
whole document doing it.

So everything here compares BYTES -- against `UGLY_TMX`, built in this file:
CRLF throughout, tab indentation for the first elements and spaces for the
rest, `</data>` at column 0, self-closing tags with no space before the
slash, a double-quoted XML declaration. That is the shape Tiled writes and
no pretty-printer reproduces, which is the entire reason `MapDocument`
exists.

It used to measure all of that against `data/maps/test.tmx`, the author's
own canvas, which happened to have every one of those properties. That was
a law-4 violation wearing a coincidence's clothes: the assertions read like
claims about the WRITER and were actually claims about one person's file,
and when the shipped map was replaced by `data/maps/starter.tmx` -- uniform
LF, uniform one-space indent -- a repoint would have DELETED the coverage
silently while still printing `PASS`. The fixture is built here now, so the
awkwardness is guaranteed rather than borrowed.

The shipped map is still read, once, at the end: it must round-trip
byte-exactly too. That assertion pins nothing about what it contains.

    .venv/Scripts/python.exe tools/check_tmx_roundtrip.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import atexit
import os
import struct
from xml.etree import ElementTree
import shutil
import sys
import tempfile
import warnings
import zlib

import pygame

pygame.init()
pygame.display.set_mode((64, 64))

import pytmx

from config.managers.map_data import AssetMapManager, MapData, resolve_map_path
from scripts.core.collision_runtime import SUBCELL, companion_subcell
from scripts.core.errors import PyoneerConfigError
from scripts.core.layer_profile import RESERVED
from scripts.loaders.map_document import (
    MapDocument,
    format_property,
    parse_property,
    subcell_property,
)

SHIPPED_SOURCE = "data/maps/starter.tmx"
SHIPPED_PATH = os.path.join(_bootstrap.REPO_ROOT, *SHIPPED_SOURCE.split("/"))

FIXTURE_WIDTH = FIXTURE_HEIGHT = 100
FIXTURE_TILE = 16
FIXTURE_SHEET = "fixture_sheet.png"


def png_bytes(width: int, height: int) -> bytes:
    """A real, decodable 8-bit RGB PNG -- pytmx has to open this one."""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x40\x80\xc0" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def fixture_csv() -> bytes:
    """One deterministic gid per cell, in Tiled's own csv shape.

    Every gid is in 1..64 so the sheet really holds it, and (3, 4) lands on
    a TWO-DIGIT value on purpose: the minimal-diff section replaces it with
    `777` and asserts the file grew by exactly one byte.
    """
    rows = []
    for y in range(FIXTURE_HEIGHT):
        rows.append(",".join(
            str((x * 7 + y * 13) % 64 + 1) for x in range(FIXTURE_WIDTH)))
    return ("\r\n".join(row + "," for row in rows[:-1])
            + "\r\n" + rows[-1] + "\r\n").encode("ascii")


def build_ugly_tmx() -> bytes:
    """The awkward file, assembled byte by byte.

    Five properties are asserted about it a few lines below, and every one
    of them is written HERE rather than found somewhere: CRLF everywhere,
    a tab-indented `<tileset>`, a space-indented `<layer>`, `</data>` at
    column 0, and a self-closing tag with no space before the slash.
    """
    csv = fixture_csv()
    parts = [
        b'<?xml version="1.0" encoding="UTF-8"?>\r\n',
        b'<map version="1.10" tiledversion="1.11.0" orientation="orthogonal"'
        b' renderorder="right-down" width="%d" height="%d" tilewidth="%d"'
        b' tileheight="%d" infinite="0" nextlayerid="12" nextobjectid="1">\r\n'
        % (FIXTURE_WIDTH, FIXTURE_HEIGHT, FIXTURE_TILE, FIXTURE_TILE),
        b'\t<editorsettings>\r\n',
        b'\t\t<export target="." format="tmx"/>\r\n',
        b'\t</editorsettings>\r\n',
        b'\t<tileset firstgid="1" name="Fixture" tilewidth="%d" tileheight="%d"'
        b' tilecount="64" columns="8">\r\n' % (FIXTURE_TILE, FIXTURE_TILE),
        b'\t\t<image source="%s" width="128" height="128"/>\r\n'
        % FIXTURE_SHEET.encode("ascii"),
        b'\t</tileset>\r\n',
    ]
    for layer_id, name in ((1, b"Floor"), (2, b"Above1")):
        parts += [
            b'  <layer id="%d" name="%s" width="%d" height="%d">\r\n'
            % (layer_id, name, FIXTURE_WIDTH, FIXTURE_HEIGHT),
            b'   <data encoding="csv">\r\n',
            csv,
            b'</data>\r\n',
            b'  </layer>\r\n',
        ]
    parts += [
        b'  <objectgroup id="9" name="entity"/>\r\n',
        b'</map>\r\n',
    ]
    return b"".join(parts)


FIXTURE_DIR = tempfile.mkdtemp(prefix="pyoneer_ugly_tmx_")
atexit.register(shutil.rmtree, FIXTURE_DIR, ignore_errors=True)
MAP_PATH = os.path.join(FIXTURE_DIR, "ugly.tmx")
with open(MAP_PATH, "wb") as _handle:
    _handle.write(build_ugly_tmx())
with open(os.path.join(FIXTURE_DIR, FIXTURE_SHEET), "wb") as _handle:
    _handle.write(png_bytes(128, 128))

failures: list[str] = []


def brief(value) -> str:
    """A repr that will not dump 133KB of csv into the check output."""
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>" if len(value) > 60 else repr(value)
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


ONE_OF_EVERY_KIND = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.10.2" orientation="orthogonal" renderorder="right-down" width="2" height="1" tilewidth="16" tileheight="16" infinite="0" nextlayerid="5" nextobjectid="2">
 <tileset firstgid="1" name="t" tilewidth="16" tileheight="16" tilecount="1" columns="1">
  <image source="t.png" width="16" height="16"/>
 </tileset>
 <layer id="1" name="Floor" width="2" height="1">
  <data encoding="csv">
0,0
</data>
 </layer>
 <objectgroup id="2" name="entity">
  <object id="1" name="hero" type="GamePlayer" x="0" y="0" width="16" height="16"/>
 </objectgroup>
 <imagelayer id="3" name="back">
  <image source="t.png" width="16" height="16"/>
 </imagelayer>
</map>
"""
"""One of every element kind pytmx can build, and nothing else.

Not the section's own fixture and not a shipped map: what the two rows under
it measure is which names PYTMX puts on an element, so the file only has to
contain one of each. A map from `data/` here would be a law-4 claim about
somebody's authoring rather than about the library.
"""


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


def attempt(label, fn, want):
    """`expect`, for a call that must SUCCEED -- it reports, never dies.

    `expect(label, probe.set(...), want)` evaluates its argument before
    the helper is entered, so a guard that wrongly refuses takes the whole
    run down and every section below it loses its coverage. The rows that
    exist to prove a refusal is not refusing everything are exactly the
    rows most likely to raise, so those go through here.
    """
    try:
        got = fn()
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<54} raised {type(exc).__name__}: {exc}")
        failures.append(label)
        return
    expect(label, got, want)


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
with open(SHIPPED_PATH, "rb") as handle:
    SHIPPED = handle.read()

# --------------------------------------------------------------------------
print("the fixture is the awkward case, on purpose")
# --------------------------------------------------------------------------
# NOT a pinned byte count, even now that this file writes the bytes: the
# size was only ever a description of the property under test, which is that
# `to_bytes()` reproduces the file, `save()` writes the same bytes, and a
# revert restores them. Those compare against the REAL bytes.
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
    # Every expectation below is DERIVED from the same file, never named.
    # A check that spells its layers out says nothing about MapDocument,
    # which is the only thing it is here to test. What IS a code claim: the reader returns every
    # layer in document order, descending into groups and counting a group as
    # a layer, and splits tile from object by element tag.
    root = ElementTree.parse(MAP_PATH).getroot()

    def declared(element):
        for child in element:
            if (child.tag in ("layer", "objectgroup", "imagelayer", "group")
                    and child.get("name")):
                yield child.tag, child.get("name")
            if child.tag == "group":
                yield from declared(child)

    in_file = list(declared(root))
    expect("map size matches the <map> element",
           (document.width, document.height),
           (int(root.get("width")), int(root.get("height"))))
    expect("tile size matches the <map> element",
           (document.tile_width, document.tile_height),
           (int(root.get("tilewidth")), int(root.get("tileheight"))))
    expect("layer_names() is every declared layer, in document order",
           document.layer_names(), [name for _tag, name in in_file])
    expect("tile layers only", document.tile_layer_names(),
           [name for tag, name in in_file if tag == "layer"])
    expect("object layers only", document.object_layer_names(),
           [name for tag, name in in_file if tag == "objectgroup"])
    # The derivation must be able to disagree, or the four above are one
    # tautology: a map with no <layer> element at all yields no tile layers.
    expect("...and the same walk finds nothing in a map with no layers",
           list(declared(ElementTree.fromstring("<map></map>"))), [])

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
    expect("the fixture object group is empty", entity.objects(), [])
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
    # The group's OWN indent, read off the file, plus one step. The old form
    # typed three spaces, which was the author's file's answer rather than
    # the writer's rule.
    _before_group = ORIGINAL[:ORIGINAL.index(b'<objectgroup')]
    GROUP_INDENT = _before_group[_before_group.rindex(b"\n") + 1:]
    expect("the added lines use CRLF and indent one step past their group",
           b"\r\n" + GROUP_INDENT + b'  <object id="1"' in with_object, True)
    expect("no lone LF was introduced",
           with_object.count(b"\r\n"), with_object.count(b"\n"))

    expect("remove_object finds it", entity.remove_object(spawned.id), True)
    expect("nextobjectid rolled back", document.root.get("nextobjectid"), "1")
    expect("the round trip is byte identical again", document.to_bytes(), ORIGINAL)
    expect("removing it twice is False, not an exception",
           entity.remove_object(spawned.id), False)

    # --------------------------------------------------------------------
    print()
    print("the attribute door and the property door refuse each other's names")
    # --------------------------------------------------------------------
    # WHY THIS SECTION EXISTS, measured before it was written: a `pyoneer_`
    # name handed to MapObject.set became an XML ATTRIBUTE. The map still
    # loaded, pytmx hung the value on the object as a plain Python attribute,
    # `obj.properties` stayed empty -- and the engine reads `obj.properties`
    # everywhere. A silent no-op wearing a successful write's clothes, which
    # is law 7's failure shape. Then, the moment anyone wrote the real
    # property through the correct door, the SAME name on both sides made
    # pytmx raise and the whole map stop loading: law 1's stated cost,
    # reached through a sanctioned writer.
    #
    # Both of those facts about pytmx are re-measured below rather than
    # asserted, so the refusals cannot quietly become a test of nothing.
    entity = document.object_layer("entity")
    expect("the fixture is back to no objects", entity.objects(), [])
    probe = entity.add_object(name="probe", type="player", x=16, y=16,
                              width=16, height=16,
                              properties={"pyoneer_behaviors": "topdown_move"})

    # -- what the attribute path actually did, in pytmx's own words --------
    # Written with element.set, DELIBERATELY around the model, because
    # building the broken document is the only way to show the guards below
    # guard something real rather than a branch nobody could reach.
    silent_path = os.path.join(os.path.dirname(MAP_PATH), "_check_silent.tmx")
    probe.element.set("pyoneer_script", "greeting")
    document.save(silent_path)
    try:
        seen = list(pytmx.TiledMap(silent_path).get_layer_by_name("entity"))[0]
        expect("a pyoneer_ ATTRIBUTE loads fine and is invisible as a property",
               "pyoneer_script" in seen.properties, False)
        expect("...pytmx hangs it on the object instead, where nothing looks",
               getattr(seen, "pyoneer_script", None), "greeting")
        expect("...while the same name through the property door IS a property",
               "pyoneer_behaviors" in seen.properties, True)
    finally:
        os.remove(silent_path)

    # And the fatal half: the same name on BOTH sides of one element.
    fatal_path = os.path.join(os.path.dirname(MAP_PATH), "_check_fatal.tmx")
    probe.element.set("pyoneer_behaviors", "topdown_move")
    document.save(fatal_path)
    try:
        raises("an attribute shadowing a property makes the map unloadable",
               ValueError, lambda: pytmx.TiledMap(fatal_path))
        # The control. Without it the line above passes against any broken
        # fixture, including one broken for an unrelated reason.
        del probe.element.attrib["pyoneer_behaviors"]
        del probe.element.attrib["pyoneer_script"]
        document.save(fatal_path)
        expect("...and with the attribute gone the same file loads",
               len(list(pytmx.TiledMap(fatal_path).get_layer_by_name("entity"))), 1)
    finally:
        os.remove(fatal_path)

    # -- half one: the three refusals at the attribute door ----------------
    raises_naming("a pyoneer_ name is refused at the attribute door",
                  PyoneerConfigError,
                  lambda: probe.set("pyoneer_script", "greeting"),
                  "pyoneer_script", "object.properties[", "map.object.property.set")
    raises_naming("...including one already carried as a property",
                  PyoneerConfigError,
                  lambda: probe.set("pyoneer_behaviors", "topdown_move"),
                  "pyoneer_behaviors", "object.properties[")
    # A name that is not prefixed at all, so the collision rule is the only
    # thing that can have fired.
    probe.properties["depth"] = 50
    raises_naming("a name already carried as a property is refused too",
                  PyoneerConfigError, lambda: probe.set("depth", 9),
                  "depth", "stops loading")
    if "depth" in probe.properties:          # teardown, not an assertion
        del probe.properties["depth"]
    for bad in ("not a name", "", "1bad", 'quote"inside'):
        raises_naming("an illegal XML attribute name is refused: %r" % (bad,),
                      PyoneerConfigError, lambda b=bad: probe.set(b, 1),
                      "legal XML attribute name")

    # -- half two: a refusal must not have touched the document ------------
    # A guard that raises after mutating the tree is worse than no guard:
    # the caller catches the exception, saves, and ships the bytes anyway.
    pristine = MapDocument.load(MAP_PATH)
    victim = pristine.object_layer("entity").add_object(name="p", x=0, y=0)
    baseline = pristine.to_bytes()
    for bad_key in ("pyoneer_script", "not a name", "1bad"):
        raises("refused, with the document already on the table: %r" % bad_key,
               PyoneerConfigError, lambda b=bad_key: victim.set(b, "x"))
    expect("a refused attribute write leaves the bytes alone",
           pristine.to_bytes(), baseline)
    expect("...and adds nothing to the element's attribute list",
           sorted(victim.element.attrib), ["id", "name", "x", "y"])
    spotless = MapDocument.load(MAP_PATH)
    raises("the property door refuses without touching the document",
           PyoneerConfigError,
           lambda: spotless.properties.__setitem__("orientation", "x"))
    expect("...the document still reports itself unchanged", spotless.changed, False)
    expect("...and still serializes to the original bytes",
           spotless.to_bytes(), ORIGINAL)
    # In memory is not the claim that matters. The claim is that a caller
    # who catches the refusal and saves anyway ships the file it opened.
    refused_path = os.path.join(scratch, "after_refusal.tmx")
    spotless.save(refused_path)
    with open(refused_path, "rb") as handle:
        expect("...and the file it WRITES after a refusal is the one it "
               "loaded", handle.read(), ORIGINAL)

    # -- half three: the legitimate attribute path is untouched ------------
    # Without this, all of the above is satisfied by a method that refuses
    # everything it is handed.
    attempt("a built-in attribute still sets",
            lambda: (probe.set("x", 96), probe.x)[1], 96.0)
    expect("...and reaches the bytes as an attribute",
           b'name="probe" type="player" x="96"' in document.to_bytes(), True)
    for key, value, reader in (("y", 48, "y"), ("width", 32, "width"),
                               ("gid", 7, "gid"), ("name", "renamed", "name"),
                               ("type", "npc", "type"), ("rotation", 90, None),
                               ("visible", 0, None), ("template", "a.tx", None)):
        cast = {"y": float, "width": float, "gid": int}.get(reader, str)
        attempt("set(%r) lands, and the reader agrees" % key,
                lambda k=key, v=value, r=reader, c=cast:
                (probe.set(k, v), getattr(probe, r) if r else c(v))[1],
                cast(value))
        expect("set(%r) wrote an attribute, not a property" % key,
               (key in probe.element.attrib, key in probe.properties), (True, False))
    # A colon and a hyphen are legal XML name characters, so an attribute a
    # future Tiled invents still passes: the rule is the XML grammar, not a
    # whitelist of names somebody has to keep up to date.
    attempt("an unknown but legal name passes through",
            lambda: (probe.set("tiled:some-future.attr", 1),
                     probe.element.attrib.get("tiled:some-future.attr"))[1], "1")
    attempt("the property door still takes the name the other one refused",
            lambda: (probe.properties.__setitem__("pyoneer_script", "greeting"),
                     probe.properties["pyoneer_script"])[1], "greeting")

    # -- half four: the mirror, so neither door can build the collision ----
    # On a THROWAWAY load, not on `document`: if this guard ever stops
    # guarding, the write it lets through poisons the document for every
    # section below, and the run dies somewhere with no relation to the
    # thing that broke. A check whose failure mode is "something else",
    # three hundred lines away, is a check nobody can act on.
    mirror = MapDocument.load(MAP_PATH)
    twin = mirror.object_layer("entity").add_object(name="twin", x=0, y=0)
    raises_naming("a property named after an attribute on the SAME element "
                  "is refused", PyoneerConfigError,
                  lambda: twin.properties.__setitem__("name", "x"),
                  "name", "unloadable", "pyoneer_name")
    raises_naming("...on a tile layer too", PyoneerConfigError,
                  lambda: mirror.tile_layer("Floor")
                  .properties.__setitem__("width", 1),
                  "width", "unloadable")
    raises_naming("...and on the <map> element itself", PyoneerConfigError,
                  lambda: mirror.properties.__setitem__("orientation", "x"),
                  "orientation", "unloadable")
    # Maps written before the attribute door was guarded still exist, and
    # for one of those the advice "prefix it" would say
    # pyoneer_pyoneer_script. So that branch says something else.
    twin.element.set("pyoneer_legacy", "x")
    raises_naming("...and a prefixed attribute is told to go, not to be "
                  "prefixed twice", PyoneerConfigError,
                  lambda: twin.properties.__setitem__("pyoneer_legacy", 1),
                  "Delete that attribute")
    # The refusal cannot be "every property name": these must still land.
    attempt("an ordinary property name still writes",
            lambda: (twin.properties.__setitem__("depth", 50),
                     twin.properties["depth"])[1], 50)
    attempt("...and on a layer as well",
            lambda: (mirror.tile_layer("Floor")
                     .properties.__setitem__("pyoneer_depth", 3),
                     mirror.tile_layer("Floor").properties["pyoneer_depth"])[1], 3)

    # -- half five: the fatal names that are NOT in `attrib` ---------------
    # The residual hole BOTH doors shared until this pass, and the reason the
    # attribute check alone was never enough. pytmx gives an object a default
    # `rotation` and a layer a default `opacity` whether the file writes them
    # or not, and `TiledTileLayer`/`TiledObjectGroup` subclass `list`, so
    # `rotation`, `opacity` and `append` are fatal on elements whose `attrib`
    # holds none of the three -- a guard reading only the element's own
    # attributes sees nothing wrong with any of them. Measured before the
    # guard existed: each one loaded to `ValueError` and took the whole map
    # with it.
    for owner_label, owner, fatal in (
            ("an object", twin, ("rotation", "gid", "properties", "parent")),
            ("a tile layer", mirror.tile_layer("Floor"),
             ("opacity", "offsetx", "append", "index"))):
        for reserved_name in fatal:
            raises_naming(
                "a pytmx name the element does NOT carry as an attribute is "
                "refused on %s: %r" % (owner_label, reserved_name),
                PyoneerConfigError,
                lambda o=owner, n=reserved_name: o.properties.__setitem__(n, 1),
                reserved_name, "unloadable")

    # -- and that set is MEASURED off pytmx, never remembered --------------
    # `RESERVED` was eleven names typed from memory in `editor/core/layers.py`
    # and it was missing `rotation`, `gid` and every list method -- three of
    # the four rows above. It is derived here from the library itself, over a
    # fixture carrying one of every element kind, so a pytmx upgrade that adds
    # an attribute turns THIS row red instead of turning somebody's map
    # unloadable. Its own fixture, and a tiny one: what is under measurement
    # is what pytmx puts on an element, not what any shipped map contains
    # (law 4).
    kinds_root = tempfile.mkdtemp(prefix="pyoneer_reserved_")
    atexit.register(shutil.rmtree, kinds_root, ignore_errors=True)
    kinds_path = os.path.join(kinds_root, "kinds.tmx")
    with open(kinds_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(ONE_OF_EVERY_KIND)
    # The DEFAULT image loader, so nothing opens a file: the names on an
    # element do not depend on whether its art is there, and a check that
    # needed a real PNG here would be measuring the loader instead.
    kinds = pytmx.TiledMap(kinds_path)
    elements = ([kinds] + list(kinds.layers) + list(kinds.tilesets)
                + list(kinds.objects))
    expect("the fixture really carries one of every element kind, or the "
           "two rows below are measuring a short list",
           sorted({type(e).__name__ for e in elements}),
           ["TiledImageLayer", "TiledMap", "TiledObject", "TiledObjectGroup",
            "TiledTileLayer", "TiledTileset"])
    derived = set()
    for element in elements:
        derived |= {n for n in dir(element) if not n.startswith("_")}
    expect("`RESERVED` carries every name pytmx hangs on an element it has "
           "loaded -- derived from the library, not remembered",
           sorted(derived - RESERVED), [])
    expect("...and carries nothing pytmx does not, so it cannot quietly grow "
           "into a refusal of every property name",
           sorted(RESERVED - derived), [])

    # -- and the whole section undoes byte-exactly --------------------------
    expect("removing the probe returns the original bytes",
           (entity.remove_object(probe.id), document.to_bytes())[1], ORIGINAL)

    # --------------------------------------------------------------------
    print()
    print("a 4x sub-cell companion is CREATABLE, and undoes byte-exactly")
    # --------------------------------------------------------------------
    # The dimensions are the point. Before add_layer took them, every layer
    # the editor could create was the map's size, so the format the engine
    # reads -- a companion `subcell` times finer -- could not be written by
    # any editor action at all.
    #
    # Nothing here pins a dimension. It reads width, height and tile size
    # off whatever the file is and asserts the arithmetic against those.
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
    # A synthetic map, not the fixture above: this is about a shape a real tmx
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
    print("growing and renaming a tileset survive the mixed-indent file")
    # --------------------------------------------------------------------
    # Growth rewrites four attribute VALUES and adds no element, so the
    # whitespace question is not "does the indent get computed" -- it is
    # "does anything else move". Measured on the awkward fixture, because
    # that is the one that mixes tab-indented and space-indented blocks and
    # is CRLF throughout, and measured on a tileset THIS SECTION ADDS.
    grower = MapDocument.load(MAP_PATH)
    expect("a fresh load of the fixture round trips",
           grower.to_bytes(), ORIGINAL)

    def placed(doc):
        """Every gid the map places: csv cells and tile objects both, raw."""
        return ({name: doc.tile_layer(name).gids()
                 for name in doc.tile_layer_names()},
                [(element.get("id"), element.get("gid"))
                 for group in doc.root.iter("objectgroup")
                 for element in group.findall("object")])

    BEFORE = placed(grower)
    tile_w, tile_h = grower.tile_width, grower.tile_height
    borrowed = grower.tilesets()[0].image_source
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        added = grower.add_tileset("RoundTripGrowth", borrowed,
                                   image_width=tile_w * 4,
                                   image_height=tile_h * 3)
    ADDED = grower.to_bytes()
    expect("the added tileset is a plain 4x3 grid at the top of the space",
           (added.columns, added.tile_count, added.margin, added.spacing),
           (4, 12, 0, 0))
    expect("and adding it moved no placed gid", placed(grower), BEFORE)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        restore = grower.grow_tileset("RoundTripGrowth",
                                      image_height=tile_h * 6)
    grown = grower.to_bytes()
    expect("the grown sheet holds twice the tiles",
           grower.tileset("RoundTripGrowth").tile_count, 24)
    expect("its stride did not move",
           grower.tileset("RoundTripGrowth").columns, 4)
    expect("NOT ONE PLACED GID MOVED", placed(grower), BEFORE)
    span = diff_span(ADDED, grown)
    element_start = ADDED.index(b'<tileset firstgid="%d" name="RoundTripGrowth"'
                                % added.first_gid)
    expect("the diff is inside the grown element and nowhere else",
           (span is not None and span[0] > element_start,
            span is not None and span[1] < len(ADDED)), (True, True))
    expect("no lone LF was introduced", grown.count(b"\r\n"), grown.count(b"\n"))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        grower.grow_tileset("RoundTripGrowth", image_source=restore["image"],
                            image_width=restore["image_width"],
                            image_height=restore["image_height"],
                            tile_count=restore["tile_count"])
    expect("and the four values it returned put the file back byte for byte",
           grower.to_bytes(), ADDED)

    previous = grower.rename_tileset("RoundTripGrowth", "RoundTripRenamed")
    expect("rename returns the name it replaced", previous, "RoundTripGrowth")
    expect("and moves that attribute and nothing else",
           grower.to_bytes(),
           ADDED.replace(b'name="RoundTripGrowth"', b'name="RoundTripRenamed"'))
    expect("NOT ONE PLACED GID MOVED", placed(grower), BEFORE)
    grower.rename_tileset("RoundTripRenamed", "RoundTripGrowth")
    expect("renaming back is byte identical", grower.to_bytes(), ADDED)

    grower.remove_tileset("RoundTripGrowth")
    expect("and taking the whole tileset out returns the original bytes",
           grower.to_bytes(), ORIGINAL)
    with open(MAP_PATH, "rb") as handle:
        expect("the fixture was never written to", handle.read(), ORIGINAL)

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
    # The one section that has to name a REPO-relative path, because
    # resolving one is the thing under test. It names the shipped map and
    # asserts nothing about its contents.
    expect("resolve_map_path returns an absolute path",
           os.path.isabs(resolve_map_path(SHIPPED_SOURCE)), True)
    expect("and it points at the shipped map",
           os.path.normcase(resolve_map_path(SHIPPED_SOURCE)),
           os.path.normcase(SHIPPED_PATH))
    expect("an already-absolute path is left alone",
           os.path.normcase(resolve_map_path(MAP_PATH)), os.path.normcase(MAP_PATH))

    entry = MapData({"file": SHIPPED_SOURCE, "name": "shipped",
                     "identifier": "shipped"})
    expect("MapData keeps the authored string", entry.source, SHIPPED_SOURCE)
    expect("MapData resolves the file", os.path.isfile(entry.file), True)

    # The path must not depend on where the process happens to be standing,
    # or this raises FileNotFoundError from a different working directory.
    previous_cwd = os.getcwd()
    os.chdir(scratch)
    try:
        manager = AssetMapManager().prepare(
            {"data": [{"file": SHIPPED_SOURCE, "name": "shipped",
                       "identifier": "shipped"}]}
        )
        parsed = manager.load_assets("shipped")
        expect("a map loads from an unrelated working directory",
               (parsed.width > 0, parsed.height > 0), (True, True))
        opened = manager.document("shipped")
        # THE SHIPPED MAP, round-tripped. `starter.tmx` is uniform LF where
        # the fixture above is CRLF, so this is the second spelling of the
        # same contract and the reason a repoint would not have been enough.
        expect("and document() opens the same file byte-faithfully",
               opened.to_bytes(), SHIPPED)
    finally:
        os.chdir(previous_cwd)
finally:
    shutil.rmtree(scratch, ignore_errors=True)

# Neither file may have been touched by any of the above.
with open(MAP_PATH, "rb") as handle:
    expect("the fixture is untouched on disk", handle.read(), ORIGINAL)
with open(SHIPPED_PATH, "rb") as handle:
    expect("data/maps/starter.tmx is untouched on disk", handle.read(), SHIPPED)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
