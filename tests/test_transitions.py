"""Tests for the transition generation system.

The weaver was redesigned 2026-09-09 from a whole-note round-trip to a
transition-only stage.  A live run on 2026-09-08 destroyed 72% of a 9,000-word
note when the weaver replaced the entire body.  The rule going forward is
absolute: the note body must never round-trip through a model.

These tests cover the pure functions in avicenna.pipeline.transitions and the
TransitionStage integration with FakeProvider.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from avicenna.bus import EventBus, drain
from avicenna.events import Event, LogMessage, RunFailed, TransitionsApplied
from avicenna.pipeline.context import RunContext
from avicenna.pipeline.run import execute_run
from avicenna.pipeline.transitions import (
    NoteSkeleton,
    SectionSkeleton,
    build_transition_prompt,
    extract_skeleton,
    parse_transitions,
    splice_transitions,
    validate_transition,
)
from avicenna.providers.base import Completion
from avicenna.providers.fake import FakeProvider
from avicenna.vault.init_scaffold import init_vault
from avicenna.vault.vault import Vault


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TOPIC = "The Epistemic Gap and the Necessity of Revelation"
HEADINGS = [
    "The Limits of Unaided Reason",
    "The Shape of the Gap",
    "Revelation as Closure",
]
BODY = "Finished prose for this section. " * 12


def _declaration(**over: Any) -> str:
    payload = {
        "topic": TOPIC,
        "domain": "general",
        "template": "general",
        "headings": HEADINGS,
        "target_words": 900,
        "slug": "epistemic-gap",
    }
    payload.update(over)
    return "Here is the plan.\n```json\n" + json.dumps(payload) + "\n```"


def _scaffold(tmp_path: Path, *, agents: tuple[str, ...] = ()) -> Vault:
    root = init_vault(tmp_path / "vault")
    for name in agents:
        (root / ".agents" / "agents" / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: Pipeline agent {name}\n"
            f"type: pipeline\nstage: 1\ninvocation: /agent {name}\n---\n\n"
            f"You are the {name}.\n",
            encoding="utf-8",
            newline="\n",
        )
    return Vault.load(root)


# --- scripts ----------------------------------------------------------------

def _transition_clean(system: str, messages: list[Any]) -> Completion:
    """Returns well-formed numbered transitions for the transition stage."""
    prompt = messages[-1].content if messages else ""
    if "transition" in prompt.lower() and "section 1" in prompt:
        lines = []
        for i, h in enumerate(HEADINGS, 1):
            lines.append(f"{i}. Building on this foundation, we turn to {h.lower()}.")
        return Completion(text="\n".join(lines))
    return Completion(text="")


def _transition_off_topic(system: str, messages: list[Any]) -> Completion:
    """Returns one on-topic and one off-topic transition."""
    prompt = messages[-1].content if messages else ""
    if "transition" in prompt.lower() and "section 1" in prompt:
        return Completion(text=(
            "1. The epistemic gap reveals the limits of unaided reason.\n"
            "2. Cooking pasta requires boiling water and salt.\n"
            "3. Revelation provides the closure reason alone cannot reach."
        ))
    return Completion(text="")


def _transition_malformed(system: str, messages: list[Any]) -> Completion:
    """Returns a mix of valid and malformed transitions."""
    prompt = messages[-1].content if messages else ""
    if "transition" in prompt.lower() and "section 1" in prompt:
        return Completion(text=(
            "1. A valid transition about the epistemic gap and revelation.\n"
            "2. A transition with a [[wikilink]] to a non-existent note.\n"
            "3. Another valid transition about revelation and reason."
        ))
    return Completion(text="")


def _transition_multi_line(system: str, messages: list[Any]) -> Completion:
    """Returns a transition with embedded line breaks."""
    prompt = messages[-1].content if messages else ""
    if "transition" in prompt.lower() and "section 1" in prompt:
        return Completion(text=(
            "1. A valid transition about epistemology and the gap.\n"
            "2. This transition has\na line break inside it.\n"
            "3. Another valid transition about revelation and closure."
        ))
    return Completion(text="")


def _transition_empty(system: str, messages: list[Any]) -> Completion:
    """Returns no transitions (empty response from weaver)."""
    prompt = messages[-1].content if messages else ""
    if "transition" in prompt.lower() and "section 1" in prompt:
        return Completion(text="")
    return Completion(text="")


def _transition_error(system: str, messages: list[Any]) -> Completion:
    """Raises during the transition stage."""
    prompt = messages[-1].content if messages else ""
    if "transition" in prompt.lower() and "section 1" in prompt:
        raise RuntimeError("simulated provider error")
    return Completion(text="")


# Main run scripts — these handle the pre-flight, section, and tagger prompts.
# The weaver provider is separate (FakeProvider with a transition script).

def _main_script(system: str, messages: list[Any]) -> Completion:
    """Standard script for the main provider."""
    prompt = messages[-1].content if messages else ""
    if "pre-flight plan" in prompt or "JSON fence" in prompt:
        return Completion(text=_declaration())
    if "TAGS:" in prompt:
        return Completion(text="Reviewed the note.\nTAGS: philosophy, epistemology, revelation")
    return Completion(text=BODY.strip())


# A sample note for pure-function tests.
SAMPLE_NOTE = """\
---
title: Test Note
tags: [philosophy]
---

