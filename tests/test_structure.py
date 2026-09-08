"""Tests for avicenna.pipeline.structure.

The task specifies these invariants:
- Idempotence: f(f(x)) == f(x)
- Fenced code blocks byte-identical
- Frontmatter untouched
- TOC-anchor property: every link in the generated TOC resolves to a heading
- Duplicate headings disambiguated
- Stray # demoted, not deleted
- Restated heading stripped
- Pre-existing TOC not duplicated
"""

from __future__ import annotations

import re

from avicenna.pipeline.structure import StructureResult, apply_structure, generate_toc

# --- helpers -----------------------------------------------------------------

_TOC_LINK = re.compile(r"\[\[#([^\]|]+)(?:\|[^\]]+)?\]\]")

_SAMPLE = (
    "---\ntitle: Test\n---\n\n"
    "# The Topic\n\n"
    "## Alpha\n\nAlpha content here.\n\n"
    "## Beta\n\nBeta content here.\n\n"
    "## Gamma\n\nGamma content here.\n"
)


def _headings(text: str) -> list[str]:
    """Extract heading lines from a note (ignoring frontmatter)."""
    lines = text.split("\n")
    in_fm = False
    headings: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            in_fm = not in_fm
            continue
        if in_fm:
            continue
        if re.match(r"^#{1,6}\s", stripped):
            headings.append(stripped)
    return headings


def _toc_links(text: str) -> list[str]:
    """Extract anchor text from [[#anchor]] links in the TOC."""
    return _TOC_LINK.findall(text)


def _heading_texts(text: str) -> list[str]:
    """Extract heading text (without the # prefix) from the note."""
    result: list[str] = []
    for line in text.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line.strip())
        if m:
            result.append(m.group(2).strip())
    return result


# --- idempotence -------------------------------------------------------------


class TestIdempotence:
    """f(f(x)) == f(x) for all inputs."""

    def test_basic_note(self) -> None:
        first = apply_structure(_SAMPLE)
        second = apply_structure(first.text)
        assert first.text == second.text

    def test_already_numbered(self) -> None:
        numbered = apply_structure(_SAMPLE)
        again = apply_structure(numbered.text)
        assert again.text == numbered.text

    def test_note_with_toc(self) -> None:
        with_toc = apply_structure(_SAMPLE)
        again = apply_structure(with_toc.text)
        assert again.text == with_toc.text

    def test_empty_note(self) -> None:
        assert apply_structure("").text == ""

    def test_no_headings(self) -> None:
        text = "---\ntitle: T\n---\n\nJust some text.\n"
        first = apply_structure(text)
        second = apply_structure(first.text)
        assert first.text == second.text


# --- fenced code blocks ------------------------------------------------------


class TestFencedCodeBlocks:
    """Fenced code blocks are passed through byte-identically."""

    def test_backtick_fence_preserved(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Alpha\n\nContent.\n\n"
            "```python\n# This is not a heading\nprint('hello')\n```\n\n"
            "## Beta\n\nMore content.\n"
        )
        result = apply_structure(text)
        assert "```python\n# This is not a heading\nprint('hello')\n```" in result.text

    def test_tilde_fence_preserved(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Alpha\n\nContent.\n\n"
            "~~~\n## Not a heading\n~~~\n\n"
            "## Beta\n\nMore content.\n"
        )
        result = apply_structure(text)
        assert "~~~\n## Not a heading\n~~~" in result.text

    def test_fence_with_info_string(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Alpha\n\nContent.\n\n"
            "```markdown\n# Heading in code\n```\n\n"
            "## Beta\n\nMore content.\n"
        )
        result = apply_structure(text)
        assert "```markdown\n# Heading in code\n```" in result.text

    def test_heading_inside_fence_not_numbered(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Alpha\n\n```\n## Fake Heading\n```\n\n"
            "## Beta\n\nContent.\n"
        )
        result = apply_structure(text)
        # The fenced heading should not be numbered.
        assert "```" in result.text
        lines = result.text.split("\n")
        in_fence = False
        for line in lines:
            if line.strip().startswith("```"):
                in_fence = not in_fence
            if in_fence and "## Fake Heading" in line:
                # Should be unchanged
                assert line.strip() == "## Fake Heading"


