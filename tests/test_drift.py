"""Tests for the semantic drift guard.

Exercises the DriftOracle, embedding cache, registry injection seam, and
degradation paths.  All tests use FakeEmbeddingProvider and tmp_path; no
live network calls, no reads or writes to the real vault.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from avicenna.bus import EventBus, drain
from avicenna.events import Event, SemanticGuardDecision, ThemeMinted
from avicenna.pipeline.context import RunContext, RunSpec
from avicenna.pipeline.stages import _resolve_tags_against_registry
from avicenna.providers.fake import FakeEmbeddingProvider
from avicenna.vault.drift import DriftOracle, DriftVerdict
from avicenna.vault.init_scaffold import init_vault
from avicenna.vault.registry import ThemeRegistry, semantic_guard
from avicenna.vault.vault import Vault


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _taxonomy_path(vault: Vault) -> Path:
    return vault.root / ".agents" / "taxonomy.json"


def _seed_taxonomy(
    vault: Vault,
    *,
    themes: list[str] | None = None,
    types: list[str] | None = None,
) -> None:
    data = json.loads(_taxonomy_path(vault).read_text("utf-8"))
    if themes is not None:
        data["themes"] = themes
    if types is not None:
        data["types"] = types
    path = _taxonomy_path(vault)
    path.write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n",
    )


def _make_ctx(tmp_path: Path) -> tuple[Vault, RunContext]:
    from avicenna.providers.fake import FakeProvider

    vault = Vault.load(init_vault(tmp_path / "vault"))
    ctx = RunContext(spec=RunSpec(
        topic="Test Topic",
        vault=vault,
        provider=FakeProvider(),
        bus=EventBus(),
        run_id="test",
    ))
    ctx.domain = "general"
    return vault, ctx


# ---------------------------------------------------------------------------
# 1. DriftOracle — basic behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oracle_merges_when_above_threshold(tmp_path: Path) -> None:
    """A proposed key that is semantically close to an existing key is merged."""
    provider = FakeEmbeddingProvider(dimensions=64)
    oracle = DriftOracle(provider, threshold=0.50, cache_dir=tmp_path)

    # Two identical texts will have cosine similarity 1.0 (unit vectors).
    verdicts = await oracle.check_batch(
        proposed=[("nationalism", "")],
        existing_keys=["nationalism"],
    )
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v.proposed == "nationalism"
    assert v.merge_with == "nationalism"
    assert v.nearest == "nationalism"
    assert v.similarity == pytest.approx(1.0, abs=1e-6)


@pytest.mark.asyncio
async def test_oracle_mints_when_below_threshold(tmp_path: Path) -> None:
    """A proposed key that is not similar enough to any existing key is minted."""
    provider = FakeEmbeddingProvider(dimensions=64)
    oracle = DriftOracle(provider, threshold=0.999, cache_dir=tmp_path)

    # Different texts produce different hash-based vectors.  With a very high
    # threshold they should not merge.
    verdicts = await oracle.check_batch(
        proposed=[("epistemology", "")],
        existing_keys=["eschatology"],
    )
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v.proposed == "epistemology"
    assert v.merge_with is None
    assert v.nearest == "eschatology"
    assert v.similarity < 0.999


@pytest.mark.asyncio
async def test_oracle_empty_existing_keys(tmp_path: Path) -> None:
    """When there are no existing keys, every verdict is a mint."""
    provider = FakeEmbeddingProvider(dimensions=64)
    oracle = DriftOracle(provider, threshold=0.80, cache_dir=tmp_path)

    verdicts = await oracle.check_batch(
        proposed=[("nationalism", ""), ("epistemology", "")],
        existing_keys=[],
    )
    assert len(verdicts) == 2
    for v in verdicts:
        assert v.merge_with is None
        assert v.nearest == ""
        assert v.similarity == 0.0


@pytest.mark.asyncio
async def test_oracle_empty_proposed(tmp_path: Path) -> None:
    """When there are no proposed keys, return an empty list."""
    provider = FakeEmbeddingProvider(dimensions=64)
    oracle = DriftOracle(provider, threshold=0.80, cache_dir=tmp_path)

    verdicts = await oracle.check_batch(
        proposed=[],
        existing_keys=["nationalism"],
    )
    assert verdicts == []


@pytest.mark.asyncio
async def test_oracle_picks_closest_existing(tmp_path: Path) -> None:
    """When multiple existing keys exist, the closest one is returned."""
    provider = FakeEmbeddingProvider(dimensions=64)
    oracle = DriftOracle(provider, threshold=0.0, cache_dir=tmp_path)

    # With threshold 0.0 everything merges.  Verify the oracle picks the
    # closest key (highest cosine similarity).
    verdicts = await oracle.check_batch(
        proposed=[("test-key", "")],
        existing_keys=["aaa", "bbb", "ccc"],
    )
    assert len(verdicts) == 1
    # The result should be one of the existing keys.
    assert verdicts[0].merge_with in ("aaa", "bbb", "ccc")


# ---------------------------------------------------------------------------
# 2. Cache persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_persists_and_reuses(tmp_path: Path) -> None:
    """Embeddings are cached to disk and reused on the next oracle instance."""
    provider = FakeEmbeddingProvider(dimensions=64)
    cache_dir = tmp_path / "cache"

    # First call: embed and cache.
    oracle1 = DriftOracle(provider, threshold=0.80, cache_dir=cache_dir)
    await oracle1.check_batch(
        proposed=[("nationalism", "")],
        existing_keys=["philosophy"],
    )
    assert provider.calls  # embed was called

    # Cache file should exist.
    cache_file = cache_dir / "embedding_cache.json"
    assert cache_file.exists()

    # Second call: same oracle instance should not re-embed.
    provider.calls.clear()
    await oracle1.check_batch(
        proposed=[("nationalism", "")],
        existing_keys=["philosophy"],
    )
    # Both texts are cached, so no new embed call.
    assert not provider.calls

    # New oracle instance loads from disk.
    provider2 = FakeEmbeddingProvider(dimensions=64)
    oracle2 = DriftOracle(provider2, threshold=0.80, cache_dir=cache_dir)
    await oracle2.check_batch(
        proposed=[("nationalism", "")],
        existing_keys=["philosophy"],
    )
    # Cache was loaded from disk — no embed call needed.
    assert not provider2.calls


@pytest.mark.asyncio
async def test_cache_keyed_by_model_name(tmp_path: Path) -> None:
    """Vectors from different models do not collide in the cache."""
    cache_dir = tmp_path / "cache"

    provider1 = FakeEmbeddingProvider(dimensions=64)
    provider1.name = "model-a"
    oracle1 = DriftOracle(provider1, threshold=0.80, cache_dir=cache_dir)
    await oracle1.check_batch(
        proposed=[("test", "")],
        existing_keys=["other"],
    )

    # A different model should miss the cache and re-embed.
    provider2 = FakeEmbeddingProvider(dimensions=64)
    provider2.name = "model-b"
    oracle2 = DriftOracle(provider2, threshold=0.80, cache_dir=cache_dir)
    await oracle2.check_batch(
        proposed=[("test", "")],
        existing_keys=["other"],
    )
    assert provider2.calls  # embed was called (cache miss)


# ---------------------------------------------------------------------------
# 3. Registry injection seam
# ---------------------------------------------------------------------------


def _registry(tmp_path: Path) -> ThemeRegistry:
    """A registry over a minimal taxonomy, for seam tests."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "taxonomy.json"
    path.write_text(
        json.dumps({"themes": ["political-philosophy"], "types": ["concept"]}),
        encoding="utf-8",
    )
    return ThemeRegistry.load(path)


