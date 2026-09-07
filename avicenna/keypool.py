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

  1. MISTRAL_API_KEYS env var (comma-separated): use EXACTLY those keys.
     An explicit list is an explicit override — the CI and container case.
  2. Otherwise: the UNION of the pool file and the single configured key
     from avicenna/secrets.py:read_api_key, deduplicated, file keys first.
  3. No keys from any source: raise, as before.

A pool of one is the normal, supported case — it behaves exactly like the
single-key path.
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


def load_pool(provider: str = "mistral") -> KeyPool:
    """Build a KeyPool from the configured sources.

    If MISTRAL_API_KEYS is set, use EXACTLY those keys — an explicit list is
    an explicit override (CI, containers).  Otherwise take the UNION of the
    pool file and the single configured key from read_api_key, deduplicated,
    order preserved with file keys first.  Never silently drop a working
    credential.

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

    # Source 2+3: union of pool file and single configured key.
    file_keys: list[str] = []
    pool_path = Path.home() / ".avicenna" / "api_keys_pool"
    if pool_path.is_file():
        try:
            for line in pool_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    file_keys.append(stripped)
        except OSError:
            _log.warning("could not read pool file %s", pool_path)

    from avicenna.secrets import read_api_key

    single = read_api_key(provider)

    # Union: file keys first (preserve their order), then the single key if
    # it is not already present.
    combined: list[str] = list(file_keys)
    if single and single not in combined:
        combined.append(single)

    if combined:
        # Determine which sources contributed.
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
        f"create {pool_path}, or configure a single key"
    )


__all__ = ["KeyPool", "load_pool"]
