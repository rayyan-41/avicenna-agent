# AGENTS.md — Avicenna

> Avicenna is an academic scribe. You hand it a raw idea; it hands you back a
> long-form, structurally-guaranteed, semantically-connected note in your
> Obsidian vault. It is not a chatbot, and everything in this document exists
> to keep it from becoming one.

This file is the canonical document for the `avicenna-agent` repository. It is
written for both human contributors and AI coding agents. Read it before
changing anything: it explains not just what the code does, but what it is
allowed to become.

---

## 0. Two files are called AGENTS.md. They are different files.

| File | Lives at | Audience | Purpose |
| --- | --- | --- | --- |
| **This one** | repository root | contributors, coding agents | How the harness is built and what it is for |
| **The vault protocol** | *vault* root, e.g. `~/my-vault/AGENTS.md` | the model, at runtime | The orchestrator system prompt for one user's vault |

The vault's `AGENTS.md` is read at runtime by `Vault.load` into
`Vault.protocol_text`. Its presence, alongside a `.agents/` directory, is
literally how `discover_vault` recognises a directory as a vault. Never rename
either one. Never merge them.

---

## 1. The purpose

### The problem Avicenna exists to solve

You have an idea. Not a question — an idea, half-formed, of the kind that
arrives while reading something else:

> *The epistemic gap and the necessity of revelation.*

You know roughly what you mean. Unaided reason can establish some things: that
there is a necessary existent, that human beings have ends, that some acts are
better than others. It cannot establish others: the determinate content of
obligation, the particulars of the afterlife, what specifically is owed and to
whom. Between what reason reaches and what a human life requires, there is a
gap. The claim that revelation is what closes it is an argument with a long
history, a technical vocabulary, and several centuries of objections.

To turn that half-formed idea into something you can actually think with, you
would have to read Ibn Sina on prophecy, al-Ghazali on the limits of the
intellect, Aquinas on *sacra doctrina*, the kalam disputes over whether good and
bad are knowable by reason alone, and enough of the modern literature to know
which of your intuitions already have names. Then you would have to write it
down in a way that connects to everything else you already know.

That is weeks of work. **Avicenna compresses it into a note.**

### What it actually produces

One Markdown file, written into the correct domain folder of your Obsidian
vault, that has:

- **Structure that was declared before a word was written.** A pre-flight stage
  commits to a template, a heading list, a target word count and a slug. The
  note is generated against that declaration rather than improvised into
  existence.
- **Depth in every section.** Every heading is written in its own fresh context
  by a domain specialist, to a per-section word budget. Section eleven is as
  careful as section one.
- **Prose, not an outline.** Chunks are woven together with real transitions by
  a `weaver` agent, not concatenated under headings.
- **Tags from a closed taxonomy.** A `tagger` proposes; `validate_tags` checks
  the proposal against `taxonomy.json` and rejects invention. Tags that do not
  exist in your vocabulary do not enter your vault.
- **Wikilinks into what you already have.** `get_related_notes` scores existing
  notes against the new one's tags; a `linker` agent inserts `[[wikilinks]]` at
  the places where the argument actually touches them.
- **A place in the graph.** The domain's Map of Content is updated, so the note
  is reachable rather than orphaned.

The deliverable is not the text. **The deliverable is a note that is connected
to the rest of your thinking.** A brilliant orphan note is a failure of this
program.

### What Avicenna is not

It is not a chatbot. It is not a research assistant you converse with. It is not
a general-purpose agent, a coding assistant, or a shell. `/agent <name>` exists
so you can interrogate a domain specialist about its own domain — a diagnostic
instrument for the vault, not the product.

The single-purpose framing is the design, not a limitation waiting to be lifted.
Every request of the form *"could it also…"* is answered by asking whether it
makes the next note better connected. If not, the answer is no.

---

## 2. The doctrine

Six commitments. They are not preferences: the architecture depends on them, and
most of the failure modes in this codebase come from violating one.

### 2.1 One heading, one fresh context. This is the whole trick.

**Where it came from.** Avicenna began as a Gemini CLI script. For each heading
in an outline, it opened a new shell and launched a *separate* headless Gemini
instance — `--yolo` for no permission prompts, `-p` with a prompt covering that
one heading — and captured the output to a chunk file. Nothing was shared
between those processes. Each one booted, wrote its section, and died.