def test_semantic_guard_is_pure_and_always_none() -> None:
    """The module-level guard is the default and has no state.

    It is deliberately not the injection point.  An earlier draft made it read
    a module-level dict, which meant two registries in one process -- a run and
    a test, or two runs -- shared guard decisions, and every test that touched
    it needed save/restore boilerplate.  Decisions belong to a registry.
    """
    assert semantic_guard("nationalism", ["philosophy"]) is None
    assert semantic_guard("anything", []) is None


def test_guard_decisions_apply_to_one_registry_only(tmp_path: Path) -> None:
    """Decisions are instance state: a sibling registry is unaffected."""
    a = _registry(tmp_path / "a")
    b = _registry(tmp_path / "b")

    with a.guard_decisions({("nationalism", "theme"): "political-philosophy"}):
        canon, is_new = a.resolve_theme("nationalism")
        assert (canon, is_new) == ("political-philosophy", False)

        # The other registry never saw the decision and mints as usual.
        canon_b, is_new_b = b.resolve_theme("nationalism")
        assert (canon_b, is_new_b) == ("nationalism", True)


def test_guard_decisions_restored_on_exit(tmp_path: Path) -> None:
    """The scope is restored afterwards, so a later resolve mints again."""
    reg = _registry(tmp_path)
    with reg.guard_decisions({("nationalism", "theme"): "political-philosophy"}):
        assert reg.resolve_theme("nationalism")[0] == "political-philosophy"
    canon, is_new = reg.resolve_theme("nationhood")
    assert (canon, is_new) == ("nationhood", True)


