# MAP: avicenna/vault

> Owns the vault abstraction: finding it, loading it, validating it, routing
> topics into it, and scaffolding a new one. A vault is a user's Obsidian
> directory — it carries its own protocol (the runtime orchestrator prompt in
> `AGENTS.md`), agent definitions, taxonomy, skills and tools. Nothing in this
> package writes a note; writing is the pipeline's job.

**Depends on:** `avicenna/tools/` (registry + builtin registration) · **Depended on by:** `avicenna/pipeline/`, `avicenna/cli/`, `avicenna/bridge/`
**Reads:** vault on disk (`AGENTS.md`, `.agents/` tree, `taxonomy.json`, agent `.md` files, existing notes for vocabulary) · `~/.avicenna/user_config.json` for `default_vault` · **Writes:** scaffolded vault directories on `avicenna init`

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `__init__.py` | 12 | Re-exports `Vault`, `AgentDef`, `Taxonomy`, `VaultConfigError`, `discover_vault`, `VaultNotFound`. |
| `context.py` | 148 | Rich vault-location detection: `VaultContext.detect` resolves which vault, whether cwd is inside it, and what domain/category the user is standing in as a placement hint. Parallel to `discovery.py` but returns structured context rather than a bare `Path`. |
| `discovery.py` | 54 | Minimal vault finder with four-source precedence. Used by the pipeline and CLI when only the vault root matters. |
| `init_scaffold.py` | 79 | `init_vault` scaffolds a minimal working vault: `AGENTS.md`, `taxonomy.json`, a `scribe` content agent, empty `mcp.json`, and `_tmp/.gitignore`. No PowerShell tools ship — a tool-less vault is legitimate. |
| `models.py` | 107 | `AgentDef` (parses YAML frontmatter + body from `.md`) and `Taxonomy` (loads `taxonomy.json`). Validation happens at load: frontmatter must close, `name` must match filename, content agents need a domain, pipeline agents need a stage number. |
| `routing.py` | 362 | Deterministic keyword scoring — no model call. Weights: domain 4.0, category 3.0, theme 2.5, entity 1.5, description 1.0. Gates: `MIN_SCORE` 2.5, `MIN_MARGIN` 1.0 over runner-up. Vocabulary is derived from the vault's own notes (self-maintaining). Three v1 defects fixed: substring matching let function words score, kebab-case themes never matched whitespace-split prose, and flat `themes` added the same weight to every domain. A single-agent vault skips the score gate entirely (the old `score > 0` check killed every new user's first run). |
| `vault.py` | 119 | `Vault.load` assembles the full vault from disk: reads protocol text from `AGENTS.md`, loads all agents, skills, taxonomy, registers builtin + vault PowerShell tools, then cross-validates that every content agent's domain exists in `taxonomy.json`. MCP attach is async and separate — a vault with zero MCP servers pays nothing. |
<!-- map:files:end -->

## Invariants

- **Two files named `AGENTS.md` exist and must not be conflated.** The repo-root
  one is doctrine for contributors and coding agents. The vault-root one is the
  runtime orchestrator prompt — `Vault.load` reads it into `protocol_text` and
  the model sees it at session start. The vault's `AGENTS.md` is also the
  discovery sentinel: `_looks_like_vault` checks for its presence alongside
  `.agents/`.
- Discovery precedence in `discovery.py` is strict: `--vault` flag >
  `AVICENNA_VAULT` env var > cwd walk-up > `default_vault` in
  `~/.avicenna/user_config.json`. An explicit or env source that points at a
  non-vault is an **error**, not a fallback to the next candidate.
- `VaultConfigError` is raised at load time, not mid-run. A malformed agent or
  missing taxonomy key fails immediately.
- Routing refuses to guess below its thresholds and returns `None` so the
  pipeline can escalate to the user. A wrong domain silently produces an entire
  note in the wrong voice and folder.

## Entry points

- To change how a topic maps to a domain, start at `routing.py:178` (`score_domains`).
- To change what `avicenna init` creates, start at `init_scaffold.py:63` (`init_vault`).
- To change vault-loading or cross-validation, start at `vault.py:31` (`Vault.load`).
- To change how the vault is located on disk, start at `discovery.py:26` (`discover_vault`).

## See also

- `../tools/MAP.md` — the tool registry and contracts that `Vault.load` populates
- `../pipeline/MAP.md` — the consumer of routing decisions and vault agents
