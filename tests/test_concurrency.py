"""Concurrency tests for gather_sections."""

from __future__ import annotations

import asyncio

import pytest

from avicenna.concurrency import gather_sections


@pytest.mark.asyncio
async def test_concurrency_capped():
    running = 0
    peak = 0

    async def task():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return 1

    results = await gather_sections([task] * 10, concurrency=3)
    assert peak <= 3
    assert all(r == 1 for r in results if not isinstance(r, BaseException))


@pytest.mark.asyncio
async def test_one_failure_does_not_cancel_others():
    async def ok():
        await asyncio.sleep(0.01)
        return 42

    async def fail():
        raise ValueError("boom")

    tasks = [ok, fail, ok]
    results = await gather_sections(tasks, concurrency=3)
    assert results[0] == 42
    assert isinstance(results[1], ValueError)
    assert results[2] == 42


@pytest.mark.asyncio
async def test_cancel_leaves_no_pending():
    async def slow():
        await asyncio.sleep(10)

    task = asyncio.create_task(gather_sections([slow] * 5, concurrency=3))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
