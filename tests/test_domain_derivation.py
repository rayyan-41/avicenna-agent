"""Tests for domain derivation from the vault's folder tree.

Domains and categories are derived from the filesystem rather than declared
in taxonomy.json. The folder's on-disk name is canonical.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from avicenna.vault.models import VaultConfigError
from avicenna.vault.vault import Vault, _derive_domains, _DOMAIN_EXCLUDE
from avicenna.vault.routing import validate_domain, route_request, clear_cache
from avicenna.vault.init_scaffold import init_vault


# --- helpers ----------------------------------------------------------------

def _make_vault_with_folders(
    tmp_path: Path,
    domain_folders: dict[str, list[str]],
    *,
    taxonomy_domains: dict[str, list[str]] | None = None,
    agents: list[tuple[str, str]] | None = None,
) -> Vault:
    """Create a vault with explicit domain/category folder structure."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / ".agents" / "agents").mkdir(parents=True)
    (root / ".agents" / "skills").mkdir(parents=True)
    (root / ".agents" / "tools").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# protocol\n", encoding="utf-8")

    # Create domain and category folders.
    for domain, cats in domain_folders.items():
        domain_dir = root / domain
        domain_dir.mkdir(exist_ok=True)
        for cat in cats:
            (domain_dir / cat).mkdir(exist_ok=True)

    # Use taxonomy_domains if provided, else derive from domain_folders.
    tax_domains = taxonomy_domains if taxonomy_domains is not None else {
        k.lower(): list(v) for k, v in domain_folders.items()
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
        json.dumps(taxonomy), encoding="utf-8"
    )

    # Create content agents for each domain.
    agent_list = agents or [(f"agent-{d.lower()}", d.lower()) for d in domain_folders]
    for name, domain in agent_list:
        (root / ".agents" / "agents" / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: agent for {domain}\n"
            f"type: content\ndomain: {domain}\n---\n\nbody\n",
            encoding="utf-8",
        )

    clear_cache()
    return Vault.load(root)


# --- domain derivation from folders -----------------------------------------

def test_domains_derive_from_root_folders(tmp_path: Path) -> None:
    """Domains are the immediate subdirectories of the vault root."""
    v = _make_vault_with_folders(tmp_path, {
        "History": [],
        "Science": [],
        "Art": [],
    })
    assert v.domain_names == {"history", "science", "art"}


def test_dotted_directories_excluded(tmp_path: Path) -> None:
    """Dotted directories are never treated as domains."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / ".agents" / "agents").mkdir(parents=True)
    (root / ".agents" / "skills").mkdir(parents=True)
    (root / ".agents" / "tools").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# protocol\n", encoding="utf-8")
    (root / "History").mkdir()
    (root / ".hidden").mkdir()
    (root / ".agents").mkdir(exist_ok=True)  # already exists
    taxonomy = {
        "version": 1, "schema": {"markers": ["cli"]},
        "domains": {"history": []},
        "universalCategories": [], "folderMap": {},
        "types": ["concept"], "themes": [], "reservedModifiers": [],
    }
    (root / ".agents" / "taxonomy.json").write_text(json.dumps(taxonomy), encoding="utf-8")
    (root / ".agents" / "agents" / "h.md").write_text(
        "---\nname: h\ndescription: test\ntype: content\ndomain: history\n---\n\nbody\n",
        encoding="utf-8",
    )
    clear_cache()
    v = Vault.load(root)
    assert ".hidden" not in v.domain_names
    assert "history" in v.domain_names


def test_tmp_directory_excluded(tmp_path: Path) -> None:
    """_tmp is never treated as a domain."""
    v = _make_vault_with_folders(tmp_path, {"History": []})
    assert "_tmp" not in v.domain_names


def test_file_not_treated_as_domain(tmp_path: Path) -> None:
    """Files at the root are not treated as domains."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / ".agents" / "agents").mkdir(parents=True)
    (root / ".agents" / "skills").mkdir(parents=True)
    (root / ".agents" / "tools").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# protocol\n", encoding="utf-8")
    (root / "History").mkdir()
    (root / "notes.txt").write_text("not a domain", encoding="utf-8")
    taxonomy = {
        "version": 1, "schema": {"markers": ["cli"]},
        "domains": {"history": []},
        "universalCategories": [], "folderMap": {},
        "types": ["concept"], "themes": [], "reservedModifiers": [],
    }
    (root / ".agents" / "taxonomy.json").write_text(json.dumps(taxonomy), encoding="utf-8")
    (root / ".agents" / "agents" / "h.md").write_text(
        "---\nname: h\ndescription: test\ntype: content\ndomain: history\n---\n\nbody\n",
        encoding="utf-8",
    )
    clear_cache()
    v = Vault.load(root)
    assert "notes" not in v.domain_names
    assert "history" in v.domain_names


