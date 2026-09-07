"""Tests for frontmatter schema detection (T33).

The harness must detect the vault's frontmatter convention and write that,
rather than imposing its own schema.  Every test uses tmp_path; none touch
the real vault.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from avicenna.bus import EventBus, drain
from avicenna.events import Event, SchemaDetected
from avicenna.pipeline.context import RunContext, RunSpec
from avicenna.pipeline.run import execute_run
from avicenna.pipeline.schema import FrontmatterSchema, detect_frontmatter_schema
from avicenna.pipeline.stages import apply_tags, build_frontmatter, _render_tags
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


def _write_note(root: Path, domain: str, filename: str, content: str) -> None:
    """Write a note into the vault."""
    path = root / domain / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


# =============================================================================
# 1. A vault whose notes use date/status/tags/note gets that schema
# =============================================================================


def test_date_status_tags_note_schema(tmp_path: Path) -> None:
    """A vault whose notes use date/status/tags/note gets that schema, in that order."""
    root = tmp_path / "vault"
    root.mkdir()

    for i in range(3):
        _write_note(root, "Art", f"note{i}.md",
                    "---\ndate: 2024-01-0{d}\nstatus: complete\ntags: [art, theory]\nnote: \"\"\n---\n\nBody.\n".format(d=i+1))

    schema = detect_frontmatter_schema(root)
    assert schema.keys == ("date", "status", "tags", "note"), f"got {schema.keys}"
    assert schema.source == "vault"


# =============================================================================
# 2. A vault whose notes use title/domain/template/tags gets that one
# =============================================================================


def test_title_domain_template_tags_schema(tmp_path: Path) -> None:
    """A vault with title/domain/template/tags gets that schema."""
    root = tmp_path / "vault"
    root.mkdir()

    for i in range(3):
        _write_note(root, "General", f"note{i}.md",
                    "---\ntitle: Note {i}\ndomain: general\ntemplate: general\ntags: [philosophy]\n---\n\nBody.\n".format(i=i))

    schema = detect_frontmatter_schema(root)
    assert schema.keys == ("title", "domain", "template", "tags"), f"got {schema.keys}"


# =============================================================================
# 3. Key ORDER matches the sample, not the harness's preference
# =============================================================================


def test_key_order_matches_sample(tmp_path: Path) -> None:
    """The schema preserves the order found in the vault's notes, not any
    hardcoded preference."""
    root = tmp_path / "vault"
    root.mkdir()

    # Unusual order: tags first, then status, then date
    for i in range(3):
        _write_note(root, "Art", f"note{i}.md",
                    "---\ntags: [art]\nstatus: draft\ndate: 2024-01-01\n---\n\nBody.\n")

    schema = detect_frontmatter_schema(root)
    assert schema.keys == ("tags", "status", "date"), f"got {schema.keys}"


# =============================================================================
# 4. Empty vault falls back to scaffold schema
# =============================================================================


def test_empty_vault_falls_back_to_scaffold(tmp_path: Path) -> None:
    """An empty vault (no notes) falls back to the scaffold schema."""
    root = tmp_path / "vault"
    root.mkdir()

    schema = detect_frontmatter_schema(root)
    assert schema.source == "fallback"
    assert "title" in schema.keys
    assert "domain" in schema.keys
    assert "template" in schema.keys
    assert "tags" in schema.keys


# =============================================================================
# 5. tags is present even when the sampled notes lacked it
# =============================================================================


def test_tags_added_even_when_notes_lack_it(tmp_path: Path) -> None:
    """The harness always includes 'tags' even when the sampled notes had none."""
    root = tmp_path / "vault"
    root.mkdir()

    for i in range(3):
        _write_note(root, "History", f"note{i}.md",
                    "---\ndate: 2024-01-01\nstatus: complete\nnote: \"\"\n---\n\nBody.\n")

    schema = detect_frontmatter_schema(root)
    assert "tags" in schema.keys, "tags must always be present"
    # The order: date, status, note from the sample, then tags appended
    assert schema.keys[-1] == "tags", f"tags must be appended: {schema.keys}"


def test_tags_render_as_flow_sequence(tmp_path: Path) -> None:
    """_render_tags still produces [a, b] flow sequence for update_moc.ps1."""
    result = _render_tags(["art", "theory", "concept"])
    assert result == "[art, theory, concept]"
    parsed = yaml.safe_load(result)
    assert parsed == ["art", "theory", "concept"]


# =============================================================================
# 6. A date key is filled with a real date, never a placeholder
# =============================================================================


def test_date_key_filled_with_real_date(tmp_path: Path) -> None:
    """A 'date' key in the schema gets today's ISO date, never YYYY-MM-DD."""
    root = tmp_path / "vault"
    root.mkdir()

    for i in range(3):
        _write_note(root, "Reason", f"note{i}.md",
                    "---\ndate: 2024-01-01\nstatus: complete\ntags: [reason]\nnote: \"\"\n---\n\nBody.\n")

    schema = detect_frontmatter_schema(root, domain="reason")
    assert "date" in schema.defaults, "date must have a default"
    today = date.today().isoformat()
    assert schema.defaults["date"] == today, f"got {schema.defaults['date']}"
    assert "YYYY" not in schema.defaults["date"], "must not be a placeholder"


