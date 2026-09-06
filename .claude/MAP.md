# MAP: .claude/

> Claude Code local settings for this repository. Contains only per-session
> skill overrides; repo-wide agent instructions live in `CLAUDE.md` and
> `AGENTS.md` at the root, not here.

**Depends on:** nothing · **Depended on by:** Claude Code sessions in this repo
**Reads:** nothing · **Writes:** nothing

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
<!-- map:files:end -->

The inventory above is deliberately empty. The only file here,
`settings.local.json`, is per-developer Claude Code configuration that is
gitignored by design: the rule ships in the user-level git ignore file, so the
file is invisible to `git status` in every clone. The map gate derives its
inventories from `git ls-files`, so a row naming that file would fail parity on
every run. The directory still keeps a map, so that the one-map-per-directory
rule holds without exception — and so this paragraph explains why the table is
bare, rather than leaving the next reader to rediscover it.

## Invariants

- Repo-wide agent instructions are in `CLAUDE.md` and `AGENTS.md` at the
  repository root. This directory holds only local Claude Code session config.

## Entry points

- To change which skills are suppressed, edit `settings.local.json` — it is
  local to your clone and will not appear in `git status`.

## See also

- `../CLAUDE.md` — operational rules for Claude Code in this repository.
- `../AGENTS.md` — the canonical doctrine document.
