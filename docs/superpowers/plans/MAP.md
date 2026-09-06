# MAP: docs/superpowers/plans/

> Implementation plans, one per approved spec. A plan turns a design into
> bite-sized tasks an engineer with no context can execute in order: exact files,
> exact test code, exact commands, and a commit at the end of each task. Plans
> are written before implementation and are not updated to match code that later
> drifts — the spec argues, the plan sequences, the code is the truth.

**Depends on:** the spec each plan implements · **Depended on by:** nothing at runtime
**Reads:** nothing · **Writes:** nothing

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `2026-09-06-layered-configuration.md` | 631 | Eight tasks turning the hardcoded harness into a tunable engine: a `Settings` resolver with one precedence chain, a registry populated from the existing constants so they become defaults rather than values, a vault-scoped `.agents/config.json`, the provider and model resolution fix, the `avicenna config` command group, per-run flags on `note`, vault-derived probe topics, and vault-owned contract tokens and note placement. |
<!-- map:files:end -->

## Invariants

- A plan names exact files and exact test code. "Add appropriate error handling"
  or "write tests for the above" is a plan failure, not a shortcut — the
  executor may be a fresh agent with no context and no way to infer intent.
- Every task ends with a commit, so a partially executed plan leaves the tree in
  a working state rather than half-applied.
- Each task's `Interfaces` block names the signatures its neighbours rely on,
  because an executor sees only its own task.

## Entry points

- To execute a plan, use `superpowers:subagent-driven-development` (a fresh
  agent per task, reviewed between tasks) or `superpowers:executing-plans`.
- To write one, use `superpowers:writing-plans` after a spec is approved.

## See also

- `../specs/MAP.md` — the designs these plans implement
- `../../../MAP.md` — state of the world
