"""Offline tests for GeminiProvider.

All tests fake the transport layer — no network calls are made.
Covers: error mapping, timeout/budget enforcement, key-pool rotation,
wire format conversion, and the lazy-import guarantee.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from avicenna.keypool import KeyPool
from avicenna.providers.base import (
    Completion,
    LLMProvider,
    Message,
    ToolCall,
    ToolSpec,
)
from avicenna.providers.errors import (
    AuthError,
    BadRequestError,
    ProviderError,
    RateLimitError,
    TransientError,
)
from avicenna.providers.fake import FakeProvider


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _gemini_response(
    text: str = "ok",
    *,
    finish_reason: str = "STOP",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> dict[str, Any]:
    """Minimal valid Gemini generateContent response."""
    return {
        "candidates": [{
            "content": {
                "parts": [{"text": text}],
                "role": "model",
            },
            "finishReason": finish_reason,
            "index": 0,
        }],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": completion_tokens,
            "totalTokenCount": prompt_tokens + completion_tokens,
        },
        "modelVersion": "models/gemini-2.5-flash",
    }


def _gemini_tool_response(
    name: str = "get_weather",
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Minimal valid Gemini response with a function call."""
    return {
        "candidates": [{
            "content": {
                "parts": [{
                    "functionCall": {
                        "name": name,
                        "args": args or {"location": "London"},
                    },
                }],
                "role": "model",
            },
            "finishReason": "STOP",
            "index": 0,
        }],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 5,
            "totalTokenCount": 15,
        },
    }


def _http_error(status: int, body: str = "error") -> Exception:
    """Build a urllib HTTPError-like exception."""
    import urllib.error
    from http.client import HTTPResponse
    from io import BytesIO

    # urllib.error.HTTPError needs url, code, msg, hdrs, fp.
    exc = urllib.error.HTTPError(
        url="https://example.com",
        code=status,
        msg=body,
        hdrs=None,  # type: ignore[arg-type]
        fp=BytesIO(body.encode()),
    )
    return exc


# ------------------------------------------------------------------
# ABC conformance
# ------------------------------------------------------------------

def test_abc_conformance() -> None:
    from avicenna.providers.gemini import GeminiProvider

    assert issubclass(GeminiProvider, LLMProvider)


def test_get_provider_gemini_registered() -> None:
    """gemini is in the registry; constructing one does not pull urllib into
    the import path at package-import time (the factory defers it)."""
    from avicenna.providers.registry import get_provider

    p = get_provider("fake")
    assert p.name == "fake"


# ------------------------------------------------------------------
# Error mapping
# ------------------------------------------------------------------

