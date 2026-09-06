# MAP: avicenna/

> The Python backend package root. Every module here is cross-cutting: the
> runtime primitives (Session, one_shot), the event taxonomy that wires the
> pipeline to the frontend, configuration and secret management, the async
> event bus, the chat controller, and the provider-agnostic auth flow. Nothing
> here is domain-specific; subpackages own the pipeline stages, the vault
> model, the wire protocol, and the tool layer.

**Depends on:** every subpackage imports upward into this level · **Depended on by:** `tui/` (via the bridge wire)
**Reads:** `~/.avicenna/user_config.json`, `~/.avicenna/mcp_config.json`, `.env`, OS keyring · **Writes:** `user_config.json`, keyring/file key store

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `__init__.py` | 2 | Package marker; no re-exports. |
| `auth.py` | 119 | Provider onboarding: validate a key with one real completion, persist it, report status. Deferred imports from `providers/` keep the auth module importable without pulling in the SDK. |
| `bus.py` | 51 | Fan-out async event bus. Each subscriber gets its own queue; `LogMessage` events are droppable under backpressure, all others block the emitter. |
| `chat.py` | 108 | Agent chat controller. One `AgentChat` per vault agent with a per-agent lock to prevent interleaved appends. Tool allowlist (`CHAT_SAFE_TOOLS` plus the agent's MCP servers) keeps pipeline-only mutators unreachable from chat. |
| `concurrency.py` | 26 | `gather_sections`: bounded concurrent execution of N awaitables via a semaphore (default 3). One failure does not cancel siblings. |
| `config.py` | 127 | Central configuration: env resolution, `.env` loading via dotenv, MCP and user config persistence. All diagnostics go to stderr — never stdout, which belongs to the NDJSON wire protocol. Atomic writes with `os.replace`; best-effort `chmod` on the user config. |
| `events.py` | 165 | Typed event taxonomy — frozen dataclasses for every pipeline signal. The bridge serialises structurally (class name becomes `event`, fields become `data`), so adding an event here is sufficient for the wire. A matching `EventName` entry in `tui/src/protocol.ts` plus a frontend translator case are required; `scripts/check_protocol_parity.py` gates this in CI. |
| `secrets.py` | 61 | API key read/write/redact. Precedence: env var, OS keyring, `user_config.json` file fallback. Write prefers keyring and tells the caller where the key landed ("keyring" or "file") so the frontend can be honest about protection. |
| `session.py` | 118 | The two runtime primitives. `Session` owns a message list and the tool-resolution loop (up to 8 iterations) on top of the stateless provider ABC. `one_shot` is `SPAWN_SECTION`: builds a Session, sends one prompt, returns the text, discards the context. This is what gives every heading a fresh context — the mechanism behind AGENTS.md §2.1. |
<!-- map:files:end -->

## Subpackages

- **bridge/** — NDJSON wire protocol between backend and the TypeScript frontend.
- **cli/** — Typer CLI entry point (`avicenna/cli/app.py::main`).
- **mcp/** — MCP client transport, config schema, and tool-spec export.
- **pipeline/** — Run orchestration, stage execution, section generation, resume.
- **providers/** — LLMProvider ABC, error hierarchy, Mistral backend, FakeProvider, registry.
- **tools/** — ToolRegistry, contract-token parser, built-in tools, runner protocol.
- **vault/** — Vault discovery, loading, agent/taxonomy models, routing, init scaffold.

Each subpackage has its own `MAP.md`.

## Invariants

- `session.py`'s `one_shot` is the isolation boundary: each section gets a
  fresh `Session` that has never seen another section. Sharing a session
  across headings degrades quality monotonically. Never "optimise" this.
- Every module must begin with `from __future__ import annotations` and be
  fully type-annotated. CI rejects any `.py` file missing the future import.
- `events.py` is the single source of truth for the event taxonomy. Adding a
  event requires: (1) frozen dataclass here, (2) `EventName` in
  `tui/src/protocol.ts`, (3) handler case in the frontend translator. The
  bridge itself needs no change — it serialises structurally.
  `scripts/check_protocol_parity.py` fails the build if (1) and (2) diverge.
- stdout belongs to the NDJSON protocol. No module in this package (or any
  reachable from the bridge) may `print()` to stdout. Diagnostics go to
  stderr via `config.warn()` or `print(..., file=sys.stderr)`.

## Entry points

- To change the event taxonomy, start at `events.py:30`.
- To change how a provider is validated during onboarding, start at `auth.py:27`.
- To change the tool-resolution loop or `one_shot` behaviour, start at `session.py:34`.

## See also

- `providers/MAP.md` — the ABC every Session talks to, the only real backend, and the CI gates that keep vendor SDKs contained.
- `pipeline/MAP.md` — the run orchestrator that calls `one_shot` per heading.
- `bridge/MAP.md` — the NDJSON protocol that subscribes to the events defined here.
