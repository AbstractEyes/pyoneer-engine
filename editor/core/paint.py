"""Tile painting -- what a drag on the canvas means, as pure logic.

No Qt, no pygame, no document. Every function here takes plain numbers and
a `read(x, y) -> gid` callable and returns a list of `(x, y, gid)` edits, so
flood fill, rectangle and stamp placement are testable without a window.

ONE STROKE IS ONE UNDO STEP
---------------------------
A stroke accumulates here and commits as a single `map.tile.set_many`, which
is both the correct undo granularity and much cheaper than one command per
cell: the tmx csv payload is re-rendered once per transaction.

STAMPS
------
A brush is a 1x1 stamp. Selecting a rectangle in the tile palette gives a
larger one, and every tool honours it: a rectangle tool with a 2x2 stamp
tiles that pattern across the rectangle. Special-casing the single tile
would mean two code paths that drift.

A SIZE IS NOT A PATTERN, AND A GRID IS NOT A BRUSH
--------------------------------------------------
How big the grid is, what a click snaps to and how much one press paints are
three separate quantities here. That separation rests on two measurements:

  * A brush FOOTPRINT is real for `Tool.BRUSH` and `Tool.ERASER` and
    provably inert for `RECTANGLE`, `FILLED_RECT` and `FILL`. Those three
    go through `Stroke.__cover`, which reads the stamp as a repeating
    PATTERN keyed on map coordinates, so a uniform NxN tiles to itself and
    produces BIT-IDENTICAL edits to a 1x1. Hence `Tool.uses_size` -- a
    control that silently does nothing for three of seven tools is worse
    than no control. It is deliberately NOT `uses_stamp`, which is False
    for terrain and terrain does take a size.
  * Growing a picked PATTERN into a footprint disagrees with `__cover`'s
    map-aligned phase in every cell, so the same 4x4 patch could be
    authored two ways and come out different. `footprint()` therefore
    grows only a SINGLE stamp, into a uniform block that has no phase, and
    hands a picked pattern back untouched.

`grid_lines` is the other half. The grid may draw a SUBSET of the real cell
boundaries and never a superset: a line the author can see but no click can
land on is a lie the code would have to keep telling.

WHAT A STROKE IS GENERIC OVER
-----------------------------
`gid` is a name, not a type. Everything here moves small non-negative
integers around and never asks what one means, which is why collision
authoring reuses this module wholesale rather than growing a second stroke
machinery: a passability mask stored in a companion layer IS a gid --
`first_gid + mask` -- so a mask brush is `Stamp.single(gid)`, an eraser
writing 0 is the empty cell that means "no opinion", and one drag is still
one `map.tile.set_many`. `EditMode` below is the whole difference.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, Iterator

# A reader is anything that can answer "what gid is at this cell". The
# document, a test fixture, a preview overlay -- all the same to this module.
Reader = Callable[[int, int], int]

# One edit. Deliberately a plain tuple: it is what map.tile.set_many wants.
Edit = tuple[int, int, int]


class Tool(Enum):
    BRUSH = "brush"
    RECTANGLE = "rectangle"
    FILLED_RECT = "filled_rect"
    FILL = "fill"
    ERASER = "eraser"
    PICKER = "picker"
    # Terrain is a different model entirely -- it paints a CORNER lattice and
    # re-tiles the cells around it, so it does not go through Stroke. See
    # `editor/core/autotile.py`; the canvas routes it separately.
    AUTOTILE = "autotile"

    @property
    def label(self) -> str:
        return {
            Tool.BRUSH: "Brush",
            Tool.RECTANGLE: "Rectangle outline",
            Tool.FILLED_RECT: "Rectangle fill",
            Tool.FILL: "Flood fill",
            Tool.ERASER: "Eraser",
            Tool.PICKER: "Pick tile",
            Tool.AUTOTILE: "Terrain",
        }[self]

    @property
    def is_drag(self) -> bool:
        """Does dragging extend the operation, or just repeat it?"""
        return self in (Tool.RECTANGLE, Tool.FILLED_RECT)

    @property
    def edits(self) -> bool:
        """False for tools that only read (the picker)."""
        return self is not Tool.PICKER

    @property
    def uses_stamp(self) -> bool:
        """Terrain derives its tiles from a rule, not from the palette
        selection, so a multi-tile stamp is meaningless to it."""
        return self not in (Tool.PICKER, Tool.AUTOTILE)

    @property
    def uses_size(self) -> bool:
        """Does a brush FOOTPRINT change what this tool writes?

        Not a synonym for `uses_stamp`; the two disagree in both directions:

          * AUTOTILE has `uses_stamp` False (it cannot take a pattern) and
            `uses_size` True (it takes a block of cells and sets their
            corners).
          * RECTANGLE, FILLED_RECT and FILL have `uses_stamp` True and
            `uses_size` False. Those three reach `Stroke.__cover`, which
            treats the stamp as a repeating pattern keyed on MAP
            coordinates, so a uniform 3x3 tiles to itself and yields the
            same edits as a 1x1. A size control wired to them would move a
            number and change nothing.

        PICKER edits nothing at all, so it has no footprint either.
        """
        return self in (Tool.BRUSH, Tool.ERASER, Tool.AUTOTILE)


class EditMode(Enum):
    """What the tools act ON. Deliberately not what the tools ARE.

    A mode that rebinds B/R/G/E/I is a mode nobody learns -- the same key has
    to mean the same tool. So brush still brushes, fill still fills, and the
    only thing that changes is which layer receives the write and what the
    palette offers to write.

    It lives beside `Tool`, in a module that imports no Qt, because it is a
    fact about what a drag MEANS; `collision_view` re-exports it.
    """

    TILES = "tiles"
    COLLISION = "collision"

    @property
    def label(self) -> str:
        return {EditMode.TILES: "Tiles",
                EditMode.COLLISION: "Collision"}[self]

    @property
    def tip(self) -> str:
        return {
            EditMode.TILES: "Paint the active tile layer.",
            EditMode.COLLISION: "Paint the active layer's companion "
                                "passability layer. Same tools, same keys.",
        }[self]

    @property
    def subdivides(self) -> bool:
        """Does a stroke in this mode land on the active layer's COMPANION?

        WHICH LAYER, never how finely. Its one reader is
        `MapCanvas.paint_unit`, where it picks the layer a stroke is measured
        against and written to -- the active layer's passability companion in
        COLLISION, the active layer itself in TILES. The RESOLUTION is then
        read off whichever layer that turned out to be, from that layer's own
        `pyoneer_subcell`; it cannot live here, because it belongs to one
        layer of one map and this module holds no document by design.

        Treating the mode as the cell-size authority costs 1,200px: a
        companion is a selectable row in the Layers panel, so an author can
        paint one in TILE mode, where "a cell is a tile" is false and every
        mask lands in the wrong sub-cell.

        False for TILES on purpose: there the author is painting the row they
        selected, whatever kind of layer it is, and redirecting that write to
        a companion would make the selected row unpaintable.
        """
        return self is EditMode.COLLISION

    @property
    def disabled_tools(self) -> frozenset[Tool]:
        """Tools with no meaning in this mode.

        Terrain is the only one: autotile indexes a 47-tile corner sheet, and
        in collision mode there is no such sheet to index.
        """
        if self is EditMode.COLLISION:
            return frozenset({Tool.AUTOTILE})
        return frozenset()

    def allows(self, tool: Tool) -> bool:
        return tool not in self.disabled_tools

    @property
    def other(self) -> "EditMode":
        return EditMode.COLLISION if self is EditMode.TILES else EditMode.TILES


@dataclass(frozen=True)
class Stamp:
    """A rectangle of gids to place as a unit.

    `gids` is row-major, length width*height. A gid of -1 means "leave this
    cell alone", which is how a non-rectangular brush is expressed without
    inventing a mask type.
    """

    width: int
    height: int
    gids: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"a stamp must have positive size, got "
                             f"{self.width}x{self.height}")
        if len(self.gids) != self.width * self.height:
            raise ValueError(
                f"stamp is {self.width}x{self.height} = "
                f"{self.width * self.height} cells but carries "
                f"{len(self.gids)} gids")

    @classmethod
    def single(cls, gid: int) -> "Stamp":
        return cls(1, 1, (gid,))

    @classmethod
    def uniform(cls, gid: int, size: int) -> "Stamp":
        """A size x size FOOTPRINT of one gid.

        Uniform on purpose, and the reason `footprint()` refuses to grow a
        picked pattern: a uniform block has no phase, so it reads the same
        whether `place()` puts it under a cursor or `Stroke.__cover` tiles it
        across an area. A grown 2x2 pattern disagrees between those routes in
        every cell.
        """
        if size < 1:
            raise ValueError(f"a brush footprint must be at least 1 cell, "
                             f"got {size}")
        return cls(size, size, (gid,) * (size * size))

    @classmethod
    def from_rows(cls, rows: list[list[int]]) -> "Stamp":
        if not rows or not rows[0]:
            raise ValueError("a stamp needs at least one cell")
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise ValueError("stamp rows must all be the same length")
        flat = tuple(gid for row in rows for gid in row)
        return cls(width, len(rows), flat)

    @property
    def is_single(self) -> bool:
        return self.width == 1 and self.height == 1

    @property
    def primary(self) -> int:
        """The top-left gid -- what flood fill and single-cell tools use."""
        return self.gids[0]

    def gid_at(self, column: int, row: int) -> int:
        return self.gids[(row % self.height) * self.width + (column % self.width)]

    def cells(self) -> Iterator[tuple[int, int, int]]:
        for index, gid in enumerate(self.gids):
            yield index % self.width, index // self.width, gid


@dataclass
class Bounds:
    width: int
    height: int

    def contains(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height


# --------------------------------------------------------------------------
# Placement
# --------------------------------------------------------------------------

def place(stamp: Stamp, x: int, y: int, bounds: Bounds) -> list[Edit]:
    """Put a stamp with its top-left at (x, y), clipped to the layer."""
    out: list[Edit] = []
    for column, row, gid in stamp.cells():
        if gid < 0:
            continue
        target_x, target_y = x + column, y + row
        if bounds.contains(target_x, target_y):
            out.append((target_x, target_y, gid))
    return out


def footprint(stamp: Stamp, size: int) -> tuple[Stamp, tuple[int, int]]:
    """What a brush of `size` cells actually places, and where.

    Returns the stamp to place and the offset from the CURSOR to that
    stamp's top-left, so a size-3 brush is centred on the cell under the
    pointer instead of hanging down and right of it. `place()` anchors
    top-left, which is correct for a pattern picked out of the palette --
    you place it by the corner you selected -- and wrong for a swept
    footprint, so the two are distinguished here rather than in `place`.

    A picked PATTERN comes back untouched at any size -- its own dimensions
    are its footprint. Only a single stamp grows, into `Stamp.uniform`.

    Even sizes cannot be centred on a cell -- there is no middle -- so they
    bias up and left, which is `(size - 1) // 2` and needs no special case.
    """
    if size < 1:
        raise ValueError(f"a brush footprint must be at least 1 cell, "
                         f"got {size}")
    if size == 1 or not stamp.is_single:
        return stamp, (0, 0)
    offset = -((size - 1) // 2)
    return Stamp.uniform(stamp.primary, size), (offset, offset)


def grid_lines(count: int, step: int) -> list[int]:
    """Which of `count` cells' boundaries the displayed grid draws.

    ALWAYS A SUBSET of `range(count + 1)`, never a superset: a grid finer
    than the cell a click addresses would show boundaries no click can land
    on. A coarser grid draws fewer lines, and every one of them is real.

    The far edge is always included, so the map never ends on a step
    boundary it does not have.
    """
    if step < 1:
        raise ValueError(f"a grid step must be at least one cell, got {step}")
    lines = list(range(0, count + 1, step))
    if lines[-1] != count:
        lines.append(count)
    return lines


def line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Bresenham. A mouse move skips cells at speed; without this a fast
    drag paints a dotted line instead of a stroke."""
    cells: list[tuple[int, int]] = []
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    step_x = 1 if x0 < x1 else -1
    step_y = 1 if y0 < y1 else -1
    error = dx - dy
    x, y = x0, y0
    while True:
        cells.append((x, y))
        if x == x1 and y == y1:
            break
        doubled = error * 2
        if doubled > -dy:
            error -= dy
            x += step_x
        if doubled < dx:
            error += dx
            y += step_y
    return cells


