"""Parallel section generation.

One closure per heading through gather_sections. Each task uses one_shot
for fresh context, retries once on exception or empty output, and Python
(not the model) writes _tmp/[slug]_chunk_NN.md.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from avicenna.concurrency import gather_sections
from avicenna.events import SectionCompleted, SectionFailed, SectionStarted
from avicenna.pipeline.context import RunContext
from avicenna.session import one_shot

SECTION_PROMPT = """You are writing ONE section of a longer note titled "{topic}".

Write the section under this heading, and only this heading:
    {heading}

This is section {index} of {total}. The full outline, for orientation only, is:
{outline}

Rules:
- Write approximately {words} words of finished prose for this heading alone.
- Do NOT restate the heading; the assembler adds it.
- Do NOT write a preamble, a table of contents, a summary of the whole note,
  or any transition into the next section.
- Do NOT write frontmatter, tags, or wikilinks.
- Sub-headings below this heading are allowed at level 3 (###) or deeper.
- Maintain the voice and analytical standards of your agent definition,
  appropriate to the {domain} domain.
Output the section body as Markdown, nothing else."""


def _count_words(text: str) -> int:
    return len(text.split())


def _build_task(ctx: RunContext, index: int, heading: str) -> Callable[[], Awaitable[int]]:
    spec = ctx.spec
    assert ctx.agent is not None and ctx.domain is not None
    outline = "\n".join(f"{i}. {h}" for i, h in enumerate(ctx.headings, start=1))
    prompt = SECTION_PROMPT.format(
        topic=spec.topic, heading=heading, index=index, total=len(ctx.headings),
        outline=outline,
        words=max(600, ctx.target_words // max(1, len(ctx.headings))),
        domain=ctx.domain,
    )

    async def task() -> int:
        for attempt in (1, 2):
            await ctx.emit(SectionStarted, index=index, heading=heading)
            start = time.perf_counter()
            try:
                text = await one_shot(
                    provider=spec.provider,
                    system=ctx.agent.system_prompt,
                    prompt=prompt,
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
            path.write_text(text.strip() + "\n", encoding="utf-8", newline="\n")
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
    tasks = [_build_task(ctx, i, ctx.headings[i - 1]) for i in indices]
    results = await gather_sections(tasks, concurrency=ctx.spec.concurrency)
    ctx.total_words += sum(r for r in results if isinstance(r, int))
