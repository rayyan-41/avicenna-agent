"""A minimal MCP server, used to prove the MCP path actually works.

Deliberately dependency-free beyond the `mcp` SDK itself and deliberately
boring: two tools, no side effects, no network. Its job is to be a real server
speaking the real protocol over real stdio, so the tests exercise the whole
path — transport, schema export, registration, access gating and invocation —
rather than a mock of it.

One of the tools is called `read_note` on purpose. That name collides with a
builtin, which is how the registry's precedence and aliasing get tested against
something other than a fixture.

Written against the mcp 2.x `MCPServer` API. `avicenna/mcp/mcp_client.py` reads
tool schemas across both 1.x and 2.x, so if this fixture ever has to move back
to the 1.x `Server` decorators, the client side needs no change.
"""

from __future__ import annotations

from mcp.server import MCPServer

server: MCPServer = MCPServer("avicenna-test-echo")


@server.tool()
def echo(text: str) -> str:
    """Echo the supplied text back, uppercased."""
    return text.upper()


@server.tool()
def read_note(path: str) -> str:
    """Collides with the builtin read_note, on purpose."""
    return f"mcp read_note: {path}"


if __name__ == "__main__":
    server.run("stdio")
