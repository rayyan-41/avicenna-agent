"""All pipeline stage implementations."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from avicenna.events import (
    LinkCandidatesFound, LogMessage, ManifestWritten, MocUpdated,
    NoteWritten, PreflightDeclared, Stage, TagsProposed,
    TagsValidated, WordCountChecked,
)
from avicenna.pipeline.context import RunContext
from avicenna.pipeline.delegate import delegate
from avicenna.pipeline.preflight import (
    TEMPLATE_MINIMUMS, PreflightError, parse_preflight,
)
from avicenna.pipeline.stage import PipelineAbort, PipelineStage
from avicenna.pipeline.sections import generate_sections
from avicenna.pipeline.toolcall import invoke_tool
from avicenna.tools.base import ToolResult
from avicenna.vault.routing import route_request, validate_domain


# --- graceful degradation ---------------------------------------------------
# A vault may legitimately have zero PowerShell tools (`avicenna init` produces
# one). Every tool call below is optional: when the tool is absent the stage
# falls back to a Python equivalent or skips, and always says so, so a user
# never silently receives a lesser note.

async def _skip(ctx: RunContext, tool: str, what: str) -> None:
    await ctx.emit(
        LogMessage, level="warning",
        text=f"{tool} not available in this vault; {what}",
    )


def _safe_filename(title: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", title).strip().rstrip(".")
    return (cleaned or "Untitled")[:120] + ".md"


def _note_destination(ctx: RunContext) -> Path:
    """Where the finished note belongs in the vault.

    Domain folders are Title Case at the vault root (Art/, History/, ...).
    Created if absent so a scaffolded vault works on its first run.

    Never returns a path that already holds a note. The destination derives
    from the topic alone, so running the same topic twice — or two topics that
    sanitise to the same 120 characters — used to `os.replace` the earlier note
    out of existence with no event and no backup. Losing a note in the right
    vault is the same class of failure as writing into the wrong one.
    """
    domain = (ctx.domain or "general").replace("-", " ").title()
    folder = ctx.spec.vault.root / domain
    folder.mkdir(parents=True, exist_ok=True)

    candidate = folder / _safe_filename(ctx.spec.topic)
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    for n in range(2, 1000):
        alt = folder / f"{stem} ({n}).md"
        if not alt.exists():
            return alt
    raise PipelineAbort("assembly", f"cannot find a free filename beside {candidate}")


def _write_note_atomically(dest: Path, text: str) -> None:
    """Write via a sibling temp file plus os.replace.

    Obsidian indexes on write, so a partially written note would appear in
    search, in graph view, and in any git plugin's next commit.
    """
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, dest)


# --- frontmatter ------------------------------------------------------------
# The pipeline owns the frontmatter, not the model. Tagging, formatting and
# linking each hand back prose; only this module writes to the vault. Earlier
# the tagger's tags lived in ctx.tags and never reached the file, and the
# weaver was asked to emit a literal `tags: [PLACEHOLDER]` that nothing ever
# substituted — so every note shipped orphaned and unsearchable.

#: How long the weaver gets to return a whole note. Generous, because it is
#: handed the entire assembly — a 10k-word note is a large single request, and
#: a timeout here costs the transitions between sections.
WEAVER_TIMEOUT_S = 600.0

_FRONTMATTER = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---\r?\n?", re.DOTALL)
_TAGS_LINE = re.compile(r"^tags\s*:.*$", re.MULTILINE)


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_block, body). The block is '' when absent."""
    match = _FRONTMATTER.match(text)
    if match is None:
        return "", text
    return match.group(0), text[match.end():]


def _render_tags(tags: list[str]) -> str:
    cleaned = [t.strip().lstrip("#").strip() for t in tags]
    return "[" + ", ".join(t for t in cleaned if t) + "]"