That crude arrangement produced something a chat session could not: a 10,000-word
note in which the last heading was as substantial as the first.

**The primitive survived; only the process went away.** `one_shot()` is that
subprocess without the subprocess — one prompt, one completion, a context that
has never seen another section. `SPAWN_SECTION` is the runtime name for it, and
`DELEGATE @agent` is the same call with an agent's body as the system prompt.
Sections now run in parallel under bounded concurrency (default 3) instead of
sequentially in separate shells, but the isolation is identical and deliberate.

**Three levels, and context crosses none of them:**

| Level | Lifetime | What accumulates |
| --- | --- | --- |
| Session | As long as the user keeps the app open | Many ideas, many notes, one transcript |
| Run | One note | Structure and stage state — never model context |
| Section | One heading | Nothing. It ends with the completion. |

One session is home to as many ideas as the user wants to throw at it. That
transcript is a **log**, not a conversation history: nothing in it is replayed
back to the model. Every ping to the provider behind the scenes is a fresh
one-shot for exactly one heading.

**Why this is what makes a 10k note possible.** Give a heading its own context
and the model's entire attention budget is spent on that heading — which is how
a floor of roughly 1,000 words per section can be *asked for and met*, rather
than hoped for. Eleven headings at that floor is an 11,000-word note whose
eleventh section is written as carefully as its first. Fidelity stays flat
across the note, and context bloat never happens because there is no context to
bloat.

The temptation to undo this is obvious: keep one chat session, feed it heading
after heading, save the tokens. **Never do this.** In a shared session, section
eight is written by a model whose context is mostly its own earlier output.
Quality decays monotonically: later sections get shorter, vaguer, and start
summarising what came before instead of advancing the argument. A reader notices
immediately — it is the signature of machine-written long-form text, and it is
precisely the failure the original Gemini CLI hack was written to escape.

Cross-section coherence is not bought with a shared context. It is bought
afterwards, by the `weaver`, which sees every chunk at once and writes the
transitions. That is the correct place to spend it.

### 2.2 Domain specialists, not one generalist

A note on Ottoman military logistics and a note on transformer attention are not
the same writing task. They differ in what counts as evidence, what a citation
looks like, which claims need hedging, and what an educated reader is assumed
already to know.

So the writing is delegated. A **content agent** is a Markdown file with YAML
frontmatter whose body becomes the system prompt for every section of every note
in its domain. `DELEGATE @agent` is literally `one_shot()` with
`system = agent.system_prompt`. That is the whole mechanism, and its simplicity
is the point: adding a specialist means writing a Markdown file, not writing
code.

### 2.3 Contracts gate the pipeline, never the model's opinion

Tools return machine-parseable tokens — `MANIFEST_WRITTEN`, `ALL_PRESENT`,
`WORDCOUNT_FAIL`, `PASS`. The pipeline branches on a regex match against those
tokens. It never branches on the model saying the step went well.

A model asked *"did that work?"* answers yes. This is not a prompt problem to be
engineered around; it is why the contract layer exists. If a stage's success
cannot be decided by a deterministic check, that stage does not get to gate
anything.

### 2.4 Graceful degradation, loudly

A vault may legitimately ship zero PowerShell tools — `avicenna init` produces
one that does. Every tool call in `pipeline/stages.py` is therefore optional:
when the tool is absent, the stage falls back to a Python equivalent or skips,
and **always emits a warning saying so**. A user must never silently receive a
lesser note.

### 2.5 The vault is user data

Avicenna is the engine; the vault is the corpus. A vault carries its own
protocol, agents, skills, taxonomy and tools, and `avicenna init` must produce a
working vault from scratch using none of ours.

De Anima is the *reference* vault used during development. It is never a
dependency. **No module outside `tests/` may contain the literal string
`De Anima`.**

Notes are written atomically — a sibling `.part` file plus `os.replace` —
because Obsidian indexes on write, and a half-written note would appear in
search, in graph view, and in the next commit of the user's git plugin.

### 2.6 Stateless completion is the primitive; everything else subscribes

The pipeline emits typed events (`avicenna/events.py`) onto a bus and knows
nothing about a terminal. The interface, the JSONL run log and headless mode are
all just subscribers.

