# Handoff

State of play for a session that starts cold. Read [AGENTS.md](../AGENTS.md)
for doctrine and [CLAUDE.md](../CLAUDE.md) for the operational layer first —
this file only carries what neither of those can know: what is half-done, what
was learned the hard way, and what comes next.

**Rewritten 2026-09-08 (second pass).** The three-task list landed, a live run
against the real vault exposed four further defects, and all four are now fixed.
The most important thing in this file is no longer the diagnosis correction
below — it is that **CI had been running zero tests for at least a dozen
commits.** See "The build was lying".

---

## Decision: linker stage dropped (2026-09-08)

The user was asked which of the three whole-note model round-trips (weaver,
formatter, linker) should become deterministic, and chose: keep the weaver,
drop the linker. The formatter was already replaced by deterministic Python on
another branch.

**Why:** The fidelity benchmark note had 0 external wikilinks. Interconnectivity
in this vault is entity-driven through tags, not wikilink-driven. The linker was
also the stage most prone to inventing notes that do not exist — `LinkingStage`
already carried a comment about it, and `_resolve_wikilinks` existed purely to
unwrap the links it hallucinated.

**What was removed:** `LinkingStage` class, `LinkCandidatesFound` event, the
`"linking"` stage literal, and all test coverage for the linker stage.

**What was kept:** `_resolve_wikilinks` and `_build_vault_notes_index` remain as
a guard on weaver output — a model writing transition prose can spontaneously
produce `[[wikilinks]]` to non-existent notes. The resolver strips unresolvable
links to plain text. The `get_related_notes` vault tool contract and
registration remain since they are still valid vault infrastructure.

---

## Where things stand

| | |
| --- | --- |
| Repo | `master`, pushed, working tree clean |
| Tests | 714 passing, 1 skipped (was 519 at the start of the session) |
| Gates | All green **on CI**, which is new — see "The build was lying". `mypy --strict` on providers+pipeline+bridge (26 files); parity OK (23 events); `check_maps` OK; both PowerShell lints; bridge smoke test; frontend typecheck/build/29 tests |
| Vault | separate git repo on `E:`, with **three uncommitted changes** from the live run: one new note under `History/`, plus a modified `.agents/taxonomy.json` and History MOC. Left alone deliberately; reverting is the user's call |
| Config | `~/.avicenna/` holds `api_keys_pool`, `user_config.json`, `mcp_config.json`, `index/` |

---

## The correction that matters

**The previous handoff's diagnosis of the 2.4-hour stall was false.** It said:

> The cause is a provider client that can hang indefinitely on a single call.

It cannot. The installed SDK (`mistralai 2.9.1`) applies a per-call ceiling all
on its own — `chat.py:379-383` falls back to `sdk_configuration.timeout_ms` and
then to a hardcoded `300000` ms. A 5-minute per-call limit has been in force the
entire time. **No single call ever hung for 8,703 seconds.**

What was unbounded was the *total*. `complete()` retries up to `_MAX_RETRIES`
times and **every retry restarts the per-call clock**, so one logical
completion could burn `4 x 300s` plus backoff with nothing watching the sum. A
run makes one such call per section plus the whole-note round-trips that
follow, and section concurrency has now gone from 3 to 6.

Bounded-but-slow attempts multiplying across a run is the best available
explanation for 8,703 seconds. **It is inferred from the code path, not
measured** — that run's logs were not kept. If you ever reproduce a very long
run, capture the logs before anything else; this inference is the weakest link
in the current understanding and the only thing that would settle it.

The lesson generalises: the previous handoff stated that diagnosis as fact, and
it was carried into three agent briefs before anyone checked it against the SDK
source. **State the evidence for a diagnosis, or mark it as inference.**

---

## What landed this session

### 1. Provider wall time is bounded, per call and across retries — DONE

`avicenna/providers/mistral.py` now stores its `timeout` (it previously
accepted the parameter and discarded it) and applies it as `timeout_ms` at the
eager constructor, the lazy per-key client in `_get_client`, **and** the call
site. The pooled path builds one client per API key, so a fix applied to only
one of those stays invisible until a key rotation.

Default is 300s — matching the SDK's own implicit value, so making it explicit
regresses nothing. An earlier draft used 600s, which would have *doubled* the
worst case for the failure it was written to cure. If you are tempted to raise
it, work out the retry multiplication first.

