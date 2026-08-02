"""Event bus tests: fan-out, ordering, backpressure."""

from __future__ import annotations

import asyncio

import pytest

from avicenna.bus import EventBus, drain
from avicenna.events import Event, LogMessage, RunStarted, SectionCompleted


@pytest.mark.asyncio
async def test_two_subscribers_get_all():
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    for i in range(20):
        await bus.emit(RunStarted(run_id=f"r{i}"))
    await bus.close()

    items1 = [e async for e in drain(q1)]
    items2 = [e async for e in drain(q2)]
    assert len(items1) == 20
    assert len(items2) == 20
    for a, b in zip(items1, items2):
        assert a.seq == b.seq


@pytest.mark.asyncio
async def test_seq_strictly_increasing():
    bus = EventBus()
    q = bus.subscribe()
    await bus.emit(Event())
    await bus.emit(Event())
    await bus.emit(Event())
    await bus.close()
    items = [e async for e in drain(q)]
    seqs = [e.seq for e in items]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


@pytest.mark.asyncio
async def test_logmessage_droppable():
    bus = EventBus(maxsize=2)
    q = bus.subscribe()

    # Start a slow consumer in the background that ultimately drains
    collected = []

    async def slow_consumer():
        async for e in drain(q):
            collected.append(e)

    consumer_task = asyncio.create_task(slow_consumer())

    # Fill beyond capacity with log messages (droppable)
    for _ in range(5):
        await bus.emit(LogMessage(level="debug", text="drop me"))
    # Now a SectionCompleted (non-droppable) — will wait until consumer drains
    await bus.emit(SectionCompleted(index=1, heading="h"))
    await bus.close()

    await consumer_task
    # The exact count of LogMessages received depends on timing,
    # but we must have received the SectionCompleted
    assert any(isinstance(e, SectionCompleted) for e in collected)


@pytest.mark.asyncio
async def test_drain_terminates_on_sentinel():
    bus = EventBus()
    q = bus.subscribe()
    await bus.close()
    items = [e async for e in drain(q)]
    assert items == []
