"""Parallel section generation.

One closure per heading through gather_sections. Each task uses one_shot
for fresh context, retries once on exception or empty output, and Python
(not the model) writes _tmp/[slug]_chunk_NN.md.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from avicenna.concurrency import gather_sections
from avicenna.events import SectionCompleted, SectionFailed, SectionStarted
from avicenna.pipeline.context import RunContext
from avicenna.pipeline.delegate import tools_for_agent
from avicenna.session import one_shot
from avicenna.settings import (
    heading_word_band,
    load_vault_config,
    resolve_words_per_heading,
)

SECTION_PROMPT = """You are writing ONE section of a longer note titled "{topic}".

Write the section under this heading, and only this heading:
    {heading}

This is section {index} of {total}. The full outline, for orientation only, is:
{outline}

Length is a hard requirement, not a target to approach:
- Write between {min_words} and {max_words} words of finished prose for this
  heading alone. Aim for {words}.
- A section under {min_words} words is incomplete and will be rejected. If you
  find yourself running short, you have treated the heading too narrowly: go
  further into the argument, the objections to it, the primary sources, the
  historical circumstances and the positions it is answering.
- Do not pad to reach the count. Reach it by saying more of substance.

Rules:
- Do NOT restate the heading; the assembler adds it.
- Do NOT write a preamble, a table of contents, a summary of the whole note,
  or any transition into the next section.
- Do NOT write frontmatter, tags, or wikilinks.
- Sub-headings below this heading are allowed at level 3 (###) or deeper.
- Maintain the voice and analytical standards of your agent definition,
  appropriate to the {domain} domain.
Output the section body as Markdown, nothing else."""

# --- form-specific prompt suffixes -------------------------------------------
# A form overrides the prose default for exactly one section.  The suffix is
# appended to the standard prompt so the section agent sees the heading, the
# outline, and the form constraint in one message.  The form does NOT let the
# model choose its own control flow — it selects a fragment from this closed
# mapping.

_TABLE_SUFFIX = """
This section MUST be written as a Markdown comparative table.
Use pipe-delimited columns with a separator row.  The table must be complete,
renderable, and cover the heading's topic.  Do not add prose before or after
the table — the output IS the table.
"""

_MERMAID_SUFFIX = """
This section MUST be a single Mermaid diagram and nothing else.
Acceptable diagram types: flowchart TD, flowchart LR, graph TD, graph LR,
sequenceDiagram, classDiagram, stateDiagram-v2, erDiagram, gantt, pie,
mindmap.
The output must be exactly one fenced block:

```mermaid
...diagram here...
```

Nothing may appear outside the fence.  The diagram must parse as valid
Mermaid syntax — every node, edge and label must be well-formed.  A diagram
that fails to render is a visible defect in the user's vault.
"""

_FORM_SUFFIXES: dict[str, str] = {
    "table": _TABLE_SUFFIX,
    "mermaid": _MERMAID_SUFFIX,
}


def _count_words(text: str) -> int:
    return len(text.split())


def _write_chunk(path: Path, text: str) -> None:
    """Write one chunk atomically, off the event loop.

    Atomically because resume decides a chunk is complete by looking at it: a
    chunk truncated by a kill mid-write would be woven into the note as though
    it were finished. Off the loop because sections run concurrently and a
    synchronous write blocks every other section's progress for its duration.
    """
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _build_task(
    ctx: RunContext, index: int, heading: str, form: str | None,
) -> Callable[[], Awaitable[int]]:
    spec = ctx.spec
    assert ctx.agent is not None and ctx.domain is not None
    # Bound outside the closure so the narrowing survives into `task()`; the
    # closure reading ctx.agent directly widened it back to AgentDef | None.
    agent = ctx.agent
    # A section is where MCP earns its place: writing on the necessity of
    # revelation, this is the call that can pull the actual passage out of a
    # reference server instead of reconstructing it from memory. Sections used
    # to be the one delegation given no tools at all.
    section_tools = tools_for_agent(spec.vault, agent)
    outline = "\n".join(f"{i}. {h}" for i, h in enumerate(ctx.headings, start=1))
    vault_cfg = load_vault_config(Path(spec.vault.root) if spec.vault else None)
    wph = resolve_words_per_heading(
        template=ctx.template,
        overrides=spec.overrides,
        vault_config=vault_cfg,
    )
    low, high = heading_word_band(wph)
    prompt = SECTION_PROMPT.format(
        topic=spec.topic, heading=heading, index=index, total=len(ctx.headings),
        outline=outline,
        words=wph, min_words=low, max_words=high,
        domain=ctx.domain,
    )
    if form is not None:
        suffix = _FORM_SUFFIXES.get(form)
        if suffix is not None:
            prompt = prompt.rstrip() + "\n" + suffix

    async def task() -> int:
        for attempt in (1, 2):
            await ctx.emit(SectionStarted, index=index, heading=heading)
            start = time.perf_counter()
            try:
                text = await one_shot(
                    provider=spec.provider,
                    system=agent.system_prompt,
                    prompt=prompt,
                    tools=section_tools or None,
                    tool_runner=spec.vault.tools.runner if section_tools else None,
                    bus=spec.bus,
                    run_id=spec.run_id,
                    section_index=index,
                )
                if not text or not text.strip():
                    raise ValueError("empty section output")
            except Exception as exc:  # noqa: BLE001 - retried once
                will_retry = attempt == 1
                await ctx.emit(
                    SectionFailed, index=index, heading=heading,
                    error=f"{type(exc).__name__}: {exc}",
                    will_retry=will_retry, attempt=attempt,
                )
                if will_retry:
                    continue
                ctx.failed_sections.append(index)
                return 0
            path = ctx.chunk_path(index)
            await asyncio.to_thread(_write_chunk, path, text.strip() + "\n")
            ctx.chunk_paths[index] = path
            words = _count_words(text)
            await ctx.emit(
                SectionCompleted, index=index, heading=heading, words=words,
                elapsed=time.perf_counter() - start, path=str(path),
            )
            return words
        return 0

    return task


async def generate_sections(ctx: RunContext, indices: list[int]) -> None:
    tasks = [
        _build_task(ctx, i, ctx.headings[i - 1],
                     ctx.section_forms[i - 1] if i - 1 < len(ctx.section_forms) else None)
        for i in indices
    ]
    # The approved path (human gate) sets concurrency to the heading count,
    # bypassing the configured ceiling.  The configured path (no gate) uses
    # spec.concurrency, which is clamped by resolve_concurrency.
    effective = ctx.approved_concurrency if ctx.approved_concurrency is not None else ctx.spec.concurrency
    results = await gather_sections(tasks, concurrency=effective)
    ctx.total_words += sum(r for r in results if isinstance(r, int))
