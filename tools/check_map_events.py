"""Verify the map-event vocabulary: round trip, validation, filter semantics.

`editor/core/map_events.py` is the AUTHORING half of collision triggers. No
runtime reads it yet -- nothing under `scripts/` reads `pyoneer_trigger`,
there is no MAP_TRIGGER_* event type, and entities are not on the event bus
-- so nothing about it is proved by running the game. (This sentence used to
say the engine has no collision detection. It has one: the renderer bakes
`field_from_map` and gates every body with it. The missing half is the
trigger read and the firing, not the pipeline under them.) It has to be
proved here or not at all:

  * a declaration survives properties -> tmx -> properties unchanged, with
    its TYPES intact, and authoring one is a reversible edit to the file
  * an invented trigger kind is refused at the authoring door, and a
    hand-edited one is survived at the reading door -- loudly, not silently
  * the filter means what the docstring says: empty passes everything, names
    within an axis are OR-ed, axes are AND-ed, so a second axis can only
    narrow
  * a region's cells are half-open, a zero-sized object is one cell, and a
    tile object is bottom-anchored
  * the authoring VERBS call the gate this module already carries, so a
    property name pytmx cannot survive is refused at the door instead of
    making the map unloadable at the next boot

Every fixture is built here. Nothing asserts anything about what
`data/maps/starter.tmx` happens to contain -- it is a live, repaintable map.

No Qt. No pygame either until the last section, which imports the editor's
command layer to drive the authoring verbs and pulls pygame in through
`scripts.core.depth`; `QUIET_AT_IMPORT` pins that map_events itself does
not. Runs on a bare clone with no art.

    .venv/Scripts/python.exe tools/check_map_events.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import dataclasses
import json
import os
import shutil
import sys
import tempfile
import warnings

from scripts.core.errors import PyoneerContentWarning
from scripts.loaders.map_document import MapDocument

from editor.core import map_events
from editor.core.layers import BY_KEY as LAYER_CAPABILITIES
from editor.core.layers import PREFIX, RESERVED
from editor.core.map_events import (
    ARGS,
    BLOCKS,
    COOLDOWN_MS,
    EVENT_NAMES,
    FILTER_CLASS,
    FILTER_TAGS,
    KNOWN,
    ONCE,
    PAYLOAD,
    TRIGGER,
    TRIGGER_KINDS,
    TRIGGER_LAYER,
    EntityFilter,
    MapEvent,
    Region,
    check_property_name,
    describe_all,
    format_args,
    read,
    read_all,
    read_anchor,
    validate,
    validate_properties,
)

#: Which of pygame and Qt the imports ABOVE dragged in. Sampled here rather
#: than where it is asserted, because the last section of this file imports
#: `editor.core.session` to drive the authoring verbs and that reaches
#: `scripts.core.depth`, which imports pygame. The claim being made is about
#: THIS module -- map_events cannot execute -- and it stays exactly as
#: falsifiable when it is sampled at the moment it is about.
QUIET_AT_IMPORT = [name for name in sys.modules
                   if name.split(".")[0] in ("pygame", "PySide6")]

failures: list[str] = []

# The lenient reader warns by design, and half the lines below feed it
# deliberate rubbish. Silence that globally; `expect_warns` turns warnings
# back on for the lines where the warning IS the assertion.
warnings.simplefilter("ignore", PyoneerContentWarning)


def brief(value) -> str:
    """A repr that will not dump a whole tmx file into the check output."""
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>" if len(value) > 60 else repr(value)
    text = str(value)
    return text if len(text) <= 68 else text[:65] + "..."


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} "
          f"got={brief(got)} want={brief(want)}")
    if not ok:
        failures.append(label)
        if isinstance(got, bytes) and isinstance(want, bytes):
            low = next((i for i, (a, b) in enumerate(zip(want, got)) if a != b),
                       min(len(want), len(got)))
            print(f"        first diff at byte {low}")
            print(f"        want ...{want[max(0, low - 30):low + 30]!r}...")
            print(f"        got  ...{got[max(0, low - 30):low + 30]!r}...")


def expect_raises(label, exception_type, fn):
    try:
        fn()
    except exception_type as exc:
        text = str(exc).splitlines()[0]
        print(f"  ok   {label:<58} {type(exc).__name__}: {text[:56]}")
        return
    except Exception as exc:                                    # noqa: BLE001
        print(f"  FAIL {label:<58} raised {type(exc).__name__}, "
              f"wanted {exception_type.__name__}")
        failures.append(label)
        return
    print(f"  FAIL {label:<58} did not raise {exception_type.__name__}")
    failures.append(label)


def expect_warns(label, needle, fn):
    """A lenient read must not raise -- but it must not be silent either."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = fn()
    said = [str(w.message) for w in caught
            if issubclass(w.category, PyoneerContentWarning)]
    ok = any(needle in message for message in said)
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} "
          f"warned={said[0][:44] if said else None!r}")
    if not ok:
        failures.append(label)
    return result