On top of that sits a **total-elapsed budget** (`PROVIDER_BUDGET_DEFAULT`,
900s): computed once on entry from `time.monotonic()`, checked before every
attempt, and used to shrink the per-attempt `timeout_ms` so the last attempt
cannot overrun it. This is the part that actually bounds a run.

Both are resolvable through the layered settings (`provider_timeout` /
`provider_budget`, env `AVICENNA_PROVIDER_TIMEOUT` / `AVICENNA_PROVIDER_BUDGET`).
Key quarantine and rate-limit rotation semantics are untouched — the budget
bounds time, it does not change which errors are retryable.

The harness-side `asyncio.wait_for` in `AssemblyStage` is gone, removed only
after the client had its own deadline. That ordering is not ceremony: it was
once done in the wrong order, and that is what produced the stall.

`httpx` is now declared in `pyproject.toml` rather than relied on transitively
through `mistralai`, because `_map_error` branches on `httpx.TimeoutException`.

### 2. The normaliser is wired — DONE

`avicenna/pipeline/normalise.py` had 30 passing tests and zero callers. It now
runs at **two** call sites, and the second one is the point:

- `AssemblyStage`, which writes through `_write_note_atomically`.
- `_write_back`, which is where `FormatterStage` pushes
  whole-note model output **after** assembly. Wiring assembly alone would have
  left the note normalised and then overwritten by un-normalised model
  output. The formatter is by function the stage most likely to reintroduce
  exactly the damage the normaliser repairs.

Inside `_write_back` the normaliser runs after frontmatter reconciliation and
before the truncation guard, so the guard validates the bytes that land on disk,
and both sides of its ratio stay like-for-like (`ref_body` is itself already
normalised by an earlier pass). Body recovery re-splits with
`_split_frontmatter` rather than slicing at the pre-normalisation frontmatter
length — that slice was only correct while the normaliser left frontmatter
byte-identical, and a wrong body feeds the truncation guard, where the failure
mode is a legitimate revision silently rejected.

`MarkdownNormalised` carries a `stage` field because it fires from more than one
place.

### 3. Concurrency — DONE

Section concurrency was hardcoded to `3` in five places. There is now one
`MAX_CONCURRENCY_DEFAULT = 6` in `avicenna/settings.py`, resolved through
`resolve_concurrency()` with the usual precedence (CLI → `AVICENNA_CONCURRENCY`
→ vault `max_concurrency` → default) and clamped to `[1, 16]`, because every
concurrent section is a live call against a rate-limited provider and an
unbounded value turns a config typo into a 429 storm.

### 4. Structural fidelity — DONE

The benchmark note (7,882 words, 12 numbered `###` headings, a TOC callout whose
anchors match exactly, 11 tags including 4 entities, **0 external wikilinks**)
was the target. All three parts landed:

- `avicenna/pipeline/structure.py` — pure Python, imports no LLM client.
  Numbered `###` headings, TOC callout generation, restated headings stripped,
  stray `#` demoted. Idempotent.
- `FormatterStage` no longer delegates to a model; it calls `apply_structure`
  and still writes through `_write_back`, so the frontmatter guarantee,
  normalisation and truncation guard all still apply.
- `TocStage` is gone. It ran five stages *before* numbering and emitted
  `[[#Foo-1]]` for duplicate headings — an anchor present nowhere in the
  document — then had its work replaced by `FormatterStage` in the same run.
- `[Table]` / `[Mermaid Diagram]` section forms are parsed in `preflight.py`
  and change the section prompt in `sections.py`. The form is metadata: it
  travels in a parallel `forms` tuple, so the heading text stays clean and the
  ~15 existing readers of `.headings` did not have to change. Formed sections
  are excluded from the prose word-count total.

The TOC anchor invariant is a property test worth keeping: **every `[[#...]]`
target in the TOC must resolve to a heading actually present in the note.** It
is asserted on both code paths. The anchor format was implemented from
Obsidian's documented heading-link rules and matches what its autocomplete
produces; it has **not** been tested against the application, and
`generate_toc` is the single place to change if it proves wrong.

---

## The build was lying

CI had been failing on `master` for at least a dozen commits, and **both jobs
aborted at their Tests step** — so every gate that runs after it had never
executed at all: strict mypy, the bridge blocking-call lint, vendor neutrality
and containment, the reference-vault name check, the future-annotations check,
the stray-print lint, protocol parity, the bridge smoke test, and the frontend's
unstyled check. The build read as merely red rather than as vacuous, because the
failure was at collection.