def build_frontmatter(ctx: RunContext, tags: list[str] | None = None) -> str:
    """The canonical frontmatter block for this run."""
    return (
        "---\n"
        f"title: {ctx.spec.topic}\n"
        f"domain: {ctx.domain or 'general'}\n"
        f"template: {ctx.template or 'general'}\n"
        f"tags: {_render_tags(tags or [])}\n"
        "---\n"
    )


def apply_tags(text: str, ctx: RunContext, tags: list[str]) -> str:
    """Return `text` with its frontmatter `tags:` line set to `tags`.

    Adds a frontmatter block when the note has none, so a weaver-less vault
    still produces an Obsidian-indexable note.
    """
    block, body = _split_frontmatter(text)
    if not block:
        return build_frontmatter(ctx, tags) + body
    rendered = f"tags: {_render_tags(tags)}"
    if _TAGS_LINE.search(block):
        block = _TAGS_LINE.sub(rendered, block, count=1)
    else:
        block = block.rstrip()
        assert block.endswith("---")
        block = block[: -len("---")] + rendered + "\n---\n"
    return block + body


async def _write_back(ctx: RunContext, stage: str, produced: str) -> bool:
    """Persist an agent's revision of the note, if it is safe to.

    Tagging, formatting and linking all return the *whole* note. A model that
    truncates, summarises or answers conversationally would otherwise replace a
    10k-word note with a paragraph, so anything that loses more than a quarter
    of the note is rejected and the previous text stands.
    """
    assert ctx.note_path is not None
    candidate = produced.strip()
    if not candidate:
        await ctx.emit(LogMessage, level="warning",
                       text=f"{stage} returned nothing; note left unchanged")
        return False
    current = ctx.note_path.read_text(encoding="utf-8", errors="replace")
    if len(candidate) < len(current.strip()) * 0.75:
        await ctx.emit(
            LogMessage, level="warning",
            text=(f"{stage} returned {len(candidate)} chars against {len(current)} "
                  "on disk; rejected as truncation, note left unchanged"),
        )
        return False
    _write_note_atomically(ctx.note_path, candidate if candidate.endswith("\n") else candidate + "\n")
    ctx.total_words = len(candidate.split())
    return True


async def _invoke_optional(ctx: RunContext, tool: str, **kwargs: Any) -> ToolResult | None:
    """invoke_tool, but returns None (with a warning) when the tool is absent."""
    if not ctx.spec.vault.tools.has(tool):
        await _skip(ctx, tool, "skipping this check")
        return None
    return await invoke_tool(ctx, tool, **kwargs)


def _no_moc_domains(ctx: RunContext) -> set[str]:
    """Domains this vault has declared as keeping no Map of Content.

    Read from `taxonomy.json`, because which domains keep a MOC is the user's
    policy about their own vault, not the harness's business.
    """
    taxonomy = getattr(ctx.spec.vault, "taxonomy", None)
    raw = getattr(taxonomy, "no_moc", None) if taxonomy is not None else None
    if raw is None and taxonomy is not None:
        raw = getattr(taxonomy, "raw", {}).get("noMoc") if hasattr(taxonomy, "raw") else None
    return {str(d).lower() for d in raw} if raw else set()


class RoutingStage(PipelineStage):
    # Shares the "preflight" label with PreflightStage (both read as one step
    # to the user) but keeps its own identity for timings and the dry-run set.
    name: Stage = "preflight"
    id = "routing"

    async def run(self, ctx: RunContext) -> None:
        vault = ctx.spec.vault
        if ctx.spec.domain_override:
            ctx.domain = ctx.spec.domain_override
        elif ctx.domain:
            # ResumeStage already rehydrated the domain from the manifest; the
            # resumed run must stay with the agent that wrote its chunks.
            pass
        else:
            agent = route_request(vault, ctx.spec.topic)
            if agent is None:
                raise PipelineAbort("preflight",
                    "cannot determine domain; try --domain or be more specific")
            ctx.domain = agent.domain
        if not ctx.domain:
            raise PipelineAbort("preflight", "no domain resolved for this run")
        ctx.agent = validate_domain(vault, ctx.domain)


