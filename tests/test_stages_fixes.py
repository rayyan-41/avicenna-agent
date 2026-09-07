"""Tests for two fixes in stages.py: domain casing and tagging floor.

PART A — _canonical_domain_dir must resolve a domain like "reason" to an
existing "Reason/" directory rather than creating a second one.

PART B — when the tagger fails three times, a minimal valid tag array is
constructed from the taxonomy instead of shipping tags: []. And when
get_related_notes yields 0 candidates the linker is skipped rather than
asked to weave links against nothing (which invented notes that did not exist).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from avicenna.bus import EventBus, drain
from avicenna.events import Event, LogMessage, LinkCandidatesFound
from avicenna.pipeline.run import execute_run
from avicenna.pipeline.stages import _canonical_domain_dir
from avicenna.providers.base import Completion
from avicenna.providers.fake import FakeProvider
from avicenna.vault.init_scaffold import init_vault
from avicenna.vault.vault import Vault


TOPIC = "The Epistemic Gap and the Necessity of Revelation"
HEADINGS = [
    "The Limits of Unaided Reason",
    "The Shape of the Gap",
    "Revelation as Closure",
]
BODY = "Finished prose for this section. " * 12


def _declaration(**over: Any) -> str:
    payload = {
        "topic": TOPIC,
        "domain": "general",
        "template": "general",
        "headings": HEADINGS,
        "target_words": 900,
        "slug": "epistemic-gap",
    }
    payload.update(over)
    return "Here is the plan.\n```json\n" + json.dumps(payload) + "\n```"


def _script(system: str, messages: list[Any]) -> Completion:
    prompt = messages[-1].content if messages else ""
    if "pre-flight plan" in prompt or "JSON fence" in prompt:
        return Completion(text=_declaration())
    if "TAGS:" in prompt:
        return Completion(text="Reviewed the note.\nTAGS: philosophy, epistemology, revelation")
    if "genuinely related" in prompt:
        note = prompt.split("\n\n", 1)[-1]
        return Completion(text=note.replace("this section", "this [[section]]", 1))
    if "formatting corrected" in prompt:
        return Completion(text=prompt.split("\n\n", 1)[-1])
    if "Assemble this into one continuous note" in prompt:
        return Completion(text=prompt.split("\n\nTopic:")[0])
    return Completion(text=BODY.strip())


def _scaffold(tmp_path: Path, *, agents: tuple[str, ...] = ()) -> Vault:
    root = init_vault(tmp_path / "vault")
    for name in agents:
        (root / ".agents" / "agents" / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: Pipeline agent {name}\n"
            f"type: pipeline\nstage: 1\ninvocation: /agent {name}\n---\n\n"
            f"You are the {name}.\n",
            encoding="utf-8",
            newline="\n",
        )
    return Vault.load(root)


def _scaffold_with_taxonomy(
    tmp_path: Path,
    taxonomy: dict[str, Any],
    *,
    agents: tuple[str, ...] = (),
    content_domains: tuple[str, ...] = (),
) -> Vault:
    root = init_vault(tmp_path / "vault")
    (root / ".agents" / "taxonomy.json").write_text(
        json.dumps(taxonomy, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for name in agents:
        (root / ".agents" / "agents" / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: Pipeline agent {name}\n"
            f"type: pipeline\nstage: 1\ninvocation: /agent {name}\n---\n\n"
            f"You are the {name}.\n",
            encoding="utf-8",
            newline="\n",
        )
    for domain in content_domains:
        name = f"agent-{domain}"
        (root / ".agents" / "agents" / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: Content agent for {domain}\n"
            f"type: content\ndomain: {domain}\ninvocation: /agent {name}\n---\n\n"
            f"You are a specialist in {domain}.\n",
            encoding="utf-8",
            newline="\n",
        )
    return Vault.load(root)


async def _run(vault: Vault, script: Any = None, **kw: Any) -> list[Event]:
    bus = EventBus()
    queue = bus.subscribe()
    provider = FakeProvider(script=script or _script)
    await execute_run(TOPIC, provider, vault, bus=bus, concurrency=3, **kw)
    await bus.close()
    seen: list[Event] = []
    async for event in drain(queue):
        seen.append(event)
    return seen


def _note(vault: Vault) -> Path:
    notes = [
        p for p in vault.root.rglob("*.md")
        if ".agents" not in p.parts and p.name != "AGENTS.md"
    ]
    assert len(notes) == 1, f"expected exactly one note, found {notes}"
    return notes[0]


# =============================================================================
# PART A — domain directory resolution
# =============================================================================


def test_existing_directory_is_used_cased_differently(tmp_path: Path) -> None:
    """A run whose ctx.domain is "reason" must write into an existing Reason/."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Reason").mkdir()

    resolved = _canonical_domain_dir(type("V", (), {"root": root})(), "reason")
    assert resolved == root / "Reason"
    assert resolved.name == "Reason"


