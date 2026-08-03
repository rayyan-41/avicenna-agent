"""Where am I, and what does that imply?

Avicenna is runnable from anywhere. Whether the current directory is inside a
vault changes what the harness can do and where notes land, so that fact is
resolved once, explicitly, and surfaced to the user rather than inferred
silently at each call site.

Running inside `E:\\De Anima\\History\\Biographies` should not just find the
vault; it should understand that the caller is standing in the `biography`
category of the `history` domain, and use that as a placement hint.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

Source = Literal["explicit", "env", "cwd", "default", "none"]


def _looks_like_vault(path: Path) -> bool:
    return (path / "AGENTS.md").is_file() and (path / ".agents").is_dir()


def _remembered_default() -> Optional[Path]:
    cfg = Path.home() / ".avicenna" / "user_config.json"
    if not cfg.is_file():
        return None
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = data.get("default_vault")
    return Path(raw) if raw else None


@dataclass(frozen=True)
class VaultContext:
    """The resolved answer to 'which vault, and am I standing in it?'"""

    cwd: Path
    root: Optional[Path]
    source: Source
    inside: bool
    relative: Optional[Path]      # cwd relative to root, when inside

    # ---- presentation -----------------------------------------------------

    @property
    def found(self) -> bool:
        return self.root is not None

    @property
    def badge(self) -> str:
        """One-glance location indicator."""
        if not self.found:
            return "NO VAULT"
        return "IN VAULT" if self.inside else "EXTERNAL"

    @property
    def summary(self) -> str:
        if not self.found:
            return "no vault found - run `avicenna init` or pass --vault"
        # Callers prefix this with `badge`, so do not repeat it here.
        where = str(self.relative) if (self.inside and self.relative and str(self.relative) != ".") else ""
        if self.inside:
            loc = f" / {where}" if where else " (vault root)"
            return f"{self.root.name}{loc}"
        return f"bound to {self.root} via {self.source}; cwd is outside the vault"

    # ---- detection --------------------------------------------------------

    @classmethod
    def detect(
        cls,
        explicit: str | Path | None = None,
        cwd: Path | None = None,
    ) -> "VaultContext":
        here = (cwd or Path.cwd()).resolve()

        candidates: list[tuple[Source, Path]] = []
        if explicit:
            candidates.append(("explicit", Path(explicit)))
        env = os.environ.get("AVICENNA_VAULT")
        if env:
            candidates.append(("env", Path(env)))

        # Walk up from cwd. This is what makes "runnable from anywhere" behave
        # the way a user expects when they are standing inside a vault.
        for parent in [here, *here.parents]:
            if _looks_like_vault(parent):
                candidates.append(("cwd", parent))
                break

        remembered = _remembered_default()
        if remembered:
            candidates.append(("default", remembered))

        for source, path in candidates:
            resolved = path.expanduser().resolve()
            if _looks_like_vault(resolved):
                inside = resolved == here or resolved in here.parents
                rel = here.relative_to(resolved) if inside else None
                return cls(here, resolved, source, inside, rel)
            if source in ("explicit", "env"):
                # An explicit pointer that is not a vault is an error, not a
                # reason to silently fall through to something else.
                return cls(here, None, "none", False, None)

        return cls(here, None, "none", False, None)

    # ---- placement hints --------------------------------------------------

    def location_hint(self, vault: object) -> tuple[Optional[str], Optional[str]]:
        """(domain, category) implied by where the user is standing.

        Only meaningful when inside the vault. Lets `avicenna note` default to
        the folder the user is actually in, and gives the MOC update the right
        domain without guessing.
        """
        if not (self.inside and self.relative and self.root):
            return (None, None)

        parts = [p for p in self.relative.parts if p not in (".", "")]
        if not parts:
            return (None, None)

        taxonomy = getattr(vault, "taxonomy", None)
        if taxonomy is None:
            return (None, None)

        domain = parts[0].lower()
        if domain not in getattr(taxonomy, "domains", {}):
            return (None, None)

        category = None
        try:
            category = taxonomy.category_for_path("/".join(parts))
        except Exception:  # noqa: BLE001 - a hint must never break a run
            category = None
        return (domain, category)
