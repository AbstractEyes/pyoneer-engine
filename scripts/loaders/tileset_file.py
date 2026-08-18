"""The .tileset file, and the line grammar the whole .blit* family shares.

WHY A TILESET IS ITS OWN FILE
-----------------------------
In .tmx a tileset is either EMBEDDED -- copied whole into every map that uses
it -- or EXTERNAL, in a .tsx that is a second XML document with its own
parser, its own escaping and its own round-trip problem. Embedding means the
same 768-tile declaration lives in five maps and drifts in four of them.
Externalizing means a second copy of the .tmx machinery.

So: one tileset, one file, always. `mapname.blitmap` points at
`tilesetname.tileset` the way a stylesheet points at a font. Sharing is the
default rather than the advanced option, a tileset's collision defaults have
somewhere to live that is not "inside whichever map was saved last", and the
map file stops carrying a copy of data it does not own.

THE MAGIC WORD IS THE EXTENSION
-------------------------------
`.blitmask` already ships and its first line is `blitmask 1`. This file
follows that rule exactly: the first line of a `.tileset` is `tileset 1`, and
the first line of a `.blitmap` is `blitmap 1`. One rule, no table to
remember, and `head -1` identifies any file in the family.

WHAT THIS FORMAT DOES *NOT* DO, DELIBERATELY
--------------------------------------------
It does not preserve punctuation. `map_document.py` goes to enormous lengths
to reproduce Tiled's tabs, spaces, CRLFs and self-closing tags, and it is
right to: that file is written by someone else's program and a reflow makes
every future human diff unreadable.

This format is OURS. Nobody else writes it. So it takes the opposite trade
and is CANONICAL: exactly one spelling per model. That turns byte-exactness
from a thousand lines of whitespace bookkeeping into two theorems --

    parse(render(model)) == model        for every model
    render(parse(text))  == text         for every text render() can emit

-- and a reader that hand-edits a file into a non-canonical shape gets it
normalized on the next save rather than silently preserved. The whole
apparatus of `prev_tail`, `parent_text` and `__sibling_shape` disappears.

THE GRAMMAR
-----------
Line oriented. One tab per level of nesting, never spaces. A line is a
keyword, a space, and the rest:

    tileset 1
    name TileA2
    image ../graphics/tilesets/System/TileA2.png
    imagesize 512 384
    tilesize 16 16
    count 768
    columns 32
    collision TileA2.blitmask
    prop string author rm-vx-ace
    tile 4
    	class wall
    	prop bool solid true

Zero-valued optionals (`margin 0`, `spacing 0`) are omitted, because a file
that states every default is a file where the two lines that matter are
invisible.

Tabs, not spaces, and it RAISES on a space indent rather than accepting it.
Being lenient here would mean two spellings of the same tree, which breaks
the second theorem above -- and the failure of a lenient reader is silent,
while the failure of a strict one names the line.

ESCAPING
--------
`\\\\`, `\\n`, `\\r`, `\\t`, and `\\s` for a space. Two encoders, one decoder:
a WORD (a key, a property name) escapes every space because it has to stay
one token; a VALUE escapes only the spaces at its ENDS, because interior
spaces are the readable part and a line that ends in whitespace is a line
some editor will silently trim.

PROPERTIES KEEP THEIR ON-DISK TEXT
----------------------------------
A property is stored as (type, name, RAW TEXT) rather than as a Python
value, and that is not laziness. Tiled's `color`, `file` and `object` types
all read back as `str`, so a round trip through Python values would rewrite
`type="color"` as a plain string and the colour picker would be gone the
next time the map opened in Tiled. `.value` casts on demand through
`map_document.parse_property`, which is the same function the engine's read
path uses, so there is one caster and it cannot drift.
"""
from __future__ import annotations

import filecmp
import os
import shutil
from dataclasses import dataclass, replace
from typing import Any, Callable, ClassVar, Iterable, Sequence

from scripts.core.errors import PyoneerConfigError, warn_content
from scripts.loaders.map_document import parse_property, tileset_geometry

MAGIC = "tileset"
VERSION = 1

# What a .blitmap's `source` line is expected to point at, and what an
# interned image is measured against. Both live here so the two modules
# cannot disagree about the family's own extensions.
TILESET_SUFFIX = ".tileset"
BLITMAP_SUFFIX = ".blitmap"
BLITMASK_SUFFIX = ".blitmask"


