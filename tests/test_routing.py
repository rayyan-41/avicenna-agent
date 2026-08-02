"""Routing regression suite.

Routing is stage 1 of the pipeline. When it is wrong, every downstream stage is
wrong, and the v1.0.0 scorer was wrong on 6 of 7 realistic topics without a
single test noticing. These labelled cases are the guard against that recurring.

Cases needing the real De Anima vault are skipped when it is absent, so the
suite still runs in CI. The synthetic cases always run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avicenna.vault.routing import (
    clear_cache,
    content_words,
    normalise,
    route_request,
    score_domains,
    singular,
    terms,
)
from avicenna.vault.vault import Vault

REFERENCE_VAULT = Path(r"E:\De Anima")
needs_vault = pytest.mark.skipif(
    not (REFERENCE_VAULT / "AGENTS.md").is_file(),
    reason="reference vault not present",
)


@pytest.fixture(scope="module")
def vault() -> Vault:
    clear_cache()
    return Vault.load(REFERENCE_VAULT)


# --- tokenisation -----------------------------------------------------------

def test_normalise_splits_kebab_and_strips_punctuation() -> None:
    assert normalise("Machine-Learning, and AI!") == ["machine", "learning", "and", "ai"]


def test_singular_handles_common_plurals() -> None:
    assert singular("conquests") == "conquest"
    assert singular("biographies") == "biography"
    assert singular("madhabs") == "madhab"
    assert singular("class") == "class"       # -ss must not be stripped


def test_content_words_decomposes_multiword_vocabulary() -> None:
    # The v1.0.0 bug: 'empire-and-conquest' is a trigram, so it could never
    # match prose that says "empire". Decomposition is what fixes it.
    assert content_words("empire-and-conquest") == {"empire", "conquest"}
    assert content_words("islamic-golden-age") == {"islamic", "golden", "age"}


def test_terms_drops_stopwords() -> None:
    assert "the" not in terms("The Ottoman Empire")
    assert "empire" in terms("The Ottoman Empire")


# --- the regression that matters -------------------------------------------

ROUTING_CASES: list[tuple[str, str]] = [
    # history
    ("The Ottoman Empire and its Balkan conquests", "machiavelli"),
    ("Hannibal at the Battle of Cannae", "machiavelli"),
    ("The Great Western Schism and the Holy Roman Empire", "machiavelli"),
    ("A biography of Gauss", "machiavelli"),
    # islam
    ("The ruling on raf al-yadayn in the four madhabs", "ghazali"),
    ("Aqeedah and the Ash'ari position on divine attributes", "ghazali"),
    ("Fiqh of witr prayer and its timing", "ghazali"),
    # science
    ("How transformer attention works in large language models", "haytham"),
    ("Neural networks and backpropagation algorithms", "haytham"),
    ("The Riemann hypothesis and number theory", "haytham"),
    ("Geodesic equations in astronomy", "haytham"),
    # reason
    ("Kant's epistemology and the limits of metaphysics", "avicenna"),
    ("Hegel's dialectic and the absolute idea", "avicenna"),
    # literature
    ("The myth of Orpheus and Eurydice", "tolstoy"),
    ("Narrative craft in the short story", "tolstoy"),
    # art
    ("Chevreul and Seurat on colour theory", "michelangelo"),
    ("Aesthetics of the master painters", "michelangelo"),
]


@needs_vault
@pytest.mark.parametrize("topic,expected", ROUTING_CASES)
def test_routes_to_expected_agent(vault: Vault, topic: str, expected: str) -> None:
    agent = route_request(vault, topic)
    if agent is None:
        table = "\n".join(f"      {s}" for s in score_domains(vault, topic)[:4])
        pytest.fail(f"routed to None, expected {expected}\n{table}")
    assert agent.name == expected, (
        f"{topic!r} -> {agent.name}, expected {expected}\n"
        + "\n".join(f"      {s}" for s in score_domains(vault, topic)[:4])
    )


@needs_vault
@pytest.mark.parametrize("topic", ["Test Topic", "asdf qwerty", ""])
def test_ambiguous_input_escalates(vault: Vault, topic: str) -> None:
    # Returning None is correct: a wrong domain silently produces a whole note
    # in the wrong voice, folder and taxonomy.
    assert route_request(vault, topic) is None


@needs_vault
def test_score_domains_reports_matched_terms(vault: Vault) -> None:
    scores = score_domains(vault, "The Ottoman Empire and its Balkan conquests")
    assert scores[0].agent.name == "machiavelli"
    assert scores[0].score > 0
    assert "empire" in scores[0].matched
    assert scores == sorted(scores, key=lambda s: (-s.score, s.agent.name))


@needs_vault
def test_no_substring_false_positives(vault: Vault) -> None:
    """The exact v1.0.0 failure: 'for' matching transFORmer et al."""
    scores = {s.agent.name: s for s in score_domains(vault, "transformer attention works")}
    assert "haytham" == max(scores.values(), key=lambda s: s.score).agent.name
    for junk in ("de", "for", "on", "or"):
        for s in scores.values():
            assert junk not in s.matched, f"{junk!r} matched for {s.agent.name}"


# --- synthetic vault: always runs -------------------------------------------

def _make_vault(tmp_path: Path, agents: list[tuple[str, str]]) -> Vault:
    (tmp_path / ".agents" / "agents").mkdir(parents=True)
    (tmp_path / ".agents" / "skills").mkdir(parents=True)
    (tmp_path / ".agents" / "tools").mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("# protocol\n", encoding="utf-8")
    taxonomy = {
        "version": 1,
        "schema": {"marker": "cli", "markers": ["cli", "manual"]},
        "domains": {domain: [f"{domain}-cat"] for _, domain in agents},
        "universalCategories": ["moc"],
        "folderMap": {},
        "types": ["concept"],
        "themes": [],
        "reservedModifiers": [],
    }
    (tmp_path / ".agents" / "taxonomy.json").write_text(
        json.dumps(taxonomy), encoding="utf-8"
    )
    for name, domain in agents:
        (tmp_path / ".agents" / "agents" / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: agent for {domain}\n"
            f"type: content\ndomain: {domain}\n---\n\nbody\n",
            encoding="utf-8",
        )
    clear_cache()
    return Vault.load(tmp_path)


def test_single_content_agent_always_wins(tmp_path: Path) -> None:
    """A one-agent scaffold has nothing to disambiguate, so it must not escalate."""
    v = _make_vault(tmp_path, [("scribe", "general")])
    assert route_request(v, "literally anything general").name == "scribe"


def test_domain_name_alone_is_decisive(tmp_path: Path) -> None:
    v = _make_vault(tmp_path, [("alpha", "history"), ("beta", "science")])
    assert route_request(v, "a question about history").name == "alpha"
    assert route_request(v, "a question about science").name == "beta"


def test_pipeline_agents_are_never_routing_candidates(tmp_path: Path) -> None:
    v = _make_vault(tmp_path, [("alpha", "history")])
    names = {s.agent.name for s in score_domains(v, "history")}
    assert names == {"alpha"}
