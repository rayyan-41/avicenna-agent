"""Contract-gated tool invocation for the pipeline."""

from __future__ import annotations

from typing import Any

from avicenna.events import ToolInvoked, ToolReturned
from avicenna.pipeline.context import RunContext
from avicenna.tools.base import ToolResult


async def invoke_tool(
    ctx: RunContext, name: str, *, section_index: int | None = None, **kwargs: Any
) -> ToolResult:
    tool = ctx.spec.vault.tools.get(name)
    await ctx.emit(
        ToolInvoked, name=name, args=dict(kwargs),
        source=tool.source.value, section_index=section_index,
    )
    result = await tool.invoke(**kwargs)
    await ctx.emit(
        ToolReturned, name=name,
        contract=(result.parsed.token if result.parsed else ""),
        ok=bool(result.parsed and result.parsed.ok),
        elapsed=result.duration_s, section_index=section_index,
    )
    return result
