"""Tests for T38: folder names are paths; tags are kebab.

Separates the two spellings of derived categories/domains — path form (the
folder's on-disk name) and tag form (lowercase kebab-case) — so no consumer
has to remember to convert.

Also covers: tagger output normalisation, registry input validation, and the
check-then-mint refactor that replaced mint-then-undo.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from avicenna.bus import EventBus, drain
from avicenna.events import Event, LogMessage, ThemeMinted
from avicenna.pipeline.context import RunContext, RunSpec
from avicenna.pipeline.stages import (
    _build_floor_tags,
    _resolve_tags_against_registry,
    extract_tag_line,
)
from avicenna.providers.fake import FakeProvider
from avicenna.vault.init_scaffold import init_vault
from avicenna.vault.registry import ThemeRegistry
from avicenna.vault.vault import Vault, tag_form


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _taxonomy_path(vault: Vault) -> Path:
    return vault.root / ".agents" / "taxonomy.json"


def _load_taxonomy(vault: Vault) -> dict[str, Any]:
    return json.loads(_taxonomy_path(vault).read_text("utf-8"))


def _seed_taxonomy(
    vault: Vault, *,
    themes: list[str] | None = None,
    types: list[str] | None = None,
    domains: dict[str, list[str]] | None = None,
) -> None:
    data = _load_taxonomy(vault)
    if themes is not None:
        data["themes"] = themes
    if types is not None:
        data["types"] = types
    if domains is not None:
        data["domains"] = domains
    path = _taxonomy_path(vault)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def _make_vault_with_folders(
    tmp_path: Path,
    domain_folders: dict[str, list[str]],
    *,
    taxonomy_domains: dict[str, list[str]] | None = None,
) -> Vault:
    """Create a vault with explicit domain/category folder structure."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / ".agents" / "agents").mkdir(parents=True)
    (root / ".agents" / "skills").mkdir(parents=True)
    (root / ".agents" / "tools").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# protocol\n", encoding="utf-8")

    for domain, cats in domain_folders.items():
        domain_dir = root / domain
        domain_dir.mkdir(exist_ok=True)
        for cat in cats:
            (domain_dir / cat).mkdir(exist_ok=True)

    tax_domains = taxonomy_domains if taxonomy_domains is not None else {
        k.lower(): [] for k in domain_folders
    }
    taxonomy = {
        "version": 1,
        "schema": {"markers": ["cli"]},
        "domains": tax_domains,
        "universalCategories": [],
        "folderMap": {},
        "types": ["concept"],
        "themes": [],
        "reservedModifiers": [],
    }
    (root / ".agents" / "taxonomy.json").write_text(
        json.dumps(taxonomy, indent=2) + "\n", encoding="utf-8", newline="\n",
    )
    # Create a content agent for each domain.
    for domain in domain_folders:
        name = f"agent-{domain.lower()}"
        (root / ".agents" / "agents" / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: agent for {domain}\n"
            f"type: content\ndomain: {domain.lower()}\n---\n\nbody\n",
            encoding="utf-8",
        )
    from avicenna.vault.routing import clear_cache
    clear_cache()
    return Vault.load(root)


def _make_ctx(
    tmp_path: Path,
    taxonomy: dict[str, Any] | None = None,
    *,
    domain_folders: dict[str, list[str]] | None = None,
    domain: str = "general",
) -> tuple[Vault, RunContext]:
    if domain_folders is not None:
        vault = _make_vault_with_folders(
            tmp_path, domain_folders,
            taxonomy_domains={k.lower(): v for k, v in domain_folders.items()},
        )
    else:
        vault = Vault.load(init_vault(tmp_path / "vault"))
    if taxonomy is not None:
        path = _taxonomy_path(vault)
        path.write_text(json.dumps(taxonomy, indent=2) + "\n", encoding="utf-8", newline="\n")
        # Reload so the registry sees the updated taxonomy.
        from avicenna.vault.routing import clear_cache
        clear_cache()
        vault = Vault.load(vault.root)
    ctx = RunContext(spec=RunSpec(
        topic="Test Topic",
        vault=vault,
        provider=FakeProvider(),
        bus=EventBus(),
        run_id="test",
    ))
    ctx.domain = domain
    return vault, ctx


