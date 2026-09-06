# Layered Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every user-relevant value in the harness configurable through one precedence chain, so a stranger can tune the engine without editing code.

**Architecture:** Settings split by ownership — vault policy in `.agents/config.json`, user preferences in `~/.avicenna/user_config.json`. One `Settings` resolver applies a single precedence chain (CLI flag, environment variable, scope file, built-in default) to every key. Existing module constants stay as the defaults table rather than as the values.

**Tech Stack:** Python 3.12, Typer, dataclasses, stdlib json. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-06-layered-configuration-design.md`

## Global Constraints

- `from __future__ import annotations` at the top of every Python module; everything fully annotated.
- `mypy --strict avicenna/providers avicenna/pipeline avicenna/bridge` must stay clean.
- UTF-8 without BOM, LF endings on every file write; pass `newline="\n"` explicitly.
- The reference vault name must not appear outside `tests/`.
- stdout belongs to the wire protocol; diagnostics go to stderr. Nothing under `avicenna/bridge/` may block.
- No vendor SDK outside `avicenna/providers/`.
- `pyproject.toml` is the only dependency manifest. Do not add a dependency.
- The full suite runs offline against `FakeProvider`; no test may require a key or a network call.
- `PROTOCOL_VERSION` is deliberately NOT configurable and must remain a module constant.
- A vault with no `.agents/config.json` must behave exactly as it does today.
- Every task ends green: `python -m pytest -q` and `python scripts/check_maps.py`.

---

### Task 1: The settings resolver

**Files:**
- Create: `avicenna/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Layer` enum with members `FLAG`, `ENV`, `FILE`, `DEFAULT`; frozen dataclass `SettingSpec(key, default, env, scope, cast, help)` where `scope` is `"user"` or `"vault"`; `REGISTRY: dict[str, SettingSpec]`; `Settings.load(*, vault_root, user_config, overrides) -> Settings`; `Settings.resolve(key) -> tuple[object, Layer]`; `Settings.get(key) -> object`.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest

from avicenna.settings import Layer, Settings


def test_default_layer_when_nothing_else_set(monkeypatch):
    monkeypatch.delenv("AVICENNA_CONCURRENCY", raising=False)
    s = Settings.load(vault_root=None, user_config={}, overrides={})
    assert s.resolve("concurrency") == (3, Layer.DEFAULT)


def test_file_beats_default(monkeypatch):
    monkeypatch.delenv("AVICENNA_CONCURRENCY", raising=False)
    s = Settings.load(vault_root=None, user_config={"concurrency": 7}, overrides={})
    assert s.resolve("concurrency") == (7, Layer.FILE)


def test_env_beats_file(monkeypatch):
    monkeypatch.setenv("AVICENNA_CONCURRENCY", "9")
    s = Settings.load(vault_root=None, user_config={"concurrency": 7}, overrides={})
    assert s.resolve("concurrency") == (9, Layer.ENV)


def test_flag_beats_env(monkeypatch):
    monkeypatch.setenv("AVICENNA_CONCURRENCY", "9")
    s = Settings.load(vault_root=None, user_config={"concurrency": 7},
                      overrides={"concurrency": 11})
    assert s.resolve("concurrency") == (11, Layer.FLAG)


def test_unknown_key_raises():
    s = Settings.load(vault_root=None, user_config={}, overrides={})
    with pytest.raises(KeyError, match="no_such_setting"):
        s.get("no_such_setting")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'avicenna.settings'`

- [ ] **Step 3: Write minimal implementation**

Create `avicenna/settings.py` containing `Layer`, `SettingSpec`, a `REGISTRY` holding at least `concurrency` (default `3`, env `AVICENNA_CONCURRENCY`, scope `user`, cast `int`), and a `Settings` dataclass holding the overrides dict, the user-config dict and the vault-config dict.

`resolve(key)` looks up `REGISTRY[key]`, then checks in order: the overrides dict; `os.environ[spec.env]` passed through `spec.cast`; the dict for `spec.scope`; finally `spec.default`. It returns the value paired with the `Layer` that supplied it.

