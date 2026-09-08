"""All pipeline stage implementations."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from avicenna.events import (
    LogMessage, ManifestWritten, MarkdownNormalised,
    MocUpdated, NoteWritten, PlanApprovalRequested, PreflightDeclared,
    SchemaDetected, Stage,
    TagsProposed, TagsValidated, ThemeMinted, TransitionsApplied,
    WordCountChecked,
)
from avicenna.pipeline.normalise import normalise_markdown
from avicenna.pipeline.schema import FrontmatterSchema, detect_frontmatter_schema
from avicenna.pipeline.structure import apply_structure
from avicenna.pipeline.context import RunContext
from avicenna.pipeline.delegate import delegate
from avicenna.pipeline.preflight import PreflightError, parse_preflight
from avicenna.pipeline.stage import PipelineAbort, PipelineStage
from avicenna.pipeline.sections import generate_sections
from avicenna.pipeline.toolcall import invoke_tool
from avicenna.settings import load_vault_config, resolve_words_per_heading
from avicenna.tools.base import ToolResult
from avicenna.vault.routing import classify_domain, route_request, validate_domain
from avicenna.vault.registry import ThemeRegistry, _normalize as _normalize_tag
from avicenna.vault.vault import Vault, tag_form


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

def _canonical_domain_dir(vault: Vault, domain: str) -> Path | None:
    """Resolve the vault's canonical directory name for *domain*.

    If a directory at the vault root already matches *domain*
    case-insensitively (tolerating ``"-"`` vs ``" "``), return THAT
    directory — canonical by construction, correct on any filesystem.

    When no such directory exists, return ``None``.  Under the derivation
    doctrine a domain with no folder is a routing failure, not licence to
    invent structure in the user's vault.
    """
    norm = domain.replace("-", " ").lower()
    for child in vault.root.iterdir():
        if child.is_dir() and child.name.replace("-", " ").lower() == norm:
            return child
    return None


def _note_destination(ctx: RunContext) -> Path:
    """Where the finished note belongs in the vault.

    Domain folders are resolved from the vault's actual folder tree.
    When the domain does not map to an existing directory the run is
    aborted — the harness must never create a domain folder to satisfy a
    route.

    Never returns a path that already holds a note. The destination derives
    from the topic alone, so running the same topic twice — or two topics that
    sanitise to the same 120 characters — used to `os.replace` the earlier note
    out of existence with no event and no backup. Losing a note in the right
    vault is the same class of failure as writing into the wrong one.
    """
    domain = ctx.domain
    if not domain:
        raise PipelineAbort("assembly", "no domain resolved for this run")
    folder = _canonical_domain_dir(ctx.spec.vault, domain)
    if folder is None:
        available = sorted(ctx.spec.vault.domain_names)
        raise PipelineAbort(
            "assembly",
            f"domain {domain!r} has no folder in the vault; "
            f"available domains: {', '.join(available)}",
        )

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
# The pipeline owns the frontmatter, not the model. Tagging and formatting
# each hand back prose; only this module writes to the vault. Earlier
# the tagger's tags lived in ctx.tags and never reached the file, and the
# weaver was asked to emit a literal `tags: [PLACEHOLDER]` that nothing ever
# substituted — so every note shipped orphaned and unsearchable.

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


# A topic containing ": " produces invalid YAML frontmatter — an unquoted
# scalar with colon-space is ambiguous YAML at best and a parse failure at
# worst.  Every consumer (Obsidian, update_moc.ps1, get_related_notes) sees
# a broken block.  The quoting rule belongs to the writer, not the caller's
# luck, so all frontmatter scalars pass through this guard.
_YAML_INDICATORS = set("- ? : , [ ] { } & * ! | > % @ `")
_YAML_BOOL_NULL = frozenset({
    "true", "false", "null", "~",
    "True", "False", "Null",
    "TRUE", "FALSE", "NULL",
})


def _needs_yaml_quote(value: str) -> bool:
    """Return True when *value* must be double-quoted in a YAML scalar."""
    if not value:
        return True
    if ": " in value or " #" in value or value.startswith("#"):
        return True
    if value[0] in _YAML_INDICATORS:
        return True
    if value.startswith('"') or value.startswith("'"):
        return True
    if "\n" in value:
        return True
    if value != value.strip():
        return True
    if value in _YAML_BOOL_NULL:
        return True
    try:
        float(value)
        return True
    except ValueError:
        pass
    return False


def _quote_yaml_scalar(value: str) -> str:
    """Double-quote *value* for a YAML scalar when quoting is required.

    Returns the value unquoted when it is safe to leave bare, so existing
    notes stay byte-identical.
    """
    if not _needs_yaml_quote(value):
        return value
    # Collapse newlines to spaces (a title must not span lines).
    collapsed = value.replace("\n", " ").replace("\r", "")
    escaped = collapsed.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_frontmatter(ctx: RunContext, tags: list[str] | None = None) -> str:
    """The canonical frontmatter block for this run.

    Uses the detected schema when available so the note matches the vault's
    own convention.  Falls back to the scaffold schema only when the vault
    has no notes to learn from.
    """
    schema = ctx.frontmatter_schema
    lines = ["---"]
    if schema and schema.keys:
        value_map: dict[str, str] = {}
        value_map["tags"] = _render_tags(tags or [])
        value_map["title"] = ctx.spec.topic
        if ctx.domain:
            value_map["domain"] = ctx.domain
        if ctx.template:
            value_map["template"] = ctx.template
        for k in schema.keys:
            if k == "tags":
                # tags is a YAML flow sequence ([a, b]) and must not be
                # quoted — _quote_yaml_scalar would wrap the brackets in
                # double quotes, turning the list into a plain string.
                lines.append(f"tags: {value_map['tags']}")
            elif k in value_map:
                lines.append(f"{k}: {_quote_yaml_scalar(value_map[k])}")
            elif k in schema.defaults:
                lines.append(f"{k}: {_quote_yaml_scalar(schema.defaults[k])}")
            # Keys with no value and no default are omitted — the harness
            # does not invent content for a key just to fill it.
    else:
        lines.append(f"title: {_quote_yaml_scalar(ctx.spec.topic)}")
        if ctx.domain:
            lines.append(f"domain: {_quote_yaml_scalar(ctx.domain)}")
        if ctx.template:
            lines.append(f"template: {_quote_yaml_scalar(ctx.template)}")
        lines.append(f"tags: {_render_tags(tags or [])}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# --- duplicate-frontmatter-in-fence ----------------------------------------
# A live run produced this, and it reached disk verbatim:
#
#     ---
#     date: YYYY-MM-DD
#     ...
#     ---
#     ```markdown
#     ---
#     date: YYYY-MM-DD
#     ...
#     ---
#
#     # What makes an object art...
#
# The model emitted a frontmatter block, then a ```markdown fence containing a
# SECOND copy of the same block plus the whole note.  Because the text opens
# with `---`, the existing guard treated the fence as mid-note and left it.
# `_write_back` then kept the disk frontmatter and appended a body that began
# with a stray fence and a duplicate block.
#
# The fix: when the body after a leading frontmatter block consists ENTIRELY of
# a fenced code block (opening immediately, closing at the very end), unwrap
# that fence and return the frontmatter plus the fence's contents.  Then the
# existing frontmatter handling in `_write_back` discards the duplicate block
# inside the fence, exactly like any other model-supplied frontmatter.


def _extract_body_from_frontmatter_fence(text: str) -> str | None:
    """When *text* is frontmatter wrapping a fenced body, return the unwrapped form.

    Returns ``None`` when the pattern does not match.  The pattern is narrow
    and conservative: a legitimate note whose body contains a code block
    followed by prose will never match because the fence does not close at
    the very end.
    """
    fm = _FRONTMATTER.match(text)
    if fm is None:
        return None
    remaining = text[fm.end():]
    if not remaining.strip():
        return None
    for close_fence in ("```", "~~~"):
        fence_pattern = re.compile(
            re.escape(close_fence) + r"([a-zA-Z0-9_-]*)\r?\n"
            r"(.+?)\r?\n?"
            + re.escape(close_fence) + r"\s*\Z",
            re.DOTALL,
        )
        m = fence_pattern.match(remaining)
        if m:
            return fm.group(0) + m.group(2)
    return None


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


def _unwrap_model_output(text: str) -> tuple[str, bool]:
    """Strip chat preamble and code fences a chatty model wraps around a note.

    Ministral-8b (and models like it) commonly prepend "Here is the corrected
    note:" and wrap the real content in a ```markdown fence.  This helper
    peels those wrappers off so the pipeline sees clean Markdown.

    Conservative by design: when nothing matches, the input is returned
    unchanged.  Idempotent — f(f(x)) == f(x) — because the inner content of
    an already-unwrapped note never starts with a fence that closes at the
    very end (a legitimate note continues past any code block it contains).

    Returns ``(text, unwrapped_fence)`` where *unwrapped_fence* is ``True``
    when a fenced body after frontmatter was stripped — a model defect the
    caller should warn about.
    """
    if not text:
        return text, False

    did_unwrap_fence = False

    # --- frontmatter wrapping a fenced body ----------------------------------
    # A live run produced a frontmatter block followed by a ```markdown fence
    # containing a SECOND copy of the same block plus the whole note.  Because
    # the text opened with `---`, the guard below treated the fence as mid-note
    # and left it.  When the body after a leading frontmatter block consists
    # ENTIRELY of a fenced code block (opening immediately, closing at the very
    # end), unwrap that fence and re-enter so a duplicate block inside is
    # discarded like any other model-supplied frontmatter.
    extracted = _extract_body_from_frontmatter_fence(text)
    if extracted is not None:
        did_unwrap_fence = True
        text = extracted

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
                return m.group("body"), did_unwrap_fence

    # --- drop a leading conversational preamble -----------------------------
    # Any lines before the first line that is exactly "---" (frontmatter open)
    # or starts with "#" (a heading).  When no such anchor exists, change
    # nothing — the model may have returned body-only prose on purpose.
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "---" or stripped.startswith("#"):
            if i > 0:
                return "\n".join(lines[i:]), did_unwrap_fence
            break

    return text, did_unwrap_fence


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
    candidate, did_unwrap_fence = _unwrap_model_output(produced)
    candidate = candidate.strip()
    if did_unwrap_fence:
        await ctx.emit(
            LogMessage, level="warning",
            text=f"{stage}: unwrapped a fenced code block that wrapped the body "
                 "after the frontmatter block (model defect)",
        )
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

    # --- normalise structural damage ------------------------------------------
    # The formatter and tagger push whole-note model output through this
    # function.  Models over-eagerly produce horizontal rules and break
    # heading spacing; the normaliser is idempotent and frontmatter-safe, so
    # it runs on every revision that passes through this funnel.  The guard
    # runs after normalisation so it validates the bytes that actually land on
    # disk.  ref_body is itself already normalised (by AssemblyStage or an
    # earlier pass through this function), so both sides of the ratio are
    # like-for-like.
    words_before_norm = len(result_text.split())
    norm = normalise_markdown(result_text)
    if norm.text != result_text:
        result_text = norm.text
        # Re-split structurally rather than slicing at the pre-normalisation
        # frontmatter length.  The slice is only correct when the normaliser
        # leaves the frontmatter byte-identical; _split_frontmatter makes no
        # such assumption.
        _, norm_body = _split_frontmatter(result_text)
        result_body = norm_body.strip()
        await ctx.emit(
            MarkdownNormalised,
            stage=stage,
            rules_removed=norm.rules_removed,
            consecutive_rules_collapsed=norm.consecutive_rules_collapsed,
            adjacent_rules_removed=norm.adjacent_rules_removed,
            words_before=words_before_norm,
            words_after=len(result_text.split()),
        )

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
            "Headings may optionally carry a form marker: "
            "[Table] for a comparative table, [Mermaid Diagram] for a "
            "Mermaid diagram.  Example: "
            '"[Table] Comparative Matrix of Theological Positions".\n'
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
        ctx.section_forms = list(decl.forms)
        ctx.target_words = decl.target_words
        await ctx.emit(PreflightDeclared,
            topic=decl.topic, domain=decl.domain, template=decl.template,
            headings=decl.headings, target_words=decl.target_words, slug=decl.slug,
        )

        # --- approval gate ---------------------------------------------------
        # When on_plan is set, the human (or an explicit auto-approve) decides
        # whether this plan should run.  Approval sets concurrency to the
        # heading count — one API call per heading, all concurrent — which is
        # safe because a human has seen the number.  The configured ceiling
        # (MAX_CONCURRENCY_MAX) does not apply here; the real upper bound is
        # parse_preflight's 40-heading refusal.  When on_plan is None no gate
        # runs and concurrency stays on the configured precedence chain —
        # this is the default that keeps tests, gen_matrix and the bridge
        # unchanged.
        if ctx.on_plan is not None:
            approved_concurrency = len(decl.headings)
            await ctx.emit(PlanApprovalRequested,
                topic=decl.topic, domain=decl.domain, template=decl.template,
                headings=decl.headings, target_words=decl.target_words,
                concurrency=approved_concurrency,
            )
            approved = await ctx.on_plan(decl)
            if not approved:
                raise PipelineAbort("preflight", "plan declined by user")
            ctx.approved_concurrency = approved_concurrency


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
        ctx.section_forms = list(manifest.forms)
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
        # Detect the frontmatter schema before any note is written so every
        # stage writes the same convention.  Cached on ctx for the run.
        if ctx.frontmatter_schema is None:
            schema = detect_frontmatter_schema(
                ctx.spec.vault.root, domain=ctx.domain,
            )
            ctx.frontmatter_schema = schema
            await ctx.emit(
                SchemaDetected, keys=schema.keys, source=schema.source,
            )
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
            forms=list(ctx.section_forms) if ctx.section_forms else None,
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

        # The whole-note weaver round-trip was removed 2026-09-09.  It sent
        # the entire assembled note to a "weaver" agent and replaced the body
        # with whatever came back — on a live run this destroyed 72% of a
        # 9,000-word note (reduced to ~2,500 words) and injected paragraphs
        # about subjects the note was not about.  Nothing caught it because
        # _write_note_atomically has no truncation guard (unlike _write_back).
        #
        # The replacement is TransitionStage, which runs after assembly and
        # before word count.  It sends only a skeleton (topic, headings,
        # first/last sentence per paragraph) to the weaver model and splices
        # one transition sentence per section back into the note body.  The
        # note body never round-trips through a model.

        # --- resolve hallucinated wikilinks ----------------------------------
        # A model writing transition prose can spontaneously produce [[links]]
        # to notes that do not exist.  Resolve every [[target]] against the
        # vault's note index; unresolvable links are unwrapped to plain text.
        dest = _note_destination(ctx)
        note_text = await _resolve_wikilinks(
            note_text, ctx.spec.vault, dest, ctx,
        )

        # --- normalise structural damage --------------------------------------
        # Models over-eagerly produce horizontal rules and break heading
        # spacing.  The normaliser collapses consecutive rules, removes rules
        # adjacent to headings, caps blank-line runs, and ensures a blank line
        # around every heading — idempotently, with fenced code blocks
        # byte-identical and frontmatter untouched.  It is called here, after
        # the weaver round-trip and before the note reaches the vault, so every
        # note on disk carries clean structure regardless of which model wrote
        # it.
        words_before = len(note_text.split())
        norm = normalise_markdown(note_text)
        note_text = norm.text
        await ctx.emit(
            MarkdownNormalised,
            stage="assembly",
            rules_removed=norm.rules_removed,
            consecutive_rules_collapsed=norm.consecutive_rules_collapsed,
            adjacent_rules_removed=norm.adjacent_rules_removed,
            words_before=words_before,
            words_after=len(note_text.split()),
        )

        # --- place it in the vault, not in _tmp ------------------------------
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


def _weaver_pool_name(provider_name: str) -> str:
    """Which key-pool section funds *provider_name*.

    Gemini's keys live under "google" -- the same section the embedding
    provider draws from, because they are Google AI Studio keys.  Every other
    provider spends from a section of its own name.

    This existed inline as a hardcoded load_pool("google") that ignored the
    configured provider entirely, so a vault naming a different weaver would
    have been handed Google keys.  That is the conflation that once made a
    valid Gemini key look expired: it was being offered to Mistral.
    """
    return "google" if provider_name == "gemini" else provider_name


class TransitionStage(PipelineStage):
    """Generate and splice transition sentences — the note body never
    round-trips through a model.

    Before the 2026-09-09 redesign, the weaver agent received the entire
    assembled note and returned a replacement.  On a live run this destroyed
    72% of the content.  The rule going forward is absolute: the note body
    must never round-trip through a model.  This stage sends only a skeleton
    (topic, headings, first/last sentence per paragraph) and receives back
    one numbered transition per section.

    Every failure mode — no weaver agent, no API key, provider error,
    unparseable response, zero transitions surviving the guard — leaves the
    assembled note unchanged and emits a warning.
    """

    name: Stage = "transitions"
    id = "transitions"

    async def run(self, ctx: RunContext) -> None:
        assert ctx.note_path is not None
        from avicenna.pipeline.transitions import (
            build_transition_prompt,
            extract_skeleton,
            parse_transitions,
            splice_transitions,
            validate_transition,
        )

        # --- degrade: no weaver agent ----------------------------------------
        if "weaver" not in ctx.spec.vault.agents:
            await ctx.emit(
                LogMessage, level="warning",
                text="no weaver agent in this vault; transitions skipped, "
                     "note body unchanged",
            )
            return

        # --- resolve the weaver provider --------------------------------------
        # The user wants Gemini for this.  Do not hardcode a vendor name in
        # stage logic: resolve it through the provider registry from a setting
        # (default "gemini"), with its keys from the pool.  For testing,
        # RunSpec.weaver_provider may be set explicitly (FakeProvider).
        if ctx.spec.weaver_provider is not None:
            weaver_provider = ctx.spec.weaver_provider
        else:
            try:
                from avicenna.keypool import load_pool
                from avicenna.providers.registry import get_provider
                from avicenna.settings import load_vault_config

                # The vendor name is configuration, not stage logic.  The
                # default is gemini because that is what this vault weaves
                # with; a vault that sets weaver_provider gets its own.
                cfg = load_vault_config(Path(ctx.spec.vault.root))
                provider_name = str(cfg.get("weaver_provider", "gemini"))
                # Keys are scoped to the provider that will spend them.
                pool = load_pool(_weaver_pool_name(provider_name))
                # get_provider takes **kwargs, so mypy checks nothing here and
                # a wrong keyword surfaces only at runtime -- where this whole
                # block's `except` would swallow it and silently skip every
                # transition.  The construction below mirrors auth.build_provider
                # exactly: providers still take a single api_key alongside the
                # pool they rotate through.  Timeout and budget are left to the
                # factory, which resolves the Gemini-specific env vars.
                key = pool._keys[0]
                weaver_provider = get_provider(
                    provider_name, api_key=key, pool=pool,
                )
            except Exception as exc:  # noqa: BLE001 - degrade gracefully
                detail = str(exc).strip() or type(exc).__name__
                await ctx.emit(
                    LogMessage, level="warning",
                    text=f"transition provider unavailable ({detail}); "
                         "transitions skipped, note body unchanged",
                )
                return

        # --- build skeleton and call provider ---------------------------------
        note_text = ctx.note_path.read_text(encoding="utf-8", errors="replace")
        skeleton = extract_skeleton(note_text, ctx.spec.topic)
        if not skeleton.sections:
            await ctx.emit(
                LogMessage, level="warning",
                text="no sections found in note; transitions skipped",
            )
            return

        prompt = build_transition_prompt(skeleton)
        weaver_agent = ctx.spec.vault.agents["weaver"]
        try:
            from avicenna.session import one_shot
            raw = await one_shot(
                provider=weaver_provider,
                system=weaver_agent.system_prompt,
                prompt=prompt,
                bus=ctx.spec.bus,
                run_id=ctx.spec.run_id,
            )
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            detail = str(exc).strip() or type(exc).__name__
            await ctx.emit(
                LogMessage, level="warning",
                text=f"weaver provider error ({detail}); "
                     "transitions skipped, note body unchanged",
            )
            return

        if not raw or not raw.strip():
            await ctx.emit(
                LogMessage, level="warning",
                text="weaver returned empty response; transitions skipped",
            )
            await ctx.emit(
                TransitionsApplied,
                requested=len(skeleton.sections), accepted=0, dropped=0,
            )
            return

        # --- parse, validate, splice -----------------------------------------
        parsed = parse_transitions(raw)
        requested = len(skeleton.sections)
        accepted_map: dict[int, str] = {}
        dropped = 0
        for pt in parsed:
            if pt.index < 1 or pt.index > requested:
                dropped += 1
                continue
            sec = skeleton.sections[pt.index - 1]
            preceding = (
                skeleton.sections[pt.index - 2].heading
                if pt.index >= 2 else ctx.spec.topic
            )
            verdict = validate_transition(
                pt.text,
                section_heading=sec.heading,
                preceding_heading=preceding,
                note_topic=ctx.spec.topic,
            )
            if verdict.accepted:
                accepted_map[pt.index] = pt.text
            else:
                dropped += 1
                await ctx.emit(
                    LogMessage, level="warning",
                    text=f"transition {pt.index} dropped: {verdict.reason}",
                )

        # Also count sections that had no parsed transition at all
        for i in range(1, requested + 1):
            if i not in accepted_map and not any(p.index == i for p in parsed):
                dropped += 1

        if not accepted_map:
            await ctx.emit(
                LogMessage, level="warning",
                text="zero transitions survived validation; note body unchanged",
            )
            await ctx.emit(
                TransitionsApplied,
                requested=requested, accepted=0, dropped=dropped,
            )
            return

        # --- splice and write back --------------------------------------------
        new_text = splice_transitions(note_text, accepted_map)
        written = await _write_back(ctx, "transitions", new_text)
        await ctx.emit(
            TransitionsApplied,
            requested=requested,
            accepted=len(accepted_map),
            dropped=dropped,
        )
        if not written:
            await ctx.emit(
                LogMessage, level="warning",
                text="transition splice rejected by truncation guard; "
                     "note body unchanged",
            )


class WordCountStage(PipelineStage):
    name: Stage = "wordcount"
    id = "wordcount"

    async def run(self, ctx: RunContext) -> None:
        assert ctx.note_path is not None
        vault_cfg = load_vault_config(Path(ctx.spec.vault.root))
        target = resolve_words_per_heading(
            template=ctx.template,
            overrides=ctx.spec.overrides,
            vault_config=vault_cfg,
        )
        # The per-heading target is multiplied by the number of prose headings
        # to produce an expected whole-note total.  Formed sections (tables,
        # Mermaid diagrams) do not write to a prose word target and must not
        # count against it — including them produces a permanently misleading
        # "below guidance" warning.
        prose_headings = max(1, len(ctx.headings) - sum(
            1 for f in ctx.section_forms if f is not None
        ))
        expected_total = target * prose_headings

        if ctx.spec.vault.tools.has("validate_wordcount"):
            result = await invoke_tool(ctx, "validate_wordcount",
                FilePath=str(ctx.note_path), MinWords=expected_total,
                Template=ctx.template or "general")
            token = result.parsed.token if result.parsed else ""
            deficit = int(result.parsed.captures.get("short", 0)) if result.parsed else 0
            actual = ctx.total_words if token != "WORDCOUNT_FAIL" else max(expected_total - deficit, 0)
        else:
            await _skip(ctx, "validate_wordcount", "counting words in Python instead")
            body = ctx.note_path.read_text(encoding="utf-8", errors="replace")
            actual = len(body.split())

        ctx.total_words = actual
        # Advisory only: report the count and note the distance from target,
        # but a short note is always kept.  Observed output of 1,180 words
        # where a previous run produced 9,040 is acceptable variance.
        ctx.wordcount_ok = True
        await ctx.emit(WordCountChecked, actual=actual, minimum=expected_total, verdict="pass")
        if actual < expected_total:
            await ctx.emit(LogMessage, level="info",
                           text=f"word count {actual} is below guidance {expected_total} (advisory, not a failure)")


#: The tagger must mark its answer. Scanning for "a line containing a comma"
#: meant any ordinary prose sentence could win and be handed to the validator
#: as though it were the tag line — control flow deduced from the shape of
#: model prose, which is exactly what the contract-token discipline exists to
#: avoid. The sentinel makes extraction deterministic.
_TAGS_SENTINEL = re.compile(r"^\s*TAGS\s*:\s*(?P<tags>.+?)\s*$", re.MULTILINE | re.IGNORECASE)


_CLEAN_TAG = re.compile(r'[\[\]"\x27`#]')
_TAG_STRIP = re.compile(r"[^a-z0-9 -]")


def _to_kebab(raw: str) -> str:
    """Normalise a single tag to lowercase kebab-case.

    Applied to every tag emitted by the tagger so the registry only ever
    sees clean ``^[a-z0-9]+(-[a-z0-9]+)*$`` input.  The vault's validator
    documents that it accepts tags with or without decorations — so the
    tagger emitting them is not a model failure — but downstream code must
    never receive them.
    """
    t = raw.lower().replace("_", "-").replace(" ", "-")
    t = _TAG_STRIP.sub("", t)
    while "--" in t:
        t = t.replace("--", "-")
    return t.strip("-")


def extract_tag_line(output: str) -> str:
    """Pull the declared tag line out of a tagger's response, or '' if absent.

    Normalises the tagger's output before anything downstream consumes it:
    strips surrounding brackets and quotes from the whole line, then per-tag
    removes a leading ``#``, any inner bracket or quote characters, and
    leading/trailing whitespace, and finally converts to lowercase
    kebab-case.  The vault's validator documents that it tolerates these
    decorations, so the tagger emitting them is not a model failure — but
    the registry must never see them.
    """
    match = _TAGS_SENTINEL.search(output)
    if match is None:
        return ""
    raw = match.group("tags").strip()
    # Strip outer brackets on the whole line: [a, b, c] → a, b, c
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1].strip()
    # Strip outer quotes: 'a, b' or "a, b" → a, b
    if len(raw) >= 2 and raw[0] in "'\"" and raw[-1] == raw[0]:
        raw = raw[1:-1].strip()
    tags = []
    for part in raw.split(","):
        t = part.strip()
        t = _CLEAN_TAG.sub("", t)
        t = _to_kebab(t)
        if t:
            tags.append(t)
    return ", ".join(tags)


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
    #    than 2 tags (the note never enters its MOC). Now a minimal valid array
    #    is constructed from the taxonomy and passed through validate_tags like
    #    any other candidate.
    #
    # 3. Even the constructed array can fail if the taxonomy is malformed or
    #    validate_tags has a stricter rule. In that case we fall through to
    #    today's empty-tags behaviour.

    name: Stage = "tagging"
    id = "tagging"

    async def run(self, ctx: RunContext) -> None:
        assert ctx.note_path is not None
        if "tagger" not in ctx.spec.vault.agents:
            await ctx.emit(LogMessage, level="warning", text="no tagger agent registered; skipping")
            return

        # Load the theme/type registry once per run.
        if ctx.theme_registry is None:
            taxonomy_path = ctx.spec.vault.root / ".agents" / "taxonomy.json"
            if taxonomy_path.is_file():
                try:
                    ctx.theme_registry = ThemeRegistry.load(taxonomy_path)
                except (OSError, ValueError) as exc:
                    await ctx.emit(LogMessage, level="warning",
                                   text=f"could not load taxonomy registry: {exc}")

        for attempt in range(1, 4):
            retry_detail = ""
            if attempt > 1 and ctx.handoffs.get("tagger_errors"):
                retry_detail = f"\nPrevious validation errors: {ctx.handoffs['tagger_errors']}"
            # Show the taxonomy hint (including registry state) on every
            # attempt so the tagger sees current themes and types.
            taxonomy_hint = _taxonomy_hint(ctx) if attempt > 1 else ""
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
            await ctx.emit(TagsProposed, tags=tuple(
                t.strip() for t in tag_line.split(",") if t.strip()
            ))

            # --- registry resolution -------------------------------------------
            # Resolve themes and types against the registry BEFORE validation.
            # Newly minted values are persisted to taxonomy.json so the
            # vault's own validate_tags sees them.
            resolved_line = await _resolve_tags_against_registry(tag_line, ctx)

            result = await _invoke_optional(ctx, "validate_tags", TagLine=resolved_line)
            if result is None:
                # No validator in this vault: trust the tagger rather than
                # burning three attempts failing against a tool that is absent.
                ctx.tags = [t.strip() for t in resolved_line.split(",") if t.strip()]
                ctx.handoffs["tagger"] = tagger_output
                await ctx.emit(TagsValidated, verdict="pass",
                               message="accepted unvalidated (validate_tags absent)",
                               accepted=tuple(ctx.tags))
                break
            token = result.parsed.token if result.parsed else ""
            if token == "PASS":
                ctx.tags = [t.strip() for t in resolved_line.split(",") if t.strip()]
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

    Reads categories from the vault's derived folder set (in tag form,
    since the tagger's output will be compared against tags) and
    themes/types from the registry so the tagger sees the vault's current
    vocabulary and prefers existing entries over coining new ones.
    """
    vault = ctx.spec.vault
    taxonomy = getattr(vault, "taxonomy", None)
    if taxonomy is None or not ctx.domain:
        return ""
    # categories_for_domain now returns tag form (lowercase kebab-case).
    categories = vault.categories_for_domain(ctx.domain)
    # Include universal categories for completeness in the hint.
    universal = list(getattr(taxonomy, "universal_categories", []))
    all_cats = [*categories, *universal] if universal else categories
    # Use registry when available; fall back to taxonomy for init vaults.
    registry = ctx.theme_registry
    if registry is not None:
        types = registry.types_for_hint()
        themes = registry.themes_for_hint()
    else:
        types = list(taxonomy.types) if hasattr(taxonomy, "types") else []
        themes = list(taxonomy.themes) if hasattr(taxonomy, "themes") else []
    lines = [
        f"\nValid tags for the routed domain ({ctx.domain}):",
        f"  Domain (exactly 1): {ctx.domain}",
        f"  Category (exactly 1): {', '.join(all_cats)}" if all_cats else "  Category: (none available)",
        f"  Type (exactly 1): {', '.join(types)}" if types else "  Type: (none available)",
        f"  Themes (1-3): {', '.join(themes)}" if themes else "  Themes: (none available)",
        "  Entities (0-6): open vocabulary",
        "  cli must be the last tag.",
        "The positional order is: domain, category, type, themes..., entities..., cli\n",
    ]
    return "\n".join(lines)


