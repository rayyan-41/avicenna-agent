"""End-to-end pipeline tests: a topic in, a real note on disk out.

This file exists because its absence was the single most expensive gap in the
project. `avicenna/pipeline` had no test coverage at all — no test imported it —
so a suite of 84 passing tests coexisted with a pipeline that could not produce
a usable note: routing refused every realistic topic on a scaffolded vault, the
assembler emitted `<!-- CHUNK nn -->` markers instead of headings, and the
tagger's tags never reached the file because nothing ever wrote them.

Every assertion below is about the *deliverable*, not the mechanism. A note is
correct when it has frontmatter, a heading per planned section, no scaffolding
left in the body, and — when the vault has a tagger — real tags in place of a
placeholder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from avicenna.bus import EventBus, drain
from avicenna.events import Event
from avicenna.pipeline.run import execute_run
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
    """A provider that answers each stage the way a real agent would."""
    prompt = messages[-1].content if messages else ""
    if "pre-flight plan" in prompt or "JSON fence" in prompt:
        return Completion(text=_declaration())
    if "TAGS:" in prompt:
        return Completion(text="Reviewed the note.\nTAGS: philosophy, epistemology, revelation")
    if "wikilinks" in prompt:
        # The linker returns the whole note with a link woven in.
        note = prompt.split("\n\n", 1)[-1]
        return Completion(text=note.replace("reason", "[[reason]]", 1))
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


async def _run(vault: Vault, **kw: Any) -> list[Event]:
    bus = EventBus()
    queue = bus.subscribe()
    seen: list[Event] = []
    await execute_run(
        TOPIC, FakeProvider(script=_script), vault,
        bus=bus, concurrency=3, **kw,
    )
    await bus.close()
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


# --- the out-of-the-box path ------------------------------------------------


async def test_scaffolded_vault_produces_a_structured_note(tmp_path: Path) -> None:
    """`avicenna init` then a real topic must yield a usable note.

    This is the path a new user takes, and it used to fail twice: routing
    refused the topic outright, and forcing past that produced a headingless
    note full of chunk markers.
    """
    vault = _scaffold(tmp_path)
    await _run(vault)

    body = _note(vault).read_text(encoding="utf-8")

    assert body.startswith("---\n"), "note must open with frontmatter"
    assert "tags:" in body.split("---")[1], "frontmatter must carry a tags line"
    for heading in HEADINGS:
        assert f"## {heading}" in body, f"missing heading: {heading}"
    assert "CHUNK" not in body, "chunk scaffolding leaked into the delivered note"
    assert "PLACEHOLDER" not in body, "placeholder tags reached the note"


async def test_routing_accepts_any_topic_in_a_single_agent_vault(tmp_path: Path) -> None:
    """A lone content agent has nothing to disambiguate against."""
    from avicenna.vault.routing import route_request

    vault = _scaffold(tmp_path)
    for topic in (TOPIC, "The Ottoman Conquest of the Balkans", "Ibn Sina on the soul"):
        assert route_request(vault, topic) is not None, f"refused: {topic}"


async def test_tmp_is_cleaned_only_after_the_run_finishes(tmp_path: Path) -> None:
    vault = _scaffold(tmp_path)
    await _run(vault)
    leftovers = [p.name for p in vault.tmp_dir.glob("*") if p.name != ".gitignore"]
    assert leftovers == [], f"_tmp not cleaned: {leftovers}"


# --- the full-agent path ----------------------------------------------------


async def test_tagger_output_reaches_the_note(tmp_path: Path) -> None:
    """The tags the tagger proposes must end up in the file, not just in ctx."""
    vault = _scaffold(tmp_path, agents=("tagger",))
    await _run(vault)

    body = _note(vault).read_text(encoding="utf-8")
    frontmatter = body.split("---")[1]
    assert "philosophy" in frontmatter, frontmatter
    assert "epistemology" in frontmatter, frontmatter
    assert "tags: []" not in frontmatter


async def test_linker_output_reaches_the_note(tmp_path: Path) -> None:
    """A linked note that never reaches disk is the orphan we exist to prevent."""
    vault = _scaffold(tmp_path, agents=("tagger", "linker"))
    await _run(vault)

    body = _note(vault).read_text(encoding="utf-8")
    assert "[[" in body, "the linker's wikilinks were discarded"


async def test_a_truncating_agent_cannot_clobber_the_note(tmp_path: Path) -> None:
    """Write-back rejects a response that has lost most of the note."""
    vault = _scaffold(tmp_path, agents=("formatter",))

    def truncating(system: str, messages: list[Any]) -> Completion:
        prompt = messages[-1].content if messages else ""
        if "formatting corrected" in prompt:
            return Completion(text="Sure! Here is your note.")
        return _script(system, messages)

    bus = EventBus()
    await execute_run(TOPIC, FakeProvider(script=truncating), vault, bus=bus, concurrency=2)

    body = _note(vault).read_text(encoding="utf-8")
    assert "Sure! Here is your note." not in body
    for heading in HEADINGS:
        assert f"## {heading}" in body


# --- resume -----------------------------------------------------------------


async def test_resume_reuses_existing_chunks(tmp_path: Path) -> None:
    """Resume must find the interrupted run rather than minting a new slug.

    Pre-flight routes its slug through `unique_slug`, whose job is to bump the
    slug when chunks already exist — precisely the state a resume starts from.
    So resume used to regenerate everything it was meant to preserve.
    """
    from avicenna.pipeline.resume import Manifest, find_resumable, write_manifest

    vault = _scaffold(tmp_path)
    tmp = vault.tmp_dir
    write_manifest(tmp, Manifest(
        slug="epistemic-gap", headings=list(HEADINGS), expected_count=3,
        topic=TOPIC, domain="general", template="general", target_words=900,
    ))
    for i in (1, 2):
        (tmp / f"epistemic-gap_chunk_{i:02d}.md").write_text(
            f"Preserved chunk {i}.\n", encoding="utf-8", newline="\n")

    found = find_resumable(tmp, TOPIC)
    assert found is not None and found.slug == "epistemic-gap"

    provider = FakeProvider(script=_script)
    bus = EventBus()
    await execute_run(TOPIC, provider, vault, bus=bus, concurrency=2,
                      resume=True, fresh=False)

    body = _note(vault).read_text(encoding="utf-8")
    assert "Preserved chunk 1." in body, "resume discarded an existing chunk"
    assert "Preserved chunk 2." in body
    # Only the missing third section should have been generated, and pre-flight
    # must not have run again.
    assert len(provider.calls) == 1, [c["messages"][-1].content[:60] for c in provider.calls]


async def test_resume_with_nothing_to_resume_starts_fresh(tmp_path: Path) -> None:
    vault = _scaffold(tmp_path)
    await _run(vault, resume=True, fresh=False)
    body = _note(vault).read_text(encoding="utf-8")
    assert f"## {HEADINGS[0]}" in body


# --- guarantees -------------------------------------------------------------


async def test_existing_note_is_never_silently_overwritten(tmp_path: Path) -> None:
    vault = _scaffold(tmp_path)
    await _run(vault)
    first = _note(vault)
    original = first.read_text(encoding="utf-8")

    await execute_run(TOPIC, FakeProvider(script=_script), vault,
                      bus=EventBus(), concurrency=2)

    assert first.read_text(encoding="utf-8") == original, "the first note was clobbered"
    siblings = sorted(p.name for p in first.parent.glob("*.md"))
    assert len(siblings) == 2, siblings


async def test_every_missing_tool_is_announced(tmp_path: Path) -> None:
    """Degrading is fine; degrading silently is not."""
    from avicenna.events import LogMessage

    vault = _scaffold(tmp_path)
    events = await _run(vault)
    warnings = [
        e.text for e in events
        if isinstance(e, LogMessage) and "not available in this vault" in e.text
    ]
    for tool in ("verify_chunks", "validate_wordcount", "generate_toc"):
        assert any(tool in w for w in warnings), f"{tool} degraded without saying so"


async def test_dry_run_stops_before_writing_anything(tmp_path: Path) -> None:
    vault = _scaffold(tmp_path)
    await _run(vault, dry_run=True)
    notes = [p for p in vault.root.rglob("*.md")
             if ".agents" not in p.parts and p.name != "AGENTS.md"]
    assert notes == [], f"a dry run wrote {notes}"


async def test_stage_identities_are_unique() -> None:
    """Timings and the dry-run filter key on `id`, so collisions corrupt both."""
    from avicenna.pipeline.stages import build_stages

    ids = [stage.id for stage in build_stages()]
    assert len(ids) == len(set(ids)), ids


@pytest.mark.parametrize("bad", ["../outside.md", "../../etc/passwd"])
async def test_builtin_tools_refuse_paths_outside_the_vault(tmp_path: Path, bad: str) -> None:
    from avicenna.tools.builtin import ReadNoteTool

    vault = _scaffold(tmp_path)
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")
    result = await ReadNoteTool(vault.root).invoke(path=bad)
    assert not result.ok
    assert "escapes vault root" in (result.error or "")


async def test_sibling_directory_is_not_inside_the_vault(tmp_path: Path) -> None:
    """`startswith` used to accept `<root>-private` as being inside `<root>`."""
    from avicenna.tools.builtin import _safe_path

    root = tmp_path / "vault"
    root.mkdir()
    (tmp_path / "vault-private").mkdir()
    with pytest.raises(ValueError):
        _safe_path(root, "../vault-private/secrets.md")


async def test_headings_with_commas_are_accepted(tmp_path: Path) -> None:
    """Headings containing commas must not abort the run.

    The comma restriction used to live in pre-flight to protect the PowerShell
    tool's delimiter encoding.  It killed legitimate academic headings like
    "Causes, Course and Consequences".  The restriction was removed; commas are
    now sanitised only at the PS1 boundary.
    """
    from avicenna.events import PreflightDeclared

    comma_headings = [
        "Causes, Course and Consequences",
        "The Limits of Unaided Reason",
    ]

    def script(system: str, messages: list[Any]) -> Completion:
        prompt = messages[-1].content if messages else ""
        if "pre-flight plan" in prompt or "JSON fence" in prompt:
            return Completion(text=_declaration(headings=comma_headings))
        return _script(system, messages)

    vault = _scaffold(tmp_path)
    bus = EventBus()
    queue = bus.subscribe()
    await execute_run(TOPIC, FakeProvider(script=script), vault,
                      bus=bus, concurrency=3)
    await bus.close()

    # Pre-flight must have accepted the comma-containing heading.
    events: list[Event] = []
    async for ev in drain(queue):
        events.append(ev)
    preflight = [e for e in events if isinstance(e, PreflightDeclared)]
    assert len(preflight) == 1
    assert "Causes, Course and Consequences" in preflight[0].headings

    # The heading must survive through the entire pipeline into the note body.
    body = _note(vault).read_text(encoding="utf-8")
    assert "## Causes, Course and Consequences" in body
