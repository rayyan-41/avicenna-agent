"""Tests for avicenna.pipeline.normalise."""

from __future__ import annotations

from avicenna.pipeline.normalise import NormaliseResult, normalise_markdown


class TestHorizontalRuleCollapse:
    """91-rule input reduces to a sane number; every ## heading survives."""

    def test_massive_rule_input(self) -> None:
        """A note resembling the observed shape: 11 headings, 91 rules."""
        lines: list[str] = [
            "---",
            "title: Test Note",
            "tags: [philosophy]",
            "---",
            "",
            "# Test Note",
            "",
        ]
        for i in range(1, 12):
            lines.append("---")
            lines.append("")
            lines.append(f"## Heading {i}")
            lines.append("")
            lines.append(f"Content of section {i}.")
            lines.append("")
            lines.append("---")
            lines.append("")
            for j in range(1, 4):
                lines.append("---")
                lines.append("")
                lines.append(f"Subsection {i}.{j} content.")
                lines.append("")
                lines.append("---")
                lines.append("")
        lines.append("---")

        text = "\n".join(lines)
        rule_count = sum(1 for l in lines if l.strip() in ("---", "***", "___"))
        assert rule_count >= 80

        result = normalise_markdown(text)
        surviving_rules = sum(
            1 for l in result.text.split("\n") if l.strip() in ("---", "***", "___")
        )
        # Adjacent-to-heading rules are removed; subsection rules survive.
        assert surviving_rules <= 40
        assert result.rules_removed >= 50

    def test_headings_survive(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Title\n\n"
            "---\n\n"
            "## Alpha\n\nContent.\n\n"
            "---\n\n"
            "## Beta\n\nContent.\n\n"
            "---\n\n"
            "## Gamma\n\nContent.\n"
        )
        result = normalise_markdown(text)
        assert result.text.count("## Alpha") == 1
        assert result.text.count("## Beta") == 1
        assert result.text.count("## Gamma") == 1


class TestAdjacentAndIsolated:
    """A rule immediately after a heading is removed; an isolated rule
    mid-prose survives."""

    def test_rule_after_heading_removed(self) -> None:
        text = "# Title\n\n## Section\n\n---\n\nSome text.\n"
        result = normalise_markdown(text)
        lines = result.text.split("\n")
        rule_lines = [l for l in lines if l.strip() in ("---", "***", "___")]
        assert len(rule_lines) == 0

    def test_rule_before_heading_removed(self) -> None:
        text = "Some text.\n\n---\n\n## Section\n\nContent.\n"
        result = normalise_markdown(text)
        lines = result.text.split("\n")
        rule_lines = [l for l in lines if l.strip() in ("---", "***", "___")]
        assert len(rule_lines) == 0

    def test_isolated_rule_mid_prose_survives(self) -> None:
        text = "First paragraph.\n\n---\n\nSecond paragraph.\n"
        result = normalise_markdown(text)
        assert "---" in result.text
        lines = result.text.split("\n")
        rule_lines = [l for l in lines if l.strip() == "---"]
        assert len(rule_lines) == 1


class TestBlankLineCollapse:
    """Consecutive blank lines collapse to one."""

    def test_multiple_blanks_collapse(self) -> None:
        text = "First.\n\n\n\n\nSecond.\n"
        result = normalise_markdown(text)
        assert "\n\n\n" not in result.text
        assert "First." in result.text
        assert "Second." in result.text

    def test_blanks_around_rules_collapse(self) -> None:
        text = "First.\n\n\n---\n\n\nSecond.\n"
        result = normalise_markdown(text)
        assert "\n\n\n" not in result.text
        assert "---" in result.text


class TestFencedCodeBlockUntouched:
    """A fenced code block containing ---, *** and blank lines is
    byte-identical after normalisation."""

    def test_backtick_fence(self) -> None:
        code = "---\n\n***\n\n\n___\n"
        text = f"# Title\n\n```python\n{code}```\n"
        result = normalise_markdown(text)
        start = result.text.index("```python")
        end = result.text.index("```", start + 3) + 3
        assert result.text[start:end] == f"```python\n{code}```"

    def test_tilde_fence_with_info(self) -> None:
        code = "---\n\n***\n"
        text = f"# Title\n\n~~~json\n{code}~~~\n"
        result = normalise_markdown(text)
        start = result.text.index("~~~json")
        end = result.text.index("~~~", start + 3) + 3
        assert result.text[start:end] == f"~~~json\n{code}~~~"

    def test_fence_with_info_string(self) -> None:
        """A fenced block with an info string (```python) is handled."""
        code = "x = 1\n---\n\ny = 2\n"
        text = f"# Title\n\n```python\n{code}```\n"
        result = normalise_markdown(text)
        start = result.text.index("```python")
        end = result.text.index("```", start + 3) + 3
        assert result.text[start:end] == f"```python\n{code}```"


class TestUnclosedFence:
    """An unclosed fence does not cause the rest of the note to be swallowed."""

    def test_unclosed_fence_treated_as_content(self) -> None:
        text = "```\nline1\nline2\n\nSome text.\n"
        result = normalise_markdown(text)
        assert "Some text." in result.text
        assert "line1" in result.text
        assert "line2" in result.text


