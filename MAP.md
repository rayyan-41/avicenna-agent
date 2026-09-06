# MAP: avicenna-agent

> Avicenna is an academic scribe: a two-process harness that turns a raw,
> half-formed idea into a long-form Markdown note in an Obsidian vault. The note
> is structured by a pre-flight declaration, written heading by heading in fresh
> contexts by domain-specialist subagents, woven into continuous prose, tagged
> from a closed taxonomy, wikilinked into existing notes, and entered into the
> domain Map of Content. It is a harness for subagents and MCP tools, not a
> chatbot. Every design decision answers one question: does this make the next
> note better connected to the rest of the user's thinking?

## Read this first

1. This file — state of the world, directory routing, commands, invariants.
2. The directory `MAP.md` for whatever you are about to touch.
3. Source. `AGENTS.md` holds the doctrine and answers *why* the system is built
   this way; this file answers *what is true right now*. Do not duplicate
   doctrine here — point and move on.

## State of the world

| Component | Status | Notes |
| --- | --- | --- |
| Generation pipeline | Working | 14 stages, contract-gated, fresh context per heading. |
| Vault binding & routing | Working | A model classifies the topic against the vault's domains; `validate_domain` gates the answer; the deterministic keyword scorer is the offline fallback and refusal is the last resort. Keyword-only scoring reached 3 of 6 domains on the reference vault, which is what prompted the inversion. |
| Tool layer | Working | Registry with BUILTIN > VAULT_PS1 > MCP precedence; contract tokens. |
| MCP layer | Working | Full client, config schema, tool-spec export. Ships zero servers. |
| Provider layer | Working | Mistral is the only real backend. FakeProvider is the offline test double. |
| Stdio bridge | Working | NDJSON over stdin/stdout; structural event serialisation; no blocking I/O. |
| CLI | Working | Typer app: note, route, init, mcp, config, doctor, headless mode. |
| Healthcheck | Working | `avicenna doctor` / `scripts/healthcheck.py`. Eight probes over config, provider reachability, vault load, tool registry, vault PowerShell tools, MCP servers, all bridge methods, and routing. This is what an "endpoint" means here: there is no HTTP surface. |
| Live generation matrix | Working | `scripts/gen_matrix.py`. One ~1000-word note per domain agent against a real vault, gated behind `--yes`, refusing a dirty git tree, printing revert commands before it writes. |
| Continuous delivery | Working | `.github/workflows/release.yml` on `v*` tags: gates via `workflow_call` into `ci.yml`, builds sdist, wheel and the tui bundle, publishes a GitHub Release. No PyPI job — no token exists. |
| Terminal frontend | Partial | Mechanism works (bridge, input, screen, commands). Deliberately an unstyled skeleton with no visual design — no palette, no glyph set, no boxes. A design pass must build a new layer on top. |
| Map context tree | Working | 20 maps, one per source directory. `scripts/check_maps.py` gates coverage, inventory parity and placeholders in CI's `hygiene` job. |

Mistral is the only implemented provider. There is no OpenAI, Anthropic, or Gemini backend — adding one means implementing `LLMProvider` from `providers/base.py` and registering a lazy factory. `FakeProvider` is a scripted in-memory stand-in; the entire test suite runs against it with no API key and no network.

Because the suite runs entirely against `FakeProvider`, a green build says
nothing about whether the product works against a real API. It did not, once:
the configured model was gated behind a subscription tier and every call
returned 403 while all tests passed. `avicenna doctor` exists to close that gap
and is the first thing to run when something behaves oddly.

## Runtime shape

A bound vault is an Obsidian directory containing:

```
vault-root/
  AGENTS.md              # runtime orchestrator prompt — NOT this repo's AGENTS.md
  .agents/
    agents/<name>.md     # content, pipeline, and audit agent definitions
    skills/<name>/       # named procedures (SKILL.md per skill)
    tools/*.ps1          # contract-token-emitting PowerShell scripts
    taxonomy.json        # domains, categories, types, themes — closed vocabulary
    mcp.json             # MCP server declarations (ships empty)
  _tmp/                  # chunks, manifest, pipeline state; gitignored
  <Domain>/              # Title Case folders, created on first note
```

`avicenna init` scaffolds this from scratch. A vault with zero `.ps1` tools is
legitimate — builtin Python tools always register, and pipeline stages degrade
with a warning when a vault tool is absent.

## Directory index

