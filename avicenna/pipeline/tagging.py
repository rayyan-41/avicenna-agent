"""Pure tagging logic: parsing, entity derivation, assembly.

No I/O, no RunContext, no provider, no ``await``.  The tagger agent lives in
the vault and writes its own prompt; this module only parses the reply, derives
entities from the topic when the model provides none, and assembles the
positional tag array.  ``TaggingStage`` keeps the I/O, retries, and events.

The earlier design asked the model to emit a positional array — domain,
category, type, themes, entities, marker — in exactly the right slots.  A model
given that contract silently got it wrong: it produced the right words and filed
a person as a *theme*.  The fix is not a better prompt.  It is that the harness
should never have been asking a model to emit a positional array in the first
place.  The model is asked what it is good at — reading a note and judging what
it is about — and Python handles what it is bad at: positional ordering.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Labelled-slot parsing
# ---------------------------------------------------------------------------
# The tagger is asked to emit labelled lines.  But the tagger agent's prompt
# lives in the vault, not in this repo, and ``avicenna init`` scaffolds no
# tagger prompt at all.  A vault whose tagger still answers with the existing
# positional ``TAGS: a, b, c`` line must keep working.  So: parse labelled
# slots first; fall back to the positional line; and when falling back, repair
# the ordering rather than trusting it — that ordering is the thing that just
# failed.

_LABEL_CATEGORY = re.compile(
    r"^\s*CATEGORY\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE,
)
_LABEL_TYPE = re.compile(
    r"^\s*TYPE\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE,
)
_LABEL_THEMES = re.compile(
    r"^\s*THEMES?\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE,
)
_LABEL_ENTITIES = re.compile(
    r"^\s*ENTIT(?:Y|IES)\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE,
)

# Positional fallback: the legacy ``TAGS:`` line.
_TAGS_SENTINEL = re.compile(
    r"^\s*TAGS\s*:\s*(?P<tags>.+?)\s*$", re.MULTILINE | re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedTags:
    """Structured result from parsing the tagger's reply."""

    category: str | None = None
    type_: str | None = None
    themes: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    labelled: bool = False  # True when labelled slots were found


def _split_csv(raw: str) -> list[str]:
    """Split a comma-separated value string, stripping whitespace."""
    return [t.strip() for t in raw.split(",") if t.strip()]


def _to_kebab(raw: str) -> str:
    """Normalise a single tag to lowercase kebab-case.

    Consistent with ``stages._to_kebab``: lowercases, replaces underscores
    and spaces with hyphens, strips non-alphanumeric characters, collapses
    double hyphens, and strips leading/trailing hyphens.
    """
    t = raw.lower().replace("_", "-").replace(" ", "-")
    t = re.sub(r"[^a-z0-9 -]", "", t)
    while "--" in t:
        t = t.replace("--", "-")
    return t.strip("-")


def _strip_code_fence(text: str) -> str:
    """Remove a wrapping code fence if present.

    A model given a new format will sometimes wrap its answer in a code
    fence.  Strip it before parsing so the labelled-slot regex can see
    the content.
    """
    text = text.strip()
    m = re.match(
        r"^(`{3,}|~{3,})[a-zA-Z0-9_-]*\s*\n(.*?)\n?\1\s*$",
        text, re.DOTALL,
    )
    if m:
        return m.group(2).strip()
    return text


def parse_tagger_reply(output: str) -> ParsedTags:
    """Parse the tagger's reply into structured slots.

    Accepts two formats:

    1. **Labelled**: ``CATEGORY: …``, ``TYPE: …``, ``THEMES: …``,
       ``ENTITIES: …``
    2. **Positional**: ``TAGS: a, b, c, d, e``

    A mixed reply (both labelled and ``TAGS:``) is handled: labelled slots
    win for the slots they cover.  The ``TAGS:`` line is ignored when any
    labelled slot is present — the labelled slots are the explicit contract.
    """
    output = _strip_code_fence(output)

    # --- labelled slots ------------------------------------------------
    cat_m = _LABEL_CATEGORY.search(output)
    typ_m = _LABEL_TYPE.search(output)
    the_m = _LABEL_THEMES.search(output)
    ent_m = _LABEL_ENTITIES.search(output)

    has_labelled = any([cat_m, typ_m, the_m, ent_m])

    category = _to_kebab(cat_m.group(1).strip()) if cat_m else None
    type_ = _to_kebab(typ_m.group(1).strip()) if typ_m else None
    themes = tuple(
        t for t in (_to_kebab(v) for v in _split_csv(the_m.group(1))) if t
    ) if the_m else ()
    entities = tuple(
        t for t in (_to_kebab(v) for v in _split_csv(ent_m.group(1))) if t
    ) if ent_m else ()

    if has_labelled:
        return ParsedTags(
            category=category, type_=type_,
            themes=themes, entities=entities, labelled=True,
        )

    # --- positional fallback -------------------------------------------
    tags_m = _TAGS_SENTINEL.search(output)
    if tags_m:
        raw_tags = _split_csv(tags_m.group("tags"))
        kebab = [t for t in (_to_kebab(v) for v in raw_tags) if t]
        return ParsedTags(
            category=None, type_=None,
            themes=tuple(kebab), entities=(), labelled=False,
        )

    # --- nothing found -------------------------------------------------
    return ParsedTags()


