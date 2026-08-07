from pygame import Rect, Vector2

from behavior import Behavior
from simple_component import SimpleComponent


class Transform(Behavior):
    def __init__(self):
        super().__init__("transform")

    def create(self, component: SimpleComponent):
        self.set_attribute(component, "bounds", Rect(0, 0, 0, 0))
        self.set_attribute(component, "offset", Vector2(0, 0))



