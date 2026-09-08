# MAP: docs/

> User-facing documentation root. The only current live document is the MCP
> configuration guide and, while work is in flight, `HANDOFF.md`; everything
> else has been archived as historical record
> or lives in the `superpowers/specs/` design-spec tree. This is not where
> doctrine lives — that is `AGENTS.md` and `CLAUDE.md` at the repository root.

**Depends on:** nothing · **Depended on by:** users and agents seeking operational guidance
**Reads:** nothing · **Writes:** nothing

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `MCP_GUIDE.md` | 208 | How to configure MCP servers: the three transports (node, python, executable), the `~/.avicenna/mcp_config.json` schema, `avicenna mcp test/list/tools` CLI, and the security boundary that an MCP server is arbitrary code with tool access. |
| `HANDOFF.md` | 205 | Transient state-of-the-work note for a session starting cold: the three open tasks (API timeouts, wiring the normaliser, deterministic assembly), the working-tree rule that followed a data-loss incident, defects not to reintroduce, and what is unwired on purpose. Deleted once its tasks land. |
<!-- map:files:end -->

## Subdirectories

- **archive/** — Superseded guides and the version history. Useful for
  understanding past decisions but not current truth; each file warns that
  behaviour it describes may have changed. Has its own `MAP.md`.
- **superpowers/specs/** — Design specifications (approved proposals):
  `2026-09-06-map-context-tree-design.md`, the format contract for the `MAP.md`
  context-tree system; `2026-09-07-vault-sovereignty-and-emergent-taxonomy-design.md`,
  which gives the vault authority over structure and the harness authority over
  generation and cohesion only; and `2026-09-07-terminal-interface-design.md`,
  designed but not yet built.

## Invariants

- Doctrine lives in `AGENTS.md` and `CLAUDE.md` at the repository root, not
  here. This directory holds operational guides, not architectural law.
- Any agent reading `archive/` documents must treat them as historical — the
  code, not the docs, is the source of current truth.

## Entry points

- To change MCP configuration guidance, start at `MCP_GUIDE.md:1`.

## See also

- `../AGENTS.md` — doctrine, architecture, and the six commitments.
- `../CLAUDE.md` — operational rules for coding agents.
