"""
Layering, derived from what the codebase does rather than from an opinion.

A rule invented in our source would be a judgement about somebody else's
architecture, and the first thing anybody does with an opinionated linter is turn it
off. So the direction of a rule comes from the evidence: if `cli → service` happens
thirty-three times and `service → cli` once, the one is the violation.

A codebase with no discernible layering produces no rules and therefore no findings.
That is the right answer for a codebase that has none — not a reason to invent some.
"""

from __future__ import annotations

from collections import Counter

import pytest

from codelith.apps.qa.drift import DriftFinding, DriftReport, _derive_rules


class TestDerivingTheRules:
    def test_an_emphatic_direction_becomes_a_rule(self) -> None:
        rules = _derive_rules(Counter({("cli", "service"): 33, ("service", "cli"): 1}))

        assert rules == {("cli", "service")}

    def test_the_dominant_direction_wins_whatever_the_order(self) -> None:
        """
        The bug this caught. An earlier version tested whichever direction the counter
        yielded first, so meeting `service → cli` (1 edge) before `cli → service` (33)
        discarded the pair — the clearest rule in the codebase was invisible because of
        dict ordering, and the run reported no violations at all.
        """
        minority_first = Counter()
        minority_first[("service", "cli")] = 1
        minority_first[("cli", "service")] = 33

        majority_first = Counter()
        majority_first[("cli", "service")] = 33
        majority_first[("service", "cli")] = 1

        assert _derive_rules(minority_first) == _derive_rules(majority_first)
        assert _derive_rules(minority_first) == {("cli", "service")}

    def test_two_conventions_produce_no_rule(self) -> None:
        """15 one way and 7 the other is a codebase with two conventions. Calling one
        of them wrong is picking a side nobody asked us to pick."""
        assert _derive_rules(Counter({("service", "utility"): 15, ("utility", "service"): 7})) == set()

    def test_too_little_evidence_produces_no_rule(self) -> None:
        """Two imports one way and none the other is not a convention. It is two
        imports."""
        assert _derive_rules(Counter({("a", "b"): 2})) == set()

    def test_a_one_way_pair_with_enough_evidence_is_a_rule(self) -> None:
        assert _derive_rules(Counter({("cli", "config"): 8})) == {("cli", "config")}

    def test_nothing_at_all_produces_nothing(self) -> None:
        assert _derive_rules(Counter()) == set()


class TestTheReport:
    def test_no_layering_is_stated_not_hidden(self) -> None:
        """A codebase where no direction dominates gets told that, rather than a
        clean bill of health it did not earn."""
        assert "No consistent layering" in DriftReport(no_layering=True).summary

    def test_no_violations_says_so(self) -> None:
        assert "follows the direction" in DriftReport(rules=[("a", "b", 9)]).summary

    def test_new_violations_are_counted_separately(self) -> None:
        """"This is new since last week" is a different sentence from "this exists",
        and it is the one somebody acts on."""
        report = DriftReport(
            findings=[
                DriftFinding("service", "cli", count=1, is_new=True),
                DriftFinding("api", "data_access", count=3),
            ]
        )

        assert "2 layering violation" in report.summary
        assert "1 new since the last analysis" in report.summary

    def test_a_finding_says_which_way_the_import_goes(self) -> None:
        finding = DriftFinding("service", "cli", count=1)

        assert "from service into cli" in finding.summary

    def test_singular_and_plural_are_both_right(self) -> None:
        assert "1 import from" in DriftFinding("a", "b", count=1).summary
        assert "3 imports from" in DriftFinding("a", "b", count=3).summary
