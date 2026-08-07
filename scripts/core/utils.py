import sys

from pygame import rect


class RectUtils:

    @staticmethod
    def offset(parent: rect.Rect | None = None, child: rect.Rect | None = None) -> rect.Rect:
        if parent is None:
            return rect.Rect(0, 0, child.width, child.height)
        return RectUtils.bounds_difference(parent, child)

    @staticmethod
    def bounds_difference(parent: rect.Rect | None, child: rect.Rect) -> rect.Rect:
        if parent is None:
            return rect.Rect(child.x, child.y, child.width, child.height)
        return rect.Rect(child.x - parent.x, child.y - parent.y, child.width, child.height)


def __debugging() -> bool:
    """Return if the debugger is currently active"""
    return hasattr(sys, 'gettrace') and sys.gettrace() is not None


VERBOSE = False
DEBUGGING = __debugging() and VERBOSE
import uuid

from pygame import Vector3, Surface, Rect
