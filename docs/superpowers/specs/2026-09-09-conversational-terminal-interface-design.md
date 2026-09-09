# The conversational terminal interface — design

Status: **complete, awaiting approval**. Section 1 (architecture and runtime)
was approved 2026-09-09. Sections 2 to 4 were drafted the same day, one agent
each, and are written down here for review — they have not been approved, and
no implementation begins until they are.

Where a number in sections 2 to 4 came from counting the tree it is stated as
fact; where it came from judgement it is marked as a proposal. That distinction
is deliberate and should survive editing.

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

`tui/` is rebuilt from scratch. No file is ported. Two things about the current
`bridge.ts` nonetheless carry into the new client, and they are not the same
kind of thing — an earlier draft of this section wrongly described both as
existing behaviour to preserve:

- **Preserved.** A stdout chunk may split a JSON line, so the reader buffers
  partial lines across chunk boundaries. `bridge.ts` does this today, it was
  learned rather than designed, and rediscovering it costs a day.
- **Corrected.** A non-JSON line on stdout should be a fatal desync rather than
  a line to skip — the frontend half of the rule that stdout belongs to the wire
  protocol. `bridge.ts` does **not** do this today: on a parse failure it calls
  `diagnose()` and continues. So this is a fix the rewrite must make, not a
  behaviour it must keep.

Both go into the new client with the reasoning recorded in comments, per the
house style, and the second carries a test asserting the frame is fatal.

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

## Section 2 — behaviour

### a. The trigger-verb list, and near-misses

Intent routing is deterministic pattern matching in `avicenna/intent.py`, a new
pure Python module shaped like `linking.py` and `tagging.py`: no I/O, no
`RunContext`, no provider, unit-tested by pytest. The frontend calls
`chat.submit {text}` and receives one of two shapes:

```json
{"kind": "chat",    "agent": "...", "text": "...", "turns": 1, "tokens": 420}
{"kind": "propose", "topic": "...", "domain": "...", "matched": "write a note"}
```

Classification happens server-side. The frontend never decides control flow — it
renders whatever the backend returns. This is what makes intent routing
compatible with AGENTS.md §2.3 rather than an exception to it.

#### The pattern list

Each pattern is an anchored regex, compiled once at module load. The shape is:

- **Anchoring.** Every pattern is anchored to the start of the message, with
  optional leading whitespace. A trigger verb buried in the middle of a sentence
  is not a trigger — it is a near-miss, and the distinction is the whole design.
- **Case.** Case-insensitive. "Write a Note" and "write a note" match the same
  pattern.
- **Topic extraction.** The remainder after the matched verb phrase is the topic.
  Leading whitespace and punctuation are stripped. An empty remainder (the user
  typed "write a note" and nothing else) returns `kind:"propose"` with an empty
  topic, and the confirm step prompts for one rather than sending a blank string
  to `run.note`.
- **Matched field.** The response includes the specific pattern that fired, so
  the confirm step can show "Matched: write about" and the user can see what the
  harness thought it heard.

The closed set, grouped by intent:

| Pattern | Captures topic from |
| --- | --- |
| `write(?: me)? a note(?: (?:on\|about))? (.+)` | the trailing noun phrase |
| `generate (?:me )?a note(?: (?:on\|about))? (.+)` | same |
| `create (?:me )?a note(?: (?:on\|about))? (.+)` | same |
| `write (?:on\|about) (.+)` | everything after "write about" or "write on" |
| `draft(?: me)? (?:a )?note (?:on\|about) (.+)` | topic after "draft a note on/about" |
| `draft(?: me)? (?:on\|about) (.+)` | topic after "draft about" or "draft on" |
| `draft(?: me)? (.+)` | bare topic after "draft" |
| `compose(?: me)? (?:a )?note (?:on\|about) (.+)` | topic after "compose a note on/about" |
| `compose(?: me)? (?:on\|about) (.+)` | topic after "compose about" or "compose on" |
| `compose(?: me)? (.+)` | bare topic after "compose" |
| `note (?:on\|about) (.+)` | the trailing noun phrase |

That is eleven patterns across eight verbs. Draft and compose each need three
patterns because a single regex cannot distinguish "draft a note" as a
structural phrase from "draft a note" where "note" is the start of the topic.
The three-way split handles this: the first pattern requires "note" to be
followed by a preposition ("on" or "about"), which makes "note" structural; the
second handles a bare preposition without "note"; the third handles a bare
topic. Pattern ordering matters: the specific "note" pattern is tried first so
"draft a note about Kant" matches the first pattern (topic: "Kant") rather than
the third (topic: "a note about Kant").

The write, generate, and create patterns do not need this split because they
require "a note" to be present in the verb phrase — a bare "write" without "a
note" is handled by the separate "write on/about" pattern.

Standard `re` module — no atomic groups or possessive quantifiers. The list is
closed: adding a new verb means editing `intent.py` and its test file, not
tuning a prompt.

The patterns are tested against the full input string, not against a
pre-processed token list, because the verb phrase matters to topic extraction —
"write about Kant" yields topic "Kant" only if the regex captures the
post-verb-phrase remainder. Verified against these inputs:

| Input | Pattern | Topic |
| --- | --- | --- |
| `write a note on Kant` | write...a note | `Kant` |
| `write a note about Kant` | write...a note | `Kant` |
| `write a note Kant` | write...a note | `Kant` |
| `write about Kant` | write on/about | `Kant` |
| `draft Kant` | draft | `Kant` |
| `draft a note about Kant` | draft...note | `Kant` |
| `compose Kant` | compose | `Kant` |
| `note on Kant` | note | `Kant` |
| `I was going to write about Kant but I got distracted.` | (none) | not classified |

#### Near-misses

A near-miss is a message that contains a trigger verb somewhere in the sentence
but does not start with one. Examples:

- "I was going to write about Kant but I got distracted."
- "Can you help me think about what to generate a note about?"
- "Someone should write a note on this."

These are chat, not proposals. The anchoring rule handles them: the trigger
verb does not appear at the start, so no pattern matches, and `chat.submit`
returns `kind:"chat"`. The user gets a chat reply.

The rejected alternative was treating a mid-sentence trigger as a proposal with
a lower confidence. This was rejected because the cost of a false positive is
high (an expensive generation run the user did not ask for) and the cost of a
false negative is low (the user repeats themselves more explicitly). The
asymmetry is decisive: **the design should err toward false negatives.** A user
who genuinely wants a note will say so at the start of a message. A user who
happens to use the word "write" in the middle of a sentence is, overwhelmingly,
not requesting a generation.

The second rejected alternative was offering an inline hint — "Did you mean to
generate a note?" — on a near-miss. This was rejected because it interrupts
every conversational use of the word "write" with a suggestion the user has to
dismiss, and the dismissal cost accumulates. A silent pass-through has no such
cost.

One edge case deserves a rule: a slash command that starts with `/` is never
classified by intent routing. It is dispatched by the command catalogue first.
This prevents `/agent write` from being misclassified as a note request.

**Where this pattern set knowingly departs from its own principle.** The bare
`draft (.+)` and `compose (.+)` patterns match anything following those verbs at
the start of a message. Tested: "draft an email to my boss" proposes a note on
"an email to my boss", and "compose a reply to this thread" proposes one on "a
reply to this thread". Both are false positives, in a design that has just
argued false positives are the expensive direction.

They are kept for two reasons. The bare form is the natural way to ask this
program for a note — "draft Kant" — and dropping it to protect against a use
that is not what Avicenna is for would cost the common case to defend the rare
one. And the confirm step means a false positive here costs one keystroke rather
than a run: nothing is generated until the user accepts the proposal.

That second reason is doing the real work, and it is worth stating plainly,
because it means the confirm step is not a convenience. **It is the safety
mechanism that lets the pattern set be permissive at all.** If a later change
ever makes generation start without confirmation, these two patterns must be
removed in the same change.

#### Failure modes

| Direction | What happens | Cost |
| --- | --- | --- |
| False positive | An expensive generation run starts for a message that was chat | User wastes tokens, sees an unsolicited plan, has to decline |
| False negative | A message the user intended as a note request is treated as chat | User has to rephrase, starting with the verb |

A false positive is worse because it is harder to undo (a run in progress
consumes tokens and emits events) and more confusing (the user sees a plan for
a note they did not request). The anchoring rule exists to prevent it.

---

### b. The confirm step and the context toggle

When `chat.submit` returns `kind:"propose"`, the frontend shows the confirm
dialog before calling `run.note`. This is the only decision point between
detection and generation.

#### What the dialog shows

The confirm dialog is a single-line composer overlay, not a full-screen modal.
It displays:

1. **The detected topic**, rendered in `leaf` so it reads as structure rather
   than as a chat message. If the user typed "write about Kant's moral
   philosophy", the topic shown is "Kant's moral philosophy".
