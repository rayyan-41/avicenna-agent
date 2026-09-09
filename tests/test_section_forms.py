"""Tests for section form markers: [Table] and [Mermaid Diagram].

The benchmark note's pre-flight plan declared forms for some sections:

    #6. [Table] Comparative Matrix...
    #9. [Mermaid Diagram] The Architecture of Revelation...

A form marker is parsed out of the heading, stored as metadata parallel to
the headings tuple, and changes the prompt the section agent receives.
The heading reaching the note must be clean — no leaked ``[Table]`` prefix
in a TOC.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from avicenna.bus import EventBus, drain
from avicenna.events import Event, PreflightDeclared
from avicenna.pipeline.preflight import PreflightDeclaration, parse_form, parse_preflight
from avicenna.pipeline.run import execute_run
from avicenna.pipeline.sections import SECTION_PROMPT, _FORM_SUFFIXES, _MERMAID_SUFFIX, _TABLE_SUFFIX
from avicenna.providers.base import Completion
from avicenna.providers.fake import FakeProvider
from avicenna.vault.init_scaffold import init_vault
from avicenna.vault.vault import Vault


# --- parse_form unit tests ---------------------------------------------------


class TestParseForm:
    def test_table_prefix_extracted(self) -> None:
        title, form = parse_form("[Table] Comparative Matrix")
        assert title == "Comparative Matrix"
        assert form == "table"

    def test_mermaid_prefix_extracted(self) -> None:
        title, form = parse_form("[Mermaid Diagram] The Architecture of Revelation")
        assert title == "The Architecture of Revelation"
        assert form == "mermaid"

    def test_bare_mermaid_prefix_extracted(self) -> None:
        title, form = parse_form("[Mermaid] System Overview")
        assert title == "System Overview"
        assert form == "mermaid"

    def test_case_insensitive_matching(self) -> None:
        for variant in ("[table]", "[TABLE]", "[Table]", "[tAbLe]"):
            title, form = parse_form(f"{variant} Foo")
            assert title == "Foo", f"{variant} did not strip"
            assert form == "table", f"{variant} did not match table"

    def test_case_insensitive_mermaid(self) -> None:
        for variant in ("[mermaid diagram]", "[MERMAID DIAGRAM]", "[Mermaid Diagram]"):
            title, form = parse_form(f"{variant} Bar")
            assert title == "Bar"
            assert form == "mermaid"

    def test_unknown_prefix_stays_in_title(self) -> None:
        """A model inventing [Chart] must not produce a heading with a missing word."""
        title, form = parse_form("[Chart] Revenue Over Time")
        assert title == "[Chart] Revenue Over Time"
        assert form is None

    def test_unknown_prefix_table_of_contents(self) -> None:
        """[Table of Contents] is not a recognised form marker."""
        title, form = parse_form("[Table of Contents] Introduction")
        assert title == "[Table of Contents] Introduction"
        assert form is None

    def test_no_prefix(self) -> None:
        title, form = parse_form("The Limits of Unaided Reason")
        assert title == "The Limits of Unaided Reason"
        assert form is None

    def test_bracket_at_end_not_a_prefix(self) -> None:
        """A bracket that is not a prefix (no trailing space) is not a marker."""
        title, form = parse_form("Section [draft]")
        assert title == "Section [draft]"
        assert form is None


# --- parse_preflight integration tests ---------------------------------------


class TestPreflightForms:
    def _json_preflight(self, headings: list[str]) -> str:
        payload = {
            "topic": "Test Topic",
            "domain": "general",
            "template": "general",
            "headings": headings,
            "target_words": 6000,
            "slug": "test-topic",
        }
        return "Plan:\n```json\n" + json.dumps(payload) + "\n```"

    def test_json_preflight_extracts_forms(self, tmp_path: Path) -> None:
        text = self._json_preflight([
            "The Limits of Unaided Reason",
            "[Table] Comparative Matrix",
            "[Mermaid Diagram] The Architecture of Revelation",
            "Revelation as Closure",
        ])
        decl, used_json = parse_preflight(
            text, default_domain="general", default_topic="Test", tmp_dir=tmp_path,
        )
        assert used_json is True
        assert decl.headings == (
            "The Limits of Unaided Reason",
            "Comparative Matrix",
            "The Architecture of Revelation",
            "Revelation as Closure",
        )
        assert decl.forms == (None, "table", "mermaid", None)

    def test_prose_preflight_extracts_forms(self, tmp_path: Path) -> None:
        text = (
            "Topic: Test\n"
            "Domain: general\n"
            "Template: general\n"
            "Target words: 6000\n"
            "Slug: test\n"
            "Headings:\n"
            "- The Limits of Unaided Reason\n"
            "- [Table] Comparative Matrix\n"
            "- [Mermaid Diagram] The Architecture of Revelation\n"
            "- Revelation as Closure\n"
        )
        decl, used_json = parse_preflight(
            text, default_domain="general", default_topic="Test", tmp_dir=tmp_path,
        )
        assert used_json is False
        assert decl.headings == (
            "The Limits of Unaided Reason",
            "Comparative Matrix",
            "The Architecture of Revelation",
            "Revelation as Closure",
        )
        assert decl.forms == (None, "table", "mermaid", None)

    def test_unknown_prefix_survives_in_json(self, tmp_path: Path) -> None:
        text = self._json_preflight([
            "[Chart] Revenue Over Time",
            "Normal Heading",
        ])
        decl, _ = parse_preflight(
            text, default_domain="general", default_topic="Test", tmp_dir=tmp_path,
        )
        assert decl.headings == ("[Chart] Revenue Over Time", "Normal Heading")
        assert decl.forms == (None, None)

    def test_clean_headings_have_no_forms(self, tmp_path: Path) -> None:
        text = self._json_preflight([
            "The Limits of Unaided Reason",
            "The Shape of the Gap",
        ])
        decl, _ = parse_preflight(
            text, default_domain="general", default_topic="Test", tmp_dir=tmp_path,
        )
        assert decl.headings == ("The Limits of Unaided Reason", "The Shape of the Gap")
        assert decl.forms == (None, None)


# --- prompt assembly tests ---------------------------------------------------


class TestFormPrompts:
    def test_table_prompt_differs_from_prose(self) -> None:
        prose = SECTION_PROMPT.format(
            topic="T", heading="H", index=1, total=3,
            outline="1. H", words=1000, domain="general",
        )
        table = prose.rstrip() + "\n" + _TABLE_SUFFIX
        assert table != prose
        assert "comparative table" in table.lower()

    def test_mermaid_prompt_differs_from_prose(self) -> None:
        prose = SECTION_PROMPT.format(
            topic="T", heading="H", index=1, total=3,
            outline="1. H", words=1000, domain="general",
        )
        mermaid = prose.rstrip() + "\n" + _MERMAID_SUFFIX
        assert mermaid != prose
        assert "mermaid" in mermaid.lower()
        assert "```mermaid" in mermaid

    def test_form_suffixes_cover_all_forms(self) -> None:
        """Every value in _FORM_SUFFIXES must be a non-empty string."""
        for key, suffix in _FORM_SUFFIXES.items():
            assert isinstance(key, str) and key, f"empty key"
            assert isinstance(suffix, str) and suffix.strip(), f"empty suffix for {key}"


# --- word count tests --------------------------------------------------------


class TestFormWordCount:
    async def test_formed_sections_excluded_from_expected_total(self, tmp_path: Path) -> None:
        """A note with a table and a mermaid section must not count those
        against the prose word target."""
        from avicenna.pipeline.context import RunContext, RunSpec
        from avicenna.pipeline.stages import WordCountStage

        # Build a minimal RunContext with formed sections.
        root = init_vault(tmp_path / "vault")
        vault = Vault.load(root)
        provider = FakeProvider(script=[])
        bus = EventBus()
        spec = RunSpec(topic="T", vault=vault, provider=provider,
                       bus=bus, run_id="test")
        ctx = RunContext(spec=spec)
        ctx.headings = ["Prose One", "Table Section", "Mermaid Section", "Prose Two"]
        ctx.section_forms = [None, "table", "mermaid", None]
        ctx.slug = "test"
        ctx.total_words = 2000
        # Write a fake note so WordCountStage can count words.
        note = tmp_path / "note.md"
        note.write_text("# T\n\n" + "word " * 2000, encoding="utf-8")
        ctx.note_path = note

        stage = WordCountStage()
        await stage.run(ctx)

        # With 1000 words_per_heading default and 4 headings, old expected
        # would be 4000.  With 2 prose headings, expected is 2000.
        # ctx.total_words is 2000, so no "below guidance" warning.
        events: list[Event] = []
        queue = bus.subscribe()
        await bus.close()
        async for ev in drain(queue):
            events.append(ev)
        from avicenna.events import LogMessage
        below = [e for e in events if isinstance(e, LogMessage) and "below guidance" in e.text]
        assert below == [], f"spurious 'below guidance' warning with formed sections: {below}"

    async def test_all_prose_headings_count_normally(self, tmp_path: Path) -> None:
        """Without forms, the expected total is target * headings (old behaviour)."""
        from avicenna.pipeline.context import RunContext, RunSpec
        from avicenna.pipeline.stages import WordCountStage

        root = init_vault(tmp_path / "vault")
        vault = Vault.load(root)
        provider = FakeProvider(script=[])
        bus = EventBus()
        spec = RunSpec(topic="T", vault=vault, provider=provider,
                       bus=bus, run_id="test")
        ctx = RunContext(spec=spec)
        ctx.headings = ["A", "B", "C"]
        ctx.section_forms = [None, None, None]
        ctx.slug = "test"
        ctx.total_words = 3000
        note = tmp_path / "note.md"
        note.write_text("# T\n\n" + "word " * 3000, encoding="utf-8")
        ctx.note_path = note

        stage = WordCountStage()
        await stage.run(ctx)
        # expected = 1000 * 3 = 3000, actual = 3000 → no warning.
        events: list[Event] = []
        queue = bus.subscribe()
        await bus.close()
        async for ev in drain(queue):
            events.append(ev)
        from avicenna.events import LogMessage
        below = [e for e in events if isinstance(e, LogMessage) and "below guidance" in e.text]
        assert below == []


# --- end-to-end pipeline test ------------------------------------------------


TOPIC = "The Epistemic Gap and the Necessity of Revelation"
HEADINGS_WITH_FORMS = [
    "The Limits of Unaided Reason",
    "[Table] Comparative Matrix",
    "[Mermaid Diagram] The Architecture of Revelation",
    "Revelation as Closure",
]
BODY = "Finished prose for this section. " * 12


def _declaration_with_forms(**over: Any) -> str:
    payload = {
        "topic": TOPIC,
        "domain": "general",
        "template": "general",
        "headings": HEADINGS_WITH_FORMS,
        "target_words": 6000,
        "slug": "epistemic-gap",
    }
    payload.update(over)
    return "Here is the plan.\n```json\n" + json.dumps(payload) + "\n```"


def _script_with_forms(system: str, messages: list[Completion]) -> Completion:
    prompt = messages[-1].content if messages else ""
    if "pre-flight plan" in prompt or "JSON fence" in prompt:
        return Completion(text=_declaration_with_forms())
    if "labelled slots" in prompt:
        return Completion(text="Reviewed.\nTAGS: philosophy, epistemology, revelation")
    if "genuinely related" in prompt:
        note = prompt.split("\n\n", 1)[-1]
        return Completion(text=note)
    if "formatting corrected" in prompt:
        return Completion(text=prompt.split("\n\n", 1)[-1])
    if "Assemble this into one continuous note" in prompt:
        return Completion(text=prompt.split("\n\nTopic:")[0])
    if "comparative table" in prompt.lower():
        return Completion(text="| Col A | Col B |\n| --- | --- |\n| a | b |")
    if "mermaid" in prompt.lower():
        return Completion(text="```mermaid\nflowchart TD\n    A --> B\n```")
    return Completion(text=BODY.strip())


def _scaffold(tmp_path: Path) -> Vault:
    root = init_vault(tmp_path / "vault")
    return Vault.load(root)


def _note(vault: Vault) -> Path:
    notes = [
        p for p in vault.root.rglob("*.md")
        if ".agents" not in p.parts and p.name != "AGENTS.md"
    ]
    assert len(notes) == 1, f"expected exactly one note, found {notes}"
    return notes[0]


async def test_e2e_formed_sections_clean_headings(tmp_path: Path) -> None:
    """The headings reaching the note must be clean — no [Table] prefix."""
    vault = _scaffold(tmp_path)
    bus = EventBus()
    queue = bus.subscribe()
    await execute_run(
        TOPIC, FakeProvider(script=_script_with_forms), vault,
        bus=bus, concurrency=2,
    )
    await bus.close()

    events: list[Event] = []
    async for ev in drain(queue):
        events.append(ev)

    # The PreflightDeclared event must carry clean headings.
    preflight = [e for e in events if isinstance(e, PreflightDeclared)]
    assert len(preflight) == 1
    headings = preflight[0].headings
    assert "Comparative Matrix" in headings
    assert "The Architecture of Revelation" in headings
    for h in headings:
        assert not h.startswith("["), f"form marker leaked into heading: {h!r}"

    # The note on disk must have clean headings too.  The assertion is
    # deliberately agnostic about heading level and numbering: the structure
    # pass owns those (it emits "### 2. Comparative Matrix"), and this test is
    # about the form marker not leaking, not about how headings are rendered.
    # Pinning the literal "## " here made this test fail the moment numbering
    # landed, on a note whose headings were in fact correct.
    body = _note(vault).read_text(encoding="utf-8")
    note_headings = [m.group(1).strip() for m in re.finditer(r"^#{2,6}\s+(.*)$", body, re.M)]
    assert any(h.endswith("Comparative Matrix") for h in note_headings), note_headings
    assert any(h.endswith("The Architecture of Revelation") for h in note_headings), note_headings
    for h in note_headings:
        assert "[" not in h, f"form marker leaked into a note heading: {h!r}"
    assert "[Table]" not in body.split("---", 2)[-1]
    assert "[Mermaid Diagram]" not in body.split("---", 2)[-1]