class Stub:
    """The least a reader may assume: attributes plus a property mapping.

    Stands in for both a `MapDocument.MapObject` (typed properties) and a
    pytmx `TiledObject` (string properties), which is the whole point -- the
    reader must give the same answer whichever one it was handed.
    """

    def __init__(self, properties=None, *, id=1, name="", type="",
                 x=0.0, y=0.0, width=0.0, height=0.0, gid=0, rotation=0.0):
        self.properties = dict(properties or {})
        self.id = id
        self.name = name
        self.type = type
        self.x, self.y = x, y
        self.width, self.height = width, height
        self.gid = gid
        self.rotation = rotation


class StubLayer:
    """An objectgroup: a name, properties, and objects()."""

    def __init__(self, name, objects, properties=None):
        self.name = name
        self.properties = dict(properties or {})
        self._objects = list(objects)

    def objects(self):
        return list(self._objects)


DOOR = MapEvent(
    kind=map_events.ENTER,
    filter=EntityFilter(tags=frozenset({"player"}),
                        classes=frozenset({"Actor"})),
    blocks=True,
    once=True,
    cooldown_ms=250,
    payload="door_north",
    args=(("to", "cave_01"), ("facing", "up")),
    region=Region(32, 16, 32, 16),
)


# --------------------------------------------------------------------------
print("the vocabulary is prefixed, and the prefix is the whole safety story")
# --------------------------------------------------------------------------
expect("every property this module writes is prefixed",
       [name for name in KNOWN if not name.startswith(PREFIX)], [])
expect("so none of them can shadow a pytmx attribute",
       [name for name in KNOWN if name in RESERVED], [])
expect("and the fields are exactly the declared vocabulary",
       sorted(KNOWN),
       sorted([TRIGGER, FILTER_TAGS, FILTER_CLASS, BLOCKS, ONCE,
               COOLDOWN_MS, PAYLOAD, ARGS]))
expect_raises("a natural but fatal property name is refused outright",
              ValueError, lambda: check_property_name("visible"))
expect_warns("an unknown pyoneer_ name is a namespace, not an error",
             "not a map-event field",
             lambda: check_property_name("pyoneer_something_else"))
expect("the layer anchor lives on the objectgroup, not the object",
       TRIGGER_LAYER in KNOWN, False)

# The anchor belongs in the engine's layer vocabulary. If the parallel change
# has landed, the two spellings must agree; if it has not, this still holds.
try:
    from scripts.core import layer_profile
    engine_anchor = getattr(layer_profile, "TRIGGER_LAYER", TRIGGER_LAYER)
except ImportError:                                             # pragma: no cover
    engine_anchor = TRIGGER_LAYER
expect("and does not drift from the engine's spelling of it",
       TRIGGER_LAYER, engine_anchor)


# --------------------------------------------------------------------------
print()
print("a declaration round-trips through its own properties")
# --------------------------------------------------------------------------
written = DOOR.to_properties()
expect("a full declaration writes every field it uses",
       sorted(written), sorted([TRIGGER, FILTER_TAGS, FILTER_CLASS, BLOCKS,
                                ONCE, COOLDOWN_MS, PAYLOAD, ARGS]))
expect("and reads back identical",
       read(Stub(written, id=14, x=32, y=16, width=32, height=16)),
       dataclasses.replace(DOOR, object_id=14))
expect("bools stay bool, so the tmx type attribute is written right",
       [type(written[BLOCKS]).__name__, type(written[COOLDOWN_MS]).__name__],
       ["bool", "int"])
expect("defaults are omitted rather than written",
       MapEvent(blocks=True).to_properties(), {BLOCKS: True})
expect("an empty declaration writes nothing at all",
       MapEvent().to_properties(), {})