def rectangle(x0: int, y0: int, x1: int, y1: int, *,
              filled: bool) -> list[tuple[int, int]]:
    """Cells of a rectangle between two corners, in either order."""
    left, right = min(x0, x1), max(x0, x1)
    top, bottom = min(y0, y1), max(y0, y1)
    if filled:
        return [(x, y) for y in range(top, bottom + 1)
                for x in range(left, right + 1)]
    cells: list[tuple[int, int]] = []
    for x in range(left, right + 1):
        cells.append((x, top))
        if bottom != top:
            cells.append((x, bottom))
    for y in range(top + 1, bottom):
        cells.append((left, y))
        if right != left:
            cells.append((right, y))
    return cells


def flood(read: Reader, bounds: Bounds, x: int, y: int, *,
          limit: int = 40_000) -> list[tuple[int, int]]:
    """Four-connected flood of the region matching the gid at (x, y).

    `limit` is a real guard: filling an empty 100x100 layer is 10,000 cells.
    A truncated region must not be returned silently, so the caller is told
    -- see `flood_or_raise`.
    """
    if not bounds.contains(x, y):
        return []
    target = read(x, y)
    seen: set[tuple[int, int]] = {(x, y)}
    out: list[tuple[int, int]] = []
    queue: deque[tuple[int, int]] = deque([(x, y)])
    while queue:
        cx, cy = queue.popleft()
        out.append((cx, cy))
        if len(out) > limit:
            return out
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if (nx, ny) in seen or not bounds.contains(nx, ny):
                continue
            if read(nx, ny) != target:
                continue
            seen.add((nx, ny))
            queue.append((nx, ny))
    return out


