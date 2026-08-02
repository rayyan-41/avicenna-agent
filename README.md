# Avicenna — The Note-Generation TUI Harness

> A two-pane terminal cockpit for producing long-form, structurally-guaranteed
> notes in an Obsidian vault.

## What Avicenna Does

Avicenna is **not a chatbot**. It is a single-purpose instrument for generating
long-form notes. The terminal is split:

- **Left panel (Metadata)** — vault card, pre-flight checklist, per-heading
  completion grid, pipeline stage stepper, word count, tool-call tracker.
- **Right panel (Chat)** — push a topic, watch the run narrate itself, get
  final confirmation.

Once bound to a vault, `avicenna note "some topic"` runs a full pipeline:
routing, pre-flight, parallel section generation, assembly, word count, TOC,
tagging, formatting, linking and MOC update — all gated by deterministic
PowerShell contract tokens, never by model prose.

## Installation

```bash
# Prerequisites: Python 3.10+, Git
git clone https://github.com/rayyan-41/avicenna-agent.git
cd avicenna-agent
python -m venv .venv
source .venv/Scripts/activate  # Git Bash on Windows
pip install -e .
```

## Quick Start

### 1. Scaffold a vault

```bash
avicenna init ~/my-vault
```

### 2. Configure a provider

Create a `.env` file in the project root:

```env
MISTRAL_API_KEY=your_mistral_api_key_here
```

Or let the TUI's onboarding screens handle it on first launch.

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

## Slash Commands

`/agent <name>`, `/agents`, `/note <topic>`, `/vault`, `/mcp`, `/clear`, `/help`, `/save`

## Headless Mode

```bash
avicenna --no-tui
avicenna note "The Ottoman Conquest of the Balkans" --vault ~/my-vault
```

## MCP Integration

Supports the Model Context Protocol. Ships with **zero** servers by default.

```bash
avicenna mcp list
avicenna mcp path
```

See [docs/MCP_GUIDE.md](docs/MCP_GUIDE.md) for the full guide.

## Development

See [AVICENNA.md](AVICENNA.md). Run tests:

```bash
pip install -e ".[dev]"
pytest tests/ --asyncio-mode=auto
```
