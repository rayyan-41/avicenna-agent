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
from avicenna.vault.routing import classify_domain, route_request, validate_domain
from avicenna.vault.vault import Vault


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


# --- domain directory resolution ---------------------------------------------
# Two places derive a vault path from `ctx.domain` and they used to disagree.
# `_note_destination` applied `.replace("-", " ").title()` (yielding "Reason")
# while `MocStage` passed the raw `ctx.domain` (yielding "reason") to
# update_moc.ps1, which built filenames and directory paths from it. On Windows
# the case mismatch was invisible (one file), but git tracked "Reason/Map of
# Contents - Reason.md" and "Reason/Map of Contents - reason.md" as distinct
# paths — and on a case-sensitive filesystem a second, competing MOC and domain
# directory would appear beside the real one.  A single helper now resolves the
# canonical directory for both call sites.

def _canonical_domain_dir(vault: Vault, domain: str) -> Path:
    """Resolve the vault's canonical directory name for *domain*.

    If a directory at the vault root already matches *domain*
    case-insensitively (tolerating ``"-"`` vs ``" "``), return THAT
    directory — canonical by construction, correct on any filesystem.

    When no such directory exists, fall back to Title Case so a scaffolded
    vault works on its first run.
    """
    norm = domain.replace("-", " ").lower()
    for child in vault.root.iterdir():
        if child.is_dir() and child.name.replace("-", " ").lower() == norm:
            return child
    return vault.root / domain.replace("-", " ").title()


def _note_destination(ctx: RunContext) -> Path:
    """Where the finished note belongs in the vault.

    Domain folders are Title Case at the vault root (Art/, History/, ...).
    Created if absent so a scaffolded vault works on its first run.

    Uses `_canonical_domain_dir` so that a domain like "reason" resolves to
    an existing "Reason/" directory rather than creating a second, differently
    cased one.

    Never returns a path that already holds a note. The destination derives
    from the topic alone, so running the same topic twice — or two topics that
    sanitise to the same 120 characters — used to `os.replace` the earlier note
    out of existence with no event and no backup. Losing a note in the right
    vault is the same class of failure as writing into the wrong one.
    """
    folder = _canonical_domain_dir(ctx.spec.vault, ctx.domain or "general")
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

# Production models sometimes return an UNTERMINATED frontmatter block — an
# opening `---`, some `key: value` lines, and then straight into the note with
# no closing `---`.  `_FRONTMATTER` is non-greedy, so it matches from the top
# down to the FIRST later `---` line — and a Markdown note is full of `---`
# horizontal rules.  Everything up to that rule is classified as "frontmatter"
# and, because `_write_back` discards the candidate's frontmatter by design,
# that content is DELETED.
#
# Measured on a realistic note (script output, not speculation):
#
#     written = True
#     TOC survived       : False      <-- the whole Table of Contents was deleted
#     stray 'date:' leak : False
#     frontmatter ok     : True
#     body chars 9622 vs disk 9687    <-- 0.7% loss
#
# 0.7% is far under the 25% truncation guard, so the write SUCCEEDS and nothing
# is reported.  A stage output (the `toc` stage's table of contents) disappears
# silently.  With a larger malformed block, whole sections would go the same way.
#
# When the loss happens to exceed 25% the truncation guard does catch it and the
# note is left unchanged — safe, but it also throws away the formatter's entire
# legitimate revision.  Both outcomes are wrong.
#
# The root problem is that "starts with ---" is being treated as proof of
# frontmatter.  It is not.  Frontmatter is YAML-ish: every non-blank line is a
# key: value, a list item, or an indented continuation.  The strict parser below
# validates that shape before trusting the frontmatter boundary.

_YAMLISH_LINE = re.compile(
    r"^\s*(?:[A-Za-z_][\w.-]*\s*:|\s+-\s)",
    re.MULTILINE,
)


def _strip_malformed_frontmatter(text: str) -> tuple[str, str]:
    """Drop a malformed leading block and return (dropped_prefix, body).

    When the text starts with ``---`` but the enclosed lines are not all
    YAML-ish, or there is no closing ``---``, the block is malformed.
    Instead of trusting the first later ``---`` (which may be a horizontal
    rule), we drop only the leading run of key-ish lines and return
    everything from the first non-key-ish line onward as body.
    """
    lines = text.split("\n")
    # Skip the opening ---
    idx = 1
    # Consume blank lines and YAML-ish lines
    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            idx += 1
            continue
        if _YAMLISH_LINE.match(line):
            idx += 1
            continue
        break
    dropped = "\n".join(lines[:idx])
    body = "\n".join(lines[idx:])
    return dropped, body


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


