"""Secret management: API key read/write/redact.

Precedence: env var (.env loaded by config), then keyring, then user_config.json.
Write prefers the OS keyring and falls back to a file the caller is told about,
because "we tried to chmod it" is not the same guarantee as a keyring and is no
guarantee at all on Windows. Keys are never stored in the repo, never logged,
never echoed.
"""

from __future__ import annotations

import os
import re

from avicenna.config import Config

SERVICE = "avicenna"
_KEYISH = re.compile(r"\b[A-Za-z0-9_\-]{24,}\b")


def redact(text: str) -> str:
    return _KEYISH.sub("***REDACTED***", text)


def read_api_key(provider: str = "mistral") -> str | None:
    env_name = f"{provider.upper()}_API_KEY"
    value = os.environ.get(env_name)
    if value:
        return value
    try:
        import keyring
        stored: str | None = keyring.get_password(SERVICE, provider)
    except Exception:
        stored = None
    if stored:
        return stored
    try:
        api_keys: dict[str, str] = Config.load_user_config().get("api_keys", {})
        return api_keys.get(provider)
    except Exception:
        return None


def write_api_key(provider: str, key: str) -> str:
    """Store a key. Returns "keyring" or "file" — where it actually landed.

    The file fallback is plain JSON in the user's home directory. It is
    chmod'ed to owner-only, but POSIX mode bits do nothing on Windows, so the
    caller must present "file" as *less* protected rather than as equivalent.
    """
    try:
        import keyring

        keyring.set_password(SERVICE, provider, key)
        return "keyring"
    except Exception:  # noqa: BLE001 - no keyring backend, or a locked one
        cfg = Config.load_user_config()
        cfg.setdefault("api_keys", {})[provider] = key
        # Deliberately not swallowed: reporting "file" while having failed to
        # write the file would tell the user their key was saved when it was not.
        Config.save_user_config(cfg)
        return "file"
