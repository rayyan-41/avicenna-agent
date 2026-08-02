# AVICENNA.md — Repo Development Guidance

This file is the authoritative development-guidance document for the
`avicenna-agent` repository. It is intended for both human contributors
and AI coding agents working on the codebase.

## What Avicenna Is

Avicenna is **not a chatbot**. It is a single-purpose instrument for
producing long-form, structurally-guaranteed notes in an Obsidian vault.
The terminal is a cockpit:

- **Left panel** — live metadata: pre-flight checklist, per-heading
  completion grid, running stats, current pipeline stage.
- **Right panel** — chat: where the user prompts, watches the run
  narrate itself, and gets the final confirmation.

The vault is user data; Avicenna is the engine. A vault carries its own
`AGENTS.md` protocol, agent definitions, skills, taxonomy and tools.
De Anima is the *reference* vault, never a hardcoded dependency.
`avicenna init` must produce a working vault from scratch.

The two runtime primitives:

| Primitive | Meaning | Implementation |
|---|---|---|
| `SPAWN_SECTION` | Run one prompt in a **completely fresh context**, write the result to `_tmp/[slug]_chunk_NN.md`. | `one_shot()` |
| `DELEGATE @agent` | Load a named agent's markdown body as the system prompt, run a payload in a fresh context, return the output. | `delegate()` over `one_shot()` |

## Architecture Decisions

1. **Stateless completion is the primitive, chat is built on top.**
   The pipeline emits typed events and knows nothing about a terminal.
   The TUI, the JSONL run log, and headless mode are all just subscribers.

2. **Fresh-context-per-section.** Sections run in parallel (bounded
   concurrency, default 3). Never "optimise" into a shared chat session
   — that degrades quality for later sections.

3. **Mistral is primary.** Gemini is quarantined behind a new stateless
   provider ABC (`avicenna/providers/base.py`) and will not be shipped in
   the initial release.

4. **Google Workspace/OAuth is cut.** Parked on branch
   `archive/google-workspace` and tag `v1-pre-harness`.

5. **MCP ships with zero servers** but full schema and transport support
   (python, node, executable transports, the Windows `npx.cmd` fallback,
   `AsyncExitStack` teardown).

6. **The vault is user data.** De Anima is the reference, never a
   dependency.

7. **Contract-gated tool execution.** Tools emit machine-parseable tokens.
   The pipeline branches on regex-parsed contracts, never on the model's
   opinion of whether a step worked.

## Repo Conventions

| Concern | Canonical | Not |
|---|---|---|
| Neutral provider types + ABC | `avicenna/providers/base.py` | `providers/types.py` |
| Tool-call events | `ToolInvoked` / `ToolReturned` | `ToolCallStarted` / `ToolCallFinished` |
| Tool package | `avicenna/tools/` (a package) | `avicenna/tools.py` (a module) |
| Tool-runner protocol | `avicenna/tools/runner.py`, exposed as `ToolRegistry.runner` | `vault.tools.run` |
| CLI | `avicenna/cli/` package, entry `avicenna/cli/app.py::main` | `avicenna/cli.py` |
| MCP neutral schema export | `MCPClientManager.tool_specs()` | `get_tool_specs()` |
| Dependency manifest | `pyproject.toml` only | `requirements.txt` |
| Repo dev doc | `AVICENNA.md` (repo root) | — |
| Vault protocol file | `AGENTS.md` (vault root) | never rename to `AVICENNA.md` |

**Style rules:**

- Python 3.10+, `from __future__ import annotations` at the top of every
  module.
- Fully type-annotated. `mypy --strict` clean for `avicenna/pipeline` and
  `avicenna/providers`.
- All file writes are UTF-8 **without BOM**, LF line endings.
- No module outside `avicenna/providers/` imports a vendor SDK.
- No module outside `avicenna/tui/` imports `textual`.
- No module outside `tests/` contains the literal string `De Anima`.
- Keep `requirements.txt` deleted. `pyproject.toml` is the single source
  of truth for dependencies.

## Rollback Points

- **Tag `v1-pre-harness`** — Snapshot of Avicenna v1 (Gemini + Google
  Workspace era) before the TUI harness rewrite. Immutable.
- **Branch `archive/google-workspace`** — Parked Google Workspace/OAuth
  WIP. Also reachable from `v1-pre-harness`. Do not commit further to
  this branch.

## Phase Map

| Phase | Title | Leaves the app runnable? |
|---|---|---|
| 0 | Baseline, safety net, environment | yes |
| 1 | Repo cleanse and restructure | no (intentionally) |
| 2 | Provider abstraction and the Mistral backend | no |
| 3 | Event system and the session primitive | no |
| 4 | The tool layer | no |
| 5 | The vault layer | no |
| 6 | The generation pipeline | yes (headless) |
| 7 | The Textual TUI | yes |
| 8 | Onboarding and the startup flow | yes |
| 9 | Agent chat mode | yes |
| 10 | MCP guide, packaging, release | yes |