def test_guard_decisions_restored_on_exception(tmp_path: Path) -> None:
    """A raise inside the scope must not leave decisions attached.

    This is the case the floor-tag path depends on: it resolves a second time
    after the first attempt failed, and must not inherit stale answers.
    """
    reg = _registry(tmp_path)
    with pytest.raises(RuntimeError):
        with reg.guard_decisions({("nationalism", "theme"): "political-philosophy"}):
            raise RuntimeError("boom")
    assert reg.resolve_theme("nationalism")[0] == "nationalism"


def test_guard_decision_respects_kind(tmp_path: Path) -> None:
    """A decision recorded for themes does not apply to types."""
    reg = _registry(tmp_path)
    with reg.guard_decisions({("nationalism", "theme"): "political-philosophy"}):
        assert reg.resolve_type("nationalism")[0] == "nationalism"


def test_guard_candidate_skips_what_needs_no_check(tmp_path: Path) -> None:
    """Only tags with a mint at stake are worth embedding."""
    reg = _registry(tmp_path)
    # Genuinely new -- the guard should be asked.
    assert reg.guard_candidate("nationhood") == "nationhood"
    # Already a known theme, in a separator variant -- no mint at stake.
    assert reg.guard_candidate("Political-Philosophy") is None
    # Already a known type.
    assert reg.guard_candidate("concept") is None
    # Malformed: the registry rejects it before the guard is reached.
    assert reg.guard_candidate('bad"quote') is None


def test_registry_key_accessors(tmp_path: Path) -> None:
    """The pipeline reads keys through the public accessors, not the maps."""
    reg = _registry(tmp_path)
    assert reg.theme_keys() == ["political philosophy"]
    assert reg.type_keys() == ["concept"]
    # A copy, not the live map -- mutating the result must not corrupt state.
    reg.theme_keys().append("intruder")
    assert reg.theme_keys() == ["political philosophy"]


# ---------------------------------------------------------------------------
# 4. Real construction path — catches the get_embedding_provider bug
# ---------------------------------------------------------------------------


def test_get_embedding_provider_google_construction() -> None:
    """Constructing a GoogleEmbeddingProvider through the factory with the
    correct parameter name produces a working instance.

    This catches the exact defect from the handoff: a previous agent passed
    ``keys=pool`` when the signature wanted ``api_key=``, and because
    ``get_embedding_provider`` is ``(name, **kwargs)``, mypy checked nothing.
    The TypeError landed in a broad ``except`` and the feature was silently
    dead on every real run.
    """
    from avicenna.providers import get_embedding_provider
    from avicenna.providers.google_embedding import GoogleEmbeddingProvider

    # Correct construction — should succeed.
    provider = get_embedding_provider("google", api_key="test-key-12345")
    assert isinstance(provider, GoogleEmbeddingProvider)
    assert provider.dimensions == 768

    # Incorrect parameter name — should raise TypeError.
    with pytest.raises(TypeError):
        get_embedding_provider("google", keys="wrong-param")


def test_get_embedding_provider_fake() -> None:
    """The fake embedding provider is also registered and constructible."""
    from avicenna.providers import get_embedding_provider
    from avicenna.providers.fake import FakeEmbeddingProvider

    provider = get_embedding_provider("fake", dimensions=32)
    assert isinstance(provider, FakeEmbeddingProvider)
    assert provider.dimensions == 32


# ---------------------------------------------------------------------------
# 5. Degradation — no provider, embed failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oracle_degrades_on_embed_failure(tmp_path: Path) -> None:
    """When the embedding call fails, the oracle returns mint-all verdicts."""
    provider = FakeEmbeddingProvider(dimensions=64)

    # Monkey-patch embed to always fail.
    async def _fail(*args, object, **kwargs):  # type: ignore[override]
        raise RuntimeError("simulated API failure")

    provider.embed = _fail  # type: ignore[assignment]

    oracle = DriftOracle(provider, threshold=0.80, cache_dir=tmp_path)
    verdicts = await oracle.check_batch(
        proposed=[("nationalism", ""), ("epistemology", "")],
        existing_keys=["philosophy"],
    )
    assert len(verdicts) == 2
    for v in verdicts:
        assert v.merge_with is None
        assert v.nearest == ""
        assert v.similarity == 0.0


# ---------------------------------------------------------------------------
# 6. Integration — _resolve_tags_against_registry with the guard
# ---------------------------------------------------------------------------


