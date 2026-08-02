"""EventBus to Textual bridge.

Uses post_message (not call_from_thread) to forward pipeline events
into Textual's message queue.
"""

from __future__ import annotations

import asyncio

from textual.message import Message
from textual.message_pump import MessagePump

from avicenna.bus import EventBus, drain
from avicenna.events import Event


class EventMessage(Message):
    """One pipeline Event, delivered on the Textual message queue."""

    def __init__(self, event: Event) -> None:
        self.event: Event = event
        super().__init__()


async def pump_bus(bus: EventBus, target: MessagePump) -> None:
    """Forward every bus event to `target` as an EventMessage, until close()."""
    queue: asyncio.Queue[Event | None] = bus.subscribe()
    async for event in drain(queue):
        target.post_message(EventMessage(event))
