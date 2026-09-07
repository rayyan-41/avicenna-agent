"""T41 — Vault embedding index tests.

All tests use FakeEmbeddingProvider and tmp_path.  No live network calls,
no reads or writes to the real vault.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avicenna.providers.fake import FakeEmbeddingProvider
from avicenna.vault.index import (
    ChunkEntry,
    IndexStats,
    VaultIndex,
    chunk_note,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vault(root: Path, notes: dict[str, str]) -> None:
    """Scaffold a minimal vault with the given notes."""
    (root / ".agents").mkdir(parents=True, exist_ok=True)
    (root / "_tmp").mkdir(exist_ok=True)
    for rel, content in notes.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _simple_note(title: str, body: str) -> str:
    """One ``# heading`` note with plain body text."""
    return f"# {title}\n\n{body}\n"


def _multi_heading_note(title: str, sections: dict[str, str]) -> str:
    """Note with a title heading and ``##`` sections."""
    parts = [f"# {title}\n"]
    for heading, body in sections.items():
        parts.append(f"## {heading}\n\n{body}\n")
    return "\n".join(parts)


def _vault_snapshot(root: Path) -> dict[str, str]:
    """Return {relative_posix_path: text_content} for all .md files in vault."""
    snap: dict[str, str] = {}
    for md in root.rglob("*.md"):
        rel = md.relative_to(root)
        # Skip .agents and _tmp (internal directories).
        if any(p.startswith(".") or p == "_tmp" for p in rel.parts):
            continue
        snap[rel.as_posix()] = md.read_text("utf-8")
    return snap


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_produces_one_entry_per_chunk(tmp_path: Path) -> None:
    """Indexing a vault produces one entry per chunk, with path and heading."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "Science/physics.md": _simple_note("Physics", "Force equals mass times acceleration."),
        "History/rome.md": _simple_note("Rome", "The Roman Empire lasted centuries."),
    })

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    stats = await idx.index()

    assert stats.notes_seen == 2
    assert stats.total_chunks == 2
    assert stats.chunks_added == 2
    paths = {e.note_path for e in idx.entries}
    assert paths == {"Science/physics.md", "History/rome.md"}
    # Every entry has a non-empty content hash.
    for entry in idx.entries:
        assert entry.content_hash


@pytest.mark.asyncio
async def test_reindex_unchanged_vault_embeds_nothing(tmp_path: Path) -> None:
    """Re-indexing an unchanged vault embeds NOTHING (hash hit)."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "note.md": _simple_note("Note", "Some content here."),
    })

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    await idx.index()
    assert len(provider.calls) == 1  # first pass embedded 1 chunk

    # Second pass — unchanged.
    stats2 = await idx.index()
    assert stats2.chunks_added == 0
    assert len(provider.calls) == 1  # no new embed call


@pytest.mark.asyncio
async def test_editing_one_note_reembeds_only_that_note(tmp_path: Path) -> None:
    """Editing one note re-embeds only that note's chunks."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "a.md": _simple_note("A", "Alpha content."),
        "b.md": _simple_note("B", "Bravo content."),
    })

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    await idx.index()
    assert len(provider.calls) == 1  # 2 texts in one batch call
    assert provider.calls[0]["task"] == "RETRIEVAL_DOCUMENT"

    # Edit only a.md.
    (vault / "a.md").write_text(
        _simple_note("A", "Alpha content has changed significantly."),
        encoding="utf-8",
    )

    stats2 = await idx.index()
    assert stats2.chunks_added == 1  # only a.md re-embedded
    # b.md entries unchanged.
    b_entries = [e for e in idx.entries if e.note_path == "b.md"]
    assert len(b_entries) == 1


@pytest.mark.asyncio
async def test_deleting_a_note_removes_its_entries(tmp_path: Path) -> None:
    """Deleting a note removes its entries from the index."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "keep.md": _simple_note("Keep", "Stays."),
        "drop.md": _simple_note("Drop", "Goes away."),
    })

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    await idx.index()
    assert len(idx.entries) == 2

    (vault / "drop.md").unlink()

    stats2 = await idx.index()
    assert stats2.chunks_removed >= 1
    paths = {e.note_path for e in idx.entries}
    assert paths == {"keep.md"}


@pytest.mark.asyncio
async def test_long_note_produces_multiple_chunks(tmp_path: Path) -> None:
    """A note longer than the chunk threshold produces multiple chunks."""
    # Create a note with ~600 words in one section (> 500 word target).
    words = "word " * 600
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "long.md": _simple_note("Long", words),
    })

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index", chunk_target_words=500)
    stats = await idx.index()

    assert stats.total_chunks >= 2


