"""Neutral Tool abstraction.

A tool is a name, description, JSON Schema params, provenance tag,
access class, and async invoke. Vault, MCP, and built-in tools share
this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from collections.abc import Mapping


class ToolSource(str, Enum):
    VAULT_PS1 = "vault_ps1"
    MCP = "mcp"
    BUILTIN = "builtin"


class ToolAccess(str, Enum):
    MODEL_CALLABLE = "model_callable"
    PIPELINE_ONLY = "pipeline_only"


@dataclass(slots=True)
class ToolResult:
    tool: str
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_s: float
    parsed: ParsedContract | None = None
    error: str | None = None

    @property
    def summary(self) -> str:
        """Short single-line text safe to feed back to the model."""
        if self.parsed is not None:
            return self.parsed.render()
        return (self.stdout or self.stderr or "").strip()[:2000]


class Tool(ABC):
    name: str
    description: str
    parameters: Mapping[str, object]          # JSON Schema object
    source: ToolSource
    access: ToolAccess = ToolAccess.MODEL_CALLABLE

    @abstractmethod
    async def invoke(self, **kwargs: object) -> ToolResult: ...


from avicenna.tools.contracts import ParsedContract  # noqa: E402

__all__ = [
    "ToolSource", "ToolAccess", "ToolResult", "Tool", "ParsedContract",
]
