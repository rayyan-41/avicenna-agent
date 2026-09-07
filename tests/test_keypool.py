"""Tests for avicenna/keypool.py — the API key pool.

Covers: round-robin order and wraparound; blank and # lines ignored; duplicates
collapsed; env var beats file+single (explicit override); file+single union
merges both sources with file keys first and deduplicates; file-only and
single-only paths; pool of one behaves like the single-key path; quarantine
removes a key and the rotation skips it; all-quarantined raises; fingerprints
never contain key material; concurrent next() from many tasks hands out keys
without two tasks racing to the same index.

Do NOT put real keys in tests or fixtures. Do NOT read the user's real pool
file — use tmp_path and monkeypatch.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import pytest

from avicenna.keypool import KeyPool, load_pool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fp(key: str) -> str:
    """Replicate the fingerprint logic for assertions."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def _setup_pool_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    *,
    single_key: str | None = None,
) -> None:
    """Create the pool file under tmp_path and wire Path.home to tmp_path.

    Also monkeypatches read_api_key so tests never touch the real keyring.
    """
    avicenna_dir = tmp_path / ".avicenna"
    avicenna_dir.mkdir(exist_ok=True)
    pool_file = avicenna_dir / "api_keys_pool"
    pool_file.write_text(content, encoding="utf-8")
    monkeypatch.setattr("avicenna.keypool.Path.home", lambda: tmp_path)
    monkeypatch.setattr(
        "avicenna.secrets.read_api_key",
        lambda provider="mistral": single_key,
    )


# ---------------------------------------------------------------------------
# KeyPool construction and basic behaviour
# ---------------------------------------------------------------------------

class TestKeyPoolInit:
    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one key"):
            KeyPool([])

    def test_single_key(self) -> None:
        pool = KeyPool(["k1"])
        assert len(pool) == 1
        assert pool.live_count == 1
        assert not pool.exhausted

    def test_deduplication_preserves_order(self) -> None:
        pool = KeyPool(["k1", "k2", "k1", "k3", "k2"])
        assert len(pool) == 3
        assert pool._keys == ["k1", "k2", "k3"]


# ---------------------------------------------------------------------------
# Round-robin next() and wraparound
# ---------------------------------------------------------------------------

class TestRoundRobin:
    @pytest.mark.asyncio
    async def test_rotation_order(self) -> None:
        pool = KeyPool(["k1", "k2", "k3"])
        seen = [await pool.next() for _ in range(6)]
        assert seen == ["k1", "k2", "k3", "k1", "k2", "k3"]

    @pytest.mark.asyncio
    async def test_pool_of_one_returns_same_key(self) -> None:
        pool = KeyPool(["only-key"])
        results = [await pool.next() for _ in range(5)]
        assert all(r == "only-key" for r in results)


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------

class TestQuarantine:
    @pytest.mark.asyncio
    async def test_quarantine_skips_key(self) -> None:
        pool = KeyPool(["k1", "k2", "k3"])
        pool.quarantine("k2", "401")
        seen = [await pool.next() for _ in range(4)]
        # k2 must never appear.
        assert "k2" not in seen
        assert seen == ["k1", "k3", "k1", "k3"]

    @pytest.mark.asyncio
    async def test_all_quarantined_raises(self) -> None:
        pool = KeyPool(["k1", "k2"])
        pool.quarantine("k1", "401")
        pool.quarantine("k2", "401")
        assert pool.exhausted
        with pytest.raises(RuntimeError, match="quarantined"):
            await pool.next()

    def test_quarantine_unknown_key_is_noop(self) -> None:
        pool = KeyPool(["k1"])
        pool.quarantine("not-a-key", "401")
        assert pool.live_count == 1


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------

class TestFingerprints:
    def test_fingerprints_are_short_hashes(self) -> None:
        pool = KeyPool(["secret-key-1", "secret-key-2"])
        fps = pool.fingerprints()
        assert len(fps) == 2
        for fp in fps:
            assert len(fp) == 8
            # Must not contain the original key material.
            assert "secret-key" not in fp

    def test_fingerprints_match_expected(self) -> None:
        pool = KeyPool(["my-api-key-12345"])
        fps = pool.fingerprints()
        assert fps == [_fp("my-api-key-12345")]


