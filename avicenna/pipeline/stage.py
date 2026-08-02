"""PipelineStage ABC and PipelineRunner.

Every stage has a name and one coroutine. The runner owns timing,
StageEntered/StageCompleted, and failure translation. Resume becomes
a filter over a list.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod

from avicenna.events import RunFailed, Stage, StageCompleted, StageEntered
from avicenna.pipeline.context import RunContext


class PipelineAbort(Exception):
    """Raised by a stage to end the run without a traceback reaching the TUI."""

    def __init__(self, stage: Stage, message: str) -> None:
        super().__init__(message)
        self.stage: Stage = stage
        self.message: str = message


class PipelineStage(ABC):
    name: Stage

    async def should_run(self, ctx: RunContext) -> bool:
        return True

    @abstractmethod
    async def run(self, ctx: RunContext) -> None: ...


class PipelineRunner:
    def __init__(self, stages: list[PipelineStage]) -> None:
        self.stages: list[PipelineStage] = stages

    async def run(self, ctx: RunContext) -> bool:
        for stage in self.stages:
            if not await stage.should_run(ctx):
                continue
            await ctx.emit(StageEntered, stage=stage.name)
            start = time.perf_counter()
            try:
                await stage.run(ctx)
            except PipelineAbort as exc:
                await ctx.emit(RunFailed, error=exc.message, stage=exc.stage)
                return False
            except asyncio.CancelledError:
                await ctx.emit(RunFailed, error="cancelled by user", stage=stage.name)
                raise
            except Exception as exc:  # noqa: BLE001 - boundary
                await ctx.emit(
                    RunFailed, error=f"{type(exc).__name__}: {exc}", stage=stage.name
                )
                return False
            elapsed = time.perf_counter() - start
            ctx.timings[stage.name] = elapsed
            ctx.stages_completed.append(stage.name)
            await ctx.emit(StageCompleted, stage=stage.name, elapsed=elapsed)
        return True
