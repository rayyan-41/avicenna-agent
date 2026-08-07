"""ChatView: scrollable RichLog-based chat panel.

Replaces the old Label-based ChatPanel that rebuilt the entire string
on every append. RichLog writes each message independently and scrolls
automatically.
"""
from __future__ import annotations

from rich.text import Text
from textual.widgets import RichLog


class ChatView(RichLog):
    """Scrollable chat log with styled message methods."""

    def on_mount(self) -> None:
        self.border_title = "Chat"
        self.markup = True
        self.wrap = True
        self.highlight = True

    def write_user(self, text: str) -> None:
        styled = Text(f"> {text}", style="bold bright_cyan")
        self.write(styled, shrink=False)

    def write_assistant(self, text: str) -> None:
        self.write(text, shrink=False)

    def write_pipeline(self, text: str) -> None:
        styled = Text(f"  {text}", style="dim")
        self.write(styled, shrink=False)

    def write_error(self, text: str) -> None:
        styled = Text(f"! {text}", style="bold red")
        self.write(styled, shrink=False)
