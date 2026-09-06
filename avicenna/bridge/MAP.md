# MAP: avicenna/bridge

> Stdio NDJSON bridge between the Python agent core and the TypeScript frontend. The frontend spawns `python -m avicenna.bridge` as a child process and communicates over stdin/stdout using newline-delimited JSON frames. This package owns the wire format, the request dispatcher, and the invariant that stdout belongs exclusively to the protocol — any stray `print` reachable from here desyncs the frontend parser, so `sys.stdout` is redirected to stderr for the process lifetime and all frames write to a private handle.

**Depends on:** `avicenna.bus`, `avicenna.events`, `avicenna.vault`, `avicenna.pipeline`, `avicenna.auth`, `avicenna.chat`, `avicenna.config` · **Depended on by:** `tui/` (spawns this process), `avicenna.cli` (hidden `bridge` command)
**Reads:** stdin (NDJSON frames from frontend), vault on disk (lazy-loaded) · **Writes:** stdout (NDJSON frames to frontend)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `__init__.py` | 8 | Re-exports `PROTOCOL_VERSION`, `Bridge`, `BridgeError`, `main`. |
| `__main__.py` | 10 | `python -m avicenna.bridge` entry point; delegates to `server.main()`. |
| `protocol.py` | 73 | Wire format definitions. Exports `encode()` for JSON serialisation, `event_frame()` to turn `avicenna.events` dataclasses into wire frames, and `ok_frame()`/`err_frame()` for request responses. The envelope shapes are: request `{"type":"req","id":"...","method":"...","params":{}}`, response `{"type":"res","id":"...","ok":true,"result":{}}` or `{"type":"res","id":"...","ok":false,"error":{"kind":"...","message":"..."}}`, event `{"type":"event","event":"...","runId":"...","seq":0,"ts":0.0,"data":{}}`. A ready frame `{"type":"ready","protocol":N}` is sent on startup. This file is mirrored by `tui/src/protocol.ts`; `scripts/check_protocol_parity.py` gates the pair in CI. |
| `server.py` | 510 | The bridge itself. `Bridge` class owns the async request loop, the event pump, and lazy resolution of vault/provider/chat. `main()` parses `--vault` and runs the bridge. Dispatches methods via `_m_<name>` convention — the dot in a method name becomes an underscore lookup. |
<!-- map:files:end -->

## Bridge methods

The `_dispatch` table is the API surface the frontend calls. Each method name maps to `_m_<name>` with dots replaced by underscores:

| Method | Handler | What it does |
| --- | --- | --- |
| `hello` | `_m_hello` | Returns protocol version, Python version, cwd, pid, auth status. First call after `ready`. |
| `vault.info` | `_m_vault_info` | Vault detection: found state, badge, summary, agent/skill/domain counts, location hint. |
| `vault.init` | `_m_vault_init` | Scaffolds a new vault; invalidates cached vault, provider, and chat controller. |
| `agents.list` | `_m_agents_list` | Every agent sorted by (type, name) with name, description, type, domain, stage, mcp. |
| `tools.list` | `_m_tools_list` | Every registered tool with name, description, source, access level. |
| `mcp.list` | `_m_mcp_list` | Every configured MCP server from `~/.avicenna/mcp_config.json` with name, type, enabled, description. |
| `auth.status` | `_m_auth_status` | Current authentication state (key presence, provider). |
| `auth.validate` | `_m_auth_validate` | Validates a supplied API key against the default provider. Async. |
| `auth.persist` | `_m_auth_persist` | Saves an API key; invalidates cached provider and chat controller. |
| `auth.local_stub` | `_m_auth_local_stub` | Returns the local-model stub message constant. |
| `route.explain` | `_m_route_explain` | Deterministic keyword routing scores for a topic; shows chosen agent or ambiguity. |
| `run.note` | `_m_run_note` | Kicks off `execute_run` as a background task; returns runId immediately. Supports resume. Progress arrives as events, not in the response. |
| `run.cancel` | `_m_run_cancel` | Cancels a running task by runId, or all if none specified. |
| `chat.select` | `_m_chat_select` | Selects an agent for the `/agent` diagnostic chat. |
| `chat.send` | `_m_chat_send` | Sends text to the selected agent's chat; returns completion text and token counts. |
| `chat.clear` | `_m_chat_clear` | Clears chat history for a specific agent or the active one. |
| `shutdown` | `_m_shutdown` | Sets the stopping event; the request loop exits on next iteration. |

## Invariants

- **stdout is the wire.** `Bridge.run()` redirects `sys.stdout` to `sys.stderr` before reading a single frame. Every diagnostic, rich console output, and typer echo that leaks through goes to stderr. Writing to the real stdout handle happens only through `Bridge._send()`, guarded by `_write_lock`.
- **Nothing under bridge/ may block.** CI rejects `subprocess.run`, `time.sleep`, and `requests.` in this package. All I/O is async; stdin reads use `asyncio.to_thread` wrapping the blocking `readline`.
- **A request never blocks the event stream.** Long work (`run.note`, `chat.send`) is dispatched via `_spawn()` and answered immediately with an id. Progress arrives as `EventBus` events pumped by `_pump_events()`.
- **The event pump must not die.** If `_pump_events` terminates, the `EventBus` queue fills to `maxsize=1000` and every `bus.emit` in the pipeline awaits forever, deadlocking the run mid-note with no error.
- **Events are serialised structurally.** `protocol.event_frame` reads class name and field names from the dataclass — adding an event to `events.py` requires no change here, and `scripts/check_protocol_parity.py` enforces frontend parity.

## Entry points

- To change the wire format or envelope shape, start at `protocol.py:24`.
- To add a bridge method, add `_m_<method_name>` to `server.py:162` and update this map's method table.
- To change how stdin is read or the process lifecycle, start at `server.py:445` (`Bridge.run`).
- To change event forwarding, start at `server.py:90` (`_pump_events`).

## See also

- `../events.py` — the dataclasses that become wire events
- `../bus.py` — the `EventBus` the bridge subscribes to
- `tui/src/protocol.ts` — the frontend mirror of `protocol.py`
- `scripts/check_protocol_parity.py` — CI gate keeping the two in sync
