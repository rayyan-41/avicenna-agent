"""RunSpec (immutable) and RunContext (mutable) for generation runs.

Keeping them separate means a stage can only corrupt the mutable half,
and resume has an obvious place to rehydrate state from disk.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from avicenna.bus import EventBus
from avicenna.events import Event
from avicenna.pipeline.schema import FrontmatterSchema
from avicenna.providers.base import LLMProvider
from avicenna.settings import MAX_CONCURRENCY_DEFAULT
from avicenna.vault.registry import ThemeRegistry
from avicenna.vault.vault import Vault
from avicenna.vault.models import AgentDef

if TYPE_CHECKING:
    from avicenna.pipeline.preflight import PreflightDeclaration

E = TypeVar("E", bound=Event)


@dataclass(frozen=True)
class RunSpec:
    """Immutable inputs to one generation run."""

    topic: str
    # Concretely typed. These were `Any`, which silently switched off checking
    # for every `spec.vault.…` and `ctx.agent.…` access in the pipeline — the
    # bulk of the code that touches the vault.
    vault: Vault
    provider: LLMProvider
    bus: EventBus
    run_id: str
    concurrency: int = MAX_CONCURRENCY_DEFAULT
    dry_run: bool = False
    resume: bool = False
    fresh: bool = True
    domain_override: str | None = None
    template_override: str | None = None
    #: Per-run settings overrides (from CLI flags).  Passed to the settings
    #: resolver so flag > env > vault config > default holds uniformly.
    overrides: dict[str, Any] = field(default_factory=dict)
    #: Optional dedicated provider for the transition weaver stage.
    # When None, TransitionStage constructs one from settings (default: gemini).
    # Tests inject FakeProvider here so the stage exercises the pipeline
    # without requiring real API keys.
    weaver_provider: LLMProvider | None = None


@dataclass
class RunContext:
    """Mutable state accumulated as stages execute."""

    spec: RunSpec
    agent: AgentDef | None = None
    domain: str | None = None
    template: str | None = None
    slug: str | None = None
    headings: list[str] = field(default_factory=list)
    #: Per-heading form overrides (parallel to headings).  ``None`` means
    #: prose; recognised values are ``"table"`` and ``"mermaid"``.
    section_forms: list[str | None] = field(default_factory=list)
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
    #: False when the finished note came in under its template's word floor.
    #: The run still completes — a short note is worth keeping — but the
    #: summary says so rather than reporting an unqualified success.
    wordcount_ok: bool = True
    #: True once ResumeStage has rehydrated slug/headings from a manifest.
    #: Pre-flight keys off this to avoid re-declaring a structure that already
    #: has chunks on disk under a slug it would not mint again.
    resumed_from_manifest: bool = False
    #: Detected frontmatter schema for this run, cached so every stage writes
    #: the same convention.  Set once by AssemblyStage before the first write.
    frontmatter_schema: FrontmatterSchema | None = None
    #: Theme/type registry for this run.  Loaded once during tagging so
    #: themes and types can be resolved against the vault's accumulated
    #: vocabulary before validation.
    theme_registry: ThemeRegistry | None = None
    #: Injectable approval gate.  Called after preflight with the declared
    #: plan.  Returns True to proceed (setting concurrency to the heading
    #: count) or False to abort cleanly.  When None, no gate runs and
    #: concurrency follows the configured precedence chain — this is the
    #: default that keeps tests, gen_matrix and the bridge unchanged.
    on_plan: Callable[[PreflightDeclaration], Awaitable[bool]] | None = None
    #: Set by the approval gate when it approves.  SectionsStage prefers
    #: this over spec.concurrency, which remains the configured-path value
    #: (clamped).  The approved path is bounded only by parse_preflight's
    #: 40-heading refusal — the human gate replaces the clamp.
    approved_concurrency: int | None = None

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