class PreflightStage(PipelineStage):
    name: Stage = "preflight"
    id = "preflight"

    async def should_run(self, ctx: RunContext) -> bool:
        # On resume the structure is rehydrated from the manifest rather than
        # re-declared. Asking the model again would mint a fresh slug (the whole
        # job of unique_slug) and could return a different heading list, which
        # would orphan every chunk the interrupted run had already paid for.
        return not ctx.resumed_from_manifest

    async def run(self, ctx: RunContext) -> None:
        assert ctx.agent is not None
        assert ctx.domain is not None
        prompt = (
            f"Topic: {ctx.spec.topic}\n"
            f"Domain: {ctx.domain}\n"
            f"Template override (if any): {ctx.spec.template_override or 'none'}\n\n"
            f"Generate a pre-flight plan in a JSON fence block.\n"
            f"Use this exact format:\n"
            "```json\n"
            "{\n"
            '  "topic": "string",\n'
            '  "domain": "string",\n'
            '  "template": "string",\n'
            '  "headings": ["heading 1", "heading 2", ...],\n'
            '  "target_words": 6000,\n'
            '  "slug": "string"\n'
            "}\n"
            "```\n"
        )
        from avicenna.session import one_shot
        raw = await one_shot(
            provider=ctx.spec.provider,
            system=ctx.agent.system_prompt,
            prompt=prompt,
            bus=ctx.spec.bus,
            run_id=ctx.spec.run_id,
        )
        decl, used_json = parse_preflight(
            raw, default_domain=ctx.domain,
            default_topic=ctx.spec.topic, tmp_dir=ctx.tmp_dir,
        )
        if not used_json:
            await ctx.emit(LogMessage, level="warning",
                          text="preflight parsed from prose fallback")
        ctx.slug = decl.slug
        ctx.template = decl.template
        ctx.headings = list(decl.headings)
        ctx.target_words = decl.target_words
        await ctx.emit(PreflightDeclared,
            topic=decl.topic, domain=decl.domain, template=decl.template,
            headings=decl.headings, target_words=decl.target_words, slug=decl.slug,
        )


class ResumeStage(PipelineStage):
    """Rehydrate slug and structure from a previous run's manifest."""

    name: Stage = "preflight"
    id = "resume"

    async def should_run(self, ctx: RunContext) -> bool:
        return bool(ctx.spec.resume)

    async def run(self, ctx: RunContext) -> None:
        from avicenna.pipeline.resume import find_resumable

        manifest = find_resumable(ctx.tmp_dir, ctx.spec.topic)
        if manifest is None:
            await ctx.emit(
                LogMessage, level="warning",
                text="nothing to resume in _tmp; starting a fresh run",
            )
            return
        ctx.slug = manifest.slug
        ctx.headings = list(manifest.headings)
        ctx.template = manifest.template or ctx.template
        ctx.target_words = manifest.target_words or ctx.target_words
        if manifest.domain:
            ctx.domain = manifest.domain
        ctx.resumed_from_manifest = True
        await ctx.emit(
            LogMessage, level="info",
            text=f"resuming {manifest.slug} with {len(manifest.headings)} headings",
        )
        await ctx.emit(PreflightDeclared,
            topic=manifest.topic or ctx.spec.topic,
            domain=ctx.domain or "general",
            template=ctx.template or "general",
            headings=tuple(ctx.headings),
            target_words=ctx.target_words,
            slug=manifest.slug,
        )


