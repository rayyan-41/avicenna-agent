"""Transition generation: the weaver becomes a transition-only stage.

After the 2026-09-08 defect where the whole-note weaver round-trip destroyed
72% of a 9,000-word note, the weaver's role was narrowed to generating one
transition sentence per section.  It never sees the body it cannot damage and
never returns the body.  This module contains every pure function involved:
skeleton extraction, prompt construction, response parsing, validation, and
splice.  No provider, no I/O, no RunContext.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


# ---------------------------------------------------------------------------
# Stopwords for relevance checking
# ---------------------------------------------------------------------------
# Small, high-frequency English words that carry no topical signal.  Used only
# to filter the overlap check so that "the" and "of" do not count as evidence
# that a transition is on-topic.

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "shall", "should", "may", "might", "must", "can", "could", "this",
    "that", "these", "those", "it", "its", "i", "me", "my", "we", "our",
    "you", "your", "he", "his", "she", "her", "they", "them", "their",
    "what", "which", "who", "whom", "not", "no", "so", "if", "then",
    "than", "too", "very", "just", "about", "above", "after", "again",
    "all", "also", "any", "as", "before", "between", "both", "each",
    "few", "more", "most", "other", "some", "such", "into", "over",
    "own", "same", "up", "out", "only",
})


def _significant_words(text: str) -> set[str]:
    """Lowercase, stopword-filtered content words from *text*."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


# ---------------------------------------------------------------------------
# Sentence extraction
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """Split *text* into sentences.  Conservative: splits on . ! ? followed
    by whitespace or end-of-string, not on decimal points or abbreviations.
    """
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _first_last_sentences(paragraph: str) -> tuple[str, str]:
    """Return (first_sentence, last_sentence) of a non-empty paragraph."""
    sentences = _split_sentences(paragraph)
    if not sentences:
        return paragraph.strip(), paragraph.strip()
    if len(sentences) == 1:
        return sentences[0], sentences[0]
    return sentences[0], sentences[-1]


# ---------------------------------------------------------------------------
# Skeleton extraction
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SectionSkeleton:
    """The visible structure of one section, as seen by the weaver."""
    heading: str
    #: ``(first_sentence, last_sentence)`` for each paragraph in the section.
    paragraph_bookends: list[tuple[str, str]]


@dataclass(frozen=True)
class NoteSkeleton:
    """A reduced representation of the assembled note, enough for the weaver
    to write transitions without seeing the body."""
    topic: str
    sections: list[SectionSkeleton]


# ---------------------------------------------------------------------------
# Fenced code blocks
# ---------------------------------------------------------------------------
# A `## ` inside a fenced block is sample text, not a section.  Without this,
# a note whose body quotes Markdown -- and this program writes notes about
# writing -- had its fenced example counted as a section, which shifted every
# later section's index by one and spliced a transition *inside the code
# block*.  Every other pass over a note in this codebase is fence-aware
# (structure.apply_structure, normalise_markdown); this one was not.

_FENCE_LINE = re.compile(r"^\s*(`{3,}|~{3,})")


def _section_heading_lines(lines: Sequence[str]) -> list[int]:
    """Indices of the lines that open a section, skipping fenced regions.

    A fence is closed only by a fence of the same character, so a tilde fence
    containing a backtick fence stays open, as Markdown requires.
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
        if not fence_char and line.startswith("## "):
            out.append(i)
    return out


def extract_skeleton(note_text: str, topic: str) -> NoteSkeleton:
    """Build a skeleton from the assembled note.

    Strips frontmatter and the top-level heading, then splits on ``## ``
    headings.  For each section, records the heading and the first/last
    sentence of every paragraph.
    """
    # Strip frontmatter
    body = note_text
    if body.lstrip().startswith("---"):
        m = re.match(r"---\r?\n.*?\r?\n---\r?\n?", body, re.DOTALL)
        if m:
            body = body[m.end():]

    # Strip the top-level heading and any blank lines after it
    body = re.sub(r"^#[^#].*\n*", "", body, count=1)

    # Split on ## headings, ignoring any that sit inside a fenced block.
    lines = body.split("\n")
    starts = _section_heading_lines(lines)
    sections: list[SectionSkeleton] = []
    for n, start in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else len(lines)
        heading = lines[start][3:].strip()
        if not heading:
            continue
        section_body = "\n".join(lines[start + 1:stop]).strip()
        bookends: list[tuple[str, str]] = []
        for para in section_body.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            fl = _first_last_sentences(para)
            bookends.append(fl)
        sections.append(SectionSkeleton(heading=heading, paragraph_bookends=bookends))

    return NoteSkeleton(topic=topic, sections=sections)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_transition_prompt(skeleton: NoteSkeleton) -> str:
    """Build the prompt the weaver model receives.

    The model sees the topic, every heading in order, and for each section the
    first and last sentence of each paragraph — enough to write transitions,
    not enough to regurgitate the note.
    """
    parts: list[str] = [
        f"Topic: {skeleton.topic}",
        "",
        "Below is the skeleton of a note — the topic, every heading in order, "
        "and for each section the first and last sentence of each paragraph.  "
        "Your job is to write ONE transition sentence for each section.  A "
        "transition orients the reader: it connects what came before to what "
        "this section is about.",
        "",
        "Rules:",
        "- Return exactly one transition per section, numbered, one per line.",
        "- Each transition must be a single line with no line breaks inside it.",
        "- Section 1's transition orients the reader from the topic into the "
        "first section.",
        "- Transitions are prose: no wikilinks, no headings, no lists, no "
        "code fences.",
        "",
        "Format: one numbered line per section, like this:",
        "1. <transition for section 1>",
        "2. <transition for section 2>",
        "3. <transition for section 3>",
        "",
    ]
    for i, sec in enumerate(skeleton.sections, 1):
        parts.append(f"Section {i}: ## {sec.heading}")
        for j, (first, last) in enumerate(sec.paragraph_bookends, 1):
            if first == last:
                parts.append(f"  paragraph {j}: \"{first}\"")
            else:
                parts.append(f"  paragraph {j}: \"{first}\" ... \"{last}\"")
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

# Matches a numbered transition line: "1. Some text here"
_TRANSITION_LINE = re.compile(r"^\s*(\d+)\.\s+(.+)$")


@dataclass(frozen=True)
class ParsedTransition:
    """One parsed transition line from the model's response."""
    index: int  # 1-based section index
    text: str