def _unwrap_model_output(text: str) -> str:
    """Strip chat preamble and code fences a chatty model wraps around a note.

    Ministral-8b (and models like it) commonly prepend "Here is the corrected
    note:" and wrap the real content in a ```markdown fence.  This helper
    peels those wrappers off so the pipeline sees clean Markdown.

    Conservative by design: when nothing matches, the input is returned
    unchanged.  Idempotent — f(f(x)) == f(x) — because the inner content of
    an already-unwrapped note never starts with a fence that closes at the
    very end (a legitimate note continues past any code block it contains).
    """
    if not text:
        return text

    # --- unwrap a fenced block that IS the bulk of the output ---------------
    # Only match when the fence opens the content (possibly after a preamble)
    # and closes at the very end.  A fenced block mid-note is legitimate
    # Markdown (code examples, etc.) and must not be touched.
    # re doesn't support variable-length back-references (``` vs ~~~), so we
    # try each fence type separately and match only when the fence opens AND
    # closes the output.
    for close_fence in ("```", "~~~"):
        pattern = re.compile(
            r"(?s)^(?P<preamble>.*?)\r?\n?"
            + re.escape(close_fence) + r"(?P<info>[a-zA-Z0-9_-]*)\r?\n"
            r"(?P<body>.+?)\r?\n"
            + re.escape(close_fence) + r"\s*\Z",
        )
        m = pattern.match(text)
        if m:
            # The fence must actually open the real content, not wrap a code
            # block that sits inside longer prose.  If the preamble already
            # contains a heading or frontmatter, the fence is mid-note.
            preamble = m.group("preamble").strip()
            if not preamble or not (
                preamble.startswith("---") or preamble.startswith("#")
            ):
                return m.group("body")

    # --- drop a leading conversational preamble -----------------------------
    # Any lines before the first line that is exactly "---" (frontmatter open)
    # or starts with "#" (a heading).  When no such anchor exists, change
    # nothing — the model may have returned body-only prose on purpose.
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "---" or stripped.startswith("#"):
            if i > 0:
                return "\n".join(lines[i:])
            break

    return text


