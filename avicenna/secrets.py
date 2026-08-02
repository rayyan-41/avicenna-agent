"""Secret management: API key read/write/redact.

Precedence: env var (.env loaded by config), then keyring, then user_config.json.
Write prefers OS keyring with 0o600 file fallback. Keys are never stored
in the repo, never logged, never echoed.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

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
        stored = keyring.get_password(SERVICE, provider)
    except Exception:
        stored = None
    if stored:
        return stored
    try:
        return Config.load_user_config().get("api_keys", {}).get(provider)
    except Exception:
        return None


def write_api_key(provider: str, key: str) -> str:
    try:
        import keyring
        keyring.set_password(SERVICE, provider, key)
        return "keyring"
    except Exception:
        cfg = Config.load_user_config()
        cfg.setdefault("api_keys", {})[provider] = key
        Config.save_user_config(cfg)
        path = Path.home() / ".avicenna" / "user_config.json"
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return "file"
