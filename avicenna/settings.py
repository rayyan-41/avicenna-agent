"""Minimal settings resolver for the four T36 settings.

Precedence chain (highest wins):
  1. CLI flag  (overrides dict)
  2. Environment variable
  3. Scope file  (vault .agents/config.json)
  4. Built-in default

This is the slice of the layered-configuration design that words_per_heading,
provider_timeout, provider_budget and max_concurrency need.  The full design (REGISTRY, Layer
enum, config show/get/set) is on the unexecuted plan and should not be built
here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from avicenna.config import warn


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# A section agent asked for "approximately 1000 words" reliably returned six or
# seven hundred, and headings planned narrowly enough to have nothing left to
# say at nine hundred made that worse.  Both halves are prompting problems, so
# both are fixed by prompting: the target moved to the middle of the band the
# user actually wants a heading to occupy, the section prompt now states that
# band as a floor and a ceiling rather than a single soft number, and preflight
# is told to plan headings broad enough to sustain it.
WORDS_PER_HEADING_DEFAULT: int = 1500

# Every concurrent section is a live API call against a rate-limited provider.
# Six matches the comparable project the user pointed at; the upper bound is
# deliberately conservative — an unbounded value turns a config typo into a
# 429 storm with no recovery path.
#
# The APPROVED path (human gate) bypasses this ceiling: concurrency is set to
# the heading count, which is bounded by parse_preflight's 40-heading refusal.
# The clamp applies only to the CONFIGURED path (CLI flag, env var, vault
# config), where a typo has no human between it and the provider.
MAX_CONCURRENCY_DEFAULT: int = 6
MAX_CONCURRENCY_MIN: int = 1
MAX_CONCURRENCY_MAX: int = 16

# Per-call API timeout for the provider client (seconds).  300s matches the
# Mistral SDK's own implicit default (chat.py:379-383) so the explicit value
# introduces no regression.  Configurable via AVICENNA_PROVIDER_TIMEOUT env
# var or the "provider_timeout" key in vault config.
PROVIDER_TIMEOUT_DEFAULT: float = 300.0

# Total wall-time budget for one logical complete() call across all retry
# attempts, backoff included (seconds).  900s (15 min) allows 2-3 full-length
# retries at the 300s per-call default, which is enough for transient failures
# to clear.  Without it nothing bounds the total: each retry restarts the
# per-call clock, so bounded-but-slow attempts multiply across a run.  That is
# the best available explanation for the 8,703-second run — inferred from the
# code path, not measured, because the logs from that run were not kept.
# Configurable via AVICENNA_PROVIDER_BUDGET env var or "provider_budget" in
# vault config.
PROVIDER_BUDGET_DEFAULT: float = 900.0

# Semantic similarity threshold for the drift guard.  Above this cosine
# similarity, a proposed theme/type is considered equivalent to the nearest
# existing key and merged instead of minted.
#
# THIS VALUE IS INFERRED, NOT MEASURED.  It is a defensible starting point
# for gemini-embedding-2 at 768 dimensions: ``nationalism`` /
# ``national-identity`` should merge (expected >0.85), ``epistemology`` /
# ``eschatology`` must not (expected <0.70).  The right value would be
# settled by running the pairwise similarity matrix over the user's actual
# taxonomy and adjusting until both traps behave correctly.  Until then,
# 0.80 is conservative enough to avoid false merges while catching obvious
# duplicates.  A wrong threshold is diagnosable from the event stream:
# SemanticGuardDecision carries ``nearest``, ``similarity`` and
# ``threshold`` precisely so that a threshold fault is visible.
SEMANTIC_GUARD_THRESHOLD_DEFAULT: float = 0.80
SEMANTIC_GUARD_THRESHOLD_MIN: float = 0.50
SEMANTIC_GUARD_THRESHOLD_MAX: float = 0.99


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
        warn(f"could not parse {path}: {exc}")
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


def heading_word_band(target: int) -> tuple[int, int]:
    """The acceptable word range for one heading, around *target*.

    A single number reads to a model as a suggestion, and the suggestion is
    always undershot.  A floor and a ceiling do not: the floor is a thing the
    section can fail to reach, and saying so is what makes it hold.

    The band is two-thirds to four-thirds of the target, rounded to fifty, so
    the default 1500 yields 1000-2000 and any override the user sets scales
    with it rather than dragging a hardcoded range out of alignment.
    """
    low = max(50, round(target * 2 / 3 / 50) * 50)
    high = max(low + 50, round(target * 4 / 3 / 50) * 50)
    return low, high


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
        warn(f"concurrency {value} below minimum {MAX_CONCURRENCY_MIN}, clamping")
        return MAX_CONCURRENCY_MIN
    if value > MAX_CONCURRENCY_MAX:
        warn(f"concurrency {value} above maximum {MAX_CONCURRENCY_MAX}, clamping")
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


def _clamp_semantic_guard_threshold(value: float) -> float:
    """Clamp to [SEMANTIC_GUARD_THRESHOLD_MIN, SEMANTIC_GUARD_THRESHOLD_MAX]."""
    if value < SEMANTIC_GUARD_THRESHOLD_MIN:
        warn(
            f"semantic guard threshold {value} below minimum "
            f"{SEMANTIC_GUARD_THRESHOLD_MIN}, clamping"
        )
        return SEMANTIC_GUARD_THRESHOLD_MIN
    if value > SEMANTIC_GUARD_THRESHOLD_MAX:
        warn(
            f"semantic guard threshold {value} above maximum "
            f"{SEMANTIC_GUARD_THRESHOLD_MAX}, clamping"
        )
        return SEMANTIC_GUARD_THRESHOLD_MAX
    return value


def resolve_semantic_guard_threshold(
    *,
    overrides: dict[str, Any] | None = None,
    vault_config: dict[str, Any] | None = None,
) -> float:
    """Resolve the semantic guard threshold through the precedence chain.

    Precedence (highest wins):
      1. CLI flag  (overrides dict)
      2. Environment variable  ``AVICENNA_SEMANTIC_GUARD_THRESHOLD``
      3. Vault config  ``semantic_guard_threshold``
      4. Built-in default  ``SEMANTIC_GUARD_THRESHOLD_DEFAULT``

    The resolved value is clamped to
    ``[SEMANTIC_GUARD_THRESHOLD_MIN, SEMANTIC_GUARD_THRESHOLD_MAX]``.
    """
    overrides = overrides or {}
    vault_config = vault_config or {}

    # 1. CLI flag
    if "semantic_guard_threshold" in overrides:
        try:
            return _clamp_semantic_guard_threshold(
                float(overrides["semantic_guard_threshold"])
            )
        except (ValueError, TypeError):
            pass

    # 2. Environment variable
    env = os.environ.get("AVICENNA_SEMANTIC_GUARD_THRESHOLD")
    if env is not None:
        try:
            return _clamp_semantic_guard_threshold(float(env))
        except ValueError:
            pass

    # 3. Vault config
    cfg_val = vault_config.get("semantic_guard_threshold")
    if cfg_val is not None:
        try:
            return _clamp_semantic_guard_threshold(float(cfg_val))
        except (ValueError, TypeError):
            pass

    # 4. Default
    return SEMANTIC_GUARD_THRESHOLD_DEFAULT
