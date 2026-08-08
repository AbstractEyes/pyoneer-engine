"""Tile painting -- what a drag on the canvas means, as pure logic.

No Qt, no pygame, no document. Every function here takes plain numbers and
a `read(x, y) -> gid` callable and returns a list of `(x, y, gid)` edits.
That makes the interesting parts -- flood fill, rectangle, stamp
placement -- testable without opening a window, which is the only reason
their edge cases got found.

ONE STROKE IS ONE UNDO STEP
---------------------------
The first canvas emitted `map.tile.set` per click, so dragging a brush
across forty cells produced forty transactions and forty undos. A stroke
accumulates here and commits as a single `map.tile.set_many`, which is both
the correct undo granularity and dramatically cheaper -- the tmx csv payload
is re-rendered once per transaction, not once per cell.

STAMPS
------
A brush is a 1x1 stamp. Selecting a rectangle in the tile palette gives a
larger one, and every tool honours it: a rectangle tool with a 2x2 stamp
tiles that pattern across the rectangle. Special-casing the single tile
would mean two code paths that drift.
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

    `limit` is a real guard, not decoration: filling an empty 100x100 layer
    is 10,000 cells and a larger map is trivially bigger. Returning a
    truncated region silently would be worse than refusing, so the caller is
    told -- see `flood_or_raise`.
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
            self.__cover(flood(self.read, self.bounds, x, y))
            return
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
