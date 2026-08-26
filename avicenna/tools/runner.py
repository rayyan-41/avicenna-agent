"""The ToolRunner protocol.

Session depends on this rather than on any concrete registry, so it never
imports MCP — or PowerShell, or anything else that knows how a tool actually
runs. `ToolRegistry.runner` is the implementation the pipeline uses.

An `MCPToolRunner` adapter used to live here as well. It was dead: MCP tools go
into the same `ToolRegistry` as everything else (see `tools/mcp_tools.py`), so
there is nothing for a second, MCP-only runner to do, and routing MCP calls
around the registry would have skipped the access gating the registry enforces.
"""

from __future__ import annotations

from typing import Any, Protocol

from avicenna.providers.base import ToolSpec


class ToolRunner(Protocol):
    async def call(self, name: str, args: dict[str, Any]) -> str: ...
    def source_of(self, name: str) -> str: ...
    def specs(self) -> list[ToolSpec]: ...
