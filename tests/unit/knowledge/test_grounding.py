"""
Groundedness: does a paragraph name things that exist?

For AI-written documentation, *"here is what we could not ground"* is what makes the
rest trustable. The failure it catches is real and has happened here: the diagram
agent invented `Workers`, `Storage` and a `Feedback Loop` for a codebase containing
none of them, and nothing downstream noticed.

Measured deterministically rather than by a second model, which would be expensive,
non-reproducible, and wrong in correlated ways — it approves exactly the
confident-sounding invention a reader would also miss.

The hard part is not detecting inventions. It is **not crying wolf**. A groundedness
surface that flags correct prose is worse than none, because it trains the reader to
ignore it — so most of these cases are about what must *not* be reported. The first
run of this scored sound pages at 0.27 by flagging `FastAPI` and `ThreadPoolExecutor`
as ungrounded.
"""

from __future__ import annotations

from app.knowledge.grounding import check_page

KNOWN = frozenset({
    "SessionFactory", "make_engine", "app/db/session.py", "session.py",
    "RevisionService", "rekey_anchor", "app/services", "fastapi", "FastAPI",
    "pydantic", "app/main.py",
})


class TestInventionsAreCaught:
    def test_a_symbol_that_does_not_exist_is_reported(self) -> None:
        page = (
            "The `WorkerPool` class dispatches every incoming job to a background "
            "thread, and each worker reports its progress as it goes along.\n"
        )

        report = check_page(page, KNOWN)

        assert report.unverified == 1
        assert "WorkerPool" in report.problems[0]["unknown"]

    def test_a_file_that_does_not_exist_is_reported(self) -> None:
        page = (
            "Configuration is assembled in `app/queue/manager.py` before the "
            "application starts, and validated against the declared schema.\n"
        )

        report = check_page(page, KNOWN)

        assert report.unverified == 1

    def test_the_problem_carries_an_excerpt_the_reader_can_locate(self) -> None:
        """A count is not actionable. The point of the surface is opening the
        specific sentence that could not be grounded."""
        page = "The `GhostService` reads from the primary store on every request made.\n"

        report = check_page(page, KNOWN)

        assert "GhostService" in report.problems[0]["excerpt"]
        assert report.problems[0]["paragraph"] == 1


class TestCorrectProseIsNotFlagged:
    """The failure mode that makes the whole surface useless."""

    def test_a_paragraph_naming_real_things_is_grounded(self) -> None:
        page = (
            "The `SessionFactory` in `app/db/session.py` builds the async engine, "
            "and every caller asks it for a session rather than constructing one.\n"
        )

        report = check_page(page, KNOWN)

        assert report.grounded == 1
        assert report.unverified == 0

    def test_a_third_party_name_is_grounded_when_the_repo_imports_it(self) -> None:
        """`FastAPI` is not declared in this repository and is not an invention.
        Flagging it scored sound pages at 0.27 and would have made the surface
        actively misleading."""
        page = (
            "Routes are registered on the `FastAPI` application at startup, so the "
            "whole HTTP surface is known before the first request arrives.\n"
        )

        report = check_page(page, KNOWN)

        assert report.unverified == 0

    def test_an_attribute_access_is_not_a_claim(self) -> None:
        """`self._cache` is a local implementation detail. The KB indexes
        declarations, not every attribute, so checking these reports a problem for
        every correct sentence that mentions one."""
        page = (
            "Inside the method, `self._node_map` holds the resolved nodes and "
            "`self._order` records the sequence they will execute in.\n"
        )

        report = check_page(page, KNOWN)

        assert report.unverified == 0

    def test_common_acronyms_are_not_identifiers(self) -> None:
        page = (
            "The service returns JSON over HTTP, and every response carries a UUID "
            "so a client can correlate it with the request it sent.\n"
        )

        report = check_page(page, KNOWN)

        assert report.unverified == 0

    def test_a_backticked_phrase_is_prose_in_code_font(self) -> None:
        page = (
            "Set the flag to `use the cached value` when the upstream has not "
            "changed since the previous run completed successfully.\n"
        )

        report = check_page(page, KNOWN)

        assert report.unverified == 0

    def test_alternative_spellings_of_a_path_resolve(self) -> None:
        """A writer says `session.py` for `app/db/session.py`. Refusing that reports
        a false problem, which is worse than missing a real one."""
        page = (
            "The engine is created once in `session.py` and shared by every request "
            "that needs a database connection during its lifetime.\n"
        )

        report = check_page(page, KNOWN)

        assert report.grounded == 1

    def test_a_method_written_with_its_class_resolves(self) -> None:
        page = (
            "After a rename the worker calls `RevisionService.rekey_anchor` so the "
            "conversation follows the heading onto its new address.\n"
        )

        report = check_page(page, KNOWN)

        assert report.grounded == 1

    def test_a_call_written_with_parentheses_resolves(self) -> None:
        page = (
            "The startup path calls `make_engine()` exactly once, and every later "
            "caller reuses the engine it returned rather than building another.\n"
        )

        report = check_page(page, KNOWN)

        assert report.grounded == 1


