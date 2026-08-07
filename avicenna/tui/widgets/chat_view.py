"""ChatView: scrollable RichLog-based chat panel.

Cline-style chat with neon green accents for user input,
muted text for pipeline output, and clean message separation.
"""
from __future__ import annotations

from rich.text import Text
from textual.widgets import RichLog

NEON_GREEN = "#00FF41"
DIM_GREEN = "#00AA2A"


class ChatView(RichLog):
    """Scrollable chat log with styled message methods."""

    def on_mount(self) -> None:
        self.border_title = " Avicenna "
        self.markup = True
        self.wrap = True
        self.highlight = True

    def write_user(self, text: str) -> None:
        styled = Text()
        styled.append("> ", style=f"bold {NEON_GREEN}")
        styled.append(text, style=f"bold {NEON_GREEN}")
        self.write(styled, shrink=False)
        self.write(Text(""), shrink=False)

    def write_assistant(self, text: str) -> None:
        self.write(text, shrink=False)
        self.write(Text(""), shrink=False)

    def write_pipeline(self, text: str) -> None:
        styled = Text(f"  {text}", style=f"dim {DIM_GREEN}")
        self.write(styled, shrink=False)

    def write_error(self, text: str) -> None:
        styled = Text()
        styled.append("  ! ", style="bold red")
        styled.append(text, style="red")
        self.write(styled, shrink=False)
