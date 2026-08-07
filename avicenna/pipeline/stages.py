"""All pipeline stage implementations."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from avicenna.events import (
    LinkCandidatesFound, LogMessage, ManifestWritten, MocUpdated,
    NoteWritten, PreflightDeclared, Stage, RunComplete, TagsProposed,
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
    """
    domain = (ctx.domain or "general").replace("-", " ").title().replace(" ", " ")
    folder = ctx.spec.vault.root / domain
    folder.mkdir(parents=True, exist_ok=True)
    return folder / _safe_filename(ctx.spec.topic)


def _write_note_atomically(dest: Path, text: str) -> None:
    """Write via a sibling temp file plus os.replace.

    Obsidian indexes on write, so a partially written note would appear in
    search, in graph view, and in any git plugin's next commit.
    """
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, dest)


async def _invoke_optional(ctx: RunContext, tool: str, **kwargs):
    """invoke_tool, but returns None (with a warning) when the tool is absent."""
    if not ctx.spec.vault.tools.has(tool):
        await _skip(ctx, tool, "skipping this check")
        return None
    return await invoke_tool(ctx, tool, **kwargs)


class RoutingStage(PipelineStage):
    name: Stage = "preflight"

    async def run(self, ctx: RunContext) -> None:
        vault = ctx.spec.vault
        if ctx.spec.domain_override:
            ctx.domain = ctx.spec.domain_override
        else:
            agent = route_request(vault, ctx.spec.topic)
            if agent is None:
                raise PipelineAbort("preflight",
                    "cannot determine domain; try --domain or be more specific")
            ctx.domain = agent.domain
        ctx.agent = validate_domain(vault, ctx.domain)


class PreflightStage(PipelineStage):
    name: Stage = "preflight"

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


class ManifestStage(PipelineStage):
    name: Stage = "manifest"

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
        else:
            # The manifest is telemetry plus resume state, not a gate.
            await _skip(ctx, "write_manifest", "continuing without a manifest (--resume unavailable)")
        await ctx.emit(ManifestWritten, slug=ctx.slug, expected_count=expected)
        # Record preflight complete
        try:
            await invoke_tool(ctx, "update_pipeline_state",
                Slug=ctx.slug, Stage="preflight", Status="complete")
        except Exception:
            pass  # state sidecar is best-effort


class SectionsStage(PipelineStage):
    name: Stage = "sections"

    async def run(self, ctx: RunContext) -> None:
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
        try:
            await invoke_tool(ctx, "update_pipeline_state",
                Slug=ctx.slug, Stage="yolo", Status="complete")
        except Exception:
            pass


class AssemblyStage(PipelineStage):
    name: Stage = "assembly"

    async def run(self, ctx: RunContext) -> None:
        assert ctx.slug is not None
        expected = list(range(1, len(ctx.headings) + 1))

        # --- gate: every chunk must exist before anything is assembled -------
        if ctx.spec.vault.tools.has("verify_chunks"):
            result = await invoke_tool(ctx, "verify_chunks",
                Slug=ctx.slug, ExpectedCount=len(ctx.headings), Mode="verify")
            token = result.parsed.token if result.parsed else ""
            if token != "ALL_PRESENT":
                missing = result.parsed.captures.get("missing", "?") if result.parsed else "?"
                raise PipelineAbort("assembly",
                    f"missing chunks: {missing}/{len(ctx.headings)}; use --resume to regenerate")
            chunk_text = (await invoke_tool(ctx, "verify_chunks",
                Slug=ctx.slug, ExpectedCount=len(ctx.headings), Mode="read")).stdout or ""
        else:
            await _skip(ctx, "verify_chunks", "verifying and reading chunks in Python instead")
            missing = [i for i in expected if not ctx.chunk_path(i).is_file()]
            if missing:
                raise PipelineAbort("assembly",
                    f"missing chunks: {missing}; use --resume to regenerate")
            parts: list[str] = []
            for i in expected:
                body = ctx.chunk_path(i).read_text(encoding="utf-8", errors="replace")
                parts.append(f"<!-- CHUNK {i:02d} START -->\n{body}\n<!-- CHUNK {i:02d} END -->")
            chunk_text = "\n\n".join(parts)

        # --- assemble --------------------------------------------------------
        note_text = chunk_text
        if "weaver" in ctx.spec.vault.agents:
            weaver_prompt = (
                f"Topic: {ctx.spec.topic}\n"
                f"Slug: {ctx.slug}\n"
                f"Headings: {', '.join(ctx.headings)}\n"
                "Assemble these chunks into one note: add transitions between "
                "sections, apply the canonical frontmatter with tags: [PLACEHOLDER], "
                "and separate sections with '- - -'. Return only the note.\n"
            )
            try:
                woven = await asyncio.wait_for(
                    delegate(ctx, "weaver", chunk_text + "\n\n" + weaver_prompt),
                    timeout=300.0,
                )
                if woven and woven.strip():
                    note_text = woven
            except Exception as exc:  # noqa: BLE001 - fall back to raw chunks
                await ctx.emit(LogMessage, level="warning",
                               text=f"weaver failed ({exc}); using raw chunk text")

        # --- place it in the vault, not in _tmp ------------------------------
        dest = _note_destination(ctx)
        _write_note_atomically(dest, note_text)
        ctx.note_path = dest
        ctx.total_words = len(note_text.split())
        await ctx.emit(NoteWritten, path=str(dest), words=ctx.total_words)

        # --- cleanup only once the note is confirmed on disk -----------------
        if dest.is_file():
            if ctx.spec.vault.tools.has("cleanup_chunks"):
                await invoke_tool(ctx, "cleanup_chunks", Slug=ctx.slug)
            else:
                for i in expected:
                    ctx.chunk_path(i).unlink(missing_ok=True)
                for sidecar in ("_manifest.json", "_pipeline_state.json"):
                    (ctx.tmp_dir / f"{ctx.slug}{sidecar}").unlink(missing_ok=True)


