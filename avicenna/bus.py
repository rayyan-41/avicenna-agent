"""Fan-out async event bus with per-subscriber queues.

A slow subscriber cannot starve a fast one. Backpressure:
LogMessage is droppable (level debug/info), everything else blocks
the emitter.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import AsyncIterator

from avicenna.events import Event, LogMessage


class EventBus:
    def __init__(self, maxsize: int = 1000) -> None:
        self._subs: list[asyncio.Queue[Event | None]] = []
        self._maxsize = maxsize
        self._seq = 0
        self._lock = asyncio.Lock()

    def subscribe(self) -> asyncio.Queue[Event | None]:
        q: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=self._maxsize)
        self._subs.append(q)
        return q

    async def emit(self, event: Event) -> None:
        async with self._lock:
            self._seq += 1
            event = dataclasses.replace(event, seq=self._seq)
        for q in self._subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                if isinstance(event, LogMessage):
                    continue        # log spam is droppable
                await q.put(event)  # load-bearing: block

    async def close(self) -> None:
        for q in self._subs:
            await q.put(None)       # sentinel: sinks exit their loop


async def drain(q: asyncio.Queue[Event | None]) -> AsyncIterator[Event]:
    while True:
        ev = await q.get()
        if ev is None:
            return
        yield ev
