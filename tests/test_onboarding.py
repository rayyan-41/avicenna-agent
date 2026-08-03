"""First-run onboarding and vault-context tests.

The v1.0.0 TUI opened straight to a chat pane with no provider, so any prompt
returned "No vault or provider configured". These tests exist so that cannot
regress silently: onboarding must appear on first run, the local-model option
must not proceed, and a validated key must configure the app.

`validate_key` is stubbed throughout. These cover the screen flow, not the
network, and the real keyring / user_config are never touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avicenna.bus import EventBus
from avicenna.tui.app import AvicennaApp
from avicenna.tui.screens import onboarding as ob
from avicenna.tui.screens.onboarding import (
    ApiKeyScreen,
    LocalModelStubScreen,
    ProviderSelectScreen,
    ValidationResult,
)
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
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AvicennaApp:
    # Never touch the real keyring or ~/.avicenna from a test.
    import avicenna.secrets as secrets
    from avicenna.config import Config

    monkeypatch.setattr(secrets, "write_api_key", lambda provider, key: "test-store")
    monkeypatch.setattr(Config, "save_user_config", staticmethod(lambda cfg: None))
    monkeypatch.setattr(Config, "load_user_config", staticmethod(dict))

    v = _vault(tmp_path)
    ctx = VaultContext.detect(cwd=tmp_path)
    return AvicennaApp(vault=v, bus=EventBus(), provider=None, context=ctx)


async def test_onboarding_appears_on_first_run(app: AvicennaApp) -> None:
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ProviderSelectScreen)
        ids = {b.id for b in app.screen.query("Button")}
        assert {"pick-api", "pick-local"} <= ids
        await pilot.press("ctrl+q")


async def test_local_model_explains_and_does_not_proceed(app: AvicennaApp) -> None:
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#pick-local")
        await pilot.pause()
        assert isinstance(app.screen, LocalModelStubScreen)

        body = " ".join(str(w.renderable) for w in app.screen.query("Static"))
        assert "tool calling" in body      # states the real reason
        assert app._provider is None       # and never configures a provider

        await pilot.click("#stub-back")
        await pilot.pause()
        assert isinstance(app.screen, ProviderSelectScreen)
        await pilot.press("ctrl+q")


async def test_api_key_field_is_masked_and_rejects_empty(app: AvicennaApp) -> None:
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#pick-api")
        await pilot.pause()
        assert isinstance(app.screen, ApiKeyScreen)
        assert app.screen.query_one("#api-key-input").password is True

        await pilot.press("enter")          # empty submit
        await pilot.pause()
        status = str(app.screen.query_one("#api-key-status").renderable)
        assert "Enter a key" in status
        assert app._provider is None
        await pilot.press("ctrl+q")


async def test_bad_key_shows_specific_error_and_clears_field(
    app: AvicennaApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def reject(*a: object, **k: object) -> ValidationResult:
        return ValidationResult(False, "Key rejected. Check for a typo or an expired key.")

    monkeypatch.setattr(ob, "validate_key", reject)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#pick-api")
        await pilot.pause()
        app.screen.query_one("#api-key-input").value = "bad-key"
        await pilot.press("enter")
        for _ in range(8):
            await pilot.pause()

        status = str(app.screen.query_one("#api-key-status").renderable)
        assert "rejected" in status.lower()
        assert app.screen.query_one("#api-key-input").value == ""
        assert app._provider is None
        await pilot.press("ctrl+q")


async def test_good_key_configures_provider_and_closes_onboarding(
    app: AvicennaApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def accept(*a: object, **k: object) -> ValidationResult:
        return ValidationResult(True, "Validated against mistral-large-latest.")

    monkeypatch.setattr(ob, "validate_key", accept)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#pick-api")
        await pilot.pause()
        app.screen.query_one("#api-key-input").value = "good-key"
        await pilot.press("enter")
        for _ in range(12):
            await pilot.pause()

        assert not isinstance(app.screen, (ApiKeyScreen, ProviderSelectScreen))
        assert app._provider is not None
        await pilot.press("ctrl+q")


async def test_existing_provider_skips_onboarding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from avicenna.providers.fake import FakeProvider

    v = _vault(tmp_path)
    ctx = VaultContext.detect(cwd=tmp_path)
    a = AvicennaApp(vault=v, bus=EventBus(), provider=FakeProvider(), context=ctx)
    async with a.run_test() as pilot:
        await pilot.pause()
        assert not isinstance(a.screen, (ProviderSelectScreen, ApiKeyScreen))
        await pilot.press("ctrl+q")
