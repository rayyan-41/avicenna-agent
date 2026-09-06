# MAP: tui/test/

> The test suite for the Avicenna terminal frontend. Three files covering the
> three modules that have deterministic, pure-function behaviour worth
> asserting: command parsing, key decoding, and text measurement. The heavier
> modules (app, bridge, screen) are integration-tested through the backend
> smoke test in CI rather than with unit stubs.

**Depends on:** compiled JS in `../dist/` (tests import from `../dist/`, not `../src/`), `node:test`, `node:assert/strict` · **Depended on by:** CI `tui` job
**Reads:** nothing from disk · **Writes:** nothing (test-only)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `commands.test.mjs` | 65 | Tests command detection, parsing (name/args/argv), argument casing, the prefix-first completion order, hidden-command exclusion from the palette, and the invariant that every command has a summary. |
| `keys.test.mjs` | 79 | Tests raw-mode decoding: printable characters, CSI arrow sequences, tilde codes (delete, page up/down), modifier parameters (ctrl+right, shift+up), shift+tab, C0 control characters back to their letter, enter/tab/backspace naming, bare escape, bracketed paste arriving as one key with the `paste` flag, and astral codepoints surviving as a single key. |
| `text.test.mjs` | 65 | Tests display-width measurement: escape sequences as zero width, CJK as two columns, combining marks as zero, `padEnd`/`center` at display width, truncation within budget, word-wrap with hard-break for overlong words, and blank-line preservation between paragraphs. |
<!-- map:files:end -->

## Invariants

- **Tests are `.mjs`, not `.ts`.** They import the compiled output from `../dist/` directly, which means `npm test` builds first (`tsc -p tsconfig.json`) and then runs `node --test "test/*.test.mjs"`. A type error in the source will fail the build step before any test executes.
- **Tests use `node:test` and `node:assert/strict`.** No external test runner. Node >= 18 is required for `node:test` stability.
- **Every test file mirrors a source module.** `commands.test.mjs` covers `commands.ts`, `keys.test.mjs` covers `keys.ts`, `text.test.mjs` covers `text.ts`. Modules like `app.ts`, `bridge.ts`, and `screen.ts` have no unit tests — they are exercised through the backend bridge smoke test in the CI `build` job.

## Entry points

- To add a command-parsing assertion, edit `commands.test.mjs`.
- To add a key-decoding case, edit `keys.test.mjs`.
- To add a width or wrapping case, edit `text.test.mjs`.

## See also

- `../src/MAP.md` — the source modules under test.
- `../MAP.md` — build scripts and the CI `tui` job that runs `npm test`.
