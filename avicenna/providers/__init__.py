"""Provider layer public surface.

Re-exports only neutral types and error classes.
No vendor SDK is imported at package-import time.
"""

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
from avicenna.providers.mistral import MistralProvider
from avicenna.providers.registry import get_provider, register as _register

# Register known providers
_register("mistral", MistralProvider)
_register("fake", FakeProvider)

__all__ = [
    "Role", "ToolCall", "Message", "ToolSpec", "Usage", "Completion",
    "LLMProvider",
    "ProviderError", "AuthError", "RateLimitError", "TransientError",
    "BadRequestError", "ContextOverflowError",
    "MistralProvider", "FakeProvider", "get_provider",
]
