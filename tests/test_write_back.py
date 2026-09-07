"""Tests for _write_back and _unwrap_model_output in pipeline/stages.py.

The pipeline owns the frontmatter, not the model.  These tests verify that
_write_back preserves the on-disk frontmatter, unwraps chatty model output,
and rejects truncation — exactly the guarantees that keep a note vault-safe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from avicenna.bus import EventBus
from avicenna.events import LogMessage
from avicenna.pipeline.context import RunContext
from avicenna.pipeline.stages import _unwrap_model_output, _write_back
from avicenna.providers.base import Completion
from avicenna.providers.fake import FakeProvider
from avicenna.vault.init_scaffold import init_vault
from avicenna.vault.vault import Vault

TOPIC = "The Epistemic Gap and the Necessity of Revelation"

DISK_FM = (
    "---\n"
    "title: The Epistemic Gap and the Necessity of Revelation\n"
    "domain: general\n"
    "template: general\n"
    "tags: [philosophy, epistemology]\n"
    "---\n"
)

BODY = (
    "# The Epistemic Gap\n\n"
    "## The Limits of Unaided Reason\n\n"
    "Some prose about the limits of reason. " * 20 + "\n"
    "## The Shape of the Gap\n\n"
    "More prose about the shape of the epistemic gap. " * 20 + "\n"
)

# A realistic malformed frontmatter block observed in production: opening ---,
# key: value lines, no closing ---, then straight into the note body including
# a --- horizontal rule that the old regex would have matched as the closing
# delimiter, deleting everything up to that rule.
_MALFORMED_FM_HEADER = (
    "date: 2024-06-15\n"
    "status: complete\n"
    "tags: philosophy, ethics, ... , cli\n"
    'note: ""\n'
    "\n"
    "> [!abstract] Table of Contents\n"
    "> - [[#Introduction]]\n"
    "> - [[#The Argument]]\n"
    "> - [[#Conclusion]]\n"
    "\n"
    "---\n"
    "\n"
)
MALFORMED_FM_BODY = (
    _MALFORMED_FM_HEADER
    + "## Introduction\n\n" + ("This is the introduction prose. " * 40) + "\n"
    + "## The Argument\n\n" + ("This is the argument prose. " * 40) + "\n"
    + "## Conclusion\n\n" + ("This is the conclusion prose. " * 40) + "\n"
)


def _scaffold(tmp_path: Path) -> Vault:
    root = init_vault(tmp_path / "vault")
    return Vault.load(root)


def _make_context(vault: Vault, note_path: Path) -> RunContext:
    """Build a minimal RunContext with a note_path set."""
    from avicenna.pipeline.context import RunContext, RunSpec

    spec = RunSpec(
        topic=TOPIC,
        provider=FakeProvider(script=lambda s, m: Completion(text="")),
        vault=vault,
        bus=EventBus(),
        run_id="test-run",
    )
    ctx = RunContext(spec=spec)
    ctx.note_path = note_path
    return ctx


# --- _unwrap_model_output ---------------------------------------------------


class TestUnwrapModelOutput:
    """Tests for the conservative unwrapper."""

    def test_plain_output_passes_through(self) -> None:
        text = DISK_FM + BODY
        result, did_unwrap = _unwrap_model_output(text)
        assert result == text
        assert did_unwrap is False

    def test_strips_chat_preamble_before_frontmatter(self) -> None:
        wrapped = "Here is the corrected note:\n\n" + DISK_FM + BODY
        result, _ = _unwrap_model_output(wrapped)
        assert result == DISK_FM + BODY

    def test_unwraps_markdown_fence(self) -> None:
        inner = DISK_FM + BODY
        wrapped = "```markdown\n" + inner + "```"
        result, _ = _unwrap_model_output(wrapped)
        assert result.strip() == inner.strip()

    def test_unwraps_fence_with_preamble(self) -> None:
        inner = DISK_FM + BODY
        wrapped = "Here is the corrected note:\n\n```markdown\n" + inner + "```"
        result, _ = _unwrap_model_output(wrapped)
        assert result.strip() == inner.strip()

    def test_unwraps_tilde_fence(self) -> None:
        inner = DISK_FM + BODY
        wrapped = "~~~md\n" + inner + "~~~"
        result, _ = _unwrap_model_output(wrapped)
        assert result.strip() == inner.strip()

    def test_unwraps_bare_fence_no_info_string(self) -> None:
        inner = DISK_FM + BODY
        wrapped = "```\n" + inner + "```"
        result, _ = _unwrap_model_output(wrapped)
        assert result.strip() == inner.strip()

    def test_preserves_legitimate_code_block_mid_note(self) -> None:
        """A fenced code block inside the note body must not be unwrapped."""
        note = DISK_FM + BODY + "\n```python\nprint('hello')\n```\n"
        # The inner code block does NOT wrap the entire output, so the note
        # should pass through unchanged.
        result, _ = _unwrap_model_output(note)
        assert result == note

    def test_idempotent(self) -> None:
        inner = DISK_FM + BODY
        wrapped = "Here is the corrected note:\n\n```markdown\n" + inner + "```"
        once_text, _ = _unwrap_model_output(wrapped)
        twice_text, _ = _unwrap_model_output(once_text)
        assert once_text == twice_text

    def test_empty_input(self) -> None:
        result, did_unwrap = _unwrap_model_output("")
        assert result == ""
        assert did_unwrap is False


# --- _write_back ------------------------------------------------------------


class TestWriteBack:
    """Tests for the frontmatter-preserving write-back."""

    @pytest.fixture()
    def setup(self, tmp_path: Path) -> tuple[RunContext, Path]:
        vault = _scaffold(tmp_path)
        note_path = tmp_path / "vault" / "Art" / "test.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(DISK_FM + BODY, encoding="utf-8", newline="\n")
        ctx = _make_context(vault, note_path)
        return ctx, note_path

    @pytest.mark.asyncio()
    async def test_plain_output_passes_through(self, setup: tuple[RunContext, Path]) -> None:
        ctx, note_path = setup
        produced = DISK_FM + BODY
        result = await _write_back(ctx, "formatter", produced)
        assert result is True
        written = note_path.read_text(encoding="utf-8")
        assert written.startswith("---\n")
        assert "tags: [philosophy, epistemology]" in written

    @pytest.mark.asyncio()
    async def test_disk_tags_survive_model_returning_unbracketed(self, setup: tuple[RunContext, Path]) -> None:
        """tags: [a, b] on disk must survive a model that returns tags: a, b."""
        ctx, note_path = setup
        # Model returns the note with unbracketed tags (the real-world bug).
        bad_fm = (
            "---\n"
            "title: The Epistemic Gap and the Necessity of Revelation\n"
            "domain: general\n"
            "template: general\n"
            "tags: philosophy, epistemology\n"
            "---\n"
        )
        produced = bad_fm + BODY
        result = await _write_back(ctx, "formatter", produced)
        assert result is True
        written = note_path.read_text(encoding="utf-8")
        # Disk frontmatter must be preserved verbatim.
        assert "tags: [philosophy, epistemology]" in written
        assert "tags: philosophy, epistemology" not in written

    @pytest.mark.asyncio()
    async def test_model_returning_no_frontmatter_still_gets_disks(self, setup: tuple[RunContext, Path]) -> None:
        """A model that drops the frontmatter still gets the disk's copy."""
        ctx, note_path = setup
        # Model returns body-only prose (must be long enough to pass truncation).
        produced = "# Title\n\nSome body text for the note. " * 100
        result = await _write_back(ctx, "linker", produced)
        assert result is True
        written = note_path.read_text(encoding="utf-8")
        assert written.startswith("---\n")
        assert "tags: [philosophy, epistemology]" in written

    @pytest.mark.asyncio()
    async def test_chat_preamble_and_fence_stripped(self, setup: tuple[RunContext, Path]) -> None:
        """A chatty model's preamble and ``` fences must not land in the note."""
        ctx, note_path = setup
        produced = "Here is the corrected note:\n\n```markdown\n" + DISK_FM + BODY + "```"
        result = await _write_back(ctx, "formatter", produced)
        assert result is True
        written = note_path.read_text(encoding="utf-8")
        assert "Here is the corrected note" not in written
        assert "```" not in written

    @pytest.mark.asyncio()
    async def test_disk_note_with_no_frontmatter_candidate_written_as_is(self, tmp_path: Path) -> None:
        """When the disk note has no frontmatter, the candidate is written as-is."""
        vault = _scaffold(tmp_path)
        note_path = tmp_path / "vault" / "Art" / "test.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        # Write a note with no frontmatter.
        note_path.write_text(BODY, encoding="utf-8", newline="\n")
        ctx = _make_context(vault, note_path)

        new_body = BODY + "\n## New Section\n\nMore prose. " * 20
        result = await _write_back(ctx, "formatter", new_body)
        assert result is True
        written = note_path.read_text(encoding="utf-8")
        # No frontmatter should have been injected by the pipeline.
        assert written.startswith("# The Epistemic Gap")

    @pytest.mark.asyncio()
    async def test_truncation_rejected(self, setup: tuple[RunContext, Path]) -> None:
        """A note that has lost more than 25% of its body must be rejected."""
        ctx, note_path = setup
        # Return a much shorter candidate.
        short = DISK_FM + "# Title\n\nShort."
        result = await _write_back(ctx, "formatter", short)
        assert result is False
        # Note should be unchanged.
        written = note_path.read_text(encoding="utf-8")
        assert "Some prose about the limits of reason" in written

    @pytest.mark.asyncio()
    async def test_empty_candidate_returns_false(self, setup: tuple[RunContext, Path]) -> None:
        ctx, note_path = setup
        result = await _write_back(ctx, "formatter", "")
        assert result is False

    @pytest.mark.asyncio()
    async def test_model_frontmatter_diff_emits_warning(self, setup: tuple[RunContext, Path]) -> None:
        """When the model's FM differs from disk's, a warning is emitted."""
        ctx, note_path = setup
        bad_fm = (
            "---\n"
            "title: Different Title\n"
            "domain: science\n"
            "---\n"
        )
        produced = bad_fm + BODY
        bus = ctx.spec.bus
        queue = bus.subscribe()
        result = await _write_back(ctx, "formatter", produced)
        await bus.close()
        from avicenna.bus import drain
        events: list[Any] = []
        async for ev in drain(queue):
            events.append(ev)
        assert result is True
        warnings = [e for e in events if isinstance(e, LogMessage) and "frontmatter was discarded" in e.text]
        assert len(warnings) >= 1

    @pytest.mark.asyncio()
    async def test_word_count_reflects_final_text(self, setup: tuple[RunContext, Path]) -> None:
        ctx, note_path = setup
        produced = DISK_FM + BODY
        await _write_back(ctx, "formatter", produced)
        written = note_path.read_text(encoding="utf-8")
        assert ctx.total_words == len(written.split())

    @pytest.mark.asyncio()
    async def test_malformed_frontmatter_preserves_note_content(self, setup: tuple[RunContext, Path]) -> None:
        """Unterminated frontmatter followed by --- horizontal rule: content preserved."""
        ctx, note_path = setup
        produced = "---\n" + MALFORMED_FM_BODY
        result = await _write_back(ctx, "formatter", produced)
        assert result is True
        written = note_path.read_text(encoding="utf-8")
        # The Table of Contents must survive
        assert "> [!abstract] Table of Contents" in written
        assert "> - [[#Introduction]]" in written
        assert "> - [[#The Argument]]" in written
        assert "> - [[#Conclusion]]" in written
        # Every heading must survive
        assert "## Introduction" in written
        assert "## The Argument" in written
        assert "## Conclusion" in written
        # Disk frontmatter must be intact
        assert written.startswith("---\n")
        assert "tags: [philosophy, epistemology]" in written
        # No stray date:/status: leak into body
        body_part = written.split("---\n", 2)[-1] if written.count("---\n") >= 2 else ""
        assert "date: 2024-06-15" not in body_part
        assert "status: complete" not in body_part

    @pytest.mark.asyncio()
    async def test_malformed_frontmatter_large_block_preserved(self, setup: tuple[RunContext, Path]) -> None:
        """Large malformed block: still preserved, still not rejected as truncation."""
        ctx, note_path = setup
        # Build a large malformed block (many key: value lines)
        large_keys = "\n".join(f"key{i}: value{i}" for i in range(50))
        produced = "---\n" + large_keys + "\n" + BODY
        result = await _write_back(ctx, "formatter", produced)
        assert result is True
        written = note_path.read_text(encoding="utf-8")
        # Body must be preserved
        assert "## The Limits of Unaided Reason" in written
        assert "## The Shape of the Gap" in written
        # Disk frontmatter intact
        assert written.startswith("---\n")
        assert "tags: [philosophy, epistemology]" in written

    @pytest.mark.asyncio()
    async def test_wellformed_frontmatter_handled_as_before(self, setup: tuple[RunContext, Path]) -> None:
        """Regression: well-formed frontmatter block is handled exactly as before."""
        ctx, note_path = setup
        produced = DISK_FM + BODY
        result = await _write_back(ctx, "formatter", produced)
        assert result is True
        written = note_path.read_text(encoding="utf-8")
        assert written.startswith("---\n")
        assert "tags: [philosophy, epistemology]" in written
        assert "## The Limits of Unaided Reason" in written

    @pytest.mark.asyncio()
    async def test_body_beginning_with_horizontal_rule_not_damaged(self, setup: tuple[RunContext, Path]) -> None:
        """A note whose body legitimately begins with --- is not damaged."""
        ctx, note_path = setup
        # Make the body long enough to pass truncation check
        long_prose = "Some prose about the topic. " * 100
        produced = DISK_FM + "\n---\n\n## New Section\n\n" + long_prose
        result = await _write_back(ctx, "formatter", produced)
        assert result is True
        written = note_path.read_text(encoding="utf-8")
        assert "## New Section" in written
        assert written.startswith("---\n")
        assert "tags: [philosophy, epistemology]" in written

    @pytest.mark.asyncio()
    async def test_no_frontmatter_candidate_gets_disks(self, setup: tuple[RunContext, Path]) -> None:
        """A candidate with no frontmatter still gets the disk's frontmatter."""
        ctx, note_path = setup
        # Make the body long enough to pass truncation check
        long_prose = "Some body text for the note. " * 200
        produced = "# Title\n\n" + long_prose
        result = await _write_back(ctx, "formatter", produced)
        assert result is True
        written = note_path.read_text(encoding="utf-8")
        assert written.startswith("---\n")
        assert "tags: [philosophy, epistemology]" in written

    @pytest.mark.asyncio()
    async def test_malformed_frontmatter_emits_warning(self, setup: tuple[RunContext, Path]) -> None:
        """The malformed path emits a warning."""
        ctx, note_path = setup
        produced = "---\n" + MALFORMED_FM_BODY
        bus = ctx.spec.bus
        queue = bus.subscribe()
        result = await _write_back(ctx, "formatter", produced)
        await bus.close()
        from avicenna.bus import drain
        events: list[Any] = []
        async for ev in drain(queue):
            events.append(ev)
        assert result is True
        warnings = [e for e in events if isinstance(e, LogMessage) and "malformed frontmatter" in e.text]
        assert len(warnings) >= 1
