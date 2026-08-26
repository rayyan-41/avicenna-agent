"""Built-in read-only tools that work before any vault has .ps1 tools.

These are pure Python, vault-agnostic, and refuse paths that escape
the vault root.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from collections.abc import Mapping

from avicenna.tools.base import Tool, ToolAccess, ToolResult, ToolSource
from avicenna.tools.registry import ToolRegistry


def _safe_path(vault_root: Path, path: str) -> Path:
    """Resolve `path` inside the vault, or refuse.

    Containment is a path-component test, not a string-prefix test. With
    `startswith`, a root of `D:\\vault` happily accepted
    `../vault-private/secrets.md` — resolving to `D:\\vault-private\\...`,
    which shares the prefix but is a different directory. These tools are
    model-callable, so that was a readable-anything primitive one sibling
    directory away.
    """
    root = vault_root.resolve()
    resolved = (root / path).resolve()
    if resolved != root and root not in resolved.parents:
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
            content = await asyncio.to_thread(
                p.read_text, encoding="utf-8", errors="replace")
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
            files = await asyncio.to_thread(
                lambda: sorted(p.name for p in target.glob("*.md") if p.is_file())[:limit])
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
            # Walked lazily and in a worker thread. `sorted(rglob(...))`
            # materialised every note in the vault before the limit could
            # apply, on the event loop, which froze the interface on a large
            # vault for as long as the walk took.
            def scan() -> list[str]:
                found: list[str] = []
                needle = query.lower()
                for md in self._vault_root.rglob("*.md"):
                    if not md.is_file():
                        continue
                    rel = str(md.relative_to(self._vault_root))
                    if needle in rel.lower():
                        found.append(rel)
                        if len(found) >= limit:
                            break
                return sorted(found)

            results = await asyncio.to_thread(scan)
            out = "\n".join(results) if results else "(no matches)"
            return ToolResult(self.name, True, out, "", 0, time.perf_counter() - started)
        except Exception as exc:
            return ToolResult(self.name, False, "", str(exc), 1,
                              time.perf_counter() - started, error=str(exc))


def register_builtin_tools(vault_root: Path, registry: ToolRegistry) -> None:
    reg = registry
    reg.register(ReadNoteTool(vault_root))
    reg.register(ListNotesTool(vault_root))
    reg.register(SearchVaultTool(vault_root))
