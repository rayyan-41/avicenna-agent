"""Read the entity vocabulary a vault already uses.

Entities are the tags that carry connection in this vault -- ``kant``,
``ibn-sina``, ``al-ghazali`` -- and until now they lived nowhere but in note
frontmatter.  ``taxonomy.json`` recorded themes and types and said nothing
about entities, so the harness had no way to know that this vault writes
``galileo-galilei`` rather than ``galilei``, and a note tagged with the derived
form simply failed to join the one that already existed.

This module reads that vocabulary back out of the notes, once, so it can be
recorded in the taxonomy and used from then on.

**It never validates.**  The entity slot is an open vocabulary by contract, and
a closed list can never validate an open one -- a mistake this project has
already made and written down.  What is produced here is a record of what the
vault says about itself, which is the same direction of travel as deriving
domains from folders rather than declaring them.

The slot rule is taken from the vault's own ``validate_tags.ps1`` rather than
reinvented, because that script is the authority on what an entity is:

    $foundThemes   = @($rest | Where-Object { $themes -contains $_ })
    $foundEntities = @($rest | Where-Object { $themes -notcontains $_ })

An entity is a tail tag that is not a theme.  Note the consequence, which is
also why this matters: a tag minted into ``themes`` stops being an entity to
the validator, silently.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

#: Directories that hold no notes.  ``.obsidian`` is the app's own state and
#: ``.agents`` is the harness's; neither is vault content.
_SKIP_DIRS = frozenset({".agents", ".obsidian", ".git", ".trash"})

#: The positional contract needs domain, category, type, at least one theme and
#: the marker before any tail tag can be an entity.
_MIN_TAGS = 5

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_TAGS_LINE = re.compile(r"^tags:\s*\[(.*?)\]\s*$", re.MULTILINE)


def parse_frontmatter_tags(text: str) -> list[str]:
    """The ``tags: [...]`` array from a note's frontmatter, in order.

    Order is preserved because the contract is positional: the domain is first
    and the marker last, and losing that ordering loses the slot boundaries.
    Returns an empty list when the note has no frontmatter or no tags line,
    which is a legitimate state rather than an error -- a half-written note is
    still a note.
    """
    match = _FRONTMATTER.match(text)
    if match is None:
        return []
    tags_match = _TAGS_LINE.search(match.group(1))
    if tags_match is None:
        return []
    return [
        t.strip().strip('"').strip("'")
        for t in tags_match.group(1).split(",")
        if t.strip()
    ]


def entity_slice(tags: Sequence[str], *, themes: Iterable[str]) -> list[str]:
    """The entity tags in *tags*, by the validator's own rule.

    Everything between the type slot and the marker that is not a known theme.
    A shorter array has no room for an entity and yields nothing.
    """
    if len(tags) < _MIN_TAGS:
        return []
    theme_set = set(themes)
    return [t for t in tags[3:-1] if t and t not in theme_set]


def iter_notes(root: Path) -> Iterator[Path]:
    """Every Markdown file that is vault content."""
    for path in sorted(root.rglob("*.md")):
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


def scan_vault_entities(
    root: Path, *, themes: Iterable[str],
) -> dict[str, int]:
    """Entity tags across the vault, mapped to how many notes carry each.

    The count is the useful part: it says which figures recur, which is the
    shape of the reader's attention that the taxonomy exists to record.
    Unreadable notes are skipped rather than raising -- one bad file must not
    stop the vault being read.
    """
    theme_set = set(themes)
    counts: dict[str, int] = {}
    for path in iter_notes(root):
        try:
            text = path.read_text("utf-8", errors="replace")
        except OSError:
            continue
        for entity in entity_slice(parse_frontmatter_tags(text), themes=theme_set):
            counts[entity] = counts.get(entity, 0) + 1
    return counts


__all__ = [
    "parse_frontmatter_tags",
    "entity_slice",
    "iter_notes",
    "scan_vault_entities",
]
