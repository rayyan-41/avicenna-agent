"""Provider registry: maps names to constructors."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from avicenna.providers.base import LLMProvider

_registry: dict[str, Callable[..., LLMProvider]] = {}


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
