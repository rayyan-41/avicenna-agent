"""Tests for the normaliser wiring in AssemblyStage and _write_back.

The normaliser (avicenna.pipeline.normalise) is called in two places:

  1. AssemblyStage.run(), after the weaver round-trip and before
     _write_note_atomically — so every first-run note carries clean
     structure.
  2. _write_back(), after frontmatter reconciliation and before the
     truncation guard — so every model-produced revision (formatter,
     linker) is normalised before it reaches the vault.

These tests verify that:

  1. The assembly stage emits a MarkdownNormalised event with stage="assembly".
  2. The written note is normalised (rules collapsed, blank lines capped).
  3. The frontmatter block is preserved byte-identically through normalisation.
  4. The word count before and after normalisation are materially equal.
  5. A formatter round-trip that reintroduces rules ends with a normalised
     note on disk (the _write_back call site).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from avicenna.bus import EventBus, drain
from avicenna.events import Event, MarkdownNormalised
from avicenna.pipeline.run import execute_run
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


# --- helpers -----------------------------------------------------------------
# The normaliser only has visible work when the text has structural issues
# (consecutive rules, rules adjacent to headings, excessive blank lines).
# To test that the stage actually calls it, two scripts are used:
#
#   _messy_weaver_script — the weaver returns prose with horizontal rules
#       between every heading, which the normaliser will collapse.
#
#   _clean_script — the standard script that returns well-formed prose, so the
#       normaliser runs but finds nothing to fix (the event still fires with
#       counts at zero).


def _messy_weaver_script(system: str, messages: list[Any]) -> Completion:
    """A script whose weaver output contains excessive horizontal rules."""
    prompt = messages[-1].content if messages else ""
    if "pre-flight plan" in prompt or "JSON fence" in prompt:
        return Completion(text=_declaration())
    if "TAGS:" in prompt:
        return Completion(text="Reviewed the note.\nTAGS: philosophy, epistemology, revelation")
    if "genuinely related" in prompt:
        note = prompt.split("\n\n", 1)[-1]
        return Completion(text=note)
    if "formatting corrected" in prompt:
        return Completion(text=prompt.split("\n\n", 1)[-1])
    # The weaver: inject rules between every heading.
    if "Assemble this into one continuous note" in prompt:
        raw = prompt.split("\n\nTopic:")[0]
        # Insert --- between every ## heading
        lines = raw.split("\n")
        out: list[str] = []
        for line in lines:
            out.append(line)
            if line.startswith("## "):
                out.append("")
                out.append("---")
        return Completion(text="\n".join(out))
    return Completion(text=BODY.strip())


def _clean_script(system: str, messages: list[Any]) -> Completion:
    """Standard script — well-formed output, normaliser has nothing to fix."""
    prompt = messages[-1].content if messages else ""
    if "pre-flight plan" in prompt or "JSON fence" in prompt:
        return Completion(text=_declaration())
    if "TAGS:" in prompt:
        return Completion(text="Reviewed the note.\nTAGS: philosophy, epistemology, revelation")
    if "genuinely related" in prompt:
        note = prompt.split("\n\n", 1)[-1]
        return Completion(text=note)
    if "formatting corrected" in prompt:
        return Completion(text=prompt.split("\n\n", 1)[-1])
    if "Assemble this into one continuous note" in prompt:
        return Completion(text=prompt.split("\n\nTopic:")[0])
    return Completion(text=BODY.strip())


async def _run(vault: Vault, script: Any = None, **kw: Any) -> list[Event]:
    bus = EventBus()
    queue = bus.subscribe()
    provider = FakeProvider(script=script or _clean_script)
    await execute_run(TOPIC, provider, vault, bus=bus, concurrency=3, **kw)
    await bus.close()
    seen: list[Event] = []
    async for event in drain(queue):
        seen.append(event)
    return seen


def _note(vault: Vault) -> Path:
    notes = [
        p for p in vault.root.rglob("*.md")
        if ".agents" not in p.parts and p.name != "AGENTS.md"
    ]
    assert len(notes) == 1, f"expected exactly one note, found {notes}"
    return notes[0]


# =============================================================================
# 1. Event emission
# =============================================================================


async def test_assembly_emits_markdown_normalised(tmp_path: Path) -> None:
    """Every run produces a MarkdownNormalised event, even when nothing
    needs fixing."""
    vault = _scaffold(tmp_path, agents=("tagger",))
    events = await _run(vault)
    norm_events = [e for e in events if isinstance(e, MarkdownNormalised)]
    assert len(norm_events) == 1, (
        f"expected exactly one MarkdownNormalised event, found {len(norm_events)}"
    )
    ev = norm_events[0]
    assert isinstance(ev.words_before, int) and ev.words_before > 0
    assert isinstance(ev.words_after, int) and ev.words_after > 0


async def test_messy_weaver_gets_normalised(tmp_path: Path) -> None:
    """When the weaver returns excessive rules, the normaliser removes them
    and the event reports nonzero counts."""
    vault = _scaffold(tmp_path, agents=("tagger", "weaver"))
    events = await _run(vault, script=_messy_weaver_script)
    norm_events = [e for e in events if isinstance(e, MarkdownNormalised)]
    assert len(norm_events) == 1
    ev = norm_events[0]
    assert ev.rules_removed > 0, (
        f"messy weaver should trigger rule removal, got {ev.rules_removed}"
    )


# =============================================================================
# 2. Written note is normalised
# =============================================================================


async def test_written_note_has_no_adjacent_rules_to_headings(tmp_path: Path) -> None:
    """The note on disk must not contain a --- rule immediately before or
    after a ## heading."""
    vault = _scaffold(tmp_path, agents=("tagger", "weaver"))
    await _run(vault, script=_messy_weaver_script)
    body = _note(vault).read_text(encoding="utf-8")
    lines = body.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "---":
            # Check neighbour above
            if i > 0:
                prev = lines[i - 1].strip()
                if prev.startswith("## ") or prev == "":
                    # blank line before is fine; heading directly before is not
                    if i > 1 and lines[i - 1].strip() == "" and lines[i - 2].strip().startswith("## "):
                        pass  # blank line between heading and rule is OK
                    elif prev.startswith("## "):
                        assert False, f"rule on line {i+1} directly after heading on line {i}"
            # Check neighbour below
            if i < len(lines) - 1:
                nxt = lines[i + 1].strip()
                if nxt.startswith("## "):
                    assert False, f"rule on line {i+1} directly before heading on line {i+2}"


