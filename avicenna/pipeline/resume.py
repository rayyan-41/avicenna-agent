"""Resume support: manifest sidecars, the last-run pointer, section planning.

Resume used to be unreachable. `--resume` re-ran pre-flight, and pre-flight
routes its slug through `unique_slug`, whose entire job is to bump the slug
when `{slug}_manifest.json` or `{slug}_chunk_*.md` already exist — which is
exactly the state an interrupted run leaves behind. So a resume computed
`topic-2`, looked for `topic-2_chunk_01.md`, found nothing, and regenerated
every section it was supposed to preserve. Worse, the second pre-flight could
return a different heading list, making the retained chunks unusable anyway.
`load_manifest`, the function that would have prevented all of it, had no
callers.

The fix has two halves, both here:

* the manifest is written by Python rather than only by an optional PowerShell
  tool, so resume works in a vault with no `.ps1` tools at all;
* a `last_run.json` pointer records which slug the most recent run of a given
  topic used, because the caller supplies a topic and the sidecars are keyed
  by slug.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LAST_RUN = "last_run.json"


class Manifest:
    """Snapshot of a manifest sidecar for resume."""

    def __init__(
        self,
        slug: str,
        headings: list[str],
        expected_count: int,
        *,
        topic: str = "",
        domain: str = "",
        template: str = "",
        target_words: int = 0,
    ) -> None:
        self.slug = slug
        self.headings = headings
        self.expected_count = expected_count
        self.topic = topic
        self.domain = domain
        self.template = template
        self.target_words = target_words


def manifest_path(tmp_dir: Path, slug: str) -> Path:
    return tmp_dir / f"{slug}_manifest.json"


def write_manifest(tmp_dir: Path, manifest: Manifest) -> Path:
    """Persist a manifest sidecar plus the last-run pointer.

    Written unconditionally, even when the vault ships a `write_manifest.ps1`,
    so that resume does not depend on a tool a vault may not have.
    """
    tmp_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "slug": manifest.slug,
        "topic": manifest.topic,
        "domain": manifest.domain,
        "template": manifest.template,
        "headings": manifest.headings,
        "expected_count": manifest.expected_count,
        "target_words": manifest.target_words,
    }
    path = manifest_path(tmp_dir, manifest.slug)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8", newline="\n")
    tmp.replace(path)

    pointer = tmp_dir / LAST_RUN
    try:
        index: dict[str, str] = json.loads(pointer.read_text("utf-8"))
        if not isinstance(index, dict):
            index = {}
    except (json.JSONDecodeError, OSError):
        index = {}
    index[manifest.topic] = manifest.slug
    index["__last__"] = manifest.slug
    tmp2 = pointer.with_suffix(".json.part")
    tmp2.write_text(json.dumps(index, indent=2), encoding="utf-8", newline="\n")
    tmp2.replace(pointer)
    return path


def load_manifest(tmp_dir: Path, slug: str) -> Manifest | None:
    """Try to load a saved manifest sidecar. Returns None if absent."""
    path = manifest_path(tmp_dir, slug)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    headings = [str(h) for h in data.get("headings", [])]
    return Manifest(
        slug=str(data.get("slug", slug)),
        headings=headings,
        expected_count=int(data.get("expected_count", len(headings))),
        topic=str(data.get("topic", "")),
        domain=str(data.get("domain", "")),
        template=str(data.get("template", "")),
        target_words=int(data.get("target_words", 0)),
    )


def find_resumable(tmp_dir: Path, topic: str) -> Manifest | None:
    """The manifest to resume for `topic`, or the most recent run if unknown.

    The caller has a topic; the sidecars are keyed by slug. The pointer written
    by `write_manifest` bridges the two. An empty topic (the frontend's bare
    `/resume`) falls back to whichever run was last started.
    """
    pointer = tmp_dir / LAST_RUN
    try:
        index = json.loads(pointer.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(index, dict):
        return None
    slug = index.get(topic) or (index.get("__last__") if not topic else None)
    if not slug:
        return None
    return load_manifest(tmp_dir, str(slug))


def plan_sections(ctx: Any, slug: str, headings: list[str]) -> list[int]:
    """Return indices of sections that need to be (re)generated."""
    from avicenna.pipeline.context import RunContext

    ctx2: RunContext = ctx
    if ctx2.spec.fresh:
        # Delete stale _tmp artifacts
        tmp = ctx2.spec.vault.tmp_dir
        for pattern in [f"{slug}_*"]:
            for f in tmp.glob(pattern):
                f.unlink(missing_ok=True)
        return list(range(1, len(headings) + 1))

    missing: list[int] = []
    for i, _ in enumerate(headings, start=1):
        chunk = ctx2.chunk_path(i)
        # A chunk is only complete if it is non-empty AND was not left mid-write:
        # section writes go through a .part sibling, so a surviving .part means
        # the process died during the write and the chunk cannot be trusted.
        part = chunk.with_suffix(chunk.suffix + ".part")
        if not chunk.exists() or chunk.stat().st_size == 0 or part.exists():
            part.unlink(missing_ok=True)
            missing.append(i)
        else:
            ctx2.chunk_paths[i] = chunk
    return missing
