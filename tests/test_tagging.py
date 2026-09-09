"""Tests for avicenna.pipeline.tagging: pure tagging logic.

Covers three layers, each tested as pure functions with no I/O:

1. Parsing — labelled slots, positional TAGS: line, mixed, malformed, empty,
   extra whitespace, and code-fence wrapping.
2. Derivation — possessives, name particles (Ibn Sina, Al-Ghazali), multi-word
   names (Galileo Galilei, David Hume), a topic with nothing derivable, and a
   topic with more than six figures.
3. Assembly — correct order and arity from every parse outcome, and the
   property that the domain is always routing's, never the model's.
"""

from __future__ import annotations

from avicenna.pipeline.tagging import (
    ParsedTags,
    assemble_tag_array,
    derive_entities,
    parse_tagger_reply,
    repair_positional_tags,
)


# ===================================================================
# 1. Parsing
# ===================================================================


class TestParseLabelledSlots:
    """The tagger emits labelled lines: CATEGORY:, TYPE:, THEMES:, ENTITIES:."""

    def test_basic_labelled(self) -> None:
        output = (
            "CATEGORY: epistemology\n"
            "TYPE: essay\n"
            "THEMES: revelation, knowledge\n"
            "ENTITIES: kant, hume\n"
        )
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is True
        assert parsed.category == "epistemology"
        assert parsed.type_ == "essay"
        assert parsed.themes == ("revelation", "knowledge")
        assert parsed.entities == ("kant", "hume")

    def test_labelled_case_insensitive(self) -> None:
        output = (
            "category: Epistemology\n"
            "type: Essay\n"
            "themes: Revelation\n"
            "entities: Kant\n"
        )
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is True
        assert parsed.category == "epistemology"
        assert parsed.type_ == "essay"
        assert parsed.themes == ("revelation",)
        assert parsed.entities == ("kant",)

    def test_labelled_singular_forms(self) -> None:
        """Accept THEME: and ENTITY: (singular) as well as plural."""
        output = (
            "CATEGORY: metaphysics\n"
            "TYPE: treatise\n"
            "THEME: consciousness\n"
            "ENTITY: hegel\n"
        )
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is True
        assert parsed.themes == ("consciousness",)
        assert parsed.entities == ("hegel",)

    def test_labelled_extra_whitespace(self) -> None:
        output = (
            "  CATEGORY:   epistemology  \n"
            "  TYPE:   essay  \n"
            "  THEMES:   revelation ,  knowledge  \n"
            "  ENTITIES:   kant  ,  hume  \n"
        )
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is True
        assert parsed.category == "epistemology"
        assert parsed.type_ == "essay"
        assert parsed.themes == ("revelation", "knowledge")
        assert parsed.entities == ("kant", "hume")

    def test_labelled_partial(self) -> None:
        """Only some labelled slots present — still counts as labelled."""
        output = "CATEGORY: ethics\nTHEMES: virtue\n"
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is True
        assert parsed.category == "ethics"
        assert parsed.type_ is None
        assert parsed.themes == ("virtue",)
        assert parsed.entities == ()

    def test_labelled_in_prose(self) -> None:
        """Labelled slots embedded in surrounding prose."""
        output = (
            "After reviewing the note, here are my tags:\n"
            "CATEGORY: epistemology\n"
            "TYPE: essay\n"
            "THEMES: revelation\n"
            "ENTITIES: kant\n"
            "I hope this helps.\n"
        )
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is True
        assert parsed.category == "epistemology"
        assert parsed.entities == ("kant",)


