"""Keyword-based domain routing fallback.

Scores the user request against each content agent's description plus
that domain's category and theme vocabulary. Ties escalate to the user.
The chosen domain is always validated against the taxonomy.
"""

from __future__ import annotations

from avicenna.vault import AgentDef, Taxonomy, Vault


def route_request(vault: Vault, text: str) -> AgentDef | None:
    """Keyword-scoring fallback. Returns None if no clear match."""
    scores: list[tuple[int, AgentDef]] = []
    text_lower = text.lower()
    for agent in vault.agents.values():
        if agent.type != "content":
            continue
        score = 0
        desc_words = set(agent.description.lower().split())
        score += sum(1 for w in desc_words if w in text_lower)
        domain = agent.domain or ""
        if domain in vault.taxonomy.domains:
            cats = vault.taxonomy.categories_for(domain)
            themes = [t.lower() for t in vault.taxonomy.themes]
            for w in text_lower.split():
                if w in cats or w in themes:
                    score += 2
        scores.append((score, agent))
    if not scores:
        return None
    scores.sort(key=lambda x: (-x[0], x[1].name))
    best_score = scores[0][0]
    if best_score == 0:
        return None
    winners = [a for s, a in scores if s == best_score]
    # Tie: escalate to user
    if len(winners) > 1:
        return None
    return winners[0]


def validate_domain(vault: Vault, domain: str) -> AgentDef:
    if domain not in vault.taxonomy.domains:
        raise ValueError(
            f"unknown domain {domain!r}; known: {sorted(vault.taxonomy.domains)}"
        )
    return vault.content_agent_for(domain)