class PyoneerBlitFormatError(PyoneerConfigError):
    """A .blitmap or .tileset is not the agreed format.

    Carries the offending line, because a 100-row map with one bad
    character should not read as "the file is broken". Same shape as
    `PyoneerBlitmaskError` in the editor's collision stack, on purpose --
    the two formats are siblings and a caller catching one shape catches
    both families of authoring mistake.
    """

    def __init__(self, message: str, *, line: int | None = None,
                 path: str | None = None, **context: Any):
        where = []
        if path:
            where.append(path)
            context["path"] = path
        if line is not None:
            where.append("line %d" % line)
            context["line"] = line
        if where:
            message = "%s: %s" % (" ".join(where), message)
        super().__init__(message, **context)
        self.line = line
        self.path = path


# ---------------------------------------------------------------------------
# Text primitives
#
# These live in this module rather than in blitmap.py because the dependency
# between the two runs one way: a .blitmap references .tileset files, so
# blitmap.py imports this and never the reverse. Putting the shared grammar
# in the leaf is what keeps that direction true without a third module.
# ---------------------------------------------------------------------------

_INDENT = "\t"
_ESCAPES = {"\\": "\\", "n": "\n", "r": "\r", "t": "\t", "s": " "}


def escape_word(text: str) -> str:
    """Escape a token that must survive as ONE whitespace-free word."""
    out = str(text).replace("\\", "\\\\")
    out = out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return out.replace(" ", "\\s")


def escape_text(text: str) -> str:
    """Escape a value that runs to the end of the line.

    Interior spaces stay literal -- they are what makes the line readable --
    but a run of spaces at either END is escaped, because the parser strips
    trailing whitespace and so does every editor with "trim on save" on.
    """
    out = str(text).replace("\\", "\\\\")
    out = out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    stripped = out.strip(" ")
    if not stripped:
        return "\\s" * len(out)
    lead = len(out) - len(out.lstrip(" "))
    trail = len(out) - len(out.rstrip(" "))
    return "\\s" * lead + stripped + "\\s" * trail


def unescape(text: str, *, line: int | None = None,
             path: str | None = None) -> str:
    """The one decoder for both encoders.

    An unknown escape RAISES rather than passing the backslash through. A
    lenient decoder turns a typo into a value that is subtly wrong and still
    loads, which is this repo's documented worst case.
    """
    if "\\" not in text:
        return text
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        if index + 1 >= len(text):
            raise PyoneerBlitFormatError(
                "a trailing backslash escapes nothing", line=line, path=path)
        following = text[index + 1]
        if following not in _ESCAPES:
            raise PyoneerBlitFormatError(
                "\\%s is not an escape; this format knows \\\\ \\n \\r \\t \\s"
                % following, line=line, path=path)
        out.append(_ESCAPES[following])
        index += 2
    return "".join(out)


def tail(text: str) -> str:
    """A value appended to a line, or nothing at all when it is empty.

    An empty value must not leave the line ending in a space: `render` would
    emit trailing whitespace that the lexer strips and half the editors in
    the world strip too, so the file on disk and the file the model renders
    would differ by a byte nobody typed.
    """
    return (" " + text) if text else ""


def number_text(value: float | int) -> str:
    """Render a number the way Tiled writes an attribute: ints stay ints.

    `x=64` and `x=64.0` are the same to a parser and not the same to a human
    reading a diff, so the whole-number case loses the `.0`. Same rule and
    same reasoning as `map_document._attribute_text`.
    """
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@dataclass(frozen=True)
class Line:
    """One significant line: where it was, how deep, and what it says."""

    number: int
    depth: int
    keyword: str
    rest: str

    def word(self, *, path: str | None = None) -> tuple[str, str]:
        """Split `rest` into its first word and the remainder, unescaping
        the word. The remainder is left encoded for the caller to decide."""
        head, _, tail = self.rest.partition(" ")
        return unescape(head, line=self.number, path=path), tail

    def text(self, *, path: str | None = None) -> str:
        return unescape(self.rest, line=self.number, path=path)

    def ints(self, count: int, *, path: str | None = None) -> list[int]:
        parts = self.rest.split()
        if len(parts) != count:
            raise PyoneerBlitFormatError(
                "%s wants %d integer(s), got %r"
                % (self.keyword, count, self.rest), line=self.number, path=path)
        try:
            return [int(part) for part in parts]
        except ValueError:
            raise PyoneerBlitFormatError(
                "%s wants integers, got %r" % (self.keyword, self.rest),
                line=self.number, path=path) from None