class TestParsePositionalFallback:
    """The legacy TAGS: line — backwards compatibility."""

    def test_basic_positional(self) -> None:
        output = "Reviewed the note.\nTAGS: philosophy, epistemology, revelation, kant, cli"
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is False
        assert parsed.category is None
        assert parsed.type_ is None
        assert parsed.themes == ("philosophy", "epistemology", "revelation", "kant", "cli")
        assert parsed.entities == ()

    def test_positional_brackets(self) -> None:
        output = "TAGS: [philosophy, epistemology, revelation]"
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is False
        assert parsed.themes == ("philosophy", "epistemology", "revelation")

    def test_positional_quotes(self) -> None:
        output = 'TAGS: "philosophy", "epistemology"'
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is False
        assert parsed.themes == ("philosophy", "epistemology")

    def test_positional_hashes(self) -> None:
        output = "TAGS: #philosophy, #epistemology"
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is False
        assert parsed.themes == ("philosophy", "epistemology")

    def test_positional_case_insensitive(self) -> None:
        output = "tags: Philosophy, Epistemology"
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is False
        assert parsed.themes == ("philosophy", "epistemology")

    def test_positional_extra_whitespace(self) -> None:
        output = "  TAGS:   philosophy ,  epistemology  ,  revelation  "
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is False
        assert parsed.themes == ("philosophy", "epistemology", "revelation")


class TestParseMixed:
    """A model given a new format will sometimes emit both."""

    def test_labelled_wins_over_positional(self) -> None:
        output = (
            "CATEGORY: ethics\n"
            "TYPE: essay\n"
            "THEMES: virtue\n"
            "TAGS: old, format, tags\n"
        )
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is True
        assert parsed.category == "ethics"
        assert parsed.themes == ("virtue",)
        # The TAGS: line is ignored when labelled slots are present.

    def test_labelled_partial_with_tags(self) -> None:
        """Labelled slots found → labelled mode, even if TAGS: is also present."""
        output = (
            "CATEGORY: metaphysics\n"
            "TAGS: philosophy, epistemology, revelation\n"
        )
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is True
        assert parsed.category == "metaphysics"
        # TAGS: line is ignored.


class TestParseMalformed:
    """Empty, garbage, refusal, or unrecognised format."""

    def test_empty_string(self) -> None:
        parsed = parse_tagger_reply("")
        assert parsed.labelled is False
        assert parsed.themes == ()
        assert parsed.entities == ()

    def test_garbage_prose(self) -> None:
        parsed = parse_tagger_reply("Here are my thoughts on this note.")
        assert parsed.labelled is False
        assert parsed.themes == ()

    def test_refusal(self) -> None:
        parsed = parse_tagger_reply("I cannot determine the tags for this note.")
        assert parsed.labelled is False
        assert parsed.themes == ()

    def test_only_blanks(self) -> None:
        parsed = parse_tagger_reply("   \n  \n  ")
        assert parsed.labelled is False
        assert parsed.themes == ()


class TestParseCodeFence:
    """A model wrapping its answer in a code fence."""

    def test_backtick_fence(self) -> None:
        output = (
            "```text\n"
            "CATEGORY: epistemology\n"
            "TYPE: essay\n"
            "THEMES: revelation\n"
            "ENTITIES: kant\n"
            "```"
        )
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is True
        assert parsed.category == "epistemology"
        assert parsed.entities == ("kant",)

    def test_tilde_fence(self) -> None:
        output = (
            "~~~\n"
            "TAGS: philosophy, epistemology, revelation\n"
            "~~~"
        )
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is False
        assert parsed.themes == ("philosophy", "epistemology", "revelation")

    def test_fence_with_language(self) -> None:
        output = (
            "```markdown\n"
            "CATEGORY: ethics\n"
            "THEMES: virtue, justice\n"
            "```"
        )
        parsed = parse_tagger_reply(output)
        assert parsed.labelled is True
        assert parsed.category == "ethics"
        assert parsed.themes == ("virtue", "justice")


# ===================================================================
# 2. Entity derivation
# ===================================================================


