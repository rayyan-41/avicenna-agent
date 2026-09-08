"""Tests for surgical taxonomy.json persistence.

TagRegistry.persist() must edit the file as text — every byte it does not
need to change stays identical, including inline arrays, blank lines, key
order and ``$comment`` keys.  When the structure does not match expectations,
the write falls back to full reserialisation and the file is still correct,
just reformatted.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from avicenna.vault.registry import ThemeRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

#: Hand-formatted taxonomy with inline arrays, blank lines and a $comment key.
HAND_FORMATTED = """\
{
  "version": 1,
  "$comment": "Hand-authored. Do not reformat.",

  "schema": {
    "date": "date",
    "status": "status",
    "tags": "tags[]",
    "topic": "text"
  },

  "domains": {
    "Science": {
      "domain": [1, 1],
      "category": [1, 1]
    },
    "Philosophy": {
      "domain": [1, 0],
      "category": [1, 0]
    }
  },

  "themes": ["epistemology", "optic", "revelation"],

  "types": ["note", "concept"],

  "_themeCounts": {
    "epistemology": 3,
    "optic": 1,
    "revelation": 2
  },

  "_typeCounts": {
    "note": 5,
    "concept": 2
  }
}
"""

#: Same structure, but _themeCounts and _typeCounts are absent.
HAND_FORMATTED_NO_COUNTS = """\
{
  "version": 1,
  "$comment": "Hand-authored. Do not reformat.",

  "schema": {
    "date": "date",
    "status": "status",
    "tags": "tags[]",
    "topic": "text"
  },

  "domains": {
    "Science": {
      "domain": [1, 1],
      "category": [1, 1]
    },
    "Philosophy": {
      "domain": [1, 0],
      "category": [1, 0]
    }
  },

  "themes": ["epistemology", "optic", "revelation"],

  "types": ["note", "concept"]
}
"""


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def _read(path: Path) -> str:
    return path.read_text("utf-8")


def _diff_count(a: str, b: str) -> int:
    """Return the number of lines involved in edits between *a* and *b*.

    Uses SequenceMatcher so that a single insertion does not cascade into
    every subsequent line being reported as different.
    """
    import difflib
    la = a.splitlines()
    lb = b.splitlines()
    matcher = difflib.SequenceMatcher(None, la, lb)
    return sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )


# ---------------------------------------------------------------------------
# 1. Mint one theme — only the affected lines change
# ---------------------------------------------------------------------------


def test_surgical_mint_minimal_diff(tmp_path: Path) -> None:
    """Adding one theme changes only the lines that must change."""
    path = tmp_path / "taxonomy.json"
    _write(path, HAND_FORMATTED)
    original = _read(path)

    reg = ThemeRegistry.load(path)
    reg.resolve_theme("experimental-method")
    assert reg.persist()

    result = _read(path)
    diff = _diff_count(original, result)
    # The themes line, _themeCounts entry line, and the structural lines
    # that shift because the inline array grew (closing ] and ,).
    assert diff <= 6, f"Expected <= 6 differing lines, got {diff}"
    data = json.loads(result)
    assert "experimental-method" in data["themes"]


def test_surgical_mint_preserves_formatting(tmp_path: Path) -> None:
    """Inline arrays, blank lines and $comment survive a mint."""
    path = tmp_path / "taxonomy.json"
    _write(path, HAND_FORMATTED)

    reg = ThemeRegistry.load(path)
    reg.resolve_theme("experimental-method")
    reg.persist()

    result = _read(path)
    assert '"domain": [1, 1],' in result
    assert '"domain": [1, 0]' in result
    assert '"$comment"' in result
    # Blank lines between blocks are preserved.
    assert "\n\n  \"schema\"" in result
    assert "\n\n  \"themes\"" in result


# ---------------------------------------------------------------------------
# 2. Counts object absent — created from scratch
# ---------------------------------------------------------------------------


def test_counts_object_created_when_absent(tmp_path: Path) -> None:
    """When _themeCounts is absent, it is created without rewriting the rest."""
    path = tmp_path / "taxonomy.json"
    _write(path, HAND_FORMATTED_NO_COUNTS)
    original = _read(path)

    reg = ThemeRegistry.load(path)
    reg.resolve_theme("experimental-method")
    assert reg.persist()

    result = _read(path)
    data = json.loads(result)
    assert data["_themeCounts"] == {"experimental-method": 1}
    # Unrelated formatting is preserved.
    assert '"domain": [1, 1],' in result
    assert '"$comment"' in result
    # Creating a new block from scratch costs 5 edits: the themes
    # array line, a comma on the types line, and 3 new lines for
    # the counts object (key, entry, closing brace).
    diff = _diff_count(original, result)
    assert diff <= 5, f"Expected <= 5 differing lines, got {diff}"


# ---------------------------------------------------------------------------
# 3. Second mint appends beside the first
# ---------------------------------------------------------------------------


def test_second_mint_appends(tmp_path: Path) -> None:
    """A second mint in the same session appends to the same array."""
    path = tmp_path / "taxonomy.json"
    _write(path, HAND_FORMATTED)
    original = _read(path)

    reg = ThemeRegistry.load(path)
    reg.resolve_theme("experimental-method")
    reg.resolve_theme("alchemy")
    assert reg.persist()

    result = _read(path)
    data = json.loads(result)
    assert "experimental-method" in data["themes"]
    assert "alchemy" in data["themes"]
    assert data["_themeCounts"]["experimental-method"] == 1
    assert data["_themeCounts"]["alchemy"] == 1
    # Formatting still preserved.
    assert '"domain": [1, 1],' in result


# ---------------------------------------------------------------------------
# 4. File still parses after every test
# ---------------------------------------------------------------------------


def test_result_is_valid_json(tmp_path: Path) -> None:
    """The persisted file is always valid JSON."""
    path = tmp_path / "taxonomy.json"
    _write(path, HAND_FORMATTED)

    reg = ThemeRegistry.load(path)
    reg.resolve_theme("experimental-method")
    reg.resolve_type("essay")
    reg.persist()

    result = _read(path)
    data = json.loads(result)
    assert "version" in data
    assert "experimental-method" in data["themes"]
    assert "essay" in data["types"]


# ---------------------------------------------------------------------------
# 5. Unwritable file still returns False
# ---------------------------------------------------------------------------


def test_unwritable_returns_false(tmp_path: Path) -> None:
    """An unwritable taxonomy.json returns False, no crash."""
    path = tmp_path / "taxonomy.json"
    _write(path, HAND_FORMATTED)

    reg = ThemeRegistry.load(path)
    reg.resolve_theme("experimental-method")

    os.chmod(path, stat.S_IREAD)
    ok = reg.persist()
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)

    assert not ok
    # Original file is untouched.
    assert _read(path) == HAND_FORMATTED


# ---------------------------------------------------------------------------
# 6. Fallback when the array key is absent from the file
# ---------------------------------------------------------------------------


def test_fallback_when_array_missing(tmp_path: Path) -> None:
    """Falls back to reserialisation when the array key is absent."""
    no_themes = (
        '{\n'
        '  "version": 1,\n'
        '  "types": ["note"]\n'
        '}\n'
    )
    path = tmp_path / "taxonomy.json"
    _write(path, no_themes)

    reg = ThemeRegistry.load(path)
    reg.resolve_theme("nationalism")
    assert reg.persist()

    result = _read(path)
    data = json.loads(result)
    assert "nationalism" in data["themes"]
    # The file was reformatted (fallback), but still valid.
    assert "types" in data


# ---------------------------------------------------------------------------
# 7. Existing _themeCounts entries are preserved
# ---------------------------------------------------------------------------


def test_existing_counts_preserved(tmp_path: Path) -> None:
    """Existing count entries are not overwritten by the surgical edit."""
    path = tmp_path / "taxonomy.json"
    _write(path, HAND_FORMATTED)

    reg = ThemeRegistry.load(path)
    reg.resolve_theme("experimental-method")
    reg.persist()

    data = json.loads(_read(path))
    # Existing counts are untouched.
    assert data["_themeCounts"]["epistemology"] == 3
    assert data["_themeCounts"]["optic"] == 1
    assert data["_themeCounts"]["revelation"] == 2
    # New count is appended.
    assert data["_themeCounts"]["experimental-method"] == 1


# ---------------------------------------------------------------------------
# 8. Type mint is surgical too
# ---------------------------------------------------------------------------


def test_type_mint_surgical(tmp_path: Path) -> None:
    """Minting a type uses the same surgical path."""
    path = tmp_path / "taxonomy.json"
    _write(path, HAND_FORMATTED)
    original = _read(path)

    reg = ThemeRegistry.load(path)
    reg.resolve_type("essay")
    assert reg.persist()

    result = _read(path)
    data = json.loads(result)
    assert "essay" in data["types"]
    assert data["_typeCounts"]["essay"] == 1
    # Formatting preserved.
    assert '"domain": [1, 1],' in result
    diff = _diff_count(original, result)
    assert diff <= 6


# ---------------------------------------------------------------------------
# 9. Keys the file carries are never lost
# ---------------------------------------------------------------------------


def test_all_keys_preserved(tmp_path: Path) -> None:
    """Every key in the original file survives a persist."""
    path = tmp_path / "taxonomy.json"
    _write(path, HAND_FORMATTED)
    original_keys = set(json.loads(HAND_FORMATTED).keys())

    reg = ThemeRegistry.load(path)
    reg.resolve_theme("experimental-method")
    reg.persist()

    result_keys = set(json.loads(_read(path)).keys())
    assert original_keys == result_keys
