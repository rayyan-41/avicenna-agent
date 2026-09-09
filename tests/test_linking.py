"""Tests for deterministic linking: related notes, and inline entity mentions.

Both mechanisms exist to make a note reachable from the rest of the vault, so
the failures worth guarding against are the ones that produce a *wrong*
connection rather than none: a link to the other Mill, a link inside a heading
that breaks its anchor, a second Related Notes section on every resume.
"""

from __future__ import annotations

from avicenna.pipeline.linking import (
    RelatedNote,
    append_section,
    link_first_mentions,
    parse_related_output,
    render_related_section,
    resolve_entity_notes,
    strip_related_section,
    subject_index,
)

# ---------------------------------------------------------------------------
# Which entities have a note
# ---------------------------------------------------------------------------


class TestSubjectIndex:
    def test_a_note_is_findable_by_its_full_name(self) -> None:
        index = subject_index(["Jean-Jacques Rousseau"])
        assert index["jean-jacques-rousseau"] == "Jean-Jacques Rousseau"

    def test_and_by_its_surname(self) -> None:
        """The tag says `rousseau`; the vault filed the full name."""
        index = subject_index(["Jean-Jacques Rousseau"])
        assert index["rousseau"] == "Jean-Jacques Rousseau"

    def test_an_ambiguous_surname_is_dropped(self) -> None:
        """Two Mills on file means `mill` names neither of them.

        A link to the wrong person is worse than no link: it is a claim the
        note did not make, and nothing downstream can tell it was a guess.
        """
        index = subject_index(["John Stuart Mill", "James Mill"])
        assert "mill" not in index
        assert index["john-stuart-mill"] == "John Stuart Mill"
        assert index["james-mill"] == "James Mill"

    def test_the_same_note_listed_twice_is_not_ambiguous(self) -> None:
        index = subject_index(["Kant", "Kant"])
        assert index["kant"] == "Kant"

    def test_punctuation_in_a_filename(self) -> None:
        index = subject_index(["Al-Ghazali (Biography)"])
        assert index["al-ghazali-biography"] == "Al-Ghazali (Biography)"

    def test_a_title_gets_no_surname_alias(self) -> None:
        """Found against the real vault, where every one of these was wrong.

        Registering the last segment unconditionally made `kant` resolve to a
        note called "Rousseau's and David Hume's profound impact on Immanuel
        Kant" — a note that mentions Kant, filed under a sentence, and not the
        Kant note. The rule now asks whether the filename reads as a name.
        """
        index = subject_index([
            "Rousseau's and David Hume's profound impact on Immanuel Kant",
            "Foundations of Attention",
            "Triangles as the basis for Rasterization",
            "An Effort to Understand Iqbal",
        ])
        for stranded in ("kant", "attention", "rasterization", "iqbal"):
            assert stranded not in index, stranded
        # The full form still resolves — only the surname alias is withheld.
        assert index["foundations-of-attention"] == "Foundations of Attention"

    def test_a_name_still_gets_its_alias(self) -> None:
        index = subject_index(["Galileo Galilei", "Jean-Jacques Rousseau", "Ibn Sina"])
        assert index["galilei"] == "Galileo Galilei"
        assert index["rousseau"] == "Jean-Jacques Rousseau"
        assert index["sina"] == "Ibn Sina"

    def test_a_long_name_is_treated_as_a_title(self) -> None:
        """Five segments with no function word is past where a name lives."""
        index = subject_index(["Abu Hamid Muhammad ibn Muhammad al-Ghazali"])
        assert "ghazali" not in index


class TestResolveEntityNotes:
    def test_only_entities_with_a_note(self) -> None:
        index = subject_index(["Jean-Jacques Rousseau", "Aristotle"])
        got = resolve_entity_notes(["rousseau", "kant", "aristotle"], index)
        assert got == {"rousseau": "Jean-Jacques Rousseau", "aristotle": "Aristotle"}

    def test_two_entities_resolving_to_one_note_link_once(self) -> None:
        """`rousseau` and `jean-jacques-rousseau` are the same person."""
        index = subject_index(["Jean-Jacques Rousseau"])
        got = resolve_entity_notes(["rousseau", "jean-jacques-rousseau"], index)
        assert list(got.values()) == ["Jean-Jacques Rousseau"]

    def test_no_entities(self) -> None:
        assert resolve_entity_notes([], subject_index(["Kant"])) == {}


# ---------------------------------------------------------------------------
# Inline linking
# ---------------------------------------------------------------------------