Two causes, both invocation differences hidden by a developer machine:

- **Python.** Three test modules import from `scripts/`, which is not a package
  and is not installed by `pip install -e`. `python -m pytest` puts the working
  directory on `sys.path` and collected fine; the bare `pytest` CI runs does
  not, so collection was interrupted with three `ModuleNotFoundError`s and no
  test ran. Fixed with `pythonpath = ["."]` in the pytest ini.
- **Frontend.** `node --test "test/*.test.mjs"` passes the glob to node quoted,
  and node only expands globs from v21. `package.json` declares `>=18` and CI
  pins 20; this dev machine runs 24. Fixed with argument-free `node --test`.

Then the first run that actually *reached* the type check failed on undeclared
`types-PyYAML`, now in the dev extra.

**The lesson generalises:** run gates the way CI runs them, not the way that is
convenient locally. `python -m pytest` and `pytest` are not the same command.

---

## What is actually left

- **Wire the embedding index.** `avicenna/vault/index.py` still has no callers,
  and `semantic_guard` in `avicenna/vault/registry.py` still returns `None` for
  every proposal. That is the seam, and it is the thing that would stop synonym
  proliferation in the taxonomy.
- **Vault sovereignty / emergent taxonomy.** Designed but unbuilt —
  `docs/superpowers/specs/2026-09-07-vault-sovereignty-and-emergent-taxonomy-design.md`.
- **The terminal interface.** Designed but unbuilt —
  `docs/superpowers/specs/2026-09-07-terminal-interface-design.md`. Read the
  frontend-skeleton section of CLAUDE.md before touching `tui/`.
- **A live run against the new weaver.** The transition weaver has never been
  exercised against a real API — every test injects a `FakeProvider`, and that
  seam is exactly where its last defect hid.
- **Bridge plan approval.** The bridge auto-approves every plan. A real
  approve/decline needs a response path in the wire protocol, which is a
  protocol change rather than a pipeline one. `PlanApprovalRequested` already
  carries everything the frontend would need.
- **The tagger files people as themes.** The live run tagged a person as a
  *theme* rather than an *entity*, and coined `optic` as a singular of "optics".
  Since connection in this vault is carried by entity tags, that is a miss in
  the thing the project exists to do. Prompt quality, not code.

---

## What the live run exposed, and how each was fixed

The first end-to-end run against the real vault took 204.8s against a previous
8,703s, which settled the timeout question. It also produced four defects, plus
a fifth found while verifying the fix for the first.

1. **The weaver destroyed 72% of the note.** It received the whole assembled
   note and returned a replacement; a 9,000-word note came back at ~2,500, with
   paragraphs about subjects the note was not about. Nothing caught it because
   `AssemblyStage` writes through `_write_note_atomically`, which has no
   truncation guard. Replaced by `TransitionStage` — see below.
2. **`WordCountChecked` reported `verdict=pass`** at 3,401 words against a 9,000
   minimum, one line after logging that the note was short. The field was the
   constant `"pass"` because the only alternative was `"fail"`, and a short note
   is deliberately not a failure. Added `"short"`; the advisory policy is
   unchanged and nothing branches on the verdict.
3. **The normaliser added a blank line to every correctly-spaced heading**, and
   was not idempotent: a heading with no blank after it gained one on the first
   pass and a second on the next. 658 tests passed over it, because nothing
   asserted on heading spacing at all.
4. **Numbering made every section a sibling of its own sub-headings.**
   `## Section` is promoted to `### N. Section`, which is the level the section
   agents' sub-headings already use. Sub-headings now demote with their parent,
   guarded so the pass stays idempotent.
5. **Four characters in a heading silently broke its TOC anchor** — `]` closes
   the wikilink early, `|` is the alias separator, `#` the heading separator,
   `^` a block reference. The heading is sanitised, not merely the anchor,
   because the two must stay byte-identical. Emphasis, colons, parentheses and
   ampersands are legal in a link target and are deliberately left alone, which
   also settles the open question about a live note's
   `[[#4. The *Book of Optics* ...]]` anchor: it was always fine.

---

## The weaver is now transition-only

The note body never round-trips through a model. Sections are written once, by
their section subagent; after that only the pipeline edits the note.

