"""Run orchestration: build_stages, execute_run, cancellation, dry-run."""

from __future__ import annotations

import asyncio
import time
import uuid

from avicenna.bus import EventBus
from avicenna.events import RunComplete, RunFailed, RunStarted
from avicenna.pipeline.context import RunContext, RunSpec
from avicenna.pipeline.stage import PipelineAbort, PipelineRunner
from avicenna.pipeline.stages import build_stages
from avicenna.providers.base import LLMProvider


async def execute_run(
    topic: str,
    provider: LLMProvider,
    vault,
    *,
    bus: EventBus | None = None,
    run_id: str | None = None,
    concurrency: int = 3,
    dry_run: bool = False,
    domain_override: str | None = None,
    template_override: str | None = None,
    fresh: bool = True,
) -> None:
    rid = run_id or str(uuid.uuid4())[:8]
    bus = bus or EventBus()
    spec = RunSpec(
        topic=topic, vault=vault, provider=provider, bus=bus,
        run_id=rid, concurrency=concurrency, dry_run=dry_run,
        fresh=fresh, domain_override=domain_override,
        template_override=template_override,
    )
    ctx = RunContext(spec=spec)
    await bus.emit(RunStarted(
        run_id=rid, topic=topic,
        provider=provider.name, model=getattr(provider, '_model', ''),
    ))

    stages = build_stages()

    if dry_run:
        # In dry-run, only routing and preflight run
        dry_stages = [s for s in stages if s.name == "preflight"]
        runner = PipelineRunner(dry_stages)
        ok = await runner.run(ctx)
        if ok:
            await bus.emit(
                RunComplete, summary=f"dry-run: {ctx.slug}", elapsed=time.time() - ctx.started_at,
                total_words=ctx.target_words,
            )
        return

    try:
        runner = PipelineRunner(stages)
        ok = await runner.run(ctx)
    except asyncio.CancelledError:
        await bus.emit(RunFailed(error="cancelled by user"))
        raise
    finally:
        pass  # _tmp is left intact

    if ok:
        await bus.emit(
            RunComplete,
            summary=f"note written to {ctx.note_path}",
            elapsed=time.time() - ctx.started_at,
            total_words=ctx.total_words,
        )
