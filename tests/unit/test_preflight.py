"""
What an edit would touch — the judgement, not the queries.

Two things here are easy to get wrong and expensive to get wrong quietly.

The first is **ranking**. A pre-flight that calls everything high risk is a pre-flight
an agent learns to ignore, and one that calls a load-bearing untested module "low"
is worse than none at all. The weighting was Quality's, lifted into the base, and it
is pinned here because it is the number every future caller will sort on.

The second is **what the reader is told when there is nothing to tell**. Empty
sections must not be printed as zeroes: a brief padded with "0 callers, 0 pages"
teaches its reader to skim, and the one line that mattered is in the part they
skimmed.
"""

from __future__ import annotations

import pytest

from codelith.knowledge.preflight import (
    REACH_CEILING,
    CitedBy,
    Preflight,
    Reached,
    _is_test,
    reach_weight,
)


def _reached(n: int, *, distance: int = 1, tests: int = 0) -> list[Reached]:
    out = [Reached(f"pkg/mod_{i}.py", distance, False) for i in range(n)]
    out += [Reached(f"tests/test_{i}.py", distance, True) for i in range(tests)]
    return out


class TestTheWeighting:
    def test_a_written_page_counts_for_more_than_an_import(self) -> None:
        """
        A page describing code is a claim somebody published. Breaking it costs more
        than breaking an import nobody reads, so one page outweighs four importers.
        """
        assert reach_weight(4, 0) < reach_weight(0, 1)

    def test_reach_is_capped(self) -> None:
        """
        Without a ceiling the single most-imported file in a repository crowds out
        everything else in any ranking built on this — and "200 importers" is not
        twice the warning that "100 importers" is. Both mean load-bearing.
        """
        assert reach_weight(REACH_CEILING) == reach_weight(REACH_CEILING * 10)

    def test_nothing_touched_weighs_nothing(self) -> None:
        assert reach_weight(0, 0) == 0

    def test_negatives_do_not_subtract(self) -> None:
        """Defensive: a count can only ever be a count."""
        assert reach_weight(-5, -5) == 0


class TestRisk:
    def _p(self, **kw) -> Preflight:
        return Preflight(target="x", files=["pkg/x.py"], kind="file", **kw)

    def test_an_unresolved_target_is_unknown_not_low(self) -> None:
        """
        The difference matters. "Nothing depends on this" and "I have never seen this
        file" are different facts, and only one of them is permission to edit freely.
        """
        assert Preflight(target="ghost").risk == "unknown"

    def test_a_leaf_is_low_even_with_no_test(self) -> None:
        """
        Nothing imports it and nothing describes it, so the blast radius of getting it
        wrong is the file itself. Warning here is the noise that makes the real
        warnings ignorable.
        """
        assert self._p().risk == "low"

    def test_touched_and_tested_is_low(self) -> None:
        p = self._p(reached=_reached(3, tests=1))
        p.tests = [r.path for r in p.reached if r.is_test]
        assert p.risk == "low"

    def test_untested_raises_the_level(self) -> None:
        """
        The amplifier, isolated: identical reach, and the only difference between the
        two is whether a test file is among the things that reach it.
        """
        tested = self._p(reached=_reached(7, tests=1))
        tested.tests = [r.path for r in tested.reached if r.is_test]
        untested = self._p(reached=_reached(8))

        assert len(tested.reached) == len(untested.reached) == 8
        assert tested.risk == "moderate"
        assert untested.risk == "high"

    def test_wide_reach_is_high_even_when_tested(self) -> None:
        p = self._p(reached=_reached(30, tests=2))
        p.tests = [r.path for r in p.reached if r.is_test]
        assert p.risk == "high"

    def test_a_documented_leaf_is_not_free_to_change(self) -> None:
        """
        Five written pages describe it and nothing imports it. The code is safe; the
        documentation is not, and that is the whole reason pages are in the weighting.
        """
        p = self._p(documented_in=[CitedBy(f"api/p{i}", f"P{i}") for i in range(5)])
        assert p.risk == "high"


