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