class ManifestStage(PipelineStage):
    name: Stage = "manifest"
    id = "manifest"

    async def run(self, ctx: RunContext) -> None:
        assert ctx.slug is not None
        expected = len(ctx.headings)
        if ctx.spec.vault.tools.has("write_manifest"):
            result = await invoke_tool(ctx, "write_manifest",
                Slug=ctx.slug, Headings=",".join(ctx.headings))
            if result.parsed is None or result.parsed.token != "MANIFEST_WRITTEN":
                raise PipelineAbort("manifest",
                    f"write_manifest failed: {result.parsed.token if result.parsed else result.stderr}")
            expected = int(result.parsed.captures.get("chunks", expected))

        # Written regardless of the tool: this sidecar plus its last-run pointer
        # is what makes --resume possible, and a vault with zero PowerShell
        # tools is legitimate. Without it, resume had no way back to the slug.
        from avicenna.pipeline.resume import Manifest, write_manifest
        write_manifest(ctx.tmp_dir, Manifest(
            slug=ctx.slug,
            headings=list(ctx.headings),
            expected_count=expected,
            topic=ctx.spec.topic,
            domain=ctx.domain or "",
            template=ctx.template or "",
            target_words=ctx.target_words,
        ))

        await ctx.emit(ManifestWritten, slug=ctx.slug, expected_count=expected)
        await _invoke_optional(ctx, "update_pipeline_state",
            Slug=ctx.slug, Stage="preflight", Status="complete")


class SectionsStage(PipelineStage):
    name: Stage = "sections"
    id = "sections"

    async def run(self, ctx: RunContext) -> None:
        assert ctx.slug is not None
        if ctx.spec.resume:
            from avicenna.pipeline.resume import plan_sections
            indices = plan_sections(ctx, ctx.slug, ctx.headings)
            if not indices:
                await ctx.emit(LogMessage, level="info",
                               text="all sections present from previous run; nothing to regenerate")
        else:
            indices = list(range(1, len(ctx.headings) + 1))
        if indices:
            await generate_sections(ctx, indices)
        await _invoke_optional(ctx, "update_pipeline_state",
            Slug=ctx.slug, Stage="sections", Status="complete")