class TestLinkFirstMentions:
    def test_links_the_first_mention_only(self) -> None:
        body = "Rousseau argued this.\n\nLater Rousseau recanted it.\n"
        out, linked = link_first_mentions(body, {"rousseau": "Rousseau"})
        assert out == "[[Rousseau]] argued this.\n\nLater Rousseau recanted it.\n"
        assert linked == ["Rousseau"]

    def test_a_shorter_surface_form_gets_an_alias(self) -> None:
        """The sentence keeps the words its author wrote."""
        body = "Rousseau argued this.\n"
        out, _ = link_first_mentions(body, {"rousseau": "Jean-Jacques Rousseau"})
        assert out == "[[Jean-Jacques Rousseau|Rousseau]] argued this.\n"

    def test_the_full_name_is_preferred_when_the_prose_uses_it(self) -> None:
        """Otherwise "Jean-Jacques " is stranded outside the link."""
        body = "Jean-Jacques Rousseau argued this.\n"
        out, _ = link_first_mentions(body, {"rousseau": "Jean-Jacques Rousseau"})
        assert out == "[[Jean-Jacques Rousseau]] argued this.\n"

    def test_headings_are_never_linked(self) -> None:
        """A link in a heading breaks the anchor the TOC generated for it."""
        body = "## 1. Rousseau on Sovereignty\n\nRousseau argued this.\n"
        out, _ = link_first_mentions(body, {"rousseau": "Rousseau"})
        assert out.startswith("## 1. Rousseau on Sovereignty\n")
        assert "[[Rousseau]] argued this." in out

    def test_the_table_of_contents_is_never_linked(self) -> None:
        """The TOC lives in a blockquote callout."""
        body = "> - [Rousseau on Sovereignty](#rousseau)\n\nRousseau argued this.\n"
        out, _ = link_first_mentions(body, {"rousseau": "Rousseau"})
        assert out.startswith("> - [Rousseau on Sovereignty](#rousseau)\n")
        assert "[[Rousseau]] argued this." in out

    def test_fenced_code_is_never_linked(self) -> None:
        body = "```python\nRousseau = 1\n```\n\nRousseau argued this.\n"
        out, _ = link_first_mentions(body, {"rousseau": "Rousseau"})
        assert "Rousseau = 1" in out
        assert "[[Rousseau]] argued this." in out

    def test_a_note_already_linked_is_left_entirely_alone(self) -> None:
        """One link is the whole contract, whoever wrote it.

        The body may already carry a link — from a previous run of this stage,
        or from transition prose. Adding another is not idempotent: on the
        second pass the first mention is already wrapped, so the *second* one
        becomes the first unlinked match and a note gains one more link per
        resume, while each individual pass still looks like it linked once.
        """
        body = "See [[Rousseau]] for more. Rousseau argued this.\n"
        out, linked = link_first_mentions(body, {"rousseau": "Rousseau"})
        assert out == body
        assert linked == []

    def test_an_existing_wikilink_to_another_note_is_not_nested(self) -> None:
        body = "See [[Autonomy]] for more. Rousseau argued this.\n"
        out, _ = link_first_mentions(body, {"rousseau": "Rousseau"})
        assert out == "See [[Autonomy]] for more. [[Rousseau]] argued this.\n"

    def test_a_substring_of_a_longer_word_is_not_a_mention(self) -> None:
        body = "Kantian ethics differ. Kant argued this.\n"
        out, _ = link_first_mentions(body, {"kant": "Kant"})
        assert out == "Kantian ethics differ. [[Kant]] argued this.\n"

    def test_an_entity_never_mentioned_in_the_prose_is_not_linked(self) -> None:
        body = "The argument runs otherwise.\n"
        out, linked = link_first_mentions(body, {"rousseau": "Rousseau"})
        assert out == body
        assert linked == []

    def test_a_filename_that_cannot_be_a_link_target_is_skipped(self) -> None:
        """`[`, `]`, `#`, `^` and `|` break a wikilink; do not emit a dead one."""
        body = "Rousseau argued this.\n"
        out, linked = link_first_mentions(body, {"rousseau": "Rousseau [draft]"})
        assert out == body
        assert linked == []

    def test_no_targets_changes_nothing(self) -> None:
        body = "The argument runs otherwise.\n"
        assert link_first_mentions(body, {}) == (body, [])


# ---------------------------------------------------------------------------
# Reading the vault tool's output
# ---------------------------------------------------------------------------


SAMPLE = """CANDIDATES_FOUND: 2
---
SCORE:5 | MATCH:primary | PATH:E:\\Vault\\Islam\\Fiqh\\Prayer (Fiqh).md | TAGS:islam,fiqh,prayer,cli
SCORE:2 | MATCH:secondary | PATH:E:\\Vault\\Islam\\Aqeedah\\Niyyah.md | TAGS:islam,aqeedah,intention,cli
---
EXCLUDED_BY_POLICY: 1
"""


