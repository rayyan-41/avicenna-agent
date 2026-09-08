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

_JSON_FENCE = re.compile(r"```json\s*(?P<body>\{.*?\})\s*```", re.DOTALL)
_HEADING_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(?P<h>[^\n]+?)\s*$", re.MULTILINE)
_FIELD = r"^\s*(?:[-*]\s*)?(?:\*\*)?{key}(?:\*\*)?\s*[:=]\s*(?P<v>[^\n]+)$"
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_RESERVED = {"CON", "PRN", "AUX", "NUL"}

# --- section forms -----------------------------------------------------------
# A closed vocabulary of bracketed form markers that a heading may carry.
# Case-insensitive lookup; values are the canonical form identifiers consumed
# by sections.py.  An unrecognised bracketed prefix is left in the title — a
# model inventing [Chart] must not produce a heading with a missing word.
_FORM_MARKER = re.compile(r"^\[([^\]]+)\]\s+")

_SECTION_FORMS: dict[str, str] = {
    "table": "table",
    "mermaid": "mermaid",
    "mermaid diagram": "mermaid",
}


class PreflightError(ValueError):
    pass


def parse_form(heading: str) -> tuple[str, str | None]:
    """Extract a recognised form marker from *heading*, if present.

    Returns ``(clean_title, form_or_none)``.  An unrecognised bracketed
    prefix is left as part of the title — a model inventing ``[Chart]``
    must not produce a heading with a missing word.
    """
    m = _FORM_MARKER.match(heading)
    if not m:
        return heading, None
    candidate = m.group(1).strip().lower()
    form = _SECTION_FORMS.get(candidate)
    if form is None:
        return heading, None
    return heading[m.end():].strip(), form


@dataclass(frozen=True)
class PreflightDeclaration:
    topic: str
    domain: str
    template: str
    headings: tuple[str, ...]
    forms: tuple[str | None, ...]
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
    # Strip and reject empties, then extract form markers.  The marker is
    # metadata that travels alongside the heading; the title reaching the
    # note must be clean (no leaked `[Table]` prefix in a TOC).
    cleaned: list[str] = []
    forms: list[str | None] = []
    for raw in headings_raw:
        h = str(raw).strip()
        if not h:
            continue
        title, form = parse_form(h)
        cleaned.append(title)
        forms.append(form)
    if not cleaned:
        raise PreflightError("pre-flight declared zero headings")
    if len(cleaned) > 40:
        raise PreflightError(f"pre-flight declared {len(cleaned)} headings, refusing")
    template = str(data.get("template") or "general").strip().lower()
    try:
        target = int(str(data.get("target_words") or 0).replace(",", "").split()[0])
    except (ValueError, IndexError):
        target = 0

    topic = str(data.get("topic") or default_topic).strip()
    domain = str(data.get("domain") or default_domain).strip().lower()
    base = slugify(str(data.get("slug") or topic))
    return (
        PreflightDeclaration(
            topic=topic, domain=domain, template=template,
            headings=tuple(cleaned), forms=tuple(forms), target_words=target,
            slug=unique_slug(base, tmp_dir),
        ),
        used_json,
    )
