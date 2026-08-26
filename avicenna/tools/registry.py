"""ToolRegistry: single lookup surface over vault, MCP, and builtin tools.

spec_for_model() is the ONLY path from registry to provider.
Pipeline-only tools such as cleanup_chunks and update_moc can never
be selected by the model. ToolRegistry.runner satisfies the ToolRunner
protocol from Phase 3.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from avicenna.providers.base import ToolSpec
from avicenna.tools.base import Tool, ToolAccess, ToolSource


class ToolNameCollision(RuntimeError):
    pass


class _RegistryRunner:
    """Adapts ToolRegistry to the Phase 3 ToolRunner protocol."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._r = registry

    async def call(self, name: str, args: dict[str, Any]) -> str:
        result = await self._r.get(name).invoke(**args)
        return result.summary

    def source_of(self, name: str) -> str:
        return self._r.get(name).source.value

    def specs(self) -> list[ToolSpec]:
        return self._r.spec_for_model()


class ToolRegistry:
    """Single lookup surface over vault, MCP, and builtin tools."""

    _PRECEDENCE = {ToolSource.BUILTIN: 0, ToolSource.VAULT_PS1: 1, ToolSource.MCP: 2}

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self.runner = _RegistryRunner(self)

    def register(self, tool: Tool, *, replace: bool = False) -> str:
        existing = self._tools.get(tool.name)
        if existing is None or replace:
            self._tools[tool.name] = tool
            return tool.name
        if existing.source is tool.source:
            raise ToolNameCollision(f"duplicate tool {tool.name!r} from {tool.source.value}")
        loser = tool if self._PRECEDENCE[tool.source] > self._PRECEDENCE[existing.source] else existing
        winner = existing if loser is tool else tool
        alias = f"{loser.source.value}__{loser.name}"
        self._tools[winner.name] = winner
        self._tools[alias] = loser
        return alias if loser is tool else tool.name

    def has(self, name: str) -> bool:
        """Is this tool available?

        A vault may legitimately ship zero PowerShell tools (see `avicenna init`).
        Pipeline stages use this to degrade to a Python fallback instead of
        aborting, so a tool-less vault can still produce a complete note.
        """
        return name in self._tools

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool {name!r}; known: {sorted(self._tools)}") from exc

    def __iter__(self) -> Iterator[Tool]:
        return iter(dict.fromkeys(self._tools.values()))

    def names_from(self, source: ToolSource) -> set[str]:
        """Registry keys currently held by tools from `source`."""
        return {key for key, tool in self._tools.items() if tool.source is source}

    def spec_for_model(
        self,
        *,
        allow: Iterable[str] | None = None,
        deny: Iterable[str] | None = None,
    ) -> list[ToolSpec]:
        """The model-visible tool surface. The only registry-to-provider path.

        Specs are named by their **registry key**, not by `tool.name`. When two
        sources supply the same name the loser is kept under a
        `{source}__{name}` alias, but its `.name` attribute is unchanged — so
        naming specs after `.name` handed the model two entries with an
        identical name, one of them unreachable, and strict providers reject a
        duplicate outright. The key is what `get()` resolves, so the key is what
        the model must be told.
        """
        allowed = set(allow) if allow is not None else None
        denied = set(deny) if deny is not None else set()
        specs: list[ToolSpec] = []
        for key, tool in self._tools.items():
            if tool.access is not ToolAccess.MODEL_CALLABLE:
                continue
            if key in denied:
                continue
            if allowed is not None and key not in allowed:
                continue
            specs.append(ToolSpec(
                name=key,
                description=tool.description,
                parameters=dict(tool.parameters),
            ))
        return specs
