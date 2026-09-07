"""Tests for the PROVIDER probe in scripts/healthcheck.py.

Verifies that probe_provider validates every key in the pool concurrently,
reports per-key results by fingerprint (never key material), and returns the
correct status: PASS when all keys are valid, WARN when some are invalid, FAIL
when none are valid, SKIP when no keys are configured.

T25 additions: validates keys against their own provider.  Keys for an
unregistered provider are reported as SKIP (informational, never FAIL, does
not affect exit code).  Keys for another registered provider are validated
against that provider and reported separately.  Never advises removing a
valid key merely because the active provider rejects it.

Do NOT make real network calls or read the real ~/.avicenna/api_keys_pool.
Monkeypatch the validator and Path.home.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import pytest

from avicenna.auth import ValidationResult
from avicenna.keypool import KeyPool
from scripts.healthcheck import ProbeResult, Status, probe_provider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fp(key: str) -> str:
    """Replicate the fingerprint logic for assertions."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def _make_validator(
    results_map: dict[str, tuple[bool, str]],
) -> Any:
    """Return an async validator that maps key -> (ok, detail).

    Tracks call count so tests can assert concurrency.
    """
    call_count = 0

    async def _validate(
        provider_name: str, api_key: str, model: str
    ) -> ValidationResult:
        nonlocal call_count
        call_count += 1
        ok, detail = results_map.get(api_key, (False, "unknown key"))
        return ValidationResult(ok=ok, detail=detail)

    _validate.call_count = lambda: call_count  # type: ignore[attr-defined]
    return _validate


def _stub_pool_file(sections: dict[str, list[str]]) -> Any:
    """Return a load_pool_file stub that returns the given sections."""
    def _load() -> dict[str, list[str]]:
        return sections
    return _load


def _stub_registered(registered: set[str]) -> Any:
    """Return an is_provider_registered stub."""
    def _check(name: str) -> bool:
        return name in registered
    return _check


# ---------------------------------------------------------------------------
# All keys valid -> PASS
# ---------------------------------------------------------------------------

class TestAllValid:
    @pytest.mark.asyncio
    async def test_pass_when_all_keys_valid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every key validates — status is OK."""
        keys = ["k1", "k2", "k3"]
        pool = KeyPool(keys, source="file")
        monkeypatch.setattr("avicenna.keypool.load_pool", lambda provider="mistral": pool)
        monkeypatch.setattr("avicenna.keypool.load_pool_file", _stub_pool_file({}))
        monkeypatch.setattr(
            "avicenna.config.Config.load_user_config",
            lambda: {"model": "mistral-large-latest"},
        )
        validator = _make_validator({k: (True, "ok") for k in keys})
        monkeypatch.setattr("avicenna.auth.validate_key", validator)

        result = await probe_provider()

        assert result.status is Status.OK
        assert "3/3 keys valid" in result.summary
        assert "source=file" in result.summary

    @pytest.mark.asyncio
    async def test_pass_includes_count_and_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PASS line includes the key count and pool source."""
        keys = ["only-one"]
        pool = KeyPool(keys, source="single")
        monkeypatch.setattr("avicenna.keypool.load_pool", lambda provider="mistral": pool)
        monkeypatch.setattr("avicenna.keypool.load_pool_file", _stub_pool_file({}))
        monkeypatch.setattr(
            "avicenna.config.Config.load_user_config",
            lambda: {"model": "mistral-large-latest"},
        )
        validator = _make_validator({"only-one": (True, "ok")})
        monkeypatch.setattr("avicenna.auth.validate_key", validator)

        result = await probe_provider()

        assert result.status is Status.OK
        assert "1/1 keys valid" in result.summary
        assert "source=single" in result.summary


# ---------------------------------------------------------------------------
# One of four invalid -> WARN, fingerprint in output
# ---------------------------------------------------------------------------