class TestDeriveEntities:
    """Extract proper nouns from the topic string."""

    def test_worked_example(self) -> None:
        """The canonical example from the task spec."""
        topic = "Rousseau's and David Hume's profound impact on Immanuel Kant"
        entities = derive_entities(topic)
        assert entities == ["rousseau", "hume", "kant"]

    def test_possessive_stripping(self) -> None:
        entities = derive_entities("Nietzsche's critique of morality")
        assert entities == ["nietzsche"]

    def test_lowercase_particle_yields_surname_only(self) -> None:
        """A lowercase nobiliary particle bridges the name but is dropped.

        The vault holds `descartes`, not `de-descartes`, and certainly not a
        separate `rene`.  The particle has to bridge the gap -- it is lowercase,
        so the capitalised-word scan cannot see it and the run would otherwise
        break in the middle of the name -- without joining the tag.
        """
        assert derive_entities(
            "René de Descartes and the method of doubt",
        ) == ["descartes"]
        assert derive_entities(
            "Ludwig van Beethoven's symphonies",
        ) == ["beethoven"]

    def test_capitalised_particle_is_kept(self) -> None:
        """A capitalised particle is part of how the figure is named.

        `ibn-sina` and `al-ghazali` are both in the vault in full.  This is the
        asymmetry with the lowercase case above, and it is the vault's
        convention rather than an inconsistency.
        """
        assert derive_entities("Ibn Sina's Canon of Medicine") == ["ibn-sina"]
        assert derive_entities(
            "Al-Ghazali's response to the philosophers",
        ) == ["al-ghazali"]

    def test_possessed_work_is_not_an_entity(self) -> None:
        """A lone capitalised word trailing a possessive is the thing possessed.

        `Canon` and `Medicine` are the work, not two more people, and a wrong
        entity is worse than a missing one: it connects the note to the wrong
        place and pollutes an open vocabulary that has no guard on it.
        """
        assert derive_entities("Ibn Sina's Canon of Medicine") == ["ibn-sina"]

    def test_a_multi_token_run_ends_the_suppression(self) -> None:
        """Otherwise the possessive rule would swallow the next real name."""
        assert derive_entities(
            "Rousseau's and David Hume's profound impact on Immanuel Kant",
        ) == ["rousseau", "hume", "kant"]

    def test_bare_names_without_a_possessive_are_admitted(self) -> None:
        """The commonest topic shape of all has no possessive in it."""
        assert derive_entities("The influence of Hume on Kant") == ["hume", "kant"]

    def test_multi_word_david_hume(self) -> None:
        entities = derive_entities("David Hume on causation")
        assert entities == ["hume"]

    def test_multi_word_galileo_galilei(self) -> None:
        """Two-word name without a particle: last token as surname.

        The vault writes `galileo-galilei` in full, and derivation cannot know
        that -- nothing in the string separates this case from `David Hume` ->
        `hume`.  Deriving the surname here is correct and deliberate: the house
        form is reconciled afterwards by `ThemeRegistry.resolve_entity`, which
        has the vault's recorded entities to consult, and is covered in
        tests/test_entities.py. Keeping the two apart is what lets this
        function stay a pure string transform.
        """
        assert derive_entities("Galileo Galilei and the telescope") == ["galilei"]

    def test_nothing_derivable(self) -> None:
        entities = derive_entities("the nature of consciousness and free will")
        assert entities == []

    def test_more_than_six_figures_is_capped(self) -> None:
        """The contract allows at most six entities; the first six survive."""
        topic = (
            "David Hume, Immanuel Kant, Georg Hegel, Friedrich Nietzsche, "
            "Rene Descartes, Baruch Spinoza, and Gottfried Leibniz on knowledge"
        )
        entities = derive_entities(topic)
        assert entities == [
            "hume", "kant", "hegel", "nietzsche", "descartes", "spinoza",
        ]

    def test_commas_separate_names(self) -> None:
        """A comma ends a run; it is not a space.

        Treating the two alike once collapsed a seven-name list into a single
        run whose last token was the only survivor -- the test above returned
        ["hegel", "nietzsche"] for seven figures.
        """
        entities = derive_entities("David Hume, Immanuel Kant on causation")
        assert entities == ["hume", "kant"]

    def test_dedupe(self) -> None:
        entities = derive_entities("Kant and Kant's critical philosophy")
        assert entities == ["kant"]
        assert len(entities) == 1

    def test_sentence_initial_skip(self) -> None:
        """A sentence-initial 'The' is not a proper noun."""
        entities = derive_entities("The influence of Hume on Kant")
        assert entities == ["hume", "kant"]

    def test_single_name(self) -> None:
        entities = derive_entities("Aristotle's ethics")
        assert entities == ["aristotle"]

    def test_hyphenated_particle(self) -> None:
        entities = derive_entities("Al-Ghazali and Ibn Sina")
        assert entities == ["al-ghazali", "ibn-sina"]


