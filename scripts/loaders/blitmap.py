"""The .blitmap file: this engine's own map format, and the tmx converter.

WHY STOP USING TILED'S FORMAT
-----------------------------
Nothing is wrong with .tmx as a file. What is wrong is depending on it, and
the dependency has three separate costs that only look like one:

  * **pytmx decides what a map means.** It RENUMBERS gids, so `layer.data`
    holds internal ids and `tmx.tiledgidmap` is mandatory to get back to what
    the file says. It RAISES on a custom property that shadows one of its
    attribute names -- `opacity`, `visible`, `offsetx`, `name`, `data`, `id`
    -- which is the entire reason every capability in
    `scripts/core/layer_profile.py` wears a `pyoneer_` prefix. It cannot read
    Wang sets at all, so the terrain the editor authors is invisible to it.
    It invents a layer named None for every per-tile collision shape. Each of
    those is a workaround this engine carries in production code.
  * **XML costs more than it returns.** `map_document.py` is 1,981 lines, and
    the large majority of them exist to reproduce punctuation: the original
    declaration byte for byte, CRLF, tabs on the first elements and spaces on
    the rest, `</data>` at column 0, no space before `/>`. That work is
    correct and necessary -- for a file Tiled also writes.
  * **A tileset is trapped inside whichever map embedded it.** Two maps using
    TileA2 carry two copies of its 768-tile declaration, and the copies drift.

So this format. It is not a better XML; it is a different trade.

THE TRADE, STATED PLAINLY
-------------------------
`map_document.py` PRESERVES punctuation because another program writes those
bytes. This format has exactly ONE writer, so it is CANONICAL instead: one
spelling per model, and byte-exactness stops being bookkeeping and becomes
two theorems that `tools/check_blitmap.py` asserts directly --

    parse(render(model)) == model       for every model
    render(parse(text))  == text        for every text render() can emit

DIFFABLE BY A HUMAN
-------------------
Line oriented, one tab per level of nesting, and the tile data is a grid the
shape of the map. A changed tile is a changed token on the line whose number
is its row -- so `git diff` points at a place on the map, not at an offset
into a base64 blob. That is the same reasoning `.blitmask` uses, and the two
formats are deliberately readable side by side.

CHEAP TO LOAD
-------------
No XML parser, no DOM, no gid renumbering, no second pass to undo the
renumbering. `str.splitlines`, `str.partition`, and `int()` per csv token.
Loading is one forward pass and the gids that come out are the gids in the
file -- `tiledgidmap` has nothing to be the inverse of.

VERSIONED
---------
The first line is `blitmap 1`. The magic word is the extension, exactly as
`.blitmask` already does (`blitmask 1`) and `.tileset` now does
(`tileset 1`), so `head -1` identifies any file in the family and a reader
built for version 1 refuses version 2 out loud instead of guessing.

WHAT IT CARRIES
---------------
Everything `data/maps/test.tmx` carries, which is the bar the converter is
measured against:

    blitmap 1
    size 100 100
    tilesize 16 16
    attr orientation orthogonal
    attr nextlayerid 10
    tileset 1 TileA2
    	source tilesets/TileA2.tileset
    group 7 Graphic
    	tiles 6 Paralax
    		size 100 100
    		prop string pyoneer_motion dynamic
    		prop float pyoneer_parallax_x 1.4
    		data
    			0,0,0,...
    	tiles 1 Floor
    		...
    group 8 Entity
    	objects 9 entity
    		object 14
    			name Hero
    			class spawn
    			at 64 96
    			prop int hp 20

FIRST-CLASS NAMES, AND THE `attr` PRESSURE VALVE
------------------------------------------------
The rule for what gets its own keyword is: **what the engine reads.** Map
size and tile size, layer nesting, gids, object placement, custom
properties -- those the renderer and the (still unbuilt) spawn path act on.
Tiled's `tiledversion`, `compressionlevel`, `locked`, `nextlayerid` are
bookkeeping we neither interpret nor are entitled to throw away, so they ride
along as `attr` lines, in document order, untouched.

That valve is what keeps the format from growing a field every time Tiled
grows one, and it is why the converter can claim fidelity for attributes it
has never heard of.

WHAT THE CONVERTER DOES NOT CARRY
---------------------------------
`Conversion.dropped` names every tmx element that did not survive, rather
than the converter warning or silently skipping. Today that is
`<editorsettings>` (Tiled's own export target -- editor state, not map
data), per-tile `<animation>` and per-tile `<objectgroup>` collision shapes
inside a tileset, and XML comments. A caller that cannot afford to lose one
of those can see it in the value rather than in a log.

Two normalizations are deliberate and are NOT losses of meaning, only of
punctuation: Tiled's pre-1.9 `type` and post-1.9 `class` on an object both
become `class`, and `x="64.0"` becomes `at 64` because a whole number is
written as one.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, ClassVar, Iterator, Union

from scripts.core.errors import PyoneerConfigError
from scripts.loaders.map_document import MapDocument
from scripts.loaders.map_document import TileLayer as TmxTileLayer
from scripts.loaders.tileset_file import (  # the shared line grammar
    BLITMAP_SUFFIX,
    TILESET_SUFFIX,
    Cursor,
    Line,
    Property,
    PyoneerBlitFormatError,
    TilesetFile,
    _attributes_of,
    _properties_of,
    escape_text,
    escape_word,
    from_tmx_tileset,
    lex,
    number_text,
    once,
    read_attribute,
    read_magic,
    render_attributes,
    render_properties,
    tail,
    unescape,
)

MAGIC = "blitmap"
VERSION = 1
_INDENT = "\t"

__all__ = [
    "MAGIC", "VERSION", "BLITMAP_SUFFIX", "TILESET_SUFFIX",
    "PyoneerBlitFormatError", "Property", "TilesetFile",
    "Shape", "BlitObject", "TileLayer", "ObjectLayer", "ImageLayer",
    "LayerGroup", "TilesetLink", "Blitmap", "Conversion",
    "from_tmx", "write_conversion",
]


# ---------------------------------------------------------------------------
# Objects
# ---------------------------------------------------------------------------

_SHAPE_KINDS = ("point", "ellipse", "polygon", "polyline", "text")


@dataclass(frozen=True)
class Shape:
    """An object's geometry, when it is not a plain rectangle.

    One optional value rather than five booleans, because a tmx object has
    at most one shape child and modelling that as independent flags invents
    states the source format cannot express.
    """

    kind: str
    points: tuple[tuple[float, float], ...] = ()
    text: str = ""
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in _SHAPE_KINDS:
            raise PyoneerBlitFormatError(
                "%r is not a shape; expected one of %s"
                % (self.kind, ", ".join(_SHAPE_KINDS)))
        if self.points and self.kind not in ("polygon", "polyline"):
            raise PyoneerBlitFormatError(
                "a %s shape carries no points" % self.kind)

    def render(self, depth: int = 0) -> list[str]:
        pad = _INDENT * depth
        if self.kind in ("polygon", "polyline"):
            drawn = " ".join("%s,%s" % (number_text(x), number_text(y))
                             for x, y in self.points)
            return ["%s%s %s" % (pad, self.kind, drawn) if drawn
                    else "%s%s" % (pad, self.kind)]
        if self.kind == "text":
            lines = ["%stext%s" % (pad, tail(escape_text(self.text)))]
            lines += ["%stextattr %s%s" % (pad, escape_word(key),
                                           tail(escape_text(value)))
                      for key, value in self.attributes]
            return lines
        return ["%s%s" % (pad, self.kind)]


# Object attributes the format names. Everything else on a tmx <object>
# falls through to `attr` and survives verbatim.
_OBJECT_MODELLED = ("id", "name", "type", "class", "gid", "x", "y",
                    "width", "height", "rotation", "visible")


@dataclass(frozen=True)
class BlitObject:
    """One placed object: where it is, what it is, and what it declares."""

    id: int
    x: float = 0.0
    y: float = 0.0
    name: str = ""
    type: str = ""
    width: float = 0.0
    height: float = 0.0
    gid: int = 0
    rotation: float = 0.0
    visible: bool = True
    shape: Shape | None = None
    attributes: tuple[tuple[str, str], ...] = ()
    properties: tuple[Property, ...] = ()

    def __post_init__(self) -> None:
        if self.id < 0:
            raise PyoneerBlitFormatError("object id %d is negative" % self.id)
        if self.gid < 0:
            raise PyoneerBlitFormatError(
                "object %d has gid %d; tmx gids are unsigned" % (self.id, self.gid))

    def render(self, depth: int = 0) -> list[str]:
        pad = _INDENT * depth
        inner = _INDENT * (depth + 1)
        lines = ["%sobject %d" % (pad, self.id)]
        if self.name:
            lines.append("%sname %s" % (inner, escape_text(self.name)))
        if self.type:
            lines.append("%sclass %s" % (inner, escape_text(self.type)))
        lines.append("%sat %s %s" % (inner, number_text(self.x),
                                     number_text(self.y)))
        if self.width or self.height:
            lines.append("%ssize %s %s" % (inner, number_text(self.width),
                                           number_text(self.height)))
        if self.gid:
            lines.append("%sgid %d" % (inner, self.gid))
        if self.rotation:
            lines.append("%srotation %s" % (inner, number_text(self.rotation)))
        if not self.visible:
            lines.append("%shidden" % inner)
        lines += render_attributes(self.attributes, depth + 1)
        if self.shape is not None:
            lines += self.shape.render(depth + 1)
        lines += render_properties(self.properties, depth + 1)
        return lines


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TileLayer:
    """A grid of gids, rendered as the grid it is.

    `gids` holds FILE gids -- what the tileset ranges say, flip flags and
    all. Not pytmx's internal ids: those are an artefact of pytmx's own
    loading and require `tiledgidmap` to invert, which is a second table
    that can only ever be wrong.
    """

    id: int
    name: str
    width: int
    height: int
    gids: tuple[int, ...] = ()
    attributes: tuple[tuple[str, str], ...] = ()
    properties: tuple[Property, ...] = ()

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise PyoneerBlitFormatError(
                "tile layer %r is %dx%d; a layer is at least 1x1"
                % (self.name, self.width, self.height))
        if len(self.gids) != self.width * self.height:
            raise PyoneerBlitFormatError(
                "tile layer %r declares %dx%d (%d cells) but carries %d"
                % (self.name, self.width, self.height,
                   self.width * self.height, len(self.gids)))
        negative = [g for g in self.gids if g < 0]
        if negative:
            # The same trap `TileLayer._require_gid` guards in the tmx
            # writer: a negative gid is not an error anywhere downstream, it
            # is a plausible wrong tile.
            raise PyoneerBlitFormatError(
                "tile layer %r holds negative gids %s; tmx gids are unsigned "
                "(0 means empty)" % (self.name, sorted(set(negative))[:4]))

    def at(self, x: int, y: int) -> int:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.gids[y * self.width + x]
        return 0

    def row(self, y: int) -> tuple[int, ...]:
        return self.gids[y * self.width:(y + 1) * self.width]

    def rows(self) -> list[tuple[int, ...]]:
        return [self.row(y) for y in range(self.height)]

    def render(self, depth: int = 0) -> list[str]:
        pad = _INDENT * depth
        inner = _INDENT * (depth + 1)
        lines = ["%stiles %d %s" % (pad, self.id, escape_text(self.name)),
                 "%ssize %d %d" % (inner, self.width, self.height)]
        lines += render_attributes(self.attributes, depth + 1)
        lines += render_properties(self.properties, depth + 1)
        lines.append("%sdata" % inner)
        rows = _INDENT * (depth + 2)
        for y in range(self.height):
            lines.append(rows + ",".join(str(g) for g in self.row(y)))
        return lines


@dataclass(frozen=True)
class ObjectLayer:
    """An object group: placements, not pixels."""

    id: int
    name: str
    objects: tuple[BlitObject, ...] = ()
    attributes: tuple[tuple[str, str], ...] = ()
    properties: tuple[Property, ...] = ()

    def find(self, object_id: int) -> BlitObject | None:
        for item in self.objects:
            if item.id == object_id:
                return item
        return None

    def render(self, depth: int = 0) -> list[str]:
        lines = ["%sobjects %d %s" % (_INDENT * depth, self.id,
                                      escape_text(self.name))]
        lines += render_attributes(self.attributes, depth + 1)
        lines += render_properties(self.properties, depth + 1)
        for item in self.objects:
            lines += item.render(depth + 1)
        return lines


@dataclass(frozen=True)
class ImageLayer:
    """A single image placed as a layer. Carried, not yet rendered anywhere.

    Present because `_LAYER_TAGS` in the tmx reader includes `imagelayer`,
    so a map can legally contain one, and a converter that silently dropped
    it would make "every layer survives" a false claim rather than a
    measured one.
    """

    id: int
    name: str
    source: str = ""
    attributes: tuple[tuple[str, str], ...] = ()
    properties: tuple[Property, ...] = ()

    def render(self, depth: int = 0) -> list[str]:
        lines = ["%simage %d %s" % (_INDENT * depth, self.id,
                                    escape_text(self.name))]
        if self.source:
            lines.append("%ssource %s" % (_INDENT * (depth + 1),
                                          escape_text(self.source)))
        lines += render_attributes(self.attributes, depth + 1)
        lines += render_properties(self.properties, depth + 1)
        return lines


@dataclass(frozen=True)
class LayerGroup:
    """A `<group>`: how this project's maps are actually organized.

    Nesting is carried rather than flattened because the group IS the
    authored structure -- test.tmx's "Graphic" wraps six tile layers and
    "Entity" wraps the object group -- and a flattened map cannot be edited
    back into the shape its author left it in.
    """

    id: int
    name: str
    layers: tuple["Layer", ...] = ()
    attributes: tuple[tuple[str, str], ...] = ()
    properties: tuple[Property, ...] = ()

    def render(self, depth: int = 0) -> list[str]:
        lines = ["%sgroup %d %s" % (_INDENT * depth, self.id,
                                    escape_text(self.name))]
        lines += render_attributes(self.attributes, depth + 1)
        lines += render_properties(self.properties, depth + 1)
        for layer in self.layers:
            lines += layer.render(depth + 1)
        return lines


Layer = Union[TileLayer, ObjectLayer, ImageLayer, LayerGroup]


@dataclass(frozen=True)
class TilesetLink:
    """Where a gid range comes from: a firstgid and a .tileset file.

    A LINK, never an embedded copy. That is the point of splitting the
    formats -- see `tileset_file.TilesetFile` for why one tileset is one
    file -- and it means a map diff never contains a 768-tile declaration
    that nobody edited.
    """

    first_gid: int
    name: str
    source: str = ""

    def __post_init__(self) -> None:
        if self.first_gid < 1:
            raise PyoneerBlitFormatError(
                "tileset %r has firstgid %d; gid 0 means 'no tile', so a "
                "firstgid starts at 1" % (self.name, self.first_gid))
        if not self.name:
            raise PyoneerBlitFormatError("a tileset link needs a name")

    def render(self, depth: int = 0) -> list[str]:
        lines = ["%stileset %d %s" % (_INDENT * depth, self.first_gid,
                                      escape_text(self.name))]
        if self.source:
            lines.append("%ssource %s" % (_INDENT * (depth + 1),
                                          escape_text(self.source)))
        return lines


# ---------------------------------------------------------------------------
# The map
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Blitmap:
    """A whole map, as a value.

    Frozen all the way down, for the reason every model in this project is:
    a command's inverse must be built from STORED STATE rather than rebuilt
    from attributes, and a frozen tree IS the stored state -- there is
    nothing to copy defensively and nothing that can change underneath a
    saved reference. `map.object.remove` destroying polygons is the
    documented bug that rule exists to prevent.
    """

    width: int
    height: int
    tile_width: int
    tile_height: int
    tilesets: tuple[TilesetLink, ...] = ()
    layers: tuple[Any, ...] = ()
    attributes: tuple[tuple[str, str], ...] = ()
    properties: tuple[Property, ...] = ()

    MAGIC: ClassVar[str] = MAGIC
    VERSION: ClassVar[int] = VERSION

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise PyoneerBlitFormatError(
                "a map is at least 1x1, got %dx%d" % (self.width, self.height))
        if self.tile_width <= 0 or self.tile_height <= 0:
            raise PyoneerBlitFormatError(
                "a map needs a positive tile size, got %dx%d"
                % (self.tile_width, self.tile_height))
        gids = [link.first_gid for link in self.tilesets]
        if len(set(gids)) != len(gids):
            raise PyoneerBlitFormatError(
                "two tilesets share a firstgid (%s); a gid would resolve to "
                "both" % sorted(gids))

    # -- traversal ---------------------------------------------------------
    def walk(self) -> Iterator[tuple[tuple[str, ...], Any]]:
        """Every layer, depth first, with the group path that reaches it."""
        def descend(layers, path):
            for layer in layers:
                here = path + (layer.name,)
                yield here, layer
                if isinstance(layer, LayerGroup):
                    yield from descend(layer.layers, here)
        yield from descend(self.layers, ())

    def layer_names(self) -> list[str]:
        """Every layer and group name, in document order.

        Groups included, same as `MapDocument.layer_names`, because in this
        project the groups ARE the organization and a caller listing layers
        needs to see them.
        """
        return [layer.name for _path, layer in self.walk()]

    def tile_layers(self) -> list[TileLayer]:
        return [layer for _p, layer in self.walk() if isinstance(layer, TileLayer)]

    def object_layers(self) -> list[ObjectLayer]:
        return [layer for _p, layer in self.walk() if isinstance(layer, ObjectLayer)]

    def layer(self, name: str) -> Any:
        for _path, found in self.walk():
            if found.name == name:
                return found
        raise PyoneerBlitFormatError(
            "no layer named %r; this map has %s" % (name, self.layer_names()))

    def tileset_for_gid(self, gid: int) -> TilesetLink | None:
        """Which tileset owns a gid: the highest firstgid at or below it.

        The same rule pytmx uses, restated here so the two agree -- and with
        the flip flags masked off first, because a horizontally flipped tile
        carries 0x80000000 and would otherwise match nothing at all.
        """
        bare = gid & 0x1FFFFFFF
        if bare <= 0:
            return None
        best: TilesetLink | None = None
        for link in self.tilesets:
            if link.first_gid <= bare and (best is None
                                           or link.first_gid > best.first_gid):
                best = link
        return best

    # -- text --------------------------------------------------------------
    def render(self) -> str:
        """The file, as a string. Always ends in a newline."""
        lines = ["%s %d" % (MAGIC, VERSION),
                 "size %d %d" % (self.width, self.height),
                 "tilesize %d %d" % (self.tile_width, self.tile_height)]
        lines += render_attributes(self.attributes, 0)
        lines += render_properties(self.properties, 0)
        for link in self.tilesets:
            lines += link.render(0)
        for layer in self.layers:
            lines += layer.render(0)
        return "\n".join(lines) + "\n"

    @classmethod
    def parse(cls, text: str, *, path: str | None = None) -> "Blitmap":
        cursor = Cursor(lex(text, path=path), path)
        read_magic(cursor, MAGIC, VERSION)
        size: tuple[int, int] | None = None
        tile_size: tuple[int, int] | None = None
        attributes: list[tuple[str, str]] = []
        properties: list[Property] = []
        tilesets: list[TilesetLink] = []
        layers: list[Any] = []
        seen: set[str] = set()
        for line in cursor.block(0):
            keyword = line.keyword
            if keyword == "size":
                once(seen, line, cursor)
                width, height = line.ints(2, path=path)
                size = (width, height)
            elif keyword == "tilesize":
                once(seen, line, cursor)
                tile_width, tile_height = line.ints(2, path=path)
                tile_size = (tile_width, tile_height)
            elif keyword == "attr":
                attributes.append(read_attribute(line, cursor))
            elif keyword == "prop":
                properties.append(Property.read(line, cursor))
            elif keyword == "tileset":
                tilesets.append(_read_tileset_link(line, cursor, path))
            elif keyword in _LAYER_KEYWORDS:
                layers.append(_read_layer(line, cursor, path))
            else:
                raise cursor.fail("unknown keyword %r at map level" % keyword,
                                  line)
        if size is None:
            raise PyoneerBlitFormatError("no size line", path=path)
        if tile_size is None:
            raise PyoneerBlitFormatError("no tilesize line", path=path)
        return cls(size[0], size[1], tile_size[0], tile_size[1],
                   tuple(tilesets), tuple(layers), tuple(attributes),
                   tuple(properties))

    # -- disk --------------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "Blitmap":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.parse(handle.read(), path=path)

    def save(self, path: str) -> str:
        """Write it. newline='' so the bytes are the bytes on every platform."""
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
        return "Blitmap(%dx%d, tiles %dx%d, layers=%r)" % (
            self.width, self.height, self.tile_width, self.tile_height,
            self.layer_names())


# ---------------------------------------------------------------------------
# Reading blocks
# ---------------------------------------------------------------------------

_LAYER_KEYWORDS = ("tiles", "objects", "image", "group")


def _split_id_and_name(line: Line, cursor: Cursor) -> tuple[int, str]:
    """`<keyword> <id> <name>`: the id is a number, the name is the rest.

    In that order because a name may contain spaces and an id may not, so
    only "number first" parses without escaping the common case.
    """
    head, _, tail = line.rest.partition(" ")
    try:
        identifier = int(head)
    except ValueError:
        raise cursor.fail(
            "%s wants a numeric id then a name, got %r"
            % (line.keyword, line.rest), line) from None
    return identifier, unescape(tail, line=line.number, path=cursor.path)


def _read_tileset_link(header: Line, cursor: Cursor,
                       path: str | None) -> TilesetLink:
    first_gid, name = _split_id_and_name(header, cursor)
    source = ""
    seen: set[str] = set()
    for line in cursor.block(header.depth + 1):
        if line.keyword == "source":
            once(seen, line, cursor)
            source = line.text(path=path)
        else:
            raise cursor.fail("unknown keyword %r inside a tileset link"
                              % line.keyword, line)
    return TilesetLink(first_gid, name, source)


def _read_layer(header: Line, cursor: Cursor, path: str | None) -> Any:
    if header.keyword == "tiles":
        return _read_tile_layer(header, cursor, path)
    if header.keyword == "objects":
        return _read_object_layer(header, cursor, path)
    if header.keyword == "image":
        return _read_image_layer(header, cursor, path)
    return _read_group(header, cursor, path)


def _read_tile_layer(header: Line, cursor: Cursor,
                     path: str | None) -> TileLayer:
    layer_id, name = _split_id_and_name(header, cursor)
    size: tuple[int, int] | None = None
    attributes: list[tuple[str, str]] = []
    properties: list[Property] = []
    gids: list[int] | None = None
    seen: set[str] = set()
    for line in cursor.block(header.depth + 1):
        if line.keyword == "size":
            once(seen, line, cursor)
            width, height = line.ints(2, path=path)
            size = (width, height)
        elif line.keyword == "attr":
            attributes.append(read_attribute(line, cursor))
        elif line.keyword == "prop":
            properties.append(Property.read(line, cursor))
        elif line.keyword == "data":
            once(seen, line, cursor)
            if line.rest:
                raise cursor.fail("data takes no argument; the rows follow it "
                                  "indented one level", line)
            gids = _read_data(line, cursor, path)
        else:
            raise cursor.fail("unknown keyword %r inside a tile layer"
                              % line.keyword, line)
    if size is None:
        raise cursor.fail("tile layer %r has no size line" % name, header)
    if gids is None:
        raise cursor.fail("tile layer %r has no data block" % name, header)
    return TileLayer(layer_id, name, size[0], size[1], tuple(gids),
                     tuple(attributes), tuple(properties))


def _read_data(header: Line, cursor: Cursor, path: str | None) -> list[int]:
    """The csv rows under a `data` line.

    Spaces around a token are accepted although `render` never emits them:
    somebody hand-aligning a column of a map is doing the thing this format
    exists to allow, and it costs one `strip()` to let them.
    """
    gids: list[int] = []
    for line in cursor.block(header.depth + 1):
        raw = line.keyword if not line.rest else line.keyword + " " + line.rest
        for token in raw.split(","):
            token = token.strip()
            if not token:
                raise cursor.fail("empty csv cell in %r" % raw, line)
            try:
                gids.append(int(token))
            except ValueError:
                raise cursor.fail("csv cell %r is not an integer" % token,
                                  line) from None
    return gids


def _read_object_layer(header: Line, cursor: Cursor,
                       path: str | None) -> ObjectLayer:
    layer_id, name = _split_id_and_name(header, cursor)
    attributes: list[tuple[str, str]] = []
    properties: list[Property] = []
    objects: list[BlitObject] = []
    for line in cursor.block(header.depth + 1):
        if line.keyword == "attr":
            attributes.append(read_attribute(line, cursor))
        elif line.keyword == "prop":
            properties.append(Property.read(line, cursor))
        elif line.keyword == "object":
            objects.append(_read_object(line, cursor, path))
        else:
            raise cursor.fail("unknown keyword %r inside an object layer"
                              % line.keyword, line)
    return ObjectLayer(layer_id, name, tuple(objects), tuple(attributes),
                       tuple(properties))


def _read_object(header: Line, cursor: Cursor, path: str | None) -> BlitObject:
    object_id = header.ints(1, path=path)[0]
    values: dict[str, Any] = {"id": object_id}
    attributes: list[tuple[str, str]] = []
    properties: list[Property] = []
    shape: Shape | None = None
    text_attributes: list[tuple[str, str]] = []
    seen: set[str] = set()

    def claim_shape(candidate: Shape, line: Line) -> Shape:
        if shape is not None:
            raise cursor.fail(
                "object %d declares two shapes (%s and %s); a tmx object has "
                "at most one" % (object_id, shape.kind, candidate.kind), line)
        return candidate

    for line in cursor.block(header.depth + 1):
        keyword = line.keyword
        if keyword == "name":
            once(seen, line, cursor)
            values["name"] = line.text(path=path)
        elif keyword == "class":
            once(seen, line, cursor)
            values["type"] = line.text(path=path)
        elif keyword == "at":
            once(seen, line, cursor)
            values["x"], values["y"] = _floats(line, 2, cursor)
        elif keyword == "size":
            once(seen, line, cursor)
            values["width"], values["height"] = _floats(line, 2, cursor)
        elif keyword == "gid":
            once(seen, line, cursor)
            values["gid"] = line.ints(1, path=path)[0]
        elif keyword == "rotation":
            once(seen, line, cursor)
            values["rotation"] = _floats(line, 1, cursor)[0]
        elif keyword == "hidden":
            once(seen, line, cursor)
            values["visible"] = False
        elif keyword == "attr":
            attributes.append(read_attribute(line, cursor))
        elif keyword == "prop":
            properties.append(Property.read(line, cursor))
        elif keyword in ("point", "ellipse"):
            shape = claim_shape(Shape(keyword), line)
        elif keyword in ("polygon", "polyline"):
            shape = claim_shape(Shape(keyword, _read_points(line, cursor)), line)
        elif keyword == "text":
            shape = claim_shape(Shape("text", text=line.text(path=path)), line)
        elif keyword == "textattr":
            text_attributes.append(read_attribute(line, cursor))
        else:
            raise cursor.fail("unknown keyword %r inside an object" % keyword,
                              line)

    if text_attributes:
        if shape is None or shape.kind != "text":
            raise cursor.fail(
                "object %d has textattr lines but no text line" % object_id,
                header)
        shape = Shape("text", text=shape.text, attributes=tuple(text_attributes))
    if "x" not in values:
        raise cursor.fail("object %d has no `at` line" % object_id, header)
    return BlitObject(shape=shape, attributes=tuple(attributes),
                      properties=tuple(properties), **values)


def _floats(line: Line, count: int, cursor: Cursor) -> list[float]:
    parts = line.rest.split()
    if len(parts) != count:
        raise cursor.fail("%s wants %d number(s), got %r"
                          % (line.keyword, count, line.rest), line)
    try:
        return [float(part) for part in parts]
    except ValueError:
        raise cursor.fail("%s wants numbers, got %r"
                          % (line.keyword, line.rest), line) from None


def _read_points(line: Line, cursor: Cursor) -> tuple[tuple[float, float], ...]:
    points: list[tuple[float, float]] = []
    for pair in line.rest.split():
        parts = pair.split(",")
        if len(parts) != 2:
            raise cursor.fail("%r is not an x,y point" % pair, line)
        try:
            points.append((float(parts[0]), float(parts[1])))
        except ValueError:
            raise cursor.fail("%r is not an x,y point" % pair, line) from None
    return tuple(points)


def _read_image_layer(header: Line, cursor: Cursor,
                      path: str | None) -> ImageLayer:
    layer_id, name = _split_id_and_name(header, cursor)
    source = ""
    attributes: list[tuple[str, str]] = []
    properties: list[Property] = []
    seen: set[str] = set()
    for line in cursor.block(header.depth + 1):
        if line.keyword == "source":
            once(seen, line, cursor)
            source = line.text(path=path)
        elif line.keyword == "attr":
            attributes.append(read_attribute(line, cursor))
        elif line.keyword == "prop":
            properties.append(Property.read(line, cursor))
        else:
            raise cursor.fail("unknown keyword %r inside an image layer"
                              % line.keyword, line)
    return ImageLayer(layer_id, name, source, tuple(attributes),
                      tuple(properties))


def _read_group(header: Line, cursor: Cursor, path: str | None) -> LayerGroup:
    group_id, name = _split_id_and_name(header, cursor)
    attributes: list[tuple[str, str]] = []
    properties: list[Property] = []
    layers: list[Any] = []
    for line in cursor.block(header.depth + 1):
        if line.keyword == "attr":
            attributes.append(read_attribute(line, cursor))
        elif line.keyword == "prop":
            properties.append(Property.read(line, cursor))
        elif line.keyword in _LAYER_KEYWORDS:
            layers.append(_read_layer(line, cursor, path))
        else:
            raise cursor.fail("unknown keyword %r inside a group"
                              % line.keyword, line)
    return LayerGroup(group_id, name, tuple(layers), tuple(attributes),
                      tuple(properties))


# ---------------------------------------------------------------------------
# tmx -> blitmap
# ---------------------------------------------------------------------------

_MAP_MODELLED = ("width", "height", "tilewidth", "tileheight")
_LAYER_MODELLED = ("id", "name", "width", "height")
_TMX_LAYER_TAGS = ("layer", "objectgroup", "imagelayer", "group")


@dataclass(frozen=True)
class Conversion:
    """The result of converting one .tmx: the map, its tilesets, the losses.

    `dropped` is a value rather than a warning on purpose. A warning is read
    by whoever happens to be watching stderr; a field is read by the caller
    that has to decide whether this conversion is acceptable, and by the
    check that asserts what the converter does and does not carry.
    """

    blitmap: Blitmap
    tilesets: tuple[TilesetFile, ...] = ()
    dropped: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.dropped

    def tileset(self, name: str) -> TilesetFile:
        for found in self.tilesets:
            if found.name == name:
                return found
        raise PyoneerBlitFormatError(
            "no tileset named %r; this conversion produced %s"
            % (name, [t.name for t in self.tilesets]))

    def __repr__(self) -> str:
        return "Conversion(%r, tilesets=%r, dropped=%d)" % (
            self.blitmap, [t.name for t in self.tilesets], len(self.dropped))


def _int_attribute(element, key: str, default: int = 0) -> int:
    raw = element.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _float_attribute(element, key: str, default: float = 0.0) -> float:
    raw = element.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _object_from_tmx(element, dropped: list[str], where: str) -> BlitObject:
    shape: Shape | None = None
    for child in element:
        tag = child.tag
        if not isinstance(tag, str) or tag == "properties":
            continue
        if tag in ("point", "ellipse"):
            shape = Shape(tag)
        elif tag in ("polygon", "polyline"):
            points = []
            for pair in (child.get("points") or "").split():
                parts = pair.split(",")
                if len(parts) == 2:
                    points.append((float(parts[0]), float(parts[1])))
            shape = Shape(tag, tuple(points))
        elif tag == "text":
            shape = Shape("text", text=child.text or "",
                          attributes=tuple(child.attrib.items()))
        else:
            dropped.append("%s/object[%s]/%s" % (where, element.get("id", "?"), tag))
    return BlitObject(
        id=_int_attribute(element, "id", 0),
        x=_float_attribute(element, "x", 0.0),
        y=_float_attribute(element, "y", 0.0),
        name=element.get("name", ""),
        # Tiled renamed `type` to `class` in 1.9. One field, one spelling on
        # the way out: the meaning is identical and carrying both would make
        # every reader ask which one won.
        type=element.get("type") or element.get("class") or "",
        width=_float_attribute(element, "width", 0.0),
        height=_float_attribute(element, "height", 0.0),
        gid=_int_attribute(element, "gid", 0),
        rotation=_float_attribute(element, "rotation", 0.0),
        visible=element.get("visible", "1") != "0",
        shape=shape,
        attributes=_attributes_of(element, _OBJECT_MODELLED),
        properties=_properties_of(element),
    )


def _layer_from_tmx(document: MapDocument, element, dropped: list[str]) -> Any:
    tag = element.tag
    name = element.get("name", "")
    layer_id = _int_attribute(element, "id", 0)

    if tag == "layer":
        # Built through the tmx reader's own TileLayer rather than by
        # re-splitting the csv here: it is where the "encoding must be csv"
        # and "not a chunked infinite map" guards already live, and a second
        # csv reader is a second place for them to be missing.
        wrapper = TmxTileLayer(document, element)
        return TileLayer(layer_id, name, wrapper.width, wrapper.height,
                         tuple(wrapper.gids()),
                         _attributes_of(element, _LAYER_MODELLED),
                         _properties_of(element))

    if tag == "objectgroup":
        objects = tuple(_object_from_tmx(child, dropped, name)
                        for child in element.findall("object"))
        for child in element:
            if isinstance(child.tag, str) and child.tag not in ("object", "properties"):
                dropped.append("%s/%s" % (name, child.tag))
        return ObjectLayer(layer_id, name, objects,
                           _attributes_of(element, _LAYER_MODELLED),
                           _properties_of(element))

    if tag == "imagelayer":
        image = element.find("image")
        for child in element:
            if isinstance(child.tag, str) and child.tag not in ("image", "properties"):
                dropped.append("%s/%s" % (name, child.tag))
        return ImageLayer(layer_id, name,
                          "" if image is None else image.get("source", ""),
                          _attributes_of(element, _LAYER_MODELLED),
                          _properties_of(element))

    layers: list[Any] = []
    for child in element:
        child_tag = child.tag
        if not isinstance(child_tag, str):
            dropped.append("%s/<comment>" % name)
        elif child_tag in _TMX_LAYER_TAGS:
            layers.append(_layer_from_tmx(document, child, dropped))
        elif child_tag != "properties":
            dropped.append("%s/%s" % (name, child_tag))
    return LayerGroup(layer_id, name, tuple(layers),
                      _attributes_of(element, _LAYER_MODELLED),
                      _properties_of(element))


def tileset_reference(name: str, directory: str = "tilesets") -> str:
    """Where a tileset's own file sits, relative to the .blitmap.

    Path separators in a tileset NAME are replaced rather than honoured: a
    tileset called `System/TileA2` must not be able to write outside the
    directory it was told to write into.
    """
    safe = name.replace("/", "_").replace("\\", "_")
    reference = safe + TILESET_SUFFIX
    return "%s/%s" % (directory.rstrip("/"), reference) if directory else reference


def from_tmx(document: MapDocument, *, tileset_dir: str = "tilesets",
             collision_for=None) -> Conversion:
    """Convert a loaded .tmx into a .blitmap plus one .tileset per tileset.

    No pytmx. The source is `MapDocument`, which reads the FILE's gids
    rather than pytmx's renumbered internal ones, so no `tiledgidmap`
    inversion is needed and no property can make the load fail by shadowing
    a reader's attribute name.

    `collision_for(tileset_name) -> str` supplies each tileset's `.blitmask`
    reference, if the caller has one. Injected rather than discovered
    because the mask lives beside the ART, which is a directory this module
    has no business guessing at -- and because `scripts/` may never import
    the editor code that reads the mask.
    """
    dropped: list[str] = []
    tilesets: list[TilesetLink] = []
    files: list[TilesetFile] = []
    layers: list[Any] = []

    for child in document.root:
        tag = child.tag
        if not isinstance(tag, str):
            dropped.append("<comment>")
            continue
        if tag == "properties":
            continue                      # read from the root below
        if tag == "tileset":
            collision = "" if collision_for is None else (
                collision_for(child.get("name", "")) or "")
            built = from_tmx_tileset(child, dropped=dropped, collision=collision)
            first_gid = _int_attribute(child, "firstgid", 1)
            tilesets.append(TilesetLink(first_gid, built.name,
                                        tileset_reference(built.name, tileset_dir)))
            files.append(built)
        elif tag in _TMX_LAYER_TAGS:
            layers.append(_layer_from_tmx(document, child, dropped))
        else:
            # `<editorsettings>` lands here: Tiled's export target is editor
            # state, not map data, and this format has no editor to hold it.
            dropped.append(tag)

    blitmap = Blitmap(
        width=document.width,
        height=document.height,
        tile_width=document.tile_width,
        tile_height=document.tile_height,
        tilesets=tuple(tilesets),
        layers=tuple(layers),
        attributes=_attributes_of(document.root, _MAP_MODELLED),
        properties=_properties_of(document.root),
    )
    return Conversion(blitmap, tuple(files), tuple(dropped))


def convert_file(tmx_path: str, *, tileset_dir: str = "tilesets",
                 collision_for=None) -> Conversion:
    """Load a .tmx from disk and convert it. Writes nothing."""
    return from_tmx(MapDocument.load(tmx_path), tileset_dir=tileset_dir,
                    collision_for=collision_for)


def write_conversion(conversion: Conversion, blitmap_path: str) -> list[str]:
    """Write the .blitmap and every .tileset it links. Returns the paths.

    Each tileset lands where the map's own link SAYS it does, resolved
    relative to the .blitmap -- so the file that gets written and the
    reference that points at it cannot disagree.
    """
    written = [conversion.blitmap.save(blitmap_path)]
    base = os.path.dirname(os.path.abspath(blitmap_path))
    by_name = {link.name: link for link in conversion.blitmap.tilesets}
    for tileset in conversion.tilesets:
        link = by_name.get(tileset.name)
        if link is None or not link.source:
            raise PyoneerConfigError(
                "tileset %r has no link in the map it was converted with, so "
                "there is nowhere to write it" % tileset.name,
                source=blitmap_path)
        written.append(tileset.save(os.path.join(base, link.source)))
    return written
