"""Tests for the entity vocabulary: reading it, recording it, reconciling it.

Entities carry connection in this vault, and until the taxonomy recorded them
the harness could not know that a vault writes ``galileo-galilei`` rather than
``galilei`` -- so a note tagged with the derived form never joined the one that
already existed.
"""

from __future__ import annotations

import json
from pathlib import Path

from avicenna.vault.entities import (
    entity_slice,
    iter_notes,
    parse_frontmatter_tags,
    scan_vault_entities,
)
from avicenna.vault.registry import ThemeRegistry

THEMES = ["philosophy", "epistemology", "metaphysics"]


def _note(path: Path, tags: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = ", ".join(tags)
    path.write_text(
        f"---\ndate: 2026-09-09\nstatus: complete\ntags: [{rendered}]\n"
        f'note: ""\n---\n\nBody.\n',
        encoding="utf-8",
        newline="\n",
    )


def _registry(tmp_path: Path, **raw: object) -> ThemeRegistry:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "taxonomy.json"
    base: dict[str, object] = {"themes": list(THEMES), "types": ["concept"]}
    base.update(raw)
    path.write_text(json.dumps(base, indent=2), encoding="utf-8", newline="\n")
    return ThemeRegistry.load(path)


# ---------------------------------------------------------------------------
# Reading frontmatter
# ---------------------------------------------------------------------------


class TestParseFrontmatterTags:
    def test_reads_the_inline_array_in_order(self, tmp_path: Path) -> None:
        """Order is the contract: domain first, marker last."""
        p = tmp_path / "n.md"
        _note(p, ["reason", "essay", "concept", "philosophy", "kant", "cli"])
        assert parse_frontmatter_tags(p.read_text("utf-8")) == [
            "reason", "essay", "concept", "philosophy", "kant", "cli",
        ]

    def test_no_frontmatter_is_not_an_error(self) -> None:
        """A half-written note is still a note."""
        assert parse_frontmatter_tags("# Just a heading\n") == []

    def test_frontmatter_without_tags(self) -> None:
        assert parse_frontmatter_tags('---\ndate: 2026-09-09\n---\n\nBody.\n') == []

    def test_quotes_are_stripped(self) -> None:
        text = '---\ntags: ["reason", \'kant\', cli]\n---\n\nBody.\n'
        assert parse_frontmatter_tags(text) == ["reason", "kant", "cli"]

    def test_only_the_leading_frontmatter_counts(self) -> None:
        """A `---` rule later in the body is not a second frontmatter block."""
        text = (
            "---\ntags: [reason, kant, cli]\n---\n\n"
            "Body.\n\n---\ntags: [not, real, cli]\n---\n"
        )
        assert parse_frontmatter_tags(text) == ["reason", "kant", "cli"]


# ---------------------------------------------------------------------------
# The slot rule
# ---------------------------------------------------------------------------


class TestEntitySlice:
    def test_tail_tags_that_are_not_themes(self) -> None:
        tags = ["reason", "essay", "concept", "philosophy", "kant", "hume", "cli"]
        assert entity_slice(tags, themes=THEMES) == ["kant", "hume"]

    def test_themes_are_excluded(self) -> None:
        tags = ["reason", "essay", "concept", "philosophy", "epistemology", "cli"]
        assert entity_slice(tags, themes=THEMES) == []

    def test_the_marker_is_never_an_entity(self) -> None:
        """`cli` is the marker slot, not a figure."""
        tags = ["reason", "essay", "concept", "philosophy", "kant", "cli"]
        assert "cli" not in entity_slice(tags, themes=THEMES)

    def test_domain_category_and_type_are_never_entities(self) -> None:
        """They are positional, so they are excluded by slot, not by lookup."""
        tags = ["reason", "essay", "concept", "philosophy", "kant", "cli"]
        got = entity_slice(tags, themes=THEMES)
        assert got == ["kant"]

    def test_too_short_an_array_has_no_entity_slot(self) -> None:
        """A MOC carries [domain, moc, cli] and names nobody."""
        assert entity_slice(["art", "moc", "cli"], themes=THEMES) == []

    def test_empty(self) -> None:
        assert entity_slice([], themes=THEMES) == []


# ---------------------------------------------------------------------------
# Scanning a vault
# ---------------------------------------------------------------------------


class TestScanVaultEntities:
    def test_counts_notes_per_entity(self, tmp_path: Path) -> None:
        _note(tmp_path / "Reason" / "a.md",
              ["reason", "essay", "concept", "philosophy", "kant", "cli"])
        _note(tmp_path / "Reason" / "b.md",
              ["reason", "essay", "concept", "philosophy", "kant", "hume", "cli"])
        assert scan_vault_entities(tmp_path, themes=THEMES) == {"kant": 2, "hume": 1}

    def test_harness_and_app_directories_are_skipped(self, tmp_path: Path) -> None:
        """`.agents` is the harness's own state and `.obsidian` is the app's."""
        _note(tmp_path / "Reason" / "a.md",
              ["reason", "essay", "concept", "philosophy", "kant", "cli"])
        _note(tmp_path / ".agents" / "template.md",
              ["reason", "essay", "concept", "philosophy", "ghost", "cli"])
        _note(tmp_path / ".obsidian" / "note.md",
              ["reason", "essay", "concept", "philosophy", "phantom", "cli"])
        assert scan_vault_entities(tmp_path, themes=THEMES) == {"kant": 1}

    def test_empty_vault(self, tmp_path: Path) -> None:
        assert scan_vault_entities(tmp_path, themes=THEMES) == {}

    def test_iter_notes_finds_markdown_only(self, tmp_path: Path) -> None:
        _note(tmp_path / "a.md", ["reason", "essay", "concept", "philosophy", "x", "cli"])
        (tmp_path / "b.txt").write_text("not a note", encoding="utf-8")
        assert [p.name for p in iter_notes(tmp_path)] == ["a.md"]


# ---------------------------------------------------------------------------
# Reconciliation — the divergence this exists to close
# ---------------------------------------------------------------------------


class TestResolveEntity:
    def test_bare_surname_joins_the_recorded_full_form(self, tmp_path: Path) -> None:
        """The exact divergence: derivation yields `galilei` from the topic.

        The vault writes `galileo-galilei`, and nothing in the string says so.
        Without the recorded form these are two entity tags and the note fails
        to join the one that exists, which is the entire purpose of the tag.
        """
        reg = _registry(tmp_path, entities=["galileo-galilei"])
        assert reg.resolve_entity("galilei") == ("galileo-galilei", False)

    def test_full_form_joins_the_recorded_surname(self, tmp_path: Path) -> None:
        """The other direction: a model proposing the full name."""
        reg = _registry(tmp_path, entities=["kant"])
        assert reg.resolve_entity("immanuel-kant") == ("kant", False)

    def test_exact_match_reuses(self, tmp_path: Path) -> None:
        reg = _registry(tmp_path, entities=["kant"])
        assert reg.resolve_entity("kant") == ("kant", False)

    def test_separator_and_case_variants_reuse(self, tmp_path: Path) -> None:
        reg = _registry(tmp_path, entities=["ibn-sina"])
        assert reg.resolve_entity("Ibn Sina") == ("ibn-sina", False)

    def test_two_full_names_sharing_a_surname_stay_distinct(
        self, tmp_path: Path,
    ) -> None:
        """`john-mill` and `james-mill` are two people, not one.

        This is why the match requires one side to be a bare surname: matching
        on the last segment alone would merge them, and a wrong merge destroys
        a distinction silently.
        """
        reg = _registry(tmp_path, entities=["john-mill", "james-mill"])
        assert reg.resolve_entity("james-mill") == ("james-mill", False)
        assert reg.resolve_entity("john-mill") == ("john-mill", False)

    def test_an_ambiguous_bare_surname_stands_alone(self, tmp_path: Path) -> None:
        """With both Mills on record, `mill` matches neither.

        Guessing which was meant is worse than leaving it: the note stays
        where it is rather than joining the wrong figure.
        """
        reg = _registry(tmp_path, entities=["john-mill", "james-mill"])
        assert reg.resolve_entity("mill") == ("mill", True)

    def test_an_unknown_entity_is_always_accepted(self, tmp_path: Path) -> None:
        """Open vocabulary: this is a record, never a constraint."""
        reg = _registry(tmp_path, entities=["kant"])
        assert reg.resolve_entity("schopenhauer") == ("schopenhauer", True)

    def test_a_vault_with_no_entities_key(self, tmp_path: Path) -> None:
        """Every vault written before this feature existed."""
        reg = _registry(tmp_path)
        assert reg.entity_keys() == []
        assert reg.resolve_entity("kant") == ("kant", True)

    def test_entities_never_reach_the_theme_registry(self, tmp_path: Path) -> None:
        """The defect this whole seam exists to prevent."""
        reg = _registry(tmp_path)
        reg.resolve_entity("kant")
        assert "kant" not in reg.theme_keys()
        assert "kant" in reg.entity_keys()


# ---------------------------------------------------------------------------
# Persistence — creating a key the file has never had
# ---------------------------------------------------------------------------


class TestPersistEntities:
    def test_creates_the_array_without_reserialising(self, tmp_path: Path) -> None:
        """A missing key must not send the writer to the fallback.

        Falling back reserialises the whole document, which expands every
        inline array and drops every blank line -- the 118-line diff on a
        hand-authored file that the surgical writer exists to prevent.
        """
        tmp_path.mkdir(parents=True, exist_ok=True)
        path = tmp_path / "taxonomy.json"
        path.write_text(
            '{\n'
            '  "$comment": "hand authored",\n'
            '\n'
            '  "types": ["concept", "essay"],\n'
            '  "themes": [\n'
            '    "philosophy",\n'
            '    "epistemology"\n'
            '  ],\n'
            '  "reservedModifiers": ["incomplete"]\n'
            '}\n',
            encoding="utf-8", newline="\n",
        )
        before = path.read_text("utf-8")

        reg = ThemeRegistry.load(path)
        reg.resolve_entity("kant")
        assert reg.persist()
        after = path.read_text("utf-8")

        data = json.loads(after)
        assert data["entities"] == ["kant"]
        # The inline arrays stayed inline and the comment survived.
        assert '"types": ["concept", "essay"]' in after
        assert '"reservedModifiers": ["incomplete"]' in after
        assert '"$comment": "hand authored"' in after
        # The blank line the author put there is still there.
        assert '"$comment": "hand authored",\n\n' in after
        # And nothing was lost.
        assert set(json.loads(before)) <= set(data)

    def test_appends_to_an_existing_array(self, tmp_path: Path) -> None:
        reg = _registry(tmp_path, entities=["kant"])
        reg.resolve_entity("hume")
        assert reg.persist()
        data = json.loads((tmp_path / "taxonomy.json").read_text("utf-8"))
        assert data["entities"] == ["kant", "hume"]

    def test_reconciled_entities_are_not_minted(self, tmp_path: Path) -> None:
        """Reconciling is the point: it must not grow the record."""
        reg = _registry(tmp_path, entities=["galileo-galilei"])
        reg.resolve_entity("galilei")
        assert reg.persist()
        data = json.loads((tmp_path / "taxonomy.json").read_text("utf-8"))
        assert data["entities"] == ["galileo-galilei"]