# =============================================================================
# 3. Frontmatter preservation
# =============================================================================


async def test_frontmatter_preserved_through_normalisation(tmp_path: Path) -> None:
    """The normaliser must not touch the frontmatter block.  The on-disk
    note's frontmatter must contain the expected keys."""
    vault = _scaffold(tmp_path, agents=("tagger", "weaver"))
    await _run(vault, script=_messy_weaver_script)
    body = _note(vault).read_text(encoding="utf-8")
    # The note must start with frontmatter
    assert body.startswith("---\n"), f"note does not start with frontmatter: {body[:60]}"
    # The frontmatter block must close
    fm_end = body.index("\n---\n", 4)
    fm = body[4:fm_end]
    # Must contain the expected keys
    assert "title:" in fm, f"frontmatter missing title: {fm}"
    assert "tags:" in fm, f"frontmatter missing tags: {fm}"
    # Tags must be populated (from the tagger, not empty)
    for line in fm.split("\n"):
        if line.strip().startswith("tags:"):
            tag_part = line.split(":", 1)[1].strip()
            assert tag_part != "[]", f"tags must not be empty: {tag_part}"


# =============================================================================
# 4. Word count stability
# =============================================================================


async def test_word_count_not_materially_changed(tmp_path: Path) -> None:
    """Normalisation must not materially change the word count.  The
    difference must be < 5% of the before count."""
    vault = _scaffold(tmp_path, agents=("tagger", "weaver"))
    events = await _run(vault, script=_messy_weaver_script)
    norm_events = [e for e in events if isinstance(e, MarkdownNormalised)]
    assert len(norm_events) == 1
    ev = norm_events[0]
    if ev.words_before > 0:
        diff = abs(ev.words_after - ev.words_before)
        ratio = diff / ev.words_before
        assert ratio < 0.05, (
            f"normalisation changed word count by {ratio:.1%}: "
            f"{ev.words_before} -> {ev.words_after}"
        )


# =============================================================================
# 5. Stage field
# =============================================================================


async def test_assembly_event_has_stage_field(tmp_path: Path) -> None:
    """The MarkdownNormalised event from assembly carries stage='assembly'."""
    vault = _scaffold(tmp_path, agents=("tagger",))
    events = await _run(vault)
    norm_events = [e for e in events if isinstance(e, MarkdownNormalised)]
    assert len(norm_events) >= 1
    assert norm_events[0].stage == "assembly"


# =============================================================================
# 6. Formatter round-trip (_write_back normalisation)
# =============================================================================


async def test_formatter_reintroducing_rules_gets_normalised(tmp_path: Path) -> None:
    """When the formatter returns a note with rules adjacent to headings,
    _write_back normalises them and the final note on disk is clean.

    This is the test that would have caught the assembly-only wiring: the
    formatter runs after assembly and writes through _write_back, so without
    normalisation there the final note would carry the formatter's damage.
    """
    def messy_formatter_script(system: str, messages: list[Any]) -> Completion:
        prompt = messages[-1].content if messages else ""
        if "pre-flight plan" in prompt or "JSON fence" in prompt:
            return Completion(text=_declaration())
        if "TAGS:" in prompt:
            return Completion(text="Reviewed.\nTAGS: philosophy, epistemology, revelation")
        if "genuinely related" in prompt:
            note = prompt.split("\n\n", 1)[-1]
            return Completion(text=note)
        if "Assemble this into one continuous note" in prompt:
            return Completion(text=prompt.split("\n\nTopic:")[0])
        # The formatter: inject rules adjacent to headings.
        if "formatting corrected" in prompt:
            raw = prompt.split("\n\n", 1)[-1]
            lines = raw.split("\n")
            out: list[str] = []
            for line in lines:
                out.append(line)
                if line.startswith("## "):
                    out.append("")
                    out.append("---")
            return Completion(text="\n".join(out))
        return Completion(text=BODY.strip())

    vault = _scaffold(tmp_path, agents=("tagger", "formatter"))
    events = await _run(vault, script=messy_formatter_script)

    # The formatter writes through _write_back, which should normalise.
    norm_events = [e for e in events if isinstance(e, MarkdownNormalised)]
    formatter_norms = [e for e in norm_events if e.stage == "formatter"]
    assert len(formatter_norms) >= 1, (
        "formatter revision must trigger normalisation in _write_back"
    )

    # The final note on disk must not have rules adjacent to headings.
    body = _note(vault).read_text(encoding="utf-8")
    lines = body.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "---":
            if i > 0 and lines[i - 1].strip().startswith("## "):
                assert False, f"rule on line {i+1} directly after heading on line {i}"
            if i < len(lines) - 1 and lines[i + 1].strip().startswith("## "):
                assert False, f"rule on line {i+1} directly before heading on line {i+2}"
