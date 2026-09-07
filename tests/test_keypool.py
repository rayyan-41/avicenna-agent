"""Tests for avicenna/keypool.py — the API key pool.

Covers: round-robin order and wraparound; blank and # lines ignored; duplicates
collapsed; env var beats file+single (explicit override); file+single union
merges both sources with file keys first and deduplicates; file-only and
single-only paths; pool of one behaves like the single-key path; quarantine
removes a key and the rotation skips it; all-quarantined raises; fingerprints
never contain key material; concurrent next() from many tasks hands out keys
without two tasks racing to the same index.

Provider-scoped pool file tests: flat legacy files, inline prefix
(``provider: key``), section headers (``[provider]``), case-insensitive
matching, bare keys before and after section headers, keys for an
unregistered provider are retained but never returned for a different pool,
env var per provider, and ``load_pool_file`` returning the full structure.

Do NOT put real keys in tests or fixtures. Do NOT read the user's real pool
file — use tmp_path and monkeypatch.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import pytest

from avicenna.keypool import KeyPool, load_pool, load_pool_file


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


# ---------------------------------------------------------------------------
# T25 — Provider-scoped pool file: legacy flat file regression
# ---------------------------------------------------------------------------

class TestProviderScopeLegacyFlat:
    """A flat legacy file with bare keys only — all belong to the default
    provider (exact backward-compatibility guarantee)."""

    def test_flat_legacy_all_default_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "key-a\nkey-b\nkey-c\n",
        )
        pool = load_pool("mistral")
        assert pool._keys == ["key-a", "key-b", "key-c"]

    def test_flat_legacy_other_provider_returns_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A flat file's keys belong to the default provider; loading another
        provider's pool from it must not return them."""
        monkeypatch.delenv("GOOGLE_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "key-a\nkey-b\n",
            single_key=None,
        )
        # read_api_key for google returns None by default in our monkeypatch.
        # So load_pool("google") should raise (no keys for google).
        with pytest.raises(RuntimeError, match="no API keys found"):
            load_pool("google")


# ---------------------------------------------------------------------------
# T25 — Provider-scoped pool file: inline prefix format
# ---------------------------------------------------------------------------

