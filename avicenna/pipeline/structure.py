"""Deterministic note structure: numbered headings, TOC, heading cleanup.

Replaces two model round-trips (formatter, TOC tool) with pure Python.
No LLM client is imported anywhere in this module.  The formatter stage
previously delegated the entire note to a ``formatter`` agent; the TOC stage
shelled out to a PowerShell ``generate_toc.ps1``.  Both are now deterministic.

The defect this module exists to prevent: a model asked to number headings,
generate a TOC, or clean up stray headings treats these as editorial choices
and can rephrase, reorder, or skip them.  They are mechanical operations —
positional numbering, regex matching, callout generation — and ten lines of
Python are faster, cheaper, and more reliable than a whole-note round-trip.

Hard constraints:

- The frontmatter block (leading ``---`` / ``---``) is untouched.
- Fenced code blocks (````` and ``~~~``) are passed through byte-identically.
- The transformation is idempotent: ``f(f(x)) == f(x)``.
- Every link in the generated TOC resolves to a heading that exists in the note.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- heading patterns --------------------------------------------------------
# Section headings are ## level (as emitted by _assemble).  The title is #.
# Stray top-level headings in body text are # but not the title.

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})([a-zA-Z0-9_-]*)\s*$")

# The frontmatter regex must match stages._FRONTMATTER exactly — both are
# anchored at \A and use non-greedy matching to the first closing ---.
_FRONTMATTER = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---\r?\n?", re.DOTALL)

# A numbered heading prefix like "1. " or "12. ".
_NUMBERED_PREFIX = re.compile(r"^\d+\.\s+")

# Obsidian callout opening: "> [!type]- Title" or "> [!type] Title".
_CALLOUT_OPEN = re.compile(r"^>\s*\[![\w]+\].*$")

# A TOC wikilink entry: "> - [[#anchor|display]]" or "> - [[#anchor]]".
_TOC_LINK = re.compile(r"\[\[#([^\]|]+)(?:\|[^\]]+)?\]\]")


@dataclass(frozen=True)
class StructureResult:
    """Return value from :func:`apply_structure`."""

    text: str
    headings_numbered: int = 0
    headings_stripped: int = 0
    stray_demoted: int = 0
    subheadings_demoted: int = 0
    toc_added: bool = False


# --- frontmatter splitting ---------------------------------------------------
# Duplicated from stages._split_frontmatter to avoid a circular import:
# stages imports from structure, not the other way around.  Both match the
# same regex.

def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(frontmatter_block, body)``.  The block is ``''`` when absent."""
    match = _FRONTMATTER.match(text)
    if match is None:
        return "", text
    return match.group(0), text[match.end():]


# --- heading identification --------------------------------------------------

def _is_fence(line: str) -> tuple[str, str] | None:
    """Return (fence_char, info_string) if *line* opens a fenced code block."""
    m = _FENCE_RE.match(line.strip())
    return (m.group(1)[0], m.group(2)) if m else None


def _is_section_heading(level: str, txt: str) -> bool:
    """Check if a heading is a section heading in either pre- or post-numbering form.

    Pre-numbering (from _assemble): ``## Heading``.
    Post-numbering (from apply_structure): ``### N. Heading``.
    """
    if level == "##":
        return True
    if level == "###" and _NUMBERED_PREFIX.match(txt):
        return True
    return False


def _strip_numbered_prefix(text: str) -> str:
    """Strip a leading ``N. `` number prefix from heading text.

    ``1. The Epistemic Gap`` -> ``The Epistemic Gap``.
    ``Already Clean`` -> ``Already Clean``.
    """
    return _NUMBERED_PREFIX.sub("", text)


def _parse_headings(body_lines: list[str]) -> list[tuple[int, str, str]]:
    """Extract headings from body lines, respecting fenced code blocks.

    Returns list of ``(line_index, level_dots, heading_text)`` where
    *level_dots* is ``#``, ``##``, etc. and *heading_text* is the text
    without the marker.
    """
    headings: list[tuple[int, str, str]] = []
    in_fence = False
    fence_char = ""
    for i, line in enumerate(body_lines):
        stripped = line.rstrip()
        if not in_fence:
            fm = _is_fence(stripped)
            if fm:
                in_fence = True
                fence_char = fm[0]
                continue
        else:
            fm = _is_fence(stripped)
            if fm and fm[0] == fence_char:
                in_fence = False
                fence_char = ""
            continue
        m = _HEADING_RE.match(stripped)
        if m:
            headings.append((i, m.group(1), m.group(2).strip()))
    return headings


