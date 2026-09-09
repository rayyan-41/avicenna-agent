# The conversational terminal interface — design

Status: **partial**. Section 1 (architecture and runtime) approved 2026-09-09.
Sections 2–4 are not yet designed; the decisions they must honour are recorded
below so a cold session can resume without re-litigating them.

Supersedes part of [2026-09-07-terminal-interface-design.md](2026-09-07-terminal-interface-design.md).
That document is still the authority on the *run* surface — the outline as the
progress display, progress-versus-decisions, and the three failure modes. What
it settled about the *input* surface is reversed here, deliberately, and §1 of
this document says why.

## The reversal, stated plainly

The 2026-09-07 spec says:

> So there is no chat. The input is a topic, not a message. The interface never
> asks the user to make a decision the harness should make.

The user's instruction on 2026-09-09 is the opposite: Avicenna doubles as a
chatbot, using the same API keys and the same vault agents, and a generation run
begins from inside that conversation.

This is a reversal, not a clarification, and it is worth being honest about
which part of the old argument survives.

**What survives.** The reasoning against a chat surface was that conversation is
what this program is not, and that a chat pane invites the user to treat a
scribe as an assistant. That risk is real and unchanged. The mitigation is that
chat cannot write: `avicenna/chat.py` already restricts a chat turn to
`read_note`, `search_vault`, `list_notes`, `get_related_notes` and
`validate_tags`, and the module's own docstring records that this allowlist
lives in the core rather than the frontend precisely because it is a safety
boundary rather than a presentation detail. A conversation can look at the
vault. It can never change it. Only the pipeline writes.

**What does not survive.** "The interface never asks the user to make a decision
the harness should make" was written to argue against blocking on a minted
theme, and that argument still holds — a new theme is reported, never held for
approval. It does not extend to the generation plan. The plan is the one
decision that is genuinely the user's, the pipeline already emits
`PlanApprovalRequested` for it, and `bridge/server.py` currently auto-approves
with a comment conceding that a real approve/decline path was deferred rather
than rejected. Building it is completing that stub, not violating the principle.

**What the prime directive becomes.** `CLAUDE.md` opens "Do not turn Avicenna
into a chatbot." That sentence has to change, and the change should be recorded
rather than drifted into: Avicenna has a conversational surface, but the
deliverable is still a connected note, and chat is a read-only instrument
pointed at the vault. The test for a new feature is unchanged — does it make the
next note better connected — and a conversation that helps the user find the
note they actually want passes it.

## What was already built

Five findings from reading the tree on 2026-09-09, each of which changed the
shape of this design.

1. **The chat backend exists.** `avicenna/chat.py` (109 lines) provides
   `AgentChatController`: one `AgentChat` per vault agent, history, turn and
   token accounting, a per-agent `asyncio.Lock` (added after two concurrent
   sends interleaved their appends into one history list), and the read-only
   tool allowlist above. `chat.select`, `chat.send` and `chat.clear` are already
   bridge methods. This is a frontend job, not a backend one.

2. **OpenTUI does not require Zig.** Cline's `DEVELOPMENT.md` says it does
   because Cline pins `@opentui/core` 0.4.3. Current is 0.5.11 and publishes
   prebuilt native binaries as optional dependencies, including
   `@opentui/core-win32-x64`. Verified by installing it: 20 packages, seven
   seconds, no compiler.

3. **OpenTUI does require Bun.** Its engine field is `bun >=1.3.0 || node
   >=26.4.0`. This machine has Bun 1.4.0 and Node 24.12, so npm installs with an
   `EBADENGINE` warning. Verified that it loads and resolves under Bun on
   Windows: 279 exports, `createCliRenderer` present, plus `ImageRenderable`,
   `MarkdownRenderable`, `DiffRenderable` and `CodeRenderable`.

4. **Four generation arguments reach the wire.** `run.note` accepts `topic`,
   `resume`, `dryRun`, `domain` and `concurrency`. Not exposed: words per
   heading, template override, agent override, provider, model.

5. **Nothing streams.** `chat.send` is request/response, and `LLMProvider` has
   no streaming method at all. Chat replies arrive whole.

## Decisions taken

Each of these was put to the user and answered. They are inputs to sections 2–4,
not open questions.

