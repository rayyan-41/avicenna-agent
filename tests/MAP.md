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
| `test_check_maps.py` | 392 | Tests for `scripts/check_maps.py` — MAP.md inventory parity gate. Covers: untracked file detection before staging, staged-file parity, extra-row rejection for untracked files, ignored-file exclusion, (untracked) annotation on missing-row findings, the marker-alone-on-its-line rule, and placeholder rejection (rows containing the placeholder token must fail). All tests use tmp_path with a real `git init`. |
| `test_concurrency.py` | 55 | Proves `gather_sections` caps peak concurrency at the requested limit, isolates failures so one exception does not cancel siblings, and cleans up on cancellation. |
| `test_domain_derivation.py` | 359 | Domain derivation from the vault's folder tree: domains derive from root subdirectories excluding dotted dirs and `_tmp`; on-disk casing is canonical; categories derive from domain subfolders; routing validates against the derived set; no directory creation outside init; drift between folders and taxonomy.json is reported; `_derive_domains` unit tests. |
| `test_embedding.py` | 390 | Offline tests for `EmbeddingProvider`: `FakeEmbeddingProvider` round-trips, order preservation, unit-length vectors, call recording, ABC conformance. `GoogleEmbeddingProvider` error mapping (401/403 terminal, 429/5xx retried), `taskType` and `outputDimensionality` pass-through, batch-to-sequential fallback on `BadRequestError`, no vendor SDK in `sys.modules` after import. Missing key message names the pool file and env var. |
| `test_events.py` | 77 | Verifies the `EventBus` invariants: fan-out delivers every event to every subscriber in identical order, sequence numbers are strictly monotonic, `LogMessage` is droppable under backpressure while structural events like `SectionCompleted` block, and `drain` terminates cleanly on the close sentinel. |
| `test_gen_matrix.py` | 342 | MOC file detection for the generation matrix: tag-based detection finds files with `moc` in frontmatter tags regardless of filename; filename fallback catches `Map of Contents - <Domain>.md` and whole-word `moc` stems; `Mocking Realism.md` is not mistaken; empty dirs return nothing; malformed frontmatter does not crash; `_no_moc_domains` reads `noMoc` from taxonomy. |
| `test_healthcheck.py` | 496 | Tests for the PROVIDER healthcheck probe: all keys valid passes with count and source; one of four invalid warns with the failing fingerprint named; all invalid fails; no keys configured skips; raw key material never appears in output; validation runs concurrently via asyncio.gather. T25 additions: keys for an unregistered provider are SKIP (informational, never FAIL, no exit-code impact); keys for another registered provider are validated against that provider and reported separately. |
| `test_keypool.py` | 680 | API key pool tests: round-robin order and wraparound; blank and # lines ignored; duplicates collapsed; env var is explicit override (exact keys, file and single ignored); file+single union merges both sources with file keys first and deduplicates; file-only and single-only paths; pool of one behaves like the single-key path; quarantine removes a key and the rotation skips it; all-quarantined raises; fingerprints never contain key material; concurrent next() from many tasks hands out keys without racing. T25 additions: provider-scoped pool file format (inline prefix, section headers, case-insensitive matching, bare keys before/after sections), keys for unregistered provider retained but never returned for another pool, env var per provider, `load_pool_file` returns full structure. |
| `test_mcp_integration.py` | 185 | End-to-end MCP tests against a real fixture server over real stdio: connection, schema export, tool registration and invocation, `BUILTIN > VAULT_PS1 > MCP` precedence with surviving alias, the `mcp:` frontmatter gate that prevents undeclared agents from reaching MCP tools, server-side errors reported as results not exceptions, and the no-op path when no servers are configured. |
| `test_onboarding.py` | 345 | Pins the first-run onboarding guarantees: a fresh install reports itself unconfigured so the interface can show onboarding; bad, rate-limited, and network-failing keys produce distinct actionable messages; a good key persists and flips the install to onboarded; the local-model option remains an honest stub; and a missing vault is a reportable state rather than a crash. |
| `test_phases_789.py` | 93 | Covers the safety boundary between chat and pipeline: `CHAT_SAFE_TOOLS` contains only read-only tools, `spec_for_model` excludes `PIPELINE_ONLY` entries, onboarding validation maps provider errors to user-facing messages, and `secrets.redact` masks long key-shaped tokens while leaving short strings intact. |
| `test_pipeline_e2e.py` | 351 | Full pipeline orchestration: a scaffolded vault produces a structured note with frontmatter, one heading per planned section, no chunk scaffolding, and real tags when a tagger agent is present; linker wikilinks reach the file; a truncating formatter cannot clobber the note; resume reuses existing chunks without re-running pre-flight; a second run slug-bumps rather than overwriting; missing tools emit `LogMessage` warnings; dry-run writes nothing; stage identities are unique; and builtin tools refuse path-traversal escapes. |
| `test_providers.py` | 388 | Offline provider tests: `FakeProvider` round-trips, call recording, callable-script mode, `LLMProvider` ABC conformance, `ToolSpec`/`ToolCall`/`Completion` type behaviour, `wants_tools` detection, and `get_provider` registry lookups for `fake` and unknown names. |
| `test_registry.py` | 484 | Theme and type registry (T34 Part B): a theme already in the registry is reused unchanged; a genuinely new theme is minted and persisted to taxonomy.json; normalisation folds case, separator and plural variants; taxonomy.json preserves key order and indentation; validate_tags is called after the registry write; unwritable taxonomy warns and the run continues; the write is atomic; types accumulate the same way as themes; existing note tags are unaffected. |
| `test_routing.py` | 328 | Routing regression suite. Tokenisation tests (normalise, singular, content-word decomposition, stopword filtering) run always. Seventeen parametrised cross-domain cases and the synthetic-vault tests (single-agent always wins, domain-name-alone is decisive, pipeline agents excluded) run against the reference vault when present and skip cleanly when absent. |
| `test_schema_detection.py` | 629 | Frontmatter schema detection (T33): a vault whose notes use `date/status/tags/note` gets that schema; key ORDER matches the sample; empty vault falls back to scaffold; `tags` is always present even when notes lacked it; `date` is filled with today's ISO date never a placeholder; MOCs are excluded from the sample; a topic with `: ` round-trips through YAML; the detected schema is reported via `SchemaDetected` event; `build_frontmatter` uses detected schema; `apply_tags` preserves model-supplied keys. |
| `test_session.py` | 99 | Session mechanics: simple and multi-turn message accumulation, the tool loop with tool result injection, the `MAX_TOOL_ITERATIONS` cap that raises on infinite tool-call chains, and the `one_shot` fresh-context guarantee that two calls each see exactly one message. |
| `test_settings.py` | 510 | Tests for the T36 settings changes: word count guidance, advisory word count, timeout removal, and per-heading resolution. Covers: per-heading target independence from heading count, precedence chain (CLI > env > vault config > default), per-template overrides, the rendered section prompt containing the resolved number, short notes completing successfully, WordCountStage emitting pass verdicts unconditionally, matrix cell word count as advisory, no harness-side timeout by default, provider timeout pass-through, cancellation propagating through PipelineRunner, _tmp chunks surviving resume, and absence of TEMPLATE_MINIMUMS coercion. |
| `test_stages_fixes.py` | 617 | Tests for the three stage defects fixed together: `_canonical_domain_dir` resolves a domain against the folder actually on disk (case-insensitive, hyphen/space tolerant) and returns `None` for a missing domain (never fabricates a Title Case path), so the note folder and the MOC filename can no longer disagree; the tagging floor constructs a minimal valid array from the taxonomy when the tagger fails three times, rather than shipping `tags: []` and orphaning the note; and LinkingStage skips the model only when `get_related_notes` actually ran and returned nothing, never when the tool is merely absent. |
| `test_t29_fixes.py` | 381 | Tests for three defects a live six-domain run exposed: a topic containing a colon must round-trip through a YAML parser (build_frontmatter quotes and escapes scalars that need it, and leaves ordinary topics unquoted); a model that returns a frontmatter block followed by the whole note inside a ```markdown fence has that fence unwrapped and the duplicate block discarded, while a legitimate mid-note code block is untouched; and every [[wikilink]] the linker produces is resolved against the vault's note index, with unresolvable targets unwrapped to plain text so the weaver's prose survives. |
| `test_t32_vault_sovereignty.py` | 318 | Tests for T32 vault sovereignty: `_canonical_domain_dir` returns `None` when no folder matches (never fabricates); `_note_destination` aborts with a message naming the failed domain and available domains; no directory is created by a failed or successful run; init scaffold still creates folders; `_`-prefixed, dotted, and `_tmp` directories excluded from categories; `excludeFromDerivation` from taxonomy.json removes user-specified folders; template defaulting unchanged. |
| `test_t38_tag_form.py` | 559 | T38 tests: folder names are paths, tags are kebab. `tag_form` converts folder names to lowercase kebab-case; `categories_for_domain` returns tag form while `categories_for_domain_path` returns path form; `_build_floor_tags` produces tag-form categories; a tag matching a derived category is passed through not minted; `extract_tag_line` normalises tagger output (brackets, quotes, hashes, underscores, case); the registry refuses brackets and quotes before normalisation and validates the normalised key against the tag-form regex; a known type is not minted as a theme (no undo_mint); taxonomy unchanged when all proposed tags already exist; path resolution still uses folder casing. |
| `test_tools.py` | 155 | Tool-layer unit tests: PowerShell value normalisation (comma, space, list, plain, boolean) and `build_argv` construction; contract-token parsing for success, failure, and unmatched outputs plus `write_manifest` capture groups; `PIPELINE_ONLY` tools excluded from `spec_for_model`; and registry collision precedence where `BUILTIN` wins and the loser keeps a `{source}__{name}` alias. |
| `test_vault.py` | 101 | Vault-layer tests: `AgentDef.from_file` parses frontmatter, rejects name-mismatch and missing-required-field malformation; `init_vault` then `Vault.load` round-trips to a vault with three read-only builtin tools and no `vault_ps1` scripts; `Taxonomy.category_for_path` resolves the `folderMap` correctly; and a zero-agent vault loads without error. |
| `test_write_back.py` | 383 | Tests for `_write_back` and `_unwrap_model_output` in pipeline/stages.py. The pipeline owns the frontmatter, not the model. These tests verify that `_write_back` preserves the on-disk frontmatter, unwraps chatty model output, and rejects truncation — exactly the guarantees that keep a note vault-safe. Includes tests for malformed frontmatter blocks. |
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