This is why the frontend was able to leave the process entirely (§6). It is also
why adding an event to `events.py` surfaces it on the wire with no bridge
change: the serialiser is structural — the class name becomes `event`, the
fields become `data`.

---

## 3. Anatomy of a run

```
topic
  |
  |- Routing ......... deterministic keyword scoring -> domain -> content agent
  |- Pre-flight ...... the agent declares template, headings, target words, slug
  |- Manifest ........ write_manifest.ps1 -> MANIFEST_WRITTEN, resume state
  |- Sections ........ N parallel one_shot() calls, one per heading, fresh each
  |- Assembly ........ verify_chunks -> ALL_PRESENT, then @weaver, then atomic write
  |- Word count ...... validate_wordcount -> PASS / FAIL (warns, never blocks)
  |- TOC ............. generate_toc.ps1
  |- Tagging ......... @tagger proposes -> validate_tags gates -> up to 3 attempts
  |- Formatting ...... @formatter applies the declared template
  |- Linking ......... get_related_notes scores -> @linker inserts wikilinks
  \- MOC ............. update_moc.ps1 puts the note in the domain's index
```

The parts that are easy to get wrong:

**Routing** (`vault/routing.py`) is deterministic keyword scoring, not a model
call. Weighted signals — domain name 4.0, category 3.0, theme 2.5, entity 1.5,
description 1.0 — with a `MIN_SCORE` of 2.5 and a `MIN_MARGIN` of 1.0 over the
runner-up. Below either threshold it refuses to guess and escalates to the user.
Its vocabulary is derived from the tags on the vault's own notes, so routing
sharpens as the vault grows. It is self-maintaining by construction.

**Sections** retry exactly once on exception or empty output, then record the
failure and continue. **Python writes the chunk files, not the model:** the
model returns text and `sections.py` writes `_tmp/[slug]_chunk_NN.md`.

**Assembly** gates on every chunk being present before anything is assembled,
and deletes `_tmp` only once the finished note is confirmed on disk. A cancelled
run deliberately leaves `_tmp` intact so `/resume` can pick it back up.

**Word count** warns and never blocks. A short note on disk, marked short, is
more useful than no note.

**Tagging** is the strictest gate in the pipeline, because it decides whether the
note joins the graph or sits outside it. Three attempts, each fed the previous
validation errors. If the vault has no `validate_tags` tool, the tagger is
trusted and the event says so explicitly.

---

## 4. The cast: subagents

An agent is a Markdown file in `<vault>/.agents/agents/<name>.md`: YAML
frontmatter, then a body that becomes the system prompt verbatim.

```markdown
---
name: haytham              # must equal the filename stem
description: Science and mathematics specialist
type: content              # content | pipeline | audit
domain: science            # required for content; must exist in taxonomy.json
invocation: /agent haytham # optional
mcp: [zotero]              # optional: MCP servers this agent may reach
---

You are a historian of science writing for a reader who knows the mathematics
but not the historiography. Claims about priority need a date and a manuscript.
Never smooth over a disputed attribution...
```

`AgentDef.from_file` validates on load: frontmatter must exist and be closed,
`name` must match the filename, content agents must declare a domain, pipeline
agents must declare a stage. `Vault._cross_validate` then checks every content
agent's domain against `taxonomy.json`. A malformed agent fails at vault load,
not mid-run.

### The three types

**`content`** — domain specialists, one per domain. The body is the system
prompt for pre-flight and for every section of every note routed to that domain.
Subject-matter voice, evidentiary standards and the assumed reader all live
here. This is the agent that does the actual writing.

**`pipeline`** — stage workers, invoked by name at a fixed point in the run:

| Agent | Stage | Job |
| --- | --- | --- |
| `weaver` | assembly | Sees all chunks; writes transitions, frontmatter, separators |
| `tagger` | tagging | Proposes a tag line for validation against the taxonomy |
| `formatter` | tagging | Applies the declared template's structure |
| `linker` | linking | Inserts `[[wikilinks]]` where the argument touches other notes |

Every one of them is optional. A vault without a `weaver` gets raw chunk text; a
vault without a `linker` gets an unlinked note. The stage says so in an event.

**`audit`** — read-only inspectors. They report; they do not mutate the note.