# ---------------------------------------------------------------------------
# Entity derivation from topic
# ---------------------------------------------------------------------------
# When the model returns no entities, they are derived from the topic string.
# The topic is a natural sentence, so capitalisation carries information;
# headings are Title Case, which would make every noun a candidate.
#
# The naming rule is fitted to the 103 entity-slot values in the user's vault.
# Surname alone is the convention for well-known figures -- ``kant``,
# ``descartes``, ``hegel``, ``aristotle``, ``darwin``, ``schopenhauer``,
# ``euclid``, ``euler``, ``gauss`` -- while the full form survives where a
# particle makes it the customary name: ``al-ghazali``, ``ibn-sina``.
#
# KNOWN DIVERGENCE, recorded rather than papered over: the vault also holds
# ``galileo-galilei`` in full, and this derives ``galilei``.  Nothing in the
# string distinguishes that case from ``David Hume`` -> ``hume``; the full form
# there is a human refinement, and taxonomy.json records themes and types but
# NOT entities, so the harness has no cheap record of the house form to check
# against.  Reconciling a derived entity with one the vault already uses is the
# same reuse-above-threshold problem the drift guard now solves for themes, and
# it should reuse that oracle rather than grow a second heuristic here.
#
# PRECISION OVER RECALL.  Derivation is a fallback, and the two errors are not
# symmetric: a missing entity leaves a note where it already was, while a wrong
# one connects it to the wrong place and pollutes an open vocabulary that has
# no guard on it.  So a capitalised word is admitted only with a positive
# signal that it names somebody -- a possessive, a multi-token run, or a
# particle.  A bare capitalised noun is left alone.  This is why
# "Ibn Sina's Canon of Medicine" yields ``ibn-sina`` and not ``canon`` and
# ``medicine``.

_NAME_PARTICLES: frozenset[str] = frozenset({
    "ibn", "al", "bin", "de", "van", "von", "da", "del", "bint", "abu",
})

#: Sentence-initial common words that are capitalised by grammar, not by name.
_SENTENCE_INITIAL_SKIP: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "shall", "should", "may", "might", "must", "can", "could", "this",
    "that", "these", "those", "it", "its", "i", "me", "my", "we", "our",
    "you", "your", "he", "his", "she", "her", "they", "them", "their",
    "what", "which", "who", "whom", "not", "no", "so", "if", "then",
    "than", "too", "very", "just", "how", "why", "when", "where",
    "between", "through", "during", "before", "after", "above", "below",
    "up", "down", "out", "off", "over", "under", "again", "further",
    "once", "here", "there", "each", "every", "all", "both",
    "few", "more", "most", "other", "some", "such", "nor",
    "only", "own", "same", "about", "against",
})

#: A capitalised word.  Accented letters are included because the vault's
#: content is not ASCII.
_CAP_WORD = re.compile(r"[A-ZÀ-Þ][a-zß-ÿ]+")

#: A possessive clitic, straight or typographic.  It is a run *terminator*,
#: not noise to be deleted: it is the strongest available signal that the run
#: before it names somebody, and deleting it first -- as the first
#: implementation did -- destroys the boundary and lets the following word join
#: the name, which is how "Ibn Sina's Canon" became one run.
_POSSESSIVE = re.compile(r"[’']s?\b")

#: The maximum number of entity tags the contract allows.
_MAX_ENTITIES = 6


@dataclass(frozen=True)
class _Run:
    """A maximal group of capitalised words, and whether a possessive ends it."""

    tokens: tuple[str, ...]
    possessive: bool


