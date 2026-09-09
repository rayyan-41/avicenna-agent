"""Connect a finished note to the rest of the vault, deterministically.

This is not the linker that was removed on 2026-09-08.  That one handed the
whole note to a model and asked it where links belonged; it invented notes that
did not exist, wrapped the note's own headings in brackets eight times in one
run, and needed a resolver downstream purely to clean up after it.  Nothing
here asks a model anything.  Both mechanisms are string and tag operations over
data the vault already holds:

1. **Related notes, by shared tags.**  The vault's own ``get_related_notes.ps1``
   already implements the policy -- two or more shared core tags is a primary
   match, one shared core tag plus the same category is secondary -- so the
   harness calls it and renders the result rather than reimplementing the rule.
   That is the same discipline as ``validate_tags``: the tool is the authority.

2. **Entity mentions that have their own note.**  A note on Kant that mentions
   Rousseau should reach the note *about* Rousseau, if one exists.  The entity
   tags say who the note is about; the vault's filenames say who has a note.

The naming problem is the same one the entity registry solves: a note may be
filed as "Jean-Jacques Rousseau" while the entity tag is ``rousseau``.  So the
index is keyed by both the full kebab-case form of the filename and its last
segment, and a key claimed by two different notes is dropped rather than
guessed -- ``mill`` with two Mills on file links to neither.

Every function here is pure.  The stage supplies the vault listing and the tool
output; nothing in this module reads a file or calls a provider.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

#: A fenced code block opener or closer.
_FENCE_LINE = re.compile(r"^\s*(`{3,}|~{3,})")

#: Text already inside a wikilink, so a second pass cannot nest one.
_EXISTING_LINK = re.compile(r"\[\[[^\]]*\]\]")

#: Characters that break a wikilink target, mirroring structure.py's rule.
_LINK_HOSTILE = re.compile(r"[\[\]#^|]")


def _kebab(text: str) -> str:
    """Filename to tag form: ``Jean-Jacques Rousseau`` -> ``jean-jacques-rousseau``."""
    cleaned = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s_-]+", "-", cleaned)


# ---------------------------------------------------------------------------
# Which entities have a note of their own
# ---------------------------------------------------------------------------


#: Words that mark a filename as a sentence rather than somebody's name.
#: A title containing one of these is a note *about* a subject, not a note
#: filed *under* a name, so its last word is not a surname.
_FUNCTION_WORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "from",
    "as", "by", "with", "without", "into", "over", "under", "between", "how",
    "why", "what", "when", "is", "was", "were", "are", "its", "his", "her",
    "their", "this", "that", "these", "those", "not", "no", "vs", "versus",
})

#: Longest a filename can be and still plausibly be a personal name.
_MAX_NAME_SEGMENTS = 4


def _is_name_like(key: str) -> bool:
    """True when a kebab-case filename could be somebody's name.

    This decides whether the last segment is registered as a surname alias,
    and getting it wrong is expensive in a way that shows up only against a
    real vault. Registering the last segment unconditionally made the tag
    `kant` resolve to a note called "Rousseau's and David Hume's profound
    impact on Immanuel Kant" -- a note that mentions Kant, filed under a
    sentence, and not the Kant note at all. The same rule sent `attention` to
    "Foundations of Attention" and `rasterization` to "Triangles as the basis
    for Rasterization".

    A name is short and carries no function words. A title is one or both.
    """
    segments = key.split("-")
    if len(segments) > _MAX_NAME_SEGMENTS:
        return False
    return not any(seg in _FUNCTION_WORDS for seg in segments)


def subject_index(note_stems: Iterable[str]) -> dict[str, str]:
    """Map an entity tag form to the note filed under that name.

    A filename is always registered under its full kebab-case form. It is
    *also* registered under its last segment when the filename reads as a
    name rather than a title (see `_is_name_like`), so the tag ``rousseau``
    finds "Jean-Jacques Rousseau". That asymmetry is the one the entity
    registry reconciles, for the same reason -- the tag records a figure, the
    filename records how this vault writes their name, and the two are rarely
    identical.

    A key that two different notes would claim is **removed**, not resolved.
    With both Mills on file, ``mill`` names neither of them, and a link to the
    wrong person is worse than no link: it is a claim the note did not make.
    """
    claims: dict[str, set[str]] = {}
    for stem in note_stems:
        key = _kebab(stem)
        if not key:
            continue
        claims.setdefault(key, set()).add(stem)
        last = key.rsplit("-", 1)[-1]
        if last != key and _is_name_like(key):
            claims.setdefault(last, set()).add(stem)
    return {k: next(iter(v)) for k, v in claims.items() if len(v) == 1}


def resolve_entity_notes(
    entities: Sequence[str],
    index: Mapping[str, str],
) -> dict[str, str]:
    """Entity tag -> the note filed under that name, for those that have one.

    Order follows *entities*, so the note's own tag order decides which link
    lands first when two entities share a sentence.
    """
    out: dict[str, str] = {}
    for entity in entities:
        key = _kebab(entity)
        stem = index.get(key)
        if stem is not None and stem not in out.values():
            out[entity] = stem
    return out


# ---------------------------------------------------------------------------
# Inline linking
# ---------------------------------------------------------------------------


def _linkable_regions(lines: Sequence[str]) -> list[int]:
    """Line indices that hold ordinary prose.

    Excluded, and each for its own reason: fenced code, because a name inside
    a code sample is not a mention; headings, because a link in a heading
    breaks the TOC anchor that must match it byte for byte; and callouts and
    blockquotes, which is where the table of contents lives.
    """
    out: list[int] = []
    fence_char = ""
    for i, line in enumerate(lines):
        m = _FENCE_LINE.match(line)
        if m:
            char = m.group(1)[0]
            if not fence_char:
                fence_char = char
            elif char == fence_char:
                fence_char = ""
            continue
        if fence_char:
            continue
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith(">"):
            continue
        out.append(i)
    return out


def _mention_candidates(entity: str, stem: str) -> list[str]:
    """Surface forms to look for, longest first.

    The full filename is tried before the bare surname so "Jean-Jacques
    Rousseau" in the prose is captured whole rather than leaving a stray
    "Jean-Jacques " outside the link.
    """
    candidates = [stem]
    surname = _kebab(entity).rsplit("-", 1)[-1]
    if surname:
        candidates.append(surname.capitalize())
    ordered = list(dict.fromkeys(c for c in candidates if c))
    return sorted(ordered, key=len, reverse=True)


def _already_linked(body: str, stem: str) -> bool:
    """True when *body* already carries a wikilink to *stem*.

    Matches both `[[Name]]` and the aliased `[[Name|surface]]`.
    """
    pattern = re.compile(rf"\[\[{re.escape(stem)}(\||\]\])")
    return pattern.search(body) is not None


def link_first_mentions(
    body: str,
    targets: Mapping[str, str],
) -> tuple[str, list[str]]:
    """Wrap the first mention of each target in a wikilink.

    Returns the new body and the note names actually linked.  Only the first
    occurrence of each is touched: a note that says "Rousseau" forty times
    should read as prose, not as a link farm, and Obsidian resolves the
    connection from one link as well as from forty.

    Where the prose uses a shorter form than the filename, the alias form
    ``[[Jean-Jacques Rousseau|Rousseau]]`` is written, so the sentence still
    reads the way its author wrote it.
    """
    if not targets:
        return body, []

    lines = body.split("\n")
    linkable = _linkable_regions(lines)
    linked: list[str] = []

    for entity, stem in targets.items():
        if _LINK_HOSTILE.search(stem):
            # The filename cannot survive as a link target; skip rather than
            # emit a link that silently resolves to nothing.
            continue
        if _already_linked(body, stem):
            # A resumed run re-enters the stage on a note that was already
            # linked. Without this the *second* mention gets linked too, then
            # the third, and a note picks up one more link per resume -- while
            # every individual pass still looks like it linked once.
            continue
        done = False
        for surface in _mention_candidates(entity, stem):
            if done:
                break
            pattern = re.compile(rf"(?<![\w\[]){re.escape(surface)}(?![\w\]])")
            for i in linkable:
                line = lines[i]
                # Never nest inside an existing link.
                spans = [m.span() for m in _EXISTING_LINK.finditer(line)]
                for m in pattern.finditer(line):
                    if any(a <= m.start() < b for a, b in spans):
                        continue
                    replacement = (
                        f"[[{stem}]]" if surface == stem
                        else f"[[{stem}|{surface}]]"
                    )
                    lines[i] = line[:m.start()] + replacement + line[m.end():]
                    linked.append(stem)
                    done = True
                    break
                if done:
                    break

    return "\n".join(lines), linked


# ---------------------------------------------------------------------------
# The related-notes section
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelatedNote:
    """One candidate from ``get_related_notes.ps1``."""

    score: int
    match: str
    path: str
    tags: tuple[str, ...]

    @property
    def stem(self) -> str:
        """The note name, from the tail of the path."""
        tail = self.path.replace("\\", "/").rsplit("/", 1)[-1]
        return tail[:-3] if tail.lower().endswith(".md") else tail


_CANDIDATE_LINE = re.compile(
    r"SCORE:\s*(?P<score>\d+)\s*\|\s*MATCH:\s*(?P<match>\w+)\s*\|\s*"
    r"PATH:\s*(?P<path>.*?)\s*\|\s*TAGS:\s*(?P<tags>.*?)\s*$"
)


def parse_related_output(text: str) -> list[RelatedNote]:
    """Read the candidate block the vault tool prints.

    The tool's contract token (``CANDIDATES_FOUND``) is parsed by the stage
    through the usual contract machinery; this reads only the detail lines, and
    ignores anything it does not recognise rather than failing the run over a
    tool that gained a field.
    """
    out: list[RelatedNote] = []
    for line in text.split("\n"):
        m = _CANDIDATE_LINE.search(line)
        if m is None:
            continue
        tags = tuple(t.strip() for t in m.group("tags").split(",") if t.strip())
        out.append(RelatedNote(
            score=int(m.group("score")),
            match=m.group("match"),
            path=m.group("path"),
            tags=tags,
        ))
    return out


def render_related_section(
    related: Sequence[RelatedNote],
    *,
    own_tags: Sequence[str] = (),
    heading: str = "Related Notes",
    limit: int = 10,
) -> str:
    """Render the section appended to the end of a note.

    Kept at ``##`` while body sections are numbered ``###`` by the formatter:
    this is apparatus rather than content, and sitting a level above the
    numbered sections is what says so.  It is added after the formatter has
    run, so it is deliberately absent from the table of contents.

    Each entry names the tags it shares, because a bare list of links does not
    say why they are there, and a reader who cannot see the reason cannot tell
    a good match from a coincidence.
    """
    if not related:
        return ""
    own = {t for t in own_tags}
    lines = [f"## {heading}", ""]
    for note in related[:limit]:
        shared = [t for t in note.tags if t in own]
        stem = note.stem
        if _LINK_HOSTILE.search(stem):
            continue
        suffix = f" — shared: {', '.join(shared)}" if shared else ""
        lines.append(f"- [[{stem}]]{suffix}")
    if len(lines) == 2:
        return ""
    lines.append("")
    return "\n".join(lines)


def _is_section_heading(line: str, heading: str) -> bool:
    """True when *line* is a heading for *heading*, however it got mangled.

    Deliberately loose about level and numbering. The section is written at
    ``##``, but a resumed run re-enters the formatter first, and
    ``apply_structure`` turns every ``## Heading`` into ``### N. Heading`` — so
    on the second pass the exact string is gone, and an exact match would
    append a second section instead of replacing the first.
    """
    stripped = line.strip()
    if not stripped.startswith("#"):
        return False
    text = re.sub(r"^\d+\.\s*", "", stripped.lstrip("#").strip())
    return text.casefold() == heading.casefold()


def strip_related_section(body: str, *, heading: str = "Related Notes") -> str:
    """Remove a previously written section, so rewriting is idempotent.

    ``--resume`` re-runs the stage on a note that may already carry one.
    Without this the note grows a second Related Notes section every time,
    which is the kind of defect that only shows up on the fourth run.

    Everything from the heading to the next heading at ``##`` or shallower is
    removed. A deeper heading inside the section (there should not be one) is
    treated as part of it.
    """
    lines = body.split("\n")
    start = next(
        (i for i, ln in enumerate(lines) if _is_section_heading(ln, heading)),
        None,
    )
    if start is None:
        return body
    end = len(lines)
    for i in range(start + 1, len(lines)):
        stripped = lines[i].lstrip()
        if stripped.startswith("#") and not stripped.startswith("###"):
            end = i
            break
    return "\n".join(lines[:start] + lines[end:]).rstrip("\n") + "\n"


def append_section(body: str, section: str) -> str:
    """Append *section* to *body* with exactly one blank line between them."""
    if not section:
        return body
    return body.rstrip("\n") + "\n\n" + section.rstrip("\n") + "\n"


__all__ = [
    "RelatedNote",
    "append_section",
    "link_first_mentions",
    "parse_related_output",
    "render_related_section",
    "resolve_entity_notes",
    "strip_related_section",
    "subject_index",
]