expect("filter names are sorted, so the same filter is the same bytes",
       MapEvent(filter=EntityFilter(
           tags=frozenset({"npc", "player"}))).to_properties()[FILTER_TAGS],
       "npc,player")
expect("arguments keep the order they were authored in",
       written[ARGS], "to=cave_01;facing=up")
expect("a blocks-only region is declared but never fires",
       [MapEvent(blocks=True).declared, MapEvent(blocks=True).fires],
       [True, False])
expect("an object with no properties at all reads as undeclared",
       read(Stub()).declared, False)
expect("a declaration is hashable, so a load-time index may key on it",
       isinstance(hash(DOOR), int), True)


# --------------------------------------------------------------------------
print()
print("and through a real tmx file, with its types intact")
# --------------------------------------------------------------------------
FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.10.2" orientation="orthogonal" renderorder="right-down" width="4" height="4" tilewidth="16" tileheight="16" infinite="0" nextlayerid="4" nextobjectid="3">
 <layer id="1" name="Floor" width="4" height="4">
  <data encoding="csv">
0,0,0,0,
0,0,0,0,
0,0,0,0,
0,0,0,0
</data>
 </layer>
 <objectgroup id="2" name="Triggers">
  <properties>
   <property name="pyoneer_trigger_layer" value="Floor"/>
   <property name="pyoneer_renders" type="bool" value="false"/>
  </properties>
  <object id="1" name="north door" type="Trigger" x="32" y="16" width="32" height="16">
   <properties>
    <property name="unrelated" value="left alone"/>
   </properties>
  </object>
  <object id="2" name="spawn" type="Actor" x="16" y="16"/>
 </objectgroup>
