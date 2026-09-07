"""Vault module — binding, discovery, models, routing, and init scaffold."""

from __future__ import annotations

from avicenna.vault.discovery import VaultNotFound, discover_vault
from avicenna.vault.models import AgentDef, Taxonomy, VaultConfigError
from avicenna.vault.vault import Vault, tag_form

__all__ = [
    "Vault", "AgentDef", "Taxonomy", "VaultConfigError",
    "discover_vault", "VaultNotFound", "tag_form",
]
