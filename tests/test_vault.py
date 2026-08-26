"""Vault layer tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from avicenna.vault.models import AgentDef, Taxonomy, VaultConfigError
from avicenna.vault.vault import Vault
from avicenna.vault.init_scaffold import init_vault


def test_agentdef_from_valid_string():
    content = """---
name: testagent
description: A test agent
type: content
domain: general
---

This is the system prompt body."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "testagent.md"
        path.write_text(content, encoding="utf-8")
        agent = AgentDef.from_file(path)
        assert agent.name == "testagent"
        assert agent.type == "content"
        assert agent.domain == "general"
        assert "system prompt body" in agent.system_prompt


def test_agentdef_name_mismatch():
    content = """---
name: wrongname
description: desc
type: content
domain: general
---

body"""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "rightname.md"
        path.write_text(content, encoding="utf-8")
        with pytest.raises(VaultConfigError, match="does not match filename"):
            AgentDef.from_file(path)


def test_agentdef_missing_required():
    content = """---
name: test
---
body"""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "test.md"
        path.write_text(content, encoding="utf-8")
        with pytest.raises(VaultConfigError, match="description"):
            AgentDef.from_file(path)


def test_init_then_load():
    with tempfile.TemporaryDirectory() as td:
        root = init_vault(Path(td) / "testvault")
        vault = Vault.load(root)
        assert vault.protocol_text
        assert "scribe" in vault.agents
        # No .ps1 scripts in a scaffolded vault, but the read-only builtins are
        # registered by Vault.load so every entry point shares one tool surface.
        names = {spec.name for spec in vault.tools.spec_for_model()}
        assert names == {"read_note", "list_notes", "search_vault"}
        assert not any(t.source.value == "vault_ps1" for t in vault.tools)


def test_taxonomy_category_for_path():
    import json
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "taxonomy.json"
        path.write_text(json.dumps({
            "version": 1, "schema": {}, "domains": {"history": ["empire"]},
            "universalCategories": [], "folderMap": {
                "History/Biographies/Rumi": "biography",
                "History": "empire",
            }, "types": [], "themes": [], "reservedModifiers": [],
        }), encoding="utf-8")
        tax = Taxonomy.load(path)
        assert tax.category_for_path("History/Biographies/Rumi") == "biography"
        assert tax.category_for_path("History/Ancient Times") == "empire"
        assert tax.category_for_path("Science") is None


def test_vault_no_agents_is_ok():
    """Vault.load should succeed with zero agents (minimum viable vault)."""
    with tempfile.TemporaryDirectory() as td:
        root = init_vault(Path(td) / "minvault")
        # Delete the starter agent
        agent_file = root / ".agents" / "agents" / "scribe.md"
        agent_file.unlink()
        vault = Vault.load(root)
        assert vault.agents == {}
        assert vault.protocol_text != ""
