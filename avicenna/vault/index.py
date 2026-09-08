"""Incremental embedding index over a vault's notes.

Embeds title, headings, and lead paragraphs per note.  Long notes are chunked
on heading boundaries since a section is the natural unit of meaning and the
unit a retrieval query will later match against.

Keyed by note path (relative to vault root) plus a SHA-256 content hash so
a note edited in Obsidian invalidates by hash on the next index pass; nothing
triggers a full re-embed.  A full rebuild is always available via ``rebuild``.

Storage lives under ``~/.avicenna/index/<vault_path_hash>/`` — the sovereignty
doctrine says the vault is the user's and the index is the harness's own
bookkeeping, so it must not pollute the note tree or the vault's git history.

Vectors plus metadata are stored as JSON.  At 768 dimensions and a few thousand
chunks this is tens of megabytes — pure-Python dot products over that scale are
fast enough.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from avicenna.providers.base import EmbeddingProvider

_log = logging.getLogger(__name__)

# Directories never scanned for notes.
_SKIP_DIRS: frozenset[str] = frozenset({".agents", "_tmp", ".git"})

# Frontmatter delimiter regex.
_FM_DELIM = re.compile(r"^---\s*$")

# Heading regex: captures level (number of #) and text.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")

# Default target words per chunk.
_DEFAULT_CHUNK_WORDS = 500

# Current index format version.
_INDEX_VERSION = 1


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChunkEntry:
    """One chunk in the embedding index."""

    note_path: str       # relative to vault root
    heading: str         # the section heading this chunk belongs to
    content_hash: str    # SHA-256 of the chunk text
    vector: list[float]  # embedding vector


@dataclass
class IndexStats:
    """Returned by :meth:`VaultIndex.index`."""

    notes_seen: int
    chunks_added: int
    chunks_removed: int
    total_chunks: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _content_hash(text: str) -> str:
    """SHA-256 hex digest of *text*."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _vault_index_dir(vault_root: Path) -> Path:
    """Default storage directory: ``~/.avicenna/index/<hash>``."""
    vault_hash = hashlib.sha256(
        str(vault_root.resolve()).encode("utf-8")
    ).hexdigest()[:16]
    return Path.home() / ".avicenna" / "index" / vault_hash


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Pure-Python cosine similarity.  Both vectors must be the same length."""
    dot: float = sum(x * y for x, y in zip(a, b))
    norm_a: float = sum(x * x for x in a) ** 0.5
    norm_b: float = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Note reading and chunking
# ---------------------------------------------------------------------------

def _should_skip(rel: Path) -> bool:
    """Return True if this relative path should be excluded from indexing."""
    for part in rel.parts:
        if part.startswith(".") or part == "_tmp":
            return True
    return False


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from the start of a note."""
    lines = text.split("\n")
    if not lines or not _FM_DELIM.match(lines[0]):
        return text
    for i in range(1, len(lines)):
        if _FM_DELIM.match(lines[i]):
            return "\n".join(lines[i + 1 :])
    # Unclosed frontmatter — treat whole text as body.
    return text


def _extract_title(text: str, filename: str) -> str:
    """Extract a title: first ``#`` heading, else stem of the filename."""
    body = _strip_frontmatter(text)
    for line in body.split("\n"):
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) == 1:
            return m.group(2).strip()
    return filename.removesuffix(".md")


def _extract_heading_sections(
    text: str,
) -> list[tuple[str, str]]:
    """Split note body into ``(heading, section_text)`` pairs.

    The first section (before any heading) gets heading ``""``.
    Only ``##`` and ``###`` level headings start new sections — ``#`` is
    the document title and does not split.
    """
    body = _strip_frontmatter(text)
    lines = body.split("\n")

    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in lines:
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) >= 2:
            # A ## or ### heading — flush the previous section.
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = m.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    return sections


