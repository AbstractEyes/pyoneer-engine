import asyncio
from inspect import iscoroutinefunction

class Action:
    def __init__(self, name, task, on_begin=None, on_end=None):
        self.name = name
        self.task = task
        self.on_begin = on_begin
        self.on_end = on_end
        self.begin = False
        self.running = False
        self.complete = False

    async def execute(self):
        self.begin = True
        await self._run_callback(self.on_begin)

        self.running = True
        await self._run_task(self.task)
        self.running = False

        self.complete = True
        await self._run_callback(self.on_end)

    async def _run_task(self, task):
        if iscoroutinefunction(task):
            await task()
        else:
            task()

    async def _run_callback(self, callback):
        if callback:
            if iscoroutinefunction(callback):
                await callback(self)
            else:
                callback(self)

    def __str__(self):
        return (f"Action({self.name}, Begin: {self.begin}, Running: {self.running}, "
                f"Complete: {self.complete})")

class ActionQueue:
    def __init__(self):
        self.queue = []

    def add_action(self, action):
        self.queue.append(action)

    async def run(self):
        while self.queue:
            action = self.queue.pop(0)
            await action.execute()
            print(action)  # Print the status of the action after execution
