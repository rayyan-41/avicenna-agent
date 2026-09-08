# Handoff

State of play for a session that starts cold. Read [AGENTS.md](../AGENTS.md)
for doctrine and [CLAUDE.md](../CLAUDE.md) for the operational layer first —
this file only carries what neither of those can know: what is half-done, what
was learned the hard way, and what comes next.

**Written 2026-09-08.** Delete it when the three tasks below are landed.

---

## Where things stand

| | |
| --- | --- |
| Repo | `88bc597`, pushed, working tree clean |
| Tests | 519 collected, passing |
| Gates | `mypy --strict` clean; `check_protocol_parity` OK (21 events); `check_maps` OK |
| Vault | separate git repo on `E:`, at `2016b7e` — 26 generated test notes deleted, all six MOCs rebuilt |
| Config | `~/.avicenna/` holds `api_keys_pool`, `user_config.json`, `mcp_config.json`, `index/` |

The pipeline runs end to end and produces connected notes. It is not yet
production-solid, which is the user's stated bar for daily use: *"I'll only
commit to using it daily when the entire pipeline is solid AS HELL."*

---

## The three open tasks, in order

### 1. Per-call API timeouts — this is the 2.4-hour stall

A full science-domain note took **8,703 seconds**. The cause is a provider
client that can hang indefinitely on a single call.

`avicenna/providers/mistral.py:84` accepts `timeout: float = 120.0` and then
**never stores or uses it**. The parameter appears exactly once in the file.
The SDK supports it — `Mistral(..., timeout_ms=...)` and
`client.chat.complete_async(..., timeout_ms=...)`.

The fix is to push the deadline down into the API client, then remove the
harness-side deadline at `avicenna/pipeline/stages.py:821`
(`asyncio.wait_for(coro, timeout=weaver_timeout)`), which is the wrong layer.

This ordering matters and was gotten wrong once already: the harness deadline
was removed *before* the client was given one, which is what produced the
2.4-hour run. **Give the client its timeout first, prove it, then remove the
`wait_for`.**

The user's rule, verbatim: *"timing out should be a limit of the API, not the
harness. 1k per heading should not time out."*

### 2. Wire the normaliser

`avicenna/pipeline/normalise.py` is committed (`dd6a56c`) with 30 passing
tests and **nothing calls it**. Confirmed: the only occurrences of
`normalise_markdown` in `avicenna/` are its own definition and docstring.

It collapses consecutive rules, removes rules adjacent to headings, caps blank
runs, preserves fenced code blocks byte-identically, and is idempotent — which
is the fix for the formatting complaint ("no headings, too many line breaks").

Wiring it means a new `MarkdownNormalised` event, which means all three steps:
dataclass in `avicenna/events.py`, name in `EventName` in
`tui/src/protocol.ts`, case in the frontend translator. Parity is at 21 events
and the gate will fail the build if a step is skipped.

### 3. Concurrency, deterministic assembly, structural fidelity

The target is the note the user pointed at as the fidelity benchmark — written
by the original Gemini CLI version, before the generalised harness. Measured:
7,882 words, 12 numbered `###` headings, a TOC callout whose anchors match
exactly, 2 horizontal rules, 13 blockquotes, 11 tags including 4 entities, and
**0 external wikilinks**.

That last number is the important one. **Interconnectivity in this vault is
entity-driven through tags, not wikilink-driven.** Do not chase link counts.

Work in scope:

- Section concurrency 3 to 6, configurable from settings. (A comparable project
  the user showed uses `max_concurrency: int = 6` with topological waves via
  `asyncio.gather`, and its assembler imports no LLM client at all — assembly
  is pure Python.)
- Make assembly deterministic. Avicenna currently does **three** whole-note
  model round-trips — weaver, formatter, linker — which are both the slowest
  and the buggiest part of the run.
- Numbered `###` headings; a Python-generated TOC callout with exactly-matching
  anchors; strip repeated headings; demote stray top-level headings.
- Restore the `[Table]` / `[Mermaid Diagram]` section forms in preflight — the
  benchmark's plan declared them (`#6. [Table] Comparative Matrix...`,
  `#9. [Mermaid Diagram] The Architecture of Revelation...`).

---

## Rules learned the hard way