# =============================================================================
# 7. Maps of Content are excluded from the sample
# =============================================================================


def test_mocs_excluded_from_sample(tmp_path: Path) -> None:
    """MOC files with a different schema do not pollute the detection."""
    root = tmp_path / "vault"
    root.mkdir()

    # Notes use date/status/tags/note
    for i in range(3):
        _write_note(root, "Art", f"note{i}.md",
                    "---\ndate: 2024-01-01\nstatus: complete\ntags: [art]\nnote: \"\"\n---\n\nBody.\n")

    # MOC uses a different schema
    _write_note(root, "Art", "Map of Contents - Art.md",
                "---\ndate: 2024-01-01\nstatus: complete\ntags: [art, moc]\nnote: \"\"\n---\n\nMOC content.\n")

    schema = detect_frontmatter_schema(root, domain="art")
    # The MOC should be excluded; detection should be based on the 3 notes.
    assert schema.keys == ("date", "status", "tags", "note"), f"got {schema.keys}"


def test_moc_with_different_schema_excluded(tmp_path: Path) -> None:
    """A MOC with a completely different schema does not affect detection."""
    root = tmp_path / "vault"
    root.mkdir()

    # Notes use a compact schema
    for i in range(3):
        _write_note(root, "Science", f"note{i}.md",
                    "---\ntitle: Note\ntags: [science]\n---\n\nBody.\n")

    # MOC uses a totally different schema
    _write_note(root, "Science", "Map of Contents - Science.md",
                "---\ndomain: science\nversion: 3\nupdated: 2024-06-01\ncount: 5\n---\n\nMOC.\n")

    schema = detect_frontmatter_schema(root, domain="science")
    assert schema.keys == ("title", "tags"), f"got {schema.keys}"


# =============================================================================
# 8. A topic containing ": " round-trips through YAML
# =============================================================================


def _parse_frontmatter_yaml(fm: str) -> dict[str, Any]:
    """Parse a frontmatter block (---\\n...\\n---\\n) into a dict."""
    import re
    m = re.match(r"---\r?\n(.*?)\r?\n---", fm, re.DOTALL)
    if m:
        body = m.group(1).strip()
    else:
        body = fm.strip().removeprefix("---").removesuffix("---").strip()
    return yaml.safe_load(body)  # type: ignore[no-any-return]


def test_topic_with_colon_round_trips_through_yaml(tmp_path: Path) -> None:
    """A topic containing ': ' must produce valid YAML frontmatter."""
    vault = _scaffold(tmp_path)

    schema = detect_frontmatter_schema(vault.root)

    ctx = RunContext(spec=RunSpec(
        topic="Art: The Sublime and the Beautiful",
        vault=vault,
        provider=FakeProvider(),
        bus=EventBus(),
        run_id="test",
    ))
    ctx.domain = "general"
    ctx.frontmatter_schema = schema

    fm = build_frontmatter(ctx, tags=["art", "aesthetics"])
    # Must parse as valid YAML
    parsed = _parse_frontmatter_yaml(fm)
    assert parsed is not None, f"YAML parse failed: {fm}"
    assert parsed["tags"] == ["art", "aesthetics"]


