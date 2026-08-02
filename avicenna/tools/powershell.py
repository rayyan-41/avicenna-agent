"""PowerShell executor with -File argument normalisation.

Powershell's -File parser interprets bare token "A,B,C" as an array.
When binding to a [string] parameter, the array is coerced with $OFS
(a space). Wrapping values in literal double quotes forces single-string
parsing. Lists are joined with commas first.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from avicenna.tools.base import Tool, ToolAccess, ToolResult, ToolSource
from avicenna.tools.contracts import CONTRACTS, ToolContract

_NEEDS_QUOTING = (",", " ", ";", "(", ")", "{", "}", "'", "`", "$", "@")


def normalise_ps_value(value: Any) -> str:
    """Render a Python value as one PowerShell -File argument token.

    Lists are joined with commas first, since every vault script that
    takes a list documents a comma-separated string.
    """
    if isinstance(value, bool):
        return ""  # switch parameters are emitted as the flag alone
    if isinstance(value, (list, tuple)):
        value = ",".join(str(v) for v in value)
    text = str(value)
    if any(ch in text for ch in _NEEDS_QUOTING) or text == "":
        return '"' + text.replace('"', '`"') + '"'
    return text


def build_argv(script: Path, params: Mapping[str, Any]) -> list[str]:
    argv = ["powershell", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", str(script)]
    for key, value in params.items():
        if value is None or value is False:
            continue
        argv.append(f"-{key}")
        if value is not True:
            argv.append(normalise_ps_value(value))
    return argv


class PowerShellTool(Tool):
    source = ToolSource.VAULT_PS1

    def __init__(self, name: str, script: Path, vault_root: Path, description: str,
                 parameters: Mapping[str, object], access: ToolAccess,
                 contract: ToolContract | None = None, timeout_s: float = 120.0) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.access = access
        self._script = script
        self._cwd = vault_root
        self._contract = contract if contract is not None else CONTRACTS.get(name)
        self._timeout = timeout_s

    async def invoke(self, **kwargs: Any) -> ToolResult:
        argv = build_argv(self._script, kwargs)
        started = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(self._cwd),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(self.name, False, "", "", -1,
                              time.perf_counter() - started,
                              error=f"timeout after {self._timeout}s")
        stdout, stderr = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
        code = proc.returncode or 0
        parsed = self._contract.parse(self.name, stdout, stderr, code) if self._contract else None
        ok = parsed.ok if parsed is not None else code == 0
        return ToolResult(self.name, ok, stdout, stderr, code,
                          time.perf_counter() - started, parsed=parsed)
