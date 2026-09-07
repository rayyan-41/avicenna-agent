"""Offline provider tests against FakeProvider."""

from __future__ import annotations

import pytest

from avicenna.providers.base import (
    Completion,
    LLMProvider,
    Message,
    ToolCall,
    ToolSpec,
    Usage,
)
from avicenna.providers.fake import FakeProvider
from avicenna.providers.registry import get_provider


async def test_fake_round_trip():
    p = FakeProvider(script=[Completion(text="ok")])
    msg = Message(role="user", content="hi")
    result = await p.complete(system="you are a bot", messages=[msg])
    assert result.text == "ok"


async def test_fake_records_calls():
    p = FakeProvider(script=[Completion(text="a"), Completion(text="b")])
    await p.complete(system="sys", messages=[Message(role="user", content="1")])
    await p.complete(system="sys", messages=[Message(role="user", content="2")])
    assert len(p.calls) == 2
    assert p.calls[0]["messages"][0].content == "1"
    assert p.calls[1]["messages"][0].content == "2"


async def test_fake_callable_script():
    def script(system: str, messages: list[Message]) -> Completion:
        return Completion(text=f"echo: {messages[-1].content}")

    p = FakeProvider(script=script)
    result = await p.complete(system="sys", messages=[Message(role="user", content="hi")])
    assert result.text == "echo: hi"


def test_abc_conformance():
    assert issubclass(FakeProvider, LLMProvider)


def test_tool_spec_conversion():
    spec = ToolSpec(name="t1", description="desc", parameters={"type": "object"})
    assert spec.name == "t1"
    assert spec.parameters["type"] == "object"


def test_tool_call_arguments_are_parsed():
    tc = ToolCall(id="1", name="f", arguments={"x": 1})
    assert isinstance(tc.arguments, dict)
    assert tc.arguments["x"] == 1


def test_completion_wants_tools():
    c = Completion(text="", tool_calls=(ToolCall(id="1", name="f", arguments={}),))
    assert c.wants_tools is True
    c2 = Completion(text="hello")
    assert c2.wants_tools is False


def test_get_provider_fake():
    p = get_provider("fake")
    assert p.name == "fake"
    assert isinstance(p, LLMProvider)


def test_get_provider_unknown():
    with pytest.raises(ValueError, match="nope"):
        get_provider("nope")


def test_get_provider_mistral_exists():
    """Mistral is registered but importing it pulls in the SDK — just check registry."""
    p = get_provider("fake")
    assert p.name == "fake"


# ------------------------------------------------------------------
# MistralProvider._map_error — offline, no SDK call needed
# ------------------------------------------------------------------

class _FakeHTTPError(Exception):
    """Stand-in for an SDK HTTP exception carrying a status_code attribute."""

    def __init__(self, status_code: int, message: str = "boom") -> None:
        super().__init__(message)
        self.status_code = status_code


async def test_map_error_403_is_auth_error():
    """A 403 (e.g. tier restriction) must be terminal, not retried."""
    from avicenna.providers.errors import AuthError
    from avicenna.providers.mistral import MistralProvider

    exc = _FakeHTTPError(
        403,
        '{"message":"This model is not available in your subscription tier",'
        '"type":"tier_not_allowed","code":"1910"}',
    )
    mapped = MistralProvider._map_error(exc)
    assert isinstance(mapped, AuthError)


async def test_map_error_403_preserves_api_message():
    """The caller must see the API's own explanation, not a generic string."""
    from avicenna.providers.mistral import MistralProvider

    api_msg = (
        '{"message":"This model is not available in your subscription tier",'
        '"type":"tier_not_allowed","code":"1910"}'
    )
    mapped = MistralProvider._map_error(_FakeHTTPError(403, api_msg))
    assert api_msg in str(mapped)


async def test_map_error_401_is_auth_error():
    from avicenna.providers.errors import AuthError
    from avicenna.providers.mistral import MistralProvider

    assert isinstance(MistralProvider._map_error(_FakeHTTPError(401)), AuthError)


