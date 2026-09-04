"""Measure MapDocument's tileset methods against BYTES, not against XML.

A tileset is the only element in a .tmx that other elements depend on
NUMERICALLY -- every csv token and every `<object gid=...>` is an index into
the concatenated firstgid ranges -- so there are two separate claims here and
neither implies the other:

    add_tileset + remove_tileset          reproduces the original bytes
    serialize + remove + restore_tileset  reproduces the original bytes
    a firstgid that would force a renumber is REFUSED
    a tileset whose gids are still painted is REFUSED

The byte claims are the same minimal-diff contract check_tmx_roundtrip
measures, and they are hard for the same reason: `_child_indent(root)` can
only ever return a single space (the root has no parent to be deeper than),
so EVERY tileset insert lands on whitespace the file spells with a tab, and
`_append_child` clobbers `root.text` on an index-0 insert while
`_remove_child` never puts it back.

The refusal claims are the other half. Nothing raises when a gid outranges
its tileset: pytmx's `get_tileset_from_gid` sorts firstgids descending and
returns the first one that is <= the gid, so an orphan resolves to the
tileset BELOW and paints the wrong art. Silence is the failure mode, so the
refusals are asserted by message content, not just by exception type.

Every fixture below is BUILT HERE, INCLUDING the awkward one. The four
punctuation claims -- a tab-indented `<tileset>`, its `<image>` one level
deeper with tabs, no lone LF, and `root.text` surviving an insert -- used to
be measured against `data/maps/test.tmx`, which happened to be CRLF and
tab-indented. That made them claims about one person's canvas wearing a
claim about the WRITER's clothes, and the day the shipped map was replaced
by `data/maps/starter.tmx` -- uniform LF, uniform one-space indent -- a
repoint would have deleted the coverage in silence. `UGLY_MAP` below is
guaranteed awkward instead of borrowed.

The shipped map is still read, once, at the end: every tileset it declares
must serialize, remove and restore byte-exactly. That loop names none of
them and asserts nothing about what it contains.

    .venv/Scripts/python.exe tools/check_tileset.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import atexit
import os
import shutil
import struct
import sys
import tempfile
import warnings
import zlib

from scripts.core.errors import PyoneerConfigError
from scripts.loaders.map_document import (MapDocument, TilesetRef, image_size,
                                          tileset_geometry)

SHIPPED_PATH = os.path.join(_bootstrap.REPO_ROOT, "data", "maps", "starter.tmx")


def png_bytes(width: int, height: int) -> bytes:
    """A real, decodable 8-bit RGB PNG."""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x40\x80\xc0" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


#: CRLF throughout, tab-indented children, TWO tilesets so the loop below
#: gets both the index-0 (parent_text) case and a middle (prev_tail) one,
#: and a tile layer so the file is a map rather than a header.
UGLY_MAP = (
    b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
    b'<map version="1.10" tiledversion="1.11.0" orientation="orthogonal"'
    b' renderorder="right-down" width="8" height="8" tilewidth="16"'
    b' tileheight="16" infinite="0" nextlayerid="3" nextobjectid="1">\r\n'
    b'\t<tileset firstgid="1" name="Alpha" tilewidth="16" tileheight="16"'
    b' tilecount="64" columns="8">\r\n'
    b'\t\t<image source="alpha.png" width="128" height="128"/>\r\n'
    b'\t</tileset>\r\n'
    b'\t<tileset firstgid="65" name="Beta" tilewidth="16" tileheight="16"'
    b' tilecount="16" columns="4">\r\n'
    b'\t\t<image source="beta.png" width="64" height="64"/>\r\n'
    b'\t</tileset>\r\n'
    b'\t<layer id="1" name="Floor" width="8" height="8">\r\n'
    b'\t\t<data encoding="csv">\r\n'
    + b"".join(b"1,2,3,4,5,6,7,8,\r\n" for _ in range(7))
    + b"1,2,3,4,5,6,7,8\r\n"
    b'</data>\r\n'
    b'\t</layer>\r\n'
    b'</map>\r\n'
)

FIXTURE_DIR = tempfile.mkdtemp(prefix="pyoneer_ugly_tileset_")
atexit.register(shutil.rmtree, FIXTURE_DIR, ignore_errors=True)
MAP_PATH = os.path.join(FIXTURE_DIR, "ugly.tmx")
with open(MAP_PATH, "wb") as _handle:
    _handle.write(UGLY_MAP)
for _name, _w, _h in (("alpha.png", 128, 128), ("beta.png", 64, 64),
                      ("check_sheet.png", 64, 48)):
    with open(os.path.join(FIXTURE_DIR, _name), "wb") as _handle:
        _handle.write(png_bytes(_w, _h))

failures: list[str] = []


def brief(value) -> str:
    """A repr that will not dump 135KB of csv into the check output."""
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>" if len(value) > 60 else repr(value)
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={brief(got)} want={brief(want)}")
    if not ok:
        failures.append(label)
        if isinstance(got, bytes) and isinstance(want, bytes) and len(want) > 60:
            span = diff_span(want, got)
            if span is not None:
                low, high = span
                print(f"        first diff at byte {low}")
                print(f"        want ...{want[max(0, low - 40):high + 40]!r}...")
                print(f"        got  ...{got[max(0, low - 40):low + 40]!r}...")


def expect_raises(label, exception_type, fn):
    """Assert an operation REFUSES. A guard that returns a plausible value
    instead of raising is the failure mode this file exists to catch."""
    try:
        fn()
    except exception_type as exc:
        print(f"  ok   {label:<58} {type(exc).__name__}: "
              f"{str(exc).splitlines()[0][:44]}")
        return
    except Exception as exc:                                    # noqa: BLE001
        print(f"  FAIL {label:<58} raised {type(exc).__name__}, "
              f"wanted {exception_type.__name__}")
        failures.append(label)
        return
    print(f"  FAIL {label:<58} did not raise {exception_type.__name__}")
    failures.append(label)


def raises(label, exc_type, fn, contains: str | None = None):
    """Assert `fn` raises, and optionally that the message SAYS WHY.

    The `contains` half matters more than usual here: a refusal whose
    message does not name the tiles that block it is a dead end for whoever
    hits it, and "it raised something" would keep passing after the
    explanation rotted away.
    """
    try:
        fn()
    except exc_type as exc:
        if contains is not None and contains not in str(exc):
            print(f"  FAIL {label:<58} message lacks {contains!r}: {exc}")
            failures.append(label)
            return
        print(f"  ok   {label:<58} {type(exc).__name__}")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<58} raised {type(exc).__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<58} did not raise")
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


def png_bytes(width: int, height: int) -> bytes:
    """A real, decodable 8-bit RGB PNG of the requested size.

    Real rather than a 24-byte stub for the first fixture, so `image_size`
    is measured against a file any decoder would agree with rather than
    against a header this check invented to match itself.
    """
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def csv_rows(width: int, height: int, gid: int = 0, newline: str = "\r\n") -> str:
    """The csv shape Tiled writes: every row comma-terminated but the last.

    `newline` defaults to CRLF because these fixtures are CRLF documents,
    and MapDocument decides a file's newline convention from its RAW bytes.
    A fixture that mixes a bare LF into a CRLF body is not a harder test,
    it is an invalid file: to_bytes() normalises it to CRLF on the way out
    and the round trip fails on the fixture's own malformation rather than
    on anything the tileset code did.
    """
    row = ",".join(str(gid) for _ in range(width))
    return ("," + newline).join(row for _ in range(height))


scratch = tempfile.mkdtemp(prefix="pyoneer_tileset_")
try:
    # A real PNG on disk, so the auto-measuring path in add_tileset is
    # exercised rather than short-circuited by explicit dimensions.
    SHEET = os.path.join(scratch, "sheet.png")
    with open(SHEET, "wb") as handle:
        handle.write(png_bytes(64, 48))

    # ----------------------------------------------------------------------
    print("PNG headers and grid geometry, without pygame or Qt")
    # ----------------------------------------------------------------------
    expect("image_size reads a real PNG", image_size(SHEET), (64, 48))

    # 24 bytes is all the information there is; the rest of the file is
    # pixels this code must never need.
    stub = os.path.join(scratch, "stub.png")
    with open(stub, "wb") as handle:
        handle.write(png_bytes(512, 384)[:24])
    expect("image_size needs only the 24-byte IHDR", image_size(stub), (512, 384))

    truncated = os.path.join(scratch, "short.png")
    with open(truncated, "wb") as handle:
        handle.write(png_bytes(16, 16)[:20])
    raises("a truncated header refuses instead of guessing",
           PyoneerConfigError, lambda: image_size(truncated), contains="not a PNG")

    not_png = os.path.join(scratch, "sheet.bmp")
    with open(not_png, "wb") as handle:
        handle.write(b"BM" + b"\x00" * 60)
    raises("a non-PNG refuses and says to pass the size",
           PyoneerConfigError, lambda: image_size(not_png), contains="image_width")
    raises("a missing file refuses", PyoneerConfigError,
           lambda: image_size(os.path.join(scratch, "nope.png")))

    # The formula, against the numbers Tiled itself wrote for the two sheets
    # this project ships. Stated as literals here rather than read out of the
    # map, so the assertion survives the author repainting anything.
    expect("512x384 at 16px is Tiled's 32x24=768",
           tileset_geometry(512, 384, 16, 16), (32, 24, 768))
    expect("512x512 at 16px is Tiled's 32x32=1024",
           tileset_geometry(512, 512, 16, 16), (32, 32, 1024))
    # Spacing shortens every gap but the last: 3 tiles of 16 with 2 between
    # them is 16+2+16+2+16 = 52, so 52 fits 3 and 51 fits 2.
    expect("spacing leaves no gap after the last column",
           tileset_geometry(52, 52, 16, 16, 0, 2), (3, 3, 9))
    expect("one pixel short drops a column",
           tileset_geometry(51, 52, 16, 16, 0, 2), (2, 3, 6))
    expect("margin eats from the leading edge",
           tileset_geometry(66, 66, 16, 16, 2, 0), (4, 4, 16))
    expect("an image too small for one tile is zero, not negative",
           tileset_geometry(8, 8, 16, 16), (0, 0, 0))
    expect("a zero tile size is zero, not a ZeroDivisionError",
           tileset_geometry(64, 64, 0, 16), (0, 4, 0))

    # ----------------------------------------------------------------------
    print()
    print("add_tileset then remove_tileset returns the awkward file's bytes")
    # ----------------------------------------------------------------------
    # A COPY, in the same directory, because <image source> resolves relative
    # to the .tmx.
    with open(MAP_PATH, "rb") as handle:
        ORIGINAL = handle.read()
    COPY_PATH = os.path.join(os.path.dirname(MAP_PATH), "_check_tileset.tmx")
    with open(COPY_PATH, "wb") as handle:
        handle.write(ORIGINAL)

    try:
        document = MapDocument.load(COPY_PATH)
        expect("the copy round trips before anything is added",
               document.to_bytes(), ORIGINAL)

        refs = document.tilesets()
        expect("tilesets() finds direct children only",
               len(refs), len(document.root.findall("tileset")))
        expect("every ref is a TilesetRef",
               all(isinstance(r, TilesetRef) for r in refs), True)
        expect("tileset_names() agrees with tilesets()",
               document.tileset_names(), [r.name for r in refs])
        # WHAT the tilesets are is map content and is not asserted; that the
        # accessor reports each one's own attributes faithfully is code.
        expect("each ref mirrors its element's attributes",
               [(r.name, r.first_gid, r.tile_width, r.tile_height,
                 r.columns, r.tile_count, r.image_source) for r in refs],
               [(e.get("name", ""), int(e.get("firstgid", "1")),
                 int(e.get("tilewidth", "0")), int(e.get("tileheight", "0")),
                 int(e.get("columns", "0")), int(e.get("tilecount", "0")),
                 e.find("image").get("source", "") if e.find("image") is not None else "")
                for e in document.root.findall("tileset")])
        expect("ranges are contiguous and non-overlapping",
               all(a.last_gid + 1 == b.first_gid for a, b in zip(refs, refs[1:])), True)
        expect("lookup by name round trips",
               [document.tileset(r.name).first_gid for r in refs],
               [r.first_gid for r in refs])
        expect("lookup by firstgid round trips",
               [document.tileset(r.first_gid).name for r in refs],
               [r.name for r in refs])
        raises("an unknown tileset names the ones that exist", KeyError,
               lambda: document.tileset("NoSuchTileset"))

        appended = document.next_tileset_firstgid()
        expect("next_tileset_firstgid is 1 + sum(tilecount) on a packed map",
               appended, 1 + sum(r.tile_count for r in refs))

        added = document.add_tileset(
            "CheckSheet", "check_sheet.png", image_width=64, image_height=48)
        expect("the new tileset took the appended firstgid",
               added.first_gid, appended)
        expect("its geometry came from the image", (added.columns, added.tile_count), (4, 12))
        expect("its tile size defaulted to the map's",
               (added.tile_width, added.tile_height),
               (document.tile_width, document.tile_height))
        expect("it is listed last", document.tileset_names()[-1], "CheckSheet")

        with_tileset = document.to_bytes()
        expect("it serializes in Tiled's attribute order",
               b'<tileset firstgid="%d" name="CheckSheet" tilewidth="16" '
               b'tileheight="16" tilecount="12" columns="4">' % appended
               in with_tileset, True)
        expect("its <image> carries source, width, height",
               b'<image source="check_sheet.png" width="64" height="48"/>'
               in with_tileset, True)
        # The trap, asserted directly: _child_indent(root) returns ' ', the
        # file uses '\t', and a computed indent would show up right here.
        expect("it is tab-indented like its siblings, not space-indented",
               b'\r\n\t<tileset firstgid="%d" name="CheckSheet"' % appended
               in with_tileset, True)
        expect("its <image> is indented one level deeper, with tabs",
               b'\r\n\t\t<image source="check_sheet.png"'
               in with_tileset, True)
        expect("no lone LF was introduced",
               with_tileset.count(b"\r\n"), with_tileset.count(b"\n"))
        expect("root.text survived the insert", document.root.text, "\n\t")

        expect("remove_tileset finds it", document.remove_tileset("CheckSheet"), True)
        expect("add then remove is byte identical", document.to_bytes(), ORIGINAL)
        expect("removing it twice is False, not an exception",
               document.remove_tileset("CheckSheet"), False)

        # And again, addressed by firstgid rather than by name, because the
        # int branch of the lookup is the one an external tileset needs.
        # The image is deliberately bogus here -- this probe is about the
        # lookup, and the missing-image warning has its own assertion later.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            document.add_tileset("CheckSheet2", "sheet.png",
                                 image_width=64, image_height=48)
        expect("remove by firstgid works too",
               document.remove_tileset(appended), True)
        expect("add then remove-by-firstgid is byte identical",
               document.to_bytes(), ORIGINAL)

        # ------------------------------------------------------------------
        print()
        print("every tileset in it serializes and restores byte identically")
        # ------------------------------------------------------------------
        # Every one, discovered rather than named: the first is the index-0
        # case (parent_text) and any later one is the middle case
        # (prev_tail). Neither is asserted to exist by count.
        for position, ref in enumerate(document.tilesets()):
            label = ref.name or ref.source or str(ref.first_gid)
            payload = document.serialize_tileset(ref.first_gid)
            expect(f"[{position}] {label} serializes", payload is not None, True)
            expect(f"[{position}] {label} payload records its index",
                   payload["index"], list(document.root).index(ref.element))
            expect(f"[{position}] {label} payload carries its firstgid",
                   payload["first_gid"], str(ref.first_gid))
            expect(f"[{position}] {label} carries parent_text only when first",
                   payload["parent_text"] is not None, payload["index"] == 0)
            expect(f"[{position}] {label} carries prev_tail only when not first",
                   payload["prev_tail"] is not None, payload["index"] != 0)

            expect(f"[{position}] {label} removes with force",
                   document.remove_tileset(ref.first_gid, force=True), True)
            expect(f"[{position}] {label} is gone",
                   document.tileset_names().count(ref.name), 0)
            expect(f"[{position}] {label} restores under its own name",
                   document.restore_tileset(payload), ref.name)
            expect(f"[{position}] {label} remove+restore is byte identical",
                   document.to_bytes(), ORIGINAL)

        # The whole point of serializing rather than rebuilding from
        # attributes: the <image> child comes back too.
        first = document.tilesets()[0]
        payload = document.serialize_tileset(first.first_gid)
        document.remove_tileset(first.first_gid, force=True)
        document.restore_tileset(payload)
        expect("the <image> grandchild survived the round trip",
               document.tilesets()[0].image_source, first.image_source)
        expect("and the document still matches on disk", document.to_bytes(), ORIGINAL)

        raises("restore_tileset refuses a non-tileset element",
               PyoneerConfigError,
               lambda: document.restore_tileset({"xml": "<layer/>", "index": 0}),
               contains="expects a <tileset>")
        raises("restore_tileset refuses text that is not XML",
               PyoneerConfigError,
               lambda: document.restore_tileset({"xml": "<not xml", "index": 0}))
        expect("neither refusal changed the bytes", document.to_bytes(), ORIGINAL)
        expect("serialize_tileset of a missing tileset is None",
               document.serialize_tileset("NoSuchTileset"), None)
    finally:
        os.remove(COPY_PATH)

    with open(MAP_PATH, "rb") as handle:
        expect("the awkward fixture is untouched on disk", handle.read(), ORIGINAL)

    # ----------------------------------------------------------------------
    print()
    print("and the SHIPPED map survives the same treatment, tileset by tileset")
    # ----------------------------------------------------------------------
    # The real file, read-only, on its own bytes. Every tileset is
    # DISCOVERED, never named, and no attribute of any of them is asserted:
    # what is asserted is that the reader reproduces the file and that
    # remove+restore is a no-op on it. That holds for whatever is painted in
    # it, which is what makes it legal to point at a live map at all.
    with open(SHIPPED_PATH, "rb") as handle:
        SHIPPED = handle.read()
    shipped = MapDocument.load(SHIPPED_PATH)
    expect("the shipped map round trips untouched", shipped.to_bytes(), SHIPPED)
    expect("it declares at least two tilesets, so both insert cases run",
           len(shipped.tilesets()) >= 2, True)
    for ref in list(shipped.tilesets()):
        payload = shipped.serialize_tileset(ref.first_gid)
        expect(f"[shipped] {ref.name} serializes", payload is not None, True)
        shipped.remove_tileset(ref.first_gid, force=True)
        expect(f"[shipped] {ref.name} is gone",
               shipped.tileset_names().count(ref.name), 0)
        shipped.restore_tileset(payload)
        expect(f"[shipped] {ref.name} remove+restore is byte identical",
               shipped.to_bytes(), SHIPPED)
    with open(SHIPPED_PATH, "rb") as handle:
        expect("data/maps/starter.tmx is untouched on disk",
               handle.read(), SHIPPED)

    # ----------------------------------------------------------------------
    print()
    print("a map with NO tilesets: the index-0 insert that clobbers root.text")
    # ----------------------------------------------------------------------
    # This is the case the fixture above cannot exercise, and the one that fails
    # without snapshotting root.text: _append_child overwrites parent.text
    # with a COMPUTED indent whenever it is whitespace-only, and
    # _remove_child never puts it back. Tab-indented, so a computed '\n '
    # shows up as a diff.
    NO_TILESETS = (
        b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
        b'<map version="1.2" orientation="orthogonal" renderorder="right-down"'
        b' width="4" height="2" tilewidth="16" tileheight="16" infinite="0"'
        b' nextlayerid="2" nextobjectid="1">\r\n'
        b'\t<layer id="1" name="Floor" width="4" height="2">\r\n'
        b'\t\t<data encoding="csv">\r\n'
        + csv_rows(4, 2).encode() + b'\r\n'
        b'</data>\r\n'
        b'\t</layer>\r\n'
        b'</map>\r\n'
    )
    bare = MapDocument.from_bytes(NO_TILESETS, path=os.path.join(scratch, "bare.tmx"))
    expect("the fixture round trips untouched", bare.to_bytes(), NO_TILESETS)
    expect("it really has no tilesets", bare.tilesets(), [])
    expect("next_tileset_firstgid on an empty map is 1",
           bare.next_tileset_firstgid(), 1)

    bare.add_tileset("First", "sheet.png", image_width=64, image_height=48)
    body = bare.to_bytes()
    expect("the first tileset lands in front of the layers",
           body.index(b"<tileset") < body.index(b"<layer"), True)
    expect("and it is tab-indented, not space-indented",
           b'\r\n\t<tileset firstgid="1" name="First"' in body, True)
    expect("root.text was restored after the index-0 insert", bare.root.text, "\n\t")
    expect("the layer that got displaced kept its indent",
           b'\r\n\t<layer id="1" name="Floor"' in body, True)
    expect("removing it returns the original bytes",
           (bare.remove_tileset("First"), bare.to_bytes())[1], NO_TILESETS)

    # ----------------------------------------------------------------------
    print()
    print("a map with tilesets and NO layers: the append-at-the-end branch")
    # ----------------------------------------------------------------------
    # Here the new tileset becomes the LAST root child, so it inherits the
    # whitespace in front of `</map>` and the element it displaced needs the
    # real separator put back -- the branch _append_child computes.
    NO_LAYERS = (
        b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
        b'<map version="1.2" width="4" height="2" tilewidth="16"'
        b' tileheight="16" nextlayerid="1" nextobjectid="1">\r\n'
        b'\t<tileset firstgid="1" name="Only" tilewidth="16" tileheight="16"'
        b' tilecount="12" columns="4">\r\n'
        b'\t\t<image source="sheet.png" width="64" height="48"/>\r\n'
        b'\t</tileset>\r\n'
        b'</map>\r\n'
    )
    lonely = MapDocument.from_bytes(NO_LAYERS, path=os.path.join(scratch, "lonely.tmx"))
    expect("the fixture round trips untouched", lonely.to_bytes(), NO_LAYERS)
    expect("next firstgid follows the only tileset",
           lonely.next_tileset_firstgid(), 13)

    lonely.add_tileset("Second", "sheet.png", image_width=64, image_height=48)
    body = lonely.to_bytes()
    expect("the appended tileset is tab-indented",
           b'\r\n\t<tileset firstgid="13" name="Second"' in body, True)
    expect("the tileset it displaced kept its tab",
           b'\r\n\t<tileset firstgid="1" name="Only"' in body, True)
    expect("</map> kept its own indent", body.endswith(b'\r\n</map>\r\n'), True)
    expect("removing it returns the original bytes",
           (lonely.remove_tileset("Second"), lonely.to_bytes())[1], NO_LAYERS)

    # And the same map's only tileset, removed and restored: index 0 AND
    # last child at once, which is the case where parent_text and the
    # closing whitespace are the same two bytes doing different jobs.
    payload = lonely.serialize_tileset("Only")
    expect("the only tileset serializes at index 0", payload["index"], 0)
    lonely.remove_tileset("Only", force=True)
    expect("the map is left with no tilesets", lonely.tilesets(), [])
    expect("restoring it returns the original bytes",
           (lonely.restore_tileset(payload), lonely.to_bytes())[1], NO_LAYERS)

    # ----------------------------------------------------------------------
    print()
    print("a firstgid that would force a renumber is refused, not accommodated")
    # ----------------------------------------------------------------------
    packed = MapDocument.from_bytes(NO_LAYERS, path=os.path.join(scratch, "packed.tmx"))
    packed.add_tileset("Upper", "sheet.png", image_width=64, image_height=48)
    expect("two tilesets, packed end to end",
           [(r.first_gid, r.last_gid) for r in packed.tilesets()], [(1, 12), (13, 24)])
    expect("next_tileset_firstgid == 1 + sum(tilecount)",
           packed.next_tileset_firstgid(),
           1 + sum(r.tile_count for r in packed.tilesets()))

    before = packed.to_bytes()
    raises("a firstgid inside an existing range is refused", PyoneerConfigError,
           lambda: packed.add_tileset("Middle", "sheet.png", first_gid=7,
                                      image_width=64, image_height=48),
           contains="renumbering every csv token")
    raises("a firstgid exactly on an existing one is refused", PyoneerConfigError,
           lambda: packed.add_tileset("Middle", "sheet.png", first_gid=13,
                                      image_width=64, image_height=48),
           contains="collides with or sits below")
    raises("firstgid 0 is refused (gid 0 means empty)", PyoneerConfigError,
           lambda: packed.add_tileset("Middle", "sheet.png", first_gid=0,
                                      image_width=64, image_height=48),
           contains="at least 1")
    raises("a duplicate name is refused, like add_layer", PyoneerConfigError,
           lambda: packed.add_tileset("Upper", "sheet.png",
                                      image_width=64, image_height=48),
           contains="already has a tileset named")
    raises("an image too small for one tile is refused", PyoneerConfigError,
           lambda: packed.add_tileset("Tiny", "sheet.png",
                                      image_width=8, image_height=8),
           contains="no tiles")
    raises("an unmeasurable image is refused rather than guessed",
           PyoneerConfigError,
           lambda: packed.add_tileset("Ghost", "does_not_exist.png"),
           contains="pass image_width and image_height")
    raises("an external .tsx is out of scope and says so", PyoneerConfigError,
           lambda: packed.add_tileset("External", ""),
           contains="byte-exactness contract")
    expect("no refusal left a partial element behind", packed.to_bytes(), before)
    expect("and the tileset list is unchanged",
           packed.tileset_names(), ["Only", "Upper"])

    # The append that IS allowed, at the top of the range.
    packed.add_tileset("Third", "sheet.png", first_gid=25,
                       image_width=64, image_height=48)
    expect("an explicit firstgid at the top of the range is accepted",
           packed.tileset("Third").first_gid, 25)
    packed.remove_tileset("Third")
    expect("and removing it is byte identical again", packed.to_bytes(), before)

    # ----------------------------------------------------------------------
    print()
    print("removing a tileset whose gids are still painted is refused")
    # ----------------------------------------------------------------------
    # An orphaned gid does not raise ANYWHERE: pytmx sorts firstgids
    # descending and returns the first one that is <= the gid, so a tile
    # from a removed tileset silently resolves to the tileset BELOW and
    # paints the wrong art. Refusing is the only way that becomes visible.
    IN_USE = (
        b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
        b'<map version="1.2" width="4" height="2" tilewidth="16"'
        b' tileheight="16" nextlayerid="3" nextobjectid="2">\r\n'
        b'\t<tileset firstgid="1" name="Lower" tilewidth="16" tileheight="16"'
        b' tilecount="12" columns="4">\r\n'
        b'\t\t<image source="sheet.png" width="64" height="48"/>\r\n'
        b'\t</tileset>\r\n'
        b'\t<tileset firstgid="13" name="Upper" tilewidth="16" tileheight="16"'
        b' tilecount="12" columns="4">\r\n'
        b'\t\t<image source="sheet.png" width="64" height="48"/>\r\n'
        b'\t</tileset>\r\n'
        b'\t<layer id="1" name="Floor" width="4" height="2">\r\n'
        b'\t\t<data encoding="csv">\r\n'
        b'0,0,0,0,\r\n'
        b'0,14,0,2147483661\r\n'      # 14, and 13 with the horizontal-flip bit
        b'</data>\r\n'
        b'\t</layer>\r\n'
        b'\t<objectgroup id="2" name="entity">\r\n'
        b'\t\t<object id="1" gid="15" x="0" y="16" width="16" height="16"/>\r\n'
        b'\t</objectgroup>\r\n'
        b'</map>\r\n'
    )
    used = MapDocument.from_bytes(IN_USE, path=os.path.join(scratch, "used.tmx"))
    expect("the fixture round trips untouched", used.to_bytes(), IN_USE)

    expect("tiles_using_tileset finds the plain and the flipped gid",
           used.tiles_using_tileset("Upper"),
           [("Floor", 1, 1, 14), ("Floor", 3, 1, 2147483661)])
    expect("the flip flags are masked off before the range test, not after",
           2147483661 & 0x1FFFFFFF, 13)
    expect("objects_using_tileset finds the tile object",
           used.objects_using_tileset("Upper"), [("entity", 1, 15)])
    expect("the untouched tileset reports no users",
           (used.tiles_using_tileset("Lower"), used.objects_using_tileset("Lower")),
           ([], []))

    raises("removing a tileset still in use is refused", PyoneerConfigError,
           lambda: used.remove_tileset("Upper"),
           contains="still reference it")
    raises("and the refusal names the layers and counts", PyoneerConfigError,
           lambda: used.remove_tileset("Upper"), contains="Floor x2, entity x1")
    raises("and explains that renumbering is not the fix", PyoneerConfigError,
           lambda: used.remove_tileset("Upper"), contains="wrong art")
    expect("the refusal left the document alone", used.to_bytes(), IN_USE)

    expect("an UNUSED tileset removes without force",
           used.remove_tileset("Lower"), True)
    expect("which leaves a legal firstgid hole",
           [r.first_gid for r in used.tilesets()], [13])
    expect("removal did NOT renumber the survivor",
           used.serialize_tileset(13)["first_gid"], "13")
    # Put Lower back from a payload assembled BY HAND rather than by
    # serialize_tileset, so restore_tileset is measured against the payload
    # SHAPE a command would persist and reload, not just against whatever
    # this module happened to hand itself a moment ago.
    lower_payload = {"xml": '<tileset firstgid="1" name="Lower" tilewidth="16"'
                            ' tileheight="16" tilecount="12" columns="4">\n\t\t'
                            '<image source="sheet.png" width="64" height="48"/>\n\t'
                            '</tileset>',
                     "index": 0, "tail": "\n\t", "prev_tail": None,
                     "parent_text": "\n\t", "first_gid": "1", "name": "Lower"}
    expect("a hand-built payload restores just like a serialized one",
           used.restore_tileset(lower_payload), "Lower")
    expect("and the bytes come back", used.to_bytes(), IN_USE)

    expect("force=True removes it anyway, for a caller that zeroed the gids",
           used.remove_tileset("Upper", force=True), True)
    expect("the orphaned gids are still there -- clearing them is the "
           "caller's job", used.tile_layer("Floor").get_tile(1, 1), 14)

    # ----------------------------------------------------------------------
    print()
    print("the odd shapes: no whitespace at all, and an external tileset")
    # ----------------------------------------------------------------------
    # A document written with no whitespace must come back with none. This
    # is what makes the root.text restore unconditional rather than
    # "restore it if it looked like an indent".
    TIGHT = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
             b'<map version="1.2" width="1" height="1" tilewidth="16"'
             b' tileheight="16"><layer id="1" name="F" width="1" height="1">'
             b'<data encoding="csv">0</data></layer></map>')
    tight = MapDocument.from_bytes(TIGHT, path=os.path.join(scratch, "tight.tmx"))
    expect("the tight fixture round trips untouched", tight.to_bytes(), TIGHT)
    tight.add_tileset("T", "sheet.png", image_width=64, image_height=48)
    expect("add + remove on a whitespace-free document is byte identical",
           (tight.remove_tileset("T"), tight.to_bytes())[1], TIGHT)

    EXTERNAL = (
        b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
        b'<map version="1.2" width="1" height="1" tilewidth="16" tileheight="16">\r\n'
        b'\t<tileset firstgid="1" source="shared.tsx"/>\r\n'
        b'\t<tileset firstgid="9" name="Embedded" tilewidth="16"'
        b' tileheight="16" tilecount="12" columns="4">\r\n'
        b'\t\t<image source="sheet.png" width="64" height="48"/>\r\n'
        b'\t</tileset>\r\n'
        b'</map>\r\n'
    )
    external = MapDocument.from_bytes(EXTERNAL, path=os.path.join(scratch, "ext.tmx"))
    expect("the external fixture round trips untouched",
           external.to_bytes(), EXTERNAL)
    ext_ref = external.tilesets()[0]
    expect("an external tileset is flagged", ext_ref.is_external, True)
    expect("it names its .tsx", ext_ref.source, "shared.tsx")
    # It has NO name in this file, which is exactly why lookup takes a
    # firstgid as well as a name.
    expect("it has no name here", ext_ref.name, "")
    expect("tileset_names() reports the gap honestly",
           external.tileset_names(), ["", "Embedded"])
    expect("it claims no gids, because this file cannot see its tilecount",
           (ext_ref.tile_count, ext_ref.holds(1)), (0, False))
    expect("and it says so, rather than only answering False",
           ext_ref.extent_known, False)
    expect("firstgid lookup reaches it", external.tileset(1).source, "shared.tsx")

    # An UNKNOWN extent is not an empty one. `holds()` returns False either
    # way, and every guard built on it collapses into a confident wrong
    # answer: next_tileset_firstgid hands back a gid the external sheet
    # already owns, and the orphan scan reports "unused" for a tileset with
    # live references. pytmx resolves a gid to the highest firstgid at or
    # below it, so the newcomer wins and every tile silently repaints.
    #
    # The first version of this check asserted the broken behaviour was
    # correct -- "tiles_using_tileset on an external one is empty, not a
    # crash" -- which is how a guard gets pinned open.
    expect_raises("choosing a firstgid refuses rather than guessing",
                  PyoneerConfigError, external.next_tileset_firstgid)
    expect_raises("scanning for users refuses too", PyoneerConfigError,
                  lambda: external.tiles_using_tileset(1))
    expect_raises("and so does scanning tile objects", PyoneerConfigError,
                  lambda: external.objects_using_tileset(1))
    expect_raises("so a tileset cannot be appended into the ambiguity",
                  PyoneerConfigError,
                  lambda: external.add_tileset("New", "new.png",
                                               tile_width=16, tile_height=16,
                                               image_width=64, image_height=64))
    # ----------------------------------------------------------------------
    print()
    print("interior indentation is COPIED from a sibling, not recomputed")
    # ----------------------------------------------------------------------
    # add_tileset copies the <image> indent off an existing <tileset> rather
    # than deriving it. On the shipped map those two agree by coincidence --
    # the interior indent is exactly twice the root indent, which is what
    # _child_indent computes anyway -- so every other fixture in this file
    # passes with the copy deleted. This one does not agree: the root indent
    # is ONE space and the interior is FOUR, so a recomputed indent writes
    # two spaces and the new tileset fails to line up with its neighbour.
    ODD = (
        b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
        b'<map version="1.10" tiledversion="1.10.2" orientation="orthogonal"'
        b' renderorder="right-down" width="2" height="2" tilewidth="16"'
        b' tileheight="16" infinite="0" nextlayerid="2" nextobjectid="1">\r\n'
        b' <tileset firstgid="1" name="Odd" tilewidth="16" tileheight="16"'
        b' tilecount="4" columns="2">\r\n'
        b'    <image source="odd.png" width="32" height="32"/>\r\n'
        b' </tileset>\r\n'
        b' <layer id="1" name="Floor" width="2" height="2">\r\n'
        b'  <data encoding="csv">\r\n0,0,\r\n0,0\r\n</data>\r\n'
        b' </layer>\r\n'
        b'</map>\r\n'
    )
    odd = MapDocument.from_bytes(ODD, path="odd.tmx")
    expect("the odd-indent fixture round-trips before any edit",
           odd.to_bytes(), ODD)
    odd.add_tileset("Second", "second.png", tile_width=16, tile_height=16,
                    image_width=32, image_height=32)
    written = odd.to_bytes()
    expect("the new tileset's image copies the sibling's 4-space indent",
           b'\r\n    <image source="second.png"' in written, True)
    expect("and not the 2-space indent a computed one would produce",
           b'\r\n  <image source="second.png"' in written, False)
    odd.remove_tileset("Second")
    expect("and it still removes byte-identically", odd.to_bytes(), ODD)

    payload = external.serialize_tileset(1)
    expect_raises("and removal refuses, because 'unused' is unknowable",
                  PyoneerConfigError, lambda: external.remove_tileset(1))
    expect("an external tileset restores under an empty name",
           (external.remove_tileset(1, force=True),
            external.restore_tileset(payload))[1], "")
    expect("and its self-closing form survives", external.to_bytes(), EXTERNAL)

    # ----------------------------------------------------------------------
    print()
    print("a tileset grows by ROWS into headroom, and no placed gid moves")
    # ----------------------------------------------------------------------
    # Two tilesets, painted cells in BOTH, and a reserved gid hole between
    # them. This is the fixture the whole growth model has to survive: if a
    # grow silently renumbers anything, the Props gids below change meaning
    # and the map paints the wrong art with nothing raised.
    #
    # BOTH tilesets are painted through a FLIPPED gid (0x80000000 | local),
    # and Props is painted through a tile object as well -- the half that
    # lives in an attribute and never appears in any <data>. The flips are
    # what make the counting assertions discriminating: unmasked, Ground's
    # 2147483652 reads as a number far ABOVE Props' firstgid, so a scan that
    # forgot to mask would report one more cell than a renumber touches.
    GROWTH = (
        b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
        b'<map version="1.2" orientation="orthogonal" renderorder="right-down"'
        b' width="2" height="2" tilewidth="16" tileheight="16" infinite="0"'
        b' nextlayerid="3" nextobjectid="2">\r\n'
        b'\t<tileset firstgid="1" name="Ground" tilewidth="16" tileheight="16"'
        b' tilecount="4" columns="2">\r\n'
        b'\t\t<image source="ground.png" width="32" height="32"/>\r\n'
        b'\t</tileset>\r\n'
        b'\t<tileset firstgid="101" name="Props" tilewidth="16"'
        b' tileheight="16" tilecount="4" columns="2">\r\n'
        b'\t\t<image source="props.png" width="32" height="32"/>\r\n'
        b'\t</tileset>\r\n'
        b'\t<layer id="1" name="Floor" width="2" height="2">\r\n'
        b'\t\t<data encoding="csv">\r\n'
        b'1,2147483652,\r\n101,2147483752\r\n'
        b'</data>\r\n'
        b'\t</layer>\r\n'
        b'\t<objectgroup id="2" name="entity">\r\n'
        b'\t\t<object id="1" gid="104" x="0" y="16" width="16" height="16"/>\r\n'
        b'\t</objectgroup>\r\n'
        b'</map>\r\n'
    )
    for stem, size in (("ground", (32, 32)), ("props", (32, 32)),
                       ("ground_tall", (32, 48)), ("ground_wide", (48, 32))):
        with open(os.path.join(scratch, stem + ".png"), "wb") as handle:
            handle.write(png_bytes(*size))
    GROW_PATH = os.path.join(scratch, "growth.tmx")
    with open(GROW_PATH, "wb") as handle:
        handle.write(GROWTH)

    def painted(doc):
        """Every placed gid in the map: csv cells and tile objects both.

        Raw, flip flags intact. This is the value the whole section
        compares -- "no placed gid moved" is a statement about these
        numbers, and about nothing else.
        """
        cells = {name: doc.tile_layer(name).gids() for name in doc.tile_layer_names()}
        objects = [(int(element.get("id", "0")), int(element.get("gid", "0")))
                   for group in doc.root.iter("objectgroup")
                   for element in group.findall("object")]
        return cells, objects

    grower = MapDocument.load(GROW_PATH)
    expect("the growth fixture round trips before any edit",
           grower.to_bytes(), GROWTH)
    BEFORE = painted(grower)
    expect("both tilesets are painted, one of them through a flip bit",
           BEFORE, ({"Floor": [1, 2147483652, 101, 2147483752]}, [(1, 104)]))
    expect("Ground's headroom is the hole under Props",
           grower.tileset_headroom("Ground"), 96)
    expect("the top tileset's headroom runs to the flip bits, not to 2**31",
           grower.tileset_headroom("Props"), 0x1FFFFFFF - 104)

    previous = grower.grow_tileset("Ground", image_source="ground_tall.png")
    expect("grow returns the four values it replaced", previous,
           {"image": "ground.png", "image_width": 32, "image_height": 32,
            "tile_count": 4})
    expect("the sheet grew by one row", grower.tileset("Ground").tile_count, 6)
    expect("its column count did not move", grower.tileset("Ground").columns, 2)
    expect("NOT ONE PLACED GID MOVED", painted(grower), BEFORE)
    expect("the headroom shrank by exactly the tiles claimed",
           grower.tileset_headroom("Ground"), 94)

    grown_bytes = grower.to_bytes()
    span = diff_span(GROWTH, grown_bytes)
    expect("the diff is confined to the Ground <tileset> element",
           (span[0] > GROWTH.index(b'<tileset firstgid="1"'),
            span[1] < GROWTH.index(b"</tileset>")), (True, True))
    expect("the new tile count is written",
           b'tilecount="6" columns="2"' in grown_bytes, True)
    expect("the new sheet and its measured size are written",
           b'<image source="ground_tall.png" width="32" height="48"/>'
           in grown_bytes, True)
    expect("no lone LF was introduced",
           grown_bytes.count(b"\r\n"), grown_bytes.count(b"\n"))

    grower.grow_tileset("Ground", image_source=previous["image"],
                        image_width=previous["image_width"],
                        image_height=previous["image_height"],
                        tile_count=previous["tile_count"])
    expect("the four returned values ARE the inverse, byte for byte",
           grower.to_bytes(), GROWTH)

    # ----------------------------------------------------------------------
    print()
    print("...and every way of growing that would repaint the map is refused")
    # ----------------------------------------------------------------------
    raises("a WIDER sheet is refused: it renumbers every id after row 0",
           PyoneerConfigError,
           lambda: grower.grow_tileset("Ground", image_source="ground_wide.png"),
           contains="renumbers every tile after the first row")
    raises("growing into the tileset above is refused by name",
           PyoneerConfigError,
           lambda: grower.grow_tileset("Ground", image_width=32,
                                       image_height=816, tile_count=101),
           contains="already owned by Props at 101-104")
    exceeded = None
    try:
        grower.grow_tileset("Ground", image_width=32, image_height=816,
                            tile_count=101)
    except PyoneerConfigError as exc:
        exceeded = str(exc)
    expect("the refusal quotes the room this tileset does have",
           "room for 96 more tiles" in (exceeded or ""), True)
    # The number a caller needs in order to decide, counted rather than
    # estimated -- and counted through the flip mask and the tile objects,
    # which is what makes it 3 and not 1.
    expect("and what renumbering the survivors would cost, in painted gids",
           "renumber 3 painted gid(s) (Floor x2, entity x1)" in (exceeded or ""),
           True)

    raises("truncating over a painted cell is refused",
           PyoneerConfigError,
           lambda: grower.grow_tileset("Ground", tile_count=3),
           contains="still point at gids 4-4 (Floor x1)")
    raises("...and the flipped gid and the tile object are both counted",
           PyoneerConfigError,
           lambda: grower.grow_tileset("Props", tile_count=3),
           contains="2 tile(s) still point at gids 104-104")
    expect("no refusal changed a single byte", grower.to_bytes(), GROWTH)

    # Truncation is not banned, only truncation over live gids: grow, then
    # take the empty rows straight back. This is the "resizable and
    # truncatable" half of the ask, and it has to be provably reachable or
    # the guard above is just a ban.
    grower.grow_tileset("Ground", image_source="ground_tall.png")
    expect("the grown rows are empty, so truncating them back is allowed",
           (grower.grow_tileset("Ground", image_source="ground.png",
                                tile_count=4),
            grower.to_bytes())[1], GROWTH)

    raises("a count the sheet cannot hold is refused",
           PyoneerConfigError,
           lambda: grower.grow_tileset("Ground", tile_count=5),
           contains="holds 4")
    raises("a count of zero is refused; removal is the verb for that",
           PyoneerConfigError,
           lambda: grower.grow_tileset("Ground", tile_count=0),
           contains="remove it instead")
    expect_raises("an unknown tileset raises rather than growing nothing",
                  KeyError, lambda: grower.grow_tileset("Nope", tile_count=2))

    spaced = MapDocument.from_bytes(
        GROWTH.replace(b'name="Ground" tilewidth="16" tileheight="16"',
                       b'name="Ground" tilewidth="16" tileheight="16"'
                       b' spacing="2"'),
        path=GROW_PATH)
    raises("a margin/spacing sheet is refused: the readers disagree on columns",
           PyoneerConfigError,
           lambda: spaced.grow_tileset("Ground", tile_count=2),
           contains="only agree on a tileset's column count at 0/0")

    collection = MapDocument.from_bytes(
        GROWTH.replace(b'\t\t<image source="ground.png" width="32" height="32"/>',
                       b'\t\t<tile id="0">\r\n'
                       b'\t\t\t<image source="a.png" width="16" height="16"/>\r\n'
                       b'\t\t</tile>'),
        path=GROW_PATH)
    raises("a collection-of-images tileset is refused, naming its shape",
           PyoneerConfigError,
           lambda: collection.grow_tileset("Ground", tile_count=2),
           contains="collection of images")

    padded = MapDocument.from_bytes(GROWTH.replace(b'tilecount="4" columns="2">\r\n'
                                                   b'\t\t<image source="ground.png"',
                                                   b'tilecount="04" columns="2">\r\n'
                                                   b'\t\t<image source="ground.png"'),
                                    path=GROW_PATH)
    raises("an integer the inverse could not respell is refused",
           PyoneerConfigError,
           lambda: padded.grow_tileset("Ground", tile_count=2),
           contains="not spelled the way this edit writes an integer back")

    mismatched = MapDocument.from_bytes(
        GROWTH.replace(b'name="Ground" tilewidth="16" tileheight="16"'
                       b' tilecount="4" columns="2"',
                       b'name="Ground" tilewidth="16" tileheight="16"'
                       b' tilecount="4" columns="4"'),
        path=GROW_PATH)
    raises("a declared stride the sheet contradicts is refused",
           PyoneerConfigError,
           lambda: mismatched.grow_tileset("Ground", tile_count=4),
           contains="already disagree about this tileset's stride")

    raises("an external tileset cannot be grown", PyoneerConfigError,
           lambda: external.grow_tileset(1, tile_count=4),
           contains="live in the .tsx")
    raises("...and its unknown extent makes headroom unknowable too",
           PyoneerConfigError, lambda: external.tileset_headroom(1),
           contains="do not declare their extent")

    # ----------------------------------------------------------------------
    print()
    print("headroom is bought at add time, and spent by growth later")
    # ----------------------------------------------------------------------
    # The whole point of the model: `add_tileset` already accepts a firstgid
    # ABOVE the packed one, so a map can be authored with a reserved hole
    # under every range. Growth then costs zero cell rewrites instead of the
    # whole-map renumber the refusal above prices.
    reserved = MapDocument.from_bytes(NO_LAYERS,
                                      path=os.path.join(scratch, "reserved.tmx"))
    expect("packed, the only tileset's headroom runs to the top of the space",
           reserved.tileset_headroom("Only"), 0x1FFFFFFF - 12)
    reserved.add_tileset("Above", "ground.png", first_gid=1025,
                         image_width=32, image_height=32)
    expect("a reserved firstgid leaves a hole beneath it",
           reserved.tileset_headroom("Only"), 1012)
    expect("and the next append lands above the reservation, not inside it",
           reserved.next_tileset_firstgid(), 1029)
    expect("growing all the way into the hole is free", (
        reserved.grow_tileset("Only", image_width=64, image_height=4096,
                              tile_count=1024),
        reserved.tileset("Only").last_gid)[1], 1024)
    expect("which spends the headroom exactly",
           reserved.tileset_headroom("Only"), 0)
    raises("one tile past it is refused, and says how much room there was",
           PyoneerConfigError,
           lambda: reserved.grow_tileset("Only", image_width=64,
                                         image_height=4112, tile_count=1025),
           contains="room for 0 more tiles")

    # ----------------------------------------------------------------------
    print()
    print("a tileset is nameable, and renaming moves no gid")
    # ----------------------------------------------------------------------
    expect("rename returns the name it replaced",
           grower.rename_tileset("Ground", "Village exteriors"), "Ground")
    expect("the new name addresses it",
           grower.tileset("Village exteriors").first_gid, 1)
    expect("NOT ONE PLACED GID MOVED", painted(grower), BEFORE)
    expect("only the name attribute changed",
           grower.to_bytes(),
           GROWTH.replace(b'name="Ground"', b'name="Village exteriors"'))
    expect("renaming back is byte identical",
           (grower.rename_tileset("Village exteriors", "Ground"),
            grower.to_bytes())[1], GROWTH)
    expect("renaming to the name it already has is a no-op",
           (grower.rename_tileset("Ground", "Ground"),
            grower.to_bytes())[1], GROWTH)
    raises("a duplicate name is refused: the name is an address",
           PyoneerConfigError,
           lambda: grower.rename_tileset("Ground", "Props"),
           contains="already has a tileset named 'Props'")
    raises("an empty name is refused for the same reason",
           PyoneerConfigError, lambda: grower.rename_tileset("Ground", ""),
           contains="a tileset needs a name")
    raises("an external tileset has no name here to rename",
           PyoneerConfigError, lambda: external.rename_tileset(1, "Named"),
           contains="carries no name in this file")
    expect_raises("renaming a tileset that is not there raises", KeyError,
                  lambda: grower.rename_tileset("Nope", "Whatever"))
    expect("no refusal changed a single byte", grower.to_bytes(), GROWTH)

    # ----------------------------------------------------------------------
    print()
    print("warnings fire where a silent success would be a lie")
    # ----------------------------------------------------------------------
    warn_path = os.path.join(scratch, "warn.tmx")
    with open(warn_path, "wb") as handle:
        handle.write(NO_TILESETS)
    warned = MapDocument.load(warn_path)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warned.add_tileset("Missing", "nowhere.png",
                           image_width=64, image_height=48)
        messages = [str(w.message) for w in caught]
    expect("a missing image file warns rather than raising",
           any("does not exist relative to the map" in m for m in messages), True)
    warned.remove_tileset("Missing")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warned.add_tileset("Spaced", "sheet.png", margin=1, spacing=2,
                           image_width=64, image_height=48)
        messages = [str(w.message) for w in caught]
    expect("margin/spacing warns that the three readers disagree",
           any("only agree on tile geometry at 0/0" in m for m in messages), True)
    body = warned.to_bytes()
    expect("spacing and margin serialize in Tiled's order",
           b'tileheight="16" spacing="2" margin="1" tilecount=' in body, True)
    warned.remove_tileset("Spaced")
    expect("and removing the spaced tileset is byte identical",
           warned.to_bytes(), NO_TILESETS)
    expect("zero margin/spacing are omitted, as Tiled omits them",
           (warned.add_tileset("Plain", "sheet.png", image_width=64,
                               image_height=48),
            b'spacing=' in warned.to_bytes())[1], False)

finally:
    shutil.rmtree(scratch, ignore_errors=True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