2. **The matched pattern**, in `gloss`, as "Matched: write about". This is
   diagnostic — it tells the user what the harness heard, which is the minimum
   required for the user to understand a mis-classification.
3. **The context toggle**, rendered as a small labelled switch beside the topic.
   The label reads "include conversation", and the toggle defaults to on. When
   on, the conversation transcript so far is sent to the backend and fed to
   pre-flight only. When off, `run.note` receives no chat context.
4. **Three actions**: confirm (Enter), edit (a key or click that puts the topic
   into the composer for editing), and escape (Esc).

Default focus is on confirm. The user can accept immediately by pressing Enter.

#### What "edit" edits

Edit puts the topic string — and only the topic string — into the composer. The
user can rephrase, correct a mis-parsed topic, or add detail. The matched
pattern is not editable: if the topic is wrong, the user fixes the topic, not
the verb. Editing does not open a second screen; it replaces the confirm
overlay with the composer, pre-filled.

Editing the topic and pressing Enter re-enters the confirm flow. The harness
does not re-classify: the topic is whatever the user typed, and intent routing
has already done its job. The confirm step is a gate, not a loop.

#### What escape does

Esc dismisses the confirm dialog and returns to the chat surface. The message
the user typed is preserved in the composer's history (the user can recall it
with the up-arrow or equivalent). Nothing is sent to `run.note`. This is the
primary way a user says "I didn't mean that."

#### Why chat context stops at pre-flight

AGENTS.md §2.1 establishes that every heading is written in a fresh context,
and that this is the reason a 10,000-word note holds quality across every
heading. A section written by a model whose context includes the user's earlier
conversation about unrelated topics is a section whose attention budget is
partly spent on that conversation. The quality degrades monotonically: later
sections get shorter and vaguer, because the model's context is mostly its own
earlier output plus an unrelated chat history.

Pre-flight is the exception because it is a single call that declares structure.
Knowing what the user has been circling — "I keep coming back to Kant's
relationship with Hume" — genuinely improves the heading plan, because pre-flight
is the one stage where breadth of subject matter matters more than depth. The
transcript is included as a system-message annotation, not as a user turn, so
the model treats it as background rather than as an instruction to discuss the
conversation's topics.

This is why the toggle exists and why it defaults to on: the transcript helps
pre-flight and hurts everything downstream. A user who wants a note that has
nothing to do with the conversation turns the toggle off. A user who does not
think about it gets the better default.

The toggle is a per-run setting, not a global preference. Each confirm dialog
resets it to on. This is deliberate: the question of whether the conversation
is relevant is asked every time because the answer changes every time.

#### Does not exist today

The `chat.submit` method that combines classification and response does not
exist. Today `chat.send` handles the chat path and intent routing does not
exist at all. The confirm dialog is a new frontend component. The context
toggle is a new parameter on `run.note`. All three are additions, not
modifications.

---

### c. The plan-review screen

When `run.note` is called, the backend runs routing and pre-flight, then emits
`PlanApprovalRequested` and waits. Today it does not actually wait: the
`_auto_approve` stub in `bridge/server.py` returns `True` immediately, and the
comment at line 343 concedes this was deferred, not rejected. `run.approve`
completes that deferral.

#### What the screen shows

The plan-review screen receives `PlanApprovalRequested` as a wire event and
renders:

1. **Topic and domain**, in `leaf`, matching the confirm dialog's presentation.
2. **Template**, in `gloss`. If the pre-flight agent chose a template other
   than "general", it is shown here; otherwise the line is omitted.
3. **Headings**, as a numbered list. This is the primary content of the screen:
   the user is approving a structure, and the structure is the headings.
4. **Target word count**, in `gloss`, as "Target: N words". Derived from the
   heading count multiplied by the resolved words-per-heading.
5. **Concurrency**, in `gloss`, as "N sections in parallel". This is the value
   the approval gate sets — today it is `len(plan.headings)`, and that
   behaviour is preserved.

The screen is rendered as a scrollable list, not a modal. The user can scroll
through the headings with arrow keys or equivalent.

#### Editable fields

The plan-review screen is the per-run override surface. Decision 3 says
generation arguments are overridable here. The fields are:

| Field | Default | What it overrides |
| --- | --- | --- |
| Words per heading | from settings | `wordsPerHeading` on `run.note` |
| Template | from pre-flight | `template` on `run.note` |
| Agent | from routing | `agent` on `run.note` |
| Chat context | the toggle from the confirm step | `chatContext` on `run.note` |

Editing a field is inline: the user navigates to it and types. The headings
themselves are **not editable**. Re-editing the heading list would require
re-running pre-flight (the model declared the structure, and changing one
heading without changing the others could make the plan incoherent), and that
is a different feature. A user who wants different headings declines and
rephrases the topic.

#### What happens on approval

The frontend calls `run.approve {runId: "...", approved: true, overrides:
{...}}`. The backend receives it, resolves the approval gate callback in the
run context, and the pipeline continues.

The existing behaviour when a human approves is that concurrency is set to the
heading count — one API call per heading, all concurrent. This is safe because
a human has seen the number and approved it. The configured ceiling
(`MAX_CONCURRENCY_MAX`, 16) does not apply here; the real upper bound is
`parse_preflight`'s 40-heading refusal. This behaviour is in
`PreflightStage.run` at line 736 of `stages.py` and is preserved exactly.

When a plan is approved, `ctx.approved_concurrency` is set, and the sections
stage uses it instead of the configured concurrency. This is the existing
mechanism; `run.approve` only replaces the `_auto_approve` callback that feeds
it.

#### What happens on decline

The frontend calls `run.approve {runId: "...", approved: false}`. The backend
raises `PipelineAbort("preflight", "plan declined by user")`, which emits
`RunFailed` with `stage="preflight"`. The frontend returns to the chat surface.
No note is written, no chunks are created, and `_tmp` is not touched.

This matches the existing `note_cmd` decline path (line 258 of `app.py`):
decline is not an error, but `RunFailed` is the event, because the pipeline
protocol has no `RunDeclined` event and adding one for a single screen would
be a protocol change that buys the frontend nothing it cannot already derive
from `RunFailed.stage == "preflight"`.

#### Does not exist today

`run.approve` does not exist as a bridge method. `PlanApprovalRequested` exists
as an event but is consumed only by the auto-approve stub. The plan-review
screen is a new frontend component. The override fields are new parameters on
`run.note`.

---

### d. The settings panel

Decision 9 puts three things in the settings panel: generation values,
provider and model, and API keys.

#### Layered configuration, not a flat settings model

The layered-configuration spec (2026-09-06) splits settings by ownership:

- **Vault policy** lives in `.agents/config.json` inside the vault. These
  travel with the vault: word floors, routing weights, the no-MOC domain list.
- **User preferences** live in `~/.avicenna/user_config.json`. These describe
  the operator: provider, model, API keys, concurrency, timeouts.

The precedence chain is uniform: CLI flag, environment variable, scope file,
built-in default. The settings panel must respect that split. Each setting
shown in the panel carries an indication of which scope supplied its current
value — "vault" or "user" or "default" — so the user knows which file to edit
if they want the change to persist or to travel with the vault.

The panel does not flatten these scopes. A setting sourced from the vault
config is labelled differently from one sourced from user config, because
changing one changes a different file than changing the other, and a user who
does not know which file they are editing will edit the wrong one.

#### Generation values

These are the settings that control a run:

| Setting | Scope | Default | Source today |
| --- | --- | --- | --- |
| Words per heading | vault (global) or user | 1500 | `settings.py` `WORDS_PER_HEADING_DEFAULT` |
| Max concurrency | user | 6 | `settings.py` `MAX_CONCURRENCY_DEFAULT` |
| Provider timeout | user | 300s | `settings.py` `PROVIDER_TIMEOUT_DEFAULT` |
| Provider budget | user | 900s | `settings.py` `PROVIDER_BUDGET_DEFAULT` |
| Semantic guard threshold | vault | 0.80 | `settings.py` `SEMANTIC_GUARD_THRESHOLD_DEFAULT` |

Each is editable inline. The panel does not offer per-template overrides —
those live in `.agents/config.json` under `words_per_heading_overrides` and
are too specialised for a general settings screen.

#### Provider and model

The panel shows the active provider and model, sourced from
`user_config.json` with the standard precedence. `providers.list` (a new
bridge method) returns the available providers and their models, and which
is active. The user can switch provider and model here; the change persists
to `user_config.json`.

This does not today exist as a single resolution path. `build_provider` in
`auth.py` resolves the provider from the key pool and the model from an
env var or `user_config.json`, but there is no `providers.list` method on
the bridge and no way to change the model from the TUI. The settings panel
requires both.

