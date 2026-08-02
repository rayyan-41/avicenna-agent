"""Provider error hierarchy.

Only RateLimitError and TransientError are retryable.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base for all provider-layer errors."""


class AuthError(ProviderError):
    """API key rejected or expired."""


class RateLimitError(ProviderError):
    """Rate limited. retry_after is seconds until the next request is permitted."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after: float | None = retry_after


class TransientError(ProviderError):
    """Network or temporary server error. Retryable."""


class BadRequestError(ProviderError):
    """Malformed request (400/422). Not retryable."""


class ContextOverflowError(ProviderError):
    """The combined prompt exceeded the model's context window."""


__all__ = [
    "ProviderError", "AuthError", "RateLimitError", "TransientError",
    "BadRequestError", "ContextOverflowError",
]
