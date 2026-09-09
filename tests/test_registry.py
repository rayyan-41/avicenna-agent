"""Tests for the theme/type registry (T34 Part B).

The registry accumulates inferred themes and types in taxonomy.json so the
harness maintains a map of the reader's mind.  Every test uses tmp_path;
none touch the real vault.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from typing import Any

from avicenna.bus import EventBus, drain
from avicenna.events import Event, ThemeMinted, TagsProposed, TagsValidated
from avicenna.pipeline.context import RunContext, RunSpec
from avicenna.pipeline.stages import (
    _resolve_tags_against_registry,
    build_frontmatter,
    extract_tag_line,
)
from avicenna.providers.fake import FakeProvider
from avicenna.vault.init_scaffold import init_vault
from avicenna.vault.registry import ThemeRegistry, _normalize, semantic_guard
from avicenna.vault.vault import Vault


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _taxonomy_path(vault: Vault) -> Path:
    return vault.root / ".agents" / "taxonomy.json"


def _load_taxonomy(vault: Vault) -> dict[str, Any]:
    return json.loads(_taxonomy_path(vault).read_text("utf-8"))


def _seed_taxonomy(vault: Vault, *, themes: list[str] | None = None,
                   types: list[str] | None = None) -> None:
    """Write a taxonomy.json with the given themes/types for testing."""
    data = _load_taxonomy(vault)
    if themes is not None:
        data["themes"] = themes
    if types is not None:
        data["types"] = types
    path = _taxonomy_path(vault)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def _make_ctx(tmp_path: Path) -> tuple[Vault, RunContext]:
    """Create a scaffolded vault and a RunContext for testing."""
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
# 1. A theme already in the registry is reused, and the registry is unchanged
# ---------------------------------------------------------------------------


def test_existing_theme_reused(tmp_path: Path) -> None:
    """A theme that already exists in the registry is reused and the file is
    not rewritten."""
    vault, ctx = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["philosophy", "epistemology"])

    reg = ThemeRegistry.load(_taxonomy_path(vault))
    ctx.theme_registry = reg

    canon, is_new = reg.resolve_theme("philosophy")
    assert canon == "philosophy"
    assert not is_new
    assert not reg._dirty
    assert reg.theme_count == 2


# ---------------------------------------------------------------------------
# 2. A genuinely new theme is minted, appended to taxonomy.json, and reported
# ---------------------------------------------------------------------------


def test_new_theme_minted_and_persisted(tmp_path: Path) -> None:
    """A genuinely new theme is minted, appended, and reported."""
    vault, ctx = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["philosophy"])

    reg = ThemeRegistry.load(_taxonomy_path(vault))

    canon, is_new = reg.resolve_theme("nationalism")
    assert canon == "nationalism"
    assert is_new
    assert reg._minted_themes == ["nationalism"]
    assert reg.theme_count == 2

    # Persist and verify on disk.
    assert reg.persist()
    data = _load_taxonomy(vault)
    assert data["themes"] == ["philosophy", "nationalism"]


def test_theme_minted_event_emitted(tmp_path: Path) -> None:
    """Resolving a new theme emits ThemeMinted with the correct fields."""
    vault, ctx = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["philosophy"])
    ctx.theme_registry = ThemeRegistry.load(_taxonomy_path(vault))

    import asyncio

    async def _run() -> list[Event]:
        bus = ctx.spec.bus
        queue = bus.subscribe()
        await _resolve_tags_against_registry(
            "general, note, nationalism, cli", ctx,
        )
        await bus.close()
        return [e async for e in drain(queue)]

    events = asyncio.run(_run())
    minted = [e for e in events if isinstance(e, ThemeMinted)]
    assert len(minted) >= 1
    assert "nationalism" in minted[0].minted
    assert minted[0].kind == "theme"


# ---------------------------------------------------------------------------
# 3. Normalisation folds case, separator and plural variants onto one entry
# ---------------------------------------------------------------------------


def test_normalization_case_insensitive(tmp_path: Path) -> None:
    """Case variants fold onto one entry."""
    vault, _ = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["Nationalism"])

    reg = ThemeRegistry.load(_taxonomy_path(vault))

    canon, is_new = reg.resolve_theme("nationalism")
    assert canon == "Nationalism"
    assert not is_new

    canon, is_new = reg.resolve_theme("NATIONALISM")
    assert canon == "Nationalism"
    assert not is_new


def test_normalization_separator_insensitive(tmp_path: Path) -> None:
    """Separator variants (hyphen, underscore, space) fold onto one entry."""
    vault, _ = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["political-philosophy"])

    reg = ThemeRegistry.load(_taxonomy_path(vault))

    canon, is_new = reg.resolve_theme("political_philosophy")
    assert canon == "political-philosophy"
    assert not is_new

    canon, is_new = reg.resolve_theme("political philosophy")
    assert canon == "political-philosophy"
    assert not is_new


def test_normalization_plural_insensitive(tmp_path: Path) -> None:
    """Plural variants fold onto one entry."""
    vault, _ = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["nationalism"])

    reg = ThemeRegistry.load(_taxonomy_path(vault))

    canon, is_new = reg.resolve_theme("nationalisms")
    assert canon == "nationalism"
    assert not is_new


def test_normalize_function() -> None:
    """The _normalize function handles edge cases."""
    assert _normalize("Nationalism") == "nationalism"
    assert _normalize("national-identity") == "national identity"
    assert _normalize("national_identity") == "national identity"
    assert _normalize("churches") == "church"
    assert _normalize("nationalisms") == "nationalism"
    assert _normalize("categories") == "category"
    # Short words (≤3 chars) with trailing 's' are left alone.
    assert _normalize("bus") == "bus"


# ---------------------------------------------------------------------------
# 4. taxonomy.json keeps every unrelated key, its key order, and indentation
# ---------------------------------------------------------------------------


def test_taxonomy_preserves_key_order(tmp_path: Path) -> None:
    """Persisting the registry preserves all keys and their order."""
    vault, _ = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["philosophy"])

    reg = ThemeRegistry.load(_taxonomy_path(vault))
    reg.resolve_theme("nationalism")
    reg.persist()

    text = _taxonomy_path(vault).read_text("utf-8")
    data = json.loads(text)
    # Every original key must still be present.
    assert "version" in data
    assert "schema" in data
    assert "domains" in data
    assert "themes" in data
    assert "types" in data
    # themes must contain both original and new.
    assert "philosophy" in data["themes"]
    assert "nationalism" in data["themes"]


def test_taxonomy_preserves_indentation(tmp_path: Path) -> None:
    """Persisting preserves the file's indentation style."""
    vault, _ = _make_ctx(tmp_path)
    # Write with 4-space indent.
    data = _load_taxonomy(vault)
    data["themes"] = ["philosophy"]
    path = _taxonomy_path(vault)
    path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8", newline="\n")

    reg = ThemeRegistry.load(path)
    reg.resolve_theme("nationalism")
    reg.persist()

    text = path.read_text("utf-8")
    # Verify 4-space indent is preserved.
    assert '    "version"' in text
    data2 = json.loads(text)
    assert "philosophy" in data2["themes"]
    assert "nationalism" in data2["themes"]