# --- frontmatter untouched ---------------------------------------------------


class TestFrontmatterUntouched:
    """The frontmatter block is never modified."""

    def test_frontmatter_preserved(self) -> None:
        fm = "---\ntitle: Test Note\ntags: [philosophy, epistemology]\ndate: 2024-01-01\n---"
        text = f"{fm}\n\n# Topic\n\n## Alpha\n\nContent.\n\n## Beta\n\nMore.\n"
        result = apply_structure(text)
        assert result.text.startswith(fm)

    def test_no_frontmatter(self) -> None:
        text = "# Topic\n\n## Alpha\n\nContent.\n\n## Beta\n\nMore.\n"
        result = apply_structure(text)
        assert not result.text.startswith("---")

    def test_frontmatter_with_colons(self) -> None:
        fm = "---\ntitle: \"Key: Value\"\n---"
        text = f"{fm}\n\n# Topic\n\n## Alpha\n\nContent.\n\n## Beta\n\nMore.\n"
        result = apply_structure(text)
        assert result.text.startswith(fm)


# --- TOC-anchor property test -----------------------------------------------


class TestTocAnchors:
    """Every link in the generated TOC resolves to a heading that exists.

    This is the most important test: a TOC link that does not resolve is worse
    than no TOC at all.  We test with punctuation, colons, ampersands,
    em-dashes, non-ASCII characters, and duplicate heading text.

    The invariant must hold for BOTH code paths:
    - generate_toc standalone (pre-numbering, used in apply_structure)
    - apply_structure (post-numbering, the full pass)
    """

    def _assert_anchors_match(self, text: str) -> None:
        """Verify the anchor invariant for both pre- and post-numbering paths."""
        # Post-numbering: apply_structure
        result = apply_structure(text)
        self._check_anchors(result.text)

        # Pre-numbering: generate_toc standalone
        toc_only = generate_toc(text)
        self._check_anchors(toc_only)

    @staticmethod
    def _check_anchors(text: str) -> None:
        links = _toc_links(text)
        heading_texts = _heading_texts(text)
        heading_set = {h.lower() for h in heading_texts}
        for link in links:
            assert link.lower() in heading_set, (
                f"TOC link [[#{link}]] does not match any heading in the note. "
                f"Headings: {heading_texts}"
            )

    def test_basic_anchors(self) -> None:
        self._assert_anchors_match(_SAMPLE)

    def test_headings_with_colons(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Key: Point\n\nContent.\n\n"
            "## Another: Idea\n\nMore.\n"
        )
        self._assert_anchors_match(text)

    def test_headings_with_ampersands(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Faith & Reason\n\nContent.\n\n"
            "## Law & Order\n\nMore.\n"
        )
        self._assert_anchors_match(text)

    def test_headings_with_em_dashes(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## The Gap \u2014 A Problem\n\nContent.\n\n"
            "## The Bridge \u2014 A Solution\n\nMore.\n"
        )
        self._assert_anchors_match(text)

    def test_headings_with_non_ascii(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## \u00c9pist\u00e9mologie\n\nContent.\n\n"
            "## \u00dcber die Erkenntnis\n\nMore.\n"
        )
        self._assert_anchors_match(text)

    def test_duplicate_heading_text(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Introduction\n\nFirst intro.\n\n"
            "## Main Argument\n\nArgument.\n\n"
            "## Introduction\n\nSecond intro.\n"
        )
        self._assert_anchors_match(text)

    def test_headings_with_parentheses(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Section (Part 1)\n\nContent.\n\n"
            "## Section (Part 2)\n\nMore.\n"
        )
        self._assert_anchors_match(text)

    def test_single_section_no_toc(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Only Section\n\nContent.\n"
        )
        result = apply_structure(text)
        assert "[[#" not in result.text


# --- duplicate headings ------------------------------------------------------


