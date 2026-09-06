# MAP: avicenna/mcp

> MCP (Model Context Protocol) client layer. Manages connections to external tool servers so the harness can reach past the vault — reference managers, search, PDF corpora, citation stores — without building any of that into the core. Ships with zero servers configured; a vault opts in through its agents' `mcp:` frontmatter keys and a user-level config file. The config schema and client manager are separate modules because the schema is loaded early (by `Config.load_mcp_config`) while the client pulls in the `mcp` SDK and only starts servers on demand.

**Depends on:** `mcp` (Python SDK), `avicenna.providers.base` (for `ToolSpec`), `avicenna.config` · **Depended on by:** `avicenna.tools.registry` (registers MCP tools), `avicenna.cli.mcp_cmd` (test command), `avicenna.bridge.server` (list command)
**Reads:** `~/.avicenna/mcp_config.json` (user-level server declarations), environment variables (server-specific env passed through) · **Writes:** nothing to disk — connections are transient and teardown on `cleanup()`

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `__init__.py` | 1 | Package marker; `from __future__ import annotations` only. |
| `mcp_client.py` | 314 | `MCPClientManager`: connects to servers, discovers tools, dispatches calls, exports neutral `ToolSpec` objects. |
| `mcp_config_schema.py` | 163 | `MCPServerConfig` and `MCPConfiguration` dataclasses with JSON serialisation, validation, and legacy-format handling. |
<!-- map:files:end -->

## Transports

`MCPClientManager._get_server_command` resolves a server config to a `(command, args)` pair, then the `mcp` SDK's `stdio_client` handles the actual subprocess and framing. Three transport types:

| Type | Constant | What it spawns | Required field |
| --- | --- | --- | --- |
| `python` | `SERVER_TYPE_PYTHON` | `sys.executable <script> [args]` | `script` (path, relative to project root if not absolute) |
| `node` | `SERVER_TYPE_NODE` | `npx -y <package> [args]` | `package` (npm package name) |
| `executable` | `SERVER_TYPE_EXECUTABLE` | `<command> [args]` | `command` (resolved via `shutil.which` or absolute path) |

On Windows, the Node transport checks `PROGRAMFILES`, `APPDATA`, and `~/AppData/Roaming/npm` for `npx.cmd` when `shutil.which("npx")` returns nothing.

## Config schema

The user-level config lives at `~/.avicenna/mcp_config.json` (path from `Config.MCP_CONFIG_PATH`). Shape:

```json
{
  "version": "2.0",
  "mcp_servers": [
    {
      "name": "server-name",
      "type": "python|node|executable",
      "enabled": true,
      "description": "optional",
      "script": "path.py",
      "package": "@scope/package",
      "command": "binary-name",
      "args": ["--flag"],
      "env": {"KEY": "value"}
    }
  ]
}
```

`MCPServerConfig.__post_init__` validates that the type-appropriate field is present: `script` for python, `package` for node, `command` for executable. `MCPConfiguration.from_file` handles legacy configs that omit the `type` field but include `script` (inferred as `python`).

## Invariants

- **Zero servers by default.** A fresh install has no MCP config; this is a supported and expected state, not an error. `MCPConfiguration.default()` returns an empty server list.
- **`tool_specs()` is the vendor-neutral export.** Each `ToolSpec` carries name, description, and JSON Schema parameters. Providers convert at their edge — no MCP types leak past `avicenna/providers/`.
- **Cross-version SDK compatibility.** `_tool_schema()` reads `input_schema` then falls back to `inputSchema` because mcp 1.x and 2.x use different attribute names for the same thing. The previous `getattr(t, "inputSchema", {})` returned `{}` for every tool under 2.x.
- **`connect_server` swallows exceptions and returns `False`.** Real error text goes to the `avicenna.mcp.mcp_client` logger. The `mcp test` CLI command installs a temporary handler to capture it.
- **Cleanup is mandatory.** `AsyncExitStack` owns all subprocess handles and sessions. Callers must `await manager.cleanup()` or use it as a context manager, or child processes leak.
- **Empty env values mean "inherit".** In `MCPServerConfig.env`, an empty string means "use the value from the parent environment", not "set to empty". `connect_server` skips empty values when merging.

## Entry points

- To add a transport type, extend `_get_server_command` in `mcp_client.py:68` and add a constant to `mcp_config_schema.py:17`.
- To change how tools are exported to providers, start at `mcp_client.py:291` (`tool_specs`).
- To change config validation, start at `mcp_config_schema.py:69` (`__post_init__`).

## See also

- `../tools/registry.py` — where MCP tools are registered alongside builtins and vault tools
- `../cli/mcp_cmd.py` — the `mcp test` command that exercises this module in isolation
- `../providers/base.py` — the `ToolSpec` type that `tool_specs()` returns