def lex(text: str, *, path: str | None = None) -> list[Line]:
    """Text to significant lines. Blank lines and `#` comments are dropped.

    Dropping comments means they do not survive a load/save cycle, which is
    exactly what `.blitmask` already does and is the honest consequence of a
    canonical format: there is nowhere in the MODEL for a comment to live,
    and inventing a place for one is how a format grows a second spelling.
    """
    lines: list[Line] = []
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.rstrip()
        if not stripped or stripped.lstrip("\t").startswith("#"):
            continue
        depth = len(stripped) - len(stripped.lstrip("\t"))
        body = stripped[depth:]
        if body[:1] in (" ", "\t"):
            raise PyoneerBlitFormatError(
                "indent with tabs only; this line mixes in a space. The "
                "format is canonical, so two spellings of one tree is a bug "
                "rather than a preference", line=number, path=path)
        keyword, _, rest = body.partition(" ")
        lines.append(Line(number, depth, keyword, rest))
    return lines


class Cursor:
    """A position in a lexed file, with the block loop every reader wants."""

    def __init__(self, lines: Sequence[Line], path: str | None = None):
        self.lines = list(lines)
        self.path = path
        self.index = 0

    def peek(self) -> Line | None:
        return self.lines[self.index] if self.index < len(self.lines) else None

    def take(self) -> Line:
        line = self.lines[self.index]
        self.index += 1
        return line

    def fail(self, message: str, line: Line | None = None) -> "PyoneerBlitFormatError":
        number = line.number if line is not None else (
            self.lines[self.index - 1].number if self.index else None)
        return PyoneerBlitFormatError(message, line=number, path=self.path)

    def block(self, depth: int) -> Iterable[Line]:
        """Yield every line at exactly `depth`, stopping at the first
        shallower one. A DEEPER line is an error rather than a skip: it means
        the writer indented something under a keyword that takes no block,
        and silently ignoring it loses authored data."""
        while True:
            line = self.peek()
            if line is None or line.depth < depth:
                return
            if line.depth > depth:
                raise self.fail(
                    "unexpected indent: %r is nested under a line that takes "
                    "no block" % line.keyword, line)
            yield self.take()


def once(seen: set[str], line: Line, cursor: Cursor) -> None:
    """Refuse a duplicate header key.

    Without this a second `columns` line silently wins and the tileset is
    read against a shape its author did not write last -- the same trap
    `.blitmask` guards its `size` line against.
    """
    if line.keyword in seen:
        raise cursor.fail("%r appears twice" % line.keyword, line)
    seen.add(line.keyword)


# ---------------------------------------------------------------------------
# Custom properties
# ---------------------------------------------------------------------------

_PROPERTY_TYPES = ("string", "int", "float", "bool", "color", "file", "object")


@dataclass(frozen=True)
class Property:
    """One custom property, kept as it sits on disk.

    `type` is Tiled's vocabulary, with `string` written explicitly where a
    .tmx omits the attribute. Explicit because "absent" and "string" being
    the same thing is a rule a reader has to know, and a format that needs
    footnotes is a format that gets read wrong.
    """

    name: str
    type: str = "string"
    text: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise PyoneerBlitFormatError("a property needs a name")
        if not self.type or any(c.isspace() for c in self.type):
            raise PyoneerBlitFormatError(
                "property type %r must be one word" % self.type)
        if self.type not in _PROPERTY_TYPES:
            # Warn, never raise: Tiled adds types (`class`, enums) and a map
            # that opens in Tiled must not fail to open here. The raw text is
            # carried either way, so nothing is lost by not understanding it.
            warn_content("property %r declares unknown type %r; its text is "
                         "carried verbatim" % (self.name, self.type))

    @property
    def value(self) -> Any:
        """The typed value, cast by the engine's own property caster."""
        return parse_property(self.type, self.text)

    def render(self, depth: int = 0) -> str:
        return "%sprop %s %s%s" % (_INDENT * depth, self.type,
                                   escape_word(self.name),
                                   tail(escape_text(self.text)))

    @classmethod
    def read(cls, line: Line, cursor: Cursor) -> "Property":
        # Exactly two splits: the type and the name are words, and the value
        # is whatever is left, spaces and all.
        parts = line.rest.split(" ", 2)
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise cursor.fail(
                "prop wants a type, a name and a value, got %r" % line.rest,
                line)
        type_name, name, text = parts[0], parts[1], (parts[2] if len(parts) > 2 else "")
        return cls(unescape(name, line=line.number, path=cursor.path),
                   unescape(type_name, line=line.number, path=cursor.path),
                   unescape(text, line=line.number, path=cursor.path))


