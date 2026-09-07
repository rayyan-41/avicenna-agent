"""Tests for scripts/gen_matrix.py — MOC file detection and tag validation.

Covers: tag-based detection of MOC files; filename fallback for untagged MOCs;
non-MOC files not misidentified; empty domain dirs; case-insensitive matching;
malformed frontmatter tolerated; noMoc domain skip; tag validation delegation
to the vault's own validate_tags tool.

All tests use tmp_path — no real vault is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from avicenna.tools.base import ToolResult
from avicenna.tools.contracts import ParsedContract
from scripts.gen_matrix import CellResult, _find_moc_files, _no_moc_domains, _run_assertions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_note(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tag-based detection
# ---------------------------------------------------------------------------

class TestTagBasedDetection:
    def test_tagged_moc_found_regardless_of_filename(
        self, tmp_path: Path
    ) -> None:
        """A file with 'moc' in its frontmatter tags is found whatever its name."""
        _write_note(
            tmp_path / "Some Random Name.md",
            "---\ntags: [art, moc, cli]\n---\nBody text.\n",
        )
        found = _find_moc_files(tmp_path)
        assert len(found) == 1
        assert found[0].name == "Some Random Name.md"

    def test_tagged_moc_case_insensitive(self, tmp_path: Path) -> None:
        """Tag comparison is case-insensitive — 'MOC' and 'Moc' both match."""
        _write_note(
            tmp_path / "Note A.md",
            "---\ntags: [art, MOC, cli]\n---\nBody.\n",
        )
        _write_note(
            tmp_path / "Note B.md",
            "---\ntags: [art, Moc, cli]\n---\nBody.\n",
        )
        found = _find_moc_files(tmp_path)
        names = {f.name for f in found}
        assert "Note A.md" in names
        assert "Note B.md" in names

    def test_multiline_tags_still_detected(self, tmp_path: Path) -> None:
        """A single-line bracketed tags field is detected."""
        _write_note(
            tmp_path / "MOC.md",
            "---\ntags: [science, moc, cli]\ndescription: test\n---\nBody.\n",
        )
        found = _find_moc_files(tmp_path)
        assert len(found) == 1


# ---------------------------------------------------------------------------
# Filename fallback
# ---------------------------------------------------------------------------

class TestFilenameFallback:
    def test_map_of_contents_found_by_stem(self, tmp_path: Path) -> None:
        """'Map of Contents - Art.md' found via the filename fallback when untagged."""
        _write_note(
            tmp_path / "Map of Contents - Art.md",
            "---\ntags: [art, cli]\n---\nSome content.\n",
        )
        found = _find_moc_files(tmp_path)
        assert len(found) == 1
        assert found[0].name == "Map of Contents - Art.md"

    def test_moc_whole_word_in_stem(self, tmp_path: Path) -> None:
        """A file with 'moc' as a whole word in the stem is found."""
        _write_note(
            tmp_path / "Art MOC.md",
            "---\ntags: [art, cli]\n---\nBody.\n",
        )
        found = _find_moc_files(tmp_path)
        assert len(found) == 1

    def test_filename_fallback_case_insensitive(self, tmp_path: Path) -> None:
        """Filename fallback is case-insensitive."""
        _write_note(
            tmp_path / "map of contents - Science.md",
            "---\ntags: [science, cli]\n---\nBody.\n",
        )
        found = _find_moc_files(tmp_path)
        assert len(found) == 1


# ---------------------------------------------------------------------------
# Non-MOC files not misidentified
# ---------------------------------------------------------------------------

class TestNonMocNotMistaken:
    def test_mocking_realism_not_moc(self, tmp_path: Path) -> None:
        """'Mocking Realism.md' with ordinary tags is NOT treated as a MOC."""
        _write_note(
            tmp_path / "Mocking Realism.md",
            "---\ntags: [art, concept]\n---\nAn essay on mocking in art.\n",
        )
        found = _find_moc_files(tmp_path)
        assert found == []

    def test_no_tags_no_moc(self, tmp_path: Path) -> None:
        """A file with no tags at all is not a MOC."""
        _write_note(
            tmp_path / "Random Note.md",
            "---\ndescription: something\n---\nBody.\n",
        )
        found = _find_moc_files(tmp_path)
        assert found == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_domain_dir(self, tmp_path: Path) -> None:
        """A domain dir with no .md files returns an empty list."""
        found = _find_moc_files(tmp_path)
        assert found == []

    def test_no_md_files(self, tmp_path: Path) -> None:
        """Non-.md files are ignored."""
        (tmp_path / "readme.txt").write_text("not a note", encoding="utf-8")
        found = _find_moc_files(tmp_path)
        assert found == []

    def test_malformed_frontmatter_no_crash(self, tmp_path: Path) -> None:
        """A malformed / unterminated frontmatter block does not raise."""
        _write_note(
            tmp_path / "Broken.md",
            "---\ntags: [art, moc, cli\n---\nnever closed bracket above.\n",
        )
        # Should not raise — malformed bracket list means tags stay empty,
        # so no tag-based match.  Falls through to filename check.
        found = _find_moc_files(tmp_path)
        # No filename match either.
        assert found == []

    def test_unterminated_frontmatter_no_crash(self, tmp_path: Path) -> None:
        """An unterminated frontmatter block does not raise."""
        _write_note(
            tmp_path / "No End.md",
            "---\ntags: [art, moc, cli]\nThis block never closes.\n",
        )
        # Only one --- boundary found, so frontmatter is not parsed.
        # Falls through to filename heuristic.
        found = _find_moc_files(tmp_path)
        assert found == []

    def test_multiple_mocs_in_one_dir(self, tmp_path: Path) -> None:
        """A dir with multiple MOCs returns all of them."""
        _write_note(
            tmp_path / "Map of Contents - Art.md",
            "---\ntags: [art, moc, cli]\n---\nBody.\n",
        )
        _write_note(
            tmp_path / "Art MOC Backup.md",
            "---\ntags: [art, moc]\n---\nBackup.\n",
        )
        found = _find_moc_files(tmp_path)
        assert len(found) == 2


# ---------------------------------------------------------------------------
# _no_moc_domains
# ---------------------------------------------------------------------------

class _FakeTaxonomy:
    """Minimal stand-in for Taxonomy with a noMoc raw field."""
    def __init__(self, no_moc: list[str] | None = None) -> None:
        self._no_moc = no_moc

    @property
    def no_moc(self) -> list[str] | None:
        return self._no_moc

    @property
    def raw(self) -> dict[str, object]:
        if self._no_moc is not None:
            return {"noMoc": self._no_moc}
        return {}


class TestNoMocDomains:
    def test_no_moc_returns_set(self) -> None:
        taxonomy = _FakeTaxonomy(no_moc=["reason"])
        result = _no_moc_domains(taxonomy)  # type: ignore[arg-type]
        assert result == {"reason"}

    def test_no_no_moc_returns_empty(self) -> None:
        taxonomy = _FakeTaxonomy(no_moc=None)
        result = _no_moc_domains(taxonomy)  # type: ignore[arg-type]
        assert result == set()

    def test_case_insensitive(self) -> None:
        taxonomy = _FakeTaxonomy(no_moc=["Reason", "SCIENCE"])
        result = _no_moc_domains(taxonomy)  # type: ignore[arg-type]
        assert result == {"reason", "science"}


# ---------------------------------------------------------------------------
# Tag validation delegation (assertion 4)
# ---------------------------------------------------------------------------

class _FakeTool:
    """Mock tool whose invoke returns a pre-built ToolResult."""
    def __init__(self, result: ToolResult) -> None:
        self._result = result

    async def invoke(self, **kwargs: Any) -> ToolResult:
        return self._result


class _FakeTools:
    """Mock ToolRegistry that optionally holds a validate_tags tool."""
    def __init__(self, tool: _FakeTool | None = None) -> None:
        self._tool = tool

    def has(self, name: str) -> bool:
        return name == "validate_tags" and self._tool is not None

    def get(self, name: str) -> _FakeTool:
        if name == "validate_tags" and self._tool is not None:
            return self._tool
        raise KeyError(name)


class _FakeVault:
    """Minimal vault stand-in carrying only what _run_assertions needs."""
    def __init__(self, tools: _FakeTools, root: Path) -> None:
        self.tools = tools
        self.root = root
        self.taxonomy = _FakeTaxonomy()


def _make_note(path: Path, tags: list[str]) -> None:
    tag_list = ", ".join(tags)
    path.write_text(
        f"---\ntags: [{tag_list}]\n---\nBody content here.\n",
        encoding="utf-8",
    )


def _pass_result() -> ToolResult:
    return ToolResult(
        tool="validate_tags", ok=True, stdout="PASS", stderr="",
        exit_code=0, duration_s=0.01,
        parsed=ParsedContract("validate_tags", True, "PASS", detail="PASS"),
    )


def _fail_result(reason: str) -> ToolResult:
    return ToolResult(
        tool="validate_tags", ok=False, stdout=f"FAIL: {reason}", stderr="",
        exit_code=0, duration_s=0.01,
        parsed=ParsedContract(
            "validate_tags", False, "FAIL",
            captures={"reasons": reason},
            detail=f"FAIL: {reason}",
        ),
    )


class TestTagValidationDelegation:
    async def test_entity_tag_passes_when_validator_passes(
        self, tmp_path: Path
    ) -> None:
        """An open-vocabulary entity (e.g. 'michelangelo') passes when the
        vault's own validate_tags tool returns PASS."""
        note = tmp_path / "note.md"
        _make_note(note, ["art", "art-theory", "concept", "aesthetics",
                          "michelangelo", "cli"])
        vault = _FakeVault(_FakeTools(_FakeTool(_pass_result())), tmp_path)
        result = CellResult(domain="art", agent="test")
        await _run_assertions(result, note, vault, {})  # type: ignore[arg-type]
        tag_failures = [a for a in result.failed_assertions if "invalid_tag" in a or "invalid_tags" in a]
        assert tag_failures == []

    async def test_invalid_tag_fails_with_validator_reason(
        self, tmp_path: Path
    ) -> None:
        """A genuinely invalid tag line fails, recording the validator's own
        reason rather than a reconstructed one."""
        note = tmp_path / "note.md"
        _make_note(note, ["art", "bogus-tag", "cli"])
        reason = "unrecognised tag: bogus-tag"
        vault = _FakeVault(_FakeTools(_FakeTool(_fail_result(reason))), tmp_path)
        result = CellResult(domain="art", agent="test")
        await _run_assertions(result, note, vault, {})  # type: ignore[arg-type]
        tag_failures = [a for a in result.failed_assertions if "invalid_tags" in a]
        assert len(tag_failures) == 1
        assert reason in tag_failures[0]

    async def test_validator_absent_skips_assertion(
        self, tmp_path: Path
    ) -> None:
        """When validate_tags is absent, the assertion is SKIPPED (not failed)."""
        note = tmp_path / "note.md"
        _make_note(note, ["art", "concept", "cli"])
        vault = _FakeVault(_FakeTools(None), tmp_path)  # no validate_tags tool
        result = CellResult(domain="art", agent="test")
        await _run_assertions(result, note, vault, {})  # type: ignore[arg-type]
        tag_failures = [a for a in result.failed_assertions if "invalid_tag" in a]
        assert tag_failures == []
        skipped = [a for a in result.failed_assertions if "tag_validation_skipped" in a]
        assert len(skipped) == 1

    async def test_no_hardcoded_enumeration_consulted(
        self, tmp_path: Path
    ) -> None:
        """The assertion must not consult a hardcoded tag set.

        We verify this by ensuring _all_valid_tags is not importable from
        gen_matrix — it was deleted as part of this fix.
        """
        import scripts.gen_matrix as gm
        assert not hasattr(gm, "_all_valid_tags"), (
            "_all_valid_tags should have been deleted; "
            "entities are open vocabulary and cannot be enumerated"
        )
