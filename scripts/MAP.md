# MAP: scripts

> Build-time hygiene checks that run in CI and fail the build on drift. These
> are not tests — they operate on source files, not runtime behaviour — but they
> enforce invariants that would otherwise decay silently: the wire protocol
> staying in sync across two languages, and the MAP.md tree staying in sync with
> the files it describes. Each script is self-contained and can be invoked
> directly with `python scripts/<name>.py`.

**Depends on:** repository source files (`avicenna/events.py`, `tui/src/protocol.ts`, `tui/src/app.ts`, every `MAP.md`) · **Depended on by:** CI `hygiene` job
**Reads:** source files to parse their structure · **Writes:** nothing (exits non-zero on failure, zero on success)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `check_protocol_parity.py` | 94 | Parses `avicenna/events.py` with `ast` to find every concrete `Event` subclass, regex-extracts the `EventName` union members from `tui/src/protocol.ts`, and regex-extracts handled cases from `tui/src/app.ts`. Fails the build if any event name exists in one file but not the other, or is declared but unhandled. |
| `check_maps.py` | ~ | Gates the MAP.md tree: enforces that every tracked directory with source files has a MAP.md, that the filename set inside the `<!-- map:files -->` markers matches the source files on disk exactly, and that no row contains an unwritten placeholder. |
<!-- map:files:end -->

## Invariants

- Neither script writes to the repository. They are read-only linters that
  fail the build by exiting non-zero.
- `check_protocol_parity.py` reads three files — `events.py`, `protocol.ts`,
  `app.ts` — and nothing else. Adding an event requires edits in all three;
  this script enforces that. The bridge itself needs no change because it
  serialises structurally (class name becomes `event`, fields become `data`).
- `check_maps.py` is wired into CI with no `continue-on-error`. Its `--fix`
  mode adds skeleton rows for new files, but an unwritten role in any row
  fails the gate — a human or agent must supply the sentence.

## See also

- `../MAP.md` — the root map that this script's output helps keep accurate
