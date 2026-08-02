"""Provider layer public surface.

Re-exports only neutral types and error classes eagerly.
No vendor SDK is imported at package-import time: concrete backends that
depend on a vendor SDK (currently MistralProvider) are resolved lazily via
the PEP 562 module-level ``__getattr__`` below, and registered under a
lazy factory so ``get_provider("mistral")`` also defers the SDK import
until a provider is actually constructed.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from avicenna.providers.base import (
    Completion,
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
from avicenna.providers.fake import FakeProvider
from avicenna.providers.registry import get_provider, register as _register

if TYPE_CHECKING:  # names resolved at runtime by __getattr__, below
    from avicenna.providers.mistral import MistralProvider


def _mistral_factory(**kwargs: Any) -> LLMProvider:
    """Construct a MistralProvider, importing the vendor SDK on first use."""
    from avicenna.providers.mistral import MistralProvider

    return MistralProvider(**kwargs)


# Register known providers. The mistral entry goes in behind a factory so
# registration itself does not drag in `mistralai`.
_register("mistral", _mistral_factory)
_register("fake", FakeProvider)

# Attribute name -> module that defines it. Kept out of the eager import list
# because importing these modules pulls in a vendor SDK.
_LAZY_ATTRS: dict[str, str] = {
    "MistralProvider": "avicenna.providers.mistral",
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
    "LLMProvider",
    "ProviderError", "AuthError", "RateLimitError", "TransientError",
    "BadRequestError", "ContextOverflowError",
    "MistralProvider", "FakeProvider", "get_provider",
]
