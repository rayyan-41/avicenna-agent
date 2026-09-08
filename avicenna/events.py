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


__all__ = [
    "Stage", "Event", "RunStarted", "PreflightDeclared", "ManifestWritten",
    "SectionStarted", "SectionCompleted", "SectionFailed", "StageEntered",
    "StageCompleted", "ToolInvoked", "ToolReturned", "WordCountChecked",
    "MarkdownNormalised",
    "TagsProposed", "TagsValidated", "SchemaDetected", "ThemeMinted",
    "TransitionsApplied",
    "MocUpdated", "NoteWritten", "PlanApprovalRequested", "RunFailed",
    "RunComplete", "LogMessage",
]