class TestMixedValid:
    @pytest.mark.asyncio
    async def test_warn_when_some_keys_invalid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One bad key among several — status is WARN."""
        keys = ["good-1", "good-2", "good-3", "bad-key"]
        pool = KeyPool(keys, source="file")
        monkeypatch.setattr("avicenna.keypool.load_pool", lambda provider="mistral": pool)
        monkeypatch.setattr("avicenna.keypool.load_pool_file", _stub_pool_file({}))
        monkeypatch.setattr(
            "avicenna.config.Config.load_user_config",
            lambda: {"model": "mistral-large-latest"},
        )
        monkeypatch.setattr("avicenna.keypool.Path.home", lambda: tmp_path)
        results_map: dict[str, tuple[bool, str]] = {
            "good-1": (True, "ok"),
            "good-2": (True, "ok"),
            "good-3": (True, "ok"),
            "bad-key": (False, "Key rejected. Check for a typo or an expired key."),
        }
        validator = _make_validator(results_map)
        monkeypatch.setattr("avicenna.auth.validate_key", validator)

        result = await probe_provider()

        assert result.status is Status.WARN
        assert "3/4 keys valid" in result.summary
        assert "1 will be quarantined" in result.summary
        # The failing fingerprint must appear in the details.
        bad_fp = _fp("bad-key")
        assert any(bad_fp in line for line in result.details)


# ---------------------------------------------------------------------------
# All keys invalid -> FAIL
# ---------------------------------------------------------------------------

class TestAllInvalid:
    @pytest.mark.asyncio
    async def test_fail_when_all_keys_invalid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No key validates — status is FAIL."""
        keys = ["bad-1", "bad-2"]
        pool = KeyPool(keys, source="file")
        monkeypatch.setattr("avicenna.keypool.load_pool", lambda provider="mistral": pool)
        monkeypatch.setattr("avicenna.keypool.load_pool_file", _stub_pool_file({}))
        monkeypatch.setattr(
            "avicenna.config.Config.load_user_config",
            lambda: {"model": "mistral-large-latest"},
        )
        results_map: dict[str, tuple[bool, str]] = {
            "bad-1": (False, "Key rejected"),
            "bad-2": (False, "Key rejected"),
        }
        validator = _make_validator(results_map)
        monkeypatch.setattr("avicenna.auth.validate_key", validator)

        result = await probe_provider()

        assert result.status is Status.FAIL
        assert "0/2 keys valid" in result.summary


# ---------------------------------------------------------------------------
# No keys configured -> SKIP
# ---------------------------------------------------------------------------

class TestNoKeys:
    @pytest.mark.asyncio
    async def test_skip_when_no_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No keys configured at all — SKIP, same as before."""
        def _no_pool(provider: str = "mistral") -> Any:
            raise RuntimeError("no API keys found")

        monkeypatch.setattr("avicenna.keypool.load_pool", _no_pool)
        monkeypatch.setattr("avicenna.keypool.load_pool_file", _stub_pool_file({}))

        result = await probe_provider()

        assert result.status is Status.SKIP
        assert "no API key configured" in result.summary


# ---------------------------------------------------------------------------
# Key material never appears in output
# ---------------------------------------------------------------------------

class TestNoKeyLeakage:
    @pytest.mark.asyncio
    async def test_key_material_absent_from_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raw key strings must never appear in summary or details."""
        keys = ["super-secret-key-1", "super-secret-key-2", "super-secret-key-3"]
        pool = KeyPool(keys, source="file")
        monkeypatch.setattr("avicenna.keypool.load_pool", lambda provider="mistral": pool)
        monkeypatch.setattr("avicenna.keypool.load_pool_file", _stub_pool_file({}))
        monkeypatch.setattr(
            "avicenna.config.Config.load_user_config",
            lambda: {"model": "mistral-large-latest"},
        )
        monkeypatch.setattr("avicenna.keypool.Path.home", lambda: tmp_path)
        results_map: dict[str, tuple[bool, str]] = {
            "super-secret-key-1": (True, "ok"),
            "super-secret-key-2": (False, "Key rejected"),
            "super-secret-key-3": (True, "ok"),
        }
        validator = _make_validator(results_map)
        monkeypatch.setattr("avicenna.auth.validate_key", validator)

        result = await probe_provider()

        rendered = result.summary + " ".join(result.details)
        for key in keys:
            assert key not in rendered, f"Key material leaked into output: {key}"


# ---------------------------------------------------------------------------
# Validation runs concurrently, not serially
# ---------------------------------------------------------------------------

