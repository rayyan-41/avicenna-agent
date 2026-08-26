# CLAUDE.md

Working instructions for Claude Code in the `avicenna-agent` repository.

**Read [AGENTS.md](AGENTS.md) first.** It is the canonical document: the purpose,
the doctrine, the architecture and the conventions. This file does not repeat
it — it is the short operational layer on top, plus the things that are easy to
get wrong from inside an editor.

---

## What you are working on, in one paragraph

Avicenna is an academic scribe. A user gives it a raw, half-formed idea — *the
epistemic gap and the necessity of revelation*, say — and it returns a
long-form Markdown note in their Obsidian vault: structure declared up front,
every heading written in a fresh context by a domain-specialist subagent, woven
into continuous prose, tagged from a closed taxonomy, wikilinked into the notes
the user already has, and entered into the domain's Map of Content. It is a
harness for subagents and MCP tools, not a chatbot, and the point of the whole
program is the *connection*: a brilliant note that links to nothing is a
failure.

---

## The prime directive

**Do not turn Avicenna into a chatbot.** Every change should be checked against
one question: does this make the next note better connected to the rest of the
user's thinking? Features that make it a better general assistant, and worse at
that, are regressions no matter how well implemented.

Three specific temptations, all of which look like optimisations and are not:

1. **Sharing one session across sections.** Sections use `one_shot()` with a
   fresh context each, deliberately (AGENTS.md §2.1). This descends from the
   project's origin — a Gemini CLI script that spawned a *separate headless
   process per heading* — and it is the reason a 10k-word note can hold ~1k
   words per heading at constant quality. The session transcript is a log, not
   a conversation history: nothing in it is replayed to the model. A shared
   session degrades every section after roughly the third. Never "optimise"
   this.
2. **Letting the model decide control flow.** Stages branch on regex-parsed
   contract tokens, never on the model's account of whether a step worked
   (§2.3).
3. **Widening the write surface.** The vault is the entire write surface, the
   taxonomy is closed, and tools are declared rather than arbitrary (§9).

---

## Where things live

| You want to change | Go to |
| --- | --- |
| Run orchestration, cancellation, dry-run | `avicenna/pipeline/run.py` |
| A pipeline stage | `avicenna/pipeline/stages.py` |
| Resume state (manifest + last-run pointer) | `avicenna/pipeline/resume.py` |
| Parallel section generation | `avicenna/pipeline/sections.py` |
| Subagent invocation | `avicenna/pipeline/delegate.py` (it is `one_shot` + a system prompt) |
| Which agent a topic routes to | `avicenna/vault/routing.py` |
| Vault loading, agent/taxonomy validation | `avicenna/vault/vault.py`, `vault/models.py` |
| What `avicenna init` scaffolds | `avicenna/vault/init_scaffold.py` |
| Tool lookup, precedence, model-visible specs | `avicenna/tools/registry.py` |
| Contract-token parsing | `avicenna/tools/contracts.py` |
| MCP transports and schema export | `avicenna/mcp/mcp_client.py` |
| The event taxonomy | `avicenna/events.py` |
| The wire protocol | `avicenna/bridge/protocol.py` + `tui/src/protocol.ts` |
| CLI commands | `avicenna/cli/app.py` |
| The terminal frontend | `tui/src/` (TypeScript, its own toolchain) |

---

## Frontend status: the UI is intentionally a skeleton

`tui/` has been stripped back to the plumbing on purpose. What remains is the
mechanism — process bridge, wire protocol, alt-screen differential renderer, raw
key decoding, display-width measurement, the edit buffer, the command catalogue,
and an unstyled event translator that turns pipeline events into plain lines.

There is currently **no visual design**: no palette, no glyph set, no wordmark,
no boxes, no overlays, no Markdown styling. That is not an oversight or an
unfinished migration — the aesthetic is being redesigned from scratch.

So: do not reintroduce styling, colour systems, banners, panels or box-drawing
into `tui/src/` unless the user explicitly asks for a design pass. When they do,
build it as a new layer on top of the skeleton rather than by restoring what was
removed. See `tui/README.md` for the module map and the seams a design is meant
to attach to.

---

## Commands

```bash
# backend
pip install -e ".[dev]"
pytest -q
mypy --strict avicenna/providers avicenna/pipeline   # must be clean
python scripts/check_protocol_parity.py              # events.py vs protocol.ts

# frontend
cd tui && npm ci && npm run typecheck && npm run build && npm test

# drive the backend without a terminal
echo '{"type":"req","id":"1","method":"vault.info","params":{}}' | python -m avicenna.bridge
```

CI runs the Python job on `windows-latest` (vault tools shell out to
PowerShell) and the TUI job on `ubuntu-latest`.

---

## Rules that bite

- **stdout belongs to the wire protocol.** One stray `print` reachable from the
  bridge desyncs the frontend's NDJSON parser. Diagnostics go to stderr.
- **Nothing under `avicenna/bridge/` may block.** `subprocess.run`,
  `time.sleep` and `requests.` are rejected by a CI lint; use the asyncio
  equivalents. A blocking call there freezes the interface.
- **No vendor SDK outside `avicenna/providers/`,** and importing
  `avicenna.providers` must not pull one into `sys.modules`.
- **`from __future__ import annotations`** at the top of every Python module;
  everything fully annotated.
- **UTF-8 without BOM, LF endings**, for every file write in the codebase and
  every file you write yourself.
- **The literal string `De Anima` appears nowhere outside `tests/`.**
- **`pyproject.toml` is the only dependency manifest.** Do not recreate
  `requirements.txt`.
- **Two files named `AGENTS.md`**: this repo's root (doctrine, for you) and the
  vault root (runtime orchestrator prompt, for the model). Do not conflate them.
- New events: dataclass in `avicenna/events.py`, name in `EventName` in
  `tui/src/protocol.ts`, then a case in the frontend translator. The bridge
  serialises structurally and needs no change. `scripts/check_protocol_parity.py`
  fails the build if you skip a step, and `App.onEvent`'s `never` check makes
  the compiler point at a missing case.
- **A stage has two identifiers.** `name` is the user-facing `Stage` label and
  may be shared (routing and pre-flight both read as "preflight"); `id` is its
  identity and must be unique, because timings, completion records and the
  dry-run filter key on it.
- **Only the pipeline writes to a note.** No model-callable tool can write, by
  design. An agent that revises a note returns the whole thing and a stage
  writes it back through `_write_back`, which rejects a suspicious truncation.
- **CI has no `continue-on-error`.** A check that cannot fail the build is
  documentation, not a gate. If something cannot be enforced yet, delete the
  step rather than leaving a check that lies.
- Tools the pipeline calls directly (`cleanup_chunks`, `update_moc`) must stay
  out of `spec_for_model()` so a model can never select them.
- Every vault tool call in a stage must degrade gracefully **and say so** when
  the tool is absent — a vault with zero PowerShell tools is legitimate.

---

## Style of work

Match the surrounding code: it is densely commented, and the comments explain
*why* a decision was made rather than what the line does. Several modules open
with a paragraph recording the defect that motivated the current design
(`vault/routing.py` is the clearest example). Keep that habit — when you fix
something subtle, leave the reasoning where the next reader will find it.