| Directory | What it owns | Map |
| --- | --- | --- |
| `avicenna/` | Backend package root: Session, one_shot, events, bus, config, auth, secrets | [`avicenna/MAP.md`](avicenna/MAP.md) |
| `avicenna/bridge/` | NDJSON wire protocol between backend and TypeScript frontend | [`avicenna/bridge/MAP.md`](avicenna/bridge/MAP.md) |
| `avicenna/cli/` | Typer CLI: all commands, TUI launch, headless mode | [`avicenna/cli/MAP.md`](avicenna/cli/MAP.md) |
| `avicenna/mcp/` | MCP client transport, config schema, tool-spec export | [`avicenna/mcp/MAP.md`](avicenna/mcp/MAP.md) |
| `avicenna/pipeline/` | Run orchestration, 14 stages, section fan-out, resume | [`avicenna/pipeline/MAP.md`](avicenna/pipeline/MAP.md) |
| `avicenna/providers/` | LLMProvider ABC, Mistral backend, FakeProvider, registry | [`avicenna/providers/MAP.md`](avicenna/providers/MAP.md) |
| `avicenna/tools/` | ToolRegistry, contract tokens, builtin tools, PS1 and MCP wrappers | [`avicenna/tools/MAP.md`](avicenna/tools/MAP.md) |
| `avicenna/vault/` | Vault discovery, loading, agent/taxonomy models, routing, init scaffold | [`avicenna/vault/MAP.md`](avicenna/vault/MAP.md) |
| `scripts/` | Build-time hygiene linters (protocol parity, map gate) | [`scripts/MAP.md`](scripts/MAP.md) |
| `tests/` | Full backend test suite, runs against FakeProvider | [`tests/MAP.md`](tests/MAP.md) |
| `tests/fixtures/` | Real MCP fixture server for integration tests | [`tests/fixtures/MAP.md`](tests/fixtures/MAP.md) |
| `tui/` | TypeScript terminal frontend, its own toolchain and CI job | [`tui/MAP.md`](tui/MAP.md) |
| `tui/src/` | Ten runtime modules: bridge, app, screen, composer, commands, keys, text, ansi, protocol, main | [`tui/src/MAP.md`](tui/src/MAP.md) |
| `tui/test/` | Frontend tests: commands, keys, text measurement | [`tui/test/MAP.md`](tui/test/MAP.md) |
| `docs/` | User-facing MCP guide; design specs | [`docs/MAP.md`](docs/MAP.md) |
| `docs/archive/` | Historical docs from pre-harness architecture | [`docs/archive/MAP.md`](docs/archive/MAP.md) |
| `.github/workflows/` | CI: three jobs, no continue-on-error | [`.github/workflows/MAP.md`](.github/workflows/MAP.md) |
| `.claude/` | Claude Code local session settings (gitignored) | [`.claude/MAP.md`](.claude/MAP.md) |

## Where do I go for X

| You want to | Start at |
| --- | --- |
| Change the stage list or add a stage | `avicenna/pipeline/stages.py:761` (`build_stages`) |
| Change what a specific stage does | Its class in `stages.py`; read the docstring and surrounding comments |
| Change which agent a topic routes to | `avicenna/vault/routing.py:178` (`score_domains`) |
| Add a new event to the wire | `avicenna/events.py` (dataclass), `tui/src/protocol.ts` (EventName), `tui/src/app.ts` (handler case) |
| Add a new tool | Builtin: `avicenna/tools/builtin.py`. Vault PS1: `tools/vault_tools.py` manifest row. MCP: configure in `mcp_config.json`. |
| Add a contract token | `avicenna/tools/contracts.py:52` (`CONTRACTS` dict) |
| Add a new provider backend | `avicenna/providers/`: implement `LLMProvider`, map errors, register lazy factory in `__init__.py` |
| Change the wire protocol envelope | `avicenna/bridge/protocol.py:47` (`event_frame`), `:42` (`encode`); bump `PROTOCOL_VERSION` at `:24` |
| Add a bridge method | `avicenna/bridge/server.py:162` (add `_m_<name>`) |
| Change what `avicenna init` scaffolds | `avicenna/vault/init_scaffold.py:63` (`init_vault`) |
| Change cancellation or resume | `avicenna/pipeline/stage.py:65` (runner), `pipeline/run.py:71` (re-raise), `pipeline/resume.py` (manifest) |
| Change section parallelism or retry | `avicenna/pipeline/sections.py:120` (`generate_sections`) |
| Debug a desynced frontend | `tui/src/bridge.ts:101` (process spawn), `tui/src/protocol.ts` (wire shapes), then `avicenna/bridge/server.py:445` (run loop) |
| Change what the screen looks like | `tui/src/app.ts:1067` (`render`); the visual design attaches at `write()`, `transcriptLines()`, `status()`, `composer.layout()` |
| Add a CLI command | `avicenna/cli/app.py:57` (`@app.command`) |
| Add an MCP transport | `avicenna/mcp/mcp_client.py:68` (`_get_server_command`) |
| Add a CI gate | `.github/workflows/ci.yml` — add a step to the appropriate job |
| Change onboarding or key management | `avicenna/auth.py:31` (`validate_key` — one cheap real call), `avicenna/secrets.py` (persistence) |
| Understand cross-cutting invariants | `AGENTS.md` §2 (the six commitments), `CLAUDE.md` (rules that bite) |