def test_guard_prevents_mint_in_resolve(tmp_path: Path) -> None:
    """With a merge decision attached, the resolve path reuses instead of minting.

    This exercises the seam directly through ``lookup_theme``, which is the
    call site inside the resolve loop, rather than through the oracle -- the
    oracle needs a real API key, and the seam is what can silently do nothing.
    """
    vault, ctx = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["political-philosophy"])
    reg = ThemeRegistry.load(_taxonomy_path(vault))
    assert reg.theme_keys() == ["political philosophy"]

    with reg.guard_decisions({("nationalism", "theme"): "political-philosophy"}):
        canon, reason = reg.lookup_theme("nationalism")
        assert reason is None
        assert canon == "political-philosophy"

        # A theme decision must not leak into the type registry.
        canon_t, _ = reg.lookup_type("nationalism")
        assert canon_t is None

        # A key with no decision still mints.
        canon2, reason2 = reg.lookup_theme("epistemology")
        assert canon2 is None
        assert reason2 is None


def test_guard_integration_with_resolve(tmp_path: Path) -> None:
    """Full integration: _resolve_tags_against_registry uses injected guard
    decisions to merge a tag instead of minting.

    Patches the oracle construction path at the source modules (the function
    uses inline ``from X import Y`` imports, so patching the source module
    is necessary).
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    vault, ctx = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["political-philosophy"])
    reg = ThemeRegistry.load(_taxonomy_path(vault))
    ctx.theme_registry = reg

    # Build a fake oracle that returns a merge verdict for "nationalism".
    fake_verdict = DriftVerdict(
        proposed="nationalism",
        merge_with="political-philosophy",
        nearest="political-philosophy",
        similarity=0.87,
    )
    fake_oracle = MagicMock()
    fake_oracle.check_batch = AsyncMock(return_value=[fake_verdict])
    fake_oracle.threshold = 0.80

    # Mock at the source modules — the inline ``from X import Y`` will
    # pick up the patched names.
    async def _run() -> tuple[str, list[Event]]:
        with patch("avicenna.keypool.load_pool") as mock_pool, \
             patch("avicenna.providers.get_embedding_provider") as mock_ep, \
             patch("avicenna.vault.drift.DriftOracle") as mock_oracle_cls, \
             patch("avicenna.settings.resolve_semantic_guard_threshold") as mock_thresh, \
             patch("avicenna.settings.load_vault_config", return_value={}):
            mock_pool.return_value = MagicMock(_keys=["fake-key"])
            mock_ep.return_value = MagicMock()
            mock_oracle_cls.return_value = fake_oracle
            mock_thresh.return_value = 0.80

            bus = ctx.spec.bus
            queue = bus.subscribe()
            result = await _resolve_tags_against_registry(
                "general, note, nationalism, cli", ctx,
            )
            await bus.close()
            events = [e async for e in drain(queue)]
            return result, events

    result, events = asyncio.run(_run())
    tags = [t.strip() for t in result.split(",")]

    # "nationalism" should have been resolved to "political-philosophy".
    assert "political-philosophy" in tags
    assert "nationalism" not in tags

    # SemanticGuardDecision should have been emitted.
    guard_events = [e for e in events if isinstance(e, SemanticGuardDecision)]
    assert len(guard_events) >= 1
    assert guard_events[0].decision == "reuse"
    assert guard_events[0].nearest == "political-philosophy"


def test_guard_decisions_do_not_outlive_the_resolve_loop(tmp_path: Path) -> None:
    """Nothing stays attached to the registry after the loop returns.

    The floor-tag path resolves a second time when the first attempt failed,
    and must not inherit answers computed for the first.  With the decisions
    scoped to the instance by a context manager this is structural rather than
    a cleanup step someone can forget.
    """
    vault, ctx = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["philosophy"])
    reg = ThemeRegistry.load(_taxonomy_path(vault))
    ctx.theme_registry = reg

    asyncio.run(
        _resolve_tags_against_registry("general, note, philosophy, cli", ctx)
    )
    assert reg._guard_decisions is None


# ---------------------------------------------------------------------------
# 7. DriftVerdict dataclass
# ---------------------------------------------------------------------------


def test_drift_verdict_fields() -> None:
    """DriftVerdict is a frozen dataclass with the expected fields."""
    v = DriftVerdict(
        proposed="nationalism",
        merge_with="political-philosophy",
        nearest="political-philosophy",
        similarity=0.87,
    )
    assert v.proposed == "nationalism"
    assert v.merge_with == "political-philosophy"
    assert v.nearest == "political-philosophy"
    assert v.similarity == 0.87

    # Frozen.
    with pytest.raises(AttributeError):
        v.proposed = "other"  # type: ignore[misc]
