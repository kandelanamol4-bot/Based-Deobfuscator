"""Bounded async queue: global + per-user concurrency."""
from __future__ import annotations
import asyncio


class QueueManager:
    def __init__(self, max_concurrent: int = 2):
        self._sem = asyncio.Semaphore(max_concurrent)
        self.max_concurrent = max_concurrent
        self.queued = 0

    async def acquire(self):
        self.queued += 1
        try:
            await self._sem.acquire()
        finally:
            self.queued -= 1

    def release(self):
        try:
            self._sem.release()
        except ValueError:
            pass

    def position(self) -> int:
        return self.queued
