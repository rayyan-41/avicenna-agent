# LLM-assisted routing — design

Status: approved 2026-09-06. Amends the routing behaviour described in
`2026-09-06-backend-shippability-design.md`.

## Problem

Routing is deterministic keyword scoring, and on the reference vault it routes
three of six domains correctly. The healthcheck measured it:

    art topic   -> history 3.00  matched ['how', 'influenced']
                   art     2.00  matched ['depth', 'painting']
    islam topic -> history 4.00  matched ['theology', 'how']
                   islam   2.50  matched ['theology']

Three distinct causes were traced:

1. **Stopword leak.** `how` was absent from `STOPWORDS` and had entered one
   domain's derived vocabulary at entity weight, because kebab-case tags are
   decomposed into component words. Fixed separately; it converted wrong answers
   into refusals rather than into correct ones.
2. **Category outranks theme on a shared word.** `narrative` is a category under
   history in this vault and a theme for literature. `W_CATEGORY` (3.0) beats
   `W_THEME` (2.5), so history wins literature's defining word.
3. **Vocabulary size tracks note count.** art has 21 vocabulary entries against
   history's 99. A thin domain cannot clear `MIN_SCORE` even unopposed.

Causes 2 and 3 are not bugs in the scorer. They are what a bag-of-words scorer
does. Fixing them means retuning weights and thresholds against one vault's
particular shape, and then retuning again as the vault grows.

## The decision

Invert the design. A language model classifies the topic; the deterministic
scorer becomes the offline fallback.

Semantic classification against a closed set is what models are reliably good
at. "Brunelleschi, Masaccio, the Brancacci Chapel" is unambiguously art to any
model, and no amount of weight tuning teaches a bag-of-words scorer that
without the vault first accumulating art notes that contain those words.

The cost argument that justified keyword-only routing does not survive
inspection: this is one ~256-token call at the start of a run that will spend
tens of thousands of tokens generating the note.

## Why this does not violate the prime directive

The doctrine is that stages branch on regex-parsed contract tokens and never on
the model's account of whether a step worked. That guards against trusting a
model's self-report about execution. Routing is not a step-completion judgment;
it is a content classification against a closed set, and its answer is validated
by `validate_domain` before anything acts on it. The model proposes, the closed
set disposes.

## Resolution order

1. **LLM classifier.** Constrained to the vault's actual domains, read from
   `taxonomy.json` rather than hardcoded. Structured JSON response, small token
   budget.
2. **Validation.** `validate_domain` gates every answer against the closed set.
   An unknown domain is treated as a failed classification, not as a result.
3. **Deterministic scorer.** Used when the model call fails or its answer does
   not validate: no key configured, offline, rate limited, malformed output.
4. **Refusal.** If both fail, `None`, preserving the existing escalation
   contract that lets the caller ask the user rather than guess.

Never silently default to a particular agent. An unparseable answer falls to the
next step; it does not become a domain. Musannif, the implementation that
prompted this design, returns `data.get("domain", "turing")` on malformed JSON,
which converts a parse failure into a confident wrong answer.

## What does not change

`route_request` and `score_domains` keep their present signatures and behaviour.
They are pure, synchronous, free, and pinned by thirty regression tests, and
they remain the fallback path. No weight constant and no threshold moves.

The classifier is reached through the `LLMProvider` ABC, so no vendor SDK enters
`avicenna/vault/`, and the path is exercised in tests through `FakeProvider`
like every other model call in the suite.

## Observability

The run reports which path decided the domain, via the existing `LogMessage`
event. No new wire event: adding one would require a dataclass in `events.py`, a
name in `protocol.ts`, a translator case, and a parity-gate pass, which is a
large amount of protocol surface for a diagnostic line.

## Accepted trade-off

A provider outage now affects routing, where previously it did not. Steps 3 and
4 exist precisely for that case, so the degradation is to the previous
behaviour rather than to a failure. CI stays hermetic because the deterministic
path is unchanged and the model path runs against `FakeProvider`.
