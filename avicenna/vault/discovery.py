"""Vault discovery with four-source precedence:

1. --vault CLI flag
2. AVICENNA_VAULT env var
3. Walk up from cwd looking for AGENTS.md + .agents/
4. default_vault in ~/.avicenna/user_config.json

A wrong --vault is an error, not a fallback.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class VaultNotFound(RuntimeError):
    pass


def _looks_like_vault(path: Path) -> bool:
    return (path / "AGENTS.md").is_file() and (path / ".agents").is_dir()


def discover_vault(explicit: str | Path | None = None,
                   start: Path | None = None) -> Path:
    candidates: list[tuple[str, Path]] = []
    if explicit:
        candidates.append(("--vault", Path(explicit)))
    if env := os.environ.get("AVICENNA_VAULT"):
        candidates.append(("AVICENNA_VAULT", Path(env)))
    cursor = (start or Path.cwd()).resolve()
    for parent in [cursor, *cursor.parents]:
        if _looks_like_vault(parent):
            candidates.append(("cwd walk-up", parent))
            break
    cfg = Path.home() / ".avicenna" / "user_config.json"
    if cfg.is_file():
        data = json.loads(cfg.read_text("utf-8"))
        if default := data.get("default_vault"):
            candidates.append(("user_config.json", Path(default)))
    for origin, path in candidates:
        resolved = path.expanduser().resolve()
        if _looks_like_vault(resolved):
            return resolved
        raise VaultNotFound(
            f"{origin} points at {resolved}, which is missing AGENTS.md and/or .agents/"
        )
    raise VaultNotFound(
        "No vault found. Pass --vault PATH, set AVICENNA_VAULT, run from inside a "
        "vault, set default_vault in ~/.avicenna/user_config.json, or run "
        "`avicenna init <path>` to scaffold one."
    )
