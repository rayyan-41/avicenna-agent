"""Deterministic keyword routing from a request to a content agent.

Replaces the v1.0.0 scorer, which was noise-driven. Three defects were fixed:

1. It tested SUBSTRINGS, not words. `sum(1 for w in desc_words if w in text_lower)`
   let 'for' match transFORmer, 'on' match attentiON and 'or' match wORks, so
   michelangelo scored 4 on ['de','for','on','or'] against an LLM topic and beat
   haytham. The winner was decided entirely by noise.
2. Vocabulary is kebab-case (`machine-learning`, `islamic-golden-age`) but the
   request was split on whitespace, so 24 of 49 themes could never match prose.
3. `themes` is a FLAT list evaluated identically inside every agent's loop, so a
   theme hit added the same score to all six domains and could not discriminate.

A fourth defect was caught during matrix validation: common English function
words — interrogatives (how, what, which), generic adverbs (most, first), and
generic verbs (make, use) — were absent from STOPWORDS and had leaked into
per-domain vocabulary at entity weight via kebab-case theme decomposition. The
largest domain accumulated the most such noise and won topics belonging to other
domains. Extended the stopword list to cover interrogatives, common adverbs,
conjunctions, and generic verbs/nouns that carry no domain signal. Words that
could be genuine scholarly vocabulary (reason, matter, form, nature, etc.) are
deliberately excluded.

The scorer here normalises both sides, matches on decomposed content words,
and derives per-domain vocabulary from the vault's own notes.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from avicenna.vault import AgentDef, Vault

if TYPE_CHECKING:
    from avicenna.providers.base import LLMProvider

_log = logging.getLogger(__name__)

# Weights. Ordered by how much signal each source actually carries.
W_DOMAIN = 4.0      # the domain word itself: explicit and unambiguous
W_CATEGORY = 3.0    # closed set, scoped to one domain
W_THEME = 2.5       # derived from real notes, genuinely discriminating
W_ENTITY = 1.5      # also derived; specific but noisier than a theme
W_DESCRIPTION = 1.0 # weakest; prose, only useful after stopword removal

MIN_SCORE = 2.5     # require at least one real signal
MIN_MARGIN = 1.0    # and a clear win over the runner-up

# Without this the description signal is almost entirely function words.
#
# Words deliberately excluded that look like they should be here: reason,
# order, matter, form, nature, state, law, power, light, work, sense, mind,
# act, end, good, right, will, present, subject, object, body, motion, cause.
# Several are core philosophical or scientific terms and removing them would
# break routing in the other direction.
STOPWORDS = frozenset("""
a an and any are as at be by for from has have in into invoke is it its of on or
that the their to when with within you your this these those note notes agent
domain related including such any all can may write writes written produce
produces producing use uses using for example e.g i.e etc
how what which who whom whose where when why
also through between during while than then both each other more most some many
much very only just about over under after before again further
use used using make made new first one two part way role kind thing
""".split())

_WORD = re.compile(r"[a-z0-9]+")
_CACHE: dict[str, dict[str, dict[str, float]]] = {}


def normalise(text: str) -> list[str]:
    """Lowercase, split hyphens/underscores, drop punctuation, return words."""
    return _WORD.findall(text.lower().replace("-", " ").replace("_", " "))


def singular(word: str) -> str:
    """Crude de-pluralisation so 'conquests' matches 'conquest'."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("es") and not word.endswith("ses"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def terms(text: str) -> set[str]:
    """Content words of a request, singularised, stopwords removed."""
    return {
        singular(w)
        for w in normalise(text)
        if w not in STOPWORDS and len(w) > 2
    }


def content_words(term: str) -> set[str]:
    """Decompose a vocabulary entry into matchable content words.

    Vocabulary is kebab-case and often three or more words long
    ('empire-and-conquest', 'islamic-golden-age', 'biography-and-legacy').
    Requiring the whole phrase to appear verbatim in prose is why the previous
    scorer never fired. Matching any content word of the phrase does fire, and
    'empire' alone is a strong signal for history.
    """
    return {
        singular(w)
        for w in normalise(term)
        if w not in STOPWORDS and len(w) > 2
    }