# The Epistemic Gap and the Necessity of Revelation

## The Limits of Unaided Reason

Human reason can establish many truths through careful observation and logical
deduction.  The existence of necessary being, the reality of moral obligation,
and the structure of the natural world are all within its reach.

Yet there are boundaries that reason alone cannot cross.  The particular
content of divine obligation, the specifics of the afterlife, and the
precise duties owed to particular persons exceed what unaided reason can
determine.

## The Shape of the Gap

The gap between what reason reaches and what a human life requires is not
uniform across all domains.  In ethics, reason grasps general principles but
struggles with particular applications.

In metaphysics, reason establishes the existence of a necessary being but
cannot determine its specific attributes without additional input.
"""

# ---------------------------------------------------------------------------
# 1. Skeleton extraction: first and last sentences per paragraph
# ---------------------------------------------------------------------------


class TestExtractSkeleton:
    def test_extracts_topic(self) -> None:
        skeleton = extract_skeleton(SAMPLE_NOTE, "Test Note")
        assert skeleton.topic == "Test Note"

    def test_extracts_headings(self) -> None:
        skeleton = extract_skeleton(SAMPLE_NOTE, "Test Note")
        headings = [s.heading for s in skeleton.sections]
        assert headings == ["The Limits of Unaided Reason", "The Shape of the Gap"]

    def test_picks_first_and_last_sentences(self) -> None:
        skeleton = extract_skeleton(SAMPLE_NOTE, "Test Note")
        sec1 = skeleton.sections[0]
        # First paragraph: "Human reason can establish..." and "...within its reach."
        assert len(sec1.paragraph_bookends) == 2
        first_para_first, first_para_last = sec1.paragraph_bookends[0]
        assert "Human reason" in first_para_first
        assert "within its reach" in first_para_last
        # Second paragraph: "Yet there are boundaries..." and "...unaided reason can determine."
        second_para_first, second_para_last = sec1.paragraph_bookends[1]
        assert "Yet there are boundaries" in second_para_first
        assert "unaided reason can" in second_para_last

    def test_single_sentence_paragraph(self) -> None:
        note = """\
---

# Topic

## Heading

Only one sentence here.
"""
        skeleton = extract_skeleton(note, "Topic")
        assert len(skeleton.sections) == 1
        first, last = skeleton.sections[0].paragraph_bookends[0]
        assert first == last == "Only one sentence here."

    def test_empty_section_body(self) -> None:
        note = """\
---

# Topic

## Empty Section

## Next Section

Some content here.
"""
        skeleton = extract_skeleton(note, "Topic")
        # Empty section should still appear but with no paragraph bookends
        assert len(skeleton.sections) == 2
        assert skeleton.sections[0].heading == "Empty Section"
        assert skeleton.sections[0].paragraph_bookends == []
        assert skeleton.sections[1].heading == "Next Section"


# ---------------------------------------------------------------------------
# 2. Well-formed response: N transitions splice correctly, body byte-identical
# ---------------------------------------------------------------------------


class TestSpliceTransitions:
    def test_splice_inserts_transitions_after_headings(self) -> None:
        note = """\
---

# Topic

## Heading One

Body of section one.

## Heading Two