## Commands

```bash
# backend
pip install -e ".[dev]"                          # editable install + test extras
pytest -q                                         # full backend test suite
mypy --strict avicenna/providers avicenna/pipeline # strict type check (must be clean)
python scripts/check_protocol_parity.py           # events.py vs protocol.ts
python scripts/check_maps.py                      # MAP.md coverage + parity (--fix to refresh)
avicenna doctor                                   # eight live probes; --json for machines
python scripts/gen_matrix.py                      # prints the plan; --yes to actually generate

# frontend
cd tui && npm ci && npm run typecheck && npm run build && npm test

# drive the backend without a terminal
echo '{"type":"req","id":"1","method":"vault.info","params":{}}' | python -m avicenna.bridge
```

CI runs the Python job on `windows-latest` (vault tools depend on PowerShell)
and the TUI job on `ubuntu-latest`.

## Invariants that bite

- **stdout belongs to the wire protocol.** One stray `print` desyncs the
  frontend's NDJSON parser. Diagnostics go to stderr. See `bridge/MAP.md`.
- **Nothing under `bridge/` may block.** CI rejects `subprocess.run`,
  `time.sleep`, `requests.` in that package. See `bridge/MAP.md`.
- **No vendor SDK outside `providers/`.** Two CI gates enforce this: containment
  and neutrality. See `providers/MAP.md`.
- **`from __future__ import annotations` at the top of every Python module.**
  CI rejects any `.py` file missing it. See `avicenna/MAP.md`.
- **UTF-8 without BOM, LF endings.** Every file write, every commit.
  `.gitattributes` normalises; CI's hygiene job checks.
- **The reference vault's name appears nowhere outside `tests/`.** CI gate
  enforces. See `.github/workflows/MAP.md`.
- **`pyproject.toml` is the only dependency manifest.** `requirements.txt`
  stays deleted. CI checks.
- **Only the pipeline writes to a note.** `_write_back` guards every
  post-assembly revision against model truncation. See `pipeline/MAP.md`.
- **Sections get fresh contexts.** Each heading runs through `one_shot()` with
  no accumulated history. Never "optimise" this — quality degrades monotonically
  after ~3 sections in a shared session. See `pipeline/MAP.md`.
- **Contract tokens gate the pipeline, never the model's opinion.** Stages
  branch on regex-parsed `MANIFEST_WRITTEN`, `ALL_PRESENT`, `PASS`, etc. See
  `tools/MAP.md`.
- **CI has no `continue-on-error`.** A check that cannot fail the build is
  documentation, not a gate. See `.github/workflows/MAP.md`.

## Root files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `AGENTS.md` | 515 | The canonical doctrine document: purpose, the six commitments, architecture, conventions. Answers *why*. Read it before proposing any structural change. |
| `AVICENNA.md` | 15 | A pointer to the two documents above, kept so historical inbound links still land somewhere useful. |
| `CLAUDE.md` | 159 | The short operational layer for coding agents: where things live, the commands, and the rules that bite from inside an editor. |
| `README.md` | 184 | User-facing overview: installation, quick start, and the command table. |
<!-- map:files:end -->

`pyproject.toml` is the sole dependency manifest and declares the `avicenna`
console-script entry point; `avicenna.png` is the project image. Neither carries
a row above, because the gate's inventory covers only the extensions it can
meaningfully line-count.

## Keeping these maps true

Every subdirectory `MAP.md` carries `<!-- map:files:start -->` /
`<!-- map:files:end -->` markers around a table of its source files.
`scripts/check_maps.py` gates three properties in CI's `hygiene` job: every
tracked directory holding source has a map, the filename set inside the markers
matches `git ls-files` exactly, and no row carries an unwritten placeholder
role. A marker is recognised only when it stands alone on its line, so a map may
quote the convention in prose — as this section does — without tripping the
duplicate check.

Its `--fix` mode adds rows for new files and refreshes line counts, but writes
the role as a placeholder deliberately: a placeholder always fails the gate, so
a mechanical fix can never satisfy it and someone must supply the sentence.
Stage a new file before running `--fix`, because inventories are derived from
`git ls-files` and an untracked file's row will be removed rather than added.