**Pre-existing defect: `persist_key` resets provider and model.**
`auth.py`'s `persist_key` calls `cfg.update(onboarded=True,
provider=DEFAULT_PROVIDER, model=DEFAULT_MODEL, key_store=store)` on every
key save (line 75). This overwrites the user's provider and model choices
with the hardcoded defaults (`mistral`, `mistral-large-latest`) every time
they re-enter their API key. The layered-configuration spec (2026-09-06)
explicitly says "`persist_key` stops writing `provider` and `model`" — the
code has not been updated to match.

The settings panel is where a user would hit this: they change their model
to something other than the default, re-enter their API key (perhaps to
switch keys), and their model choice silently reverts. The panel's design
must account for this. The fix is in `auth.py` itself — `persist_key` should
record only `onboarded`, `key_store`, and optionally `default_vault`, leaving
`provider` and `model` untouched — but the panel must also not assume the fix
is in place. When the panel detects that `persist_key` would overwrite
`provider` or `model` (by comparing the current values against the defaults),
it should warn the user before submitting the key, or split the key-save
path into a call that writes only the key. **This is a backend fix, not a
frontend workaround**, but the panel cannot silently inherit the bug.

#### API key entry

This is the part that needs care.

**Existing storage path.** `secrets.py` stores keys in the OS keyring
(preferred) or in `user_config.json` under `api_keys` (fallback).
`auth.py`'s `validate_key` tests the key with one cheap completion. `persist_key`
writes it and marks the install as onboarded. The `redact` function in
`secrets.py` replaces anything matching `\b[A-Za-z0-9_\-]{24,}\b` with
`***REDACTED***`. This is the function that protects the wire log and stderr.

**The rule is absolute: an API key value is never printed in plaintext.** This
means:

1. **While typing.** The input field renders every character as `U+2022`
   (bullet). The raw key exists only in the edit buffer's memory. The
   character is never sent over the wire as part of a keystroke event — the
   frontend buffers locally and sends the completed key only when the user
   submits.

2. **Over the wire.** `auth.validate {key: "..."}` carries the key in the
   request payload. The backend's NDJSON log (which is stderr) is protected
   by `secrets.redact`, which is applied in the bridge's error handler. The
   request frame itself is a JSON line on stdout, which is the protocol
   channel and is never persisted by the frontend. The key appears in exactly
   one JSON object, travels once, and is never echoed back.

3. **After saving.** The settings panel shows the provider's status, not the
   key. A key that was validated and stored shows as "Configured" in `leaf`,
   with the storage location ("keyring" or "file") in `gloss` beside it. The
   key itself is never shown — not truncated, not fingerprinted, not
   partially masked. The existing `keys` CLI command shows fingerprints, but
   those are derived from the key hash and are not reversible. The panel
   could show the same fingerprint, but showing nothing is safer and costs
   the user nothing, because the panel is not the place to verify which key
   is active — `avicenna keys` is.

4. **On validation failure.** `auth.validate` returns `{ok: false, detail:
   "Key rejected. Check for a typo or an expired key."}`. The detail is
   human-readable and never includes the key. The panel shows the detail in
   `oxide` (the failure colour, per the palette) with a refusal mark. The key
   is not echoed back for "correction" — the user must retype it, which is the
   correct trade: a slightly slower retry against the guarantee that the wrong
   key never appeared on screen.

   **Glyph note.** The shared context's "three state glyphs only" rule
   (`U+2713`, `U+25B8`, `U+00B7`) governs the run display's stage tree — the
   progress surface where pending, running, and done must be distinguishable at
   a glance. Input masking and error marks are a different job and use different
   glyphs: `U+2022` (bullet) for masked password input, and `U+00D7`
   (multiplication sign) for validation refusal. Both are standard terminal
   glyphs for their respective purposes and do not conflict with the stage-tree
   rule, which was written for the run surface and does not exhaust the
   interface's glyph repertoire.

5. **The input flow.** The user enters the settings panel, navigates to the
   API key field, and types. On submit, the frontend calls `auth.validate`.
   If validation succeeds, the frontend calls `auth.persist`. The backend
   returns `{store: "keyring"}` or `{store: "file"}`. The panel shows the
   result. If validation fails, the panel shows the error and clears the
   input field — the failed key is not retained in the edit buffer.

This flow requires two new bridge methods that do not exist today: `config.get`,
`config.set`, and `providers.list`. `auth.validate` and `auth.persist` already
exist.

---

### e. Slash commands

#### The existing catalogue

`tui/src/commands.ts` defines 17 commands (16 visible, 1 hidden — `/exit` is
the only entry carrying `hidden: true`):

`/help`, `/note`, `/dry`, `/resume`, `/cancel`, `/agent`, `/agents`, `/route`,
`/vault`, `/tools`, `/mcp`, `/init`, `/login`, `/clear`, `/diagnostics`,
`/quit`, `/exit` (hidden).

#### What survives the rewrite

| Command | Status | Reason |
| --- | --- | --- |
| `/help` | survives | Always needed. Content changes to reflect the conversational surface. |
| `/note` | survives | Explicit generation bypasses intent detection. Useful when the topic starts with a word that looks like chat. |
| `/dry` | survives | Dry run is a development and debugging tool. |
| `/resume` | survives | Resume is an explicit action. |
| `/cancel` | survives | Cancel is an explicit action. |
| `/agent` | survives | Switches the chat persona. Named by the user. |
| `/agents` | survives | Lists agents. Diagnostic. |
| `/route` | survives | Shows routing explanation. Diagnostic. |
| `/vault` | survives | Shows bound vault. Diagnostic. |
| `/tools` | survives | Lists tools. Diagnostic. |
| `/mcp` | survives | Lists MCP servers. Diagnostic. |
| `/init` | survives | Scaffold a new vault. |
| `/clear` | survives | Clears the transcript. |
| `/quit` | survives | Exit. `/exit` stays hidden. |

#### What changes

| Command | Change |
| --- | --- |
| `/login` | **replaced** by `/settings`. The login flow moves into the settings panel, where it belongs alongside the other provider configuration. `/login` as a standalone command made sense when API key entry was the only configuration; with the settings panel it is an orphan. |
| `/diagnostics` | **survives but changes scope.** The backend stderr log is still accessible, but the settings panel now shows provider status, so `/diagnostics` becomes the overflow for things the panel does not surface: wire protocol stats, MCP transport errors, key pool state. |

#### What is added

| Command | Purpose |
| --- | --- |
| `/settings` | Opens the settings panel. This is the primary entry point for Decision 9. |
| `/resume` already exists | No new commands needed for the six subsections. |

#### The distinction between slash commands and trigger verbs

A slash command is an explicit instruction to the harness. It always starts
with `/`, it is dispatched by name, and it never involves the model. A trigger
verb is a natural-language request that is classified by deterministic pattern
matching and requires a confirm step before anything happens.

The rule: **if the user has to ask whether something is a command or a
proposal, the design has failed.** Slash commands are for the harness; trigger
verbs are for the note. A user who types `/note Kant` is issuing a command. A
user who types "write about Kant" is making a request that the harness
interprets. The distinction is the leading `/`.

One practical consequence: `/note <topic>` bypasses intent routing entirely. It
calls `run.note` directly, skipping the confirm dialog. This is intentional —
it is the escape hatch for a topic that starts with a word the trigger patterns
would misclassify, and it is the existing behaviour of the command.

---

### f. Onboarding

#### What happens today

`_tui_launch` in `app.py` sets `AVICENNA_FORCE_ONBOARD=1` when `--reconfigure`
is passed. The frontend reads this env var and shows an onboarding screen. The
frontend owns the screens; `auth.py` owns the decisions.

`auth_status()` returns `{configured, onboarded, provider, model, keyStore}`.
The frontend uses this to decide whether to show onboarding on first launch.

`init_vault` scaffolds: `AGENTS.md`, `.agents/taxonomy.json`,
`.agents/agents/scribe.md`, `.agents/mcp.json`, `_tmp/.gitignore`, and domain
and category directories derived from the taxonomy. The scaffolded vault has
one content agent (`scribe`, domain `general`) and no tools.

#### What the first run becomes

With a conversational surface, the first run has three parts: vault detection,
API key entry, and an optional first note. The order matters because each step
unlocks the next.

**Step 1: vault detection.** On first launch, the backend attempts vault
discovery. If no vault is found (`VaultContext.found == false`), the frontend
shows a prompt: "No vault found. Where should I create one?" The user provides
a path, or accepts the default (`~/avicenna-vault`). The frontend calls
`vault.init {path}`. This is `init_vault` today, scaffolded as described
above. The result is a working vault with one agent, one domain, and an empty
taxonomy.

If a vault is found, this step is skipped.

This is the one place where the conversational surface is not conversational:
vault creation is a one-time setup action, not a chat exchange. The prompt is
a setup screen, not a chat message, because the user cannot have a
conversation about their vault before it exists.

**Step 2: API key entry.** `auth_status()` returns `configured: false`. The
frontend shows the settings panel, focused on the API key field, with a brief
explanation: "Avicenna needs an API key to generate notes and chat." The user
enters the key. Validation and persistence follow the path described in
section 2.d. The panel shows the result.

If the key is already configured, this step is skipped.

**Step 3: optional first note.** After the key is validated, the frontend
enters the chat surface. A system message in `gloss` explains: "Avicenna
generates long-form notes from a topic. Try: write about [your topic]." This
is a hint, not a prompt — the user can ignore it and start chatting, or type
a trigger verb to generate their first note.

This step is optional. The user might want to chat first, configure MCP
servers, or inspect the vault. The hint is shown once and not repeated.

#### What is optional

- **Vault creation.** If the user already has a vault, they point at it with
  `--vault` or by `cd`-ing into it. The onboarding skips to step 2.
- **API key entry.** If the key is already configured via env var or a
  previous onboarding, the onboarding skips to step 3.
- **First note.** The hint is a suggestion, not a requirement. The user can
  dismiss it and use the chat surface normally.

#### What changes from today

Today onboarding is a multi-screen flow owned entirely by the frontend. With
the conversational surface, onboarding becomes a shorter sequence that leads
the user into the chat rather than into a separate mode. The settings panel
replaces the standalone API key screen. The vault creation prompt replaces the
frontend's scaffold flow. The first-note hint replaces the "ready" screen.

`--reconfigure` continues to force the full onboarding sequence, resetting the
settings panel to the API key field regardless of whether a key is already
stored. This is the existing behaviour of `AVICENNA_FORCE_ONBOARD=1` and is
preserved.

## Section 3 — the face

The face is the illuminated headpiece: it opens the page when idle and retreats
into the margin once there is text to gloss. It is also the only animated
element in the interface. There are no spinners, no progress bars, no pulsing
dots anywhere else. Every other piece of motion in the design is a state glyph
changing once (`U+2713` done, `U+25B8` running, `U+00B7` pending). The face is
the one orchestrated moment, and it is load-bearing: nothing in the codebase
streams, so every chat reply arrives whole after a silent pause, and the face is
what covers that pause. If the face fails to convey that the system is working,
the interface feels broken during every interaction.

### a. How the image becomes terminal cells

The source image (`avicenna.png`, 1024×1024, RGB) is effectively two-tone.
Verified measurements: 64.5% of pixels are pure `#000000`; a further 16.7% are
near-black values (such as `#000100`, `#010000`, `#000001`) spread across 385
distinct shades, each only ±1 in one or two channels from black. The cause of
this spread is not established — the file is PNG (lossless), so compression
artefacts are not the mechanism, and a colour-space round-trip or a lossy step
earlier in the image's history is equally consistent with the data. The
remaining 18.8% are a single green averaging `#0BB926`, with the ten most
common values all falling within `#0BB_26`–`#0CBD27`. There is no mid-tone, no
anti-aliased edge, no gradient. The near-black spread is irrelevant to the
design: the luminance threshold (step 3 below) classifies all of it as dark.
A luminance ramp (` .:;+*#@`) would therefore invent shading that is not in the
source: it would map the near-black spread to visible grey speckle and give the
face a texture it does not have.

