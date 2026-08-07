"""StatsBar: compact single-line running statistics."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class StatsBar(Static):
    """Running stats: words, sections, tool calls."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._total_words = 0
        self._done = 0
        self._total_sections = 0
        self._tool_calls = 0
        self._tags: list[str] = []

    def on_mount(self) -> None:
        self.border_title = "Stats"

    def render(self) -> Text:
        text = Text()
        text.append("  Words: ", style="dim")
        text.append(str(self._total_words), style="bold")
        text.append("  |  Sections: ", style="dim")
        text.append(f"{self._done}/{self._total_sections}", style="bold")
        text.append("  |  Tools: ", style="dim")
        text.append(str(self._tool_calls), style="bold")
        if self._tags:
            text.append("  |  Tags: ", style="dim")
            text.append(", ".join(self._tags), style="cyan")
        return text

    def set_total_sections(self, n: int) -> None:
        self._total_sections = n
        self.refresh()

    def add_words(self, n: int) -> None:
        self._total_words += n
        self.refresh()

    def mark_section_done(self) -> None:
        self._done += 1
        self.refresh()

    def inc_tool(self) -> None:
        self._tool_calls += 1
        self.refresh()

    def set_tags(self, tags: list[str]) -> None:
        self._tags = tags
        self.refresh()