Body of section two.
"""
        transitions = {
            1: "Transition into the first section.",
            2: "Moving on to the second section.",
        }
        result = splice_transitions(note, transitions)
        lines = result.split("\n")
        # Find the heading lines and check transitions follow
        found_h1_transition = False
        found_h2_transition = False
        for i, line in enumerate(lines):
            if line.strip() == "## Heading One":
                # Transition should be 2 lines after (blank, transition)
                assert lines[i + 2].strip() == "Transition into the first section."
                found_h1_transition = True
            if line.strip() == "## Heading Two":
                assert lines[i + 2].strip() == "Moving on to the second section."
                found_h2_transition = True
        assert found_h1_transition
        assert found_h2_transition

    def test_splice_preserves_body_byte_identically(self) -> None:
        """The body text between transitions must be byte-identical."""
        body_section_1 = "First section body paragraph."
        body_section_2 = "Second section body paragraph."
        note = f"""\
---

# Topic

## Heading One

{body_section_1}

## Heading Two

{body_section_2}
"""
        transitions = {1: "Transition one.", 2: "Transition two."}
        result = splice_transitions(note, transitions)
        assert body_section_1 in result
        assert body_section_2 in result
        # Verify body text is preserved exactly
        assert f"\n{body_section_1}\n" in result
        assert f"\n{body_section_2}\n" in result

    def test_splice_only_specified_sections(self) -> None:
        """Sections without transitions are left unchanged."""
        note = """\
---

# Topic

## Heading One

Body one.

## Heading Two

Body two.

## Heading Three

Body three.
"""
        transitions = {2: "Transition for section two only."}
        result = splice_transitions(note, transitions)
        assert "Transition for section two only." in result
        # Section 1 and 3 should have no transitions
        lines = result.split("\n")
        h1_idx = next(i for i, l in enumerate(lines) if l.strip() == "## Heading One")
        h3_idx = next(i for i, l in enumerate(lines) if l.strip() == "## Heading Three")
        # After heading 1: blank line, then body (no transition)
        assert lines[h1_idx + 2].strip() == "Body one."
        # After heading 3: blank line, then body (no transition)
        assert lines[h3_idx + 2].strip() == "Body three."

    def test_splice_section_1_gets_transition(self) -> None:
        """Section 1 gets a transition — it orients from the topic."""
        note = """\
---

# Topic

## First Section