class TestFrontmatterUntouched:
    """The frontmatter block is untouched, including its --- delimiters."""

    def test_frontmatter_preserved(self) -> None:
        text = "---\ntitle: My Note\ntags: [a, b]\ndate: 2024-01-01\n---\n\n# Title\n\nContent.\n"
        result = normalise_markdown(text)
        assert result.text.startswith("---\ntitle: My Note\ntags: [a, b]\ndate: 2024-01-01\n---\n")

    def test_frontmatter_with_rules_after(self) -> None:
        text = "---\ntitle: T\n---\n\n---\n\n# Title\n\nContent.\n"
        result = normalise_markdown(text)
        # The --- after frontmatter is adjacent to heading → removed
        # Result should be: frontmatter + heading + content
        lines = result.text.split("\n")
        # Frontmatter delimiters preserved
        assert lines[0] == "---"
        assert "title: T" in result.text
        assert "# Title" in result.text
        # The stray --- is gone
        body_after_fm = result.text.split("---\n", 2)[2]
        assert body_after_fm.strip().startswith("# Title")


class TestIdempotent:
    """f(f(x)) == f(x)"""

    def test_idempotent_clean(self) -> None:
        text = "---\ntitle: T\n---\n\n# Title\n\nContent.\n"
        r1 = normalise_markdown(text)
        r2 = normalise_markdown(r1.text)
        assert r1.text == r2.text

    def test_idempotent_massive_rules(self) -> None:
        text = "---\ntitle: T\n---\n\n# Title\n\n---\n---\n---\n\n## S\n\n---\n\nContent.\n"
        r1 = normalise_markdown(text)
        r2 = normalise_markdown(r1.text)
        assert r1.text == r2.text

    def test_idempotent_blank_lines(self) -> None:
        text = "First.\n\n\n\nSecond.\n"
        r1 = normalise_markdown(text)
        r2 = normalise_markdown(r1.text)
        assert r1.text == r2.text


class TestWordCountUnchanged:
    """Word count is not materially changed."""

    def test_word_count_stable(self) -> None:
        text = (
            "---\ntitle: T\n---\n\n"
            "# Title\n\n"
            "---\n\n"
            "## Alpha\n\n"
            "This is content with several words here.\n\n"
            "---\n\n"
            "## Beta\n\n"
            "More content with different words to count.\n\n"
            "---\n"
        )
        before = len(text.split())
        result = normalise_markdown(text)
        after = len(result.text.split())
        # Allow ±5 words due to blank line changes
        assert abs(before - after) <= 5


class TestHeadingSurroundingBlankLines:
    """Headings gain surrounding blank lines when missing."""

    def test_heading_without_before_blank(self) -> None:
        text = "Some text.\n## Section\nContent.\n"
        result = normalise_markdown(text)
        assert "\n## Section\n" in result.text
        before_idx = result.text.index("## Section")
        assert result.text[before_idx - 1] == "\n"
        after_idx = before_idx + len("## Section")
        assert result.text[after_idx] == "\n"

    def test_heading_without_after_blank(self) -> None:
        text = "Some text.\n\n## Section\nContent.\n"
        result = normalise_markdown(text)
        idx = result.text.index("## Section") + len("## Section")
        assert result.text[idx] == "\n"
        assert result.text[idx + 1] == "\n"

    def test_heading_surrounded_by_content(self) -> None:
        text = "Before.\n## Section\nAfter.\n"
        result = normalise_markdown(text)
        lines = result.text.split("\n")
        heading_idx = next(i for i, l in enumerate(lines) if "## Section" in l)
        assert lines[heading_idx - 1].strip() == ""
        assert lines[heading_idx + 1].strip() == ""


class TestSpacedRuleForms:
    """Spaced forms like - - - are recognised as horizontal rules."""

    def test_spaced_dash_rule(self) -> None:
        text = "First.\n\n- - -\n\nSecond.\n"
        result = normalise_markdown(text)
        # The spaced form is normalized to ---, not removed
        assert "---" in result.text
        assert "- - -" not in result.text

    def test_spaced_star_rule(self) -> None:
        text = "First.\n\n* * *\n\nSecond.\n"
        result = normalise_markdown(text)
        assert "---" in result.text
        assert "* * *" not in result.text


class TestEdgeCases:
    """Various edge cases."""

    def test_empty_text(self) -> None:
        result = normalise_markdown("")
        assert result.text == ""
        assert result.rules_removed == 0

    def test_only_frontmatter(self) -> None:
        text = "---\ntitle: T\n---\n"
        result = normalise_markdown(text)
        assert result.text == text

    def test_only_headings(self) -> None:
        text = "# Title\n\n## S1\n\n## S2\n"
        result = normalise_markdown(text)
        assert "## S1" in result.text
        assert "## S2" in result.text
        assert result.rules_removed == 0

    def test_trailing_whitespace_stripped(self) -> None:
        text = "Line with trailing spaces.   \n\nAnother line.\t\t\n"
        result = normalise_markdown(text)
        for line in result.text.split("\n"):
            if line:
                assert line == line.rstrip()

    def test_consecutive_rules_with_blanks_between(self) -> None:
        """Rules separated by blanks still collapse."""
        text = "First.\n\n---\n\n\n---\n\n\n---\n\nSecond.\n"
        result = normalise_markdown(text)
        assert result.text.count("---") <= 1
        assert result.rules_removed >= 2

    def test_rule_at_end_of_document(self) -> None:
        text = "Content.\n\n---\n"
        result = normalise_markdown(text)
        assert "---" in result.text
        lines = result.text.rstrip("\n").split("\n")
        assert lines[-1].strip() == "---" or lines[-2].strip() == "---"

    def test_two_heading_with_rule_between(self) -> None:
        """Rule between two headings — adjacent to both, should be removed."""
        text = "## A\n\n---\n\n## B\n"
        result = normalise_markdown(text)
        assert "---" not in result.text

    def test_normalise_result_fields(self) -> None:
        text = "## A\n\n---\n\n---\n\n## B\n"
        result = normalise_markdown(text)
        assert isinstance(result, NormaliseResult)
        assert result.rules_removed >= 1
        assert isinstance(result.text, str)
