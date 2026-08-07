"""RunSpec (immutable) and RunContext (mutable) for generation runs.

Keeping them separate means a stage can only corrupt the mutable half,
and resume has an obvious place to rehydrate state from disk.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from avicenna.bus import EventBus
from avicenna.events import Event
from avicenna.providers.base import LLMProvider
from avicenna.vault.vault import Vault  # noqa: F401
from avicenna.vault.models import AgentDef  # noqa: F401

E = TypeVar("E", bound=Event)


@dataclass(frozen=True)
class RunSpec:
    """Immutable inputs to one generation run."""

    topic: str
    vault: Any  # Vault
    provider: LLMProvider
    bus: EventBus
    run_id: str
    concurrency: int = 3
    dry_run: bool = False
    resume: bool = False
    fresh: bool = True
    domain_override: str | None = None
    template_override: str | None = None


@dataclass
class RunContext:
    """Mutable state accumulated as stages execute."""

    spec: RunSpec
    agent: Any | None = None  # AgentDef
    domain: str | None = None
    template: str | None = None
    slug: str | None = None
    headings: list[str] = field(default_factory=list)
    target_words: int = 0
    chunk_paths: dict[int, Path] = field(default_factory=dict)
    failed_sections: list[int] = field(default_factory=list)
    note_path: Path | None = None
    tags: list[str] = field(default_factory=list)
    handoffs: dict[str, str] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    stages_completed: list[str] = field(default_factory=list)
    total_words: int = 0
    started_at: float = field(default_factory=time.time)

    @property
    def tmp_dir(self) -> Path:
        return Path(self.spec.vault.tmp_dir)

    def chunk_path(self, index: int) -> Path:
        assert self.slug is not None, "slug not set"
        return self.tmp_dir / f"{self.slug}_chunk_{index:02d}.md"

    async def emit(self, event_cls: type[E], **fields: Any) -> E:
        event = event_cls(run_id=self.spec.run_id, **fields)
        await self.spec.bus.emit(event)
        return event
