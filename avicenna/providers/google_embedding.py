"""Google embedding backend implementing the stateless EmbeddingProvider ABC.

Uses the Google AI Studio REST API (no vendor SDK).  The standard library's
urllib runs inside asyncio.to_thread so nothing reachable from avicenna/bridge/
blocks the event loop.

The primary endpoint is ``batchEmbedContents`` (one HTTP call for N texts).
When the batch call fails in a way that suggests the API shape has changed,
the provider falls back to sequential ``embedContent`` calls so a working
vault never breaks because of an assumption about batching.

Configuration precedence (FLAG → ENV → FILE → DEFAULT):
    model:          GOOGLE_EMBEDDING_MODEL   → "models/gemini-embedding-2"
    dimensions:     GOOGLE_EMBEDDING_DIMENSIONS → 768
    task_type:      GOOGLE_EMBEDDING_TASK_TYPE → "RETRIEVAL_DOCUMENT" (default)
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any

from avicenna.providers.base import EmbedTask, EmbeddingProvider
from avicenna.providers.errors import (
    AuthError,
    BadRequestError,
    ProviderError,
    RateLimitError,
    TransientError,
)

_log = logging.getLogger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_MODEL = "models/gemini-embedding-2"
_DEFAULT_DIMENSIONS = 768
_MAX_RETRIES = 4
_BASE_DELAY = 1.0
_BATCH_SIZE = 100  # texts per batchEmbedContents call
_MAX_CONCURRENCY = 5  # parallel sequential calls when batch falls back


class GoogleEmbeddingProvider(EmbeddingProvider):
    """Google AI Studio embedding backend with retry and error mapping.

    Accepts a KeyPool for key rotation (single-key is the common case).
    Every request is a plain REST call via the standard library — no vendor
    SDK is imported.
    """

    name = "google"

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        dimensions: int = _DEFAULT_DIMENSIONS,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self.dimensions = dimensions
        self._max_retries = max_retries

    async def embed(
        self,
        texts: Sequence[str],
        *,
        task: EmbedTask = "RETRIEVAL_DOCUMENT",
    ) -> list[list[float]]:
        if not texts:
            return []

        # Try batch first; fall back to sequential on structural failures
        # (bad request shape, unexpected response).  Auth and rate-limit errors
        # propagate immediately — they affect sequential calls the same way.
        try:
            return await self._embed_batch(texts, task=task)
        except (AuthError, RateLimitError, TransientError):
            raise
        except BadRequestError as exc:
            _log.warning(
                "batchEmbedContents failed (%s); falling back to sequential calls",
                exc,
            )
            return await self._embed_sequential(texts, task=task)
        except ProviderError as exc:
            _log.warning(
                "batchEmbedContents failed (%s); falling back to sequential calls",
                exc,
            )
            return await self._embed_sequential(texts, task=task)

    async def close(self) -> None:
        pass  # no persistent connections with urllib

    # ------------------------------------------------------------------
    # Batch path
    # ------------------------------------------------------------------

    async def _embed_batch(
        self,
        texts: Sequence[str],
        *,
        task: EmbedTask,
    ) -> list[list[float]]:
        """Embed all texts via batchEmbedContents, chunked into batches."""
        all_vectors: list[list[float]] = []
        for start in range(0, len(texts), _BATCH_SIZE):
            chunk = texts[start : start + _BATCH_SIZE]
            vectors = await self._batch_call_with_retry(chunk, task=task)
            all_vectors.extend(vectors)
        return all_vectors

    async def _batch_call_with_retry(
        self,
        texts: Sequence[str],
        *,
        task: EmbedTask,
    ) -> list[list[float]]:
        """One batchEmbedContents call with retry logic."""
        body = {
            "requests": [
                {
                    "model": self._model,
                    "content": {"parts": [{"text": t}]},
                    "outputDimensionality": self.dimensions,
                    "taskType": task,
                }
                for t in texts
            ],
        }
        url = f"{_BASE_URL}/{self._model}:batchEmbedContents?key={self._api_key}"
        data = await self._request_with_retry(url, body)
        embeddings = data.get("embeddings", [])
        if len(embeddings) != len(texts):
            raise ProviderError(
                f"batchEmbedContents returned {len(embeddings)} embeddings "
                f"for {len(texts)} texts"
            )
        return [e["values"] for e in embeddings]

    # ------------------------------------------------------------------
    # Sequential fallback
    # ------------------------------------------------------------------

    async def _embed_sequential(
        self,
        texts: Sequence[str],
        *,
        task: EmbedTask,
    ) -> list[list[float]]:
        """Embed texts via individual embedContent calls with bounded concurrency."""
        semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
        results: list[list[float]] = [None] * len(texts)  # type: ignore[list-item]

        async def _one(idx: int, text: str) -> None:
            async with semaphore:
                results[idx] = await self._single_call_with_retry(text, task=task)

        await asyncio.gather(*(_one(i, t) for i, t in enumerate(texts)))
        return results

    async def _single_call_with_retry(
        self,
        text: str,
        *,
        task: EmbedTask,
    ) -> list[float]:
        """One embedContent call with retry logic."""
        body = {
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": self.dimensions,
            "taskType": task,
        }
        url = f"{_BASE_URL}/{self._model}:embedContent?key={self._api_key}"
        data = await self._request_with_retry(url, body)
        return list(data["embedding"]["values"])

    # ------------------------------------------------------------------
    # HTTP + retry core
    # ------------------------------------------------------------------

    async def _request_with_retry(
        self,
        url: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST JSON to the Google API with retry on transient/rate-limit errors.

        Auth errors (401/403) are terminal and never retried, matching the
        convention in mistral.py and the reason recorded in errors.py.
        """
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return await self._post_json(url, body)
            except AuthError:
                raise
            except RateLimitError as exc:
                if attempt == self._max_retries - 1:
                    raise
                delay = (
                    exc.retry_after
                    if exc.retry_after is not None
                    else _BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
                )
                _log.warning("rate limited, retrying in %.1fs (attempt %d)", delay, attempt + 1)
                await asyncio.sleep(delay)
                last_exc = exc
            except TransientError as exc:
                if attempt == self._max_retries - 1:
                    raise
                delay = _BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
                _log.warning("transient error, retrying in %.1fs (attempt %d)", delay, attempt + 1)
                await asyncio.sleep(delay)
                last_exc = exc
        raise last_exc or RuntimeError("unreachable")  # pragma: no cover

    async def _post_json(
        self,
        url: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a JSON POST request in a thread (non-blocking).

        Maps HTTP status codes to the provider error hierarchy, matching
        mistral.py's convention: 401/403 terminal, 429 retryable, 5xx retryable.
        """
        payload = json.dumps(body).encode("utf-8")

        def _do_request() -> dict[str, Any]:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                    return result
            except urllib.error.HTTPError as exc:
                raw_body = exc.read().decode("utf-8", errors="replace")
                self._map_http_error(exc.code, raw_body)
                raise  # unreachable; _map_http_error always raises
            except urllib.error.URLError as exc:
                raise TransientError(f"network error: {exc.reason}") from exc

        return await asyncio.to_thread(_do_request)

    @staticmethod
    def _map_http_error(status: int, body: str) -> None:
        """Map an HTTP status code to the provider error hierarchy.

        Raises the appropriate error; never returns.
        """
        # 401/403 are terminal — the credential is valid but not authorised.
        # See mistral.py for the full rationale.
        if status in (401, 403):
            raise AuthError(f"HTTP {status}: {body}")
        if status == 429:
            raise RateLimitError(f"HTTP 429: {body}")
        if 500 <= status < 600:
            raise TransientError(f"HTTP {status}: {body}")
        if status in (400, 422):
            raise BadRequestError(f"HTTP {status}: {body}")
        raise ProviderError(f"HTTP {status}: {body}")


__all__ = ["GoogleEmbeddingProvider"]
