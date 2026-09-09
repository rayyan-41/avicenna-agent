"""Semantic drift guard: embedding-based similarity oracle.

The taxonomy is meant to be a map of where a reader's attention has actually
gone.  Left alone, a model will mint ``nationalism``, ``national-identity``,
``nationhood`` and ``the-nation-state`` across four notes about one region of
thought, and the map becomes a log.  The oracle detects when a proposed key
is semantically equivalent to one already in the registry and returns the
existing key to reuse instead of minting a new one.

**The 0.80 default is a guess, not a measurement.**  Nobody here has seen
``gemini-embedding-2``'s score distribution over this vault's vocabulary, and
the right threshold cannot be derived from the model's dimensionality or from
first principles -- it is a property of the vocabulary being compared.  0.80 is
chosen to err toward minting, because the two failure modes are not symmetric:
a registry that fragments into synonyms is prunable afterwards, while a merge
that collapses two distinct ideas destroys the distinction silently and cannot
be recovered from the taxonomy alone.

What would settle it: run the pairwise similarity matrix over the real
taxonomy and read where the two traps actually fall -- ``nationalism`` /
``national-identity`` (which should merge) must sit above the line, and
``epistemology`` / ``eschatology`` (which must not) below it.  Until someone
has done that against real vectors, treat this number as unvalidated.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from avicenna.providers.base import EmbeddingProvider

_log = logging.getLogger(__name__)

# Where the embedding cache lives.  ~/.avicenna/index/ is already the
# harness's own bookkeeping directory — VaultIndex stores its note-vectors
# there.  The guard cache is a sibling file, not inside a vault hash
# subdirectory, because tag embeddings are global: the same tag appears
# across vaults and should not be re-embedded per vault.
_CACHE_DIR = Path.home() / ".avicenna" / "index"
_CACHE_FILE_NAME = "embedding_cache.json"
_CACHE_VERSION = 1


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Pure-Python cosine similarity.  Both vectors must be the same length."""
    dot: float = sum(x * y for x, y in zip(a, b))
    norm_a: float = sum(x * x for x in a) ** 0.5
    norm_b: float = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass(frozen=True)
class DriftVerdict:
    """One verdict from the drift oracle, for a single proposed key."""

    proposed: str
    #: The existing key to merge with, or ``None`` when the key is genuinely
    #: new.
    merge_with: str | None
    #: The nearest existing key, regardless of threshold.  Always populated
    #: when existing keys were available; empty string only when the existing
    #: set was empty.
    nearest: str
    #: Cosine similarity to the nearest key.
    similarity: float


