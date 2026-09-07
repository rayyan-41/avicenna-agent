"""Theme and type registry: the harness maintains a map of the reader's mind.

Themes and types are inferred by the harness, per note, and accumulated in
taxonomy.json so the registry becomes a record of where the reader's
attention has actually gone.  This module owns the resolution, normalization
and persistence logic.  The tagger proposes; a deterministic check disposes.

The semantic guard (embedding-based similarity that folds near-duplicates
like ``national-identity`` into ``nationalism``) is deferred to step 4 of
the sequencing plan.  ``semantic_guard`` is the seam it will attach to —
it currently returns ``None`` for every proposed key and must not be
replaced with a fuzzy string-similarity heuristic, because a wrong merge
silently collapses distinct ideas.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
# Case, separator and plural insensitive: ``Nationalism``, ``nationalism``,
# ``nationalisms`` are one theme.  The canonical form is the first raw value
# encountered for a given normalized key.

_PLURAL_S = re.compile(r"ies$")
_PLURAL_ES = re.compile(r"(?:sh|ch|x|z|s)es$")


def _normalize(key: str) -> str:
    """Fold case, separator and plural variants into a canonical form.

    ``National-Identity`` → ``national identity``
    ``nationalisms`` → ``nationalism``
    """
    k = key.lower().replace("-", " ").replace("_", " ").strip()
    # Naive singularisation — deliberately conservative.  It handles the
    # common cases (nationalisms → nationalism, churches → church) and
    # leaves irregular plurals alone.  The semantic guard is the correct
    # place for deeper merging; this is the fast, deterministic floor.
    k = _PLURAL_S.sub("y", k)
    k = _PLURAL_ES.sub(
        lambda m: m.group(0)[: -2],  # drop 'es'
        k,
    )
    if k.endswith("s") and not k.endswith("ss") and len(k) > 3:
        k = k[:-1]
    return k


def semantic_guard(
    proposed: str,
    existing_keys: list[str],
    context: str = "",
) -> str | None:
    """Return an existing key that is semantically equivalent to *proposed*.

    This is a seam for the embedding-based similarity check described in
    the design spec.  When the embedding provider is integrated, this
    function will embed *proposed* (with its *context*) and compare against
    every existing key's embedding.  Above the similarity threshold the
    existing key is returned; below it, ``None`` signals a new mint.

    Currently always returns ``None`` — every proposed key that passes
    normalization is accepted as genuinely new.  Do NOT replace this with
    a fuzzy string-similarity heuristic; a wrong merge silently collapses
    distinct ideas, which is worse than the drift it prevents.

    Args:
        proposed: The proposed theme or type, after normalization.
        existing_keys: Normalized keys already in the registry.
        context: The sentence-level context that produced the key (unused
            until the embedding provider is available).
    """
    return None


# ---------------------------------------------------------------------------
# ThemeRegistry
# ---------------------------------------------------------------------------

@dataclass
class ThemeRegistry:
    """Accumulate themes and types in taxonomy.json.

    The registry loads the file independently of ``Taxonomy`` (which is a
    frozen dataclass) so it can mutate the arrays and persist back.
    """

    taxonomy_path: Path
    raw: dict[str, Any] = field(default_factory=dict)
    _theme_canonical: dict[str, str] = field(default_factory=dict)
    _type_canonical: dict[str, str] = field(default_factory=dict)
    #: Newly minted keys in this run, not yet persisted.
    _minted_themes: list[str] = field(default_factory=list)
    _minted_types: list[str] = field(default_factory=list)
    _dirty: bool = False

    @classmethod
    def load(cls, taxonomy_path: Path) -> ThemeRegistry:
        """Load the registry from taxonomy.json."""
        data = json.loads(taxonomy_path.read_text("utf-8"))
        reg = cls(taxonomy_path=taxonomy_path, raw=data)
        reg._rebuild_index()
        return reg

    def _rebuild_index(self) -> None:
        """Rebuild the canonical lookup from the current raw data."""
        self._theme_canonical = {}
        for t in self.raw.get("themes", []):
            nk = _normalize(t)
            if nk not in self._theme_canonical:
                self._theme_canonical[nk] = t
        self._type_canonical = {}
        for t in self.raw.get("types", []):
            nk = _normalize(t)
            if nk not in self._type_canonical:
                self._type_canonical[nk] = t

    # --- resolution ----------------------------------------------------------

    def resolve_theme(self, proposed: str) -> tuple[str, bool]:
        """Resolve *proposed* against the theme registry.

        Returns ``(canonical_form, is_new)``.  When *proposed* normalizes
        to an existing key, the existing canonical form is returned and
        *is_new* is ``False``.  Otherwise the proposed value is minted
        as a new theme, appended to the raw array, and *is_new* is
        ``True``.
        """
        nk = _normalize(proposed)
        if nk in self._theme_canonical:
            return self._theme_canonical[nk], False

        # Semantic guard — the seam for embedding-based similarity.
        guard = semantic_guard(nk, list(self._theme_canonical.keys()))
        if guard is not None:
            return guard, False

        # Mint: use the proposed value as-is for the canonical form.
        self._theme_canonical[nk] = proposed
        themes = self.raw.setdefault("themes", [])
        themes.append(proposed)
        self._minted_themes.append(proposed)
        self._dirty = True
        return proposed, True

    def resolve_type(self, proposed: str) -> tuple[str, bool]:
        """Resolve *proposed* against the type registry.

        Same contract as ``resolve_theme``.
        """
        nk = _normalize(proposed)
        if nk in self._type_canonical:
            return self._type_canonical[nk], False

        guard = semantic_guard(nk, list(self._type_canonical.keys()))
        if guard is not None:
            return guard, False

        self._type_canonical[nk] = proposed
        types = self.raw.setdefault("types", [])
        types.append(proposed)
        self._minted_types.append(proposed)
        self._dirty = True
        return proposed, True

    # --- persistence ---------------------------------------------------------

    def persist(self) -> bool:
        """Atomically write taxonomy.json if the registry was mutated.

        Preserves key order, existing indentation style, and every key the
        file carries.  Returns ``True`` if the write succeeded, ``False``
        if the file was unwritable (the run must continue with the tags
        validated against what is already there).

        When themes carry a ``_counts`` mapping alongside the array, the
        counts are persisted too.  This is a schema extension that lives
        inside the raw dict and is invisible to ``Taxonomy.load`` (which
        ignores unknown keys).  If the vault's taxonomy.json already has
        a ``_counts`` key it is preserved; otherwise one is created when
        the first theme is minted.
        """
        if not self._dirty:
            return True

        # Update counts if we have a _counts mapping.
        counts: dict[str, int] = self.raw.setdefault("_themeCounts", {})
        for t in self._minted_themes:
            counts[t] = counts.get(t, 0) + 1
        type_counts: dict[str, int] = self.raw.setdefault("_typeCounts", {})
        for t in self._minted_types:
            type_counts[t] = type_counts.get(t, 0) + 1

        # Detect indentation from the existing file.
        indent = self._detect_indent()
        tmp = self.taxonomy_path.with_suffix(".json.part")
        try:
            tmp.write_text(
                json.dumps(self.raw, indent=indent, ensure_ascii=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            os.replace(tmp, self.taxonomy_path)
        except OSError:
            tmp.unlink(missing_ok=True)
            return False
        self._dirty = False
        return True

    def _detect_indent(self) -> int:
        """Detect the indentation level of the existing file."""
        try:
            text = self.taxonomy_path.read_text("utf-8")
        except OSError:
            return 2
        for line in text.splitlines():
            stripped = line.lstrip()
            if stripped and stripped != line:
                diff = len(line) - len(stripped)
                return diff if diff > 0 else 2
        return 2

    # --- queries -------------------------------------------------------------

    def undo_mint(self, kind: str, canonical: str) -> None:
        """Reverse a mint that turned out to belong to the other category.

        Called when a tag was tentatively minted as a theme but is actually
        a known type (or vice versa).  Removes from the canonical index,
        the raw array, and the minted list.
        """
        nk = _normalize(canonical)
        if kind == "theme":
            self._theme_canonical.pop(nk, None)
            themes = self.raw.get("themes", [])
            self.raw["themes"] = [t for t in themes if _normalize(t) != nk]
            self._minted_themes = [t for t in self._minted_themes
                                   if _normalize(t) != nk]
        elif kind == "type":
            self._type_canonical.pop(nk, None)
            types = self.raw.get("types", [])
            self.raw["types"] = [t for t in types if _normalize(t) != nk]
            self._minted_types = [t for t in self._minted_types
                                  if _normalize(t) != nk]

    @property
    def minted_themes(self) -> list[str]:
        """Themes minted in this run, not yet cleared."""
        return list(self._minted_themes)

    @property
    def minted_types(self) -> list[str]:
        """Types minted in this run, not yet cleared."""
        return list(self._minted_types)

    @property
    def theme_count(self) -> int:
        """Total themes in the registry."""
        return len(self.raw.get("themes", []))

    @property
    def type_count(self) -> int:
        """Total types in the registry."""
        return len(self.raw.get("types", []))

    def themes_for_hint(self) -> list[str]:
        """Current themes, for injecting into the tagger's taxonomy hint."""
        return list(self.raw.get("themes", []))

    def types_for_hint(self) -> list[str]:
        """Current types, for injecting into the tagger's taxonomy hint."""
        return list(self.raw.get("types", []))