@pytest.mark.asyncio
async def test_chunking_prefers_heading_boundaries(tmp_path: Path) -> None:
    """Chunking splits on heading boundaries when possible."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "multi.md": _multi_heading_note("Multi", {
            "First": "Content of first section.",
            "Second": "Content of second section.",
            "Third": "Content of third section.",
        }),
    })

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    stats = await idx.index()

    # Intro section (before first ##) + three ## sections = 4 chunks.
    assert stats.total_chunks == 4
    headings = [e.heading for e in idx.entries]
    assert "First" in headings
    assert "Second" in headings
    assert "Third" in headings
    # Intro section before any ## heading gets empty heading.
    assert "" in headings


@pytest.mark.asyncio
async def test_query_returns_nearest_first_with_scores(tmp_path: Path) -> None:
    """Query returns nearest first, with scores."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "physics.md": _simple_note("Physics", "Quantum mechanics and wave functions."),
        "cooking.md": _simple_note("Cooking", "Pasta carbonara with guanciale."),
    })

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    await idx.index()

    results = await idx.query("quantum field theory", k=2)
    assert len(results) == 2
    # Results are sorted descending by score.
    assert results[0]["score"] >= results[1]["score"]
    # Every result has the required keys.
    for r in results:
        assert "note_path" in r
        assert "heading" in r
        assert "score" in r


@pytest.mark.asyncio
async def test_task_types_are_correct(tmp_path: Path) -> None:
    """Indexing uses RETRIEVAL_DOCUMENT and querying uses RETRIEVAL_QUERY."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "note.md": _simple_note("Note", "Some content."),
    })

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    await idx.index()

    # Index call used RETRIEVAL_DOCUMENT.
    assert provider.calls[0]["task"] == "RETRIEVAL_DOCUMENT"

    await idx.query("test query")

    # Query call used RETRIEVAL_QUERY.
    query_call = provider.calls[-1]
    assert query_call["task"] == "RETRIEVAL_QUERY"
    # embed_one wraps a single text in a list.
    assert len(query_call["texts"]) == 1


@pytest.mark.asyncio
async def test_index_lives_outside_vault(tmp_path: Path) -> None:
    """The index directory is outside the vault; vault is unchanged after indexing."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "note.md": _simple_note("Note", "Some content."),
    })

    before = _vault_snapshot(vault)

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    await idx.index()

    after = _vault_snapshot(vault)
    assert before == after  # byte-identical

    # Index directory is not inside the vault.
    assert not str(idx.index_dir).startswith(str(vault))


@pytest.mark.asyncio
async def test_corrupt_index_is_detected_and_rebuilt(tmp_path: Path) -> None:
    """A corrupt index file is detected and rebuilt rather than crashing."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "note.md": _simple_note("Note", "Some content."),
    })

    provider = FakeEmbeddingProvider()
    idx_dir = tmp_path / "index"
    idx = VaultIndex(provider, vault, idx_dir)

    # First pass to create the file.
    await idx.index()
    assert idx_dir.joinpath("index.json").exists()

    # Corrupt the file.
    idx_dir.joinpath("index.json").write_text("NOT VALID JSON{{{", encoding="utf-8")

    # Re-open and re-index — must not crash.
    idx2 = VaultIndex(provider, vault, idx_dir)
    stats = await idx2.index()
    assert stats.notes_seen == 1
    assert stats.total_chunks == 1  # rebuilt from scratch


@pytest.mark.asyncio
async def test_truncated_index_is_detected_and_rebuilt(tmp_path: Path) -> None:
    """A truncated index file is detected and rebuilt."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "note.md": _simple_note("Note", "Some content."),
    })

    provider = FakeEmbeddingProvider()
    idx_dir = tmp_path / "index"
    idx = VaultIndex(provider, vault, idx_dir)
    await idx.index()

    # Truncate to first 10 bytes.
    raw = idx_dir.joinpath("index.json").read_text("utf-8")
    idx_dir.joinpath("index.json").write_text(raw[:10], encoding="utf-8")

    idx2 = VaultIndex(provider, vault, idx_dir)
    stats = await idx2.index()
    assert stats.total_chunks == 1


@pytest.mark.asyncio
async def test_empty_vault_yields_empty_index(tmp_path: Path) -> None:
    """An empty vault yields an empty index and an empty query result."""
    vault = tmp_path / "vault"
    _make_vault(vault, {})  # no notes

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    stats = await idx.index()

    assert stats.notes_seen == 0
    assert stats.total_chunks == 0
    assert stats.chunks_added == 0
    assert idx.entries == []

    results = await idx.query("anything")
    assert results == []
    # No embed calls at all.
    assert len(provider.calls) == 0


@pytest.mark.asyncio
async def test_empty_vault_query_skips_embed(tmp_path: Path) -> None:
    """Querying an empty index does not call the provider."""
    vault = tmp_path / "vault"
    _make_vault(vault, {})

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    await idx.index()
    provider.calls.clear()

    results = await idx.query("test")
    assert results == []
    assert len(provider.calls) == 0  # no embed call for empty index