`get(key)` returns only the value. An unknown key raises `KeyError` naming the key — a typo in a flag or a config file must be loud rather than silently `None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings.py -q`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add avicenna/settings.py tests/test_settings.py
git commit -m "feat: settings resolver with a single precedence chain"
```

---

### Task 2: Populate the registry from the existing constants

**Files:**
- Modify: `avicenna/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `REGISTRY`, `SettingSpec` from Task 1.
- Produces: registry keys `provider`, `model`, `concurrency`, `weaver_timeout_s`, `max_tool_iterations`, `provider_max_retries`, `provider_base_delay_s`, `routing_min_score`, `routing_min_margin`, `routing_weights`, `routing_stopwords`, `template_minimums`, `no_moc_domains`.

- [ ] **Step 1: Write the failing test**

```python
def test_registry_covers_the_documented_keys():
    from avicenna.settings import REGISTRY
    expected = {
        "provider", "model", "concurrency", "weaver_timeout_s",
        "max_tool_iterations", "provider_max_retries", "provider_base_delay_s",
        "routing_min_score", "routing_min_margin", "routing_weights",
        "routing_stopwords", "template_minimums", "no_moc_domains",
        "max_headings",
    }
    assert expected <= set(REGISTRY)


def test_vault_scoped_keys_are_marked_vault():
    from avicenna.settings import REGISTRY
    for key in ("template_minimums", "routing_weights", "routing_stopwords",
                "no_moc_domains", "routing_min_score", "routing_min_margin",
                "max_headings"):
        assert REGISTRY[key].scope == "vault", key


def test_user_scoped_keys_are_marked_user():
    from avicenna.settings import REGISTRY
    for key in ("provider", "model", "concurrency", "weaver_timeout_s",
                "max_tool_iterations"):
        assert REGISTRY[key].scope == "user", key


def test_defaults_match_the_current_constants():
    from avicenna.settings import REGISTRY
    from avicenna.pipeline.preflight import TEMPLATE_MINIMUMS
    assert REGISTRY["weaver_timeout_s"].default == 600.0
    assert REGISTRY["max_tool_iterations"].default == 8
    assert REGISTRY["routing_min_score"].default == 2.5
    assert REGISTRY["routing_min_margin"].default == 1.0
    assert REGISTRY["template_minimums"].default == TEMPLATE_MINIMUMS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings.py -q`
Expected: FAIL with `KeyError` on the first missing registry key.

- [ ] **Step 3: Write minimal implementation**

Add the remaining `SettingSpec` entries. Import the current constants as the defaults rather than retyping their values, so the constants stay the single source of truth:

- `weaver_timeout_s` from `WEAVER_TIMEOUT_S` in `avicenna.pipeline.stages`
- `max_tool_iterations` from `MAX_TOOL_ITERATIONS` in `avicenna.session`
- `provider_max_retries` and `provider_base_delay_s` from `_MAX_RETRIES` and `_BASE_DELAY` in `avicenna.providers.mistral`
- `routing_weights` as a dict built from `W_DOMAIN`, `W_CATEGORY`, `W_THEME`, `W_ENTITY`, `W_DESCRIPTION`; `routing_min_score`, `routing_min_margin`, `routing_stopwords` from `avicenna.vault.routing`
- `template_minimums` from `TEMPLATE_MINIMUMS` in `avicenna.pipeline.preflight`
- `provider` and `model` from `DEFAULT_PROVIDER` and `DEFAULT_MODEL` in `avicenna.auth`
- `max_headings`, default `40`, scope `vault`, taken from the literal currently
  inlined in `preflight.py` as `if len(headings) > 40`. This one was found by
  running the matrix: a smaller model declared sixty headings for a
  thousand-word note and the run was refused by a number no user could change.
  Replace that literal with a settings read in Task 6.

Perform these imports lazily inside a builder function if a module-level import would create a cycle. Env names follow `AVICENNA_<KEY_UPPER>`, except `model` and `provider` which also accept `AVICENNA_MODEL` and `AVICENNA_PROVIDER`. For dict- and set-valued settings the `cast` parses JSON from the environment.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add avicenna/settings.py tests/test_settings.py
git commit -m "feat: register every tunable, with current constants as defaults"
```

---

### Task 3: Vault-scope config file

**Files:**
- Modify: `avicenna/settings.py`
- Modify: `avicenna/vault/init_scaffold.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `Settings.load` from Task 1, `REGISTRY` from Task 2.
- Produces: `load_vault_config(vault_root: Path) -> dict[str, object]`; the file lives at `.agents/config.json`.

- [ ] **Step 1: Write the failing test**

