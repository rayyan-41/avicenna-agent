"""Gemini backend implementing the stateless LLMProvider ABC.

Uses the Google AI Studio REST API via the standard library (urllib in
asyncio.to_thread) — the same transport approach as google_embedding.py.
No vendor SDK is imported.

When a KeyPool is provided, each complete() call selects a key via round-robin.
Auth failure (401/403) quarantines the key and rotates without consuming an
attempt.  Rate-limit (429) rotates to an untried live key before sleeping;
only when every live key has been tried does it back off and consume an
attempt.  This is identical to MistralProvider's key-pool semantics.

A total-elapsed budget (_budget_s) bounds wall time across all retry attempts
for one logical complete() call.  Without it, repeated bounded-but-slow retries
multiply across calls — each retry restarts the per-call clock.  See
docs/HANDOFF.md "The correction that matters" for the 8,703-second run that
motivated this.

Tool calling is implemented: ToolSpec maps to Gemini's functionDeclarations,
and functionCall parts in the response map back to ToolCall.  Gemini does not
provide tool-call IDs natively — we generate synthetic ones (``gemini-{n}``)
that are stable within a single response.

Default model: gemini-3.6-flash (verified live 2026-09-08 by a real completion;
the free tier's request quota is per model per day, so which model is chosen
also decides which daily bucket the weaver spends from, suitable for long-context
generation with a 1M-token context window).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import socket
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from avicenna.providers.base import (
    Completion,
    LLMProvider,
    Message,
    ToolCall,
    ToolSpec,
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

_log = logging.getLogger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
# Verified live 2026-09-08 by an actual completion, not a model listing.
#
# This was gemini-2.5-flash, which is now a generation behind: the API's own
# 404 for the retired gemini-2.0-flash names gemini-3.6-flash as the current
# model.  The free tier's GenerateRequestsPerDayPerProjectPerModel quota is
# twenty requests **per model per day**, so the choice of model also decides
# which daily bucket the weaver spends from -- one that a few verification
# probes can exhaust.  A weaver that is out of quota degrades silently by
# design, leaving the note unwoven, so this default is worth keeping current.
#
# Configurable via the GOOGLE_COMPLETION_MODEL env var or the "gemini_model"
# key in settings.
_DEFAULT_MODEL = "models/gemini-3.6-flash"
_MAX_RETRIES = 4
_BASE_DELAY = 1.0


class GeminiProvider(LLMProvider):
    """Gemini completion backend with retry, error mapping, and key pooling.

    Accepts an optional KeyPool alongside the legacy single api_key.  When
    pooled, each complete() call rotates to the next key.  The pool is the
    caller's responsibility — this class only selects keys and quarantines
    bad ones.
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        timeout: float = 300.0,
        budget: float | None = 900.0,
        max_retries: int = _MAX_RETRIES,
        pool: KeyPool | None = None,
    ) -> None:
        self._model = model
        self._max_retries = max_retries
        self._pool = pool
        # Stored as milliseconds to match the per-call timeout parameter
        # the API expects and to avoid repeated conversion at every call site.
        self._timeout_ms: int = int(timeout * 1000)
        # Total wall-time budget for one complete() call across all retries.
        # Bounding per-call alone is not enough: each retry restarts the clock.
        # See docs/HANDOFF.md "The correction that matters".
        self._budget_s: float | None = budget
        self._default_key = api_key

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion:
        # Build the wire payload once — it is the same for every attempt.
        contents = self._to_contents(messages)
        gen_config: dict[str, Any] = {}
        if temperature is not None:
            gen_config["temperature"] = temperature
        if max_tokens is not None:
            gen_config["maxOutputTokens"] = max_tokens
        body: dict[str, Any] = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system}]},
        }
        if gen_config:
            body["generationConfig"] = gen_config
        wire_tools = self._to_wire_tools(tools) if tools else None
        if wire_tools:
            body["tools"] = wire_tools

        # Select the initial key: pool round-robin or the legacy single key.
        current_key = await self._pool.next() if self._pool else self._default_key

        last_exc: Exception | None = None
        attempt = 0
        tried_keys: set[str] = {current_key}
        # Safety bound: even with key rotation the loop cannot spin more than
        # live_count * max_retries times without sleeping.
        rotation = 0
        max_rotations = (
            self._pool.live_count * self._max_retries if self._pool
            else self._max_retries
        )
        budget_start = time.monotonic()

        while attempt < self._max_retries:
            if rotation >= max_rotations:
                break
            rotation += 1

            # Budget check: if the total elapsed time across all retries
            # exceeds the budget, stop.  Each retry restarts the per-call
            # clock, so per-call timeouts alone do not bound the total.
            if self._budget_s is not None:
                elapsed = time.monotonic() - budget_start
                if elapsed >= self._budget_s:
                    raise last_exc or TransientError("provider budget exhausted")

            # Shrink the per-call timeout to fit the remaining budget so the
            # last attempt cannot overrun it.
            call_timeout_ms = self._timeout_ms
            if self._budget_s is not None:
                remaining_s = self._budget_s - (time.monotonic() - budget_start)
                remaining_ms = int(remaining_s * 1000)
                if remaining_ms <= 0:
                    raise last_exc or TransientError("provider budget exhausted")
                call_timeout_ms = min(call_timeout_ms, remaining_ms)

            url = (
                f"{_BASE_URL}/{self._model}:generateContent"
                f"?key={current_key}"
            )
            try:
                data = await self._post_json(url, body, timeout_ms=call_timeout_ms)
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
                # backoff and start a fresh rotation.
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

            # Parse the response.
            candidates = data.get("candidates", [])
            if not candidates:
                raise ProviderError("Gemini returned no candidates")

            candidate = candidates[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])

            # Extract text from text parts.
            text_parts = [p["text"] for p in parts if "text" in p]
            text: str | None = "\n".join(text_parts) if text_parts else None

            # Map Gemini's finishReason to the neutral string.
            finish = self._map_finish_reason(candidate.get("finishReason"))

            # Extract tool calls from functionCall parts.
            tool_calls_list: list[ToolCall] = []
            for i, part in enumerate(parts):
                if "functionCall" not in part:
                    continue
                fc = part["functionCall"]
                name = fc["name"]
                # Gemini returns args as a dict; json.loads is not needed.
                raw_args = fc.get("args", {})
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        raise BadRequestError(
                            f"tool call {name!r} returned unparseable arguments"
                        )
                else:
                    args = dict(raw_args)
                tool_calls_list.append(
                    ToolCall(
                        id=f"gemini-{i}",
                        name=name,
                        arguments=args,
                    )
                )

            usage_meta = data.get("usageMetadata")
            usage: Usage | None = None
            if usage_meta:
                usage = Usage(
                    prompt_tokens=usage_meta.get("promptTokenCount", 0),
                    completion_tokens=usage_meta.get("candidatesTokenCount", 0),
                    total_tokens=usage_meta.get("totalTokenCount", 0),
                )

            return Completion(
                text=text,
                tool_calls=tuple(tool_calls_list),
                raw=data,
                usage=usage,
                finish_reason=finish,
            )

        raise last_exc or RuntimeError("unreachable")

    async def close(self) -> None:
        pass  # no persistent connections with urllib

    # ------------------------------------------------------------------
    # Wire conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _to_contents(
        messages: list[Message],
    ) -> list[dict[str, Any]]:
        """Convert neutral messages to Gemini's ``contents`` array.

        The system prompt is injected as a top-level ``systemInstruction``
        key by the caller, not as a content message — Gemini treats them
        as separate concepts with different placement guarantees.
        """
        contents: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                contents.append({
                    "role": "user",
                    "parts": [{"text": m.content}],
                })
            elif m.role == "assistant":
                parts: list[dict[str, Any]] = []
                if m.content:
                    parts.append({"text": m.content})
                if m.tool_calls:
                    for tc in m.tool_calls:
                        parts.append({
                            "functionCall": {
                                "name": tc.name,
                                "args": tc.arguments,
                            },
                        })
                if parts:
                    contents.append({"role": "model", "parts": parts})
            elif m.role == "tool":
                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": m.name or "unknown",
                            "response": (
                                json.loads(m.content)
                                if m.content.startswith("{")
                                else {"result": m.content}
                            ),
                        },
                    }],
                })
        return contents

    @staticmethod
    def _to_wire_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        """Map neutral ToolSpec to Gemini's ``tools`` array."""
        return [{
            "functionDeclarations": [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                }
                for t in tools
            ],
        }]

    @staticmethod
    def _map_finish_reason(reason: str | None) -> str | None:
        """Map Gemini's finishReason to the neutral Completion string."""
        if reason is None:
            return None
        mapping = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
            "RECITATION": "content_filter",
            "OTHER": "error",
        }
        return mapping.get(reason, reason.lower())

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------

    async def _post_json(
        self,
        url: str,
        body: dict[str, Any],
        *,
        timeout_ms: int,
    ) -> dict[str, Any]:
        """Send a JSON POST in a thread (non-blocking) with a per-call timeout.

        The timeout is passed to urlopen as seconds — it applies to the
        connection and each read operation.  A timeout maps to TransientError
        (retryable, no quarantine) because the key is fine; the call hung.
        """
        payload = json.dumps(body).encode("utf-8")
        timeout_s = timeout_ms / 1000.0

        def _do_request() -> dict[str, Any]:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    result: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                    return result
            except urllib.error.HTTPError as exc:
                raw_body = exc.read().decode("utf-8", errors="replace")
                self._map_http_error(exc.code, raw_body)
                raise  # unreachable; _map_http_error always raises
            except urllib.error.URLError as exc:
                # socket.timeout (TimeoutError) is wrapped as URLError.reason
                # on most platforms.  Check explicitly so timeouts map to
                # TransientError rather than a generic network error.
                if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                    raise TransientError(f"request timed out after {timeout_s}s") from exc
                raise TransientError(f"network error: {exc.reason}") from exc
            except TimeoutError as exc:
                # Some code paths raise TimeoutError directly (Python 3.12+).
                raise TransientError(f"request timed out after {timeout_s}s") from exc

        return await asyncio.to_thread(_do_request)

    @staticmethod
    def _map_http_error(status: int, body: str) -> None:
        """Map an HTTP status code to the provider error hierarchy.

        Raises the appropriate error; never returns.
        """
        if status in (401, 403):
            raise AuthError(f"HTTP {status}: {body}")
        if status == 429:
            raise RateLimitError(f"HTTP 429: {body}")
        if 500 <= status < 600:
            raise TransientError(f"HTTP {status}: {body}")
        if status in (400, 422):
            raise BadRequestError(f"HTTP {status}: {body}")
        raise ProviderError(f"HTTP {status}: {body}")

    @staticmethod
    def _map_error(exc: Exception) -> ProviderError:
        """Map an exception to the provider error hierarchy.

        Called from complete() when _post_json raises.  Handles both our
        own ProviderError subclasses (from _map_http_error) and unexpected
        exceptions (network, DNS, etc.).
        """
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, (socket.timeout, TimeoutError)):
            return TransientError(str(exc))
        return TransientError(str(exc))


__all__ = ["GeminiProvider"]