def _chunk_section(
    heading: str,
    text: str,
    target_words: int,
) -> list[tuple[str, str]]:
    """Chunk one section into pieces of at most *target_words* words.

    Returns ``[(heading, chunk_text), ...]``.  Paragraph boundaries are the
    secondary split point.
    """
    words = text.split()
    if len(words) <= target_words:
        return [(heading, text)]

    paragraphs = text.split("\n\n")
    chunks: list[tuple[str, str]] = []
    buf: list[str] = []
    buf_words = 0

    for para in paragraphs:
        pw = len(para.split())
        if buf_words + pw > target_words and buf:
            chunks.append((heading, "\n\n".join(buf)))
            buf = []
            buf_words = 0
        buf.append(para)
        buf_words += pw

    if buf:
        chunks.append((heading, "\n\n".join(buf)))

    return chunks


def chunk_note(
    text: str,
    filename: str,
    target_words: int = _DEFAULT_CHUNK_WORDS,
) -> list[tuple[str, str]]:
    """Split a note into ``(heading, chunk_text)`` pairs.

    Prefers heading boundaries; falls back to paragraph splits for sections
    longer than *target_words*.
    """
    sections = _extract_heading_sections(text)
    if not sections:
        return []

    chunks: list[tuple[str, str]] = []
    for heading, section_text in sections:
        if not section_text:
            continue
        chunks.extend(_chunk_section(heading, section_text, target_words))

    # Ensure at least one chunk if there is any content at all.
    if not chunks:
        body = _strip_frontmatter(text).strip()
        if body:
            title = _extract_title(text, filename)
            chunks.append((title, body))

    return chunks


def _read_vault_notes(
    vault_root: Path,
) -> list[tuple[str, str]]:
    """Read all Markdown files from the vault.

    Returns ``(relative_path, full_text)`` pairs, skipping hidden and
    internal directories.
    """
    notes: list[tuple[str, str]] = []
    for md in vault_root.rglob("*.md"):
        rel = md.relative_to(vault_root)
        if _should_skip(rel):
            continue
        text = md.read_text("utf-8", errors="replace")
        notes.append((str(rel.as_posix()), text))
    return notes


# ---------------------------------------------------------------------------
# VaultIndex
# ---------------------------------------------------------------------------