def render_properties(properties: Sequence[Property], depth: int) -> list[str]:
    return [prop.render(depth) for prop in properties]


def render_attributes(attributes: Sequence[tuple[str, str]],
                      depth: int) -> list[str]:
    """`attr` lines: everything the format does not model, carried verbatim.

    This is the pressure valve that keeps the format from growing a field
    every time Tiled grows one. What gets a first-class name is what the
    ENGINE reads; the rest -- `tiledversion`, `compressionlevel`, `locked` --
    is bookkeeping we neither interpret nor are entitled to discard.
    """
    return ["%sattr %s%s" % (_INDENT * depth, escape_word(key),
                             tail(escape_text(value)))
            for key, value in attributes]


def read_attribute(line: Line, cursor: Cursor) -> tuple[str, str]:
    key, rest = line.word(path=cursor.path)
    if not key:
        raise cursor.fail("attr wants a key and a value", line)
    return key, unescape(rest, line=line.number, path=cursor.path)


# ---------------------------------------------------------------------------
# The tileset
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TileEntry:
    """Per-tile authored data: `<tile id=...>` inside a tmx tileset."""

    id: int
    type: str = ""
    attributes: tuple[tuple[str, str], ...] = ()
    properties: tuple[Property, ...] = ()

    def __post_init__(self) -> None:
        if self.id < 0:
            raise PyoneerBlitFormatError("tile id %d is negative" % self.id)

    def render(self, depth: int = 0) -> list[str]:
        lines = ["%stile %d" % (_INDENT * depth, self.id)]
        if self.type:
            lines.append("%sclass %s" % (_INDENT * (depth + 1),
                                         escape_text(self.type)))
        lines += render_attributes(self.attributes, depth + 1)
        lines += render_properties(self.properties, depth + 1)
        return lines


