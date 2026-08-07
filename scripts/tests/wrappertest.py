# success

def wrapped_class(arg1, arg2):
    def decorator(cls):
        original_init = cls.__init__

        def new_init(self, *args, **kwargs):
            # Inject decorator arguments into the instance
            self.decorator_arg1 = arg1
            self.decorator_arg2 = arg2
            # Call the original __init__ with the overridden arguments
            original_init(self, self.decorator_arg1, self.decorator_arg2)

        cls.__init__ = new_init

        if hasattr(cls, '__call__'):
            original_call = cls.__call__

            def decorated_call(self, *args, **kwargs):
                print("decorated")
                # replace the args with new args
                old_arg = self.arg1
                self.arg1 = "new arg1"
                original = original_call(self, *args, **kwargs)
                self.arg1 = old_arg
                return original

            cls._original_call = original_call
            cls.__call__ = decorated_call

        return cls

    return decorator


# Example usage
@wrapped_class("taco", "cheese")
class MyClass:
    def __init__(self, arg1, arg2):
        self.arg1 = arg1
        self.arg2 = arg2
        print("Initialized; arguments: ", arg1, arg2)

    def __call__(self, *args, **kwargs):
        print(f"Arguments: {self.arg1}, {self.arg2}")

    def test(self):
        print("test")


# Instance creation
instance = MyClass("ignored", "values")
instance()
print(type(instance))
instance.test()