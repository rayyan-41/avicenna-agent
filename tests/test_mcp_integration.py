"""MCP end-to-end: a real server, over real stdio, into the real registry.

MCP was fully built and completely unwired. `register_mcp_tools` had no callers
anywhere in the repo, so no MCP tool ever entered the ToolRegistry, and the
`mcp:` key in agent frontmatter — parsed and reported over the wire — was
consulted by nothing. The transport worked; nothing downstream of it did.

These tests exercise the whole path against `tests/fixtures/echo_mcp_server.py`:
connect, export schemas, register, apply precedence, gate per agent, invoke.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from avicenna.mcp.mcp_config_schema import MCPServerConfig
from avicenna.pipeline.delegate import tools_for_agent
from avicenna.tools.base import ToolAccess, ToolSource
from avicenna.tools.builtin import register_builtin_tools
from avicenna.tools.mcp_tools import register_mcp_tools
from avicenna.tools.registry import ToolRegistry
from avicenna.vault.models import AgentDef

FIXTURE = Path(__file__).parent / "fixtures" / "echo_mcp_server.py"

pytestmark = pytest.mark.skipif(not FIXTURE.is_file(), reason="MCP fixture server missing")


@asynccontextmanager
async def echo_server() -> AsyncIterator[Any]:
    """A live MCPClientManager connected to the fixture server.

    A context manager rather than an async pytest fixture, deliberately: the
    SDK's stdio transport is built on anyio cancel scopes, which must be entered
    and exited in the *same* task. A yield-fixture puts setup and teardown in
    different tasks, and anyio rejects that outright.
    """
    from avicenna.mcp.mcp_client import MCPClientManager

    manager = MCPClientManager()
    config = MCPServerConfig(
        name="echo",
        type="python",
        enabled=True,
        description="test fixture",
        script=str(FIXTURE.resolve()),
    )
    if not await manager.connect_server(config):
        pytest.skip("could not start the fixture MCP server in this environment")
    try:
        yield manager
    finally:
        await manager.cleanup()


def _agent(name: str, mcp: list[str]) -> AgentDef:
    return AgentDef(
        name=name,
        description=f"{name} agent",
        type="content",
        domain="reason",
        invocation=f"/agent {name}",
        system_prompt="You write.",
        path=Path("memory://test"),
        mcp=mcp,
    )


async def test_server_connects_and_exports_schemas() -> None:
    async with echo_server() as manager:
        specs = {spec.name: spec for spec in manager.tool_specs()}
        assert "echo" in specs, sorted(specs)
        echo = specs["echo"]
        assert "Echo" in echo.description
        # The schema has to survive the SDK's own shape, across mcp 1.x and 2.x.
        assert echo.parameters["type"] == "object"
        assert "text" in echo.parameters["properties"]


async def test_tools_register_and_invoke() -> None:
    async with echo_server() as manager:
        registry = ToolRegistry()
        names = register_mcp_tools(manager, registry)
        assert "echo" in names, names

        tool = registry.get("echo")
        assert tool.source is ToolSource.MCP
        assert tool.access is ToolAccess.MODEL_CALLABLE

        result = await tool.invoke(text="revelation")
        assert result.ok, result.error
        assert "REVELATION" in result.stdout


async def test_builtin_wins_a_collision_and_the_loser_stays_reachable(tmp_path: Path) -> None:
    """Precedence is BUILTIN > VAULT_PS1 > MCP, and the loser keeps an alias.

    The alias used to be unusable: it was stored under a `{source}__{name}` key
    but kept its original `.name`, so `spec_for_model` advertised two tools with
    an identical name — one unreachable, and a duplicate that strict providers
    reject outright.
    """
    async with echo_server() as manager:
        registry = ToolRegistry()
        register_builtin_tools(tmp_path, registry)
        register_mcp_tools(manager, registry)

        assert registry.get("read_note").source is ToolSource.BUILTIN
        aliased = registry.get("mcp__read_note")
        assert aliased.source is ToolSource.MCP

        names = [spec.name for spec in registry.spec_for_model()]
        assert len(names) == len(set(names)), f"duplicate tool names offered: {names}"
        assert "mcp__read_note" in names

        # The alias must invoke the MCP tool, not the builtin that beat it.
        result = await aliased.invoke(path="Some/Note.md")
        assert result.ok and "mcp read_note" in result.stdout


async def test_mcp_is_opt_in_per_agent(tmp_path: Path) -> None:
    """The `mcp:` frontmatter key gates access; it used to gate nothing.

    MCP reaches outside the vault, so an agent that has not declared a server
    must not be handed its tools — otherwise "declared rather than arbitrary"
    is enforced nowhere.
    """
    async with echo_server() as manager:
        registry = ToolRegistry()
        register_builtin_tools(tmp_path, registry)
        register_mcp_tools(manager, registry)
        vault = SimpleNamespace(tools=registry)

        opted_in = {s.name for s in tools_for_agent(vault, _agent("haytham", ["echo"]))}
        opted_out = {s.name for s in tools_for_agent(vault, _agent("tolstoy", []))}

        assert "echo" in opted_in
        assert "echo" not in opted_out, "an agent declaring no servers was given MCP tools"
        # Builtins stay open to everyone either way.
        assert {"read_note", "list_notes", "search_vault"} <= opted_out


async def test_a_bad_call_is_reported_not_raised() -> None:
    """A server-side failure must come back as a result, not an exception.

    A tool that raises through `invoke` would abort the section that called it;
    the contract is that the model sees the error and can correct itself.
    """
    async with echo_server() as manager:
        registry = ToolRegistry()
        register_mcp_tools(manager, registry)
        result = await registry.get("echo").invoke(wrong_argument="x")
        combined = f"{result.stdout} {result.stderr} {result.error or ''}".lower()
        assert "error" in combined or "valid" in combined, combined


async def test_vault_attach_mcp_is_a_no_op_without_servers(tmp_path: Path) -> None:
    """A vault with no configured servers must not pay for MCP at all."""
    from avicenna.vault.init_scaffold import init_vault
    from avicenna.vault.vault import Vault

    root = init_vault(tmp_path / "vault")
    vault = Vault.load(root)
    before = {spec.name for spec in vault.tools.spec_for_model()}

    import avicenna.config as config_module

    class _Empty:
        servers: list[MCPServerConfig] = []

    original = config_module.Config.load_mcp_config
    config_module.Config.load_mcp_config = classmethod(lambda cls: _Empty())  # type: ignore[assignment]
    try:
        added = await vault.attach_mcp()
    finally:
        config_module.Config.load_mcp_config = original  # type: ignore[assignment]

    assert added == []
    assert {spec.name for spec in vault.tools.spec_for_model()} == before
