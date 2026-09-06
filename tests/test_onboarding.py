"""First-run onboarding and vault-context tests.

The v1.0.0 frontend opened straight to a chat pane with no provider, so any
prompt returned "No vault or provider configured". Onboarding now lives in the
TypeScript interface, but the guarantees it depends on are backend ones, and
these tests pin them:

  * a fresh install reports itself unconfigured, which is what makes the
    interface show onboarding at all;
  * a bad key produces a specific, actionable message and is never persisted;
  * a good key is persisted and flips the install to onboarded;
  * the local-model option stays an honest stub rather than a silent no-op.

The real keyring and ~/.avicenna are never touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from avicenna import auth
from avicenna.bridge.server import Bridge, BridgeError
from avicenna.vault.context import VaultContext
from avicenna.vault.vault import Vault


def _vault(tmp_path: Path) -> Vault:
    (tmp_path / ".agents" / "agents").mkdir(parents=True)
    (tmp_path / ".agents" / "skills").mkdir(parents=True)
    (tmp_path / ".agents" / "tools").mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("# protocol\n", encoding="utf-8")
    (tmp_path / ".agents" / "taxonomy.json").write_text(json.dumps({
        "version": 1,
        "schema": {"marker": "cli", "markers": ["cli", "manual"]},
        "domains": {"general": ["note"]},
        "universalCategories": ["moc"],
        "folderMap": {"General": "note"},
        "types": ["concept"], "themes": [], "reservedModifiers": [],
    }), encoding="utf-8")
    (tmp_path / ".agents" / "agents" / "scribe.md").write_text(
        "---\nname: scribe\ndescription: general agent\ntype: content\n"
        "domain: general\n---\n\nbody\n", encoding="utf-8")
    return Vault.load(tmp_path)


@pytest.fixture
def isolated_config(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """An in-memory stand-in for user_config.json and the OS keyring."""
    store: dict[str, Any] = {}
    written: dict[str, str] = {}

    import avicenna.secrets as secrets
    from avicenna.config import Config

    monkeypatch.setattr(Config, "load_user_config", staticmethod(lambda: dict(store)))
    monkeypatch.setattr(
        Config, "save_user_config", staticmethod(lambda cfg: store.update(cfg))
    )

    def fake_write(provider: str, key: str) -> str:
        written[provider] = key
        return "test-store"

    monkeypatch.setattr(secrets, "write_api_key", fake_write)
    monkeypatch.setattr(auth, "persist_key", auth.persist_key)  # keep the real one
    store["_written"] = written
    return store


# ---------------------------------------------------------------------------
# A fresh install must ask
# ---------------------------------------------------------------------------

def test_fresh_install_reports_unconfigured(
    monkeypatch: pytest.MonkeyPatch, isolated_config: dict[str, Any]
) -> None:
    monkeypatch.setattr("avicenna.secrets.read_api_key", lambda provider="mistral": None)

    status = auth.auth_status()

    assert status["configured"] is False
    assert status["onboarded"] is False
    # The interface reads these two fields to decide whether to open onboarding.
    assert status["provider"] == auth.DEFAULT_PROVIDER
    assert status["model"] == auth.DEFAULT_MODEL


def test_unconfigured_install_has_no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("avicenna.secrets.read_api_key", lambda provider="mistral": None)
    assert auth.build_provider() is None


# ---------------------------------------------------------------------------
# build_provider() honours the model the user chose during onboarding
# ---------------------------------------------------------------------------

class _StubProvider:
    """Minimal stand-in so build_provider has something to return."""
    name = "mistral"

    async def complete(self, **_: Any) -> Any:
        return object()

    async def close(self) -> None:
        pass


def test_build_provider_uses_model_from_user_config(
    monkeypatch: pytest.MonkeyPatch, isolated_config: dict[str, Any]
) -> None:
    """The model written by onboarding must reach the provider, not the hardcoded default.

    Before this was centralised into build_provider(), the CLI built the
    provider by hand with Config.MISTRAL_MODEL (the env-var fallback), ignoring
    user_config.json — which meant an account whose tier did not include the    hardcoded default got a 403 on every generation.
    """
    captured: dict[str, Any] = {}

    def capture_factory(provider: str, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return _StubProvider()

    isolated_config["model"] = "mistral-small-latest"
    monkeypatch.setattr("avicenna.secrets.read_api_key", lambda provider="mistral": "fake-key")
    monkeypatch.setattr("avicenna.providers.registry.get_provider", capture_factory)

    result = auth.build_provider()

    assert result is not None
    assert captured["model"] == "mistral-small-latest"


def test_build_provider_env_var_overrides_user_config(
    monkeypatch: pytest.MonkeyPatch, isolated_config: dict[str, Any]
) -> None:
    """MISTRAL_MODEL env var wins over user_config.json when explicitly set."""
    captured: dict[str, Any] = {}

    def capture_factory(provider: str, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return _StubProvider()

    isolated_config["model"] = "mistral-small-latest"
    monkeypatch.setenv("MISTRAL_MODEL", "mistral-medium-latest")
    monkeypatch.setattr("avicenna.secrets.read_api_key", lambda provider="mistral": "fake-key")
    monkeypatch.setattr("avicenna.providers.registry.get_provider", capture_factory)

    result = auth.build_provider()

    assert result is not None
    assert captured["model"] == "mistral-medium-latest"


# ---------------------------------------------------------------------------
# Key validation maps failures to something a human can act on
# ---------------------------------------------------------------------------

class _RaisingProvider:
    name = "mistral"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def complete(self, **_: Any) -> Any:
        raise self._exc

    async def close(self) -> None:
        return None


def _provider_factory(exc: Exception | None):
    def factory(*_args: Any, **_kwargs: Any) -> Any:
        if exc is None:
            class _Ok(_RaisingProvider):
                async def complete(self, **_kw: Any) -> Any:
                    return object()

            return _Ok(RuntimeError("unused"))
        return _RaisingProvider(exc)

    return factory


@pytest.mark.asyncio
async def test_bad_key_reports_a_typo_not_a_stack_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from avicenna.providers.errors import AuthError

    monkeypatch.setattr(
        "avicenna.providers.registry.get_provider", _provider_factory(AuthError("401"))
    )
    result = await auth.validate_key("mistral", "bad-key", "mistral-large-latest")

    assert result.ok is False
    assert "typo" in result.detail.lower() or "rejected" in result.detail.lower()


@pytest.mark.asyncio
async def test_rate_limited_key_is_reported_as_working(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from avicenna.providers.errors import RateLimitError

    monkeypatch.setattr(
        "avicenna.providers.registry.get_provider",
        _provider_factory(RateLimitError("429")),
    )
    result = await auth.validate_key("mistral", "k", "mistral-large-latest")

    # A rate limit is not a bad key, and saying so avoids a pointless re-paste.
    assert result.ok is False
    assert "rate limited" in result.detail.lower()


@pytest.mark.asyncio
async def test_network_failure_is_distinguished_from_a_bad_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from avicenna.providers.errors import TransientError

    monkeypatch.setattr(
        "avicenna.providers.registry.get_provider",
        _provider_factory(TransientError("connection reset")),
    )
    result = await auth.validate_key("mistral", "k", "mistral-large-latest")

    assert result.ok is False
    assert "network" in result.detail.lower()


@pytest.mark.asyncio
async def test_good_key_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "avicenna.providers.registry.get_provider", _provider_factory(None)
    )
    result = await auth.validate_key("mistral", "good-key", "mistral-large-latest")

    assert result.ok is True
    assert "mistral-large-latest" in result.detail


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_persisting_a_key_marks_the_install_onboarded(
    isolated_config: dict[str, Any], tmp_path: Path
) -> None:
    store = auth.persist_key("good-key", vault_root=tmp_path)

    assert store == "test-store"
    assert isolated_config["onboarded"] is True
    assert isolated_config["provider"] == auth.DEFAULT_PROVIDER
    assert isolated_config["model"] == auth.DEFAULT_MODEL
    assert isolated_config["default_vault"] == str(tmp_path)
    assert isolated_config["_written"]["mistral"] == "good-key"


@pytest.mark.asyncio
async def test_validation_alone_never_persists(
    monkeypatch: pytest.MonkeyPatch, isolated_config: dict[str, Any]
) -> None:
    from avicenna.providers.errors import AuthError

    monkeypatch.setattr(
        "avicenna.providers.registry.get_provider", _provider_factory(AuthError("401"))
    )
    bridge = Bridge()
    result = await bridge._dispatch("auth.validate", {"key": "bad-key"})

    assert result["ok"] is False
    # A rejected key must leave no trace behind.
    assert "onboarded" not in isolated_config
    assert isolated_config["_written"] == {}


@pytest.mark.asyncio
async def test_empty_key_is_refused_before_any_network_call() -> None:
    bridge = Bridge()
    with pytest.raises(BridgeError, match="No key supplied"):
        await bridge._dispatch("auth.validate", {"key": "   "})


# ---------------------------------------------------------------------------
# The local-model option stays honest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_local_model_option_explains_itself_and_configures_nothing() -> None:
    bridge = Bridge()
    result = await bridge._dispatch("auth.local_stub", {})

    message = result["message"]
    assert len(message) > 100
    assert "planned for a future release" in message
    # It names the actual blocker rather than "coming soon".
    assert "tool call" in message


# ---------------------------------------------------------------------------
# Vault context still drives what the interface can offer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_vault_info_describes_a_bound_vault(tmp_path: Path) -> None:
    _vault(tmp_path)
    bridge = Bridge(str(tmp_path))
    info = await bridge._dispatch("vault.info", {})

    assert info["found"] is True
    assert info["root"] == str(tmp_path.resolve())
    assert info["agentCount"] == 1
    assert "general" in info["domains"]


@pytest.mark.asyncio
async def test_missing_vault_is_a_reportable_state_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "not-a-vault"
    empty.mkdir()
    monkeypatch.setattr(
        VaultContext, "detect",
        classmethod(lambda cls, explicit=None, cwd=None: cls(empty, None, "none", False, None)),
    )
    bridge = Bridge()
    info = await bridge._dispatch("vault.info", {})

    assert info["found"] is False
    assert info["badge"] == "NO VAULT"
    # Asking for a run without a vault must explain, not raise a traceback.
    with pytest.raises(BridgeError, match="No vault found"):
        await bridge._dispatch("run.note", {"topic": "anything"})