async def _resolve_tags_against_registry(
    tag_line: str,
    ctx: RunContext,
) -> str:
    """Resolve themes and types in *tag_line* against the registry.

    Returns a new tag line with near-duplicate themes/types folded onto
    existing registry entries and genuinely new ones minted and persisted.
    Emits ``ThemeMinted`` for each category of new keys and persists the
    taxonomy before returning so ``validate_tags`` sees the updated file.

    Tags that are not themes or types (domain, category, entities, markers)
    pass through unchanged.

    Decides BEFORE mutating: looks up the tag in themes, then types, then
    mints only if it is in neither.  Never uses the mint-then-undo pattern,
    which left residue when anything between the two steps went wrong.
    """
    registry = ctx.theme_registry
    if registry is None:
        return tag_line

    taxonomy = getattr(ctx.spec.vault, "taxonomy", None)
    if taxonomy is None or not ctx.domain:
        return tag_line

    # Categories and domains are compared in tag form (lowercase kebab-case).
    known_categories = set(ctx.spec.vault.categories_for_domain(ctx.domain))
    universal = set(getattr(taxonomy, "universal_categories", []))
    all_categories = known_categories | universal
    known_domains = set(ctx.spec.vault.domain_names)
    markers = set(taxonomy.markers) if hasattr(taxonomy, "markers") else set()
    all_entities = known_domains | all_categories | markers

    raw_tags = [t.strip() for t in tag_line.split(",") if t.strip()]
    resolved: list[str] = []
    new_themes: list[str] = []
    new_types: list[str] = []
    rejected: list[str] = []

    for tag in raw_tags:
        if tag in all_entities:
            resolved.append(tag)
            continue
        # Decide BEFORE mutating: look the tag up in themes, then types,
        # then mint only if it is in neither.  No mint-then-undo.
        canon, reason = registry.lookup_theme(tag)
        if reason is not None:
            rejected.append(f"{tag}: {reason}")
            continue
        if canon is not None:
            # Already in the theme registry — reuse.
            resolved.append(canon)
            continue
        canon, reason = registry.lookup_type(tag)
        if reason is not None:
            rejected.append(f"{tag}: {reason}")
            continue
        if canon is not None:
            # Already a known type — use it.
            resolved.append(canon)
            continue
        # Neither an existing theme nor an existing type.  Mint as a theme
        # (themes are the growing category).  Use the normalized kebab-case
        # key for the mint so the registry stores a consistent form.
        nk = _normalize_tag(tag)
        tag_key = nk.replace(" ", "-")
        registry.mint_theme(tag_key)
        new_themes.append(tag_key)
        resolved.append(tag_key)

    if rejected:
        await ctx.emit(
            LogMessage, level="warning",
            text=f"registry rejected malformed tags: {'; '.join(rejected)}",
        )

    # Persist newly minted values BEFORE validate_tags reads the file.
    if new_themes or new_types:
        ok = registry.persist()
        if not ok:
            await ctx.emit(
                LogMessage, level="warning",
                text="taxonomy.json is unwritable; new themes/types not persisted "
                     "but run continues with validated tags",
            )
        if new_themes:
            await ctx.emit(ThemeMinted, kind="theme",
                           minted=tuple(new_themes),
                           registry_size=registry.theme_count)
        if new_types:
            await ctx.emit(ThemeMinted, kind="type",
                           minted=tuple(new_types),
                           registry_size=registry.type_count)

    return ", ".join(resolved)


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
    # Categories for the floor come from taxonomy.json (not the folder tree),
    # because the floor is validated against taxonomy.json by validate_tags.ps1.
    tax_domains = getattr(taxonomy, "domains", {})
    categories = list(tax_domains.get(ctx.domain, []))
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
    # Previously delegated the entire note to a "formatter" agent.  Replaced
    # with deterministic Python (structure.apply_structure) which numbers
    # headings, strips repeated headings, demotes stray top-level headings,
    # and generates the TOC.  No model round-trip.  _write_back still runs
    # for frontmatter reconciliation, normalisation and the truncation guard.
    name: Stage = "tagging"  # grouped with tagging in the user-facing label
    id = "formatting"

    async def should_run(self, ctx: RunContext) -> bool:
        return ctx.note_path is not None

    async def run(self, ctx: RunContext) -> None:
        assert ctx.note_path is not None
        note = ctx.note_path.read_text(encoding="utf-8", errors="replace")
        result = apply_structure(note)
        if result.text == note:
            return
        await ctx.emit(
            LogMessage, level="info",
            text=(
                f"structure: {result.headings_numbered} headings numbered, "
                f"{result.headings_stripped} repeated headings stripped, "
                f"{result.stray_demoted} stray headings demoted"
            ),
        )
        await _write_back(ctx, "formatting", result.text)