def test_topic_with_colon_is_quoted(tmp_path: Path) -> None:
    """A topic with ': ' is double-quoted in the YAML scalar."""
    vault = _scaffold(tmp_path)

    schema = FrontmatterSchema(keys=("title", "tags"), source="test", defaults={})
    ctx = RunContext(spec=RunSpec(
        topic="Kant: Critique of Pure Reason",
        vault=vault,
        provider=FakeProvider(),
        bus=EventBus(),
        run_id="test",
    ))
    ctx.domain = "general"
    ctx.frontmatter_schema = schema

    fm = build_frontmatter(ctx, tags=["philosophy"])
    parsed = _parse_frontmatter_yaml(fm)
    assert parsed is not None
    assert "title" in parsed


# =============================================================================
# 9. The detected schema is reported
# =============================================================================


def test_schema_detected_event_emitted(tmp_path: Path) -> None:
    """A SchemaDetected event is emitted during the run."""
    vault = _scaffold(tmp_path)

    async def _run_and_collect() -> list[Event]:
        bus = EventBus()
        queue = bus.subscribe()
        provider = FakeProvider(script=_script)
        await execute_run(TOPIC, provider, vault, bus=bus, concurrency=3)
        await bus.close()
        seen: list[Event] = []
        async for event in drain(queue):
            seen.append(event)
        return seen

    import asyncio
    events = asyncio.run(_run_and_collect())
    schema_events = [e for e in events if isinstance(e, SchemaDetected)]
    assert len(schema_events) >= 1, "must emit SchemaDetected"
    assert schema_events[0].keys, "schema keys must not be empty"


def test_schema_reported_for_real_vault() -> None:
    """The detector reports the schema for the real vault at E:\\De Anima.

    This test reads the real vault but does not write to it.
    """
    vault_path = Path(r"E:\De Anima")
    if not vault_path.is_dir():
        import pytest
        pytest.skip("real vault not available")

    schema = detect_frontmatter_schema(vault_path)
    print(f"\nReal vault schema: {' / '.join(schema.keys)}")
    print(f"Source: {schema.source}")
    print(f"Defaults: {schema.defaults}")

    assert schema.keys, "must detect at least one key"
    assert "tags" in schema.keys, "tags must always be present"


# =============================================================================
# Additional: build_frontmatter uses detected schema
# =============================================================================


def test_build_frontmatter_uses_detected_schema(tmp_path: Path) -> None:
    """build_frontmatter emits keys in the detected schema's order."""
    vault = _scaffold(tmp_path)

    schema = FrontmatterSchema(
        keys=("date", "status", "tags", "note"),
        source="test",
        defaults={"date": "2024-06-15", "status": "complete", "note": ""},
    )
    ctx = RunContext(spec=RunSpec(
        topic="Test Topic",
        vault=vault,
        provider=FakeProvider(),
        bus=EventBus(),
        run_id="test",
    ))
    ctx.domain = "general"
    ctx.frontmatter_schema = schema

    fm = build_frontmatter(ctx, tags=["philosophy", "epistemology"])
    lines = fm.strip().splitlines()

    # Must start with ---
    assert lines[0] == "---"
    # Keys must appear in schema order
    key_order = [line.split(":")[0] for line in lines[1:] if line.strip() != "---"]
    assert key_order == ["date", "status", "tags", "note"], f"got {key_order}"


def test_build_frontmatter_fills_date_from_schema_default(tmp_path: Path) -> None:
    """When schema has a 'date' default, build_frontmatter fills it."""
    vault = _scaffold(tmp_path)

    schema = FrontmatterSchema(
        keys=("date", "status", "tags"),
        source="test",
        defaults={"date": "2024-06-15", "status": "complete"},
    )
    ctx = RunContext(spec=RunSpec(
        topic="Test",
        vault=vault,
        provider=FakeProvider(),
        bus=EventBus(),
        run_id="test",
    ))
    ctx.domain = "general"
    ctx.frontmatter_schema = schema

    fm = build_frontmatter(ctx, tags=["art"])
    parsed = _parse_frontmatter_yaml(fm)
    # yaml.safe_load parses ISO dates as datetime.date objects
    assert str(parsed["date"]) == "2024-06-15"
    assert parsed["status"] == "complete"
    assert parsed["tags"] == ["art"]


