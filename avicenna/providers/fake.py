"""Fake provider for deterministic offline testing.

The load-bearing test seam for all later phases.
Records every call into self.calls so tests can assert fresh-context
and verify correct parameter passing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from avicenna.providers.base import Completion, LLMProvider, Message, ToolSpec


class FakeProvider(LLMProvider):
    """Returns scripted completions; records every call."""

    name = "fake"

    def __init__(
        self,
        script: list[Completion] | Callable[[str, list[Message]], Completion] | None = None,
    ) -> None:
        self.script = script or []
        self.calls: list[dict[str, Any]] = []
        self._idx = 0
        self._closed = False

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion:
        self.calls.append({
            "system": system, "messages": list(messages),
            "tools": tools, "temperature": temperature, "max_tokens": max_tokens,
        })
        if callable(self.script):
            return self.script(system, messages)
        completion = self.script[self._idx]
        self._idx += 1
        return completion

    async def close(self) -> None:
        self._closed = True
