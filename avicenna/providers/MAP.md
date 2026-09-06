# MAP: avicenna/providers/

> The provider layer isolates every vendor SDK behind a stateless ABC so the
> rest of the codebase never imports one. Mistral is the only real backend
> implemented. FakeProvider is the deterministic offline stand-in the entire
> test suite runs against. The registry maps names to lazy factories so that
> `import avicenna.providers` does not pull a vendor SDK into `sys.modules`
> — enforced by two separate CI gates (see Invariants).

**Depends on:** `mistralai` SDK (lazy, only at construction time) · **Depended on by:** `avicenna/session.py`, `avicenna/chat.py`, `avicenna/auth.py`, `pipeline/`
**Reads:** nothing from disk (providers are stateless) · **Writes:** nothing (completions are returned, not persisted)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `__init__.py` | 79 | Public surface: re-exports neutral types, error classes, and FakeProvider eagerly. MistralProvider is behind PEP 562 `__getattr__` — the `mistralai` SDK is imported only when the attribute is first accessed or `get_provider("mistral")` is called. Registers the `mistral` and `fake` factories at import time (the mistral factory defers its SDK import to construction). |
| `base.py` | 81 | Neutral types and the `LLMProvider` ABC. Frozen dataclasses: `Message`, `ToolCall`, `ToolSpec`, `Usage`, `Completion`. The ABC has two abstract methods: `complete(system, messages, tools, temperature, max_tokens)` and `close()`. `Completion.wants_tools` is the property that drives the tool-resolution loop in `session.py`. |
| `errors.py` | 40 | Provider error hierarchy rooted at `ProviderError`. Only `RateLimitError` (carries `retry_after`) and `TransientError` are retryable. `AuthError`, `BadRequestError`, and `ContextOverflowError` are terminal. |
| `fake.py` | 50 | `FakeProvider`: accepts either a list of scripted `Completion` objects or a callable. Records every call into `self.calls` so tests can assert on system prompts, message histories, and fresh-context isolation. The load-bearing test seam for the entire harness. |
| `mistral.py` | 252 | `MistralProvider`: the only real backend. Maps neutral `Message`/`ToolSpec` types to Mistral wire types and back. Handles the SDK's `Unset` sentinel for nullable content, JSON-string tool arguments, and optional usage info. Retries on `RateLimitError` and `TransientError` with exponential backoff plus jitter (max 4 attempts). Maps HTTP status codes to the error hierarchy. |
| `registry.py` | 25 | Name-to-factory registry. `register(name, factory)` stores; `get_provider(name, **kwargs)` constructs. Raises `ValueError` with the known-provider list on miss. |
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
- To change the ABC contract, start at `base.py:44`.

## See also

- `../MAP.md` — the package root where `session.py` calls `one_shot` through the provider.
- `../tools/MAP.md` — the tool registry whose `runner` is passed alongside the provider into every Session.
