"""Mistral backend implementing the stateless LLMProvider ABC.

Verified against mistralai v2.8.0 (installed 2026-08-02).
Import path: from mistralai.client import Mistral.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any

from mistralai.client import Mistral as MistralClient
from mistralai.client.models import (
    AssistantMessage,
    SystemMessage,
    ToolMessage,
    UserMessage,
)

from avicenna.providers.base import (
    Completion,
    LLMProvider,
    Message,
    ToolSpec,
    ToolCall,
    Usage,
)
from avicenna.providers.errors import (
    AuthError,
    BadRequestError,
    ProviderError,
    RateLimitError,
    TransientError,
)

_MAX_RETRIES = 4
_BASE_DELAY = 1.0


class MistralProvider(LLMProvider):
    """Mistral completion backend with retry and error mapping."""

    name = "mistral"

    def __init__(
        self,
        api_key: str,
        model: str = "mistral-large-latest",
        timeout: float = 120.0,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._model = model
        self._max_retries = max_retries
        self._client = MistralClient(api_key=api_key)

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion:
        wire_messages = [SystemMessage(content=system)]
        wire_messages += self._to_wire_messages(messages)
        wire_tools = self._to_wire_tools(tools) if tools else None

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = await self._client.chat.complete_async(
                    model=self._model,
                    messages=wire_messages,
                    tools=wire_tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                mapped = self._map_error(exc)
                if not isinstance(mapped, (RateLimitError, TransientError)):
                    raise mapped
                if attempt == self._max_retries - 1:
                    raise mapped
                delay = (
                    mapped.retry_after
                    if isinstance(mapped, RateLimitError) and mapped.retry_after is not None
                    else _BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
                )
                await asyncio.sleep(delay)
                last_exc = mapped
                continue

            choice = response.choices[0]
            finish = choice.finish_reason

            text = choice.message.content
            if isinstance(text, list):
                text = "".join(
                    chunk if isinstance(chunk, str) else str(chunk)
                    for chunk in text
                )

            tool_calls: tuple[ToolCall, ...] = ()
            if choice.message.tool_calls:
                tc_list: list[ToolCall] = []
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        raise BadRequestError(
                            f"tool call {tc.id!r} returned unparseable arguments"
                        )
                    tc_list.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
                tool_calls = tuple(tc_list)

            usage = (
                Usage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                )
                if response.usage
                else None
            )

            return Completion(
                text=text,
                tool_calls=tool_calls,
                raw=response,
                usage=usage,
                finish_reason=finish,
            )

        raise last_exc or RuntimeError("unreachable")

    async def close(self) -> None:
        self._client = None  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Wire conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _to_wire_messages(messages: list[Message]) -> list:
        out = []
        for m in messages:
            if m.role == "user":
                out.append(UserMessage(content=m.content))
            elif m.role == "assistant":
                am = AssistantMessage(content=m.content or None)
                if m.tool_calls:
                    tc_list = [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                        for tc in m.tool_calls
                    ]
                    am.tool_calls = tc_list
                out.append(am)
            elif m.role == "tool":
                out.append(ToolMessage(
                    content=m.content,
                    tool_call_id=m.tool_call_id or "",
                    name=m.name or "unknown",
                ))
        return out

    @staticmethod
    def _to_wire_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }}
            for t in tools
        ]

    @staticmethod
    def _map_error(exc: Exception) -> ProviderError:
        status = getattr(exc, "status_code", None)
        if status == 401:
            return AuthError(str(exc))
        if status == 429:
            retry = getattr(exc, "retry_after", None) if hasattr(exc, "retry_after") else None
            return RateLimitError(str(exc), retry_after=retry)
        if status is not None and 500 <= status < 600:
            return TransientError(str(exc))
        if status in (400, 422):
            return BadRequestError(str(exc))
        # network / dns / connection reset
        return TransientError(str(exc))