**Half-block rendering with two colours is correct.** Each terminal cell
contains two vertical pixels from the resampled image. The mapping:

| Top pixel | Bottom pixel | Cell character | Foreground |
| --- | --- | --- | --- |
| lit | lit | `U+2588` (full block) | `phosphor` |
| lit | dark | `U+2580` (upper half block) | `phosphor` |
| dark | lit | `U+2584` (lower half block) | `phosphor` |
| dark | dark | `U+0020` (space) | n/a (ink ground shows through) |

The foreground is always `phosphor` (`#0BBA26`) or absent; the background is
always `ink` (`#000000`). No cell carries both foreground and background colour
because no cell straddles the silhouette boundary in a way that would require
it — the source has no anti-aliased edges.

**The pipeline, specified precisely:**

1. **Crop.** The content bounding box within the source is (204, 88, 788, 964)
   — verified as (202, 86, 789, 965) with a 2–3 pixel tolerance at the edges.
   This yields a content region of 584×876 pixels, a portrait aspect ratio of
   0.667. Rendering this region square (say, 34×34 cells) distorts the face: the
   jaw stretches, the forehead compresses. The aspect ratio must be preserved.

2. **Resample.** Resize the cropped region to the target cell width, with the
   height calculated to preserve aspect ratio and produce an even number of
   pixel rows (since two rows become one cell row):
   `rows = round(width × (876 / 584) / 2)`. The resampling filter is Lanczos
   (Lanczos3). Nearest-neighbour produces aliasing at small sizes; bilinear
   blurs the silhouette edge. Lanczos preserves the sharp boundary the source
   already has.

3. **Threshold.** A pixel is "lit" if its luminance exceeds 60 (Rec. 709
   coefficients: `0.2126R + 0.7152G + 0.0722B > 60`). This is a perceptual
   threshold, not a channel check: it correctly classifies the near-black spread
   as dark and the green silhouette as lit, without needing to know the palette
   in advance.

4. **Cell assignment.** For each column in each pair of rows, apply the table
   above. Empty columns (all cells in a column are spaces) are trimmed so the
   face pins to its column edge rather than floating with leading whitespace.

**Why half-blocks rather than a ramp.** A ramp maps luminance to glyph density,
which is the right tool for photographs and gradients. The source has neither.
It has exactly two values, and the ramp would spread them across10 or16 levels,
inventing detail that a viewer would then try to interpret. Half-blocks with
two colours give a lossless representation of a two-tone source at double the
vertical resolution of full-block-only rendering.

**Why the portrait aspect ratio matters.** The content box is 584 wide and 876
tall — a portrait aspect of 0.667. At34 cells wide, the face is34×26 cells. If
rendered as34×34 (square), the face would be stretched vertically by31%, turning
the oval head into an egg and the narrow jaw into a rectangle. The aspect ratio
is part of the face's identity; discarding it discards the silhouette.

**Degradation under reduced colour capability.**

- **256 colours.** The16 ANSI colours plus their bright variants map to256 via
  the6×6×6 colour cube. `#0BBA26` lands on cube index (0, 5, 2), which is
  `#00AF5F` — recognisably green, shifted toward teal. The face remains
  legible. The palette tokens `leaf`, `oxide` and `gloss` similarly land on
  their nearest cube neighbours; the design weakens but holds.

- **16 colours.** ANSI green (colour2) is the only candidate for `phosphor`.
  Its exact value varies by terminal theme — it may be `#00AA00`, `#00CD00`,
  or something else entirely. The face remains a recognisable green shape on
  black. The rest of the palette collapses: `page`, `gloss` and `leaf` all
  compete for the same yellow/brown slots, and `oxide` may land on the same
  red as an error glyph. The documented fallback is that speaker labels and
  rubricated words gain the only casing in the design (the shared context
  specifies this).

- **`NO_COLOR`.** The face renders as Unicode half-blocks with no colour escape
  sequences. Every cell is the terminal's default foreground on its default
  background. The silhouette is still visible — half-blocks give double
  vertical resolution — but it is monochrome and relies on the terminal's
  contrast ratio between foreground and background. On a light-theme terminal
  the face inverts (green-on-black becomes foreground-on-background, which may
  be dark-on-light). This is the expected cost of `NO_COLOR`; the design does
  not attempt to compensate.

### b. Where the frame data lives and what generates it

This is the part where a naive design goes wrong, and the failure mode of each
option is worth recording.

**The three options.**

1. **Commit only the generated output.** The frontend loads a JSON file
   containing pre-rendered frame data. No generator is checked in.

   *Failure mode.* When the source image changes — a new logo, a revised
   silhouette, a palette adjustment — the next person has a blob and no way to
   regenerate it. They must reverse-engineer the rendering pipeline from the
   spec and reimplement it. If the spec is ambiguous (and it will be, two years
   from now), they will produce a different result and not know whether the
   difference matters.

2. **Generate at build time in `tui/`.** A build step in `package.json` runs a
   script that reads `avicenna.png` and emits the JSON. The committed repo
   contains the generator and the source image; the built output is in
   `dist/` or similar.

   *Failure mode.* The frontend is TypeScript on Bun. Its only Python is the
   bridge subprocess; it has no image-processing library. Adding Sharp or
   `@napi-rs/image` as a build dependency for one file is disproportionate, and
   installing a native addon in CI adds a platform-specific compilation step
   that the current `tui/` job (ubuntu-latest, npm ci) does not have. More
   importantly, the generator needs to run on the developer's machine too —
   during design iteration, during palette changes, during testing — and
   requiring a full `tui/` build to regenerate a static asset couples two
   concerns that have no reason to share a lifecycle.