# ===================================================================
# 1. tag_form conversions
# ===================================================================

class TestTagForm:
    def test_art_history(self) -> None:
        assert tag_form("Art History") == "art-history"

    def test_aqeedah(self) -> None:
        assert tag_form("Aqeedah") == "aqeedah"

    def test_research_with_punctuation(self) -> None:
        assert tag_form("Research @ Vizant") == "research-vizant"

    def test_already_kebab(self) -> None:
        assert tag_form("art-history") == "art-history"

    def test_underscores_to_hyphens(self) -> None:
        assert tag_form("art_history") == "art-history"

    def test_collapse_repeats(self) -> None:
        assert tag_form("Art  History") == "art-history"
        assert tag_form("Art--History") == "art-history"

    def test_leading_trailing_stripped(self) -> None:
        assert tag_form("-Art-") == "art"

    def test_empty(self) -> None:
        assert tag_form("") == ""

    def test_only_punctuation(self) -> None:
        assert tag_form("@#$%") == ""


# ===================================================================
# 2. path form vs tag form on Vault
# ===================================================================

class TestVaultPathVsTag:
    def test_categories_for_domain_returns_tag_form(self, tmp_path: Path) -> None:
        """categories_for_domain returns lowercase kebab-case."""
        v = _make_vault_with_folders(tmp_path, {
            "Islam": ["Aqeedah", "Fiqh"],
        })
        cats = v.categories_for_domain("islam")
        assert cats == ["aqeedah", "fiqh"]

    def test_categories_for_domain_path_returns_path_form(self, tmp_path: Path) -> None:
        """categories_for_domain_path returns on-disk folder names."""
        v = _make_vault_with_folders(tmp_path, {
            "Islam": ["Aqeedah", "Fiqh"],
        })
        cats = v.categories_for_domain_path("islam")
        assert cats == ["Aqeedah", "Fiqh"]

    def test_punctuated_folder_yields_valid_tag(self, tmp_path: Path) -> None:
        """A folder with punctuation yields a valid kebab tag form."""
        v = _make_vault_with_folders(tmp_path, {
            "Art": ["Research @ Vizant", "Art History"],
        })
        cats = v.categories_for_domain("art")
        assert "research-vizant" in cats
        assert "art-history" in cats

    def test_path_resolution_still_uses_folder_casing(self, tmp_path: Path) -> None:
        """Regression guard: reason resolves to Reason/ (the MOC rename fix)."""
        from avicenna.pipeline.stages import _canonical_domain_dir
        v = _make_vault_with_folders(tmp_path, {"Reason": []})
        resolved = _canonical_domain_dir(v, "reason")
        assert resolved is not None
        assert resolved.name == "Reason"


# ===================================================================
# 3. _build_floor_tags produces tag-form categories
# ===================================================================

class TestFloorTags:
    def test_floor_category_is_tag_form(self, tmp_path: Path) -> None:
        """The floor uses tag-form categories, not folder names."""
        taxonomy = {
            "version": 1,
            "schema": {"markers": ["cli"]},
            "domains": {"art": ["art-history", "art-theory"]},
            "universalCategories": [],
            "folderMap": {},
            "types": ["person", "essay"],
            "themes": ["knowledge"],
            "reservedModifiers": [],
        }
        vault, ctx = _make_ctx(tmp_path, taxonomy, domain_folders={
            "Art": ["Art History", "Art Theory"],
        }, domain="art")
        floor = _build_floor_tags(ctx)
        # The category must be in kebab-case, not Title Case.
        assert "art-history" in floor
        assert "Art History" not in floor

    def test_floor_passes_tag_form_regex(self, tmp_path: Path) -> None:
        """Every tag in the floor satisfies the tag-form regex."""
        import re
        TAG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
        taxonomy = {
            "version": 1,
            "schema": {"markers": ["cli"]},
            "domains": {"art": ["art-history", "art-theory"]},
            "universalCategories": [],
            "folderMap": {},
            "types": ["person", "essay"],
            "themes": ["knowledge"],
            "reservedModifiers": [],
        }
        vault, ctx = _make_ctx(tmp_path, taxonomy, domain_folders={
            "Art": ["Art History", "Art Theory"],
        }, domain="art")
        floor = _build_floor_tags(ctx)
        for tag in floor:
            assert TAG_RE.match(tag), f"tag {tag!r} does not satisfy tag-form regex"