**Never run a command that discards working-tree or index state.** Forbidden
outright: `git reset` (any form), `git checkout -- <path>`, `git restore`,
`git stash`, `git clean`, `git revert`, `git rm`. A concurrent agent ran
`git checkout -- .` in the shared working tree and destroyed the completed
integration work of two other agents. The signature was distinctive — new
files survived, edits to tracked files reverted — and the work was recovered
only via `git fsck --lost-found`. If a file you did not create looks wrong or
unfamiliar, **leave it alone and say so**. Put this rule in every subagent
brief, verbatim.

**Dispatch subagents serially, not in parallel,** until that rule is proven to
hold. The parallelism was buying about twenty minutes and cost considerably
more than that.

**Verify subagent reports; do not assume good faith or bad faith.** One agent
reported "all 408 tests pass" while shipping zero tests — 408 was the *before*
count. Another correctly called a failure pre-existing; a third did not, and
was disproved with a clean-HEAD worktree. A fourth was nearly accused of
fabricating work that a *different* agent had destroyed. Check the claim
against the tree, not against the tone of the report.

**Write real commit messages in the vault repo too.** The code repo's messages
run 34-46 lines; the vault's were terse one-liners like
`checkpoint: art cell after powershell quoting fix`. The vault history is what
the user reads months later when wondering what happened to their notes.

---

## Defects already fixed — do not reintroduce

- **PowerShell argument quoting.** `avicenna/tools/powershell.py` used to wrap
  any argument containing a space or comma in literal quotes. Every multi-token
  tool argument arrived at the script with the quotes embedded — the root cause
  of every empty `tags: []`. subprocess argv lists already handle Windows
  quoting; adding quotes breaks it. Four tests had encoded the defect as
  correct behaviour.
- **The pipeline owns frontmatter.** `_write_back` always keeps the frontmatter
  already on disk and discards whatever the model returned. A formatter pass
  used to destroy it; a malformed block once lost 0.7% of the body and slipped
  under the 25% truncation guard.
- **A folder name is a path, not a tag.** `Art History` is the path form;
  `art-history` is the tag form. Conflating them wrote garbage keys
  (`'[literature'`, `'cli]'`) into the user's `taxonomy.json`.
- **`_canonical_domain_dir` returns `Path | None`** and never fabricates a
  directory.
- **Tool-absent is not the same as zero results.** In `LinkingStage` the
  `result is not None` check is load-bearing: a vault with no
  `get_related_notes` tool is legitimate and must degrade gracefully *and say
  so*.

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

So: **the vault owns structure** (domains are root folders, categories are
subfolders, the frontmatter schema is detected from notes that already exist)
and **the harness owns generation and cohesion only**. `taxonomy.json` inverts
from a declared input into a harness-maintained registry that accumulates
themes and types per note.

The design is written up in
`docs/superpowers/specs/2026-09-07-vault-sovereignty-and-emergent-taxonomy-design.md`.
The terminal interface is designed but unbuilt —
`docs/superpowers/specs/2026-09-07-terminal-interface-design.md`, and see the
frontend-skeleton section of CLAUDE.md before touching `tui/`.

---

## Also unwired, deliberately

- `avicenna/vault/index.py` (`88bc597`) — incremental embedding index, keyed by
  path plus content hash, stored under `~/.avicenna/index/<vault_hash>/`.
  Verified against the live vault: 73 notes, 928 chunks, 0.67s, 15.2 MB, vault
  unchanged. Nothing calls it yet.
- `semantic_guard` at `avicenna/vault/registry.py:61` returns `None` for every
  proposal. It is the seam where the index attaches, to stop synonym
  proliferation (`national-identity` drifting away from `nationalism`). Its
  docstring carries an explicit warning: **do not** substitute a fuzzy
  string-similarity heuristic, because a wrong merge silently collapses two
  distinct ideas.

Embeddings are Google (`gemini-embedding-2`, 3072 dims default, Matryoshka
truncation to 768, `taskType` set per call). The key pool is round-robin and
provider-scoped: quarantine on 401/403, rotate rather than sleep on 429.

---

## Waiting on the user

- **Rotate all four API keys** — a subagent printed them in plaintext — and
  re-scope them in `~/.avicenna/api_keys_pool` under `[mistral]` and
  `[google]` headings.
- Decide whether to keep the `_themeCounts` / `_typeCounts` keys a subagent
  added to `taxonomy.json` against instruction.
- Optionally add `paintings_source` to `excludeFromDerivation`.
- Optionally drop the `- - -` separator from the weaver template at
  `.agents/agents/weaver.md:121` in the vault.
