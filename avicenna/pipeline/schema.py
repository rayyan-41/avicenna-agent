"""Frontmatter schema detection: match the vault, do not impose.

The harness used to write its own schema (title / domain / template / tags)
into every note, regardless of what the vault's existing notes used.  Two
notes from the same live run ended up with different schemas depending on
whether the weaver happened to emit a frontmatter block — an accident
deciding the shape of the user's data.

This module samples existing notes to detect the vault's convention and
returns a schema the pipeline can write faithfully.  The detection result is
cached per run on RunContext so every stage sees the same schema.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Sequence

_FRONTMATTER = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---\r?\n?", re.DOTALL)
_KEY_LINE = re.compile(r"^\s*([A-Za-z_][\w.-]*)\s*:", re.MULTILINE)


@dataclass(frozen=True)
class FrontmatterSchema:
    """The detected frontmatter convention for a vault or domain.

    ``keys`` preserves the order found in the sampled notes.  ``tags_present``
    is always True because the harness owns tags regardless of what the sample
    contained.  ``defaults`` maps keys to values the harness can fill when it
    has a real value — a date gets today's ISO string, a status gets the
    dominant sample value.
    """

    keys: tuple[str, ...]
    source: str  # "domain" | "vault" | "fallback"
    defaults: dict[str, str] = field(default_factory=dict)


_KEY_VALUE = re.compile(r"^\s*([A-Za-z_][\w.-]*)\s*:\s*(.*?)\s*$", re.MULTILINE)


def _parse_frontmatter_keys(text: str) -> list[str] | None:
    """Return the ordered list of YAML keys from a frontmatter block, or None."""
    match = _FRONTMATTER.match(text)
    if match is None:
        return None
    body = match.group("body")
    keys: list[str] = []
    for line in body.splitlines():
        m = _KEY_LINE.match(line)
        if m:
            keys.append(m.group(1))
    return keys if keys else None


def _extract_frontmatter_value(text: str, key: str) -> str | None:
    """Return the YAML-parsed value of *key* from a frontmatter block, or None.

    The raw YAML scalar is parsed so quoted values (``""``, ``'foo'``) resolve
    to their Python equivalents rather than carrying the quote characters.
    """
    match = _FRONTMATTER.match(text)
    if match is None:
        return None
    body = match.group("body")
    for line in body.splitlines():
        m = _KEY_VALUE.match(line)
        if m and m.group(1) == key:
            raw = m.group(2)
            try:
                import yaml
                parsed = yaml.safe_load(raw)
            except Exception:  # noqa: BLE001
                return raw
            return str(parsed) if parsed is not None else ""
    return None


def _is_moc(path: Path) -> bool:
    """Heuristic: MOC files are named 'Map of Contents - <Domain>.md' or
    contain 'MOC' in the stem."""
    stem = path.stem.lower()
    return "map of contents" in stem or "moc" in stem


def _sample_notes(vault_root: Path, domain: str | None = None,
                  limit: int = 50) -> list[Path]:
    """Collect up to *limit* ``.md`` files from the vault, preferring the
    target domain.  Excludes MOCs, ``_tmp/``, ``.agents/``, and the vault
    root's ``AGENTS.md``."""
    candidates: list[Path] = []

    # Domain-first search
    if domain:
        norm = domain.replace("-", " ").lower()
        for child in vault_root.iterdir():
            if not child.is_dir():
                continue
            if child.name.replace("-", " ").lower() != norm:
                continue
            for p in child.glob("*.md"):
                if not _is_moc(p):
                    candidates.append(p)
                    if len(candidates) >= limit:
                        return candidates

    # Vault-wide search
    for p in vault_root.rglob("*.md"):
        if len(candidates) >= limit:
            break
        rel = p.relative_to(vault_root)
        parts = rel.parts
        # Skip dotted dirs, _tmp, .agents, and root AGENTS.md
        if any(part.startswith(".") or part == "_tmp" for part in parts):
            continue
        if p.parent == vault_root and p.name == "AGENTS.md":
            continue
        if _is_moc(p):
            continue
        if p not in candidates:
            candidates.append(p)

    return candidates[:limit]


def _dominant_schema(keys_lists: Sequence[Sequence[str]]) -> tuple[tuple[str, ...], str]:
    """Return the most common key-set-and-order, and its frequency label.

    When there is a tie the lexicographically first tuple wins (deterministic).
    """
    counter: Counter[tuple[str, ...]] = Counter()
    for keys in keys_lists:
        counter[tuple(keys)] += 1
    if not counter:
        return (), ""
    best, count = counter.most_common(1)[0]
    return best, f"{count}/{len(keys_lists)}"


def _default_for_key(key: str, values: Sequence[str]) -> str | None:
    """Return a sensible default for *key* when the harness can fill one.

    ``date`` → today's ISO string.  For every other key, if the sampled
    values are all the same literal (including empty string), that literal
    becomes the default.  When values genuinely vary, return ``None`` —
    the harness does not invent content.
    """
    if key == "date":
        return date.today().isoformat()
    if not values:
        return None
    first = values[0]
    if all(v == first for v in values):
        return first
    return None


def detect_frontmatter_schema(
    vault_root: Path,
    domain: str | None = None,
) -> FrontmatterSchema:
    """Sample the vault's notes and return the dominant frontmatter schema.

    The target domain is sampled first; if it has no notes the vault at large
    is sampled.  When the vault has no notes at all the scaffold schema is
    returned as a fallback — that is the one case where the harness may choose
    because there is nothing to read.
    """
    # --- scaffold fallback (used when the vault has no notes) ----------------
    fallback = FrontmatterSchema(
        keys=("title", "domain", "template", "tags"),
        source="fallback",
        defaults={},
    )

    notes = _sample_notes(vault_root, domain=domain)
    if not notes:
        return fallback

    keys_lists: list[list[str]] = []
    for path in notes:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        keys = _parse_frontmatter_keys(text)
        if keys is not None:
            keys_lists.append(keys)

    if not keys_lists:
        return fallback

    best, freq = _dominant_schema(keys_lists)

    # Ensure 'tags' is present — the harness owns it regardless of what the
    # sample contained.
    if "tags" not in best:
        best = (*best, "tags")

    # Collect the actual text value of each key across every sampled note so
    # _default_for_key can learn consistent-value defaults (e.g. ``note: ""``
    # appearing in every note becomes the default, not an omission).
    values_per_key: dict[str, list[str]] = {k: [] for k in best}
    for path in notes:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for k in best:
            v = _extract_frontmatter_value(text, k)
            if v is not None:
                values_per_key[k].append(v)

    # Build defaults for keys the harness can fill.
    defaults: dict[str, str] = {}
    for k in best:
        d = _default_for_key(k, values_per_key.get(k, []))
        if d is not None:
            defaults[k] = d

    source = "domain" if domain and any(
        p.relative_to(vault_root).parts[0].lower() == domain.lower()
        for p in notes
    ) else "vault"

    return FrontmatterSchema(keys=best, source=source, defaults=defaults)
