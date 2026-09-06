# MAP: docs/archive/

> Historical documentation from earlier phases of the project. These files
> describe behaviour and architecture that may have been superseded by the
> current harness design. They are preserved so an agent or contributor can
> trace *why* a decision was made, not *what the system does today*. Treat
> every claim here as potentially stale unless corroborated by source.

**Depends on:** nothing · **Depended on by:** nothing
**Reads:** nothing · **Writes:** nothing

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `AVICENNA_VERSION_HISTORY.md` | 1081 | Full changelog from v0.1.0 (Gemini API wrapper) through v2.0.0 (MCP ecosystem). Useful for understanding the project's evolution, the motivation behind architectural decisions (async conversion, MCP migration, project reorganisation), and the sequence of features that existed before the harness rewrite. Describes a pre-harness codebase that no longer exists in this form. |
| `MCP_ECOSYSTEM_MIGRATION.md` | 424 | The original migration plan from custom MCP servers to official ecosystem servers. Covers the five-phase strategy, schema changes, and server catalog. Still useful as a reference for which MCP servers were considered and why, but the implementation it describes was for a prior architecture. |
| `MCP_TOOLS_GUIDE.md` | 644 | Inventory of MCP tools available in v2.0 — filesystem, sequential thinking, SQLite, Git, GitHub, Google Workspace, plus recommended optional servers. Useful for understanding what the pre-harness system could reach via MCP and for evaluating which servers might be worth configuring in the current harness. Some package names and setup instructions may be outdated. |
<!-- map:files:end -->

## Invariants

- Every file in this directory is historical. An agent must not treat any
  claim here as current truth without checking the source code.
- The literal string for the reference vault appears in
  `AVICENNA_VERSION_HISTORY.md`; this is acceptable because the file is
  historical context, not harness code.

## Entry points

- To understand how Avicenna arrived at its current architecture, start at
  `AVICENNA_VERSION_HISTORY.md:1`.

## See also

- `../MCP_GUIDE.md` — the current, maintained MCP configuration guide.
- `../../AGENTS.md` — the doctrine that replaced the conventions described here.
