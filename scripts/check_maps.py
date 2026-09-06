"""Enforce MAP.md inventory parity across the repository.

Every directory that contains mappable source files must carry a MAP.md whose
file table — delimited by HTML comment markers — lists exactly those files, no
more, no fewer. A literal ``TODO:`` in any map fails the build, so ``--fix``
cannot land a placeholder without someone writing the sentence.

Run directly: ``python scripts/check_maps.py``
Or in fix mode: ``python scripts/check_maps.py --fix``
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Dict, List, Set, Tuple

ROOT: Path = Path(__file__).resolve().parent.parent

MAPPABLE_EXTENSIONS: Set[str] = {
    ".py",
    ".ts",
    ".mjs",
    ".md",
    ".json",
    ".yml",
    ".ps1",
}

START_MARKER: str = "<!-- map:files:start -->"
END_MARKER: str = "<!-- map:files:end -->"
PLACEHOLDER: str = "TODO:"

TABLE_HEADER: str = "| File | Loc | Role |"
TABLE_SEP: str = "| --- | --- | --- |"

# Matches a data row:  | `name` | 123 | role text |
ROW_RE: re.Pattern[str] = re.compile(
    r"^\|\s*`(?P<name>[^`]+)`\s*\|\s*(?P<loc>\d+)\s*\|\s*(?P<role>.*?)\s*\|$"
)


# ---------------------------------------------------------------------------
# Git interaction
# ---------------------------------------------------------------------------


def git_tracked_files() -> List[str]:
    """Return every path tracked by git, forward-slash separated."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        cwd=ROOT,
        check=True,
    )
    # -z uses NUL separators; split and drop the trailing empty string.
    decoded: str = result.stdout.decode()
    return [p for p in decoded.split("\x00") if p]


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------


def mappable_files(files: List[str]) -> Dict[str, List[str]]:
    """Group mappable source files by their parent directory.

    MAP.md is excluded from every inventory. Paths use forward slashes; the
    repository root is represented as ``"."``.
    """
    by_dir: Dict[str, List[str]] = {}
    for f in files:
        p = PurePosixPath(f)
        if p.suffix not in MAPPABLE_EXTENSIONS:
            continue
        if p.name == "MAP.md":
            continue
        dirpath: str = str(p.parent)
        by_dir.setdefault(dirpath, []).append(p.name)
    for dirpath in by_dir:
        by_dir[dirpath].sort()
    return by_dir


# ---------------------------------------------------------------------------
# MAP.md parsing
# ---------------------------------------------------------------------------


def _find_marker_lines(lines: List[str]) -> Tuple[int, int, str]:
    """Locate the sole start and end marker lines in *lines*.

    A marker only counts when it is **alone on its own line** (ignoring
    leading and trailing whitespace).  An inline mention inside a sentence or
    inside backticks is prose and must be ignored entirely.

    Returns ``(start_idx, end_idx, "")`` on success, or ``(-1, -1, error)``
    where *error* is one of ``"missing_both"``, ``"missing_start"``,
    ``"missing_end"``, ``"duplicated"``, or ``"order"``.  Every caller
    branches on the error string, never on prose — the contract is
    deterministic.

    Historical note: this helper was introduced because the root MAP.md
    documents the marker convention in prose, which caused
    ``content.count()`` to see duplicates and fail the gate on a map that
    was doing exactly the right thing.
    """
    start_idx: int = -1
    end_idx: int = -1
    for i, line in enumerate(lines):
        stripped: str = line.strip()
        if stripped == START_MARKER:
            start_idx = i
        elif stripped == END_MARKER:
            end_idx = i

    if start_idx == -1 and end_idx == -1:
        return -1, -1, "missing_both"
    if start_idx == -1:
        return -1, -1, "missing_start"
    if end_idx == -1:
        return -1, -1, "missing_end"
    # A second standalone occurrence means the file has two real blocks.
    # Count after the first find to detect duplicates without a second pass.
    count_s: int = sum(1 for line in lines if line.strip() == START_MARKER)
    count_e: int = sum(1 for line in lines if line.strip() == END_MARKER)
    if count_s > 1 or count_e > 1:
        return -1, -1, "duplicated"
    if start_idx >= end_idx:
        return -1, -1, "order"
    return start_idx, end_idx, ""


