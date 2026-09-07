"""Tests for scripts/check_maps.py — MAP.md inventory parity gate.

Covers: untracked file detection, extra-row behaviour for untracked files,
ignored-file exclusion, marker-alone-on-its-line rule, TODO: rejection,
and the (untracked) annotation on missing-row findings.

All tests use tmp_path with a real ``git init`` — no real repository is touched.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_maps import (
    START_MARKER,
    END_MARKER,
    PLACEHOLDER,
    TABLE_HEADER,
    TABLE_SEP,
    check_inventory_parity,
    check_placeholders,
    discover_maps,
    find_markers,
    git_repository_files,
    git_tracked_files,
    git_untracked_files,
    mappable_files,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_init(repo: Path) -> None:
    """Initialise a git repo and configure it for test commits."""
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _make_map(repo: Path, rel_dir: str, filenames: list[str]) -> Path:
    """Write a minimal MAP.md with marker block listing *filenames*."""
    rows = "\n".join(f"| `{f}` | 1 | role |" for f in filenames)
    block = f"\n{TABLE_HEADER}\n{TABLE_SEP}\n{rows}\n" if rows else f"\n{TABLE_HEADER}\n{TABLE_SEP}\n"
    content = (
        f"# MAP: {rel_dir}\n\n"
        f"{START_MARKER}{block}{END_MARKER}\n"
    )
    target: Path = repo / rel_dir / "MAP.md" if rel_dir != "." else repo / "MAP.md"
    _write_file(target, content)
    return target


# ---------------------------------------------------------------------------
# Tests: untracked file with no row fails the gate
# ---------------------------------------------------------------------------


def test_untracked_file_with_no_map_row_fails(tmp_path: Path) -> None:
    """An untracked, non-ignored source file with no map row must FAIL."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)

    src = repo / "example.py"
    _write_file(src, "x = 1\n")

    # Monkey-patch ROOT so the gate inspects tmp_path, not the real repo.
    import scripts.check_maps as cm
    original_root = cm.ROOT
    cm.ROOT = repo
    try:
        untracked = git_untracked_files()
        assert "example.py" in untracked
        all_files, tracked = git_repository_files()
        assert "example.py" in all_files
        assert "example.py" not in tracked

        mappable = mappable_files(all_files)
        assert "." in mappable
        assert "example.py" in mappable["."]

        # No MAP.md exists — coverage fails too.
        errors: list[str] = []
        errors.extend(cm.check_coverage(mappable))
        assert any("Missing MAP.md" in e for e in errors)
    finally:
        cm.ROOT = original_root


