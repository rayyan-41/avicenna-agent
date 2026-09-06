# MAP: avicenna/cli

> Typer-based command-line interface. With no subcommand it launches the TypeScript frontend (`tui/dist/main.js` via Node); pass `--no-tui` for headless mode. All note generation, vault scaffolding, routing diagnostics, and MCP testing are accessible as CLI commands. The `mcp test` subcommand lives in its own module because it pulls in the full MCP client machinery and keeps `app.py` from dragging that dependency chain into every invocation.

**Depends on:** `avicenna.vault`, `avicenna.pipeline`, `avicenna.providers`, `avicenna.auth`, `avicenna.config`, `avicenna.bridge`, `avicenna.mcp`, `typer`, `dotenv` · **Depended on by:** `pyproject.toml` console_scripts entry point
**Reads:** `.env` via dotenv, vault on disk, `~/.avicenna/` config, stdin (headless) · **Writes:** stdout, vault files (via `init` and `note` commands)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `__init__.py` | 2 | Package marker; `from __future__ import annotations` only. |
| `app.py` | 335 | Typer application, all top-level commands, subcommand group registration, TUI/headless launch helpers. |
| `mcp_cmd.py` | 277 | `avicenna mcp test` command: connects to each configured MCP server in isolation, captures the real error text from the MCP client logger, and renders a rich or plain table of results. |
<!-- map:files:end -->

## Commands

| Command | Function | Purpose |
| --- | --- | --- |
| `avicenna` (no args) | `main_callback` | Launches the TypeScript frontend in `tui/dist/main.js`. Falls back to headless with `--no-tui`. |
| `avicenna init [VAULT]` | `init_cmd` | Scaffolds a minimal working vault at the given path (default: `./avicenna-vault`). |
| `avicenna route <TOPIC>` | `route_cmd` | Deterministic keyword scoring — shows which agent a topic routes to and the full score table. |
| `avicenna note <TOPIC>` | `note_cmd` | Generates a note end-to-end. Supports `--dry-run`, `--resume`, `--concurrency`. Uses location hint from vault context. |
| `avicenna bridge` | `bridge_cmd` (hidden) | Runs the stdio bridge directly for debugging. Not shown in `--help`. |
| `avicenna run-prompt <FILE>` | `run_prompt_cmd` | Executes a prompt file via `one_shot()` — exists for external integration. |
| `avicenna config reset` | `config_reset` | Deletes `~/.avicenna/user_config.json` and `~/.avicenna/mcp_config.json`, restoring first-run onboarding. |
| `avicenna mcp list` | `mcp_list` | Lists every configured MCP server with transport type, enabled state, and description. |
| `avicenna mcp path` | `mcp_path` | Prints the path to `mcp_config.json`. |
| `avicenna mcp tools` | `mcp_tools` | Placeholder — MCP tools are discovered at runtime, not statically. |
| `avicenna mcp test [NAME]` | `mcp_test` (in `mcp_cmd.py`) | Connects to MCP servers in isolation and reports the real failure reason. Accepts optional server name to test one; omits to test all enabled. `--timeout` controls per-server wait. |

## Environment overrides

| Variable | Effect |
| --- | --- |
| `AVICENNA_NODE` | Path to the Node.js binary. Bypasses PATH lookup when launching the TUI. Used by `_find_node()` in `app.py:243`. |
| `AVICENNA_FORCE_ONBOARD` | Set to `"1"` to force the frontend to re-run onboarding. Injected into the TUI subprocess environment by `_tui_launch()` when `--reconfigure` is passed. |

## Invariants

- `app.py` uses `subprocess.run` to launch the TUI process, which is acceptable here (this is the CLI layer, not the bridge). Nothing under `bridge/` has this liberty.
- The `mcp test` command captures log records from `avicenna.mcp.mcp_client` via a temporary `logging.Handler` to extract real error text — `MCPClientManager.connect_server()` swallows exceptions and returns `False`.
- `_tui_launch` forwards `--vault`, `--ascii`, and `AVICENNA_FORCE_ONBOARD` to the frontend subprocess. A flag documented in the README but not forwarded is a bug that has happened before (`--ascii`).
- `dotenv` is loaded at import time (`app.py:18`), so `.env` values are available to every command.

## Entry points

- To add a CLI command, add a `@app.command` function in `app.py:57` or register it on a subcommand group (`config_app`, `mcp_app`).
- To change TUI launch behaviour, start at `app.py:253` (`_tui_launch`).
- To change MCP test logic, start at `mcp_cmd.py:116` (`test_server`).

## See also

- `../bridge/MAP.md` — the stdio bridge the TUI spawns behind the scenes
- `../mcp/MAP.md` — the MCP client manager `mcp test` exercises
- `../vault/init_scaffold.py` — what `avicenna init` actually scaffolds