def _is_standalone(content: str, match_start: int, match_end: int) -> bool:
    """Check whether a marker match at ``content[match_start:match_end]`` stands alone on its line.

    The marker is standalone when the rest of its line — both before and
    after — is whitespace only.
    """
    # Text after the marker up to the next newline (or end of content).
    after: str = content[match_end:].split("\n", 1)[0]
    if after.strip() != "":
        return False
    # Text before the marker from the start of its line.
    line_start: int = content.rfind("\n", 0, match_start)
    before: str = content[line_start + 1 : match_start]
    return before.strip() == ""


def find_markers(content: str) -> Tuple[int, int]:
    """Return character offsets of the start and end markers.

    Returns ``(-1, -1)`` on any structural violation: missing markers,
    duplicates, or start not preceding end.  Only standalone marker lines
    (ignoring leading/trailing whitespace) are recognised — inline mentions
    in prose are invisible to this function.
    """
    start_off: int = -1
    end_off: int = -1
    start_count: int = 0
    end_count: int = 0
    for m in re.finditer(re.escape(START_MARKER), content):
        if _is_standalone(content, m.start(), m.end()):
            start_off = m.start()
            start_count += 1
    for m in re.finditer(re.escape(END_MARKER), content):
        if _is_standalone(content, m.start(), m.end()):
            end_off = m.start()
            end_count += 1
    if start_count != 1 or end_count != 1:
        return -1, -1
    if start_off >= end_off:
        return -1, -1
    return start_off, end_off


def parse_table_filenames(content: str, start: int, end: int) -> Set[str]:
    """Extract filenames from the table between the markers."""
    block: str = content[start + len(START_MARKER) : end]
    names: Set[str] = set()
    for line in block.splitlines():
        m = ROW_RE.match(line.strip())
        if m:
            names.add(m.group("name"))
    return names


def count_lines(path: Path) -> int:
    """Count lines in a UTF-8 file, or 0 if it does not exist."""
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _posix_rel(path: Path) -> str:
    """Convert a path to forward-slash form relative to ROOT."""
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return str(path)
    return rel.as_posix()


# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------


def check_coverage(mappable: Dict[str, List[str]]) -> List[str]:
    """COVERAGE: every directory with mappable files has a MAP.md."""
    errors: List[str] = []
    for dirpath, files in sorted(mappable.items()):
        map_path: Path = ROOT / dirpath / "MAP.md"
        if not map_path.exists():
            display: str = dirpath if dirpath != "." else "."
            n: int = len(files)
            errors.append(
                f"::error file={display}/MAP.md::Missing MAP.md in {display}/ "
                f"({n} mappable file{'s' if n != 1 else ''})"
            )
    return errors


def check_marker_block(map_path: Path) -> List[str]:
    """Return error strings if the map's markers are malformed.

    Uses ``_find_marker_lines`` so that only standalone marker lines are
    counted — inline mentions in prose (e.g. a MAP.md that documents the
    convention itself) are invisible.
    """
    content: str = map_path.read_text(encoding="utf-8")
    rel_str: str = _posix_rel(map_path)
    errors: List[str] = []

    lines: List[str] = content.splitlines()
    _start, _end, err = _find_marker_lines(lines)

    if err == "missing_both":
        errors.append(f"::error file={rel_str}::Missing both markers")
    elif err == "missing_start":
        errors.append(f"::error file={rel_str}::Missing start marker")
    elif err == "missing_end":
        errors.append(f"::error file={rel_str}::Missing end marker")
    elif err == "duplicated":
        count_s: int = sum(1 for line in lines if line.strip() == START_MARKER)
        count_e: int = sum(1 for line in lines if line.strip() == END_MARKER)
        errors.append(
            f"::error file={rel_str}::Markers duplicated (start×{count_s}, end×{count_e})"
        )
    elif err == "order":
        errors.append(f"::error file={rel_str}::Start marker does not precede end marker")
    # err == "" means well-formed — no error to append.

    return errors


def check_inventory_parity(
    mappable: Dict[str, List[str]], known_maps: List[Path]
) -> List[str]:
    """INVENTORY PARITY: filenames in the table equal files on disk."""
    errors: List[str] = []
    for map_path in known_maps:
        rel_str: str = _posix_rel(map_path)
        parent: str = str(PurePosixPath(rel_str).parent)
        dirpath: str = parent if parent != "." else "."
        content: str = map_path.read_text(encoding="utf-8")

        start, end = find_markers(content)
        if start == -1:
            continue  # marker errors already reported by check_marker_block

        listed: Set[str] = parse_table_filenames(content, start, end)
        actual: Set[str] = set(mappable.get(dirpath, []))

        missing: Set[str] = actual - listed
        extra: Set[str] = listed - actual
        for f in sorted(missing):
            errors.append(f"::error file={rel_str}::Missing row for {f}")
        for f in sorted(extra):
            errors.append(f"::error file={rel_str}::Extra row for {f} (file not in directory)")

    return errors