class TestTheBriefAnAgentReads:
    def test_an_unresolved_target_says_what_to_do(self) -> None:
        brief = Preflight(target="does/not/exist.py").brief()
        assert "does/not/exist.py" in brief
        assert "re-analyse" in brief.lower()

    def test_empty_sections_are_omitted_not_printed_as_zero(self) -> None:
        brief = Preflight(target="x", files=["pkg/x.py"], kind="file").brief()
        assert "Called from" not in brief
        assert "Declares" not in brief
        assert "0 " not in brief

    def test_missing_coverage_is_stated_rather_than_omitted(self) -> None:
        """
        The one absence worth printing. Every other empty section means "nothing to
        report"; this one means "nobody will notice if you break it".
        """
        assert "No test file reaches this" in Preflight(
            target="x", files=["pkg/x.py"], kind="file"
        ).brief()

    def test_it_leads_with_the_files_and_the_risk(self) -> None:
        p = Preflight(target="x", files=["pkg/x.py"], kind="file", reached=_reached(12))
        p.dependents = ["pkg/a.py"]
        first = p.brief().splitlines()[0]
        assert first.startswith("pkg/x.py")
        assert "high risk" in first

    def test_the_headline_counts_what_is_there(self) -> None:
        p = Preflight(target="x", files=["pkg/x.py"], kind="file", reached=_reached(4, tests=1))
        p.dependents = ["pkg/a.py", "pkg/b.py"]
        p.tests = ["tests/test_0.py"]
        p.documented_in = [CitedBy("api/x", "X")]

        headline = p.headline()
        assert "2 file(s) import it directly" in headline
        assert "5 reach it within 3 hops" in headline
        assert "1 test file(s) reach it" in headline
        assert "1 written page(s) describe it" in headline

    def test_the_headline_names_the_absence_of_tests(self) -> None:
        p = Preflight(target="x", files=["pkg/x.py"], kind="file", reached=_reached(2))
        assert "nothing tests it" in p.headline()


class TestTestDetectionIsTheLanguagesJob:
    """
    `_is_test` must not grow its own regex. Every provider already answers this its
    own way — Go by the `_test.go` suffix, TypeScript by `.spec.` or a `__tests__`
    directory — and the point of the language layer is that this module never learns
    which is which.
    """

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("tests/unit/test_thing.py", True),
            ("codelith/llm/client.py", False),
            ("internal/server_test.go", True),
            ("internal/server.go", False),
            ("src/auth/session.spec.ts", True),
            ("src/auth/session.ts", False),
            ("src/__tests__/helper.tsx", True),
            # Not a language anything registers. An unrecognised file is not a test.
            ("README.md", False),
            ("docs/testing.rst", False),
        ],
    )
    def test_paths(self, path: str, expected: bool) -> None:
        assert _is_test(path) is expected


class TestWhatTheFileDependsOn:
    """
    The fourth leg of the graph.

    Callers, importers and transitive reach have always been here: they all answer
    "who would notice if this changed". What the file itself leans on was on the
    graph store and reachable only through MCP, so a pre-flight could describe
    everything around a file except what it stands on.
    """

    def test_it_appears_in_the_brief(self) -> None:
        p = Preflight(
            target="x", files=["pkg/x.py"], kind="file", imports=["pkg/a.py", "pkg/b.py"]
        )
        brief = p.brief()
        assert "Depends on:" in brief
        assert "pkg/a.py" in brief and "pkg/b.py" in brief

    def test_it_is_omitted_when_there_is_nothing_to_report(self) -> None:
        """Same rule as every other section: a brief padded with zeroes teaches its
        reader to skim, and the line that mattered is in the part they skimmed."""
        assert "Depends on" not in Preflight(
            target="x", files=["pkg/x.py"], kind="file"
        ).brief()

    def test_it_does_not_change_the_risk(self) -> None:
        """
        Deliberate. Risk is about what an edit breaks, and what a file imports is not
        that: a module importing forty others is not dangerous to change, it is
        merely well connected. Folding it in would make every leaf with a long import
        list look like a hazard.
        """
        leaf = Preflight(target="x", files=["pkg/x.py"], kind="file", tests=["t.py"])
        loaded = Preflight(
            target="x",
            files=["pkg/x.py"],
            kind="file",
            tests=["t.py"],
            imports=[f"pkg/dep{i}.py" for i in range(40)],
        )
        assert leaf.risk == loaded.risk

    def test_it_does_not_change_the_weight(self) -> None:
        p = Preflight(target="x", files=["pkg/x.py"], kind="file", imports=["a.py"] * 30)
        assert p.weight == 0
