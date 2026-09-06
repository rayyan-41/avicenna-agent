# MAP: avicenna/tools/

> Single lookup surface for every tool the harness can invoke: vault PowerShell
> scripts, MCP servers, and built-in read-only Python tools. The registry owns
> name resolution, collision handling, and access gating. The contract layer owns
> pipeline branching — the pipeline never asks a model whether a step worked; it
> regex-matches the tool's stdout against a declared contract token.

**Depends on:** `avicenna/providers/base.py` (`ToolSpec`) · **Depended on by:** `avicenna/vault/` (populates at load), `avicenna/pipeline/` (invokes tools), `avicenna/bridge/`
**Reads:** `.agents/tools/*.ps1` on disk · **Writes:** nothing (no tool in this package writes a note; only the pipeline writes)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `__init__.py` | 16 | Re-exports `Tool`, `ToolSource`, `ToolAccess`, `ToolResult`, `ToolRegistry`, `ToolNameCollision`, `ToolContract`, `ParsedContract`, `CONTRACTS`. |
| `base.py` | 61 | Neutral `Tool` ABC: name, description, JSON Schema parameters, `ToolSource` (VAULT_PS1 / MCP / BUILTIN), `ToolAccess` (MODEL_CALLABLE / PIPELINE_ONLY), and `async invoke`. `ToolResult` carries stdout, stderr, exit code, duration, and an optional parsed contract. |
| `builtin.py` | 139 | Three read-only Python tools that work before any vault has `.ps1` scripts: `read_note`, `list_notes`, `search_vault`. Path containment uses a component test, not `startswith`, because a prefix check on `D:\vault` accepted `../vault-private/secrets.md`. |
| `contracts.py` | 98 | Declarative contract layer. A `ToolContract` pairs a success regex and a failure regex; the pipeline branches on `ParsedContract.token`, never on prose. Nine contracts defined for `write_manifest`, `verify_chunks`, `validate_wordcount`, `validate_tags`, `generate_toc`, `get_related_notes`, `update_moc`, `cleanup_chunks`, `count_citations`. |
| `mcp_tools.py` | 46 | `MCPTool` wraps `MCPClientManager.call_tool`. `register_mcp_tools` reads the manager's `tool_specs()` and registers each into the same `ToolRegistry` — MCP tools share the same lookup and access gating as everything else. |
| `powershell.py` | 110 | `PowerShellTool` executes vault `.ps1` scripts. `normalise_ps_value` handles PowerShell's `-File` parser quirk: bare tokens containing commas or spaces are interpreted as arrays, so values are wrapped in literal double quotes. This module is why CI runs the Python job on `windows-latest`. Stdin is `DEVNULL` because a vault script that reads stdin would consume bridge NDJSON frames. |
| `registry.py` | 115 | `ToolRegistry` — the single lookup surface. **Precedence: BUILTIN > VAULT_PS1 > MCP.** On name collision the loser is re-registered under `{source}__{name}` (never silently dropped). `spec_for_model()` is the **only** path from registry to provider; it gates on `ToolAccess.MODEL_CALLABLE`, so pipeline-only tools (`cleanup_chunks`, `update_moc`, etc.) can never be selected by a model. Specs are keyed by registry key, not `tool.name`, because aliased losers share the same `.name`. |
| `runner.py` | 23 | `ToolRunner` protocol: `call`, `source_of`, `specs`. The pipeline depends on this abstraction, not on `ToolRegistry` directly. `_RegistryRunner` in `registry.py` is the implementation. |
| `vault_tools.py` | 208 | Declarative manifest mapping every known `.ps1` filename to its display name, description, JSON Schema, and `ToolAccess` class. `register_vault_tools` scans `.agents/tools/*.ps1`, looks up each in the manifest, and registers a `PowerShellTool`. Scripts absent from the manifest default to `PIPELINE_ONLY` with a warning. The manifest is the authority on which tools are model-callable — no model-callable tool can write to a note. |
<!-- map:files:end -->

## Invariants

- **Registry precedence is BUILTIN > VAULT_PS1 > MCP.** A vault tool silently
  shadows a builtin of the same name; an MCP tool silently shadows neither. The
  loser is aliased, never dropped.
- **`spec_for_model()` is the only registry-to-provider path.** It excludes
  `PIPELINE_ONLY` tools. `cleanup_chunks` and `update_moc` are called directly
  by the pipeline and must never appear in a model's tool list.
- **No model-callable tool can write to a note.** The linker returns the note
  body; the stage writes it back through `_write_back`.
- **Contracts gate the pipeline, never the model's opinion.** `ParsedContract`
  is the branch condition. If a stage's success cannot be decided by regex match
  against a contract token, that stage does not gate anything.
- **`PowerShellTool` exists because vault tools are `.ps1`.** The `-File`
  argument normaliser handles commas, spaces, and special characters. CI runs
  the Python job on `windows-latest` specifically because of this.
- A vault with zero `.ps1` tools is legitimate — `builtin.py` tools always
  register, and pipeline stages degrade with a warning when a tool is absent.

## Entry points

- To add a new builtin tool, add a class in `builtin.py` and register it in
  `register_builtin_tools` at `builtin.py:135`.
- To change tool precedence or collision handling, edit `registry.py:42`.
- To add or modify a contract token, edit `CONTRACTS` at `contracts.py:52`.
- To add a vault `.ps1` tool, add its manifest row in `vault_tools.py:32`.

## See also

- `../vault/MAP.md` — `Vault.load` is what populates this registry from disk
- `../pipeline/MAP.md` — the consumer that invokes tools and branches on contracts
