# Backend shippability layer — design

Status: approved 2026-09-06.

## Problem

The repository has strong CI and no evidence. Fourteen gates block the build,
and every one of them tests the code in isolation: types, encodings, import
boundaries, protocol parity. Not one of them has ever run the product.

The entire test suite executes against `FakeProvider`. That is the right default
— it is fast, free, deterministic, and needs no key — but it means the claim
"Avicenna generates a note" has never been demonstrated by anything automated.
The pipeline could be broken end to end and every gate would stay green.

Three things are missing, and they are independent subsystems rather than one
feature: a way to ask a running installation whether it is healthy, a way to
prove a real generation works, and a way to ship a build.

## What "endpoint" means here

There is no HTTP surface. The runtime surfaces are the stdio bridge's seventeen
methods, the MCP servers declared in the user's config, the vault's PowerShell
tools, and the provider API. A healthcheck that does not probe those four is not
checking anything a user depends on.

## 1. Healthcheck

`scripts/healthcheck.py`, surfaced as `avicenna doctor`. Eight probes, each
independent, each degrading gracefully and reporting the degradation rather than
failing silently:

1. **Config and vault resolution** — which vault was found and by which of the
   four discovery sources, which provider is configured, whether a key is
   present. The key is reported as present or absent and never printed.
2. **Provider reachability** — one cheap real call, reusing `validate_key` in
   `avicenna/auth.py`. This is the only probe that spends money, and it spends
   almost none.
3. **Vault load** — agents parse, the taxonomy validates, and every content
   agent's declared domain exists in `taxonomy.json`.
4. **Tool registry** — every tool registered, with source and access level.
   Flags any `.ps1` present in the vault but missing from the manifest in
   `vault_tools.py`, because those silently default to pipeline-only.
5. **Vault PowerShell tools** — executes the read-only ones against a probe
   input and asserts the declared contract token parses out of stdout. A tool
   that returns prose instead of its token gates nothing, and this is the only
   place that would notice.
6. **MCP servers** — reuses the existing `avicenna mcp test` machinery. That
   command already connects to each server in isolation and captures the real
   error text; duplicating it would create a second thing to keep true.
7. **Bridge methods** — spawns `python -m avicenna.bridge`, sends all seventeen
   methods, and asserts each answers a well-formed frame. The existing CI smoke
   test sends exactly one method; this is the difference between knowing the
   process starts and knowing the surface works.
8. **Routing** — the six domain topics each route to the expected agent, above
   the score and margin thresholds.

Output is a table by default, `--json` for machines, and a non-zero exit on any
hard failure. Degradations that are legitimate — a vault with no PowerShell
tools, no MCP servers configured — are reported as such and do not fail.

Probes 5 and 7 must never mutate. The tool probe runs only tools declared
read-only; the bridge probe never calls `run.note`.

## 2. Live generation matrix

`scripts/gen_matrix.py`. Six runs, one per domain agent, each on the `general`
template whose minimum is exactly 1000 words.

Runs go into the real vault, in the real domain folders, with MOC updates and
wikilinking against the real corpus. A note written to `_tmp/` would have to
skip `linking` and `moc`, and those two stages are the product's reason to
exist: a brilliant note that links to nothing is a failure. Testing everything
except the part that matters is not a test.

The safety net is the vault's own git repository, which is clean. The harness
records `HEAD` and the working-tree state before the first run, and prints the
exact commands to revert. It never reverts on its own — deciding what to keep is
the vault owner's call, not the harness's.

Per-run assertions, reported per cell rather than collapsed into one verdict:

- the note exists on disk where routing said it would,
- word count at or above the template minimum,
- YAML frontmatter parses,
- every tag drawn from the closed taxonomy,
- every wikilink resolving to a note that exists,
- the domain's Map of Content containing the new entry.

A failed cell reports which assertion failed and leaves its artefacts in place
for inspection.

## 3. Continuous delivery

`.github/workflows/release.yml`, triggered on `v*` tags: build the sdist and
wheel, build the `tui` bundle, attach both to a GitHub Release.

There is deliberately **no PyPI publish job**. No token exists for one. This
repository's stated policy is that a check which cannot fail the build is
documentation, not a gate, and the same reasoning applies to a publish step that
cannot publish: it would sit in the workflow looking like distribution while
doing nothing. When a token exists, the job gets written then.

## 4. Two gate corrections

- `mypy --strict` covers `providers` and `pipeline` only. `bridge/server.py` is
  510 lines carrying the whole wire contract, and a type error there desyncs the
  frontend. `avicenna/bridge` joins the strict set.
- `CLAUDE.md` states the reference-vault-name invariant repository-wide, but the
  CI gate scans only `avicenna/**/*.py`. The rule is wider than its enforcement,
  which is the same defect the no-`continue-on-error` policy exists to prevent.
  The gate widens to every tracked file outside `tests/`, excluding the files
  that necessarily quote the name in order to document or implement the rule.

## Non-goals

Widening `mypy --strict` to `tools`, `vault` and `cli`. Adding a second provider
backend. Any change to the frontend. Any change to pipeline control flow — the
generation matrix observes the pipeline, it does not modify it.
