# Handoff

State of play for a session that starts cold. Read [AGENTS.md](../AGENTS.md)
for doctrine and [CLAUDE.md](../CLAUDE.md) for the operational layer first —
this file only carries what neither of those can know: what is half-done, what
was learned the hard way, and what comes next.

**Rewritten 2026-09-08.** The previous version listed three tasks. Two have
landed, the third is half landed, and its diagnosis of the first was wrong —
see the correction below, which matters more than anything else in this file.

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
| Repo | `3ce9524` on `master`, **not yet pushed** (10 ahead of `origin/master`), working tree clean |
| Tests | 550 passing (was 519) |
| Gates | `mypy --strict` on providers+pipeline+bridge clean; parity OK (22 events); `check_maps` OK; both PowerShell lints clean; bridge smoke test OK; frontend typecheck/build/29 tests clean |
| Vault | separate git repo on `E:`, at `2016b7e` — unchanged this session |
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
run makes one such call per section plus three whole-note round-trips, and
section concurrency has now gone from 3 to 6.

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
place. Parity is at 22.

### 3. Concurrency — DONE. The rest of task 3 — NOT DONE

Section concurrency was hardcoded to `3` in five places. There is now one
`MAX_CONCURRENCY_DEFAULT = 6` in `avicenna/settings.py`, resolved through
`resolve_concurrency()` with the usual precedence (CLI → `AVICENNA_CONCURRENCY`
→ vault `max_concurrency` → default) and clamped to `[1, 16]`, because every
concurrent section is a live call against a rate-limited provider and an
unbounded value turns a config typo into a 429 storm.

---

## The one open task

**Deterministic assembly, structural fidelity.** The target is the note the user
pointed at as the fidelity benchmark, written by the original Gemini CLI
version. Measured: 7,882 words, 12 numbered `###` headings, a TOC callout whose
anchors match exactly, 2 horizontal rules, 13 blockquotes, 11 tags including 4
entities, and **0 external wikilinks**.

That last number is the important one. **Interconnectivity in this vault is
entity-driven through tags, not wikilink-driven.** Do not chase link counts.

Work in scope:

- Make assembly deterministic. The run still does **two** whole-note model
  round-trips — weaver and formatter — which are the slowest and buggiest
  part of it. A comparable project the user showed does assembly in pure
  Python; its assembler imports no LLM client at all.
- Numbered `###` headings; a Python-generated TOC callout with exactly-matching
  anchors; strip repeated headings; demote stray top-level headings.
- Restore the `[Table]` / `[Mermaid Diagram]` section forms in preflight — the
  benchmark's plan declared them (`#6. [Table] Comparative Matrix...`,
  `#9. [Mermaid Diagram] The Architecture of Revelation...`).

Note the interaction with what just landed: removing model round-trips removes
`_write_back` call sites, and `_write_back` is now also a normalisation point.
Do not drop the normalisation when you drop the round-trip.

---

## Rules learned the hard way

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
- **`master` is 10 commits ahead of `origin/master` and has not been pushed.**
- Decide whether to keep the `_themeCounts` / `_typeCounts` keys a subagent
  added to `taxonomy.json` against instruction.
- Optionally add `paintings_source` to `excludeFromDerivation`.
- Optionally drop the `- - -` separator from the weaver template at
  `.agents/agents/weaver.md:121` in the vault. Less urgent now that the
  normaliser collapses rules on every write.
