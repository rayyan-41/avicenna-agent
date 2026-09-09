"""Theme and type registry: the harness maintains a map of the reader's mind.

Themes and types are inferred by the harness, per note, and accumulated in
taxonomy.json so the registry becomes a record of where the reader's
attention has actually gone.  This module owns the resolution, normalization
and persistence logic.  The tagger proposes; a deterministic check disposes.

The semantic guard (embedding-based similarity that folds near-duplicates
like ``national-identity`` into ``nationalism``) is deferred to step 4 of
the sequencing plan.  ``semantic_guard`` is the seam it will attach to —
it currently returns ``None`` for every proposed key and must not be
replaced with a fuzzy string-similarity heuristic, because a wrong merge
silently collapses distinct ideas.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
# Case, separator and plural insensitive: ``Nationalism``, ``nationalism``,
# ``nationalisms`` are one theme.  The canonical form is the first raw value
# encountered for a given normalized key.

_PLURAL_S = re.compile(r"ies$")
_PLURAL_ES = re.compile(r"(?:sh|ch|x|z|s)es$")

#: Valid tag form — lowercase kebab-case, at least one character.
_VALID_TAG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _normalize(key: str) -> str:
    """Fold case, separator and plural variants into a canonical form.

    ``National-Identity`` → ``national identity``
    ``nationalisms`` → ``nationalism``
    """
    k = key.lower().replace("-", " ").replace("_", " ").strip()
    # Naive singularisation — deliberately conservative.  It handles the
    # common cases (nationalisms → nationalism, churches → church) and
    # leaves irregular plurals alone.  The semantic guard is the correct
    # place for deeper merging; this is the fast, deterministic floor.
    k = _PLURAL_S.sub("y", k)
    k = _PLURAL_ES.sub(
        lambda m: m.group(0)[: -2],  # drop 'es'
        k,
    )
    if k.endswith("s") and not k.endswith("ss") and len(k) > 3:
        k = k[:-1]
    return k


def semantic_guard(
    proposed: str,
    existing_keys: list[str],
    context: str = "",
) -> str | None:
    """Return an existing key that is semantically equivalent to *proposed*.

    This is the *default* guard, and it always returns ``None``: every
    proposed key that passes normalization is accepted as genuinely new.
    The embedding-backed guard is not a replacement for this function — it
    is precomputed asynchronously by the pipeline and handed to a specific
    ``ThemeRegistry`` through :meth:`ThemeRegistry.guard_decisions`, because
    embedding is async and the registry's resolve path is not.

    Keeping this a pure function with no state matters for two reasons: it
    stays trivially testable, and ``registry.py`` stays importable without a
    provider.  A vault with no embedding provider is legitimate and must
    behave exactly as it always has.

    Do NOT replace this with a fuzzy string-similarity heuristic; a wrong
    merge silently collapses distinct ideas, which is worse than the drift
    it prevents.  ``nationalism`` and ``national-identity`` are
    string-similar and should merge; ``epistemology`` and ``eschatology``
    are string-similar and must not.  Only meaning separates those.

    Args:
        proposed: The proposed theme or type, after normalization.
        existing_keys: Normalized keys already in the registry.
        context: The sentence-level context that produced the key.
    """
    return None


# ---------------------------------------------------------------------------
# Surgical JSON editing
# ---------------------------------------------------------------------------
# persist() operates on the file's text rather than reserialising a dict,
# because json.dumps destroys the user's formatting: inline arrays get
# expanded, blank lines vanish, key order drifts.  A taxonomy.json that is
# hand-authored by the user must leave the harness byte-identical in every
# position the mutation did not touch.
#
# The two primitives are append_to_array and set_key_in_object.  Each
# returns the edited text, or None when the structure does not match
# expectations — at which point persist() falls back to reserialisation.


def _find_json_colon(text: str, key: str) -> int:
    """Find the colon after the **top-level** *key* in *text*.

    Returns the position of the colon, or -1 when *key* is not a key of the
    root object.  Depth matters, and getting it wrong corrupts the file: this
    used to take the first textual occurrence of the key at any nesting level,
    so on a real taxonomy.json "themes" resolved to ``schema.arity.themes`` --
    the arity pair ``[1, 3]`` -- which sits above the real themes array.
    Minting a tag appended its name into the schema's arity declaration, and
    the file still parsed, so nothing downstream noticed until the validator
    read an arity of ``[1, 3, "some-tag"]``.

    Only the root object's own keys are candidates, and a key inside a string
    value is never one.
    """
    qkey = json.dumps(key, ensure_ascii=False)
    depth = 0
    in_str = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
                i += 1
                continue
            i += 1
            continue
        if c == '"':
            # A key of the root object sits at depth 1 and is followed, after
            # optional whitespace, by a colon.
            if depth == 1 and text.startswith(qkey, i):
                after = i + len(qkey)
                j = after
                while j < n and text[j] in " \t\n\r":
                    j += 1
                if j < n and text[j] == ":":
                    return j
            in_str = True
            i += 1
            continue
        if c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        i += 1
    return -1


def _find_object_end(text: str, start: int) -> int:
    """Find the closing ``}`` of an object whose opening ``{`` is at *start*.

    Returns -1 on malformed input.  Handles nested braces inside strings
    (e.g. ``"a { b } c"``) and nested structures.
    """
    depth = 0
    in_string = False
    i = start
    while i < len(text):
        c = text[i]
        if in_string:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_string = False
        else:
            if c == '"':
                in_string = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _create_array_after(
    text: str,
    key: str,
    anchor_key: str,
    items: list[str],
) -> str | None:
    """Insert a new top-level array *key* just after the *anchor_key* array.

    Used when a vault predates the key entirely.  The alternative -- letting
    the append fail and reserialising -- rewrites every inline array in the
    user's hand-authored file, which is exactly the damage the surgical writer
    was built to stop.

    Indentation and the multiline/inline style are copied from the anchor, so
    the new key looks like it was always there.  Returns ``None`` when the
    anchor cannot be located, which sends the caller to the fallback.
    """
    colon = _find_json_colon(text, anchor_key)
    if colon == -1:
        return None
    bracket = text.find("[", colon + 1)
    if bracket == -1:
        return None

    depth = 0
    in_str = False
    end = -1
    i = bracket
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = i
                break
        i += 1
    if end == -1:
        return None

    # The anchor's own indentation is the indentation of the line it starts on.
    line_start = text.rfind("\n", 0, colon) + 1
    key_indent = ""
    for ch in text[line_start:]:
        if ch in " \t":
            key_indent += ch
        else:
            break

    body = text[bracket:end + 1]
    if "\n" in body:
        item_indent = key_indent + "  "
        rendered = (
            "[\n"
            + ",\n".join(f'{item_indent}"{it}"' for it in items)
            + f"\n{key_indent}]"
        )
    else:
        rendered = "[" + ", ".join(f'"{it}"' for it in items) + "]"

    # Insert after the anchor array and its comma, keeping the file valid.
    insert_at = end + 1
    trailing = text[insert_at:insert_at + 1]
    prefix = "" if trailing == "," else ","
    if trailing == ",":
        insert_at += 1
    return (
        text[:insert_at]
        + prefix
        + f'\n{key_indent}"{key}": {rendered}'
        + ("," if trailing == "," else "")
        + text[insert_at:]
    )


def _append_to_array(
    text: str,
    key: str,
    items: list[str],
) -> str | None:
    """Append *items* to the JSON array at ``"key"`` in *text*.

    Matches the array's existing style: inline arrays stay inline, multiline
    arrays follow the detected indentation.  Returns the edited text, or
    ``None`` if the key or array cannot be located.
    """
    colon = _find_json_colon(text, key)
    if colon == -1:
        return None
    bracket = text.find("[", colon + 1)
    if bracket == -1:
        return None
    # Count brackets to find the matching close, skipping strings.
    depth = 0
    in_str = False
    end = -1
    i = bracket
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        i += 1
    if end == -1:
        return None

    content = text[bracket + 1 : end].strip()

    if not content:
        # Empty array — stay inline:  []
        new_items = ", ".join(f'"{it}"' for it in items)
        return text[: bracket + 1] + new_items + text[end:]

    # Detect whether the array is inline (no newlines between [ and ]).
    between = text[bracket + 1 : end]
    is_inline = "\n" not in between

    if is_inline:
        # Stay inline:  append after the last element.
        new_items = ", ".join(f'"{it}"' for it in items)
        return text[: end] + ", " + new_items + text[end:]

    # Multiline — match the indentation of the existing items, and insert
    # directly after the last one.
    #
    # Two off-by-ones lived here.  The indent scan began AT the newline, so
    # the first character it saw was "\n", which is not a space or tab: it
    # broke immediately and measured an indent of "", putting every appended
    # entry at column 0.  And the insert was made at `end` -- the closing
    # bracket -- which is preceded by the whitespace indenting that bracket,
    # so the comma landed alone on its own line after that whitespace.
    last_item_end = len(text[:end].rstrip())
    last_line_start = text.rfind("\n", 0, last_item_end)
    if last_line_start == -1:
        return None
    item_indent = ""
    for ch in text[last_line_start + 1:]:
        if ch in " \t":
            item_indent += ch
        else:
            break

    new_lines = ",\n".join(f'{item_indent}"{it}"' for it in items)
    return text[:last_item_end] + ",\n" + new_lines + text[last_item_end:]


def _set_key_in_object(
    text: str,
    obj_key: str,
    items: list[str],
) -> str | None:
    """Set a key in the object at ``"obj_key"`` in *text*.

    Creates the object if absent (using the indentation of the file's root
    object).  If the object already has entries, appends after the last one.
    Returns the edited text, or ``None`` if the parent object cannot be
    located.
    """
    colon = _find_json_colon(text, obj_key)
    if colon != -1:
        brace = text.find("{", colon + 1)
        if brace == -1:
            return None
        end = _find_object_end(text, brace)
        if end == -1:
            return None

        content = text[brace + 1 : end].strip()
        entry = ", ".join(f'"{k}": 1' for k in items)

        if not content:
            # Detect indent from the key line.
            line_start = text.rfind("\n", 0, colon)
            if line_start == -1:
                return None
            key_line = text[line_start + 1 : colon]
            key_indent = ""
            for ch in key_line:
                if ch in " \t":
                    key_indent += ch
                else:
                    break
            inner = key_indent + "  "
            return (
                text[: brace + 1]
                + "\n" + inner + entry
                + "\n" + key_indent
                + text[end:]
            )

        # Find the last real content character before `}` to detect
        # indentation and to insert the comma on the correct line.
        # Between the last entry and `}` there is whitespace (the indent
        # of `}`).  We insert right after the entry, so the comma lands
        # on the same line and the new entry goes on the next.
        content_raw = text[brace + 1 : end]
        last_content_stripped = content_raw.rstrip()
        insert_pos = brace + 1 + len(last_content_stripped)
        # The indent scan began at the newline, which is neither a space nor a
        # tab, so it measured "" and put new entries at column 0.  Start after
        # it.
        last_line_start = text.rfind("\n", 0, insert_pos)
        if last_line_start == -1:
            return None
        entry_indent = ""
        for ch in text[last_line_start + 1:]:
            if ch in " \t":
                entry_indent += ch
            else:
                break

        # One entry per line, matching how the object is already written --
        # joining them onto a single line reformats a region the caller did
        # not ask to reformat.
        block = (",\n").join(f'{entry_indent}"{k}": 1' for k in items)
        return text[:insert_pos] + ",\n" + block + text[insert_pos:]

    # Key absent — create the object inside the root.  The root object
    # is the outermost pair of braces; its `}` is the last `}` in the
    # file (assuming well-formed JSON without trailing junk).
    root_end = text.rfind("}")
    if root_end == -1:
        return None

    # Derive indentation from the last content line before the root `}`.
    before_root = text[:root_end].rstrip()
    last_nl = before_root.rfind("\n")
    if last_nl == -1:
        return None
    last_line = before_root[last_nl + 1:]
    key_indent = ""
    for ch in last_line:
        if ch in " \t":
            key_indent += ch
        else:
            break

    inner = key_indent + "  "
    entry = ", ".join(f'"{k}": 1' for k in items)
    insert_pos = len(before_root)

    qkey = json.dumps(obj_key, ensure_ascii=False)
    insertion = (
        ",\n" + key_indent + qkey + ": {"
        + "\n" + inner + entry
        + "\n" + key_indent + "}"
    )
    return text[:insert_pos] + insertion + text[insert_pos:]


# ---------------------------------------------------------------------------
# ThemeRegistry
# ---------------------------------------------------------------------------

@dataclass
class ThemeRegistry:
    """Accumulate themes and types in taxonomy.json.

    The registry loads the file independently of ``Taxonomy`` (which is a
    frozen dataclass) so it can mutate the arrays and persist back.
    """

    taxonomy_path: Path
    raw: dict[str, Any] = field(default_factory=dict)
    _theme_canonical: dict[str, str] = field(default_factory=dict)
    _type_canonical: dict[str, str] = field(default_factory=dict)
    _entity_canonical: dict[str, str] = field(default_factory=dict)
    #: Newly minted keys in this run, not yet persisted.
    _minted_themes: list[str] = field(default_factory=list)
    _minted_types: list[str] = field(default_factory=list)
    _minted_entities: list[str] = field(default_factory=list)
    _dirty: bool = False
    #: Precomputed drift-guard decisions for this registry, keyed by
    #: ``(normalized_key, kind)``.  ``None`` means no oracle ran and the pure
    #: ``semantic_guard`` default applies; an empty dict means the oracle ran
    #: and found nothing to merge.  See :meth:`guard_decisions`.
    _guard_decisions: dict[tuple[str, str], str] | None = None

    @classmethod
    def load(cls, taxonomy_path: Path) -> ThemeRegistry:
        """Load the registry from taxonomy.json."""
        data = json.loads(taxonomy_path.read_text("utf-8"))
        reg = cls(taxonomy_path=taxonomy_path, raw=data)
        reg._rebuild_index()
        return reg

    def _rebuild_index(self) -> None:
        """Rebuild the canonical lookup from the current raw data."""
        self._theme_canonical = {}
        for t in self.raw.get("themes", []):
            nk = _normalize(t)
            if nk not in self._theme_canonical:
                self._theme_canonical[nk] = t
        self._type_canonical = {}
        for t in self.raw.get("types", []):
            nk = _normalize(t)
            if nk not in self._type_canonical:
                self._type_canonical[nk] = t
        # Entities are an open vocabulary, so this is a *record* of the forms
        # this vault already uses -- never a list to validate against.  The
        # vault's own validate_tags.ps1 classifies a tail tag as an entity by
        # exclusion (`$themes -notcontains $_`) and never reads this key, so
        # recording entities here cannot start gatekeeping them.
        self._entity_canonical = {}
        for t in self.raw.get("entities", []):
            nk = _normalize(t)
            if nk not in self._entity_canonical:
                self._entity_canonical[nk] = t

    # --- the drift guard seam ------------------------------------------------
    # Embedding is async; `resolve_theme` and `resolve_type` are not, and they
    # are called from synchronous code throughout.  Making them async would
    # push `await` up through every caller and every test for the sake of one
    # optional check.
    #
    # So the decision is computed *before* the resolve loop runs -- the
    # pipeline embeds every candidate in one batch, works out which should
    # merge, and hands the answers to this registry for the duration of that
    # loop.  The state lives on the instance rather than on the module: two
    # registries (a run and a test, or two runs in one process) must not see
    # each other's decisions, and a module global would also leave
    # `semantic_guard` impure, which is the one thing its docstring asks
    # callers not to do.

    @contextmanager
    def guard_decisions(
        self, decisions: dict[tuple[str, str], str],
    ) -> Iterator[None]:
        """Apply precomputed drift-guard *decisions* for the duration of the block.

        Restores the previous state on exit, including on exception, so a
        failure inside the resolve loop cannot leave stale decisions behind
        for a later call (the floor-tag path resolves a second time).
        """
        previous = self._guard_decisions
        self._guard_decisions = decisions
        try:
            yield
        finally:
            self._guard_decisions = previous

    def _guard(self, nk: str, kind: str, existing_keys: list[str]) -> str | None:
        """The guard for one normalized key: precomputed answer, else default."""
        if self._guard_decisions is not None:
            return self._guard_decisions.get((nk, kind))
        return semantic_guard(nk, existing_keys)

    def theme_keys(self) -> list[str]:
        """Normalized keys currently in the theme registry."""
        return list(self._theme_canonical)

    def type_keys(self) -> list[str]:
        """Normalized keys currently in the type registry."""
        return list(self._type_canonical)

    def guard_candidate(self, proposed: str) -> str | None:
        """The normalized key the guard would be asked about, or ``None``.

        ``None`` means the guard will never see this tag: it is malformed, or
        it already resolves to a known theme or type, so no mint is at stake.
        Callers use this to build the batch to embed -- embedding a tag whose
        answer is already known is a wasted call against a rate-limited API.

        This exists so the pipeline does not have to reach into the
        registry's private validation helpers and canonical maps to work out
        the same thing, which is how it was first written.
        """
        if self._validate_raw(proposed) is not None:
            return None
        nk = _normalize(proposed)
        if self._validate_tag(nk.replace(" ", "-")) is not None:
            return None
        if nk in self._theme_canonical or nk in self._type_canonical:
            return None
        return nk

    # --- resolution ----------------------------------------------------------

    #: Characters that must never appear in a proposed tag, even before
    #: normalisation.  ``_normalize`` would strip some of these silently
    #: (brackets, quotes), but the registry is the last line of defence
    #: and must reject rather than silently clean.
    _FORBIDDEN = re.compile(r"[\[\]\"'`]")

    def _validate_raw(self, proposed: str) -> str | None:
        """Pre-normalisation check for characters the registry must reject.

        Returns ``None`` if the raw value is acceptable for normalisation,
        else a reason string.  This catches brackets, quotes, and other
        decorations that ``_normalize`` would silently strip — the registry
        must not silently repair malformed input.
        """
        if not proposed:
            return "empty string"
        if self._FORBIDDEN.search(proposed):
            return f"forbidden characters in {proposed!r}"
        return None

    def _validate_tag(self, tag: str) -> str | None:
        """Validate *tag* (post-normalisation) against the tag-form regex.

        Returns ``None`` if valid, else a reason string.
        """
        if not tag:
            return "empty string"
        if not _VALID_TAG.match(tag):
            return f"invalid tag form {tag!r}"
        return None

    def _lookup(
        self, proposed: str, canonical_map: dict[str, str], *, kind: str = "",
    ) -> tuple[str | None, str | None]:
        """Read-only lookup: check if *proposed* is already known.

        Returns ``(canonical_form, rejection_reason)``.  If the proposed
        value is already in the registry, *canonical_form* is its stored
        form and *rejection_reason* is ``None``.  If it is not yet known,
        both are ``None``.  If it fails validation, *canonical_form* is
        ``None`` and *rejection_reason* describes why.
        """
        reason = self._validate_raw(proposed)
        if reason is not None:
            return None, reason
        nk = _normalize(proposed)
        tag_key = nk.replace(" ", "-")
        reason = self._validate_tag(tag_key)
        if reason is not None:
            return None, reason
        # Fuzzy-match via normalized key.
        if nk in canonical_map:
            return canonical_map[nk], None
        guard = self._guard(nk, kind, list(canonical_map.keys()))
        if guard is not None:
            return guard, None
        return None, None

    def _mint(
        self, tag_key: str, canonical_map: dict[str, str],
        items_key: str, minted_list: list[str],
    ) -> None:
        """Mint a new value — call only after ``_lookup`` returned
        ``(None, None)``.  *tag_key* is the kebab-case form that passed
        validation.  The normalized key (spaces) is used for the canonical
        index so future lookups with separator variants match."""
        nk = tag_key.replace("-", " ")
        canonical_map[nk] = tag_key
        items = self.raw.setdefault(items_key, [])
        items.append(tag_key)
        minted_list.append(tag_key)
        self._dirty = True

    def resolve_theme(self, proposed: str) -> tuple[str, bool]:
        """Resolve *proposed* against the theme registry.

        Returns ``(canonical_form, is_new)``.  When *proposed* normalizes
        to an existing key, the existing canonical form is returned and
        *is_new* is ``False``.  Otherwise the proposed value is minted
        as a new theme, appended to the raw array, and *is_new* is
        ``True``.

        If the raw value contains forbidden characters or the normalized
        form fails tag-form validation, the original value is returned
        with *is_new* ``False`` and nothing is persisted — the caller
        should reject the tag rather than store it.
        """
        reason = self._validate_raw(proposed)
        if reason is not None:
            return proposed, False
        nk = _normalize(proposed)
        tag_key = nk.replace(" ", "-")
        reason = self._validate_tag(tag_key)
        if reason is not None:
            return proposed, False
        if nk in self._theme_canonical:
            return self._theme_canonical[nk], False
        guard = self._guard(nk, "theme", list(self._theme_canonical))
        if guard is not None:
            return guard, False
        self._mint(tag_key, self._theme_canonical, "themes", self._minted_themes)
        return tag_key, True

    def resolve_type(self, proposed: str) -> tuple[str, bool]:
        """Resolve *proposed* against the type registry.

        Same contract as ``resolve_theme``.
        """
        reason = self._validate_raw(proposed)
        if reason is not None:
            return proposed, False
        nk = _normalize(proposed)
        tag_key = nk.replace(" ", "-")
        reason = self._validate_tag(tag_key)
        if reason is not None:
            return proposed, False
        if nk in self._type_canonical:
            return self._type_canonical[nk], False
        guard = self._guard(nk, "type", list(self._type_canonical))
        if guard is not None:
            return guard, False
        self._mint(tag_key, self._type_canonical, "types", self._minted_types)
        return tag_key, True

    def entity_keys(self) -> list[str]:
        """Normalized keys currently in the entity record."""
        return list(self._entity_canonical)

    def _reconcile_surname(self, nk: str) -> str | None:
        """Return the entity this one already exists as, under another form.

        Derivation yields ``galilei`` from "Galileo Galilei" while the vault
        holds ``galileo-galilei``; a model may propose ``immanuel-kant`` where
        the vault holds ``kant``.  Both are the same person under two forms,
        and without this they become two entity tags and the note fails to
        join the one that already exists -- which is the whole point of an
        entity tag.

        The match is on the last segment, and **only when one side is a single
        token**.  That restriction is what keeps ``john-mill`` and
        ``james-mill`` apart: two multi-token names sharing a surname are
        ordinarily two different people, while a bare surname beside a full
        name is ordinarily one.  An ambiguous bare surname -- ``mill`` when
        both Mills are on record -- matches nothing and stands on its own,
        because guessing which is meant is worse than leaving it.
        """
        parts = nk.split()
        candidates: list[str] = []
        for existing_nk, canonical in self._entity_canonical.items():
            other = existing_nk.split()
            # Exactly one side must be a bare surname.
            if (len(parts) == 1) == (len(other) == 1):
                continue
            if parts[-1] == other[-1]:
                candidates.append(canonical)
        if len(candidates) == 1:
            return candidates[0]
        return None

    def resolve_entity(self, proposed: str) -> tuple[str, bool]:
        """Resolve *proposed* against the entity record.

        Returns ``(canonical_form, is_new)``.  Unlike themes and types this is
        never a constraint: an unrecognised entity is always accepted, and the
        only question is whether the vault already writes it another way.
        """
        if self._validate_raw(proposed) is not None:
            return proposed, False
        nk = _normalize(proposed)
        tag_key = nk.replace(" ", "-")
        if self._validate_tag(tag_key) is not None:
            return proposed, False
        if nk in self._entity_canonical:
            return self._entity_canonical[nk], False
        reconciled = self._reconcile_surname(nk)
        if reconciled is not None:
            return reconciled, False
        self._mint(tag_key, self._entity_canonical, "entities", self._minted_entities)
        return tag_key, True

    def lookup_theme(self, proposed: str) -> tuple[str | None, str | None]:
        """Read-only check against the theme registry.

        Returns ``(canonical_form, rejection_reason)``.  ``None, None``
        means the tag is genuinely new and is eligible for minting.
        Never mutates.
        """
        return self._lookup(proposed, self._theme_canonical, kind="theme")

    def lookup_type(self, proposed: str) -> tuple[str | None, str | None]:
        """Read-only check against the type registry.

        Same contract as ``lookup_theme``.
        """
        return self._lookup(proposed, self._type_canonical, kind="type")

    def mint_theme(self, tag_key: str) -> None:
        """Mint a new theme.  Call only after ``lookup_theme`` returned
        ``(None, None)``.  *tag_key* is the kebab-case form."""
        self._mint(tag_key, self._theme_canonical, "themes", self._minted_themes)

    def mint_type(self, tag_key: str) -> None:
        """Mint a new type.  Call only after ``lookup_type`` returned
        ``(None, None)``.  *tag_key* is the kebab-case form."""
        self._mint(tag_key, self._type_canonical, "types", self._minted_types)

    # --- persistence ---------------------------------------------------------

    def persist(self) -> bool:
        """Atomically write taxonomy.json if the registry was mutated.

        Makes surgical text edits: every byte not involved in the mutation
        stays identical, including inline arrays, blank lines, key order and
        ``$comment`` keys.  When the file's structure does not match
        expectations (an array the file does not contain, an unexpected
        layout), falls back to full reserialisation with detected
        indentation — the file is still written correctly, just reformatted.

        Returns ``True`` if the write succeeded, ``False`` if the file was
        unwritable (the run continues with the tags already on disk).
        """
        if not self._dirty:
            return True

        # Update counts in self.raw — the surgical edit reads these.
        counts: dict[str, int] = self.raw.setdefault("_themeCounts", {})
        for t in self._minted_themes:
            counts[t] = counts.get(t, 0) + 1
        type_counts: dict[str, int] = self.raw.setdefault("_typeCounts", {})
        for t in self._minted_types:
            type_counts[t] = type_counts.get(t, 0) + 1
        entity_counts: dict[str, int] = self.raw.setdefault("_entityCounts", {})
        for t in self._minted_entities:
            entity_counts[t] = entity_counts.get(t, 0) + 1

        tmp = self.taxonomy_path.with_suffix(".json.part")
        try:
            ok = self._surgical_persist(tmp)
            if not ok:
                self._fallback_persist(tmp)
            os.replace(tmp, self.taxonomy_path)
        except OSError:
            tmp.unlink(missing_ok=True)
            return False
        self._dirty = False
        return True

    def _surgical_persist(self, tmp: Path) -> bool:
        """Attempt surgical text edits.  Returns False to trigger fallback."""
        try:
            text = self.taxonomy_path.read_text("utf-8")
            original = json.loads(text)
        except (OSError, json.JSONDecodeError):
            return False

        # Build the ordered list of mutations to apply.
        mutations: list[tuple[str, str, list[str]]] = []
        if self._minted_themes:
            mutations.append(("themes", "_themeCounts", self._minted_themes))
        if self._minted_types:
            mutations.append(("types", "_typeCounts", self._minted_types))
        if self._minted_entities:
            mutations.append(("entities", "_entityCounts", self._minted_entities))

        # Apply mutations sequentially — each sees the text produced by the
        # previous one, so offsets stay valid.
        for array_key, counts_key, items in mutations:
            if _find_json_colon(text, array_key) == -1:
                # A vault written before this key existed.  Creating it in
                # place keeps the surgical guarantee; falling through to
                # _append_to_array would return None and reserialise the whole
                # document, which is the 118-line diff this writer exists to
                # prevent.
                created = _create_array_after(text, array_key, "themes", items)
                if created is None:
                    return False
                text = created
                new_text = _set_key_in_object(text, counts_key, items)
                if new_text is None:
                    return False
                text = new_text
                continue
            new_text = _append_to_array(text, array_key, items)
            if new_text is None:
                return False
            text = new_text
            new_text = _set_key_in_object(text, counts_key, items)
            if new_text is None:
                return False
            text = new_text

        # Verify the result still parses and carries every original key.
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            return False
        for key in original:
            if key not in result:
                return False

        tmp.write_text(text, encoding="utf-8", newline="\n")
        return True

    def _fallback_persist(self, tmp: Path) -> None:
        """Full reserialisation when surgical editing cannot apply."""
        indent = self._detect_indent()
        tmp.write_text(
            json.dumps(self.raw, indent=indent, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def _detect_indent(self) -> int:
        """Detect the indentation level of the existing file."""
        try:
            text = self.taxonomy_path.read_text("utf-8")
        except OSError:
            return 2
        for line in text.splitlines():
            stripped = line.lstrip()
            if stripped and stripped != line:
                diff = len(line) - len(stripped)
                return diff if diff > 0 else 2
        return 2

    # --- queries -------------------------------------------------------------

    def undo_mint(self, kind: str, canonical: str) -> None:
        """Reverse a mint that turned out to belong to the other category.

        Called when a tag was tentatively minted as a theme but is actually
        a known type (or vice versa).  Removes from the canonical index,
        the raw array, and the minted list.
        """
        nk = _normalize(canonical)
        if kind == "theme":
            self._theme_canonical.pop(nk, None)
            themes = self.raw.get("themes", [])
            self.raw["themes"] = [t for t in themes if _normalize(t) != nk]
            self._minted_themes = [t for t in self._minted_themes
                                   if _normalize(t) != nk]
        elif kind == "type":
            self._type_canonical.pop(nk, None)
            types = self.raw.get("types", [])
            self.raw["types"] = [t for t in types if _normalize(t) != nk]
            self._minted_types = [t for t in self._minted_types
                                  if _normalize(t) != nk]

    @property
    def minted_themes(self) -> list[str]:
        """Themes minted in this run, not yet cleared."""
        return list(self._minted_themes)

    @property
    def minted_types(self) -> list[str]:
        """Types minted in this run, not yet cleared."""
        return list(self._minted_types)

    @property
    def theme_count(self) -> int:
        """Total themes in the registry."""
        return len(self.raw.get("themes", []))

    @property
    def type_count(self) -> int:
        """Total types in the registry."""
        return len(self.raw.get("types", []))

    def themes_for_hint(self) -> list[str]:
        """Current themes, for injecting into the tagger's taxonomy hint."""
        return list(self.raw.get("themes", []))

    def types_for_hint(self) -> list[str]:
        """Current types, for injecting into the tagger's taxonomy hint."""
        return list(self.raw.get("types", []))