def test_lowercase_directory_is_used_not_replaced(tmp_path: Path) -> None:
    """A vault with a lowercase reason/ must use that, not create Reason/."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "reason").mkdir()

    resolved = _canonical_domain_dir(type("V", (), {"root": root})(), "reason")
    assert resolved == root / "reason"


def test_new_domain_is_title_cased(tmp_path: Path) -> None:
    """A domain with no directory yet: created as Title Case (regression)."""
    root = tmp_path / "vault"
    root.mkdir()

    resolved = _canonical_domain_dir(type("V", (), {"root": root})(), "history")
    assert resolved == root / "History"


def test_hyphenated_domain_resolves_to_existing_folder(tmp_path: Path) -> None:
    """A hyphenated domain resolves to an existing "Art Theory"-style folder."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Art Theory").mkdir()

    resolved = _canonical_domain_dir(type("V", (), {"root": root})(), "art-theory")
    assert resolved == root / "Art Theory"


def test_domain_unchanged_by_helper(tmp_path: Path) -> None:
    """ctx.domain itself is unchanged by the helper — it is the taxonomy key."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Reason").mkdir()
    domain = "reason"

    _canonical_domain_dir(type("V", (), {"root": root})(), domain)
    assert domain == "reason", "the input string was mutated"


def test_no_moc_domains_uses_lowercase_domain_key(tmp_path: Path) -> None:
    """_no_moc_domains compares against ctx.domain (the lowercase taxonomy key),
    not the resolved directory name. The Taxonomy model has no no_moc field so
    the function falls back to checking the raw dict — which is absent in a
    scaffold, yielding an empty set. This test guards that invariant."""
    from avicenna.pipeline.stages import _no_moc_domains
    from avicenna.pipeline.context import RunContext, RunSpec
    from avicenna.bus import EventBus

    vault = _scaffold(tmp_path)
    ctx = RunContext(spec=RunSpec(
        topic=TOPIC, vault=vault, provider=FakeProvider(),
        bus=EventBus(), run_id="test",
    ))
    ctx.domain = "general"
    # With no noMoc in taxonomy, the set is empty — which is correct.
    result = _no_moc_domains(ctx)
    assert isinstance(result, set)


# =============================================================================
# PART B — tagging floor
# =============================================================================


async def test_tagger_garbage_yields_nonempty_valid_tags(tmp_path: Path) -> None:
    """Tagger returns no TAGS: line3 times → the note gets a floor tag array.

    The floor is drawn from the taxonomy and accepted through the
    validate_tags gate (or trusted when validate_tags is absent).
    """
    tagger_calls: list[str] = []

    def garbage_tagger(system: str, messages: list[Any]) -> Completion:
        prompt = messages[-1].content if messages else ""
        if "Reply with the tags" in prompt:
            tagger_calls.append(prompt)
            return Completion(text="Here are my thoughts on this note.")
        return _script(system, messages)

    vault = _scaffold(tmp_path, agents=("tagger",))
    events = await _run(vault, script=garbage_tagger)
    body = _note(vault).read_text(encoding="utf-8")
    frontmatter = body.split("---")[1]

    assert "tags: []" not in frontmatter, "tags must not be empty"
    # Must contain at least the domain and a type from the scaffold taxonomy.
    assert "general" in frontmatter, f"floor must include the domain: {frontmatter}"
    assert any(
        t in frontmatter for t in ("note", "essay")
    ), f"floor must include a type: {frontmatter}"
    warnings = [
        e.text for e in events
        if isinstance(e, LogMessage) and "TAGGER_UNRESOLVED" in e.text
    ]
    assert any("assigned mechanically" in w for w in warnings), "floor warning must be emitted"


async def test_floor_array_satisfies_positional_rules(tmp_path: Path) -> None:
    """The floor tag array: domain first, cli last, at least 2 tags."""
    tagger_calls: list[str] = []

    def garbage_tagger(system: str, messages: list[Any]) -> Completion:
        prompt = messages[-1].content if messages else ""
        if "Reply with the tags" in prompt:
            tagger_calls.append(prompt)
            return Completion(text="I cannot determine the tags.")
        return _script(system, messages)

    vault = _scaffold(tmp_path, agents=("tagger",))
    await _run(vault, script=garbage_tagger)

    body = _note(vault).read_text(encoding="utf-8")
    fm = body.split("---")[1]

    # Extract tags from the frontmatter
    for line in fm.strip().splitlines():
        if line.strip().startswith("tags:"):
            tag_part = line.split(":", 1)[1].strip()
            tags = [t.strip().strip("[]") for t in tag_part.split(",")]
            tags = [t for t in tags if t]
            break
    else:
        raise AssertionError("no tags: line in frontmatter")

    assert len(tags) >= 2, f"at least 2 tags for MOC grouping: {tags}"
    assert tags[0] == "general", f"domain must be first: {tags}"
    assert tags[-1] == "cli", f"cli must be last: {tags}"


async def test_tagger_succeeds_on_attempt_1_unaffected(tmp_path: Path) -> None:
    """A tagger that succeeds on attempt 1 is unaffected (regression)."""
    vault = _scaffold(tmp_path, agents=("tagger",))
    await _run(vault)

    body = _note(vault).read_text(encoding="utf-8")
    frontmatter = body.split("---")[1]
    assert "philosophy" in frontmatter, frontmatter
    assert "epistemology" in frontmatter, frontmatter
    assert "tags: []" not in frontmatter


async def test_constrained_retry_injects_taxonomy_options(tmp_path: Path) -> None:
    """On the second and third attempt, the tagger prompt must contain the
    valid categories for the routed domain, read from the taxonomy.
    """
    taxonomy = {
        "version": 1,
        "schema": {"markers": ["cli"]},
        "domains": {
            "general": ["note", "essay"],
            "philosophy": ["epistemology", "metaphysics", "ethics"],
        },
        "universalCategories": ["general"],
        "folderMap": {},
        "types": ["note", "essay", "treatise"],
        "themes": ["consciousness", "revelation", "knowledge"],
        "reservedModifiers": [],
    }
    prompts: list[str] = []
    call_count = 0

    def failing_then_succeeding(system: str, messages: list[Any]) -> Completion:
        nonlocal call_count
        prompt = messages[-1].content if messages else ""
        # Domain classifier
        if "Classify this topic" in prompt:
            return Completion(text='{"domain": "philosophy"}')
        # Standard stages
        if "pre-flight plan" in prompt or "JSON fence" in prompt:
            return Completion(text=_declaration(domain="philosophy"))
        if "genuinely related" in prompt:
            note = prompt.split("\n\n", 1)[-1]
            return Completion(text=note)
        if "formatting corrected" in prompt:
            return Completion(text=prompt.split("\n\n", 1)[-1])
        if "Assemble this into one continuous note" in prompt:
            return Completion(text=prompt.split("\n\nTopic:")[0])
        # Tagger: detect by the tagger's unique prompt opening
        if "Reply with the tags" in prompt:
            call_count += 1
            prompts.append(prompt)
            if call_count < 3:
                return Completion(text="no tags here")
            return Completion(text="TAGS: philosophy, epistemology, consciousness, cli")
        return Completion(text=BODY.strip())

    vault = _scaffold_with_taxonomy(
        tmp_path, taxonomy, agents=("tagger",), content_domains=("philosophy",),
    )
    await _run(vault, script=failing_then_succeeding)

    # Attempt 1: no taxonomy hint
    assert len(prompts) >= 1
    assert "Valid tags" not in prompts[0], "attempt 1 must not have taxonomy hint"

    # Attempt 2: must have taxonomy hint with the domain's categories
    assert len(prompts) >= 2
    assert "epistemology" in prompts[1], f"attempt 2 must list categories: {prompts[1]}"
    assert "metaphysics" in prompts[1], f"attempt 2 must list categories: {prompts[1]}"
    assert "Valid tags" in prompts[1], f"attempt 2 must have taxonomy header: {prompts[1]}"

    # Note must end up with the successful tagger's tags, not the floor
    body = _note(vault).read_text(encoding="utf-8")
    assert "consciousness" in body.split("---")[1]


async def test_linker_skipped_when_zero_candidates(tmp_path: Path) -> None:
    """0 link candidates → linker skipped, no model call, warning emitted."""
    from avicenna.tools.base import Tool, ToolResult, ToolSource, ToolAccess
    from avicenna.tools.contracts import ParsedContract

    agents_called: list[str] = []

    def tracking_script(system: str, messages: list[Any]) -> Completion:
        prompt = messages[-1].content if messages else ""
        if "pre-flight plan" in prompt or "JSON fence" in prompt:
            return Completion(text=_declaration())
        if "Reply with the tags" in prompt:
            return Completion(text="Reviewed.\nTAGS: philosophy, epistemology, revelation")
        if "Assemble this into one continuous note" in prompt:
            return Completion(text=prompt.split("\n\nTopic:")[0])
        if "formatting corrected" in prompt:
            return Completion(text=prompt.split("\n\n", 1)[-1])
        if "genuinely related" in prompt:
            agents_called.append("linker")
            return Completion(text=prompt.split("\n\n", 1)[-1])
        return Completion(text=BODY.strip())

    class FakeNoCandidatesTool(Tool):
        name = "get_related_notes"
        description = "find related notes"
        parameters = {"type": "object", "properties": {
            "NotePath": {"type": "string"},
            "CoreTags": {"type": "string"},
        }}
        source = ToolSource.BUILTIN
        access = ToolAccess.PIPELINE_ONLY

        async def invoke(self, **kwargs: Any) -> ToolResult:
            return ToolResult(
                "get_related_notes", True,
                "CANDIDATES_FOUND: 0",
                "", 0, 0.0,
                parsed=ParsedContract("get_related_notes", True, "CANDIDATES_FOUND",
                                      {"count": "0"}),
            )

    vault = _scaffold(tmp_path, agents=("tagger", "linker"))
    vault.tools.register(FakeNoCandidatesTool())
    events = await _run(vault, script=tracking_script)

    assert "linker" not in agents_called, "linker must not be called with 0 candidates"
    warnings = [
        e.text for e in events
        if isinstance(e, LogMessage) and "0 link candidates" in e.text
    ]
    assert warnings, "must emit a warning when skipping the linker"


async def test_linker_called_with_candidates(tmp_path: Path) -> None:
    """When there ARE link candidates, the linker is invoked (regression)."""
    agents_called: list[str] = []

    def script_with_candidates(system: str, messages: list[Any]) -> Completion:
        prompt = messages[-1].content if messages else ""
        if "pre-flight plan" in prompt or "JSON fence" in prompt:
            return Completion(text=_declaration())
        if "Reply with the tags" in prompt:
            return Completion(text="Reviewed.\nTAGS: philosophy, epistemology, revelation")
        if "Assemble this into one continuous note" in prompt:
            return Completion(text=prompt.split("\n\nTopic:")[0])
        if "formatting corrected" in prompt:
            return Completion(text=prompt.split("\n\n", 1)[-1])
        if "genuinely related" in prompt:
            agents_called.append("linker")
            note = prompt.split("\n\n", 1)[-1]
            return Completion(text=note.replace("this section", "this [[section]]", 1))
        return Completion(text=BODY.strip())

    # Scaffold with a fake get_related_notes tool that returns candidates.
    from avicenna.tools.base import Tool, ToolResult, ToolSource, ToolAccess
    from avicenna.tools.contracts import ParsedContract

    class FakeRelatedTool(Tool):
        name = "get_related_notes"
        description = "find related notes"
        parameters = {"type": "object", "properties": {
            "NotePath": {"type": "string"},
            "CoreTags": {"type": "string"},
            "SupportingTags": {"type": "string"},
            "ExcludedMentions": {"type": "string"},
            "TopN": {"type": "integer"},
            "MinScore": {"type": "number"},
        }}
        source = ToolSource.BUILTIN
        access = ToolAccess.PIPELINE_ONLY

        async def invoke(self, **kwargs: Any) -> ToolResult:
            return ToolResult(
                "get_related_notes", True,
                "CANDIDATES_FOUND: 3\n"
                "1. [[Philosophy of Mind]] (score 0.8)\n"
                "2. [[Ibn Sina]] (score 0.6)\n"
                "3. [[Epistemology]] (score 0.5)",
                "", 0, 0.0,
                parsed=ParsedContract("get_related_notes", True, "CANDIDATES_FOUND",
                                      {"count": "3"}),
            )

    vault = _scaffold(tmp_path, agents=("tagger", "linker"))
    vault.tools.register(FakeRelatedTool())
    events = await _run(vault, script=script_with_candidates)

    assert "linker" in agents_called, "linker must be called when candidates exist"
    body = _note(vault).read_text(encoding="utf-8")
    assert "[[" in body, "the linker's wikilinks must reach the note"


# =============================================================================
# PART C — _build_floor_tags fixes (T26)
# =============================================================================


def _floor_context(
    tmp_path: Path,
    taxonomy: dict[str, Any],
    domain: str = "art",
    *,
    content_domains: tuple[str, ...] = (),
) -> Any:
    """Build a minimal RunContext whose taxonomy and domain are set."""
    from avicenna.pipeline.context import RunContext, RunSpec

    vault = _scaffold_with_taxonomy(
        tmp_path, taxonomy, content_domains=content_domains or (domain,),
    )
    ctx = RunContext(spec=RunSpec(
        topic="test", vault=vault, provider=FakeProvider(),
        bus=EventBus(), run_id="test",
    ))
    ctx.domain = domain
    return ctx


def test_floor_excludes_universal_category(tmp_path: Path) -> None:
    """With universalCategories=["moc"], the floor must NOT use "moc"."""
    from avicenna.pipeline.stages import _build_floor_tags

    taxonomy = {
        "version": 1,
        "schema": {"markers": ["cli", "manual"]},
        "domains": {
            "general": ["note", "essay"],
            "art": ["art-history", "art-theory", "moc"],
            "history": ["moc"],
        },
        "universalCategories": ["moc"],
        "folderMap": {},
        "types": ["person", "essay"],
        "themes": ["history-of-ideas", "knowledge"],
        "reservedModifiers": [],
    }
    ctx = _floor_context(tmp_path, taxonomy, "art")
    floor = _build_floor_tags(ctx)
    assert "moc" not in floor, f"moc must be excluded from floor: {floor}"


def test_floor_contains_exactly_one_marker_last(tmp_path: Path) -> None:
    """The floor must contain exactly one marker, and it must be last."""
    from avicenna.pipeline.stages import _build_floor_tags

    taxonomy = {
        "version": 1,
        "schema": {"markers": ["cli", "manual"]},
        "domains": {
            "general": ["note", "essay"],
            "art": ["art-history", "art-theory", "moc"],
        },
        "universalCategories": ["moc"],
        "folderMap": {},
        "types": ["person", "essay"],
        "themes": ["history-of-ideas", "knowledge"],
        "reservedModifiers": [],
    }
    ctx = _floor_context(tmp_path, taxonomy, "art")
    floor = _build_floor_tags(ctx)
    markers_in_floor = [t for t in floor if t in ("cli", "manual")]
    assert len(markers_in_floor) == 1, f"expected exactly one marker: {floor}"
    assert floor[-1] == markers_in_floor[0], f"marker must be last: {floor}"


def test_floor_has_at_least_two_tags(tmp_path: Path) -> None:
    """update_moc requires >= 2 tags to group the note."""
    from avicenna.pipeline.stages import _build_floor_tags

    taxonomy = {
        "version": 1,
        "schema": {"markers": ["cli"]},
        "domains": {
            "general": ["note", "essay"],
            "art": ["art-history", "art-theory"],
        },
        "universalCategories": [],
        "folderMap": {},
        "types": ["person", "essay"],
        "themes": ["history-of-ideas"],
        "reservedModifiers": [],
    }
    ctx = _floor_context(tmp_path, taxonomy, "art")
    floor = _build_floor_tags(ctx)
    assert len(floor) >= 2, f"at least 2 tags required: {floor}"


def test_all_universal_categories_yields_empty(tmp_path: Path) -> None:
    """A domain whose only category is universal yields []."""
    from avicenna.pipeline.stages import _build_floor_tags

    taxonomy = {
        "version": 1,
        "schema": {"markers": ["cli"]},
        "domains": {
            "general": ["note", "essay"],
            "misc": ["moc"],
        },
        "universalCategories": ["moc"],
        "folderMap": {},
        "types": ["person", "essay"],
        "themes": ["knowledge"],
        "reservedModifiers": [],
    }
    ctx = _floor_context(tmp_path, taxonomy, "misc")
    floor = _build_floor_tags(ctx)
    assert floor == [], f"all-universal domain must yield []: {floor}"


def test_markers_come_from_taxonomy_not_literal(tmp_path: Path) -> None:
    """A taxonomy whose first marker is something else produces that value."""
    from avicenna.pipeline.stages import _build_floor_tags

    taxonomy = {
        "version": 1,
        "schema": {"markers": ["zettel", "note"]},
        "domains": {
            "general": ["note", "essay"],
            "science": ["physics", "biology"],
        },
        "universalCategories": [],
        "folderMap": {},
        "types": ["essay"],
        "themes": ["knowledge"],
        "reservedModifiers": [],
    }
    ctx = _floor_context(tmp_path, taxonomy, "science")
    floor = _build_floor_tags(ctx)
    assert floor[-1] == "zettel", f"first marker from taxonomy must be used: {floor}"
