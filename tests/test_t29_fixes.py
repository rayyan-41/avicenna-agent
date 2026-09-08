"""Tests for T29 — three defects found by a live six-domain run.

PART A — a topic containing a colon produces invalid YAML frontmatter.
PART B — a fenced duplicate frontmatter block survives unwrapping.
PART C — wikilink resolution strips links to non-existent notes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from avicenna.bus import EventBus, drain
from avicenna.events import Event, LogMessage
from avicenna.pipeline.context import RunContext, RunSpec
from avicenna.pipeline.stages import (
    _build_vault_notes_index,
    _extract_body_from_frontmatter_fence,
    _quote_yaml_scalar,
    _resolve_wikilinks,
    _unwrap_model_output,
    build_frontmatter,
)
from avicenna.providers.base import Completion
from avicenna.providers.fake import FakeProvider
from avicenna.vault.init_scaffold import init_vault
from avicenna.vault.vault import Vault


TOPIC = "The Epistemic Gap and the Necessity of Revelation"
HEADINGS = [
    "The Limits of Unaided Reason",
    "The Shape of the Gap",
    "Revelation as Closure",
]
BODY = "Finished prose for this section. " * 12


def _scaffold(tmp_path: Path) -> Vault:
    root = init_vault(tmp_path / "vault")
    return Vault.load(root)


def _make_context(vault: Vault, note_path: Path | None = None, topic: str = TOPIC) -> RunContext:
    spec = RunSpec(
        topic=topic,
        provider=FakeProvider(script=lambda s, m: Completion(text="")),
        vault=vault,
        bus=EventBus(),
        run_id="test-run",
    )
    ctx = RunContext(spec=spec)
    if note_path is not None:
        ctx.note_path = note_path
    return ctx


# =============================================================================
# PART A — YAML scalar quoting
# =============================================================================


class TestYamlScalarQuoting:
    """build_frontmatter must produce valid YAML for any topic."""

    def _parse_fm(self, text: str) -> dict[str, Any]:
        """Extract and parse the YAML frontmatter block."""
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        assert m is not None, f"no frontmatter found in: {text[:200]}"
        return yaml.safe_load(m.group(1))

    def test_colon_space_topic_round_trips(self, tmp_path: Path) -> None:
        """A topic containing ': ' must parse with the title intact."""
        topic = "How literary fiction creates a kind of knowledge: the way narrative shapes understanding"
        vault = _scaffold(tmp_path)
        ctx = _make_context(vault, topic=topic)
        ctx.domain = "literature"
        ctx.template = "general"
        fm = build_frontmatter(ctx, ["literature", "book"])
        parsed = self._parse_fm(fm)
        assert parsed["title"] == topic

    def test_leading_hash_round_trips(self, tmp_path: Path) -> None:
        topic = "#hashtag topic"
        vault = _scaffold(tmp_path)
        ctx = _make_context(vault, topic=topic)
        fm = build_frontmatter(ctx, [])
        parsed = self._parse_fm(fm)
        assert parsed["title"] == topic

    def test_double_quote_round_trips(self, tmp_path: Path) -> None:
        topic = 'He said "hello" to me'
        vault = _scaffold(tmp_path)
        ctx = _make_context(vault, topic=topic)
        fm = build_frontmatter(ctx, [])
        parsed = self._parse_fm(fm)
        assert parsed["title"] == topic

    def test_backslash_round_trips(self, tmp_path: Path) -> None:
        topic = r"Backslash \ in the title"
        vault = _scaffold(tmp_path)
        ctx = _make_context(vault, topic=topic)
        fm = build_frontmatter(ctx, [])
        parsed = self._parse_fm(fm)
        assert parsed["title"] == topic

    def test_trailing_space_round_trips(self, tmp_path: Path) -> None:
        topic = "Trailing space here "
        vault = _scaffold(tmp_path)
        ctx = _make_context(vault, topic=topic)
        fm = build_frontmatter(ctx, [])
        parsed = self._parse_fm(fm)
        assert parsed["title"] == topic

    def test_newline_round_trips(self, tmp_path: Path) -> None:
        topic = "Line one\nLine two"
        vault = _scaffold(tmp_path)
        ctx = _make_context(vault, topic=topic)
        fm = build_frontmatter(ctx, [])
        parsed = self._parse_fm(fm)
        # Newlines are collapsed to spaces.
        assert parsed["title"] == "Line one Line two"

    def test_numeric_topic_round_trips(self, tmp_path: Path) -> None:
        topic = "2024"
        vault = _scaffold(tmp_path)
        ctx = _make_context(vault, topic=topic)
        fm = build_frontmatter(ctx, [])
        parsed = self._parse_fm(fm)
        assert parsed["title"] == "2024"

    def test_ordinary_topic_is_unquoted(self, tmp_path: Path) -> None:
        """An ordinary topic must NOT be quoted (no gratuitous churn)."""
        topic = "The Epistemic Gap and the Necessity of Revelation"
        vault = _scaffold(tmp_path)
        ctx = _make_context(vault, topic=topic)
        fm = build_frontmatter(ctx, [])
        assert f"title: {topic}\n" in fm

    def test_tags_rendering_unchanged(self, tmp_path: Path) -> None:
        """tags: [a, b] rendering is unchanged by the quoting fix."""
        vault = _scaffold(tmp_path)
        ctx = _make_context(vault)
        fm = build_frontmatter(ctx, ["philosophy", "epistemology"])
        assert "tags: [philosophy, epistemology]\n" in fm

    def test_frontmatter_parses_with_yaml(self, tmp_path: Path) -> None:
        """The full frontmatter block parses with PyYAML."""
        topic = "A topic: with colons and #hashes"
        vault = _scaffold(tmp_path)
        ctx = _make_context(vault, topic=topic)
        ctx.domain = "philosophy"
        ctx.template = "general"
        fm = build_frontmatter(ctx, ["philosophy", "epistemology"])
        parsed = self._parse_fm(fm)
        assert parsed["title"] == topic
        assert parsed["domain"] == "philosophy"
        assert parsed["template"] == "general"
        assert parsed["tags"] == ["philosophy", "epistemology"]


# =============================================================================
# PART B — fenced duplicate frontmatter unwrapping
# =============================================================================


class TestFencedDuplicateFrontmatter:
    """_unwrap_model_output must strip a fenced body after frontmatter."""

    def test_exact_production_shape(self) -> None:
        """The exact shape from the live run: FM + fenced FM + body."""
        inner_body = "# What makes an object art\n\nSome prose here. " * 20
        produced = (
            "---\n"
            "date: YYYY-MM-DD\n"
            "status: complete\n"
            "tags: [art, art-theory, concept, aesthetics, artistic-technique, cli]\n"
            'note: ""\n'
            "---\n"
            "```markdown\n"
            "---\n"
            "date: YYYY-MM-DD\n"
            "status: complete\n"
            "tags: [art, art-theory, concept, aesthetics, artistic-technique, cli]\n"
            'note: ""\n'
            "---\n\n"
            f"{inner_body}"
            "```"
        )
        result, did_unwrap = _unwrap_model_output(produced)
        assert did_unwrap is True
        # Must have at least one FM block, no fence, body intact.
        assert result.count("---\n") >= 2, "must have at least one FM block"
        assert "```" not in result
        assert "# What makes an object art" in result

    def test_legitimate_mid_note_code_block_unchanged(self) -> None:
        """A code block inside the note followed by prose must not be stripped."""
        note = (
            "---\ntitle: test\n---\n\n"
            "# Title\n\nSome prose.\n\n"
            "```python\nprint('hello')\n```\n\n"
            "More prose after the code block.\n"
        )
        result, did_unwrap = _unwrap_model_output(note)
        assert result == note
        assert did_unwrap is False

    def test_fence_without_frontmatter_still_unwrapped(self) -> None:
        """A fence that opens the output with no preceding FM: existing behaviour."""
        inner = "---\ntitle: test\n---\n\n# Title\n\nBody."
        wrapped = "```markdown\n" + inner + "```"
        result, _ = _unwrap_model_output(wrapped)
        assert "---\ntitle: test\n---" in result

    def test_no_fence_unchanged(self) -> None:
        text = "---\ntitle: test\n---\n\n# Title\n\nBody."
        result, did_unwrap = _unwrap_model_output(text)
        assert result == text
        assert did_unwrap is False

    def test_idempotent(self) -> None:
        produced = (
            "---\ntitle: test\n---\n"
            "```markdown\n"
            "---\ntitle: test\n---\n\n# Title\n\nBody."
            "```"
        )
        once_text, _ = _unwrap_model_output(produced)
        twice_text, _ = _unwrap_model_output(once_text)
        assert once_text == twice_text

    def test_tilde_fence_also_unwrapped(self) -> None:
        produced = (
            "---\ntitle: test\n---\n"
            "~~~markdown\n"
            "---\ntitle: test\n---\n\n# Title\n\nBody."
            "~~~"
        )
        result, did_unwrap = _unwrap_model_output(produced)
        assert did_unwrap is True
        assert "~~~" not in result
        assert "# Title" in result

    @pytest.mark.asyncio()
    async def test_warning_emitted_in_write_back(self, tmp_path: Path) -> None:
        """_write_back emits a warning when the fenced-body unwrap fires."""
        from avicenna.pipeline.stages import _write_back
        from avicenna.pipeline.context import RunSpec

        vault = _scaffold(tmp_path)
        note_path = tmp_path / "vault" / "Art" / "test.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        fm = "---\ntitle: test\ntags: []\n---\n"
        body = "# Title\n\nBody text. " * 50
        note_path.write_text(fm + body, encoding="utf-8", newline="\n")
        spec = RunSpec(
            topic=TOPIC,
            provider=FakeProvider(script=lambda s, m: Completion(text="")),
            vault=vault,
            bus=EventBus(),
            run_id="test-run",
        )
        ctx = RunContext(spec=spec)
        ctx.note_path = note_path
        bus = ctx.spec.bus
        queue = bus.subscribe()
        produced = (
            fm
            + "```markdown\n"
            + fm + body
            + "```"
        )
        await _write_back(ctx, "formatter", produced)
        await bus.close()
        events: list[Event] = []
        async for ev in drain(queue):
            events.append(ev)
        warnings = [e for e in events if isinstance(e, LogMessage) and "model defect" in e.text]
        assert len(warnings) >= 1


# =============================================================================
# PART C — wikilink validation
# =============================================================================


class TestWikilinkResolution:
    """_resolve_wikilinks drops links to non-existent notes."""

    @pytest.fixture()
    def vault_with_notes(self, tmp_path: Path) -> tuple[Vault, Path]:
        """Create a vault with a few notes for resolution testing."""
        vault = _scaffold(tmp_path)
        root = vault.root
        # Create some notes in the vault.
        art_dir = root / "Art"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "Philosophy of Mind.md").write_text("# Philosophy of Mind\n\nBody.", encoding="utf-8", newline="\n")
        (art_dir / "Ibn Sina.md").write_text("# Ibn Sina\n\nBody.", encoding="utf-8", newline="\n")
        (art_dir / "Epistemology.md").write_text("# Epistemology\n\nBody.", encoding="utf-8", newline="\n")
        # A note that will be the "current" note (excluded from index).
        current = art_dir / "Current Note.md"
        current.write_text("---\ntitle: test\ntags: []\n---\n\n# Current\n\nBody.", encoding="utf-8", newline="\n")
        return vault, current

    @pytest.mark.asyncio()
    async def test_link_to_real_note_survives(self, vault_with_notes: tuple[Vault, Path]) -> None:
        vault, note_path = vault_with_notes
        ctx = _make_context(vault, note_path)
        text = "See also [[Philosophy of Mind]] for more."
        result = await _resolve_wikilinks(text, vault, note_path, ctx)
        assert "[[Philosophy of Mind]]" in result

    @pytest.mark.asyncio()
    async def test_link_to_nonexistent_note_unwrapped(self, vault_with_notes: tuple[Vault, Path]) -> None:
        vault, note_path = vault_with_notes
        ctx = _make_context(vault, note_path)
        text = "The Role of Intention: Why Purpose Matters in [[Role of Intention: Why Purpose Matters]] here."
        result = await _resolve_wikilinks(text, vault, note_path, ctx)
        assert "[[Role of Intention: Why Purpose Matters]]" not in result
        assert "Role of Intention: Why Purpose Matters" in result
        # Surrounding sentence unchanged.
        assert "The Role of Intention" in result
        assert "here." in result

    @pytest.mark.asyncio()
    async def test_heading_link_untouched(self, vault_with_notes: tuple[Vault, Path]) -> None:
        vault, note_path = vault_with_notes
        ctx = _make_context(vault, note_path)
        text = "See the [[#Introduction]] section above."
        result = await _resolve_wikilinks(text, vault, note_path, ctx)
        assert result == text

    @pytest.mark.asyncio()
    async def test_alias_link_to_real_note_survives(self, vault_with_notes: tuple[Vault, Path]) -> None:
        vault, note_path = vault_with_notes
        ctx = _make_context(vault, note_path)
        text = "See [[Philosophy of Mind|this note]] for details."
        result = await _resolve_wikilinks(text, vault, note_path, ctx)
        assert "[[Philosophy of Mind|this note]]" in result

    @pytest.mark.asyncio()
    async def test_case_insensitive_resolution(self, vault_with_notes: tuple[Vault, Path]) -> None:
        vault, note_path = vault_with_notes
        ctx = _make_context(vault, note_path)
        text = "See [[philosophy of mind]] for details."
        result = await _resolve_wikilinks(text, vault, note_path, ctx)
        assert "[[philosophy of mind]]" in result

    @pytest.mark.asyncio()
    async def test_warning_with_dropped_and_resolved_counts(self, vault_with_notes: tuple[Vault, Path]) -> None:
        vault, note_path = vault_with_notes
        ctx = _make_context(vault, note_path)
        bus = ctx.spec.bus
        queue = bus.subscribe()
        text = "See [[Philosophy of Mind]] and [[Nonexistent Thing]]."
        await _resolve_wikilinks(text, vault, note_path, ctx)
        await bus.close()
        events: list[Event] = []
        async for ev in drain(queue):
            events.append(ev)
        warnings = [e for e in events if isinstance(e, LogMessage) and "model produced" in e.text]
        assert len(warnings) >= 1
        assert "1" in warnings[0].text  # 1 dropped
        info = [e for e in events if isinstance(e, LogMessage) and "resolved" in e.text]
        assert len(info) >= 1
        assert "1 resolved" in info[0].text
        assert "1 dropped" in info[0].text

    @pytest.mark.asyncio()
    async def test_no_links_unchanged(self, vault_with_notes: tuple[Vault, Path]) -> None:
        vault, note_path = vault_with_notes
        ctx = _make_context(vault, note_path)
        text = "This note has no wikilinks at all."
        result = await _resolve_wikilinks(text, vault, note_path, ctx)
        assert result == text
