from scripts.core.ui.widget.behavior.grid import GridComponent
from scripts.core.component import GameComponent
from scripts.core.ui.widget.containers.panel import Panel


class ListBoxComponent(Panel):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__selected_index = -1
        self.__selected_item: GameComponent | None = None
        self.__selected_items: list | None = None
        self.__grid: GridComponent | None = None
        self.__make()

    def __make(self):
        self.__grid = GridComponent(parent=self, bounds=self.world_bounds, max_columns=1)
        self.bind_component("grid", self.__grid)

    def add(self, component: GameComponent):
        self.__grid.add_item(component)

    def remove(self, component: GameComponent):
        self.__grid.remove_item(component)

    def clear(self):
        self.__grid.clear()



