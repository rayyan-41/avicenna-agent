"""Agent tools package.

Exposes Tool, ToolRegistry, ToolResult, and related utilities.
"""

from __future__ import annotations

from avicenna.tools.base import Tool, ToolAccess, ToolResult, ToolSource
from avicenna.tools.registry import ToolNameCollision, ToolRegistry
from avicenna.tools.contracts import CONTRACTS, ParsedContract, ToolContract

__all__ = [
    "Tool", "ToolSource", "ToolAccess", "ToolResult",
    "ToolRegistry", "ToolNameCollision",
    "ToolContract", "ParsedContract", "CONTRACTS",
]
