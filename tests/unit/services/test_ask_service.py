"""
Answering a question, and the check that makes the answer trustable.

K4 built the retrieval half and measured it before anything was built on top. This is
the other half: a prompt, a stream, and a verification.

**The verification is the whole point.** A model asked to cite will produce a
plausible `app/services/handler.py:40-60` for a file that does not exist, and to
anybody who has not memorised the repository it is indistinguishable from a real one.
So every citation is checked against the evidence that was actually retrieved — the
same rule the router follows, where the model proposes and the knowledge base
disposes.

An unresolved citation is demoted to plain text rather than deleted: the sentence
around it still reads, and the missing backticks are the signal that it was not
verifiable.
"""

from __future__ import annotations

import pytest

from app.knowledge.questions import Evidence, EvidenceBundle, QuestionPlan
from app.services.ask_service import AskService


def _bundle(*titles: str) -> EvidenceBundle:
    bundle = EvidenceBundle(plan=QuestionPlan(question="q"))
    bundle.items = [
        Evidence(kind="code", title=t, body="…", why="semantic match") for t in titles
    ]
    return bundle


def _entity_bundle(name: str, path: str) -> EvidenceBundle:
    """Evidence titled by its kind, carrying the path in the body — how entities look."""
    bundle = EvidenceBundle(plan=QuestionPlan(question="q"))
    bundle.items = [
        Evidence(
            kind="entity",
            title=f"datastore: {name}",
            body=f"{{'engine': 'vector'}}\n  at {path}",
            why="question names the 'datastore' concept",
        )
    ]
    return bundle


def _check(text: str, *titles: str):
    return AskService._check_citations(text, _bundle(*titles))


class TestCitationsThatResolve:
    def test_an_exact_citation_is_kept(self) -> None:
        kept, stripped, cleaned = _check(
            "The engine is built in `app/db/session.py:12-40`.",
            "app/db/session.py:12-40",
        )

        assert kept == ["app/db/session.py:12-40"]
        assert stripped == []
        assert "`app/db/session.py:12-40`" in cleaned

    def test_a_different_line_range_still_resolves(self) -> None:
        """A citation off by a few lines still points the reader at the right file.
        Rejecting it would remove a working reference over a rounding error."""
        kept, stripped, _ = _check(
            "See `app/db/session.py:20-30`.", "app/db/session.py:12-40"
        )

        assert kept == ["app/db/session.py:20-30"]
        assert stripped == []

    def test_a_bare_path_resolves(self) -> None:
        kept, stripped, _ = _check("See `app/db/session.py`.", "app/db/session.py:12-40")

        assert kept and not stripped

    def test_a_basename_resolves(self) -> None:
        """A writer legitimately shortens a path once it has been named in full."""
        kept, stripped, _ = _check("Back in `session.py`, the pool is bounded.",
                                   "app/db/session.py:12-40")

        assert kept == ["session.py"]
        assert stripped == []

    def test_an_unbackticked_citation_is_checked_and_formatted(self) -> None:
        """
        The bug this caught. Asked to cite in backticks, a real answer wrote
        `neurosurfer/vectorstores/chroma.py:13-105` as plain prose — every citation
        in it was correct and every one went unchecked, because the pattern required
        a formatting convention the model had not followed.

        Depending on a model to format its output for a safety check is depending on
        it not to make the mistake the check exists to catch.
        """
        kept, stripped, cleaned = _check(
            "See neurosurfer/vectorstores/chroma.py:13-105 for the client.",
            "neurosurfer/vectorstores/chroma.py:13-105",
        )

        assert kept == ["neurosurfer/vectorstores/chroma.py:13-105"]
        assert stripped == []
        # Normalised, so the studio can render every verified reference as a chip
        # without depending on how the model happened to write it.
        assert "`neurosurfer/vectorstores/chroma.py:13-105`" in cleaned

    def test_a_path_carried_in_an_evidence_body_resolves(self) -> None:
        """
        The second bug this caught. A code block is titled with its path, but an
        entity is titled `datastore: Chroma` and carries the path in its body.
        Reading titles alone, a citation to a file the evidence had just named was
        stripped as an invention — on a real answer, two of three "inventions" were
        exactly this.
        """
        kept, stripped, _ = AskService._check_citations(
            "Chroma is constructed in `neurosurfer/vectorstores/chroma.py:16`.",
            _entity_bundle("Chroma", "neurosurfer/vectorstores/chroma.py:16"),
        )

        assert kept == ["neurosurfer/vectorstores/chroma.py:16"]
        assert stripped == []

    def test_prose_abbreviations_are_not_citations(self) -> None:
        """`e.g.` matches "word dot short-extension". Requiring a slash outside
        backticks is what keeps ordinary prose out of the citation list."""
        text = "The loader handles this, e.g. when a file is missing, i.e. always."

        kept, stripped, cleaned = _check(text, "app/main.py:1-5")

        assert kept == [] and stripped == []
        assert cleaned == text

    def test_each_citation_is_reported_once(self) -> None:
        kept, _, _ = _check(
            "`app/main.py:1-5` does this, and `app/main.py:1-5` also does that.",
            "app/main.py:1-5",
        )

        assert kept == ["app/main.py:1-5"]