def _is_particle_gap(gap: str) -> bool:
    """True when *gap* is a lowercase nobiliary particle between two names.

    ``René de Descartes`` and ``Ludwig van Beethoven`` are one name each, but
    the particle is lowercase, so the capitalised-word scan cannot see it and
    the run would break in the middle of the name.  Bridging the gap keeps them
    together.

    The particle is *not* added to the run, and that asymmetry is the vault's
    own convention rather than an oversight.  A capitalised particle is part of
    how the figure is named and is kept -- ``ibn-sina``, ``al-ghazali``.  A
    lowercase one is dropped in favour of the surname alone -- ``descartes``,
    ``beethoven`` -- which is exactly what the vault's existing entity values
    show.
    """
    return gap.startswith(" ") and gap.endswith(" ") and gap.strip().lower() in _NAME_PARTICLES


def _capitalised_runs(topic: str) -> list[_Run]:
    """Group the topic's capitalised words into candidate name runs.

    A run continues across a single space or a hyphen, and nothing else.  A
    comma, any other punctuation, or an intervening lowercase word ends it.
    Treating a comma like a space is what once collapsed "Plato, Aristotle,
    Descartes, Hume, Kant, Hegel" into a single run whose last token was the
    only survivor.
    """
    words = [(m.start(), m.end(), m.group()) for m in _CAP_WORD.finditer(topic)]
    if not words:
        return []

    runs: list[_Run] = []
    current: list[str] = []

    def close(end_pos: int) -> None:
        if current:
            runs.append(_Run(
                tokens=tuple(current),
                possessive=bool(_POSSESSIVE.match(topic[end_pos:end_pos + 2])),
            ))

    for i, (start, _end, word) in enumerate(words):
        if not current:
            current = [word]
            continue
        prev_end = words[i - 1][1]
        gap = topic[prev_end:start]
        if re.fullmatch(r"[ ]|-", gap) or _is_particle_gap(gap):
            current.append(word)
        else:
            close(prev_end)
            current = [word]
    close(words[-1][1])
    return runs


def derive_entities(topic: str) -> list[str]:
    """Extract entity tags from the topic string.

    1. Group capitalised words into runs, breaking on punctuation, on an
       intervening lowercase word, and on the possessive.  A lowercase
       nobiliary particle bridges a run without joining it.
    2. Drop a sentence-initial word that is capitalised by grammar rather than
       by name, and drop a lone capitalised word that trails a possessive --
       that is the thing possessed, not another name.
    3. A run containing a capitalised particle keeps its whole form
       (``ibn-sina``); otherwise the last token is the surname (``hume``).
    4. Kebab-case, dedupe, cap at six, in order of first appearance.

    The topic is the only source.  Headings were considered and rejected:
    they are Title Case, so every noun in one is capitalised, and "The
    Epistemic Gap" would offer ``gap`` as an entity with exactly the
    confidence of a surname.

    Returns an empty list when nothing in the topic names anybody, which is a
    legitimate answer -- "the nature of consciousness and free will" has no
    entities, and inventing one would be worse than having none.
    """
    entities: list[str] = []
    seen: set[str] = set()
    first = True
    trailing_possessive = False

    for run in _capitalised_runs(topic):
        tokens = list(run.tokens)
        # A sentence-initial common word is capitalised by grammar, not name.
        if first and tokens and tokens[0].lower() in _SENTENCE_INITIAL_SKIP:
            tokens = tokens[1:]
        first = False
        if not tokens:
            continue

        has_particle = any(t.lower() in _NAME_PARTICLES for t in tokens)

        # A lone capitalised word trailing a possessive is the thing possessed,
        # not another name: in "Ibn Sina's Canon of Medicine", ``Canon`` and
        # ``Medicine`` are the work.  The suppression carries on through
        # further lone words, and a multi-token run ends it -- which is what
        # keeps ``Immanuel Kant`` in "Rousseau's and David Hume's profound
        # impact on Immanuel Kant".
        #
        # It is a narrow rule and it does not catch everything: "Kant's
        # Critique of Pure Reason" still yields ``reason``, because ``Pure
        # Reason`` is two tokens and nothing in the string says it is a title
        # rather than a name.  Separating work titles from names by string
        # shape alone is not reliably possible.  That is tolerable because
        # derivation only runs when the tagger returned no entities at all --
        # it is the floor, not the primary source.
        if len(tokens) == 1 and not has_particle:
            if trailing_possessive:
                continue
        else:
            trailing_possessive = False

        if run.possessive:
            trailing_possessive = True

        name = (
            "-".join(t.lower() for t in tokens) if has_particle
            else tokens[-1].lower()
        )
        if name and name not in seen:
            seen.add(name)
            entities.append(name)
            if len(entities) >= _MAX_ENTITIES:
                break

    return entities


