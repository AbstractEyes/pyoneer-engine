"""Grid layout for components.

WHAT WAS HERE BEFORE
--------------------
A shell. `add_item` recorded a GridNode holding a (column, row) cell
coordinate and never bound the component or gave it a pixel position, so items
never entered the component tree and nothing was ever drawn. `row_height` and
`max_rows` were stored and never read. There was no layout pass at all, and a
`DummyParent` class that nothing referenced. It had never executed.

WHAT IT DOES NOW
----------------
Items flow left-to-right, wrapping at `max_columns`, and `relayout()` assigns
each one a real `local_bounds`. Column widths and row heights are measured from
the items that occupy them unless fixed sizes are given, so a grid of mixed
widgets lines up. The grid then resizes itself to fit its content, which is what
lets a scrolling Panel know how far it can scroll.

    grid = GridComponent(parent=panel, bounds=Rect(0, 0, 200, 0), max_columns=2,
                         spacing=(4, 4), padding=(6, 6))
    grid.add_item(Button(bounds=Rect(0, 0, 80, 24), text="one"))
    grid.add_item(Button(bounds=Rect(0, 0, 80, 24), text="two"))
    grid.add_item(Button(bounds=Rect(0, 0, 80, 24), text="three"))
    # -> two columns, two rows; grid.local_bounds grew to 178x62

SCROLLING INSIDE A PANEL
------------------------
Attach the GRID to the panel, not the items. `Panel.__offset_children` sets an
offset on its attached children, and `GameComponent.__update_world_bounds`
computes `child.world = child.local + parent.world + child.offset` -- so
offsetting the grid moves everything inside it, with no per-item bookkeeping.

    panel.attach_component("grid", grid)
    panel.fit_scroll_area()   # scrollbars now measure the grid's real size
"""
from __future__ import annotations

from pygame import Rect, Vector2

from scripts.core.component import GameComponent
from scripts.core.errors import PyoneerLayoutError
from scripts.core.log import trace_lifecycle


def _as_pair(value, default=(0, 0)) -> tuple[int, int]:
    """Accept a Vector2, a 2-tuple, or a single number for x/y pairs."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value), int(value)
    if isinstance(value, Vector2):
        return int(value.x), int(value.y)
    return int(value[0]), int(value[1])


class GridNode:
    """One item's place in the grid."""

    def __init__(self, component: GameComponent, cell: Vector2):
        self.component = component
        self.cell = cell
        """Grid coordinate as (column, row). Not pixels."""

    @property
    def column(self) -> int:
        return int(self.cell.x)

    @property
    def row(self) -> int:
        return int(self.cell.y)

    def __repr__(self) -> str:
        return f"GridNode({type(self.component).__name__} at c{self.column} r{self.row})"


