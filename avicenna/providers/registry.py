"""Provider registry: maps names to constructors.

Two registries: one for LLM completions, one for embeddings.  Both follow
the same pattern — a factory callable registered by name.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from avicenna.providers.base import EmbeddingProvider, LLMProvider

_registry: dict[str, Callable[..., LLMProvider]] = {}
_embedding_registry: dict[str, Callable[..., EmbeddingProvider]] = {}


def register(name: str, factory: Callable[..., LLMProvider]) -> None:
    _registry[name] = factory


def get_provider(name: str, **kwargs: Any) -> LLMProvider:
    try:
        factory = _registry[name]
    except KeyError as exc:
        known = sorted(_registry)
        raise ValueError(
            f"unknown provider {name!r}; known: {known}"
        ) from exc
    return factory(**kwargs)


def register_embedding(
    name: str, factory: Callable[..., EmbeddingProvider]
) -> None:
    _embedding_registry[name] = factory


def get_embedding_provider(name: str, **kwargs: Any) -> EmbeddingProvider:
    try:
        factory = _embedding_registry[name]
    except KeyError as exc:
        known = sorted(_embedding_registry)
        raise ValueError(
            f"unknown embedding provider {name!r}; known: {known}"
        ) from exc
    return factory(**kwargs)
