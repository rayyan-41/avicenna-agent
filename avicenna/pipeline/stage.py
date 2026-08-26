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
    """One step of a run.

    Two identifiers, deliberately distinct:

    * ``name`` is the *user-facing* label that crosses the wire as a ``Stage``
      literal. Several stages legitimately share one — routing and pre-flight
      both read as "preflight" to the user, tagging and formatting both read
      as "tagging".
    * ``id`` is this stage's *identity*. It must be unique across the stage
      list, because timings, completion records and the dry-run filter key on
      it. These were once the same field, and the collision meant a stage's
      timing silently overwrote its neighbour's and the dry-run filter selected
      by label — so adding any future stage under an existing label would have
      silently joined the dry run.
    """

    name: Stage
    id: str = ""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Default the identity to the label, so a stage with no collision does
        # not have to declare the same string twice.
        if not cls.__dict__.get("id"):
            cls.id = cls.__dict__.get("name", getattr(cls, "name", "")) or cls.__name__

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
            # Keyed on identity, not label: two stages may share a label.
            ctx.timings[stage.id] = elapsed
            ctx.stages_completed.append(stage.id)
            await ctx.emit(StageCompleted, stage=stage.name, elapsed=elapsed)
        return True