| | Decision | Consequence |
| --- | --- | --- |
| Launch surface | Chat first; generation happens from within it | One view, no mode picker |
| Intent | Deterministic verb patterns, then a confirm step | No model in the control path |
| Generation arguments | Settings panel for defaults **and** plan review for per-run override | Both surfaces get built |
| Face animation | Eye tracking when idle **and** state animation during a run | Both behaviours |
| Chat identity | A built-in general persona, overridable by a vault file | Chat works in a vault with no agents |
| Chat → run context | A toggle at the confirm step, default on, feeding pre-flight only | Section agents keep fresh context |
| Runtime | Full rewrite of `tui/` on Bun and OpenTUI | Nothing is ported |
| Sequencing | Spine first: shell → chat → controls → face | Four usable stages |
| Settings scope | Generation values, provider/model, **and** API keys | Auth moves into the panel |
| Face placement | Persistent; large when idle, small above the status bar while running | State animation is visible during a run |
| Run in transcript | An entry that expands while running and collapses to a summary | History records notes as well as conversations |
| Streaming | Deferred, recorded as the next piece of work | Spine ships with block replies |

Two of these deserve their reasoning kept.

**Chat context reaches pre-flight and stops there.** AGENTS.md §2.1 is that a
section is written in a fresh context, and that this is the reason a 10k-word
note holds quality across every heading. A growing conversational preamble in
front of every section call is exactly the degradation that rule exists to
prevent. Pre-flight is different: it declares structure once, it is the one
stage where knowing what the user has been circling genuinely improves the
output, and it is a single call. So the transcript reaches the planner and
nothing downstream.

**The persona is built in but overridable.** Every agent today is a Markdown
file in the vault, and `avicenna init` scaffolds only `scribe.md`. A
vault-file-only persona means chat is broken in every vault that exists right
now until a migration runs. A harness-only persona means the voice is ours and
the user cannot change it without editing the repo, which sits badly beside the
vault-sovereignty rule. Shipping a default that a vault file overrides costs one
lookup and satisfies both.

## Section 1 — architecture and runtime (approved)

### Processes

Three, unchanged in shape. `avicenna` (Python, Typer) spawns the frontend; the
frontend spawns `python -m avicenna.bridge` as its own child and speaks NDJSON
over its stdio. What changes is the middle process: Node and npm become Bun.
`_find_node()` in `cli/app.py` becomes `_find_bun()`, keeping the same
shape — an `AVICENNA_BUN` environment override, a PATH lookup, and an error that
tells the user how to install it and how to run headless instead.

### The rewrite

`tui/` is rebuilt from scratch. No file is ported. Two behaviours of the current
`bridge.ts` must nonetheless be preserved, because they were learned rather than
designed and rediscovering them costs a day:

- a stdout chunk may split a JSON line, so the reader buffers partial lines
  across chunk boundaries;
- a non-JSON line on stdout is a fatal desync, not a line to skip — this is the
  frontend half of the rule that stdout belongs to the wire protocol.

Both go into the new client with the reasoning recorded in comments, per the
house style.

```
tui/
  package.json          bun · @opentui/core · @opentui/react · react 19
  src/
    index.tsx           entry: args, signals, createCliRenderer, root
    bridge/
      client.ts         NDJSON framing over the bridge child
      protocol.ts       EventName union · Stage list · method signatures
      translate.ts      typed event → TranscriptEntry
    state/
      transcript.tsx    entries, append, updateLast
      run.tsx           active run: stages, sections, plan
      config.tsx        vault info, settings, provider
    views/
      chat.tsx          the single surface
      onboarding.tsx    first run
    components/
      face.tsx          + face-frames.generated.json
      transcript.tsx  entry.tsx  run-entry.tsx
      composer.tsx  status-bar.tsx
      confirm-run.tsx  plan-review.tsx  settings.tsx
```

### Intent detection lives in Python

A new pure module, `avicenna/intent.py`, in the same shape as `linking.py` and
`tagging.py`: no I/O, no `RunContext`, no provider, unit-tested by pytest. The
frontend never decides control flow. It calls one method and renders the answer:

```
chat.submit {text}
   → {kind:"chat",    agent, text, turns, tokens}   backend already answered
   → {kind:"propose", topic, domain, matched}       backend did nothing
```

On `propose` the frontend shows the confirm dialog. Only on acceptance does it
call `run.note`. This keeps classification testable, shared with the CLI, and
out of the model's hands — which is what makes it compatible with AGENTS.md §2.3
rather than an exception to it.

