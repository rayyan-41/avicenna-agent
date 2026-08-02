"""Onboarding screens for first-run provider selection and API key entry."""

from __future__ import annotations

from dataclasses import dataclass

from avicenna.providers.base import Message
from avicenna.providers.errors import AuthError, RateLimitError, TransientError
from avicenna.providers.registry import get_provider


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    detail: str


async def validate_key(provider_name: str, api_key: str, model: str) -> ValidationResult:
    provider = get_provider(provider_name, api_key=api_key, model=model)
    try:
        await provider.complete(
            system="Reply with the single word: ok",
            messages=[Message(role="user", content="ping")],
            tools=None,
            temperature=0.0,
            max_tokens=5,
        )
    except AuthError:
        return ValidationResult(False, "Key rejected by the provider. Check for a typo or an expired key.")
    except RateLimitError:
        return ValidationResult(False, "Key accepted but rate limited right now. Try again shortly.")
    except TransientError as exc:
        return ValidationResult(False, f"Network problem reaching the provider: {exc}")
    finally:
        await provider.close()
    return ValidationResult(True, f"Validated against {model}.")


LOCAL_MODEL_STUB_MESSAGE = (
    "Local model support is planned for a future release. "
    "The pipeline depends on reliable structured tool calling across ten stages, "
    "and local models are still inconsistent at emitting well-formed tool calls, "
    "so shipping it now would produce silent mid-run failures."
)