3. **Commit the generator script and its output, with a CI gate that fails if
   they disagree.** The generator is a Python script in `scripts/` that reads
   `avicenna.png` and writes the JSON. The JSON is committed alongside it. CI
   regenerates the JSON and compares it to the committed version; a diff fails
   the build.

   *Failure mode.* The generator needs Pillow, which is not currently a dev
   dependency. Adding it is one line in `pyproject.toml` under `[dev]`. If
   Pillow is absent, the gate fails — which is the correct behaviour: it means
   someone changed the image without regenerating, and the gate catches it.

**Recommendation: option 3.** It preserves reproducibility (the generator is
the source of truth), it keeps the frontend clean (TypeScript loads a JSON
file, no image processing), and it catches drift at the same point in CI that
catches every other form of drift.

**The generator script.** `scripts/generate_face_frames.py`. It reads
`avicenna.png` from the repository root, crops to the content bounding box,
resamples to each declared size, applies the threshold and half-block pipeline
from §3a, and writes the output. It takes no arguments; the sizes and
parameters are constants in the script, matching this spec. Running it
idempotently overwrites the output file. The script must declare
`from __future__ import annotations` at the top, per the repository convention.

**The output file.** `tui/src/components/face-frames.generated.json`. Section 1
of this spec names this path provisionally; it is accepted here. The file
contains:

```json
{
  "meta": {
    "source": "avicenna.png",
    "crop": [204, 88, 788, 964],
    "threshold": 60,
    "generator": "scripts/generate_face_frames.py"
  },
  "sizes": {
    "large": {
      "cellWidth": 34,
      "cellHeight": 26,
      "rows": ["██  ████...", "..."]
    },
    "small": {
      "cellWidth": 22,
      "cellHeight": 16,
      "rows": ["██  ████...", "..."]
    }
  }
}
```

Each row string contains the half-block characters (`U+2588`, `U+2580`,
`U+2584`, `U+0020`) for that row. The frontend applies `phosphor` as the
foreground colour to every non-space character. The `meta` block records the
parameters that produced the file, so a reader can verify the provenance
without reading the generator.

**The CI gate.** A new step in the `build` job, after the existing "No stray
prints" step. The `build` job is the correct home because it runs on
`windows-latest` and already executes `pip install -e ".[dev]"` (line 37 of
`ci.yml`), so Pillow is available once it is declared as a dev dependency. The
`hygiene` job is a bare checkout — it sets up Python 3.12 but never runs
`pip install`, and its own comment says "this job is a bare checkout." A gate
that imports Pillow would fail on its first run there.

```yaml
- name: Face frames are up to date
  run: python scripts/generate_face_frames.py --check
```

The `--check` flag regenerates the JSON to a temporary path and compares it
byte-for-byte to the committed file. If they differ, the script exits 1 and
prints the diff. The step runs in the `build` job alongside the other
source-file gates (protocol parity, MAP.md parity via `hygiene`, vendor
containment).

Pillow is not currently a dev dependency. `pyproject.toml` line 35 reads:
`dev = ["pytest", "pytest-asyncio", "mypy", "types-PyYAML"]`. Adding Pillow
requires a real change to that list: `"Pillow>=10.0"` appended. It is not a
runtime dependency; it is needed only by the generator and by the gate.

**Rejected alternative: a gate that checks only file hash.** A simpler gate
would hash the committed JSON and compare it to a hash stored in the script.
This fails when the JSON is regenerated with a different serialiser version or
whitespace convention. Byte-for-byte comparison of the regenerated output is
strict and unambiguous.

### c. The eyes

**There are no isolable pupils in the source.** Verified: scanning the eye band
(36%–55% of face height, y=402 to y=569 in the content region) for dark pixels
surrounded on all eight sides by green found zero candidates. The eye band row
analysis confirms the structure: the eyes are open notches in the green
silhouette, connected to the black background. At y=417–447 the pattern is
three green blocks (each ~37 source pixels wide) separated by two dark gaps
(~109 and ~146 pixels wide). The green blocks are the brow ridge and cheek; the
dark gaps are the eye sockets, open to the background. Lower in the band
(y=452–562), the pattern becomes more complex — the brow, nose bridge, and
cheekbone create ten transitions per row — but the eyes remain open notches,
never enclosed islands.

Eye tracking (decision 4) is therefore **synthesis drawn on top of the mask**,
not existing pixels moved. The design must specify where the synthetic pupils
sit, what they are made of, and how many gaze positions exist.

**Pupil placement.** Two synthetic pupil regions, one per eye, specified as
coordinates relative to the content bounding box so the placement survives a
change of render size. These centres are design proposals derived from the row
analysis of the eye band, not precise measurements — the eye sockets are
irregular shapes, and the "centre" is a judgement call about where a pupil
looks most natural:

- **Left eye.** The notch centre is proposed at approximately 38% across the
  content width and 44% down the content height. In the cell grid at 34 cells
  wide, this is cell column 13, row 11. At 22 cells wide, cell column 8,
  row 7.

- **Right eye.** The notch centre is proposed at approximately 65% across the
  content width and 44% down the content height. In the cell grid at 34 cells
  wide, this is cell column 22, row 11. At 22 cells wide, cell column 14,
  row 7.

These are the centre gaze positions. The pupils shift from here.

**What a pupil is made of.** The eye sockets are ink (black). The face
silhouette is phosphor (green). A pupil drawn in `phosphor` on `ink` is a dot —
a single green cell in a field of black. A pupil drawn in `ink` on `phosphor`
is a hole — a single black cell in a field of green. The eye sockets are ink,
so the pupils are phosphor dots: small green cells placed within the black
socket, creating the impression of an iris looking in a direction.

At the small render size (22 cells wide), each eye socket is approximately 3–4
cells wide. A single-cell pupil therefore occupies roughly one-third of the
socket width, which is proportionally correct for a gaze shift. At the large
size (34 cells wide), each socket is approximately 5–6 cells wide, and the
pupil is one cell — proportionally smaller, but the face is also farther from
the viewer's focal point (it occupies more of the screen).

**Gaze positions.** The proposal is five discrete positions, because continuous
tracking is not possible on a cell grid and because fewer than five produces a
mechanical oscillation rather than a natural glance. The number five and the
offset values are design choices, not measurements — they are chosen to give
the pupil a visible range of motion at both render sizes without exceeding the
socket boundaries:

| Position | Label | Pupil offset from centre | Appearance |
| --- | --- | --- | --- |
| 0 | far left | −2 cells | Looking at the edge of the terminal |
| 1 | left | −1 cell | Looking at the text block's left margin |
| 2 | centre | 0 cells | Looking at the viewer / forward |
| 3 | right | +1 cell | Looking at the margin gloss |
| 4 | far right | +2 cells | Looking at the terminal edge |

The offset is applied to both pupils simultaneously; cross-eyed states are not
used. At the small render size, positions 0 and 4 may place the pupil at the
edge of the socket or one cell beyond it; in that case the pupil clamps to the
socket boundary. This is acceptable — a gaze that hits the wall of the socket
reads as a sidelong glance.

**Mapping from caret to gaze.** When the interface is idle and the user is
typing, the caret's horizontal position in the composer maps to a gaze
position. The text block occupies roughly the left 60% of the terminal width;
the mapping divides that span into five bands, one per gaze position. The
mapping is recalculated on each caret move, not on a timer — the eyes snap to
the new position rather than tracking smoothly, because smooth animation
between cell positions would require fractional-cell rendering that
half-blocks do not support.

**When there is no caret to follow.** The eyes default to position 2 (centre).
During a run, when the face is in the margin and the user is not typing, the
eyes shift to position 1 (left) — looking toward the text block where the run
progress is unfolding. This is a fixed offset, not a tracking behaviour: the
eyes do not follow individual stage completions.

**During a run.** The eyes remain at position 1 (left, toward the text block)
for the duration of the run. State changes are conveyed by the animation
vocabulary (§3d), not by eye movement. Moving the eyes during state transitions
would create two competing signals.

**Blinking.** In scope. The proposed timing is every 4–6 seconds (randomised,
uniform distribution), with the pupils disappearing for 0.15 seconds — the eye
sockets return to solid ink. These numbers are design proposals, not measured
values; they are chosen to feel natural at typical terminal frame rates and
should be tuned during implementation. This is the only periodic animation in
the interface. The blink timer is
frontend-only (a `setInterval` in the face component); it does not involve the
backend or the event stream. Blinking is disabled when the terminal signals
reduced-motion preference: the implementation checks for the `NO_COLOR`
environment variable as a proxy for minimal terminal capability, and also for a
dedicated `AVICENNA_REDUCED_MOTION` variable. When either is set, the pupils
remain static. This is a graceful degradation — the face still works, it simply
does not blink.