# ===================================================================
# 4. A tag matching a derived category is passed through, not minted
# ===================================================================

class TestCategoryPassthrough:
    def test_fiqh_not_minted_as_theme(self, tmp_path: Path) -> None:
        """fiqh against a Fiqh/ folder must be passed through, not minted."""
        taxonomy = {
            "version": 1,
            "schema": {"markers": ["cli"]},
            "domains": {"islam": ["aqeedah", "fiqh"]},
            "universalCategories": [],
            "folderMap": {},
            "types": ["concept"],
            "themes": ["revelation"],
            "reservedModifiers": [],
        }
        vault, ctx = _make_ctx(tmp_path, taxonomy, domain_folders={
            "Islam": ["Aqeedah", "Fiqh"],
        }, domain="islam")
        ctx.theme_registry = ThemeRegistry.load(_taxonomy_path(vault))

        async def _resolve() -> str:
            return await _resolve_tags_against_registry(
                "islam, fiqh, revelation, cli", ctx,
            )

        result = asyncio.run(_resolve())
        tags = [t.strip() for t in result.split(",")]
        assert "fiqh" in tags
        # Must not have been minted as a theme.
        data = _load_taxonomy(vault)
        assert "fiqh" not in data.get("themes", [])


# ===================================================================
# 5. extract_tag_line normalisation
# ===================================================================

class TestExtractTagLine:
    def test_clean_input(self) -> None:
        assert extract_tag_line("TAGS: literature, book, cli") == "literature, book, cli"

    def test_brackets_stripped(self) -> None:
        assert extract_tag_line("TAGS: [literature, book, cli]") == "literature, book, cli"

    def test_quotes_stripped(self) -> None:
        assert extract_tag_line("TAGS: 'literature', 'book'") == "literature, book"

    def test_double_quotes_stripped(self) -> None:
        assert extract_tag_line('TAGS: "literature", "book"') == "literature, book"

    def test_hash_stripped(self) -> None:
        assert extract_tag_line("TAGS: #literature, #book") == "literature, book"

    def test_no_tags_line(self) -> None:
        assert extract_tag_line("Here are my thoughts on this note.") == ""

    def test_mixed_decorations(self) -> None:
        """Bracket on whole line, quotes on individual tags, hash prefix."""
        result = extract_tag_line("TAGS: [#literature, 'book', cli]")
        assert result == "literature, book, cli"

    def test_backticks_stripped(self) -> None:
        assert extract_tag_line("TAGS: `literature`, `book`") == "literature, book"

    def test_whitespace_handling(self) -> None:
        assert extract_tag_line("TAGS:   literature ,  book  , cli  ") == "literature, book, cli"


# ===================================================================
# 6. Registry refuses to persist malformed tags
# ===================================================================