### Extending the cast

Adding a specialist is: write the Markdown file, add its domain to
`taxonomy.json`, done. No Python change, no registration, no restart hook. That
is the extensibility story, and it should stay this cheap.

---

## 5. Tools and MCP

### Three sources, one registry

`ToolRegistry` is the single lookup surface. Precedence on a name collision is
`BUILTIN > VAULT_PS1 > MCP`; the loser is not dropped but re-registered under a
`{source}__{name}` alias, so a vendored MCP tool can never silently shadow a
vault tool the pipeline depends on.

| Source | What it is |
| --- | --- |
| `BUILTIN` | Ships with the harness |
| `VAULT_PS1` | PowerShell scripts in `<vault>/.agents/tools/`, contract-token emitters |
| `MCP` | Anything a configured MCP server exposes |

`ToolRegistry.spec_for_model()` is the **only** path from the registry to a
provider. Pipeline-only tools (`cleanup_chunks`, `update_moc`) are excluded from
it and can therefore never be selected by a model — the pipeline calls them
directly, by name, at the point where they are correct.

### MCP is how Avicenna reaches past the vault

Full schema and transport support — python, node and executable transports, the
Windows `npx.cmd` fallback, `AsyncExitStack` teardown — and **zero servers
configured by default**. Servers are declared in `<vault>/.agents/mcp.json`, and
an agent opts into them through its `mcp:` frontmatter key.

This is the extension point for everything the harness deliberately does not do
itself: reference managers, search, a PDF corpus, a citation store. A section
being written on the necessity of revelation can, through MCP, pull the actual
passage out of a Zotero library instead of reconstructing it from memory.

The boundary: **MCP extends what a section can know. It does not extend what
Avicenna is.** A server that makes notes better sourced belongs here. A server
that turns the harness into a general agent does not.

### Contract tokens

A vault tool prints a token line that the pipeline parses:

```
MANIFEST_WRITTEN chunks=11
ALL_PRESENT
WORDCOUNT_FAIL short=420
PASS
```

`tools/contracts.py` parses; `pipeline/stages.py` branches. Nothing branches on
prose. See §2.3.

---

## 6. Repository architecture

Two processes, one pipe.

```
  tui/  (TypeScript)                    avicenna/  (Python)
  +--------------------+   NDJSON      +---------------------+
  | renderer, input,   |  over stdio   | bridge, pipeline,   |
  | transcript         | <===========> | providers, tools,   |
  |                    |               | MCP, vault          |
  +--------------------+               +---------------------+
```

The frontend owns everything you see and nothing you run. The backend owns
everything it runs and nothing you see. This follows from §2.6: the pipeline
already knew nothing about a terminal, so the terminal was free to leave the
process. It buys a UI toolkit chosen on its merits rather than on whatever pip
offers, and it makes the boundary testable — the entire backend can be driven
from `echo`.

### The wire

One JSON object per line, in both directions:

```
frontend -> backend   {"type":"req","id":"7","method":"run.note","params":{}}
backend  -> frontend  {"type":"res","id":"7","ok":true,"result":{}}
                      {"type":"event","event":"SectionCompleted","data":{}}
```

Two invariants hold it together:

- **stdout belongs to the protocol.** The core prints to stdout in several
  places (rich consoles in `config.py`, typer echoes). One stray line desyncs
  the frontend's parser, so `sys.stdout` is redirected to stderr for the process
  lifetime and frames go to a private handle.
- **A request never blocks the event stream.** Long work is dispatched to a task
  and answered immediately with an id; progress arrives as events. CI enforces
  this by rejecting `subprocess.run`, `time.sleep` and `requests.` anywhere
  under `avicenna/bridge/`.

### Adding an event

1. Add the frozen dataclass to `avicenna/events.py`. The bridge serialises
   structurally, so no bridge change is needed.
2. Add its name to `EventName` in `tui/src/protocol.ts`.
3. Handle it in the frontend's event translator.

### Provider layer

Mistral is primary. Gemini is quarantined behind the stateless provider ABC in
`avicenna/providers/base.py` and is not shipped. **No module outside
`avicenna/providers/` imports a vendor SDK**, and importing `avicenna.providers`
must not drag one into `sys.modules` — provider imports live behind the
registry, at the edge. Google Workspace/OAuth is cut, parked on branch
`archive/google-workspace` and tag `v1-pre-harness`.