@dataclass(frozen=True)
class TilesetFile:
    """One tileset: the image, the grid over it, and what its tiles mean.

    Frozen, like everything else a command has to be able to invert from
    stored state. An edit produces a NEW TilesetFile and the old one IS the
    undo value -- nothing to copy defensively, nothing that can change
    underneath a stored reference. `replace()` from dataclasses is the
    editing verb.

    COLLISION IS A REFERENCE, NOT A COPY
    ------------------------------------
    `collision` names a `.blitmask` sitting beside the image. That format
    lives in `scripts/core/collision_runtime.py`, it is already grid-shaped
    to the tileset (`TilesetDefaults.opinions` is row-major over
    columns x rows), and it is already round-trip tested. Re-encoding those
    opinions inside this file would be a second spelling of the same data,
    and the second spelling is always the one that rots.

    WHAT READS IT TODAY, AND WHAT DOES NOT. The engine reads per-tile masks
    on the .tmx path: a tmx `<tileset>` declares `pyoneer_collision`,
    `collision_runtime.tileset_defaults` loads the file it names, and
    `field_from_map` stacks it under the companion levels. Nothing reads
    THIS line yet, because the .blitmap path has no collision read at all --
    `field_from_map` answers None for a native map, by design and with its
    reasons written down. When that path grows one, this field is the
    declaration it should use, and the parser is now on this side of the
    fence: the old reason it could not be read here (`scripts/` may never
    import `editor/`) stopped applying the day the format moved.
    """

    name: str
    image: str = ""
    image_width: int = 0
    image_height: int = 0
    tile_width: int = 0
    tile_height: int = 0
    margin: int = 0
    spacing: int = 0
    tile_count: int = 0
    columns: int = 0
    collision: str = ""
    attributes: tuple[tuple[str, str], ...] = ()
    properties: tuple[Property, ...] = ()
    tiles: tuple[TileEntry, ...] = ()

    MAGIC: ClassVar[str] = MAGIC
    VERSION: ClassVar[int] = VERSION

    def __post_init__(self) -> None:
        if not self.name:
            raise PyoneerBlitFormatError("a tileset needs a name")
        if self.tile_width <= 0 or self.tile_height <= 0:
            raise PyoneerBlitFormatError(
                "tileset %r needs a positive tile size, got %dx%d"
                % (self.name, self.tile_width, self.tile_height))
        if self.margin < 0 or self.spacing < 0:
            raise PyoneerBlitFormatError(
                "tileset %r has margin=%d spacing=%d; both are non-negative"
                % (self.name, self.margin, self.spacing))
        if self.tile_count < 0 or self.columns < 0:
            raise PyoneerBlitFormatError(
                "tileset %r declares %d tiles in %d columns; both are "
                "non-negative" % (self.name, self.tile_count, self.columns))
        if self.collision and not self.collision.endswith(BLITMASK_SUFFIX):
            # Warn rather than raise: the tileset is still usable and the
            # reference is still carried. But a mask reference that is not a
            # mask is a file the editor will fail to open LATER, somewhere
            # far from the line that wrote it.
            warn_content(
                "tileset %r points its collision defaults at %r, which is not "
                "a %s. The per-tile mask format is the one in "
                "scripts/core/collision_runtime.py, and a reference that is "
                "not one names a file no reader will open"
                % (self.name, self.collision, BLITMASK_SUFFIX))
        seen: set[int] = set()
        for entry in self.tiles:
            if entry.id in seen:
                raise PyoneerBlitFormatError(
                    "tileset %r declares tile %d twice" % (self.name, entry.id))
            seen.add(entry.id)

    # -- derived -----------------------------------------------------------
    @property
    def rows(self) -> int:
        """Rows the declared tile count occupies. 0 when columns is unknown."""
        if self.columns <= 0:
            return 0
        return -(-self.tile_count // self.columns)      # ceiling division

    @property
    def measured(self) -> tuple[int, int, int]:
        """(columns, rows, tiles) the IMAGE can actually hold.

        Separate from the declared numbers on purpose. A sheet that was
        recropped outside the editor still declares its old tile count, and
        the difference between what is declared and what fits is the only
        signal that has happened.
        """
        return tileset_geometry(self.image_width, self.image_height,
                                self.tile_width, self.tile_height,
                                self.margin, self.spacing)

    @property
    def last_local_id(self) -> int:
        return self.tile_count - 1

    def tile(self, tile_id: int) -> TileEntry | None:
        for entry in self.tiles:
            if entry.id == tile_id:
                return entry
        return None

    # -- text --------------------------------------------------------------
    def render(self) -> str:
        """The file, as a string. Always ends in a newline."""
        lines = ["%s %d" % (MAGIC, VERSION),
                 "name %s" % escape_text(self.name)]
        if self.image:
            lines.append("image %s" % escape_text(self.image))
        if self.image_width or self.image_height:
            lines.append("imagesize %d %d" % (self.image_width, self.image_height))
        lines.append("tilesize %d %d" % (self.tile_width, self.tile_height))
        # Zero-valued optionals are omitted. A file that restates every
        # default is one where the two lines that matter do not stand out.
        if self.margin:
            lines.append("margin %d" % self.margin)
        if self.spacing:
            lines.append("spacing %d" % self.spacing)
        if self.tile_count:
            lines.append("count %d" % self.tile_count)
        if self.columns:
            lines.append("columns %d" % self.columns)
        if self.collision:
            lines.append("collision %s" % escape_text(self.collision))
        lines += render_attributes(self.attributes, 0)
        lines += render_properties(self.properties, 0)
        for entry in self.tiles:
            lines += entry.render(0)
        return "\n".join(lines) + "\n"

    @classmethod
    def parse(cls, text: str, *, path: str | None = None) -> "TilesetFile":
        cursor = Cursor(lex(text, path=path), path)
        read_magic(cursor, MAGIC, VERSION)
        fields: dict[str, Any] = {"attributes": [], "properties": [],
                                  "tiles": []}
        seen: set[str] = set()
        for line in cursor.block(0):
            keyword = line.keyword
            if keyword == "name":
                once(seen, line, cursor)
                fields["name"] = line.text(path=path)
            elif keyword == "image":
                once(seen, line, cursor)
                fields["image"] = line.text(path=path)
            elif keyword == "imagesize":
                once(seen, line, cursor)
                fields["image_width"], fields["image_height"] = line.ints(2, path=path)
            elif keyword == "tilesize":
                once(seen, line, cursor)
                fields["tile_width"], fields["tile_height"] = line.ints(2, path=path)
            elif keyword in ("margin", "spacing", "count", "columns"):
                once(seen, line, cursor)
                key = {"count": "tile_count"}.get(keyword, keyword)
                fields[key] = line.ints(1, path=path)[0]
            elif keyword == "collision":
                once(seen, line, cursor)
                fields["collision"] = line.text(path=path)
            elif keyword == "attr":
                fields["attributes"].append(read_attribute(line, cursor))
            elif keyword == "prop":
                fields["properties"].append(Property.read(line, cursor))
            elif keyword == "tile":
                fields["tiles"].append(_read_tile_entry(line, cursor, path))
            else:
                raise cursor.fail("unknown keyword %r in a .tileset" % keyword,
                                  line)
        if "name" not in fields:
            raise PyoneerBlitFormatError("no name line", path=path)
        fields["attributes"] = tuple(fields["attributes"])
        fields["properties"] = tuple(fields["properties"])
        fields["tiles"] = tuple(fields["tiles"])
        return cls(**fields)

    # -- disk --------------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "TilesetFile":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.parse(handle.read(), path=path)

    def save(self, path: str) -> str:
        """Write it. newline='' so the bytes are the bytes on every platform.

        The engine's whole map contract is byte-exactness, and a file that
        grows carriage returns on Windows and loses them on the next machine
        is a diff nobody authored. Same reasoning, same spelling, as
        `Blitmask.save`.
        """
        target = os.path.abspath(path)
        directory = os.path.dirname(target)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as handle:
            handle.write(self.render())
        return target

    def __str__(self) -> str:
        return self.render()

    def __repr__(self) -> str:
        return "TilesetFile(%r, %d tiles, %d columns, image=%r)" % (
            self.name, self.tile_count, self.columns, self.image)


def read_magic(cursor: Cursor, magic: str, version: int) -> None:
    """Consume and check the `<magic> <version>` line every file starts with."""
    line = cursor.peek()
    if line is None:
        raise PyoneerBlitFormatError("file is empty", path=cursor.path)
    cursor.take()
    if line.depth != 0 or line.keyword != magic:
        raise cursor.fail(
            "expected %r and a version, got %r" % (magic, line.keyword), line)
    try:
        found = int(line.rest.strip())
    except ValueError:
        raise cursor.fail(
            "version must be an integer, got %r" % line.rest, line) from None
    if found != version:
        raise cursor.fail(
            "version %d is not readable by this build (expected %d)"
            % (found, version), line)


def _read_tile_entry(header: Line, cursor: Cursor,
                     path: str | None) -> TileEntry:
    tile_id = header.ints(1, path=path)[0]
    type_name = ""
    attributes: list[tuple[str, str]] = []
    properties: list[Property] = []
    seen: set[str] = set()
    for line in cursor.block(header.depth + 1):
        if line.keyword == "class":
            once(seen, line, cursor)
            type_name = line.text(path=path)
        elif line.keyword == "attr":
            attributes.append(read_attribute(line, cursor))
        elif line.keyword == "prop":
            properties.append(Property.read(line, cursor))
        else:
            raise cursor.fail("unknown keyword %r inside a tile block"
                              % line.keyword, line)
    return TileEntry(tile_id, type_name, tuple(attributes), tuple(properties))


# ---------------------------------------------------------------------------
# tmx -> .tileset
# ---------------------------------------------------------------------------

# Attributes this format gives a first-class name to. Everything else on a
# tmx <tileset> falls through to `attr` and survives untouched.
_TILESET_MODELLED = ("firstgid", "source", "name", "tilewidth", "tileheight",
                     "margin", "spacing", "tilecount", "columns")
_TILE_MODELLED = ("id", "type", "class")


def _int_of(element, key: str, default: int = 0) -> int:
    raw = element.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        warn_content("tmx <%s %s=%r> is not an integer; using %d"
                     % (element.tag, key, raw, default))
        return default


def _properties_of(element) -> tuple[Property, ...]:
    """Every `<property>` under `element`, as (type, name, raw text).

    Reads the raw strings, never `MapProperties` typed values, because the
    point is to carry `type="color"` across unchanged. It also picks up the
    multi-line case Tiled writes into the element BODY rather than the
    `value` attribute -- pytmx raises on those, so a converter that used
    pytmx would lose the map instead of the property.
    """
    container = element.find("properties")
    if container is None:
        return ()
    found: list[Property] = []
    for entry in container.findall("property"):
        name = entry.get("name", "")
        type_name = entry.get("type") or "string"
        text = entry.get("value") if "value" in entry.attrib else (entry.text or "")
        found.append(Property(name, type_name, text or ""))
    return tuple(found)


def _attributes_of(element, modelled: Sequence[str]) -> tuple[tuple[str, str], ...]:
    return tuple((key, value) for key, value in element.attrib.items()
                 if key not in modelled)


def from_tmx_tileset(element, *, dropped: list[str] | None = None,
                     collision: str = "") -> TilesetFile:
    """One tmx `<tileset>` element as a TilesetFile.

    EMBEDDED tilesets only. An external `<tileset source="foo.tsx"/>` is a
    second XML document this module cannot open, and inventing its tile
    count would silently repaint every tile authored against it -- the same
    failure `MapDocument.require_known_extents` refuses to risk. Convert the
    .tsx first, then point the map at the .tileset.
    """
    source = element.get("source", "")
    if source:
        raise PyoneerBlitFormatError(
            "tileset at firstgid %s is EXTERNAL (%r): its tile count, image "
            "and geometry all live in a .tsx this converter cannot open. "
            "Convert that .tsx to a .tileset first, then point the map at it"
            % (element.get("firstgid", "?"), source))

    name = element.get("name", "")
    image = element.find("image")
    image_source = "" if image is None else image.get("source", "")
    image_width = 0 if image is None else _int_of(image, "width", 0)
    image_height = 0 if image is None else _int_of(image, "height", 0)

    tiles: list[TileEntry] = []
    for tile in element.findall("tile"):
        extra = [child.tag for child in tile
                 if child.tag not in ("properties",)]
        if extra and dropped is not None:
            # `<animation>` and per-tile `<objectgroup>` collision shapes.
            # Named rather than silently skipped: the caller decides whether
            # losing them is acceptable for this conversion.
            dropped.extend("tileset/%s/tile[%s]/%s" % (name, tile.get("id", "?"), tag)
                           for tag in extra)
        tiles.append(TileEntry(
            _int_of(tile, "id", 0),
            tile.get("type") or tile.get("class") or "",
            _attributes_of(tile, _TILE_MODELLED),
            _properties_of(tile),
        ))

    if dropped is not None:
        for child in element:
            if child.tag not in ("image", "tile", "properties"):
                dropped.append("tileset/%s/%s" % (name, child.tag))

    return TilesetFile(
        name=name,
        image=image_source,
        image_width=image_width,
        image_height=image_height,
        tile_width=_int_of(element, "tilewidth", 0),
        tile_height=_int_of(element, "tileheight", 0),
        margin=_int_of(element, "margin", 0),
        spacing=_int_of(element, "spacing", 0),
        tile_count=_int_of(element, "tilecount", 0),
        columns=_int_of(element, "columns", 0),
        collision=collision,
        attributes=_attributes_of(element, _TILESET_MODELLED),
        properties=_properties_of(element),
        tiles=tuple(tiles),
    )


# ---------------------------------------------------------------------------
# Asset interning
#
# "if the tilemap is pointing at some file, we copy that into our asset
# management directory." The interesting half of that sentence is WHEN NOT TO
# -- an intern that overwrites is an intern that can destroy art -- so the
# decision is computed as a value first and executed second.
# ---------------------------------------------------------------------------

COPY = "copy"
KEEP = "keep"
MISSING = "missing"
OCCUPIED = "occupied"


@dataclass(frozen=True)
class InternPlan:
    """What interning one image WOULD do. Computing this touches nothing.

    Split from the copy for two reasons. The obvious one is testability: a
    check can exercise every branch with a fake `exists` and never go near
    the author's files. The load-bearing one is that three of the four
    outcomes are not copies -- an image already inside the managed directory
    must not be copied onto itself, a missing image must not create an empty
    file, and a DIFFERENT image already holding the destination name must
    stop the operation rather than overwrite it. Two tilesets in different
    folders both called `tiles.png` is not a hypothetical; it is what an art
    directory looks like.
    """

    source: str
    destination: str
    reference: str
    action: str
    reason: str = ""

    @property
    def copies(self) -> bool:
        return self.action == COPY

    @property
    def safe(self) -> bool:
        """May the tileset's reference be rewritten to `reference`?"""
        return self.action in (COPY, KEEP)

    def __repr__(self) -> str:
        return "InternPlan(%s %r -> %r)" % (self.action, self.source,
                                            self.reference)


def _posix(path: str) -> str:
    return path.replace("\\", "/")


def _same(left: str, right: str) -> bool:
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(
        os.path.normpath(right))


def resolve_image(tileset: TilesetFile, tileset_path: str) -> str:
    """Where a tileset's `image` reference points, absolutely.

    Relative to the .tileset FILE, never to the working directory. Same trap
    `MapDocument.__resolve_image` exists for, and the same answer.
    """
    if not tileset.image:
        return ""
    if os.path.isabs(tileset.image):
        return os.path.normpath(tileset.image)
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(tileset_path)),
                     tileset.image))