class FloodTooLargeError(Exception):
    """A flood fill would touch more cells than the caller allowed."""


def flood_or_raise(read: Reader, bounds: Bounds, x: int, y: int, *,
                   limit: int = 40_000) -> list[tuple[int, int]]:
    cells = flood(read, bounds, x, y, limit=limit)
    if len(cells) > limit:
        raise FloodTooLargeError(
            f"flood fill from ({x}, {y}) covers more than {limit:,} cells; "
            f"refusing rather than truncating")
    return cells


# --------------------------------------------------------------------------
# Strokes
# --------------------------------------------------------------------------

@dataclass
class Stroke:
    """One press-drag-release, accumulated into a single transaction.

    Later edits to the same cell win, and cells whose value never actually
    changed are dropped, so scrubbing back and forth over one tile produces
    one edit -- or none, if you ended where you started.
    """

    tool: Tool
    stamp: Stamp
    bounds: Bounds
    read: Reader
    origin: tuple[int, int] | None = None
    last: tuple[int, int] | None = None
    #: Where the stamp's top-left goes relative to the cursor -- what
    #: `footprint()` returns beside the stamp. It applies to the POINT
    #: operations only: an area tool defines its own cells and a flood
    #: starts from the cell actually clicked, so offsetting either would
    #: move the shape rather than centre a brush.
    anchor: tuple[int, int] = (0, 0)
    # init=False: this is accumulated state, not something a caller supplies.
    # Without it the mangled name leaks into the generated __init__ signature.
    __pending: dict[tuple[int, int], int] = field(
        default_factory=dict, init=False, repr=False)

    # -- driving -----------------------------------------------------------

    def begin(self, x: int, y: int) -> None:
        self.origin = (x, y)
        self.last = (x, y)
        self.__pending.clear()
        self.__apply_at(x, y)

    def extend(self, x: int, y: int) -> None:
        """A mouse move. For drag tools this redefines the shape; for
        painting tools it continues the stroke."""
        if self.origin is None:
            return
        if (x, y) == self.last and not self.tool.is_drag:
            return
        if self.tool.is_drag:
            # A drag tool REDEFINES its shape on every move rather than
            # accumulating, so dragging back shrinks the rectangle.
            self.__pending.clear()
            self.__cover(rectangle(*self.origin, x, y,
                                   filled=self.tool is Tool.FILLED_RECT))
        else:
            previous = self.last or (x, y)
            for cx, cy in line(previous[0], previous[1], x, y):
                self.__apply_at(cx, cy)
        self.last = (x, y)

    def __apply_at(self, x: int, y: int) -> None:
        """Apply the tool at one cursor position -- a POINT operation."""
        if self.tool is Tool.FILL:
            # Before the anchor is applied: a flood starts from the cell the
            # author clicked, and a brush footprint must not move which
            # region gets filled.
            self.__cover(flood(self.read, self.bounds, x, y))
            return
        x, y = x + self.anchor[0], y + self.anchor[1]
        if self.tool is Tool.ERASER:
            # The eraser's stamp is a footprint, not a pattern.
            for column, row, _gid in self.stamp.cells():
                self.__put(x + column, y + row, 0)
            return
        # A brush anchors the whole stamp under the cursor.
        for edit_x, edit_y, gid in place(self.stamp, x, y, self.bounds):
            self.__put(edit_x, edit_y, gid)

    def __cover(self, cells: Iterable[tuple[int, int]]) -> None:
        """Apply the tool over an AREA the tool itself defined.

        Here the stamp is a repeating pattern rather than a footprint: the
        area decides which cells change, and each one takes the pattern
        value for its own position. Tiling is aligned to MAP coordinates,
        not to where the drag started, so two rectangles painted with the
        same pattern line up with each other.
        """
        erasing = self.tool is Tool.ERASER
        for cx, cy in cells:
            gid = 0 if erasing else self.stamp.gid_at(cx, cy)
            if gid < 0:                       # a hole in the pattern
                continue
            self.__put(cx, cy, gid)

    def __put(self, x: int, y: int, gid: int) -> None:
        if self.bounds.contains(x, y):
            self.__pending[(x, y)] = gid

    # -- reading -----------------------------------------------------------

    def preview(self) -> list[Edit]:
        """Every cell this stroke currently covers, changed or not.
        The canvas draws this as a ghost overlay."""
        return [(x, y, gid) for (x, y), gid in self.__pending.items()]

    def edits(self) -> list[Edit]:
        """Only the cells whose value would actually change."""
        return [(x, y, gid) for (x, y), gid in sorted(self.__pending.items())
                if self.read(x, y) != gid]

    @property
    def empty(self) -> bool:
        return not self.edits()

    def __len__(self) -> int:
        return len(self.__pending)


def edits_to_triples(edits: Iterable[Edit]) -> list[list[int]]:
    """map.tile.set_many wants JSON-shaped [x, y, gid] lists."""
    return [[x, y, gid] for x, y, gid in edits]
