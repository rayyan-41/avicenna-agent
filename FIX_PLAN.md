# Avicenna 1.0.1 — Fix Plan

Remediation plan for the defects found in the v1.0.0 audit. Ordered so the harness
becomes usable as early as possible: Phase A alone restores end-to-end generation.

**Baseline:** `v1.0.0` (tag), master @ `4f57aec`. 57 modules, 5,102 lines, 42/45 tests passing.

| Phase | Title | Unblocks |
|---|---|---|
| A | Routing repair | **A working agent.** Nothing runs without this. |
| B | Zero-tool vault degradation | `avicenna init` vaults can generate |
| C | Provider layer hygiene and types | Neutral layer, `mypy --strict` |
| D | Quick correctness fixes | Tests actually run, dead flags wired |
| E | Tooling, CI, and release | Regression safety, `v1.0.1` |

---

## Phase A — Routing Repair

### Goal
Replace the noise-driven scorer with a deterministic, explainable one, and lock it down
with a labelled regression suite. Routing is stage 1; when it is wrong every downstream
stage is wrong, and nothing currently catches it.

### The three defects being fixed

1. **Substring matching.** `sum(1 for w in desc_words if w in text_lower)` tests substrings,
   not words. Measured: `michelangelo` scored 4 on `['de','for','on','or']` against
   "how transformer attention works in large language models" (mo**de**ls, trans**for**mer,
   attenti**on**, w**or**ks), beating `haytham` at 3 on the same junk. The winner was noise.

2. **Kebab-case vocabulary can never match prose.** 24 of 49 themes contain a hyphen
   (`machine-learning`, `islamic-golden-age`). Scoring splits the request on whitespace, so
   a theme matches only if the user types the hyphen literally.

3. **Themes do not discriminate.** `themes = [t.lower() for t in vault.taxonomy.themes]` is
   the *entire flat list*, evaluated identically inside every agent's loop. A theme hit adds
   the same score to all six domains, so the strongest intended signal contributes exactly
   nothing to the decision.

### Design

**Normalise both sides.** Lowercase, replace `-` and `_` with spaces, strip punctuation,
tokenise on word boundaries. Generate unigrams **and bigrams** from the request, so
"machine learning" matches the theme `machine-learning` after normalisation.

**Build a per-domain vocabulary**, each term carrying a weight:

| Source | Weight | Rationale |
|---|---|---|
| Domain name (`history`, `islam`) | 4.0 | Explicit and unambiguous |
| Categories for that domain | 3.0 | Closed set, domain-scoped |
| Themes observed on that domain's notes | 2.0 | Data-derived, genuinely discriminating |
| Content words from the agent description | 1.0 | Weakest, stopword-filtered |

Themes are associated with domains **by scanning the vault's own notes** (tags position 3+),
not by a hardcoded map. This is self-maintaining: as the vault grows, routing sharpens.
Memoised per vault root. A vault with no notes degrades to domain plus category plus
description, which still works.

**Stopwords** are removed from descriptions. Without this the description signal is mostly
`for`, `any`, `note`, `to`, `and`.

**Decision rule.** Return the top scorer only if it clears a floor and beats the runner-up
by a margin; otherwise return `None` so the caller escalates. A single content agent wins
by default when it scores at all, which is what makes a one-agent scaffold usable.

```python
MIN_SCORE = 3.0      # at least one strong signal
MIN_MARGIN = 1.5     # must beat second place decisively
```

**Diagnostics.** Add `score_domains(vault, text) -> list[DomainScore]` exposing per-domain
score and matched terms. This is what the regression test asserts against and what
`avicenna route` prints, so a routing failure is inspectable instead of mysterious.

### Steps
1. Rewrite `avicenna/vault/routing.py`: `normalise`, `tokens_and_bigrams`, `STOPWORDS`,
   `domain_vocabulary(vault)` (memoised), `DomainScore`, `score_domains`, `route_request`.
2. Keep the `route_request(vault, text) -> AgentDef | None` signature so no caller breaks.
3. Add `avicenna route "<topic>"` CLI command printing the score table.
4. Add `tests/test_routing.py` with **at least 15 labelled topics across all six domains**,
   asserting the correct agent, plus negative cases that must return `None`.

### Acceptance criteria
- [ ] All six De Anima domains route correctly on realistic topics.
- [ ] "how transformer attention works in large language models" routes to `haytham`.
- [ ] "the ottoman empire and its balkan conquests" routes to `machiavelli`.
- [ ] "the ruling on raf al-yadayn in the four madhabs" routes to `ghazali`.
- [ ] Genuinely ambiguous input ("Test Topic") returns `None`.
- [ ] `score_domains` reports matched terms for every candidate.
- [ ] A single-content-agent vault routes to that agent.
- [ ] `pytest tests/test_routing.py` passes.

---

## Phase B — Zero-Tool Vault Degradation

### Goal
Make a vault with no PowerShell tools generate a complete note. The plan promised this
("contract gating simply has nothing to gate") and the Definition of Done requires it, but
`ManifestStage` hard-requires `write_manifest` and aborts with
`KeyError: unknown tool 'write_manifest'; known: []`.