class TestParseRelatedOutput:
    def test_reads_every_candidate_line(self) -> None:
        got = parse_related_output(SAMPLE)
        assert [n.score for n in got] == [5, 2]
        assert [n.match for n in got] == ["primary", "secondary"]
        assert got[0].tags == ("islam", "fiqh", "prayer", "cli")

    def test_the_stem_comes_off_the_windows_path(self) -> None:
        got = parse_related_output(SAMPLE)
        assert got[0].stem == "Prayer (Fiqh)"
        assert got[1].stem == "Niyyah"

    def test_the_contract_token_and_separators_are_not_candidates(self) -> None:
        assert len(parse_related_output(SAMPLE)) == 2

    def test_no_candidates(self) -> None:
        text = (
            "CANDIDATES_FOUND: 0\nNO_POLICY_VALID_CANDIDATES: nothing\n"
            "EXCLUDED_BY_POLICY: 0\n"
        )
        assert parse_related_output(text) == []

    def test_an_unrecognised_line_is_ignored_rather_than_fatal(self) -> None:
        """A tool that gains a field must not fail the run."""
        text = SAMPLE + "SOMETHING_NEW: 3\n"
        assert len(parse_related_output(text)) == 2


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _note(stem: str, tags: tuple[str, ...], score: int = 4) -> RelatedNote:
    return RelatedNote(score=score, match="primary", path=f"V\\{stem}.md", tags=tags)


class TestRenderRelatedSection:
    def test_names_the_shared_tags(self) -> None:
        """A bare list of links does not say why they are there."""
        got = render_related_section(
            [_note("Prayer", ("islam", "fiqh", "prayer"))],
            own_tags=["islam", "fiqh", "salah"],
        )
        assert "## Related Notes" in got
        assert "- [[Prayer]] — shared: islam, fiqh" in got

    def test_sits_a_level_above_the_numbered_sections(self) -> None:
        """Apparatus, not content — and so deliberately outside the TOC."""
        got = render_related_section([_note("Prayer", ("islam",))], own_tags=["islam"])
        assert got.startswith("## Related Notes")

    def test_no_candidates_renders_nothing(self) -> None:
        assert render_related_section([]) == ""

    def test_the_limit_is_honoured(self) -> None:
        notes = [_note(f"N{i}", ("islam",)) for i in range(20)]
        got = render_related_section(notes, own_tags=["islam"], limit=3)
        assert got.count("- [[") == 3

    def test_a_candidate_with_no_shared_tag_still_renders(self) -> None:
        """The script decided it matched; it is not this function's call."""
        got = render_related_section([_note("Prayer", ("islam",))], own_tags=[])
        assert "- [[Prayer]]\n" in got

    def test_a_filename_that_cannot_be_a_link_target_is_dropped(self) -> None:
        got = render_related_section([_note("Prayer [draft]", ("islam",))],
                                     own_tags=["islam"])
        assert got == ""


class TestAppendAndStrip:
    def test_append_leaves_one_blank_line(self) -> None:
        assert append_section("Body.\n\n\n", "## X\n\n- a\n") == "Body.\n\n## X\n\n- a\n"

    def test_appending_nothing_changes_nothing(self) -> None:
        assert append_section("Body.\n", "") == "Body.\n"

    def test_strip_removes_a_previous_section(self) -> None:
        """`--resume` re-enters the stage; without this the note grows one
        Related Notes section per run."""
        body = "Body.\n\n## Related Notes\n\n- [[A]]\n"
        assert strip_related_section(body) == "Body.\n"

    def test_strip_stops_at_the_next_heading_of_the_same_level(self) -> None:
        body = "Body.\n\n## Related Notes\n\n- [[A]]\n\n## References\n\nX.\n"
        assert strip_related_section(body) == "Body.\n\n## References\n\nX.\n"

    def test_strip_leaves_a_note_that_has_no_such_section(self) -> None:
        assert strip_related_section("Body.\n") == "Body.\n"

    def test_append_then_strip_round_trips(self) -> None:
        body = "Body.\n"
        section = render_related_section([_note("Prayer", ("islam",))],
                                         own_tags=["islam"])
        assert strip_related_section(append_section(body, section)) == body

    def test_strip_survives_the_formatter_renumbering_the_heading(self) -> None:
        """A resumed run re-enters the formatter before this stage.

        `apply_structure` turns `## Related Notes` into `### 3. Related Notes`,
        so an exact-string match would miss it and append a second section.
        """
        body = "Body.\n\n### 3. Related Notes\n\n- [[A]]\n"
        assert strip_related_section(body) == "Body.\n"

    def test_strip_is_not_fooled_by_a_similar_heading(self) -> None:
        body = "Body.\n\n## Related Notes On Method\n\n- [[A]]\n"
        assert strip_related_section(body) == body
