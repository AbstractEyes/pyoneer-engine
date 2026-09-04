"""Verify the tileset verbs: exact inverses, and a refusal that survives.

`MapDocument` already knows how to add, remove and restore a tileset, and
`tools/check_tileset.py` measures that against bytes. This file measures the
layer above it -- the three commands that let the editor reach any of it --
and it exists because a verb can get all three of these wrong while still
looking correct in the history panel:

    the inverse is built from SERIALIZED STATE, not from attributes
        A `<tileset>` may carry `<tile>` children -- animations, terrains,
        per-tile collision shapes. An inverse rebuilt from a TilesetRef's
        ten attributes would put back a plausible tileset with all of that
        silently gone. The byte assertions below are what catch it.

    the refusal is not swallowed
        Removing a tileset that tiles still point into raises NOWHERE at
        runtime: pytmx sorts firstgids descending and resolves an orphan to
        the tileset BELOW it, so the map loads and paints the wrong art.
        MapDocument refuses and names the layers and counts. A verb that
        caught that to make the UI tidier would turn a loud stop into a
        silent corruption.

    force=True stays paired with zeroing
        It is correct in one situation only -- the gids were cleared
        earlier in the SAME transaction -- and the pattern is asserted here
        end to end, including that undo puts the tileset back BEFORE it
        puts the gids back.

WHAT IS FIXTURE AND WHAT IS NOT
-------------------------------
data/maps/starter.tmx is the live, shipped map. It is used here for
exactly one thing: a COPY of it is the byte-identity target for add/undo,
and nothing below asserts what it contains. Every map whose CONTENT is
tested -- painted gids, tile objects, an external tileset -- is built in
this file.

    .venv/Scripts/python.exe tools/check_tileset_verbs.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import importlib.util
import json
import os
import shutil
import struct
import sys
import tempfile
import warnings
import zlib

from editor.core.collision import (
    BLOCK_ALL,
    DEFAULTS_PROPERTY,
    NO_DATA,
    PASS_ALL,
    STAR,
    Blitmask,
)
from editor.core.layers import BLOCK_LEFT, BLOCK_RIGHT
from editor.core.commands import Command, verb, verb_names
from editor.core.errors import (
    PyoneerCommandApplyError,
    PyoneerCommandArgumentError,
)
from editor.core.scope import Scope
from editor.core.session import Session
from scripts.core.collision_runtime import field_from_map
from scripts.core.errors import PyoneerConfigError
from scripts.loaders.map_document import tileset_geometry

REPO = _bootstrap.REPO_ROOT
failures: list[str] = []


def brief(value) -> str:
    """A repr that will not dump 130KB of csv into the check output."""
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>" if len(value) > 60 else repr(value)
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={brief(got)} want={brief(want)}")
    if not ok:
        failures.append(label)


def raises(label, exc_type, fn, contains: str | None = None):
    """Assert `fn` refuses, and optionally that the message SAYS WHY.

    The `contains` half carries most of the weight. A refusal whose message
    does not name the tiles blocking it is a dead end for whoever hits it,
    and "it raised something" keeps passing long after the explanation has
    rotted away.
    """
    try:
        fn()
    except exc_type as exc:
        if contains is not None and contains not in str(exc):
            print(f"  FAIL {label:<58} message lacks {contains!r}")
            print(f"        {str(exc).splitlines()[0][:100]}")
            failures.append(label)
            return None
        print(f"  ok   {label:<58} {type(exc).__name__}")
        return exc
    except Exception as exc:                                    # noqa: BLE001
        print(f"  FAIL {label:<58} raised {type(exc).__name__}: {exc}")
        failures.append(label)
        return None
    print(f"  FAIL {label:<58} did not raise {exc_type.__name__}")
    failures.append(label)
    return None


def png_bytes(width: int, height: int) -> bytes:
    """A real, decodable 8-bit RGB PNG.

    Real rather than a 24-byte header stub, because QImage in the dialog
    half of this file has to DECODE it, not just measure it.
    """
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x40\x80\xc0" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# A map that PAINTS with its tilesets, so the orphan guard has something to
# guard. Lower owns 1-12, Upper owns 13-24. The Floor layer holds gid 14 and
# gid 13 with the horizontal-flip bit set, and the entity layer holds a tile
# object at gid 15 -- the half of the problem that is easy to forget, since
# an object's gid lives in an attribute and never appears in any <data>.
#
# The `<tile>` child on Upper is the trap detector: it is the part of a
# tileset that an inverse rebuilt from attributes cannot reproduce.
IN_USE = (
    b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
    b'<map version="1.2" orientation="orthogonal" renderorder="right-down"'
    b' width="4" height="2" tilewidth="16" tileheight="16"'
    b' nextlayerid="3" nextobjectid="2">\r\n'
    b'\t<tileset firstgid="1" name="Lower" tilewidth="16" tileheight="16"'
    b' tilecount="12" columns="4">\r\n'
    b'\t\t<image source="sheet.png" width="64" height="48"/>\r\n'
    b'\t</tileset>\r\n'
    b'\t<tileset firstgid="13" name="Upper" tilewidth="16" tileheight="16"'
    b' tilecount="12" columns="4">\r\n'
    b'\t\t<image source="sheet.png" width="64" height="48"/>\r\n'
    b'\t\t<tile id="2">\r\n'
    b'\t\t\t<animation>\r\n'
    b'\t\t\t\t<frame tileid="2" duration="120"/>\r\n'
    b'\t\t\t\t<frame tileid="3" duration="120"/>\r\n'
    b'\t\t\t</animation>\r\n'
    b'\t\t</tile>\r\n'
    b'\t</tileset>\r\n'
    b'\t<layer id="1" name="Floor" width="4" height="2">\r\n'
    b'\t\t<data encoding="csv">\r\n'
    b'0,0,0,0,\r\n'
    b'0,14,0,2147483661\r\n'
    b'</data>\r\n'
    b'\t</layer>\r\n'
    b'\t<objectgroup id="2" name="entity">\r\n'
    b'\t\t<object id="1" gid="15" x="0" y="16" width="16" height="16"/>\r\n'
    b'\t</objectgroup>\r\n'
    b'</map>\r\n'
)

# An EXTERNAL tileset: no name, no tilecount, no image in this file. It is
# the reason every tileset verb addresses by firstgid as well as by name.
EXTERNAL = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<map version="1.2" orientation="orthogonal" renderorder="right-down"'
    b' width="2" height="1" tilewidth="16" tileheight="16"'
    b' nextlayerid="2" nextobjectid="1">\n'
    b' <tileset firstgid="1" source="outside.tsx"/>\n'
    b' <layer id="1" name="Floor" width="2" height="1">\n'
    b'  <data encoding="csv">\n'
    b'0,0\n'
    b'</data>\n'
    b' </layer>\n'
    b'</map>\n'
)

# A map whose tileset ALREADY declares its masks, with an author-written
# sidecar beside it. It is the other half of the mask verbs' invariant: on
# this map a set must change the FILE and leave the .tmx alone, where on
# `used` it must do both. The sidecar is deliberately SHORT -- two rows of a
# three-row sheet, which `tileset_defaults` documents as legal -- and carries
# a metadata key nothing in the engine reads, so a verb that rebuilt the file
# from a TilesetDefaults instead of editing the one on disk would lose it.
#
# It also carries a COMPANION layer, because "the level the engine stacks
# UNDER every companion, so a painted cell still wins" is a sentence
# map.tileset.mask.set's summary says to whoever is reading COMMANDS.md, and
# a sentence a generated document states is a sentence something has to
# measure. Both cells hold the same masked tile; only the left one is painted
# over.
MASKED = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<map version="1.2" orientation="orthogonal" renderorder="right-down"'
    b' width="2" height="1" tilewidth="16" tileheight="16"'
    b' nextlayerid="3" nextobjectid="1">\n'
    b' <tileset firstgid="1" name="Art" tilewidth="16" tileheight="16"'
    b' tilecount="12" columns="4">\n'
    b'  <properties>\n'
    b'   <property name="pyoneer_collision" value="Art.blitmask"/>\n'
    b'  </properties>\n'
    b'  <image source="sheet.png" width="64" height="48"/>\n'
    b' </tileset>\n'
    b' <tileset firstgid="13" name="collision" tilewidth="16" tileheight="16"'
    b' tilecount="17" columns="17">\n'
    b'  <image source="Collision.png" width="272" height="16"/>\n'
    b' </tileset>\n'
    b' <layer id="1" name="Floor" width="2" height="1">\n'
    b'  <data encoding="csv">\n'
    b'3,3\n'
    b'</data>\n'
    b' </layer>\n'
    b' <layer id="2" name="FloorCollision" width="2" height="1">\n'
    b'  <data encoding="csv">\n'
    b'13,0\n'
    b'</data>\n'
    b' </layer>\n'
    b'</map>\n'
)

# A map with a RESERVED GID HOLE: Lower owns 1-12, Upper starts at 101, and
# the 88 gids between them belong to nobody. That hole is what makes growth
# free -- Lower can claim any of it without moving one csv token, and cannot
# claim the 89th tile without moving Upper.
#
# Painted in BOTH ranges, and Lower's second cell carries the horizontal-flip
# bit. Unmasked, 2147483660 reads as a number far above Upper's firstgid, so
# a scan that forgot to mask reports one more cell than a renumber touches.
# The tile object is the other half that is easy to forget: its gid lives in
# an attribute and never appears in any <data>.
GROWABLE = (
    b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
    b'<map version="1.2" orientation="orthogonal" renderorder="right-down"'
    b' width="2" height="2" tilewidth="16" tileheight="16"'
    b' nextlayerid="3" nextobjectid="2">\r\n'
    b'\t<tileset firstgid="1" name="Lower" tilewidth="16" tileheight="16"'
    b' tilecount="12" columns="4">\r\n'
    b'\t\t<image source="sheet.png" width="64" height="48"/>\r\n'
    b'\t</tileset>\r\n'
    b'\t<tileset firstgid="101" name="Upper" tilewidth="16" tileheight="16"'
    b' tilecount="12" columns="4">\r\n'
    b'\t\t<image source="sheet.png" width="64" height="48"/>\r\n'
    b'\t</tileset>\r\n'
    b'\t<layer id="1" name="Floor" width="2" height="2">\r\n'
    b'\t\t<data encoding="csv">\r\n'
    b'1,2147483660,\r\n101,112\r\n'
    b'</data>\r\n'
    b'\t</layer>\r\n'
    b'\t<objectgroup id="2" name="entity">\r\n'
    b'\t\t<object id="1" gid="105" x="0" y="16" width="16" height="16"/>\r\n'
    b'\t</objectgroup>\r\n'
    b'</map>\r\n'
)

# Tile 2 (row 0, column 2) is the gid the Floor layer above paints, so this
# is a mask the engine really reads. Canonical spelling: `Blitmask.render`
# writes the magic, then size, then metadata in the order it was parsed.
AUTHORED_MASK = ("blitmask 1\n"
                 "size 4 2\n"
                 "kind tileset\n"
                 "firstgid 1\n"
                 "name Art\n"
                 "note hand-authored\n"
                 "..f.\n"
                 "....\n")

workspace = tempfile.mkdtemp(prefix="pyoneer_tileset_verbs_")
try:
    maps_dir = os.path.join(workspace, "data", "maps")
    graphics_dir = os.path.join(workspace, "data", "graphics")
    os.makedirs(maps_dir)
    os.makedirs(graphics_dir)
    os.makedirs(os.path.join(workspace, "config"))

    # Beside the maps, so `<image source="sheet.png">` resolves the way
    # Tiled resolves it and add_tileset's measuring path really runs.
    SHEET = os.path.join(maps_dir, "sheet.png")
    with open(SHEET, "wb") as handle:
        handle.write(png_bytes(64, 48))
    # And one a directory away, to prove the written path is relative to the
    # MAP and spelled with forward slashes.
    NESTED_SHEET = os.path.join(graphics_dir, "nested.png")
    with open(NESTED_SHEET, "wb") as handle:
        handle.write(png_bytes(32, 32))
    # The same width as sheet.png and one row taller. That is the only shape
    # map.tileset.grow accepts, because a local id is row * columns + column
    # and every reader takes the stride from the sheet's width.
    with open(os.path.join(maps_dir, "tall.png"), "wb") as handle:
        handle.write(png_bytes(64, 64))

    # The SHIPPED map, copied in. It is the workspace's own fixture from
    # here on and the workspace calls it "test"; nothing below writes back
    # to data/maps/starter.tmx.
    shutil.copy2(os.path.join(REPO, "data", "maps", "starter.tmx"),
                 os.path.join(maps_dir, "test.tmx"))
    with open(os.path.join(maps_dir, "used.tmx"), "wb") as handle:
        handle.write(IN_USE)
    with open(os.path.join(maps_dir, "external.tmx"), "wb") as handle:
        handle.write(EXTERNAL)
    with open(os.path.join(maps_dir, "masked.tmx"), "wb") as handle:
        handle.write(MASKED)
    with open(os.path.join(maps_dir, "growth.tmx"), "wb") as handle:
        handle.write(GROWABLE)
    AUTHORED = os.path.join(maps_dir, "Art.blitmask")
    with open(AUTHORED, "w", encoding="utf-8", newline="") as handle:
        handle.write(AUTHORED_MASK)
    with open(os.path.join(workspace, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [
            {"name": name, "identifier": name, "file": f"data/maps/{name}.tmx"}
            for name in ("test", "used", "external", "masked",
                         "growth")]}, handle)

    with open(os.path.join(maps_dir, "test.tmx"), "rb") as handle:
        ORIGINAL = handle.read()

    session = Session.open(workspace, genre_id="topdown_rpg")
    TEST = Scope.of(("map", "test"))
    USED = Scope.of(("map", "used"))
    EXT = Scope.of(("map", "external"))
    MASK = Scope.of(("map", "masked"))
    GROW = Scope.of(("map", "growth"))

    def document(name: str):
        return session.project.map(name)

    def tileset_state(name: str):
        """(name, firstgid, tilecount) per tileset, in document order."""
        return [(ref.name, ref.first_gid, ref.tile_count)
                for ref in document(name).tilesets()]

    def placed(name: str):
        """Every gid the map places: csv cells and tile objects both.

        Raw, flip flags intact. "No placed gid moved" is a claim about these
        numbers and about nothing else, so the growth assertions compare the
        whole structure rather than sampling one cell.
        """
        doc = document(name)
        return ({layer: doc.tile_layer(layer).gids()
                 for layer in doc.tile_layer_names()},
                [(int(element.get("id", "0")), int(element.get("gid", "0")))
                 for group in doc.root.iter("objectgroup")
                 for element in group.findall("object")])

    # ----------------------------------------------------------------------
    print("the vocabulary reaches the document's tileset half at all")
    # ----------------------------------------------------------------------
    # The gap this whole file closes: MapDocument grew add_tileset /
    # remove_tileset / serialize_tileset / restore_tileset and no verb named
    # any of them, so nothing in the editor -- human or AI -- could reach it.
    registered = [name for name in verb_names() if name.startswith("map.tileset.")]
    expect("every tileset verb is registered", registered,
           ["map.tileset.add", "map.tileset.grow", "map.tileset.mask.restore",
            "map.tileset.mask.set", "map.tileset.remove",
            "map.tileset.rename", "map.tileset.restore"])
    expect("they act on a map, not on a layer",
           [verb(n).scopes for n in registered],
           [("map:*",)] * len(registered))
    expect("remove is marked destructive", verb("map.tileset.remove").destructive, True)
    expect("force defaults to False, so the guard is opt-out",
           verb("map.tileset.remove").param("force").default, False)
    expect("a layer scope is refused by the scope check",
           any(Scope.parse("map:test/layer:Floor").matches(p)
               for p in verb("map.tileset.add").scopes), False)

    # ----------------------------------------------------------------------
    print()
    print("add: measured from the image, appended above every live gid")
    # ----------------------------------------------------------------------
    expect("the copy starts byte-identical", document("test").to_bytes(), ORIGINAL)
    appended_gid = document("test").next_tileset_firstgid()
    before_count = len(document("test").tilesets())

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        added = session.run(Command("map.tileset.add", TEST,
                                    {"name": "CheckSheet", "image": "sheet.png"}))
    ref = document("test").tileset("CheckSheet")
    expect("the tileset is there", ref.name, "CheckSheet")
    expect("appended above every existing range", ref.first_gid, appended_gid)
    expect("the 64x48 sheet measured itself into a 4x3 grid",
           (ref.columns, ref.tile_count, ref.tile_width, ref.tile_height),
           (4, 12, 16, 16))
    expect("one more tileset than before",
           len(document("test").tilesets()), before_count + 1)
    # Without this the byte assertion below would pass on a verb that did
    # nothing at all.
    expect("the file actually changed", document("test").to_bytes() == ORIGINAL, False)
    expect("the inverse is a remove that does NOT force",
           (added.inverses[0].verb, added.inverses[0].args),
           ("map.tileset.remove", {"name": "CheckSheet", "force": False}))

    session.undo()
    expect("undo removed it",
           "CheckSheet" in document("test").tileset_names(), False)
    expect("undo of add restores the BYTES",
           document("test").to_bytes(), ORIGINAL)

    session.redo()
    expect("redo puts it back at the same firstgid",
           document("test").tileset("CheckSheet").first_gid, appended_gid)
    session.undo()
    expect("and undo is still exact", document("test").to_bytes(), ORIGINAL)

    print()
    print("add: explicit geometry overrides the measurement")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        session.run(Command("map.tileset.add", TEST, {
            "name": "Spaced", "image": "sheet.png",
            "tile_width": 16, "tile_height": 16, "spacing": 2, "margin": 2,
            "image_width": 64, "image_height": 48}))
    spaced = document("test").tileset("Spaced")
    # (64-2-16)//18+1 = 3 across, (48-2-16)//18+1 = 2 down.
    expect("margin and spacing reach tileset_geometry",
           (spaced.columns, spaced.tile_count, spaced.margin, spaced.spacing),
           (3, 6, 2, 2))
    session.undo()
    expect("undo of the spaced add is byte-exact",
           document("test").to_bytes(), ORIGINAL)

    raises("a name already in the map is refused", PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.add", TEST, {
               "name": document("test").tileset_names()[0],
               "image": "sheet.png"})),
           contains="already has a tileset")
    expect("the refused add left the bytes alone",
           document("test").to_bytes(), ORIGINAL)

    # ----------------------------------------------------------------------
    print()
    print("remove and restore round-trip through the command stream")
    # ----------------------------------------------------------------------
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        session.run(Command("map.tileset.add", TEST,
                            {"name": "CheckSheet", "image": "sheet.png"}))
    added_bytes = document("test").to_bytes()
    added_payload = document("test").serialize_tileset("CheckSheet")

    removal = session.run(Command("map.tileset.remove", TEST,
                                  {"name": "CheckSheet"}))
    expect("nothing pointed at it, so no force was needed",
           "CheckSheet" in document("test").tileset_names(), False)
    expect("the inverse is a restore carrying the serialised element",
           removal.inverses[0].verb, "map.tileset.restore")
    expect("and the payload is the document's own, not a rebuild",
           removal.inverses[0].args["payload"], added_payload)

    session.undo()
    expect("undo of remove restores the tileset",
           document("test").tileset("CheckSheet").first_gid, appended_gid)
    expect("byte-for-byte, whitespace included",
           document("test").to_bytes(), added_bytes)
    session.undo()
    expect("and unwinding the add too returns the original file",
           document("test").to_bytes(), ORIGINAL)

    raises("removing a tileset that is not there names the ones that are",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.remove", TEST,
                                       {"name": "NeverExisted"})),
           contains="no tileset")
    unaddressed = raises(
        "addressing nothing at all is an argument error, not a guess",
        PyoneerCommandApplyError,
        lambda: session.run(Command("map.tileset.remove", TEST, {})),
        contains="first_gid")
    if unaddressed is not None:
        # An unaddressed remove must be the EDITOR's argument error, not the
        # document's -- "which tileset did you mean" is a question about the
        # command, and answering it with a config error would send whoever
        # hits it looking at the .tmx.
        expect("and it is the command layer that says so",
               PyoneerCommandArgumentError.__name__ in str(unaddressed), True)
    expect("neither refusal touched the file",
           document("test").to_bytes(), ORIGINAL)

    # ----------------------------------------------------------------------
    print()
    print("the refusal: a tileset with live gids does not come out quietly")
    # ----------------------------------------------------------------------
    expect("the fixture round trips before anything runs",
           document("used").to_bytes(), IN_USE)
    expect("the fixture declares two ranges",
           tileset_state("used"), [("Lower", 1, 12), ("Upper", 13, 12)])

    error = raises("removing a tileset that tiles point into is refused",
                   PyoneerCommandApplyError,
                   lambda: session.run(Command("map.tileset.remove", USED,
                                               {"name": "Upper"})),
                   contains="still reference it")
    if error is not None:
        # The verb must not reword the document's refusal. These three
        # strings are the entire reason a caller can act on it: what blocks
        # it, why it is not merely fussiness, and what to do instead.
        expect("the message survives the command layer: which layers",
               "Floor x2, entity x1" in str(error), True)
        expect("the message survives: why silence is the failure mode",
               "wrong art" in str(error), True)
        expect("the message survives: what to do instead",
               "map.tile.set_many" in str(error), True)
        expect("the original exception type is named on the way out",
               PyoneerConfigError.__name__ in str(error), True)
        expect("and the transaction rolled back cleanly", error.rolled_back, True)
    expect("the refused removal left the file untouched",
           document("used").to_bytes(), IN_USE)
    expect("and left no history behind", len(session.history()), 0)

    print()
    print("force=True is a real override, and that is why it needs pairing")
    forced = session.run(Command("map.tileset.remove", USED,
                                 {"name": "Upper", "force": True}))
    expect("force removes it anyway", tileset_state("used"), [("Lower", 1, 12)])
    expect("the gids it orphaned are STILL painted -- clearing them was the "
           "caller's job", document("used").tile_layer("Floor").get_tile(1, 1), 14)
    expect("the inverse is a restore, even for a forced removal",
           forced.inverses[0].verb, "map.tileset.restore")
    session.undo()
    expect("undo brings the whole element back", document("used").to_bytes(), IN_USE)
    # The `<tile>` child is what an inverse rebuilt from a TilesetRef's
    # attributes cannot reproduce: TilesetRef models ten numbers and no
    # children, so a rebuilt tileset comes back without its animation and
    # nothing says so.
    expect("including the <tile> animation an attribute rebuild would lose",
           len(document("used").tileset("Upper").element.findall("tile")), 1)

    print()
    print("the paired pattern: zero the gids and remove in ONE transaction")
    # This is the only shape in which force=True is correct, and the order
    # matters twice. Forward: the gids go to 0 before the tileset leaves.
    # Backward: the inverses run in reverse, so the tileset is restored
    # BEFORE the gids come back and never spends a moment orphaned.
    paired = session.run([
        Command("map.tile.set_many", USED.child("layer", "Floor"),
                {"tiles": [[1, 1, 0], [3, 1, 0]]}),
        Command("map.object.remove",
                USED.child("layer", "entity").child("object", "1")),
        Command("map.tileset.remove", USED, {"name": "Upper", "force": True}),
    ], label="replace tileset")
    expect("one transaction, three commands", len(paired.commands), 3)
    expect("the tileset is gone", tileset_state("used"), [("Lower", 1, 12)])
    expect("and nothing points into the hole it left",
           document("used").tile_layer("Floor").gids(), [0, 0, 0, 0, 0, 0, 0, 0])
    expect("undoing the whole transaction is byte-exact",
           (session.undo(), document("used").to_bytes())[1], IN_USE)

    print()
    print("after the pairing, the plain removal is no longer refused")
    session.run([
        Command("map.tile.set_many", USED.child("layer", "Floor"),
                {"tiles": [[1, 1, 0], [3, 1, 0]]}),
        Command("map.object.remove",
                USED.child("layer", "entity").child("object", "1")),
    ], label="clear the range")
    unforced = session.run(Command("map.tileset.remove", USED, {"name": "Upper"}))
    expect("the guard was about live references, not about the flag",
           tileset_state("used"), [("Lower", 1, 12)])
    session.undo()
    session.undo()
    expect("both transactions unwind to the original bytes",
           document("used").to_bytes(), IN_USE)
    expect("the unforced removal also inverted from serialized state",
           unforced.inverses[0].args["payload"]["name"], "Upper")

    # ----------------------------------------------------------------------
    print()
    print("an external tileset: no name, so firstgid is the only address")
    # ----------------------------------------------------------------------
    expect("the external fixture round trips",
           document("external").to_bytes(), EXTERNAL)
    expect("it declares no name in this file",
           document("external").tileset_names(), [""])

    raises("removing it by extent is refused -- the tilecount is in the .tsx",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.remove", EXT, {"first_gid": 1})),
           contains="unknowable here")
    expect("the refusal left the file alone",
           document("external").to_bytes(), EXTERNAL)

    external_removal = session.run(Command("map.tileset.remove", EXT,
                                           {"first_gid": 1, "force": True}))
    expect("force removes an external tileset", len(document("external").tilesets()), 0)
    inverse = external_removal.inverses[0]
    expect("its inverse restores from the payload", inverse.verb, "map.tileset.restore")
    session.undo()
    expect("undo of an external removal is byte-exact",
           document("external").to_bytes(), EXTERNAL)

    # restore's OWN inverse has to address a nameless tileset by firstgid,
    # or undoing a restore would be un-expressible as a command.
    payload = document("external").serialize_tileset(1)
    session.run(Command("map.tileset.remove", EXT, {"first_gid": 1, "force": True}))
    restored = session.run(Command("map.tileset.restore", EXT, {"payload": payload}))
    # force=True on a restore's inverse, where an add's inverse says False.
    # A restore returns the document to a state it was in a moment ago, so
    # the orphan guard has nothing to protect -- and an external tileset
    # keeps its extent in the .tsx, so without force the guard would refuse
    # to undo its own undo.
    expect("restore's inverse addresses the nameless tileset by firstgid",
           (restored.inverses[0].verb, restored.inverses[0].args),
           ("map.tileset.remove", {"first_gid": 1, "force": True}))
    session.undo()
    session.undo()
    expect("and the file is back", document("external").to_bytes(), EXTERNAL)

    raises("a payload with no first_gid is refused BEFORE it mutates anything",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.restore", EXT, {
               "payload": {"xml": '<tileset firstgid="1" source="outside.tsx"/>',
                           "index": 0, "tail": "\n "}})),
           contains="first_gid")
    expect("so the document never saw it",
           document("external").to_bytes(), EXTERNAL)

    # ----------------------------------------------------------------------
    print()
    print("tile masks: the verb writes the sidecar nobody could author here")
    # ----------------------------------------------------------------------
    # Level one of the collision stack -- a mask on the TILE, so stamping the
    # tile IS painting collision. The engine has read it since 6794bde; until
    # these two verbs the property had to be typed into the .tmx by hand and
    # the .blitmask written outside the editor entirely.

    def sidecar(name: str) -> str:
        return os.path.join(maps_dir, name)

    def sidecar_text(name: str) -> str | None:
        path = sidecar(name)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8", newline="") as handle:
            return handle.read()

    UPPER_MASK = "Upper.blitmask"

    expect("the fixture declares no masks anywhere",
           [DEFAULTS_PROPERTY in document("used").properties_of(ref.element)
            for ref in document("used").tilesets()], [False, False])
    expect("so the map bakes no passability at all -- level one is opt-in",
           field_from_map(document("used")), None)
    expect("and the sidecar this verb would write is not there",
           sidecar_text(UPPER_MASK), None)

    masked = session.run(Command("map.tileset.mask.set", USED,
                                 {"name": "Upper", "tile": 1, "mask": BLOCK_ALL}))
    expect("the sidecar was WRITTEN, sized to the sheet, without asking",
           sidecar_text(UPPER_MASK),
           "blitmask 1\nsize 4 3\nkind tileset\nfirstgid 13\nname Upper\n"
           ".f..\n....\n....\n")
    expect("the tileset now declares it, spelled beside the art",
           document("used").properties_of(
               document("used").tileset("Upper").element)[DEFAULTS_PROPERTY],
           UPPER_MASK)
    # Named after the TILESET and not after the sheet, which is the only
    # naming that survives two tilesets sharing one image: `to_blitmask`
    # stores the tileset's name in the file and `tileset_defaults` raises
    # when it disagrees with the tileset it is attached to.
    expect("the OTHER tileset over the same sheet is untouched",
           DEFAULTS_PROPERTY in document("used").properties_of(
               document("used").tileset("Lower").element), False)
    expect("the inverse carries the opinion and the reference it FOUND",
           (masked.inverses[0].verb, masked.inverses[0].args),
           ("map.tileset.mask.restore",
            {"name": "Upper", "first_gid": 0, "tile": 1, "mask": NO_DATA,
             "reference": ""}))

    print()
    print("...and the engine reads THAT file, end to end")
    field = field_from_map(document("used"))
    expect("the map now bakes a field where a moment ago it baked none",
           field is None, False)
    # gid 14 is Upper's tile 1, painted at (1, 1) by the fixture.
    expect("the cell holding that tile is blocked on all four sides",
           field.mask_at(1, 1), BLOCK_ALL)
    expect("and a cell holding no tile of that tileset is not",
           field.mask_at(0, 0), PASS_ALL)

    session.run(Command("map.tileset.mask.set", USED,
                        {"name": "Upper", "tile": 0, "mask": BLOCK_LEFT}))
    # The fixture paints gid 13 with the horizontal-flip bit at (3, 1). A
    # tileset default is a property of the TILE, so the flip has to mirror
    # it -- a mask that ignored flags makes the left half of a symmetrical
    # room walkable and the right half not.
    expect("a flipped stamp mirrors the tile's own mask",
           field_from_map(document("used")).mask_at(3, 1), BLOCK_RIGHT)

    session.undo()
    session.undo()
    expect("undo restores the .tmx byte for byte",
           document("used").to_bytes(), IN_USE)
    expect("the file is LEFT ON DISK -- a written file has no inverse",
           sidecar_text(UPPER_MASK) is None, False)
    expect("...holding no opinion about anything, which is what makes that "
           "safe", sidecar_text(UPPER_MASK),
           "blitmask 1\nsize 4 3\nkind tileset\nfirstgid 13\nname Upper\n"
           "....\n....\n....\n")
    expect("so the map bakes exactly what it baked before the verb ran",
           field_from_map(document("used")), None)

    session.redo()
    session.redo()
    expect("redo puts both masks back",
           (field_from_map(document("used")).mask_at(1, 1),
            field_from_map(document("used")).mask_at(3, 1)),
           (BLOCK_ALL, BLOCK_RIGHT))
    session.undo()
    session.undo()
    expect("and unwinding again is still byte-exact",
           document("used").to_bytes(), IN_USE)

    # ----------------------------------------------------------------------
    print()
    print("a tileset that already declares its masks: the .tmx must NOT move")
    # ----------------------------------------------------------------------
    expect("the authored sidecar round trips before anything runs",
           sidecar_text("Art.blitmask"), AUTHORED_MASK)
    authored_field = field_from_map(document("masked"))
    expect("and the engine reads the author's mask",
           authored_field.mask_at(1, 0), BLOCK_ALL)
    # The sentence map.tileset.mask.set's summary tells COMMANDS.md, measured
    # in both directions on one map: the left cell is painted over in the
    # companion and the right one is not, and the two hold the SAME tile. A
    # tileset level stacked above the companion, or one consulted only where
    # the companion is silent-by-emptiness, gets one of these two wrong.
    expect("a cell painted in the companion still beats the tile's own mask",
           authored_field.mask_at(0, 0), PASS_ALL)

    second = session.run(Command("map.tileset.mask.set", MASK,
                                 {"name": "Art", "tile": 1, "mask": STAR}))
    expect("the declaration was already there, so the .tmx did not change",
           document("masked").to_bytes(), MASKED)
    expect("only the cell moved, and every other byte of the file with it -- "
           "including a metadata key nothing reads",
           sidecar_text("Art.blitmask"),
           AUTHORED_MASK.replace("..f.\n", ".*f.\n"))
    expect("the inverse names the author's own spelling of the reference",
           second.inverses[0].args["reference"], "Art.blitmask")
    session.undo()
    expect("undo restores the sidecar byte for byte",
           sidecar_text("Art.blitmask"), AUTHORED_MASK)
    expect("and left the .tmx where it was throughout",
           document("masked").to_bytes(), MASKED)

    print()
    print("a short mask grows, and the growth is not undone -- deliberately")
    # Two rows of a three-row sheet is legal and documented; tile 9 is in the
    # row that does not exist yet.
    session.run(Command("map.tileset.mask.set", MASK,
                        {"name": "Art", "tile": 9, "mask": BLOCK_ALL}))
    expect("the row is added, no-data everywhere the author did not write",
           sidecar_text("Art.blitmask"),
           AUTHORED_MASK.replace("size 4 2", "size 4 3") + ".f..\n")
    session.undo()
    expect("undo restores the CELL, and the added row stays no-data",
           sidecar_text("Art.blitmask"),
           AUTHORED_MASK.replace("size 4 2", "size 4 3") + "....\n")
    # The claim that makes the previous line acceptable rather than sloppy.
    expect("which reads identically to the file the author wrote",
           [Blitmask.load(AUTHORED).at(x, y) for y in range(3) for x in range(4)],
           [Blitmask.parse(AUTHORED_MASK).at(x, y)
            for y in range(3) for x in range(4)])

    print()
    print("a sidecar present but UNDECLARED: undo has to take back both")
    # The narrow case the two-verb split exists for. The file is already
    # there, so the set MODIFIES it rather than creating it, and an undo that
    # only removed the property would leave the author's file edited with no
    # way back.
    LOWER_MASK = "Lower.blitmask"
    with open(sidecar(LOWER_MASK), "w", encoding="utf-8", newline="") as handle:
        handle.write("blitmask 1\nsize 4 3\nkind tileset\nname Lower\n"
                     "8...\n....\n....\n")
    before_lower = sidecar_text(LOWER_MASK)
    session.run(Command("map.tileset.mask.set", USED,
                        {"name": "Lower", "tile": 2, "mask": BLOCK_ALL}))
    expect("the existing file was edited, not replaced",
           sidecar_text(LOWER_MASK), before_lower.replace("8...", "8.f."))
    session.undo()
    expect("undo puts the cell back", sidecar_text(LOWER_MASK), before_lower)
    expect("AND takes the declaration back off", document("used").to_bytes(),
           IN_USE)

    # ----------------------------------------------------------------------
    print()
    print("mask refusals: every one leaves the file and the sidecar alone")
    # ----------------------------------------------------------------------
    def unchanged(label: str) -> None:
        expect(label + ": the .tmx is untouched",
               document("used").to_bytes(), IN_USE)

    raises("an external tileset has no extent, so no gid is knowably its own",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.mask.set", EXT,
                                       {"first_gid": 1, "tile": 0, "mask": 0})),
           contains="which gids it owns")
    expect("and it wrote nothing next to that map",
           document("external").to_bytes(), EXTERNAL)

    raises("a tile id past the end of the tileset is refused",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.mask.set", USED,
                                       {"name": "Upper", "tile": 12,
                                        "mask": 0})),
           contains="outside 0..11")
    unchanged("a tile id past the end")
    raises("a negative tile id too -- python would index from the other end",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.mask.set", USED,
                                       {"name": "Upper", "tile": -1,
                                        "mask": 0})),
           contains="outside 0..11")
    unchanged("a negative tile id")

    # `Blitmask.with_cell` refuses these too, three frames further in and as
    # a CONFIG error -- so pinning only "is not an opinion" would pass with
    # the verb's own guard deleted. The phrase below is the command layer's,
    # and it is the one that names the domain to whoever passed 17.
    domain = raises("a mask above the star is not an opinion",
                    PyoneerCommandApplyError,
                    lambda: session.run(Command("map.tileset.mask.set", USED,
                                                {"name": "Upper", "tile": 0,
                                                 "mask": STAR + 1})),
                    contains="the star that abstains")
    if domain is not None:
        expect("and it is the command layer refusing, not the file format",
               PyoneerCommandArgumentError.__name__ in str(domain), True)
    raises("nor is anything below NO_DATA",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.mask.set", USED,
                                       {"name": "Upper", "tile": 0,
                                        "mask": NO_DATA - 1})),
           contains="the star that abstains")
    unchanged("a mask outside the vocabulary")
    # Still the empty grid the section above left behind: a refusal that had
    # written the cell first and raised second would show up right here.
    expect("and not one of them touched the sidecar", sidecar_text(UPPER_MASK),
           "blitmask 1\nsize 4 3\nkind tileset\nfirstgid 13\nname Upper\n"
           "....\n....\n....\n")

    # The pair that would make the inverse inexact rather than merely wrong:
    # a blank declaration is indistinguishable from an absent one once it is
    # in an argument, and a typed one comes back as a string.
    lower = document("used").tileset("Lower")
    document("used").properties_of(lower.element)[DEFAULTS_PROPERTY] = ""
    raises("a declaration present but blank is refused, not guessed at",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.mask.set", USED,
                                       {"name": "Lower", "tile": 0,
                                        "mask": 0})),
           contains="with no value")
    document("used").properties_of(lower.element)[DEFAULTS_PROPERTY] = 7
    raises("a declaration that is not even a path is refused",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.mask.set", USED,
                                       {"name": "Lower", "tile": 0,
                                        "mask": 0})),
           contains="a mask reference is a path")
    del document("used").properties_of(lower.element)[DEFAULTS_PROPERTY]
    unchanged("the two unusable declarations, once removed again")

    # A mask the wrong WIDTH is the shape that still looks like the feature
    # working: every row after the first is shifted, so the masks load,
    # apply, and describe the wrong tiles.
    with open(sidecar(UPPER_MASK), "w", encoding="utf-8", newline="") as handle:
        handle.write("blitmask 1\nsize 3 3\nkind tileset\nname Upper\n"
                     "...\n...\n...\n")
    raises("a sidecar a different width from the sheet is refused",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.mask.set", USED,
                                       {"name": "Upper", "tile": 0,
                                        "mask": 0})),
           contains="shifts every row after the first")
    with open(sidecar(UPPER_MASK), "w", encoding="utf-8", newline="") as handle:
        handle.write("blitmask 1\nsize 4 4\nkind tileset\nname Upper\n"
                     "....\n....\n....\n....\n")
    raises("and one TALLER than the sheet, whose extra cells nothing reads",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.mask.set", USED,
                                       {"name": "Upper", "tile": 0,
                                        "mask": 0})),
           contains="would be read by nothing")
    os.remove(sidecar(UPPER_MASK))
    unchanged("both malformed sidecars")

    raises("restore with nothing declared and no reference has no file to "
           "write", PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.mask.restore", USED,
                                       {"name": "Upper", "tile": 0,
                                        "mask": 0})),
           contains="no `reference` was given")
    session.run(Command("map.tileset.mask.set", USED,
                        {"name": "Upper", "tile": 0, "mask": BLOCK_ALL}))
    raises("and pointing a declared tileset at a DIFFERENT file is two edits",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.mask.restore", USED,
                                       {"name": "Upper", "tile": 0, "mask": 0,
                                        "reference": "elsewhere.blitmask"})),
           contains="two edits, not one")
    expect("the file it would have written is not there",
           sidecar_text("elsewhere.blitmask"), None)
    session.undo()
    unchanged("after the refused move")

    print()
    print("setting a mask to the value it already holds changes nothing")
    session.run(Command("map.tileset.mask.set", USED,
                        {"name": "Upper", "tile": 4, "mask": STAR}))
    repeat = session.run(Command("map.tileset.mask.set", USED,
                                 {"name": "Upper", "tile": 4, "mask": STAR}))
    expect("the second one has no inverse to run", repeat.inverses[0].verb,
           "noop")
    session.undo()
    session.undo()
    expect("so unwinding both is still byte-exact",
           document("used").to_bytes(), IN_USE)
    os.remove(sidecar(UPPER_MASK))

    # ----------------------------------------------------------------------
    print()
    print("the import dialog's answer is one map.tileset.add accepts")
    # ----------------------------------------------------------------------
    # ONLY the seam. What the dialog LOOKS like -- its region band, its
    # spinboxes, the wording of its summary -- is measured by
    # tools/check_palette.py, which owns that widget. What is measured here
    # is the handover: the dataclass it hands back has to be acceptable to
    # this verb with nothing in between reshaping it, and what lands in the
    # file has to be what it described.
    if importlib.util.find_spec("PySide6") is None:
        print("  SKIP PySide6 is not installed "
              "(pip install -r editor/requirements.txt)")
    else:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from editor.ui.tileset_dialog import (TilesetImport,
                                              TilesetImportDialog,
                                              relative_image_path)

        application = QApplication.instance() or QApplication([])

        expect("a tmx path is relative to the MAP and uses forward slashes",
               relative_image_path(NESTED_SHEET, maps_dir), "../graphics/nested.png")
        expect("a sibling image is a bare filename",
               relative_image_path(SHEET, maps_dir), "sheet.png")

        dialog = TilesetImportDialog(maps_dir, tile_width=16, tile_height=16)
        expect("with no image there is nothing to import", dialog.value(), None)
        expect("and the button says why",
               dialog.problem(), "Choose a tileset image.")

        dialog.set_image_path(SHEET)
        expect("the whole sheet is selected, cut by the document's own formula",
               (dialog.columns, dialog.rows, dialog.tile_count),
               tileset_geometry(64, 48, 16, 16))
        expect("nothing blocks the import", dialog.problem(), None)

        taken = TilesetImportDialog(maps_dir, existing_names=["sheet"])
        taken.set_image_path(SHEET)
        expect("a name the map already uses is caught before the command runs",
               taken.problem(), "This map already has a tileset named 'sheet'.")
        expect("and nothing is handed back", taken.value(), None)

        spec = dialog.value()
        expect("the answer is a plain dataclass",
               isinstance(spec, TilesetImport), True)
        arguments = spec.command_args()
        accepted = {p.name for p in verb("map.tileset.add").params}
        expect("every argument it produces is one map.tileset.add declares",
               sorted(set(arguments) - accepted), [])
        expect("including the image path, spelled relative to the map",
               arguments["image"], "sheet.png")

        arguments["name"] = "FromDialog"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            session.run(Command("map.tileset.add", TEST, arguments))
        landed = document("test").tileset("FromDialog")
        expect("the grid it described is the grid the file records",
               (landed.columns, landed.tile_count),
               (spec.columns, spec.tile_count))
        expect("and its image path went in verbatim",
               landed.image_source, "sheet.png")
        session.undo()
        expect("undo of a dialog-driven add is byte-exact",
               document("test").to_bytes(), ORIGINAL)

    # ----------------------------------------------------------------------
    print()
    print("grow: whole rows appended into headroom, and undo takes them back")
    # ----------------------------------------------------------------------
    # Its own map, so nothing above can have left the fixture half-edited.
    # Two tilesets with a RESERVED gid hole between them and painted cells in
    # both: this is the shape the whole growth model exists for. Lower can
    # claim 88 more tiles without touching one csv token, and cannot claim
    # the 89th without moving Upper.
    expect("the growth fixture round trips before anything runs",
           document("growth").to_bytes(), GROWABLE)
    expect("it declares a reserved hole, not a packed pair",
           tileset_state("growth"), [("Lower", 1, 12), ("Upper", 101, 12)])
    PAINTED = placed("growth")
    expect("both ranges are painted, one of them through a flip bit",
           PAINTED, ({"Floor": [1, 2147483660, 101, 112]}, [(1, 105)]))

    grown = session.run(Command("map.tileset.grow", GROW,
                                {"name": "Lower", "image": "tall.png"}))
    expect("the sheet under it grew by a whole row",
           tileset_state("growth"), [("Lower", 1, 16), ("Upper", 101, 12)])
    expect("NOT ONE PLACED GID MOVED", placed("growth"), PAINTED)
    expect("the file actually changed",
           document("growth").to_bytes() == GROWABLE, False)
    expect("the inverse is a grow carrying the four values it replaced",
           (grown.inverses[0].verb, grown.inverses[0].args),
           ("map.tileset.grow",
            {"name": "Lower", "first_gid": 0, "image": "sheet.png",
             "image_width": 64, "image_height": 48, "tile_count": 12}))

    session.undo()
    expect("undo puts the sheet and the count back",
           tileset_state("growth"), [("Lower", 1, 12), ("Upper", 101, 12)])
    expect("byte for byte", document("growth").to_bytes(), GROWABLE)
    session.redo()
    expect("redo grows it again",
           document("growth").tileset("Lower").tile_count, 16)
    session.undo()
    expect("and undo is still exact", document("growth").to_bytes(), GROWABLE)

    repeat = session.run(Command("map.tileset.grow", GROW, {"name": "Lower"}))
    expect("growing to the size it already is has no inverse to run",
           repeat.inverses[0].verb, "noop")
    expect("and changed nothing", document("growth").to_bytes(), GROWABLE)

    depth = len(session.history())
    blocked = raises(
        "growing past the reservation is refused, not accommodated",
        PyoneerCommandApplyError,
        lambda: session.run(Command("map.tileset.grow", GROW, {
            "name": "Lower", "image_width": 64, "image_height": 416,
            "tile_count": 101})),
        contains="already owned by Upper at 101-112")
    if blocked is not None:
        # The three things a caller needs in order to act, carried through
        # the command layer unreworded: how much room there is, what the
        # alternative costs, and which verb keeps an exact inverse.
        expect("the message survives the command layer: the room available",
               "room for 88 more tiles" in str(blocked), True)
        expect("the message survives: what a renumber would cost",
               "renumber 3 painted gid(s) (Floor x2, entity x1)" in str(blocked),
               True)
        expect("the message survives: what to do instead",
               "map.tile.set_many" in str(blocked), True)
        expect("and the transaction rolled back cleanly", blocked.rolled_back, True)
    expect("the refused growth left the file untouched",
           document("growth").to_bytes(), GROWABLE)

    raises("a wider sheet is refused through the verb too",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.grow", GROW, {
               "name": "Lower", "image_width": 80, "image_height": 48})),
           contains="renumbers every tile after the first row")
    raises("so is truncating over a painted cell",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.grow", GROW, {
               "name": "Lower", "tile_count": 11})),
           contains="still point at gids 12-12")
    raises("an external tileset cannot be grown, addressed by firstgid",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.grow", EXT,
                                       {"first_gid": 1, "tile_count": 4})),
           contains="live in the .tsx")
    raises("and a grow that addresses nothing is an argument error",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.grow", GROW, {})),
           contains="first_gid")
    expect("no refusal touched the file", document("growth").to_bytes(), GROWABLE)
    expect("and none of them left a step in the history",
           len(session.history()), depth)

    # ----------------------------------------------------------------------
    print()
    print("headroom is bought at add time and spent by growth later")
    # ----------------------------------------------------------------------
    # `first_gid` on map.tileset.add is what makes growth free for a tileset
    # that is not the top one. Without it the only tileset with room is the
    # last, and every other grow costs a whole-map renumber.
    session.run(Command("map.tileset.add", GROW, {
        "name": "Reserved", "image": "sheet.png", "first_gid": 1001}))
    expect("the tileset took the firstgid it asked for, not the packed one",
           tileset_state("growth"),
           [("Lower", 1, 12), ("Upper", 101, 12), ("Reserved", 1001, 12)])
    expect("which leaves Upper a hole to grow into",
           document("growth").tileset_headroom("Upper"), 888)
    session.run(Command("map.tileset.grow", GROW, {
        "name": "Upper", "image_width": 64, "image_height": 3600,
        "tile_count": 900}))
    expect("and Upper spends it without moving a gid", placed("growth"), PAINTED)
    expect("the hole is exactly used up",
           document("growth").tileset_headroom("Upper"), 0)
    raises("one tile more is refused", PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.grow", GROW, {
               "name": "Upper", "image_width": 64, "image_height": 3616,
               "tile_count": 901})),
           contains="room for 0 more tiles")
    session.undo()
    session.undo()
    expect("unwinding both is byte-exact",
           document("growth").to_bytes(), GROWABLE)
    raises("a firstgid below a live range is still refused",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.add", GROW, {
               "name": "Beneath", "image": "sheet.png", "first_gid": 50})),
           contains="renumbering every csv token")
    expect("which left the file alone", document("growth").to_bytes(), GROWABLE)

    # ----------------------------------------------------------------------
    print()
    print("rename: the name moves, and the masks that name it move with it")
    # ----------------------------------------------------------------------
    # The failure this exists to catch is silent in the editor and fatal in
    # the engine: `tileset_defaults` REFUSES to load a map whose .blitmask
    # says it belongs to a tileset the map calls something else. A rename
    # that stopped at the .tmx would look perfect in the hierarchy and make
    # the map unloadable.
    expect("the masked fixture's .tmx is where the earlier sections left it",
           document("masked").to_bytes(), MASKED)
    # DERIVED, not pinned: an earlier section deliberately leaves the sidecar
    # one row taller than the author wrote it, and a constant here would be
    # asserting that section's leftovers rather than this one's edit.
    before_mask = sidecar_text("Art.blitmask")
    expect("...and its sidecar still names the tileset it belongs to",
           "name Art" + chr(10) in (before_mask or ""), True)
    before_rename = field_from_map(document("masked"))
    renamed = session.run(Command("map.tileset.rename", MASK,
                                  {"name": "Art", "to": "Village exteriors"}))
    expect("the .tmx carries the new name and nothing else moved",
           document("masked").to_bytes(),
           MASKED.replace(b'name="Art"', b'name="Village exteriors"'))
    expect("the sidecar's own header followed it, and only that line",
           sidecar_text("Art.blitmask"),
           before_mask.replace("name Art" + chr(10),
                               "name Village exteriors" + chr(10)))
    expect("the sidecar FILE was not renamed -- a mask may be shared",
           os.path.isfile(sidecar("Art.blitmask")), True)
    expect("so the engine still bakes the identical field",
           field_from_map(document("masked")), before_rename)
    expect("the inverse is this verb with the two names swapped",
           (renamed.inverses[0].verb, renamed.inverses[0].args),
           ("map.tileset.rename",
            {"name": "Village exteriors", "first_gid": 0, "to": "Art"}))

    session.undo()
    expect("undo restores the .tmx byte for byte",
           document("masked").to_bytes(), MASKED)
    expect("and the sidecar with it", sidecar_text("Art.blitmask"), before_mask)
    expect("and the field is unchanged throughout",
           field_from_map(document("masked")), before_rename)

    print()
    print("a tileset with no masks renames without provisioning any")
    plain = session.run(Command("map.tileset.rename", GROW,
                                {"name": "Lower", "to": "Terrain"}))
    expect("the name moved", tileset_state("growth"),
           [("Terrain", 1, 12), ("Upper", 101, 12)])
    expect("NOT ONE PLACED GID MOVED", placed("growth"), PAINTED)
    expect("and no sidecar appeared beside a tileset that declared none",
           sidecar_text("Terrain.blitmask"), None)
    expect("the inverse names the tileset by the name it now has",
           plain.inverses[0].args["name"], "Terrain")
    session.undo()
    expect("undo is byte-exact", document("growth").to_bytes(), GROWABLE)

    expect("renaming to the name it already holds has no inverse to run",
           session.run(Command("map.tileset.rename", GROW,
                               {"name": "Lower", "to": "Lower"}
                               )).inverses[0].verb, "noop")
    raises("a duplicate name is refused: the name is an address",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.rename", GROW,
                                       {"name": "Lower", "to": "Upper"})),
           contains="already has a tileset named 'Upper'")
    raises("an empty name is refused for the same reason",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.rename", GROW,
                                       {"name": "Lower", "to": ""})),
           contains="a tileset needs a name")
    raises("an external tileset carries no name here to rename",
           PyoneerCommandApplyError,
           lambda: session.run(Command("map.tileset.rename", EXT,
                                       {"first_gid": 1, "to": "Named"})),
           contains="carries no name in this file")
    expect("no refusal touched the file", document("growth").to_bytes(), GROWABLE)

    # ----------------------------------------------------------------------
    print()
    print("nothing was written to disk")
    # ----------------------------------------------------------------------
    with open(os.path.join(maps_dir, "test.tmx"), "rb") as handle:
        expect("the copy on disk is untouched -- no verb saves", handle.read(),
               ORIGINAL)

finally:
    shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