class TestConcurrency:
    @pytest.mark.asyncio
    async def test_validations_run_concurrently(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All keys should be validated — gather fires all at once."""
        keys = ["k1", "k2", "k3", "k4"]
        pool = KeyPool(keys, source="env")
        monkeypatch.setattr("avicenna.keypool.load_pool", lambda provider="mistral": pool)
        monkeypatch.setattr("avicenna.keypool.load_pool_file", _stub_pool_file({}))
        monkeypatch.setattr(
            "avicenna.config.Config.load_user_config",
            lambda: {"model": "mistral-large-latest"},
        )
        validator = _make_validator({k: (True, "ok") for k in keys})
        monkeypatch.setattr("avicenna.auth.validate_key", validator)

        result = await probe_provider()

        assert result.status is Status.OK
        assert "4/4 keys valid" in result.summary
        assert validator.call_count() == 4  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_uses_asyncio_gather(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """probe_provider uses asyncio.gather (not sequential awaits) to
        validate keys.  We verify by monkeypatching gather and checking it
        is called with the right number of coroutines."""
        keys = ["k1", "k2", "k3"]
        pool = KeyPool(keys, source="file")
        monkeypatch.setattr("avicenna.keypool.load_pool", lambda provider="mistral": pool)
        monkeypatch.setattr("avicenna.keypool.load_pool_file", _stub_pool_file({}))
        monkeypatch.setattr(
            "avicenna.config.Config.load_user_config",
            lambda: {"model": "mistral-large-latest"},
        )
        validator = _make_validator({k: (True, "ok") for k in keys})
        monkeypatch.setattr("avicenna.auth.validate_key", validator)

        gather_call_args: list[int] = []
        real_gather = asyncio.gather

        async def _spy_gather(*coros: Any, **kwargs: Any) -> Any:
            gather_call_args.append(len(coros))
            return await real_gather(*coros, **kwargs)

        monkeypatch.setattr("scripts.healthcheck.asyncio.gather", _spy_gather)

        result = await probe_provider()

        assert result.status is Status.OK
        # gather was called with exactly one positional arg per key.
        assert len(gather_call_args) == 1
        assert gather_call_args[0] == 3


# ---------------------------------------------------------------------------
# T25 — Keys for unregistered provider: SKIP, not FAIL
# ---------------------------------------------------------------------------

class TestUnregisteredProviderSkip:
    @pytest.mark.asyncio
    async def test_unregistered_provider_is_skip_not_fail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A key for a provider with no implementation is reported as SKIP
        in the details.  Overall status is driven by the active provider only."""
        mistral_pool = KeyPool(["mk1"], source="file")
        monkeypatch.setattr(
            "avicenna.keypool.load_pool",
            lambda provider="mistral": mistral_pool,
        )
        monkeypatch.setattr(
            "avicenna.keypool.load_pool_file",
            _stub_pool_file({"mistral": ["mk1"], "google": ["gkey"]}),
        )
        monkeypatch.setattr(
            "avicenna.keypool.is_provider_registered",
            _stub_registered({"mistral", "fake"}),
        )
        monkeypatch.setattr(
            "avicenna.config.Config.load_user_config",
            lambda: {"model": "mistral-large-latest"},
        )
        validator = _make_validator({"mk1": (True, "ok")})
        monkeypatch.setattr("avicenna.auth.validate_key", validator)

        result = await probe_provider()

        # Active provider passes.
        assert result.status is Status.OK
        # Google key is reported as informational SKIP.
        assert any("google" in d and "no provider implementation" in d
                    for d in result.details)
        # No FAIL anywhere.
        assert result.status is not Status.FAIL

    @pytest.mark.asyncio
    async def test_unregistered_does_not_affect_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even with unregistered provider keys in the file, the exit code
        depends only on the active provider's results."""
        mistral_pool = KeyPool(["mk1", "mk2"], source="file")
        monkeypatch.setattr(
            "avicenna.keypool.load_pool",
            lambda provider="mistral": mistral_pool,
        )
        monkeypatch.setattr(
            "avicenna.keypool.load_pool_file",
            _stub_pool_file({"mistral": ["mk1", "mk2"], "openai": ["okey"]}),
        )
        monkeypatch.setattr(
            "avicenna.keypool.is_provider_registered",
            _stub_registered({"mistral", "fake"}),
        )
        monkeypatch.setattr(
            "avicenna.config.Config.load_user_config",
            lambda: {"model": "mistral-large-latest"},
        )
        validator = _make_validator({
            "mk1": (True, "ok"),
            "mk2": (True, "ok"),
        })
        monkeypatch.setattr("avicenna.auth.validate_key", validator)

        result = await probe_provider()

        assert result.status is Status.OK
        assert any("openai" in d and "no provider implementation" in d
                    for d in result.details)

    @pytest.mark.asyncio
    async def test_unregistered_key_count_and_no_suffix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Singular key does not get pluralized 'keys'."""
        mistral_pool = KeyPool(["mk"], source="file")
        monkeypatch.setattr(
            "avicenna.keypool.load_pool",
            lambda provider="mistral": mistral_pool,
        )
        monkeypatch.setattr(
            "avicenna.keypool.load_pool_file",
            _stub_pool_file({"mistral": ["mk"], "anthropic": ["akey"]}),
        )
        monkeypatch.setattr(
            "avicenna.keypool.is_provider_registered",
            _stub_registered({"mistral", "fake"}),
        )
        monkeypatch.setattr(
            "avicenna.config.Config.load_user_config",
            lambda: {"model": "mistral-large-latest"},
        )
        validator = _make_validator({"mk": (True, "ok")})
        monkeypatch.setattr("avicenna.auth.validate_key", validator)

        result = await probe_provider()

        assert any("anthropic: 1 key, no provider" in d for d in result.details)


# ---------------------------------------------------------------------------
# T25 — Keys for another registered provider: validated separately
# ---------------------------------------------------------------------------

class TestOtherProviderValidation:
    @pytest.mark.asyncio
    async def test_other_registered_provider_validated_separately(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Keys for another registered provider are validated against that
        provider and reported separately in the details."""
        mistral_pool = KeyPool(["mk1"], source="file")
        monkeypatch.setattr(
            "avicenna.keypool.load_pool",
            lambda provider="mistral": mistral_pool,
        )
        monkeypatch.setattr(
            "avicenna.keypool.load_pool_file",
            _stub_pool_file({"mistral": ["mk1"], "other": ["ok1", "ok2"]}),
        )
        monkeypatch.setattr(
            "avicenna.keypool.is_provider_registered",
            _stub_registered({"mistral", "other", "fake"}),
        )
        monkeypatch.setattr(
            "avicenna.config.Config.load_user_config",
            lambda: {"model": "mistral-large-latest"},
        )
        # All keys pass validation.
        validator = _make_validator({
            "mk1": (True, "ok"),
            "ok1": (True, "ok"),
            "ok2": (True, "ok"),
        })
        monkeypatch.setattr("avicenna.auth.validate_key", validator)

        result = await probe_provider()

        assert result.status is Status.OK
        assert any("other: 2/2 keys valid" in d for d in result.details)

    @pytest.mark.asyncio
    async def test_other_provider_partial_failure_is_warn_in_details(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A key failing against its OWN provider gets a WARN with fingerprint."""
        mistral_pool = KeyPool(["mk1"], source="file")
        monkeypatch.setattr(
            "avicenna.keypool.load_pool",
            lambda provider="mistral": mistral_pool,
        )
        monkeypatch.setattr(
            "avicenna.keypool.load_pool_file",
            _stub_pool_file({"mistral": ["mk1"], "other": ["ok-good", "ok-bad"]}),
        )
        monkeypatch.setattr(
            "avicenna.keypool.is_provider_registered",
            _stub_registered({"mistral", "other", "fake"}),
        )
        monkeypatch.setattr(
            "avicenna.config.Config.load_user_config",
            lambda: {"model": "mistral-large-latest"},
        )
        validator = _make_validator({
            "mk1": (True, "ok"),
            "ok-good": (True, "ok"),
            "ok-bad": (False, "Key rejected"),
        })
        monkeypatch.setattr("avicenna.auth.validate_key", validator)

        result = await probe_provider()

        # Active provider is still OK.
        assert result.status is Status.OK
        # Other provider's partial failure shows in details.
        assert any("other: 1/2 keys valid" in d for d in result.details)
        bad_fp = _fp("ok-bad")
        assert any(bad_fp in line for line in result.details)
