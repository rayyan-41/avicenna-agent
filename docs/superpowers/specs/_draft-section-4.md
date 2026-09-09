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
`PlanApprovalRequested`, edit the topic or headings in the review screen, approve
with overrides, and observe the pipeline use the overridden values (visible in
`PreflightDeclared`'s output). Also: open settings, change the provider or
model, and see the next run use the new configuration.

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