# ---------------------------------------------------------------------------
# 5. validate_tags is called AFTER the registry write
# ---------------------------------------------------------------------------


def test_validate_tags_called_after_registry_write(tmp_path: Path) -> None:
    """A note introducing a new theme validates rather than failing because
    the registry is persisted before validate_tags is invoked.

    This is tested by verifying that the taxonomy.json on disk contains the
    new theme AFTER _resolve_tags_against_registry returns.
    """
    vault, ctx = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["philosophy"])
    ctx.theme_registry = ThemeRegistry.load(_taxonomy_path(vault))

    import asyncio
    asyncio.run(_resolve_tags_against_registry(
        "general, note, nationalism, cli", ctx,
    ))

    # taxonomy.json must now contain the new theme on disk.
    data = _load_taxonomy(vault)
    assert "nationalism" in data["themes"]


# ---------------------------------------------------------------------------
# 6. An unwritable taxonomy.json warns and the run still completes
# ---------------------------------------------------------------------------


def test_unwritable_taxonomy_warns_and_continues(tmp_path: Path) -> None:
    """When taxonomy.json is unwritable, the resolver warns and continues."""
    vault, ctx = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["philosophy"])
    path = _taxonomy_path(vault)

    # Make the file read-only (Windows-compatible).
    os.chmod(path, stat.S_IREAD)

    ctx.theme_registry = ThemeRegistry.load(path)

    import asyncio

    async def _run() -> list[Event]:
        bus = ctx.spec.bus
        queue = bus.subscribe()
        result = await _resolve_tags_against_registry(
            "general, note, nationalism, cli", ctx,
        )
        await bus.close()
        return [e async for e in drain(queue)], result

    events, result = asyncio.run(_run())

    # Restore permissions for cleanup.
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)

    # A warning was emitted.
    warnings = [e for e in events
                if hasattr(e, "level") and e.level == "warning"]
    assert any("unwritable" in e.text for e in warnings)

    # The resolved line still contains the new theme (in-memory).
    assert "nationalism" in result


