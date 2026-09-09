# MAP: tui/src/

> The runtime source for the Avicenna terminal frontend, mid-rewrite. The
> Node-and-npm skeleton was deleted on 2026-09-09 and is being replaced by a
> Bun, OpenTUI and React 19 interface per
> `docs/superpowers/specs/2026-09-09-conversational-terminal-interface-design.md`.
> Only the wire layer exists so far; the render layer lands with stage 1 of that
> spec's sequencing.

**Depends on:** `@opentui/core`, `@opentui/react`, `react` · **Depended on by:** `avicenna/cli/app.py` spawns the built entry point
**Reads:** stdin (via OpenTUI), child-process stdout · **Writes:** stdout (the rendered frame)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
<!-- map:files:end -->

## Subdirectories

- `bridge/` — the wire contract and the event translator. Pure; no renderer.

## Invariants

- Nothing outside `bridge/` knows what a child process is, and nothing inside
  it knows what a transcript is. The old frontend held this line and the
  rewrite keeps it.
- The interface never decides control flow that belongs to the harness.
  Intent routing is deterministic and lives in Python (`avicenna/intent.py`),
  so no model and no frontend heuristic decides whether the pipeline runs.
- Only the pipeline writes to a note. The chat surface holds read-only tools
  and cannot change the vault.

## Entry points

- `index.tsx` is the entry point once it exists: it parses argv, spawns the
  bridge, and hands the terminal to OpenTUI.
- To change what an event looks like on screen, start at
  `bridge/translate.ts` — it decides what an event *means* before anything
  decides how it looks.

## See also

- `bridge/MAP.md` — the wire layer
- `../MAP.md` — the frontend package
- `../../docs/superpowers/specs/2026-09-09-conversational-terminal-interface-design.md` — what is being built and why
