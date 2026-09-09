"""Tests for `LinkingStage` — the seam, not the pure functions.

`tests/test_linking.py` covers the string and tag logic. What is left here is
everything the stage does around it: reading the entity slot off the note's own
tags, degrading when the vault has no `get_related_notes` tool, not repeating
inline links in the Related Notes section, and staying idempotent across the
resumed runs that re-enter it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from avicenna.bus import EventBus, drain
from avicenna.events import Event, NotesLinked
from avicenna.pipeline.context import RunContext, RunSpec
from avicenna.pipeline.stages import LinkingStage, _note_entities
from avicenna.providers.base import Completion
from avicenna.providers.fake import FakeProvider
from avicenna.tools.base import ToolResult, ToolSource
from avicenna.tools.contracts import CONTRACTS
from avicenna.vault.init_scaffold import init_vault
from avicenna.vault.registry import ThemeRegistry
from avicenna.vault.vault import Vault

TOPIC = "Kant's Debt to Rousseau"

BODY = (
    "# Kant's Debt to Rousseau\n"
    "\n"
    "## 1. The Encounter\n"
    "\n"
    "Kant read Rousseau closely, and said so. Rousseau taught him to honour "
    "ordinary people, which is a claim Kant repeats in the Remarks.\n"
    "\n"
    "## 2. The Consequence\n"
    "\n"
    "What Rousseau supplied was not an argument but a reorientation.\n"
)

FRONTMATTER = '---\ndate: 2026-09-09\ntags: [reason, philosophy, concept, ethics, rousseau, kant, cli]\n---\n\n'

TAGS = ["reason", "philosophy", "concept", "ethics", "rousseau", "kant", "cli"]


def _scaffold(tmp_path: Path) -> Vault:
    return Vault.load(init_vault(tmp_path / "vault"))


def _registry(tmp_path: Path) -> ThemeRegistry:
    path = tmp_path / "taxonomy.json"
    path.write_text(
        json.dumps({"themes": ["ethics", "philosophy"], "types": ["concept"]}, indent=2),
        encoding="utf-8", newline="\n",
    )
    return ThemeRegistry.load(path)


def _context(
    tmp_path: Path, *, body: str = BODY, write_note: bool = True,
) -> RunContext:
    """Build a context over the fixture note.

    `write_note=False` leaves whatever is on disk alone, which is what a
    resumed run sees — and the only way to test idempotency honestly.
    """
    vault = _scaffold(tmp_path)
    note = vault.root / "Reason" / "Kant's Debt to Rousseau.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    if write_note:
        note.write_text(FRONTMATTER + body, encoding="utf-8", newline="\n")
    spec = RunSpec(
        topic=TOPIC,
        provider=FakeProvider(script=lambda s, m: Completion(text="")),
        vault=vault,
        bus=EventBus(),
        run_id="test-run",
    )
    ctx = RunContext(spec=spec)
    ctx.note_path = note
    ctx.domain = "reason"
    ctx.tags = list(TAGS)
    ctx.theme_registry = _registry(tmp_path)
    return ctx


def _subject_note(ctx: RunContext, name: str) -> Path:
    """Give the vault a note filed under *name*, as a bio would be."""
    path = ctx.spec.vault.root / "History" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ntags: [history, biography, person, enlightenment, cli]\n---\n\nLife.\n",
        encoding="utf-8", newline="\n",
    )
    return path


class _FakeTool:
    """One scripted tool, returning a fixed stdout through the real contract."""

    name = "get_related_notes"
    source = ToolSource.VAULT_PS1

    def __init__(self, stdout: str, calls: list[dict[str, Any]]) -> None:
        self._stdout = stdout
        self._calls = calls

    async def invoke(self, **kwargs: Any) -> ToolResult:
        self._calls.append(kwargs)
        # Parsed by the real contract, so a change to the token regex breaks
        # these tests rather than passing them on a fixture that agrees with
        # nothing.
        parsed = CONTRACTS["get_related_notes"].parse(self.name, self._stdout, "", 0)
        return ToolResult(
            tool=self.name, ok=True, stdout=self._stdout, stderr="",
            exit_code=0, duration_s=0.0, parsed=parsed,
        )


class _FakeTools:
    """Stand in for the vault's tool registry with one scripted tool.

    `stdout=None` means the vault does not have the tool at all, which is a
    legitimate vault and the case the stage has to degrade through.
    """

    def __init__(self, stdout: str | None, runner: Any = None) -> None:
        self._stdout = stdout
        self.calls: list[dict[str, Any]] = []
        self.runner = runner

    def has(self, name: str) -> bool:
        return self._stdout is not None and name == "get_related_notes"

    def get(self, name: str) -> _FakeTool:
        assert self._stdout is not None and name == "get_related_notes"
        return _FakeTool(self._stdout, self.calls)


def _install_tools(ctx: RunContext, stdout: str | None) -> _FakeTools:
    tools = _FakeTools(stdout)
    object.__setattr__(ctx.spec.vault, "tools", tools)
    return tools


async def _run(ctx: RunContext) -> list[Event]:
    queue = ctx.spec.bus.subscribe()
    await LinkingStage().run(ctx)
    await ctx.spec.bus.close()
    return [ev async for ev in drain(queue)]


# ---------------------------------------------------------------------------
# The entity slot
# ---------------------------------------------------------------------------


class TestNoteEntities:
    def test_reads_the_tail_tags_that_are_not_themes(self, tmp_path: Path) -> None:
        ctx = _context(tmp_path)
        assert _note_entities(ctx) == ["rousseau", "kant"]

    def test_no_registry_yields_nothing(self, tmp_path: Path) -> None:
        """Without the theme vocabulary every theme reads as an entity.

        The note would then try to link to notes named after its own subject
        matter, so returning nothing is the only safe answer.
        """
        ctx = _context(tmp_path)
        ctx.theme_registry = None
        assert _note_entities(ctx) == []


# ---------------------------------------------------------------------------
# Inline entity links
# ---------------------------------------------------------------------------


class TestInlineLinks:
    def test_an_entity_with_a_note_is_linked_on_first_mention(
        self, tmp_path: Path,
    ) -> None:
        ctx = _context(tmp_path)
        _subject_note(ctx, "Jean-Jacques Rousseau")
        _install_tools(ctx, None)
        asyncio.run(_run(ctx))
        assert ctx.note_path is not None
        text = ctx.note_path.read_text("utf-8")
        assert text.count("[[Jean-Jacques Rousseau|Rousseau]]") == 1
        # And the later mentions are left as prose.
        assert "What Rousseau supplied" in text

    def test_an_entity_with_no_note_is_not_linked(self, tmp_path: Path) -> None:
        ctx = _context(tmp_path)
        _install_tools(ctx, None)
        asyncio.run(_run(ctx))
        assert ctx.note_path is not None
        assert "[[" not in ctx.note_path.read_text("utf-8")

    def test_the_note_never_links_to_itself(self, tmp_path: Path) -> None:
        """The note is about Kant; a self-link is not a connection."""
        ctx = _context(tmp_path)
        assert ctx.note_path is not None
        # The note is filed as "Kant's Debt to Rousseau" — both entity tags
        # could match it by surname if the source note were in the index.
        _install_tools(ctx, None)
        asyncio.run(_run(ctx))
        assert "[[Kant's Debt to Rousseau" not in ctx.note_path.read_text("utf-8")

    def test_the_frontmatter_is_untouched(self, tmp_path: Path) -> None:
        ctx = _context(tmp_path)
        _subject_note(ctx, "Jean-Jacques Rousseau")
        _install_tools(ctx, None)
        asyncio.run(_run(ctx))
        assert ctx.note_path is not None
        text = ctx.note_path.read_text("utf-8")
        assert text.startswith(FRONTMATTER.rstrip("\n").rstrip())
        assert "tags: [reason, philosophy, concept, ethics, rousseau, kant, cli]" in text


# ---------------------------------------------------------------------------
# Related notes
# ---------------------------------------------------------------------------


RELATED = (
    "CANDIDATES_FOUND: 2\n"
    "---\n"
    "SCORE:6 | MATCH:primary | PATH:V\\Reason\\Autonomy.md | TAGS:reason,philosophy,ethics,cli\n"
    "SCORE:4 | MATCH:primary | PATH:V\\History\\Jean-Jacques Rousseau.md | TAGS:history,biography,rousseau,cli\n"
    "---\n"
    "EXCLUDED_BY_POLICY: 0\n"
)


class TestRelatedNotes:
    def test_the_section_is_written(self, tmp_path: Path) -> None:
        ctx = _context(tmp_path)
        _install_tools(ctx, RELATED)
        asyncio.run(_run(ctx))
        assert ctx.note_path is not None
        text = ctx.note_path.read_text("utf-8")
        assert "## Related Notes" in text
        assert "- [[Autonomy]] — shared: reason, philosophy, ethics" in text

    def test_core_and_supporting_tags_are_split_at_the_entities(
        self, tmp_path: Path,
    ) -> None:
        """Core overlap decides the match tier; entities are only evidence."""
        ctx = _context(tmp_path)
        tools = _install_tools(ctx, RELATED)
        asyncio.run(_run(ctx))
        call = tools.calls[0]
        assert call["CoreTags"] == "reason, philosophy, concept, ethics, cli"
        assert call["SupportingTags"] == "rousseau, kant"

    def test_notes_already_linked_inline_are_excluded(self, tmp_path: Path) -> None:
        """The section must not repeat a connection the prose already made."""
        ctx = _context(tmp_path)
        _subject_note(ctx, "Jean-Jacques Rousseau")
        tools = _install_tools(ctx, RELATED)
        asyncio.run(_run(ctx))
        assert tools.calls[0]["ExcludedMentions"] == "Jean-Jacques Rousseau"

    def test_an_absent_tool_degrades_and_says_so(self, tmp_path: Path) -> None:
        """A vault with zero PowerShell tools is legitimate."""
        ctx = _context(tmp_path)
        _install_tools(ctx, None)
        events = asyncio.run(_run(ctx))
        warnings = [
            e for e in events
            if getattr(e, "level", "") == "warning"
            and "get_related_notes" in getattr(e, "text", "")
        ]
        assert warnings, "absent tool must be reported, not silently skipped"
        assert ctx.note_path is not None
        assert "## Related Notes" not in ctx.note_path.read_text("utf-8")

    def test_no_candidates_writes_no_section(self, tmp_path: Path) -> None:
        ctx = _context(tmp_path)
        _install_tools(
            ctx,
            "CANDIDATES_FOUND: 0\nNO_POLICY_VALID_CANDIDATES: none\n"
            "EXCLUDED_BY_POLICY: 0\n",
        )
        asyncio.run(_run(ctx))
        assert ctx.note_path is not None
        assert "## Related Notes" not in ctx.note_path.read_text("utf-8")


# ---------------------------------------------------------------------------
# The event, and running twice
# ---------------------------------------------------------------------------


class TestStageBehaviour:
    def test_the_event_reports_the_two_mechanisms_separately(
        self, tmp_path: Path,
    ) -> None:
        """They fail separately, so one combined count would hide which."""
        ctx = _context(tmp_path)
        _subject_note(ctx, "Jean-Jacques Rousseau")
        _install_tools(ctx, RELATED)
        events = asyncio.run(_run(ctx))
        linked = [e for e in events if isinstance(e, NotesLinked)]
        assert len(linked) == 1
        assert linked[0].inline == 1
        assert linked[0].related == 2
        assert linked[0].targets == ("Jean-Jacques Rousseau",)

    def test_running_twice_does_not_duplicate_anything(self, tmp_path: Path) -> None:
        """`--resume` re-enters this stage on a note that already has both."""
        ctx = _context(tmp_path)
        _subject_note(ctx, "Jean-Jacques Rousseau")
        _install_tools(ctx, RELATED)
        asyncio.run(_run(ctx))
        assert ctx.note_path is not None
        first = ctx.note_path.read_text("utf-8")

        ctx.spec.bus._closed = False  # type: ignore[attr-defined]
        second_ctx = _context(tmp_path)
        second_ctx.note_path = ctx.note_path
        _install_tools(second_ctx, RELATED)
        asyncio.run(_run(second_ctx))
        second = ctx.note_path.read_text("utf-8")

        assert second.count("## Related Notes") == 1
        assert second.count("[[Jean-Jacques Rousseau|Rousseau]]") == 1
        assert second == first

    def test_a_note_with_no_tags_is_left_alone(self, tmp_path: Path) -> None:
        ctx = _context(tmp_path)
        ctx.tags = []
        tools = _install_tools(ctx, RELATED)
        asyncio.run(_run(ctx))
        assert tools.calls == []
        assert ctx.note_path is not None
        assert "[[" not in ctx.note_path.read_text("utf-8")

    @pytest.mark.asyncio()
    async def test_should_run_needs_a_note_on_disk(self, tmp_path: Path) -> None:
        ctx = _context(tmp_path)
        assert await LinkingStage().should_run(ctx)
        ctx.note_path = None
        assert not await LinkingStage().should_run(ctx)


class TestVaultIndexExclusions:
    def test_this_runs_own_chunks_are_not_notes(self, tmp_path: Path) -> None:
        """`_tmp/` holds the note being written, in pieces, and is deleted last.

        Indexing it gave the linker the current note's own chunks as link
        targets, and made a wikilink to a chunk filename "resolve".
        """
        from avicenna.pipeline.stages import _build_vault_notes_index

        ctx = _context(tmp_path)
        tmp = ctx.spec.vault.root / "_tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        (tmp / "kants-debt_chunk_01.md").write_text("chunk\n", encoding="utf-8", newline="\n")
        index = _build_vault_notes_index(ctx.spec.vault, exclude=ctx.note_path)
        assert "kants-debt_chunk_01" not in index