Body here.
"""
        transitions = {1: "Orienting the reader from the topic."}
        result = splice_transitions(note, transitions)
        assert "Orienting the reader from the topic." in result


# ---------------------------------------------------------------------------
# 3. Off-topic transition is dropped; siblings survive
# ---------------------------------------------------------------------------


class TestValidateTransition:
    def test_valid_transition_accepted(self) -> None:
        verdict = validate_transition(
            "The limits of reason reveal an epistemic gap.",
            section_heading="The Limits of Unaided Reason",
            preceding_heading="The Epistemic Gap",
            note_topic="The Epistemic Gap and the Necessity of Revelation",
        )
        assert verdict.accepted

    def test_off_topic_transition_dropped(self) -> None:
        verdict = validate_transition(
            "Cooking pasta requires boiling water and a pinch of salt.",
            section_heading="The Limits of Unaided Reason",
            preceding_heading="The Epistemic Gap",
            note_topic="The Epistemic Gap and the Necessity of Revelation",
        )
        assert not verdict.accepted
        assert "no overlap" in verdict.reason

    def test_topic_overlap_is_sufficient(self) -> None:
        """A transition that overlaps with the topic but not the heading is OK."""
        verdict = validate_transition(
            "This revelation fundamentally changes our understanding.",
            section_heading="Unrelated Heading",
            preceding_heading="Another Unrelated",
            note_topic="The Necessity of Revelation",
        )
        assert verdict.accepted

    def test_heading_overlap_is_sufficient(self) -> None:
        """A transition that overlaps with the heading but not the topic is OK."""
        verdict = validate_transition(
            "The limits of unaided reason shape this entire discussion.",
            section_heading="The Limits of Unaided Reason",
            preceding_heading="Unrelated",
            note_topic="Something Else Entirely",
        )
        assert verdict.accepted


# ---------------------------------------------------------------------------
# 4. Multi-line and [[link]] transitions are dropped
# ---------------------------------------------------------------------------


class TestStructuralValidation:
    def test_multiline_transition_dropped(self) -> None:
        verdict = validate_transition(
            "This transition has\na line break inside.",
            section_heading="Some Heading",
            preceding_heading="Previous",
            note_topic="Some Topic",
        )
        assert not verdict.accepted
        assert "line break" in verdict.reason

    def test_wikilink_transition_dropped(self) -> None:
        verdict = validate_transition(
            "See the discussion at [[nonexistent note]] for more context.",
            section_heading="Some Heading",
            preceding_heading="Previous",
            note_topic="Some Topic",
        )
        assert not verdict.accepted
        assert "wikilink" in verdict.reason

    def test_heading_marker_dropped(self) -> None:
        verdict = validate_transition(
            "# This looks like a heading not a transition.",
            section_heading="Some Heading",
            preceding_heading="Previous",
            note_topic="Some Topic",
        )
        assert not verdict.accepted
        assert "heading marker" in verdict.reason

    def test_list_marker_dropped(self) -> None:
        verdict = validate_transition(
            "- This looks like a list item not prose.",
            section_heading="Some Heading",
            preceding_heading="Previous",
            note_topic="Some Topic",
        )
        assert not verdict.accepted
        assert "list marker" in verdict.reason

    def test_blockquote_dropped(self) -> None:
        verdict = validate_transition(
            "> This is a blockquote not a transition.",
            section_heading="Some Heading",
            preceding_heading="Previous",
            note_topic="Some Topic",
        )
        assert not verdict.accepted
        assert "blockquote" in verdict.reason

    def test_code_fence_dropped(self) -> None:
        verdict = validate_transition(
            "```python\nprint('hello')\n```",
            section_heading="Some Heading",
            preceding_heading="Previous",
            note_topic="Some Topic",
        )
        assert not verdict.accepted

    def test_too_short_dropped(self) -> None:
        verdict = validate_transition(
            "Too short.",
            section_heading="Some Heading",
            preceding_heading="Previous",
            note_topic="Some Topic",
        )
        assert not verdict.accepted
        assert "too short" in verdict.reason

    def test_too_long_dropped(self) -> None:
        long_text = "word " * 81  # 81 words
        verdict = validate_transition(
            long_text.strip(),
            section_heading="Some Heading",
            preceding_heading="Previous",
            note_topic="Some Topic About Reason",
        )
        assert not verdict.accepted
        assert "too long" in verdict.reason


# ---------------------------------------------------------------------------
# 5. Provider error leaves the note untouched
# ---------------------------------------------------------------------------


class TestProviderDegradation:
    async def test_provider_error_leaves_note_unchanged(self, tmp_path: Path) -> None:
        vault = _scaffold(tmp_path, agents=("tagger", "weaver"))
        bus = EventBus()
        queue = bus.subscribe()
        main_provider = FakeProvider(script=_main_script)
        weaver_provider = FakeProvider(script=_transition_error)
        await execute_run(
            TOPIC, main_provider, vault, bus=bus, concurrency=3,
            weaver_provider=weaver_provider,
        )
        await bus.close()
        events: list[Event] = []
        async for event in drain(queue):
            events.append(event)
        # The note should still be written (from assembly) — the provider
        # error during transitions should not prevent the note from landing.
        note_events = [e for e in events if hasattr(e, "path") and e.path]
        assert len(note_events) >= 1
        # No RunFailed from the transitions stage
        failed = [e for e in events if isinstance(e, RunFailed)]
        assert len(failed) == 0
        # Should see a warning about the provider error
        warnings = [
            e for e in events
            if isinstance(e, LogMessage) and "provider error" in e.text.lower()
        ]
        assert len(warnings) >= 1

    async def test_empty_response_leaves_note_unchanged(self, tmp_path: Path) -> None:
        vault = _scaffold(tmp_path, agents=("tagger", "weaver"))
        bus = EventBus()
        queue = bus.subscribe()
        main_provider = FakeProvider(script=_main_script)
        weaver_provider = FakeProvider(script=_transition_empty)
        await execute_run(
            TOPIC, main_provider, vault, bus=bus, concurrency=3,
            weaver_provider=weaver_provider,
        )
        await bus.close()
        events: list[Event] = []
        async for event in drain(queue):
            events.append(event)
        # Should emit TransitionsApplied with 0 accepted
        trans_events = [e for e in events if isinstance(e, TransitionsApplied)]
        assert len(trans_events) == 1
        assert trans_events[0].accepted == 0


# ---------------------------------------------------------------------------
# 6. No weaver agent: note untouched, warning emitted
# ---------------------------------------------------------------------------


class TestNoWeaverDegradation:
    async def test_no_weaver_agent_skips_transitions(self, tmp_path: Path) -> None:
        vault = _scaffold(tmp_path, agents=("tagger",))  # no weaver
        bus = EventBus()
        queue = bus.subscribe()
        provider = FakeProvider(script=_main_script)
        await execute_run(TOPIC, provider, vault, bus=bus, concurrency=3)
        await bus.close()
        events: list[Event] = []
        async for event in drain(queue):
            events.append(event)
        # Should see a warning about no weaver agent
        warnings = [
            e for e in events
            if isinstance(e, LogMessage) and "no weaver" in e.text.lower()
        ]
        assert len(warnings) >= 1
        # The note should still be written successfully
        note_events = [e for e in events if hasattr(e, "path") and e.path]
        assert len(note_events) >= 1


# ---------------------------------------------------------------------------
# 7. Idempotency: re-running splice with same transitions
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_splice_twice_gives_different_result(self) -> None:
        """Splicing is NOT idempotent: running it twice inserts duplicate
        transitions.  This is acceptable because:
        1. TransitionStage reads the note from disk, splices, and writes back.
           A second run would read the already-spliced note, extract its
           skeleton (which now includes transitions as paragraph content),
           and generate a NEW set of transitions — not re-run the same ones.
        2. A resumed run does re-enter every stage -- stages_completed is
           appended to but never read back to skip anything -- so this rests
           on AssemblyStage instead: it rebuilds the body from the chunks on
           disk and overwrites the note before this stage runs, and the chunks
           never contain transitions.  A resume therefore re-splices into a
           freshly assembled body, not on top of an earlier splice.
        3. Making splice idempotent would require detecting existing
           transitions, which couples the pure function to the note's
           history.  The stage runner (PipelineStage) is the right place
           to enforce single-execution."""
        note = """\
