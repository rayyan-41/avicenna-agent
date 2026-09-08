"""Bounded concurrent section execution.

gather_sections runs N awaitables with a semaphore cap (default from
settings.MAX_CONCURRENCY_DEFAULT).  One failed task does not cancel siblings
(return_exceptions=True).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from avicenna.settings import MAX_CONCURRENCY_DEFAULT

T = TypeVar("T")


async def gather_sections(
    tasks: list[Callable[[], Awaitable[T]]],
    concurrency: int = MAX_CONCURRENCY_DEFAULT,
) -> list[T | BaseException]:
    sem = asyncio.Semaphore(concurrency)

    async def _run(fn: Callable[[], Awaitable[T]]) -> T:
        async with sem:
            return await fn()

    return await asyncio.gather(*(_run(f) for f in tasks), return_exceptions=True)
