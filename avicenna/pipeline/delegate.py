"""Delegate: load a named agent's markdown body as the system prompt.

DELEGATE @agent is literally one_shot with system = agent.system_prompt.
"""

from __future__ import annotations

from avicenna.pipeline.context import RunContext
from avicenna.session import one_shot


async def delegate(ctx: RunContext, agent_name: str, payload: str) -> str:
    vault = ctx.spec.vault
    agent = vault.agents[agent_name]
    allowed = vault.tools.spec_for_model()
    return await one_shot(
        provider=ctx.spec.provider,
        system=agent.system_prompt,
        prompt=payload,
        tools=allowed or None,
        tool_runner=vault.tools.runner if allowed else None,
        bus=ctx.spec.bus,
        run_id=ctx.spec.run_id,
    )
