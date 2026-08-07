
class DecoratorMetaclass:
    def __init__(self, func, pre_mutator, post_mutator):
        self.func = func
        self.pre_mutator = pre_mutator
        self.post_mutator = post_mutator

    def __call__(self, *args, **kwargs):
        args2, kwargs2 = args, kwargs
        if self.pre_mutator:
            args2, kwargs2 = self.pre_mutator(*args, **kwargs)
        output = self.func(*args2, **kwargs2)
        if self.post_mutator:
            output = self.post_mutator(output)
        return output


class_test = DecoratorMetaclass(
    lambda x: x-1,
    lambda *args, **kwargs: ((args[0]-1,),kwargs),
    lambda x: x+1)

print (class_test(555)) # 555 - 1 - 1 + 1 = 554