from functools import wraps
from inspect import signature

def auto_init(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        sig = signature(func)
        bound = sig.bind(self, *args, **kwargs)
        bound.apply_defaults()
        for name, value in bound.arguments.items():
            if name != 'self':
                setattr(self, name, value)
        func(self, *args, **kwargs)
    return wrapper

class MyClass:
    @auto_init
    def __init__(self, foo: callable, bar: int, baz: str = "default"):
        # type (callable, int, str) -> None
        pass

# Usage
obj = MyClass(foo=lambda x: x**2, bar=42)
print(obj.foo(2))  # Output: 4
print(obj.bar)     # Output: 42
print(obj.baz)     # Output: "default"
class MyClass:
    def __init__(self, foo: callable, bar: int, baz: str = "default"):
        self.__dict__.update({k: v for k, v in locals().items() if k != 'self'})

obj = MyClass(foo=lambda x: x**2, bar=42)
print(obj.foo(2))  # Output: 4
print(obj.bar)     # Output: 42
print(obj.baz)     # Output: "default"