</map>
"""

document = MapDocument.from_bytes(FIXTURE, path="fixture.tmx")
before = document.to_bytes()
expect("the fixture itself round-trips, or nothing below means anything",
       before, FIXTURE)

layer = document.object_layer("Triggers")
trigger_object = layer.objects()[0]
for property_name, value in DOOR.to_properties().items():
    trigger_object.properties[property_name] = value

reloaded = MapDocument.from_bytes(document.to_bytes(), path="fixture.tmx")
round_tripped = read_all(reloaded.object_layer("Triggers"))
expect("exactly one object on the layer declares a map event",
       len(round_tripped), 1)
expect("and it survived the file unchanged",
       round_tripped[0],
       dataclasses.replace(DOOR, layer="Floor", source_layer="Triggers",
                           object_id=1, name="north door"))
expect("the int came back an int, not the string '250'",
       type(reloaded.object_layer("Triggers").objects()[0]
            .properties[COOLDOWN_MS]).__name__, "int")
expect("the anchor names the tile layer the regions belong to",
       read_anchor(reloaded.object_layer("Triggers")), "Floor")
expect("an objectgroup with no anchor means the whole map",
       read_anchor(StubLayer("Loose", [])), "")

# Rule 1: authoring a map event has to be a reversible edit, like every other
# mutation in this repo. Written then removed must reproduce the bytes.
for property_name in DOOR.to_properties():
    del trigger_object.properties[property_name]
expect("authoring one and removing it is byte-for-byte reversible",
       document.to_bytes(), FIXTURE)


# --------------------------------------------------------------------------
print()
print("an invented trigger kind is refused at the authoring door")
# --------------------------------------------------------------------------
expect("a known kind passes and comes back coerced",
       validate("trigger", "enter"), "enter")
expect("so does the empty kind -- a wall is a legitimate declaration",
       validate("trigger", ""), "")
expect_raises("an invented kind does not",
              ValueError, lambda: validate("trigger", "explode"))
expect_raises("nor does a near-miss on a real one",
              ValueError, lambda: validate("trigger", "entre"))
expect_raises("nor an invented field",
              ValueError, lambda: validate("triggr", "enter"))
expect_raises("a bool field will not take the string 'true'",
              ValueError, lambda: validate("blocks", "true"))
expect_raises("a cooldown cannot run backwards",
              ValueError, lambda: validate("cooldown_ms", -5))
expect_raises("a filter of nothing but separators declares nothing",
              ValueError, lambda: validate("filter_tags", ",,"))
expect_raises("an argument declared twice would lose one silently",
              ValueError, lambda: validate("args", "to=a;to=b"))
expect_raises("an argument value that cannot be read back is refused",
              ValueError, lambda: format_args({"to": "a;b"}))
expect("a valid filter is normalised on the way in",
       validate("filter_tags", "Player, NPC ,"), "npc,player")
expect("classes keep their case, because a genre declares them exactly",
       validate("filter_class", "Actor,Chest"), "Actor,Chest")
expect("a whole property dict validates by property name",
       validate_properties({TRIGGER: "use", COOLDOWN_MS: 250}),
       {TRIGGER: "use", COOLDOWN_MS: 250})
expect_raises("an unknown pyoneer_ property in a declaration is refused",
              ValueError,
              lambda: validate_properties({PREFIX + "trigr": "use"}))
expect_raises("and a reserved name is refused before it is written",
              ValueError, lambda: validate_properties({"visible": False}))


# --------------------------------------------------------------------------
print()
print("a hand-edited one is survived at the reading door, but not in silence")
# --------------------------------------------------------------------------
bogus = expect_warns("an unknown kind warns rather than raising",
                     "not one of",
                     lambda: read(Stub({TRIGGER: "explode"})))
expect("and reads as a region that never fires",
       [bogus.kind, bogus.fires, bogus.declared], ["", False, False])
expect("but its siblings on the same object still read",
       read(Stub({TRIGGER: "explode", BLOCKS: True})).blocks, True)
negative = expect_warns("a negative cooldown warns and clamps",
                        "negative",
                        lambda: read(Stub({TRIGGER: "stay",
                                           COOLDOWN_MS: -5})))
expect("to zero", negative.cooldown_ms, 0)
expect_warns("a rotated region warns that its cells are the unrotated ones",
             "rotated",
             lambda: read(Stub({TRIGGER: "enter"}, rotation=45)))

# pytmx hands every property back as a string; MapProperties hands back a
# typed value. A reader that only understood one would work in the editor and
# do nothing in the game.
as_strings = read(Stub({TRIGGER: "use", BLOCKS: "true", ONCE: "false",
                        COOLDOWN_MS: "250", FILTER_TAGS: "Player"}))
expect("a pytmx-shaped object reads the same as a typed one",
       [as_strings.kind, as_strings.blocks, as_strings.once,
        as_strings.cooldown_ms, sorted(as_strings.filter.tags)],
       ["use", True, False, 250, ["player"]])
expect("garbage where a number goes falls back rather than raising",
       read(Stub({TRIGGER: "stay", COOLDOWN_MS: "soon"})).cooldown_ms, 0)
expect("a trailing comma is a typing artefact, not a nameless entity",
       sorted(read(Stub({FILTER_TAGS: "player,"})).filter.tags), ["player"])


# --------------------------------------------------------------------------
print()
print("the filter narrows: names are OR-ed, axes are AND-ed")
# --------------------------------------------------------------------------
everything = EntityFilter()
expect("an empty filter passes everything",
       [everything.universal, everything.matches("Anything", ["whatever"]),
        everything.matches()],
       [True, True, True])

tagged = EntityFilter(tags=frozenset({"player", "npc"}))
expect("names within an axis are OR-ed",
       [tagged.matches("X", ["player"]), tagged.matches("X", ["npc"]),
        tagged.matches("X", ["rock"])],
       [True, True, False])
expect("an entity carrying none of them is out",
       tagged.matches("X", []), False)
expect("tags are free-form labels, so they compare case-insensitively",
       tagged.matches("X", ["PLAYER"]), True)

classed = EntityFilter(classes=frozenset({"Actor"}))
expect("classes are the genre's declared names, so case matters",
       [classed.matches("Actor"), classed.matches("actor")], [True, False])

both = EntityFilter(tags=frozenset({"ghost"}), classes=frozenset({"Actor"}))
expect("declaring a second axis NARROWS, it never widens",
       [both.matches("Actor", ["ghost"]),      # passes both
        both.matches("Actor", ["solid"]),      # right class, wrong tag
        both.matches("Chest", ["ghost"]),      # right tag, wrong class
        both.matches("Actor")],                # right class, no tags at all
       [True, False, False, False])
expect("which is the point: the tag axis alone would have let it through",
       EntityFilter(classes=frozenset({"Actor"})).matches("Actor", ["solid"]),
       True)
expect("an event asks its filter, so callers never reach past it",
       [DOOR.accepts("Actor", ["player"]), DOOR.accepts("Actor", ["rock"])],
       [True, False])
expect("a filter says what it is",
       both.describe(), "class Actor and tagged ghost")


# --------------------------------------------------------------------------
print()
print("where: half-open cells, a point is one cell, a tile object hangs up")
# --------------------------------------------------------------------------
expect("a two-tile region covers two cells",
       Region(32, 16, 32, 16).cells(16, 16), ((2, 1), (3, 1)))
expect("a 2x2 region covers four, row-major",
       Region(0, 0, 32, 32).cells(16, 16),
       ((0, 0), (1, 0), (0, 1), (1, 1)))
expect("the far edge is half-open, so abutting regions do not overlap",
       Region(0, 0, 16, 16).cells(16, 16), ((0, 0),))
expect("and containment agrees with it",
       [Region(0, 0, 16, 16).contains(15.9, 0),
        Region(0, 0, 16, 16).contains(16, 0)], [True, False])
expect("a region straddling a boundary covers both cells",
       Region(8, 0, 16, 16).cells(16, 16), ((0, 0), (1, 0)))
expect("a zero-sized object is an authored CELL, not an empty region",
       [Region(48, 32, 0, 0).is_point, Region(48, 32, 0, 0).cells(16, 16)],
       [True, ((3, 2),)])
expect("a point has no area, so nothing is inside it",
       Region(48, 32, 0, 0).contains(48, 32), False)
expect_raises("a zero tile size is a caller bug, not authored content",
              ValueError, lambda: Region(0, 0, 16, 16).cells(0, 16))
expect("a plain object is anchored top-left",
       Region.of_object(Stub(x=32, y=16, width=32, height=16)),
       Region(32, 16, 32, 16))
expect("a TILE object is anchored bottom-left and is lifted to match",
       Region.of_object(Stub(x=32, y=32, width=32, height=16, gid=1793)),
       Region(32, 16, 32, 16))
expect("an event delegates its cells to its region",
       DOOR.cells(16, 16), ((2, 1), (3, 1)))


# --------------------------------------------------------------------------
print()
print("a whole object layer reads as the regions a runtime would index")
# --------------------------------------------------------------------------
authored = StubLayer(
    "Triggers",
    [Stub(DOOR.to_properties(), id=1, x=32, y=16, width=32, height=16),
     Stub({}, id=2, name="spawn", x=16, y=16),
     Stub({BLOCKS: True}, id=3, x=0, y=0, width=16, height=16)],
    {TRIGGER_LAYER: "Floor"})
found = read_all(authored)
expect("objects declaring nothing are dropped, spawn points and all",
       [event.object_id for event in found], [1, 3])
expect("every region is stamped with the layer it is anchored to",
       sorted({event.layer for event in found}), ["Floor"])
expect("and with the objectgroup it was authored on",
       sorted({event.source_layer for event in found}), ["Triggers"])
expect("document order is preserved, because index order is reproducible",
       [event.kind for event in found], ["enter", ""])


# --------------------------------------------------------------------------
print()
print("the seam is stated exactly, and stops there")
# --------------------------------------------------------------------------
expect("every trigger kind has a bus name",
       sorted(EVENT_NAMES), sorted(TRIGGER_KINDS))
expect("no two kinds share one -- a duplicated value tuple silently ALIASES "
       "an enum member", len(set(EVENT_NAMES.values())), len(TRIGGER_KINDS))
expect("and every name is namespaced, so appending them cannot collide",
       [name for name in EVENT_NAMES.values()
        if not name.startswith("map_trigger_")], [])
expect("an event knows the name it would be dispatched under",
       DOOR.event_name, "map_trigger_enter")
expect("a region that never fires has no bus name at all",
       MapEvent(blocks=True).event_name, "")
expect("nothing here imports pygame or Qt -- this module cannot execute",
       QUIET_AT_IMPORT, [])
expect("the generated docs cover every property, plus the layer anchor",
       [name for name in list(KNOWN) + [TRIGGER_LAYER]
        if f"`{name}`" not in describe_all()], [])
expect("a declaration describes itself for a tooltip",
       MapEvent(kind="use", payload="chest_01",
                region=Region(0, 0, 16, 16)).describe(),
       "use region fires for anything -> chest_01")
expect("and says cell when that is what was authored",
       MapEvent(kind="use", payload="chest_01").describe(),
       "use cell fires for anything -> chest_01")

# --------------------------------------------------------------------------
print()
print("the authoring verbs refuse a name that would make the map unloadable")
# --------------------------------------------------------------------------
# Everything above proves the GATE. This proves the DOOR. Measured before
# this section existed, `grep -c check_property_name editor/core/verbs.py`
# returned 0 against 3 in `editor/core/map_events.py`: the gate was written,
# unit-tested, and called by nothing. So the Inspector's New-property box
# accepted `visible`, the verb wrote it, `to_bytes()` wrote it into the file,
# and pytmx raised at the next load naming neither the object nor the
# property -- law 1's stated cost, three clicks away.
#
# Both halves for both doors: a reserved name is refused AND says what to
# type instead AND changes nothing; a legitimate name still lands and
# survives a re-read. The second is not decoration -- a gate that also
# refused `pyoneer_actor` would satisfy every refusal assertion here.
#
# Importing the command layer is what costs this file its pygame-free import
# graph, which is why QUIET_AT_IMPORT is sampled at the top.
from editor.core.commands import Command                            # noqa: E402
from editor.core.errors import PyoneerCommandApplyError             # noqa: E402
from editor.core.scope import Scope                                 # noqa: E402
from editor.core.session import Session                             # noqa: E402

FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" compressionlevel="-1" width="4" height="2" \
tilewidth="16" tileheight="16" infinite="0" nextlayerid="3" nextobjectid="2">
 <layer id="1" name="Floor" width="4" height="2">
  <data encoding="csv">
0,0,0,0,
0,0,0,0
</data>
 </layer>
 <objectgroup id="2" name="Triggers">
  <object id="1" name="plain" type="GameEntity" x="0" y="0" width="16" \
height="16"/>
 </objectgroup>
</map>
"""

