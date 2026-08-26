# Avicenna — The Note-Generation Harness

> An academic scribe: a terminal harness that turns a raw idea into a
> long-form, structurally-guaranteed, semantically-connected note in an
> Obsidian vault.

## What Avicenna Does

Avicenna is **not a chatbot**. It is a single-purpose instrument for generating
long-form notes. Give it a topic and it runs a full pipeline: routing,
pre-flight, parallel section generation, assembly, word count, TOC, tagging,
formatting, linking and MOC update — all gated by deterministic PowerShell
contract tokens, never by model prose. The interface narrates every stage as it
happens: stage markers, per-section progress with word counts and timings, tool
calls with their results, and a final written-note confirmation.

Domain-specialist subagents do the writing, one per heading in a fresh context.
MCP tools extend what a section can reach. The finished note is tagged from a
closed taxonomy and wikilinked into the notes you already have, so it arrives
connected rather than orphaned. See [AGENTS.md](AGENTS.md) for the full account.

## Architecture

Two processes, one pipe.

```
  tui/  (TypeScript)                    avicenna/  (Python)
  ┌────────────────────┐   NDJSON      ┌─────────────────────┐
  │ renderer, input,   │  over stdio   │ bridge, pipeline,   │
  │ transcript         │ <───────────> │ providers, tools,   │
  │                    │               │ MCP, vault          │
  └────────────────────┘               └─────────────────────┘
```

The frontend owns everything you see and nothing you run; the backend owns
everything it runs and nothing you see. They meet at
`avicenna/bridge/protocol.py`, one JSON object per line in each direction. The
frontend starts the backend itself, so `avicenna` remains the only command you
need.

## Installation

```bash
# Prerequisites: Python 3.10+, Node.js 18+, Git
git clone https://github.com/rayyan-41/avicenna-agent.git
cd avicenna-agent

python -m venv .venv
source .venv/Scripts/activate  # Git Bash on Windows
pip install -e .

cd tui && npm install && npm run build && cd ..
```

## Quick Start

### 1. Scaffold a vault

```bash
avicenna init ~/my-vault
```

### 2. Configure a provider

Launch `avicenna` and onboarding will ask for a key, validate it with one
small live request, and store it in your OS keyring when one is available —
falling back to `~/.avicenna/user_config.json`, and telling you which of the
two it used. Alternatively, put it in a `.env` file in the project root:

```env
MISTRAL_API_KEY=your_mistral_api_key_here
```

### 3. Launch

```bash
avicenna
```

Type a topic and press Enter.

## The Pipeline

```
User Topic
    -> Routing Stage -> Pre-flight Stage -> Manifest Stage
    -> Sections Stage (parallel one_shot per heading)
    -> Assembly Stage -> Word Count Stage -> TOC Stage
    -> Tagging Stage -> Formatter -> Linker -> MOC Stage
    -> Note written to vault
```

Every heading is a **separate one-shot call** with a context that has never seen
another section — the architecture the project started with, when it spawned a
headless CLI process per heading. One session hosts as many ideas as you like;
its transcript is a log, never replayed to the model. That isolation is what
lets a 10k-word note hold its word floor and its quality all the way to the last
heading.

## Interface

Type a topic to generate a note. Type `/` to list commands.

| Command | What it does |
| --- | --- |
| `/note <topic>` | Generate a full note through the pipeline |
| `/dry <topic>` | Route and pre-flight only — no writing |
| `/resume` | Resume the last interrupted run |
| `/cancel` | Cancel the run in flight |
| `/agent <name>` | Chat with a vault agent |
| `/agents` | List the agents this vault defines |
| `/route <topic>` | Explain which agent a topic routes to, and why |
| `/vault` | Show the bound vault and where you are standing |
| `/tools` | List every registered tool and its source |
| `/mcp` | List configured MCP servers |
| `/init [path]` | Scaffold a new vault |
| `/login` | Set or replace the provider API key |
| `/diagnostics` | Show backend stderr for this session |
| `/help` | Everything above, in the app |

| Key | Action |
| --- | --- |
| `Enter` | Send |
| `Alt+Enter` | Newline |
| `Tab` | Accept the highlighted command |
| `Up` / `Down` | Prompt history |
| `PgUp` / `PgDn` | Scroll the transcript |
| `Esc` | Dismiss command completion, or cancel a run |
| `Ctrl+L` | Clear the transcript |
| `Ctrl+C` | Cancel a run, then quit |

Options: `--vault <path>` binds a vault, `--ascii` restricts output to plain
characters on legacy consoles (or set `AVICENNA_ASCII=1`), `--no-tui` runs
headless, and `--reconfigure` forces onboarding. The launcher resolves the
Python interpreter for the backend itself.

> The interface is currently an unstyled skeleton: the visual design was
> removed deliberately and is being rebuilt. See [tui/README.md](tui/README.md).

## Headless Mode

```bash
avicenna --no-tui
avicenna note "The Ottoman Conquest of the Balkans" --vault ~/my-vault
avicenna route "Ibn Sina"
```

## MCP Integration

Supports the Model Context Protocol. Ships with **zero** servers by default.

```bash
avicenna mcp list
avicenna mcp path
```

See [docs/MCP_GUIDE.md](docs/MCP_GUIDE.md) for the full guide.

## Development

See [AGENTS.md](AGENTS.md) for the doctrine, architecture and conventions, and
[CLAUDE.md](CLAUDE.md) for the short working file used by coding agents.

```bash
# backend
pip install -e ".[dev]"
pytest -q
mypy --strict avicenna/providers avicenna/pipeline
python scripts/check_protocol_parity.py

# frontend
cd tui
npm run typecheck
npm test
```

Every one of those runs in CI, and every CI step blocks — there is deliberately
no `continue-on-error` in the workflow.

To watch the wire protocol while the interface runs, drive the bridge by hand:

```bash
echo '{"type":"req","id":"1","method":"vault.info","params":{}}' | python -m avicenna.bridge
```
