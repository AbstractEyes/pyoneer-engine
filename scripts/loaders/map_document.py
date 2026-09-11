"""A round-trip-safe read/WRITE document layer for Tiled .tmx files.

WHY THIS EXISTS
---------------
pytmx is read-only and lossy by design: it hands back a runtime view
(surfaces, resolved gids, flattened layers) with no memory of how the file on
disk was punctuated. That is right for rendering and wrong for editing, since
a human editing a map in Tiled and a program editing the same map only
collaborate while a programmatic write is a MINIMAL DIFF -- a writer that
reflows the document makes every later `git diff` all noise.

So the contract is stronger than "produces valid TMX":

    load(path) -> save(path)  is BYTE IDENTICAL when nothing was changed
    set_tile(x, y, gid)       changes the bytes of exactly one csv token
    add_object + remove_object returns the original bytes

`tools/check_tmx_roundtrip.py` byte-compares that against a deliberately
AWKWARD fixture it builds itself, and once against the shipped
data/maps/starter.tmx.

WHAT AN UNTIDY TILED FILE ACTUALLY LOOKS LIKE
---------------------------------------------
A .tmx a human has been editing is not tidy, and pretending otherwise is how
a writer breaks. Measured on the private canvas this module was written
against -- retired on 2026-09-04, and every property below is now written
into `check_tmx_roundtrip`'s own fixture so the coverage is guaranteed rather
than borrowed:

  * CRLF line endings throughout. An XML parser is REQUIRED by spec to
    normalize CRLF to LF while parsing, so every `\\r` is gone by the time
    ElementTree hands you a tree. Naive re-serialization loses 641 bytes.
  * Inconsistent indentation. The first elements use tabs
    (`\\t<tileset ...>`); everything from the second <layer> down uses one,
    two or three SPACES; and every `</data>` sits at column 0.
  * ...and a file may be none of those things: `data/maps/starter.tmx` is
    uniform LF with uniform one-space indent. Both round-trip byte-exactly,
    which is the actual contract -- reproduce what you were given.
  * ElementTree writes `<export ... format="tmx" />` with a space before the
    slash. Tiled writes `<export ... format="tmx"/>` with none.
  * ElementTree writes `<?xml version='1.0' encoding='UTF-8'?>` with single
    quotes. Tiled writes double quotes.

None of that is recoverable from a pretty-printer, so this module does not
pretty-print. It keeps the parsed tree's `text`/`tail` whitespace verbatim,
re-emits the original XML declaration byte for byte, restores the original
newline convention on the way out, and writes empty elements with no space
before `/>`.

WHAT IS DELIBERATELY NOT HANDLED
--------------------------------
  * base64 / compressed layer data. Reading a `<data encoding="base64">`
    layer through tile_layer() raises rather than silently mangling it.
  * infinite maps (`<chunk>` children under `<data>`). Same: raises.
  * a DOCTYPE, or comments/PIs sitting OUTSIDE the root element. Tiled emits
    neither, and ElementTree discards the latter.
Everything else in the document -- unknown elements, unknown attributes,
future Tiled versions -- passes through untouched, because the writer walks
the parsed tree rather than a model of what it thinks TMX contains.

PROPERTY TYPES
--------------
Tiled writes `type="int"` / `"bool"` / `"float"` / `"color"` / `"file"` /
`"object"` on custom properties and OMITS the attribute for plain strings.
Without it a `depth` of 50 reads back as the string '50', and `'50' * 2` is
'5050' rather than 100.

pytmx (3.32) honours the type attribute on READ, and `check_tmx_roundtrip`
asserts that pytmx and this module agree on the same file. What pytmx has no
equivalent for is the WRITE side: nothing in it can emit `type="int"`, and a
property written without one is silently downgraded to a string for every
future reader. `format_property` checks `bool` before `int`, because in
Python `bool` IS an `int` and `type="int" value="True"` is a file Tiled
rejects.

One pytmx gap this module does not share: it reads a property's value as
`subnode.get("value") or subnode.text` and then casts
`cls(subnode.get("value"))`, so a MULTI-LINE property -- which Tiled moves
into the element body, dropping the `value` attribute -- raises there if it
is typed. `MapProperties` reads the body text instead.
"""
from __future__ import annotations

import copy
import os
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from typing import Any, Iterator

from scripts.core.errors import PyoneerAssetMissingError, PyoneerConfigError, warn_content
from scripts.core.layer_profile import (ATTRIBUTE_TEXT, PREFIX,
                                       PROPERTY_TEXT, RESERVED,
                                       text_reads_back)
from scripts.core.log import trace_assets


def subcell_property() -> str:
    """The tmx layer property that declares a companion's sub-cell factor.

    A LOOKUP, never a second spelling. `scripts/core/collision_runtime.py`
    owns that string -- it is file format, so law 8 makes it stable once
    referenced and a retype here would be a rename waiting to disarm every
    companion carrying it. This module only needs the name to write it and to
    name it in a refusal, and it imports it late because collision is the one
    thing a map WRITER has no business dragging in at import time.
    """
    from scripts.core.collision_runtime import SUBCELL
    return SUBCELL


# ---------------------------------------------------------------------------
# Serialization primitives
#
# These reproduce ElementTree's escaping rules, with two deliberate
# differences from ElementTree.tostring: no space before `/>` on an empty
# element, and no XML declaration (the caller re-emits the original one).
# ---------------------------------------------------------------------------

_DECLARATION_RE = re.compile(rb"\A(<\?xml[^>]*\?>)(\r\n|\r|\n)?")
_DEFAULT_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>'
_CSV_TOKEN_RE = re.compile(r"\d+")
_TRAILING_INDENT_RE = re.compile(r"[ \t]*\Z")

# XML 1.0 (5th ed.) `Name`, transcribed from the grammar rather than guessed
# at. `_serialize` interpolates an attribute name straight into the output
# with no escaping -- an attribute NAME has no escape, unlike its value -- so
# a name outside this production writes bytes that no XML parser can read
# back, including this module's own loader. That is the one place a writer
# can destroy the round-trip contract by writing, so the one door that takes
# a caller-supplied name checks it here. Every other name this module emits
# is a literal in this file or came back out of a parser that already
# enforced the same production.
_NAME_START = (
    ":A-Z_a-z"
    "\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff"
    "\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf"
    "\ufdf0-\ufffd\U00010000-\U000effff"
)
_NAME_REST = _NAME_START + "\\-.0-9\u00b7\u0300-\u036f\u203f-\u2040"
_XML_NAME_RE = re.compile("[%s][%s]*" % (_NAME_START, _NAME_REST))


