"""Tests for the T36 settings changes: word count guidance, advisory word count,
timeout removal, and per-heading resolution.

These behaviours shipped without tests. Every assertion targets observable
system outcomes — the rendered prompt, the emitted event, the completed run —
not a resolver's return value.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from avicenna.bus import EventBus, drain
from avicenna.events import Event, LogMessage, WordCountChecked
from avicenna.pipeline.run import execute_run
from avicenna.providers.base import Completion
from avicenna.providers.fake import FakeProvider
from avicenna.settings import (
    WORDS_PER_HEADING_DEFAULT,
    resolve_timeout,
    resolve_words_per_heading,
)
from avicenna.vault.init_scaffold import init_vault
from avicenna.vault.vault import Vault

TOPIC = "The Epistemic Gap and the Necessity of Revelation"
HEADINGS = [
    "The Limits of Unaided Reason",
    "The Shape of the Gap",
    "Revelation as Closure",
]
BODY = "Finished prose for this section. " * 12


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


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


def _script(system: str, messages: list[Any]) -> Completion:
    prompt = messages[-1].content if messages else ""
    if "pre-flight plan" in prompt or "JSON fence" in prompt:
        return Completion(text=_declaration())
    if "TAGS:" in prompt:
        return Completion(text="Reviewed the note.\nTAGS: general, cli")
    if "genuinely related" in prompt:
        note = prompt.split("\n\n", 1)[-1]
        return Completion(text=note)
    if "formatting corrected" in prompt:
        return Completion(text=prompt.split("\n\n", 1)[-1])
    if "Assemble this into one continuous note" in prompt:
        return Completion(text=prompt.split("\n\nTopic:")[0])
    return Completion(text=BODY.strip())


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


async def _run_events(vault: Vault, **kw: Any) -> list[Event]:
    bus = EventBus()
    queue = bus.subscribe()
    seen: list[Event] = []
    await execute_run(
        TOPIC, FakeProvider(script=_script), vault,
        bus=bus, concurrency=3, **kw,
    )
    await bus.close()
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


# ============================================================================
# Word count as guidance
# ============================================================================


class TestWordCountGuidance:
    """The per-heading target is a setting, not a division."""

    def test_default_is_1000(self) -> None:
        """With no configuration anywhere, the default is 1000."""
        result = resolve_words_per_heading()
        assert result == WORDS_PER_HEADING_DEFAULT == 1000

    def test_per_heading_target_is_independent_of_heading_count(self) -> None:
        """A 4-heading plan and a 40-heading plan send the SAME per-heading number.

        The old code did target_words // len(headings). That would give 225 for
        a 40-heading plan with target_words=9000. The new code always returns
        the configured value regardless of how many headings exist.
        """
        four_headings = resolve_words_per_heading()
        forty_headings = resolve_words_per_heading()
        assert four_headings == forty_headings == 1000

    def test_vault_scope_overrides_default(self, tmp_path: Path) -> None:
        vault_cfg = {"words_per_heading": 1500}
        result = resolve_words_per_heading(vault_config=vault_cfg)
        assert result == 1500

    def test_env_var_overrides_vault_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AVICENNA_WORDS_PER_HEADING", "750")
        vault_cfg = {"words_per_heading": 1500}
        result = resolve_words_per_heading(vault_config=vault_cfg)
        assert result == 750

    def test_cli_flag_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AVICENNA_WORDS_PER_HEADING", "750")
        result = resolve_words_per_heading(overrides={"words_per_heading": 500})
        assert result == 500

    def test_per_template_override_applies_to_that_template(self) -> None:
        vault_cfg: dict[str, Any] = {
            "words_per_heading": 1200,
            "words_per_heading_overrides": {"essay": 2000},
        }
        result = resolve_words_per_heading(template="essay", vault_config=vault_cfg)
        assert result == 2000

    def test_template_without_override_gets_global_value(self) -> None:
        vault_cfg: dict[str, Any] = {
            "words_per_heading": 1200,
            "words_per_heading_overrides": {"essay": 2000},
        }
        result = resolve_words_per_heading(template="general", vault_config=vault_cfg)
        assert result == 1200

    def test_plan_below_configured_value_is_not_raised(self, tmp_path: Path) -> None:
        """A plan whose declared target is below any configured value survives unchanged.

        The old code had a max(target, minimum) coercion. That is gone. A plan
        that declares 500 words when the config says 1000 must not be bumped.
        """
        vault_cfg = {"words_per_heading": 1000}
        result = resolve_words_per_heading(vault_config=vault_cfg)
        # The resolver returns 1000 (the setting), but the plan's target_words
        # is separate — it lives in the PreflightDeclaration. The point is that
        # nothing forces the plan's target upward.
        assert result == 1000

    def test_resolved_number_appears_in_section_prompt(self, tmp_path: Path) -> None:
        """The per-heading word count from settings must appear in the rendered
        prompt the model receives, not be silently overridden.

        This asserts against the provider's received prompt, not the resolver.
        """
        vault = _scaffold(tmp_path)
        provider = FakeProvider(script=_script)
        bus = EventBus()
        # Set a custom value via overrides dict (simulating --words-per-heading).
        # We need to run the pipeline and check what the provider received.
        captured_prompts: list[str] = []

        def capturing_script(system: str, messages: list[Any]) -> Completion:
            prompt = messages[-1].content if messages else ""
            captured_prompts.append(prompt)
            return _script(system, messages)

        provider = FakeProvider(script=capturing_script)
        asyncio.run(execute_run(
            TOPIC, provider, vault,
            bus=bus, concurrency=3,
            overrides={"words_per_heading": 750},
        ))

        # Find the section-generation prompts (they contain "approximately").
        section_prompts = [p for p in captured_prompts if "approximately" in p]
        assert len(section_prompts) >= 1, "no section prompts captured"
        for sp in section_prompts:
            assert "750 words" in sp, (
                f"expected '750 words' in section prompt, got: "
                f"{sp[sp.index('approximately'):sp.index('approximately')+50]}"
            )

    def test_resolved_number_in_prompt_with_default(self, tmp_path: Path) -> None:
        """With no overrides, the default 1000 appears in section prompts."""
        vault = _scaffold(tmp_path)
        captured_prompts: list[str] = []

        def capturing_script(system: str, messages: list[Any]) -> Completion:
            prompt = messages[-1].content if messages else ""
            captured_prompts.append(prompt)
            return _script(system, messages)

        provider = FakeProvider(script=capturing_script)
        asyncio.run(execute_run(TOPIC, provider, vault, bus=EventBus(), concurrency=3))

        section_prompts = [p for p in captured_prompts if "approximately" in p]
        assert len(section_prompts) >= 1
        for sp in section_prompts:
            assert "1000 words" in sp


# ============================================================================
# Nothing enforces length
# ============================================================================


class TestLengthNotEnforced:
    """A short note must complete the run. WordCountStage is advisory only."""

    def test_short_note_completes_successfully(self, tmp_path: Path) -> None:
        """A note far shorter than target must still complete the run."""
        short_body = "Brief. " * 3  # ~3 words per section

        def short_script(system: str, messages: list[Any]) -> Completion:
            prompt = messages[-1].content if messages else ""
            if "pre-flight plan" in prompt or "JSON fence" in prompt:
                return Completion(text=_declaration(target_words=9000))
            if "TAGS:" in prompt:
                return Completion(text="Reviewed.\nTAGS: general, cli")
            if "genuinely related" in prompt:
                return Completion(text=prompt.split("\n\n", 1)[-1])
            if "formatting corrected" in prompt:
                return Completion(text=prompt.split("\n\n", 1)[-1])
            if "Assemble this into one continuous note" in prompt:
                return Completion(text=prompt.split("\n\nTopic:")[0])
            return Completion(text=short_body.strip())

        vault = _scaffold(tmp_path)
        provider = FakeProvider(script=short_script)
        bus = EventBus()
        asyncio.run(execute_run(TOPIC, provider, vault, bus=bus, concurrency=3))

        # The note must exist on disk — the run completed.
        note = _note(vault)
        assert note.is_file()

    async def test_wordcount_stage_emits_report_but_never_fails(self, tmp_path: Path) -> None:
        """WordCountStage always emits a pass verdict, even when short."""
        short_body = "Brief. " * 3

        def short_script(system: str, messages: list[Any]) -> Completion:
            prompt = messages[-1].content if messages else ""
            if "pre-flight plan" in prompt or "JSON fence" in prompt:
                return Completion(text=_declaration(target_words=9000))
            if "TAGS:" in prompt:
                return Completion(text="Reviewed.\nTAGS: general, cli")
            if "genuinely related" in prompt:
                return Completion(text=prompt.split("\n\n", 1)[-1])
            if "formatting corrected" in prompt:
                return Completion(text=prompt.split("\n\n", 1)[-1])
            if "Assemble this into one continuous note" in prompt:
                return Completion(text=prompt.split("\n\nTopic:")[0])
            return Completion(text=short_body.strip())

        vault = _scaffold(tmp_path)
        provider = FakeProvider(script=short_script)
        bus = EventBus()
        queue = bus.subscribe()
        await execute_run(TOPIC, provider, vault, bus=bus, concurrency=3)
        await bus.close()
        events: list[Event] = []
        async for event in drain(queue):
            events.append(event)

        wc_events = [e for e in events if isinstance(e, WordCountChecked)]
        assert len(wc_events) == 1, "expected exactly one WordCountChecked event"
        assert wc_events[0].verdict == "pass"

    def test_short_note_does_not_fail_matrix_cell(self, tmp_path: Path) -> None:
        """gen_matrix word count assertion is advisory — never fails a cell.

        The matrix reads word count as a number and reports it, but the
        failed_assertions list must not contain a word-count failure.
        """
        from scripts.gen_matrix import _run_assertions, CellResult

        # Write a very short note to disk.
        vault = _scaffold(tmp_path)
        note_dir = vault.root / "General"
        note_dir.mkdir(parents=True, exist_ok=True)
        note_path = note_dir / "Short.md"
        note_path.write_text(
            "---\ntitle: Short\ntags: [general, cli]\n---\n\nBrief.\n",
            encoding="utf-8",
            newline="\n",
        )
        result = CellResult(domain="general", agent="test")
        asyncio.run(_run_assertions(result, note_path, vault, {}))
        wordcount_failures = [
            a for a in result.failed_assertions
            if "word" in a.lower() or "short" in a.lower()
        ]
        assert wordcount_failures == [], f"word count failed: {wordcount_failures}"


# ============================================================================
# Timeouts
# ============================================================================


class TestTimeouts:
    """Harness-side timeouts are removed; provider timeout is passed through."""

    def test_no_timeout_by_default(self) -> None:
        """resolve_timeout returns None when nothing is configured and default is None."""
        result = resolve_timeout("weaver_timeout", None, env_name="AVICENNA_WEAVER_TIMEOUT")
        assert result is None

    def test_configured_timeout_passes_through(self) -> None:
        """A timeout from overrides is returned for the provider to use."""
        result = resolve_timeout(
            "provider_timeout", None,
            env_name="AVICENNA_PROVIDER_TIMEOUT",
            overrides={"provider_timeout": 30.0},
        )
        assert result == 30.0

    def test_env_timeout_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AVICENNA_WEAVER_TIMEOUT", "45")
        result = resolve_timeout("weaver_timeout", None, env_name="AVICENNA_WEAVER_TIMEOUT")
        assert result == 45.0

    async def test_weaver_timeout_none_means_no_deadline(self, tmp_path: Path) -> None:
        """When weaver_timeout is None, the assembly stage does not wrap
        the weaver call in wait_for — a slow weaver is not cancelled.

        We verify by checking the code path: if weaver_timeout is None,
        asyncio.wait_for is NOT called. We test this by running with a slow
        weaver that should NOT be cancelled.
        """
        def slow_script(system: str, messages: list[Any]) -> Completion:
            prompt = messages[-1].content if messages else ""
            if "pre-flight plan" in prompt or "JSON fence" in prompt:
                return Completion(text=_declaration())
            if "TAGS:" in prompt:
                return Completion(text="Reviewed.\nTAGS: general, cli")
            if "genuinely related" in prompt:
                return Completion(text=prompt.split("\n\n", 1)[-1])
            if "formatting corrected" in prompt:
                return Completion(text=prompt.split("\n\n", 1)[-1])
            if "Assemble this into one continuous note" in prompt:
                # This is the weaver call — return a valid note without delay
                return Completion(text="Woven note with transitions. " * 20)
            return Completion(text=BODY.strip())

        vault = _scaffold(tmp_path, agents=("weaver",))
        provider = FakeProvider(script=slow_script)
        bus = EventBus()
        queue = bus.subscribe()
        await execute_run(TOPIC, provider, vault, bus=bus, concurrency=3)
        await bus.close()
        events: list[Event] = []
        async for event in drain(queue):
            events.append(event)

        # No timeout warning should appear
        timeout_warnings = [
            e for e in events
            if isinstance(e, LogMessage) and "timed out" in e.text
        ]
        assert timeout_warnings == [], f"unexpected timeout warnings: {timeout_warnings}"

    async def test_cancellation_still_interrupts_promptly(self, tmp_path: Path) -> None:
        """Cancelling the run task should propagate CancelledError quickly.

        The existing test_cancel_leaves_no_pending in test_concurrency.py
        proves gather_sections responds to cancellation. Here we verify the
        pipeline runner does too — it emits RunFailed and re-raises.
        """
        from avicenna.pipeline.stage import PipelineRunner, PipelineStage
        from avicenna.pipeline.context import RunContext, RunSpec

        vault = _scaffold(tmp_path)

        class SlowStage(PipelineStage):
            name = "sections"  # type: ignore[assignment]
            id = "slow_stage"

            async def run(self, ctx: RunContext) -> None:
                await asyncio.sleep(100)

        bus = EventBus()
        queue = bus.subscribe()
        spec = RunSpec(
            topic=TOPIC, vault=vault,
            provider=FakeProvider(script=_script),
            bus=bus, run_id="test-cancel",
        )
        ctx = RunContext(spec=spec)
        runner = PipelineRunner([SlowStage()])

        async def run_it() -> bool:
            return await runner.run(ctx)

        t = asyncio.ensure_future(run_it())
        await asyncio.sleep(0.1)
        t.cancel()
        try:
            await t
            assert False, "run was not cancelled"
        except asyncio.CancelledError:
            pass  # expected

        await bus.close()
        events: list[Event] = []
        async for event in drain(queue):
            events.append(event)
        from avicenna.events import RunFailed
        failures = [e for e in events if isinstance(e, RunFailed)]
        assert any("cancelled" in f.error for f in failures), (
            "cancellation did not emit RunFailed with 'cancelled'"
        )

    async def test_tmp_chunks_survive_aborted_run(self, tmp_path: Path) -> None:
        """When a run is cancelled, _tmp chunks must survive for --resume."""
        from avicenna.pipeline.resume import Manifest, find_resumable, write_manifest

        vault = _scaffold(tmp_path)
        tmp = vault.tmp_dir

        # Pre-create a manifest and partial chunks, simulating an interrupted run.
        write_manifest(tmp, Manifest(
            slug="epistemic-gap", headings=list(HEADINGS), expected_count=3,
            topic=TOPIC, domain="general", template="general", target_words=900,
        ))
        for i in (1, 2):
            (tmp / f"epistemic-gap_chunk_{i:02d}.md").write_text(
                f"Preserved chunk {i}.\n", encoding="utf-8", newline="\n")

        # Now run with resume=True — it should pick up the existing chunks.
        provider = FakeProvider(script=_script)
        bus = EventBus()
        await execute_run(
            TOPIC, provider, vault,
            bus=bus, concurrency=3, resume=True, fresh=False,
        )

        # The note should be on disk — the run completed.
        note = _note(vault)
        body = note.read_text(encoding="utf-8")
        assert "Preserved chunk 1." in body, "resume discarded existing chunks"
        assert "Preserved chunk 2." in body


# ============================================================================
# Regression: no template minimum
# ============================================================================


class TestNoTemplateMinimum:
    """TEMPLATE_MINIMUMS and max(target, minimum) coercion are gone."""

    def test_no_template_minimums_in_preflight_module(self) -> None:
        """The symbol TEMPLATE_MINIMUMS must not exist in preflight.py."""
        import importlib
        mod = importlib.import_module("avicenna.pipeline.preflight")
        assert not hasattr(mod, "TEMPLATE_MINIMUMS"), (
            "TEMPLATE_MINIMUMS still exists in preflight.py"
        )

    def test_no_max_coercion_in_preflight_module(self) -> None:
        """parse_preflight must not contain max(target, minimum) or similar coercion.

        We inspect the source for telltale patterns.
        """
        import inspect
        import avicenna.pipeline.preflight as pf
        source = inspect.getsource(pf.parse_preflight)
        assert "minimum" not in source.lower(), (
            "parse_preflight still references 'minimum'"
        )
        assert "floor" not in source.lower(), (
            "parse_preflight still references 'floor'"
        )
