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
from pytmx.pytmx import convert_to_bool
from pytmx.pytmx import prop_type as PYTMX_PROP_TYPE
from pytmx.pytmx import types as _pytmx_types
# A COPY, TAKEN BEFORE ANYTHING LOADS A MAP. `types` is a defaultdict
# and pytmx SUBSCRIPTS it for every attribute it meets, so the live
# table grows a `str` row for `pyoneer_behaviors` the first time a
# fixture is parsed -- and a derivation read off it later would be
# reading this check's own footprints instead of pytmx's declaration.
PYTMX_TYPES = dict(_pytmx_types)

# NAMING THE SAME TUPLE RATHER THAN RETYPING IT. `map.object.unset` is the
# only door in the editor that removes an XML attribute, and the attribute
# ORDER it disturbs is this module's problem, so the loop that proves the
# repair has to be driven by the editor's own declared vocabulary. Spelled
# again here it would cover nine names on the day it was written and five on
# the day somebody added two -- which is the exact shape the defect shipped
# in. This is a tools/ module, so law 2 does not bind it; `scripts/` still
# imports nothing from `editor/`, which the rows in check_blitmap measure.
from editor.core.verbs import _OBJECT_ATTRIBUTES
from config.managers.map_data import AssetMapManager, MapData, resolve_map_path
from scripts.core.collision_runtime import SUBCELL, companion_subcell
from scripts.core.errors import PyoneerConfigError
from scripts.core.layer_profile import (ATTRIBUTE_TEXT, PROPERTY_TEXT,
                                       RESERVED, text_reads_back)
from scripts.loaders.map_document import (
    MapDocument,
    format_property,
    parse_property,
    subcell_property,
)

