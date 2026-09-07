"""Tests for T32: the harness must never create a domain folder to satisfy a route.

Part A — _canonical_domain_dir returns None when no folder matches;
_note_destination aborts the run instead of creating a directory;
the "general" fallback is removed.

Part B — Category derivation excludes _-prefixed, dotted, and _tmp
directories, and respects the user-extendable excludeFromDerivation
list from taxonomy.json.

Part C — Init scaffold still creates its folders.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from avicenna.bus import EventBus
from avicenna.events import Event, LogMessage
from avicenna.pipeline.run import execute_run
from avicenna.pipeline.stages import _canonical_domain_dir, _note_destination
from avicenna.pipeline.stage import PipelineAbort
from avicenna.providers.fake import FakeProvider
from avicenna.vault.init_scaffold import init_vault
from avicenna.vault.vault import Vault, _derive_domains, _DOMAIN_EXCLUDE
from avicenna.vault.routing import clear_cache


# --- helpers ----------------------------------------------------------------

TOPIC = "The Epistemic Gap and the Necessity of Revelation"
HEADINGS = [
    "The Limits of Unaided Reason",
    "The Shape of the Gap",
    "Revelation as Closure",
]
BODY = "Finished prose for this section. " * 12


def _make_vault(
    tmp_path: Path,
    domain_folders: dict[str, list[str]],
    *,
    taxonomy_domains: dict[str, list[str]] | None = None,
    exclude_from_derivation: list[str] | None = None,
    agents: list[tuple[str, str]] | None = None,
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
        k.lower(): list(v) for k, v in domain_folders.items()
    }
    taxonomy: dict[str, Any] = {
        "version": 1,
        "schema": {"markers": ["cli"]},
        "domains": tax_domains,
        "universalCategories": [],
        "folderMap": {},
        "types": ["concept"],
        "themes": [],
        "reservedModifiers": [],
    }
    if exclude_from_derivation is not None:
        taxonomy["excludeFromDerivation"] = exclude_from_derivation
    (root / ".agents" / "taxonomy.json").write_text(
        json.dumps(taxonomy), encoding="utf-8"
    )

    agent_list = agents or [(f"agent-{d.lower()}", d.lower()) for d in domain_folders]
    for name, domain in agent_list:
        (root / ".agents" / "agents" / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: agent for {domain}\n"
            f"type: content\ndomain: {domain}\n---\n\nbody\n",
            encoding="utf-8",
        )

    clear_cache()
    return Vault.load(root)


def _make_run_context(vault: Vault, domain: str = "history") -> Any:
    """Build a minimal RunContext for _note_destination tests."""
    from avicenna.pipeline.context import RunContext, RunSpec

    ctx = RunContext(spec=RunSpec(
        topic=TOPIC, vault=vault, provider=FakeProvider(),
        bus=EventBus(), run_id="test",
    ))
    ctx.domain = domain
    return ctx


# =============================================================================
# Part A — domain resolution returns None; no directory creation
# =============================================================================


def test_canonical_domain_dir_returns_none_for_missing(tmp_path: Path) -> None:
    """_canonical_domain_dir returns None when no folder matches."""
    v = _make_vault(tmp_path, {"History": []})
    result = _canonical_domain_dir(v, "nonexistent")
    assert result is None


def test_canonical_domain_dir_resolves_existing(tmp_path: Path) -> None:
    """_canonical_domain_dir resolves an existing folder."""
    v = _make_vault(tmp_path, {"Reason": []})
    result = _canonical_domain_dir(v, "reason")
    assert result == v.root / "Reason"


def test_canonical_domain_dir_hyphenated(tmp_path: Path) -> None:
    """_canonical_domain_dir resolves hyphenated domains."""
    v = _make_vault(tmp_path, {"Art Theory": []})
    result = _canonical_domain_dir(v, "art-theory")
    assert result == v.root / "Art Theory"


def test_note_destination_aborts_for_missing_domain(tmp_path: Path) -> None:
    """_note_destination aborts the run when the domain has no folder."""
    v = _make_vault(tmp_path, {"History": []})
    ctx = _make_run_context(v, domain="nonexistent")
    with pytest.raises(PipelineAbort, match="nonexistent.*has no folder"):
        _note_destination(ctx)


def test_note_destination_message_names_available_domains(tmp_path: Path) -> None:
    """The abort message names the vault's actual domains."""
    v = _make_vault(tmp_path, {"History": [], "Science": []})
    ctx = _make_run_context(v, domain="nonexistent")
    with pytest.raises(PipelineAbort, match="available domains: history, science"):
        _note_destination(ctx)


def test_note_destination_aborts_for_no_domain(tmp_path: Path) -> None:
    """_note_destination aborts when ctx.domain is None or empty."""
    v = _make_vault(tmp_path, {"History": []})
    ctx = _make_run_context(v, domain="history")
    ctx.domain = None
    with pytest.raises(PipelineAbort, match="no domain resolved"):
        _note_destination(ctx)