```python
def test_vault_config_beats_default(tmp_path):
    from avicenna.settings import Layer, Settings
    agents = tmp_path / ".agents"
    agents.mkdir()
    (agents / "config.json").write_text('{"routing_min_score": 4.0}', encoding="utf-8")
    s = Settings.load(vault_root=tmp_path, user_config={}, overrides={})
    assert s.resolve("routing_min_score") == (4.0, Layer.FILE)


def test_missing_vault_config_is_not_an_error(tmp_path):
    from avicenna.settings import Layer, Settings
    s = Settings.load(vault_root=tmp_path, user_config={}, overrides={})
    assert s.resolve("routing_min_score") == (2.5, Layer.DEFAULT)


def test_malformed_vault_config_falls_back_and_warns(tmp_path, capsys):
    from avicenna.settings import Layer, Settings
    agents = tmp_path / ".agents"
    agents.mkdir()
    (agents / "config.json").write_text("{not json", encoding="utf-8")
    s = Settings.load(vault_root=tmp_path, user_config={}, overrides={})
    assert s.resolve("routing_min_score")[1] is Layer.DEFAULT
    assert "config.json" in capsys.readouterr().err


def test_init_scaffolds_a_populated_config(tmp_path):
    import json
    from avicenna.settings import REGISTRY
    from avicenna.vault.init_scaffold import init_vault
    root = init_vault(tmp_path / "v")
    data = json.loads((root / ".agents" / "config.json").read_text(encoding="utf-8"))
    vault_keys = {k for k, spec in REGISTRY.items() if spec.scope == "vault"}
    assert vault_keys <= set(data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings.py -q`
Expected: FAIL — the vault config is never read and `init_vault` writes no `config.json`.

- [ ] **Step 3: Write minimal implementation**

Add `load_vault_config(vault_root)` reading `.agents/config.json`. Return `{}` when the file is absent. On a parse error, write a warning naming the file to **stderr** and return `{}` — a malformed config must degrade to defaults rather than abort, and it must say so.

Wire the result into `Settings.load` as the `"vault"` scope dict.

For `no_moc_domains`, read `noMoc` from `taxonomy.json` as a fallback so existing vaults keep working unchanged, with `config.json` winning when both define it.

In `init_scaffold.py`, write a `config.json` containing every vault-scoped registry key at its default value, so a user who opens it sees the whole engine rather than a blank file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add avicenna/settings.py avicenna/vault/init_scaffold.py tests/test_settings.py
git commit -m "feat: vault-scoped config.json, scaffolded with every key"
```

---

### Task 4: Fix provider and model resolution

**Files:**
- Modify: `avicenna/auth.py`
- Modify: `avicenna/bridge/server.py` (the `auth.validate` handler)
- Test: `tests/test_onboarding.py`

**Interfaces:**
- Consumes: `Settings` from Task 1, registry keys `provider` and `model` from Task 2.
- Produces: `resolve_provider_name() -> str`; `resolve_model() -> str`; `build_provider() -> LLMProvider | None` keeping its current behaviour of returning `None` when no key is configured.

- [ ] **Step 1: Write the failing test**

```python
def test_persist_key_preserves_an_existing_model(tmp_path, monkeypatch):
    from avicenna.auth import persist_key
    from avicenna.config import Config
    monkeypatch.setattr(Config, "USER_CONFIG_PATH", tmp_path / "user_config.json")
    Config.save_user_config({"model": "ministral-8b-latest", "provider": "mistral"})
    persist_key("sk-test-key")
    cfg = Config.load_user_config()
    assert cfg["model"] == "ministral-8b-latest"
    assert cfg["provider"] == "mistral"


def test_build_provider_uses_the_configured_model(tmp_path, monkeypatch):
    from avicenna.auth import build_provider
    from avicenna.config import Config
    monkeypatch.setattr(Config, "USER_CONFIG_PATH", tmp_path / "user_config.json")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("AVICENNA_MODEL", raising=False)
    Config.save_user_config({"model": "ministral-3b-latest", "provider": "mistral",
                             "api_keys": {"mistral": "sk-test"}})
    provider = build_provider()
    assert provider is not None
    assert getattr(provider, "_model") == "ministral-3b-latest"


