"""Delegate: load a named agent's markdown body as the system prompt.

DELEGATE @agent is literally one_shot with system = agent.system_prompt.
"""

from __future__ import annotations

from avicenna.pipeline.context import RunContext
from avicenna.providers.base import ToolSpec
from avicenna.session import one_shot
from avicenna.tools.base import ToolSource
from avicenna.vault.models import AgentDef
from avicenna.vault.vault import Vault


def tools_for_agent(vault: Vault, agent: AgentDef) -> list[ToolSpec]:
    """The tool surface one agent may see.

    Vault scripts and builtins are open to every agent; MCP is opt-in per agent
    through the `mcp:` key in its frontmatter. That key was parsed, reported
    over the wire, and then consulted by nothing — every agent was offered every
    registered tool. Since MCP reaches outside the vault, "declared rather than
    arbitrary" has to be enforced here or it is not enforced at all.
    """
    registry = vault.tools
    mcp_names = registry.names_from(ToolSource.MCP)
    if not mcp_names:
        return registry.spec_for_model()

    requested = {str(name) for name in (agent.mcp or [])}
    # An agent's `mcp:` entry may name a server or an individual tool; a server
    # entry admits every tool that server contributed, which arrive prefixed.
    permitted = {
        name for name in mcp_names
        if name in requested or any(name.startswith(f"{r}__") or name.startswith(f"{r}_") for r in requested)
    }
    return registry.spec_for_model(deny=mcp_names - permitted)


async def delegate(ctx: RunContext, agent_name: str, payload: str) -> str:
    vault = ctx.spec.vault
    agent = vault.agents[agent_name]
    allowed = tools_for_agent(vault, agent)
    return await one_shot(
        provider=ctx.spec.provider,
        system=agent.system_prompt,
        prompt=payload,
        tools=allowed or None,
        tool_runner=vault.tools.runner if allowed else None,
        bus=ctx.spec.bus,
        run_id=ctx.spec.run_id,
    )
