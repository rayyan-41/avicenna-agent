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
| `write(?: me)? a note(?: on\|about)? (.+)` | the trailing noun phrase |
| `generate (?:me )?a note(?: on\|about)? (.+)` | same |
| `create (?:me )?a note(?: on\|about)? (.+)` | same |
| `write about (.+)` | everything after "write about" |
| `write on (.+)` | everything after "write on" |
| `draft (?:me )?(?:a )?(?:note )?(?:on\|about)? (.+)` | the trailing noun phrase |
| `compose (?:me )?(?:a )?(?:note )?(?:on\|about)? (.+)` | same |
| `note (?:on\|about) (.+)` | the trailing noun phrase |

That is eight patterns. A user who says any of these is asking for a note. The
list is closed: adding a new verb means editing `intent.py` and its test file,
not tuning a prompt.

The patterns are tested against the full input string, not against a
pre-processed token list, because the verb phrase matters to topic extraction —
"write about Kant" yields topic "Kant" only if the regex captures the
post-verb-phrase remainder.

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
   `oxide` (the failure colour, per the palette) with the `U+00D7` glyph
   (the refusal signal, per the glyph rules). The key is not echoed back for
   "correction" — the user must retype it, which is the correct trade: a
   slightly slower retry against the guarantee that the wrong key never
   appeared on screen.

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

`tui/src/commands.ts` defines 16 commands (14 visible, 2 hidden):

`/help`, `/note`, `/dry`, `/resume`, `/cancel`, `/agent`, `/agents`, `/route`,
`/vault`, `/tools`, `/mcp`, `/init`, `/login`, `/clear`, `/diagnostics`,
`/quit` (plus `/exit` hidden).

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
