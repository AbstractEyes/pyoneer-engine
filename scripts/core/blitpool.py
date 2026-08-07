from __future__ import annotations
from pygame import Surface, Vector2, Rect


class BlitToken:
    def __init__(self,
                 blit: BlitToken | None = None,
                 image: Surface | None = None,
                 destination: tuple[int | float, int | float] | Vector2 | None = Vector2(0, 0),
                 draw_area: tuple[int | float, int | float, int | float, int | float] | None = Rect(0, 0, 0, 0),
                 depth: int = 0,
                 priority: int = 0,
                 sender: object | None = None):
        self.image: Surface = image
        self.destination: tuple[int | float, int | float] | Vector2 | None = self.__tup_or_vec(destination)
        self.draw_area: Rect | None = self.__rect_or_tup(draw_area)
        self.depth: int = depth
        self.priority: int = priority
        self.sender: object | None = sender
        self.copy(blit)
        #if self.image is not None and self.area.width == 0 and self.area.height == 0:
        #    self.area = self.image.get_rect() # default to the image size if we have no defined bounds

    def pygame_blit(self) -> tuple[Surface, tuple[int, int], Rect]:
        #if self.draw_area.width == 0 and self.draw_area.height == 0:
        #    return self.image, self.destination
        return self.image, self.destination, self.draw_area


    def __rect_or_tup(self, tup: tuple[int | float, int | float, int | float, int | float] | Rect):
        if isinstance(tup, tuple):
            return Rect(tup)
        elif tup is None:
            return Rect(0, 0, self.image.get_width(), self.image.get_height())
        else:
            return tup

    @staticmethod
    def __tup_or_vec(tup: tuple[int | float, int | float] | Vector2):
        if isinstance(tup, tuple):
            return Vector2(tup)
        else:
            return tup

    def copy(self, blit: BlitToken | None = None) -> BlitToken:
        if isinstance(blit, BlitToken):
            self.image = blit.image
            self.destination = blit.destination
            self.draw_area = blit.draw_area
            self.depth = blit.depth
            self.priority = blit.priority
            return self
        else:
            return BlitToken(blit=self)

    def __str__(self):
        return f"BlitToken(sender={self.sender}, position={self.destination}, area={self.draw_area}, depth={self.depth}, priority={self.priority})"


ORGANIZED_BLITS: dict[int,dict[int,list[BlitToken]]] = {}
"""The more ordered blit pool, dedicated to ordered blitting based on specific prioritization."""


class BlitPool:
    """global static access class for managing blits in a global manner."""

    @staticmethod
    def get_blit_pool(clear: bool = True) -> dict[int, list[BlitToken]] | dict[int, dict[int, list[BlitToken]]]:
        global ORGANIZED_BLITS
        cop = ORGANIZED_BLITS.copy()
        if clear:
            ORGANIZED_BLITS.clear()
        return cop

    @staticmethod
    def get_blit_pool_pygame(clear: bool = True) -> list[tuple[Surface, tuple[int, int], Rect]]:
        global ORGANIZED_BLITS
        blits = []
        for depth in sorted(ORGANIZED_BLITS.keys()):
            for priority in sorted(ORGANIZED_BLITS[depth].keys()):
                for token in ORGANIZED_BLITS[depth][priority]:
                    blits.append(token.pygame_blit())
        if clear:
            ORGANIZED_BLITS.clear()
        return blits

    @staticmethod
    def clear_organized_blits():
        global ORGANIZED_BLITS
        ORGANIZED_BLITS.clear()

    @staticmethod
    def make_blit(image: Surface | None = None,
                  destination: tuple[int | float, int | float] | Vector2 | None = None,
                  draw_area: tuple[int | float, int | float, int | float, int | float] | Rect | None = None,
                  depth: int = 0,
                  priority: int = 0,
                  sender: object | None = None) -> BlitToken:
        return BlitToken(image=image, destination=destination, draw_area=draw_area, depth=depth, priority=priority, sender=sender)

    @staticmethod
    def blit_to_layer(depth: int = 0,
                      priority: int = 0,
                      image: Surface | None = None,
                      destination: tuple[int | float, int | float] | Rect | Vector2 | None = None,
                      draw_area: tuple[int | float, int | float, int | float, int | float] | Rect | None = None,
                      blit: BlitToken | None = None,
                      sender: object | None = None):
        """
            Blits directly to a layer in an unsafe global manner when the layered renderer is called./n
            These blits are guaranteed to be drawn in this order.
        """
        prepared: BlitToken
        if isinstance(blit, BlitToken):
            prepared = blit
        else:
            prepared = BlitPool.make_blit(image=image, destination=destination, draw_area=draw_area, depth=depth, priority=priority, sender=sender)
        global ORGANIZED_BLITS
        if depth in ORGANIZED_BLITS:
            if priority in ORGANIZED_BLITS[depth]:
                ORGANIZED_BLITS[depth][priority].append(prepared)
            else:
                ORGANIZED_BLITS[depth][priority] = [prepared]
        else:
            ORGANIZED_BLITS[depth] = {priority: [prepared]}

