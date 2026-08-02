"""Vault aggregate: binds protocol text, agents, skills, taxonomy and tools.

Vault.load assembles the full vault picture from disk, cross-validates
content-agent domains against the taxonomy, and populates the Phase 4
ToolRegistry with vault PowerShell tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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

    @classmethod
    def load(cls, root: Path, *, registry: ToolRegistry | None = None) -> Vault:
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
        register_vault_tools(root, reg)
        tmp = root / "_tmp"
        tmp.mkdir(exist_ok=True)
        vault = cls(root, protocol, agents, skills, taxonomy, reg, tmp)
        vault._cross_validate()
        return vault

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
