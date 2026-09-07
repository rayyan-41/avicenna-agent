"""Fake providers for deterministic offline testing.

FakeProvider handles completions; FakeEmbeddingProvider handles embeddings.
Both record every call so tests can assert on inputs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from avicenna.providers.base import (
    Completion,
    EmbedTask,
    EmbeddingProvider,
    LLMProvider,
    Message,
    ToolSpec,
)


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


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic embeddings for offline testing.

    Generates a fixed-dimension vector for each text using a hash, so the
    result is deterministic and order is preserved.  Records every call.
    """

    name = "fake-embedding"

    def __init__(self, dimensions: int = 768) -> None:
        self.dimensions = dimensions
        self.calls: list[dict[str, Any]] = []
        self._closed = False

    async def embed(
        self,
        texts: Sequence[str],
        *,
        task: EmbedTask = "RETRIEVAL_DOCUMENT",
    ) -> list[list[float]]:
        self.calls.append({"texts": list(texts), "task": task})
        return [self._deterministic_vector(text) for text in texts]

    async def close(self) -> None:
        self._closed = True

    def _deterministic_vector(self, text: str) -> list[float]:
        """Hash-based deterministic vector; same text always gives same vector."""
        import hashlib

        h = hashlib.sha256(text.encode("utf-8")).digest()
        raw: list[float] = []
        # Generate enough bytes for the requested dimensions.
        seed = h
        while len(raw) < self.dimensions:
            for byte in seed:
                raw.append((byte - 128.0) / 128.0)
                if len(raw) >= self.dimensions:
                    break
            seed = hashlib.sha256(seed).digest()
        # Normalise to unit length so cosine similarity is meaningful.
        magnitude = sum(x * x for x in raw) ** 0.5
        if magnitude > 0:
            raw = [x / magnitude for x in raw]
        return raw
