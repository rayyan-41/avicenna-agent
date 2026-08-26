"""Central configuration: env resolution, MCP config, user config.

Three things about this module are deliberate, because each was a defect:

* **Nothing here writes to stdout.** stdout belongs to the NDJSON wire
  protocol. This module used to hold a module-level ``rich`` Console and print
  through it from six places, including an import-time check that fired
  whenever the legacy ``GOOGLE_API_KEY`` was unset — which, since the provider
  is Mistral, is essentially always. The bridge redirects ``sys.stdout`` to
  stderr and that contained it, but the containment was the only thing standing
  between an ordinary import and a desynced frontend parser. Diagnostics go to
  stderr through ``warn``.
* **No import-time side effects.** Importing configuration should not emit,
  prompt or decide anything.
* **Every file operation names its encoding.** The default on Windows is
  cp1252, so a vault path with a non-ASCII character raised
  ``UnicodeEncodeError`` on save — which was then swallowed into a console
  print, silently failing to persist the file that holds the API key.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv

from avicenna.mcp.mcp_config_schema import MCPConfiguration


def warn(message: str) -> None:
    """Report a configuration problem on stderr, never stdout."""
    print(f"avicenna: {message}", file=sys.stderr)


# The repository root: avicenna/config.py -> avicenna/ -> ROOT.
#
# This was `parent.parent.parent`, carried over from a `src/` layout that no
# longer exists, so it resolved to the directory *above* the checkout and
# `load_dotenv` looked for `.env` one level too high. The README tells users to
# put their key in a project-root `.env`; that file was never read.
BASE_DIR = Path(__file__).resolve().parent.parent

env_path = BASE_DIR / ".env"
load_dotenv(env_path)


class Config:
    """Central configuration.

    All application settings should be accessed via this class, never by
    calling os.getenv() directly in other files.
    """

    LLM_PROVIDER: str = os.getenv("AVICENNA_PROVIDER", "mistral")
    MISTRAL_API_KEY: str | None = os.getenv("MISTRAL_API_KEY")
    MISTRAL_MODEL: str = os.getenv("MISTRAL_MODEL", "mistral-large-latest")

    MCP_CONFIG_PATH = Path.home() / ".avicenna" / "mcp_config.json"
    USER_CONFIG_PATH = Path.home() / ".avicenna" / "user_config.json"

    @classmethod
    def load_mcp_config(cls) -> MCPConfiguration:
        """Load MCP configuration, creating an empty default if absent."""
        if not cls.MCP_CONFIG_PATH.exists():
            config = MCPConfiguration.default()
            try:
                config.save(cls.MCP_CONFIG_PATH)
            except OSError as exc:
                warn(f"could not create {cls.MCP_CONFIG_PATH}: {exc}")
            return config

        try:
            return MCPConfiguration.from_file(cls.MCP_CONFIG_PATH)
        except Exception as exc:  # noqa: BLE001 - malformed config is the user's
            warn(f"could not read {cls.MCP_CONFIG_PATH} ({exc}); using defaults")
            return MCPConfiguration.default()

    @classmethod
    def load_user_config(cls) -> dict[str, Any]:
        """Load user configuration (provider, model, key location, vault)."""
        if not cls.USER_CONFIG_PATH.exists():
            return {}
        try:
            raw = cls.USER_CONFIG_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            warn(f"could not read {cls.USER_CONFIG_PATH}: {exc}")
            return {}
        if not isinstance(data, dict):
            warn(f"{cls.USER_CONFIG_PATH} does not contain a JSON object; ignoring it")
            return {}
        return cast(dict[str, Any], data)

    @classmethod
    def save_user_config(cls, config: dict[str, Any]) -> None:
        """Persist user configuration atomically.

        Raises on failure. This file can hold an API key, and a silent failure
        told the caller the key was stored when it was not.
        """
        cls.USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = cls.USER_CONFIG_PATH.with_suffix(".json.part")
        tmp.write_text(
            json.dumps(config, indent=2, ensure_ascii=False),
            encoding="utf-8",
            newline="\n",
        )
        os.replace(tmp, cls.USER_CONFIG_PATH)
        cls._restrict_permissions(cls.USER_CONFIG_PATH)

    @staticmethod
    def _restrict_permissions(path: Path) -> None:
        """Best-effort owner-only permissions on a file that may hold a secret.

        POSIX mode bits are meaningless on Windows, so this is genuinely
        best-effort there and the caller must not present it as protection.
        """
        import stat

        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
