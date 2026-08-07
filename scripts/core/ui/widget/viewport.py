from pygame import Rect, Vector2

from component import GameComponent
from game_camera import GameCamera


class Viewport(GameComponent):

    def __init__(self,
                 bounds: Rect,
                 offset: Vector2 | Rect | None = None,
                 full_bounds: Rect | None = None,
                 *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.__camera = GameCamera(
            view_area=bounds,
            full_area=full_bounds,
            target=self
        )
        self.__make()

    def __make(self) -> None:
        pass

    @property
    def camera(self) -> GameCamera:
        return self.__camera

    @camera.setter
    def camera(self, value: GameCamera) -> None:
        self.__camera = value

    def move(self, position: Rect) -> None:
        """Moves the viewport's camera and fires the viewport scrolled events."""
        self.__camera.update(position)
        #self.send_event(GameEventType.VIEWPORT_SCROLLED, viewport=self)