def test_provider_name_comes_from_config(tmp_path, monkeypatch):
    from avicenna.auth import resolve_provider_name
    from avicenna.config import Config
    monkeypatch.setattr(Config, "USER_CONFIG_PATH", tmp_path / "user_config.json")
    monkeypatch.delenv("AVICENNA_PROVIDER", raising=False)
    Config.save_user_config({"provider": "someprovider"})
    assert resolve_provider_name() == "someprovider"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_onboarding.py -q`
Expected: FAIL — `persist_key` overwrites `model`, and `resolve_provider_name` does not exist.

- [ ] **Step 3: Write minimal implementation**

Add `resolve_provider_name()` and `resolve_model()` that read through `Settings`. Change `build_provider` to use them, and to call `read_api_key(resolve_provider_name())` so a key stored for a non-Mistral provider is reachable.

Change `persist_key` to write only `onboarded`, `key_store`, and `default_vault`. It must not write `provider` or `model`: overwriting the user's choice on every key save is the defect this task exists to remove.

In `bridge/server.py`, replace `validate_key(DEFAULT_PROVIDER, key, DEFAULT_MODEL)` with the resolved provider and model, so onboarding validates the credential the user will actually use.

Keep `DEFAULT_PROVIDER` and `DEFAULT_MODEL` as the registry defaults; callers stop reading them directly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_onboarding.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add avicenna/auth.py avicenna/bridge/server.py tests/test_onboarding.py
git commit -m "fix: resolve provider and model from config instead of constants"
```

---

### Task 5: The `avicenna config` command group

**Files:**
- Modify: `avicenna/cli/app.py`
- Test: `tests/test_onboarding.py`

**Interfaces:**
- Consumes: `Settings`, `REGISTRY`, `Layer` from Tasks 1-3.
- Produces: `avicenna config show`, `avicenna config get <key>`, `avicenna config set <key> <value>`. The existing `config reset` keeps its behaviour.

- [ ] **Step 1: Write the failing test**

```python
def test_config_show_lists_key_value_and_layer(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from avicenna.cli.app import app
    from avicenna.config import Config
    monkeypatch.setattr(Config, "USER_CONFIG_PATH", tmp_path / "user_config.json")
    result = CliRunner().invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "concurrency" in result.stdout
    assert "default" in result.stdout.lower()


def test_config_set_then_get_roundtrips(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from avicenna.cli.app import app
    from avicenna.config import Config
    monkeypatch.setattr(Config, "USER_CONFIG_PATH", tmp_path / "user_config.json")
    monkeypatch.delenv("AVICENNA_CONCURRENCY", raising=False)
    runner = CliRunner()
    assert runner.invoke(app, ["config", "set", "concurrency", "5"]).exit_code == 0
    out = runner.invoke(app, ["config", "get", "concurrency"])
    assert out.exit_code == 0
    assert "5" in out.stdout


def test_config_set_rejects_an_unknown_key(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from avicenna.cli.app import app
    from avicenna.config import Config
    monkeypatch.setattr(Config, "USER_CONFIG_PATH", tmp_path / "user_config.json")
    result = CliRunner().invoke(app, ["config", "set", "nonsense", "1"])
    assert result.exit_code != 0
    assert "nonsense" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_onboarding.py -q`
Expected: FAIL — no `config show` / `get` / `set` command exists.

- [ ] **Step 3: Write minimal implementation**

Add the three commands to the existing `config` Typer group, following the style of the commands already in `app.py`.

`show` prints one aligned row per registry key: the key, its effective value, and the layer that supplied it. That third column is the point of the command; without it "editable" is a claim rather than something a user can verify.

`set` writes to the file for that key's scope: user config for `scope == "user"`, the vault's `.agents/config.json` for `scope == "vault"`. It refuses an unknown key with a non-zero exit and a message naming the key, rather than silently creating one.

