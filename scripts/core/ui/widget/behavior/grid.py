import uuid

from pygame import Vector2, Rect

from component import GameComponent


class GridNode:
    def __init__(self, component: GameComponent, position: Vector2, offset: Vector2 = Vector2(0, 0)):
        self.component = component
        self.position = position
        self.offset = offset


class DummyParent:
    def __init__(self,
                 parent: GameComponent | None = None,
                 children: list[GameComponent] | None = None):
        self.__parent: GameComponent | None = parent
        self.__children: dict[str, list[GameComponent]] | None = children
        self.__bounds: Rect = Rect(0, 0, 0, 0)
        self.__local_bounds: Rect = Rect(0, 0, 0, 0)

    def bind_component(self, id: str, component: GameComponent | None = None):
        if self.__children is not None:
            if self.__children.keys().__contains__(id):
                self.__children[id].append(component)
            else:
                self.__children[id] = list([component])

    def unbind_component(self, component: GameComponent | None = None):
        ...

    @property
    def world_bounds(self) -> Rect | None:
        bounds = self.__bounds.copy()
        parent_bounds_offset: Rect = Rect(0,0,0,0)
        if self.__parent is not None:
            raw_bounds = self.__parent.world_bounds.copy()
            bounds.x += raw_bounds.x
            bounds.y += raw_bounds.y
            bounds.width += raw_bounds.width
            bounds.height += raw_bounds.height


        return self.__bounds



class GridComponent(GameComponent):

    """
        Attaching components should be handled in a logically simple way.\n
        Each component should be contained in a grid, depending on the columns or rows.\n
        The layout controller should handle the positioning of the components that exist in the grid.\n
    """
    def __init__(self,
                 row_height: int = 0,
                 max_columns = -1,
                 max_rows = -1,
                 *args,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.__grid_container: list[GridNode] = []
        self.__grid_manual: dict[str, Vector2] = {}
        self.max_columns = max_columns
        self.max_rows = max_rows
        self.row_height = row_height
        self.__current_row = 0
        """Used to determine the current row in the grid"""
        self.__current_column = 0
        """Used to determine the current column in the grid"""

    def item(self, index: int) -> GameComponent:
        return self.__grid_container[index].component

    def find(self, uuid: str) -> GridNode | None:
        for node in self.__grid_container:
            if node.component.uuid == uuid:
                return node
        return None

    def __make_node(self, component: GameComponent, position: Vector2) -> GridNode:
        return GridNode(component, position)

    def __add(self, component: GameComponent):
        self.__grid_container.append(self.__make_node(component, Vector2(self.__current_column, self.__current_row)))
        self.__increment_position()

    def __add_manual(self, component: GameComponent, position: Vector2 | tuple):
        if isinstance(position, tuple):
            self.__grid_manual[component.uuid] = Vector2(position)
        elif isinstance(position, Vector2):
            self.__grid_manual[component.uuid] = position

    def __increment_position(self):
        self.__current_column += 1
        if self.max_columns > 0 and self.__current_column >= self.max_columns:
            self.__current_column = 0
            self.__current_row += 1

    def add_item(self, component: GameComponent, position: Vector2 | tuple | None = None):
        self.__add(component)
        if position is not None:
            self.__add_manual(component, position)

    def remove_item(self, component: GameComponent):
        found = self.find(component.uuid)
        if found is not None:
            self.__grid_container.remove(found)
        if component.uuid in self.__grid_manual:
            del self.__grid_manual[component.uuid]

    def clear(self):
        self.__grid_container.clear()
        self.__grid_manual.clear()
        self.__current_column = 0
        self.__current_row = 0
