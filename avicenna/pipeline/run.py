"""Run orchestration: build_stages, execute_run, cancellation, dry-run."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from avicenna.bus import EventBus
from avicenna.events import RunComplete, RunFailed, RunStarted
from avicenna.pipeline.context import RunContext, RunSpec
from avicenna.pipeline.stage import PipelineAbort, PipelineRunner
from avicenna.pipeline.stages import build_stages
from avicenna.providers.base import LLMProvider


#: Stage identities that constitute a dry run: decide the agent, then declare
#: the structure. Selected by identity rather than by the user-facing label,
#: because several stages share a label and a label filter would silently
#: enrol any future stage that reused one.
DRY_RUN_STAGES: frozenset[str] = frozenset({"routing", "preflight"})


async def execute_run(
    topic: str,
    provider: LLMProvider,
    vault: Any,
    *,
    bus: EventBus | None = None,
    run_id: str | None = None,
    concurrency: int = 3,
    dry_run: bool = False,
    domain_override: str | None = None,
    template_override: str | None = None,
    fresh: bool = True,
    resume: bool = False,
) -> None:
    rid = run_id or str(uuid.uuid4())[:8]
    bus = bus or EventBus()
    spec = RunSpec(
        topic=topic, vault=vault, provider=provider, bus=bus,
        run_id=rid, concurrency=concurrency, dry_run=dry_run,
        fresh=fresh, resume=resume, domain_override=domain_override,
        template_override=template_override,
    )
    ctx = RunContext(spec=spec)
    await bus.emit(RunStarted(
        run_id=rid, topic=topic,
        provider=provider.name, model=getattr(provider, '_model', ''),
    ))

    stages = build_stages()

    if dry_run:
        # Route and declare structure; write nothing.
        dry_stages = [s for s in stages if s.id in DRY_RUN_STAGES]
        runner = PipelineRunner(dry_stages)
        ok = await runner.run(ctx)
        if ok:
            await bus.emit(RunComplete(
                run_id=rid, summary=f"dry-run: {ctx.slug}",
                elapsed=time.time() - ctx.started_at,
                total_words=ctx.target_words,
            ))
        return

    try:
        runner = PipelineRunner(stages)
        ok = await runner.run(ctx)
    except asyncio.CancelledError:
        # _tmp is deliberately left intact so --resume can pick the run back up.
        # PipelineRunner has already emitted RunFailed with the stage attributed,
        # so emitting again here would show the user two failures for one cancel.
        raise

    if ok:
        await bus.emit(RunComplete(
            run_id=rid,
            summary=f"note written to {ctx.note_path}",
            elapsed=time.time() - ctx.started_at,
            total_words=ctx.total_words,
        ))