# ---------------------------------------------------------------------------
# Positional tag repair
# ---------------------------------------------------------------------------
# When the positional ``TAGS:`` line is used, the model may have put tags in
# the wrong slots — that ordering is the thing that just failed.  This
# function repairs the ordering using what we know: the domain is already
# decided by routing, the marker set is known from the taxonomy, and
# categories, types and themes are all checkable against the vault's
# taxonomy.  What is left over and looks like a proper noun is an entity.

def repair_positional_tags(
    raw_tags: Sequence[str],
    *,
    domain: str,
    categories: set[str],
    types: set[str],
    themes_vocab: set[str],
    markers: set[str],
) -> ParsedTags:
    """Classify raw positional tags into structured slots.

    Uses the taxonomy to decide what each tag is, rather than trusting the
    model's positional ordering.  Tags that are not domain, category, type,
    theme, or marker are treated as entities — the open vocabulary.
    """
    category: str | None = None
    type_: str | None = None
    themes: list[str] = []
    entities: list[str] = []

    for tag in raw_tags:
        if tag == domain:
            # Domain is injected by assembly, not the model.
            continue
        if tag in categories and category is None:
            category = tag
        elif tag in types and type_ is None:
            type_ = tag
        elif tag in markers:
            # Markers are injected by assembly, not the model.
            continue
        elif tag in themes_vocab and len(themes) < 3:
            themes.append(tag)
        else:
            # Not in any closed vocabulary → entity.
            entities.append(tag)

    return ParsedTags(
        category=category, type_=type_,
        themes=tuple(themes), entities=tuple(entities),
        labelled=False,
    )


# ---------------------------------------------------------------------------
# Tag array assembly
# ---------------------------------------------------------------------------
# The positional array: ``[domain, category, type, theme(s), entity(ies), marker]``.
# Arity: domain [1,1], category [1,1], type [1,1], themes [1,3],
#        entities [0,6], marker [1,1].
#
# The domain is ALWAYS routing's, never the model's.  This is the exact
# failure this module exists to make impossible.

def assemble_tag_array(
    *,
    domain: str,
    parsed: ParsedTags,
    categories: Sequence[str],
    types: Sequence[str],
    themes_vocab: Sequence[str],
    markers: Sequence[str],
    derived_entities: Sequence[str] = (),
) -> list[str]:
    """Build the positional tag array from parsed model output.

    The domain is always routing's — never the model's.  Categories, types,
    and themes are validated against the taxonomy.  Entities are an open
    vocabulary (kebab-case proper nouns).

    Returns a structurally well-formed array regardless of what the model
    returned: empty, garbage, a refusal, the wrong format, or forty tags.
    """
    cat_set = set(categories)
    type_set = set(types)
    theme_set = set(themes_vocab)

    # --- domain [1,1]: always routing's --------------------------------
    result: list[str] = [domain]

    # --- category [1,1]: prefer model's, validate, fallback ------------
    category: str | None = None
    if parsed.category and parsed.category in cat_set:
        category = parsed.category
    elif not parsed.labelled:
        # Positional fallback — scan the themes list for a category.
        for t in parsed.themes:
            if t in cat_set:
                category = t
                break
    if category is None and categories:
        category = categories[0]
    if category:
        result.append(category)

    # --- type [1,1]: prefer model's, validate, fallback ----------------
    type_val: str | None = None
    if parsed.type_ and parsed.type_ in type_set:
        type_val = parsed.type_
    elif not parsed.labelled:
        for t in parsed.themes:
            if t in type_set:
                type_val = t
                break
    if type_val is None and types:
        type_val = types[0]
    if type_val:
        result.append(type_val)

    # --- themes [1,3]: prefer model's, validate, at least one ----------
    selected_themes: list[str] = []
    if parsed.labelled:
        for t in parsed.themes:
            if t in theme_set and t not in selected_themes:
                selected_themes.append(t)
                if len(selected_themes) >= 3:
                    break
    else:
        # Positional: anything that isn't already claimed and is in the
        # theme vocabulary.
        used = {domain, category, type_val}
        marker_set = set(markers)
        for t in parsed.themes:
            if t in used or t in marker_set:
                continue
            if t in theme_set and t not in selected_themes:
                selected_themes.append(t)
                if len(selected_themes) >= 3:
                    break
    if not selected_themes and themes_vocab:
        selected_themes.append(themes_vocab[0])
    result.extend(selected_themes)

    # --- entities [0,6]: prefer model's, then derived ------------------
    ent: list[str] = []
    if parsed.entities:
        ent = list(parsed.entities[:6])
    elif derived_entities:
        ent = list(derived_entities[:6])
    result.extend(ent)

    # --- marker [1,1]: always the taxonomy's first ---------------------
    marker = markers[0] if markers else "cli"
    result.append(marker)

    return result