---

## 7. Conventions

| Concern | Canonical | Not |
| --- | --- | --- |
| Neutral provider types + ABC | `avicenna/providers/base.py` | `providers/types.py` |
| Tool-call events | `ToolInvoked` / `ToolReturned` | `ToolCallStarted` / `ToolCallFinished` |
| Tool package | `avicenna/tools/` (a package) | `avicenna/tools.py` (a module) |
| Tool-runner protocol | `avicenna/tools/runner.py`, as `ToolRegistry.runner` | `vault.tools.run` |
| CLI | `avicenna/cli/` package, entry `avicenna/cli/app.py::main` | `avicenna/cli.py` |
| MCP neutral schema export | `MCPClientManager.tool_specs()` | `get_tool_specs()` |
| Dependency manifest | `pyproject.toml` only | `requirements.txt` |
| Repo doctrine + dev doc | `AGENTS.md` (repo root) | `AVICENNA.md` (now a pointer) |
| Claude Code working file | `CLAUDE.md` (repo root) | — |
| Frontend | `tui/` (TypeScript, its own toolchain) | any Python UI package |
| Wire protocol | `avicenna/bridge/protocol.py` + `tui/src/protocol.ts` | ad-hoc JSON at call sites |
| Chat controller | `avicenna/chat.py` | inside the frontend |
| Onboarding logic | `avicenna/auth.py` (frontend owns only the screens) | inside the frontend |
| Vault protocol file | `AGENTS.md` (vault root) | never rename to `AVICENNA.md` |

**Style:**

- Python 3.10+, `from __future__ import annotations` at the top of every module.
- Fully type-annotated. `mypy --strict` clean for `avicenna/pipeline` and
  `avicenna/providers`.
- All file writes UTF-8 **without BOM**, LF line endings.
- TypeScript `strict`, including `noUncheckedIndexedAccess`.
- No Python module imports a UI toolkit; no TypeScript module reaches past the
  bridge protocol.
- No module outside `tests/` contains the literal string `De Anima`.
- `requirements.txt` stays deleted.

---

## 8. The vault contract

```
my-vault/
+- AGENTS.md                  # the orchestrator protocol — required
+- .agents/                   # required
|  +- agents/<name>.md        # agent definitions
|  +- skills/<name>/SKILL.md  # named procedures
|  +- tools/*.ps1             # contract-token emitters
|  +- taxonomy.json           # domains, categories, types, themes — the closed vocabulary
|  \- mcp.json                # MCP servers (ships empty)
+- _tmp/                      # chunks, manifest, pipeline state; gitignored
\- <Domain>/                  # Title Case folders, created on first write
```

Discovery order (`vault/discovery.py`), highest precedence first: `--vault`,
then `AVICENNA_VAULT`, then a walk up from cwd looking for `AGENTS.md` plus
`.agents/`, then `default_vault` in `~/.avicenna/user_config.json`.

A wrong `--vault` is an error, not a fallback. Being pointed at one vault and
silently writing into another is the worst failure this program has.

---

## 9. Boundaries

Deliberately absent. Adding any of these is a change of program, not a feature:

- **Conversation memory across notes.** Each run is stateless by design.
- **A shared session across sections.** See §2.1. This one is load-bearing.
- **Model-decided control flow.** See §2.3.
- **Arbitrary shell.** Tools are declared, contracted and registered.
- **Writing outside the vault.** The vault is the entire write surface.
- **Free-form tag invention.** The taxonomy is closed; that is what keeps the
  graph navigable.
- **A general chat mode.** `/agent` is a diagnostic, not a product.

---

## 10. Working on this repository

```bash
# backend
pip install -e ".[dev]"
pytest -q
mypy --strict avicenna/providers avicenna/pipeline

# frontend
cd tui
npm ci
npm run typecheck
npm run build
npm test

# drive the backend by hand — the boundary is testable without a terminal
echo '{"type":"req","id":"1","method":"vault.info","params":{}}' | python -m avicenna.bridge
```

Before finishing a change, ask the question this whole document is built around:
**does this make the next note better connected to the rest of the user's
thinking?** If it does not, it does not belong here.
