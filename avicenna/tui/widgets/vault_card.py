"""VaultCard: compact vault identity with location badge."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class VaultCard(Static):
    """Vault name, path, provider/model, and location badge."""

    _BADGE_COLORS = {
        "IN VAULT": ("black", "green"),
        "EXTERNAL": ("black", "yellow"),
        "NO VAULT": ("white", "red"),
    }

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._info = Text("[dim]No vault configured[/dim]")

    def on_mount(self) -> None:
        self.border_title = "Vault"

    def render(self) -> Text:
        return self._info

    def set_info(
        self,
        vault_name: str,
        vault_path: str,
        provider: str,
        model: str,
        badge: str = "",
        where: str = "",
    ) -> None:
        lines = Text()
        if badge:
            fg, bg = self._BADGE_COLORS.get(badge, ("white", "dim"))
            lines.append(f" {badge} ", style=f"{fg} on {bg}")
            lines.append(f"  {vault_name}", style="bold")
        else:
            lines.append(f"  {vault_name}", style="bold")
        lines.append("\n")
        lines.append(f"  {vault_path}", style="dim")
        if where and where != ".":
            lines.append("\n")
            lines.append(f"  cwd: {where}", style="dim")
        lines.append("\n")
        lines.append(f"  {provider} / {model}", style="dim cyan")
        self._info = lines
        self.refresh()
