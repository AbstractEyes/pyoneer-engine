
class Event:

    @staticmethod
    def handler(event: pygame.event.Event):
        def decorated(func):
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            return wrapper