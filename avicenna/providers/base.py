"""Neutral provider types and the stateless LLMProvider ABC.

The ABC's primitive is a single completion call: complete(system, messages, tools).
Fresh context is expressed by passing a one-element messages list.
Chat is a thin layer on top (Phase 3 Session).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant", "tool"]
EmbedTask = Literal[
    "RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY", "SEMANTIC_SIMILARITY",
]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]  # already json.loads()-ed


@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    name: str | None = None            # tool name, when role == "tool"
    tool_call_id: str | None = None    # correlates a tool result to its call
    tool_calls: tuple[ToolCall, ...] = ()  # assistant turns


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object, vendor-neutral


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class Completion:
    text: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    raw: Any = None
    usage: Usage | None = None
    finish_reason: str | None = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion: ...

    @abstractmethod
    async def close(self) -> None: ...


class EmbeddingProvider(ABC):
    """Abstract interface for embedding providers.

    Batch-in, batch-out, order preserved.  The batch form is the primitive
    because the vault index embeds thousands of texts per run.
    """

    name: str
    dimensions: int

    @abstractmethod
    async def embed(
        self,
        texts: Sequence[str],
        *,
        task: EmbedTask = "RETRIEVAL_DOCUMENT",
    ) -> list[list[float]]: ...

    async def embed_one(
        self,
        text: str,
        *,
        task: EmbedTask = "RETRIEVAL_DOCUMENT",
    ) -> list[float]:
        """Convenience wrapper around the batch primitive."""
        results = await self.embed([text], task=task)
        return results[0]

    @abstractmethod
    async def close(self) -> None: ...


__all__ = [
    "Role", "ToolCall", "Message", "ToolSpec", "Usage", "Completion",
    "LLMProvider", "EmbedTask", "EmbeddingProvider",
]
