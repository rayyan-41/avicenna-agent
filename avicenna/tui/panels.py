"""Left panel composition for the Avicenna cockpit."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll

from avicenna.tui.widgets import (
    HeadingGrid,
    PipelineTracker,
    StatsBar,
    VaultCard,
)


class MetadataPanel(VerticalScroll):
    """Left panel: vault card, pipeline tracker, heading grid, stats bar."""

    def compose(self) -> ComposeResult:
        yield VaultCard(id="vault-card")
        yield PipelineTracker(id="pipeline-tracker")
        yield HeadingGrid(id="heading-grid")
        yield StatsBar(id="stats-bar")

    def on_mount(self) -> None:
        self.border_title = "Metadata"

    @property
    def vault_card(self) -> VaultCard:
        return self.query_one(VaultCard)

    @property
    def tracker(self) -> PipelineTracker:
        return self.query_one(PipelineTracker)

    @property
    def grid(self) -> HeadingGrid:
        return self.query_one(HeadingGrid)

    @property
    def stats(self) -> StatsBar:
        return self.query_one(StatsBar)
