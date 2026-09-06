# MAP: avicenna/pipeline

> The pipeline turns a topic into a note. It is the only module that writes to
> the vault. Every stage is a class; `build_stages()` returns the ordered list;
> `PipelineRunner.run()` walks it. The critical design commitment lives here:
> each heading gets a fresh `one_shot()` with no shared context, because a
> shared session degrades every section after roughly the third. This descends
> from the project's origin as a Gemini CLI script that spawned a separate
> headless process per heading. The runner never asks the model whether a step
> worked — it branches on regex-parsed contract tokens returned by vault tools.

**Depends on:** `avicenna/providers` · `avicenna/session` · `avicenna/tools` · `avicenna/vault` · `avicenna/bus` · `avicenna/events` · `avicenna/concurrency`
**Depended on by:** `avicenna/cli` · `avicenna/bridge` · `avicenna/chat`
**Reads:** vault `_tmp/` for chunks and manifests · vault taxonomy for MOC policy
**Writes:** vault domain folders (the finished note, atomically) · `_tmp/` sidecars (manifest, chunks, `last_run.json`)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `__init__.py` | 8 | Public surface: re-exports `RunSpec`, `RunContext`, `PipelineStage`, `PipelineRunner`, `PipelineAbort`. |
| `context.py` | 83 | `RunSpec` (frozen inputs: topic, vault, provider, run flags) and `RunContext` (mutable state accumulated by stages). Keeping them separate means a stage can only corrupt the mutable half. |
| `delegate.py` | 52 | Agent delegation: loads a named agent's body as the system prompt and calls `one_shot()`. `tools_for_agent` enforces MCP opt-in per agent through the `mcp:` frontmatter key so a tool the agent did not declare cannot be selected. |
| `preflight.py` | 130 | JSON-first pre-flight parser. Asks the agent for a fenced `json` block; falls back to regex over prose with a warning. Validates heading count (1–40), enforces template word floors, and derives filesystem-safe slugs. |
| `resume.py` | 162 | Manifest sidecars and the `last_run.json` pointer. Manifests are always written in Python — never only by an optional PowerShell tool — so resume works in vaults with zero `.ps1` tools. `plan_sections` returns the indices of chunks missing or incomplete. |
| `run.py` | 83 | `execute_run` is the single entry point for a generation run. Builds the `RunSpec`/`RunContext` pair, emits `RunStarted` and `RunComplete`, and hands `build_stages()` to `PipelineRunner`. Owns the dry-run filter — `DRY_RUN_STAGES` is `{routing, preflight}`, selected by stage `id` rather than `name`, because several stages share a label and a label filter would silently enrol any future stage that reused one. Also owns the cancellation contract: on `CancelledError` it re-raises without emitting, since `PipelineRunner` has already emitted `RunFailed` with the stage attributed, and leaves `_tmp/` intact so `--resume` can pick the run back up. |
| `sections.py` | 123 | Parallel section fan-out. Builds one closure per heading through `gather_sections`. Each task calls `one_shot()` for fresh context, retries once on exception or empty output, and Python (never the model) writes `_tmp/[slug]_chunk_NN.md`. |
| `stage.py` | 89 | `PipelineStage` ABC and `PipelineRunner`. Defines the two-identifier contract: `name` (shared, user-facing label) and `id` (unique; timings, completion records and the dry-run filter key on it). The runner owns `StageEntered`/`StageCompleted` emission and translates `PipelineAbort` and `CancelledError` into `RunFailed`. |
| `stages.py` | 802 | All 14 stage implementations plus `build_stages()`. Contains the write-back guard (`_write_back`), the frontmatter pipeline, the atomic note writer, and every vault-tool call with its graceful-degradation fallback. The bulk of pipeline logic lives here. |
| `toolcall.py` | 27 | Thin wrapper that emits `ToolInvoked`/`ToolReturned` around every vault tool call. The pipeline never invokes a tool directly; it goes through here so the event bus sees it. |
<!-- map:files:end -->

## Invariants

- A stage has **two identifiers**. `name` is the `Stage` literal on the wire; multiple stages may share it (resume, routing, and pre-flight all carry `"preflight"`). `id` is unique and is the key for timings, completion records and the dry-run filter. When adding a stage, give it its own `id`.
- **Contract tokens gate the pipeline, never the model's narration.** Vault tools return tokens like `MANIFEST_WRITTEN`, `ALL_PRESENT`, `WORDCOUNT_FAIL`, `PASS`. The stage regex-matches against those tokens. A model saying "that worked" is not evidence.
- **Every vault tool call degrades gracefully and says so.** A vault may ship zero PowerShell tools. When a tool is absent the stage falls back to Python or skips, and emits a `LogMessage` warning — never silent degradation.
- **Only the pipeline writes to a note.** `_write_back` guards every post-assembly revision (formatting, linking). It rejects output that drops below 75% of the current note on disk, so a model that truncates or answers conversationally cannot overwrite a finished note.
- **Sections get fresh context, always.** Each heading runs through `one_shot()` with no accumulated history. The session transcript is a log, not a conversation. Never share a session across headings — quality degrades monotonically after ~3 sections.
- **Chunks are written atomically** (`.part` sibling plus `os.replace`) so resume can trust them. A surviving `.part` file means the write was interrupted and the chunk is discarded.
- **`_tmp/` is not cleaned until `CleanupStage`,** the last stage. Deleting chunks earlier made a crash between assembly and cleanup permanently unrecoverable because the resume inputs would be gone.

## Stage sequence

```
resume → routing → preflight → manifest → sections → assembly
→ wordcount → toc → tagging → tags_written → formatting
→ linking → moc → cleanup
```

IDs in order: `resume`, `routing`, `preflight`, `manifest`, `sections`, `assembly`, `wordcount`, `toc`, `tagging`, `tags_written`, `formatting`, `linking`, `moc`, `cleanup`.

Resume runs first so it can recover domain, slug and headings; routing then honours the recovered domain instead of re-deciding. Tags-written is a separate stage from tagging because the tagger proposes tags to the validator but only `TagsWrittenStage` puts them into the note's frontmatter.

## Entry points

- To change the stage list or add a new stage, start at `stages.py:761` (`build_stages()`).
- To change the write-back guard that protects a finished note from model truncation, start at `stages.py:144` (`_write_back`).
- To change how a run is started, or the dry-run stage filter, start at `run.py:25`
  (`execute_run`).
- To change how cancellation or failure is handled, start at `stage.py:65`
  (`PipelineRunner.run`), then `run.py:71` for the re-raise contract.
- To change section parallelism, retry logic, or the per-heading prompt, start at `sections.py:120` (`generate_sections`).
- To change what a stage does, identify its class in `stages.py` and read its `run` method; the class docstring and the surrounding comments record the defect the current design exists to prevent.

## See also

- `../vault/MAP.md` — routing and agent/taxonomy validation that precedes the pipeline
- `../tools/MAP.md` — `ToolRegistry`, contract parsing, and the tool-runner protocol the pipeline calls
- `../providers/MAP.md` — the LLM provider abstraction that `one_shot()` delegates to
