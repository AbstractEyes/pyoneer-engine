from pyclbr import Class
from typing import Type, Callable, TypeVar


# hierarchy; component


class ComponentNode:
    def __init__(self, name: str, callable: Callable):
        self.name = name
        self.callable = callable

    def call(self, *args, **kwargs):
        return self.callable(*args, **kwargs)


COMPONENT_POOL: dict[str, ComponentNode] = {}
COMPONENT_POOL_READY: bool = False


class ComponentFactory:
    """This takes in the component data and attempts to create a component object to return."""

    def __init__(self):
        pass

    def get(self, name: str) -> ComponentNode:
        global COMPONENT_POOL
        return COMPONENT_POOL[name]

    def register(self, name: str, callable: Callable) -> ComponentNode:
        """Registers a component to the factory."""
        node = ComponentNode(name, callable)
        global COMPONENT_POOL
        COMPONENT_POOL[name] = node
        return node

    def register_all(self, lst: list[tuple[str, Callable]]):
        """Registers all components to the factory."""
        for name, component in lst:
            self.register(name, component)

    def is_ready(self) -> bool:
        """Returns whether the factory is ready."""
        global COMPONENT_POOL_READY
        return COMPONENT_POOL_READY

    def mark_ready(self):
        """Sets the factory as ready."""
        global COMPONENT_POOL_READY
        COMPONENT_POOL_READY = True

    def make(self, name: str, callback: Callable = None, *args, **kwargs):
        """Creates a component object."""
        global COMPONENT_POOL
        if name not in COMPONENT_POOL:
            if callback is not None:
                self.register(name, callback)
            else:
                raise ValueError(f"Component {name} not found in factory and no callable sent.")
        try:
            node = COMPONENT_POOL[name]
        except KeyError:
            raise ValueError(f"Component {name} not found in factory.")
        return node.call(*args, **kwargs)




# register all components
#class CallableClass:
#    def __init__(self, test: str):
#        self.test = test
#        print(f"CallableClass created; {test}")
#
#    def __str__(self):
#        return self.test




#factory = ComponentFactory()
#factory.register_all([("TestComponent", CallableClass)])
#component: CallableClass = factory.make("TestComponent", None, *["test"])