workspace = tempfile.mkdtemp(prefix="pyoneer_map_events_")
os.makedirs(os.path.join(workspace, "config"))
os.makedirs(os.path.join(workspace, "data", "maps"))
with open(os.path.join(workspace, "data", "maps", "fixture.tmx"), "w",
          encoding="utf-8", newline="") as handle:
    handle.write(FIXTURE)
with open(os.path.join(workspace, "config", "maps.json"), "w",
          encoding="utf-8") as handle:
    json.dump({"data": [{"name": "fixture", "identifier": "fixture",
                         "file": "data/maps/fixture.tmx"}]}, handle)

session = Session.open(workspace, genre_id="topdown_rpg")
document = session.project.map("fixture")
OBJECT = Scope.of(("map", "fixture"), ("layer", "Triggers"), ("object", "1"))
LAYER = Scope.of(("map", "fixture"), ("layer", "Triggers"))
FLOOR = Scope.of(("map", "fixture"), ("layer", "Floor"))


def refusal(verb, scope, args) -> str:
    """The text ONE command refused with, or "" if it did not refuse."""
    try:
        session.run(Command(verb, scope, args))
    except PyoneerCommandApplyError as exc:
        return str(exc)
    return ""


def written(object_id: int = 1) -> dict:
    return document.object_layer("Triggers").find(object_id).properties.as_dict()