SHIPPED_SOURCE = "data/maps/starter.tmx"
SHIPPED_PATH = os.path.join(_bootstrap.REPO_ROOT, *SHIPPED_SOURCE.split("/"))
# Spelled once, because a literal escape inside a byte string is the one
# thing a patch tool reliably mangles.
CRLF = b"\r\n"

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
    print("the raw-XML door refuses what the other two doors refuse")
    # --------------------------------------------------------------------
    # THE THIRD DOOR, and until this pass the only one still open. The two
    # halves above guard ONE NAME AT A TIME, at the moment a caller writes it.
    # `restore_object`, `restore_layer` and `restore_tileset` take a whole
    # ELEMENT as text and hang its attributes on the document verbatim, so a
    # `pyoneer_` name inside the payload walked past every refusal above --
    # measured on the shipped verb: the attribute reached the file, pytmx
    # loaded the map, and `obj.properties` came back `{}`. It matters more
    # than the other doors because `map.object.restore` is reachable from a
    # script and from the relay, which is the AI edit path this editor's whole
    # design treats as equal to a human's.
    #
    # Every verb below is measured in BOTH directions: the legal payload
    # restores and comes back byte-exactly, the smuggled one is refused NAMING
    # the attribute, and the bytes after a refusal are the bytes before it.
    #
    # The pytmx facts these refusals rest on are measured in the section
    # above, on `probe`, rather than restated here.

    # -- the door is ONE door, which is the half that keeps it shut --------
    # The recurring defect in this tree is a guard that lands on one route
    # while its siblings grow without it, so the guard is at the parse and
    # every restore verb comes through it. These two rows are the tripwire: a
    # fourth restore verb that calls `fromstring` itself, or an
    # `attrib = dict(parsed.attrib)` with no parse door in front of it, turns
    # them red instead of quietly reopening the hole.
    with open(os.path.join(_bootstrap.REPO_ROOT, "scripts", "loaders",
                           "map_document.py"), encoding="utf-8") as handle:
        module_source = handle.read()
    expect("`fromstring` appears twice in the whole module -- the parse door "
           "and MapDocument.load, which reads a file rather than text",
           module_source.count("ElementTree.fromstring("), 2)
    expect("...and every element hung on the document verbatim came through "
           "that door: one call site per `attrib = dict(parsed.attrib)`",
           module_source.count("_parse_restored_element(") - 1,
           module_source.count("attrib = dict(parsed.attrib)"))

    # -- restore_object ----------------------------------------------------
    doors = MapDocument.load(MAP_PATH)
    group = doors.object_layer("entity")
    made = group.add_object(name="door", type="GamePlayer", x=32, y=32,
                            width=16, height=16,
                            properties={"pyoneer_script": "greeting"})
    WITH_OBJECT = doors.to_bytes()
    # `next_object_id` is carried the way `map.object.remove` carries it:
    # remove_object rolls nextobjectid back down, and an inverse that puts
    # the element back but not the counter is not an inverse.
    payload_xml = group.serialize_object(made.id)
    payload_index = group.object_index(made.id)
    payload_next = doors.root.get("nextobjectid", "1")
    group.remove_object(made.id)
    WITHOUT_OBJECT = doors.to_bytes()
    attempt("serialize + remove + restore_object is byte-exact",
            lambda: (group.restore_object(payload_xml, payload_index),
                     doors.root.set("nextobjectid", payload_next),
                     doors.to_bytes())[2], WITH_OBJECT)
    expect("...and taking it out again returns the other bytes",
           (group.remove_object(made.id), doors.to_bytes())[1], WITHOUT_OBJECT)

    SMUGGLED_OBJECT = ('<object id="%d" name="door" x="32" y="32" width="16" '
                       'height="16" pyoneer_script="smuggled"/>' % made.id)
    raises_naming("a pyoneer_ ATTRIBUTE in the payload is refused, named",
                  PyoneerConfigError,
                  lambda: group.restore_object(SMUGGLED_OBJECT, payload_index),
                  "pyoneer_script", "ATTRIBUTE", "<property name=")
    # A name pytmx puts on every object whether the file writes it or not, so
    # the element's own `attrib` cannot see the collision coming -- the same
    # residual hole the property door closed with RESERVED.
    RESERVED_PROPERTY = ('<object id="%d" x="32" y="32"><properties>'
                         '<property name="rotation" value="90"/>'
                         '</properties></object>' % made.id)
    raises_naming("...so is a <property> named after a pytmx name the element "
                  "does not carry", PyoneerConfigError,
                  lambda: group.restore_object(RESERVED_PROPERTY, payload_index),
                  "rotation", "unloadable")
    # Neither prefixed nor reserved: the ONLY rule that can fire here is the
    # collision read off the element itself, so this row is what proves the
    # guard is more than a RESERVED lookup.
    SHADOWED = ('<object id="%d" x="32" y="32" tint="red"><properties>'
                '<property name="tint" value="blue"/></properties></object>'
                % made.id)
    raises_naming("...and a <property> shadowing an attribute on the SAME "
                  "element", PyoneerConfigError,
                  lambda: group.restore_object(SHADOWED, payload_index),
                  "tint", "unloadable")
    expect("three refusals, and the document is the one they started from",
           doors.to_bytes(), WITHOUT_OBJECT)
    expect("...with nothing appended to the layer either",
           len(group.objects()), 0)

    # The refusal cannot be "refuse every payload". A RESERVED name used as an
    # ATTRIBUTE is what Tiled writes on every rotated object, and refusing it
    # would make undo impossible for exactly the elements serialize_object
    # exists to carry.
    ROTATED = ('<object id="%d" name="door" x="32" y="32" width="16" '
               'height="16" rotation="90" visible="0"/>' % made.id)
    attempt("a RESERVED name as an ATTRIBUTE still restores",
            lambda: (group.restore_object(ROTATED, payload_index).element
                     .get("rotation")), "90")
    expect("...and it undoes byte-exactly too",
           (group.remove_object(made.id), doors.to_bytes())[1], WITHOUT_OBJECT)

    # -- restore_layer: the same guard, reached through a different verb ----
    # And through a CHILD, not the payload's own element: a layer carries its
    # objects, so a name smuggled one level down is the same defect wearing a
    # parent. A guard that read only `parsed.attrib` would pass this.
    layer_payload = doors.serialize_layer("Above1")
    doors.remove_layer("Above1")
    WITHOUT_LAYER = doors.to_bytes()
    raises_naming("restore_layer refuses a pyoneer_ attribute on a CHILD of "
                  "the payload", PyoneerConfigError,
                  lambda: doors.restore_layer(
                      dict(layer_payload,
                           xml='<objectgroup id="9" name="smuggler">'
                               '<object id="1" pyoneer_actor="ghost"/>'
                               '</objectgroup>')),
                  "pyoneer_actor", "ATTRIBUTE")
    raises_naming("...and a RESERVED <property> on the layer itself",
                  PyoneerConfigError,
                  lambda: doors.restore_layer(
                      dict(layer_payload,
                           xml='<objectgroup id="9" name="smuggler">'
                               '<properties><property name="opacity" '
                               'value="1"/></properties></objectgroup>')),
                  "opacity", "unloadable")
    expect("both refusals left the document where it was",
           doors.to_bytes(), WITHOUT_LAYER)
    attempt("and the real payload still restores byte-exactly",
            lambda: (doors.restore_layer(layer_payload),
                     doors.to_bytes())[1], WITHOUT_OBJECT)

    # -- restore_tileset: on one nothing places, so it can come out --------
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        doors.add_tileset("RestoreDoor", doors.tilesets()[0].image_source,
                          image_width=FIXTURE_TILE * 4,
                          image_height=FIXTURE_TILE * 3)
    WITH_TILESET = doors.to_bytes()
    tileset_payload = doors.serialize_tileset("RestoreDoor")
    doors.remove_tileset("RestoreDoor")
    WITHOUT_TILESET = doors.to_bytes()
    raises_naming("restore_tileset refuses a pyoneer_ attribute on a <tile> "
                  "child", PyoneerConfigError,
                  lambda: doors.restore_tileset(
                      dict(tileset_payload,
                           xml='<tileset firstgid="65" name="RestoreDoor">'
                               '<tile id="0" pyoneer_solid="1"/></tileset>')),
                  "pyoneer_solid", "ATTRIBUTE")
    raises_naming("...and a RESERVED <property> on the <tileset> itself",
                  PyoneerConfigError,
                  lambda: doors.restore_tileset(
                      dict(tileset_payload,
                           xml='<tileset firstgid="65" name="RestoreDoor">'
                               '<properties><property name="columns" '
                               'value="4"/></properties></tileset>')),
                  "columns", "unloadable")
    expect("both refusals left the document where it was",
           doors.to_bytes(), WITHOUT_TILESET)
    # A `<tile>`'s own `<properties>` are NOT subject to the collision rule:
    # pytmx merges a tile's attributes and its properties into one dict and
    # checks neither against the other, so refusing this would refuse a
    # legitimate payload. The rule is where pytmx's failure modes are, and
    # this row is the edge of it.
    attempt("a RESERVED <property> on a <tile> child is accepted, because "
            "pytmx never checks one",
            lambda: doors.restore_tileset(
                dict(tileset_payload,
                     xml='<tileset firstgid="65" name="RestoreDoor" '
                         'tilewidth="16" tileheight="16" tilecount="12" '
                         'columns="4"><tile id="0"><properties>'
                         '<property name="width" value="9"/>'
                         '</properties></tile></tileset>')),
            "RestoreDoor")
    doors.remove_tileset("RestoreDoor")
    expect("...and that one came back out cleanly",
           doors.to_bytes(), WITHOUT_TILESET)
    attempt("and the real payload restores byte-exactly",
            lambda: (doors.restore_tileset(tileset_payload),
                     doors.to_bytes())[1], WITH_TILESET)

    # -- the refusal survives the round trip a caller actually makes -------
    # In memory is not the claim that matters: a caller who catches the
    # refusal and saves anyway must ship the file it opened.
    refused_restore = MapDocument.load(MAP_PATH)
    refused_group = refused_restore.object_layer("entity")
    raises("the raw-XML door refuses without touching the document",
           PyoneerConfigError,
           lambda: refused_group.restore_object(SMUGGLED_OBJECT, 0))
    expect("...the document still reports itself unchanged",
           refused_restore.changed, False)
    smuggle_path = os.path.join(scratch, "after_smuggle.tmx")
    refused_restore.save(smuggle_path)
    with open(smuggle_path, "rb") as handle:
        expect("...and the file it WRITES after the refusal is the one it "
               "loaded", handle.read(), ORIGINAL)

    # -- the tag and parse refusals the door inherited still land ----------
    raises_naming("restore_object still refuses a non-<object>",
                  PyoneerConfigError,
                  lambda: refused_group.restore_object("<layer/>", 0),
                  "expects an <object>")
    raises_naming("restore_layer still refuses a non-layer", PyoneerConfigError,
                  lambda: refused_restore.restore_layer({"xml": "<tileset/>"}),
                  "expects a layer element")
    raises_naming("restore_tileset still refuses a non-<tileset>",
                  PyoneerConfigError,
                  lambda: refused_restore.restore_tileset({"xml": "<layer/>"}),
                  "expects a <tileset>")
    raises_naming("...and text that is not XML at all", PyoneerConfigError,
                  lambda: refused_group.restore_object("<not xml", 0),
                  "was handed text that is not")

    # --------------------------------------------------------------------
    print()
    print("...and the same door refuses a VALUE no reader can cast")
    # --------------------------------------------------------------------
    # THE SIBLING RULE, ONE PASS LATE, which is this repository's most-
    # repeated defect shape and the reason it is measured here rather than
    # described. The section above refuses smuggled NAMES and said nothing
    # about VALUES, so every row it passed still let `<object width="abc"/>`
    # through -- and that costs the identical thing law 1 costs: pytmx casts
    # every attribute onto the element before it reads one property, so the
    # cast raises and takes the WHOLE map with it, naming neither the map
    # nor the attribute. Driven through the relay before this existed, all
    # three restore verbs ACCEPTED it.
    #
    # The rule is ONE table, `ATTRIBUTE_TEXT`, living beside `RESERVED` in
    # `scripts/core/layer_profile.py` because `editor/core/verbs.py` asks it
    # the same question about its typed command arguments and `scripts/` may
    # never import `editor/` (law 2). So the first rows here are the same
    # bargain RESERVED is written under: DERIVE it from pytmx, so an upgrade
    # that adds a cast turns this red instead of turning a map unloadable.
    AS_PYTMX = {int: int, float: float, str: str, bool: convert_to_bool}
    expect("every name pytmx casts is declared, with the cast pytmx really "
           "applies -- `in`, never `[]`, because the subscript on a "
           "defaultdict would INSERT the name and pass for free",
           sorted(name for name in PYTMX_TYPES
                  if name not in ATTRIBUTE_TEXT
                  or AS_PYTMX[ATTRIBUTE_TEXT[name]] is not PYTMX_TYPES[name]),
           [])
    expect("...and the rows pytmx does NOT carry are exactly the three that "
           "are ours: two names it never casts, and the one counter our own "
           "reader is stricter about",
           (sorted(n for n, w in ATTRIBUTE_TEXT.items()
                   if n not in PYTMX_TYPES and w is str),
            sorted(n for n, w in ATTRIBUTE_TEXT.items()
                   if n not in PYTMX_TYPES and w is not str)),
           (["class", "template"], ["nextlayerid"]))
    expect("every property type pytmx knows is declared with its own cast, "
           "and `class` is the one deliberately absent -- pytmx resolves it "
           "against the map's custom types instead of casting text",
           (sorted(k for k in PYTMX_PROP_TYPE
                   if k != "class"
                   and (k not in PROPERTY_TEXT
                        or AS_PYTMX[PROPERTY_TEXT[k]] is not PYTMX_PROP_TYPE[k])),
            sorted(set(PROPERTY_TEXT) - set(PYTMX_PROP_TYPE)),
            "class" in PROPERTY_TEXT),
           ([], [], False))
    # And the predicate itself against the reader, text by text, BOTH ways:
    # a row that only proved agreement on refusals would be satisfied by a
    # predicate that refuses everything.
    corpus = ["0", "1", "16", "-3", "12.5", "22.5", "", "   ", "abc",
              "not-a-number", "maybe", "true", "False", "y", "n", "NaN"]

    def pytmx_takes(cast, text):
        try:
            cast(text)
        except Exception:                                   # noqa: BLE001
            return False
        return True

    expect("text_reads_back agrees with pytmx's own cast on every text in a "
           "corpus that is half legal and half not, for all four shapes",
           sorted((wants.__name__, text) for wants in (int, float, bool, str)
                  for text in corpus
                  if text_reads_back(wants, text)
                  is not pytmx_takes(AS_PYTMX[wants], text)),
           [])
    expect("...and that corpus really does split, so the row above is not "
           "agreement between two functions that always say yes",
           sorted({(wants.__name__, text_reads_back(wants, text))
                   for wants in (int, float, bool) for text in corpus}),
           [("bool", False), ("bool", True), ("float", False),
            ("float", True), ("int", False), ("int", True)])

    # -- now the door, driven on all three restore verbs -------------------
    # NaN is the text worth using twice: `float("NaN")` SUCCEEDS, so an
    # `x="NaN"` is a legal float attribute and a `<property type="int">`
    # carrying it is not. A guard that tested the text instead of the
    # declared cast would get one of those two wrong.
    values = MapDocument.load(MAP_PATH)
    values_group = values.object_layer("entity")
    VALUES_BEFORE = values.to_bytes()
    raises_naming("restore_object refuses an <object> whose width is not "
                  "float text, naming the attribute and the cast",
                  PyoneerConfigError,
                  lambda: values_group.restore_object(
                      '<object id="77" x="0" y="0" width="abc"/>', 0),
                  "width", "float", "unloadable")
    raises_naming("...and restore_layer, one verb along and one level down",
                  PyoneerConfigError,
                  lambda: values.restore_layer(
                      {"xml": '<objectgroup id="77" name="v">'
                              '<object id="1" gid="12.5"/></objectgroup>',
                       "index": 1, "tag": "objectgroup"}),
                  "gid", "int")
    raises_naming("...and restore_tileset, whose firstgid decides what every "
                  "painted csv token in the map means",
                  PyoneerConfigError,
                  lambda: values.restore_tileset(
                      {"xml": '<tileset firstgid="abc" name="V"/>',
                       "index": 1, "first_gid": 65}),
                  "firstgid", "int")
    raises_naming("a <property> is the same question asked through its own "
                  "type=, and the TYPED door cannot even build this one",
                  PyoneerConfigError,
                  lambda: values_group.restore_object(
                      '<object id="77" x="0" y="0"><properties>'
                      '<property name="pyoneer_hp" type="int" value="NaN"/>'
                      '</properties></object>', 0),
                  "pyoneer_hp", "int", "NaN")
    raises_naming("...and a type= pytmx has no cast for at all, because it "
                  "looks that table up by subscript",
                  PyoneerConfigError,
                  lambda: values_group.restore_object(
                      '<object id="77" x="0" y="0"><properties>'
                      '<property name="pyoneer_hp" type="colour" value="1"/>'
                      '</properties></object>', 0),
                  "colour", "no such property type")
    expect("five refusals, and the document is the one they started from",
           (values.to_bytes() == VALUES_BEFORE, values.changed),
           (True, False))

    # -- THE OTHER HALF, three times over ---------------------------------
    # A door that refused every payload would pass every row above. These
    # say what still goes through, and each one is a payload a real inverse
    # carries.
    attempt("an attribute NOTHING casts takes any text at all -- a name that "
            "looks like a number is a name",
            lambda: values_group.restore_object(
                '<object id="77" name="not-a-number" type="9" x="0" y="0"/>',
                0).element.get("name"), "not-a-number")
    expect("...and it comes back out",
           (values_group.remove_object(77), values.to_bytes())[1],
           VALUES_BEFORE)
    # NOT STRICTER THAN THE READER, and this is the row that keeps it that
    # way: pytmx's bool cast reads the first character, so `visible="n..."`
    # is false rather than fatal. Refusing it would break the undo of a
    # value a human authored, which is a worse failure than the one this
    # door exists to stop.
    attempt("a bool attribute is judged the way pytmx judges it, first "
            "character and all, not by a plausible {'0','1'}",
            lambda: values_group.restore_object(
                '<object id="77" x="0" y="0" visible="not-a-number"/>',
                0).element.get("visible"), "not-a-number")
    values_group.remove_object(77)
    attempt("an honest typed property still restores",
            lambda: values_group.restore_object(
                '<object id="77" x="0" y="0"><properties>'
                '<property name="pyoneer_hp" type="int" value="30"/>'
                '</properties></object>', 0).properties.as_dict()["pyoneer_hp"],
            30)
    expect("...and the whole fixture is back where this sub-section found it",
           (values_group.remove_object(77), values.to_bytes())[1],
           VALUES_BEFORE)

    # -- AND THE COST, measured on the reader rather than described --------
    # Every refusal above claims a map pytmx will not load. That claim is
    # about pytmx, so it is measured on pytmx -- and both halves, because a
    # row that only planted fatal text would be satisfied by a loader that
    # refuses everything.
    EMPTY_GROUP = b'<objectgroup id="9" name="entity"/>'
    expect("the empty group this sub-section plants an object INTO is in the "
           "fixture exactly once, so a plant that quietly matched nothing "
           "cannot report `loads` about a file it never changed",
           VALUES_BEFORE.count(EMPTY_GROUP), 1)
    for planted, verdict_wanted in ((b'width="abc"', "ValueError"),
                                    (b'gid="12.5"', "ValueError"),
                                    (b'rotation="sideways"', "ValueError"),
                                    (b'name="not-a-number"', "loads"),
                                    (b'type="9"', "loads")):
        fatal_path = os.path.join(scratch, "fatal_value.tmx")
        # A WHOLE object is written into the fixture's empty group rather
        # than an attribute inserted beside an existing one: a second copy
        # of a name is an XML ParseError, which is a different failure
        # wearing the same red and would have hidden whether pytmx casts at
        # all.
        with open(fatal_path, "wb") as handle:
            handle.write(VALUES_BEFORE.replace(
                EMPTY_GROUP,
                b'<objectgroup id="9" name="entity"><object id="1" x="0" '
                b'y="0" ' + planted + b'/></objectgroup>', 1))
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pytmx.TiledMap(fatal_path)
            verdict = "loads"
        except Exception as exc:                            # noqa: BLE001
            verdict = type(exc).__name__
        expect("<object %s ...> in a real file: pytmx %s"
               % (planted.decode(), verdict_wanted), verdict, verdict_wanted)

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
    print("the last child out turns the light off -- and only when the room "
          "is empty")
    # --------------------------------------------------------------------
    # WHY THIS SECTION EXISTS, and it is the counter-move CLAUDE.md's
    # sibling-route warning prescribes rather than a new rule.
    # `_append_child` writes `parent.text` -- the whitespace in front of the
    # first child -- the moment an element gains one, and nothing took it
    # away again. So an element the file wrote SELF-CLOSING came back as an
    # open/close pair with a blank line between the tags after a
    # declare-then-undo: two lines of diff nobody authored, and a map
    # reported dirty after a NO-OP pair, because `MapDocument.changed`
    # re-serialises and compares BYTES.
    # That one line was copied into FOUR verb bodies in
    # `editor/core/verbs.py`, each carrying a comment saying it belonged
    # here -- and the fourth was missed for a whole pass by a grep that
    # enumerated the other three. It is one line in `_remove_child` now and
    # the four copies are deleted, so it cannot be missed a fifth time.
    closing = MapDocument.from_bytes(ORIGINAL)
    empty = closing.object_layer("entity")
    expect("the fixture's object group is the self-closing case",
           (empty.objects(), empty.element.text), ([], None))

    empty.properties["pyoneer_depth"] = 5
    expect("declaring a capability opens the group",
           b'<objectgroup id="9" name="entity">' in closing.to_bytes(), True)
    expect("...and the element gains the text that opened it",
           (empty.element.text or "").strip(), "")
    expect("...which really is text, not nothing",
           empty.element.text is None, False)

    del empty.properties["pyoneer_depth"]
    expect("removing it closes the group again, BYTE for byte",
           closing.to_bytes(), ORIGINAL)
    expect("...at the mechanism: the text is gone, not merely blank",
           empty.element.text, None)
    expect("...so a no-op pair does not leave the document dirty",
           closing.changed, False)

    # THE OFF HALF, and it is the half an unconditional `text = None` fails.
    # A tile layer always carries `<data>`, so removing its property leaves
    # a parent that still has a child: the whitespace in front of `<data>`
    # is load-bearing and must survive untouched.
    floor = closing.tile_layer("Floor")
    kept_text = floor.element.text
    expect("a tile layer's text is the indent in front of its <data>",
           (kept_text or "").strip() == "" and kept_text is not None, True)
    floor.properties["pyoneer_depth"] = 5
    del floor.properties["pyoneer_depth"]
    expect("a parent that still has children keeps its text",
           floor.element.text, kept_text)
    expect("...and the file is byte-identical either way",
           closing.to_bytes(), ORIGINAL)

    # THE OTHER OFF HALF: only WHITESPACE is cleared. An element carrying
    # real content keeps it no matter what is removed from it, which is the
    # exact mirror of `_append_child`'s own condition.
    holder = ElementTree.fromstring("<holder>keep me<child/></holder>")
    closing._remove_child(holder, list(holder)[0])
    expect("a parent whose text is REAL CONTENT keeps it when its last "
           "child goes", (holder.text, len(list(holder))), ("keep me", 0))

    # AND THE GUARD IS NOT COPIED BACK. A fifth copy in a verb body is how
    # this defect survived three passes; the primitive is the only place
    # that may spell it.
    with open(os.path.join(_bootstrap.REPO_ROOT, "scripts", "loaders", "map_document.py"),
              "r", encoding="utf-8") as handle:
        _module_source = handle.read()
    expect("`parent.text = None` is spelled exactly once in the module",
           _module_source.count("parent.text = None"), 1)
    with open(os.path.join(_bootstrap.REPO_ROOT, "editor", "core", "verbs.py"),
              "r", encoding="utf-8") as handle:
        _verbs_source = handle.read()
    expect("and no verb body carries a copy of it any more",
           _verbs_source.count(".element.text = None"), 0)

    # AND THE SAME RULE ON THE OTHER END OF THE LIST. `_append_child`'s
    # append branch already INHERITED the closing whitespace -- with a
    # comment saying recomputing "looked equivalent and was not" -- and
    # then recomputed the separator it put in front of the new last child,
    # three lines below its own warning. `_separator_of` is that sentence
    # made into one function both branches call.
    odd = b"".join([
        b'<?xml version="1.0" encoding="UTF-8"?>' + CRLF,
        b'<map version="1.2" width="1" height="1" tilewidth="16"'
        b' tileheight="16" nextlayerid="2" nextobjectid="3">' + CRLF,
        b' <objectgroup id="1" name="odd">' + CRLF,
        b'   <object id="1" x="0" y="0"/>' + CRLF,
        b'   <object id="2" x="0" y="0"/>' + CRLF,
        b' </objectgroup>' + CRLF,
        b'</map>' + CRLF,
    ])
    # Three-space children under a one-space parent, so the computed answer
    # is TWO and every recomputed indent in this fixture is wrong by a byte.
    quirky = MapDocument.from_bytes(odd)
    expect("the quirky fixture round-trips untouched", quirky.to_bytes(), odd)
    group = quirky.object_layer("odd")
    expect("its children really are indented deeper than the rule computes",
           (group.element.text, quirky._child_indent(group.element)),
           ("\n   ", "  "))
    added = group.add_object(name="third", x=0, y=0)
    expect("an APPENDED child copies its siblings' indent, not the computed "
           "one",
           CRLF + b'   <object id="3" name="third"' in quirky.to_bytes(), True)
    expect("...and removing it again is byte-identical",
           (group.remove_object(added.id), quirky.to_bytes()), (True, odd))

    # THE EXCLUSION, asserted directly, because no fixture above can reach
    # it: measured, a mutation that widened the candidate list to include
    # the LAST child's tail left every row in this file green. That tail is
    # the whitespace before the PARENT's own closing tag, so it is a step
    # shallower than a sibling separator, and taking it would indent a new
    # child level with its parent.
    probe = ElementTree.Element("probe")
    kid = ElementTree.SubElement(probe, "kid")
    probe.text = None
    kid.tail = "\n "
    expect("a lone child's tail is not a sibling separator, so there is "
           "nothing to copy and the computed indent has to answer",
           quirky._separator_of(probe, list(probe)), None)
    kid.tail = "\n   "
    second = ElementTree.SubElement(probe, "kid")
    second.tail = "\n "
    expect("...and with a real sibling in front of it, the separator "
           "between the two is the one that is read",
           quirky._separator_of(probe, list(probe)), "\n   ")

    # THE WHOLE INVERSE, on the fixture that can tell a read indent from a
    # computed one: `map.object.remove` serializes, removes and carries the
    # index, and `map.object.restore` puts it back. Every position, and the
    # EMPTIED layer last -- that one has no sibling left to copy, so it is
    # the case `ObjectLayer.remove_object`'s saved text answers and the one
    # the R7 handoff reported as a one-byte-per-line diff.
    for _which in (1, 2, 3):
        _round = MapDocument.from_bytes(odd)
        _group = _round.object_layer("odd")
        if _which == 3:
            _round.object_layer("odd").remove_object(2)
            _before = _round.to_bytes()
            _target = 1
        else:
            _before = odd
            _target = _which
        _payload = _group.serialize_object(_target)
        _index = _group.object_index(_target)
        _next = _round.root.get("nextobjectid")
        _group.remove_object(_target)
        _group.restore_object(_payload, _index)
        _round.root.set("nextobjectid", _next)
        expect("remove-then-restore is byte-exact at position %d%s" %
               (_which, " -- the EMPTIED layer" if _which == 3 else ""),
               _round.to_bytes(), _before)

    # --------------------------------------------------------------------
    print()
    print("an attribute put back comes back WHERE IT WAS, not at the end")
    # --------------------------------------------------------------------
    # THE SAME SENTENCE `_separator_of` IS WRITTEN UNDER, on the other axis
    # of the same contract: read the order off the FILE, never compute one.
    # There it is the whitespace in front of a child; here it is the
    # left-to-right order of an attribute list.
    #
    # `Element.attrib` is a dict and `Element.set` APPENDS, so removing an
    # attribute and writing it back moved it to the END of the element.
    # `map.object.unset` is the only door in the editor that removes one and
    # its inverse is `map.object.set`, so apply-then-undo restored the VALUE
    # and not the BYTES -- measured before the repair, EIGHT of the nine
    # names the verb accepts came back last, each leaving the map dirty
    # after a NO-OP pair, and the ninth passed only because it already sat
    # last. One name that cannot move is exactly how a loop covering half a
    # vocabulary reads green, so the fixture below deliberately puts
    # vocabulary names in front, in the middle AND at the end, and the loop
    # is driven by the editor's tuple rather than by a list written here.
    #
    # WHY A MEMORY AND NOT A CANONICAL ORDER. A canonical attribute order
    # would need no memory at all -- and would rewrite every element of
    # every map the first time it was saved, including the two files this
    # module measures byte for byte. The memory touches an element only
    # after something removed one of its attributes; the shipped map's rows
    # at the end of this file are what that choice is protecting.
    ORDERED = b"".join([
        b'<?xml version="1.0" encoding="UTF-8"?>' + CRLF,
        b'<map version="1.10" width="1" height="1" tilewidth="16"'
        b' tileheight="16" nextlayerid="3" nextobjectid="4">' + CRLF,
        b'\t<objectgroup id="2" name="entity">' + CRLF,
        b'  <object id="1" name="hero" class="Hero" gid="5" visible="1"'
        b' rotation="90" template="t.tx" type="GamePlayer" x="16" y="16"'
        b' width="16" height="16">' + CRLF,
        b'   <properties>' + CRLF,
        b'    <property name="hp" type="int" value="30"/>' + CRLF,
        b'   </properties>' + CRLF,
        b'  </object>' + CRLF,
        b'\t</objectgroup>' + CRLF,
        b'</map>' + CRLF,
    ])

    def object_line(body: bytes) -> bytes:
        """The fixture's `<object>` line alone.

        Needed because `name=` and `type=` are also spelled on the
        `<property>` two lines below it, so "is the attribute gone" asked of
        the whole document answers about the wrong element.
        """
        for line in body.split(CRLF):
            if line.lstrip().startswith(b"<object "):
                return line
        return b""

    expect("the ordered fixture round-trips untouched",
           MapDocument.from_bytes(ORDERED).to_bytes(), ORDERED)
    _carrier = MapDocument.from_bytes(ORDERED).object_layer("entity").objects()[0]
    expect("...and carries every name the editor's vocabulary declares, so "
           "the loop cannot skip one by not finding it",
           [k for k in _OBJECT_ATTRIBUTES if k not in _carrier.element.attrib],
           [])
    expect("...with exactly one vocabulary name sitting LAST -- the one "
           "position the defect could never show",
           [k for k in _OBJECT_ATTRIBUTES
            if k == list(_carrier.element.attrib)[-1]], ["height"])

    _covered = []
    for _key in tuple(_OBJECT_ATTRIBUTES) + ("id", "x", "y"):
        _doc = MapDocument.from_bytes(ORDERED)
        _obj = _doc.object_layer("entity").objects()[0]
        _was = _obj.unset(_key)
        _gone = _doc.to_bytes()
        _obj.set(_key, _was)
        _covered.append(_key)
        expect("%-9s unset + set is byte-identical and leaves it clean" % _key,
               (_was is not None, _doc.to_bytes() == ORDERED, _doc.changed),
               (True, True, False))
        # THE HALF THAT MAKES THE ROW ABOVE FALSIFIABLE. A `unset` that did
        # nothing would satisfy every byte comparison in this loop, so the
        # removal is measured on its own: it really changed the file, and
        # the name really left the element. The leading space is load
        # bearing -- `gid="5"` contains `id="`.
        expect("%-9s ...and the unset ALONE really changed the bytes" % _key,
               (_gone != ORDERED,
                (" %s=\"" % _key).encode("ascii") in object_line(_gone)),
               (True, False))
    expect("every name in the vocabulary was driven, both directions -- a "
           "loop that silently covers five is how this shipped",
           _covered, list(_OBJECT_ATTRIBUTES) + ["id", "x", "y"])

    # THE MEMORY RESTORES A POSITION, IT NEVER INVENTS ONE -- which is what
    # keeps it from being a canonical order wearing a disguise. A name the
    # file never carried still appends, exactly as `Element.set` would.
    _new = MapDocument.from_bytes(ORDERED)
    _newobj = _new.object_layer("entity").objects()[0]
    _newobj.set("probability", "0.5")
    expect("a genuinely NEW attribute still lands at the end",
           object_line(_new.to_bytes()).endswith(b'probability="0.5">'), True)
    expect("...and taking it off again is byte-identical",
           (_newobj.unset("probability"), _new.to_bytes()), ("0.5", ORDERED))

    # AN ABSENT NAME IS NOT AN EDIT. `unset` answers None and does not even
    # touch the document, so a verb built on it can return "no inverse"
    # rather than an inverse that writes None back.
    _absent = MapDocument.from_bytes(ORDERED)
    expect("unset of a name the element never carried is a no-op",
           (_absent.object_layer("entity").objects()[0].unset("ellipse"),
            _absent.to_bytes() == ORDERED, _absent.changed),
           (None, True, False))

    # THE ROUTE `map.object.unset` TAKES TODAY: it pops `element.attrib`
    # itself rather than calling the model. So the record has to be a
    # property of the DOCUMENT and not of the door, and it has to be taken
    # for all THREE provenances an `<object>` can have -- parsed, authored
    # here, restored from text. Each has its own recording line
    # (`_rebuild_parents`, `add_object`, `restore_object`) and each of the
    # three rows below reddens exactly one of them.
    def raw_cycle(document, wrapper, key):
        """Remove an attribute the way the shipped verb does, then set it."""
        was = wrapper.element.attrib.pop(key)
        document._touch()
        wrapper.set(key, was)
        return document.to_bytes()

    _raw = MapDocument.from_bytes(ORDERED)
    expect("PARSED: a raw pop and set on a LOADED object is byte-identical",
           raw_cycle(_raw, _raw.object_layer("entity").objects()[0], "name"),
           ORDERED)

    _fresh = MapDocument.from_bytes(ORDERED)
    _made = _fresh.object_layer("entity").add_object(
        name="spawned", type="GamePlayer", x=1, y=2, width=3, height=4)
    _madebytes = _fresh.to_bytes()
    expect("AUTHORED: and on an object this session CREATED, which never "
           "passes through _rebuild_parents", raw_cycle(_fresh, _made, "type"),
           _madebytes)
    expect("...and it really is the new object's line that is being read, "
           "still in the order add_object wrote it",
           b' name="spawned" type="GamePlayer" x="1" y="2"'
           in _fresh.to_bytes(), True)

    _back = MapDocument.from_bytes(ORDERED)
    _backgroup = _back.object_layer("entity")
    _payload3 = _backgroup.serialize_object(1)
    _backgroup.remove_object(1)
    _backgroup.restore_object(_payload3, 0)
    expect("RESTORED: and on one put back from its own XML text, whose "
           "record `_remove_child` had just thrown away",
           raw_cycle(_back, _backgroup.objects()[0], "rotation"), ORDERED)

    # AND THE SIBLING IN THIS MODULE, which is where the second instance was
    # hiding: `MapProperties.__setitem__` POPS `type` when a typed property
    # is overwritten with a string, and typing it back appended it after
    # `value`. Same primitive, same repair, a different door.
    _typed = MapDocument.from_bytes(ORDERED)
    _view = _typed.object_layer("entity").objects()[0].properties
    _view["hp"] = "thirty"
    _loose = _typed.to_bytes()
    _view["hp"] = 30
    expect("a typed property overwritten with a string and typed back is "
           "byte-identical", (_typed.to_bytes(), _typed.changed),
           (ORDERED, False))
    expect("...and the string step really did drop the type, so the row "
           "above is a repair and not a verb that did nothing",
           (b'<property name="hp" value="thirty"/>' in _loose,
            b'type=' in [line for line in _loose.split(CRLF)
                         if b'name="hp"' in line][0]),
           (True, False))

    # A PROPERTY THIS SESSION CREATED -- the one element `_rebuild_parents`
    # cannot have seen and no `add_*` records, so `__setitem__`'s own line is
    # the only thing holding it. Written int, retyped to a string and back.
    _born = MapDocument.from_bytes(ORDERED)
    _bornview = _born.object_layer("entity").objects()[0].properties
    _bornview["mp"] = 7
    _bornbytes = _born.to_bytes()
    expect("a NEW typed property is written in Tiled's order",
           b'<property name="mp" type="int" value="7"/>' in _bornbytes, True)
    _bornview["mp"] = "seven"
    _bornview["mp"] = 7
    expect("...and string-then-int returns it byte-identically",
           _born.to_bytes(), _bornbytes)

    # AND THE RECORD MERGES RATHER THAN OVERWRITING, which is the whole
    # subtlety of taking it more than once. The SECOND string write asks
    # again on an element that has already LOST `type`; an overwrite would
    # forget where the missing name sat, which is the only thing the record
    # exists to know.
    _twice = MapDocument.from_bytes(ORDERED)
    _twiceview = _twice.object_layer("entity").objects()[0].properties
    _twiceview["hp"] = "thirty"
    _twiceview["hp"] = "thirty-one"
    _twiceview["hp"] = 30
    expect("two string writes then an int still puts type back in place",
           (_twice.to_bytes(), _twice.changed), (ORDERED, False))

    # THE MEMORY IS NOT A LEAK. It is keyed by element, so an element that
    # leaves the tree has to take its entry with it or the document holds
    # every object the session ever deleted alive. Every restore re-PARSES
    # the element text, so there is nothing here a later restore wants.
    _leak = MapDocument.from_bytes(ORDERED)
    _leakgroup = _leak.object_layer("entity")
    _leakelement = _leakgroup.objects()[0].element
    expect("a removed element's remembered order goes with it",
           (_leakelement in _leak._attribute_spellings,
            _leakgroup.remove_object(1),
            _leakelement in _leak._attribute_spellings),
           (True, True, False))

    # AND IT IS READ IN ONE PLACE, for the reason the self-closing guard
    # above is spelled once: a second attribute loop in the serializer is a
    # copy that agrees today and cannot be mutated once.
    expect("the serializer reads attributes through the one ordering "
           "function and nowhere else",
           _module_source.count("element.attrib.items()"), 1)

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