class TestRegistryValidation:
    def test_bracket_refused(self, tmp_path: Path) -> None:
        """[literature is refused by the registry."""
        vault, _ = _make_ctx(tmp_path)
        _seed_taxonomy(vault, themes=[], types=[])
        reg = ThemeRegistry.load(_taxonomy_path(vault))
        canon, is_new = reg.resolve_theme("[literature")
        assert not is_new
        assert canon == "[literature"  # returned as-is, not minted
        assert reg.theme_count == 0
        data = _load_taxonomy(vault)
        assert "[literature" not in data.get("themes", [])

    def test_closing_bracket_refused(self, tmp_path: Path) -> None:
        """cli] is refused by the registry."""
        vault, _ = _make_ctx(tmp_path)
        _seed_taxonomy(vault, themes=[], types=[])
        reg = ThemeRegistry.load(_taxonomy_path(vault))
        canon, is_new = reg.resolve_theme("cli]")
        assert not is_new
        assert reg.theme_count == 0

    def test_snake_case_normalised_to_kebab(self, tmp_path: Path) -> None:
        """divine_law (underscores) normalises to divine-law and is accepted."""
        vault, _ = _make_ctx(tmp_path)
        _seed_taxonomy(vault, themes=[], types=[])
        reg = ThemeRegistry.load(_taxonomy_path(vault))
        canon, is_new = reg.resolve_theme("divine_law")
        assert is_new
        assert canon == "divine-law"
        assert reg.theme_count == 1

    def test_title_case_normalised_to_kebab(self, tmp_path: Path) -> None:
        """Some Theme (Title Case) normalises to some-theme and is accepted."""
        vault, _ = _make_ctx(tmp_path)
        _seed_taxonomy(vault, themes=[], types=[])
        reg = ThemeRegistry.load(_taxonomy_path(vault))
        canon, is_new = reg.resolve_theme("Some Theme")
        assert is_new
        assert canon == "some-theme"
        assert reg.theme_count == 1

    def test_empty_string_refused(self, tmp_path: Path) -> None:
        """Empty string is refused."""
        vault, _ = _make_ctx(tmp_path)
        _seed_taxonomy(vault, themes=[], types=[])
        reg = ThemeRegistry.load(_taxonomy_path(vault))
        canon, is_new = reg.resolve_theme("")
        assert not is_new
        assert reg.theme_count == 0

    def test_valid_tag_accepted(self, tmp_path: Path) -> None:
        """A valid kebab-case tag is accepted."""
        vault, _ = _make_ctx(tmp_path)
        _seed_taxonomy(vault, themes=[], types=[])
        reg = ThemeRegistry.load(_taxonomy_path(vault))
        canon, is_new = reg.resolve_theme("national-political-philosophy")
        assert is_new
        assert canon == "national-political-philosophy"
        assert reg.theme_count == 1

    def test_lookup_rejects_malformed(self, tmp_path: Path) -> None:
        """lookup_theme returns a reason for malformed tags."""
        vault, _ = _make_ctx(tmp_path)
        _seed_taxonomy(vault, themes=[])
        reg = ThemeRegistry.load(_taxonomy_path(vault))
        canon, reason = reg.lookup_theme("[literature")
        assert canon is None
        assert reason is not None
        # The reason should describe the rejection (forbidden chars or invalid form).
        assert "forbidden" in reason.lower() or "invalid" in reason.lower()

    def test_taxonomy_unchanged_when_all_tags_exist(self, tmp_path: Path) -> None:
        """taxonomy.json is unchanged when every proposed tag already exists."""
        vault, ctx = _make_ctx(tmp_path)
        _seed_taxonomy(vault, themes=["philosophy", "epistemology"], types=["concept"])
        ctx.theme_registry = ThemeRegistry.load(_taxonomy_path(vault))

        before = _load_taxonomy(vault)

        async def _resolve() -> str:
            return await _resolve_tags_against_registry(
                "general, concept, philosophy, epistemology, cli", ctx,
            )

        asyncio.run(_resolve())
        after = _load_taxonomy(vault)
        assert before["themes"] == after["themes"]
        assert before["types"] == after["types"]


# ===================================================================
# 7. Known type is not minted as a theme (no undo_mint needed)
# ===================================================================