class AssemblyStage(PipelineStage):
    name: Stage = "assembly"
    id = "assembly"

    async def run(self, ctx: RunContext) -> None:
        assert ctx.slug is not None
        expected = list(range(1, len(ctx.headings) + 1))

        # --- gate: every chunk must exist before anything is assembled -------
        # The gate may be a contract token from PowerShell, but the *reading*
        # is always done in Python. Routing a 10k-word note back through a
        # console's stdout invites codepage mangling and CRLF injection, and it
        # used to mean the weaver saw structurally different input depending on
        # whether the vault happened to ship a .ps1.
        if ctx.spec.vault.tools.has("verify_chunks"):
            result = await invoke_tool(ctx, "verify_chunks",
                Slug=ctx.slug, ExpectedCount=len(ctx.headings), Mode="verify")
            token = result.parsed.token if result.parsed else ""
            if token != "ALL_PRESENT":
                reported = result.parsed.captures.get("missing", "?") if result.parsed else "?"
                raise PipelineAbort("assembly",
                    f"missing chunks: {reported}/{len(ctx.headings)}; use --resume to regenerate")
        else:
            await _skip(ctx, "verify_chunks", "verifying chunks in Python instead")

        missing_indices = [i for i in expected if not ctx.chunk_path(i).is_file()]
        if missing_indices:
            listed = ", ".join(str(i) for i in missing_indices)
            raise PipelineAbort("assembly",
                f"missing chunks: {listed} of {len(ctx.headings)}; use --resume to regenerate")

        # --- assemble --------------------------------------------------------
        note_text = self._assemble(ctx, expected)
        if "weaver" in ctx.spec.vault.agents:
            weaver_prompt = (
                f"Topic: {ctx.spec.topic}\n"
                f"Slug: {ctx.slug}\n"
                f"Headings: {', '.join(ctx.headings)}\n"
                "Assemble this into one continuous note. Keep every '## ' heading "
                "exactly as written, add transitions between sections, and keep the "
                "frontmatter block at the top unchanged — the pipeline owns it and "
                "will fill in the tags. Return only the note.\n"
            )
            try:
                woven = await asyncio.wait_for(
                    delegate(ctx, "weaver", note_text + "\n\n" + weaver_prompt),
                    timeout=WEAVER_TIMEOUT_S,
                )
                if woven and woven.strip():
                    note_text = woven
            except asyncio.TimeoutError:
                # Named explicitly: TimeoutError stringifies to '', so the old
                # message read "weaver failed ()" and told the reader nothing
                # about the one failure the weaver is most likely to have —
                # a 10k-word note is a big enough request to run long.
                await ctx.emit(
                    LogMessage, level="warning",
                    text=(f"weaver timed out after {WEAVER_TIMEOUT_S:.0f}s on "
                          f"{len(note_text.split())} words; using the unwoven assembly"),
                )
            except Exception as exc:  # noqa: BLE001 - fall back to raw chunks
                detail = str(exc).strip() or type(exc).__name__
                await ctx.emit(LogMessage, level="warning",
                               text=f"weaver failed ({detail}); using the unwoven assembly")

        # --- place it in the vault, not in _tmp ------------------------------
        dest = _note_destination(ctx)
        _write_note_atomically(dest, note_text)
        ctx.note_path = dest
        ctx.total_words = len(note_text.split())
        await ctx.emit(NoteWritten, path=str(dest), words=ctx.total_words)
        # _tmp is NOT cleaned here. Four stages still have to run, and deleting
        # the chunks now would make a crash between here and the end permanently
        # unrecoverable. CleanupStage does it once the note is actually finished.

    @staticmethod
    def _assemble(ctx: RunContext, expected: list[int]) -> str:
        """Chunks into a note: frontmatter, then a heading above every body.

        Section prompts instruct the model *not* to restate its heading, on the
        promise that the assembler adds it. The fallback used to break that
        promise — it emitted `<!-- CHUNK nn START -->` delimiters and raw bodies,
        so a vault with no weaver (which is every vault `avicenna init` makes)
        shipped a headingless note with debug markers still in it.
        """
        parts: list[str] = [build_frontmatter(ctx), f"# {ctx.spec.topic}\n"]
        for i in expected:
            body = ctx.chunk_path(i).read_text(encoding="utf-8", errors="replace").strip()
            heading = ctx.headings[i - 1] if i - 1 < len(ctx.headings) else f"Section {i}"
            parts.append(f"## {heading}\n\n{body}\n")
        return "\n".join(parts)


class WordCountStage(PipelineStage):
    name: Stage = "wordcount"
    id = "wordcount"

    async def run(self, ctx: RunContext) -> None:
        assert ctx.note_path is not None
        mini = TEMPLATE_MINIMUMS.get(ctx.template or "general", 1000)

        if ctx.spec.vault.tools.has("validate_wordcount"):
            result = await invoke_tool(ctx, "validate_wordcount",
                FilePath=str(ctx.note_path), MinWords=mini,
                Template=ctx.template or "general")
            token = result.parsed.token if result.parsed else ""
            deficit = int(result.parsed.captures.get("short", 0)) if result.parsed else 0
            actual = ctx.total_words if token != "WORDCOUNT_FAIL" else max(mini - deficit, 0)
        else:
            await _skip(ctx, "validate_wordcount", "counting words in Python instead")
            body = ctx.note_path.read_text(encoding="utf-8", errors="replace")
            actual = len(body.split())
            token = "WORDCOUNT_PASS" if actual >= mini else "WORDCOUNT_FAIL"

        ctx.total_words = actual
        verdict = "fail" if token == "WORDCOUNT_FAIL" else "pass"
        ctx.wordcount_ok = verdict == "pass"
        await ctx.emit(WordCountChecked, actual=actual, minimum=mini, verdict=verdict)
        if verdict == "fail":
            # Deliberately not fatal: a short note is still worth keeping, and
            # the user can extend it. But it is recorded on the context so the
            # run does not get to claim success — RunComplete reports the
            # shortfall rather than passing a 630-word note off as a 1000-word one.
            await ctx.emit(LogMessage, level="warning",
                           text=f"word count {actual} below minimum {mini}")