@dataclass
class VaultIndex:
    """Incremental embedding index over a vault's notes.

    Usage::

        index = VaultIndex(provider, vault_root)
        stats = await index.index()       # incremental pass
        results = await index.query("…")  # nearest-neighbour retrieval
    """

    provider: EmbeddingProvider
    vault_root: Path
    index_dir: Path = field(init=False)
    _entries: list[ChunkEntry] = field(default_factory=list, init=False)
    _note_hashes: dict[str, str] = field(default_factory=dict, init=False)
    _loaded: bool = field(default=False, init=False)
    _chunk_target: int = field(default=_DEFAULT_CHUNK_WORDS, init=False)

    def __init__(
        self,
        provider: EmbeddingProvider,
        vault_root: Path,
        index_dir: Path | None = None,
        *,
        chunk_target_words: int = _DEFAULT_CHUNK_WORDS,
    ) -> None:
        self.provider = provider
        self.vault_root = Path(vault_root)
        self.index_dir = index_dir or _vault_index_dir(vault_root)
        self._entries = []
        self._note_hashes = {}
        self._loaded = False
        self._chunk_target = chunk_target_words

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def index(self) -> IndexStats:
        """Incremental index pass: re-embed only changed notes.

        Returns :class:`IndexStats` with counts.
        """
        self._ensure_loaded()
        notes = _read_vault_notes(self.vault_root)

        seen_paths: set[str] = set()
        to_embed: list[tuple[str, str, str]] = []  # (path, heading, text)
        chunks_removed = 0

        for note_path, text in notes:
            seen_paths.add(note_path)
            note_hash = _content_hash(text)

            if (
                note_path in self._note_hashes
                and self._note_hashes[note_path] == note_hash
            ):
                continue  # hash hit — skip

            # Remove stale entries for this note.
            old_count = len(self._entries)
            self._entries = [e for e in self._entries if e.note_path != note_path]
            chunks_removed += old_count - len(self._entries)

            self._note_hashes[note_path] = note_hash

            # Chunk and queue.
            chunks = chunk_note(text, Path(note_path).name, self._chunk_target)
            for heading, chunk_text in chunks:
                to_embed.append((note_path, heading, chunk_text))

        # Remove entries for deleted notes.
        deleted = [p for p in self._note_hashes if p not in seen_paths]
        for p in deleted:
            old_count = len(self._entries)
            self._entries = [e for e in self._entries if e.note_path != p]
            chunks_removed += old_count - len(self._entries)
            del self._note_hashes[p]

        # Batch embed everything that changed.
        if to_embed:
            texts = [t for _, _, t in to_embed]
            vectors = await self.provider.embed(texts, task="RETRIEVAL_DOCUMENT")
            for (note_path, heading, chunk_text), vector in zip(to_embed, vectors):
                self._entries.append(
                    ChunkEntry(
                        note_path=note_path,
                        heading=heading,
                        content_hash=_content_hash(chunk_text),
                        vector=vector,
                    )
                )

        self._save()

        return IndexStats(
            notes_seen=len(seen_paths),
            chunks_added=len(to_embed),
            chunks_removed=chunks_removed,
            total_chunks=len(self._entries),
        )

    async def rebuild(self) -> IndexStats:
        """Drop everything and re-index from scratch."""
        self._entries = []
        self._note_hashes = {}
        self._loaded = True
        return await self.index()

    async def query(
        self,
        text: str,
        *,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Nearest-neighbour retrieval.

        Returns up to *k* dicts with ``note_path``, ``heading``, ``score``.
        Uses ``RETRIEVAL_QUERY`` task type.
        """
        self._ensure_loaded()
        if not self._entries:
            return []

        query_vec = await self.provider.embed_one(text, task="RETRIEVAL_QUERY")

        scored: list[dict[str, Any]] = []
        for entry in self._entries:
            sim = _cosine_similarity(query_vec, entry.vector)
            scored.append(
                {
                    "note_path": entry.note_path,
                    "heading": entry.heading,
                    "score": sim,
                }
            )

        scored.sort(key=lambda d: d["score"], reverse=True)
        return scored[:k]

    @property
    def entries(self) -> list[ChunkEntry]:
        """Read-only view of current index entries."""
        return list(self._entries)

    @property
    def note_hashes(self) -> dict[str, str]:
        """Read-only view of note-path to content-hash mapping."""
        return dict(self._note_hashes)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Persist the index to ``index.json``."""
        self.index_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "version": _INDEX_VERSION,
            "vault_root": str(self.vault_root),
            "entries": [
                {
                    "note_path": e.note_path,
                    "heading": e.heading,
                    "content_hash": e.content_hash,
                    "vector": e.vector,
                }
                for e in self._entries
            ],
            "note_hashes": self._note_hashes,
        }
        path = self.index_dir / "index.json"
        path.write_text(json.dumps(data), encoding="utf-8")

    def _load(self) -> None:
        """Load index from disk.  Corrupt files are treated as empty."""
        path = self.index_dir / "index.json"
        if not path.exists():
            return
        try:
            raw = path.read_text("utf-8")
            data = json.loads(raw)
            if data.get("version") != _INDEX_VERSION:
                _log.warning("index version mismatch; will rebuild")
                return
            self._entries = [
                ChunkEntry(
                    note_path=e["note_path"],
                    heading=e["heading"],
                    content_hash=e["content_hash"],
                    vector=e["vector"],
                )
                for e in data.get("entries", [])
            ]
            self._note_hashes = data.get("note_hashes", {})
        except (json.JSONDecodeError, KeyError, TypeError):
            _log.warning("corrupt index file; will rebuild")
            self._entries = []
            self._note_hashes = {}

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._loaded = True
            self._load()


__all__ = [
    "ChunkEntry",
    "IndexStats",
    "VaultIndex",
    "chunk_note",
]
