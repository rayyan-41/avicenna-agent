"""HeadingGrid: section progress DataTable with status glyphs."""
from __future__ import annotations

from textual.widgets import DataTable

from avicenna import events as ev

GLYPH: dict[str, str] = {"pending": "○", "running": "◐", "done": "●", "failed": "✕"}


class HeadingGrid(DataTable):
    """Stable, index-sorted status grid. Rows never reorder."""

    def on_mount(self) -> None:
        self.border_title = "Sections"
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.add_columns("#", "Heading", "St", "Words", "Time")
        self._statuses: dict[int, str] = {}

    def seed(self, headings: tuple[str, ...]) -> None:
        self.clear()
        self._statuses.clear()
        for i, heading in enumerate(headings, start=1):
            self.add_row(str(i), heading[:38], GLYPH["pending"], "-", "-", key=str(i))
            self._statuses[i] = "pending"

    def _set(self, index: int, status: str, words: str, elapsed: str) -> None:
        key = str(index)
        self._statuses[index] = status
        try:
            self.update_cell(key, "St", GLYPH[status])
            self.update_cell(key, "Words", words)
            self.update_cell(key, "Time", elapsed)
        except Exception:
            pass

    def started(self, e: ev.SectionStarted) -> None:
        self._set(e.index, "running", "-", "...")

    def completed(self, e: ev.SectionCompleted) -> None:
        self._set(e.index, "done", str(e.words), f"{e.elapsed:.1f}s")

    def failed(self, e: ev.SectionFailed) -> None:
        status = "running" if e.will_retry else "failed"
        self._set(e.index, status, "-", f"try {e.attempt}")