**If eye tracking is not worth building.** The case against is that at 22 cells
wide, a single-cell pupil shift is a 3-pixel movement on a 1080p monitor —
barely perceptible, and possibly distracting if the user's eyes are on the text
block rather than the face. The case for is that the face is the interface's
one animated element and the eyes are what make it a presence rather than a
logo. Decision 4 specifies both eye tracking and state animation; this design
honours both. If implementation reveals that the small-form pupil shifts are
unreadable, the fallback is to restrict eye tracking to the large (idle) form
and keep the small form's eyes fixed at centre. That is a reduction, not a
redesign.

### d. The state animation vocabulary

The face has six animation states. Each is triggered by real events from
`avicenna/events.py`; none are invented for the design. The face is the only
animated element in the interface — no spinners, no progress bars, no pulsing
indicators exist anywhere else. A later implementer must not add them.

**The mapping from events to states.**

| State | Trigger(s) | Duration | Visual |
| --- | --- | --- | --- |
| **Idle** | No active run | Until a run starts | Large, centred. Eyes track the caret (§3c). Occasional blink. |
| **Listening** | User sends a message (`chat.submit` called); ends when the response arrives | The silent pause — typically 2–10 seconds | Large, centred. Eyes shift to position 2 (centre). A slow pulse: the face dims from `phosphor` to a 70%-brightness variant over 1.2 seconds and back (proposed timing — tune during implementation). This is the only visual feedback that the system heard the user. |
| **Planning** | `RunStarted` fires; ends when `PreflightDeclared` fires | Typically 3–15 seconds | Large, centred (the face has not yet moved to the margin). Eyes shift to position 1 (left, toward the text block). Pulse continues but faster: 0.8-second cycle (proposed timing — tune during implementation). |
| **Writing** | `SectionStarted` fires; persists through `SectionCompleted`/`SectionFailed` cycles until `RunComplete` or `RunFailed` | The bulk of the run — 2–20 minutes | Small, in the margin (§3e). Eyes at position 1 (left). The pulse stops — the face is static except for blinking. State transitions within this state (section completed, section failed) are shown in the text block's stage tree, not by face animation. The face's job during a run is to be a calm presence, not to mirror every event. |
| **Complete** | `RunComplete` fires | 3 seconds, then returns to Idle | Small, in the margin. Eyes shift to position 2 (centre) — looking at the user. A single brightening: the face pulses to full brightness once, holds for 0.5 seconds, and settles. |
| **Error** | `RunFailed` fires; also a `SectionFailed` with `will_retry=False` when no sections remain | Until the user dismisses or a new run starts | Small, in the margin. Eyes shift to position 2 (centre). The face does not pulse. The error is communicated by the text block (the `oxide`-coloured failure glyph and message); the face's stillness is the signal — the absence of the pulse that `Listening` and `Planning` use. |

**Why the pulse matters.** Nothing in the codebase streams. `chat.send` is
request/response; `LLMProvider` has no streaming method. A chat reply arrives
whole after a silent pause of2–10 seconds. A generation run begins with a
`PlanApprovalRequested` event that may take15 seconds to arrive. During these
pauses, the face is the only indication that the system is working. The pulse
animation — a slow, rhythmic dimming and brightening — fills that silence. It
is not decorative; it is the interface's equivalent of a typing indicator. If
the pulse is removed, every silent pause becomes a freeze.

**Why the face does not animate during `Writing`.** A run fires dozens of events
per minute — `SectionStarted`, `ToolInvoked`, `ToolReturned`,
`SectionCompleted`, `StageEntered`, `StageCompleted`. Mirroring these on the
face would create a strobe effect that competes with the stage tree in the text
block, which is the actual progress display. The face's role during a run is to
be still: a calm presence in the margin that says "I am here" without saying
"look at me." The stage tree does the talking.

**The one orchestrated moment.** The face is the interface's single animated
element. There are no spinners in the status bar, no pulsing dots in the
composer, no loading indicators on the confirm dialog. Every other piece of
motion is a discrete state change: a glyph appearing, a colour switching, a
line being appended. The face's pulse is the only continuous animation, and it
exists only during the two states (`Listening`, `Planning`) where the user has
no other feedback.

**Interaction with reduced motion.** When `NO_COLOR` or
`AVICENNA_REDUCED_MOTION` is set, all continuous animation is disabled: no
pulse, no blink. The face still changes state (large/small, centre/margin,
different eye positions), because those are discrete transitions rather than
continuous animation. The `Listening` state, which relies on the pulse for
feedback, falls back to a single brightness change: the face brightens when the
state enters and dims when it leaves, with no cycling.

### e. The large-to-small transition

Decision 10: the face is persistent, large and centred when idle, small in the
margin during a run. The measured legibility floor (verified against the preview
renderer) is that the face reads at34×26 cells and at22×16, and is
unrecognisable at14×10 — below about20 cells wide it stops being a face. A
status-bar thumbnail is therefore not possible.

**The transition is instant.** When a run starts (the user accepts the plan and
`RunStarted` fires), the face moves from centre to margin in a single frame.
There is no animated shrink, no interpolation through intermediate sizes. The
reasons:

1. Intermediate sizes would require pre-rendered frames at every possible
   width, or a runtime resample. Pre-rendering every width from 22 to 34 is13
   frames; runtime resampling violates the principle that the frontend does not
   process images. Neither is justified for a transition that takes 16
   milliseconds.

2. An animated shrink draws the eye to the face during the exact moment the
   eye should be moving to the stage tree. The run has started; the user's
   attention should shift to the text block. A smooth animation that takes0.3
   seconds to complete holds attention on the wrong element for0.3 seconds.

3. The face's role changes discontinuously — from "I am the page" to "I am
   the gloss" — and a discontinuous change in appearance is the honest
   representation of that shift.

**What happens at intermediate sizes.** Nothing. There are no intermediate
sizes. The face is either large (34 cells wide, idle) or small (22 cells wide,
running). If the terminal is resized during a run, the face re-renders at its
current size; it does not interpolate.

**The two-column layout and its minimum width.** The text block occupies 56
columns (the `BLOCK` constant from the preview). The margin occupies whatever
remains after the text block, the left rule (`U+258F`, 1 column), and inter-
column spacing (3 columns). The small face (22 cells wide) sits in the margin's
upper portion, with margin annotations (routing, tags, links) beside or below
it.

The minimum terminal width for the two-column layout is arithmetic from these
constants — not a measured value, but a consequence of the layout dimensions
chosen above:

- Left padding: 2 columns
- Left rule: 1 column
- Text block: 56 columns
- Inter-column gap: 3 columns
- Small face: 22 columns
- Right padding: 1 column
- **Total: 85 columns**

Below 85 columns, the margin cannot hold the face beside the text block. The
fallback is a single-column layout: the face sits above the text block, centred,
and the margin annotations appear below the text block rather than beside it.
The face remains small (22 cells wide) during a run; it does not grow to fill
the available width, because growing it past 34 cells would require a pre-
rendered frame that large, and the face at 34 cells wide in an 80-column
terminal leaves only 46 columns for the text block — too narrow for comfortable
reading.

Below 60 columns (the text block width of 56 plus minimal padding), the text
block itself wraps. This is
a degenerate case — the interface is not designed for 50-column terminals — and
the face is simply omitted. A face that is14 cells wide is mush, and mush is
worse than nothing. The status line in the catchword area still reports the
run state; the face's job is taken over by the stage tree glyphs (`U+2713`,
`U+25B8`, `U+00B7`).

**Summary of fallback tiers.**

| Terminal width | Layout | Face |
| --- | --- | --- |
| ≥ 85 columns | Two-column: text block left, margin right | Small (22×16) in the margin during a run; large (34×26) centred when idle |
| 60–84 columns | Single-column: face above text, annotations below | Small (22×16) above the text block during a run; large (34×26) centred when idle |
| < 60 columns | Single-column, text wraps | No face. Stage tree glyphs carry all state. |

The transition between tiers is also instant: it happens on terminal resize,
and the face simply re-renders or disappears. No animation, no interpolation.

## Section 4 — testing, sequencing and risk

### a. What replaces the frontend tests under Bun

**The existing suite.** Three test files, twenty-nine tests, running under Node's
built-in test runner via `npm test` (which chains `npm run build && node --test`):

- `text.test.mjs` — 10 tests: display-width measurement for CJK glyphs,
  combining marks and ANSI escape sequences; word-wrapping with hard-break
  fallback for tokens wider than the viewport; paragraph-boundary preservation;
  truncation and centre-padding to a column budget.
- `keys.test.mjs` — 11 tests: raw-mode key decoding — CSI arrow sequences,
  modifier parameters (ctrl+right, shift+up), control characters, named keys
  (enter, tab, backspace), bare escape, bracketed paste as a single unit, burst
  ordering, astral Unicode as one key.
