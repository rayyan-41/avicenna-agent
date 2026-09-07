"""Vault aggregate: binds protocol text, agents, skills, taxonomy and tools.

Vault.load assembles the full vault picture from disk, cross-validates
content-agent domains against the taxonomy, and populates the Phase 4
ToolRegistry with vault PowerShell tools.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from avicenna.tools.registry import ToolRegistry
from avicenna.vault.models import AgentDef, Taxonomy, VaultConfigError

_log = logging.getLogger(__name__)

#: Directories at the vault root that are never treated as domains.
_DOMAIN_EXCLUDE: frozenset[str] = frozenset({"_tmp"})


def _derive_domains(root: Path, exclude: frozenset[str] = _DOMAIN_EXCLUDE) -> dict[str, list[str]]:
    """Derive domains from the vault root's subdirectories.

    Dotted directories and anything in *exclude* are skipped.
    Returns ``{canonical_folder_name: [category_names]}`` where
    category names are the immediate subdirectories of each domain folder
    (excluding dotted directories).
    """
    domains: dict[str, list[str]] = {}
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name in exclude:
            continue
        cats = sorted(
            sub.name for sub in child.iterdir()
            if sub.is_dir() and not sub.name.startswith(".")
        )
        domains[child.name] = cats
    return domains


@dataclass(slots=True)
class Vault:
    root: Path
    protocol_text: str                    # AGENTS.md, the orchestrator system prompt
    agents: dict[str, AgentDef]
    skills: dict[str, str]                # skill name -> SKILL.md text
    taxonomy: Taxonomy
    tools: ToolRegistry
    tmp_dir: Path
    #: Canonical domain names → category lists, derived from the folder tree.
    _derived_domains: dict[str, list[str]] = field(default_factory=dict, repr=False)
    #: Reconciliation warnings (derived vs taxonomy.json drift).
    _domain_drift: list[str] = field(default_factory=list, repr=False)
    #: Live MCPClientManager once attach_mcp has run, else None.
    _mcp_manager: Any = field(default=None, repr=False, compare=False)

    # --- domain introspection ------------------------------------------------

    @property
    def domain_names(self) -> set[str]:
        """Lowercase domain names derived from the vault's folder tree."""
        return {k.lower() for k in self._derived_domains}

    def resolve_domain(self, name: str) -> str | None:
        """Case-insensitive lookup against the derived domain set.

        Returns the lowercase domain key or ``None`` if no folder matches.
        """
        lower = name.lower()
        for canonical in self._derived_domains:
            if canonical.lower() == lower:
                return lower
        return None

    def categories_for_domain(self, domain: str) -> list[str]:
        """Derived categories for *domain* (case-insensitive lookup).

        Returns the on-disk subfolder names, or an empty list when the domain
        has no subfolders or does not exist.
        """
        lower = domain.lower()
        for canonical, cats in self._derived_domains.items():
            if canonical.lower() == lower:
                return list(cats)
        return []

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
        derived = _derive_domains(root)
        vault = cls(
            root, protocol, agents, skills, taxonomy, reg, tmp,
            _derived_domains=derived,
        )
        vault._cross_validate()
        vault._reconcile_domains()
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
            if agent.type == "content" and agent.domain:
                if self.resolve_domain(agent.domain) is None:
                    raise VaultConfigError(
                        f"{agent.path}: domain {agent.domain!r} has no folder in the vault"
                    )

    def _reconcile_domains(self) -> None:
        """Compare derived domains against taxonomy.json and record drift.

        The derived set is authoritative for routing and placement. When it
        disagrees with the taxonomy file, the user needs to know — the vault's
        own ``validate_tags.ps1`` reads ``taxonomy.json`` directly and will
        reject notes the harness considers correctly filed.
        """
        tax_domains = set(self.taxonomy.domains)
        derived_lower = self.domain_names
        # Domains in folders but not in taxonomy
        folder_only = sorted(d for d in self._derived_domains if d.lower() not in tax_domains)
        # Domains in taxonomy but not as folders
        taxonomy_only = sorted(d for d in tax_domains if d not in derived_lower)
        for d in folder_only:
            msg = f"domain folder {d!r} exists on disk but is not in taxonomy.json domains"
            self._domain_drift.append(msg)
            _log.warning(msg)
        for d in taxonomy_only:
            msg = f"taxonomy.json domain {d!r} has no matching folder in the vault"
            self._domain_drift.append(msg)
            _log.warning(msg)

    def content_agent_for(self, domain: str) -> AgentDef:
        for agent in self.agents.values():
            if agent.type == "content" and agent.domain == domain:
                return agent
        raise VaultConfigError(f"no content agent registered for domain {domain!r}")

    def pipeline_agents(self) -> list[AgentDef]:
        return sorted((a for a in self.agents.values() if a.type == "pipeline"),
                      key=lambda a: a.stage or 0)
