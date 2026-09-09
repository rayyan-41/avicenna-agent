"""Typed event taxonomy for the generation pipeline.

Every event is a frozen dataclass with always-defaulted fields
(dataclass-inheritance constraint). All events carry run_id, ts, and a
bus-assigned seq.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

Stage = Literal[
    "preflight", "manifest", "sections", "assembly", "transitions",
    "wordcount", "tagging", "moc", "write",
]


@dataclass(frozen=True)
class Event:
    run_id: str = ""
    ts: float = field(default_factory=time.time)
    seq: int = 0


@dataclass(frozen=True)
class RunStarted(Event):
    topic: str = ""
    provider: str = ""
    model: str = ""


@dataclass(frozen=True)
class PreflightDeclared(Event):
    topic: str = ""
    domain: str = ""
    template: str = ""
    headings: tuple[str, ...] = ()
    target_words: int = 0
    slug: str = ""


@dataclass(frozen=True)
class ManifestWritten(Event):
    slug: str = ""
    expected_count: int = 0


@dataclass(frozen=True)
class SectionStarted(Event):
    index: int = -1
    heading: str = ""


@dataclass(frozen=True)
class SectionCompleted(Event):
    index: int = -1
    heading: str = ""
    words: int = 0
    elapsed: float = 0.0
    path: str = ""


@dataclass(frozen=True)
class SectionFailed(Event):
    index: int = -1
    heading: str = ""
    error: str = ""
    will_retry: bool = False
    attempt: int = 1


@dataclass(frozen=True)
class StageEntered(Event):
    stage: Stage = "preflight"


@dataclass(frozen=True)
class StageCompleted(Event):
    stage: Stage = "preflight"
    elapsed: float = 0.0


@dataclass(frozen=True)
class ToolInvoked(Event):
    name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    section_index: int | None = None


@dataclass(frozen=True)
class ToolReturned(Event):
    name: str = ""
    contract: str = ""
    ok: bool = True
    elapsed: float = 0.0
    section_index: int | None = None


@dataclass(frozen=True)
class WordCountChecked(Event):
    actual: int = 0
    minimum: int = 0
    #: "short" exists because the two-value vocabulary forced a lie.  A short
    #: note is deliberately never a failure (WordCountStage is advisory), but
    #: with only "pass" and "fail" available the stage emitted "pass" for a
    #: note it had just logged as below guidance — a live run reported
    #: verdict=pass at 3,401 words against a 9,000 minimum.  "short" reports
    #: the measurement truthfully while leaving "fail" to mean the run failed.
    verdict: Literal["pass", "short", "fail"] = "pass"


@dataclass(frozen=True)
class MarkdownNormalised(Event):
    stage: str = ""
    rules_removed: int = 0
    consecutive_rules_collapsed: int = 0
    adjacent_rules_removed: int = 0
    words_before: int = 0
    words_after: int = 0


@dataclass(frozen=True)
class TagsProposed(Event):
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class TagsValidated(Event):
    verdict: Literal["pass", "fail"] = "pass"
    message: str = ""
    accepted: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()


@dataclass(frozen=True)
class SchemaDetected(Event):
    keys: tuple[str, ...] = ()
    source: str = ""


@dataclass(frozen=True)
class MocUpdated(Event):
    result: str = ""
    path: str = ""


@dataclass(frozen=True)
class NoteWritten(Event):
    path: str = ""
    words: int = 0


@dataclass(frozen=True)
class PlanApprovalRequested(Event):
    topic: str = ""
    domain: str = ""
    template: str = ""
    headings: tuple[str, ...] = ()
    target_words: int = 0
    concurrency: int = 0


@dataclass(frozen=True)
class RunFailed(Event):
    error: str = ""
    stage: Stage | None = None


@dataclass(frozen=True)
class RunComplete(Event):
    summary: str = ""
    elapsed: float = 0.0
    total_words: int = 0


@dataclass(frozen=True)
class LogMessage(Event):
    level: Literal["debug", "info", "warning", "error"] = "info"
    text: str = ""


@dataclass(frozen=True)
class ThemeMinted(Event):
    kind: Literal["theme", "type"] = "theme"
    minted: tuple[str, ...] = ()
    registry_size: int = 0


@dataclass(frozen=True)
class TransitionsApplied(Event):
    requested: int = 0
    accepted: int = 0
    dropped: int = 0


@dataclass(frozen=True)
class SemanticGuardDecision(Event):
    """One verdict from the drift guard, whichever way it went.

    Reuse and mint are the same decision seen from two sides, so they share an
    event: what matters to a reader is the *margin*, not the outcome.  The
    design's own worked example is ``minted `nationalism`; closest existing
    `political-philosophy` at 0.61`` — unreadable without ``nearest``, and
    undiagnosable without ``threshold``, since a registry fragmenting into
    synonyms and one collapsing distinct ideas are both threshold faults and
    look identical from the mint count alone.
    """

    kind: Literal["theme", "type"] = "theme"
    proposed: str = ""
    decision: Literal["reuse", "mint"] = "mint"
    nearest: str = ""
    similarity: float = 0.0
    threshold: float = 0.0


@dataclass(frozen=True)
class EntitiesDerived(Event):
    """Where the note's entity tags came from.

    Entities carry connection in this vault, so a note that has none is
    disconnected no matter how well it is written.  When the tagger proposes
    none and the harness derives them from the topic instead, that is a
    decision the reader should see rather than a silence.
    """

    source: Literal["model", "topic", "none"] = "model"
    entities: tuple[str, ...] = ()


@dataclass(frozen=True)
class TagsAssignedMechanically(Event):
    """The deterministic floor fired: no model-proposed array survived.

    This was a ``LogMessage`` warning, which put it in the same channel as
    everything else the run says.  It is a decision — the note is tagged, but
    by the taxonomy rather than by a reading of the note — and it is the
    strongest signal that a note wants correcting by hand.
    """

    tags: tuple[str, ...] = ()
    reason: str = ""


__all__ = [
    "Stage", "Event", "RunStarted", "PreflightDeclared", "ManifestWritten",
    "SectionStarted", "SectionCompleted", "SectionFailed", "StageEntered",
    "StageCompleted", "ToolInvoked", "ToolReturned", "WordCountChecked",
    "MarkdownNormalised",
    "TagsProposed", "TagsValidated", "SchemaDetected", "ThemeMinted",
    "TransitionsApplied", "SemanticGuardDecision", "EntitiesDerived",
    "TagsAssignedMechanically",
    "MocUpdated", "NoteWritten", "PlanApprovalRequested", "RunFailed",
    "RunComplete", "LogMessage",
]