def domain_vocabulary(vault: Vault) -> dict[str, dict[str, float]]:
    """Per-domain {content word: weight}, derived from the vault's own notes.

    The taxonomy lists themes as one flat set with no domain association, so it
    cannot discriminate on its own. The notes can: a note's tags are
    [domain, category, type, theme(s), entity(ies), marker], so scanning them
    tells us `empire-and-conquest` belongs to history while `machine-learning`
    belongs to science, and that entity tags like `transformers` and `attention`
    are science signal. Self-maintaining: as the vault grows, routing sharpens.

    A vault with no notes yet degrades to domain plus category plus description,
    which is still enough to route a single-agent scaffold.
    """
    key = str(vault.root)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    known_themes = {t.lower() for t in vault.taxonomy.themes}
    known_types = {t.lower() for t in vault.taxonomy.types}
    markers = {m.lower() for m in vault.taxonomy.markers}
    domains = set(vault.taxonomy.domains)
    vocab: dict[str, dict[str, float]] = {d: {} for d in domains}

    def add(domain: str, term: str, weight: float) -> None:
        for w in content_words(term):
            if vocab[domain].get(w, 0.0) < weight:
                vocab[domain][w] = weight

    # Static signal from the taxonomy itself.
    for domain in domains:
        add(domain, domain, W_DOMAIN)
        for cat in vault.taxonomy.categories_for(domain):
            if cat not in ("moc",):
                add(domain, cat, W_CATEGORY)

    # Derived signal from real notes.
    for md in vault.root.rglob("*.md"):
        rel = md.relative_to(vault.root).parts
        if not rel or rel[0].startswith(".") or rel[0] == "_tmp":
            continue
        try:
            head = md.read_text(encoding="utf-8", errors="replace")[:1500]
        except OSError:
            continue
        m = re.search(r"(?m)^tags:\s*\[(.*?)\]", head)
        if not m:
            continue
        tags = [t.strip().lower() for t in m.group(1).split(",") if t.strip()]
        if not tags or tags[0] not in domains:
            continue
        domain = tags[0]
        for tag in tags[1:]:
            if tag in markers or tag in known_types or tag == "moc":
                continue
            add(domain, tag, W_THEME if tag in known_themes else W_ENTITY)

    _CACHE[key] = vocab
    return vocab


def clear_cache() -> None:
    """Drop the memoised per-vault vocabulary. Used by tests."""
    _CACHE.clear()


@dataclass(frozen=True)
class DomainScore:
    agent: AgentDef
    domain: str
    score: float
    matched: tuple[str, ...] = ()

    def __str__(self) -> str:
        hits = ", ".join(self.matched[:6]) or "-"
        return f"{self.agent.name:14s} {self.score:5.1f}  {hits}"


def _signal(vault: Vault, agent: AgentDef) -> dict[str, float]:
    """{content word: weight} for one content agent."""
    domain = agent.domain or ""
    signal: dict[str, float] = dict(domain_vocabulary(vault).get(domain, {}))
    for word in content_words(agent.description):
        if len(word) > 3 and signal.get(word, 0.0) < W_DESCRIPTION:
            signal[word] = W_DESCRIPTION
    return signal


def score_domains(vault: Vault, text: str) -> list[DomainScore]:
    """Score every content agent against the request, best first.

    Exposed so routing decisions are inspectable: this is what `avicenna route`
    prints and what the regression tests assert on.
    """
    request = terms(text)
    results: list[DomainScore] = []

    for agent in vault.agents.values():
        if agent.type != "content":
            continue
        signal = _signal(vault, agent)
        matched = {w: signal[w] for w in request if w in signal}
        total = sum(matched.values())
        ordered = tuple(sorted(matched, key=lambda t: (-matched[t], t)))
        results.append(DomainScore(agent, agent.domain or "", total, ordered))

    results.sort(key=lambda r: (-r.score, r.agent.name))
    return results