### Design
Add `ToolRegistry.has(name) -> bool`. Every pipeline stage that calls a `.ps1` tool becomes
**degradable**: if the tool is absent, fall back to a Python equivalent or skip with a
`LogMessage`, never abort.

| Stage | Tool | Fallback when absent |
|---|---|---|
| Manifest | `write_manifest` | Skip. The manifest is telemetry plus resume state, not a gate. Emit `ManifestWritten` from `len(ctx.headings)`. |
| Sections | `update_pipeline_state` | Already best-effort |
| Assembly (verify) | `verify_chunks -Mode verify` | Python checks `ctx.chunk_paths` against expected indices. Python wrote them, so it can verify them. |
| Assembly (read) | `verify_chunks -Mode read` | Python reads the chunk files and emits the same `<!-- CHUNK NN START/END -->` markers |
| Assembly (cleanup) | `cleanup_chunks` | `Path.unlink()` the chunks and sidecars |
| Word count | `validate_wordcount` | Count in Python, compare to `TEMPLATE_MINIMUMS` |
| ToC | `generate_toc` | Skip with a log line |
| Tagging | `validate_tags` | Accept the agent's tags unvalidated, log that validation was skipped |
| Linking | `get_related_notes` | Skip, emit `LinkCandidatesFound(count=0)` |
| MOC | `update_moc` | Skip |

The degraded path must be **visible**: every skip emits `LogMessage(level="warning")` naming
the missing tool, so a user never silently gets a lesser note without knowing.

### Acceptance criteria
- [ ] `avicenna init <tmp>` then a full run against `FakeProvider` reaches `RunComplete` and writes a note file.
- [ ] The De Anima vault (15 tools) still uses every real tool; no behaviour change.
- [ ] Each degraded stage emits a warning naming the absent tool.

---

## Phase C — Provider Layer Hygiene and Types

### Goal
Make `avicenna.providers` importable without a vendor SDK, and get `mypy --strict` clean on
`avicenna/providers` and `avicenna/pipeline`.

### Design
`avicenna/providers/__init__.py` eagerly does `from avicenna.providers.mistral import
MistralProvider`, which pulls `mistralai` into `sys.modules` on any import of the package.
Verified: `import avicenna.providers` → `'mistralai' in sys.modules` is `True`, and on a
Python without the SDK `import avicenna.cli.app` fails outright.

Replace with a module-level `__getattr__` (PEP 562) so `MistralProvider` resolves lazily on
first attribute access. The registry already constructs providers by name, so it imports
inside the factory rather than at module scope.

Then fix the 74 `mypy --strict` errors, concentrated in `mistral.py`. The substantive ones
are the wire-message list typed `list[UserMessage]` receiving `AssistantMessage` and
`ToolMessage` (lines 162, 164), and `Completion.text` receiving `str | Any | Unset | None`.

### Acceptance criteria
- [ ] `import avicenna.providers` leaves `mistralai` out of `sys.modules`.
- [ ] `get_provider("mistral", ...)` still works.
- [ ] `mypy --strict avicenna/providers avicenna/pipeline` exits 0.
- [ ] Full test suite still passes.

---

## Phase D — Quick Correctness Fixes

| # | Fix |
|---|---|
| D1 | Add `[tool.pytest.ini_options] asyncio_mode = "auto"` to `pyproject.toml`. Three async tests in `test_providers.py` have no marker and never run. |
| D2 | Wire `--resume`: `execute_run()` has no `resume` parameter, so the CLI flag is accepted and silently ignored. Thread it through to `SectionsStage` via `RunSpec.resume` and the existing `resume.py` helpers. |
| D3 | Delete `avicenna/core.py` (200 lines) and `avicenna/main.py` (128), the legacy Gemini chatbot. Only `main.py` imports `core.py`; nothing imports `main.py`. |
| D4 | Accept `avicenna init --vault PATH` as well as the positional form, for consistency with every other command. |
| D5 | Scaffold `.agents/mcp.json` in `init_vault`, which the plan specified and the implementation omitted. |

---

## Phase E — Tooling, CI, and Release

| # | Fix |
|---|---|
| E1 | `avicenna mcp test [name]` — connect one server (or all) in isolation and print the real error. The one subcommand that surfaces connection failures is missing. |
| E2 | `.github/workflows/ci.yml` on `windows-latest`: pytest, `mypy --strict`, and the TUI blocking-call lint. Nothing currently enforces any of it. |
| E3 | Rename the De Anima Reason agent `avicenna` to `rousseau` (vault-side), resolving the name collision. Requires updating frontmatter, `AGENTS.md`, and re-running `audit_skill_sync.ps1`. |
| E4 | End-to-end verification against the real vault, then tag and push `v1.0.1`. |

---

## Execution notes

- Phase A is done first and alone, because nothing is testable until routing works.
- Phase C (providers) and Phase E1/E2 (tooling) touch disjoint files and are parallelisable.
- Every phase ends green: `pytest` passing before the commit.
- Commit per phase, push at the end of A (usable) and at the end of E (released).
