from scripts.core.game_object import PyoneerGameObject

__object_registry__: dict[str, PyoneerGameObject] = {}
"""The global pyoneer game object registry."""


def bind_global_pyoneer_object(id: str, component: PyoneerGameObject):
    """Bind a component to the module level."""
    global __object_registry__
    __object_registry__[id] = component


def unbind_global_pyoneer_object(id: str):
    """Unbind a component from the module level."""
    global __object_registry__
    if id in __object_registry__:
        del __object_registry__[id]


def get_global_pyoneer_object(id: str) -> PyoneerGameObject | None:
    """Get a component from the module level."""
    global __object_registry__
    if id in __object_registry__:
        return __object_registry__[id]
    return None

