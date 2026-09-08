# MAP: avicenna/providers/

> The provider layer isolates every vendor SDK behind a stateless ABC so the
> rest of the codebase never imports one. Mistral is the primary real backend;
> Gemini is the second, using REST via the standard library (no SDK).
> FakeProvider is the deterministic offline stand-in the entire test suite
> runs against. The registry maps names to lazy factories so that
> `import avicenna.providers` does not pull a vendor SDK into `sys.modules`
> — enforced by two separate CI gates (see Invariants).

**Depends on:** `mistralai` SDK (lazy, only at construction time); standard library `urllib` (Gemini, no SDK) · **Depended on by:** `avicenna/session.py`, `avicenna/chat.py`, `avicenna/auth.py`, `pipeline/`
**Reads:** nothing from disk (providers are stateless) · **Writes:** nothing (completions are returned, not persisted)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `__init__.py` | 157 | Public surface: re-exports neutral types, error classes, `EmbedTask`, `EmbeddingProvider`, and both fake providers eagerly. GeminiProvider, MistralProvider, and GoogleEmbeddingProvider are behind PEP 562 `__getattr__`. Registers `gemini`, `mistral`, and `fake` LLM factories plus `google` and `fake` embedding factories at import time (all real factories defer their module imports to construction). |
| `base.py` | 117 | Neutral types and the `LLMProvider` and `EmbeddingProvider` ABCs. Frozen dataclasses: `Message`, `ToolCall`, `ToolSpec`, `Usage`, `Completion`. `EmbeddingProvider` declares `embed(texts, task)` and `embed_one` convenience wrapper. `EmbedTask` literal constrains task types to `RETRIEVAL_DOCUMENT`, `RETRIEVAL_QUERY`, `SEMANTIC_SIMILARITY`. |
| `errors.py` | 40 | Provider error hierarchy rooted at `ProviderError`. Only `RateLimitError` (carries `retry_after`) and `TransientError` are retryable. `AuthError`, `BadRequestError`, and `ContextOverflowError` are terminal. |
| `fake.py` | 103 | `FakeProvider` and `FakeEmbeddingProvider`: deterministic offline stand-ins for completions and embeddings respectively. `FakeProvider` accepts scripted `Completion` objects or a callable; `FakeEmbeddingProvider` produces hash-based unit-length vectors so cosine similarity is meaningful. Both record every call for test assertions. |
| `gemini.py` | 458 | `GeminiProvider`: REST-only completion backend for Google AI Studio. Uses the standard library (`urllib` in `asyncio.to_thread`) — no vendor SDK. Implements the full `LLMProvider` ABC including tool calling (maps `ToolSpec` to `functionDeclarations`, response `functionCall` parts back to `ToolCall`). Supports optional `KeyPool` for round-robin key rotation with quarantine on auth failure, per-call timeout, and total-elapsed budget. Maps HTTP status codes to the error hierarchy. |
| `google_embedding.py` | 277 | `GoogleEmbeddingProvider`: REST-only embedding backend for Google AI Studio. Uses the standard library (`urllib` in `asyncio.to_thread`) — no vendor SDK. Supports `batchEmbedContents` with sequential fallback. Retries on `RateLimitError` and `TransientError` with exponential backoff; 401/403 are terminal. Task type and output dimensionality are user-configurable. |
| `mistral.py` | 359 | `MistralProvider`: the only real backend. Maps neutral `Message`/`ToolSpec` types to Mistral wire types and back. Handles the SDK's `Unset` sentinel for nullable content, JSON-string tool arguments, and optional usage info. Retries on `RateLimitError` and `TransientError` with exponential backoff plus jitter (max 4 attempts). Maps HTTP status codes to the error hierarchy. Supports optional `KeyPool` for round-robin key rotation with quarantine on auth failure. |
| `registry.py` | 47 | Two name-to-factory registries: one for `LLMProvider`, one for `EmbeddingProvider`. `register`/`get_provider` and `register_embedding`/`get_embedding_provider` follow the same pattern. Raises `ValueError` with the known-provider list on miss. |
<!-- map:files:end -->

## Invariants

- **No vendor SDK may be imported outside this directory.** CI gate "Vendor
  SDK containment" (pwsh) scans every `.py` under `avicenna/` except this
  directory for `from|import` of `mistralai`, `openai`, `anthropic`, or
  `google.genai`. Any hit fails the build.
- **Importing `avicenna.providers` must not pull a vendor SDK into
  `sys.modules`.** CI gate "Vendor neutrality" runs
  `import sys, avicenna.providers` and checks that no vendor-prefixed module
  appears in `sys.modules`. The mechanism: `__init__.py` registers a factory
  for Mistral that defers `from avicenna.providers.mistral import ...` to
  construction time, and `MistralProvider` itself is behind PEP 562
  `__getattr__`.
- `mypy --strict` is enforced on this directory in CI. All types must be
  complete and correct.
- Every module begins with `from __future__ import annotations`.
- `LLMProvider.complete` is a single stateless call. There is no session,
  no streaming, no conversation memory in the provider. `Session` in
  `session.py` owns the message list; the provider receives it as a parameter.

## Entry points

- To add a new provider backend: implement `LLMProvider` from `base.py`, map
  its errors to `errors.py`, register a factory in `__init__.py` (defer the
  SDK import behind the factory), and add the name to `__getattr__`'s
  `_LAZY_ATTRS` if the class itself should be lazily accessible.
- To change retry or error-mapping logic for Mistral, start at `mistral.py:63`.
- To change retry or error-mapping logic for Gemini, start at `gemini.py:107`.
- To change the ABC contract, start at `base.py:44`.

## See also

- `../MAP.md` — the package root where `session.py` calls `one_shot` through the provider.
- `../tools/MAP.md` — the tool registry whose `runner` is passed alongside the provider into every Session.
