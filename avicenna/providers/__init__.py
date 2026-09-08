"""Provider layer public surface.

Re-exports only neutral types and error classes eagerly.
No vendor SDK is imported at package-import time: concrete backends that
depend on a vendor SDK (currently MistralProvider) are resolved lazily via
the PEP 562 module-level ``__getattr__`` below, and registered under a
lazy factory so ``get_provider("mistral")`` also defers the SDK import
until a provider is actually constructed.

Embedding providers follow the same pattern: GoogleEmbeddingProvider is
behind PEP 562 lazy access and a deferred factory.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from avicenna.providers.base import (
    Completion,
    EmbedTask,
    EmbeddingProvider,
    LLMProvider,
    Message,
    Role,
    ToolCall,
    ToolSpec,
    Usage,
)
from avicenna.providers.errors import (
    AuthError,
    BadRequestError,
    ContextOverflowError,
    ProviderError,
    RateLimitError,
    TransientError,
)
from avicenna.providers.fake import FakeEmbeddingProvider, FakeProvider
from avicenna.providers.registry import (
    get_embedding_provider,
    get_provider,
    register as _register,
    register_embedding as _register_embedding,
)

if TYPE_CHECKING:  # names resolved at runtime by __getattr__, below
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider
    from avicenna.providers.mistral import MistralProvider


def _mistral_factory(**kwargs: Any) -> LLMProvider:
    """Construct a MistralProvider, importing the vendor SDK on first use.

    When the caller does not pass explicit ``timeout`` or ``budget``, the
    factory resolves them through the layered settings (env → default).  This
    is the single wiring point so every path through ``get_provider("mistral")``
    gets deadlines without each caller having to know about them.
    """
    from avicenna.providers.mistral import MistralProvider
    from avicenna.settings import (
        PROVIDER_BUDGET_DEFAULT,
        PROVIDER_TIMEOUT_DEFAULT,
        resolve_timeout,
    )

    if "timeout" not in kwargs:
        kwargs["timeout"] = resolve_timeout(
            "provider_timeout", PROVIDER_TIMEOUT_DEFAULT,
            env_name="AVICENNA_PROVIDER_TIMEOUT",
        )
    if "budget" not in kwargs:
        kwargs["budget"] = resolve_timeout(
            "provider_budget", PROVIDER_BUDGET_DEFAULT,
            env_name="AVICENNA_PROVIDER_BUDGET",
        )
    return MistralProvider(**kwargs)


def _google_embedding_factory(**kwargs: Any) -> EmbeddingProvider:
    """Construct a GoogleEmbeddingProvider (no SDK, but defer module import)."""
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider

    return GoogleEmbeddingProvider(**kwargs)


# Register known providers. The mistral entry goes in behind a factory so
# registration itself does not drag in `mistralai`.
_register("mistral", _mistral_factory)
_register("fake", FakeProvider)

# Register known embedding providers.
_register_embedding("google", _google_embedding_factory)
_register_embedding("fake", lambda **kw: FakeEmbeddingProvider(**kw))

# Attribute name -> module that defines it. Kept out of the eager import list
# because importing these modules pulls in a vendor SDK (or in the case of
# GoogleEmbeddingProvider, keeps the import lightweight).
_LAZY_ATTRS: dict[str, str] = {
    "MistralProvider": "avicenna.providers.mistral",
    "GoogleEmbeddingProvider": "avicenna.providers.google_embedding",
}


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute access for vendor-backed providers."""
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value  # cache so __getattr__ runs at most once per name
    return value


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = [
    "Role", "ToolCall", "Message", "ToolSpec", "Usage", "Completion",
    "LLMProvider", "EmbedTask", "EmbeddingProvider",
    "ProviderError", "AuthError", "RateLimitError", "TransientError",
    "BadRequestError", "ContextOverflowError",
    "MistralProvider", "FakeProvider", "FakeEmbeddingProvider",
    "GoogleEmbeddingProvider", "get_provider", "get_embedding_provider",
]
