"""API key pool for spreading parallel completions across multiple keys.

A single note fans out to one subagent call per heading, in parallel. A 40-
heading note is 40+ completions in a burst against one API key, and Mistral's
free tier rate-limits well below that. The user may have multiple working keys
and wants the load spread across them.

There is a second, already-observed reason for a pool: one of the keys in a
user's pool may not be a valid Mistral key at all and returns 401. A pool must
survive a bad member rather than failing the run.

The pool is round-robin, advances on every call (not only on failure), and
quarantines definitively-bad keys (401/403) while leaving rate-limited keys
(429) in rotation — a rate-limited key is still a good key.

The layered-config doctrine (FLAG -> ENV -> FILE -> DEFAULT) is correct for
choosing ONE VALUE, but a pool is a SET.  The right operation for a set is
union, not precedence.  When a working key exists in the user's configured
single-key store AND different keys exist in the pool file, discarding one
source shrinks the pool for no reason — the opposite of what a pool is for.

  1. {PROVIDER}_API_KEYS env var (comma-separated): use EXACTLY those keys.
     An explicit list is an explicit override — the CI and container case.
  2. Otherwise: the UNION of the pool file (filtered to the requested
     provider) and the single configured key from avicenna/secrets.py,
     deduplicated, file keys first.
  3. No keys from any source: raise, as before.

A pool of one is the normal, supported case — it behaves exactly like the
single-key path.

Pool file format (backward-compatible):

    # comments and blank lines ignored, as today
    <bare key>            -> belongs to the DEFAULT provider
    mistral: <key>        -> explicitly scoped
    google: <key>

    [mistral]
    <key>
    <key>
    [google]
    <key>

A bare key before any section header belongs to the default provider.
A bare key after a [section] header belongs to that section's provider.
Provider names are matched case-insensitively and trimmed.
A key whose provider has no registered implementation is retained in the
parsed model but never returned for a different provider's pool.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Sequence

from avicenna.secrets import redact

_log = logging.getLogger(__name__)

DEFAULT_PROVIDER = "mistral"


class KeyPool:
    """Round-robin key rotation with quarantine for definitively-bad keys.

    Safe to call next() from many asyncio tasks at once — the index advance
    is guarded so two tasks cannot race to the same key.
    """

    def __init__(self, keys: Sequence[str], *, source: str = "single") -> None:
        if not keys:
            raise ValueError("KeyPool requires at least one key")
        # Preserve order, deduplicate.
        seen: set[str] = set()
        self._keys: list[str] = []
        for k in keys:
            if k not in seen:
                seen.add(k)
                self._keys.append(k)
        self._index = 0
        self._quarantined: set[str] = set()
        self._lock = asyncio.Lock()
        self._source = source

    def __len__(self) -> int:
        """Total keys (including quarantined)."""
        return len(self._keys)

    @property
    def live_count(self) -> int:
        """Keys still available for use."""
        return len(self._keys) - len(self._quarantined)

    @property
    def exhausted(self) -> bool:
        """True when every key has been quarantined."""
        return self.live_count <= 0

    @property
    def source(self) -> str:
        """Where the keys came from: 'env', 'file', or 'single'."""
        return self._source

    async def next(self) -> str:
        """Return the next live key via round-robin.

        Advances the index on every call, skipping quarantined keys.
        Raises RuntimeError if all keys are quarantined.
        """
        async with self._lock:
            if self.exhausted:
                raise RuntimeError(
                    "all API keys quarantined; no live keys remain"
                )
            n = len(self._keys)
            for _ in range(n):
                key = self._keys[self._index % n]
                self._index += 1
                if key not in self._quarantined:
                    return key
            # Should not reach here if live_count > 0, but be safe.
            raise RuntimeError(
                "all API keys quarantined; no live keys remain"
            )

    def quarantine(self, key: str, reason: str) -> None:
        """Remove a key from rotation for the life of this process.

        Use for definitively-bad keys (401/403), never for transient errors
        or rate limits (429).  The reason is redacted before logging so that
        unredacted provider text cannot leak into logs.
        """
        if key in self._keys and key not in self._quarantined:
            fp = self._fingerprint(key)
            _log.warning("quarantining key %s: %s", fp, redact(reason))
            self._quarantined.add(key)

    def fingerprints(self) -> list[str]:
        """Short, non-reversible identifiers for display.

        NEVER returns, logs, or echoes key material.
        """
        return [self._fingerprint(k) for k in self._keys]

    @staticmethod
    def _fingerprint(key: str) -> str:
        """First 8 chars of sha256 — short and non-reversible."""
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def _parse_pool_file(path: Path) -> dict[str, list[str]]:
    """Parse a pool file into provider -> keys mapping.

    Supports two formats, which may be mixed in a single file:

    * **Section headers**: ``[provider]`` — every bare key after the header
      belongs to that provider until the next header.
    * **Inline prefix**: ``provider: key`` — one key, explicitly scoped.

    A bare key with no prefix and no preceding section header belongs to the
    configured default provider (``DEFAULT_PROVIDER``).

    Provider names are matched case-insensitively and trimmed.  A key whose
    provider has no registered implementation is still parsed and retained so
    that ``avicenna keys --all`` can show it — it is simply never returned
    for a different provider's pool.  Keys are never silently dropped.
    """
    sections: dict[str, list[str]] = {}
    current_provider = DEFAULT_PROVIDER

    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Section header: [provider]
            if stripped.startswith("[") and stripped.endswith("]"):
                current_provider = stripped[1:-1].strip().lower()
                continue

            # Inline prefix: provider: key
            if ":" in stripped:
                prefix, key = stripped.split(":", 1)
                key = key.strip()
                if key:
                    prov = prefix.strip().lower()
                    sections.setdefault(prov, []).append(key)
                continue

            # Bare key — belongs to the current default provider.
            sections.setdefault(current_provider, []).append(stripped)
    except OSError:
        _log.warning("could not read pool file %s", path)

    return sections


def load_pool_file() -> dict[str, list[str]]:
    """Return the full parsed pool file as provider -> keys mapping.

    Used by the healthcheck to validate keys against their own providers.
    Returns an empty dict when the pool file does not exist or is empty.
    """
    pool_path = Path.home() / ".avicenna" / "api_keys_pool"
    if pool_path.is_file():
        return _parse_pool_file(pool_path)
    return {}


def is_provider_registered(name: str) -> bool:
    """Check whether a provider implementation is registered.

    Returns False when the name is not in the registry or when construction
    fails for any reason (missing SDK, import error, etc.).  This is used by
    the healthcheck to decide whether to validate a provider's keys or report
    them as SKIP — a false negative is safer than a false positive.
    """
    from avicenna.providers.registry import get_provider as _gp

    try:
        _gp(name, api_key="probe", model="probe")
    except Exception:  # noqa: BLE001 - any failure means "not usable"
        return False
    return True


def load_pool(provider: str = DEFAULT_PROVIDER) -> KeyPool:
    """Build a KeyPool from the configured sources.

    If {PROVIDER}_API_KEYS is set, use EXACTLY those keys — an explicit list
    is an explicit override (CI, containers).  Otherwise take the UNION of
    the pool file keys for THIS PROVIDER and the single configured key from
    read_api_key, deduplicated, order preserved with file keys first.  Never
    silently drop a working credential.

    A pool of one is the normal case and must behave like today's single-key
    path.
    """
    env_name = f"{provider.upper()}_API_KEYS"
    env_val = os.environ.get(env_name)

    # Source 1: env var — explicit override, use exactly.
    if env_val:
        keys = [k.strip() for k in env_val.split(",") if k.strip()]
        if keys:
            pool = KeyPool(keys, source="env")
            _log.info("loaded %d key(s) from %s env var", len(pool), env_name)
            return pool

    # Source 2+3: union of pool file (this provider only) and single key.
    sections = load_pool_file()
    file_keys = sections.get(provider.lower(), [])

    from avicenna.secrets import read_api_key

    single = read_api_key(provider)

    # Union: file keys first (preserve their order), then the single key if
    # it is not already present.
    combined: list[str] = list(file_keys)
    if single and single not in combined:
        combined.append(single)

    if combined:
        has_file = bool(file_keys)
        has_single = bool(single)
        if has_file and has_single:
            source = "file+single"
        elif has_file:
            source = "file"
        else:
            source = "single"
        pool = KeyPool(combined, source=source)
        _log.info("loaded %d key(s) (source=%s)", len(pool), source)
        return pool

    # No key at all — return an empty-ish pool that will fail on next().
    # Callers should check for None before using.
    raise RuntimeError(
        f"no API keys found for {provider!r}; set {env_name}, "
        f"create ~/.avicenna/api_keys_pool, or configure a single key"
    )


__all__ = ["KeyPool", "load_pool", "load_pool_file", "is_provider_registered", "DEFAULT_PROVIDER"]
