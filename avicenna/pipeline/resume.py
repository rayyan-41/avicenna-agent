"""Resume support: read manifest sidecars and plan remaining sections."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Manifest:
    """Snapshot of a manifest sidecar for resume."""

    def __init__(self, slug: str, headings: list[str], expected_count: int) -> None:
        self.slug = slug
        self.headings = headings
        self.expected_count = expected_count


def load_manifest(tmp_dir: Path, slug: str) -> Manifest | None:
    """Try to load a saved manifest sidecar. Returns None if absent."""
    path = tmp_dir / f"{slug}_manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return Manifest(
        slug=data.get("slug", slug),
        headings=data.get("headings", []),
        expected_count=data.get("expected_count", len(data.get("headings", []))),
    )


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
        if not chunk.exists() or chunk.stat().st_size == 0:
            missing.append(i)
        else:
            ctx2.chunk_paths[i] = chunk
    return missing