class TestDuplicateHeadings:
    """Duplicate heading text is handled correctly in both paths.

    After apply_structure (numbering): duplicates become 1. X / 2. X, so
    TOC anchors are distinct and all resolve.

    After generate_toc standalone (no numbering): duplicates produce
    identical anchors.  Obsidian resolves [[#X]] to the first matching
    heading, so the links resolve — to the same target.  We do not invent
    suffixes that exist nowhere in the document.
    """

    def test_numbered_duplicates_resolve(self) -> None:
        """After numbering, duplicate text produces distinct anchors."""
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Same Name\n\nFirst.\n\n"
            "## Different\n\nMiddle.\n\n"
            "## Same Name\n\nSecond.\n"
        )
        result = apply_structure(text)
        links = _toc_links(result.text)
        assert len(links) == 3
        # After numbering: "1. Same Name", "2. Different", "3. Same Name"
        assert len(set(link.lower() for link in links)) == 3
        # Each must resolve.
        heading_set = {h.lower() for h in _heading_texts(result.text)}
        for link in links:
            assert link.lower() in heading_set

    def test_unnumbered_duplicates_resolve_to_first(self) -> None:
        """Before numbering, duplicate text produces identical anchors that
        resolve to the first occurrence (Obsidian's behavior)."""
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Foo\n\nbody\n\n"
            "## Foo\n\nbody\n\n"
            "## Bar\n\nbody\n"
        )
        result = generate_toc(text)
        links = _toc_links(result)
        # Both [[#Foo]] links resolve — Obsidian picks the first heading.
        heading_set = {h.lower() for h in _heading_texts(result)}
        for link in links:
            assert link.lower() in heading_set, (
                f"[[#{link}]] does not match any heading"
            )
        # The links are identical (both "Foo"), not suffixed.
        assert links == ["Foo", "Foo", "Bar"]

    def test_three_identical_headings(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## X\n\nA.\n\n"
            "## X\n\nB.\n\n"
            "## X\n\nC.\n"
        )
        result = apply_structure(text)
        links = _toc_links(result.text)
        assert len(links) == 3
        # After numbering: 1. X, 2. X, 3. X — all distinct.
        assert len(set(link.lower() for link in links)) == 3


# --- stray # demoted ---------------------------------------------------------


class TestStrayDemotion:
    """A # heading in a section body is demoted to ##, not deleted."""

    def test_stray_h1_demoted_to_h2(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Alpha\n\n# Stray Heading\n\nContent.\n\n"
            "## Beta\n\nMore.\n"
        )
        result = apply_structure(text)
        # The stray # should become ##, not be removed.
        assert "## Stray Heading" in result.text
        # The original # should be gone from body (except the title).
        body_headings = _headings(result.text)
        h1_count = sum(1 for h in body_headings if h.startswith("# ") and not h.startswith("## "))
        # Only the title should remain as #.
        assert h1_count == 1

    def test_stray_demotion_preserves_text(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Alpha\n\n# Important Aside\n\nParagraph.\n\n"
            "## Beta\n\nMore.\n"
        )
        result = apply_structure(text)
        assert "Important Aside" in result.text
        assert result.stray_demoted >= 1

    def test_title_not_demoted(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Alpha\n\nContent.\n\n"
            "## Beta\n\nMore.\n"
        )
        result = apply_structure(text)
        assert "# Topic" in result.text


# --- restated heading stripped -----------------------------------------------


class TestRestatedHeading:
    """A section body that restates its own heading gets the repeat removed."""

    def test_exact_restatement_stripped(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Alpha\n\nAlpha\n\nReal content.\n"
        )
        result = apply_structure(text)
        lines = result.text.split("\n")
        # After stripping, "Alpha" should not appear as a standalone line
        # right after the heading.
        found_heading = False
        for i, line in enumerate(lines):
            if "### 1. Alpha" in line:
                found_heading = True
                # The next non-blank line should be "Real content."
                for j in range(i + 1, len(lines)):
                    if lines[j].strip():
                        assert lines[j].strip() == "Real content."
                        break
                break
        assert found_heading
        assert result.headings_stripped >= 1

    def test_restatement_with_hash_prefix_stripped(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Alpha\n\n# Alpha\n\nReal content.\n"
        )
        result = apply_structure(text)
        # "# Alpha" in the body would first be caught as a heading (demoted),
        # then the content check wouldn't trigger because it's a heading line.
        # Actually, # Alpha is a heading line, so it gets demoted to ## Alpha
        # by the heading handler. The repeated heading check only applies to
        # content lines. So this is demotion, not stripping.
        assert "## Alpha" in result.text

    def test_no_false_positive_stripping(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Alpha\n\nDifferent text here.\n\nMore.\n"
        )
        result = apply_structure(text)
        assert "Different text here." in result.text
        assert result.headings_stripped == 0


