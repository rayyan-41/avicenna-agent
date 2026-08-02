"""avicenna init: scaffold a minimal working vault."""

from __future__ import annotations

from pathlib import Path

VAULT_AGENTS_MD = """# AGENTS.md — Avicenna Vault Protocol

This vault is managed by Avicenna, a TUI harness for generating
long-form, structurally-guaranteed notes.

## Protocol

1. **Manifest** — `write_manifest.ps1` creates a tracking spec in `_tmp/`.
2. **Chunk** — Sections are generated in parallel and written to `_tmp/[slug]_chunk_NN.md`.
3. **Weave** — The weaver assembles chunks into a single note.
4. **Tag** — The tagger proposes tags; `validate_tags.ps1` checks them against the taxonomy.
5. **Format** — The formatter applies template structure.
6. **Link** — `get_related_notes.ps1` finds connections and the linker inserts wikilinks.
7. **MOC** — `update_moc.ps1` updates the domain's Map of Content.

## Runtime

- `SPAWN_SECTION` — one prompt in a completely fresh context per heading.
- `DELEGATE @agent` — load an agent's system prompt, run a payload.
"""

VAULT_TAXONOMY_JSON = """{
  "version": 1,
  "schema": {"markers": ["cli"]},
  "domains": {"general": ["note", "essay"]},
  "universalCategories": ["general"],
  "folderMap": {},
  "types": ["note", "essay"],
  "themes": [],
  "reservedModifiers": []
}
"""

SCRIBE_AGENT_MD = """---
name: scribe
description: General-purpose content agent
type: content
domain: general
invocation: /agent scribe
---

You are a meticulous writer. Your task is to produce clear, well-structured
prose on the topic provided. Follow the section prompt exactly: write only
the body text for the given heading, do not restate the heading, and do not
add frontmatter or wikilinks.
"""

TMP_GITIGNORE = "*\n"


def init_vault(target: str | Path) -> Path:
    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    agents_dir = target / ".agents"
    agents_dir.mkdir(exist_ok=True)
    (agents_dir / "agents").mkdir(exist_ok=True)
    (agents_dir / "skills").mkdir(exist_ok=True)
    (agents_dir / "tools").mkdir(exist_ok=True)
    tmp_dir = target / "_tmp"
    tmp_dir.mkdir(exist_ok=True)

    (target / "AGENTS.md").write_text(VAULT_AGENTS_MD.strip() + "\n", encoding="utf-8", newline="\n")
    (agents_dir / "taxonomy.json").write_text(VAULT_TAXONOMY_JSON.strip() + "\n", encoding="utf-8", newline="\n")
    (agents_dir / "agents" / "scribe.md").write_text(SCRIBE_AGENT_MD.strip() + "\n", encoding="utf-8", newline="\n")
    (tmp_dir / ".gitignore").write_text(TMP_GITIGNORE, encoding="utf-8", newline="\n")
    return target