- `commands.test.mjs` — 8 tests: slash-command detection, name/args/argv
  parsing, case normalisation (name lowercased, arguments preserved), completion
  with prefix-over-substring preference, the invariant that every command has a
  summary.

All three import from the compiled `dist/` directory. None test the bridge, the
screen renderer, event translation, or any application state.

**What survives conceptually.** Display-width measurement remains necessary —
the new React/OpenTUI layout still needs to know how many columns a string
occupies, and the vault's content is not ASCII. Key decoding may be partially
absorbed by OpenTUI's input layer, but any custom handling not covered by the
framework (bracketed paste, modifier combinations) still needs coverage. Command
parsing is replaced by intent detection on the Python side (`chat.submit`), so
the old commands suite has no direct successor.

**What has no equivalent today and needs one.** Two behaviours of the current
`bridge.ts` are called out in Section 1 as learned-not-designed and must survive
the rewrite:

1. **Partial-line buffering.** A stdout chunk may split a JSON frame mid-line.
   The reader must buffer the partial fragment and join it with the next chunk
   before parsing. The test should send a two-line NDJSON frame where the split
   falls between the two lines — e.g. `{"type":"event","event":"RunSta` in one
   chunk and `ted","runId":"x","seq":1,"ts":0,"data":{}}\n` in the next — and
   assert that exactly one `RunStarted` event fires.

2. **Non-JSON stdout is a fatal desync.** A line on the bridge's stdout that
   does not parse as JSON is not a line to skip — it is evidence that the wire
   contract has been violated and the connection must be treated as unreliable.
   The current `bridge.ts` violates its own rule here: it calls `diagnose()` (a
   log-and-continue path at line 239) rather than closing the connection.
   Section 1 says the rewrite fixes this. The test should send a non-JSON line
   (e.g. `not a frame\n`) on the mock backend's stdout and assert that the
   bridge emits a fatal error and closes, not that it logs and continues.

**The new test surface.** The rewrite produces a React component tree rendered by
OpenTUI's `createCliRenderer`. The testable layers, from lowest to highest:

- **Bridge client** (`bridge/client.ts`): framing, partial-line buffering, fatal
  desync, request/response correlation, timeout handling. This is pure I/O logic
  with no rendering dependency and should be the most heavily tested module.
- **Intent detection** (`avicenna/intent.py`): a new pure-Python module,
  unit-tested by pytest. No frontend involvement.
- **State management** (`state/*.tsx`): transcript append/update, run stage
  tracking, config state. These are React hooks or state objects and can be
  tested with direct invocation or `@testing-library/react` if the rendering
  layer warrants it.
- **Event translation** (`bridge/translate.ts`): typed event to
  `TranscriptEntry`. The current `onEvent` switch in `app.ts` (1,253 lines) has
  no tests at all. The new translator should have one test per event type
  asserting the output text.

**Runner: `bun test`, not Vitest.** Bun's built-in test runner is the correct
choice. Vitest is designed for browser-oriented Vite projects and adds a
dependency plus configuration surface that buys nothing for a CLI tool whose
tests exercise I/O framing and state transitions. `bun test` runs
`.test.ts`/`.test.tsx` files natively, supports TypeScript without a transpile
step, and its assertion API is close enough to the `node:test` + `node:assert`
style the old suite used. The cost is that tests import from `bun:test` rather
than `node:test`, which is Bun-specific — but the entire frontend is Bun-specific
by Decision 7, so portability is not a constraint.

**The parity check.** `scripts/check_protocol_parity.py` hardcodes two paths:

```python
PROTOCOL_TS = ROOT / "tui" / "src" / "protocol.ts"
APP_TS = ROOT / "tui" / "src" / "app.ts"
```

The rewrite moves `protocol.ts` to `tui/src/bridge/protocol.ts` (per the
directory structure in Section 1) and eliminates `app.ts` in favour of React
components. The event handler — the `case 'EventName':` switch that
`handled_events()` parses — moves to `tui/src/bridge/translate.ts` (this is
inference: the new structure names this file as the event-to-transcript
translator, and it is the natural home for the case statements).

The script's logic — AST-parse `events.py`, regex-match the `EventName` union,
regex-match the `case` statements — is structurally sound and needs no change.
Only the two path constants need updating:

```python
PROTOCOL_TS = ROOT / "tui" / "src" / "bridge" / "protocol.ts"
APP_TS = ROOT / "tui" / "src" / "bridge" / "translate.ts"
```

This is a Stage 1 change: the parity check must pass before anything else
builds, and the rewrite breaks it on the first commit.

### b. Whether a TUI snapshot tier is worth it

Cline uses `@microsoft/tui-test` and `tuistory` to capture rendered terminal
output as reference snapshots and diff against them on subsequent runs. The
question is whether Avicenna should adopt the same approach.

**What a snapshot tier catches that a unit test does not.** Visual regressions: a
column misaligned by one character, a colour applied to the wrong span, a
truncation that leaves orphaned glyphs, the face rendering at the wrong size.
These are real defects, and they are exactly the kind a reader notices
immediately and a developer does not.

**What it costs.** Every visual change — a palette adjustment, a glyph
substitution, a spacing tweak, a layout reflow — invalidates the reference
snapshot and requires regeneration. Snapshot churn is tolerable when the visual
design is stable. It is punishing when the design is being settled in real time,
which is the current situation: the palette is approved but the layout, the face
rendering, the stage-tree display, the transcript format and the margin gloss
are all in flux across Sections 2 and 3.

**Recommendation: not yet.** The design is explicitly incomplete. A snapshot tier
installed today would churn on every commit for the next several stages,
training the team to run `bun test --update-snapshots` as a reflex rather than
as a review — which is the one behaviour that defeats the purpose of snapshot
testing.

**What has to be true before revisiting.** The decision should be reopened when:

1. The face is implemented and the large-to-small rendering is settled (Stage 4).
2. Three consecutive design passes have not changed the snapshot baseline.
3. A visual regression ships that unit tests did not catch — at that point the
   evidence is that the cost of not having snapshots exceeds the cost of
   maintaining them.

Until then, unit tests for the bridge, the translator and the state layers,
plus manual inspection of the rendered output, are the better investment.

### c. The CI job rewrite

**The asymmetry is correct.** The Python `build` job runs on `windows-latest`
because the vault's PowerShell tools (`*.ps1`) are part of the pipeline's
contract with the harness. They shell out to `pwsh`, they use Windows path
conventions, and a pipeline that passes on Linux but fails on the user's actual
machine is a green build that lies. The TUI job runs on `ubuntu-latest` because
it has no PowerShell dependency — it is pure TypeScript/Bun. These are not the
same workload and should not share a runner.

**The frontend job becomes a Bun job.** The current steps and what replaces them:

| Current | Becomes |
| --- | --- |
| `actions/setup-node@v4` (Node 20, cache npm) | `oven-sh/setup-bun@v2` (Bun ≥1.3) |
| `npm ci` | `bun install --frozen-lockfile` |
| `npm run typecheck` | `bun run typecheck` |
| `npm run build` | `bun run build` |
| `npm test` | `bun test` |

The `--frozen-lockfile` flag is Bun's equivalent of `npm ci`'s lockfile
enforcement: it fails if `bun.lockb` is out of date. (This is inference: I have
not verified the flag name against Bun 1.4's CLI help. The exact flag should be
confirmed during implementation.) The `cache-dependency-path` changes from
`tui/package-lock.json` to `tui/bun.lockb`.

The `bun test` step runs bare, not through a script that chains build and test.
Chaining them (as `npm test` currently does with `npm run build && node --test`)
hides a build failure behind a test failure. Bun runs TypeScript natively, so
the build step and the test step are independent.

**`Frontend stays unstyled` is correctly deleted.** The step prevents the
accidental reintroduction of raw SGR escapes (`\x1b[...m`) outside `ansi.ts`.
This work is the deliberate introduction of a visual design — the very thing the
step was guarding against. Leaving it means the first commit of the new design
fails CI by design, which is a gate that blocks the work it was meant to allow.
Section 1 already records this deletion, and it is correct: CLAUDE.md's rule is
clear — "a check that cannot fail the build is documentation rather than a
gate."

A new lint may be warranted later: once the visual system is in place, a check
that colour is applied only through the approved palette tokens (not through raw
SGR or ad-hoc hex values) would prevent the kind of drift the original step
caught. That is a different lint for a different time.

**Section 3's face-frame gate.** Section 3 owns the face-frame generator — a
script that reads `avicenna.png` and produces `face-frames.generated.json`
containing the cell data for each animation frame. If this generator is committed
(as Section 3 specifies), CI should verify that the committed JSON matches what
the generator produces. The check is: run the generator, diff its output against
the committed file, fail on mismatch. This step belongs in the `tui` job
alongside the other frontend checks. I am not specifying it in detail because
Section 3 owns the generator and its contract.

