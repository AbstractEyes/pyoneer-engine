from component import GameComponent


class Viewport(GameComponent):
    """
        A viewport is a container that can be used to display a portion of a larger widget.
        It is necessary for scrolling and other similar behaviors.
    """
    def __init__(self, scrollable_bounds, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scrollable_bounds = scrollable_bounds
        self.scroll_position = 0
        self.scroll_rate = 20
        self.__make()