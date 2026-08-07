from functools import wraps


def requires_super(func):
    """A decorator that marks methods as requiring a super() call when overridden."""
    func._requires_super = True
    return func

class EnsureSuperMeta(type):
    """A metaclass that enforces super() calls in methods marked with @requires_super."""
    def __init__(cls, name, bases, namespace, **kwargs):
        super().__init__(name, bases, namespace, **kwargs)

        # Check each method to see if it's marked with @requires_super
        for attr_name, attr_value in namespace.items():
            if callable(attr_value) and getattr(attr_value, '_requires_super', False):
                # If method requires super, wrap it to enforce this at runtime
                original_method = attr_value

                @wraps(original_method)
                def enforced_method(self, _original_method=original_method, _attr_name=attr_name, *args, **kwargs):
                    # Before calling the method, mark super as not called
                    if 'super_called' not in self.__dict__:
                        self.super_called = set()
                    self.super_called.discard(_attr_name)
                    result = _original_method(self, *args, **kwargs)
                    # After method call, check if super was called
                    if _attr_name not in self.super_called:
                        raise RuntimeError(f"super() was not called in overridden {_attr_name} method")
                    return result
                setattr(cls, attr_name, enforced_method)

        for base in bases:
            for attr_name in dir(base):
                if attr_name in namespace and callable(namespace[attr_name]):
                    method = namespace[attr_name]
                    if getattr(method, '_requires_super', False):
                        def wrapper(self, *args, method=method, attr_name=attr_name, **kwargs):
                            if 'super_called' not in self.__dict__:
                                self.super_called = set()
                            self.super_called.add(attr_name)
                            return method(self, *args, **kwargs)
                        setattr(cls, attr_name, wrapper)

class BaseClass(metaclass=EnsureSuperMeta):
    @requires_super
    def demo(self):
        print("Base demo method.")

class DerivedClass(BaseClass):
    def demo(self):
        super().demo()
        print("Derived demo method.")

# Correct usage
d = DerivedClass()
d.demo()

# Incorrect usage example (will raise an exception if `super().demo()` call is omitted in `DerivedClass.demo`)