class TocStage(PipelineStage):
    name: Stage = "toc"
    id = "toc"

    async def run(self, ctx: RunContext) -> None:
        assert ctx.note_path is not None
        if not ctx.spec.vault.tools.has("generate_toc"):
            await _skip(ctx, "generate_toc", "note will have no table of contents")
            return
        await invoke_tool(ctx, "generate_toc", FilePath=str(ctx.note_path), MinHeadings=2)


#: The tagger must mark its answer. Scanning for "a line containing a comma"
#: meant any ordinary prose sentence could win and be handed to the validator
#: as though it were the tag line — control flow deduced from the shape of
#: model prose, which is exactly what the contract-token discipline exists to
#: avoid. The sentinel makes extraction deterministic.
_TAGS_SENTINEL = re.compile(r"^\s*TAGS\s*:\s*(?P<tags>.+?)\s*$", re.MULTILINE | re.IGNORECASE)


def extract_tag_line(output: str) -> str:
    """Pull the declared tag line out of a tagger's response, or '' if absent."""
    match = _TAGS_SENTINEL.search(output)
    if match is None:
        return ""
    return match.group("tags").strip().strip("`").strip()


class TaggingStage(PipelineStage):
    name: Stage = "tagging"
    id = "tagging"

    async def run(self, ctx: RunContext) -> None:
        assert ctx.note_path is not None
        if "tagger" not in ctx.spec.vault.agents:
            await ctx.emit(LogMessage, level="warning", text="no tagger agent registered; skipping")
            return
        for attempt in range(1, 4):
            retry_detail = ""
            if attempt > 1 and ctx.handoffs.get("tagger_errors"):
                retry_detail = f"\nPrevious validation errors: {ctx.handoffs['tagger_errors']}"
            tagger_payload = (
                f"Note path: {ctx.note_path}\n"
                "Reply with the tags on a single line beginning with 'TAGS:', "
                "comma-separated, drawn only from the vault taxonomy.\n"
                "Example:\nTAGS: philosophy, epistemology, revelation\n"
                f"{retry_detail}"
            )
            try:
                tagger_output = await delegate(ctx, "tagger", tagger_payload)
            except Exception as exc:
                await ctx.emit(LogMessage, level="error", text=f"tagger failed: {exc}")
                break
            tag_line = extract_tag_line(tagger_output)
            if not tag_line:
                ctx.handoffs["tagger_errors"] = (
                    "no 'TAGS:' line found; reply with exactly one line starting with TAGS:"
                )
                await ctx.emit(LogMessage, level="warning",
                               text="tagger produced no TAGS: line")
                continue
            await ctx.emit(TagsProposed, tags=tuple(tag_line.split(",")))
            result = await _invoke_optional(ctx, "validate_tags", TagLine=tag_line)
            if result is None:
                # No validator in this vault: trust the tagger rather than
                # burning three attempts failing against a tool that is absent.
                ctx.tags = [t.strip() for t in tag_line.split(",") if t.strip()]
                ctx.handoffs["tagger"] = tagger_output
                await ctx.emit(TagsValidated, verdict="pass",
                               message="accepted unvalidated (validate_tags absent)",
                               accepted=tuple(ctx.tags))
                break
            token = result.parsed.token if result.parsed else ""
            if token == "PASS":
                ctx.tags = [t.strip() for t in tag_line.split(",") if t.strip()]
                ctx.handoffs["tagger"] = tagger_output
                await ctx.emit(TagsValidated, verdict="pass", accepted=tuple(ctx.tags))
                break
            else:
                ctx.handoffs["tagger_errors"] = (
                    str(result.parsed.captures.get("reasons", token)) if result.parsed else token
                )
                await ctx.emit(TagsValidated, verdict="fail", message=ctx.handoffs["tagger_errors"])
        if not ctx.tags:
            await ctx.emit(LogMessage, level="error", text="TAGGER_UNRESOLVED after 3 attempts")