---

# Topic

## Heading

Body here.
"""
        transitions = {1: "A transition about the topic."}
        once = splice_transitions(note, transitions)
        twice = splice_transitions(once, transitions)
        # They differ because the second splice adds another transition
        assert once != twice
        # But the first splice is correct
        assert "A transition about the topic." in once

    def test_splice_produces_exactly_one_blank_line_each_side(self) -> None:
        """Each transition must have exactly one blank line before and after."""
        note = """\
---

# Topic

## Heading

Body here.
"""
        transitions = {1: "The transition sentence."}
        result = splice_transitions(note, transitions)
        lines = result.split("\n")
        for i, line in enumerate(lines):
            if line.strip() == "The transition sentence.":
                # Line before must be blank
                assert lines[i - 1].strip() == "", f"no blank before transition at line {i}"
                # Line after must be blank
                assert lines[i + 1].strip() == "", f"no blank after transition at line {i}"
                break
        else:
            pytest.fail("transition not found in spliced note")


# ---------------------------------------------------------------------------
# 8. Prompt construction
# ---------------------------------------------------------------------------


class TestPromptConstruction:
    def test_prompt_contains_topic(self) -> None:
        skeleton = NoteSkeleton(
            topic="Epistemic Gap",
            sections=[SectionSkeleton(heading="Section One", paragraph_bookends=[("First.", "Last.")])],
        )
        prompt = build_transition_prompt(skeleton)
        assert "Epistemic Gap" in prompt

    def test_prompt_contains_heading(self) -> None:
        skeleton = NoteSkeleton(
            topic="Epistemic Gap",
            sections=[SectionSkeleton(heading="Section One", paragraph_bookends=[("First.", "Last.")])],
        )
        prompt = build_transition_prompt(skeleton)
        assert "## Section One" in prompt

    def test_prompt_contains_paragraph_bookends(self) -> None:
        skeleton = NoteSkeleton(
            topic="Epistemic Gap",
            sections=[SectionSkeleton(
                heading="Section One",
                paragraph_bookends=[("First sentence.", "Last sentence.")],
            )],
        )
        prompt = build_transition_prompt(skeleton)
        assert "First sentence." in prompt
        assert "Last sentence." in prompt


# ---------------------------------------------------------------------------
# 9. Response parsing
# ---------------------------------------------------------------------------


class TestParseTransitions:
    def test_parses_numbered_lines(self) -> None:
        response = "1. First transition.\n2. Second transition.\n3. Third transition."
        parsed = parse_transitions(response)
        assert len(parsed) == 3
        assert parsed[0].index == 1
        assert parsed[0].text == "First transition."
        assert parsed[2].index == 3
        assert parsed[2].text == "Third transition."

    def test_skips_non_numbered_lines(self) -> None:
        response = (
            "Here are the transitions:\n"
            "1. First transition.\n"
            "Some preamble text.\n"
            "2. Second transition.\n"
        )
        parsed = parse_transitions(response)
        assert len(parsed) == 2

    def test_handles_whitespace_variations(self) -> None:
        response = "  1.  First transition.  \n  2.  Second transition.  "
        parsed = parse_transitions(response)
        assert len(parsed) == 2
        assert parsed[0].text == "First transition."


# ---------------------------------------------------------------------------
# 10. Full integration: transitions accepted, dropped, and emitted
# ---------------------------------------------------------------------------


class TestIntegration:
    async def test_transitions_applied_event_emitted(self, tmp_path: Path) -> None:
        """TransitionStage emits TransitionsApplied with correct counts."""
        vault = _scaffold(tmp_path, agents=("tagger", "weaver"))
        bus = EventBus()
        queue = bus.subscribe()
        main_provider = FakeProvider(script=_main_script)
        weaver_provider = FakeProvider(script=_transition_clean)
        await execute_run(
            TOPIC, main_provider, vault, bus=bus, concurrency=3,
            weaver_provider=weaver_provider,
        )
        await bus.close()
        events: list[Event] = []
        async for event in drain(queue):
            events.append(event)
        trans_events = [e for e in events if isinstance(e, TransitionsApplied)]
        assert len(trans_events) == 1
        ev = trans_events[0]
        assert ev.requested == len(HEADINGS)
        # At least some transitions should be accepted
        assert ev.accepted >= 1

    async def test_off_topic_dropped_sibling_survives(self, tmp_path: Path) -> None:
        """An off-topic transition is dropped while its siblings survive."""
        vault = _scaffold(tmp_path, agents=("tagger", "weaver"))
        bus = EventBus()
        queue = bus.subscribe()
        main_provider = FakeProvider(script=_main_script)
        weaver_provider = FakeProvider(script=_transition_off_topic)
        await execute_run(
            TOPIC, main_provider, vault, bus=bus, concurrency=3,
            weaver_provider=weaver_provider,
        )
        await bus.close()
        events: list[Event] = []
        async for event in drain(queue):
            events.append(event)
        trans_events = [e for e in events if isinstance(e, TransitionsApplied)]
        assert len(trans_events) == 1
        ev = trans_events[0]
        # At least 2 should be accepted (the on-topic ones), at least 1 dropped
        assert ev.accepted >= 2
        assert ev.dropped >= 1

    async def test_wikilink_transition_dropped_in_pipeline(self, tmp_path: Path) -> None:
        """A transition containing [[wikilink]] is dropped in the pipeline."""
        vault = _scaffold(tmp_path, agents=("tagger", "weaver"))
        bus = EventBus()
        queue = bus.subscribe()
        main_provider = FakeProvider(script=_main_script)
        weaver_provider = FakeProvider(script=_transition_malformed)
        await execute_run(
            TOPIC, main_provider, vault, bus=bus, concurrency=3,
            weaver_provider=weaver_provider,
        )
        await bus.close()
        events: list[Event] = []
        async for event in drain(queue):
            events.append(event)
        trans_events = [e for e in events if isinstance(e, TransitionsApplied)]
        assert len(trans_events) == 1
        ev = trans_events[0]
        # The wikilink transition should be dropped
        assert ev.dropped >= 1
        # The valid ones should survive
        assert ev.accepted >= 2

    async def test_multiline_transition_dropped_in_pipeline(self, tmp_path: Path) -> None:
        """A transition containing line breaks is dropped in the pipeline."""
        vault = _scaffold(tmp_path, agents=("tagger", "weaver"))
        bus = EventBus()
        queue = bus.subscribe()
        main_provider = FakeProvider(script=_main_script)
        weaver_provider = FakeProvider(script=_transition_multi_line)
        await execute_run(
            TOPIC, main_provider, vault, bus=bus, concurrency=3,
            weaver_provider=weaver_provider,
        )
        await bus.close()
        events: list[Event] = []
        async for event in drain(queue):
            events.append(event)
        trans_events = [e for e in events if isinstance(e, TransitionsApplied)]
        assert len(trans_events) == 1
        ev = trans_events[0]
        # The multi-line transition should be dropped
        assert ev.dropped >= 1
        assert ev.accepted >= 2


class TestRealProviderConstruction:
    """The path every real run takes, which the FakeProvider tests never touch.

    Every other test here injects `weaver_provider`, so the branch that builds
    the provider from configuration was never executed.  It was wrong -- it
    called `get_provider(name, keys=pool, ...)`, but providers take `api_key`
    plus `pool`, and `get_provider` is `(name, **kwargs)` so mypy checked
    nothing.  The TypeError landed in the stage's broad `except`, which
    reported "transition provider unavailable" and skipped the weaver on
    every real run while the suite stayed green.

    These tests construct through the registry for real, so the kwargs are
    checked by something other than a comment.
    """

    def test_gemini_is_constructible_with_the_kwargs_the_stage_passes(self) -> None:
        from avicenna.keypool import KeyPool
        from avicenna.providers.registry import get_provider

        pool = KeyPool(["k1", "k2"], source="test")
        provider = get_provider("gemini", api_key=pool._keys[0], pool=pool)
        assert provider is not None

    def test_the_old_keyword_would_have_raised(self) -> None:
        """Pins the actual failure, so a future rename cannot re-introduce it."""
        from avicenna.keypool import KeyPool
        from avicenna.providers.registry import get_provider

        pool = KeyPool(["k1"], source="test")
        with pytest.raises(TypeError):
            get_provider("gemini", keys=pool)

    def test_pool_name_follows_the_provider(self) -> None:
        """Gemini spends keys from the "google" section, not from "gemini".

        The stage used to call load_pool("google") whatever the configured
        provider was -- the same conflation that once handed a valid Gemini
        key to Mistral and made it look expired.
        """
        from avicenna.pipeline.stages import _weaver_pool_name

        assert _weaver_pool_name("gemini") == "google"
        assert _weaver_pool_name("mistral") == "mistral"
        assert _weaver_pool_name("anthropic") == "anthropic"


class TestFencedCodeBlocks:
    """A `## ` inside a fenced block is sample text, not a section.

    This program writes long notes, sometimes about writing, so a fenced block
    quoting Markdown is not exotic.  Both passes counted such a line as a
    section: the reader numbered transitions against the wrong section list,
    and the writer spliced a transition *inside the code block*.  Every other
    pass over a note here is fence-aware; these two were not.
    """

    NOTE = (
        "# T\n\n"
        "## Real Section\n\nBody text here.\n\n"
        "```markdown\n## Not A Section\n```\n\n"
        "More body.\n\n"
        "## Second Real\n\nBody.\n"
    )

    def test_reader_skips_headings_inside_a_fence(self) -> None:
        skeleton = extract_skeleton(self.NOTE, "T")
        assert [s.heading for s in skeleton.sections] == ["Real Section", "Second Real"]

    def test_writer_does_not_splice_into_a_fence(self) -> None:
        out = splice_transitions(
            self.NOTE,
            {1: "Transition one about T.", 2: "Transition two about T."},
        )
        assert "```markdown\n## Not A Section\n```" in out
        # The second transition belongs to the second real section.
        assert "## Second Real\n\nTransition two about T." in out

    def test_the_fenced_block_is_byte_identical(self) -> None:
        out = splice_transitions(self.NOTE, {1: "Transition one about T."})
        fence = "```markdown\n## Not A Section\n```"
        assert out.count(fence) == 1

    def test_a_tilde_fence_is_closed_only_by_a_tilde_fence(self) -> None:
        """Markdown's rule: a fence ends on its own character, not any fence."""
        note = (
            "# T\n\n"
            "## One\n\n~~~\n```\n## Still Inside\n```\n~~~\n\nBody.\n\n"
            "## Two\n\nBody.\n"
        )
        assert [s.heading for s in extract_skeleton(note, "T").sections] == ["One", "Two"]

    def test_indices_agree_between_reader_and_writer(self) -> None:
        """The bug that mattered: the two passes disagreeing on what section 2 is.

        The reader numbers the transitions; the writer places them.  If they
        count sections differently, every transition after the fence lands
        against the wrong heading.
        """
        skeleton = extract_skeleton(self.NOTE, "T")
        transitions = {
            i + 1: f"A transition concerning {s.heading}."
            for i, s in enumerate(skeleton.sections)
        }
        out = splice_transitions(self.NOTE, transitions)
        for section in skeleton.sections:
            assert f"## {section.heading}\n\nA transition concerning {section.heading}." in out