`get` prints the effective value alone, so it composes in a shell.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_onboarding.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add avicenna/cli/app.py tests/test_onboarding.py
git commit -m "feat: avicenna config show/get/set with the deciding layer shown"
```

---

### Task 6: Per-run flags, and the engine reading its tunables

**Files:**
- Modify: `avicenna/cli/app.py`
- Modify: `avicenna/pipeline/context.py`
- Modify: `avicenna/pipeline/preflight.py`
- Modify: `avicenna/pipeline/stages.py`
- Modify: `avicenna/vault/routing.py`
- Modify: `avicenna/session.py`
- Test: `tests/test_pipeline_e2e.py`

**Interfaces:**
- Consumes: `Settings` from Task 1; `resolve_model` from Task 4.
- Produces: `RunSpec.settings: Settings`; `minimum_words(template: str, settings: Settings | None = None) -> int`; `avicenna note` options `--model`, `--provider`, `--concurrency`, `--weaver-timeout`.

- [ ] **Step 1: Write the failing test**

```python
def test_template_minimum_comes_from_the_vault(tmp_path):
    from avicenna.pipeline.preflight import minimum_words
    from avicenna.settings import Settings
    agents = tmp_path / ".agents"
    agents.mkdir()
    (agents / "config.json").write_text(
        '{"template_minimums": {"general": 250}}', encoding="utf-8")
    s = Settings.load(vault_root=tmp_path, user_config={}, overrides={})
    assert minimum_words("general", s) == 250


def test_minimum_words_falls_back_to_the_constant():
    from avicenna.pipeline.preflight import TEMPLATE_MINIMUMS, minimum_words
    assert minimum_words("general", None) == TEMPLATE_MINIMUMS["general"]


def test_routing_threshold_comes_from_the_vault(tmp_path):
    from avicenna.settings import Settings
    agents = tmp_path / ".agents"
    agents.mkdir()
    (agents / "config.json").write_text('{"routing_min_score": 99.0}', encoding="utf-8")
    s = Settings.load(vault_root=tmp_path, user_config={}, overrides={})
    assert s.get("routing_min_score") == 99.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline_e2e.py -q`
Expected: FAIL — `minimum_words` does not exist; preflight indexes the module constant directly.

- [ ] **Step 3: Write minimal implementation**

Add a `settings: Settings` field to `RunSpec`. Add `minimum_words(template, settings=None)` to `preflight.py` reading `template_minimums` through settings and falling back to `TEMPLATE_MINIMUMS` when settings is `None`; call it everywhere the constant was indexed.

Thread settings into `score_domains` and `route_request` for the weights, `routing_min_score`, `routing_min_margin` and `routing_stopwords`; into `stages.py` for `weaver_timeout_s` and `no_moc_domains`; into `session.py` for `max_tool_iterations`.

Every one of these parameters defaults to `None` and falls back to the existing module constant, so no current caller breaks and the routing regression tests keep passing untouched.

Add `--model`, `--provider`, `--concurrency` and `--weaver-timeout` to `avicenna note`, collecting only the options the user actually supplied into the `overrides` dict passed to `Settings.load`. An option left unset must NOT appear in `overrides`, or its default would outrank the user's config file.

- [ ] **Step 4: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS, whole suite

- [ ] **Step 5: Commit**

```bash
git add avicenna/ tests/
git commit -m "feat: engine reads tunables through settings; note takes per-run flags"
```

---

### Task 7: Derive probe topics from the vault, and document the system

**Files:**
- Modify: `scripts/healthcheck.py`
- Modify: `scripts/gen_matrix.py`
- Modify: `README.md`
- Modify: `MAP.md`
- Modify: `scripts/MAP.md`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: everything above.
- Produces: no new public API.

- [ ] **Step 1: Write the failing test**

```python
def test_every_registry_key_has_help_text():
    from avicenna.settings import REGISTRY
    missing = sorted(k for k, spec in REGISTRY.items() if not spec.help.strip())
    assert missing == [], f"registry keys without help text: {missing}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings.py -q`
Expected: FAIL, listing every key whose `help` is empty.

- [ ] **Step 3: Write minimal implementation**

Fill in `help` for every registry entry. This text is what `config show` prints and what the scaffolded `config.json` uses as its per-key comment, so it must say what the setting does rather than restate its name.

In `healthcheck.py` and `gen_matrix.py`, replace the hardcoded per-domain topic maps. Read topics from the vault's `.agents/config.json` under a `probe_topics` key; when absent, derive one topic per domain from that domain's categories in `taxonomy.json`. Neither script may assume one particular vault's domain names — both currently hardcode six.

Add a `## Configuration` section to `README.md` documenting the two scopes, the precedence chain, and the three `config` commands. Update the state-of-the-world table and command list in `MAP.md`, and the `scripts/MAP.md` rows for both scripts.

- [ ] **Step 4: Run every gate**