def _escape_text(text: str) -> str:
    """Escape character data. Matches ElementTree._escape_cdata."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attribute(value: str) -> str:
    """Escape an attribute value. Matches ElementTree._escape_attrib.

    The `\\r` -> `&#13;` step is what makes a newline inside a multi-line
    property value survive a round trip: without it the parser's CRLF
    normalization would eat it.
    """
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    value = value.replace('"', "&quot;")
    return value.replace("\r", "&#13;").replace("\n", "&#10;").replace("\t", "&#9;")


def _ordered_attributes(
    element: ElementTree.Element,
    spellings: dict[ElementTree.Element, tuple[str, ...]] | None,
) -> list[tuple[str, Any]]:
    """This element's attributes in the order the FILE spells them.

    READ OFF THE FILE, NEVER COMPUTED -- the sentence `_separator_of` is
    written under, applied to the other axis of the same contract. There it
    is the whitespace in front of a child; here it is the left-to-right
    order of an attribute list, and both are destroyed the same way: by a
    writer that computes a plausible answer instead of copying the one the
    file already gave.

    `Element.attrib` is a plain dict, so `Element.set` APPENDS any name not
    already present -- which makes removing an attribute and putting it back
    move it to the END of the list. Measured on a nine-attribute `<object>`:
    eight of the nine attributes `map.object.unset` accepts came back last,
    so apply-then-undo left one line of diff nobody authored and
    `MapDocument.changed` reported the map dirty after a NO-OP PAIR. The
    ninth passed only because it was already last, which is the exact shape
    of an assertion that cannot fail.

    `spellings` holds the order each element was last seen spelling, keyed
    by element. A name it does not carry is emitted after the ones it does,
    in `attrib` order, so a genuinely NEW attribute still appends -- the
    memory restores a position, it never invents one.
    """
    known = spellings.get(element) if spellings else None
    if not known:
        return list(element.attrib.items())
    attrib = element.attrib
    ordered = [(key, attrib[key]) for key in known if key in attrib]
    remembered = set(known)
    ordered += [(key, value) for key, value in attrib.items()
                if key not in remembered]
    return ordered


def _serialize(element: ElementTree.Element, parts: list[str],
               spellings: dict[ElementTree.Element, tuple[str, ...]] | None = None,
               ) -> None:
    """Append `element` to `parts`, preserving its whitespace verbatim."""
    tag = element.tag
    if tag is ElementTree.Comment:
        parts.append("<!--%s-->" % (element.text or ""))
    elif tag is ElementTree.ProcessingInstruction:
        parts.append("<?%s?>" % (element.text or ""))
    else:
        parts.append("<" + tag)
        for key, value in _ordered_attributes(element, spellings):
            parts.append(' %s="%s"' % (key, _escape_attribute(str(value))))
        children = list(element)
        # `text is None` distinguishes `<a/>` from `<a></a>`, which is the
        # only signal ElementTree keeps about which form the file used.
        if element.text is None and not children:
            parts.append("/>")
        else:
            parts.append(">")
            if element.text:
                parts.append(_escape_text(element.text))
            for child in children:
                _serialize(child, parts, spellings)
            parts.append("</" + tag + ">")
    if element.tail:
        parts.append(_escape_text(element.tail))


# ---------------------------------------------------------------------------
# Custom property typing
# ---------------------------------------------------------------------------

def parse_property(type_name: str | None, raw: str) -> Any:
    """Turn a Tiled property's on-disk string into a real Python value.

    An unparseable value warns and falls back to the string rather than
    raising: a typo in one property in Tiled should not stop the engine, but
    it must not be invisible either.
    """
    if type_name in (None, "", "string", "color", "file"):
        return raw
    try:
        if type_name == "int" or type_name == "object":
            return int(raw)
        if type_name == "float":
            return float(raw)
        if type_name == "bool":
            return raw == "true"
    except ValueError:
        warn_content(
            "tmx property declares type=%r but its value %r does not parse; "
            "using the raw string" % (type_name, raw)
        )
        return raw
    warn_content("unknown tmx property type %r; treating %r as a string" % (type_name, raw))
    return raw


def format_property(value: Any) -> tuple[str | None, str]:
    """Inverse of parse_property: (type attribute or None, value string).

    `bool` is checked before `int` because bool IS an int in Python, and
    writing type="int" value="True" would produce a file Tiled rejects.
    """
    if isinstance(value, bool):
        return "bool", "true" if value else "false"
    if isinstance(value, int):
        return "int", str(value)
    if isinstance(value, float):
        return "float", repr(value)
    return None, str(value)


# ---------------------------------------------------------------------------
# The raw-XML door
#
# `MapObject.set` and `MapProperties.__setitem__` each refuse the names pytmx
# cannot survive, one name at a time, at the moment a caller writes one. The
# three `restore_*` verbs take a whole ELEMENT as text and hang its attributes
# on the document verbatim, so until this door existed they walked past both
# of those guards -- and `map.object.restore` is reachable from a script and
# from the relay, which is the AI edit path this editor's whole design treats
# as equal to a human's. A response bundle could smuggle in an attribute no
# human control would accept.
#
# MEASURED on the unguarded verb, both halves:
#
#   <object ... pyoneer_script="smuggled"/>  was ACCEPTED. The attribute
#     reached the file, pytmx loaded the map, and `obj.properties` -- the only
#     place the engine ever looks -- came back `{}`, with the value hung on the
#     object as a bare Python attribute instead. Law 7's failure shape written
#     into a file: the write looks like it took and nothing reads it.
#   the same name as an ATTRIBUTE and as a <property> was ACCEPTED too, and
#     pytmx then raised `ValueError: Reserved names and duplicate names are
#     not allowed` -- the WHOLE map unloadable, naming neither. Law 1's cost.
#
# So the refusal lives at the PARSE and nowhere else: every route that turns
# authored text into elements comes through `_parse_restored_element`, which
# is why adding a fourth restore verb cannot reopen this. Three copies of one
# guard at three call sites is this repository's most-repeated defect shape,
# and the pass before this one counted nine sightings of it.
# ---------------------------------------------------------------------------

# The element kinds pytmx casts XML attributes onto and then refuses a
# shadowing `<property>` for: exactly the tags whose parser reaches
# `TiledElement._set_properties`. MEASURED off the installed pytmx, and the
# OMISSIONS carry as much weight as the members. A `<tile>` is deliberately
# absent -- pytmx merges a tile's attributes and its properties into one
# dict, so neither the silent half nor the fatal half can happen there, and
# refusing it would refuse a legitimate `<tileset>` payload. So is a
# `<property type="class">`'s own nested `<properties>`, whose members are set
# on a `TiledClassType` that is checked against nothing; `findall` below is
# direct children only, which is what leaves those alone.
_PYTMX_CAST_TAGS = frozenset({
    "map", "tileset", "group", "layer", "objectgroup", "object", "imagelayer",
})


def _refuse_smuggled_names(element: ElementTree.Element, verb: str,
                           source: str | None) -> None:
    """Raise unless every name in `element`'s subtree is one pytmx survives.

    The subtree, not the top element: a restored `<objectgroup>` carries its
    `<object>` children and a restored `<tileset>` carries its `<tile>`
    children, so a smuggled name one level down is the same defect wearing a
    parent.

    The PREFIX rule is checked on every element, the collision rule only on
    the tags pytmx casts attributes onto. That asymmetry is deliberate and it
    costs nothing: Tiled writes no `pyoneer_` attribute anywhere, so the wider
    rule cannot refuse a payload any authoring tool produces, and one rule
    decidable with no lookup is the rule the next author will actually apply
    -- the same reason `MapObject.set` refuses the prefix before it consults
    anything.

    REFUSES, never sanitises. Stripping the attribute would leave the author's
    text and the document disagreeing about what was restored, which is the
    same class of failure one layer along -- and for `map.*.restore` it would
    break the inverse as well, since a command's undo has to put back the
    bytes it took away and not an edited version of them.

    Called BEFORE anything is appended to the document, so a refusal leaves
    the bytes exactly as it found them. A guard that has already mutated the
    tree is worse than no guard: the caller catches the exception, saves, and
    ships the broken file anyway.
    """
    for owner in element.iter():
        tag = owner.tag if isinstance(owner.tag, str) else "?"
        for name in owner.attrib:
            if not name.startswith(PREFIX):
                continue
            raise PyoneerConfigError(
                f"{verb} was handed an <{tag}> carrying {name!r} as an XML "
                f"ATTRIBUTE. A {PREFIX!r} name is a custom PROPERTY and never "
                f"an attribute: on every element the engine reads, pytmx hangs "
                f"an attribute on the element itself and leaves .properties -- "
                f"the only place the engine looks -- empty, so the write "
                f"reaches the file, the map still loads, and nothing reads it. "
                f"It belongs in a <property name={name!r} ...> inside that "
                f"element's <properties>, which is what "
                f"map.object.property.set writes. Refused rather than "
                f"stripped: an element quietly rewritten on the way in is not "
                f"the element the caller serialized, and an undo that restores "
                f"the value but not the bytes is not an inverse.",
                source=source, element=tag)
        if tag not in _PYTMX_CAST_TAGS:
            continue
        for container in owner.findall("properties"):
            for entry in container.findall("property"):
                name = entry.get("name", "")
                carried = name in owner.attrib
                if not carried and name not in RESERVED:
                    continue
                where = ("already carries %r as an XML attribute" % name
                         if carried else
                         "is a pytmx element, and %r is a name pytmx puts on "
                         "one" % name)
                remedy = (("Delete that attribute from the element -- nothing "
                           "should have written it.")
                          if name.startswith(PREFIX) else
                          "Law 1's answer is the prefix: name it %s%s."
                          % (PREFIX, name))
                raise PyoneerConfigError(
                    f"{verb} was handed an <{tag}> that {where}, so its "
                    f"<property> of the same name makes the map unloadable: "
                    f"pytmx sets every attribute on the element first and then "
                    f"RAISES on any property that shadows one of its own names, "
                    f"and it takes the WHOLE map with it, naming neither. "
                    f"{remedy}",
                    source=source, element=tag)


def _refuse_unreadable_text(element: ElementTree.Element, verb: str,
                            source: str | None) -> None:
    """Raise unless every VALUE in `element`'s subtree reads back out of tmx.

    THE SIBLING OF `_refuse_smuggled_names`, AND IT IS A SIBLING BECAUSE THE
    NAME DOOR WAS BUILT AND THE VALUE DOOR WAS NOT. The name rule refuses
    `<object pyoneer_script="...">` and says nothing at all about
    `<object width="abc"/>`, which costs the identical thing -- pytmx casts
    every attribute onto the element before it reads one property, so the
    cast raises and takes the WHOLE map with it, naming neither the map nor
    the attribute. Measured through the relay on all three restore verbs
    before this existed: `<object width="abc"/>`, `<layer width="abc">` and
    `<tileset firstgid="abc">` were all ACCEPTED.

    Both halves ask ONE table -- `ATTRIBUTE_TEXT` in
    `scripts/core/layer_profile.py`, which `editor/core/verbs.py`
    re-exports for its typed command arguments. An attribute no reader casts
    is absent from that table and any text is legal there, which is why this
    cannot refuse a payload Tiled writes.

    A `<property>` is the same question asked through its own `type=`:
    `<property type="int" value="NaN"/>` is the same unloadable map, and it
    is a door the TYPED route cannot even build, because
    `MapProperties.__setitem__` derives `type=` from the Python value. An
    unknown `type=` is refused too: pytmx subscripts its `prop_type` table
    and a KeyError there is the same whole-map loss.

    REFUSES, never repairs, and runs BEFORE anything is appended -- for the
    reasons `_refuse_smuggled_names` states at length.
    """
    for owner in element.iter():
        tag = owner.tag if isinstance(owner.tag, str) else "?"
        for name, value in owner.attrib.items():
            wants = ATTRIBUTE_TEXT.get(name)
            if wants is None or text_reads_back(wants, value):
                continue
            raise PyoneerConfigError(
                f"{verb} was handed an <{tag}> whose {name}={value!r} is not "
                f"{wants.__name__} text. A reader casts that attribute, so "
                f"writing it makes the WHOLE map unloadable -- the cast "
                f"raises inside the loader, naming neither the map, the "
                f"element nor the attribute -- and the element would still "
                f"be there to serialize. Refused rather than repaired: an "
                f"element quietly rewritten on the way in is not the element "
                f"the caller serialized, and for a restore verb that breaks "
                f"the inverse as well.",
                source=source, element=tag)
        if tag != "property":
            continue
        declared = owner.get("type")
        if declared is None or declared == "class":
            continue
        if declared not in PROPERTY_TEXT:
            raise PyoneerConfigError(
                f"{verb} was handed a <property name="
                f"{owner.get('name')!r} type={declared!r}>, and pytmx has no "
                f"such property type. It looks its table up by subscript, so "
                f"an unknown one raises and takes the WHOLE map with it. The "
                f"types a reader knows are: "
                f"{', '.join(sorted(PROPERTY_TEXT))}, class.",
                source=source, element=tag)
        text = owner.get("value")
        if text is None or text_reads_back(PROPERTY_TEXT[declared], text):
            continue
        raise PyoneerConfigError(
            f"{verb} was handed a <property name={owner.get('name')!r} "
            f"type={declared!r} value={text!r}>, and {text!r} is not "
            f"{PROPERTY_TEXT[declared].__name__} text. The type attribute "
            f"is a cast instruction to the reader, so the map stops loading "
            f"entire. map.object.property.set cannot build this at all -- it "
            f"writes type= FROM the Python value -- which is the measure of "
            f"what the raw-XML door is for.",
            source=source, element=tag)


def _parse_restored_element(xml: str, verb: str, kind: str,
                            tags: tuple[str, ...],
                            source: str | None) -> ElementTree.Element:
    """The ONE door authored XML text enters this document through.

    `fromstring` checks that the names are legal XML and nothing else, so all
    four things a restored element has to be -- parseable, the tag this verb
    restores, free of any name pytmx cannot survive, and free of any VALUE
    pytmx cannot cast -- are settled here rather than once per caller.

    The fourth arrived a pass after the third and is the reason this door is
    worth having: a guard that reads NAMES and not VALUES refuses
    `<object pyoneer_x="1"/>` and accepts `<object width="abc"/>`, which
    costs the whole map. One door, so a fifth rule reaches every restore
    verb by being written once.
    """
    try:
        parsed = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise PyoneerConfigError(
            "%s was handed text that is not %s: %s" % (verb, kind, exc),
            source=source) from exc
    if parsed.tag not in tags:
        raise PyoneerConfigError(
            "%s expects %s, got <%s>" % (verb, kind, parsed.tag), source=source)
    _refuse_smuggled_names(parsed, verb, source)
    _refuse_unreadable_text(parsed, verb, source)
    return parsed


class MapProperties:
    """Typed dict-like view over one element's `<properties>` child.

    The view is live: it reads and writes the underlying elements, so it
    always agrees with what save() will emit. It creates the `<properties>`
    container lazily, only on the first write, so merely *reading* the
    properties of an element that has none leaves the bytes alone.
    """

    def __init__(self, document: "MapDocument", owner: ElementTree.Element):
        self._document = document
        self._owner = owner

    # -- internals ---------------------------------------------------------
    def _container(self) -> ElementTree.Element | None:
        return self._owner.find("properties")

    def _entries(self) -> list[ElementTree.Element]:
        container = self._container()
        return [] if container is None else container.findall("property")

    @staticmethod
    def _raw_value(entry: ElementTree.Element) -> str:
        # Tiled moves multi-line string values out of the attribute and into
        # the element body; without this branch they read back as ''.
        if "value" in entry.attrib:
            return entry.get("value", "")
        return entry.text or ""

    def _find(self, name: str) -> ElementTree.Element | None:
        for entry in self._entries():
            if entry.get("name") == name:
                return entry
        return None

    # -- mapping surface ---------------------------------------------------
    def __contains__(self, name: str) -> bool:
        return self._find(name) is not None

    def __iter__(self) -> Iterator[str]:
        return iter(entry.get("name", "") for entry in self._entries())

    def __len__(self) -> int:
        return len(self._entries())

    def __getitem__(self, name: str) -> Any:
        entry = self._find(name)
        if entry is None:
            raise PyoneerAssetMissingError("map property", name, available=list(self))
        return parse_property(entry.get("type"), self._raw_value(entry))

    def get(self, name: str, default: Any = None) -> Any:
        entry = self._find(name)
        if entry is None:
            return default
        return parse_property(entry.get("type"), self._raw_value(entry))

    def keys(self) -> list[str]:
        return list(self)

    def items(self) -> list[tuple[str, Any]]:
        return [(name, self[name]) for name in self]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.items())

    def __repr__(self) -> str:
        return "MapProperties(%r)" % (self.as_dict(),)

    def __setitem__(self, name: str, value: Any) -> None:
        """Write one custom property, typed.

        The mirror of `MapObject.set`, and refusing the mirror refusal is
        the whole reason this branch exists: pytmx casts an element's XML
        attributes onto itself first and then RAISES on any `<property>`
        whose name it now shadows, so `<layer name="Floor">` plus
        `<property name="name">` is an unloadable map -- measured, for every
        owner kind this view is used on. The collision is symmetric, so a
        guard on the attribute door alone would leave the map exactly as
        unloadable, which is this repository's most-repeated defect shape.

        AND THE CLASS-LEVEL NAMES, which `attrib` cannot see. pytmx gives an
        object a default `rotation` and a layer a default `opacity` whether
        the file writes them or not, and `TiledTileLayer` subclasses `list`,
        so `rotation`, `opacity` and `append` are all fatal on elements whose
        `attrib` holds none of them. `RESERVED` in
        `scripts/core/layer_profile.py` is that set, measured off pytmx by
        `tools/check_tmx_roundtrip.py` rather than remembered, and the editor
        RE-EXPORTS it from there (law 2's corollary: one home, not two).
        It lived in `editor/core/layers.py` while this door had no guard at
        all -- which meant the one module that could enforce it was the one
        module forbidden to read it.

        Unlike an attribute name, a property name needs no XML-name check:
        it is written into an attribute VALUE (`<property name="...">`),
        which `_escape_attribute` escapes, so a name no XML parser would
        accept as an element name still round-trips here. Measured.
        """
        if name in self._owner.attrib or name in RESERVED:
            tag = self._owner.tag
            carried = name in self._owner.attrib
            where = ("already carries %r as an XML attribute" % name
                     if carried else
                     "is a pytmx element, and %r is a name pytmx puts on one"
                     % name)
            if name.startswith(PREFIX):
                remedy = ("Delete that attribute from the element -- nothing "
                          "should have written it, and MapObject.set refuses "
                          "a %r name now." % (PREFIX,))
            else:
                remedy = ("Law 1's answer is the prefix: name it %s%s."
                          % (PREFIX, name))
            raise PyoneerConfigError(
                f"<{tag}> {where}, so a <property> of the same name makes the "
                f"map unloadable: pytmx sets every attribute on the element "
                f"first and then RAISES on any property that shadows one of "
                f"its own names. {remedy}",
                source=self._document.path, element=tag)
        type_name, text = format_property(value)
        entry = self._find(name)
        if entry is None:
            container = self._container()
            if container is None:
                container = self._document._append_child(self._owner, "properties", index=0)
            entry = self._document._append_child(container, "property")
            entry.set("name", name)
        else:
            # A property already declared color/file/object keeps its type
            # when overwritten with a string; re-inferring would silently
            # downgrade it and Tiled would lose the colour picker.
            existing = entry.get("type")
            if type_name is None and existing in ("color", "file", "object"):
                type_name = existing
            entry.text = None
        if type_name is None:
            # THE SIBLING OF `map.object.unset`, in this file rather than in
            # the editor. Overwriting `<property type="int" value="30"/>`
            # with a string drops `type`; typing it back re-adds it, and
            # `Element.set` appends -- so `type` came back AFTER `value` and
            # a set-then-undo left a line of diff nobody authored. The order
            # is recorded here, before the pop, because after it there is
            # nothing left to read.
            self._document._remember_attributes(entry)
            entry.attrib.pop("type", None)
        else:
            entry.set("type", type_name)
        entry.set("value", text)
        self._document._touch()

    def __delitem__(self, name: str) -> None:
        container = self._container()
        entry = self._find(name)
        if container is None or entry is None:
            raise PyoneerAssetMissingError("map property", name, available=list(self))
        self._document._remove_child(container, entry)
        if not list(container):
            self._document._remove_child(self._owner, container)
        self._document._touch()


# ---------------------------------------------------------------------------
# Tile layers
# ---------------------------------------------------------------------------

class _CsvGrid:
    """The csv payload of a `<data>` element, split into values and gaps.

    Storing the SEPARATORS alongside the values is the whole trick. The
    payload is reassembled as sep[0] + str(v[0]) + sep[1] + str(v[1]) + ...,
    so every newline, every trailing comma, and the fact that the last row
    happens to have no trailing comma are all reproduced without this class
    knowing any of them exist. Rewriting one value therefore rewrites one
    token and nothing else.
    """

    def __init__(self, text: str):
        self.separators: list[str] = []
        self.values: list[int] = []
        position = 0
        for match in _CSV_TOKEN_RE.finditer(text):
            self.separators.append(text[position:match.start()])
            self.values.append(int(match.group()))
            position = match.end()
        self.separators.append(text[position:])

    def render(self) -> str:
        parts: list[str] = []
        for separator, value in zip(self.separators, self.values):
            parts.append(separator)
            parts.append(str(value))
        parts.append(self.separators[-1])
        return "".join(parts)


class TileLayer:
    """Read/write access to one csv-encoded `<layer>`'s gids."""

    def __init__(self, document: "MapDocument", element: ElementTree.Element):
        self._document = document
        self.element = element
        self.name = element.get("name", "")
        self.id = int(element.get("id", "0"))
        self.width = int(element.get("width") or document.width)
        self.height = int(element.get("height") or document.height)

        data = element.find("data")
        if data is None:
            raise PyoneerConfigError(
                "tile layer %r has no <data> element" % self.name,
                source=document.path,
            )
        if data.find("chunk") is not None:
            raise PyoneerConfigError(
                "tile layer %r is chunked (infinite map); this writer only "
                "handles finite maps" % self.name,
                source=document.path,
            )
        encoding = data.get("encoding")
        if encoding != "csv":
            raise PyoneerConfigError(
                "tile layer %r uses encoding=%r; save the map with CSV layer "
                "data in Tiled (Edit > Preferences > General > Tile layer "
                "format) so edits stay diffable" % (self.name, encoding),
                source=document.path,
            )
        self._data = data
        self._grid = _CsvGrid(data.text or "")
        self._dirty = False

        expected = self.width * self.height
        if len(self._grid.values) != expected:
            warn_content(
                "tile layer %r declares %dx%d (%d tiles) but its csv holds %d"
                % (self.name, self.width, self.height, expected, len(self._grid.values))
            )

    # -- geometry ----------------------------------------------------------
    def __len__(self) -> int:
        return len(self._grid.values)

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def _index(self, x: int, y: int) -> int:
        if not self.in_bounds(x, y):
            raise PyoneerConfigError(
                "tile (%d, %d) is outside layer %r (%dx%d)"
                % (x, y, self.name, self.width, self.height),
                source=self._document.path,
            )
        return y * self.width + x

    # -- reads -------------------------------------------------------------
    def get_tile(self, x: int, y: int) -> int:
        return self._grid.values[self._index(x, y)]

    def gids(self) -> list[int]:
        """A flat copy of every gid, row-major. Safe to mutate."""
        return list(self._grid.values)

    def rows(self) -> list[list[int]]:
        values = self._grid.values
        return [values[y * self.width:(y + 1) * self.width] for y in range(self.height)]

    # -- writes ------------------------------------------------------------
    def _require_gid(self, gid: int) -> int:
        """Reject a gid the csv encoding cannot round-trip.

        The serializer joins values with commas and the reader is
        `re.compile(r"\\d+")`, which treats a leading '-' as a SEPARATOR. So a
        negative gid does not fail: `fill(rect, -5)` writes '-5,-5' and reads
        back as 5, with the tile count still correct and nothing warning. A
        plausible wrong number is the worst outcome for a map file, so this is
        a hard error, and every writer goes through it.
        """
        gid = int(gid)
        if gid < 0:
            raise PyoneerConfigError(
                "gid %d is negative; tmx gids are unsigned (0 means empty)" % gid,
                source=self._document.path,
            )
        return gid

    def set_tile(self, x: int, y: int, gid: int) -> bool:
        """Set one gid. Returns True if the value actually changed.

        Writing the value it already holds is a no-op down to the byte, so a
        tool that re-stamps an unchanged region produces an empty diff.
        """
        index = self._index(x, y)
        gid = self._require_gid(gid)
        if self._grid.values[index] == gid:
            return False
        self._grid.values[index] = gid
        self._dirty = True
        self._document._touch()
        trace_assets("set_tile layer=%s x=%s y=%s gid=%s", self.name, x, y, gid)
        return True

    def fill(self, rect: Any, gid: int) -> int:
        """Set every tile in `rect` to `gid`. Returns the number changed.

        `rect` is anything with .x/.y/.width/.height (a pygame.Rect) or a
        4-tuple (x, y, width, height). The rect is clipped to the layer, so
        an over-large brush is a partial fill rather than an error.
        """
        gid = self._require_gid(gid)
        x, y, width, height = _as_rect(rect)
        left, top = max(0, x), max(0, y)
        right, bottom = min(self.width, x + width), min(self.height, y + height)
        changed = 0
        for row in range(top, bottom):
            for column in range(left, right):
                index = row * self.width + column
                if self._grid.values[index] != gid:
                    self._grid.values[index] = gid
                    changed += 1
        if changed:
            self._dirty = True
            self._document._touch()
            trace_assets("fill layer=%s rect=%s gid=%s changed=%s",
                         self.name, (x, y, width, height), gid, changed)
        return changed

    @property
    def properties(self) -> MapProperties:
        return MapProperties(self._document, self.element)

    def _flush(self) -> None:
        """Push pending gid edits back into the element, once per save.

        fill() over a 100x100 layer would be 10,000 full re-renders of a
        ~30KB string if this happened per set_tile.
        """
        if self._dirty:
            self._data.text = self._grid.render()
            self._dirty = False

    def __repr__(self) -> str:
        return "TileLayer(%r, %dx%d)" % (self.name, self.width, self.height)


def _as_rect(rect: Any) -> tuple[int, int, int, int]:
    if hasattr(rect, "width") and hasattr(rect, "x"):
        return int(rect.x), int(rect.y), int(rect.width), int(rect.height)
    x, y, width, height = rect
    return int(x), int(y), int(width), int(height)


# ---------------------------------------------------------------------------
# Object layers
# ---------------------------------------------------------------------------

class MapObject:
    """One `<object>` inside an `<objectgroup>`."""

    def __init__(self, document: "MapDocument", element: ElementTree.Element):
        self._document = document
        self.element = element

    @property
    def id(self) -> int:
        return int(self.element.get("id", "0"))

    @property
    def name(self) -> str:
        return self.element.get("name", "")

    @property
    def type(self) -> str:
        # Tiled 1.9 renamed the attribute to "class"; accept both so a map
        # re-saved by a newer Tiled does not read back as untyped.
        return self.element.get("type") or self.element.get("class") or ""

    @property
    def gid(self) -> int:
        return int(self.element.get("gid", "0"))

    @property
    def x(self) -> float:
        return float(self.element.get("x", "0"))

    @property
    def y(self) -> float:
        return float(self.element.get("y", "0"))

    @property
    def width(self) -> float:
        return float(self.element.get("width", "0"))

    @property
    def height(self) -> float:
        return float(self.element.get("height", "0"))

    @property
    def properties(self) -> MapProperties:
        return MapProperties(self._document, self.element)

    def set(self, key: str, value: Any) -> None:
        """Write a built-in `<object>` XML ATTRIBUTE -- `x`, `y`, `name`, `gid`.

        NOT the door for a custom property, and the distinction is not
        cosmetic. `<object pyoneer_script="greeting">` and an `<object>`
        carrying `<property name="pyoneer_script" .../>` are different
        documents: pytmx casts every XML attribute onto the `TiledObject` as
        a plain Python attribute and leaves `obj.properties` empty, and the
        engine reads `obj.properties` everywhere. Measured -- the map still
        loads, the write looks like it took, and nothing reads it. That is
        law 7's failure shape written into a file.

        The other half is law 1's stated cost arriving through a sanctioned
        writer. pytmx sets the attributes FIRST and then refuses any
        `<property>` whose name it now shadows, so the same call on a name
        the object already carries as a property raises `ValueError:
        Reserved names and duplicate names are not allowed` and the whole
        map stops loading. Which half an author gets depends only on whether
        the property has been written yet, so the silent write today is the
        unloadable map the first time somebody uses the correct door.

        Three refusals, and none of them is a table anyone has to keep:

          1. a `pyoneer_`-prefixed name. The prefix MEANS custom property,
             so it is decidable with no lookup at all. It refuses rather
             than quietly rerouting to `.properties[...]`: two methods doing
             one job is how the next author stops being able to tell which
             one they used.
          2. a name this element already carries as a `<property>` -- the
             fatal collision above, read off the document rather than
             guessed at.
          3. a name outside `_XML_NAME_RE`, because `_serialize` writes an
             attribute name with no escaping and a bad one produces bytes
             this module's own loader cannot parse back. The ParseError
             arrives at the next load, names a column, and names nothing
             that would find the caller.

        All three are checked BEFORE the write, so a refused call leaves the
        document byte-identical -- a refusal that has already mutated the
        tree is worse than none.

        `MapProperties.__setitem__` refuses the mirror image, a property
        named after an attribute the same element already carries, so
        neither door can build the collision the other one is refusing.
        """
        if key.startswith(PREFIX):
            raise PyoneerConfigError(
                f"{key!r} starts with {PREFIX!r}, so it is a custom PROPERTY "
                f"and never an <object> attribute. Written here it lands in "
                f"the element's attribute list, where the engine never looks "
                f"-- and makes the map unloadable the moment the real "
                f"property is added. Write "
                f"object.properties[{key!r}] = ... instead (the editor verb "
                f"is map.object.property.set).",
                source=self._document.path, object_id=self.id)
        if key in self.properties:
            raise PyoneerConfigError(
                f"this object already carries {key!r} as a custom property, "
                f"and pytmx RAISES on a map where an attribute and a property "
                f"share a name -- the whole map stops loading, naming neither. "
                f"Write object.properties[{key!r}] = ... instead, or delete "
                f"the property first.",
                source=self._document.path, object_id=self.id)
        if _XML_NAME_RE.fullmatch(key) is None:
            raise PyoneerConfigError(
                f"{key!r} is not a legal XML attribute name, so the bytes it "
                f"would write cannot be parsed back -- not by Tiled, not by "
                f"pytmx, and not by MapDocument.load.",
                source=self._document.path, object_id=self.id)
        self.element.set(key, _attribute_text(value))
        self._document._touch()

    def unset(self, key: str) -> str | None:
        """Remove a built-in `<object>` XML attribute -- the twin of `set`.

        Returns the removed text, or None when the element never carried it
        -- which is the value `map.object.set` needs to put it back, so the
        caller's inverse is this method's return value.

        THE POSITION IS THE POINT, AND THIS METHOD DOES NOT KEEP IT. That
        is deliberate. `Element.attrib` is a dict and `Element.set` appends,
        so removing an attribute and writing it back moved it to the END of
        the list -- measured, eight of the nine names `map.object.unset`
        accepts came back last and each left the map dirty after a no-op
        pair. What puts them back is the DOCUMENT's own record of how each
        element spells its attributes, taken where the order is still true:
        at parse, and at the moment an element is authored. A copy of that
        line here would be a second place the rule is spelled, and it could
        never fire -- every `<object>` in a document has been through one of
        those two moments before any door can reach it.

        So the repair holds for a caller that reaches around this method and
        pops the attribute off `element.attrib` itself, which is what
        `map.object.unset` does today. That is the property worth having:
        the order survives because the document remembers it, not because
        every writer remembered to use the right door.

        There is no vocabulary check here on purpose. `map.object.unset`
        declares `choices=_OBJECT_ATTRIBUTES` and refuses `id`, and that
        refusal is a statement about which attributes the EDITOR's inverse
        can write back, not about which ones a document may hold.
        """
        previous = self.element.attrib.pop(key, None)
        if previous is None:
            return None
        self._document._touch()
        return previous

    def __repr__(self) -> str:
        return "MapObject(id=%d, name=%r, type=%r)" % (self.id, self.name, self.type)


def _attribute_text(value: Any) -> str:
    """Render an attribute the way Tiled does: ints stay ints.

    `x="64"` and `x="64.0"` are equivalent to a parser and NOT equivalent to
    a human reading a diff, so a whole-number float is written without the
    `.0`.
    """
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class ObjectLayer:
    """Read/write access to one `<objectgroup>`.

    The shipped map's group is self-closing (`<objectgroup id="9"
    name="entity"/>`), which means its `text` is None. Adding the first
    object has to invent indentation, and removing the last one has to put
    the element back exactly as it was found -- including going back to
    self-closing and rolling `nextobjectid` back down. That is what makes
    add_object + remove_object a byte-level no-op.
    """

    def __init__(self, document: "MapDocument", element: ElementTree.Element):
        self._document = document
        self.element = element
        self.name = element.get("name", "")
        self.id = int(element.get("id", "0"))
        self._original_text = element.text

    def objects(self) -> list[MapObject]:
        return [MapObject(self._document, child) for child in self.element.findall("object")]

    def find(self, object_id: int) -> MapObject | None:
        for child in self.element.findall("object"):
            if int(child.get("id", "0")) == object_id:
                return MapObject(self._document, child)
        return None

    def add_object(self, name: str | None = None, type: str | None = None,
                   x: float = 0, y: float = 0,
                   width: float | None = None, height: float | None = None,
                   gid: int | None = None,
                   properties: dict[str, Any] | None = None,
                   object_id: int | None = None) -> MapObject:
        """Append an `<object>`, in Tiled's attribute order."""
        assigned = object_id if object_id is not None else self._document._claim_object_id()
        element = self._document._append_child(self.element, "object")
        element.set("id", str(assigned))
        if name is not None:
            element.set("name", str(name))
        if type is not None:
            element.set("type", str(type))
        if gid is not None:
            element.set("gid", str(int(gid)))
        element.set("x", _attribute_text(x))
        element.set("y", _attribute_text(y))
        if width is not None:
            element.set("width", _attribute_text(width))
        if height is not None:
            element.set("height", _attribute_text(height))
        # Tiled's order, just written above, is this element's own order --
        # and nothing else will ever record it: an object the session
        # created does not pass through `_rebuild_parents`, so without this
        # line `unset` + `set` on a BRAND NEW object still moves the
        # attribute to the end while the same pair on a loaded one does not.
        self._document._remember_attributes(element)
        wrapper = MapObject(self._document, element)
        if properties:
            view = wrapper.properties
            for key, value in properties.items():
                view[key] = value
        self._document._touch()
        trace_assets("add_object layer=%s id=%s name=%s", self.name, assigned, name)
        return wrapper

    def object_index(self, object_id: int) -> int | None:
        """Where an object sits among its siblings, for exact restoration."""
        for index, child in enumerate(self.element.findall("object")):
            if int(child.get("id", "0")) == object_id:
                return index
        return None

    def serialize_object(self, object_id: int) -> str | None:
        """The object's whole `<object>` element as XML text.

        Exists because reconstructing an object from its ATTRIBUTES loses
        everything else it carries: `<polygon>`, `<polyline>`, `<point>`,
        `<ellipse>`, `<text>`, and any attribute this module does not model
        (rotation, visible, template). Anything that removes an object must
        keep this string if it intends to be able to put it back.
        """
        for child in self.element.findall("object"):
            if int(child.get("id", "0")) != object_id:
                continue
            # Copy so the live element keeps its tail; tostring() would
            # otherwise bake the sibling whitespace into the payload.
            clone = copy.deepcopy(child)
            clone.tail = None
            return ElementTree.tostring(clone, encoding="unicode")
        return None

    def restore_object(self, xml: str, index: int | None = None) -> MapObject:
        """Put back an object serialized by `serialize_object`.

        The element is reinstated verbatim -- every attribute and every
        child -- at `index` among its siblings, with only its indentation
        recomputed. That is what makes remove-then-restore byte-identical
        rather than approximately right.

        VERBATIM is why the text goes through `_parse_restored_element`:
        `map.object.restore` is reachable from a script and from the relay,
        and its `Param` is raw XML, so it is the one route that could put a
        name on the document that `MapObject.set` and
        `MapProperties.__setitem__` both refuse.
        """
        parsed = _parse_restored_element(
            xml, "restore_object", "an <object> element", ("object",),
            self._document.path)

        placeholder = self._document._append_child(self.element, "object", index)
        placeholder.attrib = dict(parsed.attrib)
        # The restored text's own order, recorded for the same reason
        # `add_object` records Tiled's: this is a NEW element and the only
        # restore that does not go on to call `_rebuild_parents`.
        self._document._remember_attributes(placeholder)
        placeholder.text = parsed.text
        for child in list(parsed):
            placeholder.append(child)
            self._document._parents[child] = placeholder
        self._document._touch()
        trace_assets("restore_object layer=%s id=%s",
                     self.name, placeholder.get("id"))
        return MapObject(self._document, placeholder)

    def remove_object(self, object_id: int) -> bool:
        """Remove an `<object>` by id. Returns False if it was not there."""
        for child in self.element.findall("object"):
            if int(child.get("id", "0")) != object_id:
                continue
            self._document._remove_child(self.element, child)
            if not list(self.element):
                # Back to however the file found it -- None means the file
                # wrote it self-closing and it must go back to self-closing.
                self.element.text = self._original_text
            self._document._release_object_id(object_id)
            self._document._touch()
            trace_assets("remove_object layer=%s id=%s", self.name, object_id)
            return True
        return False

    @property
    def properties(self) -> MapProperties:
        return MapProperties(self._document, self.element)

    def __repr__(self) -> str:
        return "ObjectLayer(%r, %d objects)" % (self.name, len(self.objects()))


# ---------------------------------------------------------------------------
# Tilesets
#
# A tileset is the only thing in a .tmx that OTHER elements depend on
# numerically: every csv token and every `<object gid=...>` is an index into
# the concatenated firstgid ranges. So a structurally correct edit here can
# still be semantically catastrophic, and these methods are defensive.
# ---------------------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Tiled packs three flip flags into a gid's top bits. Any comparison of a
# gid against a tileset's range has to mask them off first, or a flipped
# tile reads as a gid in the billions and matches nothing.
_GID_VALUE_MASK = 0x1FFFFFFF


def image_size(path: str) -> tuple[int, int]:
    """(width, height) of a PNG, read from the 24 bytes of its IHDR header.

    No decode, no pygame, no Qt: this module is under `scripts/`, which may
    never import `editor/`, and the two integers sit at a fixed offset.

    Raises rather than guessing on a non-PNG, so a caller that supports more
    formats can catch it and fall back instead of importing a tileset with a
    fabricated tile count.
    """
    try:
        with open(path, "rb") as handle:
            header = handle.read(24)
    except OSError as exc:
        raise PyoneerConfigError(
            "cannot read tileset image %s: %s" % (path, exc), source=path) from exc
    if len(header) < 24 or not header.startswith(_PNG_SIGNATURE) or header[12:16] != b"IHDR":
        raise PyoneerConfigError(
            "image_size reads PNG headers only and %s is not a PNG; pass "
            "image_width/image_height explicitly for other formats" % path,
            source=path)
    return (int.from_bytes(header[16:20], "big"),
            int.from_bytes(header[20:24], "big"))


def tileset_geometry(image_width: int, image_height: int,
                     tile_width: int, tile_height: int,
                     margin: int = 0, spacing: int = 0) -> tuple[int, int, int]:
    """(columns, rows, tile_count) for a grid tileset, the way Tiled counts.

    Not `image_width // tile_width`, which is only right at margin 0 and
    spacing 0. The last column has no trailing spacing after it, so the
    count is "how many gaps fit, plus the one tile that needs no gap" --
    subtract a tile before dividing, then add it back.

    A tileset too small to hold a single tile yields 0 rather than a
    negative count, because a tilecount of -1 in the file is a map Tiled
    refuses to open at all.
    """
    def axis(extent: int, tile: int) -> int:
        if tile <= 0:
            return 0
        usable = int(extent) - int(margin) - int(tile)
        if usable < 0:
            return 0
        return usable // (int(tile) + int(spacing)) + 1

    columns = axis(image_width, tile_width)
    rows = axis(image_height, tile_height)
    return columns, rows, columns * rows


def _int_attribute(element: ElementTree.Element, name: str, default: int) -> int:
    """An integer attribute, falling back rather than raising on garbage.

    A tileset that declares `tilecount="lots"` should still be LISTABLE --
    the caller needs to see it in order to fix it, and an accessor that
    raises on read makes the broken tileset invisible instead of visible.
    """
    raw = element.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        warn_content("tmx <%s %s=%r> is not an integer; using %d"
                     % (element.tag, name, raw, default))
        return default


@dataclass(frozen=True)
class TilesetRef:
    """A read-only view of one `<tileset>` declaration.

    Frozen and detached from the document: `tilesets()` hands these out, and a
    caller that mutated one would be editing a snapshot. `element` is here for
    the code inside this module that needs the live node.

    An EXTERNAL tileset (`<tileset firstgid="9" source="foo.tsx"/>`) has no
    name, image or tile count in THIS file -- they live in the .tsx -- so
    those fields read as "" / 0 rather than being invented, and `holds()` is
    False for every gid. Opening the second file is outside this document's
    byte-exactness contract.
    """

    element: ElementTree.Element
    first_gid: int
    name: str
    source: str
    image_source: str
    tile_width: int
    tile_height: int
    margin: int
    spacing: int
    tile_count: int
    columns: int

    @property
    def is_external(self) -> bool:
        return bool(self.source)

    @property
    def last_gid(self) -> int:
        """Highest gid this tileset owns. Below first_gid when it owns none."""
        return self.first_gid + self.tile_count - 1

    @property
    def extent_known(self) -> bool:
        """Can this document say which gids the tileset owns?

        No, for an EXTERNAL tileset -- the tilecount lives in the .tsx -- and
        no for an embedded one that omits `tilecount`, which is legal TMX
        that Tiled always writes but a hand edit may not.

        Load-bearing: `holds()` returns False for an unknown-extent tileset,
        which is indistinguishable from "outside this range" to a caller that
        does not ask. Any operation whose CORRECTNESS depends on the extent
        must check this and refuse -- see `require_known_extents`.
        """
        return self.tile_count > 0

    def holds(self, gid: int) -> bool:
        """Is `gid` (flip flags already masked off) inside this range?

        False when the extent is unknown, which is NOT the same as "no".
        Check `extent_known` first if the answer matters.
        """
        return self.tile_count > 0 and self.first_gid <= gid <= self.last_gid

    def __repr__(self) -> str:
        if self.is_external:
            return "TilesetRef(external %r, firstgid=%d)" % (self.source, self.first_gid)
        return "TilesetRef(%r, firstgid=%d, %d tiles, %d columns)" % (
            self.name, self.first_gid, self.tile_count, self.columns)


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------

_LAYER_TAGS = ("layer", "objectgroup", "imagelayer", "group")

# What TMX allows in front of the first `<tileset>`. A new tileset goes
# after the last of these, which puts it after any existing tileset and
# still in front of every layer -- the order Tiled writes and the order the
# .tmx DTD documents.
_TILESET_PRECEDING_TAGS = ("properties", "editorsettings", "tileset")


class MapDocument:
    """A .tmx file held as an editable, byte-faithful XML document.

    This is the WRITE side. pytmx stays the read side for rendering; the two
    are independent views of the same file and neither is derived from the
    other. Use `MapDocument` to change a map, then re-parse with pytmx (or
    call AssetMapManager.load_assets(..., reload=True)) to see the change.
    """

    def __init__(self, root: ElementTree.Element, *,
                 path: str | None = None,
                 raw: bytes = b"",
                 declaration: bytes = _DEFAULT_DECLARATION,
                 declaration_newline: bytes = b"\n",
                 newline: str = "\n",
                 trailing: bytes = b""):
        self.root = root
        self.path = path
        self.raw = raw
        self._declaration = declaration
        self._declaration_newline = declaration_newline
        self._newline = newline
        self._trailing = trailing
        self._parents: dict[ElementTree.Element, ElementTree.Element] = {}
        self._attribute_spellings: dict[ElementTree.Element, tuple[str, ...]] = {}
        self._rebuild_parents()
        self._tile_layers: dict[str, TileLayer] = {}
        self._object_layers: dict[str, ObjectLayer] = {}
        self._touched = False

    # -- loading and saving ------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "MapDocument":
        """Parse `path`, remembering everything a serializer would forget."""
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise PyoneerConfigError("tmx file not found: %s" % path, source=path)
        with open(path, "rb") as handle:
            raw = handle.read()
        return cls.from_bytes(raw, path=path)

    @classmethod
    def from_bytes(cls, raw: bytes, path: str | None = None) -> "MapDocument":
        # Re-emitted byte for byte. ElementTree would write it with single
        # quotes, which is a diff on every single save against Tiled.
        match = _DECLARATION_RE.match(raw)
        if match is None:
            declaration, declaration_newline = b"", b""
        else:
            declaration = match.group(1)
            declaration_newline = match.group(2) or b""

        # The parser normalizes CRLF to LF (XML 1.0 section 2.11), so the
        # only place the file's newline convention survives is here, in the
        # raw bytes, before parsing.
        newline = "\r\n" if b"\r\n" in raw else "\n"

        # Anything after the root's `>` is whitespace the serializer has no
        # representation for; carry it verbatim.
        stripped = raw.rstrip()
        trailing = raw[len(stripped):]

        parser = ElementTree.XMLParser(
            target=ElementTree.TreeBuilder(insert_comments=True, insert_pis=True)
        )
        root = ElementTree.fromstring(raw, parser=parser)
        root.tail = None
        return cls(root, path=path, raw=raw, declaration=declaration,
                   declaration_newline=declaration_newline,
                   newline=newline, trailing=trailing)

    def to_bytes(self) -> bytes:
        """Serialize. Identical to `self.raw` when nothing was changed."""
        for layer in self._tile_layers.values():
            layer._flush()
        parts: list[str] = []
        _serialize(self.root, parts, self._attribute_spellings)
        body = "".join(parts)
        if self._newline != "\n":
            body = body.replace("\r\n", "\n").replace("\r", "\n")
            body = body.replace("\n", self._newline)
        return self._declaration + self._declaration_newline + body.encode("utf-8") + self._trailing

    def save(self, path: str | None = None) -> str:
        """Write the document. Returns the path written.

        Written in binary with the original newline convention already baked
        in, because text mode on Windows would turn every `\\n` into `\\r\\n`
        a second time.
        """
        target = os.path.abspath(path or self.path or "")
        if not target:
            raise PyoneerConfigError("MapDocument.save needs a path; this document was "
                                     "built from bytes and has none")
        payload = self.to_bytes()
        with open(target, "wb") as handle:
            handle.write(payload)
        self.raw = payload
        self.path = target
        self._touched = False
        trace_assets("saved tmx %s (%s bytes)", target, len(payload))
        return target

    @property
    def changed(self) -> bool:
        """True when serializing would produce different bytes than loaded."""
        if not self._touched:
            return False
        return self.to_bytes() != self.raw

    # -- map header --------------------------------------------------------
    @property
    def width(self) -> int:
        return int(self.root.get("width", "0"))

    @property
    def height(self) -> int:
        return int(self.root.get("height", "0"))

    @property
    def tile_width(self) -> int:
        return int(self.root.get("tilewidth", "0"))

    @property
    def tile_height(self) -> int:
        return int(self.root.get("tileheight", "0"))

    @property
    def properties(self) -> MapProperties:
        """The map's own custom properties, typed."""
        return MapProperties(self, self.root)

    def properties_of(self, element: ElementTree.Element) -> MapProperties:
        """Typed custom properties for any element in the document."""
        return MapProperties(self, element)

    # -- layers ------------------------------------------------------------
    def _layer_elements(self) -> list[ElementTree.Element]:
        return [element for element in self.root.iter() if element.tag in _LAYER_TAGS]

    def layer_names(self) -> list[str]:
        """Every named layer, group and object group, in document order.

        Groups are included because in this map they are how the layers are
        organized ("Graphic" wraps six tile layers, "Entity" wraps the
        object group) and a caller listing layers needs to see them.
        """
        return [element.get("name", "") for element in self._layer_elements()]

    def tile_layer_names(self) -> list[str]:
        return [element.get("name", "")
                for element in self.root.iter("layer")]

    def object_layer_names(self) -> list[str]:
        return [element.get("name", "")
                for element in self.root.iter("objectgroup")]

    def _find_named(self, tag: str, name: str) -> ElementTree.Element | None:
        for element in self.root.iter(tag):
            if element.get("name") == name:
                return element
        return None

    def tile_layer(self, name: str) -> TileLayer:
        """The csv tile layer called `name`. Cached, so edits accumulate."""
        cached = self._tile_layers.get(name)
        if cached is not None:
            return cached
        element = self._find_named("layer", name)
        if element is None:
            raise PyoneerAssetMissingError(
                "tile layer", name, available=self.tile_layer_names(),
                source=self.path,
            )
        layer = TileLayer(self, element)
        self._tile_layers[name] = layer
        return layer

    def object_layer(self, name: str) -> ObjectLayer:
        """The object group called `name`. Cached, so edits accumulate."""
        cached = self._object_layers.get(name)
        if cached is not None:
            return cached
        element = self._find_named("objectgroup", name)
        if element is None:
            raise PyoneerAssetMissingError(
                "object layer", name, available=self.object_layer_names(),
                source=self.path,
            )
        layer = ObjectLayer(self, element)
        self._object_layers[name] = layer
        return layer

    # -- object ids --------------------------------------------------------
    # -- layers ------------------------------------------------------------

    def _claim_layer_id(self) -> int:
        """Next layer id, honouring the map's nextlayerid."""
        declared = int(self.root.get("nextlayerid", "1"))
        highest = 0
        for tag in _LAYER_TAGS:
            for element in self.root.iter(tag):
                highest = max(highest, int(element.get("id", "0")))
        assigned = max(declared, highest + 1)
        self.root.set("nextlayerid", str(assigned + 1))
        return assigned

    def _release_layer_id(self, layer_id: int) -> None:
        """Roll nextlayerid back, but only for the id just handed out."""
        if int(self.root.get("nextlayerid", "1")) == layer_id + 1:
            self.root.set("nextlayerid", str(layer_id))

    def _layer_parent(self, kind: str) -> ElementTree.Element:
        """Where a new layer of `kind` should go by default.

        Beside its own kind, so a new tile layer lands in the group that
        already holds tile layers rather than at the root. Falls back to the
        root for a map with no layers at all.
        """
        tag = "objectgroup" if kind == "object" else "layer"
        for candidate in (tag, "layer", "objectgroup"):
            for element in self.root.iter(candidate):
                parent = self._parents.get(element)
                if parent is not None:
                    return parent
        return self.root

    def __sibling_shape(self, parent: ElementTree.Element,
                        tag: str) -> tuple[str | None, str | None]:
        """How existing siblings of `tag` lay out their inner whitespace.

        This file indents its first layer with tabs and the rest with
        spaces, so a computed indent is wrong somewhere no matter what it
        computes. Copying a sibling's shape is right everywhere, and it is
        what makes add-then-remove byte-identical.
        """
        for child in parent:
            if child.tag != tag:
                continue
            inner = child.text
            closing = None
            grandchildren = list(child)
            if grandchildren:
                closing = grandchildren[-1].tail
            if inner is not None:
                return inner, closing
        return None, None

    def add_layer(self, name: str, kind: str = "tile", *,
                  group: str | None = None,
                  index: int | None = None,
                  fill: int = 0,
                  layer_id: int | None = None,
                  width: int | None = None,
                  height: int | None = None,
                  subcell: int | None = None) -> "TileLayer | ObjectLayer":
        """Add a `<layer>` or `<objectgroup>` and return its wrapper.

        `kind` is "tile" or "object". A tile layer is created at `width` x
        `height` -- the MAP's size when they are omitted, which is what every
        caller wanted before sub-cell collision existed -- filled with `fill`
        (0 = empty), and written in the same csv shape the file already uses.

        WHY THE DIMENSIONS ARE AN ARGUMENT.                #TAG:add_layer_dimensions
        A passability companion at `pyoneer_subcell="4"` is FOUR TIMES the
        map's width and height, so a map-sized layer cannot carry a 4x mask.

        WHY `subcell` SIZES AND DECLARES IN ONE CALL. Either half alone is a
        map that does not load: a layer 4x the map that does not SAY so is
        refused by `companion_subcell` as oversized for a 1x companion, and a
        layer that says 4 while map-sized is the shrunken case below. The
        validation is `companion_subcell`'s -- the ENGINE's own reader, called
        rather than mirrored -- and a factor it refuses takes the layer back
        out again and raises, rather than leaving an unloadable companion
        behind.

        Adding a layer does NOT make it render: the engine resolves a layer
        name to a depth through `scripts/core/depth.py`, and an unmapped name
        draws nothing, so this `warn_content`s rather than being a silent
        no-op.
        """
        if kind not in ("tile", "object"):
            raise PyoneerConfigError(
                "layer kind must be 'tile' or 'object', got %r" % kind,
                source=self.path)
        if name in self.layer_names():
            raise PyoneerConfigError(
                "this map already has a layer named %r" % name,
                source=self.path)
        if kind == "object" and (width is not None or height is not None
                                 or subcell is not None):
            # An <objectgroup> in a finite map carries no width/height and no
            # sub-cell grid at all -- objects are placed in PIXELS. Accepting
            # the arguments and dropping them is how `transform=` became a
            # known gap; refusing says which argument was meaningless.
            raise PyoneerConfigError(
                "layer %r is an object layer, which has no width, height or "
                "%s: objects are positioned in pixels, not in cells"
                % (name, subcell_property()),
                source=self.path)

        layer_width, layer_height = self.__layer_size(
            name, width, height, subcell)

        tag = "layer" if kind == "tile" else "objectgroup"
        if group is not None:
            parent = self._find_named("group", group)
            if parent is None:
                raise PyoneerAssetMissingError(
                    "layer group", group,
                    available=[e.get("name", "") for e in self.root.iter("group")],
                    source=self.path)
        else:
            parent = self._layer_parent(kind)

        assigned = layer_id if layer_id is not None else self._claim_layer_id()
        element = self._append_child(parent, tag, index)
        element.set("id", str(assigned))
        element.set("name", str(name))

        # Bound out here because `__declare_subcell` needs the sibling's
        # inner whitespace and runs after the block. An object layer with a
        # factor was refused above, so the None is unreachable rather than a
        # fallback -- but a NameError one reorder away is not worth saving
        # two lines.
        inner: str | None = None
        if kind == "tile":
            element.set("width", str(layer_width))
            element.set("height", str(layer_height))
            inner, closing = self.__sibling_shape(parent, "layer")
            data = self._append_child(element, "data")
            data.set("encoding", "csv")
            data.text = "\n" + self.__csv_payload(
                fill, layer_width, layer_height) + "\n"
            if inner is not None:
                element.text = inner
            if closing is not None:
                data.tail = closing

        self._touch()
        if subcell is not None:
            self.__declare_subcell(name, element, int(subcell), inner)
        trace_assets("add_layer name=%s kind=%s id=%s %sx%s subcell=%s",
                     name, kind, assigned, layer_width, layer_height, subcell)
        from scripts.core.depth import resolve_layer_depth
        if resolve_layer_depth(name) is None:
            warn_content(
                "layer %r has no depth in scripts/core/depth.py, so the "
                "engine will not draw it. Add it to MAP_DEPTH." % name)
        return (self.tile_layer(name) if kind == "tile"
                else self.object_layer(name))

    def __layer_size(self, name: str, width: int | None, height: int | None,
                     subcell: int | None) -> tuple[int, int]:
        """The dimensions a new tile layer is written at, checked.

        A declared sub-cell factor and an explicit size are each allowed
        alone, and together only when they AGREE: a companion declaring a
        factor its dimensions do not support bakes a field from a fraction of
        the data, with no exception and no warning.
        """
        wanted_width = self.width if width is None else int(width)
        wanted_height = self.height if height is None else int(height)
        if wanted_width <= 0 or wanted_height <= 0:
            raise PyoneerConfigError(
                "layer %r would be %dx%d; a tile layer is at least 1x1"
                % (name, wanted_width, wanted_height), source=self.path)
        if subcell is None:
            return wanted_width, wanted_height

        factor = int(subcell)
        if factor < 1:
            raise PyoneerConfigError(
                "layer %r would declare %s=%d; it is 1 or more (1 means one "
                "mask per map tile)" % (name, subcell_property(), factor),
                source=self.path)
        exact_width, exact_height = self.width * factor, self.height * factor
        if width is None and height is None:
            return exact_width, exact_height
        if (wanted_width, wanted_height) != (exact_width, exact_height):
            raise PyoneerConfigError(
                "layer %r declares %s=%d but is %dx%d; on a %dx%d map that "
                "factor is exactly %dx%d, and any other size means %d - %d = "
                "%d of its cells are read by nothing"
                % (name, subcell_property(), factor,
                   wanted_width, wanted_height, self.width, self.height,
                   exact_width, exact_height,
                   exact_width * exact_height, wanted_width * wanted_height,
                   exact_width * exact_height - wanted_width * wanted_height),
                source=self.path)
        return wanted_width, wanted_height

    def __declare_subcell(self, name: str, element: ElementTree.Element,
                          subcell: int, inner: str | None) -> None:
        """Write `pyoneer_subcell` on a layer just created, and prove the
        engine will accept it.

        `companion_subcell` is the reader that decides whether a map loads, so
        it also decides whether this write is allowed -- one validator,
        called, never a second copy of its rules. A factor it refuses rolls
        the whole layer back out before re-raising, since a half-written
        companion is a map that raises at load with nothing to undo.
        """
        from scripts.core.collision_runtime import companion_subcell
        self.tile_layer(name).properties[subcell_property()] = int(subcell)
        # `_append_child` computes the indent for a <properties> inserted in
        # front of <data>; the layer's own first-child whitespace was copied
        # from a sibling and is the shape the rest of the file uses.
        properties = element.find("properties")
        if properties is not None and inner is not None:
            element.text = inner
            properties.tail = inner
        try:
            companion_subcell(self, name)
        except Exception:
            self._tile_layers.pop(name, None)
            self.remove_layer(name)
            raise

    def __csv_payload(self, fill: int, width: int, height: int) -> str:
        """The csv body, in the shape this file already writes.

        Every row ends with a comma except the last, which is what Tiled
        emits and what `_CsvGrid` reproduces when it round-trips an existing
        layer. Producing a different shape would make the first human save
        in Tiled a whole-file diff.

        The size is passed rather than read off the map: a companion layer is
        `subcell` times the map on each axis, so the grid this renders and
        the `width=`/`height=` the element declares have to come from one
        number or `TileLayer` warns that the csv does not match its header.
        """
        if fill < 0:
            raise PyoneerConfigError(
                "gid %d is negative; tmx gids are unsigned (0 means empty)" % fill,
                source=self.path)
        row = ",".join(str(int(fill)) for _ in range(width))
        return ",\n".join(row for _ in range(height))

    def remove_layer(self, name: str) -> bool:
        """Remove a layer by name. Returns False if it was not there."""
        for tag in ("layer", "objectgroup", "imagelayer"):
            for element in list(self.root.iter(tag)):
                if element.get("name") != name:
                    continue
                parent = self._parents.get(element)
                if parent is None:
                    return False
                self._remove_child(parent, element)
                self._tile_layers.pop(name, None)
                self._object_layers.pop(name, None)
                self._release_layer_id(int(element.get("id", "0")))
                self._touch()
                trace_assets("remove_layer name=%s tag=%s", name, tag)
                return True
        return False

    def serialize_layer(self, name: str) -> dict[str, Any] | None:
        """Everything needed to put a layer back exactly where it was.

        Same reason `serialize_object` exists -- rebuilding from attributes
        would lose the csv payload, the properties and anything this module
        does not model -- plus two things a layer needs and an object does
        not: which `<group>` it lived in, and its own TAIL. The tail is the
        whitespace before whatever followed it, and recomputing it is how
        the first version came back one byte different.
        """
        for tag in ("layer", "objectgroup", "imagelayer"):
            for element in self.root.iter(tag):
                if element.get("name") != name:
                    continue
                parent = self._parents.get(element)
                if parent is None:
                    return None
                clone = copy.deepcopy(element)
                clone.tail = None
                siblings = list(parent)
                index = siblings.index(element)
                # The whitespace BEFORE this layer is not its own -- in
                # ElementTree it lives in the previous sibling's tail (or in
                # parent.text when it is first). Removal overwrites that, so
                # it has to be carried or the restored layer comes back with
                # a recomputed indent.
                return {
                    "xml": ElementTree.tostring(clone, encoding="unicode"),
                    "index": index,
                    "tag": tag,
                    "tail": element.tail or "",
                    "prev_tail": (siblings[index - 1].tail or "") if index else None,
                    "parent_text": parent.text if index == 0 else None,
                    "next_layer_id": self.root.get("nextlayerid", "1"),
                    "group": parent.get("name", "") if parent is not self.root else "",
                }
        return None

    def restore_layer(self, payload: dict[str, Any]) -> str:
        """Put back a layer serialized by `serialize_layer`."""
        parsed = _parse_restored_element(
            payload.get("xml") or "", "restore_layer",
            "a layer element (one of %s)" % (list(_LAYER_TAGS),),
            _LAYER_TAGS, self.path)

        group = payload.get("group") or None
        if group:
            parent = self._find_named("group", group)
            if parent is None:
                raise PyoneerAssetMissingError(
                    "layer group", group,
                    available=[e.get("name", "") for e in self.root.iter("group")],
                    source=self.path)
        else:
            parent = self._layer_parent(
                "object" if parsed.tag == "objectgroup" else "tile")

        index = payload.get("index")
        placeholder = self._append_child(parent, parsed.tag, index)
        placeholder.attrib = dict(parsed.attrib)
        placeholder.text = parsed.text
        for child in list(parsed):
            placeholder.append(child)

        # Put every piece of whitespace back exactly. _append_child computes
        # indentation, and computed is not the same as original in a file
        # that mixes tabs and spaces -- which this one does, deliberately.
        if payload.get("tail") is not None:
            placeholder.tail = payload["tail"]
        siblings = list(parent)
        position = siblings.index(placeholder)
        if position and payload.get("prev_tail") is not None:
            siblings[position - 1].tail = payload["prev_tail"]
        if payload.get("parent_text") is not None:
            parent.text = payload["parent_text"]
        if payload.get("next_layer_id"):
            self.root.set("nextlayerid", payload["next_layer_id"])

        self._rebuild_parents()
        self._touch()
        trace_assets("restore_layer name=%s", placeholder.get("name"))
        return placeholder.get("name", "")

    # -- tilesets ----------------------------------------------------------
    #
    # These mirror add_layer / remove_layer / serialize_layer / restore_layer
    # exactly, with three differences that all come from WHERE a tileset
    # lives and WHAT depends on it:
    #
    #   * a tileset is always a direct child of <map>, so there is no group
    #     to remember -- but `_child_indent(self.root)` can only ever return
    #     a single space (the root has no parent to be deeper than), so
    #     EVERY tileset insert lands on the trap that add_layer only meets
    #     at the end of a group. The whitespace is copied, never computed.
    #   * there is no `nexttilesetid` to roll back. Layers have nextlayerid
    #     and objects have nextobjectid; a tileset's identity is its
    #     firstgid, which is derived from the tilesets already present. So
    #     the "release the id" half of the add/remove pair is a no-op here,
    #     and its absence is deliberate rather than forgotten.
    #   * removing a tileset can corrupt tiles that are not part of the
    #     tileset. Nothing else in this module can. See remove_tileset.

    def _tileset_elements(self) -> list[ElementTree.Element]:
        """Every `<tileset>` that is a DIRECT child of `<map>`.

        `findall`, deliberately, never `iter`. An embedded tileset can carry
        `<tile>` children which can themselves carry `<objectgroup>`, and
        unbounded descent through that is exactly the bug pytmx ships: it
        does `node.findall(".//objectgroup")` from the map root and injects
        a phantom layer named None for every per-tile collision shape. TMX
        defines `<tileset>` as a child of `<map>` and nowhere else, so
        anything deeper is not a tileset this document owns.
        """
        return self.root.findall("tileset")

    def __tileset_ref(self, element: ElementTree.Element) -> TilesetRef:
        image = element.find("image")
        return TilesetRef(
            element=element,
            first_gid=_int_attribute(element, "firstgid", 1),
            name=element.get("name", ""),
            source=element.get("source", ""),
            image_source="" if image is None else image.get("source", ""),
            # A tileset that omits tilewidth inherits the map's, which is
            # what Tiled assumes when it renders one.
            tile_width=_int_attribute(element, "tilewidth", self.tile_width),
            tile_height=_int_attribute(element, "tileheight", self.tile_height),
            margin=_int_attribute(element, "margin", 0),
            spacing=_int_attribute(element, "spacing", 0),
            tile_count=_int_attribute(element, "tilecount", 0),
            columns=_int_attribute(element, "columns", 0),
        )

    def tilesets(self) -> list[TilesetRef]:
        """Every tileset the map declares, in document order.

        Document order, not firstgid order, because that is what a diff
        shows and what a human editing the file sees. Nothing in the engine
        depends on the two agreeing: pytmx's `get_tileset_from_gid` sorts by
        firstgid itself before resolving.
        """
        return [self.__tileset_ref(element) for element in self._tileset_elements()]

    def tileset_names(self) -> list[str]:
        """Tileset names in document order; '' for each external tileset."""
        return [element.get("name", "") for element in self._tileset_elements()]

    def _tileset_element(self, key: str | int) -> ElementTree.Element | None:
        """Find a tileset by NAME (str) or by FIRSTGID (int).

        Both, because `_find_named` cannot do this job alone. An external
        `<tileset firstgid="9" source="foo.tsx"/>` carries no name at all,
        so a name-only lookup can address only some of a map's tilesets --
        and the ones it cannot address are exactly the ones whose contents
        this document cannot see, which is the worst combination.
        """
        # bool is an int in Python, so `tileset(True)` would otherwise match
        # firstgid="1" -- a plausible wrong answer, which is the outcome this
        # module works hardest to avoid.
        if isinstance(key, bool):
            return None
        by_gid = isinstance(key, int)
        for element in self._tileset_elements():
            if by_gid:
                if _int_attribute(element, "firstgid", 0) == key:
                    return element
            elif element.get("name", "") == key:
                return element
        return None

    def tileset(self, key: str | int) -> TilesetRef:
        """The tileset named `key`, or the one whose firstgid is `key`."""
        element = self._tileset_element(key)
        if element is None:
            raise PyoneerAssetMissingError(
                "tileset", str(key), available=self.tileset_names(),
                source=self.path)
        return self.__tileset_ref(element)

    def next_tileset_firstgid(self) -> int:
        """The firstgid a newly appended tileset should take.

        The highest gid any existing tileset claims, plus one. For a map
        Tiled wrote that is identically `1 + sum(tilecount)`, because Tiled
        packs the ranges end to end -- but the two stop agreeing the moment
        a tileset is removed from the middle, and only this form stays
        collision-free across that hole. `1 + sum(tilecount)` would hand
        back a gid the surviving top tileset already owns.
        """
        refs = self.tilesets()
        if not refs:
            return 1
        self.require_known_extents("choose a collision-free firstgid")
        return max(ref.first_gid + ref.tile_count for ref in refs)

    def require_known_extents(self, operation: str) -> None:
        """Refuse an operation that cannot be done safely.

        A tileset whose extent this document cannot see contributes 0 to every
        range calculation, so `next_tileset_firstgid` would hand back a gid
        that tileset already owns. pytmx resolves a gid by taking the highest
        firstgid at or below it, so the new sheet would silently win and every
        tile authored against the old one would repaint with the wrong art.
        The missing information lives in a file this document does not own,
        so refusing is the only answer available.
        """
        unknown = [ref for ref in self.tilesets() if not ref.extent_known]
        if not unknown:
            return
        described = ", ".join(
            "%s at firstgid %d" % (ref.source or ref.name or "<unnamed>",
                                   ref.first_gid)
            for ref in unknown)
        raise PyoneerConfigError(
            "cannot %s: %d tileset(s) do not declare their extent in this "
            "file (%s). An external <tileset source=...> keeps its tilecount "
            "in the .tsx, so this document cannot tell which gids it owns, "
            "and guessing would silently repaint every tile that uses it."
            % (operation, len(unknown), described),
            source=self.path)

    def tiles_using_tileset(self, key: str | int) -> list[tuple[str, int, int, int]]:
        """(layer_name, x, y, raw_gid) for every csv cell inside this range.

        The raw gid is returned with its flip flags intact, because a caller
        that restores it has to restore the flips too; the RANGE test masks
        them off first, since a horizontally flipped tile carries
        0x80000000 and would otherwise match no tileset at all.

        Only csv tile layers. `objects_using_tileset` covers the other half.
        """
        ref = self.tileset(key)
        found: list[tuple[str, int, int, int]] = []
        if not ref.extent_known:
            # An empty list here reads as "nothing uses it", which is what
            # remove_tileset's orphan guard trusts. For an external tileset
            # that answer is a guess, and acting on it orphans every tile
            # that referenced the sheet.
            raise PyoneerConfigError(
                "cannot scan for tiles using %r: it does not declare its "
                "extent in this file, so which gids it owns is unknowable "
                "here" % (ref.source or ref.name or key),
                source=self.path)
        for name in self.tile_layer_names():
            layer = self.tile_layer(name)
            width = layer.width or 1
            for index, raw in enumerate(layer.gids()):
                if raw and ref.holds(raw & _GID_VALUE_MASK):
                    found.append((name, index % width, index // width, raw))
        return found

    def objects_using_tileset(self, key: str | int) -> list[tuple[str, int, int]]:
        """(layer_name, object_id, raw_gid) for every TILE OBJECT in range.

        Tile objects are the half of the problem that is easy to forget:
        they carry a gid in an ATTRIBUTE rather than in the csv, so a scan
        that only walks `<data>` reports a tileset as unused while a dozen
        `<object gid=...>` still point into it.
        """
        ref = self.tileset(key)
        found: list[tuple[str, int, int]] = []
        if not ref.extent_known:
            raise PyoneerConfigError(
                "cannot scan for objects using %r: it does not declare its "
                "extent in this file" % (ref.source or ref.name or key),
                source=self.path)
        for group in self.root.iter("objectgroup"):
            layer_name = group.get("name", "")
            for element in group.findall("object"):
                raw = _int_attribute(element, "gid", 0)
                if raw and ref.holds(raw & _GID_VALUE_MASK):
                    found.append((layer_name, _int_attribute(element, "id", 0), raw))
        return found

    def __resolve_image(self, image_source: str) -> str | None:
        """A tileset image path, resolved the way Tiled resolves it.

        Relative to the .tmx, NOT to the working directory -- which is the
        same trap `resolve_map_path` exists for. None when this document was
        built from bytes and has no path to resolve against.
        """
        if not self.path:
            return None
        return os.path.normpath(
            os.path.join(os.path.dirname(self.path), image_source))

    def add_tileset(self, name: str, image_source: str, *,
                    tile_width: int | None = None,
                    tile_height: int | None = None,
                    margin: int = 0,
                    spacing: int = 0,
                    columns: int | None = None,
                    tile_count: int | None = None,
                    image_width: int | None = None,
                    image_height: int | None = None,
                    first_gid: int | None = None) -> TilesetRef:
        """Add an EMBEDDED `<tileset>` with one `<image>` child.

        Everything unspecified is measured rather than assumed: tile size
        defaults to the map's, the image is sized from its PNG header, and
        columns/tilecount fall out of `tileset_geometry`. Pass any of them
        explicitly to override.

        APPEND ONLY. `first_gid` defaults to `next_tileset_firstgid()`, and an
        explicit value at or below an existing range is REFUSED. Inserting
        into the middle of the gid space is a whole-file rewrite -- every
        later tileset's firstgid moves up, and so does every csv token at or
        above the insertion point and every `<object gid=...>`, flip flags
        masked off first -- which breaks both the minimal-diff contract and
        the exact-inverse one. Document order need not match firstgid order
        for any reader, since pytmx sorts.

        EXTERNAL tilesets (`source="foo.tsx"`) are readable through
        `tilesets()` but cannot be created here: a .tsx is a second file, and
        this document's byte-exactness contract covers exactly one.
        """
        if not name:
            raise PyoneerConfigError("a tileset needs a name", source=self.path)
        if name in self.tileset_names():
            raise PyoneerConfigError(
                "this map already has a tileset named %r" % name, source=self.path)
        if not image_source:
            raise PyoneerConfigError(
                "add_tileset builds an EMBEDDED tileset and needs an image "
                "source; an external .tsx is a second file and is outside "
                "this document's byte-exactness contract", source=self.path)

        tile_width = int(self.tile_width if tile_width is None else tile_width)
        tile_height = int(self.tile_height if tile_height is None else tile_height)
        if tile_width <= 0 or tile_height <= 0:
            raise PyoneerConfigError(
                "tileset %r needs a positive tile size, got %dx%d"
                % (name, tile_width, tile_height), source=self.path)

        margin, spacing = int(margin), int(spacing)
        if margin or spacing:
            # Not a style note. Tiled subtracts the margin, pytmx's tile
            # count ignores it entirely, and the editor's atlas ignores both
            # -- so the three readers only agree at 0/0, and a spaced sheet
            # imported here will render offset tiles somewhere.
            warn_content(
                "tileset %r declares margin=%d spacing=%d; Tiled, pytmx and "
                "the editor's atlas only agree on tile geometry at 0/0, so "
                "verify the tiles line up before authoring against it"
                % (name, margin, spacing))

        if image_width is None or image_height is None:
            probe = self.__resolve_image(image_source)
            if probe is None or not os.path.isfile(probe):
                raise PyoneerConfigError(
                    "cannot measure tileset image %r (%s); pass image_width "
                    "and image_height explicitly"
                    % (image_source,
                       "this document has no path to resolve it against"
                       if probe is None else "looked in %s" % probe),
                    source=self.path)
            measured_width, measured_height = image_size(probe)
            image_width = measured_width if image_width is None else image_width
            image_height = measured_height if image_height is None else image_height
        image_width, image_height = int(image_width), int(image_height)

        derived_columns, _rows, derived_count = tileset_geometry(
            image_width, image_height, tile_width, tile_height, margin, spacing)
        columns = derived_columns if columns is None else int(columns)
        tile_count = derived_count if tile_count is None else int(tile_count)
        if tile_count <= 0:
            raise PyoneerConfigError(
                "tileset %r would hold no tiles: a %dx%d image cannot fit a "
                "single %dx%d tile at margin=%d spacing=%d"
                % (name, image_width, image_height, tile_width, tile_height,
                   margin, spacing), source=self.path)

        appended_gid = self.next_tileset_firstgid()
        if first_gid is None:
            first_gid = appended_gid
        else:
            first_gid = int(first_gid)
            if first_gid < 1:
                raise PyoneerConfigError(
                    "firstgid must be at least 1 (gid 0 means 'no tile'), got %d"
                    % first_gid, source=self.path)
            if first_gid < appended_gid:
                raise PyoneerConfigError(
                    "refusing to add tileset %r at firstgid %d: that range "
                    "collides with or sits below the tilesets already in this "
                    "map (%s), and making room would mean renumbering every "
                    "csv token at or above %d in every layer plus every "
                    "<object gid=...>. Append at %d instead -- document order "
                    "does not have to match gid order for any reader."
                    % (name, first_gid,
                       ", ".join("%s:%d-%d" % (r.name or r.source or "?",
                                               r.first_gid, r.last_gid)
                                 for r in self.tilesets()) or "<none>",
                       first_gid, appended_gid),
                    source=self.path)

        children = list(self.root)
        index = 0
        for position, child in enumerate(children):
            if child.tag in _TILESET_PRECEDING_TAGS:
                index = position + 1

        # Read the sibling shape BEFORE inserting: once our element is in the
        # tree it is a `<tileset>` sibling too, and if it sorts first
        # __sibling_shape would hand us back the computed indentation we are
        # trying to replace.
        inner, closing = self.__sibling_shape(self.root, "tileset")
        # TRAP: _append_child overwrites parent.text whenever it is
        # whitespace-only, and _remove_child never puts it back. Reachable
        # for real -- "add the first tileset to a map that has none" inserts
        # at index 0 -- and it turns add-then-remove into a one-byte diff
        # ('\n\t' becomes '\n ') that nothing else in the file explains.
        saved_root_text = self.root.text
        saved_prev_tail = children[index - 1].tail if index else None
        # root.text IS the root-level separator by construction: it is the
        # whitespace in front of the first root child. _child_indent(root)
        # cannot derive it -- the root has no parent to be deeper than, so
        # it returns a single space no matter what the file uses.
        separator = (saved_root_text
                     if saved_root_text and not saved_root_text.strip()
                     else "\n" + self._child_indent(self.root))

        element = self._append_child(self.root, "tileset", index)
        # Tiled's attribute order. attrib is insertion-ordered and _serialize
        # walks it in that order, so writing them out of order is a diff on
        # every line of the element for a human reading `git diff`.
        element.set("firstgid", str(first_gid))
        element.set("name", str(name))
        element.set("tilewidth", str(tile_width))
        element.set("tileheight", str(tile_height))
        if spacing:
            element.set("spacing", str(spacing))
        if margin:
            element.set("margin", str(margin))
        element.set("tilecount", str(tile_count))
        element.set("columns", str(columns))

        image = self._append_child(element, "image")
        image.set("source", str(image_source))
        image.set("width", str(image_width))
        image.set("height", str(image_height))

        if inner is not None:
            element.text = inner
        if closing is not None:
            image.tail = closing

        # Put every computed byte of whitespace back to a copied one.
        siblings = list(self.root)
        position = siblings.index(element)
        if position == len(siblings) - 1:
            # We are the new LAST root child. _append_child correctly handed
            # us the old last child's tail (the whitespace in front of
            # `</map>`), but gave the child we displaced a COMPUTED
            # separator in exchange.
            if position:
                siblings[position - 1].tail = separator
        else:
            # We were inserted in front of something, so our tail is that
            # element's original leading separator -- verbatim, not
            # recomputed. Assigned unconditionally, including None, because a
            # document written with no whitespace must come back with none.
            element.tail = saved_prev_tail if position else saved_root_text
        self.root.text = saved_root_text

        self._touch()
        trace_assets("add_tileset name=%s firstgid=%s tiles=%s",
                     name, first_gid, tile_count)

        resolved = self.__resolve_image(image_source)
        if resolved is not None and not os.path.isfile(resolved):
            # Same shape as add_layer's depth warning: the edit is valid TMX
            # and the file will still load, but the tileset draws nothing.
            warn_content(
                "tileset %r points at %r, which does not exist relative to "
                "the map (%s). Tiled and the engine will both load the map "
                "and draw nothing for it." % (name, image_source, resolved))
        return self.__tileset_ref(element)

    def _gid_pressure(self, threshold: int) -> tuple[int, dict[str, int]]:
        """(total, per-layer counts) of painted gids at or above `threshold`.

        What moving a firstgid up to `threshold` would cost, counted rather
        than estimated. Both halves of the numbering are walked -- csv
        tokens and `<object gid=...>`, flip flags masked off first -- because
        a renumber that skips the objects leaves every tile object painting
        the art of whatever tileset now owns its old gid.

        The number exists to be quoted in a refusal. "Growing this would
        renumber 10,897 cells across 8 layers" is a decision the caller can
        make; "refused" on its own is not.
        """
        per_layer: dict[str, int] = {}
        total = 0
        for name in self.tile_layer_names():
            hits = sum(1 for raw in self.tile_layer(name).gids()
                       if raw and (raw & _GID_VALUE_MASK) >= threshold)
            if hits:
                per_layer[name] = hits
                total += hits
        for group in self.root.iter("objectgroup"):
            hits = 0
            for element in group.findall("object"):
                raw = _int_attribute(element, "gid", 0)
                if raw and (raw & _GID_VALUE_MASK) >= threshold:
                    hits += 1
            if hits:
                name = group.get("name", "")
                per_layer[name] = per_layer.get(name, 0) + hits
                total += hits
        return total, per_layer

    def tileset_headroom(self, key: str | int) -> int:
        """How many MORE tiles this tileset could own before it collided.

        The distance from its last gid up to the lowest firstgid above it,
        or up to the top of the gid space when nothing sits above it -- a
        gid at 0x20000000 lands in the bits Tiled packs its flip flags into,
        so that is where the space ends rather than at 2^31.

        This is the number that decides whether growth is free. `add_tileset`
        already accepts a `first_gid` above the packed one, so a map can be
        authored with a reserved hole under each range, and every tile inside
        that hole is claimable later without moving one csv token. Growth
        past it cannot be bought by moving the next firstgid instead: that
        renumbers every gid at or above it in every layer and in every
        `<object gid=...>`.
        """
        ref = self.tileset(key)
        self.require_known_extents("measure a tileset's headroom")
        ceiling = _GID_VALUE_MASK
        for other in self.tilesets():
            if other.element is ref.element:
                continue
            if other.first_gid > ref.last_gid:
                ceiling = min(ceiling, other.first_gid - 1)
        return ceiling - ref.last_gid

    def grow_tileset(self, key: str | int, *,
                     image_source: str | None = None,
                     image_width: int | None = None,
                     image_height: int | None = None,
                     tile_count: int | None = None) -> dict[str, Any]:
        """Point a tileset at a re-cut sheet and change how many tiles it
        owns. Returns the four values it replaced, which ARE its inverse.

        THE ONLY SAFE AXIS IS ROWS.                  #TAG:growth_is_rows_only
        A tile's local id is `row * columns + column`, and every reader
        derives that stride from the sheet's WIDTH -- pytmx walks the image
        in ranges over its pixel size, the editor's atlas divides by tile
        width. So a WIDER sheet renumbers every id after the first row and
        repaints every painted cell with different art, silently, with
        nothing raised anywhere. A TALLER sheet at the same width adds ids
        after the last one and moves nothing. The column count is therefore
        not a parameter here: a new image whose width yields a different
        column count is refused.

        The second axis is the gid range above. Growth extends this range
        upward into whatever sits there, and pytmx resolves an overlap two
        incompatible ways -- by sorted firstgid in `get_tileset_from_gid`,
        by document order in `reload_images` -- so the same file paints
        differently depending on which `<tileset>` was declared first. That
        is refused too, naming what is in the way, how much room this
        tileset does have, and what renumbering the survivors would cost in
        painted cells.

        SHRINKING is this method with a smaller count, and is refused while
        any tile or tile object still points into the range it would drop.
        Clearing those first through `map.tile.set_many` keeps an exact
        inverse; dropping them here would not.
        """
        ref = self.tileset(key)
        label = ref.name or ref.source or str(key)
        if ref.is_external:
            raise PyoneerConfigError(
                "cannot grow external tileset %r: its image and its tile "
                "count live in the .tsx, which is a second file and outside "
                "this document's byte-exactness contract" % label,
                source=self.path)
        self.require_known_extents("grow a tileset")
        if ref.margin or ref.spacing:
            raise PyoneerConfigError(
                "cannot grow tileset %r: it declares margin=%d spacing=%d, "
                "and Tiled, pytmx and the editor's atlas only agree on a "
                "tileset's column count at 0/0. Growth is arithmetic over "
                "that count, so growing a sheet the three readers cut "
                "differently would move a different set of tiles in each"
                % (label, ref.margin, ref.spacing), source=self.path)
        image = ref.element.find("image")
        if image is None:
            raise PyoneerConfigError(
                "cannot grow tileset %r: it declares no <image>, so it is a "
                "collection of images (one <tile><image/></tile> per tile) "
                "rather than a grid. That shape appends by adding a <tile> "
                "child, which is a different edit with a different inverse"
                % label, source=self.path)

        # Every attribute this rewrites has to come back byte for byte when
        # the inverse writes the old number, and `str(int(raw))` is what the
        # inverse will write. A file spelling `tilecount="0012"` would come
        # back as `"12"` -- a diff nothing else in the file explains.
        for owner, attribute in ((ref.element, "tilecount"),
                                 (image, "width"), (image, "height")):
            raw = owner.get(attribute)
            if raw is None:
                raise PyoneerConfigError(
                    "cannot grow tileset %r: its <%s> declares no %s, and "
                    "growth is arithmetic over the sheet's own grid -- with "
                    "no %s there is nothing to grow from"
                    % (label, owner.tag, attribute, attribute),
                    source=self.path)
            try:
                canonical = str(int(raw))
            except (TypeError, ValueError):
                canonical = None
            if canonical != raw:
                raise PyoneerConfigError(
                    "cannot grow tileset %r: <%s %s=%r> is not spelled the "
                    "way this edit writes an integer back, so undoing it "
                    "would not reproduce the file byte for byte"
                    % (label, owner.tag, attribute, raw), source=self.path)

        old_source = image.get("source", "")
        old_width, old_height = int(image.get("width")), int(image.get("height"))
        new_source = old_source if image_source is None else str(image_source)
        if not new_source:
            raise PyoneerConfigError(
                "cannot grow tileset %r: an embedded tileset draws from one "
                "image and this would leave it with none" % label,
                source=self.path)

        new_width, new_height = old_width, old_height
        if (image_width is None or image_height is None) and new_source != old_source:
            probe = self.__resolve_image(new_source)
            if probe is None or not os.path.isfile(probe):
                raise PyoneerConfigError(
                    "cannot measure the new sheet %r for tileset %r (%s); "
                    "pass image_width and image_height explicitly"
                    % (new_source, label,
                       "this document has no path to resolve it against"
                       if probe is None else "looked in %s" % probe),
                    source=self.path)
            new_width, new_height = image_size(probe)
        if image_width is not None:
            new_width = int(image_width)
        if image_height is not None:
            new_height = int(image_height)

        if ref.columns <= 0:
            raise PyoneerConfigError(
                "cannot grow tileset %r: it declares no columns, and a local "
                "tile id is row * columns + column. With no stride there is "
                "no way to say which ids a taller sheet would add" % label,
                source=self.path)
        old_columns, _old_rows, _old_fits = tileset_geometry(
            old_width, old_height, ref.tile_width, ref.tile_height)
        if old_columns != ref.columns:
            raise PyoneerConfigError(
                "cannot grow tileset %r: it declares columns=%d over a %dx%d "
                "sheet of %dx%d tiles, which is %d columns wide. The map and "
                "the sheet already disagree about this tileset's stride, so "
                "growing it would move tiles by an amount neither number "
                "describes" % (label, ref.columns, old_width, old_height,
                               ref.tile_width, ref.tile_height, old_columns),
                source=self.path)
        new_columns, _new_rows, fits = tileset_geometry(
            new_width, new_height, ref.tile_width, ref.tile_height)
        if new_columns != ref.columns:
            raise PyoneerConfigError(
                "refusing to grow tileset %r from a %d-column sheet to a "
                "%d-column one: a local tile id is row * columns + column, so "
                "changing the stride renumbers every tile after the first "
                "row. Nothing raises when that happens -- every painted cell "
                "in the map simply draws different art. Grow the sheet "
                "DOWNWARD, at %d pixels wide"
                % (label, ref.columns, new_columns, old_width),
                source=self.path)

        wanted = fits if tile_count is None else int(tile_count)
        if wanted <= 0:
            raise PyoneerConfigError(
                "tileset %r would hold no tiles; remove it instead, which "
                "checks first that nothing still points into its range"
                % label, source=self.path)
        if wanted > fits:
            raise PyoneerConfigError(
                "cannot give tileset %r %d tiles: a %dx%d sheet of %dx%d "
                "tiles holds %d. The gids past that edge would still resolve "
                "to this tileset and draw nothing"
                % (label, wanted, new_width, new_height, ref.tile_width,
                   ref.tile_height, fits), source=self.path)

        new_last = ref.first_gid + wanted - 1
        if wanted > ref.tile_count:
            blocked = [other for other in self.tilesets()
                       if other.element is not ref.element
                       and other.tile_count > 0
                       and other.first_gid <= new_last
                       and other.last_gid >= ref.first_gid]
            if blocked:
                threshold = min(other.first_gid for other in blocked)
                total, per_layer = self._gid_pressure(threshold)
                raise PyoneerConfigError(
                    "refusing to grow tileset %r from %d tiles to %d: gids "
                    "%d-%d are already owned by %s. An overlap raises nowhere "
                    "-- pytmx picks the winner by sorted firstgid in one "
                    "function and by document order in another, so the same "
                    "file paints differently depending on which <tileset> was "
                    "declared first. This tileset has room for %d more tiles. "
                    "Moving the ones above it instead would renumber %d "
                    "painted gid(s) (%s), which is a whole-map rewrite: clear "
                    "them with map.tile.set_many, whose inverse is exact, or "
                    "give this tileset headroom when it is added"
                    % (label, ref.tile_count, wanted, threshold, new_last,
                       ", ".join("%s at %d-%d" % (o.name or o.source or "?",
                                                  o.first_gid, o.last_gid)
                                 for o in blocked),
                       self.tileset_headroom(key), total,
                       ", ".join("%s x%d" % (n, c)
                                 for n, c in sorted(per_layer.items()))
                       or "none painted"),
                    source=self.path)
        elif wanted < ref.tile_count:
            dropped = ref.first_gid + wanted
            tiles = [row for row in self.tiles_using_tileset(key)
                     if (row[3] & _GID_VALUE_MASK) >= dropped]
            objects = [row for row in self.objects_using_tileset(key)
                       if (row[2] & _GID_VALUE_MASK) >= dropped]
            if tiles or objects:
                per_layer = {}
                for layer_name, _x, _y, _gid in tiles:
                    per_layer[layer_name] = per_layer.get(layer_name, 0) + 1
                for layer_name, _oid, _gid in objects:
                    per_layer[layer_name] = per_layer.get(layer_name, 0) + 1
                raise PyoneerConfigError(
                    "refusing to truncate tileset %r from %d tiles to %d: %d "
                    "tile(s) still point at gids %d-%d (%s). Those gids would "
                    "leave this tileset's range and resolve to whatever sits "
                    "below, which raises nowhere and paints the wrong art. "
                    "Clear them first with map.tile.set_many, whose inverse "
                    "is exact"
                    % (label, ref.tile_count, wanted,
                       len(tiles) + len(objects), dropped, ref.last_gid,
                       ", ".join("%s x%d" % (n, c)
                                 for n, c in sorted(per_layer.items()))),
                    source=self.path)

        previous = {"image": old_source, "image_width": old_width,
                    "image_height": old_height, "tile_count": ref.tile_count}
        # `set` on a key that is already there keeps its position, so none of
        # these four attributes moves and the diff is the four numbers.
        image.set("source", new_source)
        image.set("width", str(new_width))
        image.set("height", str(new_height))
        ref.element.set("tilecount", str(wanted))
        self._touch()
        trace_assets("grow_tileset name=%s tiles=%s->%s image=%s",
                     label, ref.tile_count, wanted, new_source)

        resolved = self.__resolve_image(new_source)
        if resolved is not None and not os.path.isfile(resolved):
            warn_content(
                "tileset %r now points at %r, which does not exist relative "
                "to the map (%s). Tiled and the engine will both load the "
                "map and draw nothing for it." % (label, new_source, resolved))
        return previous

    def rename_tileset(self, key: str | int, new_name: str) -> str:
        """Give a tileset a different name. Returns the name it had.

        One attribute, and nothing numeric: a name is not part of the gid
        arithmetic, so no placed tile changes meaning. What it IS part of is
        addressing -- every other tileset verb takes this string as its key
        -- and a `.blitmask` stores it in its own header, where
        `tileset_defaults` raises when the two disagree. Renaming that header
        is the command layer's half of the job, because a sidecar is a second
        file and this document owns exactly one.

        An EXTERNAL tileset carries no name here at all (it lives in the
        .tsx) and is refused rather than given one: an added attribute would
        be a name this file claims and the .tsx contradicts.
        """
        element = self._tileset_element(key)
        if element is None:
            raise PyoneerAssetMissingError(
                "tileset", str(key), available=self.tileset_names(),
                source=self.path)
        new_name = str(new_name)
        if not new_name:
            raise PyoneerConfigError(
                "a tileset needs a name; it is the key every other tileset "
                "verb addresses it by", source=self.path)
        previous = element.get("name")
        if previous is None:
            raise PyoneerConfigError(
                "the tileset at firstgid %s carries no name in this file, so "
                "there is nothing to rename. An external <tileset source=...> "
                "keeps its name in the .tsx"
                % element.get("firstgid", "?"), source=self.path)
        if new_name == previous:
            return previous
        if new_name in self.tileset_names():
            raise PyoneerConfigError(
                "this map already has a tileset named %r, and the name is the "
                "key the tileset verbs address one by" % new_name,
                source=self.path)
        element.set("name", new_name)
        self._touch()
        trace_assets("rename_tileset %s -> %s", previous, new_name)
        return previous

    def remove_tileset(self, key: str | int, *, force: bool = False) -> bool:
        """Remove a tileset by name or firstgid. False if it was not there.

        Purely structural: it does NOT renumber the surviving tilesets and
        does NOT touch a single gid. The firstgid hole it leaves is legal TMX
        that pytmx reads without complaint, while renumbering would rewrite
        the whole file and make this operation's inverse a map-wide gid remap.

        What it will NOT do quietly is orphan tiles. A gid whose tileset has
        vanished raises nowhere: pytmx's `get_tileset_from_gid` sorts firstgids
        descending and returns the first one <= the gid, so an orphan resolves
        to the tileset BELOW it and paints the WRONG ART. A tileset with live
        references is therefore refused, naming the layers and counts.

        `force=True` proceeds anyway, and exists for exactly one caller: a
        command that has already zeroed those gids in the same transaction
        (through `map.tile.set_many`, whose inverse is already exact) and is
        therefore removing a tileset nothing points at any more.
        """
        element = self._tileset_element(key)
        if element is None:
            return False

        if not force:
            ref = self.__tileset_ref(element)
            if not ref.extent_known:
                # The orphan scan cannot run, so the safe answer is not
                # "nothing uses it" -- it is "I cannot tell". Refusing keeps
                # the caller from acting on a guess; force=True is how a
                # caller says they have checked by other means.
                raise PyoneerConfigError(
                    "refusing to remove %r: it does not declare its extent "
                    "in this file, so whether any tile still points into it "
                    "is unknowable here. An external <tileset source=...> "
                    "keeps its tilecount in the .tsx. Remove with force=True "
                    "if you have confirmed it is unused."
                    % (ref.source or ref.name or key),
                    source=self.path)
            tiles = self.tiles_using_tileset(key)
            objects = self.objects_using_tileset(key)
            if tiles or objects:
                per_layer: dict[str, int] = {}
                for layer_name, _x, _y, _gid in tiles:
                    per_layer[layer_name] = per_layer.get(layer_name, 0) + 1
                for layer_name, _oid, _gid in objects:
                    per_layer[layer_name] = per_layer.get(layer_name, 0) + 1
                raise PyoneerConfigError(
                    "refusing to remove tileset %r (gids %d-%d): %d tile(s) "
                    "still reference it (%s). Removing it would not raise "
                    "anywhere -- pytmx resolves an orphaned gid to the "
                    "tileset BELOW it, so those tiles would silently paint "
                    "the wrong art. Renumbering the survivors is not the fix "
                    "either: it rewrites every csv token in the map and makes "
                    "this operation impossible to invert from serialized "
                    "state. Clear the tiles first (map.tile.set_many keeps an "
                    "exact inverse), then remove with force=True."
                    % (ref.name or ref.source or key, ref.first_gid,
                       ref.last_gid, len(tiles) + len(objects),
                       ", ".join("%s x%d" % (n, c)
                                 for n, c in sorted(per_layer.items()))),
                    source=self.path)

        self._remove_child(self.root, element)
        self._touch()
        trace_assets("remove_tileset key=%s", key)
        return True

    def serialize_tileset(self, key: str | int) -> dict[str, Any] | None:
        """Everything needed to put a tileset back exactly where it was.

        `serialize_layer`'s payload minus the group (a tileset is always a
        root child) and minus the next-id (a tileset has none -- its
        firstgid is carried instead, for a caller that needs to name it in
        an inverse command).

        The whitespace fields are the point, and are the same three
        `serialize_layer` carries. In ElementTree the whitespace BEFORE an
        element is not the element's own: it lives in the previous sibling's
        `tail`, or in `parent.text` when the element is first. Removal
        overwrites both, so both are captured here -- a recomputed indent is
        wrong somewhere in a file that mixes tabs and spaces.
        """
        element = self._tileset_element(key)
        if element is None:
            return None
        clone = copy.deepcopy(element)
        clone.tail = None
        siblings = list(self.root)
        index = siblings.index(element)
        return {
            "xml": ElementTree.tostring(clone, encoding="unicode"),
            "index": index,
            "tail": element.tail or "",
            "prev_tail": (siblings[index - 1].tail or "") if index else None,
            "parent_text": self.root.text if index == 0 else None,
            "first_gid": element.get("firstgid", "1"),
            "name": element.get("name", ""),
        }

    def restore_tileset(self, payload: dict[str, Any]) -> str:
        """Put back a tileset serialized by `serialize_tileset`.

        Returns its name, or '' for an external tileset -- which is why the
        payload also carries `first_gid`: it is the only key that addresses
        every tileset a map can hold.
        """
        parsed = _parse_restored_element(
            payload.get("xml") or "", "restore_tileset",
            "a <tileset> element", ("tileset",), self.path)

        placeholder = self._append_child(self.root, "tileset", payload.get("index"))
        placeholder.attrib = dict(parsed.attrib)
        placeholder.text = parsed.text
        for child in list(parsed):
            placeholder.append(child)

        if payload.get("tail") is not None:
            placeholder.tail = payload["tail"]
        siblings = list(self.root)
        position = siblings.index(placeholder)
        if position and payload.get("prev_tail") is not None:
            siblings[position - 1].tail = payload["prev_tail"]
        if payload.get("parent_text") is not None:
            self.root.text = payload["parent_text"]

        # The `<image>` grandchild was appended straight onto the parsed
        # clone rather than through _append_child, so the parent map has
        # never seen it. Anything that later asks _indent_of about it would
        # get "" without this.
        self._rebuild_parents()
        self._touch()
        trace_assets("restore_tileset name=%s firstgid=%s",
                     placeholder.get("name"), placeholder.get("firstgid"))
        return placeholder.get("name", "")

    def _claim_object_id(self) -> int:
        """Hand out the next object id, honouring the map's nextobjectid."""
        declared = int(self.root.get("nextobjectid", "1"))
        highest = 0
        for element in self.root.iter("object"):
            highest = max(highest, int(element.get("id", "0")))
        assigned = max(declared, highest + 1)
        self.root.set("nextobjectid", str(assigned + 1))
        return assigned

    def _release_object_id(self, object_id: int) -> None:
        """Undo a claim, but ONLY the most recent one.

        Tiled never lowers nextobjectid, and neither does this -- except in
        the exact case where the id being removed is the one just handed
        out. Without that, add_object + remove_object would leave a stray
        one-byte attribute change, which is precisely the diff noise this
        module exists to avoid.
        """
        if int(self.root.get("nextobjectid", "1")) == object_id + 1:
            self.root.set("nextobjectid", str(object_id))

    # -- tree edits with indentation ---------------------------------------
    def _rebuild_parents(self) -> None:
        parents: dict[ElementTree.Element, ElementTree.Element] = {}
        for parent in self.root.iter():
            # The SAME walk, because the two facts have the same lifetime:
            # a parser just handed us this element, so this is the one moment
            # its attribute order is guaranteed to be the file's own.
            self._remember_attributes(parent)
            for child in parent:
                parents[child] = parent
        self._parents = parents

    def _remember_attributes(self, element: ElementTree.Element) -> None:
        """Record the order `element` currently spells its attributes in.

        THE ORDER IS READ OFF THE FILE, NEVER COMPUTED.  #TAG:attribute_order_read_off_the_file

        MERGE, NEVER OVERWRITE, and that is the whole subtlety. Called a
        second time on an element that has since LOST an attribute, an
        overwrite would forget where the missing one sat -- which is the
        only thing this memory exists to know. So a name already remembered
        keeps its slot and only names that appeared since are appended.

        Call it wherever the order is STILL TRUE and nothing has recorded it
        yet. There are exactly three such moments and each has one caller:
        a parser has just produced the element (`_rebuild_parents`, at load
        and after every restore that rebuilds); this session has just
        authored it (`add_object`, `restore_object` -- the two paths that
        make an element and do not rebuild); and this module is one
        statement away from destroying it (`MapProperties.__setitem__`,
        which POPS `type` off a `<property>` it may itself have created).

        `MapObject.unset` deliberately does NOT call it. Every `<object>`
        has been through one of the three above before any door can reach
        it, so a call there could not fire -- and the repair has to hold for
        the caller that pops `element.attrib` directly anyway, which is what
        `map.object.unset` does today.
        """
        known = self._attribute_spellings.get(element)
        if known is None:
            self._attribute_spellings[element] = tuple(element.attrib)
            return
        appeared = tuple(key for key in element.attrib if key not in known)
        if appeared:
            self._attribute_spellings[element] = known + appeared

    def _indent_of(self, element: ElementTree.Element) -> str:
        """The horizontal whitespace preceding `element` on its own line."""
        parent = self._parents.get(element)
        if parent is None:
            return ""
        previous = None
        for child in parent:
            if child is element:
                break
            previous = child
        source = previous.tail if previous is not None else parent.text
        if not source:
            return ""
        return _TRAILING_INDENT_RE.search(source).group(0)

    def _child_indent(self, parent: ElementTree.Element) -> str:
        """Indentation for a NEW child of `parent`.

        Inferred locally from how much deeper `parent` sits than ITS parent,
        because this file's indentation is not consistent enough for a
        single global unit to be right anywhere.
        """
        own = self._indent_of(parent)
        grandparent = self._parents.get(parent)
        if grandparent is not None:
            outer = self._indent_of(grandparent)
            if own.startswith(outer) and len(own) > len(outer):
                return own + own[len(outer):]
        return own + " "

    def _separator_of(self, parent: ElementTree.Element,
                      children: list[ElementTree.Element]) -> str | None:
        """The whitespace this parent ALREADY puts in front of a child.

        READ OFF THE FILE, NEVER COMPUTED, which is the same sentence
        `__sibling_shape` is written under and the same one the append
        branch of `_append_child` learned the hard way. `_child_indent`
        infers a NEW child's indent from how much deeper the parent sits
        than ITS parent -- the only answer available when the parent has no
        children to copy -- and it is simply wrong whenever the file does
        not step by that amount. Measured on the round-trip fixture, whose
        `<layer>` is indented two and whose `<data>` is indented three:
        giving that layer a property and taking it away again moved
        `<data>` to four, one byte of diff on a no-op pair.

        The candidates are the separators BETWEEN siblings: `parent.text`
        sits in front of the first child, and each child's tail sits in
        front of the next. The LAST child's tail is excluded on purpose --
        that one is the whitespace before the parent's own closing tag and
        is a step shallower.

        A CHILDLESS PARENT STILL HAS AN ANSWER, and it is why this is
        called on every path rather than only when siblings exist: with no
        children the list is just `parent.text`, which is None for an
        element the file wrote self-closing -- no answer, compute one --
        and is the file's own separator for an element whose last child
        was just removed, because `ObjectLayer.remove_object` puts that
        text back. Restoring into an emptied layer therefore copies the
        file's indent instead of recomputing it.
        """
        for candidate in [parent.text] + [c.tail for c in children[:-1]]:
            if candidate and not candidate.strip() and "\n" in candidate:
                return candidate
        return None

    def _append_child(self, parent: ElementTree.Element, tag: str,
                      index: int | None = None) -> ElementTree.Element:
        """Insert a new element, indented to match its siblings."""
        element = ElementTree.Element(tag)
        own_indent = self._indent_of(parent)
        child_indent = self._child_indent(parent)
        children = list(parent)
        position = len(children) if index is None else index
        # ONE RULE, asked on every branch: the file's own spelling outranks
        # the computed one wherever the file has one, and `_child_indent` is
        # the fallback for a parent with nothing to copy. Three branches
        # each computing their own answer is what put a one-byte diff on a
        # no-op pair three different ways.
        separator = self._separator_of(parent, children)
        inner = separator if separator is not None else "\n" + child_indent

        if not children:
            # First child: the parent may have been written self-closing,
            # in which case there is nothing to copy and `inner` is the
            # computed answer. When it was NOT -- an emptied object layer
            # carries the text `remove_object` put back -- that is the
            # file's own separator and it stays.
            if separator is None:
                parent.text = inner
            element.tail = "\n" + own_indent
            parent.append(element)
        elif position >= len(children):
            # The last child's tail IS the whitespace before the parent's
            # closing tag, so the new last child must INHERIT it rather than
            # get a recomputed one. Recomputing looked equivalent and was
            # not: appending a layer to <group> emitted "\n\t" where the file
            # had "\n ", and since _remove_child restores from the removed
            # element's tail, add-then-remove came back one byte different.
            # Inheriting makes the pair exactly reversible.
            closing = children[-1].tail
            element.tail = closing if closing else "\n" + own_indent
            children[-1].tail = inner
            parent.append(element)
        else:
            element.tail = inner
            parent.insert(position, element)
            if position == 0 and (parent.text is None or not parent.text.strip()):
                parent.text = inner
        self._parents[element] = parent
        return element

    def _remove_child(self, parent: ElementTree.Element,
                      element: ElementTree.Element) -> None:
        """Remove an element and hand its trailing whitespace back.

        THE LAST CHILD OUT TURNS THE LIGHT OFF. `_append_child` writes
        `parent.text` -- the whitespace in front of the first child -- the
        moment an element gains one, so the inverse has to take it away
        again or an element the file wrote self-closing comes back as an
        open/close pair with a blank line between the tags. That is two
        lines of diff nobody authored on a declare-then-undo, and it makes
        `MapDocument.changed` report a map dirty after a no-op pair,
        because `changed` re-serialises and compares BYTES.

        This line lived at FOUR call sites in `editor/core/verbs.py`, each
        with a comment saying it belonged here; the fourth was missed for a
        whole pass by a grep that named the other three. It is one function
        now, and the four copies are deleted -- which is the counter-move
        CLAUDE.md's sibling-route warning prescribes.

        The condition is the exact mirror of `_append_child`'s own: only a
        WHITESPACE-ONLY text is cleared, so an element carrying real
        content (a `<data>` csv payload, a multi-line `<property>` body) is
        never touched no matter what is removed from it.
        """
        children = list(parent)
        position = children.index(element)
        # The last child owns the whitespace in front of the closing tag, so
        # its tail has to be inherited or the closing tag loses its indent.
        if position == len(children) - 1 and position > 0:
            children[position - 1].tail = element.tail
        parent.remove(element)
        self._parents.pop(element, None)
        # Its attribute order goes with it. Every restore re-PARSES the
        # element text rather than re-inserting this object, so there is
        # nothing here a later restore could want -- and a dict keyed by
        # element would otherwise hold every element the session ever
        # deleted alive for the life of the document.
        self._attribute_spellings.pop(element, None)
        if not list(parent) and not (parent.text or "").strip():  #TAG:childless_parent_closes_itself
            parent.text = None

    def _touch(self) -> None:
        self._touched = True

    def __repr__(self) -> str:
        return "MapDocument(%r, %dx%d, layers=%r)" % (
            self.path, self.width, self.height, self.layer_names())