# --- TOC generation ----------------------------------------------------------

def _find_toc_range(body_lines: list[str]) -> tuple[int, int] | None:
    """Find an existing TOC callout in the body.

    Returns ``(start_index, end_index)`` (inclusive) if a callout block
    containing ``[[#`` wikilinks is found, else ``None``.
    """
    i = 0
    while i < len(body_lines):
        stripped = body_lines[i].rstrip()
        if _CALLOUT_OPEN.match(stripped):
            start = i
            has_toc_links = False
            while i < len(body_lines):
                line = body_lines[i].rstrip()
                if not line.startswith(">") and line.strip():
                    break
                if _TOC_LINK.search(line):
                    has_toc_links = True
                i += 1
            if has_toc_links:
                return (start, i - 1)
        else:
            i += 1
    return None


def generate_toc(text: str) -> str:
    """Generate or replace a TOC callout in *text*.

    The TOC is an Obsidian callout placed after the frontmatter and the
    ``#`` title, before the first section heading.  If a TOC callout
    already exists it is replaced.

    Identifies section headings in both pre-numbering (``## Heading``) and
    post-numbering (``### N. Heading``) forms, so it works correctly when
    called from :func:`apply_structure` (after numbering, where duplicate
    text produces unique anchors like ``1. X`` / ``2. X``).

    Duplicate heading text in the unnumbered form produces identical
    anchors.  Obsidian resolves ``[[#Foo]]`` to the *first* matching
    heading, so both entries resolve — to the same target.  We do not
    invent suffixes like ``Foo-1``: those anchors exist nowhere in the
    document and produce links to nothing, which is worse than two links
    to the same place.
    """
    fm, body = _split_frontmatter(text)
    lines = body.split("\n")

    # Find the title line (# heading).
    title_idx = -1
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line.strip())
        if m and m.group(1) == "#":
            title_idx = i
            break

    # Find all section-level headings.
    headings = _parse_headings(lines)
    section_headings = [
        (idx, lvl, txt) for idx, lvl, txt in headings
        if _is_section_heading(lvl, txt)
    ]
    if len(section_headings) < 2:
        return text

    # Build the TOC callout lines.
    toc_lines: list[str] = ["> [!abstract]- Table of Contents"]
    for _idx, _lvl, txt in section_headings:
        toc_lines.append(f"> - [[#{txt}]]")

    toc_block = "\n".join(toc_lines)

    # Remove any existing TOC callout.
    body_lines = body.split("\n")
    toc_range = _find_toc_range(body_lines)
    if toc_range is not None:
        start, end = toc_range
        while end + 1 < len(body_lines) and not body_lines[end + 1].strip():
            end += 1
        body_lines = body_lines[:start] + body_lines[end + 1:]

    # Insert the new TOC after the title (and its trailing blank line).
    insert_at = 0
    if title_idx >= 0:
        insert_at = title_idx + 1
        while insert_at < len(body_lines) and not body_lines[insert_at].strip():
            insert_at += 1

    new_body_lines = (
        body_lines[:insert_at]
        + [toc_block, ""]
        + body_lines[insert_at:]
    )

    result = fm + "\n".join(new_body_lines)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result


# --- full structural pass ----------------------------------------------------