# ===================================================================
# 3. Positional tag repair
# ===================================================================


class TestRepairPositionalTags:
    """Classify raw positional tags against taxonomy knowledge."""

    def test_basic_repair(self) -> None:
        raw = ["philosophy", "epistemology", "essay", "revelation", "kant", "cli"]
        repaired = repair_positional_tags(
            raw,
            domain="philosophy",
            categories={"epistemology", "metaphysics"},
            types={"essay", "treatise"},
            themes_vocab={"revelation", "knowledge"},
            markers={"cli"},
        )
        assert repaired.category == "epistemology"
        assert repaired.type_ == "essay"
        assert repaired.themes == ("revelation",)
        assert repaired.entities == ("kant",)
        assert repaired.labelled is False

    def test_domain_stripped(self) -> None:
        """The domain tag is removed — assembly injects it."""
        raw = ["philosophy", "epistemology", "cli"]
        repaired = repair_positional_tags(
            raw,
            domain="philosophy",
            categories={"epistemology"},
            types={"essay"},
            themes_vocab={"knowledge"},
            markers={"cli"},
        )
        assert repaired.category == "epistemology"
        # "philosophy" should not appear in any slot.
        assert "philosophy" not in repaired.themes
        assert "philosophy" not in repaired.entities

    def test_marker_stripped(self) -> None:
        """Markers are injected by assembly, not the model."""
        raw = ["epistemology", "essay", "revelation", "cli"]
        repaired = repair_positional_tags(
            raw,
            domain="philosophy",
            categories={"epistemology"},
            types={"essay"},
            themes_vocab={"revelation"},
            markers={"cli"},
        )
        # "cli" should not appear in themes or entities.
        assert "cli" not in repaired.themes
        assert "cli" not in repaired.entities

    def test_unknown_tags_become_entities(self) -> None:
        """Tags not in any closed vocabulary are treated as entities."""
        raw = ["epistemology", "essay", "kant", "hume", "rousseau"]
        repaired = repair_positional_tags(
            raw,
            domain="philosophy",
            categories={"epistemology"},
            types={"essay"},
            themes_vocab={"revelation"},
            markers={"cli"},
        )
        assert repaired.entities == ("kant", "hume", "rousseau")

    def test_max_three_themes(self) -> None:
        raw = ["epistemology", "essay", "revelation", "knowledge", "consciousness", "cli"]
        repaired = repair_positional_tags(
            raw,
            domain="philosophy",
            categories={"epistemology"},
            types={"essay"},
            themes_vocab={"revelation", "knowledge", "consciousness", "justice"},
            markers={"cli"},
        )
        assert len(repaired.themes) == 3

    def test_empty_input(self) -> None:
        repaired = repair_positional_tags(
            [],
            domain="philosophy",
            categories={"epistemology"},
            types={"essay"},
            themes_vocab={"revelation"},
            markers={"cli"},
        )
        assert repaired.category is None
        assert repaired.type_ is None
        assert repaired.themes == ()
        assert repaired.entities == ()


# ===================================================================
# 4. Assembly
# ===================================================================