# ---------------------------------------------------------------------------
# 7. The write is atomic (no partial file on failure)
# ---------------------------------------------------------------------------


def test_atomic_write_no_partial_file(tmp_path: Path) -> None:
    """On a successful persist, no .part temp file remains."""
    vault, _ = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["philosophy"])
    path = _taxonomy_path(vault)

    reg = ThemeRegistry.load(path)
    reg.resolve_theme("nationalism")
    assert reg.persist()

    assert not path.with_suffix(".json.part").exists()
    assert path.exists()
    data = json.loads(path.read_text("utf-8"))
    assert "nationalism" in data["themes"]


def test_failed_write_removes_part_file(tmp_path: Path) -> None:
    """On a failed persist, the .part temp file is cleaned up."""
    vault, _ = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["philosophy"])
    path = _taxonomy_path(vault)

    reg = ThemeRegistry.load(path)
    reg.resolve_theme("nationalism")

    # Make the file read-only so os.replace fails.
    os.chmod(path, stat.S_IREAD)
    ok = reg.persist()
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)

    assert not ok
    assert not path.with_suffix(".json.part").exists()


# ---------------------------------------------------------------------------
# 8. Types accumulate the same way as themes
# ---------------------------------------------------------------------------


def test_type_reused(tmp_path: Path) -> None:
    """An existing type is reused."""
    vault, _ = _make_ctx(tmp_path)
    _seed_taxonomy(vault, types=["person", "concept"])

    reg = ThemeRegistry.load(_taxonomy_path(vault))
    canon, is_new = reg.resolve_type("person")
    assert canon == "person"
    assert not is_new
    assert reg.type_count == 2


def test_new_type_minted(tmp_path: Path) -> None:
    """A genuinely new type is minted and persisted."""
    vault, _ = _make_ctx(tmp_path)
    _seed_taxonomy(vault, types=["person"])

    reg = ThemeRegistry.load(_taxonomy_path(vault))
    canon, is_new = reg.resolve_type("event")
    assert canon == "event"
    assert is_new
    assert reg._minted_types == ["event"]
    reg.persist()

    data = _load_taxonomy(vault)
    assert data["types"] == ["person", "event"]


def test_type_normalization(tmp_path: Path) -> None:
    """Type normalization works the same as themes."""
    vault, _ = _make_ctx(tmp_path)
    _seed_taxonomy(vault, types=["concept"])

    reg = ThemeRegistry.load(_taxonomy_path(vault))
    canon, is_new = reg.resolve_type("Concepts")
    assert canon == "concept"
    assert not is_new


# ---------------------------------------------------------------------------
# 9. An existing note's tags are unaffected by any of this
# ---------------------------------------------------------------------------


def test_registry_does_not_mutate_existing_tags(tmp_path: Path) -> None:
    """The registry resolution does not change tags that are already in the
    vault's taxonomy (domain, category, entity, marker tags pass through)."""
    vault, ctx = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["philosophy"])
    ctx.theme_registry = ThemeRegistry.load(_taxonomy_path(vault))

    import asyncio

    async def _resolve() -> str:
        return await _resolve_tags_against_registry(
            "general, note, philosophy, cli", ctx,
        )

    result = asyncio.run(_resolve())
    tags = [t.strip() for t in result.split(",")]
    # Domain, category, marker pass through unchanged.
    assert "general" in tags
    assert "note" in tags
    assert "cli" in tags
    # Philosophy was already in the registry — unchanged.
    assert "philosophy" in tags


