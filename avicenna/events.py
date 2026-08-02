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
    "preflight", "manifest", "sections", "assembly",
    "wordcount", "toc", "tagging", "linking", "moc", "write",
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
    verdict: Literal["pass", "fail"] = "pass"


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
class LinkCandidatesFound(Event):
    count: int = 0
    sample: tuple[str, ...] = ()


@dataclass(frozen=True)
class MocUpdated(Event):
    result: str = ""
    path: str = ""


@dataclass(frozen=True)
class NoteWritten(Event):
    path: str = ""
    words: int = 0


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


__all__ = [
    "Stage", "Event", "RunStarted", "PreflightDeclared", "ManifestWritten",
    "SectionStarted", "SectionCompleted", "SectionFailed", "StageEntered",
    "StageCompleted", "ToolInvoked", "ToolReturned", "WordCountChecked",
    "TagsProposed", "TagsValidated", "LinkCandidatesFound", "MocUpdated",
    "NoteWritten", "RunFailed", "RunComplete", "LogMessage",
]