def test_untracked_file_detected_before_staging(tmp_path: Path) -> None:
    """The gate sees an untracked file even before it is staged."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)

    # Create an initial commit so git has something to track.
    _write_file(repo / "README.md", "# test\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    # Now create an untracked source file.
    _write_file(repo / "tests" / "test_new.py", "assert True\n")

    import scripts.check_maps as cm
    original_root = cm.ROOT
    cm.ROOT = repo
    try:
        untracked = git_untracked_files()
        assert "tests/test_new.py" in untracked

        all_files, tracked = git_repository_files()
        assert "tests/test_new.py" in all_files
        assert "tests/test_new.py" not in tracked
    finally:
        cm.ROOT = original_root


# ---------------------------------------------------------------------------
# Tests: staged file still fails (no behaviour change when tracked)
# ---------------------------------------------------------------------------


def test_staged_file_still_fails_without_map_row(tmp_path: Path) -> None:
    """After staging, the same missing-row failure persists."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)

    _write_file(repo / "README.md", "# test\n")
    _write_file(repo / "example.py", "x = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    import scripts.check_maps as cm
    original_root = cm.ROOT
    cm.ROOT = repo
    try:
        all_files, tracked = git_repository_files()
        assert "example.py" in all_files
        assert "example.py" in tracked

        mappable = mappable_files(all_files)
        errors = cm.check_coverage(mappable)
        assert any("Missing MAP.md" in e for e in errors)
    finally:
        cm.ROOT = original_root


# ---------------------------------------------------------------------------
# Tests: map row for untracked file does NOT report "extra row"
# ---------------------------------------------------------------------------


def test_map_row_for_untracked_file_not_extra(tmp_path: Path) -> None:
    """A map row for an untracked file present on disk must not report extra."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)

    _write_file(repo / "README.md", "# test\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    # Untracked source file + map that lists it.
    _write_file(repo / "new_module.py", "x = 1\n")
    _make_map(repo, ".", ["README.md", "new_module.py"])

    import scripts.check_maps as cm
    original_root = cm.ROOT
    cm.ROOT = repo
    try:
        all_files, tracked = git_repository_files()
        mappable = mappable_files(all_files)
        known_maps = discover_maps()

        assert any("MAP.md" in str(m) for m in known_maps)
        errors = check_inventory_parity(mappable, known_maps, tracked)
        extra_errors = [e for e in errors if "Extra row" in e]
        assert extra_errors == [], f"should not report extra row, got: {extra_errors}"
    finally:
        cm.ROOT = original_root


# ---------------------------------------------------------------------------
# Tests: ignored file with no row still passes
# ---------------------------------------------------------------------------


def test_ignored_file_with_no_row_passes(tmp_path: Path) -> None:
    """An IGNORED file without a map row must not fail the gate."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)

    _write_file(repo / ".gitignore", "__pycache__/\n_tmp/\n")
    _write_file(repo / "README.md", "# test\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    # Ignored files.
    _write_file(repo / "_tmp" / "chunk.md", "content\n")
    _write_file(repo / "__pycache__" / "module.cpy", "content\n")

    _make_map(repo, ".", ["README.md"])

    import scripts.check_maps as cm
    original_root = cm.ROOT
    cm.ROOT = repo
    try:
        all_files, tracked = git_repository_files()
        untracked = git_untracked_files()
        assert "_tmp/chunk.md" not in untracked
        assert "__pycache__/module.cpy" not in untracked

        mappable = mappable_files(all_files)
        known_maps = discover_maps()
        errors = check_inventory_parity(mappable, known_maps, tracked)
        assert errors == [], f"ignored files should not cause errors: {errors}"
    finally:
        cm.ROOT = original_root


# ---------------------------------------------------------------------------
# Tests: untracked finding names the file as untracked
# ---------------------------------------------------------------------------


def test_untracked_finding_annotated(tmp_path: Path) -> None:
    """A missing-row finding for an untracked file carries the (untracked) suffix."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)

    _write_file(repo / "README.md", "# test\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    _write_file(repo / "new_module.py", "x = 1\n")
    _make_map(repo, ".", ["README.md"])

    import scripts.check_maps as cm
    original_root = cm.ROOT
    cm.ROOT = repo
    try:
        all_files, tracked = git_repository_files()
        mappable = mappable_files(all_files)
        known_maps = discover_maps()

        errors = check_inventory_parity(mappable, known_maps, tracked)
        missing_errors = [e for e in errors if "Missing row" in e]
        assert len(missing_errors) == 1
        assert "(untracked)" in missing_errors[0]
    finally:
        cm.ROOT = original_root


def test_tracked_finding_not_annotated(tmp_path: Path) -> None:
    """A missing-row finding for a tracked file has no (untracked) suffix."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)

    _write_file(repo / "README.md", "# test\n")
    _write_file(repo / "module.py", "x = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    _make_map(repo, ".", ["README.md"])

    import scripts.check_maps as cm
    original_root = cm.ROOT
    cm.ROOT = repo
    try:
        all_files, tracked = git_repository_files()
        mappable = mappable_files(all_files)
        known_maps = discover_maps()

        errors = check_inventory_parity(mappable, known_maps, tracked)
        missing_errors = [e for e in errors if "Missing row" in e and "module.py" in e]
        assert len(missing_errors) == 1
        assert "(untracked)" not in missing_errors[0]
    finally:
        cm.ROOT = original_root


# ---------------------------------------------------------------------------
# Tests: marker-alone-on-its-line rule
# ---------------------------------------------------------------------------


def test_marker_only_counts_when_standalone(tmp_path: Path) -> None:
    """A marker mentioned in prose is not a real marker."""
    content = (
        "# MAP: test\n\n"
        "You can use `<!-- map:files:start -->` to delimit tables.\n\n"
        f"{START_MARKER}\n"
        f"{TABLE_HEADER}\n{TABLE_SEP}\n"
        "| `a.py` | 1 | role |\n"
        f"{END_MARKER}\n"
    )
    start, end = find_markers(content)
    assert start != -1
    assert end != -1


def test_inline_marker_is_ignored(tmp_path: Path) -> None:
    """A marker embedded in a sentence does not count."""
    content = (
        "# MAP: test\n\n"
        f"Here is an example: `{START_MARKER}` inline.\n\n"
        f"{START_MARKER}\n"
        f"{TABLE_HEADER}\n{TABLE_SEP}\n"
        "| `a.py` | 1 | role |\n"
        f"{END_MARKER}\n"
    )
    start, end = find_markers(content)
    assert start != -1
    assert end != -1


def test_duplicate_standalone_markers_fail(tmp_path: Path) -> None:
    """Two standalone start markers cause a failure."""
    content = (
        "# MAP: test\n\n"
        f"{START_MARKER}\n"
        f"{TABLE_HEADER}\n{TABLE_SEP}\n"
        "| `a.py` | 1 | role |\n"
        f"{END_MARKER}\n\n"
        f"{START_MARKER}\n"
        f"{TABLE_HEADER}\n{TABLE_SEP}\n"
        "| `b.py` | 1 | role |\n"
        f"{END_MARKER}\n"
    )
    start, end = find_markers(content)
    assert start == -1
    assert end == -1


# ---------------------------------------------------------------------------
# Tests: TODO: placeholder still fails
# ---------------------------------------------------------------------------


def test_todo_placeholder_fails(tmp_path: Path) -> None:
    """A MAP.md containing a TODO: placeholder must fail."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)

    _write_file(repo / "README.md", "# test\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    _make_map(repo, ".", ["README.md"])
    # Write a TODO: into the map.
    map_path = repo / "MAP.md"
    content = map_path.read_text(encoding="utf-8")
    content = content.replace("| `README.md` | 1 | role |", f"| `README.md` | 1 | {PLACEHOLDER} role |")
    map_path.write_text(content, encoding="utf-8", newline="\n")

    import scripts.check_maps as cm
    original_root = cm.ROOT
    cm.ROOT = repo
    try:
        known_maps = discover_maps()
        errors = check_placeholders(known_maps)
        assert len(errors) == 1
        assert PLACEHOLDER in errors[0]
    finally:
        cm.ROOT = original_root