def parse_transitions(response: str) -> list[ParsedTransition]:
    """Parse a numbered transition list from the model response.

    Returns one ``ParsedTransition`` per recognisable numbered line.  Lines
    that do not match ``N. text`` are skipped — the model may add preamble or
    postamble prose that we discard rather than fail on.
    """
    results: list[ParsedTransition] = []
    for line in response.splitlines():
        m = _TRANSITION_LINE.match(line)
        if m:
            idx = int(m.group(1))
            text = m.group(2).strip()
            results.append(ParsedTransition(index=idx, text=text))
    return results


# ---------------------------------------------------------------------------
# Guard / validation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TransitionVerdict:
    """Result of validating one transition."""
    accepted: bool
    reason: str = ""


def validate_transition(
    text: str,
    *,
    section_heading: str,
    preceding_heading: str,
    note_topic: str,
) -> TransitionVerdict:
    """Validate a single transition against the guard rules.

    Rules are documented where they are enforced:

    1. **Length sanity (lenient).** A transition that is obviously not a
       sentence — fewer than 4 words or more than 80 — is dropped.  The
       band is intentionally wide: models vary in style and that is not a
       defect.

    2. **Structural inertness.** Transitions are prose.  A line break, ``[[``,
       a leading ``#``/``-``/``>``/digit-dot, or a code fence inside a
       transition means the model hallucinated structure and the line is
       dropped.  (A ``[[wikilink]]`` in weaver prose is a real observed
       failure.)

    3. **Topic relevance (strict).** This is the check that matters — the
       observed failure was off-topic injection.  A transition must share
       significant terms (stopword-filtered, case-folded) with the heading
       it precedes, the preceding heading, or the note topic.  A transition
       sharing nothing with any of those is dropped.
    """
    # Rule 1: length sanity
    word_count = len(text.split())
    if word_count < 4:
        return TransitionVerdict(accepted=False, reason=f"too short ({word_count} words)")
    if word_count > 80:
        return TransitionVerdict(accepted=False, reason=f"too long ({word_count} words)")

    # Rule 2: structural inertness
    if "\n" in text:
        return TransitionVerdict(accepted=False, reason="contains line break")
    if "[[" in text:
        return TransitionVerdict(accepted=False, reason="contains wikilink")
    stripped = text.lstrip()
    if stripped.startswith("#"):
        return TransitionVerdict(accepted=False, reason="starts with heading marker")
    if stripped.startswith("-"):
        return TransitionVerdict(accepted=False, reason="starts with list marker")
    if stripped.startswith(">"):
        return TransitionVerdict(accepted=False, reason="starts with blockquote")
    if re.match(r"^\d+\.", stripped):
        return TransitionVerdict(accepted=False, reason="starts with numbered list")
    if stripped.startswith("```") or stripped.startswith("~~~"):
        return TransitionVerdict(accepted=False, reason="starts with code fence")

    # Rule 3: topic relevance
    transition_words = _significant_words(text)
    heading_words = _significant_words(section_heading)
    preceding_words = _significant_words(preceding_heading)
    topic_words = _significant_words(note_topic)

    # At least one significant word must overlap with one of the three
    # reference sets.
    if not transition_words:
        return TransitionVerdict(
            accepted=False, reason="no significant words in transition")
    if (transition_words & heading_words
            or transition_words & preceding_words
            or transition_words & topic_words):
        return TransitionVerdict(accepted=True)

    return TransitionVerdict(
        accepted=False,
        reason="no overlap with heading, preceding heading, or topic")


# ---------------------------------------------------------------------------
# Splice: pure function over note text
# ---------------------------------------------------------------------------

def splice_transitions(
    note_text: str,
    transitions: dict[int, str],
) -> str:
    """Insert transition sentences into the assembled note.

    *transitions* maps 1-based section index to a transition sentence.
    For section *k* the transition is placed after the ``## `` heading,
    separated by exactly one blank line on each side:

    ``## Heading\\n\\n<transition>\\n\\n<section body>``

    Section 1 gets a transition too — it orients the reader from the topic
    into the first section.  Sections without a transition in the dict are
    left unchanged.
    """
    lines = note_text.split("\n")
    # Section starts are computed once, fence-aware, so the indices here agree
    # with the ones extract_skeleton numbered the transitions against.  Walking
    # the lines and matching `## ` inline (the previous approach) counted
    # headings inside fenced code and spliced transitions into the code block.
    starts = set(_section_heading_lines(lines))
    result: list[str] = []
    section_idx = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        result.append(line)
        if i in starts:
            section_idx += 1
            transition = transitions.get(section_idx)
            if transition is not None:
                # The assembly always emits one blank line after a heading;
                # consume it so the splice does not add a second.  When it is
                # absent, the blank written below still separates the
                # transition from the body.
                if i + 1 < len(lines) and lines[i + 1].strip() == "":
                    i += 1
                result.append("")
                result.append(transition)
                result.append("")
        i += 1
    return "\n".join(result)