Run: `python -m pytest -q`
Run: `mypy --strict avicenna/providers avicenna/pipeline avicenna/bridge`
Run: `python scripts/check_protocol_parity.py`
Run: `python scripts/check_maps.py`
Expected: all four pass

- [ ] **Step 5: Commit**

```bash
git add avicenna/ scripts/ docs/ README.md MAP.md tests/
git commit -m "feat: derive probe topics from the vault; document configuration"
```

---

### Task 8: Vault-owned contract tokens and note placement

**Files:**
- Modify: `avicenna/settings.py`
- Modify: `avicenna/tools/contracts.py`
- Modify: `avicenna/pipeline/stages.py`
- Test: `tests/test_tools.py`
- Test: `tests/test_pipeline_e2e.py`

**Interfaces:**
- Consumes: `Settings`, `REGISTRY`, `SettingSpec` from Tasks 1-3.
- Produces: registry keys `contract_overrides` and `domain_folders`, both vault-scoped; `contracts_for(settings: Settings | None = None) -> Mapping[str, ToolContract]`; `note_folder(domain: str, settings: Settings | None = None) -> str`.

The spec lists tool contract tokens and folder conventions as vault policy. A vault ships its own `.ps1` tools, so the strings those tools emit belong to the vault, not to the engine. Likewise a vault may not organise domains as Title-Case folders at its root.

- [ ] **Step 1: Write the failing test**

```python
def test_contract_tokens_can_be_overridden_by_the_vault(tmp_path):
    from avicenna.settings import Settings
    from avicenna.tools.contracts import contracts_for
    agents = tmp_path / ".agents"
    agents.mkdir()
    (agents / "config.json").write_text(
        '{"contract_overrides": {"word_count": {"success": "WORDS=(?P<count>[0-9]+)"}}}',
        encoding="utf-8")
    s = Settings.load(vault_root=tmp_path, user_config={}, overrides={})
    contracts = contracts_for(s)
    parsed = contracts["word_count"].parse("WORDS=1234")
    assert parsed is not None
    assert parsed.captures["count"] == "1234"


def test_contracts_fall_back_to_the_builtin_table():
    from avicenna.tools.contracts import CONTRACTS, contracts_for
    assert contracts_for(None) == CONTRACTS


def test_note_folder_defaults_to_title_case():
    from avicenna.pipeline.stages import note_folder
    assert note_folder("history", None) == "History"
    assert note_folder("computer-science", None) == "Computer Science"


def test_note_folder_honours_a_vault_mapping(tmp_path):
    from avicenna.pipeline.stages import note_folder
    from avicenna.settings import Settings
    agents = tmp_path / ".agents"
    agents.mkdir()
    (agents / "config.json").write_text(
        '{"domain_folders": {"history": "01 - History", "art": "notes/art"}}',
        encoding="utf-8")
    s = Settings.load(vault_root=tmp_path, user_config={}, overrides={})
    assert note_folder("history", s) == "01 - History"
    assert note_folder("art", s) == "notes/art"
    assert note_folder("science", s) == "Science"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tools.py tests/test_pipeline_e2e.py -q`
Expected: FAIL — `contracts_for` and `note_folder` do not exist.

- [ ] **Step 3: Write minimal implementation**

Add two vault-scoped registry entries: `contract_overrides` (default `{}`) and `domain_folders` (default `{}`).

Add `contracts_for(settings)` to `contracts.py`. With `None` it returns `CONTRACTS` unchanged. Otherwise it returns a copy of `CONTRACTS` with each named entry's `success` and/or `failure` pattern replaced by the vault's. An override naming an unknown tool is a warning on stderr, not a crash — the vault may carry entries for tools it no longer ships. An override whose regex does not compile is also a warning, and that single entry falls back to the builtin, so one bad pattern cannot disable every contract.

Replace every direct read of `CONTRACTS` in the pipeline with `contracts_for(ctx.spec.settings)`.

Extract the folder rule out of `_note_destination` into `note_folder(domain, settings)`. Default behaviour is exactly today's: `domain.replace("-", " ").title()`. When `domain_folders` supplies a value for the domain, use it verbatim, allowing a nested path. `_note_destination` then joins the vault root with that result and keeps its existing collision handling untouched — the guard against overwriting an existing note must not change.

- [ ] **Step 4: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS, whole suite

- [ ] **Step 5: Commit**

```bash
git add avicenna/ tests/
git commit -m "feat: vault-owned contract tokens and note placement"
```