class DriftOracle:
    """Embedding-based semantic similarity check for the drift guard.

    Batch-in, verdict-out.  Embeds proposed keys and existing keys in one
    call (respecting the provider's batch primitive), computes cosine
    similarity, and returns a :class:`DriftVerdict` for each proposed key.

    Embeddings are cached on disk so the taxonomy's ~100 keys are not
    re-embedded every run.  The cache is keyed by the provider's model name
    plus a SHA-256 of the text, because vectors from two models are not
    comparable and a silent mix produces similarity scores that mean nothing.
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        threshold: float,
        *,
        cache_dir: Path | None = None,
    ) -> None:
        self._provider = provider
        self._threshold = threshold
        self._cache_dir = cache_dir or _CACHE_DIR
        self._cache: dict[str, list[float]] = {}
        self._cache_dirty = False
        self._loaded = False

    async def check_batch(
        self,
        proposed: Sequence[tuple[str, str]],
        existing_keys: Sequence[str],
    ) -> list[DriftVerdict]:
        """Check each proposed key against existing keys.

        *proposed* is a sequence of ``(normalized_key, context)`` pairs.
        *existing_keys* are the normalized keys already in the registry.

        Returns one :class:`DriftVerdict` per proposed key.  When the
        existing set is empty, every verdict is a mint.
        """
        if not proposed:
            return []

        self._ensure_cache_loaded()

        # Proposed keys embed with their context (the sentence that produced
        # them) when available; existing keys embed as-is — they are already
        # canonical tags.
        proposed_texts = [ctx if ctx else nk for nk, ctx in proposed]
        all_texts = list(proposed_texts) + list(existing_keys)

        # Embed everything that is not already cached.
        uncached = [
            t for t in all_texts
            if self._text_cache_key(t) not in self._cache
        ]
        if uncached:
            try:
                vectors = await self._provider.embed(
                    uncached,
                    task="SEMANTIC_SIMILARITY",
                )
                for text, vector in zip(uncached, vectors):
                    self._cache[self._text_cache_key(text)] = vector
                    self._cache_dirty = True
            except Exception as exc:
                _log.warning(
                    "embedding call failed; semantic guard disabled: %s", exc,
                )
                return [
                    DriftVerdict(
                        proposed=nk, merge_with=None,
                        nearest="", similarity=0.0,
                    )
                    for nk, _ in proposed
                ]

        # Retrieve all vectors from cache.  A miss here means the embed call
        # returned fewer vectors than texts — a provider bug, not a guard
        # failure.  Degrade to mint-all rather than crashing the run.
        proposed_vecs: list[list[float]] = []
        for text in proposed_texts:
            vec = self._cache.get(self._text_cache_key(text))
            if vec is None:
                _log.warning(
                    "embedding missing after successful call; skipping guard",
                )
                return [
                    DriftVerdict(
                        proposed=nk, merge_with=None,
                        nearest="", similarity=0.0,
                    )
                    for nk, _ in proposed
                ]
            proposed_vecs.append(vec)

        existing_vecs: list[list[float]] = []
        for text in existing_keys:
            vec = self._cache.get(self._text_cache_key(text))
            if vec is None:
                _log.warning(
                    "embedding missing for existing key; skipping guard",
                )
                return [
                    DriftVerdict(
                        proposed=nk, merge_with=None,
                        nearest="", similarity=0.0,
                    )
                    for nk, _ in proposed
                ]
            existing_vecs.append(vec)

        # Compute verdicts.
        verdicts: list[DriftVerdict] = []
        for i, (nk, _ctx) in enumerate(proposed):
            if not existing_keys:
                verdicts.append(DriftVerdict(
                    proposed=nk, merge_with=None,
                    nearest="", similarity=0.0,
                ))
                continue

            best_sim = -1.0
            best_idx = 0
            for j in range(len(existing_keys)):
                sim = _cosine_similarity(proposed_vecs[i], existing_vecs[j])
                if sim > best_sim:
                    best_sim = sim
                    best_idx = j

            nearest = existing_keys[best_idx]
            merge = nearest if best_sim >= self._threshold else None
            verdicts.append(DriftVerdict(
                proposed=nk,
                merge_with=merge,
                nearest=nearest,
                similarity=best_sim,
            ))

        # Persist cache only after a successful batch so a provider failure
        # never corrupts the on-disk store.
        if self._cache_dirty:
            self._save_cache()

        return verdicts

    @property
    def threshold(self) -> float:
        """The configured similarity threshold."""
        return self._threshold

    # ------------------------------------------------------------------
    # Cache persistence
    # ------------------------------------------------------------------
    # Follows the VaultIndex pattern: JSON on disk, content-hash keyed,
    # atomic write via .part + os.replace, version-gated load, corrupt file
    # treated as empty.

    def _text_cache_key(self, text: str) -> str:
        """Cache key: provider name + text, SHA-256 hashed.

        Including the provider name ensures vectors from different models
        never collide — ``gemini-embedding-2`` and a hypothetical future
        model produce incomparable vectors.
        """
        combined = f"{self._provider.name}:{text}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    def _ensure_cache_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        path = self._cache_dir / _CACHE_FILE_NAME
        if not path.exists():
            return
        try:
            raw = path.read_text("utf-8")
            data = json.loads(raw)
            if data.get("version") != _CACHE_VERSION:
                _log.warning("embedding cache version mismatch; will re-embed")
                return
            entries = data.get("entries", {})
            self._cache = {
                k: v for k, v in entries.items()
                if isinstance(v, list)
            }
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            _log.warning("corrupt embedding cache; will re-embed")
            self._cache = {}

    def _save_cache(self) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_dir / _CACHE_FILE_NAME
        tmp = path.with_suffix(".json.part")
        data = {
            "version": _CACHE_VERSION,
            "entries": self._cache,
        }
        try:
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, path)
            self._cache_dirty = False
        except OSError:
            tmp.unlink(missing_ok=True)
            _log.warning("could not persist embedding cache")


__all__ = ["DriftOracle", "DriftVerdict"]
