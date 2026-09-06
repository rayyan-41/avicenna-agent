# MAP: tui/

> The TypeScript terminal frontend for Avicenna. Owns the screen, every
> keystroke, and the pipe to the Python backend — but no agent logic. The
> interface is intentionally a skeleton: no palette, no glyph set, no wordmark,
> no boxes, no overlays, no Markdown styling. That is a deliberate state enforced
> by a CI gate, not an unfinished migration. A design pass must be a new layer
> on top of the skeleton, not a restoration of deleted chrome.

**Depends on:** Node >= 18, `typescript` + `@types/node` (dev only) · **Depended on by:** `avicenna` CLI (`tui/src/main.ts` launched via `node dist/main.js`)
**Reads:** stdin (raw keys), child-process stdout (NDJSON from `python -m avicenna.bridge`), `process.stdout` rows/cols · **Writes:** stdout (alt-screen frames), stderr (crash diagnostics)

## npm scripts

| Script | What it does |
| --- | --- |
| `build` | `tsc -p tsconfig.json` — emits `dist/` |
| `watch` | `tsc --watch` |
| `typecheck` | `tsc --noEmit` — no output, just type errors |
| `test` | builds first, then `node --test "test/*.test.mjs"` |
| `start` | `node dist/main.js` |
| `clean` | deletes `dist/` |

CI runs the TUI job on `ubuntu-latest`; the Python job runs on `windows-latest`.

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `package.json` | 26 | Package manifest; declares `type: module`, `bin`, scripts, and the two dev dependencies (`typescript`, `@types/node`). Zero runtime deps. |
| `package-lock.json` | 53 | Lockfile for deterministic `npm ci` in CI. |
| `tsconfig.json` | 22 | Compiler config: `ES2022` target, `NodeNext` modules, `strict` + `noUncheckedIndexedAccess` + `noFallthroughCasesInSwitch`, `rootDir: src`, `outDir: dist`. |
| `README.md` | 92 | Module map, build instructions, design notes, the seam list where a visual layer attaches, and the protocol for adding an event. |
<!-- map:files:end -->

## Subdirectories

- `src/` — all runtime source; see [`src/MAP.md`](src/MAP.md).
- `test/` — the test suite; see [`test/MAP.md`](test/MAP.md).
- `dist/` — compiler output, generated, gitignored. Do not edit or map.

## Invariants

- **The UI is a skeleton and must stay that way until a deliberate design pass.** CI gate "Frontend stays unstyled" (`ci.yml`) runs `grep -rnE` for raw SGR escapes (`\x1b[...m` and `\u001b[...m`) in every `.ts` file under `tui/src/` and fails if any match outside `ansi.ts`. All colour encoding lives in that one file; the rest of the skeleton emits no escape codes. Reintroducing styling is not a bugfix — it is an architectural decision that must be made as a new layer.
- **stdout belongs to the wire protocol.** The backend redirects `sys.stdout` to stderr and writes NDJSON frames to a private handle. The frontend writes only alt-screen sequences to stdout. One stray `console.log` desyncs the frame parser.
- **Protocol parity with the backend is enforced.** `scripts/check_protocol_parity.py` fails the build if an event dataclass in `avicenna/events.py` has no matching name in `src/protocol.ts`, or vice versa.
- **Strict TypeScript.** `noUncheckedIndexedAccess`, `noFallthroughCasesInSwitch`, and `noImplicitOverride` are all on. `exactOptionalPropertyTypes` is off because it interacts badly with protocol types.
- **No runtime dependencies.** The package declares only `devDependencies`. Everything shipped is hand-written.
- `tui/` is its own toolchain and gets its own CI job; it is never bolted onto the Python one.

## Entry points

- To change what the screen looks like, start at `src/app.ts:1067` (`render()`).
- To change what events are displayed, start at `src/app.ts:903` (`onEvent()`).
- To change how the backend is spawned, start at `src/bridge.ts:101` (`start()`).
- To add a new event: dataclass in `avicenna/events.py`, name in `src/protocol.ts:39`, case in `src/app.ts:917`.

## See also

- `src/MAP.md` — the ten source modules and how they compose.
- `test/MAP.md` — the three test files.
- `CLAUDE.md` — doctrine on the skeleton, the `never` exhaustiveness check, and the seam list.