class TagsWrittenStage(PipelineStage):
    """Put the validated tags into the note's frontmatter.

    Nothing used to do this. The tagger's tags lived in `ctx.tags`, the weaver
    was told to write a literal `tags: [PLACEHOLDER]`, and no model-callable
    tool can write to a note — so every note shipped with a placeholder where
    its tags belonged. The connection is the deliverable; this stage is where
    it lands on disk.
    """

    name: Stage = "tagging"
    id = "tags_written"

    async def should_run(self, ctx: RunContext) -> bool:
        return ctx.note_path is not None

    async def run(self, ctx: RunContext) -> None:
        assert ctx.note_path is not None
        current = ctx.note_path.read_text(encoding="utf-8", errors="replace")
        updated = apply_tags(current, ctx, ctx.tags)
        if updated == current:
            return
        _write_note_atomically(ctx.note_path, updated)
        if ctx.tags:
            await ctx.emit(LogMessage, level="info",
                           text=f"wrote {len(ctx.tags)} tags into the note frontmatter")
        else:
            await ctx.emit(LogMessage, level="warning",
                           text="no tags resolved; wrote an empty tags list into the frontmatter")


class FormatterStage(PipelineStage):
    name: Stage = "tagging"  # grouped with tagging in the user-facing label
    id = "formatting"

    async def should_run(self, ctx: RunContext) -> bool:
        return "formatter" in ctx.spec.vault.agents

    async def run(self, ctx: RunContext) -> None:
        assert ctx.note_path is not None
        note = ctx.note_path.read_text(encoding="utf-8", errors="replace")
        payload = (
            f"Note path: {ctx.note_path}\n"
            "Return the complete note with formatting corrected. Keep every "
            "heading and the frontmatter block. Return only the note.\n\n"
            f"{note}"
        )
        try:
            output = await delegate(ctx, "formatter", payload)
        except Exception as exc:
            await ctx.emit(LogMessage, level="error", text=f"formatter failed: {exc}")
            return
        ctx.handoffs["formatter"] = output
        # The formatter's revision is only useful if it reaches the file; it
        # used to be stored in handoffs and discarded.
        await _write_back(ctx, "formatter", output)


class LinkingStage(PipelineStage):
    name: Stage = "linking"
    id = "linking"

    async def should_run(self, ctx: RunContext) -> bool:
        return "linker" in ctx.spec.vault.agents

    async def run(self, ctx: RunContext) -> None:
        assert ctx.note_path is not None
        try:
            result = await _invoke_optional(ctx, "get_related_notes",
                NotePath=str(ctx.note_path), CoreTags=",".join(ctx.tags) if ctx.tags else "",
                SupportingTags="", ExcludedMentions="", TopN=5, MinScore=0.5)
            count = (
                int(result.parsed.captures.get("count", 0))
                if result is not None and result.parsed and result.parsed.ok
                else 0
            )
            related = (result.stdout or "").strip() if result is not None else ""
            await ctx.emit(LinkCandidatesFound, count=count, sample=())
            note = ctx.note_path.read_text(encoding="utf-8", errors="replace")
            payload = (
                f"Note path: {ctx.note_path}\n"
                f"Related notes found: {count}\n"
                f"{related}\n\n"
                "Weave [[wikilinks]] to genuinely related notes into the prose. "
                "Do not invent notes that do not exist. Keep the frontmatter and "
                "every heading. Return only the complete note.\n\n"
                f"{note}"
            )
            output = await delegate(ctx, "linker", payload)
        except Exception as exc:
            await ctx.emit(LogMessage, level="error", text=f"linking failed: {exc}")
            return
        # A linked note that never reaches disk is the orphan this program
        # exists to prevent; the return value used to be thrown away entirely.
        if await _write_back(ctx, "linker", output):
            ctx.handoffs["linker"] = output