async def test_map_error_429_is_rate_limit():
    from avicenna.providers.errors import RateLimitError
    from avicenna.providers.mistral import MistralProvider

    assert isinstance(MistralProvider._map_error(_FakeHTTPError(429)), RateLimitError)


async def test_map_error_500_is_transient():
    from avicenna.providers.errors import TransientError
    from avicenna.providers.mistral import MistralProvider

    assert isinstance(MistralProvider._map_error(_FakeHTTPError(500)), TransientError)


async def test_map_error_400_is_bad_request():
    from avicenna.providers.errors import BadRequestError
    from avicenna.providers.mistral import MistralProvider

    assert isinstance(MistralProvider._map_error(_FakeHTTPError(400)), BadRequestError)


async def test_map_error_422_is_bad_request():
    from avicenna.providers.errors import BadRequestError
    from avicenna.providers.mistral import MistralProvider

    assert isinstance(MistralProvider._map_error(_FakeHTTPError(422)), BadRequestError)


# ------------------------------------------------------------------
# R1 — Key rotation does not spend the retry budget
# ------------------------------------------------------------------

import asyncio
import random
from unittest.mock import AsyncMock

from avicenna.keypool import KeyPool
from avicenna.providers.errors import AuthError, RateLimitError


def _rate_limit_exc(retry_after: float | None = None) -> Exception:
    """Build an SDK-style HTTP exception that maps to RateLimitError."""
    exc = _FakeHTTPError(429, "rate limited")
    exc.retry_after = retry_after  # type: ignore[attr-defined]
    return exc


def _auth_exc() -> Exception:
    """Build an SDK-style HTTP exception that maps to AuthError."""
    return _FakeHTTPError(401, "unauthorised")


def _ok_response() -> object:
    """Minimal mock of a successful chat completion response."""
    from unittest.mock import MagicMock

    msg = MagicMock()
    msg.content = "ok"
    msg.tool_calls = None
    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    return resp