`TransitionStage` runs between assembly and word count. The model sees a
*skeleton* — the topic, every heading, and the first and last sentence of each
paragraph — which is enough to know what each section is about and where it
begins and ends, and not enough to regurgitate the note. It returns one numbered
single-line transition per section. Python splices one after each heading,
section 1 included, where it orients the reader from the topic into the first
section. The write goes through `_write_back`, whose truncation guard is exactly
the protection whose absence let the 72% loss through.

The guard is **lenient about length and stylistic variation** — a 4-to-80-word
band only, because models vary and that is not a defect — and **strict about
topical relation**, which is what actually failed: a transition must share
significant terms with the heading it precedes, the heading before it, or the
topic. It must also be structurally inert. A failing transition is dropped
alone; its siblings still land, and the run never aborts.

**The defect that nearly shipped, and the lesson in it.** The provider was
constructed as `get_provider(name, keys=pool, ...)`. Providers take `api_key`
plus `pool`, and `get_provider` is `(name, **kwargs)` — so mypy checked nothing,
the `TypeError` landed in the stage's own broad `except`, and every real run
would have reported "transition provider unavailable" and skipped the weaver
silently. The suite stayed green because every test injects a `FakeProvider`
through the `weaver_provider` seam and never builds a real one.

> A test seam that bypasses construction leaves construction untested, and a
> broad `except` around it turns the resulting failure into a shrug. Where a
> stage degrades gracefully, something must still exercise the path it degrades
> *from*.

---

## taxonomy.json is edited, not rewritten

`persist()` reserialised the whole document with `json.dumps(indent=2)`, so
adding four themes to the user's hand-authored source of truth produced a
**118-line diff**: every inline array expanded to one element per line and every
blank line vanished. Its docstring claimed it "preserves key order, existing
indentation style, and every key the file carries." It did not. The same mint
now changes four lines.

**Verify a formatting-sensitive change against the real file, not a fixture.**
The first implementation passed ten tests on a synthetic taxonomy and, on the
user's actual one, appended the new tags into `schema.arity.themes` — the arity
pair `[1, 3]` declaring how many themes a note may carry — because the key
locator took the first textual occurrence of `"themes"` at any nesting depth,
and the arity one comes first. The file still parsed, so nothing downstream
would have complained; the validator would simply have read an arity of
`[1, 3, "some-tag"]`. Corrupting the schema is worse than the reformatting the
change set out to prevent. The fixture had no nested key shadowing a top-level
one, so it could not have caught it.

---

## Rules learned the hard way

