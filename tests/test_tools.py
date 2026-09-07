"""Tool layer tests."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from avicenna.tools.base import ToolAccess, ToolSource
from avicenna.tools.contracts import CONTRACTS, ToolContract
from avicenna.tools.powershell import normalise_ps_value, build_argv
from avicenna.tools.registry import ToolRegistry

needs_powershell = pytest.mark.skipif(
    shutil.which("powershell") is None,
    reason="PowerShell not available",
)


class FakeTool:
    def __init__(self, name, access=ToolAccess.MODEL_CALLABLE, source=ToolSource.BUILTIN):
        self.name = name
        self.description = "desc"
        self.parameters = {"type": "object"}
        self.access = access
        self.source = source


def test_normalise_ps_list_joins_with_commas():
    assert normalise_ps_value(["A", "B", "C"]) == "A,B,C"


def test_normalise_ps_tuple_joins_with_commas():
    assert normalise_ps_value(("X", "Y")) == "X,Y"


def test_normalise_ps_bool_returns_empty():
    assert normalise_ps_value(True) == ""
    assert normalise_ps_value(False) == ""


def test_normalise_ps_passthrough():
    """Values pass through unquoted — subprocess handles quoting."""
    assert normalise_ps_value("simple") == "simple"
    assert normalise_ps_value("A,B,C") == "A,B,C"
    assert normalise_ps_value("hello world") == "hello world"
    assert normalise_ps_value("") == ""


def test_build_argv():
    argv = build_argv(Path("test.ps1"), {"Slug": "foo", "Headings": "A,B,C", "Force": True})
    assert argv[0] == "powershell"
    assert "-File" in argv
    assert any("test.ps1" in a for a in argv)


def test_contract_success():
    c = ToolContract("test", success=re.compile(r"PASS"), failure=re.compile(r"FAIL"))
    parsed = c.parse("test", "PASS", "", 0)
    assert parsed.ok
    assert parsed.token == "PASS"


def test_contract_failure():
    c = ToolContract("test", success=re.compile(r"PASS"), failure=re.compile(r"FAIL"))
    parsed = c.parse("test", "FAIL", "", 1)
    assert not parsed.ok
    assert parsed.token == "FAIL"


def test_contract_unmatched():
    c = ToolContract("test", success=re.compile(r"PASS"))
    parsed = c.parse("test", "something else", "", 0)
    assert not parsed.ok
    assert parsed.token == "CONTRACT_UNMATCHED"


def test_write_manifest_contract():
    c = CONTRACTS["write_manifest"]
    parsed = c.parse("write_manifest",
                     "MANIFEST_WRITTEN: /tmp/x_manifest.json (5 chunks expected)", "", 0)
    assert parsed.ok
    assert parsed.captures.get("chunks") == "5"


def test_spec_for_model_excludes_pipeline():
    reg = ToolRegistry()
    reg.register(FakeTool("safe", ToolAccess.MODEL_CALLABLE))
    reg.register(FakeTool("hidden", ToolAccess.PIPELINE_ONLY))
    specs = reg.spec_for_model()
    names = [s.name for s in specs]
    assert "safe" in names
    assert "hidden" not in names


def test_registry_collision_precedence():
    reg = ToolRegistry()
    reg.register(FakeTool("test", ToolAccess.MODEL_CALLABLE, ToolSource.BUILTIN))
    reg.register(FakeTool("test", ToolAccess.MODEL_CALLABLE, ToolSource.VAULT_PS1))
    # BUILTIN wins precedence; vault_ps1 version gets aliased
    assert reg.get("test").source == ToolSource.BUILTIN
    assert reg.get("vault_ps1__test").source == ToolSource.VAULT_PS1


# -- Round-trip integration tests: verify values survive subprocess ---

_ROUND_TRIP_SCRIPT = """\
param([string]$Value)
Write-Output $Value
"""


@needs_powershell
@pytest.mark.parametrize("value", [
    "A,B,C",
    "hello world",
    "a, b, c",
    "",
    "it's",
    "a;b",
    "x$y",
    'has "quotes" inside',
    "trailing space ",
])
def test_ps_value_roundtrip(tmp_path: Path, value: str) -> None:
    """Value sent through build_argv must arrive verbatim at the script."""
    script = tmp_path / "echo_value.ps1"
    script.write_text(_ROUND_TRIP_SCRIPT, encoding="utf-8")
    argv = build_argv(script, {"Value": value})
    result = subprocess.run(argv, capture_output=True, text=True)
    # rstrip only the line ending — .strip() would destroy trailing-space cases
    received = result.stdout.rstrip("\r\n")
    assert received == value, (
        f"expected {value!r} but got {received!r}\n"
        f"stderr: {result.stderr!r}\n"
        f"argv: {argv}"
    )


@needs_powershell
def test_ps_list_roundtrip(tmp_path: Path) -> None:
    """A list parameter must arrive as comma-joined string."""
    script = tmp_path / "echo_value.ps1"
    script.write_text(_ROUND_TRIP_SCRIPT, encoding="utf-8")
    argv = build_argv(script, {"Value": ["A", "B", "C"]})
    result = subprocess.run(argv, capture_output=True, text=True)
    received = result.stdout.rstrip("\r\n")
    assert received == "A,B,C", (
        f"expected 'A,B,C' but got {received!r}\n"
        f"stderr: {result.stderr!r}\n"
        f"argv: {argv}"
    )
