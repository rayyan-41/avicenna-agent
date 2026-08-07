"""TUI widgets for the Avicenna cockpit."""
from __future__ import annotations

from avicenna.tui.widgets.chat_view import ChatView
from avicenna.tui.widgets.heading_grid import HeadingGrid
from avicenna.tui.widgets.pipeline_tracker import PipelineTracker
from avicenna.tui.widgets.stats_bar import StatsBar
from avicenna.tui.widgets.vault_card import VaultCard

__all__ = ["ChatView", "HeadingGrid", "PipelineTracker", "StatsBar", "VaultCard"]
