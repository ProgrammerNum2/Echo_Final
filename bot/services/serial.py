from __future__ import annotations
import asyncio, logging
from collections import deque
from typing import Awaitable, Callable, Hashable
log=logging.getLogger(__name__)
class SerialRunner:
    def __init__(self):
        self._queues={}
        self._tasks=set()
    def submit(self,key:Hashable,job:Callable[[],Awaitable[None]]):
        q=self._queues.get(key)
        if q is None:
            q=deque(); self._queues[key]=q
            task=asyncio.create_task(self._drain(key,q)); self._tasks.add(task); task.add_done_callback(self._tasks.discard)
        q.append(job)
    async def _drain(self,key,q):
        try:
            while q:
                try: await q.popleft()()
                except Exception: log.exception("Relay job failed")
        finally:
            self._queues.pop(key,None)