async def _write_back(ctx: RunContext, stage: str, produced: str) -> bool:
    """Persist an agent's revision of the note, if it is safe to.

    The pipeline owns the frontmatter, not the model.  The on-disk
    frontmatter is ALWAYS preserved — the model's version is discarded
    whether or not it looks correct.  A model that reformats ``tags: [a, b]``
    into ``tags: a, b`` would silently break the MOC tool's regex; the
    guarantee must not depend on the model behaving.

    Truncation is checked against body lengths, not whole-file lengths, so a
    model that drops the frontmatter does not spend that against the 25%
    budget.
    """
    assert ctx.note_path is not None
    candidate = _unwrap_model_output(produced).strip()
    if not candidate:
        await ctx.emit(LogMessage, level="warning",
                       text=f"{stage} returned nothing; note left unchanged")
        return False
    current = ctx.note_path.read_text(encoding="utf-8", errors="replace")

    # --- preserve the on-disk frontmatter ------------------------------------
    disk_fm, disk_body = _split_frontmatter(current)
    cand_fm, cand_body = _split_frontmatter(candidate)

    # Detect malformed frontmatter: starts with --- but the enclosed lines
    # are not all YAML-ish, or there is no closing ---.
    if candidate.startswith("---") and cand_fm:
        # Validate the enclosed lines
        fm_lines = cand_fm.strip().split("\n")
        # Skip opening and closing ---
        inner_lines = fm_lines[1:-1] if len(fm_lines) > 2 else []
        all_yamlish = all(
            not line.strip() or _YAMLISH_LINE.match(line)
            for line in inner_lines
        )
        if not all_yamlish:
            # The block is malformed: drop only the leading run of key-ish lines
            await ctx.emit(
                LogMessage, level="warning",
                text=f"{stage}: model returned malformed frontmatter block; "
                     "discarding leading key-ish lines only",
            )
            _, cand_body = _strip_malformed_frontmatter(candidate)
            cand_fm = ""

    if disk_fm:
        # The disk note owns the frontmatter.  If the model produced its own
        # frontmatter that differs, warn so the user sees the model defect.
        if cand_fm and cand_fm.strip() != disk_fm.strip():
            await ctx.emit(
                LogMessage, level="warning",
                text=(f"{stage}: model returned frontmatter that differed from "
                      "the on-disk copy; the model's frontmatter was discarded"),
            )
        result_text = disk_fm + cand_body
        result_body = cand_body.strip()
        ref_body = disk_body.strip()
    else:
        # No frontmatter on disk (a vault with no tagger is legitimate).
        result_text = candidate
        result_body = candidate
        ref_body = current.strip()

    # --- truncation check on BODY lengths ------------------------------------
    if len(result_body) < len(ref_body) * 0.75:
        await ctx.emit(
            LogMessage, level="warning",
            text=(f"{stage} returned {len(result_body)} body chars against "
                  f"{len(ref_body)} on disk; rejected as truncation, note left unchanged"),
        )
        return False

    _write_note_atomically(ctx.note_path, result_text if result_text.endswith("\n") else result_text + "\n")
    ctx.total_words = len(result_text.split())
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
            # 1. LLM classifier — fast semantic classification against the
            #    vault's closed domain set.
            domain = await classify_domain(vault, ctx.spec.topic, ctx.spec.provider)
            if domain is not None:
                ctx.domain = domain
                await ctx.emit(LogMessage, level="info",
                    text=f"domain resolved by classifier: {domain}")
            else:
                # 2. Deterministic scorer — the offline fallback.  Still pinned
                #    by the original weight constants and thirty regression tests.
                agent = route_request(vault, ctx.spec.topic)
                if agent is not None:
                    ctx.domain = agent.domain
                    await ctx.emit(LogMessage, level="info",
                        text=f"domain resolved by scorer: {agent.domain}")
                else:
                    await ctx.emit(LogMessage, level="warning",
                        text="domain unresolved: classifier and scorer both returned None")
                    raise PipelineAbort("preflight",
                        "cannot determine domain; try --domain or be more specific")
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
            # The tool receives a lossy rendering of the headings: commas inside
            # individual headings are replaced with semicolons because the
            # PowerShell argument uses comma as a delimiter.  This is acceptable
            # because the pipeline consumes only the chunk COUNT from the tool's
            # return value (result.parsed.captures.get("chunks", ...)), not the
            # heading text.  The real headings — in the Python manifest, chunk
            # filenames, resume, and the note itself — keep their commas intact.
            safe_headings = [h.replace(",", ";") for h in ctx.headings]
            result = await invoke_tool(ctx, "write_manifest",
                Slug=ctx.slug, Headings=",".join(safe_headings))
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
    # --- tagging floor -------------------------------------------------------
    # Three defects in the old tagger:
    #
    # 1. Retries re-sent the same prompt plus the raw validator error, asking
    #    the model to guess from a closed vocabulary it was never shown.
    #    Now attempts 2-3 inject the actual valid options from the vault
    #    taxonomy for the routed domain.
    #
    # 2. After three failures the pipeline continued with `tags: []`, which
    #    orphaned the note permanently: update_moc.ps1 skips notes with fewer
    #    than 2 tags (the note never enters its MOC), and get_related_notes
    #    returns 0 candidates (which is why the linker invented notes that do
    #    not exist). Now a minimal valid array is constructed from the taxonomy
    #    and passed through validate_tags like any other candidate.
    #
    # 3. Even the constructed array can fail if the taxonomy is malformed or
    #    validate_tags has a stricter rule. In that case we fall through to
    #    today's empty-tags behaviour, but LinkingStage now refuses to ask a
    #    model to weave links against 0 candidates — that was the direct cause
    #    of the invented wikilinks.

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
            # On attempts 2-3, inject the actual valid options so the model is
            # not asked to guess from a closed vocabulary it was never shown.
            taxonomy_hint = ""
            if attempt > 1:
                taxonomy_hint = _taxonomy_hint(ctx)
            tagger_payload = (
                f"Note path: {ctx.note_path}\n"
                "Reply with the tags on a single line beginning with 'TAGS:', "
                "comma-separated, drawn only from the vault taxonomy.\n"
                "Example:\nTAGS: philosophy, epistemology, revelation\n"
                f"{taxonomy_hint}{retry_detail}"
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
        # --- deterministic floor: construct a minimal valid tag array ---------
        if not ctx.tags:
            floor = _build_floor_tags(ctx)
            if floor:
                floor_line = ", ".join(floor)
                result = await _invoke_optional(ctx, "validate_tags", TagLine=floor_line)
                if result is None:
                    ctx.tags = floor
                    await ctx.emit(TagsValidated, verdict="pass",
                                   message="accepted floor tags unvalidated (validate_tags absent)",
                                   accepted=tuple(ctx.tags))
                    await ctx.emit(LogMessage, level="warning",
                                   text="TAGGER_UNRESOLVED: tags assigned mechanically from taxonomy (validate_tags absent)")
                elif result.parsed and result.parsed.token == "PASS":
                    ctx.tags = floor
                    await ctx.emit(TagsValidated, verdict="pass",
                                   message="accepted floor tags (mechanical assignment)",
                                   accepted=tuple(ctx.tags))
                    await ctx.emit(LogMessage, level="warning",
                                   text="TAGGER_UNRESOLVED after 3 attempts: tags assigned mechanically from taxonomy; correct this note")
                else:
                    await ctx.emit(LogMessage, level="error",
                                   text="TAGGER_UNRESOLVED after 3 attempts; floor tags also failed validation")
            else:
                await ctx.emit(LogMessage, level="error",
                               text="TAGGER_UNRESOLVED after 3 attempts; cannot build floor tags (taxonomy incomplete)")


def _taxonomy_hint(ctx: RunContext) -> str:
    """Build a taxonomy options hint for constrained tagger retries.

    Reads from the vault's taxonomy.json (never hardcoded) so each vault's
    own vocabulary is what the tagger sees.
    """
    taxonomy = getattr(ctx.spec.vault, "taxonomy", None)
    if taxonomy is None or not ctx.domain:
        return ""
    try:
        categories = taxonomy.categories_for(ctx.domain)
    except Exception:
        categories = []
    types = list(taxonomy.types) if hasattr(taxonomy, "types") else []
    themes = list(taxonomy.themes) if hasattr(taxonomy, "themes") else []
    lines = [
        f"\nValid tags for the routed domain ({ctx.domain}):",
        f"  Domain (exactly 1): {ctx.domain}",
        f"  Category (exactly 1): {', '.join(categories)}" if categories else "  Category: (none available)",
        f"  Type (exactly 1): {', '.join(types)}" if types else "  Type: (none available)",
        f"  Themes (1-3): {', '.join(themes)}" if themes else "  Themes: (none available)",
        "  Entities (0-6): open vocabulary",
        "  cli must be the last tag.",
        "The positional order is: domain, category, type, themes..., entities..., cli\n",
    ]
    return "\n".join(lines)


def _build_floor_tags(ctx: RunContext) -> list[str]:
    """Construct a minimal valid tag array from the vault taxonomy.

    Returns [] when the taxonomy lacks the information needed to build one.
    The array follows the positional contract: [domain, category, type,
    themes..., marker]. Never invents values — everything is drawn from the
    taxonomy.

    Universal categories (like "moc") are EXCLUDED, not preferred.  An earlier
    version preferred them, which meant "moc" was chosen for every domain.
    Because update_moc.ps1 skips notes whose tags[1] is "moc"
    (`if ($tags[1] -eq 'moc') { continue }`), tagging an ordinary note with
    "moc" in position 1 silently un-lists it — the note ships but never enters
    its Map of Content.  The validator also rejects "moc" alongside a topical
    category in the same array.

    Exactly one marker is appended (always the taxonomy's first), not all of
    them.  The validator requires exactly one marker; appending every marker
    (e.g. both "cli" and "manual") always fails.
    """
    taxonomy = getattr(ctx.spec.vault, "taxonomy", None)
    if taxonomy is None or not ctx.domain:
        return []
    try:
        categories = taxonomy.categories_for(ctx.domain)
    except Exception:
        categories = []
    if not categories:
        return []
    types = list(taxonomy.types) if hasattr(taxonomy, "types") else []
    if not types:
        return []
    themes = list(taxonomy.themes) if hasattr(taxonomy, "themes") else []
    markers = taxonomy.markers if hasattr(taxonomy, "markers") else ["cli"]

    # Exclude structural/universal categories — they are not topics.  A domain
    # whose only category is universal cannot yield a valid floor.
    universal = set(getattr(taxonomy, "universal_categories", []))
    topical = [c for c in categories if c not in universal]
    if not topical:
        return []
    category = topical[0]

    floor: list[str] = [ctx.domain, category, types[0]]
    if themes:
        floor.append(themes[0])
    # Exactly one marker, always the taxonomy's first.
    floor.append(markers[0])
    return floor


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
    # When get_related_notes yields 0 candidates, the linker was asked to weave
    # links against an empty candidate list and invented notes that do not exist.
    # Now we skip the model call entirely and warn the user.
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
            if result is not None and count == 0:
                await ctx.emit(
                    LogMessage, level="warning",
                    text="0 link candidates found; skipping linker to avoid invented wikilinks",
                )
                return
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
        # Pass the vault's canonical directory name (not ctx.domain) so
        # update_moc.ps1 builds the filename and directory path from the
        # vault's own casing. ctx.domain is the lowercase taxonomy key; the
        # filesystem name may differ (Reason/ not reason/).
        domain_dir = _canonical_domain_dir(ctx.spec.vault, ctx.domain)
        result = await _invoke_optional(ctx, "update_moc",
            Domain=domain_dir.name,
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