# ---------------------------------------------------------------------------
# load_pool — env var is an explicit override
# ---------------------------------------------------------------------------

class TestLoadPoolEnv:
    def test_env_var_uses_exactly_those_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MISTRAL_API_KEYS env var is an explicit override — use exactly."""
        # File and single key exist but must be ignored.
        _setup_pool_file(
            tmp_path, monkeypatch,
            "file-key-1\nfile-key-2\n",
            single_key="single-key",
        )
        monkeypatch.setenv("MISTRAL_API_KEYS", "env-key-a,env-key-b")
        pool = load_pool("mistral")
        assert pool.source == "env"
        assert pool._keys == ["env-key-a", "env-key-b"]

    def test_env_var_comma_separated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Comma-separated env var keys are parsed correctly."""
        monkeypatch.setenv("MISTRAL_API_KEYS", "k1,k2, k3 ,k4")
        pool = load_pool("mistral")
        assert pool._keys == ["k1", "k2", "k3", "k4"]


# ---------------------------------------------------------------------------
# load_pool — union of file + single key
# ---------------------------------------------------------------------------

class TestLoadPoolUnion:
    def test_file_plus_distinct_single_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both file keys and a distinct single key present — union, file first."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "file-key-1\nfile-key-2\n",
            single_key="single-key",
        )
        pool = load_pool("mistral")
        assert pool.source == "file+single"
        assert pool._keys == ["file-key-1", "file-key-2", "single-key"]

    def test_file_plus_single_already_in_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Single key already in file — deduplicated, length unchanged."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "file-key-1\nfile-key-2\n",
            single_key="file-key-1",
        )
        pool = load_pool("mistral")
        assert pool.source == "file+single"
        # file-key-1 already present; single contributed nothing new.
        assert pool._keys == ["file-key-1", "file-key-2"]
        assert len(pool) == 2

    def test_file_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only file keys available — source is 'file'."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "file-key-1\nfile-key-2\n",
            single_key=None,
        )
        pool = load_pool("mistral")
        assert pool.source == "file"
        assert pool._keys == ["file-key-1", "file-key-2"]

    def test_single_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Only single key available — source is 'single', pool of one."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        # No pool file.
        monkeypatch.setattr("avicenna.keypool.Path.home", lambda: tmp_path)
        monkeypatch.setattr(
            "avicenna.secrets.read_api_key",
            lambda provider="mistral": "single-key",
        )
        pool = load_pool("mistral")
        assert pool.source == "single"
        assert pool._keys == ["single-key"]
        assert len(pool) == 1

    def test_no_keys_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raises when no keys are available from any source."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        monkeypatch.setattr("avicenna.keypool.Path.home", lambda: tmp_path)
        monkeypatch.setattr(
            "avicenna.secrets.read_api_key", lambda provider="mistral": None
        )
        with pytest.raises(RuntimeError, match="no API keys found"):
            load_pool("mistral")


# ---------------------------------------------------------------------------
# load_pool — file parsing edge cases
# ---------------------------------------------------------------------------

class TestLoadPoolFileParsing:
    def test_blank_and_comment_lines_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Blank lines and lines starting with # are ignored in pool file."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "# This is a comment\n\nkey-1\n  \n# Another comment\nkey-2\n\n",
        )
        pool = load_pool("mistral")
        assert pool._keys == ["key-1", "key-2"]

    def test_whitespace_trimmed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whitespace around keys in pool file is trimmed."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "  key-1  \n\tkey-2\t\n",
        )
        pool = load_pool("mistral")
        assert pool._keys == ["key-1", "key-2"]

    def test_duplicates_collapsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Duplicate keys in the pool file are collapsed, order preserved."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "key-1\nkey-2\nkey-1\nkey-3\nkey-2\n",
        )
        pool = load_pool("mistral")
        assert pool._keys == ["key-1", "key-2", "key-3"]


