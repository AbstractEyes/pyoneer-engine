"""Map events: authorable collision triggers, stored as tmx object properties.

WHAT AN AUTHOR SAYS
-------------------
Someone -- a human in Tiled, or an AI through `map.object.add` -- draws a
rectangle on an object layer and declares three things about it:

    what collides   `pyoneer_filter_class`, `pyoneer_filter_tags`
    where           the object's own x/y/width/height, on a named layer
    what happens    `pyoneer_trigger` (enter|exit|stay|use), plus arguments

This module is the vocabulary for those three axes, the reader that turns an
object back into a `MapEvent`, and the validator that stops an invented
trigger kind reaching the file. Nothing here executes, allocates, draws, or
ticks; it is data and the rules the data must obey.

STORED AS PROPERTIES, NOT IN A SIDE TABLE
-----------------------------------------
Tiled renders custom properties, so a trigger is editable by hand in the
dialog the author already uses; `MapDocument` writes them with a
byte-minimal, exactly reversible diff; the region and its declaration are
the same element and cannot drift apart; and `MapProperties` types them on
write, so `pyoneer_cooldown_ms` reads back as an int rather than "250".

THE PREFIX IS LOAD-BEARING
--------------------------
Every key is `pyoneer_`-prefixed for the same reason the layer vocabulary is:
pytmx RAISES and makes the whole map unloadable if a custom property shadows
one of its own attribute names. `name`, `id`, `visible`, `width` and `type`
are all plausible names for something on a trigger, and all of them are
fatal. `check_property_name` exists so the authoring verb can refuse one
before it is written rather than after the map stops loading.

NOTHING READS THIS AT RUNTIME YET
---------------------------------
This is the authoring half of a feature whose other half does not exist:
nothing under `scripts/` reads `pyoneer_trigger`, and `GameEventType` has no
`MAP_TRIGGER_*` members. A map authored with this vocabulary changes nothing
about how the game behaves.

THE SEAM A RUNTIME WOULD READ THIS THROUGH
------------------------------------------
  1. **Load.** Walk each `<objectgroup>`, call `read_all(layer)`. The
     objectgroup names the tile layer its regions are anchored to via
     `pyoneer_trigger_layer`; empty means the whole map.
  2. **Index.** Rasterize `event.cells(tile_width, tile_height)` once at
     load into a `dict[int, MapEvent]` keyed by `cell_y * map_width +
     cell_x`. Not a GameComponent per region: that is 2621 us/frame at 256
     regions against 1.7 us for the dict lookup.
  3. **Per frame.** For each entity, look up its cell and compare with last
     frame's to derive enter/exit/stay. O(entities), not O(entities x
     regions).
  4. **Filter.** `event.accepts(entity_class, entity_tags)` decides whether
     an entity may fire a region. Entities have no `tags` field yet.
  5. **Dispatch.** One FRESH event object per firing, named
     `event.event_name` -- the string a future `GameEventType` member must
     carry, e.g. `MAP_TRIGGER_ENTER = ("map_trigger_enter", None)`. Never a
     shared event: consumption here is not type-gated, so one listener
     calling `handle()` silences every sibling for the rest of the frame.
  6. **Blocking.** `event.blocks` is independent of `event.trigger`. A wall
     blocks with no trigger kind; a tripwire triggers without blocking; a
     door does both.

`once` and `cooldown_ms` are authored NUMBERS that this module transports.
It holds no clock and no fired-set, because it has no frame to hang them on.

AUTHORING ONE
-------------
No new verbs. The three that exist already write this, byte-minimally and
reversibly:

    map.layer.add   {"name": "Triggers", "kind": "object"}
    map.layer.set   {"key": "trigger_layer", "value": "Floor"}
    map.layer.set   {"key": "renders", "value": false}
    map.object.add  {"type": "Trigger", "x": 32, "y": 16,
                     "width": 32, "height": 16,
                     "properties": {"pyoneer_trigger": "enter",
                                    "pyoneer_filter_class": "Actor",
                                    "pyoneer_payload": "door_north"}}

`MapEvent.to_properties()` produces that `properties` dict, and `read()`
turns the object back into the `MapEvent`. That round trip is what
`tools/check_map_events.py` asserts, through a real `MapDocument`, including
that authoring one and removing it again reproduces the file byte for byte.

WHERE THIS FILE BELONGS, EVENTUALLY
-----------------------------------
In `scripts/core/`, beside `layer_profile.py`, because the engine is the
side that will read it and `scripts/` may never import `editor/`. The move
is mechanical: the only names taken from `editor/` are `Capability` (a plain
frozen dataclass) and `RESERVED` (a fact about pytmx), and both would move
with it. Until it moves, the engine cannot read this vocabulary.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from scripts.core.errors import warn_content
from scripts.core.layer_profile import PREFIX

from editor.core.layers import Capability, RESERVED

# The objectgroup-level anchor: which tile layer these regions belong to.
# It is a LAYER capability, so its home is the engine's layer vocabulary
# alongside `pyoneer_passability`. Import it when that has landed rather than
# keeping a second copy of the string -- two hand-kept copies of a property
# name drift, and the failure is silent (written under one name, read under
# another, does nothing at all).
try:
    from scripts.core.layer_profile import TRIGGER_LAYER
except ImportError:                     # the parallel layer change is not in yet
    TRIGGER_LAYER = PREFIX + "trigger_layer"


# --------------------------------------------------------------------------
# The vocabulary
# --------------------------------------------------------------------------

TRIGGER = PREFIX + "trigger"
FILTER_TAGS = PREFIX + "filter_tags"
FILTER_CLASS = PREFIX + "filter_class"
BLOCKS = PREFIX + "blocks"
ONCE = PREFIX + "once"
COOLDOWN_MS = PREFIX + "cooldown_ms"
PAYLOAD = PREFIX + "payload"
ARGS = PREFIX + "args"

# When a trigger fires. `blocks` is deliberately NOT in here: solidity and
# triggering are orthogonal, and folding them into one enum would make
# "a wall that also fires" unauthorable.
ENTER = "enter"
EXIT = "exit"
STAY = "stay"
USE = "use"
TRIGGER_KINDS: tuple[str, ...] = (ENTER, EXIT, STAY, USE)

# The bus name each kind fires under. A future `GameEventType` member must
# carry exactly this string as the first element of its value tuple. All four
# are distinct and prefixed: an Enum member whose whole value tuple
# duplicates another's is silently an alias for it, not a new member.
EVENT_NAMES: dict[str, str] = {
    ENTER: "map_trigger_enter",
    EXIT: "map_trigger_exit",
    STAY: "map_trigger_stay",
    USE: "map_trigger_use",
}

_TAG_SEPARATOR = ","
_ARG_SEPARATOR = ";"
_ARG_ASSIGN = "="

FIELDS: tuple[Capability, ...] = (
    Capability(
        "trigger", "trigger kind", "str", "",
        "When this region fires. enter/exit fire on the frame an entity "
        "changes cell across the boundary, stay fires every frame it is "
        "inside, use fires only on an explicit interaction. Empty means the "
        "region never fires -- which is a legitimate thing to author, "
        "because a region with `blocks` and no trigger is just a wall.",
        choices=("",) + TRIGGER_KINDS),
    Capability(
        "filter_tags", "fires for tags", "str", "",
        "Comma-separated entity tags that may fire this region, e.g. "
        "'player,npc'. Empty means every entity passes this axis. Tags are "
        "free-form labels and are compared case-insensitively."),
    Capability(
        "filter_class", "fires for classes", "str", "",
        "Comma-separated entity class names that may fire this region. "
        "Empty means every entity passes this axis. Compared exactly, "
        "because these are the same names a genre pack declares in "
        "`object_types` and a case-folded match there would hide a typo."),
    Capability(
        "blocks", "blocks movement", "bool", False,
        "This region is solid. Independent of the trigger kind: a wall is "
        "blocks with no trigger, a tripwire is a trigger with no blocks, a "
        "locked door is both."),
    Capability(
        "once", "fire once", "bool", False,
        "Disarm after the first firing. The runtime owns that bookkeeping; "
        "this is the authored intent, not a state flag."),
    Capability(
        "cooldown_ms", "cooldown (ms)", "int", 0,
        "Minimum milliseconds between two firings of this region. 0 means "
        "no limit. Only meaningful for a runtime that holds a clock; nothing "
        "in this module ticks."),
    Capability(
        "payload", "payload key", "str", "",
        "An opaque key the game resolves -- a door id, a cutscene name, a "
        "quest step. Deliberately not interpreted here: the engine should "
        "not need a schema for every game built on it."),
    Capability(
        "args", "arguments", "str", "",
        "Arguments for the payload, as 'key=value;key=value'. A bare 'key' "
        "reads as key with an empty value. Values are strings; coercing them "
        "is the game's business, for the same reason payload is opaque."),
)

BY_KEY: dict[str, Capability] = {f.key: f for f in FIELDS}
BY_PROPERTY: dict[str, Capability] = {f.property_name: f for f in FIELDS}

# Every property name this module writes or reads on an OBJECT. The layer
# anchor is not in here: it lives on the objectgroup, not on the object.
KNOWN: tuple[str, ...] = tuple(f.property_name for f in FIELDS)


# --------------------------------------------------------------------------
# Text <-> value, both directions, both lenient and strict
# --------------------------------------------------------------------------

def parse_names(text: Any, *, fold: bool = False) -> frozenset[str]:
    """A comma-separated filter list as a set. Never raises.

    Empty entries are dropped rather than becoming an empty-string member,
    so 'player,' and 'player' declare the same filter -- a trailing comma is
    a typing artefact, not an assertion about a nameless entity.
    """
    if text is None:
        return frozenset()
    names = [part.strip() for part in str(text).split(_TAG_SEPARATOR)]
    if fold:
        names = [name.lower() for name in names]
    return frozenset(name for name in names if name)


def format_names(names: Iterable[str], *, fold: bool = False) -> str:
    """The inverse, sorted so the same filter always writes the same bytes.

    Sorting is what makes the round trip stable: a set has no order, and an
    unsorted join would produce a different property value -- and therefore
    a different diff -- every run.
    """
    cleaned = []
    for name in names:
        text = str(name).strip()
        if not text:
            continue
        if _TAG_SEPARATOR in text:
            raise ValueError(
                f"filter name {text!r} contains {_TAG_SEPARATOR!r}, which "
                f"separates names and so cannot survive a round trip")
        cleaned.append(text.lower() if fold else text)
    return _TAG_SEPARATOR.join(sorted(set(cleaned)))


def parse_args(text: Any) -> tuple[tuple[str, str], ...]:
    """'a=1;b=2' as ordered pairs. Never raises; keeps the authored order.

    Author order is preserved rather than sorted, because unlike a filter
    set these are a written sequence a human reads back in the dialog.
    """
    if text is None:
        return ()
    pairs: list[tuple[str, str]] = []
    for chunk in str(text).split(_ARG_SEPARATOR):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, _, value = chunk.partition(_ARG_ASSIGN)
        key = key.strip()
        if not key:
            continue
        pairs.append((key, value.strip()))
    return tuple(pairs)


def format_args(pairs: Iterable[tuple[str, Any]] | Mapping[str, Any]) -> str:
    """The inverse. Raises on anything that could not be read back."""
    items = pairs.items() if isinstance(pairs, Mapping) else pairs
    parts = []
    seen: set[str] = set()
    for key, value in items:
        key = str(key).strip()
        text = "" if value is None else str(value).strip()
        if not key:
            raise ValueError("an argument with an empty key cannot be read back")
        for token in (key, text):
            if _ARG_SEPARATOR in token:
                raise ValueError(
                    f"argument {key!r} contains {_ARG_SEPARATOR!r}, which "
                    f"separates arguments and so cannot survive a round trip")
        if _ARG_ASSIGN in key:
            raise ValueError(
                f"argument key {key!r} contains {_ARG_ASSIGN!r}, which "
                f"separates a key from its value")
        if key in seen:
            raise ValueError(
                f"argument {key!r} is declared twice; the second would win "
                f"silently on read")
        seen.add(key)
        parts.append(f"{key}{_ARG_ASSIGN}{text}" if text else key)
    return _ARG_SEPARATOR.join(parts)


def _text(properties: Mapping[str, Any], name: str) -> str:
    value = properties.get(name, "")
    if value is None or value is False:
        return ""
    if value is True:
        return "true"
    return str(value).strip()


def _flag(properties: Mapping[str, Any], name: str, fallback: bool) -> bool:
    """Read a bool from a value that may already be one, or may be text.

    Both spellings are live: `MapProperties` hands back a real bool, and
    pytmx hands back the string 'true'. A reader that only understood one of
    them would work in the editor and silently do nothing in the game.
    """
    value = properties.get(name, fallback)
    if isinstance(value, bool):
        return value
    if value is None:
        return fallback
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _int(properties: Mapping[str, Any], name: str, fallback: int) -> int:
    value = properties.get(name, fallback)
    if isinstance(value, bool):
        return fallback
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


# --------------------------------------------------------------------------
# What collides
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class EntityFilter:
    """Which entities may fire a region.

    Two independent whitelists:

        an empty axis passes everything
        within an axis the names are OR-ed
        across the axes they are AND-ed

    So `classes='Player' tags='ghost'` means "a Player that is also tagged
    ghost", NOT "a Player or anything ghostly" -- adding a second axis can
    only ever NARROW what fires.
    """

    tags: frozenset[str] = frozenset()
    classes: frozenset[str] = frozenset()

    @property
    def universal(self) -> bool:
        """True when nothing is declared, so every entity passes."""
        return not self.tags and not self.classes

    def matches(self, entity_class: str = "", tags: Iterable[str] = ()) -> bool:
        """Does this entity pass every declared axis?"""
        if self.classes and str(entity_class or "") not in self.classes:
            return False
        if self.tags:
            carried = {str(tag).strip().lower() for tag in tags or ()}
            if not (carried & self.tags):
                return False
        return True

    def describe(self) -> str:
        if self.universal:
            return "anything"
        parts = []
        if self.classes:
            parts.append("class " + "/".join(sorted(self.classes)))
        if self.tags:
            parts.append("tagged " + "/".join(sorted(self.tags)))
        return " and ".join(parts)


# --------------------------------------------------------------------------
# Where
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Region:
    """An axis-aligned rectangle in PIXELS, top-left anchored.

    Pixels rather than cells because that is what the file stores and what
    Tiled draws: a trigger may be half a tile wide, and rounding it to cells
    at read time would throw away authored precision that a future
    pixel-accurate overlap test needs. `cells()` is the lossy view, taken on
    demand by whoever is rasterizing an index.
    """

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def is_point(self) -> bool:
        """A zero-sized object: an authored CELL rather than a region."""
        return self.width <= 0 or self.height <= 0

    @classmethod
    def of_object(cls, obj: Any) -> "Region":
        """Read an object's rectangle, correcting for the tile-object anchor.

        A plain rectangle in TMX is anchored top-left; an object with a `gid`
        (a "tile object", the kind you get by stamping a tile into an object
        layer) is anchored BOTTOM-left. pytmx does not normalize that -- it
        touches only the gid -- and neither does `MapDocument`, so a trigger
        drawn as a tile object would sit one height too low in every reader
        that forgot. Correct it once, here.
        """
        x = _float(getattr(obj, "x", 0.0))
        y = _float(getattr(obj, "y", 0.0))
        width = _float(getattr(obj, "width", 0.0))
        height = _float(getattr(obj, "height", 0.0))
        try:
            gid = int(getattr(obj, "gid", 0) or 0)
        except (TypeError, ValueError):
            gid = 0
        if gid:
            y -= height
        return cls(x, y, width, height)

    def contains(self, px: float, py: float) -> bool:
        """Half-open containment, so abutting regions never both claim a point.

        A point region contains nothing -- it has no area. Ask `covers_cell`
        instead; that is the question a point object is answering.
        """
        if self.is_point:
            return False
        return self.x <= px < self.right and self.y <= py < self.bottom

    def cells(self, tile_width: int, tile_height: int) -> tuple[tuple[int, int], ...]:
        """Every cell this region touches, row-major.

        Half-open on the far edge: a 16px-wide region at x=0 on a 16px grid
        covers one cell, not two. A point region covers the single cell its
        origin falls in, which is how "put a trigger on this tile" is
        authored -- Tiled writes a click as a zero-sized object.
        """
        if tile_width <= 0 or tile_height <= 0:
            raise ValueError(
                f"tile size must be positive, got {tile_width}x{tile_height}")
        left = int(math.floor(self.x / tile_width))
        top = int(math.floor(self.y / tile_height))
        if self.is_point:
            return ((left, top),)
        right = int(math.ceil(self.right / tile_width)) - 1
        bottom = int(math.ceil(self.bottom / tile_height)) - 1
        return tuple((cx, cy)
                     for cy in range(top, max(top, bottom) + 1)
                     for cx in range(left, max(left, right) + 1))

    def covers_cell(self, cell_x: int, cell_y: int,
                    tile_width: int, tile_height: int) -> bool:
        """Whether one cell is in `cells()`, without building the tuple."""
        return (cell_x, cell_y) in self.cells(tile_width, tile_height)


# --------------------------------------------------------------------------
# The whole declaration
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class MapEvent:
    """One authored region: what collides, where, and what happens.

    Frozen and hashable -- `args` is a tuple of pairs rather than a dict for
    exactly that reason -- so a load-time index may key on it, and so nothing
    downstream can mutate an author's declaration in place.
    """

    kind: str = ""
    filter: EntityFilter = field(default_factory=EntityFilter)
    blocks: bool = False
    once: bool = False
    cooldown_ms: int = 0
    payload: str = ""
    args: tuple[tuple[str, str], ...] = ()
    region: Region = field(default_factory=Region)
    layer: str = ""                 # tile layer anchor; "" means the whole map
    source_layer: str = ""          # the objectgroup it was authored on
    object_id: int = 0
    name: str = ""

    @property
    def declared(self) -> bool:
        """Is this object a map event at all?

        Solidity counts. An object that only says `blocks` never fires and
        still must reach the movement code, so "declared" cannot mean "has a
        trigger kind".
        """
        return bool(self.kind) or self.blocks

    @property
    def fires(self) -> bool:
        return bool(self.kind)

    @property
    def event_name(self) -> str:
        """The bus name a runtime dispatches under, or '' if it never fires."""
        return EVENT_NAMES.get(self.kind, "")

    @property
    def arguments(self) -> dict[str, str]:
        return dict(self.args)

    def accepts(self, entity_class: str = "", tags: Iterable[str] = ()) -> bool:
        return self.filter.matches(entity_class, tags)

    def cells(self, tile_width: int, tile_height: int) -> tuple[tuple[int, int], ...]:
        return self.region.cells(tile_width, tile_height)

    def to_properties(self) -> dict[str, Any]:
        """The tmx properties this declaration writes.

        Defaults are OMITTED rather than written explicitly: an absent
        property and one set to its default mean the same thing to `read`,
        and every property written is another line in the diff of a file
        under a byte-exactness contract.

        Ordered by `FIELDS`, so the same declaration always produces the same
        bytes in the same order.
        """
        values: dict[str, Any] = {}
        for capability in FIELDS:
            value = _authored(self, capability.key)
            if value != capability.default:
                values[capability.property_name] = value
        return values

    def describe(self) -> str:
        """One line, for a tooltip or a generated report."""
        if not self.declared:
            return "not a map event"
        where = "cell" if self.region.is_point else "region"
        parts = []
        if self.kind:
            parts.append(f"{self.kind} {where} fires for {self.filter.describe()}")
        else:
            parts.append(f"solid {where}")
        if self.blocks and self.kind:
            parts.append("and blocks")
        if self.payload:
            parts.append(f"-> {self.payload}")
        if self.once:
            parts.append("(once)")
        elif self.cooldown_ms:
            parts.append(f"(every {self.cooldown_ms} ms)")
        return " ".join(parts)


def _authored(event: MapEvent, key: str) -> Any:
    """One field of a MapEvent as the value its tmx property would hold."""
    if key == "trigger":
        return event.kind
    if key == "filter_tags":
        return format_names(event.filter.tags, fold=True)
    if key == "filter_class":
        return format_names(event.filter.classes)
    if key == "args":
        return format_args(event.args)
    return getattr(event, key)


# --------------------------------------------------------------------------
# Reading -- lenient, because a hand-edited tmx must not take anything down
# --------------------------------------------------------------------------

def _properties_of(obj: Any) -> Mapping[str, Any]:
    """The property mapping of a MapDocument object, a pytmx one, or a stub.

    Three shapes reach this: `MapProperties` (a live view over the XML),
    pytmx's plain dict, and whatever a test builds. All three answer
    `items()`; nothing else is assumed.
    """
    raw = getattr(obj, "properties", None)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return dict(raw.items())
    except (AttributeError, TypeError, ValueError):
        return {}


def read(obj: Any, *, layer: str = "", source_layer: str = "") -> MapEvent:
    """Read one object's declaration. NEVER raises.

    A nonsense value reads as undeclared rather than stopping the load --
    the same contract `layer_profile.read` holds -- but it warns on the way
    past. Silent fallback is how `pyoneer_trigger="entre"` becomes an
    afternoon of wondering why the door does nothing.
    """
    properties = _properties_of(obj)

    kind = _text(properties, TRIGGER).lower()
    if kind and kind not in TRIGGER_KINDS:
        warn_content(
            "map event on object %s declares %s=%r, which is not one of %s; "
            "reading it as no trigger" % (
                getattr(obj, "id", "?"), TRIGGER, kind, list(TRIGGER_KINDS)))
        kind = ""

    cooldown = _int(properties, COOLDOWN_MS, 0)
    if cooldown < 0:
        warn_content(
            "map event on object %s declares a negative %s (%d); using 0"
            % (getattr(obj, "id", "?"), COOLDOWN_MS, cooldown))
        cooldown = 0

    rotation = _float(getattr(obj, "rotation", 0.0))
    if rotation and (kind or _flag(properties, BLOCKS, False)):
        warn_content(
            "map event on object %s is rotated %g degrees; its cells are "
            "read from the unrotated rectangle, so the region the author "
            "sees and the region that fires are different"
            % (getattr(obj, "id", "?"), rotation))

    return MapEvent(
        kind=kind,
        filter=EntityFilter(
            tags=parse_names(properties.get(FILTER_TAGS, ""), fold=True),
            classes=parse_names(properties.get(FILTER_CLASS, ""))),
        blocks=_flag(properties, BLOCKS, False),
        once=_flag(properties, ONCE, False),
        cooldown_ms=cooldown,
        payload=_text(properties, PAYLOAD),
        args=parse_args(properties.get(ARGS, "")),
        region=Region.of_object(obj),
        layer=layer,
        source_layer=source_layer,
        object_id=_as_int(getattr(obj, "id", 0)),
        name=str(getattr(obj, "name", "") or ""),
    )


def read_anchor(layer: Any) -> str:
    """Which tile layer an objectgroup's regions are anchored to.

    Empty means the whole map, which is the right default: a trigger that
    does not care about elevation should not have to name a layer.
    """
    properties = getattr(layer, "properties", None)
    if properties is None:
        return ""
    try:
        mapping = properties if isinstance(properties, dict) else dict(properties.items())
    except (AttributeError, TypeError, ValueError):
        return ""
    return str(mapping.get(TRIGGER_LAYER, "") or "").strip()


def read_all(layer: Any) -> tuple[MapEvent, ...]:
    """Every declared map event on one object layer, in document order.

    Objects that declare nothing are dropped, so an entity spawn point
    sharing the layer costs nothing and confuses nobody.
    """
    anchor = read_anchor(layer)
    source = str(getattr(layer, "name", "") or "")
    objects = layer.objects() if callable(getattr(layer, "objects", None)) else layer
    found = []
    for obj in objects:
        event = read(obj, layer=anchor, source_layer=source)
        if event.declared:
            found.append(event)
    return tuple(found)


# --------------------------------------------------------------------------
# Validating -- strict, because the authoring door is where mistakes are cheap
# --------------------------------------------------------------------------

def validate(key: str, value: Any) -> Any:
    """Check one field by key. Raises ValueError with a usable message.

    Deliberately ValueError rather than an editor exception: the verb layer
    already translates ValueError into `PyoneerCommandArgumentError` (see
    `map.layer.set`), and staying dependency-free keeps this module on the
    engine's side of the boundary where it belongs.
    """
    capability = BY_KEY.get(key)
    if capability is None:
        raise ValueError(
            f"unknown map-event field {key!r}; known: {sorted(BY_KEY)}")

    coerced = capability.coerce(value)
    if coerced != value:
        if key == "trigger":
            raise ValueError(
                f"unknown trigger kind {value!r}; known: {list(TRIGGER_KINDS)} "
                f"(or '' for a region that never fires)")
        raise ValueError(f"{key!r} wants {capability.type}, got {value!r}")

    if key == "cooldown_ms" and coerced < 0:
        raise ValueError(f"cooldown_ms must not be negative, got {coerced}")
    if key in ("filter_tags", "filter_class") and value:
        names = parse_names(value, fold=(key == "filter_tags"))
        if not names:
            raise ValueError(
                f"{key!r} is {value!r}, which declares no usable names")
        # Re-format to prove the value survives a round trip rather than
        # trusting that it will.
        return format_names(names, fold=(key == "filter_tags"))
    if key == "args" and value:
        pairs = parse_args(value)
        if not pairs:
            raise ValueError(
                f"args is {value!r}, which declares no usable arguments")
        return format_args(pairs)          # raises on a duplicate key
    return coerced


def validate_properties(properties: Mapping[str, Any]) -> dict[str, Any]:
    """Check a whole `pyoneer_` property dict, by property NAME.

    Returns the coerced values. Raises on the first problem, because a
    half-applied declaration is worse than a rejected one.
    """
    checked: dict[str, Any] = {}
    for name, value in properties.items():
        check_property_name(name)
        capability = BY_PROPERTY.get(name)
        if capability is None:
            raise ValueError(
                f"unknown map-event property {name!r}; known: {sorted(KNOWN)}")
        checked[name] = validate(capability.key, value)
    return checked


def check_property_name(name: str) -> str:
    """Refuse a property name that would make the map unloadable.

    pytmx raises ValueError -- not a warning, not a skip -- when a custom
    property shadows one of its own attribute names, and the whole map stops
    loading. Nothing on the object-property path enforces this today, so an
    author who writes `visible` on a trigger breaks the map and finds out at
    the next boot.

    A `pyoneer_`-prefixed name this module does not know is NOT an error: the
    prefix is a namespace, not this module's private property. It warns,
    because a typo'd `pyoneer_triger` is far more likely than a second
    vocabulary, and returns the name.
    """
    if name in RESERVED:
        raise ValueError(
            f"property {name!r} shadows a pytmx attribute; pytmx raises on it "
            f"and the whole map stops loading. Prefix it: {PREFIX}{name}")
    if name.startswith(PREFIX) and name not in KNOWN:
        warn_content(
            "property %r is prefixed %r but is not a map-event field; "
            "known: %s" % (name, PREFIX, sorted(KNOWN)))
    return name


def describe_all() -> str:
    """Markdown for the generated request bundle, mirroring the layer table."""
    lines = ["| property | type | default | meaning |", "|---|---|---|---|"]
    for capability in FIELDS:
        doc = capability.doc
        if capability.key == "trigger":
            doc += f" One of {list(TRIGGER_KINDS)}."
        lines.append(f"| `{capability.property_name}` | {capability.type} | "
                     f"`{capability.default!r}` | {doc} |")
    lines.append(f"| `{TRIGGER_LAYER}` | str | `''` | On the OBJECTGROUP, not "
                 f"the object: which tile layer these regions are anchored to. "
                 f"Empty means the whole map. |")
    return "\n".join(lines)
