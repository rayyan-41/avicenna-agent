"""PipelineTracker: horizontal stage stepper with progress indicators."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

STAGES = [
    "route", "preflight", "manifest", "sections", "assembly",
    "wordcount", "toc", "tagging", "linking", "moc",
]


class PipelineTracker(Static):
    """Compact pipeline stage progress display."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._done: set[str] = set()
        self._current: str = ""

    def on_mount(self) -> None:
        self.border_title = "Pipeline"

    def render(self) -> Text:
        text = Text()
        for i, stage in enumerate(STAGES):
            if i > 0:
                text.append("  ")
            if stage in self._done:
                text.append("●", style="green")
                text.append(f" {stage}", style="dim")
            elif stage == self._current:
                text.append("◉", style="bold yellow")
                text.append(f" {stage}", style="bold yellow")
            else:
                text.append("○", style="dim")
                text.append(f" {stage}", style="dim")
        return text

    def set_stage(self, stage: str) -> None:
        self._current = stage
        self.refresh()

    def mark_done(self, stage: str) -> None:
        self._done.add(stage)
        self._current = ""
        self.refresh()