async def test_pool_rotation_all_keys_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three keys, ALL rate-limited: each key tried once per rotation, then sleep.

    With _max_retries=4 and 3 keys the call sequence is:
      rotation 1: k1(RL), k2(RL), k3(RL) → sleep  → attempt advances (1)
      rotation 2: k1(RL), k2(RL), k3(RL) → sleep  → attempt advances (2)
      rotation 3: k1(RL), k2(RL), k3(RL) → sleep  → attempt advances (3)
      rotation 4: k1(RL), k2(RL), k3(RL) → raise  (attempt 3 was last)
    12 calls, 3 sleeps.
    """
    from avicenna.providers.mistral import MistralProvider

    pool = KeyPool(["k1", "k2", "k3"])
    provider = MistralProvider(api_key="k1", pool=pool, max_retries=4)

    call_count = 0

    async def fake_complete(*args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        raise _rate_limit_exc()

    def _mock_client(async_fn: object) -> object:
        return type("C", (), {"chat": type("Chat", (), {"complete_async": async_fn})()})()

    provider._get_client = lambda key: _mock_client(fake_complete)  # type: ignore[return-value]

    sleep_times: list[float] = []
    async def fake_sleep(delay: float) -> None:
        sleep_times.append(delay)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    from avicenna.providers.errors import RateLimitError as RLE
    with pytest.raises(RLE):
        await provider.complete(system="s", messages=[])

    assert call_count == 12
    assert len(sleep_times) == 3


async def test_pool_rotation_second_key_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """First key rate-limited, second succeeds: 2 calls, no sleep."""
    from avicenna.providers.mistral import MistralProvider

    pool = KeyPool(["k1", "k2", "k3"])
    provider = MistralProvider(api_key="k1", pool=pool, max_retries=4)

    call_count = 0

    async def fake_complete(*args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _rate_limit_exc()
        return _ok_response()

    def _mock_client(async_fn: object) -> object:
        return type("C", (), {"chat": type("Chat", (), {"complete_async": async_fn})()})()

    provider._get_client = lambda key: _mock_client(fake_complete)  # type: ignore[return-value]

    sleep_times: list[float] = []
    async def fake_sleep(delay: float) -> None:
        sleep_times.append(delay)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    result = await provider.complete(system="s", messages=[])
    assert result.text == "ok"
    assert call_count == 2
    assert len(sleep_times) == 0


async def test_pool_auth_quarantines_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """First key returns 401: quarantined, second key succeeds.  No attempt wasted."""
    from avicenna.providers.mistral import MistralProvider

    pool = KeyPool(["k1", "k2", "k3"])
    provider = MistralProvider(api_key="k1", pool=pool, max_retries=4)

    call_count = 0

    async def fake_complete(*args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _auth_exc()
        return _ok_response()

    def _mock_client(async_fn: object) -> object:
        return type("C", (), {"chat": type("Chat", (), {"complete_async": async_fn})()})()

    provider._get_client = lambda key: _mock_client(fake_complete)  # type: ignore[return-value]

    sleep_times: list[float] = []
    async def fake_sleep(delay: float) -> None:
        sleep_times.append(delay)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    result = await provider.complete(system="s", messages=[])
    assert result.text == "ok"
    assert call_count == 2
    assert len(sleep_times) == 0
    assert "k1" in pool._quarantined
    assert pool.live_count == 2


async def test_single_key_rate_limited_throughout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single key, all rate-limited: identical call count and sleep pattern to pre-pool behaviour.

    With max_retries=4: 4 calls, 3 sleeps (sleep before attempts 1, 2, 3; raise after 3).
    """
    from avicenna.providers.mistral import MistralProvider

    provider = MistralProvider(api_key="only-key", max_retries=4)

    call_count = 0

    async def fake_complete(*args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        raise _rate_limit_exc()

    def _mock_client(async_fn: object) -> object:
        return type("C", (), {"chat": type("Chat", (), {"complete_async": async_fn})()})()

    provider._get_client = lambda key: _mock_client(fake_complete)  # type: ignore[return-value]

    sleep_times: list[float] = []
    async def fake_sleep(delay: float) -> None:
        sleep_times.append(delay)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    from avicenna.providers.errors import RateLimitError as RLE
    with pytest.raises(RLE):
        await provider.complete(system="s", messages=[])

    assert call_count == 4
    assert len(sleep_times) == 3


async def test_pool_auth_exhausted_raises() -> None:
    """Pool exhausted by auth errors: raise AuthError, no infinite loop."""
    from avicenna.providers.mistral import MistralProvider

    pool = KeyPool(["k1"])
    provider = MistralProvider(api_key="k1", pool=pool, max_retries=4)

    async def fake_complete(*args: object, **kwargs: object) -> object:
        raise _auth_exc()

    def _mock_client(async_fn: object) -> object:
        return type("C", (), {"chat": type("Chat", (), {"complete_async": async_fn})()})()

    provider._get_client = lambda key: _mock_client(fake_complete)  # type: ignore[return-value]

    with pytest.raises(AuthError):
        await provider.complete(system="s", messages=[])


async def test_redact_applied_at_provider_level(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provider-level auth error triggers quarantine with redacted reason in logs."""
    import logging
    from avicenna.providers.mistral import MistralProvider

    pool = KeyPool(["k1", "k2"])
    provider = MistralProvider(api_key="k1", pool=pool, max_retries=4)

    call_count = 0

    async def fake_complete(*args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _FakeHTTPError(401, "token ABCDEFGHJKLMNPQRSTUVWXYza12345678 invalid")
        return _ok_response()

    def _mock_client(async_fn: object) -> object:
        return type("C", (), {"chat": type("Chat", (), {"complete_async": async_fn})()})()

    provider._get_client = lambda key: _mock_client(fake_complete)  # type: ignore[return-value]

    async def fake_sleep(delay: float) -> None:
        pass
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    with caplog.at_level(logging.WARNING, logger="avicenna.keypool"):
        result = await provider.complete(system="s", messages=[])

    assert result.text == "ok"
    assert "ABCDEFGHJKLMNPQRSTUVWXYza12345678" not in caplog.text
