# Layered configuration — design

Status: approved 2026-09-06.

## Problem

The harness is meant to be an engine someone else can tune. It is not one yet.
Values that belong to a user or to a vault are compiled into the code, and in
several places two code paths disagree about the same setting.

The failure was not theoretical. `mistral-large-latest` is hardcoded as
`DEFAULT_MODEL`, and `avicenna note` built its provider from an environment
variable rather than the user's configuration, so the model chosen during
onboarding was never used by the main command. On an account whose tier does not
include that model, every generation returned 403 naming a model the user never
selected. The stdio bridge did not have the bug, because it called
`auth.build_provider()`. Two front doors, two answers.

Worse, `persist_key` overwrote `provider` and `model` with the hardcoded
defaults on every key save, so a user's choice was actively destroyed rather
than merely ignored.

## The principle already exists

This is not a new philosophy. `stages.py` reads which domains keep a Map of
Content from the vault, with the comment:

> which domains keep a MOC is the user's policy about their own vault, not the
> harness's business.

And `Config`'s own docstring states that all settings should be accessed through
it rather than by calling `os.getenv` elsewhere. Both principles are right and
both are applied in exactly one place each. This design finishes them.

## Two scopes

Settings are split by who owns them, because that determines what they travel
with.

**Vault policy** lives in a new `.agents/config.json` inside the vault: template
word floors, routing stopwords, routing weights and thresholds, the no-MOC
domain list, tool contract tokens, and folder conventions. Share a vault and
these go with it, because they describe that vault.

**User preferences** live in `~/.avicenna/user_config.json`: provider, model,
API keys, concurrency, timeouts, retry bounds, and the tool-iteration cap. These
describe the operator, not the vault.

`taxonomy.json` keeps its current role as the closed vocabulary — domains,
categories, types, themes, folder map. Vocabulary and behaviour stay separate.

## Precedence

Highest wins, uniformly, for every setting:

1. CLI flag, for this run only
2. Environment variable
3. The scope file — vault `config.json` for policy, `user_config.json` for
   preferences
4. Built-in default

The existing module-level constants stay, but stop being the value and become
the defaults table. That keeps one source of truth for fallbacks and keeps the
change reviewable.

## Interface

The CLI is the surface. The terminal frontend is a skeleton with no visual
design, so configuration must be fully usable without it.

- `avicenna config show` prints every effective setting **with the layer that
  supplied it**. Without that column, "editable" is a claim rather than a fact;
  with it, a user can see why a value is what it is.
- `avicenna config get <key>` and `avicenna config set <key> <value>` write to
  the correct scope automatically, and refuse an unknown key rather than
  silently creating one.
- `avicenna note` accepts per-run overrides: `--model`, `--provider`,
  `--concurrency`, and the timeout knobs.
- `avicenna doctor` reports the effective provider and model and the layer each
  came from, so a tier or key problem names the value actually in use.

`avicenna init` scaffolds a fully populated `.agents/config.json` with every key
at its default and a comment above each. A user opening it sees the whole
engine rather than a blank file to guess at.

## Provider and model resolution

One function resolves the provider, its key, and the model, and everything calls
it: the CLI, the bridge, and the scripts. `read_api_key` and `write_api_key` are
already per-provider and need no change — only their callers, which pass a
hardcoded constant today.

`persist_key` stops writing `provider` and `model`. It records the key and the
onboarding flag and leaves the user's choices alone.

## Backwards compatibility

A vault with no `.agents/config.json` behaves exactly as it does now: every key
falls through to its built-in default. `noMoc` continues to be honoured from
`taxonomy.json`, with `config.json` winning if both define it. No existing vault
needs editing.

## The one exception

`PROTOCOL_VERSION` stays a constant and is deliberately not configurable. It is
negotiated between the backend and the frontend; a user who edits it makes the
two disagree and desyncs the NDJSON parser. Everything else becomes tunable,
including tool contract tokens, which genuinely belong to the vault because the
vault ships the `.ps1` tools that emit them.

## Testing

The precedence chain is the thing most likely to rot, so it is tested directly:
for a representative setting, assert that a flag beats an environment variable,
which beats the scope file, which beats the default. Assert that `persist_key`
preserves an existing model. Assert that a vault with no `config.json` still
loads. The suite stays offline: provider resolution is asserted by inspecting
the constructed provider's model, not by calling an API.