@pytest.mark.asyncio
async def test_rebuild_drops_everything(tmp_path: Path) -> None:
    """rebuild() clears the index and re-embeds from scratch."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "a.md": _simple_note("A", "Alpha."),
        "b.md": _simple_note("B", "Bravo."),
    })

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    await idx.index()
    call_count_after_first = len(provider.calls)

    stats = await idx.rebuild()
    assert stats.chunks_added == 2
    assert stats.notes_seen == 2
    # Rebuild always re-embeds.
    assert len(provider.calls) > call_count_after_first


@pytest.mark.asyncio
async def test_note_hashes_persist(tmp_path: Path) -> None:
    """Note hashes survive a round-trip through save/load."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "note.md": _simple_note("Note", "Persist me."),
    })

    provider = FakeEmbeddingProvider()
    idx_dir = tmp_path / "index"
    idx = VaultIndex(provider, vault, idx_dir)
    await idx.index()

    # Reload from disk.
    idx2 = VaultIndex(provider, vault, idx_dir)
    idx2._ensure_loaded()
    assert idx2.note_hashes == idx.note_hashes


@pytest.mark.asyncio
async def test_multiple_domains_indexed(tmp_path: Path) -> None:
    """Notes in different domain folders are all indexed."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "Science/physics.md": _simple_note("Physics", "Forces."),
        "History/rome.md": _simple_note("Rome", "Empire."),
        "Philosophy/ethics.md": _simple_note("Ethics", "Good and evil."),
    })

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    stats = await idx.index()

    assert stats.notes_seen == 3
    assert stats.total_chunks == 3
    paths = {e.note_path for e in idx.entries}
    assert paths == {"Science/physics.md", "History/rome.md", "Philosophy/ethics.md"}


@pytest.mark.asyncio
async def test_agents_and_tmp_excluded(tmp_path: Path) -> None:
    """Files under .agents/ and _tmp/ are not indexed."""
    vault = tmp_path / "vault"
    _make_vault(vault, {
        "real.md": _simple_note("Real", "A real note."),
    })
    # Add files inside excluded dirs.
    (vault / ".agents" / "fake.md").write_text("not a note", encoding="utf-8")
    (vault / "_tmp" / "chunk.md").write_text("chunk data", encoding="utf-8")

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    stats = await idx.index()

    assert stats.notes_seen == 1
    assert len(idx.entries) == 1
    assert idx.entries[0].note_path == "real.md"


@pytest.mark.asyncio
async def test_frontmatter_stripped_from_chunks(tmp_path: Path) -> None:
    """Frontmatter does not appear in the chunk text sent for embedding."""
    vault = tmp_path / "vault"
    note = "---\ntitle: Test\ntags: [x]\n---\n# Title\n\nBody text.\n"
    _make_vault(vault, {"note.md": note})

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, tmp_path / "index")
    await idx.index()

    # The text sent for embedding should not contain frontmatter delimiters.
    for call in provider.calls:
        for text in call["texts"]:
            assert not text.startswith("---")


@pytest.mark.asyncio
async def test_version_mismatch_triggers_rebuild(tmp_path: Path) -> None:
    """An index file with the wrong version is discarded and rebuilt."""
    vault = tmp_path / "vault"
    _make_vault(vault, {"note.md": _simple_note("Note", "Content.")})

    idx_dir = tmp_path / "index"
    idx_dir.mkdir(parents=True)
    idx_dir.joinpath("index.json").write_text(
        json.dumps({"version": 999, "entries": [], "note_hashes": {}}),
        encoding="utf-8",
    )

    provider = FakeEmbeddingProvider()
    idx = VaultIndex(provider, vault, idx_dir)
    stats = await idx.index()

    # Rebuilt from scratch despite the existing file.
    assert stats.chunks_added == 1
    assert stats.total_chunks == 1


# ---------------------------------------------------------------------------
# chunk_note unit tests
# ---------------------------------------------------------------------------


def test_chunk_note_single_heading() -> None:
    """Single ``#`` heading produces one chunk (the intro section)."""
    text = "# Title\n\nBody text.\n"
    chunks = chunk_note(text, "test.md")
    assert len(chunks) == 1
    # The intro section (before any ## heading) gets heading "".
    assert chunks[0][0] == ""
    assert "Body text." in chunks[0][1]


def test_chunk_note_multiple_headings() -> None:
    """Multiple headings produce one chunk per section plus intro."""
    text = "# Title\n\nIntro.\n\n## A\n\nAlpha.\n\n## B\n\nBravo.\n"
    chunks = chunk_note(text, "test.md")
    # Intro + A + B = 3 chunks.
    assert len(chunks) == 3
    assert chunks[0][0] == ""  # intro
    assert chunks[1][0] == "A"
    assert chunks[2][0] == "B"


def test_chunk_note_long_section_splits_on_paragraphs() -> None:
    """A section exceeding target_words splits on paragraph boundaries."""
    # 600 words in two paragraphs.
    para1 = " ".join(["alpha"] * 300)
    para2 = " ".join(["bravo"] * 300)
    text = f"# Title\n\n## Big\n\n{para1}\n\n{para2}\n"
    chunks = chunk_note(text, "test.md", target_words=500)
    assert len(chunks) >= 2


def test_chunk_note_empty_note() -> None:
    """An empty note (after frontmatter) produces no chunks."""
    text = "---\ntitle: Empty\n---\n"
    chunks = chunk_note(text, "empty.md")
    assert chunks == []
