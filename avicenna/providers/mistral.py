"""Mistral backend implementing the stateless LLMProvider ABC.

Verified against mistralai v2.8.0 (installed 2026-08-02).
Import path: from mistralai.client import Mistral.

When a KeyPool is provided, each complete() call selects a key via round-robin.
On RateLimitError with multiple live keys, the provider tries the next key
immediately instead of sleeping — that is the entire point of a pool. On
AuthError (401/403), the offending key is quarantined and, if other keys remain
live, the call retries with the next one. A single-key pool behaves exactly
like the legacy single-key path: backoff on rate-limit, immediate raise on
auth failure.

Key rotation and retry have separate budgets.  Within one attempt the provider
cycles through every live key without sleeping; only once every live key has
been tried does it sleep and advance to the next attempt.  This prevents a
burst of rate-limited rotations from exhausting the retry budget in
milliseconds — exactly what happens when a 40-heading parallel fan-out hits
the provider simultaneously.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from typing import TYPE_CHECKING, Any, cast

import httpx
from mistralai.client import Mistral as MistralClient
from mistralai.client.models import (
    AssistantMessage,
    ChatCompletionRequestMessage,
    ChatCompletionRequestToolTypedDict,
    FunctionCall,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from mistralai.client.models import ToolCall as WireToolCall

# `Unset` is the class behind the SDK's UNSET sentinel. mistralai re-exports
# only the UNSET instance from `mistralai.client.types`, so the class itself
# has to come from the defining module for isinstance narrowing.
from mistralai.client.types.basemodel import Unset

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

if TYPE_CHECKING:
    from avicenna.keypool import KeyPool

_MAX_RETRIES = 4
_BASE_DELAY = 1.0


class MistralProvider(LLMProvider):
    """Mistral completion backend with retry, error mapping, and key pooling.

    Accepts an optional KeyPool alongside the legacy single api_key. When pooled,
    each complete() call rotates to the next key. The pool is the caller's
    responsibility — this class only selects keys and quarantines bad ones.
    """

    name = "mistral"

    def __init__(
        self,
        api_key: str,
        model: str = "mistral-large-latest",
        timeout: float = 600.0,
        max_retries: int = _MAX_RETRIES,
        pool: KeyPool | None = None,
    ) -> None:
        self._model = model
        self._max_retries = max_retries
        self._pool = pool
        # timeout_ms is the SDK's parameter name (int, milliseconds). We store
        # it as such so every client construction and per-call site can pass it
        # directly without repeated conversion.  Default is 600s (10 min).
        # The budget's job is to bound a hung call, not a slow one: a section
        # generating ~1,000 words must never hit it, while a call that has
        # genuinely hung should be killed in minutes rather than hours.
        self._timeout_ms: int = int(timeout * 1000)
        # Lazily-built clients, keyed by the API key string. When pooled, each
        # key gets its own client so we never re-create one in a hot loop.
        self._clients: dict[str, MistralClient] = {
            api_key: MistralClient(api_key=api_key, timeout_ms=self._timeout_ms)
        }
        self._default_key = api_key

    def _get_client(self, api_key: str) -> MistralClient:
        """Return a cached client for the given key, building one if needed."""
        client = self._clients.get(api_key)
        if client is None:
            client = MistralClient(api_key=api_key, timeout_ms=self._timeout_ms)
            self._clients[api_key] = client
        return client

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion:
        wire_messages: list[ChatCompletionRequestMessage] = [
            SystemMessage(content=system)
        ]
        wire_messages += self._to_wire_messages(messages)
        wire_tools = self._to_wire_tools(tools) if tools else None

        # Select the initial key: pool round-robin or the legacy single key.
        current_key = await self._pool.next() if self._pool else self._default_key

        last_exc: Exception | None = None
        attempt = 0
        # Keys tried during the current attempt.  Cleared on each new attempt.
        tried_keys: set[str] = {current_key}
        # Safety bound: even with key rotation the loop cannot spin more than
        # live_count times per attempt without sleeping.
        rotation = 0
        max_rotations = (
            self._pool.live_count * self._max_retries if self._pool
            else self._max_retries
        )

        while attempt < self._max_retries:
            if rotation >= max_rotations:
                break
            rotation += 1

            client = self._get_client(current_key)
            try:
                response = await client.chat.complete_async(
                    model=self._model,
                    messages=wire_messages,
                    tools=wire_tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_ms=self._timeout_ms,
                )
            except Exception as exc:
                mapped = self._map_error(exc)

                # Auth failure on a pooled key: quarantine and move to the next
                # live key without consuming an attempt.  The key is bad; the
                # attempt did not get a fair shot.  When the pool is exhausted,
                # raise — there is nothing left to try.
                if isinstance(mapped, AuthError) and self._pool:
                    self._pool.quarantine(current_key, str(mapped))
                    if not self._pool.exhausted:
                        current_key = await self._pool.next()
                        tried_keys.add(current_key)
                        continue
                    raise mapped

                # Rate limit on a pooled key with more live keys available:
                # try an untried live key immediately without consuming an
                # attempt.  Once every live key has been tried, sleep with
                # backoff and start a fresh rotation.  This is the pool doing
                # its job — spreading a burst across keys before falling back
                # to timed retry.
                if isinstance(mapped, RateLimitError) and self._pool and self._pool.live_count > 1:
                    rotated = False
                    for _ in range(self._pool.live_count):
                        candidate = await self._pool.next()
                        if candidate not in tried_keys:
                            current_key = candidate
                            tried_keys.add(current_key)
                            rotated = True
                            break
                    if rotated:
                        continue
                    # Every live key tried in this attempt — sleep and advance.
                    if attempt >= self._max_retries - 1:
                        raise mapped
                    delay = (
                        mapped.retry_after
                        if mapped.retry_after is not None
                        else _BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
                    )
                    await asyncio.sleep(delay)
                    last_exc = mapped
                    attempt += 1
                    tried_keys.clear()
                    rotation = 0
                    current_key = await self._pool.next()
                    tried_keys.add(current_key)
                    continue

                # Single-key path (or pool exhausted): standard retry logic.
                # This is byte-for-byte identical to the pre-pool behaviour.
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
                attempt += 1
                continue

            choice = response.choices[0]
            finish = choice.finish_reason

            message = choice.message
            if message is None:
                # complete() is non-streaming, so the API always populates
                # `message`; the SDK types it Optional because the same choice
                # model is reused for streaming deltas (`messages`).
                raise ProviderError("provider returned a choice with no message")

            # content is OptionalNullable[str | list[ContentChunk]]: it may be
            # the SDK's UNSET sentinel, which is not a string. Narrow it here so
            # the neutral Completion only ever carries str | None.
            content = message.content
            text: str | None
            if isinstance(content, Unset):
                text = None
            elif isinstance(content, list):
                text = "".join(
                    chunk if isinstance(chunk, str) else str(chunk)
                    for chunk in content
                )
            else:
                text = content

            tool_calls: tuple[ToolCall, ...] = ()
            if message.tool_calls:
                tc_list: list[ToolCall] = []
                for tc in message.tool_calls:
                    # The SDK's Arguments alias is `dict | str`. This code only
                    # supports the JSON-string form; a dict would raise TypeError
                    # out of json.loads. Typed as Any to keep that behaviour
                    # unchanged rather than silently altering it here.
                    raw_arguments: Any = tc.function.arguments
                    try:
                        args = json.loads(raw_arguments)
                    except json.JSONDecodeError:
                        raise BadRequestError(
                            f"tool call {tc.id!r} returned unparseable arguments"
                        )
                    tc_list.append(
                        ToolCall(
                            # The SDK types `id` Optional, but the API always
                            # sets it on a tool call; a missing id would break
                            # result correlation anyway.
                            id=cast(str, tc.id),
                            name=tc.function.name,
                            arguments=args,
                        )
                    )
                tool_calls = tuple(tc_list)

            usage = (
                Usage(
                    # UsageInfo declares these Optional[int] with a default of 0;
                    # mirror that default instead of leaking None into Usage,
                    # whose own fields are int-with-default-0.
                    prompt_tokens=response.usage.prompt_tokens or 0,
                    completion_tokens=response.usage.completion_tokens or 0,
                    total_tokens=response.usage.total_tokens or 0,
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
        self._clients.clear()

    # ------------------------------------------------------------------
    # Wire conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _to_wire_messages(
        messages: list[Message],
    ) -> list[ChatCompletionRequestMessage]:
        out: list[ChatCompletionRequestMessage] = []
        for m in messages:
            if m.role == "user":
                out.append(UserMessage(content=m.content))
            elif m.role == "assistant":
                am = AssistantMessage(content=m.content or None)
                if m.tool_calls:
                    am.tool_calls = [
                        WireToolCall(
                            id=tc.id,
                            type="function",
                            function=FunctionCall(
                                name=tc.name,
                                arguments=json.dumps(tc.arguments),
                            ),
                        )
                        for tc in m.tool_calls
                    ]
                out.append(am)
            elif m.role == "tool":
                out.append(ToolMessage(
                    content=m.content,
                    tool_call_id=m.tool_call_id or "",
                    name=m.name or "unknown",
                ))
        return out

    @staticmethod
    def _to_wire_tools(
        tools: list[ToolSpec],
    ) -> list[ChatCompletionRequestToolTypedDict]:
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
        # Timeout from the SDK's httpx transport layer.  The key is fine — the
        # call hung — so TransientError (retryable, no quarantine) is correct.
        # Caught explicitly here so the mapping is intentional rather than
        # relying on the fallthrough.
        if isinstance(exc, httpx.TimeoutException):
            return TransientError(str(exc))
        status = getattr(exc, "status_code", None)
        # 403 is terminal: the credential is valid but not authorised for this
        # request (e.g. a model gated behind a subscription tier).  When 403
        # fell through to TransientError the provider retried a tier-restricted
        # call four times with exponential backoff — a guaranteed failure
        # presented as a network problem to the healthcheck.
        if status in (401, 403):
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
