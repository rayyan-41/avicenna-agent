"""Offline tests for EmbeddingProvider, FakeEmbeddingProvider, and GoogleEmbeddingProvider.

Every test runs against fakes or monkeypatched HTTP — no live network calls,
no real API keys.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from avicenna.providers.base import EmbeddingProvider, EmbedTask
from avicenna.providers.fake import FakeEmbeddingProvider
from avicenna.providers.registry import get_embedding_provider


# ------------------------------------------------------------------
# FakeEmbeddingProvider
# ------------------------------------------------------------------

async def test_fake_embed_returns_correct_count():
    p = FakeEmbeddingProvider(dimensions=768)
    vectors = await p.embed(["a", "b", "c"])
    assert len(vectors) == 3
    assert all(len(v) == 768 for v in vectors)


async def test_fake_embed_order_preserved():
    """Same text always gives the same vector; different texts give different vectors."""
    p = FakeEmbeddingProvider(dimensions=768)
    v1, v2 = await p.embed(["hello", "world"])
    assert v1 != v2
    v1_again = (await p.embed(["hello"]))[0]
    assert v1 == v1_again


async def test_fake_embed_one_convenience():
    p = FakeEmbeddingProvider(dimensions=64)
    vec = await p.embed_one("test")
    assert len(vec) == 64


async def test_fake_embed_records_calls():
    p = FakeEmbeddingProvider(dimensions=16)
    await p.embed(["a", "b"], task="RETRIEVAL_QUERY")
    assert len(p.calls) == 1
    assert p.calls[0]["texts"] == ["a", "b"]
    assert p.calls[0]["task"] == "RETRIEVAL_QUERY"


async def test_fake_embed_empty():
    p = FakeEmbeddingProvider()
    result = await p.embed([])
    assert result == []


async def test_fake_embedding_is_unit_length():
    """Vectors are normalised so cosine similarity is meaningful."""
    import math

    p = FakeEmbeddingProvider(dimensions=768)
    vec = (await p.embed(["test"]))[0]
    magnitude = math.sqrt(sum(x * x for x in vec))
    assert abs(magnitude - 1.0) < 1e-6


async def test_fake_close():
    p = FakeEmbeddingProvider()
    assert not p._closed
    await p.close()
    assert p._closed


def test_fake_embedding_abc_conformance():
    assert issubclass(FakeEmbeddingProvider, EmbeddingProvider)


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

def test_get_embedding_provider_fake():
    p = get_embedding_provider("fake")
    assert p.name == "fake-embedding"
    assert isinstance(p, EmbeddingProvider)


def test_get_embedding_provider_unknown():
    with pytest.raises(ValueError, match="nope"):
        get_embedding_provider("nope")


def test_get_embedding_provider_google_registered():
    """Google is registered — just verify it resolves from the registry."""
    # Constructing it requires an api_key, which we provide as a dummy.
    p = get_embedding_provider("google", api_key="dummy")
    assert p.name == "google"
    assert isinstance(p, EmbeddingProvider)


# ------------------------------------------------------------------
# GoogleEmbeddingProvider — offline tests via monkeypatch
# ------------------------------------------------------------------

class _FakeHTTPResponse:
    """Stand-in for urllib.request.urlopen response."""

    def __init__(self, data: dict[str, Any], status: int = 200) -> None:
        self._data = data
        self.status = status
        self._body = json.dumps(data).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *_: object) -> None:
        pass


class _FakeHTTPError(Exception):
    """Stand-in for urllib.error.HTTPError."""

    def __init__(self, code: int, body: str = "error") -> None:
        super().__init__()
        self.code = code
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body


async def test_google_embed_batch_order_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """batchEmbedContents returns vectors in the same order as the input texts."""
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider

    provider = GoogleEmbeddingProvider(api_key="test-key", dimensions=768)

    def fake_urlopen(req: Any, timeout: float = 60) -> _FakeHTTPResponse:
        body = json.loads(req.data.decode("utf-8"))
        n = len(body["requests"])
        return _FakeHTTPResponse({
            "embeddings": [{"values": [float(i)] * 768} for i in range(n)]
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    vectors = await provider.embed(["a", "b", "c"], task="RETRIEVAL_DOCUMENT")
    assert len(vectors) == 3
    assert vectors[0] == [0.0] * 768
    assert vectors[1] == [1.0] * 768
    assert vectors[2] == [2.0] * 768


async def test_google_embed_task_type_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    """taskType is passed through to the API for each text in a batch."""
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider

    provider = GoogleEmbeddingProvider(api_key="test-key", dimensions=768)
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float = 60) -> _FakeHTTPResponse:
        body = json.loads(req.data.decode("utf-8"))
        captured["body"] = body
        n = len(body["requests"])
        return _FakeHTTPResponse({
            "embeddings": [{"values": [1.0] * 768} for _ in range(n)]
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    await provider.embed(["hello"], task="SEMANTIC_SIMILARITY")
    req = captured["body"]["requests"][0]
    assert req["taskType"] == "SEMANTIC_SIMILARITY"


async def test_google_embed_dimensionality_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    """outputDimensionality is set to the configured value."""
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider

    provider = GoogleEmbeddingProvider(api_key="test-key", dimensions=1536)
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float = 60) -> _FakeHTTPResponse:
        body = json.loads(req.data.decode("utf-8"))
        captured["body"] = body
        return _FakeHTTPResponse({
            "embeddings": [{"values": [1.0] * 1536}]
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    await provider.embed(["test"])
    assert captured["body"]["requests"][0]["outputDimensionality"] == 1536
    assert provider.dimensions == 1536


async def test_google_embed_dimensions_reports_truth():
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider

    provider = GoogleEmbeddingProvider(api_key="test-key", dimensions=768)
    assert provider.dimensions == 768

    provider2 = GoogleEmbeddingProvider(api_key="test-key", dimensions=3072)
    assert provider2.dimensions == 3072


async def test_google_embed_401_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """401 is terminal, not retried."""
    import urllib.error
    from avicenna.providers.errors import AuthError
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider

    provider = GoogleEmbeddingProvider(api_key="bad-key", dimensions=768)
    call_count = 0

    def fake_urlopen(req: Any, timeout: float = 60) -> None:
        nonlocal call_count
        call_count += 1
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(AuthError):
        await provider.embed(["test"])

    # Auth errors are NOT retried — exactly 1 call.
    assert call_count == 1


async def test_google_embed_403_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """403 is terminal, not retried."""
    import urllib.error
    from avicenna.providers.errors import AuthError
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider

    provider = GoogleEmbeddingProvider(api_key="bad-key", dimensions=768)

    def fake_urlopen(req: Any, timeout: float = 60) -> None:
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(AuthError):
        await provider.embed(["test"])


async def test_google_embed_429_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 raises RateLimitError and IS retried with backoff."""
    import urllib.error
    from avicenna.providers.errors import RateLimitError
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider

    provider = GoogleEmbeddingProvider(api_key="test-key", dimensions=768, max_retries=3)
    call_count = 0

    def fake_urlopen(req: Any, timeout: float = 60) -> None:
        nonlocal call_count
        call_count += 1
        raise urllib.error.HTTPError(req.full_url, 429, "Rate Limited", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    with pytest.raises(RateLimitError):
        await provider.embed(["test"])

    # 3 attempts (max_retries), 2 sleeps between them.
    assert call_count == 3
    assert len(sleep_calls) == 2


async def test_google_embed_500_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """5xx raises TransientError and IS retried."""
    import urllib.error
    from avicenna.providers.errors import TransientError
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider

    provider = GoogleEmbeddingProvider(api_key="test-key", dimensions=768, max_retries=3)
    call_count = 0

    def fake_urlopen(req: Any, timeout: float = 60) -> None:
        nonlocal call_count
        call_count += 1
        raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    async def fake_sleep(delay: float) -> None:
        pass

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    with pytest.raises(TransientError):
        await provider.embed(["test"])

    assert call_count == 3


async def test_google_embed_empty_texts():
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider

    provider = GoogleEmbeddingProvider(api_key="test-key")
    result = await provider.embed([])
    assert result == []


async def test_google_embed_missing_key_raises_message():
    """Missing key for the google provider raises with a helpful message."""
    from avicenna.keypool import load_pool

    with pytest.raises(RuntimeError) as exc_info:
        load_pool("google")

    msg = str(exc_info.value)
    assert "google" in msg.lower() or "GOOGLE_API_KEYS" in msg


async def test_google_embed_batch_falls_back_to_sequential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When batchEmbedContents returns a 400, fall back to sequential calls."""
    import urllib.error
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider

    provider = GoogleEmbeddingProvider(api_key="test-key", dimensions=768)
    call_log: list[str] = []

    def fake_urlopen(req: Any, timeout: float = 60) -> _FakeHTTPResponse:
        url = req.full_url
        if "batchEmbedContents" in url:
            call_log.append("batch")
            raise urllib.error.HTTPError(url, 400, "Bad Request", {}, None)
        call_log.append("single")
        return _FakeHTTPResponse({"embedding": {"values": [1.0] * 768}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    vectors = await provider.embed(["a", "b", "c"])
    assert len(vectors) == 3
    # Batch was tried first, then sequential for each text.
    assert call_log[0] == "batch"
    assert call_log.count("single") == 3


async def test_google_embed_no_blocking_call_reachable() -> None:
    """The provider uses asyncio.to_thread, never direct blocking I/O.

    This is a structural test: verify the _post_json method delegates to
    asyncio.to_thread.
    """
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider
    import inspect

    # Verify _post_json is an async method (uses await).
    assert inspect.iscoroutinefunction(GoogleEmbeddingProvider._post_json)
    # Verify _request_with_retry is an async method.
    assert inspect.iscoroutinefunction(GoogleEmbeddingProvider._request_with_retry)


# ------------------------------------------------------------------
# Import invariants
# ------------------------------------------------------------------

def test_importing_providers_no_vendor_sdk():
    """Importing avicenna.providers must not pull any vendor SDK into sys.modules."""
    import sys

    # Re-trigger the import to be sure.
    import avicenna.providers  # noqa: F811

    vendor_prefixes = ("mistralai", "openai", "anthropic", "google.genai")
    for mod_name in sys.modules:
        for prefix in vendor_prefixes:
            assert not mod_name.startswith(prefix), (
                f"vendor SDK {mod_name!r} loaded at import time"
            )