class TestCheckThenMint:
    def test_known_type_not_minted_as_theme(self, tmp_path: Path) -> None:
        """A tag that is a known type is not minted as a theme."""
        taxonomy = {
            "version": 1,
            "schema": {"markers": ["cli"]},
            "domains": {"general": ["note"]},
            "universalCategories": [],
            "folderMap": {},
            "types": ["person", "concept"],
            "themes": ["philosophy"],
            "reservedModifiers": [],
        }
        vault, ctx = _make_ctx(tmp_path, taxonomy)
        ctx.theme_registry = ThemeRegistry.load(_taxonomy_path(vault))

        async def _resolve() -> str:
            return await _resolve_tags_against_registry(
                "general, note, person, philosophy, cli", ctx,
            )

        result = asyncio.run(_resolve())
        tags = [t.strip() for t in result.split(",")]
        assert "person" in tags
        # Must NOT appear in themes.
        data = _load_taxonomy(vault)
        assert "person" not in data.get("themes", [])
        # No residue in themes list.
        reg = ThemeRegistry.load(_taxonomy_path(vault))
        assert "person" not in reg.themes_for_hint()

    def test_no_residue_after_type_passthrough(self, tmp_path: Path) -> None:
        """After a known type passes through, the themes list is clean."""
        taxonomy = {
            "version": 1,
            "schema": {"markers": ["cli"]},
            "domains": {"general": ["note"]},
            "universalCategories": [],
            "folderMap": {},
            "types": ["work"],
            "themes": [],
            "reservedModifiers": [],
        }
        vault, ctx = _make_ctx(tmp_path, taxonomy)
        ctx.theme_registry = ThemeRegistry.load(_taxonomy_path(vault))

        async def _resolve() -> str:
            return await _resolve_tags_against_registry(
                "general, note, work, cli", ctx,
            )

        asyncio.run(_resolve())
        data = _load_taxonomy(vault)
        assert "work" not in data.get("themes", [])
        assert "work" in data.get("types", [])


# ===================================================================
# 8. Registry rejection reported via events
# ===================================================================

class TestRegistryRejectionEvents:
    def test_malformed_tag_emits_warning(self, tmp_path: Path) -> None:
        """A malformed tag in the tagger's output produces a warning event."""
        taxonomy = {
            "version": 1,
            "schema": {"markers": ["cli"]},
            "domains": {"general": ["note"]},
            "universalCategories": [],
            "folderMap": {},
            "types": ["concept"],
            "themes": [],
            "reservedModifiers": [],
        }
        vault, ctx = _make_ctx(tmp_path, taxonomy)
        ctx.theme_registry = ThemeRegistry.load(_taxonomy_path(vault))

        async def _run() -> list[Event]:
            bus = ctx.spec.bus
            queue = bus.subscribe()
            await _resolve_tags_against_registry(
                "general, note, [literature, cli", ctx,
            )
            await bus.close()
            return [e async for e in drain(queue)]

        events = asyncio.run(_run())
        warnings = [e for e in events
                    if isinstance(e, LogMessage) and "rejected" in e.text.lower()]
        assert len(warnings) >= 1
        assert "[literature" in warnings[0].text


# ===================================================================
# 9. Tag form used in _resolve_tags_against_registry entity check
# ===================================================================

class TestEntityCheckUsesTagForm:
    def test_tag_form_category_matches_entity_set(self, tmp_path: Path) -> None:
        """A tag in kebab-case matches a derived category in the entity set,
        preventing it from being minted as a new theme."""
        taxonomy = {
            "version": 1,
            "schema": {"markers": ["cli"]},
            "domains": {"art": ["art-history"]},
            "universalCategories": [],
            "folderMap": {},
            "types": ["concept"],
            "themes": [],
            "reservedModifiers": [],
        }
        vault, ctx = _make_ctx(tmp_path, taxonomy, domain_folders={
            "Art": ["Art History"],
        }, domain="art")
        ctx.theme_registry = ThemeRegistry.load(_taxonomy_path(vault))

        async def _resolve() -> str:
            return await _resolve_tags_against_registry(
                "art, art-history, concept, cli", ctx,
            )

        result = asyncio.run(_resolve())
        tags = [t.strip() for t in result.split(",")]
        assert "art-history" in tags
        data = _load_taxonomy(vault)
        # art-history should NOT have been minted as a theme.
        assert "art-history" not in data.get("themes", [])