# ---------------------------------------------------------------------------
# Concurrent next() — no two tasks race to the same index
# ---------------------------------------------------------------------------

class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_next_no_duplicate(self) -> None:
        """Many tasks calling next() concurrently must not receive the same key."""
        pool = KeyPool(["k1", "k2", "k3"])
        n_tasks = 30
        results: list[str] = []

        async def grab() -> None:
            key = await pool.next()
            results.append(key)

        await asyncio.gather(*(grab() for _ in range(n_tasks)))
        assert len(results) == n_tasks
        # With 3 keys and 30 calls, each key should appear exactly 10 times.
        assert results.count("k1") == 10
        assert results.count("k2") == 10
        assert results.count("k3") == 10

    @pytest.mark.asyncio
    async def test_concurrent_with_quarantine(self) -> None:
        """Concurrent calls with quarantine in between must still be correct."""
        pool = KeyPool(["k1", "k2", "k3"])

        # Quarantine k2 before concurrent calls.
        pool.quarantine("k2", "401")

        results: list[str] = []

        async def grab() -> None:
            key = await pool.next()
            results.append(key)

        await asyncio.gather(*(grab() for _ in range(10)))
        assert "k2" not in results
        # With 2 live keys and 10 calls, each appears 5 times.
        assert results.count("k1") == 5
        assert results.count("k3") == 5


# ---------------------------------------------------------------------------
# Pool of one behaves like the single-key path
# ---------------------------------------------------------------------------

class TestPoolOfOne:
    @pytest.mark.asyncio
    async def test_pool_of_one_round_robin(self) -> None:
        """A pool of one must return the same key on every call."""
        pool = KeyPool(["single-key"])
        for _ in range(10):
            assert await pool.next() == "single-key"

    def test_pool_of_one_fingerprint(self) -> None:
        """A pool of one still provides fingerprints."""
        pool = KeyPool(["single-key"])
        fps = pool.fingerprints()
        assert len(fps) == 1
        assert fps[0] == _fp("single-key")
        assert "single-key" not in fps[0]


# ---------------------------------------------------------------------------
# R2 — quarantine reason is redacted
# ---------------------------------------------------------------------------

class TestQuarantineRedaction:
    def test_redact_applied_to_reason(self, caplog: pytest.LogCaptureFixture) -> None:
        """Quarantine log must not contain unredacted provider text."""
        import logging

        pool = KeyPool(["k1", "k2"])
        # A reason that looks like a long token — _KEYISH would match it.
        reason = "unauthorised: token ABCDEFGHJKLMNPQRSTUVWXYza12345678 rejected"
        with caplog.at_level(logging.WARNING, logger="avicenna.keypool"):
            pool.quarantine("k1", reason)
        # The raw token-like string must NOT appear in the log output.
        assert "ABCDEFGHJKLMNPQRSTUVWXYza12345678" not in caplog.text
        assert "***REDACTED***" in caplog.text

    def test_redact_no_false_positive(self, caplog: pytest.LogCaptureFixture) -> None:
        """A short reason with nothing to redact passes through cleanly."""
        import logging

        pool = KeyPool(["k1", "k2"])
        with caplog.at_level(logging.WARNING, logger="avicenna.keypool"):
            pool.quarantine("k1", "HTTP 401")
        assert "HTTP 401" in caplog.text


# ---------------------------------------------------------------------------
# R3 — source is a constructor argument and read-only property
# ---------------------------------------------------------------------------

class TestSourceProperty:
    def test_default_source(self) -> None:
        """Default source is 'single'."""
        pool = KeyPool(["k1"])
        assert pool.source == "single"

    def test_explicit_source(self) -> None:
        """Source can be set via constructor."""
        pool = KeyPool(["k1", "k2"], source="env")
        assert pool.source == "env"

    def test_source_file_value(self) -> None:
        """Source 'file' is accepted."""
        pool = KeyPool(["k1"], source="file")
        assert pool.source == "file"

    def test_source_file_plus_single(self) -> None:
        """Source 'file+single' is accepted."""
        pool = KeyPool(["k1", "k2"], source="file+single")
        assert pool.source == "file+single"
