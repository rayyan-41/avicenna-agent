"""Vault configuration models: AgentDef, Taxonomy, and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Literal

import yaml

AgentType = Literal["content", "pipeline", "audit"]


class VaultConfigError(RuntimeError):
    pass


@dataclass(slots=True)
class AgentDef:
    name: str
    description: str
    type: AgentType
    system_prompt: str                 # the markdown body
    path: Path
    domain: str | None = None          # content agents
    stage: int | None = None           # pipeline agents
    invocation: str | None = None
    mcp: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> AgentDef:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---"):
            raise VaultConfigError(f"{path}: missing YAML frontmatter (file must start with ---)")
        try:
            _, front, body = raw.split("---", 2)
            meta: Any = yaml.safe_load(front) or {}
        except ValueError as exc:
            raise VaultConfigError(f"{path}: frontmatter is not closed by a second ---") from exc
        except yaml.YAMLError as exc:
            raise VaultConfigError(f"{path}: invalid YAML frontmatter: {exc}") from exc
        if not isinstance(meta, dict):
            raise VaultConfigError(f"{path}: frontmatter must be a mapping")
        for required in ("name", "description", "type"):
            if required not in meta:
                raise VaultConfigError(f"{path}: frontmatter missing required key {required!r}")
        if meta["name"] != path.stem:
            raise VaultConfigError(
                f"{path}: frontmatter name {meta['name']!r} does not match filename {path.stem!r}"
            )
        if meta["type"] == "content" and not meta.get("domain"):
            raise VaultConfigError(f"{path}: content agents must declare a domain")
        if meta["type"] == "pipeline" and meta.get("stage") is None:
            raise VaultConfigError(f"{path}: pipeline agents must declare a stage")
        return cls(
            name=meta["name"], description=meta["description"], type=meta["type"],
            system_prompt=body.strip(), path=path, domain=meta.get("domain"),
            stage=meta.get("stage"), invocation=meta.get("invocation"),
            mcp=list(meta.get("mcp") or []),
        )


@dataclass(slots=True)
class Taxonomy:
    version: int
    schema: Mapping[str, Any]
    domains: Mapping[str, list[str]]
    universal_categories: list[str]
    folder_map: Mapping[str, str]
    types: list[str]
    themes: list[str]
    reserved_modifiers: list[str]

    @classmethod
    def load(cls, path: Path) -> Taxonomy:
        import json
        data = json.loads(path.read_text("utf-8"))
        try:
            return cls(
                version=data["version"], schema=data["schema"], domains=data["domains"],
                universal_categories=data.get("universalCategories", []),
                folder_map=data.get("folderMap", {}), types=data["types"],
                themes=data["themes"], reserved_modifiers=data.get("reservedModifiers", []),
            )
        except KeyError as exc:
            raise VaultConfigError(f"{path}: taxonomy missing required key {exc}") from exc

    @property
    def markers(self) -> list[str]:
        return list(self.schema.get("markers", ["cli"]))

    def categories_for(self, domain: str) -> list[str]:
        if domain not in self.domains:
            raise VaultConfigError(f"unknown domain {domain!r}; known: {sorted(self.domains)}")
        return [*self.domains[domain], *self.universal_categories]

    def category_for_path(self, relative_folder: str) -> str | None:
        """Longest-prefix match of a vault-relative folder against folderMap."""
        needle = relative_folder.replace("\\", "/").strip("/")
        best: tuple[int, str] | None = None
        for prefix, category in self.folder_map.items():
            p = prefix.replace("\\", "/").strip("/")
            if needle == p or needle.startswith(p + "/"):
                if best is None or len(p) > best[0]:
                    best = (len(p), category)
        return best[1] if best else None