### Wire protocol additions

| Method | Status |
| --- | --- |
| `chat.submit` | new — classify, then chat or propose |
| `run.note` | gains `wordsPerHeading`, `template`, `agent`, `chatContext` |
| `run.approve` | new — `{runId, approved, overrides}`; replaces the `_auto_approve` stub |
| `config.get` / `config.set` | new — vault config and `~/.avicenna/config.json` |
| `providers.list` | new — providers, models, and which is active |
| `PlanApprovalRequested` | existing event, finally rendered |

`run.approve` completes the deferral recorded in `bridge/server.py`. The
approval gate in `run.py` already sets concurrency to the heading count when a
human approves, and that behaviour is preserved rather than reimplemented.

### Doctrine amendments

- `CLAUDE.md`: the "do not turn Avicenna into a chatbot" paragraph is rewritten
  as described above — a conversational surface exists, it is read-only, and the
  deliverable is still a connected note.
- `AGENTS.md` §2.3 gains a sentence recording that intent routing is
  deterministic pattern matching *because* letting a model decide whether the
  pipeline runs would be the violation.

### Deletions

All of `tui/src/{screen,ansi,keys,text,app,main,composer,commands,protocol,bridge}.ts`
— 2,861 lines. The `Frontend stays unstyled` CI lint goes with them: it exists
to stop a design being reintroduced by accident, and this work is the design
being introduced on purpose. Removing it is correct; leaving a gate that cannot
fail would be documentation rather than a gate.

## Still to be designed

**Section 2 — behaviour.** The trigger-verb list and how a near-miss is handled;
the confirm dialog and its context toggle; the plan-review screen and which
fields are editable; the settings panel, including how API key entry avoids the
transcript and the log; `/agent` and the other slash commands; what the
onboarding flow becomes.

**Section 3 — the face.** How `avicenna.png` becomes terminal cells; where the
frame data is generated and by what (a committed generator script, not just
committed output, which is where Cline's approach falls short); the eye regions,
which have to be synthesised because the source has no separate pupils; the
state animation vocabulary; the large-to-small transition.

**Section 4 — testing, sequencing and risk.** What replaces the current 29
frontend tests under Bun; whether a TUI snapshot tier is worth it; the CI job
rewrite; the four build stages and what "done" means for each.

## Open items

**Three of the six events the 2026-09-07 spec required still do not exist.**
That spec's sequencing said to build the interface only after the event
vocabulary closed. Current state, against its list:

| Required event | Status |
| --- | --- |
| Routing rationale — runner-up and margin | **missing** |
| Typed link-resolution result | **partial** — `NotesLinked` covers the linking stage; `_resolve_wikilinks` still reports through `LogMessage` |
| Near-miss on a mint | done — `SemanticGuardDecision` |
| Registry totals | **missing** |
| Resume availability | **missing** |
| Mechanical tag assignment | done — `TagsAssignedMechanically` |

Whether the spine waits for the three missing events, or ships and adds them,
is a section 4 decision. The argument for adding them first is unchanged and
still good: an event is cheapest to add while the stage that would emit it is
open, and rendering an incomplete vocabulary means rework.

**The pipeline has still never been run end to end since the heading-length and
linking changes.** The 2026-09-07 spec's first sequencing step was to verify the
pipeline with a live run, twice. That has not happened; the user deferred it on
2026-09-09. Building a frontend for a pipeline whose recent changes are unproven
is the risk that document warned about in its own words.

**Streaming.** Deferred by decision, but the deferral has a cost that will be
felt immediately: every chat reply arrives whole after a silent pause. The face
animation is what covers that pause, which makes section 3 load-bearing rather
than decorative.

**Bun on CI.** The frontend job runs on `ubuntu-latest` with `npm ci`. It
becomes a Bun job. The Python job stays on `windows-latest` because the vault
tools shell out to PowerShell.

## Sequencing

Spine first, four stages, each usable on its own:

1. **Shell.** Bun and OpenTUI, the bridge client, the transcript, and a real run
   rendered from real events. Gates green.
2. **Chat.** The general persona, `chat.submit`, intent detection, the confirm
   dialog.
3. **Controls.** Plan review, `run.approve`, the settings panel.
4. **Face.** Render first, animate second.

Implementation of stage 1 does not begin until sections 2–4 are designed and
this document is approved in full.
