"""Built-in read-only tools that work before any vault has .ps1 tools.

These are pure Python, vault-agnostic, and refuse paths that escape
the vault root.
"""

from __future__ import annotations

import time
from pathlib import Path
from collections.abc import Mapping

from avicenna.tools.base import Tool, ToolAccess, ToolResult, ToolSource


def _safe_path(vault_root: Path, path: str) -> Path:
    resolved = (vault_root / path).resolve()
    if not str(resolved).startswith(str(vault_root.resolve())):
        raise ValueError(f"path {path!r} escapes vault root")
    return resolved


class ReadNoteTool(Tool):
    name = "read_note"
    description = "Read the full contents of a note in the vault"
    parameters: Mapping[str, object] = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path relative to vault root"}},
        "required": ["path"],
    }
    source = ToolSource.BUILTIN
    access = ToolAccess.MODEL_CALLABLE

    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root

    async def invoke(self, path: str) -> ToolResult:  # type: ignore[override]
        started = time.perf_counter()
        try:
            p = _safe_path(self._vault_root, path)
            content = p.read_text(encoding="utf-8", errors="replace")
            return ToolResult(self.name, True, content, "", 0, time.perf_counter() - started)
        except Exception as exc:
            return ToolResult(self.name, False, "", str(exc), 1,
                              time.perf_counter() - started, error=str(exc))


class ListNotesTool(Tool):
    name = "list_notes"
    description = "List markdown notes in a vault folder"
    parameters: Mapping[str, object] = {
        "type": "object",
        "properties": {
            "folder": {"type": "string", "description": "Folder relative to vault root"},
            "limit": {"type": "integer", "default": 50},
        },
    }
    source = ToolSource.BUILTIN
    access = ToolAccess.MODEL_CALLABLE

    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root

    async def invoke(self, folder: str = "", limit: int = 50) -> ToolResult:  # type: ignore[override]
        started = time.perf_counter()
        try:
            target = self._vault_root if not folder else _safe_path(self._vault_root, folder)
            files = sorted(p.name for p in target.glob("*.md") if p.is_file())[:limit]
            out = "\n".join(files) if files else "(no markdown files found)"
            return ToolResult(self.name, True, out, "", 0, time.perf_counter() - started)
        except Exception as exc:
            return ToolResult(self.name, False, "", str(exc), 1,
                              time.perf_counter() - started, error=str(exc))


class SearchVaultTool(Tool):
    name = "search_vault"
    description = "Search note filenames and a basic substring match across vault"
    parameters: Mapping[str, object] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search term"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["query"],
    }
    source = ToolSource.BUILTIN
    access = ToolAccess.MODEL_CALLABLE

    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root

    async def invoke(self, query: str, limit: int = 20) -> ToolResult:  # type: ignore[override]
        started = time.perf_counter()
        try:
            results: list[str] = []
            for md in sorted(self._vault_root.rglob("*.md")):
                if md.is_file():
                    rel = str(md.relative_to(self._vault_root))
                    if query.lower() in rel.lower():
                        results.append(rel)
                if len(results) >= limit:
                    break
            out = "\n".join(results) if results else "(no matches)"
            return ToolResult(self.name, True, out, "", 0, time.perf_counter() - started)
        except Exception as exc:
            return ToolResult(self.name, False, "", str(exc), 1,
                              time.perf_counter() - started, error=str(exc))


def register_builtin_tools(vault_root: Path, registry) -> None:
    from avicenna.tools.registry import ToolRegistry
    reg: ToolRegistry = registry
    reg.register(ReadNoteTool(vault_root))
    reg.register(ListNotesTool(vault_root))
    reg.register(SearchVaultTool(vault_root))