class WordCountStage(PipelineStage):
    name: Stage = "wordcount"

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
        await ctx.emit(WordCountChecked, actual=actual, minimum=mini, verdict=verdict)
        if verdict == "fail":
            # Never blocking: the note stays on disk marked incomplete.
            await ctx.emit(LogMessage, level="warning",
                           text=f"word count {actual} below minimum {mini}")


class TocStage(PipelineStage):
    name: Stage = "toc"

    async def run(self, ctx: RunContext) -> None:
        assert ctx.note_path is not None
        if not ctx.spec.vault.tools.has("generate_toc"):
            await _skip(ctx, "generate_toc", "note will have no table of contents")
            return
        await invoke_tool(ctx, "generate_toc", FilePath=str(ctx.note_path), MinHeadings=2)


class TaggingStage(PipelineStage):
    name: Stage = "tagging"

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
                f"Tags should be comma-separated on one line, e.g. #tag1, #tag2\n"
                f"{retry_detail}"
            )
            try:
                tagger_output = await delegate(ctx, "tagger", tagger_payload)
            except Exception as exc:
                await ctx.emit(LogMessage, level="error", text=f"tagger failed: {exc}")
                break
            # Extract a tag line from the output
            lines = tagger_output.strip().split("\n")
            tag_line = ""
            for line in lines:
                if line.strip().startswith("#") or "," in line:
                    tag_line = line.strip().lstrip("#").strip()
                    break
            if not tag_line:
                tag_line = lines[-1].strip().lstrip("#").strip() if lines else ""
            if not tag_line:
                await ctx.emit(LogMessage, level="warning", text="tagger produced no identifiable tag line")
                break
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


class FormatterStage(PipelineStage):
    name: Stage = "tagging"  # grouped with tagging per spec

    async def should_run(self, ctx: RunContext) -> bool:
        return "formatter" in ctx.spec.vault.agents

    async def run(self, ctx: RunContext) -> None:
        assert ctx.note_path is not None
        handoff = ctx.handoffs.get("tagger", "")
        payload = f"Note path: {ctx.note_path}\n{handoff}"
        try:
            output = await delegate(ctx, "formatter", payload)
            ctx.handoffs["formatter"] = output
        except Exception as exc:
            await ctx.emit(LogMessage, level="error", text=f"formatter failed: {exc}")


class LinkingStage(PipelineStage):
    name: Stage = "linking"

    async def should_run(self, ctx: RunContext) -> bool:
        return "linker" in ctx.spec.vault.agents

    async def run(self, ctx: RunContext) -> None:
        assert ctx.note_path is not None
        handoff = ctx.handoffs.get("formatter", ctx.handoffs.get("tagger", ""))
        # Get related notes
        try:
            result = await _invoke_optional(ctx, "get_related_notes",
                NotePath=str(ctx.note_path), CoreTags=",".join(ctx.tags) if ctx.tags else "",
                SupportingTags="", ExcludedMentions="", TopN=5, MinScore=0.5)
            count = (
                int(result.parsed.captures.get("count", 0))
                if result is not None and result.parsed and result.parsed.ok
                else 0
            )
            await ctx.emit(LinkCandidatesFound, count=count, sample=())
            payload = f"Note path: {ctx.note_path}\n{handoff}\nRelated count: {count}"
            await delegate(ctx, "linker", payload)
        except Exception as exc:
            await ctx.emit(LogMessage, level="error", text=f"linking failed: {exc}")


class MocStage(PipelineStage):
    name: Stage = "moc"

    async def should_run(self, ctx: RunContext) -> bool:
        return ctx.domain != "reason"

    async def run(self, ctx: RunContext) -> None:
        assert ctx.domain is not None
        result = await _invoke_optional(ctx, "update_moc",
            Domain=ctx.domain,
            NoteTitle=ctx.spec.topic,
            NoteFilename=ctx.note_path.name if ctx.note_path else "",
        )
        token = result.parsed.token if result is not None and result.parsed else "SKIPPED"
        await ctx.emit(MocUpdated, result=token, path=str(ctx.note_path or ""))


def build_stages() -> list[PipelineStage]:
    return [
        RoutingStage(),
        PreflightStage(),
        ManifestStage(),
        SectionsStage(),
        AssemblyStage(),
        WordCountStage(),
        TocStage(),
        TaggingStage(),
        FormatterStage(),
        LinkingStage(),
        MocStage(),
    ]
