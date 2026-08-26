"""Provider onboarding: validate a key, then persist it.

The frontend owns the screens; this module owns the decisions. A key is
validated with one real, cheap completion, because that is the only honest way
to tell a good key from a typo, and it is worth a handful of tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_PROVIDER = "mistral"
DEFAULT_MODEL = "mistral-large-latest"

LOCAL_MODEL_STUB_MESSAGE = (
    "Local model support is planned for a future release. "
    "The pipeline depends on reliable structured tool calling across ten stages, "
    "and local models are still inconsistent at emitting well-formed tool calls, "
    "so shipping it now would produce silent mid-run failures."
)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    detail: str


async def validate_key(
    provider_name: str, api_key: str, model: str
) -> ValidationResult:
    """One cheap real call. Maps failures to something a human can act on."""
    from avicenna.providers.base import Message
    from avicenna.providers.errors import AuthError, RateLimitError, TransientError
    from avicenna.providers.registry import get_provider

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
        return ValidationResult(False, "Key rejected. Check for a typo or an expired key.")
    except RateLimitError:
        return ValidationResult(False, "Key works but is rate limited right now. Try again shortly.")
    except TransientError as exc:
        return ValidationResult(False, f"Network problem reaching the provider: {exc}")
    except Exception as exc:  # noqa: BLE001 - surface anything else verbatim
        return ValidationResult(False, f"{type(exc).__name__}: {exc}")
    finally:
        try:
            await provider.close()
        except Exception:  # noqa: BLE001
            pass
    return ValidationResult(True, f"Validated against {model}.")


def persist_key(api_key: str, *, vault_root: Path | None = None) -> str:
    """Store a validated key and mark the install onboarded.

    Returns where the key landed ("keyring" or "file") so the frontend can tell
    the user the truth about where their secret is.
    """
    from avicenna.config import Config
    from avicenna.secrets import write_api_key

    store = write_api_key(DEFAULT_PROVIDER, api_key)
    cfg = Config.load_user_config()
    cfg.update(
        onboarded=True,
        provider=DEFAULT_PROVIDER,
        model=DEFAULT_MODEL,
        key_store=store,
    )
    if vault_root is not None:
        cfg["default_vault"] = str(vault_root)
    Config.save_user_config(cfg)
    return store


def auth_status() -> dict[str, Any]:
    """What the frontend needs to decide whether to run onboarding."""
    from avicenna.config import Config
    from avicenna.secrets import read_api_key

    cfg = Config.load_user_config()
    return {
        "configured": bool(read_api_key(DEFAULT_PROVIDER)),
        "onboarded": bool(cfg.get("onboarded")),
        "provider": cfg.get("provider", DEFAULT_PROVIDER),
        "model": cfg.get("model", DEFAULT_MODEL),
        "keyStore": cfg.get("key_store"),
    }


def build_provider() -> Any | None:
    """The configured provider, or None when the user still needs onboarding."""
    from avicenna.config import Config
    from avicenna.providers.registry import get_provider
    from avicenna.secrets import read_api_key

    key = read_api_key(DEFAULT_PROVIDER)
    if not key:
        return None
    model = Config.load_user_config().get("model", DEFAULT_MODEL)
    return get_provider(DEFAULT_PROVIDER, api_key=key, model=model)


__all__ = [
    "DEFAULT_PROVIDER", "DEFAULT_MODEL", "LOCAL_MODEL_STUB_MESSAGE",
    "ValidationResult", "validate_key", "persist_key", "auth_status",
    "build_provider",
]
