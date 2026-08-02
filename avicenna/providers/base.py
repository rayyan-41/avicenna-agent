"""Neutral provider types and the stateless LLMProvider ABC.

The ABC's primitive is a single completion call: complete(system, messages, tools).
Fresh context is expressed by passing a one-element messages list.
Chat is a thin layer on top (Phase 3 Session).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant", "tool"]


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


__all__ = [
    "Role", "ToolCall", "Message", "ToolSpec", "Usage", "Completion",
    "LLMProvider",
]