def _same_content(left: str, right: str) -> bool:
    """Byte comparison, treating unreadable as DIFFERENT.

    Unreadable-is-different is the safe direction: it produces `occupied`,
    which refuses, rather than `keep`, which would leave a tileset pointing
    at a file nobody verified.
    """
    try:
        return filecmp.cmp(left, right, shallow=False)
    except OSError:
        return False


def plan_intern(tileset: TilesetFile, *, tileset_path: str, managed_root: str,
                exists: Callable[[str], bool] = os.path.isfile,
                same_content: Callable[[str, str], bool] | None = None,
                name: str | None = None) -> InternPlan:
    """Decide what interning `tileset`'s image would do. Pure.

    Both filesystem probes are injected rather than assumed, so the whole
    decision table can be exercised without a filesystem and without going
    near the author's art. `name` overrides the destination file name for a
    caller that wants `TileA2.png` from two different folders to land as two
    different files rather than collide.

    The `keep` branch for an identical file is what makes interning
    IDEMPOTENT. Without it, running the importer twice would report a
    collision against the copy it made itself, and the obvious fix -- to
    overwrite -- is the one branch that can destroy art.
    """
    source = resolve_image(tileset, tileset_path)
    if not source:
        return InternPlan("", "", tileset.image, MISSING,
                          "tileset %r declares no image" % tileset.name)

    managed = os.path.abspath(managed_root)
    destination = os.path.join(managed, name or os.path.basename(source))
    reference = _posix(os.path.relpath(
        destination, os.path.dirname(os.path.abspath(tileset_path))))
    identical = same_content or _same_content

    if _same(source, destination):
        return InternPlan(source, destination, reference, KEEP,
                          "already inside the managed directory")
    if not exists(source):
        return InternPlan(source, destination, reference, MISSING,
                          "the image does not exist at %s" % source)
    if exists(destination):
        if identical(source, destination):
            return InternPlan(source, destination, reference, KEEP,
                              "an identical file is already interned")
        return InternPlan(
            source, destination, reference, OCCUPIED,
            "%s already holds a DIFFERENT file; interning would overwrite "
            "art that another tileset points at" % destination)
    return InternPlan(source, destination, reference, COPY,
                      "copy %s into the managed directory" % os.path.basename(source))


def interned(tileset: TilesetFile, plan: InternPlan) -> TilesetFile:
    """The tileset with its image reference rewritten. Pure; copies nothing.

    Refuses a plan that is not safe to act on, because the failure mode of
    rewriting anyway is a tileset pointing confidently at a file that is not
    there -- which loads, draws nothing, and raises nowhere.
    """
    if not plan.safe:
        raise PyoneerBlitFormatError(
            "will not rewrite tileset %r to %r: %s"
            % (tileset.name, plan.reference, plan.reason))
    return replace(tileset, image=plan.reference)


def apply_intern(plan: InternPlan) -> bool:
    """Execute a plan. Returns True if a file was actually copied.

    The only impure function in this module's intern path, and it does
    nothing a plan did not already say it would do.
    """
    if not plan.copies:
        return False
    directory = os.path.dirname(plan.destination)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    shutil.copy2(plan.source, plan.destination)
    return True