class TestAssembleTagArray:
    """Build the positional tag array from parsed model output."""

    _CATEGORIES = ["epistemology", "metaphysics", "ethics"]
    _TYPES = ["essay", "treatise", "person"]
    _THEMES = ["revelation", "knowledge", "consciousness"]
    _MARKERS = ["cli"]

    def test_labelled_full(self) -> None:
        parsed = ParsedTags(
            category="epistemology", type_="essay",
            themes=("revelation",), entities=("kant",),
            labelled=True,
        )
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        assert result == ["philosophy", "epistemology", "essay", "revelation", "kant", "cli"]

    def test_domain_is_routings(self) -> None:
        """The domain is always routing's, never the model's."""
        parsed = ParsedTags(
            # Model says "art" — routing says "philosophy".
            category="art-history", type_="essay",
            themes=("revelation",), entities=(),
            labelled=True,
        )
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        assert result[0] == "philosophy", "domain must be routing's"
        assert "art" not in result, "model's domain must not appear"

    def test_domain_routings_with_positional_model_domain(self) -> None:
        """A positional TAGS: line naming a different domain — repaired."""
        raw_tags = ["art", "epistemology", "essay", "revelation", "kant", "cli"]
        repaired = repair_positional_tags(
            raw_tags,
            domain="philosophy",
            categories={"epistemology", "metaphysics"},
            types={"essay", "treatise"},
            themes_vocab={"revelation", "knowledge"},
            markers={"cli"},
        )
        result = assemble_tag_array(
            domain="philosophy", parsed=repaired,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        assert result[0] == "philosophy", "domain must be routing's"
        # "art" was not in any closed vocabulary, so it became an entity.
        assert "art" in result

    def test_empty_model_yields_floor(self) -> None:
        """Empty model response → category/type/themes from taxonomy floor."""
        parsed = ParsedTags()
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        assert result[0] == "philosophy"
        assert result[1] == "epistemology"  # first category
        assert result[2] == "essay"  # first type
        assert result[3] == "revelation"  # first theme
        assert result[-1] == "cli"

    def test_derived_entities_used_when_model_returns_none(self) -> None:
        parsed = ParsedTags(
            category="epistemology", type_="essay",
            themes=("revelation",), entities=(),
            labelled=True,
        )
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
            derived_entities=["rousseau", "hume", "kant"],
        )
        assert "rousseau" in result
        assert "hume" in result
        assert "kant" in result

    def test_model_entities_preferred_over_derived(self) -> None:
        parsed = ParsedTags(
            category="epistemology", type_="essay",
            themes=("revelation",), entities=("hegel",),
            labelled=True,
        )
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
            derived_entities=["rousseau", "hume"],
        )
        # Model's entity wins; derived is not used.
        assert "hegel" in result
        assert "rousseau" not in result

    def test_entities_capped_at_six(self) -> None:
        parsed = ParsedTags(
            category="epistemology", type_="essay",
            themes=("revelation",),
            entities=("a", "b", "c", "d", "e", "f", "g"),
            labelled=True,
        )
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        ent_in_result = [t for t in result if t not in {
            "philosophy", "epistemology", "essay", "revelation", "cli",
        }]
        assert len(ent_in_result) <= 6

    def test_marker_is_last(self) -> None:
        parsed = ParsedTags()
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        assert result[-1] == "cli"

    def test_at_least_two_tags(self) -> None:
        """update_moc requires >= 2 tags to group the note."""
        parsed = ParsedTags()
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        assert len(result) >= 2

    def test_themes_at_least_one(self) -> None:
        """Even with no model themes, the floor provides one."""
        parsed = ParsedTags(category="epistemology", type_="essay", labelled=True)
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        themes_in_result = [t for t in result if t in set(self._THEMES)]
        assert len(themes_in_result) >= 1

    def test_themes_capped_at_three(self) -> None:
        parsed = ParsedTags(
            category="epistemology", type_="essay",
            themes=("revelation", "knowledge", "consciousness", "justice"),
            labelled=True,
        )
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        themes_in_result = [t for t in result if t in set(self._THEMES)]
        assert len(themes_in_result) <= 3

    def test_positional_repair_then_assemble(self) -> None:
        """End-to-end: positional TAGS: → repair → assembly."""
        raw = ["philosophy", "epistemology", "essay", "revelation", "kant", "hume", "cli"]
        repaired = repair_positional_tags(
            raw,
            domain="philosophy",
            categories={"epistemology", "metaphysics"},
            types={"essay", "treatise"},
            themes_vocab={"revelation", "knowledge"},
            markers={"cli"},
        )
        result = assemble_tag_array(
            domain="philosophy", parsed=repaired,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        assert result == [
            "philosophy", "epistemology", "essay", "revelation", "kant", "hume", "cli",
        ]


# ===================================================================
# 5. The property that matters
# ===================================================================


class TestStructuralWellformedness:
    """Whatever the model returns, the array is structurally well-formed.

    The domain is routing's, not the model's.  This is the exact failure
    this module exists to make impossible.
    """

    _CATEGORIES = ["epistemology", "metaphysics"]
    _TYPES = ["essay", "treatise"]
    _THEMES = ["revelation", "knowledge"]
    _MARKERS = ["cli"]

    def _assert_wellformed(self, result: list[str], domain: str = "philosophy") -> None:
        """Assert structural invariants of a tag array."""
        assert result[0] == domain, f"domain must be routing's ({domain}): {result}"
        assert result[-1] == "cli", f"marker must be last: {result}"
        assert len(result) >= 2, f"at least 2 tags: {result}"
        # All tags are non-empty strings.
        for tag in result:
            assert tag, f"empty tag in {result}"

    def test_empty_model(self) -> None:
        parsed = ParsedTags()
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        self._assert_wellformed(result)

    def test_garbage_model(self) -> None:
        """Model returns unparseable prose."""
        parsed = parse_tagger_reply("Here are my thoughts on this note.")
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        self._assert_wellformed(result)

    def test_model_names_wrong_domain(self) -> None:
        """Model says 'art' — routing says 'philosophy'."""
        parsed = ParsedTags(
            category="art-history", type_="essay",
            themes=("painting",), entities=("picasso",),
            labelled=True,
        )
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        self._assert_wellformed(result)
        assert "art" not in result

    def test_forty_tags_model(self) -> None:
        """Model returns way too many tags — array stays bounded."""
        many_themes = tuple(f"theme-{i}" for i in range(20))
        many_entities = tuple(f"entity-{i}" for i in range(20))
        parsed = ParsedTags(
            category="epistemology", type_="essay",
            themes=many_themes, entities=many_entities,
            labelled=True,
        )
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        self._assert_wellformed(result)
        # Themes capped at 3, entities capped at 6.
        assert len(result) <= 1 + 1 + 1 + 3 + 6 + 1  # domain+cat+type+themes+ents+marker

    def test_positional_wrong_domain_repaired(self) -> None:
        """Positional TAGS: with wrong domain → repair → domain is routing's."""
        raw = ["art", "art-history", "essay", "painting", "picasso", "cli"]
        repaired = repair_positional_tags(
            raw,
            domain="philosophy",
            categories={"epistemology", "metaphysics"},
            types={"essay", "treatise"},
            themes_vocab={"revelation", "knowledge"},
            markers={"cli"},
        )
        result = assemble_tag_array(
            domain="philosophy", parsed=repaired,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        self._assert_wellformed(result)
        # "art" was not in any closed vocabulary → became an entity.
        # But the domain is still routing's.
        assert result[0] == "philosophy"

    def test_labelled_empty_everything(self) -> None:
        """All labelled slots empty → floor values from taxonomy."""
        parsed = ParsedTags(labelled=True)
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        self._assert_wellformed(result)

    def test_refusal_text(self) -> None:
        """Model refuses → parsed as empty → floor."""
        parsed = parse_tagger_reply("I cannot determine the tags for this note.")
        result = assemble_tag_array(
            domain="philosophy", parsed=parsed,
            categories=self._CATEGORIES, types=self._TYPES,
            themes_vocab=self._THEMES, markers=self._MARKERS,
        )
        self._assert_wellformed(result)
