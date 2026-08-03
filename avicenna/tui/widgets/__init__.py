"""Left-panel metadata widgets."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Static, DataTable, Label

from avicenna import events as ev

GLYPH: dict[str, str] = {"pending": "○", "running": "◐", "done": "●", "failed": "✕"}


class VaultCard(Static):
    """Vault name, path, provider/model, and where the user is standing."""

    _BADGE_STYLE = {
        "IN VAULT": "black on green",
        "EXTERNAL": "black on yellow",
        "NO VAULT": "white on red",
    }

    def set_info(
        self,
        vault_name: str,
        vault_path: str,
        provider: str,
        model: str,
        badge: str = "",
        where: str = "",
    ) -> None:
        lines = []
        if badge:
            style = self._BADGE_STYLE.get(badge, "dim")
            lines.append(f"[{style}] {badge} [/] [bold]{vault_name}[/bold]")
        else:
            lines.append(f"[bold]Vault:[/bold] {vault_name}")
        lines.append(f"[dim]{vault_path}[/dim]")
        if where and where != ".":
            lines.append(f"[dim]cwd: {where}[/dim]")
        lines.append(f"[dim]{provider} / {model}[/dim]")
        self.update("\n".join(lines))


class PreflightCard(Static):
    """Filled by PreflightDeclared."""

    def on_mount(self) -> None:
        self.update("[dim]Pre-flight: waiting...[/dim]")

    def update_from(self, e: ev.PreflightDeclared) -> None:
        self.update(
            f"[bold]Topic:[/bold] {e.topic}\n"
            f"Domain: {e.domain} | Template: {e.template}\n"
            f"Target: {e.target_words} words | Slug: {e.slug}"
        )


class HeadingGrid(DataTable):
    """Stable, index-sorted status grid. Rows never reorder."""

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.add_columns("#", "Heading", "St", "Words", "Time")
        self._statuses: dict[int, str] = {}

    def seed(self, headings: tuple[str, ...]) -> None:
        self.clear()
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


class StageTracker(Static):
    """Stepper showing current pipeline stage."""

    STAGES = [
        "preflight", "manifest", "sections", "assembly",
        "wordcount", "toc", "tagging", "linking", "moc",
    ]

    def on_mount(self) -> None:
        self._done: set[str] = set()
        self._current: str = ""
        self.render_stages()

    def render_stages(self) -> None:
        lines = []
        for s in self.STAGES:
            if s in self._done:
                prefix = "[green]✔[/green]"
            elif s == self._current:
                prefix = "[bold yellow]▶[/bold yellow]"
            else:
                prefix = "[dim]·[/dim]"
            lines.append(f"{prefix} {s}")
        self.update("\n".join(lines))

    def set_stage(self, stage: str) -> None:
        self._current = stage
        self.render_stages()

    def mark_done(self, stage: str) -> None:
        self._done.add(stage)
        self._current = ""
        self.render_stages()


class StatsCard(Static):
    """Running stats: total words, progress, elapsed, tool calls."""

    def on_mount(self) -> None:
        self._total = 0
        self._done = 0
        self._total_sections = 0
        self._tool_calls = 0
        self.render_stats()

    def set_total_sections(self, n: int) -> None:
        self._total_sections = n
        self.render_stats()

    def add_words(self, n: int) -> None:
        self._total += n
        self.render_stats()

    def mark_section_done(self) -> None:
        self._done += 1
        self.render_stats()

    def inc_tool(self) -> None:
        self._tool_calls += 1
        self.render_stats()

    def set_tags(self, tags: list[str]) -> None:
        self._tags = tags
        self.render_stats()

    def render_stats(self) -> None:
        lines = [
            f"Words: {self._total}",
            f"Sections: {self._done}/{self._total_sections}",
            f"Tool calls: {self._tool_calls}",
        ]
        self.update("\n".join(lines))
