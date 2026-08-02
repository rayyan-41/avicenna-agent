"""ToolRunner protocol and MCPToolRunner adapter.

Session uses this protocol so it never imports MCP directly.
"""

from __future__ import annotations

from typing import Protocol

from avicenna.providers.base import ToolSpec


class ToolRunner(Protocol):
    async def call(self, name: str, args: dict) -> str: ...
    def source_of(self, name: str) -> str: ...
    def specs(self) -> list[ToolSpec]: ...


class MCPToolRunner:
    """Adapts MCPClientManager to the ToolRunner protocol."""

    def __init__(self, manager):
        from avicenna.mcp.mcp_client import MCPClientManager
        self._manager: MCPClientManager = manager

    async def call(self, name: str, args: dict) -> str:
        return await self._manager.call_tool(name, args)

    def source_of(self, name: str) -> str:
        return "mcp"

    def specs(self) -> list[ToolSpec]:
        return self._manager.tool_specs()
