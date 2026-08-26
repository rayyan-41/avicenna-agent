"""Vault aggregate: binds protocol text, agents, skills, taxonomy and tools.

Vault.load assembles the full vault picture from disk, cross-validates
content-agent domains against the taxonomy, and populates the Phase 4
ToolRegistry with vault PowerShell tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from avicenna.tools.registry import ToolRegistry
from avicenna.vault.models import AgentDef, Taxonomy, VaultConfigError


@dataclass(slots=True)
class Vault:
    root: Path
    protocol_text: str                    # AGENTS.md, the orchestrator system prompt
    agents: dict[str, AgentDef]
    skills: dict[str, str]                # skill name -> SKILL.md text
    taxonomy: Taxonomy
    tools: ToolRegistry
    tmp_dir: Path
    #: Live MCPClientManager once attach_mcp has run, else None.
    _mcp_manager: Any = field(default=None, repr=False, compare=False)

    @classmethod
    def load(cls, root: Path, *, registry: ToolRegistry | None = None) -> Vault:
        from avicenna.tools.builtin import register_builtin_tools
        from avicenna.tools.vault_tools import register_vault_tools

        agents_dir = root / ".agents"
        protocol = (root / "AGENTS.md").read_text("utf-8")
        agents: dict[str, AgentDef] = {}
        agents_folder = agents_dir / "agents"
        if agents_folder.is_dir():
            for f in sorted(agents_folder.glob("*.md")):
                a = AgentDef.from_file(f)
                agents[a.name] = a
        skills = {
            d.name: (d / "SKILL.md").read_text("utf-8")
            for d in sorted((agents_dir / "skills").glob("*"))
            if (d / "SKILL.md").is_file()
        }
        taxonomy = Taxonomy.load(agents_dir / "taxonomy.json")
        reg = registry or ToolRegistry()
        # Builtins are registered here rather than by the caller so that every
        # entry point gets the same tool surface. They used to be added only on
        # the bridge path, which meant `avicenna note --no-tui` ran with a
        # smaller set of tools than the same command through the interface.
        register_builtin_tools(root, reg)
        register_vault_tools(root, reg)
        tmp = root / "_tmp"
        tmp.mkdir(exist_ok=True)
        vault = cls(root, protocol, agents, skills, taxonomy, reg, tmp)
        vault._cross_validate()
        return vault

    async def attach_mcp(self, *, timeout: float = 20.0) -> list[str]:
        """Connect this vault's MCP servers and register their tools.

        Separate from `load` because connecting is async and can be slow, and
        because a vault with no servers — which is every vault out of the box —
        must not pay for it. Returns the registry keys that were added.

        Until this existed, `register_mcp_tools` had no callers anywhere in the
        repo: the transport layer, the schema export and the access gating were
        all built and none of it ever reached the registry, so no MCP tool could
        be selected by any agent.
        """
        import asyncio

        from avicenna.config import Config
        from avicenna.tools.mcp_tools import register_mcp_tools

        if self._mcp_manager is not None:
            return []
        servers = [s for s in Config.load_mcp_config().servers if getattr(s, "enabled", True)]
        if not servers:
            return []

        from avicenna.mcp.mcp_client import MCPClientManager

        manager = MCPClientManager()
        for server in servers:
            try:
                await asyncio.wait_for(manager.connect_server(server), timeout=timeout)
            except Exception:  # noqa: BLE001 - a bad server must not sink the vault
                # Reported by `avicenna mcp test`; a run degrades to the tools
                # that did connect rather than failing outright.
                continue
        self._mcp_manager = manager
        return register_mcp_tools(manager, self.tools)

    async def detach_mcp(self) -> None:
        """Shut down any MCP servers this vault started."""
        manager, self._mcp_manager = self._mcp_manager, None
        if manager is not None:
            await manager.cleanup()

    def _cross_validate(self) -> None:
        for agent in self.agents.values():
            if agent.type == "content" and agent.domain not in self.taxonomy.domains:
                raise VaultConfigError(
                    f"{agent.path}: domain {agent.domain!r} is not in taxonomy.json domains"
                )

    def content_agent_for(self, domain: str) -> AgentDef:
        for agent in self.agents.values():
            if agent.type == "content" and agent.domain == domain:
                return agent
        raise VaultConfigError(f"no content agent registered for domain {domain!r}")

    def pipeline_agents(self) -> list[AgentDef]:
        return sorted((a for a in self.agents.values() if a.type == "pipeline"),
                      key=lambda a: a.stage or 0)
