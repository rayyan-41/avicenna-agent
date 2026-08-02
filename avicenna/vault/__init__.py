"""Vault module — binding, discovery, models, routing, and init scaffold."""

from avicenna.vault.discovery import VaultNotFound, discover_vault
from avicenna.vault.models import AgentDef, Taxonomy, VaultConfigError
from avicenna.vault.vault import Vault

__all__ = [
    "Vault", "AgentDef", "Taxonomy", "VaultConfigError",
    "discover_vault", "VaultNotFound",
]
