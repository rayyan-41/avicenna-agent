# MAP: tui/test/

> Frontend tests, run by `bun test`. The suite that lived here before the
> 2026-09-09 rewrite covered the deleted Node skeleton — key decoding, display
> width, command parsing — and went with it. What is here now tests the wire
> layer, which is the part that can be exercised without a terminal.

**Depends on:** `bun:test`, `tui/src/bridge/` · **Depended on by:** nothing
**Reads:** nothing · **Writes:** nothing

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `translate.test.ts` | 158 | The event translator. Asserts the outline fills from `PreflightDeclared`, that a completion cannot disturb its neighbours, and that a section completing without a declared outline is appended rather than dropped — which is what a resumed run actually replays. One test asserts a *zero*: reading `targetWords` instead of `target_words` would give undefined and render as 0 without failing anything, so the camelCase spelling is pinned to prove the snake_case one is load-bearing. Also separates what reaches the transcript from what does not: tool traffic and debug logs stay out, warnings surface. |
<!-- map:files:end -->

## Invariants

- Tests import from `src/` directly. Bun runs TypeScript, so there is no build
  step between the source and the test, and no `dist/` for the suite to go
  stale against — which is how the old suite could pass while testing a
  previous compile.
- The wire is `snake_case`. Any test that writes a payload by hand must use
  Python's field names, or it proves nothing.

## Entry points

- `bun test` from `tui/`.

## See also

- `../src/bridge/MAP.md` — what these tests cover