def test_build_frontmatter_omits_keys_without_value_or_default(tmp_path: Path) -> None:
    """Keys with no harness value and no default are omitted."""
    vault = _scaffold(tmp_path)

    schema = FrontmatterSchema(
        keys=("date", "status", "tags", "note"),
        source="test",
        defaults={"date": "2024-06-15"},
        # status and note have no defaults and no harness value
    )
    ctx = RunContext(spec=RunSpec(
        topic="Test",
        vault=vault,
        provider=FakeProvider(),
        bus=EventBus(),
        run_id="test",
    ))
    ctx.domain = "general"
    ctx.frontmatter_schema = schema

    fm = build_frontmatter(ctx, tags=["art"])
    parsed = _parse_frontmatter_yaml(fm)
    assert "date" in parsed
    assert "tags" in parsed
    # note has no value and no default, so it must be absent
    assert "note" not in parsed


def test_build_frontmatter_fallback_without_schema(tmp_path: Path) -> None:
    """Without a detected schema, falls back to scaffold (title/domain/template/tags)."""
    vault = _scaffold(tmp_path)

    ctx = RunContext(spec=RunSpec(
        topic="Test Topic",
        vault=vault,
        provider=FakeProvider(),
        bus=EventBus(),
        run_id="test",
    ))
    ctx.domain = "general"
    # No frontmatter_schema set — fallback mode

    fm = build_frontmatter(ctx, tags=["philosophy"])
    parsed = _parse_frontmatter_yaml(fm)
    assert parsed["title"] == "Test Topic"
    assert parsed["domain"] == "general"
    assert parsed["template"] == "general"
    assert parsed["tags"] == ["philosophy"]


def test_apply_tags_preserves_model_keys(tmp_path: Path) -> None:
    """apply_tags preserves existing frontmatter keys from the model/weaver."""
    vault = _scaffold(tmp_path)

    ctx = RunContext(spec=RunSpec(
        topic="Test",
        vault=vault,
        provider=FakeProvider(),
        bus=EventBus(),
        run_id="test",
    ))
    ctx.domain = "general"
    ctx.frontmatter_schema = FrontmatterSchema(
        keys=("date", "status", "tags", "note"),
        source="test",
        defaults={"date": "2024-01-01", "status": "complete"},
    )

    existing = "---\ndate: 2024-02-20\nstatus: complete\ntags: [old, tags]\nnote: \"\"\n---\n\nBody.\n"
    result = apply_tags(existing, ctx, ["new", "tags"])

    # The existing frontmatter block must be preserved (model's date, status, note)
    assert "2024-02-20" in result, "model's date must be preserved"
    assert "note:" in result, "model's note key must be preserved"
    # Tags must be updated
    parsed = _parse_frontmatter_yaml(result)
    assert parsed["tags"] == ["new", "tags"]


def test_apply_tags_adds_frontmatter_when_absent(tmp_path: Path) -> None:
    """apply_tags builds a schema-aware frontmatter when the note has none."""
    vault = _scaffold(tmp_path)

    ctx = RunContext(spec=RunSpec(
        topic="Test",
        vault=vault,
        provider=FakeProvider(),
        bus=EventBus(),
        run_id="test",
    ))
    ctx.domain = "general"
    ctx.frontmatter_schema = FrontmatterSchema(
        keys=("date", "status", "tags"),
        source="test",
        defaults={"date": "2024-06-15", "status": "complete"},
    )

    result = apply_tags("# Heading\n\nBody.\n", ctx, ["art", "theory"])
    assert result.startswith("---\n")
    parsed = _parse_frontmatter_yaml(result)
    assert str(parsed["date"]) == "2024-06-15"
    assert parsed["status"] == "complete"
    assert parsed["tags"] == ["art", "theory"]


def test_domain_schema_detection_prefers_domain_notes(tmp_path: Path) -> None:
    """When a domain is specified, notes in that domain are preferred."""
    root = tmp_path / "vault"
    root.mkdir()

    # Art notes use date/status/tags
    for i in range(3):
        _write_note(root, "Art", f"note{i}.md",
                    "---\ndate: 2024-01-01\nstatus: complete\ntags: [art]\nnote: \"\"\n---\n\nBody.\n")

    # General notes use a different schema
    for i in range(3):
        _write_note(root, "General", f"note{i}.md",
                    "---\ntitle: Note\ndomain: general\ntags: [philosophy]\n---\n\nBody.\n")

    schema = detect_frontmatter_schema(root, domain="art")
    assert schema.keys == ("date", "status", "tags", "note"), f"got {schema.keys}"
    assert schema.source == "domain"
