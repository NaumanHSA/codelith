"""
Narratives, in the order a person reads them.

Almost nothing in this service is coercion, because narratives are two text columns
rather than model-written JSON. What it does decide is ordering and labelling, and
both are easy to get subtly wrong: `list_by_kb` sorts by topic name, which puts
"architecture" first and "overview" tenth, and a naive title makes "cli_usage" into
"Cli usage".

The other thing under test is what happens to a knowledge base written before the
writer recorded its sources. Those narratives have no provenance and must say so,
because a fabricated citation is worse than an absent one.
"""

from __future__ import annotations

import pytest

from codelith.services.narrative_service import _brief, _provenance, _title, assemble


class Row:
    """The two columns and the JSON blob, without a database behind them."""

    def __init__(self, topic: str, content_md: str = "some prose", refs: object = None):
        self.topic = topic
        self.content_md = content_md
        self.source_refs_json = refs


def build(rows: list[Row], commit_sha: str = "abc1234"):
    """The real assembly. `list_for_project` is this plus two repository calls."""
    return assemble(rows, commit_sha)


class TestReadingOrder:
    def test_overview_comes_first_not_architecture(self):
        """
        The bug this exists to prevent. The repository sorts alphabetically, so the
        page would open on "architecture" and bury "what is this project" at ten.
        """
        out = build([Row("testing"), Row("architecture"), Row("overview"), Row("auth")])
        assert [n.topic for n in out.narratives][:2] == ["overview", "architecture"]

    def test_a_topic_the_enum_has_never_heard_of_sorts_last(self):
        """The writer coerces onto the enum. The column does not, and an old row
        or a hand-inserted one must not break the ordering."""
        out = build([Row("wildcard"), Row("overview")])
        assert [n.topic for n in out.narratives] == ["overview", "wildcard"]

    def test_ordering_is_stable_for_two_unknown_topics(self):
        out = build([Row("zebra"), Row("aardvark")])
        assert [n.topic for n in out.narratives] == ["aardvark", "zebra"]


class TestWhatAReaderSees:
    @pytest.mark.parametrize(
        ("topic", "expected"),
        [
            ("request_lifecycle", "Request lifecycle"),
            ("cli_usage", "CLI usage"),
            ("auth", "Auth"),
            ("build_and_release", "Build and release"),
            ("data_model", "Data model"),
        ],
    )
    def test_titles(self, topic, expected):
        assert _title(topic) == expected

    def test_a_title_for_a_topic_nobody_planned(self):
        assert _title("some_new_thing") == "Some new thing"

    def test_the_brief_is_one_sentence(self):
        """The guidance is instruction to a model - paragraph counts and tone. Only
        the first sentence says what the topic is about."""
        brief = _brief("overview")
        assert brief.startswith("Explain what this project is")
        assert brief.count(".") == 1

    def test_no_brief_for_an_unknown_topic(self):
        assert _brief("wildcard") == ""

    def test_words_are_counted(self):
        out = build([Row("overview", "one two three four five")])
        assert out.narratives[0].words == 5

    def test_an_empty_narrative_is_not_offered(self):
        """A row with no prose behind it would open an empty reader."""
        out = build([Row("overview", "   "), Row("testing", "real")])
        assert [n.topic for n in out.narratives] == ["testing"]

    def test_nothing_written_yet(self):
        out = build([])
        assert out.available is False and out.narratives == []


class TestProvenance:
    def test_what_the_writer_now_records(self):
        refs = {
            "generated_by": "narrative_writer_agent",
            "modules": ["src.session", "src.camera"],
            "facts": ["route (12)", "env_var (24)"],
        }
        p = _provenance(refs)
        assert p.modules == ["src.session", "src.camera"]
        assert p.facts == ["route (12)", "env_var (24)"]

    def test_a_knowledge_base_written_before_the_writer_recorded_anything(self):
        """
        Every narrative on this machine today. It must come back empty rather than
        invented: guessing which modules fed a narrative after the fact would be a
        citation nobody could check.
        """
        p = _provenance({"generated_by": "narrative_writer_agent"})
        assert p.generated_by == "narrative_writer_agent"
        assert p.modules == [] and p.facts == []

    @pytest.mark.parametrize("junk", [None, "a string", 42, []])
    def test_junk_where_provenance_should_be(self, junk):
        p = _provenance(junk)
        assert p.modules == [] and p.facts == [] and p.generated_by == ""

    def test_blank_entries_are_dropped(self):
        p = _provenance({"modules": ["real", "", "   "]})
        assert p.modules == ["real"]

    def test_a_very_long_module_list_is_bounded(self):
        p = _provenance({"modules": [f"m{i}" for i in range(200)]})
        assert len(p.modules) == 40