def reread(object_id: int = 1) -> dict:
    """What a fresh parse of the bytes this document would SAVE sees.

    Asserting the in-memory dict alone would pass on a verb that accepted a
    property and never wrote it out.
    """
    fresh = MapDocument.from_bytes(document.to_bytes())
    return fresh.object_layer("Triggers").find(object_id).properties.as_dict()


BEFORE = document.to_bytes()

said = refusal("map.object.property.set", OBJECT,
               {"key": "visible", "value": True})
expect("map.object.property.set refuses a name pytmx cannot survive",
       "shadows a pytmx attribute" in said, True)
expect("and names the offending key", "'visible'" in said, True)
expect("and the spelling the author should have typed instead",
       "pyoneer_visible" in said, True)
expect("and nothing at all was written", written(), {})
expect("so the file is byte-identical", document.to_bytes(), BEFORE)
expect("every one of the eleven reserved names is refused, not just the "
       "obvious ones",
       [name for name in sorted(RESERVED)
        if "shadows a pytmx attribute"
        not in refusal("map.object.property.set", OBJECT,
                       {"key": name, "value": 1})], [])
expect("and eleven refusals later the file is still byte-identical",
       document.to_bytes(), BEFORE)

# The other half. A gate that refused everything would satisfy every line
# above and make the New-property box useless.
session.run(Command("map.object.property.set", OBJECT,
                    {"key": "pyoneer_actor", "value": "hero"}))