class MocStage(PipelineStage):
    name: Stage = "moc"
    id = "moc"

    async def should_run(self, ctx: RunContext) -> bool:
        # Whether a domain keeps a Map of Content is vault policy, declared in
        # the taxonomy. It used to be a bare `!= "reason"` — one vault's domain
        # name hardcoded into the engine.
        return ctx.domain not in _no_moc_domains(ctx)

    async def run(self, ctx: RunContext) -> None:
        assert ctx.domain is not None
        result = await _invoke_optional(ctx, "update_moc",
            Domain=ctx.domain,
            NoteTitle=ctx.spec.topic,
            NoteFilename=ctx.note_path.name if ctx.note_path else "",
        )
        token = result.parsed.token if result is not None and result.parsed else "SKIPPED"
        await ctx.emit(MocUpdated, result=token, path=str(ctx.note_path or ""))


class CleanupStage(PipelineStage):
    """Delete `_tmp` artifacts — last, once the note is genuinely finished.

    This used to happen inside AssemblyStage, the moment the note first hit
    disk. Four stages still ran after it, so a crash or a cancel anywhere in
    tagging, formatting, linking or MOC left an untagged, unlinked note in the
    vault with every chunk already deleted — unrecoverable, and `--resume` could
    not help because its inputs were gone.
    """

    name: Stage = "moc"
    id = "cleanup"

    async def should_run(self, ctx: RunContext) -> bool:
        return ctx.note_path is not None and ctx.note_path.is_file()

    async def run(self, ctx: RunContext) -> None:
        assert ctx.slug is not None
        if ctx.spec.vault.tools.has("cleanup_chunks"):
            await invoke_tool(ctx, "cleanup_chunks", Slug=ctx.slug)
        else:
            await _skip(ctx, "cleanup_chunks", "removing _tmp artifacts in Python instead")
        # Run the Python sweep regardless: the tool may not remove the manifest
        # sidecars, and leaving them behind would make the next run on this
        # topic mint a bumped slug it does not need.
        for i in range(1, len(ctx.headings) + 1):
            chunk = ctx.chunk_path(i)
            chunk.unlink(missing_ok=True)
            chunk.with_suffix(chunk.suffix + ".part").unlink(missing_ok=True)
        for sidecar in ("_manifest.json", "_pipeline_state.json"):
            (ctx.tmp_dir / f"{ctx.slug}{sidecar}").unlink(missing_ok=True)
        _forget_last_run(ctx)


def _forget_last_run(ctx: RunContext) -> None:
    """Drop this run's entry from the resume pointer once it has completed."""
    import json

    from avicenna.pipeline.resume import LAST_RUN

    pointer = ctx.tmp_dir / LAST_RUN
    try:
        index = json.loads(pointer.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(index, dict):
        return
    index.pop(ctx.spec.topic, None)
    if index.get("__last__") == ctx.slug:
        index.pop("__last__", None)
    try:
        if index:
            pointer.write_text(json.dumps(index, indent=2), encoding="utf-8", newline="\n")
        else:
            # Nothing left to point at; leaving an empty index behind would be
            # the only artifact a completed run failed to clean up.
            pointer.unlink(missing_ok=True)
    except OSError:
        pass


def build_stages() -> list[PipelineStage]:
    return [
        # Resume first: it recovers the domain, slug and headings, and routing
        # then honours the domain it recovered instead of re-deciding.
        ResumeStage(),
        RoutingStage(),
        PreflightStage(),
        ManifestStage(),
        SectionsStage(),
        AssemblyStage(),
        WordCountStage(),
        TocStage(),
        TaggingStage(),
        TagsWrittenStage(),
        FormatterStage(),
        LinkingStage(),
        MocStage(),
        CleanupStage(),
    ]
