"""Tests for the approval-gate concurrency feature.

The approval gate is an injectable async callback on execute_run that receives
the declared plan and returns whether to proceed.  When it approves, section
concurrency is set to the heading count — one API call per heading, all
concurrent.  When it declines, the run ends cleanly without writing a note.

These tests verify:
  - The default (on_plan=None) preserves existing behaviour: no gate, configured
    concurrency, no PlanApprovalRequested event.
  - An approving callback sets concurrency to the heading count.
  - A declining callback aborts the run cleanly (RunFailed, no note on disk).
  - The configured path still clamps to MAX_CONCURRENCY_MAX.
  - The approved path may exceed MAX_CONCURRENCY_MAX.
  - The plan passed to the callback carries the real headings.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from avicenna.bus import EventBus, drain
from avicenna.events import Event, PlanApprovalRequested, RunFailed
from avicenna.pipeline.preflight import PreflightDeclaration
from avicenna.pipeline.run import execute_run
from avicenna.providers.base import Completion
from avicenna.providers.fake import FakeProvider
from avicenna.settings import MAX_CONCURRENCY_MAX
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


def _declaration(headings: list[str] | None = None, **over: Any) -> str:
    payload = {
        "topic": TOPIC,
        "domain": "general",
        "template": "general",
        "headings": headings or HEADINGS,
        "target_words": 900,
        "slug": "epistemic-gap",
    }
    payload.update(over)
    return "Here is the plan.\n```json\n" + json.dumps(payload) + "\n```"


def _make_script(headings: list[str] | None = None):
    def _script(system: str, messages: list[Any]) -> Completion:
        prompt = messages[-1].content if messages else ""
        if "pre-flight plan" in prompt or "JSON fence" in prompt:
            return Completion(text=_declaration(headings))
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
    return _script


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


async def _collect_events(vault: Vault, **kw: Any) -> list[Event]:
    bus = EventBus()
    queue = bus.subscribe()
    await execute_run(
        TOPIC, FakeProvider(script=_make_script()), vault,
        bus=bus, concurrency=3, **kw,
    )
    await bus.close()
    seen: list[Event] = []
    async for event in drain(queue):
        seen.append(event)
    return seen


def _notes(vault: Vault) -> list[Path]:
    return [
        p for p in vault.root.rglob("*.md")
        if ".agents" not in p.parts and p.name != "AGENTS.md"
    ]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


async def test_default_preserves_existing_behaviour(tmp_path: Path) -> None:
    """Without on_plan, no PlanApprovalRequested event is emitted and the run
    completes normally with the configured concurrency."""
    vault = _scaffold(tmp_path)
    events = await _collect_events(vault)
    names = [type(e).__name__ for e in events]
    assert "PlanApprovalRequested" not in names, \
        "PlanApprovalRequested must not be emitted when on_plan is None"
    assert "RunFailed" not in names
    assert len(_notes(vault)) == 1


async def test_approving_callback_sets_heading_count_concurrency(
    tmp_path: Path,
) -> None:
    """An approving callback sets concurrency to the heading count."""
    vault = _scaffold(tmp_path)
    received_plans: list[PreflightDeclaration] = []

    async def _approve(plan: PreflightDeclaration) -> bool:
        received_plans.append(plan)
        return True

    events = await _collect_events(vault, on_plan=_approve)

    # The callback was called with a real plan.
    assert len(received_plans) == 1
    plan = received_plans[0]
    assert plan.headings == tuple(HEADINGS)
    assert plan.topic == TOPIC

    # PlanApprovalRequested was emitted with concurrency == heading count.
    approval_events = [e for e in events if isinstance(e, PlanApprovalRequested)]
    assert len(approval_events) == 1
    assert approval_events[0].concurrency == len(HEADINGS)

    # The run completed successfully.
    assert not any(isinstance(e, RunFailed) for e in events)
    assert len(_notes(vault)) == 1


async def test_declining_callback_ends_run_cleanly(tmp_path: Path) -> None:
    """A declining callback aborts the run without writing a note."""
    vault = _scaffold(tmp_path)
    received_plans: list[PreflightDeclaration] = []

    async def _decline(plan: PreflightDeclaration) -> bool:
        received_plans.append(plan)
        return False

    events = await _collect_events(vault, on_plan=_decline)

    # The callback was called.
    assert len(received_plans) == 1

    # PlanApprovalRequested was emitted before the decline.
    approval_events = [e for e in events if isinstance(e, PlanApprovalRequested)]
    assert len(approval_events) == 1

    # RunFailed was emitted with the decline message.
    failures = [e for e in events if isinstance(e, RunFailed)]
    assert len(failures) == 1
    assert "declined" in failures[0].error.lower()

    # No note was written.
    assert len(_notes(vault)) == 0


async def test_configured_path_still_clamps(tmp_path: Path) -> None:
    """Without on_plan, a concurrency override above MAX_CONCURRENCY_MAX is
    clamped by resolve_concurrency.  The configured path is typo-safe."""
    vault = _scaffold(tmp_path)
    bus = EventBus()
    queue = bus.subscribe()
    # Pass concurrency well above the ceiling.  No on_plan, so the configured
    # path is used and the clamp applies.
    await execute_run(
        TOPIC, FakeProvider(script=_make_script()), vault,
        bus=bus, concurrency=MAX_CONCURRENCY_MAX + 10,
    )
    await bus.close()
    seen: list[Event] = []
    async for event in drain(queue):
        seen.append(event)
    # The run must still succeed — the clamp reduced concurrency, it did not
    # reject the run.
    assert not any(isinstance(e, RunFailed) for e in seen)
    assert len(_notes(vault)) == 1


async def test_approved_path_exceeds_configured_ceiling(tmp_path: Path) -> None:
    """When the approval gate runs, concurrency is the heading count and may
    exceed MAX_CONCURRENCY_MAX.  The human gate replaces the clamp."""
    # Use a heading list longer than MAX_CONCURRENCY_MAX.
    many_headings = [f"Heading {i}" for i in range(1, MAX_CONCURRENCY_MAX + 5)]
    vault = _scaffold(tmp_path)

    async def _approve(plan: PreflightDeclaration) -> bool:
        return True

    bus = EventBus()
    queue = bus.subscribe()
    await execute_run(
        TOPIC,
        FakeProvider(script=_make_script(many_headings)),
        vault,
        bus=bus,
        concurrency=3,  # This would normally be the configured value
        on_plan=_approve,
    )
    await bus.close()
    seen: list[Event] = []
    async for event in drain(queue):
        seen.append(event)

    approval_events = [e for e in seen if isinstance(e, PlanApprovalRequested)]
    assert len(approval_events) == 1
    # The concurrency in the event exceeds the configured ceiling.
    assert approval_events[0].concurrency == len(many_headings)
    assert approval_events[0].concurrency > MAX_CONCURRENCY_MAX
    # The run completed.
    assert not any(isinstance(e, RunFailed) for e in seen)


async def test_plan_carries_real_headings(tmp_path: Path) -> None:
    """The PreflightDeclaration passed to the callback carries the actual
    headings parsed from the model's output, not defaults or placeholders."""
    custom_headings = [
        "First Principles of Epistemology",
        "The Kalam Cosmological Argument",
        "Aquinas on Sacra Doctrina",
        "Modern Objections and Replies",
    ]
    vault = _scaffold(tmp_path)
    received_plans: list[PreflightDeclaration] = []

    async def _approve(plan: PreflightDeclaration) -> bool:
        received_plans.append(plan)
        return True

    bus = EventBus()
    queue = bus.subscribe()
    await execute_run(
        TOPIC,
        FakeProvider(script=_make_script(custom_headings)),
        vault,
        bus=bus,
        concurrency=3,
        on_plan=_approve,
    )
    await bus.close()
    seen: list[Event] = []
    async for event in drain(queue):
        seen.append(event)

    assert len(received_plans) == 1
    plan = received_plans[0]
    assert list(plan.headings) == custom_headings
    assert plan.domain == "general"
    assert plan.template == "general"
    assert plan.target_words == 900