def apply_structure(text: str) -> StructureResult:
    """Apply all structural transformations to *text*.

    Operations, in order:

    1. Number section headings (``## Heading`` -> ``### N. Heading``).
    2. Demote the sub-headings underneath them by one level, so promoting a
       section does not make it a sibling of its own sub-headings.
    3. Strip repeated headings (section body restating its own heading).
    4. Demote stray top-level headings (``#`` in body -> ``##``).
    5. Generate the TOC callout, listing sections only.

    The TOC deliberately lists sections and not sub-headings: a ten-thousand
    word note has enough of the latter to bury the former.

    The frontmatter block and fenced code blocks are untouched.
    """
    if not text:
        return StructureResult(text=text)

    fm, body = _split_frontmatter(text)
    lines = body.split("\n")

    headings = _parse_headings(lines)
    if not headings:
        return StructureResult(text=text)

    # --- pass 1: identify title and section headings --------------------------
    title_idx: int | None = None
    section_indices: list[int] = []
    for hi, (_line_idx, level, _txt) in enumerate(headings):
        if level == "#" and title_idx is None:
            title_idx = hi
        elif level == "##":
            section_indices.append(hi)

    # --- pass 2: build the output ---------------------------------------------
    out: list[str] = []
    in_fence = False
    fence_char = ""
    headings_numbered = 0
    headings_stripped = 0
    stray_demoted = 0
    subheadings_demoted = 0
    section_counter = 0

    # Track which section we are inside (None = before first section).
    current_section_text: str | None = None
    first_content_seen = False

    # Build a lookup from line index to heading info.
    heading_line_map: dict[int, tuple[int, str, str]] = {}
    for hi, (line_idx, level, txt) in enumerate(headings):
        heading_line_map[line_idx] = (hi, level, txt)

    for i, line in enumerate(lines):
        stripped = line.rstrip()

        # --- fence tracking ---
        if not in_fence:
            fm_match = _is_fence(stripped)
            if fm_match:
                in_fence = True
                fence_char = fm_match[0]
                out.append(stripped)
                continue
        else:
            out.append(stripped)
            fm_match = _is_fence(stripped)
            if fm_match and fm_match[0] == fence_char:
                in_fence = False
                fence_char = ""
            continue

        # --- heading line ---
        if i in heading_line_map:
            hi, level, txt = heading_line_map[i]

            if hi == title_idx:
                current_section_text = None
                first_content_seen = False
                out.append(stripped)
                continue

            if hi in section_indices:
                section_counter += 1
                clean = _strip_numbered_prefix(txt)
                new_heading = f"### {section_counter}. {clean}"
                if new_heading != stripped:
                    headings_numbered += 1
                out.append(new_heading)
                current_section_text = clean.lower()
                first_content_seen = False
                continue

            # --- sub-heading under a section --------------------------------
            # Numbering promotes `## Section` to `### N. Section`, which lands
            # it on the level the section agents' own sub-headings already
            # occupy.  A live note came out with nineteen `###` headings of
            # which eleven were sections: in Obsidian's outline a sub-point sat
            # as a sibling of the sections it belonged under.  Promoting the
            # parent has to push the children down with it.
            #
            # Guarded on `section_indices` so the pass stays idempotent.  A
            # second application sees no `## ` headings left to promote, so it
            # demotes nothing — without the guard it would walk every
            # sub-heading one level deeper on each call.  Level 6 is Markdown's
            # floor, so a `######` sub-heading stays where it is rather than
            # becoming body text.
            if (
                section_indices
                and len(level) >= 3
                and current_section_text is not None
            ):
                new_level = "#" * min(len(level) + 1, 6)
                if new_level != level:
                    subheadings_demoted += 1
                out.append(f"{new_level} {txt}")
                continue

            # Stray top-level heading in body — demote, not delete.
            if level == "#" and current_section_text is not None:
                new_line = re.sub(r"^#\s+", "## ", stripped, count=1)
                stray_demoted += 1
                out.append(new_line)
                continue

            # Other headings in body — leave alone.
            out.append(stripped)
            continue

        # --- content line ---
        if current_section_text is not None and not first_content_seen:
            if not stripped:
                out.append(stripped)
                continue
            # First non-blank content in this section: check for repeat.
            line_text = stripped.lstrip("#").strip().lower()
            if line_text == current_section_text:
                headings_stripped += 1
                first_content_seen = True
                continue
            first_content_seen = True

        # Demote stray top-level headings in body content.
        if (
            current_section_text is not None
            and stripped.startswith("# ")
            and not stripped.startswith("## ")
        ):
            stripped = re.sub(r"^#\s+", "## ", stripped, count=1)
            stray_demoted += 1

        out.append(stripped)

    result_body = "\n".join(out)
    result_text = fm + result_body if fm else result_body

    # --- generate TOC ---------------------------------------------------------
    result_text = generate_toc(result_text)

    # Preserve trailing newline.
    if text.endswith("\n") and not result_text.endswith("\n"):
        result_text += "\n"

    return StructureResult(
        text=result_text,
        headings_numbered=headings_numbered,
        headings_stripped=headings_stripped,
        stray_demoted=stray_demoted,
        subheadings_demoted=subheadings_demoted,
        toc_added=True,
    )