expect("a pyoneer_ name the map-event vocabulary does not know still goes "
       "through -- the prefix is a namespace, not its private property",
       written().get("pyoneer_actor"), "hero")
expect("and survives the round trip out to bytes and back",
       reread().get("pyoneer_actor"), "hero")
session.undo()
expect("undo takes it back off", "pyoneer_actor" in written(), False)

session.run(Command("map.object.property.set", OBJECT,
                    {"key": "hp", "value": 30}))
expect("an UNPREFIXED name that shadows nothing is still allowed -- the gate "
       "refuses fatal names, not unfamiliar ones", written().get("hp"), 30)
expect("with its int type intact through the file", reread().get("hp"), 30)
session.undo()


def content_warnings(fn) -> list[str]:
    """Every content warning ONE command raised, past this file's global
    silence, because here the ABSENCE of one is the assertion."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fn()
    return [str(entry.message) for entry in caught
            if issubclass(entry.category, PyoneerContentWarning)]


quiet = content_warnings(
    lambda: session.run(Command("map.object.property.set", OBJECT,
                                {"key": "pyoneer_param_hp", "value": 5})))
expect("and authoring a correct name warns about NOTHING -- the gate's "
       "map-event-only advice would cry wolf on every behavior parameter",
       quiet, [])
session.undo()
expect("the object is back to carrying nothing", written(), {})

# --------------------------------------------------------------------------
# The second door. `map.object.add` loops a whole dict of caller-supplied
# names, so guarding only the obvious verb leaves the map exactly as
# unloadable.
#
# Re-snapshotted rather than compared against BEFORE: adding the FIRST
# property to a self-closing `<object/>` and undoing leaves `<object></object>`
# behind. Every value round trips and the map loads, but the bytes do not
# come back, and that is `MapProperties`, not this gate -- pinning BEFORE
# here would fail for a reason no line of this section is about.
# --------------------------------------------------------------------------
INTACT = document.to_bytes()

said = refusal("map.object.add", LAYER,
               {"type": "GamePlayer", "x": 16.0, "y": 16.0,
                "properties": {"opacity": 1}})
expect("map.object.add refuses a fatal name in the properties an object is "
       "born carrying", "shadows a pytmx attribute" in said, True)
expect("and names it, with the spelling to use instead",
       ("'opacity'" in said, "pyoneer_opacity" in said), (True, True))
expect("and refuses BEFORE creating anything, so there is no half-made "
       "object left behind",
       [obj.id for obj in document.object_layer("Triggers").objects()], [1])
expect("which leaves the file byte-identical", document.to_bytes(), INTACT)

session.run(Command("map.object.add", LAYER,
                    {"type": "GamePlayer", "x": 16.0, "y": 16.0,
                     "properties": {"pyoneer_param_hp": 30}}))
expect("a legitimate one is born carrying it",
       written(2).get("pyoneer_param_hp"), 30)
expect("and it is really in the file", reread(2).get("pyoneer_param_hp"), 30)
session.undo()
session.run(Command("map.object.add", LAYER,
                    {"type": "GamePlayer", "x": 16.0, "y": 16.0}))
expect("and an add declaring no properties at all is unaffected",
       [obj.id for obj in document.object_layer("Triggers").objects()], [1, 2])
session.undo()

# --------------------------------------------------------------------------
# The third door, which is not one. `map.layer.set` composes the property
# name as PREFIX + key from a closed vocabulary, so it cannot spell a
# reserved name and carries no guard. That is a claim about the vocabulary,
# so assert the vocabulary rather than trusting the sentence.
# --------------------------------------------------------------------------
expect("a reserved name is not a layer capability either, so map.layer.set "
       "refuses it outright",
       refusal("map.layer.set", FLOOR, {"key": "visible", "value": True}) != "",
       True)
expect("and no capability that DOES exist composes a reserved name -- which "
       "is why that path needs no guard",
       [key for key in LAYER_CAPABILITIES if PREFIX + key in RESERVED], [])
expect("and every refusal since wrote nothing at all",
       document.to_bytes(), INTACT)

shutil.rmtree(workspace, ignore_errors=True)


print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