# --- wikilink validation ----------------------------------------------------
# A model writing transition prose can spontaneously produce [[wikilinks]] —
# trained on Obsidian content, it reaches for the syntax even when the prompt
# does not ask for it.  Every [[target]] in the weaver's output is resolved
# against the vault's note index: a link whose target is not an existing note
# is unwrapped to its plain text.  The words stay; only the spurious brackets
# are removed.

_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


def _build_vault_notes_index(vault: Vault, exclude: Path | None = None) -> dict[str, str]:
    """Build a case-insensitive index of note stems from the vault.

    Returns ``{lowercase_stem: display_name}`` for every ``.md`` file in the
    vault (excluding ``.agents/`` and the file at *exclude*).
    """
    index: dict[str, str] = {}
    for p in vault.root.rglob("*.md"):
        if ".agents" in p.parts:
            continue
        if exclude is not None and p.resolve() == exclude.resolve():
            continue
        if p.parent == vault.root and p.name == "AGENTS.md":
            continue
        index[p.stem.lower()] = p.stem
    return index


async def _resolve_wikilinks(text: str, vault: Vault, note_path: Path, ctx: RunContext) -> str:
    """Validate every ``[[target]]`` in *text* against the vault's note index.

    A link to an existing note survives untouched.  A ``[[#heading]]`` internal
    link is left alone (it is not a note link).  ``[[target|alias]]`` is
    resolved by *target*.  An unresolvable link is unwrapped to its plain text
    — the words stay, only the brackets are removed.

    Emits one warning naming how many links were dropped (with examples) and
    one info message with the count that resolved.
    """
    index = _build_vault_notes_index(vault, exclude=note_path)
    dropped: list[str] = []
    resolved_count = 0

    def _replace(m: re.Match[str]) -> str:
        nonlocal resolved_count
        inner = m.group(1)
        # [[#heading]] — internal link, not a note reference.
        if inner.startswith("#"):
            return m.group(0)
        # [[target|alias]] — resolve target, keep alias.
        if "|" in inner:
            target, alias = inner.split("|", 1)
            target = target.strip()
            if target and target.lower() in index:
                resolved_count += 1
                return m.group(0)
            dropped.append(target or inner)
            return alias
        # Plain [[target]].
        target = inner.strip()
        if target and target.lower() in index:
            resolved_count += 1
            return m.group(0)
        dropped.append(target or inner)
        return target

    result = _WIKILINK.sub(_replace, text)
    if dropped:
        sample = ", ".join(f"[[{d}]]" for d in dropped[:5])
        await ctx.emit(
            LogMessage, level="warning",
            text=f"model produced {len(dropped)} wikilink(s) to non-existent notes "
                 f"(dropped {sample})",
        )
    await ctx.emit(LogMessage, level="info",
                   text=f"wikilink resolution: {resolved_count} resolved, {len(dropped)} dropped")
    return result


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
        if domain_dir is None:
            await _skip(ctx, "update_moc",
                        f"domain {ctx.domain!r} has no folder; MOC skipped")
            await ctx.emit(MocUpdated, result="SKIPPED", path=str(ctx.note_path or ""))
            return
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
    tagging, formatting or MOC left an untagged note in the vault with every
    chunk already deleted — unrecoverable, and `--resume` could not help
    because its inputs were gone.
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
        TransitionStage(),
        WordCountStage(),
        # TocStage removed: FormatterStage.apply_structure generates the TOC
        # after numbering, so every anchor resolves.  A TOC generated before
        # numbering (the old TocStage position) produced invented suffixes for
        # duplicate headings — anchors that existed nowhere in the document.
        # The "toc" Stage literal went with it.  Nothing emitted it once the
        # stage was gone, and it was safe to drop because a stage's persisted
        # identity is its `id` (a plain str), not the `name` literal — resume
        # records no stage names at all, so no old run could depend on it.
        TaggingStage(),
        TagsWrittenStage(),
        FormatterStage(),
        MocStage(),
        CleanupStage(),
    ]