# --- canonical casing -------------------------------------------------------

def test_on_disk_casing_is_canonical(tmp_path: Path) -> None:
    """A folder's on-disk casing is what every consumer receives."""
    v = _make_vault_with_folders(tmp_path, {"Reason": []})
    # The canonical name is "Reason", not "reason".
    assert "Reason" in v._derived_domains
    # Lowercase lookup works.
    assert v.resolve_domain("reason") == "reason"
    assert v.resolve_domain("Reason") == "reason"
    assert v.resolve_domain("REASON") == "reason"


def test_lowercase_routing_key_resolves_to_correct_folder(tmp_path: Path) -> None:
    """A lowercase routing key resolves to the on-disk folder."""
    from avicenna.pipeline.stages import _canonical_domain_dir

    v = _make_vault_with_folders(tmp_path, {"Reason": []})
    resolved = _canonical_domain_dir(v, "reason")
    assert resolved == v.root / "Reason"
    assert resolved.name == "Reason"


# --- categories from subfolders ---------------------------------------------

def test_categories_derive_from_domain_subfolders(tmp_path: Path) -> None:
    """Categories are the immediate subdirectories of a domain folder."""
    v = _make_vault_with_folders(tmp_path, {
        "History": ["ancient", "modern", "medieval"],
        "Science": [],
    })
    assert sorted(v.categories_for_domain("history")) == ["ancient", "medieval", "modern"]
    assert v.categories_for_domain("science") == []


def test_domain_with_no_subfolders_has_no_categories(tmp_path: Path) -> None:
    """A domain with no subfolders has no categories — this is legitimate."""
    v = _make_vault_with_folders(tmp_path, {"Art": []})
    assert v.categories_for_domain("art") == []


def test_category_lookup_is_case_insensitive(tmp_path: Path) -> None:
    """Category lookup matches domain names case-insensitively."""
    v = _make_vault_with_folders(tmp_path, {"History": ["ancient"]})
    assert v.categories_for_domain("History") == ["ancient"]
    assert v.categories_for_domain("HISTORY") == ["ancient"]
    assert v.categories_for_domain("history") == ["ancient"]


def test_nonexistent_domain_returns_empty_categories(tmp_path: Path) -> None:
    """A domain that doesn't exist returns empty categories."""
    v = _make_vault_with_folders(tmp_path, {"History": []})
    assert v.categories_for_domain("nonexistent") == []


# --- routing validates against derived set -----------------------------------

def test_routing_refuses_domain_without_folder(tmp_path: Path) -> None:
    """A proposed domain with no folder is refused, not created."""
    v = _make_vault_with_folders(tmp_path, {"History": []})
    with pytest.raises(ValueError, match="unknown domain"):
        validate_domain(v, "nonexistent")


def test_routing_validates_against_derived_set(tmp_path: Path) -> None:
    """Routing accepts domains that have folders."""
    v = _make_vault_with_folders(tmp_path, {"History": [], "Science": []})
    agent = validate_domain(v, "history")
    assert agent.domain == "history"