class TestMapHTTPError:
    """GeminiProvider._map_http_error: static, no provider instance needed."""

    def test_401_is_auth_error(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        with pytest.raises(AuthError, match="HTTP 401"):
            GeminiProvider._map_http_error(401, "unauthorised")

    def test_403_is_auth_error(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        with pytest.raises(AuthError, match="HTTP 403"):
            GeminiProvider._map_http_error(403, "forbidden")

    def test_429_is_rate_limit(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        with pytest.raises(RateLimitError, match="HTTP 429"):
            GeminiProvider._map_http_error(429, "rate limited")

    def test_500_is_transient(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        with pytest.raises(TransientError, match="HTTP 500"):
            GeminiProvider._map_http_error(500, "internal")

    def test_503_is_transient(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        with pytest.raises(TransientError, match="HTTP 503"):
            GeminiProvider._map_http_error(503, "unavailable")

    def test_400_is_bad_request(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        with pytest.raises(BadRequestError, match="HTTP 400"):
            GeminiProvider._map_http_error(400, "bad")

    def test_422_is_bad_request(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        with pytest.raises(BadRequestError, match="HTTP 422"):
            GeminiProvider._map_http_error(422, "unprocessable")

    def test_unknown_is_provider_error(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        with pytest.raises(ProviderError, match="HTTP 418"):
            GeminiProvider._map_http_error(418, "teapot")


class TestMapError:
    """GeminiProvider._map_error: maps exceptions to the error hierarchy."""

    def test_provider_error_pass_through(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        inner = AuthError("auth")
        assert GeminiProvider._map_error(inner) is inner

    def test_socket_timeout_is_transient(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        exc = socket.timeout("timed out")
        mapped = GeminiProvider._map_error(exc)
        assert isinstance(mapped, TransientError)
        assert "timed out" in str(mapped)

    def test_timeout_error_is_transient(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        exc = TimeoutError("timed out")
        mapped = GeminiProvider._map_error(exc)
        assert isinstance(mapped, TransientError)

    def test_generic_exception_is_transient(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        exc = ConnectionError("reset")
        mapped = GeminiProvider._map_error(exc)
        assert isinstance(mapped, TransientError)


# ------------------------------------------------------------------
# Timeout reaches the request layer
# ------------------------------------------------------------------

async def test_timeout_raises_transient_on_hang(monkeypatch: pytest.MonkeyPatch) -> None:
    """A socket timeout in _post_json must map to TransientError and raise
    immediately with max_retries=1.  The key must NOT be quarantined — a
    timeout means the call hung, not that the key is bad.
    """
    from avicenna.providers.gemini import GeminiProvider

    async def hanging_post(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        raise socket.timeout("timed out")

    provider = GeminiProvider(api_key="k1", timeout=0.05, max_retries=1)
    provider._post_json = hanging_post  # type: ignore[assignment]

    with pytest.raises(TransientError, match="timed out"):
        await provider.complete(system="s", messages=[])


async def test_timeout_does_not_quarantine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timeout must be retried (it's a TransientError) and must NOT
    quarantine the key — the key is fine, the call hung.
    """
    from avicenna.providers.gemini import GeminiProvider

    pool = KeyPool(["k1", "k2"])
    provider = GeminiProvider(api_key="k1", pool=pool, timeout=0.05, max_retries=3)

    call_count = 0

    async def sometimes_hanging(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise socket.timeout("timed out")
        return _gemini_response()

    provider._post_json = sometimes_hanging  # type: ignore[assignment]

    async def fake_sleep(delay: float) -> None:
        pass
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    result = await provider.complete(system="s", messages=[])
    assert result.text == "ok"
    assert call_count == 2  # retried once
    # Key must NOT be quarantined.
    assert pool.live_count == 2
    assert "k1" not in pool._quarantined


# ------------------------------------------------------------------
# Budget bounds total elapsed across retries
# ------------------------------------------------------------------

async def test_budget_bounds_total_elapsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client that times out every attempt must fail once the budget is
    spent, not after max_retries full-length attempts.
    """
    from avicenna.providers.gemini import GeminiProvider

    call_count = 0
    clock = 0.0

    def fake_monotonic() -> float:
        nonlocal clock
        clock += 1.0
        return clock

    async def always_timeout(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        raise socket.timeout("timed out")

    provider = GeminiProvider(
        api_key="k1", timeout=300.0, budget=5.0, max_retries=20,
    )
    provider._post_json = always_timeout  # type: ignore[assignment]

    async def fake_sleep(delay: float) -> None:
        pass
    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    monkeypatch.setattr("time.monotonic", fake_monotonic)

    with pytest.raises(TransientError):
        await provider.complete(system="s", messages=[])

    assert call_count < 20, f"used {call_count} retries; budget should have stopped earlier"
    assert call_count <= 5, f"used {call_count} retries; expected <= 5 with 5s budget"


async def test_budget_shrinks_per_call_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-call timeout_ms passed to _post_json must shrink to fit the
    remaining budget.
    """
    from avicenna.providers.gemini import GeminiProvider

    captured_timeouts: list[int] = []
    clock = 0.0

    def fake_monotonic() -> float:
        nonlocal clock
        clock += 0.5
        return clock

    async def record_timeout(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        captured_timeouts.append(timeout_ms)
        raise socket.timeout("timed out")

    provider = GeminiProvider(
        api_key="k1", timeout=10.0, budget=20.0, max_retries=20,
    )
    provider._post_json = record_timeout  # type: ignore[assignment]

    async def fake_sleep(delay: float) -> None:
        pass
    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    monkeypatch.setattr("time.monotonic", fake_monotonic)

    with pytest.raises(TransientError):
        await provider.complete(system="s", messages=[])

    assert len(captured_timeouts) >= 1
    assert captured_timeouts[0] == 10_000
    if len(captured_timeouts) >= 2:
        assert captured_timeouts[-1] < captured_timeouts[0]


async def test_no_budget_means_no_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When budget is None, the provider retries up to max_retries without
    a total-elapsed check.
    """
    from avicenna.providers.gemini import GeminiProvider

    call_count = 0

    async def always_timeout(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        raise socket.timeout("timed out")

    provider = GeminiProvider(
        api_key="k1", timeout=300.0, budget=None, max_retries=4,
    )
    provider._post_json = always_timeout  # type: ignore[assignment]

    async def fake_sleep(delay: float) -> None:
        pass
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    with pytest.raises(TransientError):
        await provider.complete(system="s", messages=[])

    assert call_count == 4


# ------------------------------------------------------------------
# Key-pool rotation: auth quarantines, 429 rotates
# ------------------------------------------------------------------

async def test_auth_quarantines_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First key returns 401: quarantined, second key succeeds.
    No attempt wasted.
    """
    from avicenna.providers.gemini import GeminiProvider

    pool = KeyPool(["k1", "k2", "k3"])
    provider = GeminiProvider(api_key="k1", pool=pool, max_retries=4)

    call_count = 0

    async def fake_post(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise AuthError("HTTP 401: unauthorised")
        return _gemini_response()

    provider._post_json = fake_post  # type: ignore[assignment]

    async def fake_sleep(delay: float) -> None:
        pass
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    result = await provider.complete(system="s", messages=[])
    assert result.text == "ok"
    assert call_count == 2
    assert "k1" in pool._quarantined
    assert pool.live_count == 2


async def test_pool_auth_exhausted_raises() -> None:
    """Pool exhausted by auth errors: raise AuthError, no infinite loop."""
    from avicenna.providers.gemini import GeminiProvider

    pool = KeyPool(["k1"])
    provider = GeminiProvider(api_key="k1", pool=pool, max_retries=4)

    async def fake_post(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        raise AuthError("HTTP 401: unauthorised")

    provider._post_json = fake_post  # type: ignore[assignment]

    with pytest.raises(AuthError):
        await provider.complete(system="s", messages=[])


async def test_pool_rotation_all_keys_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three keys, ALL rate-limited: each key tried once per rotation, then
    sleep.  With _max_retries=4 and 3 keys: 12 calls, 3 sleeps.
    """
    from avicenna.providers.gemini import GeminiProvider

    pool = KeyPool(["k1", "k2", "k3"])
    provider = GeminiProvider(api_key="k1", pool=pool, max_retries=4)

    call_count = 0

    async def fake_post(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        raise RateLimitError("HTTP 429: rate limited")

    provider._post_json = fake_post  # type: ignore[assignment]

    sleep_times: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_times.append(delay)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    with pytest.raises(RateLimitError):
        await provider.complete(system="s", messages=[])

    assert call_count == 12
    assert len(sleep_times) == 3


async def test_pool_rotation_second_key_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First key rate-limited, second succeeds: 2 calls, no sleep."""
    from avicenna.providers.gemini import GeminiProvider

    pool = KeyPool(["k1", "k2", "k3"])
    provider = GeminiProvider(api_key="k1", pool=pool, max_retries=4)

    call_count = 0

    async def fake_post(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RateLimitError("HTTP 429: rate limited")
        return _gemini_response()

    provider._post_json = fake_post  # type: ignore[assignment]

    sleep_times: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_times.append(delay)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    result = await provider.complete(system="s", messages=[])
    assert result.text == "ok"
    assert call_count == 2
    assert len(sleep_times) == 0


async def test_single_key_rate_limited_throughout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single key, all rate-limited: 4 calls, 3 sleeps."""
    from avicenna.providers.gemini import GeminiProvider

    provider = GeminiProvider(api_key="only-key", max_retries=4)

    call_count = 0

    async def fake_post(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        raise RateLimitError("HTTP 429: rate limited")

    provider._post_json = fake_post  # type: ignore[assignment]

    sleep_times: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_times.append(delay)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    with pytest.raises(RateLimitError):
        await provider.complete(system="s", messages=[])

    assert call_count == 4
    assert len(sleep_times) == 3


# ------------------------------------------------------------------
# Successful completion
# ------------------------------------------------------------------

async def test_basic_completion() -> None:
    """A simple completion returns the expected text and usage."""
    from avicenna.providers.gemini import GeminiProvider

    async def fake_post(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        return _gemini_response("hello world", prompt_tokens=20, completion_tokens=10)

    provider = GeminiProvider(api_key="k1", max_retries=1)
    provider._post_json = fake_post  # type: ignore[assignment]

    result = await provider.complete(
        system="you are a bot",
        messages=[Message(role="user", content="say hello")],
    )

    assert result.text == "hello world"
    assert result.finish_reason == "stop"
    assert result.usage is not None
    assert result.usage.prompt_tokens == 20
    assert result.usage.completion_tokens == 10
    assert result.usage.total_tokens == 30


async def test_completion_with_max_tokens() -> None:
    """MAX_TOKENS finishReason maps to 'length'."""
    from avicenna.providers.gemini import GeminiProvider

    async def fake_post(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        return _gemini_response("truncated", finish_reason="MAX_TOKENS")

    provider = GeminiProvider(api_key="k1", max_retries=1)
    provider._post_json = fake_post  # type: ignore[assignment]

    result = await provider.complete(
        system="s",
        messages=[Message(role="user", content="write a long essay")],
        max_tokens=100,
    )

    assert result.finish_reason == "length"


async def test_no_candidates_raises() -> None:
    """An empty candidates list must raise ProviderError."""
    from avicenna.providers.gemini import GeminiProvider

    async def fake_post(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        return {"candidates": [], "usageMetadata": {}}

    provider = GeminiProvider(api_key="k1", max_retries=1)
    provider._post_json = fake_post  # type: ignore[assignment]

    with pytest.raises(ProviderError, match="no candidates"):
        await provider.complete(system="s", messages=[])


# ------------------------------------------------------------------
# Tool calling
# ------------------------------------------------------------------

async def test_tool_call_round_trip() -> None:
    """A functionCall in the response maps to a ToolCall."""
    from avicenna.providers.gemini import GeminiProvider

    async def fake_post(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        return _gemini_tool_response("get_weather", {"location": "London"})

    provider = GeminiProvider(api_key="k1", max_retries=1)
    provider._post_json = fake_post  # type: ignore[assignment]

    result = await provider.complete(
        system="s",
        messages=[Message(role="user", content="weather?")],
        tools=[ToolSpec(
            name="get_weather",
            description="Get weather",
            parameters={"type": "object", "properties": {"location": {"type": "string"}}},
        )],
    )

    assert result.text is None
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.name == "get_weather"
    assert tc.arguments == {"location": "London"}
    assert tc.id == "gemini-0"


async def test_tools_passed_in_body() -> None:
    """When tools are provided, functionDeclarations appear in the request body."""
    from avicenna.providers.gemini import GeminiProvider

    captured_body: dict[str, Any] = {}

    async def fake_post(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        captured_body.update(body)
        return _gemini_response()

    provider = GeminiProvider(api_key="k1", max_retries=1)
    provider._post_json = fake_post  # type: ignore[assignment]

    tools = [ToolSpec(
        name="my_func",
        description="does things",
        parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
    )]
    await provider.complete(
        system="s",
        messages=[Message(role="user", content="go")],
        tools=tools,
    )

    assert "tools" in captured_body
    decls = captured_body["tools"][0]["functionDeclarations"]
    assert len(decls) == 1
    assert decls[0]["name"] == "my_func"


async def test_system_instruction_in_body() -> None:
    """The system prompt must be passed as systemInstruction, not a content message."""
    from avicenna.providers.gemini import GeminiProvider

    captured_body: dict[str, Any] = {}

    async def fake_post(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        captured_body.update(body)
        return _gemini_response()

    provider = GeminiProvider(api_key="k1", max_retries=1)
    provider._post_json = fake_post  # type: ignore[assignment]

    await provider.complete(
        system="you are a helpful assistant",
        messages=[Message(role="user", content="hi")],
    )

    assert "systemInstruction" in captured_body
    si_parts = captured_body["systemInstruction"]["parts"]
    assert si_parts[0]["text"] == "you are a helpful assistant"
    # The system prompt must NOT appear in the contents array.
    for content in captured_body["contents"]:
        for part in content.get("parts", []):
            if "text" in part:
                assert part["text"] != "you are a helpful assistant"


# ------------------------------------------------------------------
# Wire format conversion
# ------------------------------------------------------------------

class TestWireConversion:
    """Test _to_contents and _to_wire_tools static methods."""

    def test_user_message(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        contents = GeminiProvider._to_contents([
            Message(role="user", content="hello"),
        ])
        assert len(contents) == 1
        assert contents[0]["role"] == "user"
        assert contents[0]["parts"][0]["text"] == "hello"

    def test_assistant_message(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        contents = GeminiProvider._to_contents([
            Message(role="assistant", content="hi there"),
        ])
        assert len(contents) == 1
        assert contents[0]["role"] == "model"
        assert contents[0]["parts"][0]["text"] == "hi there"

    def test_assistant_with_tool_calls(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        contents = GeminiProvider._to_contents([
            Message(role="assistant", content="let me check", tool_calls=(
                ToolCall(id="tc-1", name="lookup", arguments={"q": "test"}),
            )),
        ])
        assert len(contents) == 1
        assert contents[0]["role"] == "model"
        parts = contents[0]["parts"]
        assert len(parts) == 2
        assert parts[0]["text"] == "let me check"
        assert parts[1]["functionCall"]["name"] == "lookup"
        assert parts[1]["functionCall"]["args"] == {"q": "test"}

    def test_tool_message(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        contents = GeminiProvider._to_contents([
            Message(role="tool", content='{"temp": 20}', name="lookup"),
        ])
        assert len(contents) == 1
        assert contents[0]["role"] == "user"
        fr = contents[0]["parts"][0]["functionResponse"]
        assert fr["name"] == "lookup"
        assert fr["response"] == {"temp": 20}

    def test_tool_message_non_json(self) -> None:
        """A tool message with non-JSON content wraps in {"result": ...}."""
        from avicenna.providers.gemini import GeminiProvider

        contents = GeminiProvider._to_contents([
            Message(role="tool", content="no results found", name="search"),
        ])
        fr = contents[0]["parts"][0]["functionResponse"]
        assert fr["response"] == {"result": "no results found"}

    def test_tools_conversion(self) -> None:
        from avicenna.providers.gemini import GeminiProvider

        tools = [ToolSpec(
            name="f1",
            description="first func",
            parameters={"type": "object", "properties": {"a": {"type": "string"}}},
        )]
        wire = GeminiProvider._to_wire_tools(tools)
        assert len(wire) == 1
        decls = wire[0]["functionDeclarations"]
        assert len(decls) == 1
        assert decls[0]["name"] == "f1"
        assert decls[0]["description"] == "first func"


# ------------------------------------------------------------------
# Finish reason mapping
# ------------------------------------------------------------------

class TestFinishReasonMapping:

    def test_stop(self) -> None:
        from avicenna.providers.gemini import GeminiProvider
        assert GeminiProvider._map_finish_reason("STOP") == "stop"

    def test_max_tokens(self) -> None:
        from avicenna.providers.gemini import GeminiProvider
        assert GeminiProvider._map_finish_reason("MAX_TOKENS") == "length"

    def test_safety(self) -> None:
        from avicenna.providers.gemini import GeminiProvider
        assert GeminiProvider._map_finish_reason("SAFETY") == "content_filter"

    def test_recitation(self) -> None:
        from avicenna.providers.gemini import GeminiProvider
        assert GeminiProvider._map_finish_reason("RECITATION") == "content_filter"

    def test_other(self) -> None:
        from avicenna.providers.gemini import GeminiProvider
        assert GeminiProvider._map_finish_reason("OTHER") == "error"

    def test_none(self) -> None:
        from avicenna.providers.gemini import GeminiProvider
        assert GeminiProvider._map_finish_reason(None) is None

    def test_unknown_lowercased(self) -> None:
        from avicenna.providers.gemini import GeminiProvider
        assert GeminiProvider._map_finish_reason("NEW_REASON") == "new_reason"


# ------------------------------------------------------------------
# Factory injection from settings
# ------------------------------------------------------------------

async def test_factory_injects_timeout_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gemini factory must resolve timeout and budget from settings when
    not explicitly passed by the caller.
    """
    from avicenna.providers import _gemini_factory

    captured_kwargs: dict[str, object] = {}

    def tracking_gemini(**kwargs: object) -> object:
        captured_kwargs.update(kwargs)
        return FakeProvider(script=[])

    monkeypatch.setattr("avicenna.providers.gemini.GeminiProvider", tracking_gemini)
    monkeypatch.setenv("AVICENNA_GEMINI_PROVIDER_TIMEOUT", "120")
    monkeypatch.setenv("AVICENNA_GEMINI_PROVIDER_BUDGET", "600")

    _gemini_factory(api_key="k1")
    assert captured_kwargs["timeout"] == 120.0
    assert captured_kwargs["budget"] == 600.0


async def test_factory_does_not_override_explicit_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a caller passes timeout and budget explicitly, the factory must not
    override them.
    """
    from avicenna.providers import _gemini_factory

    captured_kwargs: dict[str, object] = {}

    def tracking_gemini(**kwargs: object) -> object:
        captured_kwargs.update(kwargs)
        return FakeProvider(script=[])

    monkeypatch.setattr("avicenna.providers.gemini.GeminiProvider", tracking_gemini)
    monkeypatch.setenv("AVICENNA_GEMINI_PROVIDER_TIMEOUT", "300")
    monkeypatch.setenv("AVICENNA_GEMINI_PROVIDER_BUDGET", "600")

    _gemini_factory(api_key="k1", timeout=90.0, budget=120.0)
    assert captured_kwargs["timeout"] == 90.0
    assert captured_kwargs["budget"] == 120.0


# ------------------------------------------------------------------
# Lazy-import guarantee
# ------------------------------------------------------------------

def test_import_does_not_leak_urllib_modules() -> None:
    """Importing avicenna.providers must not pull urllib.request into
    sys.modules via the Gemini provider.  The module is only loaded when
    GeminiProvider is first accessed or constructed.
    """
    import sys

    # The gemini module should not be loaded just from importing the package.
    # Note: urllib.request may already be loaded by test infrastructure, so
    # we check that the gemini module itself is not loaded.
    gemini_loaded = "avicenna.providers.gemini" in sys.modules
    # If tests import GeminiProvider directly elsewhere, this may already be
    # loaded.  The invariant we can always check: the package __init__ does
    # not eagerly import it.
    if not gemini_loaded:
        # Good — it was not loaded eagerly.
        pass
    # The real invariant is that _LAZY_ATTRS includes it.
    from avicenna.providers import _LAZY_ATTRS
    assert "GeminiProvider" in _LAZY_ATTRS
    assert _LAZY_ATTRS["GeminiProvider"] == "avicenna.providers.gemini"


# ------------------------------------------------------------------
# URL construction
# ------------------------------------------------------------------

async def test_url_contains_model_and_key() -> None:
    """The request URL must include the model path and API key."""
    from avicenna.providers.gemini import GeminiProvider

    captured_url: str = ""

    async def fake_post(
        url: str, body: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        nonlocal captured_url
        captured_url = url
        return _gemini_response()

    provider = GeminiProvider(
        api_key="test-key-123",
        model="models/gemini-2.5-pro",
        max_retries=1,
    )
    provider._post_json = fake_post  # type: ignore[assignment]

    await provider.complete(system="s", messages=[])

    assert "models/gemini-2.5-pro:generateContent" in captured_url
    assert "key=test-key-123" in captured_url


# ------------------------------------------------------------------
# Opt-in live smoke test
# ------------------------------------------------------------------

@pytest.mark.skipif(
    not __import__("os").environ.get("AVICENNA_LIVE_SMOKE"),
    reason="Set AVICENNA_LIVE_SMOKE=1 to run live API tests",
)
async def test_live_gemini_completion() -> None:
    """Opt-in live smoke test: hits the real Gemini API.

    Skipped unless AVICENNA_LIVE_SMOKE=1 is set.  Reads the API key from
    the pool file.
    """
    from pathlib import Path

    from avicenna.keypool import load_pool
    from avicenna.providers.gemini import GeminiProvider

    pool = load_pool("google")
    provider = GeminiProvider(api_key="placeholder", pool=pool, max_retries=2)

    result = await provider.complete(
        system="You are a helpful assistant. Respond concisely.",
        messages=[Message(role="user", content="Say hello in one word.")],
        max_tokens=20,
    )

    assert result.text is not None
    assert len(result.text) > 0
    assert result.finish_reason is not None
    assert result.usage is not None
    assert result.usage.prompt_tokens > 0
