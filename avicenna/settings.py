"""Minimal settings resolver for the two T36 settings.

Precedence chain (highest wins):
  1. CLI flag  (overrides dict)
  2. Environment variable
  3. Scope file  (vault .agents/config.json)
  4. Built-in default

This is the slice of the layered-configuration design that words_per_heading
and provider_timeout need.  The full design (REGISTRY, Layer enum, config
show/get/set) is on the unexecuted plan and should not be built here.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

WORDS_PER_HEADING_DEFAULT: int = 1000

# Every concurrent section is a live API call against a rate-limited provider.
# Six matches the comparable project the user pointed at; the upper bound is
# deliberately conservative — an unbounded value turns a config typo into a
# 429 storm with no recovery path.
MAX_CONCURRENCY_DEFAULT: int = 6
MAX_CONCURRENCY_MIN: int = 1
MAX_CONCURRENCY_MAX: int = 16


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def load_vault_config(vault_root: Path | None) -> dict[str, Any]:
    """Read ``.agents/config.json`` from the vault root.

    Returns ``{}`` when the file is absent.  On a parse error writes a
    warning to stderr and returns ``{}`` — a malformed config degrades to
    defaults rather than aborting, and it says so.
    """
    if vault_root is None:
        return {}
    path = vault_root / ".agents" / "config.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARNING: could not parse {path}: {exc}", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_words_per_heading(
    *,
    template: str | None = None,
    overrides: dict[str, Any] | None = None,
    vault_config: dict[str, Any] | None = None,
) -> int:
    """Resolve the per-heading word count target through the precedence chain.

    Per-template overrides live in the vault config under
    ``"words_per_heading_overrides"`` — a dict of template name to int.
    They are checked at the FILE layer: a template override beats the global
    default, but an env var or CLI flag still wins.
    """
    overrides = overrides or {}
    vault_config = vault_config or {}

    # 1. CLI flag
    if "words_per_heading" in overrides:
        return int(overrides["words_per_heading"])

    # 2. Environment variable
    env = os.environ.get("AVICENNA_WORDS_PER_HEADING")
    if env is not None:
        try:
            return int(env)
        except ValueError:
            pass

    # 3. Per-template override in vault config
    if template:
        tpl_overrides = vault_config.get("words_per_heading_overrides")
        if isinstance(tpl_overrides, dict) and template in tpl_overrides:
            try:
                return int(tpl_overrides[template])
            except (ValueError, TypeError):
                pass

    # 3b. Global value in vault config
    cfg_val = vault_config.get("words_per_heading")
    if cfg_val is not None:
        try:
            return int(cfg_val)
        except (ValueError, TypeError):
            pass

    # 4. Default
    return WORDS_PER_HEADING_DEFAULT


def resolve_timeout(
    key: str,
    default: float | None,
    *,
    env_name: str,
    overrides: dict[str, Any] | None = None,
    vault_config: dict[str, Any] | None = None,
) -> float | None:
    """Resolve a timeout setting (provider or weaver).

    Returns ``None`` when no timeout should be applied (the default for
    weaver and gen_matrix).
    """
    overrides = overrides or {}
    vault_config = vault_config or {}

    # 1. CLI flag
    if key in overrides:
        val = overrides[key]
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    # 2. Environment variable
    env = os.environ.get(env_name)
    if env is not None:
        try:
            return float(env)
        except ValueError:
            pass

    # 3. Vault config (timeouts are user-scope but can be in vault config too)
    cfg_val = vault_config.get(key)
    if cfg_val is not None:
        try:
            return float(cfg_val)
        except (ValueError, TypeError):
            pass

    # 4. Default
    return default


def _clamp_concurrency(value: int) -> int:
    """Clamp to [MAX_CONCURRENCY_MIN, MAX_CONCURRENCY_MAX], logging when clamped."""
    if value < MAX_CONCURRENCY_MIN:
        print(
            f"WARNING: concurrency {value} below minimum {MAX_CONCURRENCY_MIN}, "
            f"clamping to {MAX_CONCURRENCY_MIN}",
            file=sys.stderr,
        )
        return MAX_CONCURRENCY_MIN
    if value > MAX_CONCURRENCY_MAX:
        print(
            f"WARNING: concurrency {value} above maximum {MAX_CONCURRENCY_MAX}, "
            f"clamping to {MAX_CONCURRENCY_MAX}",
            file=sys.stderr,
        )
        return MAX_CONCURRENCY_MAX
    return value


def resolve_concurrency(
    *,
    overrides: dict[str, Any] | None = None,
    vault_config: dict[str, Any] | None = None,
) -> int:
    """Resolve section concurrency through the precedence chain.

    Precedence (highest wins):
      1. CLI flag  (overrides dict)
      2. Environment variable  ``AVICENNA_CONCURRENCY``
      3. Vault config  ``max_concurrency``
      4. Built-in default  ``MAX_CONCURRENCY_DEFAULT``

    The resolved value is clamped to ``[MAX_CONCURRENCY_MIN, MAX_CONCURRENCY_MAX]``.
    """
    overrides = overrides or {}
    vault_config = vault_config or {}

    # 1. CLI flag
    if "max_concurrency" in overrides:
        try:
            return _clamp_concurrency(int(overrides["max_concurrency"]))
        except (ValueError, TypeError):
            pass

    # 2. Environment variable
    env = os.environ.get("AVICENNA_CONCURRENCY")
    if env is not None:
        try:
            return _clamp_concurrency(int(env))
        except ValueError:
            pass

    # 3. Vault config
    cfg_val = vault_config.get("max_concurrency")
    if cfg_val is not None:
        try:
            return _clamp_concurrency(int(cfg_val))
        except (ValueError, TypeError):
            pass

    # 4. Default
    return MAX_CONCURRENCY_DEFAULT
