"""A round-trip-safe read/WRITE document layer for Tiled .tmx files.

WHY THIS EXISTS
---------------
pytmx is read-only. It has no writer at all, and it is lossy by design: it
hands back a runtime view (surfaces, resolved gids, flattened layers) with no
memory of how the file on disk was punctuated. That is exactly right for
rendering and exactly wrong for editing.

The long-term goal of this project is that a human edits maps in Tiled while
an AI edits the same maps programmatically. That only works if a
programmatic write is a MINIMAL DIFF. A writer that reflows the document --
re-indents it, reorders attributes, rewrites the XML declaration, converts
CRLF to LF -- destroys that collaboration after the very first AI edit,
because every later `git diff` a human reads is 100% noise and 0% signal.

So the contract here is stronger than "produces valid TMX":

    load(path) -> save(path)  is BYTE IDENTICAL when nothing was changed
    set_tile(x, y, gid)       changes the bytes of exactly one csv token
    add_object + remove_object returns the original bytes

That is measured, not asserted by vibes: tools/check_tmx_roundtrip.py does
the byte comparison against the shipped 133,940-byte data/maps/test.tmx.

WHAT THE SHIPPED FILE ACTUALLY LOOKS LIKE
-----------------------------------------
data/maps/test.tmx is not tidy, and pretending otherwise is how a writer
breaks. Measured facts about it:

  * CRLF line endings throughout. An XML parser is REQUIRED by spec to
    normalize CRLF to LF while parsing, so every `\\r` is gone by the time
    ElementTree hands you a tree. Naive re-serialization loses 641 bytes.
  * Inconsistent indentation. The first elements use tabs
    (`\\t<tileset ...>`); everything from the second <layer> down uses one,
    two or three SPACES; and every `</data>` sits at column 0.
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
Without that attribute a `depth` of 50 reads back as the string '50', and
`'50' * 2` is '5050' rather than 100.

MEASURED, because the assumption is easy to get wrong: the pytmx installed
here (3.32) DOES honour the type attribute on read -- `parse_properties`
looks the type up in `prop_type` and casts. So the read side is not broken
today, and check_tmx_roundtrip asserts that pytmx and this module agree on
the same file rather than pretending otherwise.

What has no pytmx equivalent is the WRITE side. Nothing in pytmx can emit
`type="int"`, and a property written without it is silently downgraded to a
string for every future reader, pytmx included. `format_property` is what
stops a programmatic spawn point from poisoning its own properties, and it
checks `bool` before `int` because in Python `bool` IS an `int` and
`type="int" value="True"` is a file Tiled rejects.

One real pytmx gap this module does not share: pytmx reads a property's
value as `subnode.get("value") or subnode.text`, then casts
`cls(subnode.get("value"))`. A multi-line property (Tiled moves those into
the element body and drops the `value` attribute) therefore raises inside
pytmx if it is typed, and reads as None if its value is empty. MapProperties
reads the body text instead.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ElementTree
from typing import Any, Iterator

from scripts.core.errors import PyoneerAssetMissingError, PyoneerConfigError, warn_content
from scripts.core.log import trace_assets

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


def _serialize(element: ElementTree.Element, parts: list[str]) -> None:
    """Append `element` to `parts`, preserving its whitespace verbatim."""
    tag = element.tag
    if tag is ElementTree.Comment:
        parts.append("<!--%s-->" % (element.text or ""))
    elif tag is ElementTree.ProcessingInstruction:
        parts.append("<?%s?>" % (element.text or ""))
    else:
        parts.append("<" + tag)
        for key, value in element.attrib.items():
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
                _serialize(child, parts)
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
    def set_tile(self, x: int, y: int, gid: int) -> bool:
        """Set one gid. Returns True if the value actually changed.

        Writing the value it already holds is a no-op down to the byte, so a
        tool that re-stamps an unchanged region produces an empty diff.
        """
        index = self._index(x, y)
        gid = int(gid)
        if gid < 0:
            raise PyoneerConfigError(
                "gid %d is negative; tmx gids are unsigned (0 means empty)" % gid,
                source=self._document.path,
            )
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
        self.element.set(key, _attribute_text(value))
        self._document._touch()

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
        wrapper = MapObject(self._document, element)
        if properties:
            view = wrapper.properties
            for key, value in properties.items():
                view[key] = value
        self._document._touch()
        trace_assets("add_object layer=%s id=%s name=%s", self.name, assigned, name)
        return wrapper

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
# The document
# ---------------------------------------------------------------------------

_LAYER_TAGS = ("layer", "objectgroup", "imagelayer", "group")


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
        _serialize(self.root, parts)
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
        self._parents = {
            child: parent for parent in self.root.iter() for child in parent
        }

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

    def _append_child(self, parent: ElementTree.Element, tag: str,
                      index: int | None = None) -> ElementTree.Element:
        """Insert a new element, indented to match its siblings."""
        element = ElementTree.Element(tag)
        own_indent = self._indent_of(parent)
        child_indent = self._child_indent(parent)
        children = list(parent)
        position = len(children) if index is None else index

        if not children:
            # First child: the parent may have been written self-closing.
            if parent.text is None or not parent.text.strip():
                parent.text = "\n" + child_indent
            element.tail = "\n" + own_indent
            parent.append(element)
        elif position >= len(children):
            children[-1].tail = "\n" + child_indent
            element.tail = "\n" + own_indent
            parent.append(element)
        else:
            element.tail = "\n" + child_indent
            parent.insert(position, element)
            if position == 0 and (parent.text is None or not parent.text.strip()):
                parent.text = "\n" + child_indent
        self._parents[element] = parent
        return element

    def _remove_child(self, parent: ElementTree.Element,
                      element: ElementTree.Element) -> None:
        """Remove an element and hand its trailing whitespace back."""
        children = list(parent)
        position = children.index(element)
        # The last child owns the whitespace in front of the closing tag, so
        # its tail has to be inherited or the closing tag loses its indent.
        if position == len(children) - 1 and position > 0:
            children[position - 1].tail = element.tail
        parent.remove(element)
        self._parents.pop(element, None)

    def _touch(self) -> None:
        self._touched = True

    def __repr__(self) -> str:
        return "MapDocument(%r, %dx%d, layers=%r)" % (
            self.path, self.width, self.height, self.layer_names())
