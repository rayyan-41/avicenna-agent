"""Left and right panel compositions."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Input, Label, Static

from avicenna import events as ev
from avicenna.tui.widgets import (
    HeadingGrid, PreflightCard, StageTracker, StatsCard, VaultCard,
)


class MetadataPanel(VerticalScroll):
    """Left panel: vault card, pre-flight, heading grid, stage tracker, stats."""

    def compose(self) -> ComposeResult:
        yield VaultCard(id="vault-card", classes="vault-card")
        yield PreflightCard(id="preflight-card")
        yield HeadingGrid(id="heading-grid")
        yield StageTracker(id="stage-tracker")
        yield StatsCard(id="stats-card")

    def on_mount(self) -> None:
        self.border_title = "Metadata"

    @property
    def grid(self) -> HeadingGrid:
        return self.query_one(HeadingGrid)

    @property
    def preflight(self) -> PreflightCard:
        return self.query_one(PreflightCard)

    @property
    def tracker(self) -> StageTracker:
        return self.query_one(StageTracker)

    @property
    def stats(self) -> StatsCard:
        return self.query_one(StatsCard)

    @property
    def vault_card(self) -> VaultCard:
        return self.query_one(VaultCard)


class ChatPanel(VerticalScroll):
    """Right panel: scrollable chat log plus an Input docked at bottom."""

    def compose(self) -> ComposeResult:
        self._log = Label(id="chat-log", markup=True)
        yield self._log

    def on_mount(self) -> None:
        self.border_title = "Chat"

    def log_event(self, event: ev.Event) -> None:
        """Append pipeline events as directed by the app."""
        pass  # app handles this in on_event_message

    def append(self, text: str, *, style: str = "") -> None:
        current = self._log.renderable if self._log.renderable else ""
        markup = f"[{style}]{text}[/{style}]" if style else text
        if current:
            new = str(current) + "\n" + markup
        else:
            new = markup
        self._log.update(new)
        self.scroll_end(animate=False)

    def append_user(self, text: str) -> None:
        self.append(f"> {text}", style="chat-user")

    def append_assistant(self, text: str) -> None:
        self.append(text, style="chat-assistant")

    def append_pipeline(self, text: str) -> None:
        self.append(f"  {text}", style="pipeline-line")

    def append_error(self, text: str) -> None:
        self.append(f"! {text}", style="chat-error")