**The two repository rules.** CI has no `continue-on-error`: a check that cannot
fail the build is documentation, not a gate. This constrains every step in the
new job — if a check cannot enforce something, it should be deleted rather than
left to pass silently. And `pytest` and `python -m pytest` are not the same
command: the latter puts the working directory on `sys.path`, which once hid a
build where both jobs aborted during collection for a dozen commits because three
test modules import from `scripts/`, which is not a package. CI runs the bare
`pytest`. The same reasoning applies to the frontend: `bun test` is the bare
form.

### d. The four build stages and what "done" means for each

Decision 8 sequences the work: (1) shell rendering real pipeline events, (2)
chat plus intent confirm, (3) plan review plus settings, (4) the face. Each
stage's definition of done includes something that exercises the real product,
not only its parts — because the backend-shippability spec exists to record the
lesson that fourteen gates passing while the product had never been run is not
evidence.

**Stage 1: shell.** Bun and OpenTUI running, the bridge client connecting, the
transcript rendering, and a real run displayed from real events.

Done when: launch `avicenna` with a vault and a valid key, type a topic
(bypassing chat — the old direct-submission path is the interim interface),
observe the outline filling in from `PreflightDeclared`, sections appearing from
`SectionStarted`/`SectionCompleted`, and the run completing with `RunComplete`
or failing with `RunFailed`. The test is that the product works end-to-end with
no part mocked: the bridge connects to the real backend, the backend connects to
a real provider, and the note is written to a real vault. One run, one domain,
one template — the generation matrix's safety net (vault git revert commands)
applies.

**This is the stage that first makes the interface genuinely usable.** The user
can give a topic and receive a note. Everything before this is plumbing;
everything after this is polish that can be corrected by evidence from real use.
Feedback becomes possible at this point, and the remaining design can be
validated against a working product rather than against mockups.

**Stage 2: chat plus intent confirm.** The conversational surface, the built-in
persona, `chat.submit` with intent detection, the confirm dialog.

Done when: launch `avicenna`, type "what notes do I have on political
philosophy?" and receive a chat reply from the backend, then type "write me a
note on the epistemic gap" and see the confirm dialog appear with the detected
topic and domain, accept it, and observe the run start. Also: type a near-miss
trigger (ambiguous between chat and generation) and verify the confirm step
catches it rather than guessing.

**Stage 3: plan review plus settings.** The plan-review screen, `run.approve`
with overrides, the settings panel (generation values, provider/model, API keys).

Done when: launch `avicenna`, trigger a generation, see the plan from
`PlanApprovalRequested`, change words-per-heading or the agent in the review
screen, approve with overrides, and observe the pipeline use the overridden
values (visible in `PreflightDeclared`'s output). Also: open settings, change
the provider or model, and see the next run use the new configuration.

An earlier draft of this test said "edit the topic or headings", which
contradicted section 2's decision that headings are **not** editable — editing
one without re-running pre-flight leaves a plan that no longer describes what
will be written. Section 2 governs; the overridable fields are the ones it
lists.

**Stage 4: the face.** The rendered face in idle and animated states.

Done when: launch `avicenna`, see the face in its large idle form (~34×26 cells,
per the measurements in the shared context), start a run, see it transition to
the small form in the margin, see it animate through running/complete/failed
states, and verify that the face does not obscure the transcript or the status
bar during any state.

### e. Risk, and the open items

**1. Three of the six events the 2026-09-07 spec required still do not exist.**

I verified `events.py` directly. The 27 concrete event dataclasses are:
`RunStarted`, `PreflightDeclared`, `ManifestWritten`, `SectionStarted`,
`SectionCompleted`, `SectionFailed`, `StageEntered`, `StageCompleted`,
`ToolInvoked`, `ToolReturned`, `WordCountChecked`, `MarkdownNormalised`,
`TagsProposed`, `TagsValidated`, `SchemaDetected`, `MocUpdated`, `NotesLinked`,
`NoteWritten`, `PlanApprovalRequested`, `RunFailed`, `RunComplete`, `LogMessage`,
`ThemeMinted`, `TransitionsApplied`, `SemanticGuardDecision`, `EntitiesDerived`,
`TagsAssignedMechanically`. The `protocol.ts` `EventName` union lists the same
27. Parity holds today.

Against the 2026-09-07 spec's list of six required events:

| Required event | Status |
| --- | --- |
| Routing rationale — runner-up and margin | **missing** |
| Typed link-resolution result | **partial** — `NotesLinked` carries `inline`, `related`, `targets`; no examples of discarded links |
| Near-miss on a mint | **done** — `SemanticGuardDecision` |
| Registry totals | **missing** |
| Resume availability | **missing** |
| Mechanical tag assignment | **done** — `TagsAssignedMechanically` |

That spec's own sequencing argued the event vocabulary should close before the
interface is built, because "an event is cheapest to add while the stage that
would emit it is open." That argument is still sound. The counter-argument is
that the spine can render `LogMessage` fallbacks for the three missing events —
a routing runner-up is already logged by the routing stage, registry totals
appear in `avicenna doctor`'s output, and resume availability can be inferred
from the presence of `_tmp/`. The fallback is ugly but functional.

**Decision: ship the spine, add the events.** The cost of adding an event later
is one dataclass in `events.py`, one name in `EventName` in `protocol.ts`, and
one case in the translator — each is a few lines, and the parity check enforces
completeness. The cost of blocking the interface on three events is delaying the
point at which real feedback becomes possible (Stage 1). Since the events are
additions to existing stages rather than changes to control flow, they are
backwards-compatible: the frontend renders whatever arrives, and a new event name
is invisible to old code.

The partial coverage on the link-resolution result matters most. `NotesLinked`
carries counts but not examples of what was discarded, and "the model invented
nine links" is exactly the sort of judgement a reader should see without reading
warnings. When this event is completed, it should carry a `discarded` field with
a few examples of rejected targets.

**2. The pipeline has never been run end to end since the heading-length and
linking changes.**

The `WORDS_PER_HEADING_DEFAULT` change (1500, with a 1000–2000 band) altered
how many words each heading asks for. The `LinkingStage` added a whole new stage
running entity matching and related-note resolution. Neither has been exercised
against a real provider and a real vault since they were merged.

The backend-shippability spec's `scripts/gen_matrix.py` exists for exactly this
purpose: six runs, one per domain, with per-cell assertions. That script has not
been run since these changes.

**What should happen and when.** Before Stage 1 implementation begins, one run
of the generation matrix — even a single domain, not all six — should be
executed against a real provider and a real vault. The purpose is not to prove
the pipeline is perfect; it is to prove it is not broken in ways the interface
would faithfully render as progress. The shippability spec's assertion set (note
exists, word count above minimum, frontmatter parses, tags from taxonomy,
wikilinks resolve, MOC updated) is the right one.

This is not a blocking gate in CI — the matrix costs money and time and needs a
real key. It is a manual precondition for starting Stage 1.

**3. Streaming is deferred.**

Decision 12 defers streaming. The cost is immediate and visible: every chat
reply arrives whole after a silent pause of 5–30 seconds (depending on the
provider and the reply length). During that pause the interface shows nothing —
no partial text, no typing indicator, no progress.

The deferral commits the design to:

- `chat.send` remains request/response. The bridge method returns the full reply
  in one frame.
- `LLMProvider` has no streaming method. This is not a frontend constraint; the
  provider layer would need a new method returning an async iterator of tokens.
- The face animation (Stage 4) is the mitigation for the silent pause. Section 3
  must design a "thinking" animation that is engaging enough to cover 15–30
  seconds of silence without becoming irritating on repeated use. This makes
  Section 3 load-bearing rather than decorative.

**Trigger for revisiting.** Streaming should be added when: (a) users report the
silent pause is confusing or makes the interface feel broken; (b) the face
animation proves insufficient after Stage 4 is in real use; or (c) a provider
adds a streaming-first API that is cheaper or faster than request/response.
Adding streaming requires changes at three layers — `LLMProvider` (new method),
the bridge (chunked event frames for partial replies), and the frontend
(progressive text rendering) — none of which are small.

**4. The parity check breaks on Day 1 of the rewrite.**

`scripts/check_protocol_parity.py` hardcodes `tui/src/protocol.ts` and
`tui/src/app.ts`. The rewrite moves the first to `tui/src/bridge/protocol.ts`
and eliminates the second in favour of React components whose event handler
lives in `tui/src/bridge/translate.ts` (inference). The parity check will fail
on the first commit of the new frontend. This must be coordinated: the path
constants change as part of Stage 1, and the parity check must pass before the
rest of the CI matrix runs. It is a one-line-per-constant change, but forgetting
it means a green build is impossible until someone notices.