def test_no_directory_created_outside_init(tmp_path: Path) -> None:
    """Running a route does not create domain folders."""
    v = _make_vault_with_folders(tmp_path, {"History": []})
    before = {p.name for p in v.root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    validate_domain(v, "history")
    after = {p.name for p in v.root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    assert before == after


# --- drift reconciliation ---------------------------------------------------

def test_drift_folder_only_reported(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A folder that taxonomy.json doesn't list is reported as drift."""
    with caplog.at_level(logging.WARNING):
        v = _make_vault_with_folders(
            tmp_path,
            {"History": [], "Extra": []},
            taxonomy_domains={"history": []},
        )
    assert any("Extra" in msg for msg in v._domain_drift)
    assert any("Extra" in msg for msg in caplog.text.splitlines() if "Extra" in msg)


def test_drift_taxonomy_only_reported(tmp_path: Path) -> None:
    """A taxonomy domain with no matching folder is reported as drift."""
    v = _make_vault_with_folders(
        tmp_path,
        {"History": []},
        taxonomy_domains={"history": [], "ghost": []},
    )
    assert any("ghost" in msg for msg in v._domain_drift)


def test_vault_with_drift_loads_successfully(tmp_path: Path) -> None:
    """A vault with domain drift still loads — drift is reported, not fatal."""
    v = _make_vault_with_folders(
        tmp_path,
        {"History": []},
        taxonomy_domains={"history": [], "extra": []},
    )
    assert v.domain_names == {"history"}
    assert len(v._domain_drift) > 0


def test_no_drift_when_aligned(tmp_path: Path) -> None:
    """No drift when folders and taxonomy agree."""
    v = _make_vault_with_folders(
        tmp_path,
        {"History": [], "Science": []},
        taxonomy_domains={"history": [], "science": []},
    )
    assert v._domain_drift == []


# --- init scaffold creates domain folders -----------------------------------

def test_init_creates_domain_folders(tmp_path: Path) -> None:
    """init_vault creates domain folders matching taxonomy.json."""
    root = init_vault(tmp_path / "vault")
    assert (root / "General").is_dir()


def test_init_creates_category_subfolders(tmp_path: Path) -> None:
    """init_vault creates category subfolders matching taxonomy.json."""
    root = init_vault(tmp_path / "vault")
    assert (root / "General" / "note").is_dir()
    assert (root / "General" / "essay").is_dir()


def test_init_derived_domains_match_taxonomy(tmp_path: Path) -> None:
    """After init, derived domains match the scaffolded taxonomy."""
    root = init_vault(tmp_path / "vault")
    clear_cache()
    v = Vault.load(root)
    assert "general" in v.domain_names
    assert sorted(v.categories_for_domain("general")) == ["essay", "note"]
    assert v._domain_drift == []


# --- cross-validation -------------------------------------------------------

def test_agent_domain_requires_folder(tmp_path: Path) -> None:
    """A content agent whose domain has no folder fails at load time."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / ".agents" / "agents").mkdir(parents=True)
    (root / ".agents" / "skills").mkdir(parents=True)
    (root / ".agents" / "tools").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# protocol\n", encoding="utf-8")
    # No domain folders at all.
    taxonomy = {
        "version": 1, "schema": {"markers": ["cli"]},
        "domains": {"history": []},
        "universalCategories": [], "folderMap": {},
        "types": ["concept"], "themes": [], "reservedModifiers": [],
    }
    (root / ".agents" / "taxonomy.json").write_text(json.dumps(taxonomy), encoding="utf-8")
    (root / ".agents" / "agents" / "h.md").write_text(
        "---\nname: h\ndescription: test\ntype: content\ndomain: history\n---\n\nbody\n",
        encoding="utf-8",
    )
    clear_cache()
    with pytest.raises(VaultConfigError, match="has no folder"):
        Vault.load(root)


# --- _derive_domains unit tests ---------------------------------------------

def test_derive_domains_basic(tmp_path: Path) -> None:
    """_derive_domains returns canonical names and their subfolders."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "History").mkdir()
    (root / "History" / "ancient").mkdir()
    (root / "History" / "modern").mkdir()
    (root / "Science").mkdir()
    result = _derive_domains(root)
    assert result == {"History": ["ancient", "modern"], "Science": []}


def test_derive_domains_excludes_dotted(tmp_path: Path) -> None:
    """_derive_domains skips dotted directories."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "History").mkdir()
    (root / ".hidden").mkdir()
    result = _derive_domains(root)
    assert ".hidden" not in result
    assert "History" in result


def test_derive_domains_excludes_custom_set(tmp_path: Path) -> None:
    """_derive_domains respects custom exclusion set."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "History").mkdir()
    (root / "Archive").mkdir()
    result = _derive_domains(root, exclude=frozenset({"_tmp", "Archive"}))
    assert "Archive" not in result
    assert "History" in result
