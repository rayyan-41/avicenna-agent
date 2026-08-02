"""JSON-first pre-flight parsing.

Instructs the content agent to append a fenced json block. Falls back
to regex over prose with a warning.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

TEMPLATE_MINIMUMS: dict[str, int] = {
    "fiqh": 8000, "aqeedah": 3000, "geopolitical": 5000, "empire": 1500,
    "biography": 1500, "cs": 4000, "notebooklm": 4000, "general": 1000,
}

_JSON_FENCE = re.compile(r"```json\s*(?P<body>\{.*?\})\s*```", re.DOTALL)
_HEADING_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(?P<h>[^\n]+?)\s*$", re.MULTILINE)
_FIELD = r"^\s*(?:[-*]\s*)?(?:\*\*)?{key}(?:\*\*)?\s*[:=]\s*(?P<v>[^\n]+)$"
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_RESERVED = {"CON", "PRN", "AUX", "NUL"}


class PreflightError(ValueError):
    pass


@dataclass(frozen=True)
class PreflightDeclaration:
    topic: str
    domain: str
    template: str
    headings: tuple[str, ...]
    target_words: int
    slug: str


def slugify(value: str, *, max_length: int = 60) -> str:
    ascii_form = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    slug = _SLUG_STRIP.sub("-", ascii_form.lower()).strip("-")
    slug = slug[:max_length].strip("-")
    if not slug or slug.upper() in _RESERVED:
        raise PreflightError(f"cannot derive a filesystem safe slug from {value!r}")
    return slug


def unique_slug(base: str, tmp_dir: Path) -> str:
    candidate, counter = base, 2
    while (tmp_dir / f"{candidate}_manifest.json").exists() or list(
        tmp_dir.glob(f"{candidate}_chunk_*.md")
    ):
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def _field_value(text: str, key: str) -> str | None:
    match = re.search(_FIELD.format(key=key), text, re.IGNORECASE | re.MULTILINE)
    return match.group("v").strip().strip("`*") if match else None


def _from_json(text: str) -> dict[str, object] | None:
    matches = _JSON_FENCE.findall(text)
    if not matches:
        return None
    try:
        parsed = json.loads(matches[-1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _from_prose(text: str) -> dict[str, object]:
    headings_block = text
    anchor = re.search(r"headings?\s*[:=]", text, re.IGNORECASE)
    if anchor:
        headings_block = text[anchor.end():]
    headings = [h.strip().lstrip("#").strip() for h in _HEADING_ITEM.findall(headings_block)]
    return {
        "topic": _field_value(text, "topic"),
        "domain": _field_value(text, "domain"),
        "template": _field_value(text, "template"),
        "target_words": _field_value(text, r"(?:target[ _]words|word target)"),
        "slug": _field_value(text, "slug"),
        "headings": headings,
    }


def parse_preflight(
    text: str, *, default_domain: str, default_topic: str, tmp_dir: Path
) -> tuple[PreflightDeclaration, bool]:
    """Returns the declaration and whether the JSON path was used."""
    data = _from_json(text)
    used_json = data is not None
    if data is None:
        data = _from_prose(text)

    headings_raw = data.get("headings") or []
    if not isinstance(headings_raw, list):
        raise PreflightError("headings must be a list")
    headings = [str(h).strip() for h in headings_raw if str(h).strip()]
    if not headings:
        raise PreflightError("pre-flight declared zero headings")
    if len(headings) > 40:
        raise PreflightError(f"pre-flight declared {len(headings)} headings, refusing")
    if any("," in h for h in headings):
        raise PreflightError("headings must not contain commas (write_manifest delimiter)")

    template = str(data.get("template") or "general").strip().lower()
    if template not in TEMPLATE_MINIMUMS:
        template = "general"
    try:
        target = int(str(data.get("target_words") or 0).replace(",", "").split()[0])
    except (ValueError, IndexError):
        target = 0
    target = max(target, TEMPLATE_MINIMUMS[template])

    topic = str(data.get("topic") or default_topic).strip()
    domain = str(data.get("domain") or default_domain).strip().lower()
    base = slugify(str(data.get("slug") or topic))
    return (
        PreflightDeclaration(
            topic=topic, domain=domain, template=template,
            headings=tuple(headings), target_words=target,
            slug=unique_slug(base, tmp_dir),
        ),
        used_json,
    )
