"""VaultCard: compact vault identity with neon green accents."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

NEON_GREEN = "#00FF41"
DIM_GREEN = "#00AA2A"


class VaultCard(Static):
    """Vault name, path, provider/model, and location badge."""

    _BADGE_COLORS = {
        "IN VAULT": ("black", NEON_GREEN),
        "EXTERNAL": ("black", "#FFD700"),
        "NO VAULT": ("white", "#FF0000"),
    }

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._info = Text("No vault configured", style="dim")

    def on_mount(self) -> None:
        self.border_title = " Vault "

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
            lines.append(" ")
        lines.append(vault_name, style=f"bold {NEON_GREEN}")
        lines.append("\n")
        lines.append(f"  {provider} / {model}", style="dim")
        self._info = lines
        self.refresh()