def route_request(vault: Vault, text: str) -> AgentDef | None:
    """Pick the content agent for a request, or None if genuinely ambiguous.

    Returns None rather than guessing so the caller can escalate; a wrong domain
    silently produces an entire note in the wrong voice, folder and taxonomy.
    """
    scores = score_domains(vault, text)
    if not scores:
        return None

    best = scores[0]

    # A vault with exactly one content agent has nothing to disambiguate, and
    # that includes the case where the topic shares no vocabulary with it.
    #
    # This used to additionally require `best.score > 0`, which sounds harmless
    # and was in fact a dead end for every new user. `avicenna init` scaffolds
    # exactly one agent whose whole vocabulary is {general, purpose, content,
    # agent, note, essay}; any real topic scores 0.00, fell through to the
    # MIN_SCORE gate, and the run aborted with "cannot determine domain" before
    # a single word was written. A refusal is only meaningful when there is
    # something else the request might have meant.
    if len(scores) == 1:
        return best.agent

    if best.score <= 0:
        return None

    runner_up = scores[1].score
    if best.score < MIN_SCORE or (best.score - runner_up) < MIN_MARGIN:
        return None
    return best.agent


def validate_domain(vault: Vault, domain: str) -> AgentDef:
    if domain not in vault.taxonomy.domains:
        raise ValueError(
            f"unknown domain {domain!r}; known: {sorted(vault.taxonomy.domains)}"
        )
    return vault.content_agent_for(domain)


def _build_classifier_prompt(vault: Vault, text: str) -> str:
    """Build a domain-classification prompt from the vault's live taxonomy.

    Each domain line includes its categories and the content agent's
    description so the model has real discriminating context rather than a
    bare list of names.  A vault with different domains works with no code
    change — the list is derived, never hardcoded.
    """
    lines = ["Domains:"]
    for domain in sorted(vault.taxonomy.domains):
        cats = vault.taxonomy.categories_for(domain)
        cat_str = ", ".join(c for c in cats if c != "moc")
        desc = ""
        for agent in vault.agents.values():
            if agent.type == "content" and agent.domain == domain:
                desc = agent.description
                break
        entry = f"- {domain}"
        if cat_str:
            entry += f" (categories: {cat_str})"
        if desc:
            entry += f": {desc}"
        lines.append(entry)

    return (
        f"Classify this topic into exactly one of the domains listed below.\n\n"
        f"Topic: {text}\n\n"
        + "\n".join(lines)
        + '\n\nReply with ONLY a JSON object, no explanation:\n{"domain": "<name>"}'
    )


# ```json fencing is so common in model output that stripping it is cheaper
# than a retry.  The regex handles both ```json and bare ``` variants.
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


async def classify_domain(
    vault: Vault, text: str, provider: LLMProvider
) -> str | None:
    """Ask the LLM to classify `text` into one of the vault's domains.

    Returns the domain name (a key in ``vault.taxonomy.domains``) or ``None``
    on *any* failure — no key, offline, rate-limited, timeout, malformed
    output, or an answer that does not match the closed set.  Never raises.

    The model proposes; the closed set disposes.
    """
    # Import Message inside the function so avicenna/providers types stay out
    # of the module-level import graph for avicenna/vault/.  LLMProvider itself
    # is imported under TYPE_CHECKING and only appears in annotations.
    from avicenna.providers.base import Message

    prompt = _build_classifier_prompt(vault, text)
    known_domains = set(vault.taxonomy.domains)

    try:
        completion = await provider.complete(
            system="You are a domain classifier. Reply with only JSON.",
            messages=[Message(role="user", content=prompt)],
            temperature=0,
            max_tokens=256,
        )
    except Exception:
        _log.debug("classify_domain provider call failed", exc_info=True)
        return None

    raw = (completion.text or "").strip()
    if not raw:
        return None

    # Strip ```json fencing defensively — models wrap JSON in fences even when
    # explicitly told not to.  Cheaper than a retry.
    fence_match = _FENCE_RE.search(raw)
    if fence_match:
        raw = fence_match.group(1).strip()

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        _log.debug("classify_domain: unparseable output: %s", raw[:200])
        return None

    if not isinstance(data, dict):
        return None
    domain = data.get("domain")
    if not isinstance(domain, str):
        return None

    if domain not in known_domains:
        _log.debug("classify_domain: unknown domain %r", domain)
        return None

    return domain