class TestWhatIsNotChecked:
    def test_code_blocks_are_evidence_not_claims(self) -> None:
        """A fenced block is the source being shown. Checking identifiers inside it
        would grade the code rather than the prose about it."""
        page = (
            "```python\nfrom nowhere import GhostThing\nGhostThing().run()\n```\n\n"
            "The example above shows the shape of a call, and nothing more about it.\n"
        )

        report = check_page(page, KNOWN)

        assert report.unverified == 0

    def test_headings_are_labels(self) -> None:
        page = "## The GhostComponent\n\nThis section explains how requests are routed onward.\n"

        report = check_page(page, KNOWN)

        assert report.unverified == 0

    def test_a_short_fragment_is_skipped(self) -> None:
        """A list item or a caption held to the same standard produces noise."""
        report = check_page("- `GhostThing`\n", KNOWN)

        assert report.paragraphs == 0

    def test_prose_naming_nothing_is_neither_good_nor_bad(self) -> None:
        """An introduction that names no identifier is doing its job, and must not
        be counted as grounded or as a problem."""
        page = (
            "This page explains how the system behaves when something goes wrong, "
            "and what a reader should expect to see in each case.\n"
        )

        report = check_page(page, KNOWN)

        assert report.unchecked == 1
        assert report.grounded == 0
        assert report.unverified == 0


class TestScore:
    def test_unchecked_paragraphs_do_not_move_the_score(self) -> None:
        """Including them would punish a well-written introduction and reward a page
        that names nothing at all."""
        grounded = "The `SessionFactory` in `app/db/session.py` builds the engine for us.\n"
        prose = "\nThis section explains the reasoning behind that particular choice.\n"

        with_prose = check_page(grounded + prose, KNOWN)
        without = check_page(grounded, KNOWN)

        assert with_prose.score == without.score == 1.0

    def test_a_page_with_no_claims_scores_one(self) -> None:
        """Nothing was asserted, so nothing is ungrounded. Scoring zero would read
        as a failure where there was no claim to fail."""
        report = check_page("A page of plain prose that asserts nothing checkable here.\n", KNOWN)

        assert report.score == 1.0

    def test_the_score_falls_as_inventions_rise(self) -> None:
        good = "The `SessionFactory` in `app/db/session.py` builds the async engine here.\n\n"
        bad = "The `GhostPool` in `app/ghost/pool.py` dispatches to the worker fleet.\n"

        assert check_page(good + good + bad, KNOWN).score > check_page(good + bad + bad, KNOWN).score

    def test_problems_are_capped(self) -> None:
        """A page with forty problems is broken in a way a longer list does not
        help with."""
        page = "".join(
            f"The `Ghost{i}Service` handles the {i}th kind of request that arrives.\n\n"
            for i in range(30)
        )

        report = check_page(page, KNOWN, max_problems=5)

        assert len(report.problems) == 5
        assert report.unverified == 30

    def test_the_report_serialises(self) -> None:
        report = check_page("The `GhostThing` does something with every request here.\n", KNOWN)

        data = report.to_dict()

        assert set(data) >= {"paragraphs", "grounded", "unverified", "unchecked", "score"}
        assert isinstance(data["score"], float)
