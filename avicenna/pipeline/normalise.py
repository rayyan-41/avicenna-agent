"""Post-assembly Markdown normalisation.

Collapses the kind of structural damage an over-eager model introduces:
excessive horizontal rules, rules adjacent to headings, excessive blank
lines, and missing blank lines around headings.

Rules:

- Consecutive horizontal rules (``---``, ``***``, ``___``, spaced forms
  like ``- - -``) collapse to a single isolated rule.
- A rule directly adjacent to a heading (before or after) is removed.
- Consecutive blank lines collapse to one.
- A blank line is ensured before and after every heading.
- Trailing whitespace is stripped on every line.

Hard constraints:

- Fenced code blocks (````` and ``~~~``) are passed through byte-identically.
- The frontmatter block (leading ``---`` / ``---``) is untouched.
- The transformation is idempotent: ``f(f(x)) == f(x)``.
- Word count is not materially changed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


_HORIZONTAL_RULE = re.compile(
    r"^\s*(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})\s*$"
)
_HEADING = re.compile(r"^#{1,6}\s")
_FENCE = re.compile(r"^(`{3,}|~{3,})([a-zA-Z0-9_-]*)\s*$")


@dataclass(frozen=True)
class NormaliseResult:
    """Return value from :func:`normalise_markdown`."""

    text: str
    rules_removed: int = 0
    consecutive_rules_collapsed: int = 0
    adjacent_rules_removed: int = 0


def _is_hr(line: str) -> bool:
    return bool(_HORIZONTAL_RULE.match(line.strip()))


def _is_fence(line: str) -> tuple[str, str] | None:
    m = _FENCE.match(line.strip())
    return (m.group(1)[0], m.group(2)) if m else None


def normalise_markdown(text: str) -> NormaliseResult:
    """Normalise *text* and return the result with diagnostics.

    The frontmatter block is preserved untouched.  Fenced code blocks
    (backtick or tilde fences, with or without info strings) are passed
    through byte-identically.
    """
    if not text:
        return NormaliseResult(text=text)

    lines = text.split("\n")

    # --- split off frontmatter ------------------------------------------------
    fm_lines: list[str] = []
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_lines = lines[: i + 1]
                body_start = i + 1
                break

    body_lines = lines[body_start:]

    # --- normalise the body ---------------------------------------------------
    # Strategy: single pass with a rule buffer.  Rules are accumulated and
    # only flushed when the next non-rule, non-blank line is seen, so we
    # know what sits on both sides.
    out: list[str] = []
    in_fence = False
    fence_char = ""
    pending_blank = False
    last_non_blank_was_heading = False
    rule_buffer_start_was_heading = False
    rule_count = 0
    total_hr = 0
    adjacent_removed = 0
    consecutive_collapsed = 0

    def flush_blank() -> None:
        nonlocal pending_blank
        if pending_blank:
            out.append("")
            pending_blank = False

    def flush_rules() -> None:
        """Emit the buffered rules as a single ``---``."""
        nonlocal rule_count, consecutive_collapsed
        if rule_count == 0:
            return
        if rule_count > 1:
            consecutive_collapsed += rule_count - 1
        flush_blank()
        out.append("---")
        rule_count = 0

    def discard_rules(blank_before: bool) -> None:
        """Drop the buffered rules (they were adjacent to a heading)."""
        nonlocal rule_count, adjacent_removed
        if rule_count == 0:
            return
        adjacent_removed += rule_count
        if blank_before:
            flush_blank()
        else:
            pass  # pending_blank discarded too
        rule_count = 0

    for line in body_lines:
        stripped = line.rstrip()
        ls = stripped.lstrip()

        # --- fence tracking ---------------------------------------------------
        if not in_fence:
            fm = _is_fence(stripped)
            if fm:
                flush_rules()
                flush_blank()
                in_fence = True
                fence_char = fm[0]
                out.append(stripped)
                last_non_blank_was_heading = False
                continue
        else:
            out.append(stripped)
            fm = _is_fence(stripped)
            if fm and fm[0] == fence_char:
                in_fence = False
                fence_char = ""
                last_non_blank_was_heading = False
            continue

        # --- blank line -------------------------------------------------------
        if not ls:
            pending_blank = True
            continue

        # --- heading ----------------------------------------------------------
        if _HEADING.match(ls):
            if rule_count > 0:
                # Rules immediately before a heading → remove.
                # Insert a blank only if there was content (not a heading)
                # before the rules.
                discard_rules(blank_before=not rule_buffer_start_was_heading)
            if out and out[-1].strip():
                out.append("")
            out.append(stripped)
            last_non_blank_was_heading = True
            pending_blank = False
            continue

        # --- horizontal rule --------------------------------------------------
        if _is_hr(stripped):
            total_hr += 1
            if rule_count == 0:
                rule_buffer_start_was_heading = last_non_blank_was_heading
            rule_count += 1
            pending_blank = False
            continue

        # --- regular content --------------------------------------------------
        if rule_count > 0:
            if last_non_blank_was_heading:
                # Rule(s) after a heading, before content → remove.
                discard_rules(blank_before=False)
            else:
                # Rule(s) between content → keep as one rule.
                flush_rules()
        # Ensure blank line after heading before content.
        #
        # Clearing pending_blank matters: when the source ALREADY had a blank
        # line after the heading, that blank is sitting in pending_blank while
        # out[-1] is the heading itself.  Without the reset the ensured blank
        # and the pending one were both emitted, so every correctly-spaced
        # heading gained a second blank line on each pass -- and a heading with
        # no blank after it gained one on the first pass and a second on the
        # next, which is why this function was not idempotent.  The blank we
        # write here IS the pending one; it must not be written twice.
        if last_non_blank_was_heading and out and out[-1].strip():
            out.append("")
            pending_blank = False
        flush_blank()
        out.append(stripped)
        last_non_blank_was_heading = False

    # --- trailing state -------------------------------------------------------
    if rule_count > 0:
        if last_non_blank_was_heading:
            discard_rules(blank_before=False)
        else:
            flush_rules()

    # --- count surviving rules ------------------------------------------------
    rules_survived = sum(1 for l in out if _is_hr(l))
    rules_removed = total_hr - rules_survived
    if rules_removed < 0:
        rules_removed = 0
    adjacent_removed = max(0, rules_removed - consecutive_collapsed)

    # --- strip trailing whitespace and reassemble -----------------------------
    norm_lines = [l.rstrip() for l in out]

    result_lines = fm_lines + norm_lines
    result = "\n".join(result_lines)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"

    return NormaliseResult(
        text=result,
        rules_removed=rules_removed,
        consecutive_rules_collapsed=consecutive_collapsed,
        adjacent_rules_removed=adjacent_removed,
    )
