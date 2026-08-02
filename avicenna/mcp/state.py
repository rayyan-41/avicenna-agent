"""MCP server state types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ServerStatus:
    name: str
    type: str
    connected: bool
    tools_count: int = 0
    error: str | None = None


@dataclass
class MCPInitResult:
    servers: list[ServerStatus] = field(default_factory=list)
    total_tools: int = 0
    enabled_count: int = 0
    connected_count: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def all_connected(self) -> bool:
        return self.connected_count == self.enabled_count
