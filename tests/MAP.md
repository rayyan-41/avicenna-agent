# MAP: tests

> Every assertion in this tree runs against `FakeProvider` — a scripted in-memory
> stand-in — so the suite needs no API key, no network, and no terminal. The
> entire backend pipeline, tool layer, vault loading, event bus, and onboarding
> flow are exercised without touching a real provider or the user's `~/.avicenna`.
> This is the only directory in the repository where the reference vault's name
> may appear literally; it does so in `test_routing.py`, which skips labelled
> cross-domain cases when that vault is absent.

**Depends on:** `avicenna/` (imports every backend package) · **Depended on by:** CI (the `test` job runs `pytest -q` from here)
**Reads:** temporary `tmp_path` directories created per test · **Writes:** nothing outside `tmp_path` (fixtures write into the test sandbox only)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `test_concurrency.py` | 55 | Proves `gather_sections` caps peak concurrency at the requested limit, isolates failures so one exception does not cancel siblings, and cleans up on cancellation. |
| `test_events.py` | 77 | Verifies the `EventBus` invariants: fan-out delivers every event to every subscriber in identical order, sequence numbers are strictly monotonic, `LogMessage` is droppable under backpressure while structural events like `SectionCompleted` block, and `drain` terminates cleanly on the close sentinel. |
| `test_mcp_integration.py` | 185 | End-to-end MCP tests against a real fixture server over real stdio: connection, schema export, tool registration and invocation, `BUILTIN > VAULT_PS1 > MCP` precedence with surviving alias, the `mcp:` frontmatter gate that prevents undeclared agents from reaching MCP tools, server-side errors reported as results not exceptions, and the no-op path when no servers are configured. |
| `test_onboarding.py` | 338 | Pins the first-run onboarding guarantees: a fresh install reports itself unconfigured so the interface can show onboarding; bad, rate-limited, and network-failing keys produce distinct actionable messages; a good key persists and flips the install to onboarded; the local-model option remains an honest stub; and a missing vault is a reportable state rather than a crash. |
| `test_phases_789.py` | 93 | Covers the safety boundary between chat and pipeline: `CHAT_SAFE_TOOLS` contains only read-only tools, `spec_for_model` excludes `PIPELINE_ONLY` entries, onboarding validation maps provider errors to user-facing messages, and `secrets.redact` masks long key-shaped tokens while leaving short strings intact. |
| `test_pipeline_e2e.py` | 301 | Full pipeline orchestration: a scaffolded vault produces a structured note with frontmatter, one heading per planned section, no chunk scaffolding, and real tags when a tagger agent is present; linker wikilinks reach the file; a truncating formatter cannot clobber the note; resume reuses existing chunks without re-running pre-flight; a second run slug-bumps rather than overwriting; missing tools emit `LogMessage` warnings; dry-run writes nothing; stage identities are unique; and builtin tools refuse path-traversal escapes. |
| `test_providers.py` | 154 | Offline provider tests: `FakeProvider` round-trips, call recording, callable-script mode, `LLMProvider` ABC conformance, `ToolSpec`/`ToolCall`/`Completion` type behaviour, `wants_tools` detection, and `get_provider` registry lookups for `fake` and unknown names. |
| `test_routing.py` | 326 | Routing regression suite. Tokenisation tests (normalise, singular, content-word decomposition, stopword filtering) run always. Seventeen parametrised cross-domain cases and the synthetic-vault tests (single-agent always wins, domain-name-alone is decisive, pipeline agents excluded) run against the reference vault when present and skip cleanly when absent. |
| `test_session.py` | 99 | Session mechanics: simple and multi-turn message accumulation, the tool loop with tool result injection, the `MAX_TOOL_ITERATIONS` cap that raises on infinite tool-call chains, and the `one_shot` fresh-context guarantee that two calls each see exactly one message. |
| `test_tools.py` | 102 | Tool-layer unit tests: PowerShell value normalisation (comma, space, list, plain, boolean) and `build_argv` construction; contract-token parsing for success, failure, and unmatched outputs plus `write_manifest` capture groups; `PIPELINE_ONLY` tools excluded from `spec_for_model`; and registry collision precedence where `BUILTIN` wins and the loser keeps a `{source}__{name}` alias. |
| `test_vault.py` | 101 | Vault-layer tests: `AgentDef.from_file` parses frontmatter, rejects name-mismatch and missing-required-field malformation; `init_vault` then `Vault.load` round-trips to a vault with three read-only builtin tools and no `vault_ps1` scripts; `Taxonomy.category_for_path` resolves the `folderMap` correctly; and a zero-agent vault loads without error. |
<!-- map:files:end -->

## Invariants

- The entire suite runs against `FakeProvider`; no test touches a real LLM API or
  the user's keyring. If a test starts requiring network, it is in the wrong
  file.
- `test_routing.py` contains the only legal occurrences of the reference vault's
  name outside `tests/` — in fact, they *are* in `tests/`, which is the sole
  exception. Tests that need that vault are skipped via `pytest.mark.skipif`
  when it is absent; CI has no access to it.
- `tmp_path` (pytest's per-test temporary directory) is the only write surface.
  No test writes to the repository, the user's home, or another test's sandbox.
- There is no shared `conftest.py` in this directory. Fixtures are defined
  locally in the test files that need them.

## Running a subset

```bash
# everything
pytest -q

# one file
pytest tests/test_routing.py -v

# tests not needing the reference vault (the synthetic routing cases still run)
pytest tests/test_routing.py -k "not reference" -v

# a specific case
pytest tests/test_pipeline_e2e.py::test_resume_reuses_existing_chunks -v
```

## See also

- `fixtures/MAP.md` — the real MCP fixture server that `test_mcp_integration.py` connects to
- `scripts/MAP.md` — `check_protocol_parity.py` enforces the wire-protocol invariant that the event tests rely on