class TestProviderScopeInlinePrefix:
    def test_inline_prefix_filters_to_requested_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """mistral: k1 / google: k2 -> load_pool('mistral') returns only k1."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "mistral: k1\ngoogle: k2\n",
            single_key=None,
        )
        pool = load_pool("mistral")
        assert pool._keys == ["k1"]

    def test_inline_prefix_google_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GOOGLE_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "mistral: mk1\ngoogle: gk1\ngoogle: gk2\n",
            single_key=None,
        )
        pool = load_pool("google")
        assert pool._keys == ["gk1", "gk2"]

    def test_mixed_bare_and_prefixed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bare keys go to default provider; prefixed keys go to named one."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "bare-key\nmistral: explicit-key\ngoogle: gkey\n",
            single_key=None,
        )
        pool = load_pool("mistral")
        assert "bare-key" in pool._keys
        assert "explicit-key" in pool._keys
        assert "gkey" not in pool._keys


# ---------------------------------------------------------------------------
# T25 — Provider-scoped pool file: section headers
# ---------------------------------------------------------------------------

class TestProviderScopeSectionHeaders:
    def test_section_headers_filter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """[mistral] / [google] produce the same filtering as inline prefix."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "[mistral]\n"
            "mk1\n"
            "mk2\n"
            "[google]\n"
            "gk1\n",
            single_key=None,
        )
        pool = load_pool("mistral")
        assert pool._keys == ["mk1", "mk2"]

    def test_bare_key_before_section_goes_to_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bare key before any section header belongs to the default provider."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "default-key\n[mistral]\nmistral-key\n",
            single_key=None,
        )
        pool = load_pool("mistral")
        assert "default-key" in pool._keys
        assert "mistral-key" in pool._keys

    def test_bare_key_after_section_header(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bare key after a section header belongs to that section."""
        monkeypatch.delenv("GOOGLE_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "[google]\ngoogle-bare-key\n",
            single_key=None,
        )
        pool = load_pool("google")
        assert pool._keys == ["google-bare-key"]

    def test_bare_key_after_section_with_prefix_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An inline prefix can override the current section for one key."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "[google]\n"
            "gkey\n"
            "mistral: stray-mistral-key\n"
            "another-google-key\n",
            single_key=None,
        )
        google_pool = load_pool("google")
        assert "gkey" in google_pool._keys
        assert "another-google-key" in google_pool._keys
        assert "stray-mistral-key" not in google_pool._keys

        mistral_pool = load_pool("mistral")
        assert "stray-mistral-key" in mistral_pool._keys


# ---------------------------------------------------------------------------
# T25 — Provider-scoped pool file: case-insensitive provider matching
# ---------------------------------------------------------------------------

class TestProviderScopeCaseInsensitive:
    def test_case_insensitive_matching(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "MISTRAL: upper-key\nMistral: mixed-key\nmistral: lower-key\n",
            single_key=None,
        )
        pool = load_pool("mistral")
        assert pool._keys == ["upper-key", "mixed-key", "lower-key"]

    def test_case_insensitive_sections(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GOOGLE_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "[Google]\ngkey1\n[GOOGLE]\ngkey2\n",
            single_key=None,
        )
        pool = load_pool("google")
        assert pool._keys == ["gkey1", "gkey2"]


# ---------------------------------------------------------------------------
# T25 — Keys for unregistered provider are retained but never returned
# ---------------------------------------------------------------------------

class TestProviderScopeUnregistered:
    def test_unregistered_provider_keys_not_returned_for_other_pool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Keys for an unregistered provider are parsed but never leak into
        another provider's pool."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "mistral: mk\nopenai: okey\n",
            single_key=None,
        )
        pool = load_pool("mistral")
        assert pool._keys == ["mk"]
        assert "okey" not in pool._keys


# ---------------------------------------------------------------------------
# T25 — Env var per provider overrides that provider only
# ---------------------------------------------------------------------------

class TestProviderScopeEnvPerProvider:
    def test_env_var_for_different_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GOOGLE_API_KEYS overrides the google pool, not the mistral pool."""
        monkeypatch.delenv("MISTRAL_API_KEYS", raising=False)
        _setup_pool_file(
            tmp_path, monkeypatch,
            "mistral: mk\ngoogle: gk\n",
            single_key=None,
        )
        monkeypatch.setenv("GOOGLE_API_KEYS", "env-g1,env-g2")

        google_pool = load_pool("google")
        assert google_pool._keys == ["env-g1", "env-g2"]
        assert google_pool.source == "env"

        mistral_pool = load_pool("mistral")
        assert mistral_pool._keys == ["mk"]


# ---------------------------------------------------------------------------
# T25 — load_pool_file returns the full parsed structure
# ---------------------------------------------------------------------------

class TestLoadPoolFile:
    def test_returns_full_structure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("avicenna.keypool.Path.home", lambda: tmp_path)
        avicenna_dir = tmp_path / ".avicenna"
        avicenna_dir.mkdir(exist_ok=True)
        pool_file = avicenna_dir / "api_keys_pool"
        pool_file.write_text(
            "mistral: mk\n[gk]\ngk1\ngk2\nopenai: okey\n",
            encoding="utf-8",
        )
        sections = load_pool_file()
        assert "mistral" in sections
        assert sections["mistral"] == ["mk"]
        assert "gk" in sections
        assert sections["gk"] == ["gk1", "gk2"]
        assert "openai" in sections
        assert sections["openai"] == ["okey"]

    def test_empty_when_no_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("avicenna.keypool.Path.home", lambda: tmp_path)
        sections = load_pool_file()
        assert sections == {}