class TestCitationsThatDoNot:
    def test_an_invented_file_is_stripped(self) -> None:
        """The failure this exists for: plausible, confident, and about a file that
        is not in the repository."""
        kept, stripped, cleaned = _check(
            "Handled in `app/services/handler.py:40-60`.", "app/db/session.py:12-40"
        )

        assert kept == []
        assert stripped == ["app/services/handler.py:40-60"]
        assert "`app/services/handler.py:40-60`" not in cleaned

    def test_the_sentence_survives_the_strip(self) -> None:
        """Deleting the reference would leave a dangling clause. Demoting it keeps the
        prose readable, and the missing backticks are the signal."""
        _, _, cleaned = _check(
            "Handled in `app/ghost.py:1-2` during startup.", "app/db/session.py:12-40"
        )

        assert "Handled in app/ghost.py:1-2 during startup." == cleaned

    def test_real_and_invented_citations_are_separated(self) -> None:
        kept, stripped, _ = _check(
            "`app/main.py:1-5` calls into `app/ghost.py:9`.", "app/main.py:1-5"
        )

        assert kept == ["app/main.py:1-5"]
        assert stripped == ["app/ghost.py:9"]

    def test_an_empty_bundle_resolves_nothing(self) -> None:
        """No evidence means no citation can be verified, so none may claim to be."""
        kept, stripped, _ = _check("See `app/main.py:1-5`.")

        assert kept == []
        assert stripped == ["app/main.py:1-5"]


class TestWhatIsNotACitation:
    def test_inline_code_that_is_not_a_path_is_untouched(self) -> None:
        text = "Call `make_engine()` and pass a `SessionFactory`."

        kept, stripped, cleaned = _check(text, "app/db/session.py:12-40")

        assert kept == [] and stripped == []
        assert cleaned == text

    def test_a_fenced_block_is_not_scanned_for_citations(self) -> None:
        """Code samples contain paths. Treating them as claims would strip working
        imports out of an example."""
        text = "```python\nfrom app.ghost import thing\n```\n"

        _, stripped, cleaned = _check(text, "app/main.py:1-5")

        assert cleaned == text
        assert stripped == []


class TestHistory:
    def test_recent_turns_are_included_newest_first(self) -> None:
        history = [
            {"role": "user", "content": "what is this"},
            {"role": "assistant", "content": "a documentation tool"},
        ]

        rendered = AskService._history(history, budget=1000)

        assert "what is this" in rendered
        assert "a documentation tool" in rendered
        assert rendered.index("what is this") < rendered.index("a documentation tool")

    def test_a_zero_budget_drops_history_entirely(self) -> None:
        """History is trimmed before evidence, always. Evidence is what makes an
        answer grounded; an earlier turn is context a reader can restate."""
        history = [{"role": "user", "content": "x" * 500}]

        assert AskService._history(history, budget=0) == ""

    def test_older_turns_fall_off_first(self) -> None:
        history = [
            {"role": "user", "content": "the oldest question " * 40},
            {"role": "user", "content": "the newest question"},
        ]

        rendered = AskService._history(history, budget=30)

        assert "the newest question" in rendered
        assert "the oldest question" not in rendered

    def test_no_history_renders_nothing(self) -> None:
        assert AskService._history([], budget=1000) == ""


class TestSources:
    def test_every_source_says_why_it_was_retrieved(self) -> None:
        """A retrieval layer that cannot explain a result cannot be debugged, and the
        reader is being asked to trust it."""
        sources = AskService._sources(_bundle("app/main.py:1-5", "app/db.py:2-8"))

        assert len(sources) == 2
        assert all(s["why"] for s in sources)
        assert all(s["kind"] == "code" for s in sources)
