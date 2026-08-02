"""MCP tool integration.

MCPTool wraps MCPClientManager.call_tool and registers from
tool_specs(). MCP tools join the same lookup and the same access
gating as vault scripts.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from avicenna.tools.base import Tool, ToolAccess, ToolResult, ToolSource


class MCPTool(Tool):
    source = ToolSource.MCP
    access = ToolAccess.MODEL_CALLABLE

    def __init__(self, manager, name: str,
                 description: str, parameters: Mapping[str, object]) -> None:
        self._manager = manager
        self.name = name
        self.description = description
        self.parameters = parameters

    async def invoke(self, **kwargs: Any) -> ToolResult:
        started = time.perf_counter()
        try:
            payload = await self._manager.call_tool(self.name, kwargs)
        except Exception as exc:  # noqa: BLE001 - transport or server-side failure
            return ToolResult(self.name, False, "", str(exc), 1,
                              time.perf_counter() - started, error=str(exc))
        return ToolResult(self.name, True, str(payload), "", 0,
                          time.perf_counter() - started)


def register_mcp_tools(manager, registry) -> list[str]:
    names: list[str] = []
    for spec in manager.tool_specs():
        names.append(registry.register(
            MCPTool(manager, spec.name, spec.description, spec.parameters)
        ))
    return names
