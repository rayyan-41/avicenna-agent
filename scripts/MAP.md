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
| `check_maps.py` | 427 | Gates the MAP.md tree. Enforces three properties: every tracked directory holding source has a MAP.md; the filename set inside a map's marker block equals that directory's tracked source files exactly; and no row carries an unwritten placeholder. A marker counts only when alone on its line, so a map may explain the convention in prose without tripping the duplicate check. `--fix` adds rows for new files and refreshes line counts, but writes a placeholder role deliberately, so a mechanical fix can never satisfy the gate on its own. |
| `check_protocol_parity.py` | 94 | Parses `avicenna/events.py` with `ast` to find every concrete `Event` subclass, regex-extracts the `EventName` union members from `tui/src/protocol.ts`, and regex-extracts handled cases from `tui/src/app.ts`. Fails the build if any event name exists in one file but not the other, or is declared but unhandled. |
| `gen_matrix.py` | 676 | The live generation matrix: one ~1000-word note per domain agent, against a real vault with a real provider. Refuses to run without `--yes`, refuses outright if the vault's git tree is dirty, and prints the revert commands before generating so they exist even if the process is killed. Reads git state and never mutates it — deciding what to keep is the vault owner's call. Asserts per cell: note on disk, word floor, frontmatter parses, tags within the closed taxonomy, wikilinks resolve, MOC updated. Cells run sequentially and a failure leaves its artefacts in place. |
| `healthcheck.py` | 866 | Eight independent probes behind `avicenna doctor`: config and vault resolution, provider reachability, vault load, tool registry, vault PowerShell tools, MCP servers, all bridge methods, and routing. Each catches its own exceptions so one failure cannot mask the rest. WARN and SKIP never affect the exit code — a vault with no `.ps1` tools and a config with no MCP servers are both legitimate. The tool probe executes only read-only tools and asserts the declared contract token parses, which is the only place a tool returning prose instead of its token would be noticed; the bridge probe never sends `run.note`. |
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