**A worktree that runs `pip install -e` repoints the editable install for the
whole machine.** After one parallel agent installed inside its worktree,
`import avicenna` from anywhere without the working directory on `sys.path`
resolved to *that worktree's* code. Test runs were unaffected — `python -m
pytest` and the `pythonpath` ini both put the working directory first — but any
bare `python script.py` silently imported another branch. Check
`__editable___*_finder.py` if imports look impossible, and reinstall from the
repo root after merging worktrees.

**`CLAUDE.md`'s Commands section is a subset of what CI actually runs.** This
cost real time this session — an agent shipped work that passed every gate it
had been given and would still have failed the build. `.github/workflows/ci.yml`
is the authority. It additionally runs: `avicenna/bridge` in the strict mypy
set; a stray-`print(` lint; a `from __future__ import annotations` check; and a
bridge smoke test. The print lint is **line-based**, so a multi-line `print(`
whose `file=sys.stderr` sits on a later line trips it even though it writes to
stderr — use `warn()` from `avicenna/config.py` instead of hand-rolling one.

**Parallel agents are safe in separate git worktrees.** The previous handoff
said to dispatch serially until the no-destructive-git rule was proven. Three
agents ran concurrently this session with no shared state — one `git worktree`
each, on its own branch — and nothing was lost. Worktrees remove the condition
that made parallelism dangerous rather than relying on every agent to behave.
Keep the prohibition in every brief anyway.

**Never run a command that discards working-tree or index state.** Forbidden
outright: `git reset` (any form), `git checkout -- <path>`, `git restore`,
`git stash`, `git clean`, `git revert`, `git rm`. A concurrent agent once ran
`git checkout -- .` in a shared tree and destroyed the completed work of two
others; it was recovered only via `git fsck --lost-found`. When an agent needs
to undo its own change, `git show <ref>:<path> > <path>` is a read plus a
redirect and is safe.

**Verify subagent reports against the tree, not against their tone.** Every
report this session was broadly honest and every one contained at least one
inaccuracy — a file claimed untouched that was edited, an SDK version misquoted,
a gate count that was right beside a lint that had never been run. All three
agents also produced at least one comment stating a confident mechanism that was
not true, and each needed a second or third pass to correct it. Re-run the gates
yourself; read the diff, not the summary.

**A confident wrong `why` comment is worse than no comment.** This codebase's
comments are load-bearing — several modules open with the defect that motivated
the design — so a reader trusts them and designs around them. Three separate
fabricated mechanisms were caught in review this session. Re-derive a claim
before writing it down, and mark inference as inference.

---

## Defects already fixed — do not reintroduce

- **PowerShell argument quoting.** `avicenna/tools/powershell.py` used to wrap
  any argument containing a space or comma in literal quotes. subprocess argv
  lists already handle Windows quoting; adding quotes breaks it. It was the root
  cause of every empty `tags: []`.
- **The pipeline owns frontmatter.** `_write_back` always keeps the frontmatter
  already on disk and discards whatever the model returned.
- **A folder name is a path, not a tag.** `Art History` is the path form;
  `art-history` is the tag form. Conflating them wrote garbage keys into
  `taxonomy.json`.
- **`_canonical_domain_dir` returns `Path | None`** and never fabricates a
  directory.
- **Tool-absent is not the same as zero results.** Every vault tool call in a
  stage must degrade gracefully *and say so* when the tool is absent — a vault
  with zero PowerShell tools is legitimate. The `result is not None` pattern
  that was load-bearing in the now-removed `LinkingStage` generalises to all
  optional tool calls.

---

## What the architecture is converging on

The user's direction, in their words:

> *"There should be no discrepancy between the vault and the harness. I define
> domains through root folders, and within it, further folders, and all are in
> the hands of the user. The only thing the harness has control over is proper
> tagging and automatic backlink creation using semantic connections through a
> knowledge graph. Cohesion and generation is what the harness should do."*

> *"The end user, me, has only one job: give the harness an input for a note.
> Themes and types are to be decided by the harness. Over time, the theme and
> types become sort of like a map of my brain."*

So: **the vault owns structure** and **the harness owns generation and cohesion
only**. `taxonomy.json` inverts from a declared input into a harness-maintained
registry. Design in
`docs/superpowers/specs/2026-09-07-vault-sovereignty-and-emergent-taxonomy-design.md`.
The terminal interface is designed but unbuilt —
`docs/superpowers/specs/2026-09-07-terminal-interface-design.md`, and see the
frontend-skeleton section of CLAUDE.md before touching `tui/`.

---

## Also unwired, deliberately

- `avicenna/vault/index.py` — incremental embedding index, keyed by path plus
  content hash, under `~/.avicenna/index/<vault_hash>/`. Verified against the
  live vault: 73 notes, 928 chunks, 0.67s, 15.2 MB. Nothing calls it yet.
- `semantic_guard` at `avicenna/vault/registry.py:61` returns `None` for every
  proposal. It is the seam where the index attaches, to stop synonym
  proliferation. **Do not** substitute a fuzzy string-similarity heuristic — a
  wrong merge silently collapses two distinct ideas.

Embeddings are Google (`gemini-embedding-2`, 3072 dims default, Matryoshka
truncation to 768, `taskType` set per call). The key pool is round-robin and
provider-scoped: quarantine on 401/403, rotate rather than sleep on 429.

---

## Waiting on the user

- **Rotate all four API keys** — a subagent printed them in plaintext — and
  re-scope them in `~/.avicenna/api_keys_pool` under `[mistral]` and `[google]`
  headings. Still outstanding.
- Decide whether to keep the `_themeCounts` / `_typeCounts` keys a subagent
  added to `taxonomy.json` against instruction.
- **Decide what to do with the live run's output in the vault**: one new note
  under `History/`, plus a modified `.agents/taxonomy.json` and History MOC, all
  uncommitted. Nothing in this session has touched them.
- Optionally add `paintings_source` to `excludeFromDerivation`.
- Optionally drop the `- - -` separator from the weaver template at
  `.agents/agents/weaver.md:121` in the vault. Less urgent now that the
  normaliser collapses rules on every write.