class GridComponent(GameComponent):
    """Lays its child components out on a grid and sizes itself to fit them."""

    def __init__(self,
                 max_columns: int = -1,
                 max_rows: int = -1,
                 row_height: int = 0,
                 column_width: int = 0,
                 cell_size=None,
                 spacing=(0, 0),
                 padding=(0, 0),
                 grow: bool = True,
                 *args,
                 **kwargs):
        """
        max_columns   wrap to a new row after this many columns; -1 = one row
        max_rows      hard cap; -1 = unbounded. Exceeding it RAISES rather than
                      dropping the item, because a silently-missing widget is
                      the worst outcome and the hardest to diagnose
        row_height    fixed row height in pixels; 0 = size each row to its
                      tallest item
        column_width  fixed column width; 0 = size each column to its widest
        cell_size     shorthand for column_width and row_height together. Sets
                      UNIFORM cells, which is what makes the grid snappable:
                      cell geometry stops depending on what is in it, so
                      cell_at() answers the same question before and after an
                      item is placed
        spacing       (x, y) gap between cells
        padding       (x, y) inset from the grid's own edges
        grow          resize the grid's own bounds to fit content on relayout

        TWO MODES, and the difference matters:
          measured  (default) cells size to their contents. Right for a list of
                    mixed widgets. NOT reliably snappable -- placing an item
                    can move every cell after it.
          uniform   cell_size / column_width+row_height given. Cell geometry is
                    fixed, so pixel<->cell conversion is stable. This is the
                    mode for tile placement and drag-and-drop.
        """
        if cell_size is not None:
            column_width, row_height = _as_pair(cell_size)
        super().__init__(*args, **kwargs)
        self._nodes: list[GridNode] = []
        self._manual: dict[str, Vector2] = {}
        self.max_columns = max_columns
        self.max_rows = max_rows
        self.row_height = row_height
        self.column_width = column_width
        self.spacing: tuple[int, int] = _as_pair(spacing)
        self.padding: tuple[int, int] = _as_pair(padding)
        self.grow = grow
        self._next_column = 0
        self._next_row = 0
        self._laying_out = False
        """Guard: relayout() writes child bounds, which can re-enter."""

    # ---------------------------------------------------------------- #
    # contents
    # ---------------------------------------------------------------- #

    @property
    def items(self) -> list[GameComponent]:
        """The laid-out components, in insertion order."""
        return [node.component for node in self._nodes]

    @property
    def count(self) -> int:
        return len(self._nodes)

    def item(self, index: int) -> GameComponent:
        return self._nodes[index].component

    def find(self, uuid: str) -> GridNode | None:
        for node in self._nodes:
            if node.component.uuid == uuid:
                return node
        return None

    def add_item(self, component: GameComponent,
                 cell: Vector2 | tuple | None = None,
                 name: str | None = None) -> GridNode:
        """Place a component in the grid and BIND it so it actually exists.

        The previous implementation recorded a cell coordinate and stopped,
        which is why nothing ever appeared: an unbound component is not in the
        tree, receives no events and is never drawn.

        `cell` pins the item to an explicit (column, row) instead of taking the
        next auto-flow slot.
        """
        if cell is not None:
            placed = Vector2(_as_pair(cell))
            self._manual[component.uuid] = placed
        else:
            placed = Vector2(self._next_column, self._next_row)
            self._advance()

        self._check_row_limit(placed)
        node = GridNode(component, placed)
        self._nodes.append(node)

        component.bind_parent(self)
        self.bind_component(name or f"item_{len(self._nodes) - 1}", component)
        trace_lifecycle("grid add %s at c%s r%s",
                        type(component).__name__, node.column, node.row)
        self.relayout()
        return node

    def remove_item(self, component: GameComponent) -> bool:
        node = self.find(component.uuid)
        if node is None:
            return False
        self._nodes.remove(node)
        self._manual.pop(component.uuid, None)
        for name, bound in list(self.components.items()):
            if bound is component:
                self.unbind_component(name)
        self._reflow_auto_cells()
        self.relayout()
        return True

    def clear(self):
        for node in list(self._nodes):
            self.remove_item(node.component)
        self._nodes.clear()
        self._manual.clear()
        self._next_column = 0
        self._next_row = 0

    def _advance(self):
        self._next_column += 1
        if self.max_columns > 0 and self._next_column >= self.max_columns:
            self._next_column = 0
            self._next_row += 1

    def _reflow_auto_cells(self):
        """Re-pack auto-placed items after a removal, leaving pinned ones put."""
        self._next_column = 0
        self._next_row = 0
        for node in self._nodes:
            if node.component.uuid in self._manual:
                continue
            node.cell = Vector2(self._next_column, self._next_row)
            self._advance()

    def _check_row_limit(self, cell: Vector2):
        if self.max_rows > 0 and int(cell.y) >= self.max_rows:
            raise PyoneerLayoutError(
                f"grid is full: item would land on row {int(cell.y)} but "
                f"max_rows is {self.max_rows}. Raise max_rows, raise "
                f"max_columns, or put the grid in a scrolling Panel.",
                columns=self.max_columns,
                rows=self.max_rows,
                items=len(self._nodes),
            )

    # ---------------------------------------------------------------- #
    # snapping: pixels <-> cells
    # ---------------------------------------------------------------- #

    @property
    def uniform(self) -> bool:
        """True when cells have a fixed size and pixel<->cell is stable.

        In measured mode the geometry depends on the contents, so a cell's
        rect can move when a neighbour is added. cell_at() still answers, but
        the answer has a shelf life -- prefer uniform cells for placement.
        """
        return self.column_width > 0 and self.row_height > 0

    def cell_step(self) -> tuple[int, int]:
        """Pixel distance from one cell's origin to the next, including spacing.

        Only meaningful in uniform mode; raises otherwise rather than returning
        an average that would silently misplace things.
        """
        if not self.uniform:
            raise PyoneerLayoutError(
                "cell_step() needs uniform cells: construct with cell_size=... "
                "(or column_width and row_height). In measured mode each cell "
                "is sized by its contents, so there is no single step.",
                column_width=self.column_width,
                row_height=self.row_height,
            )
        return self.column_width + self.spacing[0], self.row_height + self.spacing[1]

    def cell_origin(self, column: int, row: int) -> Vector2:
        """Top-left of a cell, in grid-local pixels.

        Works in both modes. In measured mode it reports where the cell is
        *now*, derived from the same offsets relayout() uses.
        """
        widths, heights = self.measure()
        pad_x, pad_y = self.padding
        gap_x, gap_y = self.spacing
        x = pad_x
        for index in range(int(column)):
            width = widths[index] if index < len(widths) else self.column_width
            x += width + gap_x
        y = pad_y
        for index in range(int(row)):
            height = heights[index] if index < len(heights) else self.row_height
            y += height + gap_y
        return Vector2(x, y)

    def cell_rect(self, column: int, row: int) -> Rect:
        """Pixel rect of a cell, in grid-local space."""
        origin = self.cell_origin(column, row)
        widths, heights = self.measure()
        column, row = int(column), int(row)
        width = widths[column] if column < len(widths) else self.column_width
        height = heights[row] if row < len(heights) else self.row_height
        return Rect(int(origin.x), int(origin.y), int(width), int(height))

    def cell_at(self, point, *, clamp: bool = False) -> Vector2 | None:
        """Which cell contains a grid-LOCAL point. None if outside the grid.

        This is the primitive snapping is built on: give it a position, get a
        cell. Set clamp=True to pull an out-of-range point to the nearest valid
        cell instead of getting None, which is what a drag that overshoots the
        edge usually wants.
        """
        px, py = _as_pair(point)
        pad_x, pad_y = self.padding
        gap_x, gap_y = self.spacing

        if self.uniform:
            step_x, step_y = self.cell_step()
            column = (px - pad_x) // step_x
            row = (py - pad_y) // step_y
        else:
            widths, heights = self.measure()
            column = self.__index_from_runs(px - pad_x, widths, gap_x)
            row = self.__index_from_runs(py - pad_y, heights, gap_y)
            if column is None or row is None:
                return None if not clamp else Vector2(
                    max(0, min(int(column if column is not None else 0), max(0, len(widths) - 1))),
                    max(0, min(int(row if row is not None else 0), max(0, len(heights) - 1))),
                )

        column, row = int(column), int(row)
        if clamp:
            column = max(0, column)
            row = max(0, row)
            if self.max_columns > 0:
                column = min(column, self.max_columns - 1)
            if self.max_rows > 0:
                row = min(row, self.max_rows - 1)
            return Vector2(column, row)

        if column < 0 or row < 0:
            return None
        if self.max_columns > 0 and column >= self.max_columns:
            return None
        if self.max_rows > 0 and row >= self.max_rows:
            return None
        return Vector2(column, row)

    @staticmethod
    def __index_from_runs(offset: float, runs: list[int], gap: int) -> int | None:
        """Which run contains `offset`, walking measured column/row sizes."""
        if offset < 0:
            return None
        cursor = 0.0
        for index, size in enumerate(runs):
            if offset < cursor + size:
                return index
            cursor += size + gap
        return None

    def world_cell_at(self, world_point, *, clamp: bool = False) -> Vector2 | None:
        """Which cell contains a SCREEN/world point.

        The conversion a mouse handler needs. Subtracts the grid's world origin,
        which already includes any scroll offset the parent panel applied, so a
        click in a scrolled panel resolves to the cell the user actually sees.
        """
        px, py = _as_pair(world_point)
        origin = self.world_bounds
        return self.cell_at((px - origin.x, py - origin.y), clamp=clamp)

    # ---------------------------------------------------------------- #
    # occupancy
    # ---------------------------------------------------------------- #

    def occupant(self, column: int, row: int) -> GameComponent | None:
        """The component in a cell, or None."""
        for node in self._nodes:
            if node.column == int(column) and node.row == int(row):
                return node.component
        return None

    def is_free(self, column: int, row: int) -> bool:
        return self.occupant(column, row) is None

    def snap(self, component: GameComponent, point,
             *, world: bool = False, clamp: bool = True,
             on_occupied: str = "raise",
             name: str | None = None) -> GridNode:
        """Place a component into the cell containing `point`.

        point         pixel position; grid-local unless world=True
        world         treat point as a screen/world coordinate
        clamp         pull an out-of-range point to the nearest cell (default),
                      rather than refusing the placement
        on_occupied   what to do when the target cell already holds something:
                        "raise"   PyoneerLayoutError naming the occupant
                        "replace" remove the occupant, then place
                        "skip"    leave the grid alone and return the existing
                                  node, so a repeated drag is idempotent
        """
        cell = self.world_cell_at(point, clamp=clamp) if world else self.cell_at(point, clamp=clamp)
        if cell is None:
            raise PyoneerLayoutError(
                f"point {tuple(_as_pair(point))} is outside the grid and clamp is off",
                grid=self.local_bounds,
                world=world,
            )

        existing = self.occupant(int(cell.x), int(cell.y))
        if existing is not None and existing is not component:
            if on_occupied == "raise":
                raise PyoneerLayoutError(
                    f"cell c{int(cell.x)} r{int(cell.y)} already holds a "
                    f"{type(existing).__name__}; pass on_occupied='replace' or "
                    f"'skip', or find a free cell with is_free()",
                    cell=(int(cell.x), int(cell.y)),
                )
            if on_occupied == "replace":
                self.remove_item(existing)
            elif on_occupied == "skip":
                return self.find(existing.uuid)
            else:
                raise PyoneerLayoutError(
                    f"on_occupied must be 'raise', 'replace' or 'skip'; got {on_occupied!r}"
                )

        node = self.find(component.uuid)
        if node is not None:
            # Already in the grid -- this is a MOVE, not an insert.
            node.cell = cell
            self._manual[component.uuid] = cell
            self.relayout()
            trace_lifecycle("grid move %s to c%s r%s",
                            type(component).__name__, node.column, node.row)
            return node
        return self.add_item(component, cell=cell, name=name)

    # ---------------------------------------------------------------- #
    # layout
    # ---------------------------------------------------------------- #

    def measure(self) -> tuple[list[int], list[int]]:
        """Column widths and row heights.

        In UNIFORM mode every slot in the occupied span is a full cell wide and
        tall, even if nothing is in it. That is not a detail -- an empty cell
        still occupies its slot, and without this the layout collapsed the gaps
        while cell_at() went on computing from a fixed step. Snapping an item to
        a cell with an empty column before it then placed it somewhere else
        entirely: dropping at x=60 on a 24px/2gap/3pad grid resolved to column 2
        and landed at x=7 instead of x=55, not under the cursor at all.

        In MEASURED mode an empty column genuinely has no width, because the
        columns only exist to hold their contents.
        """
        columns: dict[int, int] = {}
        rows: dict[int, int] = {}
        for node in self._nodes:
            bounds = node.component.local_bounds
            width = self.column_width or bounds.width
            height = self.row_height or bounds.height
            columns[node.column] = max(columns.get(node.column, 0), int(width))
            rows[node.row] = max(rows.get(node.row, 0), int(height))

        column_count = max(columns, default=-1) + 1
        row_count = max(rows, default=-1) + 1
        if self.uniform:
            return ([self.column_width] * column_count,
                    [self.row_height] * row_count)
        widths = [columns.get(i, 0) for i in range(column_count)]
        heights = [rows.get(i, 0) for i in range(row_count)]
        return widths, heights

    def content_size(self) -> tuple[int, int]:
        """Pixel size the items occupy, including padding. (0, 0) when empty."""
        widths, heights = self.measure()
        if not widths or not heights:
            return 0, 0
        pad_x, pad_y = self.padding
        gap_x, gap_y = self.spacing
        width = sum(widths) + gap_x * (len(widths) - 1) + pad_x * 2
        height = sum(heights) + gap_y * (len(heights) - 1) + pad_y * 2
        return int(width), int(height)

    def relayout(self):
        """Assign every item its pixel rect, then fit the grid to its content.

        This is the pass the class was missing. Idempotent, and safe to call as
        often as you like -- it writes local_bounds, and GameComponent's setter
        already no-ops when the rect is unchanged.
        """
        if self._laying_out:
            return
        self._laying_out = True
        try:
            widths, heights = self.measure()
            pad_x, pad_y = self.padding
            gap_x, gap_y = self.spacing

            # Running pixel offset of each column / row.
            x_of = [pad_x]
            for width in widths:
                x_of.append(x_of[-1] + width + gap_x)
            y_of = [pad_y]
            for height in heights:
                y_of.append(y_of[-1] + height + gap_y)

            for node in self._nodes:
                bounds = node.component.local_bounds
                node.component.local_bounds = Rect(
                    x_of[node.column],
                    y_of[node.row],
                    self.column_width or bounds.width,
                    self.row_height or bounds.height,
                )

            if self.grow:
                width, height = self.content_size()
                current = self.local_bounds
                if (current.width, current.height) != (width, height):
                    self.local_bounds = Rect(current.x, current.y, width, height)
        finally:
            self._laying_out = False

    def _on_size_changed(self, width: int | float, height: int | float):
        """Re-flow when the grid itself is resized.

        Only meaningful with grow=False; a growing grid sets its own size from
        its content, and relayout() guards re-entry so this cannot loop.
        """
        if not self.grow:
            self.relayout()

    def core_lifecycle_build(self, event=None):
        super().core_lifecycle_build(event)
        self.relayout()

    def __repr__(self) -> str:
        width, height = self.content_size()
        return (f"GridComponent({self.count} items, max_columns={self.max_columns}, "
                f"content={width}x{height})")