def check_placeholders(known_maps: List[Path]) -> List[str]:
    """NO PLACEHOLDERS: no MAP.md contains the literal TODO:"""
    errors: List[str] = []
    for map_path in known_maps:
        rel_str: str = _posix_rel(map_path)
        content: str = map_path.read_text(encoding="utf-8")
        if PLACEHOLDER in content:
            errors.append(
                f"::error file={rel_str}::Contains placeholder \"{PLACEHOLDER}\""
            )
    return errors


# ---------------------------------------------------------------------------
# --fix
# ---------------------------------------------------------------------------


def fix_single_map(map_path: Path, actual_files: List[str]) -> None:
    """Rewrite the marker block in one MAP.md to match the actual file set.

    Preserves existing role text and everything outside the markers byte for
    byte. New rows carry a deliberate ``TODO:`` placeholder so the gate still
    fails until someone writes the sentence.

    If the markers are absent, duplicated, or misordered, the file is skipped
    with a warning — guessing where the block should go would corrupt the map.
    """
    content: str = map_path.read_text(encoding="utf-8")
    rel_str: str = _posix_rel(map_path)
    start, end = find_markers(content)
    if start == -1:
        print(f"WARNING: skipping {rel_str} — markers missing or malformed", file=sys.stderr)
        return

    block: str = content[start + len(START_MARKER) : end]
    before: str = content[: start + len(START_MARKER)]
    after: str = content[end:]

    # Parse existing rows to preserve their role text.
    existing_roles: Dict[str, str] = {}
    for line in block.splitlines():
        m = ROW_RE.match(line.strip())
        if m:
            existing_roles[m.group("name")] = m.group("role")

    actual_set: Set[str] = set(actual_files)
    rows: List[str] = []
    for name in sorted(actual_set):
        file_path: Path = map_path.parent / name
        loc: int = count_lines(file_path)
        role: str = existing_roles.get(name, PLACEHOLDER)
        rows.append(f"| `{name}` | {loc} | {role} |")

    new_block: str = (
        "\n" + TABLE_HEADER + "\n" + TABLE_SEP + "\n" + "\n".join(rows) + "\n"
        if rows
        else "\n" + TABLE_HEADER + "\n" + TABLE_SEP + "\n"
    )
    new_content: str = before + new_block + after

    # Write LF explicitly — the repo gates CRLF.
    map_path.write_text(new_content, encoding="utf-8", newline="\n")


def fix_maps(mappable: Dict[str, List[str]], known_maps: List[Path]) -> None:
    """Fix all existing MAP.md files to match the actual file set."""
    for map_path in known_maps:
        rel_str: str = _posix_rel(map_path)
        parent: str = str(PurePosixPath(rel_str).parent)
        dirpath: str = parent if parent != "." else "."
        actual_files: List[str] = mappable.get(dirpath, [])
        fix_single_map(map_path, actual_files)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_maps() -> List[Path]:
    """Find every MAP.md tracked by git."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        cwd=ROOT,
        check=True,
    )
    decoded: str = result.stdout.decode()
    paths: List[Path] = []
    for p in decoded.split("\x00"):
        if p and PurePosixPath(p).name == "MAP.md":
            paths.append(ROOT / p)
    return sorted(paths)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point. Returns 0 on success, 1 on any violation."""
    fix: bool = "--fix" in sys.argv

    tracked: List[str] = git_tracked_files()
    mappable: Dict[str, List[str]] = mappable_files(tracked)
    known_maps: List[Path] = discover_maps()

    if fix:
        fix_maps(mappable, known_maps)
        print("MAP.md fix complete. Re-run without --fix to verify.")
        return 0

    errors: List[str] = []
    errors.extend(check_coverage(mappable))
    for map_path in known_maps:
        errors.extend(check_marker_block(map_path))
    errors.extend(check_inventory_parity(mappable, known_maps))
    errors.extend(check_placeholders(known_maps))

    if errors:
        print("::error::MAP.md check failed.")
        for problem in errors:
            print(f"  {problem}")
        return 1

    total_maps: int = len(known_maps)
    total_files: int = sum(len(fs) for fs in mappable.values())
    print(f"MAP.md check OK: {total_maps} maps, {total_files} tracked source files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
