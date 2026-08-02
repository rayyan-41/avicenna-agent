# MCP Guide for Avicenna

> Avicenna ships with **zero** MCP servers configured. That is deliberate.
> This guide explains what MCP gives you and how to add servers yourself.

## What MCP Gives You in Avicenna

The Model Context Protocol (MCP) lets you connect external tool servers
to Avicenna. Any agent can call those tools during a chat or a run,
alongside the vault's own PowerShell tools and the built-ins.

**Zero servers is a working state**, not an error. The MCP line in the
welcome sequence will read "0 of 0 servers, 0 tools" — that means MCP is
ready to expand when you are.

## Where the Config Lives

On first run, Avicenna creates `~/.avicenna/mcp_config.json`. You can
print its path with:

```bash
avicenna mcp path
```

## The Three Transports

Each transport is declared by the `type` field.

### 1. Node.js (`type: "node"`)

An npm package run via `npx -y`. Requires Node.js 16+ on your PATH.

```json
{
  "name": "filesystem",
  "type": "node",
  "package": "@modelcontextprotocol/server-filesystem",
  "args": ["C:\\Users\\You\\Documents"],
  "enabled": true,
  "description": "Read/write files under the given directories"
}
```

### 2. Python (`type: "python"`)

A local Python script. Uses the same Python interpreter as Avicenna.

```json
{
  "name": "my-python-server",
  "type": "python",
  "script": "servers/my_server.py",
  "enabled": true,
  "description": "A local MCP server you wrote"
}
```

### 3. Executable (`type: "executable"`)

Any command runnable on your system.

```json
{
  "name": "some-uvx-server",
  "type": "executable",
  "command": "uvx",
  "args": ["some-mcp-package"],
  "env": {"SOME_API_KEY": ""},
  "enabled": false,
  "description": "Anything runnable as a command"
}
```

## Complete Example

```json
{
  "version": "2.0",
  "mcp_servers": [
    {
      "name": "filesystem",
      "type": "node",
      "package": "@modelcontextprotocol/server-filesystem",
      "args": ["C:\\Users\\You\\Documents"],
      "enabled": true,
      "description": "Read/write files under the given directories"
    },
    {
      "name": "my-python-server",
      "type": "python",
      "script": "servers/my_server.py",
      "enabled": true,
      "description": "A local MCP server you wrote"
    },
    {
      "name": "some-uvx-server",
      "type": "executable",
      "command": "uvx",
      "args": ["some-mcp-package"],
      "env": {"SOME_API_KEY": ""},
      "enabled": false,
      "description": "Anything runnable as a command"
    }
  ]
}
```

## Field Reference

| Field | Required | Description |
|---|---|---|
| `name` | Always | Unique name for this server |
| `type` | Always | One of `node`, `python`, `executable` |
| `package` | node only | npm package name |
| `script` | python only | Path to Python script |
| `command` | executable only | Command to run |
| `args` | Optional | Command-line arguments |
| `env` | Optional | Environment variables (secrets go here) |
| `enabled` | Optional (default true) | Whether to start this server |
| `description` | Optional | Human-readable description |

## Prerequisites

- **node** transport: Node.js 16+ on PATH. Avicenna falls back to common
  Windows `npx.cmd` paths, but a real install is better.
- **executable** transport: whatever the command needs.

## Verifying

```bash
# List configured servers
avicenna mcp list

# Connect to one server in isolation (prints any error)
avicenna mcp test <name>

# Show every discovered tool
avicenna mcp tools
```

`avicenna mcp test` starts each server on its own, initializes a session,
counts the tools it contributes, and shuts it down again. With no argument it
tests every **enabled** server; pass a name to test just one. It exits `1` if
any tested server failed, `0` otherwise — so it works in a script. Use
`--timeout <seconds>` (default 30) for a slow first `npx` install.

A server that connects:

```text
$ avicenna mcp test filesystem
MCP server test
┌────────────┬──────┬───────────┬───────┐
│ Server     │ Type │ Status    │ Tools │
├────────────┼──────┼───────────┼───────┤
│ filesystem │ node │ connected │    12 │
└────────────┴──────┴───────────┴───────┘

1 of 1 servers connected, 12 tools total.
```

A server that does not — the real error is printed under the table:

```text
$ avicenna mcp test some-uvx-server
MCP server test
┌─────────────────┬────────────┬────────┬───────┐
│ Server          │ Type       │ Status │ Tools │
├─────────────────┼────────────┼────────┼───────┤
│ some-uvx-server │ executable │ failed │     - │
└─────────────────┴────────────┴────────┴───────┘

some-uvx-server failed:
  Executable not found: uvx

0 of 1 servers connected, 0 tools total.
```

With no servers configured, `mcp test` reports that and exits `0` — zero
servers is a working state, so it points you at the config instead of failing.

## Security

**An MCP server is arbitrary code with tool access.** By default MCP tools
register as `model_callable`, which means the model can invoke them.
Only add servers you trust. Secrets go in the `env` field, and `env`
values are redacted from all logs.

## Troubleshooting

- **Server not connecting:** Use `avicenna mcp test <name>` to see the
  raw error.
- **`npx` not found:** Install Node.js. If it's installed but not on PATH,
  check the common fallback paths Avicenna tries (see `mcp_client.py`).
- **Tool name collision:** If a vault tool and an MCP tool have the same
  name, the vault tool wins precedence. The MCP tool gets an alias like
  `mcp__<tool>`.
- **A failing server is non-blocking.** A server that fails to connect
  degrades gracefully rather than preventing startup.
