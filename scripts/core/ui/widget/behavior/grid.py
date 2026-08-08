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
        spacing       (x, y) gap between cells
        padding       (x, y) inset from the grid's own edges
        grow          resize the grid's own bounds to fit content on relayout
        """
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
    # layout
    # ---------------------------------------------------------------- #

    def measure(self) -> tuple[list[int], list[int]]:
        """Column widths and row heights, measured from the items."""
        columns: dict[int, int] = {}
        rows: dict[int, int] = {}
        for node in self._nodes:
            bounds = node.component.local_bounds
            width = self.column_width or bounds.width
            height = self.row_height or bounds.height
            columns[node.column] = max(columns.get(node.column, 0), int(width))
            rows[node.row] = max(rows.get(node.row, 0), int(height))
        widths = [columns.get(i, 0) for i in range(max(columns, default=-1) + 1)]
        heights = [rows.get(i, 0) for i in range(max(rows, default=-1) + 1)]
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