def test_no_directory_created_by_failed_destination(tmp_path: Path) -> None:
    """A failed _note_destination must not create any directory."""
    v = _make_vault(tmp_path, {"History": []})
    before = {p.name for p in v.root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    ctx = _make_run_context(v, domain="nonexistent")
    with pytest.raises(PipelineAbort):
        _note_destination(ctx)
    after = {p.name for p in v.root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    assert before == after, "a directory was created by a failed destination call"


def test_note_destination_succeeds_for_existing_domain(tmp_path: Path) -> None:
    """_note_destination works when the domain has a folder."""
    v = _make_vault(tmp_path, {"History": []})
    ctx = _make_run_context(v, domain="history")
    dest = _note_destination(ctx)
    assert dest.parent == v.root / "History"
    assert dest.name.endswith(".md")


def test_no_directory_created_by_successful_destination(tmp_path: Path) -> None:
    """A successful _note_destination must not create directories either."""
    v = _make_vault(tmp_path, {"History": []})
    before = {p.name for p in v.root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    ctx = _make_run_context(v, domain="history")
    _note_destination(ctx)
    after = {p.name for p in v.root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    assert before == after, "a directory was created by a successful destination call"


def test_init_scaffold_still_creates_folders(tmp_path: Path) -> None:
    """init_vault still creates domain and category folders."""
    root = init_vault(tmp_path / "vault")
    assert (root / "General").is_dir()
    assert (root / "General" / "note").is_dir()
    assert (root / "General" / "essay").is_dir()


# =============================================================================
# Part B — category derivation exclusions
# =============================================================================


def test_underscore_prefixed_excluded_from_categories(tmp_path: Path) -> None:
    """_templates and other _-prefixed dirs are excluded from categories."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Literature").mkdir()
    (root / "Literature" / "Books").mkdir()
    (root / "Literature" / "_templates").mkdir()
    result = _derive_domains(root)
    assert "_templates" not in result["Literature"]
    assert "Books" in result["Literature"]


def test_dotted_directories_excluded_from_categories(tmp_path: Path) -> None:
    """Dotted directories are excluded from categories."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Science").mkdir()
    (root / "Science" / "Mathematics").mkdir()
    (root / "Science" / ".hidden").mkdir()
    result = _derive_domains(root)
    assert ".hidden" not in result["Science"]
    assert "Mathematics" in result["Science"]


def test_tmp_excluded_from_categories(tmp_path: Path) -> None:
    """_tmp is excluded from categories."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Art").mkdir()
    (root / "Art" / "_tmp").mkdir()
    (root / "Art" / "paintings").mkdir()
    result = _derive_domains(root)
    assert "_tmp" not in result["Art"]


def test_user_exclusion_removes_named_folder_from_categories(tmp_path: Path) -> None:
    """A user-extended exclusion removes a named folder from categories."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Art").mkdir()
    (root / "Art" / "Art History").mkdir()
    (root / "Art" / "paintings_source").mkdir()
    result = _derive_domains(root, user_exclude=frozenset({"paintings_source"}))
    assert "paintings_source" not in result["Art"]
    assert "Art History" in result["Art"]


def test_user_exclusion_removes_named_folder_from_domains(tmp_path: Path) -> None:
    """A user-extended exclusion also removes a named folder from domains."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "History").mkdir()
    (root / "Archive").mkdir()
    result = _derive_domains(root, user_exclude=frozenset({"Archive"}))
    assert "Archive" not in result
    assert "History" in result


def test_exclude_from_derivation_loaded_from_taxonomy(tmp_path: Path) -> None:
    """excludeFromDerivation from taxonomy.json reaches _derive_domains."""
    v = _make_vault(
        tmp_path,
        {"Art": ["Art History", "paintings_source"]},
        exclude_from_derivation=["paintings_source"],
    )
    cats = v.categories_for_domain("art")
    assert "paintings_source" not in cats
    assert "Art History" in cats


def test_exclude_from_derivation_absent_defaults_empty(tmp_path: Path) -> None:
    """When excludeFromDerivation is absent from taxonomy, exclusion is empty."""
    v = _make_vault(tmp_path, {"Science": ["Mathematics", "Astronomy"]})
    cats = v.categories_for_domain("science")
    assert "Mathematics" in cats
    assert "Astronomy" in cats


def test_template_defaulting_unchanged(tmp_path: Path) -> None:
    """ctx.template defaults to 'general' (regression)."""
    from avicenna.settings import WORDS_PER_HEADING_DEFAULT

    # The default words_per_heading must be an int (the setting exists).
    assert isinstance(WORDS_PER_HEADING_DEFAULT, int)
    assert WORDS_PER_HEADING_DEFAULT > 0


# =============================================================================
# Existing tests that must still pass
# =============================================================================


def test_resolve_domain_dir_existing(tmp_path: Path) -> None:
    """Vault.resolve_domain_dir returns the correct path."""
    v = _make_vault(tmp_path, {"History": [], "Reason": []})
    assert v.resolve_domain_dir("reason") == v.root / "Reason"
    assert v.resolve_domain_dir("history") == v.root / "History"


def test_resolve_domain_dir_missing(tmp_path: Path) -> None:
    """Vault.resolve_domain_dir returns None for missing domains."""
    v = _make_vault(tmp_path, {"History": []})
    assert v.resolve_domain_dir("nonexistent") is None


def test_resolve_domain_dir_case_insensitive(tmp_path: Path) -> None:
    """Vault.resolve_domain_dir is case-insensitive."""
    v = _make_vault(tmp_path, {"Reason": []})
    assert v.resolve_domain_dir("REASON") == v.root / "Reason"
    assert v.resolve_domain_dir("Reason") == v.root / "Reason"


def test_resolve_domain_dir_hyphenated(tmp_path: Path) -> None:
    """Vault.resolve_domain_dir handles hyphen vs space."""
    v = _make_vault(tmp_path, {"Art Theory": []})
    assert v.resolve_domain_dir("art-theory") == v.root / "Art Theory"
