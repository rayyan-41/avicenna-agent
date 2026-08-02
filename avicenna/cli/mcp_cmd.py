"""``avicenna mcp test`` — connect to MCP servers in isolation and show the real error.

The rest of the ``mcp`` sub-app only reports what the config *claims*. This command
actually starts each server, initializes a session, counts the tools it contributes,
and — when it fails — prints the underlying exception text instead of leaving the
user to discover the failure halfway through a run.

Kept in its own module so it can be attached to the existing Typer sub-app in
``avicenna/cli/app.py`` with a single line::

    from avicenna.cli.mcp_cmd import mcp_test   # top of file, or next to mcp_app
    mcp_app.command("test")(mcp_test)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterator, List, Optional

import typer

if TYPE_CHECKING:  # pragma: no cover - typing only
    from avicenna.mcp.mcp_config_schema import MCPServerConfig

# Seconds to wait for a single server to start, initialize, and list its tools.
DEFAULT_TIMEOUT_SECONDS = 30.0

# Seconds to wait for teardown of a single server before giving up on it.
CLEANUP_TIMEOUT_SECONDS = 10.0

# MCPClientManager.connect_server() swallows its exceptions and returns False,
# logging the real text through this logger. We borrow it to recover the cause.
_CLIENT_LOGGER_NAME = "avicenna.mcp.mcp_client"

# Prefixes MCPClientManager puts in front of the exception text.
_ERROR_PREFIXES = ("✗ Failed to connect to ", "✗ Config error for ")


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class ServerTestResult:
    """Outcome of testing exactly one MCP server."""

    name: str
    type: str
    connected: bool = False
    tool_count: int = 0
    error: str = ""
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Error capture
# ---------------------------------------------------------------------------

class _ErrorCapture(logging.Handler):
    """Collects ERROR records emitted by the MCP client while a test runs."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.messages: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.messages.append(record.getMessage())
        except Exception:  # pragma: no cover - never let logging break the test
            pass


@contextmanager
def _capture_client_errors() -> Iterator[_ErrorCapture]:
    """Temporarily intercept ``avicenna.mcp.mcp_client`` errors.

    Propagation is suppressed for the duration so the report stays clean; the
    captured text is printed by this command instead.
    """
    logger = logging.getLogger(_CLIENT_LOGGER_NAME)
    handler = _ErrorCapture()
    previous_level = logger.level
    previous_propagate = logger.propagate

    logger.addHandler(handler)
    logger.propagate = False
    if previous_level == logging.NOTSET or previous_level > logging.ERROR:
        logger.setLevel(logging.ERROR)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.propagate = previous_propagate
        logger.setLevel(previous_level)


def _clean_error(message: str, server_name: str) -> str:
    """Strip the client's log decoration, leaving the raw exception text."""
    text = message.strip()
    for prefix in _ERROR_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            if text.startswith(server_name):
                text = text[len(server_name):]
            return text.lstrip(": ").strip()
    return text


# ---------------------------------------------------------------------------
# Async workers
# ---------------------------------------------------------------------------

async def test_server(server: "MCPServerConfig", timeout: float = DEFAULT_TIMEOUT_SECONDS) -> ServerTestResult:
    """Start one server on a dedicated manager, then tear it down again."""
    from avicenna.mcp.mcp_client import MCPClientManager

    result = ServerTestResult(name=server.name, type=server.type)
    manager = MCPClientManager()

    with _capture_client_errors() as captured:
        try:
            connected = await asyncio.wait_for(manager.connect_server(server), timeout=timeout)
        except asyncio.TimeoutError:
            connected = False
            result.error = (
                f"Timed out after {timeout:g}s waiting for the server to start and list its tools."
            )
        except Exception as exc:  # connect_server should not raise, but never trust that
            connected = False
            result.error = f"{type(exc).__name__}: {exc}"
        else:
            if connected:
                result.connected = True
                result.tool_count = sum(
                    1 for owner in manager.tool_to_server.values() if owner == server.name
                )

        if not result.connected and not result.error:
            result.error = (
                _clean_error(captured.messages[-1], server.name)
                if captured.messages
                else "Connection failed (no error text was reported by the MCP client)."
            )

    try:
        await asyncio.wait_for(manager.cleanup(), timeout=CLEANUP_TIMEOUT_SECONDS)
    except Exception as exc:
        # Teardown trouble is worth surfacing but never changes pass/fail.
        result.notes.append(f"cleanup: {type(exc).__name__}: {exc}")

    return result