# ---------------------------------------------------------------------------
# Semantic guard seam
# ---------------------------------------------------------------------------


def test_semantic_guard_returns_none() -> None:
    """The semantic guard seam currently returns None for every proposed key."""
    assert semantic_guard("nationalism", ["political-philosophy"]) is None
    assert semantic_guard("anything", []) is None


# ---------------------------------------------------------------------------
# ThemeRegistry.load and edge cases
# ---------------------------------------------------------------------------


def test_registry_load_round_trip(tmp_path: Path) -> None:
    """Load → mutate → persist → reload preserves all data."""
    vault, _ = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["philosophy"], types=["person"])

    reg = ThemeRegistry.load(_taxonomy_path(vault))
    reg.resolve_theme("nationalism")
    reg.resolve_type("event")
    reg.persist()

    reg2 = ThemeRegistry.load(_taxonomy_path(vault))
    assert reg2.theme_count == 2
    assert reg2.type_count == 2
    assert reg2.themes_for_hint() == ["philosophy", "nationalism"]
    assert reg2.types_for_hint() == ["person", "event"]


def test_registry_load_empty_arrays(tmp_path: Path) -> None:
    """Registry loads correctly with empty themes and types."""
    vault, _ = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=[], types=[])

    reg = ThemeRegistry.load(_taxonomy_path(vault))
    assert reg.theme_count == 0
    assert reg.type_count == 0
    assert reg.themes_for_hint() == []
    assert reg.types_for_hint() == []


def test_multiple_mints_in_one_session(tmp_path: Path) -> None:
    """Multiple new themes can be minted in one registry session."""
    vault, _ = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=[])

    reg = ThemeRegistry.load(_taxonomy_path(vault))
    reg.resolve_theme("nationalism")
    reg.resolve_theme("political-philosophy")
    reg.resolve_theme("enlightenment")
    assert reg.theme_count == 3
    assert len(reg.minted_themes) == 3

    reg.persist()
    data = _load_taxonomy(vault)
    assert len(data["themes"]) == 3


def test_declared_entities_are_never_minted_as_themes(tmp_path: Path) -> None:
    """An entity tag must pass through resolution untouched.

    The pass-through set is built from the closed vocabularies -- domains,
    categories, markers -- and for a long time it was named `all_entities`
    while containing no entities at all.  So `kant` was not recognised, fell
    through to the theme registry, failed the lookup, and was minted as a
    theme.  That is the "tagger files people as themes" defect arriving from
    the Python side rather than the model's, and it is the most likely source
    of some of the eight orphan themes one live run left in the vault.

    It stayed invisible while the tagger reliably produced no entities at all.
    Now that the harness assembles them and derives them from the topic, every
    note would mint its own subject as a theme.
    """
    vault, ctx = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["philosophy"])
    reg = ThemeRegistry.load(_taxonomy_path(vault))
    ctx.theme_registry = reg

    before = list(reg.raw.get("themes", []))

    result = asyncio.run(_resolve_tags_against_registry(
        "general, note, philosophy, kant, rousseau, cli",
        ctx,
        entities=["kant", "rousseau"],
    ))

    # The entities survive into the resolved line, unchanged.
    assert "kant" in result.split(", ")
    assert "rousseau" in result.split(", ")
    # And nothing about them reached the registry.
    assert reg.raw.get("themes", []) == before
    assert "kant" not in reg.theme_keys()
    assert "rousseau" not in reg.theme_keys()


def test_undeclared_entity_still_mints(tmp_path: Path) -> None:
    """The converse, asserted so the mechanism is not mistaken for magic.

    Entities are an open vocabulary, so nothing in the tag itself marks it as
    one.  A caller that does not declare them gets the old behaviour, which is
    why the declaration is a parameter rather than an inference.
    """
    vault, ctx = _make_ctx(tmp_path)
    _seed_taxonomy(vault, themes=["philosophy"])
    reg = ThemeRegistry.load(_taxonomy_path(vault))
    ctx.theme_registry = reg

    asyncio.run(_resolve_tags_against_registry(
        "general, note, philosophy, kant, cli", ctx,
    ))
    assert "kant" in reg.theme_keys()