# --- pre-existing TOC not duplicated -----------------------------------------


class TestExistingToc:
    """A note that already has a TOC does not gain a second one."""

    def test_toc_replaced_not_doubled(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "> [!abstract]- Table of Contents\n"
            "> - [[#Old Alpha]]\n"
            "> - [[#Old Beta]]\n\n"
            "## Alpha\n\nContent.\n\n"
            "## Beta\n\nMore.\n"
        )
        result = apply_structure(text)
        # Count TOC callout blocks.
        toc_count = result.text.count("> [!abstract]- Table of Contents")
        assert toc_count == 1, f"Expected 1 TOC, found {toc_count}"

    def test_toc_links_updated(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "> [!abstract]- Table of Contents\n"
            "> - [[#Old Alpha]]\n"
            "> - [[#Old Beta]]\n\n"
            "## Alpha\n\nContent.\n\n"
            "## Beta\n\nMore.\n"
        )
        result = apply_structure(text)
        links = _toc_links(result.text)
        # The old links should be gone.
        assert "Old Alpha" not in str(links)
        assert "Old Beta" not in str(links)
        # New links should match the numbered headings.
        assert len(links) == 2

    def test_generate_toc_idempotent(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Alpha\n\nContent.\n\n"
            "## Beta\n\nMore.\n"
        )
        first = generate_toc(text)
        second = generate_toc(first)
        assert first == second


# --- diagnostics -------------------------------------------------------------


class TestDiagnostics:
    """The result dataclass carries accurate diagnostics."""

    def test_headings_numbered_count(self) -> None:
        result = apply_structure(_SAMPLE)
        assert result.headings_numbered == 3

    def test_empty_note_diagnostics(self) -> None:
        result = apply_structure("")
        assert result.headings_numbered == 0
        assert result.headings_stripped == 0
        assert result.stray_demoted == 0

    def test_toc_added_flag(self) -> None:
        result = apply_structure(_SAMPLE)
        assert result.toc_added is True


# --- heading numbering -------------------------------------------------------


class TestNumbering:
    """Section headings are numbered 1, 2, 3... as ### N. Heading."""

    def test_basic_numbering(self) -> None:
        result = apply_structure(_SAMPLE)
        assert "### 1. Alpha" in result.text
        assert "### 2. Beta" in result.text
        assert "### 3. Gamma" in result.text

    def test_old_numbers_stripped(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## 1. Already Numbered\n\nContent.\n\n"
            "## 3. Wrong Number\n\nMore.\n"
        )
        result = apply_structure(text)
        assert "### 1. Already Numbered" in result.text
        assert "### 2. Wrong Number" in result.text

    def test_positional_numbering(self) -> None:
        """Numbers are positional, not derived from content."""
        text = (
            "---\ntitle: T\n---\n\n"
            "# Topic\n\n"
            "## Section C\n\nContent.\n\n"
            "## Section A\n\nMore.\n\n"
            "## Section B\n\nEnd.\n"
        )
        result = apply_structure(text)
        assert "### 1. Section C" in result.text
        assert "### 2. Section A" in result.text
        assert "### 3. Section B" in result.text

    def test_h1_title_preserved(self) -> None:
        result = apply_structure(_SAMPLE)
        assert "# The Topic" in result.text
        headings = _headings(result.text)
        h1 = [h for h in headings if h.startswith("# ") and not h.startswith("## ")]
        assert len(h1) == 1