async def test_servers(
    servers: List["MCPServerConfig"], timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> List[ServerTestResult]:
    """Test servers one at a time so a noisy server cannot mask another."""
    return [await test_server(server, timeout=timeout) for server in servers]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render(results: List[ServerTestResult]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:  # pragma: no cover - rich is a hard dependency
        _render_plain(results)
        return

    console = Console()
    table = Table(title="MCP server test", title_justify="left")
    table.add_column("Server", style="bold", no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Tools", justify="right", no_wrap=True)

    for result in results:
        status = "[green]connected[/green]" if result.connected else "[red]failed[/red]"
        table.add_row(result.name, result.type, status, str(result.tool_count) if result.connected else "-")

    console.print(table)

    for result in results:
        if not result.connected:
            console.print(f"\n[red]{result.name}[/red] failed:")
            console.print(f"  {result.error}")
        for note in result.notes:
            console.print(f"  [yellow]{result.name}: {note}[/yellow]")

    ok = sum(1 for r in results if r.connected)
    tools = sum(r.tool_count for r in results)
    console.print(f"\n{ok} of {len(results)} servers connected, {tools} tools total.")


def _render_plain(results: List[ServerTestResult]) -> None:
    width = max((len(r.name) for r in results), default=6)
    for result in results:
        status = "connected" if result.connected else "failed"
        tools = str(result.tool_count) if result.connected else "-"
        typer.echo(f"  {result.name:<{width}}  [{result.type}]  {status:<9}  {tools:>4} tools")

    for result in results:
        if not result.connected:
            typer.echo(f"\n{result.name} failed:")
            typer.echo(f"  {result.error}")
        for note in result.notes:
            typer.echo(f"  {result.name}: {note}")

    ok = sum(1 for r in results if r.connected)
    tools = sum(r.tool_count for r in results)
    typer.echo(f"\n{ok} of {len(results)} servers connected, {tools} tools total.")


def _echo_no_servers(configured: int) -> None:
    """Zero MCP servers is a supported state for this product, not a failure."""
    from avicenna.config import Config

    if configured:
        typer.echo(f"All {configured} configured MCP servers are disabled — nothing to test.")
        typer.echo('Set "enabled": true on a server to include it.')
    else:
        typer.echo("No MCP servers configured — nothing to test. This is a normal state.")
    typer.echo(f"\nConfig file: {Config.MCP_CONFIG_PATH}")
    typer.echo("  avicenna mcp path      print that path again")
    typer.echo("  docs/MCP_GUIDE.md      how to add a server")


# ---------------------------------------------------------------------------
# Typer command
# ---------------------------------------------------------------------------

def mcp_test(
    name: Optional[str] = typer.Argument(
        None, help="Server to test. Omit to test every enabled server."
    ),
    timeout: float = typer.Option(
        DEFAULT_TIMEOUT_SECONDS, "--timeout", help="Seconds to wait for each server to connect."
    ),
) -> None:
    """Connect to MCP servers in isolation and report the real failure reason."""
    from avicenna.config import Config

    cfg = Config.load_mcp_config()

    if name:
        server = cfg.get_server(name)
        if server is None:
            typer.echo(f"No MCP server named '{name}'.", err=True)
            if cfg.servers:
                known = ", ".join(s.name for s in cfg.servers)
                typer.echo(f"Known servers: {known}", err=True)
            else:
                typer.echo(
                    "No servers are configured. See 'avicenna mcp path' and docs/MCP_GUIDE.md.",
                    err=True,
                )
            raise typer.Exit(1)
        if not server.enabled:
            typer.echo(f"Note: '{server.name}' is disabled in the config — testing it anyway.")
        targets = [server]
    else:
        targets = cfg.get_enabled_servers()
        if not targets:
            _echo_no_servers(len(cfg.servers))
            raise typer.Exit(0)

    results = asyncio.run(test_servers(targets, timeout=timeout))
    _render(results)

    if any(not r.connected for r in results):
        raise typer.Exit(1)
